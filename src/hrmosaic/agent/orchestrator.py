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
from hrmosaic.agent.guardrails import emit, g1, g2, g3, g4, g5, g6
from hrmosaic.agent.guardrails import span_name as guardrail_span_name
from hrmosaic.agent.router import (
    EMPLOYEE_ID,
    RouteDecision,
    allowed_tools,
    clamp_rationale,
    extract_amount,
    fallback_decision,
    is_monetary_approval,
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

#: The question a clarification opens with, keyed on the **first** unfilled slot (W8, C18) — and
#: since G5 (gap 4) every *other* unfilled slot is named after it, from `CLARIFY_ALSO`. Never the
#: slot list as the workflow documents it: `WorkflowSpec.required_slots` documents the completion
#: predicate for the dashboard, and reading that aloud was the defect jargon-and-exposure-4
#: recorded. Naming what is missing is a different thing from reciting a predicate.
#:
#: Keyed on the workflow, it asked the wrong question. The admin turn of 2026-09-15 was asked
#: *"which dates are you thinking of?"* by a message that had given the dates in full: what was
#: missing was an employee record, because `admin` has none. A question is only worth asking about
#: the slot that is actually empty.
#: Since W10 (ruling 9) the identity question also says **why** it is being asked. Scenario 08
#: served a persona with no employee record *"whose record should I look this up against?"* beside
#: a quick reply — *"Look it up for me"* — that persona could never use, and never said that the
#: session carries no record of its own.
CLARIFY_QUESTIONS: dict[str, str] = {
    "identity": (
        "This session is not signed in as an employee, so I have no record to read — "
        "whose record should I look this up against?"
    ),
    "start_date": "Happy to check — which dates are you thinking of?",
    "days": "Happy to check — how many days would that be?",
    "destination_country": "Happy to check — where would you be working from?",
    "duration_days": "Happy to check — how long would you be there?",
    "amount_usd": "Happy to check — how much is the claim for?",
    # The balance/identity ambiguity (G5, gap 4). `amb-003` — *"Can you check the balance for me?"* —
    # is routed `employee_data` with no workflow, so it fell all the way through to
    # `CLARIFY_FALLBACK`, which names nothing: the judge scored `named_missing_information` false and
    # clarification accuracy 1 of 3. Which balance is the missing detail, and it is the reader's own
    # record either way.
    "employee_data": (
        "Happy to check — which balance do you mean: your time off, or something else on your record? "
        "If it is not your own record, tell me whose."
    ),
}

#: How the **second and later** unfilled slots are named, after the question the first one asked
#: (G5, gap 4). `_clarification_text` asked about the first unfilled slot and stopped: `amb-002` —
#: *"Am I allowed to work from there for a while?"* — was asked only where, never for how long, and
#: the judge's `named_missing_information` verdict was false on a turn whose whole purpose was to
#: name what is missing. Fragments, not sentences: two questions in a row read as an interrogation,
#: and the router is told to name every missing detail for exactly this line to spend.
CLARIFY_ALSO: dict[str, str] = {
    "identity": "which employee record to read this against",
    "start_date": "the dates",
    "days": "how many days that would be",
    "destination_country": "where you would be working from",
    "duration_days": "how long you would be there, and from when",
    "amount_usd": "how much the claim is for",
    "employee_data": "which balance you mean",
}

#: What the one next step of a clarification says (W10, ruling 9). *"Reply with the missing detail
#: and I will pick this up"* never said **which** detail, on a turn whose whole purpose was to name
#: one. Keyed on the slot, like the question.
CLARIFY_NEXT_STEPS: dict[str, str] = {
    "identity": "Reply with the employee id and I will pick this up.",
    "start_date": "Reply with the dates and I will pick this up.",
    "days": "Reply with the number of days and I will pick this up.",
    "destination_country": "Reply with the destination and I will pick this up.",
    "duration_days": "Reply with how long you would be there and I will pick this up.",
    "amount_usd": "Reply with the amount and I will pick this up.",
    "employee_data": "Reply with which balance you mean and I will pick this up.",
}

#: The fallback, for a clarification the router could not attach to a slot.
CLARIFY_FALLBACK_STEP = "Reply with the missing detail and I will pick this up."

#: Words the router's own `needs_clarification` rationale uses for each slot (W10, ruling 9).
#: Scenario 12 — *"Can I take leave?"* — carried no workflow, so the question fell all the way back
#: to *"could you tell me a little more about what you are after?"*, which names nothing; the
#: router's rationale had already said what was missing. Read as **data**, never as an instruction:
#: the only thing taken from it is which of six closed slots it mentions.
RATIONALE_SLOT_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("identity", ("employee id", "employee record", "which employee", "whose record", "identity", "persona")),
    ("start_date", ("date", "dates", "when", "start")),
    ("days", ("how many days", "day count", "number of days", "duration of the leave", "length")),
    ("destination_country", ("country", "destination", "where", "location")),
    ("duration_days", ("how long", "weeks", "duration")),
    ("amount_usd", ("amount", "how much", "cost", "spend")),
)

#: Which slots a workflow asks about when it holds none of them, in the order a person would be
#: asked in — not the order `required_slots` documents. Every one of them that is still empty is
#: named (G5, gap 4); the first one is the one the question is built from.
CLARIFY_SLOT_ORDER: dict[str, tuple[str, ...]] = {
    "pto_request": ("identity", "start_date", "days"),
    "remote_work_eligibility": ("identity", "destination_country", "duration_days"),
    "expense_claim": ("identity", "amount_usd"),
}

#: …and which slots a turn the router attached to **no** workflow asks about, keyed on its intent
#: (G5, gap 4). `amb-003` is an `employee_data` turn with no workflow and no slot order at all, so
#: the one thing it could ask was the fallback that names nothing.
CLARIFY_INTENT_ORDER: dict[str, tuple[str, ...]] = {
    "employee_data": ("identity", "employee_data"),
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
    "employee_data": (
        "My time off balance",
        "My benefits",
    ),
}

#: The fallback pair, for a clarification the router could not attach to a workflow.
CLARIFY_FALLBACK_CHIPS: tuple[str, ...] = (
    "It is about my time off",
    "It is about working somewhere else",
)


#: A quick reply only a persona **with** a record can act on (W10, ruling 9). *"Look it up for me"*
#: was offered to the one persona the product had nothing to look up for.
NEEDS_A_RECORD: tuple[str, ...] = ("Look it up for me",)


def clarify_chips(slot: str | None, *, has_record: bool = True) -> tuple[str, ...]:
    """The quick replies for a clarification, by the slot it asks about. Shared with the replay path.

    Filtered by whether this session has a record of its own (W10, ruling 9): a chip that asks the
    product to look something up is a dead end for a persona whose record it does not have, and
    scenario 08 offered exactly that on the one turn where the missing slot **was** the record.
    """
    chips = CLARIFY_CHIPS.get(slot or "", CLARIFY_FALLBACK_CHIPS)
    if has_record:
        return chips
    return tuple(chip for chip in chips if chip not in NEEDS_A_RECORD)


def rationale_slot(rationale: str) -> str | None:
    """Which of the six slots the router's `needs_clarification` line names, or `None`.

    The router is told to name **every** missing detail in `rationale_summary` because the question
    the user is shown is built from it; until W10 nothing read it, so a turn the router could not
    attach to a workflow was asked *"could you tell me a little more about what you are after?"*
    The rationale is model prose and is read as data: the only thing taken from it is which closed
    slot name it mentions first, in the order a person would be asked.
    """
    lowered = rationale.lower()
    return next((slot for slot, words in RATIONALE_SLOT_WORDS if any(word in lowered for word in words)), None)


def clarify_slot_of(question: str) -> str | None:
    """Which slot a stored clarifying question was asking about (W8, C18).

    `turns` stores the question the reader was shown but not the slot it came from, and the replay
    path has to offer the same two quick replies the live turn did. The questions are a closed set,
    so the reverse lookup is exact — and it is the *stored text* that decides, not the workflow,
    which is the whole point of keying on the slot.

    Since G5 (gap 4) the stored question can name more than one missing slot, so the match is on the
    **opening** question: that is the slot the chips and the next step were keyed on live, and none
    of the closed set is a prefix of another.
    """
    text = question.strip()
    return next((slot for slot, ask in CLARIFY_QUESTIONS.items() if text.startswith(ask)), None)


def unfilled_slots(
    workflow: str | None,
    *,
    known: Collection[str],
    has_record: bool,
    intent: str | None = None,
) -> tuple[str, ...]:
    """Every slot this turn still needs, in the order a person would be asked for them (G5, gap 4).

    `known` is what `agent/session.py` carried forward from the last three turns, so a follow-up is
    never asked for a detail the session settled — the other half of C12's defect, and the reason
    C18 keys on the slot rather than on the workflow.

    A turn the router attached to no workflow falls back to `CLARIFY_INTENT_ORDER`, which is how an
    `employee_data` turn with no workflow — `amb-003` — gets a question about its own missing detail
    instead of the fallback that names nothing.
    """
    order = CLARIFY_SLOT_ORDER.get(workflow or "") or CLARIFY_INTENT_ORDER.get(intent or "", ())
    return tuple(slot for slot in order if ((not has_record) if slot == "identity" else slot not in known))


def unfilled_slot(workflow: str | None, *, known: Collection[str], has_record: bool) -> str | None:
    """The first slot this turn still needs, or `None` when the session already holds them all."""
    return next(iter(unfilled_slots(workflow, known=known, has_record=has_record)), None)


def clarification_question(slots: Sequence[str]) -> str:
    """The question a clarification opens with, naming **every** slot it is still missing (G5, gap 4).

    The first slot asks the question; the rest are named after it as fragments. Two full questions in
    a row read as an interrogation, and `amb-002`'s defect was not the wording of the first question
    but that the second slot was never mentioned at all.
    """
    if not slots:
        return CLARIFY_FALLBACK
    first, rest = slots[0], [CLARIFY_ALSO[slot] for slot in slots[1:] if slot in CLARIFY_ALSO]
    question = CLARIFY_QUESTIONS.get(first, CLARIFY_FALLBACK)
    if not rest:
        return question
    also = rest[0] if len(rest) == 1 else f"{', '.join(rest[:-1])} and {rest[-1]}"
    return f"{question} I will also need to know {also}."


#: What the product will not do, said first and in its own voice (W8, C20, C17). It names the act
#: and then the rule, in `corpus/manager-approval-matrix.md`'s own words, so a reader is told what
#: happens instead rather than only what does not.
UNSAFE_REFUSAL = (
    "I will not approve a request for you, record an approval somebody else has to give, or route "
    "a request around its approval chain. Nobody approves their own request, and nobody approves a "
    "request from a person who approves theirs; where that would happen, MosaicOne routes the "
    "request one level higher automatically."
)

#: Where `UNSAFE_REFUSAL`'s second sentence comes from (W10, ruling 10, scenario 14). The refusal
#: quotes `corpus/manager-approval-matrix.md` and carried no citation at all, so the one policy
#: sentence on the page was unreachable from it. Resolved through the committed index at call time
#: — a chunk id is a content hash and can never be written here — and `_finish` fails closed on a
#: stale one exactly as it does on the model's.
UNSAFE_DOC_ID = "manager-approval-matrix"
UNSAFE_HEADING = "How to Read This Matrix"


def matrix_citation() -> list[str]:
    """The chunk that carries the no-self-approval sentence, or `[]` when nothing resolves."""
    matches = [chunk for chunk in corpusread.list_chunks(UNSAFE_DOC_ID) if chunk.heading_path == UNSAFE_HEADING]
    return [min(matches, key=lambda chunk: chunk.char_start).chunk_id] if matches else []


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
    "Not yet — this turn is about one person's own HR record and the state does not carry all of "
    "it. Read the record this question is about before you answer it."
)

#: Ruling 1 of the same addendum: an answered turn whose blocks carry none of these is not an
#: answer. `oos-005` — the referral bonus — was routed `policy_qa` beside the annual bonus plan,
#: G1 allowed the annual-bonus passages, and the synthesis emitted one escalation saying the
#: evidence does not cover the question; the turn closed `answered`. It closes `refused`, with
#: G1's copy and a G1 verdict of `refuse` under this reason.
NO_SUPPORTED_CLAIMS = "no_supported_claims"
SUBSTANTIVE_BLOCKS = ("policy_fact", "record", "performed")

#: The shape ruling 1 is actually about (W10 addendum): an answer that says, in so many words, that
#: the corpus does not reach the question. Without this the refusal fired on every answer whose
#: policy facts G2 could not resolve — a citation defect answered by G2's own cascade, not by
#: throwing the answer away.
NO_EVIDENCE_PHRASES: tuple[str, ...] = (
    "does not cover",
    "do not cover",
    "is not addressed",
    "are not addressed",
    "not addressed in",
    "does not address",
    "no information",
    "not covered",
    "could not find",
    "does not contain",
    "do not contain",
    "not available in",
)

#: The keys a deterministic step carries on a block and no reader ever sees.
BLOCK_MARKERS: tuple[str, ...] = (outcome_consistency.POLICY_CLAIM, outcome_consistency.BLOCK_ID)
PROFILE_TOOL = "lookup_employee_profile"
PROFILE_FIRST_TOOLS = ("check_policy_compliance", "check_pto_balance")

#: The structured-data tools an `employee_data` turn reads its record through (§8.4 tools 5–7).
#: An `employee_data` turn has no workflow to list them, so the data debt reads this instead.
RECORD_TOOLS: tuple[str, ...] = ("lookup_employee_profile", "check_pto_balance", "lookup_benefits_status")

#: The slot families a delta follow-up may change one member of (W8 fix round, W7-review I5).
#: When the model supplies any member, none of the others is inherited from the session: "five
#: days instead" with the first turn's `end_date` carried over would be two different requests.
SLOT_FAMILIES: tuple[frozenset[str], ...] = (frozenset({"days", "end_date", "duration_days"}),)

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

#: …and the third form, for the turn the W10 fix round reaches: it has searched more than once and
#: its evidence still spans fewer documents than the answer will be judged on. It needs its own
#: opening clause for the same reason the other two do — telling a turn that has searched twice
#: that it "has not searched the corpus yet" is a false statement about its own history, in the one
#: message whose whole purpose is to correct that picture. No count of anything: the ledger's rule
#: is the debt, never the tool and never how many documents.
SEARCH_BREADTH_REPEATED = (
    f"Not yet — you have searched more than once and your evidence still comes from fewer "
    f"documents than the question spans. {_BREADTH_DEBT}"
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

    **`arguments` travels as JSON text** (W10, ruling 12). It was `dict[str, Any]`, which pydantic
    renders as `{"type": "object", "additionalProperties": true}` — a level strict mode rejects, and
    a level `_assert_strict` walked straight past because it carries no `properties` of its own. So
    every repair call the pinned provider was offered came back **400**: the one round trip §9.1
    mandates could not be made at all, the turn spent the budget on a call that produced nothing,
    and scenario 15 closed `partial` under "I reached my step limit" over a complete answer. A tool
    argument map is open by construction — it is a different shape per tool — so the only strict
    form is a string, parsed here.
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments_json: str
    rationale_summary: str

    @property
    def arguments(self) -> dict[str, Any]:
        """The repaired arguments, or `{}` when the model sent something that is not an object."""
        try:
            parsed = json.loads(self.arguments_json or "{}")
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


# --------------------------------------------------------------------------------------
# The `/chat` request and response shapes (§11.1)
# --------------------------------------------------------------------------------------


class ChatOptions(BaseModel):
    """§11.1's `options`. Everything except `k` is privileged; `web/` enforces that, not this.

    `tools_disabled` defaults to `MCP_TOOLS_DISABLED`, the process-wide form of the same filter
    (§12.3), read at construction so the environment a process boots with is what an unstated
    request gets — exactly as `RETRIEVAL_K` and `RETRIEVAL_STRATEGY` back `k` and
    `retrieval_strategy` inside `rag.retrieve`. A request that states the field wins, including
    when it states the empty list: that is the per-turn channel §13.9's ablation drives, and it
    must be able to ask for the full catalogue on a process that withholds tools by default.
    """

    model_config = ConfigDict(extra="forbid")

    k: int | None = Field(default=None, ge=1, le=10)
    retrieval_strategy: Literal["hybrid_rrf", "dense_only"] | None = None
    tools_disabled: list[str] = Field(default_factory=lambda: list(default_settings.mcp_tools_disabled_list))
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
    #: The slots this turn starts from without asking: the last three turns' resolved parameters
    #: and the amount the question itself carries (W8 fix round, W7-review I2 and I5). A compliance
    #: call that omits one of them inherits it — deterministically, not by the model's grace.
    resolved_slots: dict[str, Any] = field(default_factory=dict)
    #: Which slots were inherited into which call, for the record.
    inherited: list[str] = field(default_factory=list)

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
        # What the turn already holds: the session's resolved slots, and the amount in the question.
        turn.resolved_slots = session.inherited_slots(turn.history)
        if is_monetary_approval(req.message) and (amount := extract_amount(req.message)) is not None:
            turn.resolved_slots["amount_usd"] = amount

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

        # -- 2a. the profile debt, before anything can end the turn (W10 fix round) -------------
        # `unsafe-001` proposed its card inside the act loop and ended `awaiting_confirmation`
        # without ever reaching `_answer`, which is the only place the debt used to be settled — so
        # the turn described a person it had never read, at tool recall 0.75. One `tools/call`, no
        # model step, on every path out of the loop.
        try:
            await self._settle_profile_debt(turn)
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

        # -- 2b. the data debt (W8, C10; widened in the fix round) — before the gate ---------
        # A turn that has not read the record it is about is not ready to be gated: the profile
        # or balance it still owes may be the evidence, and the compliance verdict it still owes
        # is scored deterministically for an `expense_claim` that reached this point without one.
        parked = await self._settle_data_debt(turn, cold_start=cold_start)
        if parked is not None:
            return parked

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

        # -- 3b. the action debt (W8, C09) -------------------------------------------------
        # `_nudge` reports it on the step where the model stops calling tools. It cannot report it
        # on the step where the model stops for some other reason — a budget, a completion
        # predicate it satisfied another way — and on 9 of 12 recorded runs of `unsafe-001` the
        # turn reached synthesis with the write it was asked to propose still unmade, and answered
        # *"I cannot submit PTO requests in MosaicOne on your behalf"*. So the debt is terminal:
        # one more act step with the reminder, and then the orchestrator settles it itself.
        parked = await self._settle_action_debt(turn, cold_start=cold_start)
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
        # **…and every block carries its own identity** (W10 addendum). The citation carry below
        # used to re-home a lost citation to the *nearest surviving policy fact*, scaled by
        # position — which puts one claim's evidence under another claim's sentence as soon as a
        # step removes a block. A marker set here travels through every step's `dict(block)` copy,
        # so the carry can say "this block, or nowhere". Stripped before the answer is validated.
        claimed = set(relabelled.relabelled)
        marked = [
            {
                **block,
                outcome_consistency.BLOCK_ID: index,
                **({outcome_consistency.POLICY_CLAIM: True} if index in claimed else {}),
            }
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
            # What this **session** already filed, **when this turn is about it** (W10, ruling 7;
            # fix round, Important 2). A directive to file a request an earlier turn filed becomes
            # "amend <id>" rather than a second ticket for one absence — but only where the two are
            # the same request, by workflow or by subject slot. A session that filed a PTO ticket
            # and then asked about a conduct escalation had *"Open a case with People Operations"*
            # rewritten into an amendment of the ticket.
            prior_write=self._prior_write(turn),
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

        # -- 5l. the ledes the product says in its own voice, all of them, in their final order ---
        # Assembled here rather than one `model_copy` at a time (W10 addendum) so that the two
        # steps below — the de-duplication and the citation carry — see the answer a reader sees.
        # Reading order, top first: the budget note, the failed write, the refused write, the
        # cancelled card, then the answer the turn earned.
        stopped = turn.stop_reason in BUDGET_STOPS
        if stopped:
            # §9.4: **every** budget stop writes an `error` span naming the reason, whether or not
            # the answer came out whole (W10 fix round, Minor). Narrowing the lede had narrowed
            # this with it, so a turn that really did stop at `max_steps` closed with nothing but a
            # `stop_reason` to show for it.
            self._error(
                turn,
                turn.stop_reason,
                f"the turn stopped at its {turn.stop_reason} budget",
                component="agent_loop",
            )
        # …and the **lede** only where the answer is actually short (W10, ruling 12): scenario 15
        # carried a complete four-block answer under "I reached my step limit for this turn",
        # because the repair leg 400'd on its own schema and spent the budget without losing
        # anything.
        budget_limited = stopped and not self._complete(turn, snapshotted.blocks)
        ledes: list[dict[str, Any]] = []
        if budget_limited:
            ledes.append({"type": NOTICE, "text": BUDGET_NOTE[turn.stop_reason], "citations": []})
        if turn.write_failed:
            # §9.4's graceful partial for the other way a turn falls short of what it was asked to
            # do: the action was authorised and did not happen.
            ledes.append({"type": NOTICE, "text": WRITE_FAILED_NOTE, "citations": []})
        if turn.write_blocked:
            # **The reader is told why, in the product's own voice** (W8, C02, C17), because the
            # answer below is about a request that was not filed.
            ledes.append({"type": NOTICE, "text": turn.write_blocked, "citations": []})
        if turn.declined:
            # The receipt for what the reader decided (W8, C11, C17); the answer they already
            # earned follows it.
            ledes.append({"type": NOTICE, "text": CANCELLED_NOTICE, "citations": []})
        verdict_lede = self._verdict_lede(turn)
        if verdict_lede is not None:
            # **A refusal leads** (W10, ruling 14, scenario 02). E1108 was told, correctly, that he
            # does not have the twelve months of service an international stay needs — in the
            # *fourth* block, after three paragraphs that read as though the trip were on. The
            # answer to "can I?" is the first thing on the page, and where the engine derived the
            # day he becomes eligible, it is in the same breath.
            ledes.append({"type": outcome_consistency.RECORD, "text": verdict_lede, "citations": []})

        # One sentence, once per turn (UX W9, CPUX4-02): the refusal's lede and the record block
        # had each written the failing row's clause. **Before the citation carry** (W10 addendum):
        # it can drop a whole block, and a block dropped after the carry takes the carried
        # citations with it — so a duplicate's citations are unioned onto the block that kept the
        # sentence and the carry then runs over what is actually served.
        deduped, repeated = outcome_consistency.dedupe_sentences([*ledes, *snapshotted.blocks])

        # -- 5m. the repair's citations survive the steps (W9 addendum, ruling 2) ---------------
        # A step that took a sentence or a block took its citations with it, and `remote-002` was
        # served two documents of the three the breadth repair had produced. A citation the
        # post-breadth blocks carried and the served blocks do not goes back **on its own block**
        # (W10 addendum): a citation is evidence for one claim, and re-homing it to the nearest
        # surviving policy fact attached it to a different one.
        served, _carried = breadth.carry_citations(marked, deduped)

        # -- 5n. an answer with no supported claim is not an answer (W9 addendum, ruling 1) -----
        if self._unsupported(turn, served, had_policy_fact=bool(claimed) or self._cited_facts(marked)):
            emit(
                turn.buffer,
                "G1",
                verdict="refuse",
                reason=f"{NO_SUPPORTED_CLAIMS}: the answer carried no policy fact, record or performed block",
                details={"block_types": [str(block.get("type")) for block in served]},
            )
            return self._refuse(turn, NO_SUPPORTED_CLAIMS, cold_start=cold_start)

        answer = AnswerSchema(
            blocks=[
                AnswerBlock.model_validate({k: v for k, v in block.items() if k not in BLOCK_MARKERS})
                for block in served
            ],
            next_steps=entailed.next_steps,
            rationale_summary=clamp_rationale(str(raw.get("rationale_summary") or "")),
        )
        if repeated:
            self._error(
                turn,
                "repeated_sentence",
                "; ".join(f"{sentence!r} was already said" for _index, sentence in repeated),
                component=outcome_consistency.STEP_NAME,
            )
        outcome: TurnOutcome = "partial" if budget_limited or turn.write_failed else "answered"
        return self._finish(
            turn,
            answer,
            outcome=outcome,
            stop_reason=turn.stop_reason,
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
        """The router call of §9.2 — and the catalog it selects tools from (G5, gap 17).

        `selected_tools` is described in `system` as chosen "from the offered catalog", and until
        G5 the catalog never entered the prompt: the router call carries no `tools` array, because
        it answers with JSON and calls nothing. The model therefore emitted category labels —
        `["employee_data", "pto_request_write"]` — `normalise` dropped every one of them as unknown,
        and 183 of 183 recorded real-model router spans wrote `selected_tools: []` while
        `_requested_write` read that empty list. The names go in the `user` half, so the cached
        `tools → system` prefix does not move.
        """
        req = turn.request
        system, user = prompts.render(
            "route.j2",
            persona=prompts.persona_block(employee_id=req.employee_id, actor_source=req.actor_source),
            question=req.message,
            session_context=session.render(turn.history),
            catalog_names=turn.catalog.names if turn.catalog is not None else (),
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
                call = self._inherit_slots(turn, call)
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

    async def _settle_data_debt(self, turn: _Turn, *, cold_start: bool) -> ChatResponse | None:
        """The data debt of §9.1, settled before the evidence gate. A parked turn, or `None`.

        **W8, C10 — widened in the fix round (W7-review I7).** A turn about one person's own record
        that has not read it: a workflow turn with any reachable structured slot still empty, or an
        `employee_data` turn with no record tool called at all — which is the class's own exhibit,
        *"Which office am I assigned to?"*, declined outright with the profile never read. One act
        step with the reminder. Then, for an `expense_claim` still without a verdict, the engine is
        asked directly with the amount the question carried (W7-review I2): the threshold is the
        engine's to apply, and the answer may not say who approves until it has.
        """
        # A turn already outside its budget keeps the partial the stop exists to produce (§9.4),
        # exactly as the breadth step does: no model re-entry on its account. The **profile** read
        # at the foot of this method is not one of those — it is one `tools/call` the orchestrator
        # makes itself, and it answers to `agent_max_tool_calls` and to nothing else.
        spent = turn.stop_reason in BUDGET_STOPS or turn.elapsed_s >= self.settings.agent_wall_clock_s
        if (
            not spent
            and self._data_outstanding(turn)
            and "data_outstanding" not in turn.nudges
            and turn.steps_taken < self.settings.agent_max_steps
        ):
            turn.nudges.append("data_outstanding")
            turn.messages.append(Message(role="user", content=DATA_OUTSTANDING))
            turn.step_summaries.append(f"step {turn.steps_taken}: the reader's own record was still unread")
            try:
                await self._run_act(turn)
            except McpUnavailable as exc:
                return self._degraded(turn, str(exc), cold_start=cold_start)
            if turn.pending is not None:
                return self._park(turn, cold_start=cold_start)
        if not spent and self._verdict_outstanding(turn):
            turn.nudges.append("compliance_scored_deterministically")
            try:
                await self._score_deterministically(turn)
            except McpUnavailable as exc:
                return self._degraded(turn, str(exc), cold_start=cold_start)
            self._plan(turn, step_index=turn.steps_taken)
        # **The profile debt, last and unconditionally** (W10 addendum, Minor; fix round). Last,
        # because `_score_deterministically` above may have just minted the very verdict that
        # creates the debt; unconditionally, because a budget stop is about model steps and this is
        # one tool call the orchestrator makes itself.
        try:
            await self._settle_profile_debt(turn)
        except McpUnavailable as exc:
            return self._degraded(turn, str(exc), cold_start=cold_start)
        return None

    async def _settle_action_debt(self, turn: _Turn, *, cold_start: bool) -> ChatResponse | None:
        """The action debt of §9.1, settled after the gate. A parked turn, or `None`.

        **W8, C09.** `intent == "action"`, a permitted write tool, and no gated attempt. `_nudge`
        already reports this on the step the model stops calling tools; nine of twelve recorded
        runs of `unsafe-001` reached synthesis another way and denied the product's headline
        capability instead. One more act step with the reminder, and if the model still will not
        propose it, the orchestrator proposes it — from the slots the turn itself resolved, so the
        card is the turn's own state and not an invention.
        """
        if not self._action_outstanding(turn) or not any(name in self._permitted(turn) for name in WRITE_TOOLS):
            return None
        if turn.stop_reason in BUDGET_STOPS or turn.elapsed_s >= self.settings.agent_wall_clock_s:
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
        """A turn about one person's own record that has not read all of it, and still could.

        Two shapes (W8 fix round, W7-review I7). A **workflow** turn with any reachable required
        structured slot still empty — reading the balance but not the profile is the same debt as
        reading neither. And an **`employee_data`** turn, which has no workflow to list its slots:
        outstanding while no record tool it could call has produced anything.
        """
        if turn.pending is not None or turn.decision is None:
            return False
        if turn.declined or turn.write_failed:
            return False
        # A resumed write is a turn whose reading moment has passed: the human answered a card
        # built on what the turn had read, and re-entering the loop behind that answer would put a
        # second act step between the confirmation and the answer. The profile debt (W9 addendum,
        # ruling 3) is owed there too, and `_settle_data_debt` settles it without a model step.
        if any(name in turn.state.results for name in WRITE_TOOLS):
            return False
        # The **profile** shape is no longer one of these (W10 fix round): it is settled by
        # `_settle_profile_debt`, deterministically, on every path out of the act loop — a model
        # reminder could not reach it on a `policy_qa` turn, where §9.2's gate does not offer the
        # tool, which is exactly how `remote-003` kept scoring 0.67.
        permitted = self._permitted(turn)
        workflow = turn.workflow
        if workflow is not None:
            # `workflow_incomplete` IS this reminder for a workflow turn — the same debt in the
            # same words — and the model has already been told once. A second act step for it
            # would be the reminder twice; the verdict, where it is the debt, is scored below.
            if "workflow_incomplete" in turn.nudges:
                return False
            return any(name in permitted for name in workflow.missing_tool_results(turn.state))
        if turn.decision.intent != "employee_data":
            return False
        reachable = [name for name in RECORD_TOOLS if name in permitted]
        return bool(reachable) and not any(turn.state.has(name) for name in reachable)

    def _unsupported(self, turn: _Turn, blocks: Sequence[Mapping[str, Any]], *, had_policy_fact: bool = False) -> bool:
        """No policy fact, no record, no performed write — only an escalation or advice saying the
        evidence does not cover the question (W9 addendum, ruling 1).

        **Four conditions, not one** (W10 addendum). The first version asked only whether a
        substantive block survived, which refuses two turns it was never aimed at: a turn stopped
        at a §9.4 budget, whose graceful partial is what the budget is *for*, and a turn whose
        policy facts G2 could not resolve — a citation defect, answered by G2's own cascade and by
        the breadth shortfall, not by throwing the answer away. So the refusal needs all of:

        1. the turn did not stop at a budget;
        2. no `policy_fact` existed **before** G3 relabelled the uncited ones — `had_policy_fact`
           is that history, which the served blocks no longer carry;
        3. no `record` and no `performed` block survived;
        4. something in the answer says the evidence does not cover the question — `oos-005`'s
           shape, and the one this rule was written for.

        A declined, blocked or failed write is answered by its own notice and is not this shape.
        """
        if turn.declined or turn.write_blocked or turn.write_failed:
            return False
        if turn.stop_reason in BUDGET_STOPS or had_policy_fact:
            return False
        if any(block.get("type") in SUBSTANTIVE_BLOCKS for block in blocks):
            return False
        return any(phrase in str(block.get("text") or "").lower() for block in blocks for phrase in NO_EVIDENCE_PHRASES)

    def _verdict_lede(self, turn: _Turn) -> str | None:
        """The one sentence a refused request opens with, or `None` (W10, ruling 14, scenario 02).

        Only on a `non_compliant` verdict the turn is not already leading with — a blocked write
        says it in its own notice, and a performed one is not a refusal at all. The failing row is
        the engine's, in the reader's voice, and `computed.tenure_eligible_on` — the day a tenure
        requirement starts being met — follows it where the engine derived one, because that is the
        half of "can I?" the answer kept leaving out.
        """
        if turn.write_blocked or turn.declined or any(name in turn.state.results for name in WRITE_TOOLS):
            return None
        body = turn.state.latest(COMPLIANCE_TOOL)
        if not body or body.get("verdict") != "non_compliant":
            return None
        envelope = _ToolEnvelope(name=COMPLIANCE_TOOL, result_json=json.dumps(body, ensure_ascii=False))
        failing = next((row for row in compliance_restatement.rows([envelope]) if row.status == "unmet"), None)
        if failing is None:
            return None
        sentence = compliance_restatement.reader_sentence(failing)
        eligible = (body.get("computed") or {}).get("tenure_eligible_on")
        if isinstance(eligible, str) and ISO_DATE.fullmatch(eligible):
            human = date_consistency.human_date(date.fromisoformat(eligible))
            sentence = f"{sentence} You meet that requirement on {human}."
        return sentence

    def _prior_write(self, turn: _Turn) -> session.Write | None:
        """The write an earlier turn of this session made **about this request**, or `None`."""
        write = session.performed_write(turn.history)
        workflow = turn.workflow.name if turn.workflow is not None else None
        return write if session.relates_to(write, workflow=workflow, slots=turn.resolved_slots) else None

    @staticmethod
    def _cited_facts(blocks: Sequence[Mapping[str, Any]]) -> bool:
        """Did the model's own answer carry a cited `policy_fact` before the steps ran?"""
        return any(block.get("type") == "policy_fact" and (block.get("citations") or []) for block in blocks)

    def _complete(self, turn: _Turn, blocks: Sequence[Mapping[str, Any]]) -> bool:
        """Is this answer whole, whatever the budget did? (W10, ruling 12)

        The budget lede says *"here is what I established before stopping"*, and scenario 15 said
        it over a complete four-block answer with its verdict, its approver and its citations —
        the budget went on a repair call the provider rejected for the repair schema's own
        `additionalProperties`, and nothing about the answer was short. An answer is complete when
        the **workflow's** completion predicate holds and a substantive block survived. A turn with
        no workflow has no predicate to ask, so it keeps §9.4's graceful partial exactly as before:
        the ruling narrows the lede to the case where something can say the answer is whole, and
        never widens it into a guess.
        """
        workflow = turn.workflow
        if workflow is None or not workflow.is_complete(turn.state):
            return False
        return any(block.get("type") in SUBSTANTIVE_BLOCKS for block in blocks)

    def _served(self, turn: _Turn, answer: AnswerSchema) -> tuple[AnswerSchema, list[Citation]]:
        """`(the answer as it is served, the citations it actually carries)` — fail closed (W10).

        Two defects, one rule (ruling 10; W10 addendum, Critical):

        * `_finish` used to be handed G2's citations, taken at step 5b — before nine deterministic
          steps that merge blocks, drop sentences, re-home a citation and add cited facts of their
          own. So `/chat`, the turn record and the chat page published a set the blocks beside them
          did not have, and `min_distinct_docs` was scored on the wrong one.
        * a **dangling** block citation reached the reader on every path that did not go through
          step 5b at all: scenario 11's escalation cited `c_d5386f2efd5183f6` under a top-level
          `citations: []`, so the one source the answer named was unreachable from the page.

        So G2's own pure cascade runs once more over the blocks that are actually served — no
        `guardrail` span, because the verdict on this answer is already recorded and this is the
        same rule asked at the send boundary. An id the index will not resolve is stripped and a
        `policy_fact` that loses all of its citations goes with it: a policy sentence with no
        citation is not served.
        """
        outcome = g2.apply(
            [block.model_dump() for block in answer.blocks],
            evidence=turn.evidence,
            quarantined=turn.quarantined,
        )
        if not outcome.repaired and outcome.dropped_blocks == 0:
            return answer, outcome.citations
        if outcome.stripped or outcome.dropped_blocks:
            # **Failing closed leaves a trace** (W10 fix round, Minor). This is the one place the
            # product drops a citation the reader was about to be shown, and it was the one place
            # that left no record at all — no `error` span, nothing on the waterfall. An `error`
            # rather than a second `guardrail` verdict: the tiles and `blocks_dropped_by_g2` sum
            # every G2 span of the turn, and a second verdict here would double-count them.
            self._error(
                turn,
                "citation_unresolvable_at_send",
                "; ".join(f"{resolution.chunk_id}: {resolution.reason}" for resolution in outcome.stripped)
                or f"{outcome.dropped_blocks} block(s) lost every citation",
                component="g2",
            )
        if not outcome.blocks:
            # Failing closed must not mean failing silent: an answer the cascade emptied keeps its
            # sentences with every citation stripped, so the reader is given the prose without a
            # source rather than a blank page. `_unsupported` above is what refuses this shape when
            # it is a refusal; this is the backstop for the one that is not.
            # Only `policy_fact` blocks are ever dropped here, so an emptied answer was all policy
            # facts — and an uncited policy claim is a `recommendation`, which is exactly what G3
            # would have made of it.
            return (
                answer.model_copy(
                    update={
                        "blocks": [
                            block.model_copy(update={"type": "recommendation", "citations": []})
                            for block in answer.blocks
                        ]
                    }
                ),
                [],
            )
        return (
            answer.model_copy(update={"blocks": [AnswerBlock.model_validate(block) for block in outcome.blocks]}),
            outcome.citations,
        )

    def _profile_outstanding(self, turn: _Turn) -> bool:
        """A verdict or a balance computed **for the acting employee** with the profile never read.

        The `employee_id` test is on the call's **arguments**, not merely on the tool name (W10
        addendum, Minor): a turn that scored somebody else's request — an approver checking a
        report's claim — owes nothing about the reader's own profile, and reading it would spend a
        tool call on a record the answer is not about.

        Arguments, not the result body, since G5 (gap 11). A body echoes its input only if the tool's
        output model says so: `check_pto_balance` carries `employee_id` and `check_policy_compliance`
        does not — `ComplianceOutput` declares no such field and `_compliance` round-trips through it,
        so an extra key would be dropped. The one turn this repair was written for, `remote-003`, is a
        `policy_qa`-routed eligibility question whose only profile-first tool **is** the compliance
        engine: the debt could never fire, the profile was never read, and the published run scored it
        tool recall 0.67 with workflow completion 0. Every call records what it was asked; that is the
        question being asked here.

        **§9.2's router gate is deliberately not consulted** (W10 fix round, the live evaluation).
        That gate exists to stop the *model* wandering into people data on a corpus-only question,
        and `remote-003` is routed `policy_qa` — so the reminder could not ask for the profile and
        the debt was never settled, at tool recall 0.67. The call below is the **orchestrator's**,
        not the model's, and the turn has already put this employee's record in play by scoring a
        verdict or a balance for them. The only budget it answers to is `agent_max_tool_calls`.
        """
        actor = turn.request.employee_id or ""
        return (
            not turn.state.has(PROFILE_TOOL)
            and any(turn.state.called_with(name, "employee_id", actor) for name in PROFILE_FIRST_TOOLS)
            and turn.tool_calls_made < self.settings.agent_max_tool_calls
            and bool(actor and EMPLOYEE_ID.match(actor))
        )

    async def _settle_profile_debt(self, turn: _Turn) -> None:
        """Read the profile the turn owes, whatever else is happening (W10 fix round).

        Called on **every** path that ends a turn's tool work: before the evidence gate, and before
        a proposed write parks the turn at its confirmation card. `unsafe-001` proposed its card and
        ended `awaiting_confirmation` without ever reaching `_answer`, so the profile debt — which
        only `_settle_data_debt` settled — was never even asked about, and the item scored tool
        recall 0.75 on an answer that described a person it had not read. No model re-entry, no act
        step, no dependence on a remaining one: one `tools/call`, inside the tool budget.
        """
        if not self._profile_outstanding(turn):
            return
        turn.nudges.append("profile_read_deterministically")
        await self._read_profile_deterministically(turn)
        self._plan(turn, step_index=turn.steps_taken)

    async def _read_profile_deterministically(self, turn: _Turn) -> None:
        """Read the acting employee's profile the turn computed a verdict or a balance without
        (W9 addendum, ruling 3). The result enters state and the envelopes as a model-made call's
        would, so the answer steps and the tool-recall metric read it the same way."""
        result = await self._call(turn, PROFILE_TOOL, {"employee_id": turn.request.employee_id})
        turn.tool_calls_made += 1
        if not result.is_error:
            self._scan(turn, await self._absorb_async(turn, result))
            turn.step_summaries.append("the assistant read the profile the verdict or balance was computed without")

    def _verdict_outstanding(self, turn: _Turn) -> bool:
        """An `expense_claim` at synthesis with no verdict on an amount the turn knows (W7-review I2)."""
        workflow = turn.workflow
        return (
            workflow is not None
            and workflow.name == "expense_claim"
            and not turn.state.has(COMPLIANCE_TOOL)
            and turn.resolved_slots.get("amount_usd") is not None
            and COMPLIANCE_TOOL in self._permitted(turn)
            and turn.tool_calls_made < self.settings.agent_max_tool_calls
            and bool(turn.request.employee_id and EMPLOYEE_ID.match(turn.request.employee_id))
        )

    async def _score_deterministically(self, turn: _Turn) -> None:
        """Ask the engine for the verdict the turn reached synthesis without (W7-review I2).

        Only the amount the question carried and the scenario the workflow names: the orchestrator
        supplies what the turn already holds, never a value the model would have had to decide.
        The result enters state and the envelopes exactly as a model-made call's would, so the
        answer steps read it the same way.
        """
        arguments = {
            "scenario": "expense_claim",
            "employee_id": turn.request.employee_id,
            "parameters": {"amount_usd": turn.resolved_slots["amount_usd"]},
        }
        result = await self._call(turn, COMPLIANCE_TOOL, arguments)
        turn.tool_calls_made += 1
        if not result.is_error:
            self._scan(turn, await self._absorb_async(turn, result))
            turn.step_summaries.append("the assistant scored the claim amount the question carried")

    def _inherit_slots(self, turn: _Turn, call: ToolCall) -> ToolCall:
        """Fill the compliance parameters the model omitted from what the turn already holds.

        **Deterministic slot inheritance** (W8 fix round, W7-review I2 and I5). "What if I extend
        it to five days instead?" is a delta of the previous turn, and the previous turn's
        `start_date` is a fact the session holds — the prompt tells the model so, and this is what
        makes it true when the model leaves the slot empty anyway. Only keys the call lacks are
        filled, never one the model supplied; and a slot family the model changed one member of
        (`days` / `end_date` / `duration_days`) is not completed from the session, because five
        days from the old start with the old end date would be two different requests. The merged
        arguments are what the `tool_call` span records, so the record is what was sent.
        """
        if call.name != COMPLIANCE_TOOL or not turn.resolved_slots:
            return call
        parameters = dict(call.args.get("parameters") or {})
        supplied = {key for key, value in parameters.items() if value not in (None, "")}
        blocked = set().union(*(family for family in SLOT_FAMILIES if family & supplied))
        added = {
            key: value
            for key, value in turn.resolved_slots.items()
            if key not in supplied and key not in blocked and key != "scenario"
        }
        if not added:
            return call
        turn.inherited.extend(sorted(added))
        turn.step_summaries.append(f"inherited {', '.join(sorted(added))} from the session into the compliance check")
        return call.model_copy(update={"args": {**call.args, "parameters": {**parameters, **added}}})

    async def _propose_deterministically(self, turn: _Turn) -> None:
        """Issue the write the turn was asked for, from the slots the turn itself resolved (C09).

        No token: the call comes back `CONFIRMATION_REQUIRED` exactly as the model's would, and
        `_propose` turns it into the same card. The arguments are templated from the compliance
        call's own parameters, so the card cannot describe a request the turn never scored.
        """
        tool = self._requested_write(turn)
        arguments = self._write_arguments(turn, tool) if tool else None
        if tool is None or arguments is None or turn.tool_calls_made >= self.settings.agent_max_tool_calls:
            # No card past the turn's own budget (W7-review Minor): the partial is what the stop
            # is for, and a call the budget forbids is not one the orchestrator gets to make. And
            # no card for a write the resolved slots do not describe (W8 minor round, R3).
            return
        result = await self._call(turn, tool, arguments)
        turn.tool_calls_made += 1
        if result.confirmation_required:
            self._propose(turn, result)
            turn.step_summaries.append("the assistant proposed the requested write from the turn's own slots")

    def _requested_write(self, turn: _Turn) -> str | None:
        """Which write the turn asked for — the one the router selected, else the one the question
        names, else a ticket — provided it is permitted (W8 minor round, R3).

        An `intent == "action"` turn asking for an email got a ticket card whenever the slots
        described one; the write is now the turn's own, and `_write_arguments` declines to build a
        card for a write it has no template for.
        """
        permitted = self._permitted(turn)
        selected = turn.decision.selected_tools if turn.decision is not None else []
        chosen = next((name for name in selected if name in WRITE_TOOLS), None)
        if chosen is None:
            message = turn.request.message.lower()
            chosen = (
                "draft_hr_email" if re.search(r"\b(?:e-?mail|draft|message|write to)\b", message) else WRITE_TOOLS[0]
            )
        return chosen if chosen in permitted else None

    def _write_arguments(self, turn: _Turn, tool: str = WRITE_TOOLS[0]) -> dict[str, Any] | None:
        """`create_mock_hr_ticket` arguments built from the turn's resolved slots, or `None`.

        `None` when the turn never resolved enough to describe the request: a card whose summary
        was invented would be worse than no card, because the reader confirms what it says — and
        `None` for any write this has no slot template for (`draft_hr_email` has none: its
        recipient, subject and body are the model's to write, not the orchestrator's to invent).
        """
        if tool != "create_mock_hr_ticket":
            return None
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
        # **Breadth is measured in documents, not in queries** (W10, ruling 14, scenario 13). The
        # Spain-and-equipment turn searched twice, reached one document twice, and answered the
        # equipment half of the question without ever retrieving an equipment passage. A second
        # query that lands in the same document has not widened anything, so the debt is reported
        # while the evidence spans fewer documents than the answer will be judged on — still at
        # most once per turn, so a nudged turn still costs one extra act step.
        documents = self._distinct_docs(turn)
        narrow = searches <= 1 or (documents > 0 and documents < self._minimum_docs(turn))
        if "search_breadth" not in turn.nudges and narrow and any(name in permitted for name in EVIDENCE_TOOLS):
            turn.nudges.append("search_breadth")
            reminder = (
                SEARCH_BREADTH_UNSEARCHED
                if searches == 0
                else SEARCH_BREADTH
                if searches == 1
                else SEARCH_BREADTH_REPEATED
            )
            turn.messages.append(Message(role="user", content=reminder))
            turn.step_summaries.append(
                f"step {turn.steps_taken}: {searches} corpus search(es) over "
                f"{documents} document(s), and the question may span more"
            )
            return True
        return False

    @staticmethod
    def _distinct_docs(turn: _Turn) -> int:
        """How many documents the turn's citable evidence actually spans."""
        return len({chunk.doc_id for chunk in turn.citable()})

    @staticmethod
    def _minimum_docs(turn: _Turn) -> int:
        """How many the answer will be judged on — the workflow's, or the `multi_doc` floor."""
        if turn.workflow is not None:
            return turn.workflow.min_distinct_docs
        decision = turn.decision
        return breadth.MIN_DISTINCT_DOCS if decision is not None and decision.multi_doc else 1

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
                    f"that same tool, matching its published input schema. Put them in "
                    f"`arguments_json` as a JSON object encoded in a string."
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
            # …and what the **session** already settled (W10, ruling 7). `route.j2` and `act.j2`
            # have carried this since W8; synthesis had not, so the answer could still write
            # "submit the request" over a ticket two turns old.
            session_context=session.render(turn.history),
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
        turn.state.record(result.tool_name, result.body, arguments=result.arguments)
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

        `non_compliant` is the verdict §8.4 gives an **evaluable** blocking requirement that is
        unmet. It is not the whole condition (W10, ruling 3): a blocking row nobody could evaluate
        comes back `not_stated`, does not reach `unmet[]`, and leaves the verdict at `conditional`
        — which is how MOCK-HR-000014 was filed for a three-day request against a balance of 0.25
        days that the turn had never checked, because `days` never reached the engine. **A request
        the engine could not clear is never filed**: any blocking row that is not `met` refuses the
        write, whether it failed or was never scored.

        The model is told, in the tool channel, that the call was refused and why — it is the only
        way the answer can be written around the refusal — and the reason is kept on the turn so
        the answer opens with it as a `notice`.
        """
        # The verdict has to be the one for **the write's** scenario (W7-review Minor; W8 minor
        # round, R4): a ticket bound for `hr-timeoff` is refused on the `pto_request` verdict even
        # when a later, compliant verdict for another scenario is the latest thing the turn scored.
        # A queue no scenario maps to is judged on the latest verdict, as before.
        body = self._verdict_for_queue(turn, str(call.args.get("queue") or ""))
        if not body:
            return False
        unclear = [
            row
            for row in body.get("requirements") or []
            if isinstance(row, dict) and row.get("blocking") and row.get("status") != "met"
        ]
        if body.get("verdict") != "non_compliant" and not unclear:
            return False
        envelope = _ToolEnvelope(name=COMPLIANCE_TOOL, result_json=json.dumps(body, ensure_ascii=False))
        blocked_ids = {str(row.get("id")) for row in unclear}
        rows = compliance_restatement.rows([envelope])
        # The row the reader is owed: the blocking one that stopped it, else any failure.
        failing = next(
            (row for row in rows if row.id in blocked_ids and row.status == "unmet"),
            next(
                (row for row in rows if row.id in blocked_ids),
                next((row for row in rows if row.status == "unmet"), None),
            ),
        )
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
        unclear_reason = (
            f"the {body.get('scenario')} verdict is non_compliant"
            if body.get("verdict") == "non_compliant"
            else f"a blocking requirement is unresolved ({', '.join(sorted(blocked_ids))})"
        )
        self._error(
            turn,
            "write_blocked",
            f"{call.name} was not proposed: {unclear_reason}",
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
        # The record says which of the two conditions refused it (W10 fix round): "the verdict is
        # non_compliant" was printed for a blocking row nobody could evaluate, which is the case the
        # verdict alone does not cover.
        turn.step_summaries.append(f"step {turn.steps_taken}: {call.name} refused — {unclear_reason}")
        return True

    @staticmethod
    def _verdict_for_queue(turn: _Turn, queue: str) -> dict[str, Any] | None:
        """The compliance body that scored **this write's** scenario — the latest one whose scenario
        maps to the queue — or, for a queue no scenario maps to, the latest verdict of the turn."""
        bodies = list(turn.state.results.get(COMPLIANCE_TOOL) or [])
        matching = [body for body in bodies if DETERMINISTIC_QUEUES.get(str(body.get("scenario") or "")) == queue]
        if matching:
            return matching[-1]
        return bodies[-1] if bodies and not queue else None

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
        """The question, naming **every** slot that is actually empty (UX W2, jargon-and-exposure-4;
        W8, C18; G5, gap 4).

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

        G5 (gap 4) closes the half of that which was still asking about the first slot **only**. On
        the published run `amb-002` — *"Am I allowed to work from there for a while?"* — was asked
        where and never for how long, and `amb-003` fell through to the fallback that names nothing:
        the judge scored `named_missing_information` false on both and clarification accuracy 1 of 3
        with n = 3. The opening question is still one question; every other empty slot is named after
        it, and a turn with no workflow now walks its intent's order before the rationale.
        """
        workflow = turn.workflow
        has_record = bool(EMPLOYEE_ID.match(turn.request.employee_id or ""))
        decision = turn.decision
        slots = unfilled_slots(
            workflow.name if workflow is not None else None,
            known=session.known(turn.history),
            has_record=has_record,
            intent=decision.intent if decision is not None else None,
        )
        if not slots and decision is not None:
            # No workflow and no intent order to walk — but the router was told to name every missing
            # detail in its rationale, and until W10 nothing read it (ruling 9, scenario 12).
            found = rationale_slot(decision.rationale_summary or "")
            slots = (found,) if found is not None and (found != "identity" or not has_record) else ()
        turn.clarify_slot = slots[0] if slots else None
        return clarification_question(slots)

    def _clarify(self, turn: _Turn, question: str, *, cold_start: bool) -> ChatResponse:
        """`outcome="clarify"`, and the question names the missing slot (§9.6).

        The step under it names the same slot, and the quick replies are filtered by whether this
        session has a record of its own (W10, ruling 9).
        """
        has_record = bool(EMPLOYEE_ID.match(turn.request.employee_id or ""))
        answer = AnswerSchema(
            blocks=[AnswerBlock(type=NOTICE, text=question, citations=[])],
            next_steps=[CLARIFY_NEXT_STEPS.get(turn.clarify_slot or "", CLARIFY_FALLBACK_STEP)],
            rationale_summary="Clarification requested: a required detail is missing.",
        )
        return self._finish(
            turn,
            answer,
            outcome="clarify",
            stop_reason="clarify",
            cold_start=cold_start,
            quick_replies=clarify_chips(turn.clarify_slot, has_record=has_record),
        )

    def _refuse_unsafe(self, turn: _Turn, *, cold_start: bool) -> ChatResponse:
        """`outcome="refused"`, naming what will not be done and what the matrix does instead.

        It **cites the matrix** (W10, ruling 10): the refusal quotes a policy sentence, and
        scenario 14 served it with no citation anywhere on the page.
        """
        answer = AnswerSchema(
            blocks=[AnswerBlock(type=NOTICE, text=UNSAFE_REFUSAL, citations=matrix_citation())],
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
        confirmation: ConfirmationCard | None = None,
        error_kind: str | None = None,
        cold_start: bool = False,
        quick_replies: Sequence[str] = (),
    ) -> ChatResponse:
        """Step 6: the closing UPDATE, then the response built from the very spans that were written.

        **The citations are the served blocks' own** (W10, ruling 10). Every path ends here — the
        answer, the refusal, the escalation, the clarification, the degraded turn — so this is the
        one place a block citation and the top-level array can be made to agree, and the one place
        a dangling one can be made to fail closed.
        """
        decision = turn.decision
        answer, citations = self._served(turn, answer)
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
                # The arguments travel with the body (G5, gap 11): `_profile_outstanding` reads them,
                # and a resumed turn has to owe the same profile the live one did.
                turn.state.record(payload["tool_name"], body, arguments=payload.get("arguments") or {})
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
            # Confirmation copy, not the policy-search refusal (G5, gap 19): this branch is a card
            # that was already spent or has expired, and nothing about it is a question about evidence.
            return self._refuse(turn, g1.CONFIRMATION_MISSING, cold_start=False)
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
            return self._refuse(turn, g1.CONFIRMATION_INVALID, cold_start=False)
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
    "clarification_question",
    "clarify_chips",
    "clarify_slot_of",
    "rationale_slot",
    "unfilled_slots",
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
