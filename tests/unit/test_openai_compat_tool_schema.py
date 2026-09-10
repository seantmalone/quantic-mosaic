"""The OpenAI-compatible adapter drops the root combinator too (spec §8.4, §9.8).

`get_policy_section` publishes a root `oneOf` because §8.4 requires its exactly-one-selector rule
*in the schema, not only in prose*. The Anthropic Messages API rejects a top-level combinator on a
tool's `input_schema` and `AnthropicAdapter` has stripped it since P6 — but Gemini is **both** the
judge and the agent's failover, and the documented zero-cost path runs the whole agent through
`OpenAICompatAdapter`, so a stripper in one adapter only would send the schema Gemini refuses on
exactly the path a live demo falls back to.

So the rule and its one implementation live in `base.py` and both adapters call it. Everything here
is asserted against the **committed** `mcp/tools/*.schema.json` — the bytes the live server
publishes — rather than a hand-written fixture that might match no schema at all.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from hrmosaic.core.llm.anthropic import AnthropicAdapter, _tool_payload
from hrmosaic.core.llm.base import ROOT_COMBINATOR_KEYS, Message, ToolSchema, without_root_combinators
from hrmosaic.core.llm.openai_compat import OpenAICompatAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED = REPO_ROOT / "mcp" / "tools"

MESSAGES = [Message(role="user", content="Quote the approval section of the remote-work policy.")]


def published(name: str) -> ToolSchema:
    body = json.loads((COMMITTED / f"{name}.schema.json").read_text(encoding="utf-8"))
    return ToolSchema(name=body["name"], description=body.get("description", ""), input_schema=body["input_schema"])


def every_published_tool() -> list[ToolSchema]:
    return [published(path.name.removesuffix(".schema.json")) for path in sorted(COMMITTED.glob("*.schema.json"))]


def test_the_published_schema_really_does_carry_a_root_combinator():
    """A vacuous pass would be worse than no test: prove there is something to strip."""
    schema = published("get_policy_section").input_schema
    assert "oneOf" in schema
    assert schema["oneOf"] == [{"required": ["heading_path"]}, {"required": ["chunk_id"]}]


def test_the_openai_shape_carries_no_root_combinator():
    adapter = OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k")
    tools = adapter.request_kwargs(MESSAGES, tools=every_published_tool())["tools"]

    assert len(tools) == 9
    for tool in tools:
        parameters = tool["function"]["parameters"]
        assert [key for key in ROOT_COMBINATOR_KEYS if key in parameters] == [], tool["function"]["name"]


def test_nothing_but_the_combinator_is_dropped():
    original = published("get_policy_section").input_schema
    stripped = without_root_combinators(original)

    assert set(original) - set(stripped) == {"oneOf"}
    assert stripped["properties"] == original["properties"]
    assert stripped["required"] == original["required"]
    assert stripped["properties"]["include_neighbors"]["default"] is False, "defaults travel as published"


def test_a_schema_with_no_combinator_is_returned_unchanged():
    original = published("search_policy_documents").input_schema
    assert without_root_combinators(original) is original


def test_the_published_schema_is_never_rewritten():
    """§8.4: the committed schema stays the one the MCP server validates arguments against."""
    tool = published("get_policy_section")
    OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k").request_kwargs(MESSAGES, tools=[tool])
    _tool_payload(tool)
    assert "oneOf" in tool.input_schema


def test_a_nested_combinator_survives():
    tool = ToolSchema(
        name="nested",
        input_schema={
            "type": "object",
            "properties": {"selector": {"oneOf": [{"type": "string"}, {"type": "integer"}]}},
            "oneOf": [{"required": ["selector"]}],
        },
    )
    parameters = OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k").request_kwargs(
        MESSAGES, tools=[tool]
    )["tools"][0]["function"]["parameters"]
    assert "oneOf" not in parameters
    assert parameters["properties"]["selector"]["oneOf"], "only the TOP level is unsupported"


def test_both_adapters_send_the_same_stripped_schema_on_the_real_wire(wire, openai_response, anthropic_response):
    tool = published("get_policy_section")

    openai_client, openai_recorded = wire([openai_response(content="ok")])
    asyncio.run(
        OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=openai_client).complete(
            MESSAGES, tools=[tool]
        )
    )
    anthropic_client, anthropic_recorded = wire([anthropic_response()])
    asyncio.run(AnthropicAdapter(api_key="k", http_client=anthropic_client).complete(MESSAGES, tools=[tool]))

    sent_openai = openai_recorded[0]["body"]["tools"][0]["function"]["parameters"]
    sent_anthropic = anthropic_recorded[0]["body"]["tools"][0]["input_schema"]
    assert sent_openai == sent_anthropic == without_root_combinators(tool.input_schema)
