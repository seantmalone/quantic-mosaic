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

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hrmosaic.agent import prompts
from hrmosaic.agent.client import DiscoveredCatalog, McpClient, McpUnavailable, ToolResult
from hrmosaic.agent.guardrails import g1, g2, g3, g4, g5, g6
from hrmosaic.agent.router import RouteDecision, allowed_tools, clamp_rationale, fallback_decision, normalise, offered
from hrmosaic.agent.workflows import EVIDENCE_TOOLS, LoopState, WorkflowSpec
from hrmosaic.agent.workflows import get as get_workflow
from hrmosaic.core import corpusread, trace
from hrmosaic.core.db import Store, get_store, now_micros
from hrmosaic.core.ids import new_session_id
from hrmosaic.core.llm import build_agent_model
from hrmosaic.core.llm.base import ChatModel, Message, MissingCredentialError, ProviderError, ToolCall
from hrmosaic.core.llm.limiter import DailyCapExceeded
from hrmosaic.core.models import (
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
from hrmosaic.core.trace import SessionSpec, TurnBuffer
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
SEARCH_BREADTH = (
    "Not yet — you have searched the corpus once. This corpus is federated on purpose: duration "
    "thresholds, approved-country lists, approval authority and device/security rules are each "
    "written in a different document, and a single query reaches only one or two of them. Re-read "
    "the question, and for every distinct thing it asks that your evidence does not yet cover, "
    "search again. Then conclude."
)

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
        return (
            f"purpose={payload.get('purpose')} · "
            f"{payload.get('prompt_tokens', 0)}→{payload.get('completion_tokens', 0)} tok"
        )
    if kind == "retrieval":
        chunks = payload.get("chunks") or []
        docs = sorted({chunk.get("doc_id", "") for chunk in chunks})
        top = payload.get("max_dense_score")
        return f"{len(chunks)} chunks · top dense {top if top is not None else 'n/a'} · {', '.join(docs)}"
    if kind == "guardrail":
        return f"verdict={payload.get('verdict')} · {payload.get('reason', '')}"
    if kind == "confirmation":
        return f"{payload.get('action')} · {payload.get('user_response')}"
    if kind == "error":
        return f"{payload.get('error_kind')}: {payload.get('message', '')}"
    if kind == "tool_call":
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


def render_answer(blocks: Sequence[AnswerBlock], next_steps: Sequence[str]) -> str:
    """The deterministic join of §7.3: a recommendation is labelled, an escalation is flagged."""
    parts: list[str] = []
    for block in blocks:
        if block.type == "recommendation":
            parts.append(f"Recommendation — not company policy: {block.text}")
        elif block.type == "escalation":
            parts.append(f"Escalation: {block.text}")
        else:
            parts.append(block.text)
    if next_steps:
        parts.append("Next steps:\n" + "\n".join(f"- {step}" for step in next_steps))
    return "\n\n".join(parts)


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
    #: The gated `tool_call` span payload a resumed turn re-issues (§8.6 step 4).
    gated: dict[str, Any] | None = None

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
        turn = self._rehydrate(session_id, self._reopen(turn_id))
        return await self._resume(turn, confirmation_token)

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
        if decision.out_of_scope:
            return self._refuse(turn, g1.OUT_OF_SCOPE, cold_start=cold_start)
        if decision.needs_clarification:
            return self._clarify(turn, self._clarification_text(turn), cold_start=cold_start)

        # -- 2. act loop ----------------------------------------------------------------
        system, user = prompts.render(
            "act.j2",
            persona=prompts.persona_block(employee_id=req.employee_id, actor_source=req.actor_source),
            question=req.message,
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
        blocks = list(raw.get("blocks") or [])
        repaired = g2.check(
            blocks,
            turn=turn.buffer,
            evidence=turn.evidence,
            quarantined=turn.quarantined,
        )
        if repaired.refused:
            return self._refuse(turn, "every cited chunk failed to resolve", cold_start=cold_start)
        relabelled = g3.check(repaired.blocks, turn=turn.buffer)

        answer = AnswerSchema(
            blocks=[AnswerBlock.model_validate(block) for block in relabelled.blocks],
            next_steps=[str(step) for step in (raw.get("next_steps") or [])],
            rationale_summary=clamp_rationale(str(raw.get("rationale_summary") or "")),
        )
        if turn.write_failed:
            # §9.4's graceful partial for the other way a turn falls short of what it was asked to
            # do: the action was authorised and did not happen. The note goes first, and states no
            # policy, so it is a `recommendation`.
            answer = answer.model_copy(
                update={
                    "blocks": [
                        AnswerBlock(type="recommendation", text=WRITE_FAILED_NOTE, citations=[]),
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
                        AnswerBlock(type="recommendation", text=BUDGET_NOTE[turn.stop_reason], citations=[]),
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
                        f"{turn.steps_taken} act step(s), {turn.tool_calls_made} tool call(s), "
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
                    new_chunks += self._absorb(turn, result)
                # An `isError` result that survived its one repair still goes back to the model —
                # it is the only way the model learns what went wrong — but it never enters the
                # workflow state, or a rejected `check_policy_compliance` would count as a verdict.
                turn.messages.append(Message(role="tool", tool_call_id=call.id, name=call.name, content=result.text))

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

        A step of the act loop (§9.1 step 2); the debt it reports is §9.3's completion predicate
        and, for the second reminder, the action the router recorded.

        The completion predicate is Python and cannot be talked out of its requirements — but a
        model that has stopped calling tools cannot read it either. Three reminders, each sent only
        on the step where the model tried to stop and only while the gap is real: the workflow has
        no citable evidence yet, the user asked for something to be created and nothing has been
        proposed, or the turn searched the federated corpus once and the question spans more of it
        than one query reaches. The first two were live failures under the real provider; the third
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
        if (
            "search_breadth" not in turn.nudges
            and any(name in permitted for name in EVIDENCE_TOOLS)
            and self._searches(turn) <= 1
        ):
            turn.nudges.append("search_breadth")
            turn.messages.append(Message(role="user", content=SEARCH_BREADTH))
            turn.step_summaries.append(f"step {turn.steps_taken}: one search, and the question spans more")
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
            Message(role="tool", tool_call_id=call.id, name=call.name, content=failed.text),
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

    async def _synthesize(self, turn: _Turn) -> dict[str, Any]:
        req = turn.request
        system, user = prompts.render(
            "synthesize.j2",
            persona=prompts.persona_block(employee_id=req.employee_id, actor_source=req.actor_source),
            chunks=turn.chunks(),
            tool_results=turn.envelopes,
            question=req.message,
        )
        completion = await self.model().complete(
            [Message(role="system", content=system), Message(role="user", content=user)],
            response_schema=AnswerSchema,
            purpose="synthesize",
            turn=turn.buffer,
        )
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

    def _absorb(self, turn: _Turn, result: ToolResult) -> list[EvidenceChunk]:
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
        # ⚠ Two kinds of chunk id are *not* evidence, for one reason: an answer cannot rest on
        # them. A quarantined chunk is the second kind — G2 strips every citation to it — and it is
        # dropped by `note_evidence` above while staying, flag and all, on the `retrieval` span.
        # Tools 2 and 4 also cite chunk ids, and those ids used to count towards the workflow's
        # document spread. They no longer do (P8's live check: §9.3's predicate now reads evidence
        # the same way §7.4's G1 does). They carry no dense score, so they never enter G1's candidate
        # set — and a completion predicate that counted them while the evidence gate did not made
        # `is_complete` true on a turn G1 was about to refuse. Live, the model reached
        # `check_policy_compliance` without ever searching, the act loop closed because the workflow
        # "was complete", and both demo tasks refused for want of evidence. One meaning of
        # "evidence", shared by the predicate and the gate, is the whole fix.
        body = result.body
        if result.tool_name in WRITE_TOOLS:
            # §8.5's allocated ids: `MOCK-HR-…` from tool 8, `MOCK-EMAIL-…` from tool 9.
            for key in ("ticket_id", "draft_id"):
                if body.get(key):
                    turn.state.mock_write_ids.append(str(body[key]))
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
            ConfirmationPayload(
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
        decision = turn.decision
        workflow = turn.workflow
        missing = decision.rationale_summary if decision is not None else ""
        slots = f" I need: {', '.join(workflow.required_slots)}." if workflow is not None else ""
        return (
            f"I need one more detail before I can answer. {missing}{slots} "
            "Employee ids look like E1042, and dates are clearest as an explicit day and month."
        )

    def _clarify(self, turn: _Turn, question: str, *, cold_start: bool) -> ChatResponse:
        """`outcome="clarify"`, and the question names the missing slot (§9.6)."""
        answer = AnswerSchema(
            blocks=[AnswerBlock(type="recommendation", text=question, citations=[])],
            next_steps=["Reply with the missing detail and I will pick this up."],
            rationale_summary="Clarification requested: a required detail is missing.",
        )
        return self._finish(turn, answer, outcome="clarify", stop_reason="clarify", cold_start=cold_start)

    def _refuse(self, turn: _Turn, reason: str, *, cold_start: bool) -> ChatResponse:
        names = turn.catalog.names if turn.catalog is not None else ()
        return self._finish(
            turn,
            g1.refusal(reason, tool_names=names),
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
                    type="recommendation",
                    text=(
                        f"{card.human_summary} Nothing has been created yet — confirm and I will do it, "
                        "or cancel and I will not."
                    ),
                    citations=[],
                )
            ],
            next_steps=["Review the details on the confirmation card, then choose Confirm or Cancel."],
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
                AnswerBlock(type="recommendation", text=caveat, citations=[]),
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
            blocks=[AnswerBlock(type="recommendation", text=str(exc), citations=[])],
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
                    type="recommendation",
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
        """Read back the closed turn's own rollups, so the response and the dashboard agree."""
        row = (
            get_store()
            .execute(
                "SELECT total_tokens_in, total_tokens_out, llm_calls, tool_calls, retrievals, duration_ms, "
                "llm_ms, retrieval_ms, tool_ms, store_ms FROM turns WHERE id = ?",
                (turn.buffer.turn_id,),
            )
            .one()
        )
        if row is None:  # pragma: no cover - the row was inserted by start_turn
            return Usage(), Timings()
        return (
            Usage(
                prompt_tokens=row["total_tokens_in"] or 0,
                completion_tokens=row["total_tokens_out"] or 0,
                llm_calls=row["llm_calls"] or 0,
                tool_calls=row["tool_calls"] or 0,
                retrievals=row["retrievals"] or 0,
            ),
            Timings(
                total_ms=row["duration_ms"] or 0,
                llm_ms=row["llm_ms"] or 0,
                retrieval_ms=row["retrieval_ms"] or 0,
                tool_ms=row["tool_ms"] or 0,
                store_ms=row["store_ms"] or 0,
            ),
        )

    # ----------------------------------------------------------------------------------
    # Resume (§9.1, §8.6 step 4)
    # ----------------------------------------------------------------------------------

    def _reopen(self, turn_id: str) -> TurnBuffer:
        """The buffer `web/`'s `trace.reopen_turn(...)` already opened, or a fresh reopen."""
        writer = trace.get_writer()
        for buffer in writer.open_turns():
            if buffer.turn_id == turn_id:
                return buffer
        return writer.reopen_turn(turn_id, 0)

    def _rehydrate(self, session_id: str, buffer: TurnBuffer) -> _Turn:
        """Rebuild the in-process state from the turn's own spans — never by re-retrieving (§9.1)."""
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
        act_calls = 0
        for span in spans:
            payload = json.loads(span["payload_json"])
            kind = span["kind"]
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
                turn.envelopes.append(
                    _ToolEnvelope(name=payload["tool_name"], result_json=payload.get("result_json") or "{}")
                )
        turn.steps_taken = act_calls
        turn.workflow = get_workflow(turn.decision.workflow if turn.decision else None)
        turn.messages = self._rehydrate_messages(buffer.turn_id, request)
        turn.gated = gated
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
        # keys on "an earlier `confirmation` span in the same turn".
        turn.buffer.add_span(
            "confirmation",
            str(gated.get("tool_name")),
            ConfirmationPayload(
                action=str(gated.get("tool_name")),
                arguments_preview=dict(gated.get("arguments") or {}),
                human_summary=f"Confirmed: {gated.get('tool_name')}",
                prompt_shown=f"Confirmed: {gated.get('tool_name')}",
                expires_at=now_micros() + CONFIRMATION_TTL_S * 1_000_000,
                user_response="confirmed",
                resolved_at=now_micros(),
            ),
        )
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
            self._absorb(turn, result)
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
    "Timings",
    "ToolCallRepair",
    "Usage",
    "get_orchestrator",
    "preview_value",
    "project",
    "render_answer",
    "resume_turn",
    "run_turn",
    "set_orchestrator",
    "summarise_span",
]
