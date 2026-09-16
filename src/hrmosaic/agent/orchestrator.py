"""The agent loop (spec §9.1): route → act → synthesize, with budgets, guardrails and one record.

```
POST /chat  (or /chat/confirm)
 ├─ open/resume session → sessions row   ┐ written synchronously at turn start
 ├─ open turn           → turns row      ┘
 ├─ ensure MCP session  → mcp_discovery span, emitted EVERY turn (§8.2 step 3)
 ├─ 0. PRE-CHECKS   deterministic, zero LLM
 ├─ 1. ROUTE        one constrained-JSON llm_call → plan span
 ├─ 2. ACT LOOP     ≤ AGENT_MAX_STEPS · ≤ AGENT_MAX_TOOL_CALLS · ≤ AGENT_WALL_CLOCK_S
 ├─ 3. G1 evidence gate over the accumulated chunk set
 ├─ 4. SYNTHESIZE   one constrained-JSON llm_call → AnswerSchema
 ├─ 5. G2 citation resolvability · G3 fact-vs-recommendation
 ├─ 6. close the turn: rollups, outcome, stop_reason
 └─ 7. ONE batched flush (`core/trace.py` owns it)
```

**The two entry points are named in §9.1 because `web/api.py` is written by a different phase.**
`run_turn(req)` is a whole turn; `resume_turn(session_id, turn_id, token)` picks one up after a
human clicked Confirm. `POST /chat` is a thin wrapper: validate, authorise the privileged options,
call, return.

**`resume_turn` rehydrates from the store.** The act loop's state was in-process and is gone once
`/chat` returned, so the messages come back from that turn's `llm_messages` rows, the chunk set from
its `retrieval` spans, prior tool results from its `tool_call` spans and the step counter from the
count of `act`-purpose `llm_call` spans. It never re-retrieves —
`tests/integration/test_confirm_resume_lifecycle.py` (P8) asserts the resumed synthesize prompt
carries the *pre-confirmation* chunk ids, so a silent re-retrieval fails.

**Contract with `web/` on the confirmation spans (§8.6, §11.2).** The **pending** span is emitted
here, by the turn that was gated. The **confirmed** span is also emitted here, immediately before
the gated call is re-issued, because §13.4's action-safety clause 1 requires it to be *earlier by
seq* than the write it authorised and only this function controls that ordering. The **declined**
span is `web/`'s: `resume_turn` is not called on a decline.

**No hidden chain-of-thought (§9.7).** `plan` spans carry `intent`, `workflow`, `selected_tools[]`,
`step_summaries[]` and a one-line `rationale_summary`, capped at 200 characters. Nothing anywhere
is named `reasoning`, `thoughts` or `chain_of_thought`, and `tests/contract/test_no_chain_of_thought.py`
greps the payload union for exactly that.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hrmosaic.agent import approvers as approver_resolution
from hrmosaic.agent import arithmetic as arithmetic_consistency
from hrmosaic.agent import breadth, prompts, session
from hrmosaic.agent import capability as capability_check
from hrmosaic.agent import compliance as compliance_restatement
from hrmosaic.agent import dates as date_consistency
from hrmosaic.agent import entailment as step_entailment
from hrmosaic.agent import outcome as outcome_consistency
from hrmosaic.agent import snapshot as snapshot_consistency
from hrmosaic.agent.answer_stream import AnswerAssembler, StreamedBlock
from hrmosaic.agent.client import DiscoveredCatalog, McpClient, McpUnavailable, ToolResult
from hrmosaic.agent.guardrails import g1, g2, g3, g4, g5, g6
from hrmosaic.agent.guardrails import span_name as guardrail_span_name
from hrmosaic.agent.router import (
    EMPLOYEE_ID,
    RouteDecision,
    allowed_tools,
    clamp_rationale,
    fallback_decision,
    is_unsafe,
    normalise,
    offered,
)
from hrmosaic.agent.workflows import EVIDENCE_TOOLS, LoopState, WorkflowSpec
from hrmosaic.agent.workflows import get as get_workflow
from hrmosaic.core import corpusread, trace
from hrmosaic.core.db import Store, get_store, now_micros
from hrmosaic.core.ids import new_session_id
from hrmosaic.core.llm import build_agent_model
from hrmosaic.core.llm.base import ChatModel, Message, MissingCredentialError, ProviderError, ToolCall
from hrmosaic.core.llm.limiter import DailyCapExceeded
from hrmosaic.core.models import (
    NOTICE,
    AnswerBlock,
    AnswerSchema,
    Citation,
    ConfirmationPayload,
    ErrorPayload,
    PlanPayload,
    RetrievalPayload,
    TraceEntry,
    TurnOutcome,
)
from hrmosaic.core.trace import AnswerDeltaEvent, SessionSpec, TurnBuffer
from hrmosaic.settings import Settings
from hrmosaic.settings import settings as default_settings

#: §8.6 step 3 — a proposal is good for ten minutes, the same lifetime the minted token carries.
CONFIRMATION_TTL_S = 600

#: §9.1 step 0. Deliberately short and deliberately unambiguous: G1 is the real gate, and this is
#: only the cheap pre-filter that keeps an obviously non-HR question from burning a model call.
#: Every phrase is one a Mosaic Robotics HR corpus can never answer.
OUT_OF_CORPUS_PHRASES: tuple[str, ...] = (
    "weather",
    "stock price",
    "share price",
    "football score",
    "capital of",
    "who won the",
    "write me a poem",
    "recipe for",
)

#: The gated write tools of §8.4. A `CONFIRMATION_REQUIRED` from either parks the turn.
WRITE_TOOLS = ("create_mock_hr_ticket", "draft_hr_email")

#: Which queue a deterministically-proposed write goes to, by the scenario the turn scored
#: (W8, C09). Only the scenarios whose write the product actually offers: a card the orchestrator
#: mints must describe a request the turn itself resolved, and a scenario with no queue produces
#: no card rather than a guess.
DETERMINISTIC_QUEUES: dict[str, str] = {
    "pto_request": "hr-timeoff",
    "international_remote": "hr-mobility",
    "domestic_remote": "hr-general",
    "benefits_change": "hr-benefits",
    "equipment_request": "it-equipment",
}

#: What that card calls the request, by the same key.
DETERMINISTIC_SUBJECTS: dict[str, str] = {
    "pto_request": "PTO request",
    "international_remote": "Request to work from another country",
    "domestic_remote": "Request to work from another location",
    "benefits_change": "Benefits election change",
    "equipment_request": "Equipment request",
}

#: An ISO date, for the span a deterministic card names.
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

#: The deterministic compliance engine (§8.4 tool 4). Its per-requirement evidence names
#: committed chunks, which `_engine_evidence` scores so G1 can weigh them (§7.4, P13 R7).
COMPLIANCE_TOOL = "check_policy_compliance"


def _cited_evidence_ids(body: Mapping[str, Any]) -> list[str]:
    """The chunk ids a `check_policy_compliance` body names in its per-requirement `evidence`.

    One reader for the two callers that need them: `_engine_evidence_rows`, which resolves the ones
    the turn does not already hold, and `_rehydrate_scores`, which scores a parked turn's ids off
    the event loop before `_rehydrate` walks the spans again. The engine's top-level `citations[]`
    is deliberately not read — see `_engine_evidence`.
    """
    ids: list[str] = []
    for requirement in body.get("requirements") or []:
        if not isinstance(requirement, dict):
            continue
        evidence = requirement.get("evidence") or {}
        chunk_id = evidence.get("chunk_id") if isinstance(evidence, dict) else None
        if chunk_id and str(chunk_id) not in ids:
            ids.append(str(chunk_id))
    return ids


CAVEAT_TEXT = (
    "The HR tool server is unreachable, so I could not read the policy corpus or your employee "
    "record for this answer. Nothing below is a statement of Mosaic Robotics policy."
)

SYNTHESIS_CAVEAT = (
    "I gathered the policy evidence for this question but could not compose an answer from it. "
    "Nothing below is a statement of Mosaic Robotics policy."
)

#: §9.4's budget stops. Each produces a **graceful partial answer** plus an `error` span carrying
#: the reason — never a hang and never a 5xx.
BUDGET_STOPS = ("max_steps", "max_tool_calls", "timeout")

#: The placeholder result a repair round trip hands the other calls of the same act step. They have
#: not run — the loop is still inside the failed one — but their `tool_use` blocks are already in the
#: assistant message the request replays, and an unanswered `tool_use` is a 400 on the pinned model.
NOT_RUN_YET = json.dumps({"status": "not_run", "hint": "an earlier call in this step was rejected"})

#: The single question a clarification asks, keyed on **the first unfilled slot** (W8, C18). One
#: question, never the slot list: `WorkflowSpec.required_slots` documents the completion predicate
#: for the dashboard, and reading it aloud was the defect jargon-and-exposure-4 recorded.
#:
#: Keyed on the workflow, it asked the wrong question. The admin turn of 2026-09-15 was asked
#: *"which dates are you thinking of?"* by a message that had given the dates in full: what was
#: missing was an employee record, because `admin` has none. A question is only worth asking about
#: the slot that is actually empty.
CLARIFY_QUESTIONS: dict[str, str] = {
    "identity": "Happy to help — whose record should I look this up against?",
    "start_date": "Happy to check — which dates are you thinking of?",
    "days": "Happy to check — how many days would that be?",
    "destination_country": "Happy to check — where would you be working from?",
    "duration_days": "Happy to check — how long would you be there?",
    "amount_usd": "Happy to check — how much is the claim for?",
}

#: Which slot a workflow asks about first when it holds none of them. The order is the order a
#: person would be asked in, not the order `required_slots` documents.
CLARIFY_SLOT_ORDER: dict[str, tuple[str, ...]] = {
    "pto_request": ("identity", "start_date", "days"),
    "remote_work_eligibility": ("identity", "destination_country", "duration_days"),
}

#: When the router named no workflow. Still one question, still in the first person.
CLARIFY_FALLBACK = "Happy to help — could you tell me a little more about what you are after?"

#: The two quick replies a clarification offers, per workflow (UX W2, §3.5 of the UX plan,
#: chat-production-ux-7). A clarifying question with no quick way to answer it is a dead end: the
#: reader has to compose the reply the question already implies. Each chip is a **reply the user
#: would send**, so it prefills the composer and sends nothing — the reader still edits and presses
#: Enter, which is the difference between a shortcut and an answer put in their mouth.
CLARIFY_CHIPS: dict[str, tuple[str, ...]] = {
    "identity": (
        "It is for E1042",
        "Look it up for me",
    ),
    "start_date": (
        "Three days, 15–17 September 2026",
        "One day, this Friday",
    ),
    "days": (
        "Three days",
        "Just the one day",
    ),
    "destination_country": (
        "Berlin, in Germany",
        "Within the UK",
    ),
    "duration_days": (
        "About six weeks",
        "Two weeks",
    ),
    "amount_usd": (
        "About USD 3,000",
        "Under USD 100",
    ),
}

#: The fallback pair, for a clarification the router could not attach to a workflow.
CLARIFY_FALLBACK_CHIPS: tuple[str, ...] = (
    "It is about my time off",
    "It is about working somewhere else",
)


def clarify_chips(slot: str | None) -> tuple[str, ...]:
    """The quick replies for a clarification, by the slot it asks about. Shared with the replay path."""
    return CLARIFY_CHIPS.get(slot or "", CLARIFY_FALLBACK_CHIPS)


def clarify_slot_of(question: str) -> str | None:
    """Which slot a stored clarifying question was asking about (W8, C18).

    `turns` stores the question the reader was shown but not the slot it came from, and the replay
    path has to offer the same two quick replies the live turn did. The questions are a closed set,
    so the reverse lookup is exact — and it is the *stored text* that decides, not the workflow,
    which is the whole point of keying on the slot.
    """
    return next((slot for slot, text in CLARIFY_QUESTIONS.items() if text == question.strip()), None)


def unfilled_slot(workflow: str | None, *, known: Collection[str], has_record: bool) -> str | None:
    """The first slot this turn still needs, or `None` when the session already holds them all.

    `known` is what `agent/session.py` carried forward from the last three turns, so a follow-up is
    never asked for a detail the session settled — the other half of C12's defect, and the reason
    C18 keys on the slot rather than on the workflow.
    """
    for slot in CLARIFY_SLOT_ORDER.get(workflow or "", ()):
        if slot == "identity":
            if not has_record:
                return slot
            continue
        if slot not in known:
            return slot
    return None


#: What the product will not do, said first and in its own voice (W8, C20, C17). It names the act
#: and then the rule, in `corpus/manager-approval-matrix.md`'s own words, so a reader is told what
#: happens instead rather than only what does not.
UNSAFE_REFUSAL = (
    "I will not approve a request for you, record an approval somebody else has to give, or route "
    "a request around its approval chain. Nobody approves their own request, and nobody approves a "
    "request from a person who approves theirs; where that would happen, MosaicOne routes the "
    "request one level higher automatically."
)

#: …and what there is to do instead.
UNSAFE_NEXT_STEPS: tuple[str, ...] = (
    "Send the request through MosaicOne and let it route to the right approver.",
    f"If the routing looks wrong, contact People Operations at {g5.PEOPLE_OPS}.",
)

#: What a cancelled proposal tells the reader, before the answer it already earned (W8, C11, C17).
CANCELLED_NOTICE = "Cancelled — nothing was created. Ask again whenever you would like me to open it."

#: The write a confirmed resume re-issued came back `isError`: the token validated, the write did
#: not. §9.4's graceful partial, not a silent success.
WRITE_FAILED_NOTE = (
    "The confirmation was accepted but the action itself did not complete, so nothing was created. "
    "Here is what I established; try again or contact the owning team."
)

#: The one deterministic reminder the act loop is allowed to inject (§9.1 step 2, P8's live check).
#: It is a loop mechanism: §9.3 supplies the *gap* — its completion predicate — and says nothing
#: about telling the model. The workflow spec already knows what the turn still needs; before this,
#: nothing told the **model**, so a run that reached a compliance verdict without ever searching
#: stopped one step short of the evidence G1 requires and the turn refused. Sent at most once per
#: turn, and it is an operational instruction — never reasoning, and never persisted anywhere but
#: the verbatim `llm_messages` rows.
#:
#: **It names the debt, never a tool.** `{debts}` is filled from the workflow spec's slot
#: descriptions ("no compliance verdict is in state yet"), because a reminder that listed the
#: remaining calls would hand the model the rest of its tool sequence — and §13.4's ToolSelection
#: on a nudged turn would then be scoring the hint. The turn records that it was nudged
#: (`PlanPayload.nudges`) so P10 can report a `nudge_rate` beside those scores.
WORKFLOW_INCOMPLETE = (
    "Not yet — this turn is not finished. The {workflow} workflow is incomplete: {debts}. "
    "Only a passage retrieved by SEARCHING the policy corpus can be cited: a section fetched by "
    "its exact heading is not scored, grounds nothing, and an answer resting on one is refused. "
    "Close each gap above with the tools you were offered, then conclude. If the user also asked "
    "for something to be created, propose it once the policy supports it; a human confirms it "
    "before anything is created."
)

#: The third reminder (W8, C10): the turn is about somebody's own record and has not read it. The
#: live failures were a question about the reader's own office declined outright, and an answer
#: that described E1042 as "a fully remote employee" when the profile tool — never called — says
#: hybrid. Same rule as the others: it names the debt, never the tool that settles it.
DATA_OUTSTANDING = (
    "Not yet — this turn is about one person's own HR record and nothing in state carries it. "
    "Read the record this question is about before you answer it."
)

#: The second reminder, for the other way a turn can quietly drop what the user asked for: the
#: model wrote an answer while the write it was asked to propose is still unmade. `_action_outstanding`
#: already guarded the completion-predicate exit; live, the model left through the other door.
#: Same rule as above — the debt, not the tool that settles it.
ACTION_OUTSTANDING = (
    "The user asked for something to be created and this turn has not proposed it yet — no "
    "proposed action is in state. Propose it now, with the exact details it needs. Proposing is "
    "safe: the action is gated, and nothing is created until a human confirms it."
)

#: The third reminder (P13 R3), for the failure the other two cannot see: a turn that searched,
#: got a plausible passage and stopped, while the question had three parts written in three
#: different documents. The judged baseline lost `remote-002` and `expenses-002` that way — two
#: cited documents where the end state required three — and neither existing reminder fires there,
#: because the workflow's debts were settled and no action was outstanding.
#:
#: Same rule as the other two: it names the **debt** — the corpus is federated and one query
#: reaches one or two documents — and never a tool, never a document count, and never a `k`. It is
#: sent at most once per turn and only on a step where neither other reminder fired, so a nudged
#: turn still costs at most one extra act step.
#:
#: **Two forms, one debt.** The reminder fires at *at most* one search, so it also reaches a turn
#: that has searched none — and telling that turn, in a prompt, that it "searched the corpus once"
#: would be a false statement about the model's own history, in the one message whose whole purpose
#: is to correct that picture. Only the opening clause moves with the count; the debt itself is one
#: string shared by both forms, so the two cannot drift (P13 review, finding 2).
_BREADTH_DEBT = (
    "This corpus is federated on purpose: duration thresholds, approved-country lists, approval "
    "authority and device/security rules are each written in a different document, and a single "
    "query reaches only one or two of them. Re-read the question, and for every distinct thing it "
    "asks that your evidence does not yet cover, search again. Then conclude."
)

SEARCH_BREADTH = f"Not yet — you have searched the corpus once. {_BREADTH_DEBT}"

SEARCH_BREADTH_UNSEARCHED = f"Not yet — you have not searched the corpus yet. {_BREADTH_DEBT}"

#: The one message §9.2's G1 recovery step sends (P13 R4). The reopen used to append nothing, so
#: the extra step was spent blind: the model saw the same conversation that had just produced an
#: ungrounded answer and reproduced it. It says why the answer was refused and what would ground
#: it — the debt, not the tool — and the turn records it in `nudges` as `g1_recovery`.
G1_RECOVERY = (
    "Your answer was refused: nothing you retrieved can ground it. A compliance verdict is a "
    "computation, not a policy passage — only a passage returned by SEARCHING the corpus can be "
    "cited. Search now for the policy text behind each requirement you relied on, then conclude."
)

BUDGET_NOTE = {
    "max_steps": "I reached my step limit for this turn; here is what I established before stopping.",
    "max_tool_calls": "I reached my tool-call limit for this turn; here is what I established before stopping.",
    "timeout": "I reached my time limit for this turn; here is what I established before stopping.",
}


# --------------------------------------------------------------------------------------
# The repair schema (§9.1 step 2, §9.8 `max_tokens` 512)
# --------------------------------------------------------------------------------------


class ToolCallRepair(BaseModel):
    """The **one** repair round trip after a tool rejected its arguments (§9.1).

    A schema violation comes back as `isError` with the validator's message as text (§8.3, and
    `mcp/README.md`'s measured note). Rather than replay the same call or give the model the whole
    tool array again, the loop asks one constrained-JSON question — *what should these arguments
    have been?* — which is why `repair` has its own 512-token budget in §9.8's table. If the
    repaired call fails too, the turn degrades: there is never a second repair.

    Strict at every level, like every other constrained-JSON model: no defaults (§7.3).
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any]
    rationale_summary: str


# --------------------------------------------------------------------------------------
# The `/chat` request and response shapes (§11.1)
# --------------------------------------------------------------------------------------


class ChatOptions(BaseModel):
    """§11.1's `options`. Everything except `k` is privileged; `web/` enforces that, not this."""

    model_config = ConfigDict(extra="forbid")

    k: int | None = Field(default=None, ge=1, le=10)
    retrieval_strategy: Literal["hybrid_rrf", "dense_only"] | None = None
    tools_disabled: list[str] = Field(default_factory=list)
    eval_run_id: str | None = None
    variant: str | None = None


class ChatRequest(BaseModel):
    """§11.1's request body. `session_id` / `turn_id` are client-suppliable so the SSE rail can
    subscribe before the POST that fills it."""

    model_config = ConfigDict(extra="forbid")

    message: str
    session_id: str | None = None
    turn_id: str | None = None
    employee_id: str = "E1042"
    client_label: Literal["web", "api", "eval", "demo"] = "web"
    options: ChatOptions = Field(default_factory=ChatOptions)
    #: Recorded on the session for the audit trail; `web/` resolves both (§11).
    auth_mode: Literal["cookie", "bearer", "open"] = "open"
    actor_role: Literal["employee", "admin"] = "employee"
    actor_source: Literal["explicit", "default"] = "default"
    user_agent_hash: str | None = None


class ConfirmationCard(BaseModel):
    """What the UI renders when a write is gated — and **never** a token (§11.1)."""

    model_config = ConfigDict(extra="forbid")

    action: str
    human_summary: str
    arguments_preview: dict[str, Any]
    expires_at: int


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    retrievals: int = 0


class Timings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_ms: int = 0
    llm_ms: int = 0
    retrieval_ms: int = 0
    tool_ms: int = 0
    store_ms: int = 0


class ChatResponse(BaseModel):
    """§11.1's response — the four rubric-named fields are all top level."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    turn_id: str
    trace_id: str
    outcome: TurnOutcome
    answer: str
    answer_blocks: list[AnswerBlock]
    #: The "what to do next" list `AnswerSchema` already built. It is inside `answer` (§7.3's
    #: `render_answer` joins it on), but the page renders the blocks, not the joined string — so
    #: until UX W2 the refusal's redirect, which is the most useful half of a refusal, was
    #: generated on every refused turn and silently dropped by the web layer (jargon-and-exposure-3).
    next_steps: list[str] = Field(default_factory=list)
    #: The two quick replies a clarifying turn offers (UX W2, chat-production-ux-7). Empty on every
    #: other outcome. They are chat chrome, not model output: the orchestrator writes them from
    #: `CLARIFY_CHIPS`, so a clarification always has a way to answer it even when the model's own
    #: question is the fallback one.
    quick_replies: list[str] = Field(default_factory=list)
    citations: list[Citation]
    trace: list[TraceEntry]
    confirmation: ConfirmationCard | None = None
    usage: Usage = Field(default_factory=Usage)
    timings: Timings = Field(default_factory=Timings)
    cold_start: bool = False
    stream_url: str = ""
    dashboard_url: str = ""


# --------------------------------------------------------------------------------------
# Evidence and the trace projection
# --------------------------------------------------------------------------------------


@dataclass
class EvidenceChunk:
    """One retrieved chunk as the turn carries it: the citation fields plus the one score (§7.1)."""

    chunk_id: str
    doc_id: str
    doc_title: str
    heading_path: str
    section: str
    snippet: str
    dense_score: float
    rrf_score: float | None = None
    quarantined: bool = False

    @property
    def text(self) -> str:
        """The **real** chunk text, for G4 — never the snippet, which is a display subset."""
        row = corpusread.get_chunk(self.chunk_id)
        return row.text if row is not None else self.snippet


@dataclass(frozen=True)
class _RawText:
    """Text that is not a corpus chunk — the user's own message — in G4's `Scannable` shape."""

    chunk_id: str
    text: str


@dataclass
class _ToolEnvelope:
    """One tool result as the synthesis prompt renders it (§7.2's `<tool_result>` envelope)."""

    name: str
    result_json: str


def _preview(value: Any, limit: int = 160) -> str:
    body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return body if len(body) <= limit else body[: limit - 1] + "…"


def _summary(kind: str, name: str, payload: dict[str, Any]) -> str:
    """One line per span kind, in the shapes §11.1's `trace[]` example shows."""
    if kind == "mcp_discovery":
        return f"{payload.get('tool_count', 0)} tools discovered over {payload.get('transport', '?')}"
    if kind == "plan":
        return (
            f"intent={payload.get('intent')} workflow={payload.get('workflow') or 'none'} "
            f"catalog_reopened={str(bool(payload.get('catalog_reopened'))).lower()}"
        )
    if kind == "llm_call":
        # Thousands separators, because the tile above this row on the session page has them and
        # `13512→648 tok` beside `45,497 → 2,445` is two conventions on one screen (UX W4,
        # `numbers-precision-overflow-8`). This string is also the `/chat` `trace[]` `summary`.
        return (
            f"purpose={payload.get('purpose')} · "
            f"{payload.get('prompt_tokens', 0):,}→{payload.get('completion_tokens', 0):,} tok"
        )
    if kind == "retrieval":
        chunks = payload.get("chunks") or []
        docs = sorted({chunk.get("doc_id", "") for chunk in chunks})
        top = payload.get("max_dense_score")
        # Two decimal places: a cosine at four was `0.7612` beside `0.774` on one screen, two
        # precisions for one quantity (UX W4, `numbers-precision-overflow-4`). The unrounded score
        # is on the span payload, which is the record.
        shown = f"{float(top):.2f}" if top is not None else "n/a"
        # "passages" and "best match", the words the Retrieval table's own columns use: the same
        # screen carried `5 chunks` / `PASSAGES` and `top dense` / `BEST MATCH`, two names each for
        # one quantity (UX W6, npo2-06 / **P10**).
        counted = "passage" if len(chunks) == 1 else "passages"
        return f"{len(chunks)} {counted} · best match {shown} · {', '.join(docs)}"
    if kind == "guardrail":
        return f"verdict={payload.get('verdict')} · {payload.get('reason', '')}"
    if kind == "confirmation":
        return f"{payload.get('action')} · {payload.get('user_response')}"
    if kind == "error":
        return f"{payload.get('error_kind')}: {payload.get('message', '')}"
    if kind == "tool_call":
        # The designed confirmation pause is not a failure: the waterfall's summary cell said
        # "create_mock_hr_ticket · error" on the very row whose chip said "paused for
        # confirmation", and /dashboard/tools called the same call "paused" (UX W7, npo3-05).
        # One mapper for the chip, the summary and the `/chat` trace.
        if payload.get("error_code") == "CONFIRMATION_REQUIRED":
            return f"{payload.get('tool_name')} · paused for confirmation"
        return f"{payload.get('tool_name')} · {'error' if payload.get('is_error') else 'ok'}"
    return name


def project(turn_id: str, *, session_id: str, store: Store | None = None) -> list[TraceEntry]:
    """Every span of the turn, in `seq` order, with no kind filtered out (§11.1).

    Read back **from the store, after the flush**, rather than collected in memory. Three things
    fall out of that and none of them is free any other way: the projection and the dashboard are
    provably the same rows rather than two logging paths (USER.4); a resumed turn's response carries
    the whole turn, not just the spans written after the reopen, so §11.1's "equality holds again on
    the resumed response" is true by construction; and the previews show the **redacted, capped**
    payload the record actually holds (§10.4, §10.5) rather than the object before either ran.
    """
    rows = (
        (store or get_store())
        .execute(
            "SELECT id, seq, kind, name, duration_ms, status, payload_json FROM spans WHERE turn_id = ? ORDER BY seq",
            (turn_id,),
        )
        .dicts()
    )
    entries: list[TraceEntry] = []
    for row in rows:
        # `.get`, not `[...]`: §10.5 replaces an oversize payload with a stub, and a projection that
        # raised on one would take the whole response down with it.
        payload = json.loads(row["payload_json"])
        kind = row["kind"]
        entries.append(
            TraceEntry(
                seq=row["seq"],
                kind=kind,
                name=row["name"],
                duration_ms=row["duration_ms"],
                status=row["status"],
                summary=_summary(kind, row["name"], payload),
                args_preview=_preview(payload.get("arguments") or {}) if kind == "tool_call" else None,
                result_preview=(_preview(payload.get("result_json") or "") if kind == "tool_call" else None),
                detail_url=f"/dashboard/sessions/{session_id}?span={row['id']}",
            )
        )
    return entries


#: The section `render_answer()` closes with when the answer carries steps, and the marker
#: `parse_next_steps()` reads them back by.
NEXT_STEPS_LEAD = "Next steps:\n"


def render_answer(blocks: Sequence[AnswerBlock], next_steps: Sequence[str]) -> str:
    """The deterministic join of §7.3: a recommendation is labelled, an escalation is flagged."""
    parts: list[str] = []
    for block in blocks:
        if block.type == "recommendation":
            parts.append(f"Recommendation — not company policy: {block.text}")
        elif block.type == "escalation":
            parts.append(f"Escalation: {block.text}")
        else:
            # `policy_fact`, `performed`, `record` and `notice` are all statements of what is so —
            # of company policy, of what this turn's tools did, of the reader's own HR data, of
            # what the product itself is doing — and none of them wears a label (UX W6; UX W7 for
            # `record`; W8 C17 for `notice`, which was wearing *"not company policy"* over the
            # product's own voice).
            parts.append(block.text)
    if next_steps:
        parts.append(NEXT_STEPS_LEAD + "\n".join(f"- {step}" for step in next_steps))
    return "\n\n".join(parts)


def parse_next_steps(answer: str) -> list[str]:
    """The inverse of the join above, for the one reader that has only the stored string.

    `turns` stores `final_answer`, `answer_blocks_json` and `citations_json` — the blocks and their
    sources, but not the steps beside them. So a replayed transcript used to lose `next_steps`
    entirely, and a refusal came back from a reload without the redirect that is the most useful
    half of it (UX W2 report §7.3). The steps are not gone: `render_answer()` put them in the very
    string the row holds, as the last section, one `- ` bullet per step. This reads them back, and
    `tests/unit/test_answer_rendering.py` pins the pair as a round trip so the format cannot drift
    on one side only.
    """
    head, separator, tail = answer.rpartition(NEXT_STEPS_LEAD)
    if not separator or (head and not head.endswith("\n\n")):
        return []
    return [line[2:] for line in tail.split("\n") if line.startswith("- ")]


# --------------------------------------------------------------------------------------
# The turn
# --------------------------------------------------------------------------------------


@dataclass
class _Turn:
    """Everything one turn accumulates. Not persisted: every field below has a span behind it."""

    request: ChatRequest
    buffer: TurnBuffer
    catalog: DiscoveredCatalog | None
    began: float
    decision: RouteDecision | None = None
    workflow: WorkflowSpec | None = None
    state: LoopState = field(default_factory=LoopState)
    evidence: dict[str, EvidenceChunk] = field(default_factory=dict)
    envelopes: list[_ToolEnvelope] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    step_summaries: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    tool_calls_made: int = 0
    steps_taken: int = 0
    reopened: bool = False
    #: Which act-loop reminders (§9.1 step 2) have been sent — each at most once per turn, and the
    #: list the `plan` span publishes as `nudges[]` so a nudged turn is visible to §13.4's reader.
    nudges: list[str] = field(default_factory=list)
    stop_reason: str = "answered"
    pending: ConfirmationCard | None = None
    clarification: str | None = None
    #: A confirmed write came back `isError`: the turn closes `partial`, never `answered` (§9.4).
    write_failed: bool = False
    #: The reader cancelled the proposal (W8, C11). The question is still answered; the write is
    #: not re-issued and the receipt opens the answer.
    declined: bool = False
    #: The gated `tool_call` span payload a resumed turn re-issues (§8.6 step 4).
    gated: dict[str, Any] | None = None
    #: The id of that proposal's own `confirmation` span, resolved in place when the human answers
    #: it (W8, C11). Nothing ever rewrote it, so the same card could be confirmed twice.
    pending_span_id: str | None = None
    #: The last three closed turns of this session, rendered into both prompts' user half (W8, C12).
    history: list[session.PriorTurn] = field(default_factory=list)
    #: Why the write was refused, when a `non_compliant` verdict forbade it (W8, C02). Set means
    #: the action debt is settled — deliberately, not by the model — and the answer opens with it.
    write_blocked: str | None = None
    #: Which slot a clarification is asking about (W8, C18); the quick replies follow it.
    clarify_slot: str | None = None

    @property
    def elapsed_s(self) -> float:
        return time.perf_counter() - self.began

    def chunks(self) -> list[EvidenceChunk]:
        """Every chunk the turn retrieved — what §7.2's synthesis prompt renders, quarantine flag
        and all, so the model sees the labelled envelope rather than a silently shortened corpus."""
        return list(self.evidence.values())

    def citable(self) -> list[EvidenceChunk]:
        """What G1 weighs: the chunks an answer could actually cite.

        A quarantined chunk is not one of them — G2 strips every citation to it (§7.4 trigger 4) —
        so letting it carry the evidence gate would clear the way for an answer whose support is
        removed two steps later. The gate and the completion predicates therefore read the same
        set; `LoopState.note_evidence` drops the same chunks for the same reason.
        """
        return [chunk for chunk in self.evidence.values() if not chunk.quarantined]


class Orchestrator:
    """One agent loop over one MCP client and one chat model.

    Constructed by `web/main.py`'s lifespan (P8) and by the tests, so the client's cached handshake
    lives as long as the process rather than as long as a call. The module-level `run_turn` /
    `resume_turn` of §9.1 delegate to a lazily-built process-wide instance.
    """

    def __init__(
        self,
        *,
        client: McpClient | None = None,
        model: ChatModel | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.client = client if client is not None else McpClient(settings=self.settings)
        self._model = model
        self._served_a_turn = False

    def model(self) -> ChatModel:
        """Built on first use so a missing key is a `configuration_required` turn, not a boot failure."""
        if self._model is None:
            self._model = build_agent_model(self.settings)
        return self._model

    async def aclose(self) -> None:
        await self.client.aclose()

    # ----------------------------------------------------------------------------------
    # Entry points (§9.1)
    # ----------------------------------------------------------------------------------

    async def run_turn(self, req: ChatRequest) -> ChatResponse:
        """One whole turn. Never raises for a modelled failure: every path answers (§9.5)."""
        session = SessionSpec(
            id=req.session_id or new_session_id(),
            employee_id=req.employee_id,
            auth_mode=req.auth_mode,
            actor_role=req.actor_role,
            client_label=req.client_label,
            eval_run_id=req.options.eval_run_id,
            user_agent_hash=req.user_agent_hash,
            cold_start=not self._served_a_turn,
        )
        buffer = trace.start_turn(session, user_message=req.message, turn_id=req.turn_id)
        cold = session.cold_start
        self._served_a_turn = True
        turn = _Turn(request=req, buffer=buffer, catalog=None, began=time.perf_counter())
        return await self._drive(turn, cold_start=cold)

    async def resume_turn(self, session_id: str, turn_id: str, confirmation_token: str) -> ChatResponse:
        """Pick a parked turn back up, re-issue **that one** `tools/call` with the token (§8.6 step 4)."""
        buffer = self._reopen(turn_id)
        turn = self._rehydrate(session_id, buffer, scores=await self._rehydrate_scores(buffer.turn_id))
        return await self._resume(turn, confirmation_token)

    async def decline_turn(self, session_id: str, turn_id: str) -> ChatResponse:
        """Pick a declined turn back up and answer the question, without the write (W8, C11).

        A decline used to mint a one-sentence answer and throw the rest away: on 2026-09-15 the
        reader who cancelled demo 2 lost four cited policy blocks, the balance, the verdict and
        every citation, having asked a question and answered a card. Cancelling the card is not
        cancelling the question. The turn rehydrates exactly as a confirmed one does, the gated
        call is simply **not** re-issued, and the receipt goes first as a `notice`.
        """
        buffer = self._reopen(turn_id)
        turn = self._rehydrate(session_id, buffer, scores=await self._rehydrate_scores(buffer.turn_id))
        turn.gated = None
        turn.declined = True
        turn.stop_reason = "declined"
        self._resolve_proposal(turn, "declined")
        return await self._answer(turn, cold_start=False)

    # ----------------------------------------------------------------------------------
    # The loop
    # ----------------------------------------------------------------------------------

    async def _drive(self, turn: _Turn, *, cold_start: bool) -> ChatResponse:
        req = turn.request
        try:
            turn.catalog = await self._discover(turn)
        except McpUnavailable as exc:
            return self._degraded(turn, str(exc), cold_start=cold_start)

        # -- 0. pre-checks: deterministic, zero LLM (§9.1 step 0) -----------------------
        # What this session has already settled, for both prompts' user half (W8, C12). One
        # indexed read per turn; a first turn reads nothing and renders nothing.
        turn.history = session.recent(turn.buffer.session_id)
        g4.check([_RawText("user_message", req.message)], turn=turn.buffer, source="user_message")
        phrase = self._out_of_corpus(req.message)
        if phrase is not None:
            turn.decision = fallback_decision(req.message, reason=f"pre-check: {phrase}", out_of_scope=True)
            self._plan(turn, step_index=0)
            return self._refuse(turn, g1.OUT_OF_SCOPE, cold_start=cold_start)

        # -- 1. route -------------------------------------------------------------------
        try:
            turn.decision = await self._route(turn)
        except MissingCredentialError as exc:
            return self._configuration_required(turn, exc, cold_start=cold_start)
        except DailyCapExceeded as exc:
            return self._daily_cap(turn, exc, cold_start=cold_start)
        except (ProviderError, ValueError) as exc:
            turn.decision = fallback_decision(req.message, reason="the router call failed")
            self._error(turn, "router_failed", str(exc), component="router")
        self._plan(turn, step_index=0)
        decision = turn.decision
        assert decision is not None
        turn.workflow = get_workflow(decision.workflow)

        if decision.sensitive:
            verdict = g5.check(sensitive=True, message=req.message, turn=turn.buffer)
            return self._finish(
                turn, g5.escalation(verdict), outcome="escalated", stop_reason="escalated", cold_start=cold_start
            )
        if is_unsafe(req.message):
            # **The turn opens by saying what will not happen** (W8, C20). The live
            # `unsafe-self-approve` turn was neither refused nor escalated: it ran out of steps,
            # apologised for it, stated the no-self-approval rule, and then recommended a
            # skip-level route premised on a conflict its own lookup disproved.
            return self._refuse_unsafe(turn, cold_start=cold_start)
        if decision.out_of_scope:
            return self._refuse(turn, g1.OUT_OF_SCOPE, cold_start=cold_start)
        if decision.needs_clarification:
            return self._clarify(turn, self._clarification_text(turn), cold_start=cold_start)

        # -- 2. act loop ----------------------------------------------------------------
        system, user = prompts.render(
            "act.j2",
            persona=prompts.persona_block(employee_id=req.employee_id, actor_source=req.actor_source),
            question=req.message,
            session_context=session.render(turn.history),
        )
        turn.messages = [Message(role="system", content=system), Message(role="user", content=user)]
        try:
            await self._run_act(turn)
        except MissingCredentialError as exc:
            return self._configuration_required(turn, exc, cold_start=cold_start)
        except DailyCapExceeded as exc:
            return self._daily_cap(turn, exc, cold_start=cold_start)
        except McpUnavailable as exc:
            return self._degraded(turn, str(exc), cold_start=cold_start)

        if turn.pending is not None:
            return self._park(turn, cold_start=cold_start)
        if turn.clarification is not None:
            return self._clarify(turn, turn.clarification, cold_start=cold_start)

        return await self._answer(turn, cold_start=cold_start)

    async def _answer(self, turn: _Turn, *, cold_start: bool) -> ChatResponse:
        """Steps 3 → 5: the evidence gate, the synthesis, and the two answer repairs."""
        decision = turn.decision
        assert decision is not None

        # -- 3. G1 over the accumulated chunk set ---------------------------------------
        verdict = g1.check(turn.citable(), turn=turn.buffer)
        if not verdict.passed and decision.rag_only and not turn.reopened:
            # §9.2's one-step recovery: the full catalog, one more act step, and a plan span
            # that says so. The step counts against AGENT_MAX_STEPS.
            turn.reopened = True
            self._plan(turn, step_index=turn.steps_taken, catalog_reopened=True)
            # The recovery step is spent blind unless the model is told what happened: the same
            # conversation that produced the refused answer, re-sent, produces it again (P13 R4).
            turn.nudges.append("g1_recovery")
            turn.messages.append(Message(role="user", content=G1_RECOVERY))
            try:
                await self._run_act(turn)
            except McpUnavailable as exc:
                return self._degraded(turn, str(exc), cold_start=cold_start)
            if turn.pending is not None:
                return self._park(turn, cold_start=cold_start)
            verdict = g1.check(turn.citable(), turn=turn.buffer)
        if not verdict.passed:
            return self._refuse(turn, verdict.reason, cold_start=cold_start)

        # -- 3b. the terminal debts (W8, C09 and C10) ------------------------------------
        # `_nudge` reports these on the step where the model stops calling tools. It cannot report
        # them on the step where the model stops for some other reason — a budget, a completion
        # predicate it satisfied another way — and on 9 of 12 recorded runs of `unsafe-001` the
        # turn reached synthesis with the write it was asked to propose still unmade, and answered
        # *"I cannot submit PTO requests in MosaicOne on your behalf"*. So the debt is terminal:
        # one more act step with the reminder, and then the orchestrator settles it itself.
        parked = await self._settle_debts(turn, cold_start=cold_start)
        if parked is not None:
            return parked

        # -- 4. synthesize ---------------------------------------------------------------
        try:
            raw = await self._synthesize(turn)
        except MissingCredentialError as exc:
            return self._configuration_required(turn, exc, cold_start=cold_start)
        except DailyCapExceeded as exc:
            return self._daily_cap(turn, exc, cold_start=cold_start)
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            return self._degraded(
                turn,
                f"the model could not produce an answer: {exc}",
                kind="synthesis_failed",
                caveat=SYNTHESIS_CAVEAT,
                component="synthesize",
                cold_start=cold_start,
            )

        # -- 5. G2 then G3, over raw blocks (§7.3's validator fires on an uncited fact) ---
        # One narration step for the whole verification pass (§11.3), closed by G2 — its first
        # span, and the one whose verdict decides whether the answer survives.
        blocks = list(raw.get("blocks") or [])
        repaired = g2.check(
            blocks,
            turn=turn.buffer,
            evidence=turn.evidence,
            quarantined=turn.quarantined,
            span_id=turn.buffer.open_span("guardrail", guardrail_span_name("G2")),
        )
        if repaired.refused:
            return self._refuse(turn, "every cited chunk failed to resolve", cold_start=cold_start)
        relabelled = g3.check(repaired.blocks, turn=turn.buffer)

        # -- 5b. citation breadth (P24) — NOT a guardrail either, and no G-number -----------
        # `expenses-002` cited two of the five documents its own evidence spanned and lost the
        # approval rule the question asked for; `onboarding-001` cited two of four. On a
        # multi-document turn — the router's `multi_doc`, or a workflow — an answer narrower than
        # its citable evidence buys ONE more synthesis call that names the uncited documents, and
        # the second answer replaces the first only if it is strictly broader and G2/G3 cost it
        # nothing (§7.4's citation-breadth paragraph).
        #
        # A turn that has already spent its budget never buys that call. `_act` sets a §9.4 budget
        # `stop_reason` and returns; the answer below is the graceful partial that stop exists to
        # produce, and widening it would spend one more synthesis-sized round trip (~15 s at the
        # deployed p50, plus one against `LLM_DAILY_CALL_CAP`) on exactly the turn the budget was
        # there to bound. The wall clock is re-read rather than trusted to `stop_reason` alone:
        # the act loop can end inside 90 s and synthesis carry the turn past it.
        inside_budget = turn.stop_reason not in BUDGET_STOPS and turn.elapsed_s < self.settings.agent_wall_clock_s
        widened = breadth.applies(decision) and inside_budget
        if widened:
            broadened = await self._broaden(turn, raw, relabelled.blocks)
            if broadened is not None:
                raw, repaired, relabelled = broadened

        # -- 5c–5k. the deterministic answer steps, in order (§9.1 step 5; §7.4) ---------------
        # Outcome consistency (P22): a write the user confirmed and the server performed is
        # reported from the tool result,
        # not from model output: the `performed` statement goes first with its id and is the
        # turn's one account of the write, so a model block of any type that names that id goes
        # (P29 — the live 2026-09-15 answer filed "HR ticket MOCK-HR-000007 has been created"
        # under "What I suggest you do"), an escalation denying the very action the result shows
        # was performed goes with it, and a next step telling the reader to go and perform it
        # themselves is dropped. The measured failure was a `created` ticket answered with "I
        # cannot open PTO requests on your behalf" and "Log into MosaicOne and submit your PTO
        # request" in the same answer (§7.4's outcome-consistency paragraph). `next_steps` goes
        # through the step for the same reason the blocks do: `render_answer` puts both in front
        # of the same reader.
        # Since UX W7 the same step also trims any sentence that tells the reader to go and file
        # the request the write has filed (Addendum 3), and types a statement of the reader's own
        # record `record` rather than leaving it under "not company policy" (JX2-05); the blocks
        # G3 demoted from an uncited `policy_fact` are handed over so a policy claim is never
        # retyped as the reader's data.
        # **A G3-demoted policy claim is marked on the block, not by position** (W8 fix round,
        # W7-review I1). `relabelled.relabelled` indexes `relabelled.blocks`; the merge and the
        # restatement below can each remove a block ahead of one, and an index that has drifted
        # exempts the wrong block from the record backstop. Every later step copies the dict, so
        # the marker travels; `_finished` strips it before the answer is validated.
        claimed = set(relabelled.relabelled)
        marked = [
            {**block, outcome_consistency.POLICY_CLAIM: True} if index in claimed else dict(block)
            for index, block in enumerate(relabelled.blocks)
        ]

        # -- 5c. merge the claims the breadth round duplicated (W8, C26) --------------------
        # The model answered the breadth instruction by adding a second block rather than a second
        # citation, so `remote-004` told the reader the same rule twice in different words with
        # different sources. Blocks whose normalised claim matches are folded into the first, and
        # their citations are unioned onto it.
        merged, _merged_away = breadth.merge(marked)
        # …and where the repair round was actually bought and the answer is **still** narrower than
        # its own evidence, the shortfall is recorded rather than left advisory. Only there: a
        # narrow answer on a turn that never bought the repair is not a failed invariant.
        if widened:
            minimum = turn.workflow.min_distinct_docs if turn.workflow is not None else breadth.MIN_DISTINCT_DOCS
            shortfall = breadth.distinct_docs_shortfall(merged, turn.citable(), minimum=minimum)
            if shortfall:
                self._error(
                    turn,
                    "distinct_docs_shortfall",
                    f"the served answer cites {shortfall} document(s) fewer than the {minimum} expected",
                    component=breadth.STEP_NAME,
                )

        # -- 5d. compliance restatement (W8, C03) — NOT a guardrail, and no G-number --------
        # The engine scored the notice requirement met with eight business days and the answer
        # denied it using the same eight relabelled as calendar days, then sent the reader to
        # chase a waiver she did not need. A sentence whose polarity opposes the engine's own row
        # is replaced by that row's result, in the reader's voice.
        restated = compliance_restatement.apply(
            merged,
            turn.envelopes,
            next_steps=[str(step) for step in (raw.get("next_steps") or [])],
        )

        # -- 5e. outcome consistency (P22) — NOT a guardrail, and no G-number ---------------
        consistent = outcome_consistency.apply(
            restated.blocks,
            turn.envelopes,
            next_steps=restated.next_steps,
            policy_claims=[
                index for index, block in enumerate(restated.blocks) if block.get(outcome_consistency.POLICY_CLAIM)
            ],
        )

        # -- 5f. the capability check (W8, C09, C10) ---------------------------------------
        # A sentence asserting the assistant cannot do what a permitted tool does, or stating a
        # profile attribute the reader's own envelope contradicts, is dropped. **After** the
        # outcome step, not before it: on a turn that performed the write, the whole escalation
        # denying it is already gone, and running first would leave its contact sentence stranded
        # under "Who to contact" beside a ticket that exists.
        capable = capability_check.apply(consistent.blocks, turn.envelopes, permitted=self._permitted(turn))

        # -- 5g. approver resolution (W8, C06) ---------------------------------------------
        # "requires approval from your director", served to the Director of Engineering. The chain
        # is resolved on the envelope; this is the backstop for the answer that wrote the role.
        named = approver_resolution.apply(capable.blocks, turn.envelopes, next_steps=consistent.next_steps)

        # -- 5h. arithmetic consistency (W8, C13) — the numeric twin of 5i ------------------
        # "8.0 days … (13.5 accrued minus 4.0 used, plus 2.5 carryover)" comes to 12.0. The total
        # is the tool's and stays; the working is replaced by the envelope's own, or removed.
        summed = arithmetic_consistency.apply(named.blocks, turn.envelopes, next_steps=named.next_steps)

        # -- 5i. date consistency (UX W6, npo2-02) — NOT a guardrail, and no G-number -------
        # Where the answer shows its arithmetic — "(21 days before 3 November)" — the arithmetic is
        # redone from the two operands in the sentence and the stated deadline is corrected. The
        # recorded failure told the reader to file on 13 September against a 13 October deadline it
        # had computed itself. Nothing else about the sentence is touched.
        dated = date_consistency.apply(summed.blocks, next_steps=summed.next_steps)

        # -- 5j. snapshot consistency (P29, npo2-08/-13) — NOT a guardrail, and no G-number ----
        # The employee-data snapshot is stated once, by the page's own footer ("Based on employee
        # data from 1 September 2026"), so an answer that restates it — "your PTO balance as of
        # 1 September 2026 is 13.5 days", live on 2026-09-15 — prints the same fact twice on one
        # screen, and in the earlier capture printed it in ISO as well. The restatement is removed
        # with whatever punctuation introduced it, and a tenure the profile tool reported in words
        # ("3 years 9 months") replaces the months the same answer made the reader divide. Only
        # dates the turn's own envelopes carry are touched: a deadline is somebody else's fact.
        snapshotted = snapshot_consistency.apply(dated.blocks, turn.envelopes, next_steps=dated.next_steps)

        # -- 5k. next-step entailment (W8, C08) — last, over the blocks that survived --------
        # `next_steps` was read by no rule: G2 and G3 run over blocks only. A step naming a date, a
        # duration, an amount or a person the answer never established is dropped, and the drop is
        # recorded the way G3 records one.
        entailed = step_entailment.apply(snapshotted.blocks, turn.envelopes, next_steps=snapshotted.next_steps)
        if entailed.dropped:
            self._error(
                turn,
                "next_step_unentailed",
                "; ".join(f"{claim!r} is in no block and no envelope" for _index, _step, claim in entailed.dropped),
                component=step_entailment.STEP_NAME,
            )

        answer = AnswerSchema(
            blocks=[
                AnswerBlock.model_validate({k: v for k, v in block.items() if k != outcome_consistency.POLICY_CLAIM})
                for block in snapshotted.blocks
            ],
            next_steps=entailed.next_steps,
            rationale_summary=clamp_rationale(str(raw.get("rationale_summary") or "")),
        )
        if turn.declined:
            # The receipt for what the reader decided, first and in the product's own voice
            # (W8, C11, C17); the answer they already earned follows it.
            answer = answer.model_copy(
                update={
                    "blocks": [
                        AnswerBlock(type=NOTICE, text=CANCELLED_NOTICE, citations=[]),
                        *answer.blocks,
                    ]
                }
            )
        if turn.write_blocked:
            # **The reader is told why, in the product's own voice** (W8, C02, C17). It goes first,
            # because the answer below is about a request that was not filed.
            answer = answer.model_copy(
                update={
                    "blocks": [
                        AnswerBlock(type=NOTICE, text=turn.write_blocked, citations=[]),
                        *answer.blocks,
                    ]
                }
            )
        if turn.write_failed:
            # §9.4's graceful partial for the other way a turn falls short of what it was asked to
            # do: the action was authorised and did not happen. The note goes first, and states no
            # policy, so it is a `recommendation`.
            answer = answer.model_copy(
                update={
                    "blocks": [
                        AnswerBlock(type=NOTICE, text=WRITE_FAILED_NOTE, citations=[]),
                        *answer.blocks,
                    ]
                }
            )
        budget_limited = turn.stop_reason in BUDGET_STOPS
        if budget_limited:
            # §9.4: a budget stop is a graceful partial answer plus an `error` span naming the
            # reason. The note goes first so the reader knows the answer is incomplete before
            # reading it, and it is a `recommendation` because it states no policy.
            self._error(
                turn,
                turn.stop_reason,
                f"the turn stopped at its {turn.stop_reason} budget",
                component="agent_loop",
            )
            answer = answer.model_copy(
                update={
                    "blocks": [
                        AnswerBlock(type=NOTICE, text=BUDGET_NOTE[turn.stop_reason], citations=[]),
                        *answer.blocks,
                    ]
                }
            )
        outcome: TurnOutcome = "partial" if budget_limited or turn.write_failed else "answered"
        return self._finish(
            turn,
            answer,
            outcome=outcome,
            stop_reason=turn.stop_reason,
            citations=repaired.citations,
            cold_start=cold_start,
        )

    # ----------------------------------------------------------------------------------
    # Steps
    # ----------------------------------------------------------------------------------

    async def _discover(self, turn: _Turn) -> DiscoveredCatalog:
        """The `mcp_discovery` span, with §9.5 row 1's one re-discovery."""
        try:
            return await self.client.discover(turn.buffer)
        except McpUnavailable:
            await self.client.reset()
            return await self.client.discover(turn.buffer)

    def _out_of_corpus(self, message: str) -> str | None:
        lowered = message.lower()
        return next((phrase for phrase in OUT_OF_CORPUS_PHRASES if phrase in lowered), None)

    async def _route(self, turn: _Turn) -> RouteDecision:
        req = turn.request
        system, user = prompts.render(
            "route.j2",
            persona=prompts.persona_block(employee_id=req.employee_id, actor_source=req.actor_source),
            question=req.message,
            session_context=session.render(turn.history),
        )
        completion = await self.model().complete(
            [Message(role="system", content=system), Message(role="user", content=user)],
            response_schema=RouteDecision,
            purpose="route",
            turn=turn.buffer,
        )
        decision = RouteDecision.model_validate(completion.parsed_json())
        catalog = turn.catalog
        return normalise(decision, catalog_names=catalog.names if catalog else (), message=req.message)

    async def _run_act(self, turn: _Turn) -> None:
        """One run of the act loop, closed by the `plan` span that summarises its steps (§9.7).

        Three planning moments produce a `plan` span, and `step_index` tells them apart: the
        router's (index 0, and the one §9.2's confusion matrix reads), a catalog reopen, and this
        one — where `step_summaries[]` and the tools actually called are recorded. Emitting the
        summary on the router's span was never possible: the steps had not happened yet.
        """
        try:
            await self._act(turn)
        finally:
            turn.buffer.add_span(
                "plan",
                "act_summary",
                PlanPayload(
                    intent=turn.decision.intent if turn.decision is not None else "policy_qa",
                    workflow=turn.workflow.name if turn.workflow is not None else None,
                    step_summaries=list(turn.step_summaries),
                    selected_tools=sorted(turn.state.results),
                    rationale_summary=clamp_rationale(
                        f"{turn.steps_taken} act {'step' if turn.steps_taken == 1 else 'steps'}, "
                        f"{turn.tool_calls_made} tool {'call' if turn.tool_calls_made == 1 else 'calls'}, "
                        f"stop_reason={turn.stop_reason}."
                    ),
                    step_index=turn.steps_taken,
                    catalog_reopened=turn.reopened,
                    nudges=list(turn.nudges),
                ),
            )

    async def _act(self, turn: _Turn) -> None:
        """The act loop of §9.1 step 2, and the only place a tool is called."""
        decision, catalog = turn.decision, turn.catalog
        assert decision is not None and catalog is not None
        settings = self.settings

        while True:
            if turn.steps_taken >= settings.agent_max_steps:
                turn.stop_reason = "max_steps"
                return
            if turn.elapsed_s >= settings.agent_wall_clock_s:
                turn.stop_reason = "timeout"
                return

            permitted = self._permitted(turn)
            completion = await self.model().complete(
                turn.messages,
                tools=offered(decision, catalog, disabled=turn.request.options.tools_disabled, reopened=turn.reopened),
                purpose="act",
                turn=turn.buffer,
            )
            turn.steps_taken += 1
            turn.messages.append(
                Message(role="assistant", content=completion.text, tool_calls=list(completion.tool_calls))
            )
            if not completion.tool_calls:
                if self._nudge(turn):
                    continue
                turn.step_summaries.append(f"step {turn.steps_taken}: no tool call, the model answered")
                return

            new_chunks: list[EvidenceChunk] = []
            for call in completion.tool_calls:
                if turn.tool_calls_made >= settings.agent_max_tool_calls:
                    turn.stop_reason = "max_tool_calls"
                    self._scan(turn, new_chunks)
                    return
                if call.name not in permitted:
                    # The gate of §9.2 is enforced at the call boundary, not only by omitting the
                    # tool from the array: a model that guesses a name still makes zero calls.
                    self._refused_call(turn, call)
                    continue
                result = await self._invoke(turn, call)
                turn.tool_calls_made += 1
                if result.confirmation_required:
                    # **The card is coupled to the verdict** (W8, C02). Demo 2 for E1108: the
                    # engine scored the request `non_compliant` on the balance — 0.25 days against
                    # a 3-day request — and the product filed the ticket anyway, led with "Done —
                    # Reference MOCK-HR-000011", then told him he lacks the accrual. A write the
                    # deterministic layer refuses is not proposed, and the refusal is recorded.
                    if self._refuse_write(turn, call, result):
                        continue
                    self._propose(turn, result)
                    self._scan(turn, new_chunks)
                    return
                if result.not_found:
                    turn.clarification = str(
                        result.body.get("hint") or "I could not find that employee. Employee ids look like E1042."
                    )
                    self._scan(turn, new_chunks)
                    return
                if not result.is_error:
                    new_chunks += await self._absorb_async(turn, result)
                # An `isError` result that survived its one repair still goes back to the model —
                # it is the only way the model learns what went wrong — but it never enters the
                # workflow state, or a rejected `check_policy_compliance` would count as a verdict.
                turn.messages.append(
                    Message(role="tool", tool_call_id=call.id, name=call.name, content=result.prompt_text)
                )

            self._scan(turn, new_chunks)
            turn.step_summaries.append(
                f"step {turn.steps_taken}: " + ", ".join(call.name for call in completion.tool_calls)
            )
            if (
                turn.workflow is not None
                and turn.workflow.is_complete(turn.state)
                and not self._action_outstanding(turn)
            ):
                turn.stop_reason = "answered"
                return
            if turn.reopened:
                # The recovery path buys exactly **one** additional step (§9.2).
                return

    async def _settle_debts(self, turn: _Turn, *, cold_start: bool) -> ChatResponse | None:
        """The two terminal debts of §9.1, settled before synthesis. A parked turn, or `None`.

        **The data debt (W8, C10).** A workflow whose structured-data slots are still empty has not
        read the record it is about. The live failures were a question about the reader's own
        office declined outright and an answer calling a hybrid employee "fully remote".

        **The action debt (W8, C09).** `intent == "action"`, a permitted write tool, and no gated
        attempt. `_nudge` already reports this on the step the model stops calling tools; nine of
        twelve recorded runs of `unsafe-001` reached synthesis another way and denied the
        product's headline capability instead. One more act step with the reminder, and if the
        model still will not propose it, the orchestrator proposes it — from the slots the turn
        itself resolved, so the card is the turn's own state and not an invention.
        """
        if self._data_outstanding(turn) and "data_outstanding" not in turn.nudges:
            turn.nudges.append("data_outstanding")
            turn.messages.append(Message(role="user", content=DATA_OUTSTANDING))
            turn.step_summaries.append(f"step {turn.steps_taken}: the reader's own record was still unread")
            try:
                await self._run_act(turn)
            except McpUnavailable as exc:
                return self._degraded(turn, str(exc), cold_start=cold_start)
            if turn.pending is not None:
                return self._park(turn, cold_start=cold_start)

        if not self._action_outstanding(turn) or not any(name in self._permitted(turn) for name in WRITE_TOOLS):
            return None
        if "action_outstanding" not in turn.nudges:
            turn.nudges.append("action_outstanding")
            turn.messages.append(Message(role="user", content=ACTION_OUTSTANDING))
            turn.step_summaries.append(f"step {turn.steps_taken}: the requested action was still unproposed")
            try:
                await self._run_act(turn)
            except McpUnavailable as exc:
                return self._degraded(turn, str(exc), cold_start=cold_start)
            if turn.pending is not None:
                return self._park(turn, cold_start=cold_start)
        if not self._action_outstanding(turn):
            return None

        # Still nothing. The demo's headline capability does not depend on the model's mood.
        turn.nudges.append("action_proposed_deterministically")
        try:
            await self._propose_deterministically(turn)
        except McpUnavailable as exc:
            return self._degraded(turn, str(exc), cold_start=cold_start)
        self._plan(turn, step_index=turn.steps_taken)
        return self._park(turn, cold_start=cold_start) if turn.pending is not None else None

    def _data_outstanding(self, turn: _Turn) -> bool:
        """A workflow turn that has read no structured record it requires, and could still read one."""
        workflow = turn.workflow
        if workflow is None or turn.pending is not None:
            return False
        permitted = self._permitted(turn)
        reachable = [name for name in workflow.requires_tool_results if name in permitted]
        missing = [name for name in workflow.missing_tool_results(turn.state) if name in permitted]
        # Every reachable slot still empty: the turn has read nothing at all about this person.
        # A turn that read some of them has established a record and is not this failure.
        return bool(missing) and len(missing) == len(reachable)

    async def _propose_deterministically(self, turn: _Turn) -> None:
        """Issue the write the turn was asked for, from the slots the turn itself resolved (C09).

        No token: the call comes back `CONFIRMATION_REQUIRED` exactly as the model's would, and
        `_propose` turns it into the same card. The arguments are templated from the compliance
        call's own parameters, so the card cannot describe a request the turn never scored.
        """
        arguments = self._write_arguments(turn)
        if arguments is None:
            return
        result = await self._call(turn, WRITE_TOOLS[0], arguments)
        turn.tool_calls_made += 1
        if result.confirmation_required:
            self._propose(turn, result)
            turn.step_summaries.append("the assistant proposed the requested write from the turn's own slots")

    def _write_arguments(self, turn: _Turn) -> dict[str, Any] | None:
        """`create_mock_hr_ticket` arguments built from the turn's resolved slots, or `None`.

        `None` when the turn never resolved enough to describe the request: a card whose summary
        was invented would be worse than no card, because the reader confirms what it says.
        """
        employee_id = turn.request.employee_id
        if not employee_id or not EMPLOYEE_ID.match(employee_id):
            return None
        body = turn.state.latest(COMPLIANCE_TOOL) or {}
        computed = dict(body.get("computed") or {})
        scenario = str(body.get("scenario") or "")
        queue = DETERMINISTIC_QUEUES.get(scenario)
        if queue is None:
            return None
        days = [
            date_consistency.human_date(date.fromisoformat(value))
            for key in ("start_date", "span_end")
            if isinstance(value := computed.get(key), str) and ISO_DATE.fullmatch(value)
        ]
        span = " to ".join(days) if len(days) == 2 else ""
        subject = DETERMINISTIC_SUBJECTS[scenario]
        summary = f"{subject}: {span}" if span else subject
        rows = [f"- {row['text']} — {row['reason']}" for row in body.get("requirements") or [] if row.get("text")]
        details = "\n".join(
            [
                f"Requested by {employee_id} through the HR Copilot.",
                f"Verdict: {body.get('verdict') or 'not evaluated'} (rules {body.get('rules_version') or 'n/a'}).",
                *rows,
            ]
        )
        return {"employee_id": employee_id, "queue": queue, "summary": summary, "details": details}

    def _permitted(self, turn: _Turn) -> list[str]:
        """The names this act step may call: §9.2's gate, then §13.9's per-turn ablation filter.

        One expression, read by the loop before it offers the tool array and by `_nudge` before it
        reports a debt, so a reminder can never ask for something the very next call boundary would
        refuse. A turn with no catalog has called nothing and can call nothing.
        """
        if turn.decision is None or turn.catalog is None:
            return []
        return allowed_tools(
            turn.decision,
            turn.catalog,
            disabled=turn.request.options.tools_disabled,
            reopened=turn.reopened,
        )

    def _nudge(self, turn: _Turn) -> bool:
        """Tell the model, at most once each, what the turn still owes. Did it send one?

        A step of the act loop (§9.1 step 2); the debt it reports is §9.3's completion predicate,
        the action the router recorded, or the breadth of the corpus the turn has read.

        The completion predicate is Python and cannot be talked out of its requirements — but a
        model that has stopped calling tools cannot read it either. Three reminders, each sent only
        on the step where the model tried to stop and only while the gap is real: the workflow has
        no citable evidence yet, the user asked for something to be created and nothing has been
        proposed, or the turn has spent at most one query on the federated corpus and the question
        spans more of it than that reaches. The first two were live failures under the real provider; the third
        is the judged baseline's `remote-002` / `expenses-002`, which cited two documents where the
        end state required three. At most one reminder per step, so a nudged turn costs one extra
        act step and not three.

        **A reminder reports the debt in workflow words and stops there.** Naming the tools that
        would settle it would make the harness, not the model, the author of the rest of the tool
        sequence on every nudged turn. And a debt nothing permitted can settle is not reported at
        all: under §13.9's `no_structured_tools` ablation the model would answer the reminder with
        a call the gate refuses, and the ablation would be reading `tool_not_offered` spans of its
        own making.
        """
        permitted = self._permitted(turn)
        workflow = turn.workflow
        if workflow is not None and "workflow_incomplete" not in turn.nudges and not workflow.is_complete(turn.state):
            debts = workflow.debts(turn.state, permitted=permitted)
            if debts:
                turn.nudges.append("workflow_incomplete")
                owed = "; ".join(debts)
                turn.messages.append(
                    Message(role="user", content=WORKFLOW_INCOMPLETE.format(workflow=workflow.name, debts=owed))
                )
                turn.step_summaries.append(f"step {turn.steps_taken}: workflow incomplete — {owed}")
                return True
        if (
            self._action_outstanding(turn)
            and "action_outstanding" not in turn.nudges
            and any(name in permitted for name in WRITE_TOOLS)
        ):
            turn.nudges.append("action_outstanding")
            turn.messages.append(Message(role="user", content=ACTION_OUTSTANDING))
            turn.step_summaries.append(f"step {turn.steps_taken}: the requested action was still unproposed")
            return True
        searches = self._searches(turn)
        if "search_breadth" not in turn.nudges and searches <= 1 and any(name in permitted for name in EVIDENCE_TOOLS):
            turn.nudges.append("search_breadth")
            reminder = SEARCH_BREADTH if searches == 1 else SEARCH_BREADTH_UNSEARCHED
            turn.messages.append(Message(role="user", content=reminder))
            turn.step_summaries.append(
                f"step {turn.steps_taken}: {searches} corpus search(es), and the question may span more"
            )
            return True
        return False

    def _searches(self, turn: _Turn) -> int:
        """How many corpus searches this turn has already made.

        `EVIDENCE_TOOLS` is the same list the workflow debts read: the tools whose results carry
        scored, citable evidence. Only successful results are in state, so a search that errored
        does not count as one the model has already spent.
        """
        return sum(len(turn.state.results.get(name, ())) for name in EVIDENCE_TOOLS)

    def _action_outstanding(self, turn: _Turn) -> bool:
        """The user asked for something to be **created** and nothing has been proposed yet.

        A write the verdict forbade is **not** outstanding (W8, C02): it was deliberately not made,
        the answer says so, and nudging for it would ask the model to file what the engine refused.

        §9.3's `pto_request` predicate is satisfied by a cited answer alone — the ticket is its one
        *optional, gated* slot — so a turn whose router intent is `action` would otherwise close one
        step before the confirmation gate that demo task 2 exists to show (§18.2). A completion
        predicate decides when the slots are filled; it does not get to drop a request the user
        made in words.
        """
        return (
            turn.decision is not None
            and turn.decision.intent == "action"
            and turn.pending is None
            and turn.write_blocked is None
            # A write the reader cancelled and a write that was authorised and failed are both
            # **answered** requests: re-proposing either would put the same card back in front of
            # somebody who has already dealt with it (W8, C09 against C11 and §9.4).
            and not turn.declined
            and not turn.write_failed
            and not any(name in turn.state.results for name in WRITE_TOOLS)
        )

    async def _invoke(self, turn: _Turn, call: ToolCall) -> ToolResult:
        """One `tools/call`, with §9.1's single repair round trip on a schema violation."""
        result = await self._call(turn, call.name, call.args)
        if not result.is_error or result.confirmation_required:
            return result
        if turn.tool_calls_made + 1 >= self.settings.agent_max_tool_calls:
            # The repair costs a second `tools/call`; with no budget for it the honest move is to
            # degrade now rather than start a round trip whose result cannot be spent.
            return result
        try:
            repair = await self._repair(turn, call, result)
        except (ProviderError, ValueError, json.JSONDecodeError) as exc:
            self._error(turn, "repair_failed", str(exc), component="repair")
            return result
        if repair is None:
            return result
        turn.tool_calls_made += 1
        return await self._call(turn, call.name, repair.arguments)

    async def _call(self, turn: _Turn, name: str, arguments: dict[str, Any], token: str | None = None) -> ToolResult:
        options = turn.request.options
        return await self.client.call_tool(
            turn.buffer,
            name=name,
            arguments=arguments,
            employee_id=turn.request.employee_id,
            actor_source=turn.request.actor_source,
            strategy=options.retrieval_strategy,
            k_override=options.k,
            confirmation_token=token,
            on_retrieval=lambda payload: self._mark(turn, payload),
        )

    async def _repair(self, turn: _Turn, call: ToolCall, failed: ToolResult) -> ToolCallRepair | None:
        """Ask once for corrected arguments. Never twice — the second failure degrades (§9.1).

        `turn.messages` **already ends with** the assistant message that carries this `tool_use`
        (`_act` appends it before it runs the step's calls), so re-appending it would send the same
        id twice in two consecutive assistant messages and leave the first pair unanswered — a
        request the Messages API rejects, which would make the one repair round trip §9.1 mandates
        impossible against the pinned model. Only the results and the corrective ask are added, and
        every *other* `tool_use` of that step still awaiting a result gets a placeholder: a
        `tool_use` block with no `tool_result` in the next message is the same 400.
        """
        answered = {message.tool_call_id for message in turn.messages if message.role == "tool"}
        outstanding = [
            pending for pending in self._step_calls(turn) if pending.id != call.id and pending.id not in answered
        ]
        messages = [
            *turn.messages,
            Message(role="tool", tool_call_id=call.id, name=call.name, content=failed.prompt_text),
            *(
                Message(role="tool", tool_call_id=pending.id, name=pending.name, content=NOT_RUN_YET)
                for pending in outstanding
            ),
            Message(
                role="user",
                content=(
                    f"The call to {call.name} was rejected. Reply with the corrected arguments for "
                    f"that same tool, matching its published input schema."
                ),
            ),
        ]
        completion = await self.model().complete(
            messages, response_schema=ToolCallRepair, purpose="repair", turn=turn.buffer
        )
        repair = ToolCallRepair.model_validate(completion.parsed_json())
        return repair if repair.tool_name == call.name else None

    @staticmethod
    def _step_calls(turn: _Turn) -> list[ToolCall]:
        """The tool calls of the act step now in flight — the last assistant message's."""
        for message in reversed(turn.messages):
            if message.role == "assistant" and message.tool_calls:
                return list(message.tool_calls)
        return []

    async def _broaden(
        self, turn: _Turn, raw: Mapping[str, Any], blocks: Sequence[Mapping[str, Any]]
    ) -> tuple[dict[str, Any], g2.Outcome, g3.Outcome] | None:
        """The one breadth repair of §7.4 (P24), or `None` to keep the answer already written.

        It continues the synthesis conversation — the same rendered prompt, the model's own answer,
        and one message naming the citable documents that answer does not cite — and is recorded as
        a `repair` call, the same purpose the act loop's one tool-call repair uses, so the
        dashboard's `llm_call` drill-down shows the extra round trip without a new vocabulary.

        Every failure here keeps the first answer: a turn must never lose a written answer to the
        step that was only trying to widen it.

        **The second answer is verified with the pure rules first, and only a repair that is
        accepted emits its `guardrail` spans.** A rejected repair is a draft nobody was shown, and
        §13.3's `blocks_dropped_by_g2` — the count of grounded facts the citation guardrail
        destroyed — sums every G2 span of the turn: a discarded draft's drop would be reported as a
        fact the reader lost. The `repair` `llm_call` span still carries what the model wrote, so
        nothing about the extra round trip is hidden; what is not recorded is a verdict on an
        answer that was never served.
        """
        missing = breadth.uncited_documents(blocks, turn.citable())
        if not missing:
            return None
        messages = [
            *self._synthesis_messages(turn),
            Message(role="assistant", content=json.dumps(raw)),
            Message(role="user", content=breadth.instruction(missing, turn.citable())),
        ]
        try:
            completion = await self.model().complete(
                messages, response_schema=AnswerSchema, purpose="repair", turn=turn.buffer
            )
            body = completion.parsed_json()
            if not isinstance(body, dict):
                return None
            draft = g2.apply(
                list(body.get("blocks") or []),
                evidence=turn.evidence,
                quarantined=turn.quarantined,
            )
            widened = g3.apply(draft.blocks)
            for block in widened.blocks:
                AnswerBlock.model_validate(block)
        except (ProviderError, DailyCapExceeded, ValidationError, ValueError, json.JSONDecodeError):
            return None
        if not breadth.accepted(
            blocks,
            widened.blocks,
            turn.citable(),
            dropped_blocks=draft.dropped_blocks,
            refused=draft.refused,
        ):
            return None
        # Accepted: re-run the same two rules through the span-emitting path, so the answer the
        # reader is served carries its own guardrail record like any other (§7.4, §11.6 page 8).
        second = g2.check(
            list(body.get("blocks") or []),
            turn=turn.buffer,
            evidence=turn.evidence,
            quarantined=turn.quarantined,
        )
        return body, second, g3.check(second.blocks, turn=turn.buffer)

    def _synthesis_messages(self, turn: _Turn) -> list[Message]:
        """§7.2's two halves, rendered from the turn's accumulated evidence.

        One renderer for the two callers that need the exact same bytes: the synthesis call, and
        the breadth repair of §7.4 (P24), which continues that conversation rather than opening a
        second one — re-rendering is what keeps the two prompts identical up to the repair message.
        """
        req = turn.request
        system, user = prompts.render(
            "synthesize.j2",
            persona=prompts.persona_block(employee_id=req.employee_id, actor_source=req.actor_source),
            chunks=turn.chunks(),
            tool_results=turn.envelopes,
            question=req.message,
            # A write this turn performed: the prompt's per-turn half then says the request is
            # filed and the reader is not to be sent to file it (UX W7, Addendum 3). Advisory —
            # `outcome_consistency.apply` is the guard — and in the *user* half on purpose, so the
            # cached system prefix is the same bytes on every turn (§9.8).
            performed_write=outcome_consistency.performed_write(turn.envelopes),
        )
        return [Message(role="system", content=system), Message(role="user", content=user)]

    async def _synthesize(self, turn: _Turn) -> dict[str, Any]:
        # W2-E: the answer reaches the page while the model is still writing it. Only **complete**
        # blocks travel — `render_answer()` labels a recommendation, so a half-written block could
        # read as company policy until its prefix arrived — and only `text` / `citations` of each,
        # never `rationale_summary` (§9.7's hidden reasoning) and never `next_steps`. The assembler
        # coalesces the deltas so the bounded SSE queue can never silently drop a block.
        assembler = AnswerAssembler()
        turn_id = turn.buffer.turn_id

        def publish(blocks: Sequence[StreamedBlock]) -> None:
            for block in blocks:
                trace.publish_answer_delta(
                    AnswerDeltaEvent(
                        turn_id=turn_id,
                        index=block.index,
                        type=block.type,
                        text=block.text,
                        citations=list(block.citations),
                    )
                )

        completion = await self.model().complete(
            self._synthesis_messages(turn),
            response_schema=AnswerSchema,
            purpose="synthesize",
            turn=turn.buffer,
            on_delta=lambda delta: publish(assembler.feed(delta)),
        )
        # Whatever the last coalescing window left: a turn's final block is otherwise shown only
        # when `turn_completed` replaces the provisional answer wholesale.
        publish(assembler.flush())
        body = completion.parsed_json()
        if not isinstance(body, dict):
            raise ValueError("the synthesis call did not return a JSON object")
        return body

    # ----------------------------------------------------------------------------------
    # Evidence
    # ----------------------------------------------------------------------------------

    def _mark(self, turn: _Turn, payload: RetrievalPayload) -> None:
        """G4's seam: quarantine **before** the lifted `retrieval` span is persisted (§7.4).

        The eval's one G4 item asserts `quarantined: true` on the `retrieval` span itself, and the
        demo shows the banner from the same record, so marking a copy after the span was written
        would leave both reading `false`.
        """
        for chunk in payload.chunks:
            row = corpusread.get_chunk(chunk.chunk_id)
            if g4.scan(row.text if row is not None else chunk.snippet) is not None:
                chunk.quarantined = True
                if chunk.chunk_id not in turn.quarantined:
                    turn.quarantined.append(chunk.chunk_id)

    async def _absorb_async(self, turn: _Turn, result: ToolResult) -> list[EvidenceChunk]:
        """`_absorb` from a coroutine, with its one blocking call off the event loop (P13 p2).

        `_engine_evidence` embeds the turn's question to score the compliance engine's own chunks.
        On the 0.1-CPU instance that is ≈ 0.6 s of CPU, and it was being spent inside a synchronous
        `_absorb` called straight from the act loop, so for that 0.6 s the process served nothing —
        not the SSE rail, not `/health`, not another turn. Every other embed on the request path
        already runs under `asyncio.to_thread` (§2.1). This one now does too.

        The scoring moves; the rule does not. `_absorb` stays synchronous because it still owns the
        decision about what engine evidence is worth — this method only hands it a dict it would
        otherwise have computed itself, which is why the resolution is repeated rather than passed:
        `corpusread.get_chunk` is a handful of indexed reads, against 600 ms of ONNX.

        The act loop is not the only caller that runs on a loop: `_rehydrate` also calls
        `_engine_evidence`, from the `await`ed `resume_turn` behind `POST /chat/confirm`. That path
        has its own async boundary — `_rehydrate_scores` — for the same reason. The synchronous
        signatures survive both, which is what keeps the unit call sites unchanged.
        """
        scores: dict[str, float] | None = None
        if result.tool_name == COMPLIANCE_TOOL:
            resolved = self._engine_evidence_rows(turn, result.body)
            if resolved:
                # §4.2's `agent/** → rag/` exemption, as at `_engine_evidence` — see the note there.
                from hrmosaic.rag.retrieve import score_chunk_ids

                scores = await asyncio.to_thread(score_chunk_ids, list(resolved), query=turn.request.message)
        return self._absorb(turn, result, engine_scores=scores)

    def _absorb(
        self,
        turn: _Turn,
        result: ToolResult,
        *,
        engine_scores: Mapping[str, float] | None = None,
    ) -> list[EvidenceChunk]:
        """Fold one successful tool result into the turn's state, evidence and prompt envelopes."""
        turn.state.record(result.tool_name, result.body)
        turn.envelopes.append(_ToolEnvelope(name=result.tool_name, result_json=result.text))
        fresh: list[EvidenceChunk] = []
        for payload in result.retrievals:
            for chunk in payload.chunks:
                # `_mark` has already run (it is `call_tool`'s `on_retrieval` seam), so the flag is
                # final here: a quarantined hit stays on the `retrieval` span and stays out of the
                # evidence a predicate or a gate may count.
                turn.state.note_evidence(chunk.chunk_id, chunk.doc_id, quarantined=chunk.quarantined)
                if chunk.chunk_id in turn.evidence:
                    continue
                evidence = EvidenceChunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    doc_title=chunk.doc_title,
                    heading_path=chunk.heading_path,
                    section=chunk.section,
                    snippet=chunk.snippet,
                    dense_score=chunk.dense_score,
                    rrf_score=chunk.rrf_score,
                    quarantined=chunk.quarantined,
                )
                turn.evidence[chunk.chunk_id] = evidence
                fresh.append(evidence)
        # ⚠ A merely *cited* chunk id is not evidence, for one reason: nothing scored it. A
        # quarantined chunk is the same rule wearing a different hat — G2 strips every citation to
        # it — and it is dropped by `note_evidence` above while staying, flag and all, on the
        # `retrieval` span. Tools 2 and 4 cite ids they never retrieved, and those ids used to count
        # towards the workflow's document spread. They no longer do (P8's live check: §9.3's
        # predicate now reads evidence the same way §7.4's G1 does), because a completion predicate
        # that counted them while the evidence gate did not made `is_complete` true on a turn G1 was
        # about to refuse. One meaning of "evidence", shared by the predicate and the gate.
        #
        # `_engine_evidence` below does not weaken that: it does not admit tool 4's citations, it
        # SCORES the chunks behind its per-requirement evidence and lets the same rule judge them.
        body = result.body
        if result.tool_name == COMPLIANCE_TOOL:
            self._engine_evidence(turn, body, scores=engine_scores)
        if result.tool_name in WRITE_TOOLS:
            # §8.5's allocated ids: `MOCK-HR-…` from tool 8, `MOCK-EMAIL-…` from tool 9.
            for key in ("ticket_id", "draft_id"):
                if body.get(key):
                    turn.state.mock_write_ids.append(str(body[key]))
        return fresh

    def _engine_evidence_rows(self, turn: _Turn, body: dict[str, Any]) -> dict[str, Any]:
        """The chunks `_engine_evidence` will score: cited per requirement, new to this turn, real.

        Split out so the async boundary can resolve them, score them in a thread and hand the
        scores back — see `_absorb_async`. It reads nothing but `body` and `turn.evidence`, so the
        two callers see the same set.
        """
        ids = [chunk_id for chunk_id in _cited_evidence_ids(body) if chunk_id not in turn.evidence]
        rows = {chunk_id: corpusread.get_chunk(chunk_id) for chunk_id in ids}
        return {chunk_id: row for chunk_id, row in rows.items() if row is not None}

    def _engine_evidence(
        self,
        turn: _Turn,
        body: dict[str, Any],
        *,
        scores: Mapping[str, float] | None = None,
    ) -> list[EvidenceChunk]:
        """Score the compliance engine's own evidence and offer it to the gate (§7.4 G1, P13 R7).

        `check_policy_compliance` is deterministic and every requirement it evaluates carries an
        `evidence` block naming a **committed** chunk, resolved by `mcpserver/rules.py` from a
        `(doc_id, heading_path)` pair in `corpus/rules.yml`. Nothing had ever scored those ids, so
        G1 could not see them and a turn could reach a correct, cited verdict and be refused for
        want of evidence — the judged baseline's `remote-003`.

        **The candidate set widens; the rule does not.** Each id is resolved against the committed
        index (an unknown one is nothing, exactly as it is to G2), scored on the same dense path
        §7.1's fill step uses, run through G4, and only then handed to `note_evidence` and the turn's
        citable set — the treatment a retrieved chunk gets, no more. A resolved chunk below
        `MIN_EVIDENCE_SCORE` still refuses, and nothing is ever admitted unscored.

        The engine's top-level `citations[]` is deliberately not read: it is a list of ids the turn
        did not retrieve, and that is what `_absorb` has declined to count since P8. Cost: one embed
        per compliance result that resolves something new.
        """
        resolved = self._engine_evidence_rows(turn, body)
        if not resolved:
            return []

        if scores is None:
            # One of the **three** places `agent/**` reaches into `hrmosaic.rag` — the others are
            # `_absorb_async` and `_rehydrate_scores`, both of which score the same compliance
            # evidence off the request path (§4.2's docstring convention, and the same lazy-import
            # shape `web/api.py` uses for `/health`'s index block). The alternative was a tenth MCP
            # tool whose only caller is this line, and §13.4 would then have scored an extra
            # `tools/call` on every compliance turn.
            from hrmosaic.rag.retrieve import score_chunk_ids

            scores = score_chunk_ids(list(resolved), query=turn.request.message)
        fresh: list[EvidenceChunk] = []
        for chunk_id, row in resolved.items():
            if chunk_id not in scores:
                continue
            chunk = EvidenceChunk(
                chunk_id=row.chunk_id,
                doc_id=row.doc_id,
                doc_title=row.doc_title,
                heading_path=row.heading_path,
                section=row.section,
                snippet=row.snippet,
                dense_score=scores[chunk_id],
                quarantined=g4.scan(row.text) is not None,
            )
            turn.evidence[chunk_id] = chunk
            turn.state.note_evidence(chunk_id, row.doc_id, quarantined=chunk.quarantined)
            if chunk.quarantined and chunk_id not in turn.quarantined:
                turn.quarantined.append(chunk_id)
            fresh.append(chunk)
        if fresh:
            g4.check(fresh, turn=turn.buffer, source="compliance_evidence")
        return fresh

    def _scan(self, turn: _Turn, chunks: Sequence[EvidenceChunk]) -> None:
        """One G4 span per act step over the evidence that step produced (§9.1 step 2)."""
        if chunks:
            g4.check(list(chunks), turn=turn.buffer, source="retrieval")

    # ----------------------------------------------------------------------------------
    # Spans
    # ----------------------------------------------------------------------------------

    def _plan(self, turn: _Turn, *, step_index: int, catalog_reopened: bool = False) -> None:
        decision = turn.decision
        assert decision is not None
        turn.buffer.add_span(
            "plan",
            "router" if step_index == 0 and not catalog_reopened else "replan",
            PlanPayload(
                intent=decision.intent,
                workflow=decision.workflow,
                step_summaries=list(turn.step_summaries),
                selected_tools=list(decision.selected_tools),
                rationale_summary=clamp_rationale(decision.rationale_summary),
                step_index=step_index,
                catalog_reopened=catalog_reopened,
                # What the turn has been reminded of, so a planning moment after the act summary —
                # the orchestrator settling the action debt itself (W8, C09) — is on the record
                # too. §13.4's reader takes `nudges` from every `plan` span of the turn.
                nudges=list(turn.nudges),
            ),
        )

    def _error(self, turn: _Turn, kind: str, message: str, *, component: str, retryable: bool = False) -> None:
        turn.buffer.add_span(
            "error",
            component,
            ErrorPayload(error_kind=kind, message=message, retryable=retryable, component=component),
            status="error",
            error_message=message,
        )

    def _refused_call(self, turn: _Turn, call: ToolCall) -> None:
        """A tool the router's gate did not offer. Recorded, never called (§9.2)."""
        self._error(
            turn,
            "tool_not_offered",
            f"{call.name} is not offered for this turn's intent",
            component="router_gate",
        )
        turn.messages.append(
            Message(
                role="tool",
                tool_call_id=call.id,
                name=call.name,
                content=json.dumps(
                    {
                        "status": "not_offered",
                        "code": "TOOL_NOT_OFFERED",
                        "hint": f"{call.name} is not available for this question. Use the offered tools.",
                    }
                ),
            )
        )

    def _refuse_write(self, turn: _Turn, call: ToolCall, result: ToolResult) -> bool:
        """Refuse a proposed write the turn's own verdict forbids. Did it refuse? (W8, C02)

        `non_compliant` **is** the "blocking requirement unmet" condition: §8.4 defines it as an
        evaluable `blocking` requirement that is unmet, so the verdict alone is the test and no
        second reading of the requirement rows can disagree with it.

        The model is told, in the tool channel, that the call was refused and why — it is the only
        way the answer can be written around the refusal — and the reason is kept on the turn so
        the answer opens with it as a `notice`.
        """
        body = turn.state.latest(COMPLIANCE_TOOL)
        if not body or body.get("verdict") != "non_compliant":
            return False
        envelope = _ToolEnvelope(name=COMPLIANCE_TOOL, result_json=json.dumps(body, ensure_ascii=False))
        failing = next((row for row in compliance_restatement.rows([envelope]) if row.status == "unmet"), None)
        reason = compliance_restatement.reader_sentence(failing) if failing is not None else ""
        contact = str(body.get("escalate_to") or "")
        turn.write_blocked = " ".join(
            part
            for part in (
                "I have not opened the request:",
                reason or "the policy check came back non-compliant.",
                f"Contact {contact} to discuss the options." if contact else "",
            )
            if part
        )
        self._error(
            turn,
            "write_blocked",
            f"{call.name} was not proposed: the {body.get('scenario')} verdict is non_compliant",
            component="agent_loop",
        )
        turn.messages.append(
            Message(
                role="tool",
                tool_call_id=call.id,
                name=call.name,
                content=json.dumps(
                    {
                        "status": "not_permitted",
                        "code": "VERDICT_NON_COMPLIANT",
                        "hint": (
                            "The compliance verdict for this request is non_compliant, so it was not "
                            "proposed. Explain why and offer what the policy allows."
                        ),
                    }
                ),
            )
        )
        turn.step_summaries.append(f"step {turn.steps_taken}: {call.name} refused — the verdict is non_compliant")
        return True

    def _propose(self, turn: _Turn, result: ToolResult) -> None:
        """The pending `confirmation` span — no token, and nothing written (§8.6 step 1)."""
        body = result.body
        card = ConfirmationCard(
            action=str(body.get("action") or result.tool_name),
            human_summary=str(body.get("human_summary") or f"Run {result.tool_name}."),
            arguments_preview=dict(body.get("arguments_preview") or {}),
            expires_at=now_micros() + CONFIRMATION_TTL_S * 1_000_000,
        )
        turn.buffer.add_span(
            "confirmation",
            card.action,
            span_id=turn.buffer.open_span("confirmation", card.action, parent_span_id=result.span_id),
            payload=ConfirmationPayload(
                action=card.action,
                arguments_preview=card.arguments_preview,
                human_summary=card.human_summary,
                prompt_shown=card.human_summary,
                expires_at=card.expires_at,
                user_response="pending",
            ),
            parent_span_id=result.span_id,
        )
        turn.pending = card
        turn.stop_reason = "awaiting_confirmation"

    # ----------------------------------------------------------------------------------
    # Endings
    # ----------------------------------------------------------------------------------

    def _clarification_text(self, turn: _Turn) -> str:
        """One question, about the slot that is actually empty (UX W2, jargon-and-exposure-4; W8, C18).

        It used to read the router's `rationale_summary` aloud and then recite
        `WorkflowSpec.required_slots` — *"I need: employee profile, PTO balance, requested days,
        policy evidence on notice and approval, a compliance verdict, (optional, gated) a created
        ticket."* — and close by asking for an employee id the app already knows. Those slots are
        the predicate's documentation; they belong to the dashboard, and they are still there.

        UX W2 replaced that with one question per **workflow**, which asks the wrong question as
        soon as the workflow is right and a different slot is missing: the admin turn of
        2026-09-15 was asked *"which dates are you thinking of?"* by a message that had given the
        dates, when what `admin` lacks is an employee record. The key is the first unfilled slot,
        and the session's own history counts as filled (W8, C12).
        """
        workflow = turn.workflow
        turn.clarify_slot = unfilled_slot(
            workflow.name if workflow is not None else None,
            known=session.known(turn.history),
            has_record=bool(EMPLOYEE_ID.match(turn.request.employee_id or "")),
        )
        return CLARIFY_QUESTIONS.get(turn.clarify_slot or "", CLARIFY_FALLBACK)

    def _clarify(self, turn: _Turn, question: str, *, cold_start: bool) -> ChatResponse:
        """`outcome="clarify"`, and the question names the missing slot (§9.6)."""
        answer = AnswerSchema(
            blocks=[AnswerBlock(type=NOTICE, text=question, citations=[])],
            next_steps=["Reply with the missing detail and I will pick this up."],
            rationale_summary="Clarification requested: a required detail is missing.",
        )
        return self._finish(
            turn,
            answer,
            outcome="clarify",
            stop_reason="clarify",
            cold_start=cold_start,
            quick_replies=clarify_chips(turn.clarify_slot),
        )

    def _refuse_unsafe(self, turn: _Turn, *, cold_start: bool) -> ChatResponse:
        """`outcome="refused"`, naming what will not be done and what the matrix does instead."""
        answer = AnswerSchema(
            blocks=[AnswerBlock(type=NOTICE, text=UNSAFE_REFUSAL, citations=[])],
            next_steps=list(UNSAFE_NEXT_STEPS),
            rationale_summary="Refused: self-approval or a bypass of the approval chain.",
        )
        return self._finish(turn, answer, outcome="refused", stop_reason="refused", cold_start=cold_start)

    def _refuse(self, turn: _Turn, reason: str, *, cold_start: bool) -> ChatResponse:
        return self._finish(
            turn,
            g1.refusal(reason),
            outcome="refused",
            stop_reason="refused",
            cold_start=cold_start,
        )

    def _park(self, turn: _Turn, *, cold_start: bool) -> ChatResponse:
        """The turn ends `awaiting_confirmation` and **nothing is written** (§8.6 step 1)."""
        card = turn.pending
        assert card is not None
        answer = AnswerSchema(
            blocks=[
                AnswerBlock(
                    type=NOTICE,
                    # The card below states what is about to happen, field by field. Repeating
                    # `human_summary` here made the same sentence appear three times on one screen
                    # (UX W2, chat-production-ux-9); this lead says what the card is for.
                    text="Nothing has been created yet. Review this, then confirm or cancel.",
                    citations=[],
                )
            ],
            # The card below carries the decision and both buttons by name; a next step repeating it
            # was the third copy of the same sentence on one screen (UX W2, chat-production-ux-9).
            next_steps=[],
            rationale_summary="Paused for human confirmation before an irreversible action.",
        )
        return self._finish(
            turn,
            answer,
            outcome="awaiting_confirmation",
            stop_reason="awaiting_confirmation",
            confirmation=card,
            cold_start=cold_start,
        )

    def _degraded(
        self,
        turn: _Turn,
        reason: str,
        *,
        cold_start: bool,
        kind: str = "tool_unavailable",
        caveat: str = CAVEAT_TEXT,
        component: str = "mcp",
    ) -> ChatResponse:
        """§9.5 row 1: an explicit caveat block and an escalation note, at HTTP 200.

        The caveat is a parameter because the two ways a turn degrades say different things: the
        tool server being unreachable means no evidence was read at all, while a synthesis failure
        means the evidence was read and could not be turned into an answer. One shared sentence
        would have been a small lie in whichever case it did not describe.
        """
        self._error(turn, kind, reason, component=component, retryable=kind == "tool_unavailable")
        answer = AnswerSchema(
            blocks=[
                AnswerBlock(type=NOTICE, text=caveat, citations=[]),
                AnswerBlock(
                    type="escalation",
                    text=(
                        "Please ask People Operations directly at "
                        f"{g5.PEOPLE_OPS} while the tool server is unavailable."
                    ),
                    citations=[],
                ),
            ],
            next_steps=["Try again shortly, or contact People Operations."],
            rationale_summary=clamp_rationale(f"Degraded: {reason}."),
        )
        return self._finish(
            turn, answer, outcome="partial", stop_reason="error", error_kind=kind, cold_start=cold_start
        )

    def _configuration_required(self, turn: _Turn, exc: MissingCredentialError, *, cold_start: bool) -> ChatResponse:
        """§12.3: a missing key degrades the surface that needs it, and never at boot."""
        self._error(turn, "configuration_required", str(exc), component="llm")
        answer = AnswerSchema(
            blocks=[AnswerBlock(type=NOTICE, text=str(exc), citations=[])],
            next_steps=[f"Set {exc.variable} and try again."],
            rationale_summary="No model credential is configured.",
        )
        return self._finish(
            turn,
            answer,
            outcome="configuration_required",
            stop_reason="configuration_required",
            error_kind="configuration_required",
            cold_start=cold_start,
        )

    def _daily_cap(self, turn: _Turn, exc: DailyCapExceeded, *, cold_start: bool) -> ChatResponse:
        """§9.8's spend guard: HTTP 200, `daily_cap_reached`, and no new `degradations[]` string."""
        self._error(turn, "daily_cap_reached", str(exc), component="llm")
        answer = AnswerSchema(
            blocks=[
                AnswerBlock(
                    type=NOTICE,
                    text="The daily model budget for this deployment is exhausted. Please try again tomorrow.",
                    citations=[],
                )
            ],
            next_steps=["Contact People Operations if this is urgent."],
            rationale_summary="Daily model call cap reached.",
        )
        return self._finish(
            turn, answer, outcome="error", stop_reason="error", error_kind="daily_cap_reached", cold_start=cold_start
        )

    def _finish(
        self,
        turn: _Turn,
        answer: AnswerSchema,
        *,
        outcome: TurnOutcome,
        stop_reason: str,
        citations: Sequence[Citation] = (),
        confirmation: ConfirmationCard | None = None,
        error_kind: str | None = None,
        cold_start: bool = False,
        quick_replies: Sequence[str] = (),
    ) -> ChatResponse:
        """Step 6: the closing UPDATE, then the response built from the very spans that were written."""
        decision = turn.decision
        rendered = render_answer(answer.blocks, answer.next_steps)
        # G6 gives the redaction sweep a name and a record; `core/trace.py` runs it again on the
        # closing UPDATE, and `redact()` is idempotent (§7.4, §10.4).
        rendered = g6.check(rendered, turn=turn.buffer, subject="final answer")
        turn.buffer.close(
            outcome=outcome,
            stop_reason=stop_reason,
            final_answer=rendered,
            answer_blocks=list(answer.blocks),
            citations=list(citations),
            # Beside the blocks, not inside the joined string: a replayed refusal's redirect used
            # to depend on `parse_next_steps()` finding the section `render_answer()` had appended
            # (UX W3).
            next_steps=list(answer.next_steps),
            intent=decision.intent if decision is not None else None,
            workflow=decision.workflow if decision is not None else None,
            error_kind=error_kind,
        )
        usage, timings = self._rollups(turn)
        return ChatResponse(
            session_id=turn.buffer.session_id,
            turn_id=turn.buffer.turn_id,
            trace_id=turn.buffer.session_id,
            outcome=outcome,
            answer=rendered,
            answer_blocks=list(answer.blocks),
            next_steps=list(answer.next_steps),
            quick_replies=list(quick_replies),
            citations=list(citations),
            trace=project(turn.buffer.turn_id, session_id=turn.buffer.session_id),
            confirmation=confirmation,
            usage=usage,
            timings=timings,
            cold_start=cold_start,
            stream_url=f"/chat/stream?turn_id={turn.buffer.turn_id}",
            dashboard_url=f"/dashboard/sessions/{turn.buffer.session_id}#turn-{turn.buffer.seq}",
        )

    def _rollups(self, turn: _Turn) -> tuple[Usage, Timings]:
        """The closed turn's own rollups, so the response and the dashboard agree (W1-C(c)).

        `TurnBuffer.close()` has just computed these and written them; they used to be read back out
        of `turns` with a second query on the request path. `close_totals` is the mapping the
        closing UPDATE was built from — not a copy — so this is the same identity the re-SELECT
        provided, without the round trip. An unclosed turn has none, and reports nothing rather than
        a number nothing wrote.
        """
        totals = turn.buffer.close_totals or {}
        return (
            Usage(
                prompt_tokens=totals.get("total_tokens_in", 0),
                completion_tokens=totals.get("total_tokens_out", 0),
                llm_calls=totals.get("llm_calls", 0),
                tool_calls=totals.get("tool_calls", 0),
                retrievals=totals.get("retrievals", 0),
            ),
            Timings(
                total_ms=totals.get("duration_ms", 0),
                llm_ms=totals.get("llm_ms", 0),
                retrieval_ms=totals.get("retrieval_ms", 0),
                tool_ms=totals.get("tool_ms", 0),
                store_ms=totals.get("store_ms", 0),
            ),
        )

    # ----------------------------------------------------------------------------------
    # Resume (§9.1, §8.6 step 4)
    # ----------------------------------------------------------------------------------

    def _resolve_proposal(self, turn: _Turn, response: str) -> None:
        """Write the human's answer onto the proposal's own span, in place (W8, C11).

        Here rather than in `web/`, so **both** entry points are covered: `POST /chat/confirm` is
        one caller of `resume_turn`, and the evaluation harness and the tests are others. A turn
        with no pending span — a replay, or a resume nobody proposed — resolves nothing.
        """
        if turn.pending_span_id:
            trace.resolve_confirmation(turn.pending_span_id, user_response=response)
            turn.pending_span_id = None

    def _reopen(self, turn_id: str) -> TurnBuffer:
        """The buffer `web/`'s `trace.reopen_turn(...)` already opened, or a fresh reopen."""
        writer = trace.get_writer()
        for buffer in writer.open_turns():
            if buffer.turn_id == turn_id:
                return buffer
        return writer.reopen_turn(turn_id, 0)

    async def _rehydrate_scores(self, turn_id: str) -> dict[str, float] | None:
        """`_rehydrate`'s one blocking call, moved off the event loop (P13 p2, the resume path).

        `_rehydrate` re-runs `_engine_evidence` over the parked turn's `tool_call` spans, and that
        embeds the turn's question — ≈ 0.6 s of ONNX on the 0.1-CPU instance. `_rehydrate` is
        synchronous, but it is called from `resume_turn`, which `POST /chat/confirm` awaits, so
        that embed ran on the loop thread: the confirm path blocked exactly as the act loop used to.
        This resolves the same candidate ids ahead of the walk, scores them in a thread, and hands
        the result down as `scores=`, through the seam `_absorb_async` already opened.

        The ids collected here are a **superset** of what `_engine_evidence_rows` will resolve
        during the walk — it drops the ones the turn has already picked up from a `retrieval` span,
        which this cannot know yet — and `score_chunk_ids` is a per-chunk cosine against the query
        vector, so a wider input changes no chunk's score. `_engine_evidence` still admits only the
        ids it resolves itself. The cost of getting there is one extra indexed read of the same
        `spans` rows.
        """
        store = get_store()
        ids: list[str] = []
        for row in store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'tool_call' ORDER BY seq", (turn_id,)
        ).dicts():
            payload = json.loads(row["payload_json"])
            if payload.get("tool_name") != COMPLIANCE_TOOL:
                continue
            if payload.get("error_code") == "CONFIRMATION_REQUIRED":
                # The gated span is `_rehydrate`'s `gated`; it is re-issued, not absorbed.
                continue
            for chunk_id in _cited_evidence_ids(payload.get("structured_content") or {}):
                if chunk_id not in ids:
                    ids.append(chunk_id)
        if not ids:
            # Nothing to score, so nothing for `_engine_evidence` to admit either: leave it `None`
            # rather than an empty mapping, which would read as "scored, and none of them made it".
            return None
        message = store.execute("SELECT user_message FROM turns WHERE id = ?", (turn_id,)).scalar()

        # §4.2's `agent/** → rag/` exemption, as at `_engine_evidence` — see the note there.
        from hrmosaic.rag.retrieve import score_chunk_ids

        return await asyncio.to_thread(score_chunk_ids, ids, query=str(message or ""))

    def _rehydrate(self, session_id: str, buffer: TurnBuffer, *, scores: Mapping[str, float] | None = None) -> _Turn:
        """Rebuild the in-process state from the turn's own spans — never by re-retrieving (§9.1).

        `scores` is `_rehydrate_scores`' result on the awaited resume path, so the engine-evidence
        embed happens in a thread; left `None` (the synchronous call sites) `_engine_evidence`
        scores for itself, exactly as before.
        """
        store = get_store()
        turn_row = store.execute(
            "SELECT t.user_message, s.employee_id FROM turns t JOIN sessions s ON s.id = t.session_id WHERE t.id = ?",
            (buffer.turn_id,),
        ).one()
        if turn_row is None:
            raise KeyError(f"no such turn: {buffer.turn_id}")
        spans = store.execute(
            "SELECT id, seq, kind, name, payload_json FROM spans WHERE turn_id = ? ORDER BY seq",
            (buffer.turn_id,),
        ).dicts()

        request = ChatRequest(
            message=turn_row["user_message"] or "",
            session_id=session_id,
            turn_id=buffer.turn_id,
            employee_id=turn_row["employee_id"] or "E1042",
        )
        turn = _Turn(
            request=request,
            buffer=buffer,
            catalog=None,
            began=time.perf_counter(),
            decision=fallback_decision(request.message, reason="resumed after confirmation"),
        )

        gated: dict[str, Any] | None = None
        pending_span_id: str | None = None
        act_calls = 0
        for span in spans:
            payload = json.loads(span["payload_json"])
            kind = span["kind"]
            if kind == "confirmation" and payload.get("user_response") == "pending":
                pending_span_id = str(span["id"])
            if kind == "plan" and span["name"] == "router":
                turn.decision = turn.decision.model_copy(  # type: ignore[union-attr]
                    update={
                        "intent": payload.get("intent") or "workflow",
                        "workflow": payload.get("workflow"),
                        "selected_tools": payload.get("selected_tools") or [],
                    }
                )
            elif kind == "llm_call" and payload.get("purpose") == "act":
                act_calls += 1
            elif kind == "retrieval":
                self._rehydrate_retrieval(turn, RetrievalPayload.model_validate(payload))
            elif kind == "tool_call":
                body = payload.get("structured_content") or {}
                if payload.get("error_code") == "CONFIRMATION_REQUIRED":
                    gated = payload
                    continue
                turn.state.record(payload["tool_name"], body)
                # The same line `_absorb` runs live (P13 R7). Engine evidence is scored, never
                # retrieved, so it was never written to a `retrieval` span and `_rehydrate_retrieval`
                # cannot bring it back — and since R7 it counts towards `is_complete` and G1. Without
                # this, a turn that grounded itself on the engine, closed as complete and parked at
                # §8.6's gate came back across the confirmation boundary with an empty citable set
                # and was refused for want of evidence on a write that had already happened. The
                # gate has to mean the same thing on both sides of the park (§9.1). The embed that
                # scoring costs is `_rehydrate_scores`', already spent in a thread.
                if payload["tool_name"] == COMPLIANCE_TOOL:
                    self._engine_evidence(turn, body, scores=scores)
                turn.envelopes.append(
                    _ToolEnvelope(name=payload["tool_name"], result_json=payload.get("result_json") or "{}")
                )
        turn.steps_taken = act_calls
        turn.workflow = get_workflow(turn.decision.workflow if turn.decision else None)
        turn.messages = self._rehydrate_messages(buffer.turn_id, request)
        turn.gated = gated
        turn.pending_span_id = pending_span_id
        return turn

    def _rehydrate_retrieval(self, turn: _Turn, payload: RetrievalPayload) -> None:
        for chunk in payload.chunks:
            turn.state.note_evidence(chunk.chunk_id, chunk.doc_id, quarantined=chunk.quarantined)
            if chunk.quarantined and chunk.chunk_id not in turn.quarantined:
                turn.quarantined.append(chunk.chunk_id)
            turn.evidence.setdefault(
                chunk.chunk_id,
                EvidenceChunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    doc_title=chunk.doc_title,
                    heading_path=chunk.heading_path,
                    section=chunk.section,
                    snippet=chunk.snippet,
                    dense_score=chunk.dense_score,
                    rrf_score=chunk.rrf_score,
                    quarantined=chunk.quarantined,
                ),
            )

    def _rehydrate_messages(self, turn_id: str, request: ChatRequest) -> list[Message]:
        """The message array from the last `act` call's own `llm_messages` rows (§9.1)."""
        rows = (
            get_store()
            .execute(
                "SELECT m.role, m.content FROM llm_messages m JOIN spans s ON s.id = m.span_id "
                "WHERE s.turn_id = ? AND s.kind = 'llm_call' AND m.span_id = ("
                "  SELECT s2.id FROM spans s2 WHERE s2.turn_id = ? AND s2.kind = 'llm_call'"
                "    AND json_extract(s2.payload_json, '$.purpose') = 'act'"
                "  ORDER BY s2.seq DESC LIMIT 1) ORDER BY m.seq",
                (turn_id, turn_id),
            )
            .dicts()
        )
        if rows:
            return [Message(role=row["role"], content=row["content"]) for row in rows]
        system, user = prompts.render(
            "act.j2",
            persona=prompts.persona_block(employee_id=request.employee_id, actor_source="default"),
            question=request.message,
        )
        return [Message(role="system", content=system), Message(role="user", content=user)]

    async def _resume(self, turn: _Turn, confirmation_token: str) -> ChatResponse:
        gated = turn.gated
        if not gated:
            return self._refuse(turn, "there is no gated tool call on this turn to confirm", cold_start=False)
        try:
            turn.catalog = await self._discover(turn)
        except McpUnavailable as exc:
            return self._degraded(turn, str(exc), cold_start=False)

        # The **confirmed** span, before the write it authorises — §13.4 action-safety clause 1
        # keys on "an earlier `confirmation` span in the same turn". Since W8 (C11) that span is the
        # proposal's own, resolved in place: one card, one record of what the human said to it, and
        # a `seq` already earlier than the write below. A second span here said "Confirmed:
        # create_mock_hr_ticket" over the same fact and left the first one reading `pending` for
        # ever, which is what let the same card be confirmed twice and mint a second ticket.
        self._resolve_proposal(turn, "confirmed")
        try:
            result = await self._call(
                turn, str(gated["tool_name"]), dict(gated.get("arguments") or {}), token=confirmation_token
            )
        except McpUnavailable as exc:
            return self._degraded(turn, str(exc), cold_start=False)
        turn.tool_calls_made += 1
        if result.confirmation_required:
            self._error(turn, "confirmation_rejected", "the confirmation token was refused", component="mcp")
            return self._refuse(turn, "the confirmation could not be validated", cold_start=False)
        if result.is_error:
            # The token validated and the write still failed. Mirroring `_act`: the body goes to the
            # synthesis envelopes so the answer can say what happened, and **nowhere near**
            # `state.record`, or a rejected `create_mock_hr_ticket` would count as a created ticket
            # and the turn would close "answered" over a write that never happened.
            self._error(
                turn,
                "tool_failed",
                f"{result.tool_name} failed after the confirmation was accepted",
                component="mcp",
            )
            turn.envelopes.append(_ToolEnvelope(name=result.tool_name, result_json=result.text))
            turn.write_failed = True
            turn.stop_reason = "tool_failed"
        else:
            await self._absorb_async(turn, result)
        return await self._answer(turn, cold_start=False)


# --------------------------------------------------------------------------------------
# The process-wide instance and the two named entry points (§9.1)
# --------------------------------------------------------------------------------------

_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def set_orchestrator(orchestrator: Orchestrator | None) -> None:
    """Install (or clear) the process-wide orchestrator — the lifespan's hook, and the tests'."""
    global _orchestrator
    _orchestrator = orchestrator


async def run_turn(req: ChatRequest) -> ChatResponse:
    """§9.1's first entry point. `POST /chat` is a thin wrapper around this."""
    return await get_orchestrator().run_turn(req)


async def resume_turn(session_id: str, turn_id: str, confirmation_token: str) -> ChatResponse:
    """§9.1's second entry point. `POST /chat/confirm` calls it after minting the one-time token."""
    return await get_orchestrator().resume_turn(session_id, turn_id, confirmation_token)


async def decline_turn(session_id: str, turn_id: str) -> ChatResponse:
    """The cancelled half of the same gate: answer the question, never re-issue the write (W8, C11)."""
    return await get_orchestrator().decline_turn(session_id, turn_id)


#: The two projection helpers, published for `web/sse.py` (P8). The live span rail and `trace[]`
#: must describe a span identically — the rail collapses into the trace panel under the finished
#: answer — so there is one implementation of each, not two (§11.3).
summarise_span = _summary
preview_value = _preview


__all__ = [
    "CONFIRMATION_TTL_S",
    "OUT_OF_CORPUS_PHRASES",
    "WRITE_TOOLS",
    "ChatOptions",
    "ChatRequest",
    "ChatResponse",
    "ConfirmationCard",
    "EvidenceChunk",
    "Orchestrator",
    "clarify_chips",
    "clarify_slot_of",
    "Timings",
    "ToolCallRepair",
    "Usage",
    "decline_turn",
    "get_orchestrator",
    "preview_value",
    "project",
    "render_answer",
    "resume_turn",
    "run_turn",
    "set_orchestrator",
    "summarise_span",
]
