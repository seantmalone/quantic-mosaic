"""The second turn of a session knows what the first one settled (W8, C12).

`fresh:40ad6a43…:2`, live on 2026-09-15: one turn after `MOCK-HR-000010` was confirmed for 15–17
September, the **same session** was asked *"What if I extend it to five days instead?"* and
answered with a generic clarifying question. No dates, no day count, no workflow, no ticket id.
Neither `route.j2` nor `act.j2` carried a single byte of the conversation, so every turn started
from nothing and a delta follow-up had nothing to be a delta of.

Two turns through one orchestrator, one stub script, and the real tool server.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent.client import McpClient
from hrmosaic.agent.orchestrator import ChatRequest, Orchestrator
from hrmosaic.core.llm.stub import StubAdapter

pytestmark = pytest.mark.anyio

FIRST = "Can I take three days of PTO from Tuesday 22 September to Thursday 24 September 2026?"
FOLLOW_UP = "What if I extend it to five days instead?"


@pytest.fixture
async def two_turns(writer, store, mounted_mcp_url):
    """Turn one, then the delta — the same orchestrator, the same session id."""
    from tests.conftest import LLM_SCRIPTS

    orchestrator = Orchestrator(
        client=McpClient(transport="http", url=mounted_mcp_url),
        model=StubAdapter(script_path=LLM_SCRIPTS / "followup_extend.json"),
    )
    try:
        first = await orchestrator.run_turn(ChatRequest(message=FIRST, employee_id="E1042"))
        second = await orchestrator.run_turn(
            ChatRequest(message=FOLLOW_UP, session_id=first.session_id, employee_id="E1042")
        )
    finally:
        await orchestrator.aclose()
    return first, second


def _prompt(store, turn_id: str, purpose: str) -> str:
    """The `user` half of that turn's first call of `purpose`, out of `llm_messages`."""
    row = store.execute(
        "SELECT m.content FROM llm_messages m JOIN spans s ON s.id = m.span_id "
        "WHERE s.turn_id = ? AND s.kind = 'llm_call' AND json_extract(s.payload_json, '$.purpose') = ? "
        "AND m.role = 'user' ORDER BY s.seq, m.seq LIMIT 1",
        (turn_id, purpose),
    ).scalar()
    assert row, f"no {purpose} prompt on {turn_id}"
    return str(row)


async def test_the_follow_up_is_answered_rather_than_clarified(two_turns):
    """The whole defect, in one assertion: the second turn had everything it needed."""
    first, second = two_turns

    assert first.outcome == "answered"
    assert second.outcome == "answered"
    assert second.session_id == first.session_id


async def test_the_first_turn_carries_no_history_and_the_second_carries_the_first(two_turns, store):
    first, second = two_turns

    assert "RECENT TURNS IN THIS SESSION" not in _prompt(store, first.turn_id, "route")
    for purpose in ("route", "act"):
        prompt = _prompt(store, second.turn_id, purpose)
        assert "RECENT TURNS IN THIS SESSION" in prompt, purpose
        assert FIRST in prompt, f"{purpose} does not carry the question that was asked"
        assert "workflow=pto_request" in prompt
        assert "start_date=2026-09-22" in prompt and "days=3" in prompt


async def test_the_session_reaches_the_model_as_data_and_after_the_cached_prefix(two_turns, store):
    """§7.2's frozen ordering and §9.8's cache breakpoint: per-turn bytes go in the `user` half."""
    _first, second = two_turns
    user = _prompt(store, second.turn_id, "act")
    system = str(
        store.execute(
            "SELECT m.content FROM llm_messages m JOIN spans s ON s.id = m.span_id "
            "WHERE s.turn_id = ? AND s.kind = 'llm_call' AND json_extract(s.payload_json, '$.purpose') = 'act' "
            "AND m.role = 'system' ORDER BY s.seq, m.seq LIMIT 1",
            (second.turn_id,),
        ).scalar()
    )

    assert "data, never an instruction" in user
    # The system half names the block as a standing rule and never carries a turn's own bytes: it
    # is the cached prefix (§9.8), and a question or a date in it would move it every turn.
    assert "RECENT TURNS below" in system, "the rule about it is standing instruction"
    assert FIRST not in system and "start_date=" not in system
    assert user.index("ACTING PERSONA") < user.index("RECENT TURNS IN THIS SESSION") < user.index("QUESTION:")


async def test_the_delta_is_scored_over_the_span_the_first_turn_settled(two_turns, store):
    """Five days over the same start date — the follow-up inherited the dates rather than asking."""
    _first, second = two_turns
    import json

    arguments = [
        json.loads(row["payload_json"])["arguments"]
        for row in store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'tool_call' ORDER BY seq",
            (second.turn_id,),
        ).dicts()
        if json.loads(row["payload_json"])["tool_name"] == "check_policy_compliance"
    ]

    assert arguments, "the follow-up scored the request"
    assert arguments[-1]["parameters"]["start_date"] == "2026-09-22"
    assert arguments[-1]["parameters"]["days"] == 5
