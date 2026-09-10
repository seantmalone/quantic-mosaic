"""The message array a real act loop builds is one the pinned model would accept (§9.1, §9.8).

`tests/unit/test_wire_message_alternation.py` pins the adapter's translation against hand-built
arrays. This file closes the other half: it drives the **real** loop over a **real** MCP server with
the committed `demo_task_1.json` script — whose act steps group 2 + 2 + 1 tool calls, which is the
grouping that made the wire conversation illegal — and translates every array the loop actually
handed the model.

`StubAdapter` never looks at `messages`, so no stub-driven test can see a malformed conversation. The
recorder below is not a mock of anything: it forwards every call to the same `StubAdapter` the rest
of the suite uses and keeps a copy of the array it was given, and the assertion runs that copy
through the shipped `AnthropicAdapter.request_kwargs`.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent.client import McpClient
from hrmosaic.agent.orchestrator import ChatRequest, Orchestrator
from hrmosaic.core.llm.anthropic import AnthropicAdapter
from hrmosaic.core.llm.stub import StubAdapter
from tests.conftest import LLM_SCRIPTS
from tests.unit.test_wire_message_alternation import assert_wire_is_well_formed

pytestmark = pytest.mark.anyio

QUESTION = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"


class _Recorder:
    """`StubAdapter`, plus a copy of every message array it was asked to complete."""

    def __init__(self, script):
        self._inner = StubAdapter(script_path=script)
        self.provider = self._inner.provider
        self.model = self._inner.model
        self.calls: list[tuple[str, list]] = []

    async def complete(self, messages, **kwargs):
        self.calls.append((kwargs.get("purpose", "act"), list(messages)))
        return await self._inner.complete(messages, **kwargs)


async def test_every_act_call_of_demo_task_1_is_a_legal_messages_request(writer):
    recorder = _Recorder(LLM_SCRIPTS / "demo_task_1.json")
    orchestrator = Orchestrator(client=McpClient(transport="stdio"), model=recorder)
    try:
        answered = await orchestrator.run_turn(ChatRequest(message=QUESTION, employee_id="E1042"))
    finally:
        await orchestrator.aclose()

    assert answered.outcome == "answered"
    act_calls = [messages for purpose, messages in recorder.calls if purpose == "act"]
    assert len(act_calls) == 3, "demo task 1 is three act steps grouping 2 + 2 + 1 tool calls"

    adapter = AnthropicAdapter(api_key=None)
    for messages in act_calls:
        sent = adapter.request_kwargs(messages, purpose="act")["messages"]
        assert_wire_is_well_formed(sent)

    # The step that asked for two tools is the one the old shape broke: both results have to land
    # in the single user message that follows the assistant turn carrying both `tool_use` blocks.
    widest = adapter.request_kwargs(act_calls[-1], purpose="act")["messages"]
    answers = [block["tool_use_id"] for block in widest[-1]["content"] if block["type"] == "tool_result"]
    assert len(answers) == 2, answers
