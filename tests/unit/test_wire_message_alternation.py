"""The wire conversation the adapters build obeys the Messages API's two structural rules (§9.8).

Anthropic documents both, and both are 400s, not warnings:

* **roles alternate** — no two consecutive `user` messages and no two consecutive `assistant` ones;
* **every `tool_use` block is answered by a `tool_result` block in the immediately following
  message** — not eventually, and not spread over several messages;
* **no message is empty** — an empty content block is a 400 wherever it sits, and the act loop
  makes one every time the model stops with no text and no tool call. Whitespace-only counts as
  empty: `"\n"` is truthy in Python and still an empty block on the wire.

The provider-neutral `Message` carries **one** tool result each (`tool_call_id` is singular), so an
act step that asked for two tools hands the adapter two `tool` messages in a row. Turning each into
its own `{"role": "user", …}` message breaks both rules at once, and nothing in the suite could see
it: `StubAdapter` ignores the message array entirely, and the OpenAI-compatible adapter emits a real
`role: "tool"` message, which is legal there. So the invariants are asserted here, against the bytes
`httpx2.MockTransport` actually received.

`_repair`'s shape is checked too. It is §9.1's one repair round trip, it replays the assistant
message that carries the failed `tool_use`, and it is the only place the loop follows tool results
with a `user` message of its own.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from hrmosaic.core.llm.anthropic import AnthropicAdapter
from hrmosaic.core.llm.base import Message, ToolCall, ToolSchema
from hrmosaic.core.llm.openai_compat import OpenAICompatAdapter

SEARCH = ToolSchema(
    name="search_policy_documents",
    description="Hybrid search over the policy corpus.",
    input_schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
)

CALL_ONE = ToolCall(id="toolu_d1_1", name="lookup_employee_profile", args={"employee_id": "E1042"})
CALL_TWO = ToolCall(id="toolu_d1_2", name="search_policy_documents", args={"query": "remote work"})

#: Exactly what `_act` leaves in `turn.messages` after one act step that asked for two tools —
#: the grouping the committed `demo_task_1.json` uses (2 + 2 + 1).
TWO_TOOL_STEP = [
    Message(role="system", content="You are the Mosaic Robotics HR Copilot."),
    Message(role="user", content="Can I work from Berlin for six weeks?"),
    Message(role="assistant", content="", tool_calls=[CALL_ONE, CALL_TWO]),
    Message(role="tool", tool_call_id=CALL_ONE.id, name=CALL_ONE.name, content='{"employee_id": "E1042"}'),
    Message(role="tool", tool_call_id=CALL_TWO.id, name=CALL_TWO.name, content='{"chunks": []}'),
]


def assert_wire_is_well_formed(messages: list[dict]) -> None:
    """The three Messages API rules, over one recorded request body."""
    roles = [message["role"] for message in messages]
    assert all(first != second for first, second in zip(roles, roles[1:], strict=False)), (
        f"roles must alternate, got {roles}"
    )

    for index, message in enumerate(messages[:-1]):
        content = message["content"]
        assert content, f"message {index} of {len(messages)} is empty and is not the last"
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        for block in blocks:
            if block.get("type") == "text":
                assert block["text"].strip(), f"message {index} carries an empty text block"

    for index, message in enumerate(messages):
        content = message["content"]
        if not isinstance(content, list):
            continue
        asked = [block["id"] for block in content if block.get("type") == "tool_use"]
        if not asked:
            continue
        assert index + 1 < len(messages), f"{asked} was never answered"
        following = messages[index + 1]
        assert following["role"] == "user"
        answered = [
            block["tool_use_id"]
            for block in following["content"]
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        assert answered == asked, f"the next message answers {answered}, the step asked for {asked}"


def send(wire, anthropic_response, messages) -> list[dict]:
    client, recorded = wire([anthropic_response()])
    adapter = AnthropicAdapter(api_key="test-key", http_client=client)
    asyncio.run(adapter.complete(messages, tools=[SEARCH], purpose="act"))
    return recorded[0]["body"]["messages"]


def test_a_two_tool_step_answers_both_calls_in_one_user_message(wire, anthropic_response):
    """One assistant turn, one user turn — both `tool_result` blocks in it, in the asked order."""
    sent = send(wire, anthropic_response, TWO_TOOL_STEP)

    assert [message["role"] for message in sent] == ["user", "assistant", "user"]
    assert [block["type"] for block in sent[1]["content"]] == ["tool_use", "tool_use"]
    assert [block["type"] for block in sent[2]["content"]] == ["tool_result", "tool_result"]
    assert [block["tool_use_id"] for block in sent[2]["content"]] == [CALL_ONE.id, CALL_TWO.id]
    assert_wire_is_well_formed(sent)


def test_the_repair_round_trip_sends_one_assistant_turn_and_one_user_turn(wire, anthropic_response):
    """§9.1's single repair: results first, then the corrective ask, all in the one user message.

    The failing shape this pins was two consecutive `assistant` messages carrying the same
    `tool_use` id — which would have made the repair impossible against the pinned model, so the
    loop could only ever have degraded to `repair_failed`.
    """
    repair = [
        *TWO_TOOL_STEP[:3],
        Message(role="tool", tool_call_id=CALL_ONE.id, name=CALL_ONE.name, content='{"code": "INVALID_ARGUMENTS"}'),
        Message(role="tool", tool_call_id=CALL_TWO.id, name=CALL_TWO.name, content='{"status": "not_run"}'),
        Message(role="user", content="The call to lookup_employee_profile was rejected."),
    ]
    sent = send(wire, anthropic_response, repair)

    assert [message["role"] for message in sent] == ["user", "assistant", "user"]
    assert [block["type"] for block in sent[2]["content"]] == ["tool_result", "tool_result", "text"]
    assert sent[2]["content"][-1]["text"].startswith("The call to lookup_employee_profile")
    assert_wire_is_well_formed(sent)


def test_an_empty_assistant_turn_before_a_reminder_never_reaches_the_wire(wire, anthropic_response):
    """The shape a nudged turn makes: a completion with no text and no tool calls, then a reminder.

    `_act` appends the assistant turn before it knows whether the loop will let the model stop, so
    an empty completion followed by one of §9.1 step 2's reminders leaves a non-final
    `{"role": "assistant", "content": ""}` in the array. The Messages API rejects an empty content
    block with a non-retryable 400 — live, it escaped the loop's own handling and surfaced as the
    web layer's catch-all. The empty turn said nothing and asked for nothing, so it is dropped and
    the reminder joins the user turn it follows.
    """
    reminder = "Not yet — this turn is not finished. The pto_request workflow is incomplete."
    nudged = [
        *TWO_TOOL_STEP[:2],
        Message(role="assistant", content="", tool_calls=[]),
        Message(role="user", content=reminder),
    ]
    sent = send(wire, anthropic_response, nudged)

    assert [message["role"] for message in sent] == ["user"]
    assert [block["text"] for block in sent[0]["content"]] == [TWO_TOOL_STEP[1].content, reminder]
    assert_wire_is_well_formed(sent)


@pytest.mark.parametrize("blank", ["", " ", "\n", "\n  \t "])
def test_a_whitespace_only_assistant_turn_is_dropped_exactly_like_an_empty_one(wire, anthropic_response, blank):
    """A completion of `"\n"` is truthy in Python and still an empty content block on the wire.

    The drop rule reads `not (content or "").strip()`, not plain falsiness: the Messages API's 400
    is about the *rendered* block, so a model that stops with a stray newline would otherwise leave
    a non-final assistant message the provider rejects — the same non-retryable failure the empty
    case already fixed, reached one whitespace character later.
    """
    reminder = "Not yet — this turn is not finished."
    nudged = [
        *TWO_TOOL_STEP[:2],
        Message(role="assistant", content=blank, tool_calls=[]),
        Message(role="user", content=reminder),
    ]
    sent = send(wire, anthropic_response, nudged)

    assert [message["role"] for message in sent] == ["user"]
    assert [block["text"] for block in sent[0]["content"]] == [TWO_TOOL_STEP[1].content, reminder]
    assert_wire_is_well_formed(sent)


def test_a_reminder_after_a_tool_step_answers_the_step_and_stays_in_the_one_user_turn(wire, anthropic_response):
    """The same, one step later: the reminder rides with the `tool_result` blocks that answer the step."""
    reminder = "The user asked for something to be created and this turn has not proposed it yet."
    nudged = [
        *TWO_TOOL_STEP,
        Message(role="assistant", content="", tool_calls=[]),
        Message(role="user", content=reminder),
    ]
    sent = send(wire, anthropic_response, nudged)

    assert [message["role"] for message in sent] == ["user", "assistant", "user"]
    assert [block["type"] for block in sent[2]["content"]] == ["tool_result", "tool_result", "text"]
    assert sent[2]["content"][-1]["text"] == reminder
    assert_wire_is_well_formed(sent)


def test_a_lone_text_message_still_travels_as_a_plain_string(wire, anthropic_response):
    """The coalescing must not reshape the ordinary case: `route` and `synthesize` send strings."""
    sent = send(wire, anthropic_response, TWO_TOOL_STEP[:2])
    assert sent == [{"role": "user", "content": "Can I work from Berlin for six weeks?"}]


def test_the_openai_compatible_failover_answers_each_call_in_its_own_tool_message(wire, openai_response):
    """The other wire shape is unaffected — and it is the failover, so it is checked, not assumed."""
    client, recorded = wire([openai_response()])
    adapter = OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="test-key", http_client=client)

    asyncio.run(adapter.complete(TWO_TOOL_STEP, tools=[SEARCH], purpose="act"))

    sent = recorded[0]["body"]["messages"]
    assert [message["role"] for message in sent] == ["system", "user", "assistant", "tool", "tool"]
    assert [message["tool_call_id"] for message in sent[3:]] == [CALL_ONE.id, CALL_TWO.id]
    assert [call["id"] for call in sent[2]["tool_calls"]] == [CALL_ONE.id, CALL_TWO.id]


@pytest.mark.parametrize("group", [1, 2, 3])
def test_every_grouping_of_one_act_step_is_well_formed(wire, anthropic_response, group):
    """Whatever the model groups into one step, the next message answers exactly that step."""
    calls = [ToolCall(id=f"toolu_{n}", name="search_policy_documents", args={"query": str(n)}) for n in range(group)]
    messages = [
        *TWO_TOOL_STEP[:2],
        Message(role="assistant", content="", tool_calls=calls),
        *[
            Message(role="tool", tool_call_id=call.id, name=call.name, content=json.dumps({"n": index}))
            for index, call in enumerate(calls)
        ],
    ]
    assert_wire_is_well_formed(send(wire, anthropic_response, messages))
