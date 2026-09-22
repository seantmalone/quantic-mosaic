"""A monetary approval question is scored by the engine before anything is said about the tier
(W8 fix round, W7-review I2).

`eval:expenses-002:1` — a USD 3,000 client trip, answered from the USD 2,500 manager row and
closed by a step routing the report to the manager, because the amount never reached
`check_policy_compliance`. Here the router says `policy_qa` with no workflow, the model never
calls the engine at all, and the turn still ends with a verdict on USD 3,000 and an answer that
routes the claim to the tier that applies.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent.orchestrator import ChatRequest
from hrmosaic.agent.workflows import LoopState, expense_claim

pytestmark = pytest.mark.anyio

QUESTION = "I spent USD 3,000 on a client trip — who approves the expense claim?"


@pytest.fixture
async def scored(run_agent, mounted_mcp_url, store):
    response = await run_agent(
        "expense_claim.json", ChatRequest(message=QUESTION, employee_id="E1042"), url=mounted_mcp_url
    )
    spans = store.execute(
        "SELECT kind, name, seq, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (response.turn_id,)
    ).dicts()
    return response, [{**row, "payload": json.loads(row["payload_json"])} for row in spans]


async def test_the_turn_is_routed_to_the_expense_workflow_whatever_the_model_said(scored):
    _response, spans = scored
    plan = next(span["payload"] for span in spans if span["kind"] == "plan")

    assert plan["workflow"] == "expense_claim"
    assert plan["intent"] == "workflow"


async def test_the_engine_scores_the_amount_the_question_carried(scored):
    """The model never called it; the recorded `tool_call` carries the amount all the same."""
    _response, spans = scored
    calls = [span for span in spans if span["kind"] == "tool_call" and span["name"] == "check_policy_compliance"]

    assert len(calls) == 1
    assert calls[0]["payload"]["arguments"] == {
        "scenario": "expense_claim",
        "employee_id": "E1042",
        "parameters": {"amount_usd": 3000.0},
    }
    assert calls[0]["payload"]["is_error"] is False
    nudges = [nudge for span in spans if span["kind"] == "plan" for nudge in span["payload"].get("nudges") or []]
    assert "compliance_scored_deterministically" in nudges


async def test_the_answer_routes_the_claim_to_the_tier_that_applies(scored):
    """C07's other half, now reachable: the ceiling the recorded answer quoted is below the amount,
    so the restatement step replaces it with the tier the engine named."""
    response, _spans = scored

    assert response.outcome == "answered"
    assert "up to USD 2,500" not in response.answer
    assert "director" in response.answer.lower()


def test_the_predicate_closes_on_a_profile_a_verdict_and_two_citations():
    """`expense_claim.SPEC.is_complete` over its three states (G5b, gap 18).

    The third registered workflow's predicate had never been *observed* closing: instrumented across
    the unit and integration suites it was called 20 times and returned `False` 20 times, so "the
    workflow spec decides when the turn is complete" was asserted for two of the three. The clauses
    are §9.3's own — a `lookup_employee_profile` result **in state**, a compliance verdict that is not
    `insufficient_evidence`, and evidence for at least `MIN_CITATIONS` citations.
    """
    empty = LoopState()
    assert expense_claim.SPEC.is_complete(empty) is False

    profile_only = LoopState()
    profile_only.record("lookup_employee_profile", {"employee_id": "E1042"})
    assert expense_claim.SPEC.is_complete(profile_only) is False

    complete = LoopState()
    complete.record("lookup_employee_profile", {"employee_id": "E1042"})
    complete.record("check_policy_compliance", {"verdict": "compliant"}, arguments={"scenario": "expense_claim"})
    for index in range(expense_claim.MIN_CITATIONS):
        complete.note_evidence(f"c_{index}", "expenses-and-reimbursement")
    assert expense_claim.SPEC.is_complete(complete) is True
