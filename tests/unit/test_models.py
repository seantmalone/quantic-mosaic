"""`core/models.py` — the strict-JSON-schema contract, the §7.3 answer models and the price table.

`strict_json_schema()` is what makes `AnswerSchema` usable as P6's constrained-JSON schema, and it
rests on two invariants nothing else pins: Pydantic emits `required` in `properties` order, and
`$defs` inlining survives nesting (`AnswerSchema.blocks[].items` is a `$ref`). Both are asserted
here, so a Pydantic upgrade that changes either fails in P1 rather than inside a provider call.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from hrmosaic.core.models import (
    MODEL_PRICES,
    AnswerBlock,
    AnswerSchema,
    Citation,
    TraceEntry,
    estimate_cost_usd,
    parse_payload,
    strict_json_schema,
)

# --------------------------------------------------------------------------------------
# strict_json_schema (§7.3)
# --------------------------------------------------------------------------------------


def object_levels(node, path="$"):
    """Every JSON-schema object level in `node`, as `(path, schema)` pairs."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            yield path, node
        for key, value in node.items():
            yield from object_levels(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from object_levels(item, f"{path}[{index}]")


def test_answer_schema_inlines_every_def_and_is_strict_at_every_level():
    schema = strict_json_schema(AnswerSchema)

    assert "$defs" not in schema
    assert "$ref" not in json.dumps(schema), "a surviving $ref would be rejected by strict mode"

    levels = dict(object_levels(schema))
    # the nested level is the one that only exists because `$defs` was inlined
    assert "$.properties.blocks.items" in levels, levels.keys()
    for path, level in levels.items():
        assert level["required"] == list(level["properties"]), path
        assert level["additionalProperties"] is False, path

    block = levels["$.properties.blocks.items"]
    assert block["required"] == ["type", "text", "citations"]


def test_citation_is_strict_and_lists_all_nine_fields():
    schema = strict_json_schema(Citation)
    assert schema["required"] == list(schema["properties"]) == list(Citation.model_fields)
    assert schema["additionalProperties"] is False


def test_a_model_carrying_a_default_is_rejected():
    """`TraceEntry` is a projection model, not a schema model: six of its fields have defaults."""
    with pytest.raises(ValueError, match="required .* != properties"):
        strict_json_schema(TraceEntry)


def test_a_model_without_extra_forbid_is_rejected():
    class Loose(BaseModel):
        answer: str

    with pytest.raises(ValueError, match="additionalProperties must be false"):
        strict_json_schema(Loose)


def test_a_nested_model_without_extra_forbid_is_rejected_at_its_own_level():
    class LooseInner(BaseModel):
        note: str

    class StrictOuter(BaseModel):
        model_config = ConfigDict(extra="forbid")
        inner: LooseInner

    with pytest.raises(ValueError, match="additionalProperties must be false"):
        strict_json_schema(StrictOuter)


# --------------------------------------------------------------------------------------
# The §7.3 answer view-models
# --------------------------------------------------------------------------------------


def test_a_policy_fact_block_must_carry_a_citation():
    with pytest.raises(ValidationError, match="at least one citation"):
        AnswerBlock(type="policy_fact", text="Full-time employees accrue 1.5 days a month.", citations=[])


def test_a_recommendation_block_may_stand_uncited():
    block = AnswerBlock(type="recommendation", text="File the request before you book.", citations=[])
    assert block.citations == []


def test_an_answer_block_rejects_an_unknown_type_and_an_extra_field():
    with pytest.raises(ValidationError):
        AnswerBlock(type="opinion", text="…", citations=["c_1b7e"])
    with pytest.raises(ValidationError):
        AnswerBlock(type="escalation", text="…", citations=[], confidence=0.9)


def test_answer_schema_round_trips_a_complete_answer():
    answer = AnswerSchema(
        blocks=[AnswerBlock(type="policy_fact", text="You accrue 1.5 days a month.", citations=["c_1b7e"])],
        next_steps=["Open a PTO request in Workday."],
        rationale_summary="Quoted the accrual table for a full-time employee.",
    )
    assert AnswerSchema.model_validate_json(answer.model_dump_json()) == answer


# --------------------------------------------------------------------------------------
# parse_payload (§10.2)
# --------------------------------------------------------------------------------------


def test_parse_payload_returns_the_typed_member_of_the_union():
    parsed = parse_payload({"kind": "guardrail", "rule_id": "G6", "rule_name": "redact", "verdict": "allow"})
    assert parsed.rule_id == "G6"
    assert parsed.verdict == "allow"


def test_parse_payload_rejects_an_unknown_kind():
    with pytest.raises(ValidationError):
        parse_payload({"kind": "telemetry", "value": 1})


def test_parse_payload_rejects_an_extra_field():
    with pytest.raises(ValidationError):
        parse_payload({"kind": "plan", "intent": "pto_balance", "chain_of_thought": "…"})


# --------------------------------------------------------------------------------------
# Cost accounting (§9.8)
# --------------------------------------------------------------------------------------


def test_every_priced_model_bills_each_bucket_per_million_tokens():
    for model, prices in MODEL_PRICES.items():
        assert set(prices) == {"input", "output", "cache_write", "cache_read"}
        assert estimate_cost_usd(model, prompt_tokens=1_000_000) == pytest.approx(prices["input"])
        assert estimate_cost_usd(model, completion_tokens=1_000_000) == pytest.approx(prices["output"])
        assert estimate_cost_usd(model, cache_creation_input_tokens=1_000_000) == pytest.approx(prices["cache_write"])
        assert estimate_cost_usd(model, cache_read_input_tokens=1_000_000) == pytest.approx(prices["cache_read"])


def test_the_pinned_agent_model_is_priced_and_the_buckets_add_up():
    assert estimate_cost_usd("claude-haiku-4-5", prompt_tokens=1_000_000) == pytest.approx(1.00)
    combined = estimate_cost_usd(
        "claude-haiku-4-5",
        prompt_tokens=7_412,
        completion_tokens=883,
        cache_creation_input_tokens=4_096,
        cache_read_input_tokens=12_288,
    )
    expected = (7_412 * 1.00 + 883 * 5.00 + 4_096 * 1.25 + 12_288 * 0.10) / 1_000_000
    assert combined == pytest.approx(expected)


def test_the_judge_model_is_priced_at_the_paid_standard_rates():
    """Paid billing was enabled on the judge project on 2026-09-10; a $0 entry under-reports spend."""
    prices = MODEL_PRICES["gemini-3.5-flash-lite"]
    assert prices["input"] > 0.0 and prices["output"] > 0.0, "the free-tier $0 entry is no longer true"
    assert estimate_cost_usd("gemini-3.5-flash-lite", prompt_tokens=1_000, completion_tokens=100) == pytest.approx(
        (1_000 * 0.30 + 100 * 2.50) / 1_000_000
    )


def test_an_unpriced_model_and_a_call_with_no_tokens_both_estimate_zero():
    assert estimate_cost_usd("some-model-nobody-priced", prompt_tokens=1_000_000) == 0.0
    assert estimate_cost_usd("claude-haiku-4-5") == 0.0
