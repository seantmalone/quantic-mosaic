"""Constrained JSON is emitted strict, at every level (spec §7.3, §9.8).

Two halves, and both matter:

1. **the schema** — for every model used as a response schema, `required == list(properties)` and
   `additionalProperties is False` at *every* object level, because a Pydantic field carrying a
   default emits a schema strict mode rejects, and a nested model without `extra="forbid"` fails
   only on the nested level a shallow check would miss;
2. **the emission** — the schema that reaches the wire is exactly that one, in
   `output_config.format` on the Anthropic path and in `response_format.json_schema` with
   `strict: true` on the OpenAI-compatible path. A schema that is strict in a unit test and lax on
   the wire buys nothing.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from hrmosaic.core.llm.anthropic import AnthropicAdapter
from hrmosaic.core.llm.base import Message
from hrmosaic.core.llm.openai_compat import OpenAICompatAdapter
from hrmosaic.core.models import AnswerBlock, AnswerSchema, Citation, strict_json_schema

#: Every model the adapters are asked to constrain output to. §7.3's answer models today; the
#: router and repair schemas of §9.1 join the list at P7 by being added here.
RESPONSE_SCHEMAS = [AnswerSchema, AnswerBlock, Citation]

MESSAGES = [Message(role="user", content="Summarise the remote-work rules.")]


def _object_levels(node: Any, path: str = "$"):
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            yield path, node
        for key, value in node.items():
            yield from _object_levels(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _object_levels(item, f"{path}[{index}]")


@pytest.mark.parametrize("model", RESPONSE_SCHEMAS, ids=lambda model: model.__name__)
def test_every_response_schema_is_strict_at_every_level(model):
    schema = strict_json_schema(model)

    levels = list(_object_levels(schema))
    assert levels, f"{model.__name__} emitted no object level to check"
    for path, level in levels:
        assert level["required"] == list(level["properties"]), path
        assert level["additionalProperties"] is False, path
    assert "$defs" not in schema and "$ref" not in str(schema)


def test_a_field_with_a_default_is_rejected():
    class Lax(BaseModel):
        model_config = ConfigDict(extra="forbid")
        answer: str = "unknown"

    with pytest.raises(ValueError, match="required"):
        strict_json_schema(Lax)


def test_a_nested_model_that_allows_extras_is_rejected():
    class Inner(BaseModel):
        value: str

    class Outer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        inner: Inner

    with pytest.raises(ValueError, match="additionalProperties"):
        strict_json_schema(Outer)


def test_anthropic_emits_the_schema_in_output_config(wire, anthropic_response):
    client, recorded = wire([anthropic_response(content=[{"type": "text", "text": "{}"}])])
    adapter = AnthropicAdapter(api_key="k", http_client=client)

    completion = asyncio.run(adapter.complete(MESSAGES, response_schema=AnswerSchema, purpose="synthesize"))

    body = recorded[0]["body"]
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": strict_json_schema(AnswerSchema)}}
    # There is no prompted-JSON fallback on this path: nothing was appended to the messages.
    assert body["messages"] == [{"role": "user", "content": MESSAGES[0].content}]
    assert body["max_tokens"] == 2048
    assert completion.structured_output_mode == "output_config_json_schema"


def test_openai_compat_emits_the_schema_strict(wire, openai_response):
    client, recorded = wire([openai_response(content="{}")])
    adapter = OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=client)

    completion = asyncio.run(adapter.complete(MESSAGES, response_schema=AnswerSchema, purpose="judge"))

    assert recorded[0]["body"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "AnswerSchema", "strict": True, "schema": strict_json_schema(AnswerSchema)},
    }
    assert completion.structured_output_mode == "json_schema_strict"


def test_openai_compat_falls_back_to_prompted_json_then_repairs(wire, openai_response):
    rejection = (
        400,
        {"error": {"message": "Invalid value: 'json_schema' is not supported for response_format", "type": "invalid"}},
    )
    client, recorded = wire(
        [
            rejection,
            openai_response(content="here you go: not json at all"),
            openai_response(content='```json\n{"blocks": [], "next_steps": [], "rationale_summary": "x"}\n```'),
        ]
    )
    adapter = OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=client)

    completion = asyncio.run(adapter.complete(MESSAGES, response_schema=AnswerSchema, purpose="judge"))

    assert completion.structured_output_mode == "prompted_json_repair"
    assert completion.parsed_json() == {"blocks": [], "next_steps": [], "rationale_summary": "x"}
    # Three round trips: strict (rejected), prompted, one repair — and no more.
    assert len(recorded) == 3
    assert "response_format" not in recorded[1]["body"]
    prompted = recorded[1]["body"]["messages"][-1]["content"]
    assert "additionalProperties" in prompted  # the same strict schema, prompted instead


def test_prompted_json_needs_no_repair_when_it_parses(wire, openai_response):
    rejection = (400, {"error": {"message": "response_format json_schema unsupported", "type": "invalid"}})
    client, recorded = wire(
        [rejection, openai_response(content='{"blocks": [], "next_steps": [], "rationale_summary": "x"}')]
    )
    adapter = OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=client)

    completion = asyncio.run(adapter.complete(MESSAGES, response_schema=AnswerSchema))

    assert completion.structured_output_mode == "prompted_json"
    assert len(recorded) == 2
