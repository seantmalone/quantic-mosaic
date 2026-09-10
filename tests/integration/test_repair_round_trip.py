"""§9.1's one repair round trip, over a real MCP server that really rejected the arguments.

The repair request replays `turn.messages`, which **already ends** with the assistant message
carrying the failed `tool_use` — so the two things that can go wrong are structural, not semantic:
re-appending that assistant message (two consecutive assistant turns with the same `tool_use` id,
the first pair unanswered) and leaving the step's *other* `tool_use` unanswered while the loop is
still inside the first call. Either is a 400 on the pinned model, which would make the mandated
single repair impossible and degrade every schema violation to `repair_failed`.

Nothing here is a mock: `check_pto_balance` is called with `employee_id: "me"` against the shipped
server, whose committed schema really does reject it, and the corrected call really does succeed.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent.client import McpClient
from hrmosaic.agent.orchestrator import ChatRequest, Orchestrator
from hrmosaic.core.llm.anthropic import AnthropicAdapter
from tests.conftest import LLM_SCRIPTS
from tests.integration.test_act_loop_wire_shape import _Recorder
from tests.unit.test_wire_message_alternation import assert_wire_is_well_formed

pytestmark = pytest.mark.anyio

QUESTION = "How much PTO do I have left, and how does it accrue?"


@pytest.fixture
async def repaired(writer):
    recorder = _Recorder(LLM_SCRIPTS / "repair_round_trip.json")
    orchestrator = Orchestrator(client=McpClient(transport="stdio"), model=recorder)
    try:
        response = await orchestrator.run_turn(ChatRequest(message=QUESTION, employee_id="E1042"))
    finally:
        await orchestrator.aclose()
    return response, recorder


async def test_the_rejected_call_was_repaired_and_re_issued(repaired, spans):
    response, recorder = repaired
    records = spans(response.turn_id)

    calls = [(payload["tool_name"], payload["is_error"]) for kind, _, payload in records if kind == "tool_call"]
    assert ("check_pto_balance", True) in calls, "the schema violation really happened"
    assert ("check_pto_balance", False) in calls, "and the repaired arguments really worked"
    assert [purpose for purpose, _ in recorder.calls].count("repair") == 1, "never twice (§9.1)"
    assert not any(payload["error_kind"] == "repair_failed" for kind, _, payload in records if kind == "error")
    assert response.outcome == "answered"


async def test_the_repair_request_is_a_legal_messages_request(repaired):
    """One assistant turn, then one user turn carrying every result plus the corrective ask."""
    _, recorder = repaired
    messages = next(sent for purpose, sent in recorder.calls if purpose == "repair")

    sent = AnthropicAdapter(api_key=None).request_kwargs(messages, purpose="repair")["messages"]
    assert_wire_is_well_formed(sent)
    assert [message["role"] for message in sent] == ["user", "assistant", "user"]

    asked = [block["id"] for block in sent[1]["content"] if block["type"] == "tool_use"]
    blocks = sent[2]["content"]
    assert [block["tool_use_id"] for block in blocks if block["type"] == "tool_result"] == asked
    assert blocks[-1]["type"] == "text" and "was rejected" in blocks[-1]["text"]


async def test_the_assistant_turn_carrying_the_failed_call_is_sent_exactly_once(repaired):
    """The bug this pins: `turn.messages` already holds it, so re-appending duplicated the id."""
    _, recorder = repaired
    messages = next(sent for purpose, sent in recorder.calls if purpose == "repair")

    ids = [call.id for message in messages for call in message.tool_calls]
    assert len(ids) == len(set(ids)), ids
    assert [message.role for message in messages].count("assistant") == 1
