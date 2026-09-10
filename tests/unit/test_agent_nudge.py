"""The act loop's two operational reminders, and the one meaning of "evidence" they rest on.

`b7b5fa7` added `Orchestrator._nudge()` and narrowed `_absorb()` after P8's live-provider check,
and both landed with **no assertion anywhere**: the only evidence they worked was one run against
`claude-haiku-4-5`, which CI cannot repeat. This file is that evidence, offline. It pins the
mechanism's contract so a P7 re-review has something to review, and so that either half —
reverting the narrowing, or dropping a reminder — fails a test instead of quietly re-opening the
live defect.

**What the reminders are for.** The completion predicate of §9.3 is Python: it cannot be talked out
of its requirements by a confident answer. But a model that has stopped calling tools cannot read
it either, so a turn could close one step short of the evidence G1 was about to demand, and the
answer refused. Each reminder is sent at most once per turn, only on the step where the model tried
to stop, and only while the gap is real.

**What a reminder may say.** The DEBT, in workflow words — never the tool that would settle it.
A reminder listing the remaining calls would author the rest of the tool sequence on every nudged
turn, and §13.4's ToolSelection would be scoring the hint; a reminder claiming "one search is
enough" would be false for `remote_work_eligibility`, which needs three distinct documents. Both
are asserted below, and every turn records which reminders fired (`PlanPayload.nudges`) so P10 can
publish a `nudge_rate` next to the scores.

**What the narrowing is for.** Tools 2 and 4 (`get_policy_section`, `check_policy_compliance`) cite
chunk ids without retrieving them: those ids carry no dense score, so they never enter G1's
candidate set. While they also counted towards the workflow's document spread, `is_complete` could
be true on a turn the evidence gate was about to refuse — which is exactly what happened live. A
quarantined chunk is the same defect wearing a different hat: G2 strips every citation to one, so
evidence that only G4 quarantined is evidence no answer may lean on. One meaning of "evidence",
shared by the predicate and the gate, is the fix.
"""

from __future__ import annotations

import time

import pytest

from hrmosaic.agent.client import DiscoveredCatalog, ToolResult
from hrmosaic.agent.guardrails import g1
from hrmosaic.agent.orchestrator import (
    ACTION_OUTSTANDING,
    SEARCH_BREADTH,
    SEARCH_BREADTH_UNSEARCHED,
    WORKFLOW_INCOMPLETE,
    ChatOptions,
    ChatRequest,
    ConfirmationCard,
    Orchestrator,
    _Turn,
)
from hrmosaic.agent.router import RouteDecision
from hrmosaic.agent.workflows import LoopState
from hrmosaic.agent.workflows import get as get_workflow
from hrmosaic.core.models import DiscoveredTool, RetrievalPayload, RetrievedChunk

PTO = get_workflow("pto_request")
REMOTE = get_workflow("remote_work_eligibility")

#: The nine tools of §8.4, as `tools/list` hands them over.
TOOL_NAMES = (
    "search_policy_documents",
    "get_policy_section",
    "list_policy_documents",
    "check_policy_compliance",
    "lookup_employee_profile",
    "check_pto_balance",
    "lookup_benefits_status",
    "create_mock_hr_ticket",
    "draft_hr_email",
)

#: §13.9's ablation, verbatim from the spec's variant table — the five tools it disables.
NO_STRUCTURED_TOOLS = [
    "lookup_employee_profile",
    "check_pto_balance",
    "lookup_benefits_status",
    "create_mock_hr_ticket",
    "draft_hr_email",
]


def catalog() -> DiscoveredCatalog:
    """A discovered catalog carrying the nine names — what `allowed_tools` filters."""
    return DiscoveredCatalog(
        server="hrmosaic-mcp",
        transport="stdio",
        url=None,
        protocol_version="2025-06-18",
        server_info=None,
        tools=tuple(
            DiscoveredTool(name=name, description=name, input_schema={"type": "object", "properties": {}})
            for name in TOOL_NAMES
        ),
        catalog_sha="sha",
        mcp_session_id=None,
        handshake_ms=1,
        discovered_at=0,
    )


def decision(intent: str, workflow: str | None) -> RouteDecision:
    return RouteDecision(
        intent=intent,
        workflow=workflow,
        needs_employee_data=True,
        needs_clarification=False,
        out_of_scope=False,
        sensitive=False,
        target_employee_id="E1042",
        selected_tools=[],
        rationale_summary="fixture",
    )


def a_turn(*, intent: str = "workflow", workflow=PTO, disabled: list[str] | None = None, searches: int = 2) -> _Turn:
    """A turn carrying only what `_nudge` and `_absorb` read.

    `buffer` is `None` on purpose: neither method touches it, and a reminder that ever reached the
    span writer would fail here with an `AttributeError` rather than pass quietly. The catalog is
    real, because `_nudge` now reads the same allowed-tool list the act step calls through.

    `searches` is how many corpus searches the turn has already made, and it defaults to **two** so
    the breadth reminder (P13 R3) is out of the way: every test that does not name it is about one
    of the other two reminders, and the breadth tests set it themselves.
    """
    turn = _Turn(
        request=ChatRequest(
            message="Can I take five days off next month?",
            employee_id="E1042",
            options=ChatOptions(tools_disabled=list(disabled or [])),
        ),
        buffer=None,
        catalog=catalog(),
        began=time.perf_counter(),
        decision=decision(intent, workflow.name if workflow is not None else None),
        workflow=workflow,
    )
    for _ in range(searches):
        turn.state.record("search_policy_documents", {"chunks": []})
    return turn


def orchestrator() -> Orchestrator:
    """No client connection and no model: `_nudge` and `_absorb` are pure over the turn."""
    return Orchestrator()


def retrieval(*chunks: tuple[str, str], quarantined: bool = False) -> RetrievalPayload:
    return RetrievalPayload(
        query="pto notice period",
        k=5,
        k_source="default",
        strategy="hybrid_rrf",
        chunks=[
            RetrievedChunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                doc_title=doc_id.replace("-", " ").title(),
                heading_path="Notice > Requesting Time Off",
                section="Requesting Time Off",
                rank=index + 1,
                dense_score=0.71,
                snippet="Requests are submitted at least ten business days in advance.",
                quarantined=quarantined,
            )
            for index, (chunk_id, doc_id) in enumerate(chunks)
        ],
    )


def result(tool_name: str, body: dict, *, retrievals: list[RetrievalPayload] | None = None) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        arguments={},
        body=body,
        is_error=False,
        error_code=None,
        span_id=None,
        duration_ms=3,
        text="{}",
        retrievals=retrievals or [],
    )


# --------------------------------------------------------------------------------------
# The workflow reminder
# --------------------------------------------------------------------------------------


def test_an_incomplete_workflow_is_reminded_once_and_only_once():
    turn = a_turn()
    agent = orchestrator()

    assert agent._nudge(turn) is True
    assert [message.role for message in turn.messages] == ["user"]
    assert turn.nudges == ["workflow_incomplete"]

    # The gap is still real on the next step, and the reminder is still not repeated.
    assert agent._nudge(turn) is False
    assert len(turn.messages) == 1
    assert turn.nudges == ["workflow_incomplete"]


def test_the_reminder_names_the_workflow_and_every_unfilled_slot():
    turn = a_turn()
    orchestrator()._nudge(turn)

    content = turn.messages[0].content or ""
    assert "pto_request" in content
    assert content == WORKFLOW_INCOMPLETE.format(
        workflow="pto_request",
        debts="; ".join(
            [
                "no employee record is in state yet",
                "no PTO balance for this employee is in state yet",
                "no compliance verdict is in state yet",
                "the turn holds fewer than 2 citable policy passages on notice and approval, and "
                "an answer may state policy only from passages it can cite",
            ]
        ),
    )
    assert turn.step_summaries == [
        "step 0: workflow incomplete — no employee record is in state yet; no PTO balance for this "
        "employee is in state yet; no compliance verdict is in state yet; the turn holds fewer than "
        "2 citable policy passages on notice and approval, and an answer may state policy only from "
        "passages it can cite"
    ]


@pytest.mark.parametrize("workflow", [PTO, REMOTE], ids=lambda spec: spec.name)
def test_no_reminder_ever_names_a_tool(workflow):
    """The P7 review's I1: on a nudged turn the harness must not author the remaining calls.

    Every tool name in the catalog is checked against both reminders and against the debts of a
    turn that has done nothing at all — the state in which every slot is unfilled and the wording
    is at its most tempting.
    """
    turn = a_turn(intent="action", workflow=workflow)
    agent = orchestrator()
    agent._nudge(turn)
    agent._nudge(turn)

    sent = " ".join(message.content or "" for message in turn.messages)
    assert len(turn.messages) == 2
    for name in TOOL_NAMES:
        assert name not in sent, f"the reminder dictates {name}"
        assert name not in " ".join(turn.step_summaries)


def test_the_remote_work_reminder_states_the_three_document_floor():
    """M3: "ONE search is enough" was false — this workflow cannot be closed by one document."""
    turn = a_turn(workflow=REMOTE)
    orchestrator()._nudge(turn)

    content = turn.messages[0].content or ""
    assert "3 distinct policy documents" in content
    assert "enough" not in content


def test_a_complete_workflow_is_never_reminded():
    turn = a_turn()
    turn.state.record("lookup_employee_profile", {"employee_id": "E1042"})
    turn.state.record("check_pto_balance", {"remaining_days": 12.0})
    turn.state.record("check_policy_compliance", {"verdict": "compliant"})
    turn.state.note_evidence("pto-and-holidays#0001", "pto-and-holidays")
    turn.state.note_evidence("pto-and-holidays#0002", "pto-and-holidays")
    assert PTO.is_complete(turn.state)

    assert orchestrator()._nudge(turn) is False
    assert turn.messages == [] and turn.step_summaries == [] and turn.nudges == []


def test_a_filled_slot_drops_out_of_the_debt_and_the_rest_remains():
    turn = a_turn()
    turn.state.record("check_pto_balance", {"remaining_days": 12.0})

    orchestrator()._nudge(turn)

    content = turn.messages[0].content or ""
    assert "no PTO balance" not in content
    assert "no compliance verdict is in state yet" in content


def test_a_turn_with_no_workflow_and_no_action_is_never_reminded():
    turn = a_turn(intent="policy_qa", workflow=None)

    assert orchestrator()._nudge(turn) is False
    assert turn.messages == []


# --------------------------------------------------------------------------------------
# The action reminder
# --------------------------------------------------------------------------------------


def test_an_unproposed_action_is_reminded_once_and_only_once():
    turn = a_turn(intent="action", workflow=None)
    agent = orchestrator()

    assert agent._nudge(turn) is True
    assert turn.messages[0].role == "user"
    assert turn.messages[0].content == ACTION_OUTSTANDING
    assert turn.step_summaries == ["step 0: the requested action was still unproposed"]
    assert turn.nudges == ["action_outstanding"]

    assert agent._nudge(turn) is False
    assert len(turn.messages) == 1


@pytest.mark.parametrize("tool_name", ["create_mock_hr_ticket", "draft_hr_email"])
def test_an_action_whose_write_was_already_attempted_is_never_reminded(tool_name: str):
    turn = a_turn(intent="action", workflow=None)
    turn.state.record(tool_name, {"status": "created", "ticket_id": "MOCK-HR-000004"})

    assert orchestrator()._nudge(turn) is False
    assert turn.messages == []


def test_an_action_already_parked_at_the_confirmation_gate_is_never_reminded():
    turn = a_turn(intent="action", workflow=None)
    turn.pending = ConfirmationCard(
        action="create_mock_hr_ticket",
        human_summary="Open a PTO request ticket for E1042.",
        arguments_preview={"employee_id": "E1042"},
        expires_at=int(time.time()) + 600,
    )

    assert orchestrator()._nudge(turn) is False
    assert turn.messages == []


def test_the_workflow_reminder_comes_first_and_the_action_reminder_on_the_next_step():
    """One reminder per step: the loop gets a step back between them, never two in one message."""
    turn = a_turn(intent="action", workflow=PTO)
    agent = orchestrator()

    assert agent._nudge(turn) is True
    assert "pto_request" in (turn.messages[0].content or "")
    assert agent._nudge(turn) is True
    assert turn.messages[1].content == ACTION_OUTSTANDING
    assert agent._nudge(turn) is False
    assert len(turn.messages) == 2
    assert turn.nudges == ["workflow_incomplete", "action_outstanding"]


def test_a_reminder_never_invents_evidence():
    """It is an instruction to the model, not a fact about the turn (§9.7)."""
    turn = a_turn(intent="action", workflow=PTO)
    agent = orchestrator()
    agent._nudge(turn)
    agent._nudge(turn)

    assert turn.state.evidence_chunk_ids == [] and turn.state.evidence_doc_ids == []
    assert turn.evidence == {}


# --------------------------------------------------------------------------------------
# A reminder never asks for a tool this turn may not call (§13.9's ablation)
# --------------------------------------------------------------------------------------


def test_the_ablation_that_disables_the_write_tools_silences_the_action_reminder():
    """No permitted tool can propose the action, so asking for it would only invite a refused call."""
    turn = a_turn(intent="action", workflow=None, disabled=NO_STRUCTURED_TOOLS)

    assert orchestrator()._nudge(turn) is False
    assert turn.messages == [] and turn.nudges == []


def test_a_debt_only_a_disabled_tool_could_settle_is_not_reported():
    """The balance is out of reach under `no_structured_tools`; the reminder does not ask for it."""
    turn = a_turn(intent="action", disabled=NO_STRUCTURED_TOOLS)
    turn.state.record("check_policy_compliance", {"verdict": "compliant"})
    turn.state.note_evidence("pto-and-holidays#0001", "pto-and-holidays")
    turn.state.note_evidence("pto-and-holidays#0002", "pto-and-holidays")
    assert PTO.is_complete(turn.state) is False, "the balance is the one unfilled slot"

    assert orchestrator()._nudge(turn) is False
    assert turn.messages == [] and turn.nudges == []


def test_a_debt_a_permitted_tool_can_still_settle_is_reported_under_the_ablation():
    """The ablation silences what it disabled and nothing else: retrieval is still permitted."""
    turn = a_turn(disabled=NO_STRUCTURED_TOOLS)

    assert orchestrator()._nudge(turn) is True
    content = turn.messages[0].content or ""
    assert "no PTO balance" not in content
    assert "no compliance verdict is in state yet" in content
    assert "citable policy passages" in content


def test_a_turn_that_discovered_no_catalog_is_never_reminded():
    turn = a_turn(intent="action", workflow=PTO)
    turn.catalog = None

    assert orchestrator()._nudge(turn) is False
    assert turn.messages == []


# --------------------------------------------------------------------------------------
# One meaning of "evidence"
# --------------------------------------------------------------------------------------


def test_a_retrieved_chunk_is_evidence():
    """The control: a chunk with a dense score enters both the predicate's count and G1's set."""
    turn = a_turn()
    fresh = orchestrator()._absorb(
        turn,
        result(
            "search_policy_documents",
            {"chunks": []},
            retrievals=[retrieval(("pto-and-holidays#0007", "pto-and-holidays"))],
        ),
    )

    assert [chunk.chunk_id for chunk in fresh] == ["pto-and-holidays#0007"]
    assert turn.state.evidence_chunk_ids == ["pto-and-holidays#0007"]
    assert turn.state.evidence_doc_ids == ["pto-and-holidays"]
    assert list(turn.evidence) == ["pto-and-holidays#0007"]
    assert [chunk.chunk_id for chunk in turn.citable()] == ["pto-and-holidays#0007"]


@pytest.mark.parametrize(
    ("tool_name", "body"),
    [
        ("get_policy_section", {"doc_id": "pto-and-holidays", "chunk_ids": ["pto-and-holidays#0007"]}),
        (
            "check_policy_compliance",
            {
                "verdict": "compliant",
                "citations": [{"chunk_id": "manager-approval-matrix#0002", "doc_id": "manager-approval-matrix"}],
            },
        ),
    ],
)
def test_a_merely_cited_chunk_id_is_not_evidence(tool_name: str, body: dict):
    """Tools 2 and 4 cite ids they never scored; counting them made `is_complete` outrun G1."""
    turn = a_turn()
    fresh = orchestrator()._absorb(turn, result(tool_name, body))

    assert fresh == []
    assert turn.state.evidence_chunk_ids == [] and turn.state.evidence_doc_ids == []
    assert turn.evidence == {}
    # The result itself is still in state — only its citations stopped counting as evidence.
    assert turn.state.has(tool_name)


def test_a_quarantined_chunk_is_not_evidence_and_does_not_satisfy_a_predicate():
    """G4 quarantined it, so G2 will strip every citation to it: it can support nothing.

    The retrieval itself is untouched — the chunk is still in `turn.evidence` for the prompt and
    still on the persisted `retrieval` span with its flag — but the completion predicate and the
    evidence gate both look past it, and a turn holding nothing else is refused rather than
    answered from support the answer is forbidden to cite.
    """
    turn = a_turn()
    agent = orchestrator()
    agent._absorb(turn, result("check_pto_balance", {"remaining_days": 12.0}))
    agent._absorb(turn, result("check_policy_compliance", {"verdict": "compliant"}))
    fresh = agent._absorb(
        turn,
        result(
            "search_policy_documents",
            {"chunks": []},
            retrievals=[
                retrieval(
                    ("pto-and-holidays#0007", "pto-and-holidays"),
                    ("manager-approval-matrix#0002", "manager-approval-matrix"),
                    quarantined=True,
                )
            ],
        ),
    )

    assert [chunk.chunk_id for chunk in fresh] == ["pto-and-holidays#0007", "manager-approval-matrix#0002"]
    assert turn.state.evidence_chunk_ids == [] and turn.state.evidence_doc_ids == []
    assert PTO.is_complete(turn.state) is False
    assert REMOTE.evidence_met(turn.state) is False

    # And G1 refuses: the only chunks the turn holds are ones no answer may cite.
    assert turn.citable() == []
    assert g1.evaluate(turn.citable()).passed is False
    assert g1.evaluate(turn.chunks()).passed is True, "the control — unquarantined, these would pass"


def test_a_compliance_verdict_without_retrieval_does_not_complete_the_pto_workflow():
    """The live defect, offline: a verdict reached without ever searching is not a complete turn."""
    turn = a_turn(searches=0)
    agent = orchestrator()
    agent._absorb(turn, result("check_pto_balance", {"remaining_days": 12.0}))
    agent._absorb(
        turn,
        result(
            "check_policy_compliance",
            {
                "verdict": "compliant",
                "citations": [
                    {"chunk_id": "pto-and-holidays#0007", "doc_id": "pto-and-holidays"},
                    {"chunk_id": "manager-approval-matrix#0002", "doc_id": "manager-approval-matrix"},
                ],
            },
        ),
    )

    assert PTO.is_complete(turn.state) is False
    assert agent._nudge(turn) is True, "the model is told what the turn still owes"


def test_a_compliance_verdict_without_retrieval_does_not_complete_the_remote_work_workflow():
    turn = a_turn(workflow=REMOTE, searches=0)
    agent = orchestrator()
    agent._absorb(turn, result("lookup_employee_profile", {"employee_id": "E1042", "work_country": "US"}))
    agent._absorb(
        turn,
        result(
            "check_policy_compliance",
            {
                "verdict": "compliant",
                "citations": [
                    {"chunk_id": "remote-and-hybrid-work#0003", "doc_id": "remote-and-hybrid-work"},
                    {"chunk_id": "tax-and-location-addendum#0001", "doc_id": "tax-and-location-addendum"},
                    {"chunk_id": "security-acceptable-use#0005", "doc_id": "security-acceptable-use"},
                ],
            },
        ),
    )

    assert REMOTE.is_complete(turn.state) is False
    assert agent._nudge(turn) is True


# --------------------------------------------------------------------------------------
# The loop wiring
# --------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_reminded_turn_takes_another_act_step_instead_of_closing(run_agent, spans, store):
    """End to end under the stub: the model answers with no tool call and the loop says "not yet".

    `nudge_probe.json` scripts four prose-only act completions. Without the reminders the loop
    would close on the first one after a single act call — which is the shape the live provider
    produced and the stub could not, until this script.
    """
    response = await run_agent(
        "nudge_probe.json",
        ChatRequest(message="Book me five days off next month and open the ticket.", employee_id="E1042"),
    )
    records = spans(response.turn_id)

    act_calls = [payload for kind, _, payload in records if kind == "llm_call" and payload["purpose"] == "act"]
    assert len(act_calls) == 4, "one reminder each, then the loop lets the model stop"

    summary = next(payload for kind, name, payload in records if name == "act_summary")
    assert summary["step_summaries"] == [
        "step 1: workflow incomplete — no employee record is in state yet; no PTO balance for this "
        "employee is in state yet; no compliance verdict is in state yet; the turn holds fewer than "
        "2 citable policy passages on notice and approval, and an answer may state policy only from "
        "passages it can cite",
        "step 2: the requested action was still unproposed",
        "step 3: 0 corpus search(es), and the question may span more",
        "step 4: no tool call, the model answered",
    ]
    # Machine-readable, on the plan span, so §13.4's reader can separate nudged turns from the
    # rest and P10 can report a `nudge_rate` (P7 review, I1b).
    assert summary["nudges"] == ["workflow_incomplete", "action_outstanding", "search_breadth"]

    # The reminders reached the model verbatim, and live nowhere but the `llm_messages` rows.
    rows = store.execute(
        "SELECT m.role, m.content FROM llm_messages m JOIN spans s ON s.id = m.span_id "
        "WHERE s.turn_id = ? ORDER BY s.seq, m.seq",
        (response.turn_id,),
    ).dicts()
    reminders = [
        row["content"]
        for row in rows
        if row["role"] == "user" and row["content"].startswith(("Not yet", "The user asked for something"))
    ]
    assert reminders[0].startswith("Not yet — this turn is not finished. The pto_request workflow is incomplete")
    assert ACTION_OUTSTANDING in reminders
    assert SEARCH_BREADTH_UNSEARCHED in reminders, "this turn searched none, and is told so"

    # And they manufactured nothing: no tool ran, so G1 still refuses.
    assert response.outcome == "refused"
    assert response.usage.tool_calls == 0


@pytest.mark.anyio
async def test_a_turn_that_was_never_nudged_records_an_empty_nudges_list(run_agent, spans):
    """The other half of the `nudge_rate`: a clean turn says so, rather than saying nothing.

    `injection_probe.json` searches twice in its one act step, so none of the three reminders has
    anything to report: no workflow, no requested action, and a corpus the turn read more than one
    query's worth of.
    """
    response = await run_agent(
        "injection_probe.json",
        ChatRequest(message="What should I do about a suspicious phishing email?", employee_id="E1042"),
    )

    summary = next(payload for kind, name, payload in spans(response.turn_id) if name == "act_summary")
    assert summary["nudges"] == []


# --------------------------------------------------------------------------------------
# What `pto_request` requires in state (P13 R5)
# --------------------------------------------------------------------------------------


def test_the_pto_workflow_is_incomplete_until_the_employee_record_is_in_state():
    """R5: §9.3 lists the employee profile first among `pto_request`'s required slots.

    `is_complete` did not read it, so a turn that never looked the employee up closed early —
    `pto-003` and `unsafe-001` both ended on a balance and a verdict about an employee the turn
    had never read. The predicate now requires the result, exactly as `remote_work_eligibility`
    requires it, and the ablation that disables the people-data tools moves workflow completion
    rather than only ToolSelection (§13.9).
    """
    state = LoopState()
    state.record("check_pto_balance", {"remaining_days": 12.0})
    state.record("check_policy_compliance", {"verdict": "compliant"})
    state.note_evidence("pto-and-holidays#0001", "pto-and-holidays")
    state.note_evidence("pto-and-holidays#0002", "pto-and-holidays")
    assert PTO.is_complete(state) is False

    state.record("lookup_employee_profile", {"employee_id": "E1042", "work_country": "US"})
    assert PTO.is_complete(state) is True


def test_the_pto_workflow_requires_all_three_tool_results():
    assert PTO.requires_tool_results == (
        "lookup_employee_profile",
        "check_pto_balance",
        "check_policy_compliance",
    )
    assert PTO.missing_tool_results(LoopState()) == list(PTO.requires_tool_results)


def test_the_missing_employee_record_is_reported_as_a_debt_in_workflow_words():
    """The same words `remote_work.py` uses — the debt, never the tool that would settle it."""
    turn = a_turn()
    orchestrator()._nudge(turn)

    content = turn.messages[0].content or ""
    assert "no employee record is in state yet" in content
    assert PTO.slot_descriptions["lookup_employee_profile"] == REMOTE.slot_descriptions["lookup_employee_profile"]


# --------------------------------------------------------------------------------------
# The breadth reminder (P13 R3)
# --------------------------------------------------------------------------------------


def test_a_turn_that_searched_once_is_reminded_that_the_corpus_is_federated():
    """R3: `remote-002` and `expenses-002` cited two documents where three were required.

    Neither other reminder fires there — the workflow's debts are settled and no action is
    outstanding — so the turn stopped one query short of the document the end state wanted.
    """
    turn = a_turn(intent="policy_qa", workflow=None, searches=1)

    assert orchestrator()._nudge(turn) is True
    assert turn.messages[0].role == "user"
    assert turn.messages[0].content == SEARCH_BREADTH
    assert turn.nudges == ["search_breadth"]
    assert turn.step_summaries == ["step 0: 1 corpus search(es), and the question may span more"]


def test_the_breadth_reminder_is_sent_at_most_once_per_turn():
    turn = a_turn(intent="policy_qa", workflow=None, searches=1)
    agent = orchestrator()

    assert agent._nudge(turn) is True
    assert agent._nudge(turn) is False
    assert len(turn.messages) == 1
    assert turn.nudges == ["search_breadth"]


def test_the_breadth_reminder_is_not_sent_on_a_step_another_reminder_took():
    """One reminder per step: the loop gets a step back between them (§9.1 step 2)."""
    turn = a_turn(intent="action", workflow=PTO, searches=1)
    agent = orchestrator()

    assert agent._nudge(turn) is True
    assert turn.nudges == ["workflow_incomplete"]
    assert agent._nudge(turn) is True
    assert turn.nudges == ["workflow_incomplete", "action_outstanding"]
    assert agent._nudge(turn) is True
    assert turn.nudges == ["workflow_incomplete", "action_outstanding", "search_breadth"]
    assert [message.content for message in turn.messages][-1] == SEARCH_BREADTH


def test_a_turn_that_has_already_searched_twice_is_not_reminded():
    """The reminder is about breadth, not about searching more forever."""
    turn = a_turn(intent="policy_qa", workflow=None, searches=2)

    assert orchestrator()._nudge(turn) is False
    assert turn.messages == [] and turn.nudges == []


def test_the_breadth_reminder_is_silent_when_retrieval_is_disabled():
    """Asking for another search a turn may not make would only invite a refused call."""
    turn = a_turn(intent="policy_qa", workflow=None, disabled=["search_policy_documents"], searches=1)

    assert orchestrator()._nudge(turn) is False
    assert turn.messages == [] and turn.nudges == []


def test_the_breadth_reminder_is_silent_when_no_tool_may_be_called_at_all():
    turn = a_turn(intent="policy_qa", workflow=None, searches=1)
    turn.catalog = None

    assert orchestrator()._nudge(turn) is False
    assert turn.messages == [] and turn.nudges == []


def test_the_breadth_reminder_names_no_tool_and_no_document_count():
    """The ledger's non-negotiable: the debt, never the tool, and never how many documents."""
    for text in (SEARCH_BREADTH, SEARCH_BREADTH_UNSEARCHED):
        for name in TOOL_NAMES:
            assert name not in text
        assert "three" not in text and "3 " not in text
        assert "k=" not in text


def test_a_turn_that_has_not_searched_at_all_is_not_told_that_it_has():
    """The reminder is the one message whose job is to correct the model's picture of the turn.

    It fires at *at most* one search, so it also reaches a turn that searched none; telling that
    turn it "searched the corpus once" would put a false statement about its own history in the
    prompt. Only the opening clause moves — the debt is one shared string (P13 review, finding 2).
    """
    turn = a_turn(intent="policy_qa", workflow=None, searches=0)

    assert orchestrator()._nudge(turn) is True
    assert turn.nudges == ["search_breadth"]
    assert turn.messages[0].content == SEARCH_BREADTH_UNSEARCHED
    assert "searched the corpus once" not in (turn.messages[0].content or "")
    assert turn.step_summaries == ["step 0: 0 corpus search(es), and the question may span more"]


def test_both_forms_of_the_breadth_reminder_state_the_same_debt():
    """One shared string after the opening clause, so the two forms cannot drift apart."""
    debt = SEARCH_BREADTH.split(". ", 1)[1]

    assert SEARCH_BREADTH_UNSEARCHED.endswith(debt)
    assert SEARCH_BREADTH.startswith("Not yet — you have searched the corpus once.")
    assert SEARCH_BREADTH_UNSEARCHED.startswith("Not yet — you have not searched the corpus yet.")
