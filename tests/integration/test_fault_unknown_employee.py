"""§9.5 row 2 — an unknown `employee_id`, at **HTTP 200** with a clarifying question.

`lookup_employee_profile` answers with the structured `not_found` of §8.3 — a **successful** tool
result, not an error, because "no such employee" is a fact about the data and not a fault in the
call. The orchestrator turns it into a clarification that names the id format, and the turn ends
`outcome="clarify"` rather than guessing at a different employee.

Nothing is mocked: the id really is absent from the committed mock dataset, and the answer really
comes back over the MCP wire.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.anyio

QUESTION = "How many PTO days does employee E1999 have left?"


@pytest.fixture
async def clarified(web):
    async with web("fault_unknown_employee.json") as client:
        response = await client.post("/chat", json={"message": QUESTION})
        assert response.status_code == 200, response.text
        yield response.json()


async def test_the_turn_ends_clarify_at_http_200(clarified):
    assert clarified["outcome"] == "clarify"
    assert clarified["confirmation"] is None


async def test_the_question_names_the_id_format(clarified):
    answer = clarified["answer"]
    assert "E1042" in answer, "the clarification shows what a real id looks like"
    assert clarified["answer_blocks"][0]["type"] == "recommendation"


async def test_the_tool_result_is_a_successful_not_found_not_an_error(clarified, store):
    rows = store.execute(
        "SELECT name, status, payload_json FROM spans WHERE turn_id = ? AND kind = 'tool_call' ORDER BY seq",
        (clarified["turn_id"],),
    ).dicts()
    assert [row["name"] for row in rows] == ["lookup_employee_profile"]
    payload = json.loads(rows[0]["payload_json"])

    assert rows[0]["status"] == "ok", "§8.3: a domain not-found is a successful result"
    assert payload["is_error"] is False
    assert payload["arguments"] == {"employee_id": "E1999"}
    body = json.loads(payload["result_json"])
    assert body["code"] == "EMPLOYEE_NOT_FOUND"
    assert body["employee_id"] == "E1999"


async def test_the_turn_row_records_the_clarification(clarified, store):
    row = store.execute(
        "SELECT outcome, stop_reason, final_answer FROM turns WHERE id = ?", (clarified["turn_id"],)
    ).one()
    assert (row["outcome"], row["stop_reason"]) == ("clarify", "clarify")
    assert row["final_answer"] == clarified["answer"]


async def test_no_balance_was_invented_for_an_employee_that_does_not_exist(clarified, store):
    called = [
        row["name"]
        for row in store.execute(
            "SELECT name FROM spans WHERE turn_id = ? AND kind = 'tool_call'", (clarified["turn_id"],)
        ).dicts()
    ]
    assert "check_pto_balance" not in called
    assert clarified["citations"] == []
