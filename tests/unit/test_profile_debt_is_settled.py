"""A verdict or a balance computed with the profile never read is a data debt (W9 addendum, ruling 3).

`remote-003` and `unsafe-001` scored tool recall 0.67 / 0.75: `check_policy_compliance` or
`check_pto_balance` was called for the acting employee and `lookup_employee_profile` never was.
The data-debt gate now fires for that shape — one re-entry asking for the profile, before
synthesis — and on a confirmed write too.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent.orchestrator import ChatRequest

pytestmark = pytest.mark.anyio


@pytest.fixture
async def balance_without_profile(run_agent, mounted_mcp_url, store):
    response = await run_agent(
        "profile_debt.json",
        ChatRequest(message="How many PTO days do I have?", employee_id="E1042"),
        url=mounted_mcp_url,
    )
    spans = store.execute(
        "SELECT kind, name, seq, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (response.turn_id,)
    ).dicts()
    return response, [{**row, "payload": json.loads(row["payload_json"])} for row in spans]


async def test_the_profile_is_read_once_after_the_reminder_and_before_synthesis(balance_without_profile):
    response, spans = balance_without_profile
    nudges = [nudge for span in spans if span["kind"] == "plan" for nudge in span["payload"].get("nudges") or []]
    profile = [span for span in spans if span["kind"] == "tool_call" and span["name"] == "lookup_employee_profile"]
    balance = next(span for span in spans if span["kind"] == "tool_call" and span["name"] == "check_pto_balance")
    synthesis = next(
        span for span in spans if span["kind"] == "llm_call" and span["payload"].get("purpose") == "synthesize"
    )
    assert "data_outstanding" in nudges
    assert len(profile) == 1, "one re-entry, one profile read"
    assert balance["seq"] < profile[0]["seq"] < synthesis["seq"]
    assert response.outcome == "answered"


async def test_the_reminder_names_the_profile(balance_without_profile):
    _response, spans = balance_without_profile
    summaries = [
        line for span in spans if span["kind"] == "plan" for line in span["payload"].get("step_summaries") or []
    ]
    assert any("profile unread" in line for line in summaries), summaries
