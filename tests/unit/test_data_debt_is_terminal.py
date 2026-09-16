"""An `employee_data` turn reads the record it is about before it answers (W8 fix round, I7).

`live:d3d887f9…:1` — *"Which office am I assigned to?"* for E1108, declined outright with the
profile never read. The data debt used to require a workflow; an `employee_data` turn has none,
so the `DATA_OUTSTANDING` re-entry was unreachable for the class's own exhibit.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent.orchestrator import ChatRequest

pytestmark = pytest.mark.anyio


@pytest.fixture
async def answered_without_reading(run_agent, mounted_mcp_url, store):
    response = await run_agent(
        "data_debt.json",
        ChatRequest(message="Which office am I assigned to?", employee_id="E1108"),
        url=mounted_mcp_url,
    )
    spans = store.execute(
        "SELECT kind, name, seq, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (response.turn_id,)
    ).dicts()
    return response, [{**row, "payload": json.loads(row["payload_json"])} for row in spans]


async def test_the_reminder_fires_and_the_record_is_read_on_the_extra_step(answered_without_reading):
    response, spans = answered_without_reading
    nudges = [nudge for span in spans if span["kind"] == "plan" for nudge in span["payload"].get("nudges") or []]
    profile_calls = [
        span for span in spans if span["kind"] == "tool_call" and span["name"] == "lookup_employee_profile"
    ]

    assert "data_outstanding" in nudges
    assert len(profile_calls) == 1, "the model read the record once, after the reminder"
    assert response.outcome == "answered"


async def test_the_record_was_read_before_the_answer_was_written(answered_without_reading):
    _response, spans = answered_without_reading
    profile = next(span for span in spans if span["kind"] == "tool_call" and span["name"] == "lookup_employee_profile")
    synthesis = next(
        span for span in spans if span["kind"] == "llm_call" and span["payload"].get("purpose") == "synthesize"
    )
    assert profile["seq"] < synthesis["seq"]
