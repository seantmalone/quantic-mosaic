"""Three ruled behaviours that shipped with no guard (W10 fix round, Important 3).

The W10 report marked all three **fixed** and cited tests that do not contain the assertion. They
are pure functions over one turn, so they are tested here the way `_nudge` already is: a `_Turn`
carrying only what the method reads, and the real `Orchestrator` over it.

* **Ruling 14, scenario 02.** E1108 was told, correctly, that he does not have the twelve months of
  service an international stay needs — in the *fourth* block, after three paragraphs that read as
  though the trip were on, and never told the day he becomes eligible. The refusal leads, and the
  engine's own `computed.tenure_eligible_on` follows it.
* **Ruling 12, scenario 15.** A complete four-block answer shipped under *"I reached my step limit
  for this turn; here is what I established before stopping"*, because the repair leg 400'd on its
  own schema and spent the budget without losing anything. The lede is for the answer that is
  actually short — and the `error` span is for **every** budget stop, whether or not it is.
* **Ruling 3, scenario 06.** A blocking requirement nobody could evaluate is `not_stated`, reaches
  no `unmet[]`, and leaves the verdict `conditional` — which is how a ticket was filed for a
  three-day request against a balance of 0.25 days the turn had never checked.
"""

from __future__ import annotations

import time

import pytest

from hrmosaic.agent.orchestrator import (
    BUDGET_STOPS,
    ChatRequest,
    Orchestrator,
    _Turn,
)
from hrmosaic.agent.router import RouteDecision
from hrmosaic.agent.workflows import get as get_workflow
from hrmosaic.core.llm.base import ToolCall
from hrmosaic.mcpserver import rules
from hrmosaic.mcpserver.server import ServerDeps
from hrmosaic.mcpserver.tools.check_pto_balance import balance_row

DEPS = ServerDeps()
RULE_SET = rules.load_rules(DEPS.rules_path, DEPS.facts_path)


def verdict(scenario: str, parameters: dict, employee_id: str) -> dict:
    """A real engine verdict — never a hand-written one: the rows this reads are the engine's."""
    employee = DEPS.employee(employee_id)
    assert employee is not None
    return rules.evaluate(
        scenario,
        employee=employee,
        balance=balance_row(DEPS, employee_id) or {},
        parameters=parameters,
        holidays=[],
        as_of=DEPS.as_of(),
        submitted_on="2026-09-01",
        rule_set=RULE_SET,
        connection=DEPS.index(),
    )


def a_turn(*, workflow: str | None, employee_id: str = "E1042") -> _Turn:
    """A turn carrying only what the three methods below read. `buffer` is `None` on purpose."""
    return _Turn(
        request=ChatRequest(message="Can I?", employee_id=employee_id),
        buffer=None,
        catalog=None,
        began=time.perf_counter(),
        decision=RouteDecision(
            intent="workflow",
            workflow=workflow,
            multi_doc=False,
            needs_employee_data=True,
            needs_clarification=False,
            out_of_scope=False,
            sensitive=False,
            target_employee_id=employee_id,
            selected_tools=[],
            rationale_summary="fixture",
        ),
        workflow=get_workflow(workflow) if workflow else None,
    )


# -- ruling 14: the refusal leads, and the engine says when the answer changes --------------------


def test_the_engine_derives_the_day_an_unmet_tenure_requirement_starts_being_met():
    """E1108 was hired on 2026-08-15 and an international stay needs twelve months."""
    body = verdict(
        "international_remote",
        {"destination_country": "DE", "start_date": "2026-11-03", "end_date": "2026-12-14"},
        "E1108",
    )
    assert body["verdict"] == "non_compliant"
    assert body["computed"]["tenure_eligible_on"] == "2027-08-15"


def test_a_met_scenario_derives_no_eligibility_date():
    """The field is the answer to an *unmet* tenure row; a met one has no date to give."""
    body = verdict(
        "international_remote",
        {"destination_country": "DE", "start_date": "2026-11-03", "end_date": "2026-12-14"},
        "E1042",
    )
    assert "tenure_eligible_on" not in body["computed"]


def test_the_refused_request_opens_with_the_failing_row_and_the_date():
    turn = a_turn(workflow="remote_work_eligibility", employee_id="E1108")
    turn.state.record(
        "check_policy_compliance",
        verdict(
            "international_remote",
            {"destination_country": "DE", "start_date": "2026-11-03", "end_date": "2026-12-14"},
            "E1108",
        ),
    )

    lede = Orchestrator()._verdict_lede(turn)

    assert lede is not None
    assert lede.startswith("Your continuous service"), "the engine's own row, in the reader's voice"
    assert lede.endswith("You meet that requirement on 15 August 2027.")


def test_a_compliant_or_conditional_verdict_opens_with_nothing():
    turn = a_turn(workflow="remote_work_eligibility")
    turn.state.record(
        "check_policy_compliance",
        verdict(
            "international_remote",
            {"destination_country": "DE", "start_date": "2026-11-03", "end_date": "2026-12-14"},
            "E1042",
        ),
    )
    assert Orchestrator()._verdict_lede(turn) is None


def test_a_turn_that_already_leads_with_its_own_notice_does_not_lead_twice():
    """A blocked write says it in its own `notice`, and a declined card in its receipt."""
    turn = a_turn(workflow="remote_work_eligibility", employee_id="E1108")
    turn.state.record(
        "check_policy_compliance",
        verdict("international_remote", {"destination_country": "DE", "start_date": "2026-11-03"}, "E1108"),
    )
    turn.write_blocked = "I have not opened the request: …"
    assert Orchestrator()._verdict_lede(turn) is None

    turn.write_blocked = None
    turn.declined = True
    assert Orchestrator()._verdict_lede(turn) is None


# -- ruling 12: the budget lede is for an answer that is actually short ---------------------------

SUBSTANTIVE = [{"type": "policy_fact", "text": "Notice is five business days.", "citations": ["c_one"]}]


def complete_pto_turn() -> _Turn:
    """A `pto_request` turn whose completion predicate holds — §9.3's own slots, filled."""
    turn = a_turn(workflow="pto_request")
    turn.state.record("lookup_employee_profile", {"employee_id": "E1042"})
    turn.state.record("check_pto_balance", {"employee_id": "E1042", "remaining_days": 13.5})
    turn.state.record(
        "check_policy_compliance", verdict("pto_request", {"start_date": "2026-09-15", "days": 3}, "E1042")
    )
    turn.state.note_evidence("c_one", "pto-and-holidays")
    turn.state.note_evidence("c_two", "manager-approval-matrix")
    return turn


def test_a_complete_answer_never_wears_the_budget_lede():
    turn = complete_pto_turn()
    assert turn.workflow is not None and turn.workflow.is_complete(turn.state), "the predicate holds"

    assert Orchestrator()._complete(turn, SUBSTANTIVE) is True


def test_an_incomplete_workflow_still_wears_it():
    turn = a_turn(workflow="pto_request")
    assert Orchestrator()._complete(turn, SUBSTANTIVE) is False


def test_a_turn_with_no_workflow_keeps_the_graceful_partial_it_always_had():
    """There is no completion predicate to ask, so §9.4's partial stands exactly as before: the
    ruling narrows the lede where something can say the answer is whole, and never guesses."""
    turn = a_turn(workflow=None)
    assert Orchestrator()._complete(turn, SUBSTANTIVE) is False


def test_an_answer_with_no_substantive_block_is_never_called_complete():
    turn = complete_pto_turn()
    assert (
        Orchestrator()._complete(turn, [{"type": "escalation", "text": "Contact People Ops.", "citations": []}])
        is False
    )


def test_every_budget_stop_is_still_one_of_the_three_the_spec_names():
    assert BUDGET_STOPS == ("max_steps", "max_tool_calls", "timeout")


# -- ruling 3: a blocking row nobody could evaluate refuses the write -----------------------------


@pytest.fixture
def unclear() -> dict:
    """E1042's PTO request with **no** day count: the blocking balance row cannot be scored."""
    body = verdict("pto_request", {"start_date": "2026-09-15"}, "E1042")
    balance = next(row for row in body["requirements"] if row["id"] == "pto.request.balance")
    assert (balance["status"], balance["blocking"]) == ("not_stated", True)
    assert body["verdict"] != "non_compliant", "which is exactly why the verdict alone was not the test"
    return body


def _recorded_turn(writer, *, workflow: str):
    """The same turn, with a real `TurnBuffer` — `_refuse_write` writes an `error` span."""
    from hrmosaic.core.trace import SessionSpec

    turn = a_turn(workflow=workflow)
    turn.buffer = writer.start_turn(
        SessionSpec(id="s_fix", employee_id="E1042", auth_mode="open", actor_role="employee", client_label="web"),
        user_message="Can I?",
    )
    return turn


def a_ticket_call() -> ToolCall:
    return ToolCall(
        id="call_1",
        name="create_mock_hr_ticket",
        args={"employee_id": "E1042", "queue": "hr-timeoff", "summary": "PTO request", "details": "…"},
    )


def test_a_write_against_an_unscorable_blocking_row_is_refused(unclear, writer):
    turn = _recorded_turn(writer, workflow="pto_request")
    turn.state.record("check_policy_compliance", unclear)

    refused = Orchestrator()._refuse_write(turn, a_ticket_call(), None)

    assert refused is True
    assert turn.write_blocked, "and the reader is told why, in the product's own voice"
    assert turn.write_blocked.startswith("I have not opened the request:")
    assert "could not check" in turn.write_blocked or "PTO balance" in turn.write_blocked
    assert any("blocking requirement is unresolved" in summary for summary in turn.step_summaries)


def test_a_write_the_engine_could_not_score_at_all_is_still_refused(unclear, writer):
    """The reader is not told a ticket was opened on a balance nobody checked — the whole of
    scenario 06. The tool channel says so too, so the answer can be written around it."""
    turn = _recorded_turn(writer, workflow="pto_request")
    turn.state.record("check_policy_compliance", unclear)
    Orchestrator()._refuse_write(turn, a_ticket_call(), None)

    refusals = [message for message in turn.messages if message.role == "tool"]
    assert refusals and "VERDICT_NON_COMPLIANT" in (refusals[-1].content or "")


def test_a_write_the_engine_cleared_is_not_refused(writer):
    turn = _recorded_turn(writer, workflow="pto_request")
    turn.state.record(
        "check_policy_compliance", verdict("pto_request", {"start_date": "2026-09-15", "days": 3}, "E1042")
    )

    assert Orchestrator()._refuse_write(turn, a_ticket_call(), None) is False
    assert not turn.write_blocked


def test_a_manual_row_never_refuses_the_write():
    """`pto.request.manager_approval` is `not_stated` on every PTO turn; counting it would file no
    ticket ever again, which is why the engine publishes `blocking: false` for a `manual` check."""
    body = verdict("pto_request", {"start_date": "2026-09-15", "days": 3}, "E1042")
    manual = next(row for row in body["requirements"] if row["id"] == "pto.request.manager_approval")
    assert (manual["status"], manual["blocking"]) == ("not_stated", False)
