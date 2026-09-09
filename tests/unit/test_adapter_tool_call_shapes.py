"""Tool-call arguments normalise to the same dict on both wire shapes (spec §3 row 5, §9.8).

OpenAI-compatible endpoints deliver `function.arguments` as a JSON **string**; Anthropic delivers
`tool_use.input` as a parsed **object**. The requirement is that neither shape leaks past the
adapter boundary: the agent loop sees one `ToolCall` type whose `args` is a dict, and the
`llm_call` span records the same dict either way. String-matching a JSON blob instead of parsing it
is the concrete failure this file forbids.

The published tool definitions travel with them, so this is also where "no `strict` on the tool
definitions" is checked against real request bytes (§8.4).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from hrmosaic.core.llm.anthropic import AnthropicAdapter
from hrmosaic.core.llm.base import Message, ProviderError, ToolCall, ToolSchema
from hrmosaic.core.llm.openai_compat import OpenAICompatAdapter

# One of the nine published schemas (§8.4), with its `default` intact — the very thing strict tool
# use would reject, which is why the adapters must not declare it.
CHECK_PTO_BALANCE = ToolSchema(
    name="check_pto_balance",
    description="PTO balance for an employee at the mock-data snapshot.",
    input_schema={
        "type": "object",
        "required": ["employee_id"],
        "properties": {
            "employee_id": {"type": "string", "pattern": "^E1[0-9]{3}$"},
            "as_of": {"type": "string"},
            "k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
        },
    },
)

EXPECTED_ARGS = {"employee_id": "E1042", "as_of": "2026-09-15"}

MESSAGES = [
    Message(role="system", content="You are the Mosaic HR Copilot."),
    Message(role="user", content="How much PTO do I have left?"),
]


def test_anthropic_object_arguments_become_a_dict(wire, anthropic_response):
    client, recorded = wire(
        [
            anthropic_response(
                content=[{"type": "tool_use", "id": "toolu_1", "name": "check_pto_balance", "input": EXPECTED_ARGS}],
                stop_reason="tool_use",
            )
        ]
    )
    adapter = AnthropicAdapter(api_key="test-key", http_client=client)

    completion = asyncio.run(adapter.complete(MESSAGES, tools=[CHECK_PTO_BALANCE], purpose="act"))

    assert completion.tool_calls == [ToolCall(id="toolu_1", name="check_pto_balance", args=EXPECTED_ARGS)]
    assert completion.finish_reason == "tool_use"
    body = recorded[0]["body"]
    assert body["tools"] == [
        {
            "name": CHECK_PTO_BALANCE.name,
            "description": CHECK_PTO_BALANCE.description,
            "input_schema": CHECK_PTO_BALANCE.input_schema,
        }
    ]
    # As published: the `default` survives and nothing declares the tool strict (§8.4).
    assert "strict" not in json.dumps(body["tools"])
    assert body["tools"][0]["input_schema"]["properties"]["k"]["default"] == 5


def test_openai_string_arguments_become_the_same_dict(wire, openai_response):
    client, recorded = wire(
        [
            openai_response(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "check_pto_balance", "arguments": json.dumps(EXPECTED_ARGS)},
                    }
                ],
            )
        ]
    )
    adapter = OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="test-key", http_client=client)

    completion = asyncio.run(adapter.complete(MESSAGES, tools=[CHECK_PTO_BALANCE], purpose="act"))

    assert completion.tool_calls == [ToolCall(id="call_1", name="check_pto_balance", args=EXPECTED_ARGS)]
    assert completion.finish_reason == "tool_calls"
    # The arguments went out as a JSON string too — the wire shape really is the other one.
    sent = recorded[0]["body"]["tools"][0]
    assert sent["type"] == "function"
    assert sent["function"]["parameters"] == CHECK_PTO_BALANCE.input_schema


def test_both_adapters_agree_on_the_normalised_arguments(wire, anthropic_response, openai_response):
    anthropic_client, _ = wire(
        [
            anthropic_response(
                content=[{"type": "tool_use", "id": "toolu_1", "name": "check_pto_balance", "input": EXPECTED_ARGS}],
                stop_reason="tool_use",
            )
        ]
    )
    openai_client, _ = wire(
        [
            openai_response(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "check_pto_balance", "arguments": json.dumps(EXPECTED_ARGS)},
                    }
                ],
            )
        ]
    )
    native = asyncio.run(
        AnthropicAdapter(api_key="k", http_client=anthropic_client).complete(MESSAGES, tools=[CHECK_PTO_BALANCE])
    )
    compat = asyncio.run(
        OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=openai_client).complete(
            MESSAGES, tools=[CHECK_PTO_BALANCE]
        )
    )

    assert [(call.name, call.args) for call in native.tool_calls] == [
        (call.name, call.args) for call in compat.tool_calls
    ]


def test_the_cache_breakpoint_sits_on_the_last_system_block(wire, anthropic_response):
    client, recorded = wire([anthropic_response()])
    adapter = AnthropicAdapter(api_key="k", http_client=client)

    asyncio.run(
        adapter.complete(
            [
                Message(role="system", content="Standing rules."),
                Message(role="system", content="Tool catalogue notes."),
                Message(role="user", content="hello"),
            ],
            tools=[CHECK_PTO_BALANCE],
            purpose="route",
        )
    )

    body = recorded[0]["body"]
    assert [block.get("cache_control") for block in body["system"]] == [None, {"type": "ephemeral"}]
    # The 1.x SDK has no `temperature` keyword; the field still has to reach the API.
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 1024


def test_unparseable_openai_arguments_are_an_error_not_a_string_match(wire, openai_response):
    client, _ = wire(
        [
            openai_response(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "check_pto_balance", "arguments": "{oops"},
                    }
                ],
            )
        ]
    )
    adapter = OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=client)

    with pytest.raises(ProviderError, match="not JSON"):
        asyncio.run(adapter.complete(MESSAGES, tools=[CHECK_PTO_BALANCE]))


def test_a_tool_result_round_trips_through_both_wire_shapes(wire, anthropic_response, openai_response):
    conversation = [
        Message(role="user", content="How much PTO do I have left?"),
        Message(role="assistant", tool_calls=[ToolCall(id="t1", name="check_pto_balance", args=EXPECTED_ARGS)]),
        Message(role="tool", tool_call_id="t1", name="check_pto_balance", content='{"remaining_days": 13.5}'),
    ]

    anthropic_client, anthropic_recorded = wire([anthropic_response()])
    asyncio.run(AnthropicAdapter(api_key="k", http_client=anthropic_client).complete(conversation))
    anthropic_body = anthropic_recorded[0]["body"]
    assert anthropic_body["messages"][1]["content"][0]["input"] == EXPECTED_ARGS
    assert anthropic_body["messages"][2]["content"][0]["type"] == "tool_result"

    openai_client, openai_recorded = wire([openai_response()])
    asyncio.run(
        OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=openai_client).complete(
            conversation
        )
    )
    openai_body = openai_recorded[0]["body"]
    # Out on the OpenAI wire, the same arguments are a JSON string again.
    assert json.loads(openai_body["messages"][1]["tool_calls"][0]["function"]["arguments"]) == EXPECTED_ARGS
    assert openai_body["messages"][2]["role"] == "tool"


# `get_policy_section` as §8.4 publishes it: `doc_id` required, exactly one selector, expressed as a
# root-level `oneOf`. The Messages API returns 400 on that keyword (verified live, 2026-09-09).
GET_POLICY_SECTION = ToolSchema(
    name="get_policy_section",
    description="Verbatim section text; exactly one of heading_path or chunk_id.",
    input_schema={
        "type": "object",
        "required": ["doc_id"],
        "properties": {
            "doc_id": {"type": "string"},
            "heading_path": {"type": "string"},
            "chunk_id": {"type": "string"},
            "include_neighbors": {"type": "boolean", "default": False},
        },
        "oneOf": [{"required": ["heading_path"]}, {"required": ["chunk_id"]}],
    },
)


def test_a_root_level_oneof_is_dropped_and_nothing_else_is(wire, anthropic_response):
    client, recorded = wire([anthropic_response()])
    adapter = AnthropicAdapter(api_key="k", http_client=client)

    asyncio.run(adapter.complete(MESSAGES, tools=[GET_POLICY_SECTION]))

    sent = recorded[0]["body"]["tools"][0]["input_schema"]
    assert "oneOf" not in sent, "the Messages API rejects oneOf/allOf/anyOf at the top level"
    assert sent["required"] == ["doc_id"]
    assert sent["properties"] == GET_POLICY_SECTION.input_schema["properties"]
    # The published schema is untouched: the MCP server still validates the selector rule (§8.4).
    assert "oneOf" in GET_POLICY_SECTION.input_schema


def test_the_span_records_the_configured_model_not_the_dated_snapshot(wire, anthropic_response):
    client, _ = wire([anthropic_response(model="claude-haiku-4-5-20251001")])
    adapter = AnthropicAdapter(api_key="k", http_client=client)

    completion = asyncio.run(adapter.complete(MESSAGES))

    # `MODEL_PRICES` and the §10.1 span name key on the configured id, so a snapshot roll must not
    # silently drop the cost estimate to zero.
    assert completion.model == "claude-haiku-4-5"
    assert completion.cost_usd_estimate > 0
