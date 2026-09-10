"""§9.5 row 4 — an ambiguous request, at **HTTP 200**, `clarify`, and **without burning a tool call**.

The router sets `needs_clarification` and the turn stops there. That "without burning a tool call"
clause is the substance of the row: an agent that guessed a date, called three tools and then asked
the question anyway would have spent the budget and the grader's patience before admitting it did
not know. The question itself has to name the missing information — §13.4 judges exactly that as
`clarification_accuracy` over the dataset's `ambiguous` items.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.anyio

QUESTION = "Can I take some time off soon?"


@pytest.fixture
async def clarified(web):
    async with web("fault_ambiguous.json") as client:
        response = await client.post("/chat", json={"message": QUESTION})
        assert response.status_code == 200, response.text
        yield response.json()


async def test_the_turn_ends_clarify_at_http_200(clarified):
    assert clarified["outcome"] == "clarify"
    assert clarified["answer"].strip()
    assert clarified["confirmation"] is None


async def test_not_one_tool_call_was_made(clarified, store):
    kinds = [
        row["kind"]
        for row in store.execute(
            "SELECT kind FROM spans WHERE turn_id = ? ORDER BY seq", (clarified["turn_id"],)
        ).dicts()
    ]
    assert "tool_call" not in kinds
    assert "retrieval" not in kinds
    assert kinds.count("plan") == 1, "the router planned once and stopped"


async def test_the_question_names_the_missing_information(clarified):
    answer = clarified["answer"]
    assert "dates" in answer or "date" in answer
    assert "E1042" in answer, "and shows the shape of the other slot it may need"


async def test_exactly_one_model_call_was_spent(clarified, store):
    purposes = [
        json.loads(row["payload_json"])["purpose"]
        for row in store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'llm_call' ORDER BY seq",
            (clarified["turn_id"],),
        ).dicts()
    ]
    assert purposes == ["route"]


async def test_the_plan_span_records_the_decision_that_produced_the_clarification(clarified, store):
    plan = json.loads(
        store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'plan' ORDER BY seq LIMIT 1",
            (clarified["turn_id"],),
        ).scalar()
    )
    assert plan["intent"] == "workflow"
    assert plan["workflow"] == "pto_request"
    assert plan["rationale_summary"], "R4.1's decision is logged, not inferred"

    row = store.execute("SELECT outcome, stop_reason FROM turns WHERE id = ?", (clarified["turn_id"],)).one()
    assert (row["outcome"], row["stop_reason"]) == ("clarify", "clarify")
