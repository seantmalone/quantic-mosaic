"""No hidden chain-of-thought anywhere in the record (spec §9.7, R4.3).

`plan` spans carry `intent`, `workflow`, `selected_tools[]`, `step_summaries[]` and a one-line
`rationale_summary` — **operational records only, never reasoning**. The contract §9.7 states has two
clauses, and both are asserted here in every place a payload can come from:

1. no span-payload field is named `reasoning`, `thoughts` or `chain_of_thought` — checked against the
   §10.2 discriminated union itself, against the three constrained-JSON schemas the agent asks the
   model to fill, against the committed golden traces, and against the spans a real turn writes;
2. `rationale_summary` is **≤ 200 characters** — checked on the clamp, on the router's normalisation
   of a model-supplied decision, and on the persisted payloads.

The reason it is a *contract* test rather than a style note: a field called `reasoning` would be the
one place a future phase could park raw chain-of-thought and have it rendered on a dashboard page
that the assignment explicitly asks not to expose.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hrmosaic.agent import prompts
from hrmosaic.agent.orchestrator import ChatRequest, ToolCallRepair
from hrmosaic.agent.router import MAX_RATIONALE_CHARS, RouteDecision, clamp_rationale, normalise
from hrmosaic.core.models import PAYLOAD_MODELS, AnswerSchema, strict_json_schema

pytestmark = pytest.mark.anyio

#: The three names §9.7 forbids, plus the two spellings a future phase would reach for first.
FORBIDDEN = ("reasoning", "thoughts", "chain_of_thought", "thinking", "scratchpad")

TRACES = Path(__file__).resolve().parents[1] / "fixtures" / "traces"

#: Every model the agent asks a provider to fill with constrained JSON (§7.3, §9.8).
RESPONSE_SCHEMAS = [RouteDecision, ToolCallRepair, AnswerSchema]


def keys(node: Any) -> list[str]:
    """Every key name anywhere in a nested structure."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.append(str(key))
            found += keys(value)
    elif isinstance(node, list):
        for item in node:
            found += keys(item)
    return found


def property_names(schema: Any) -> list[str]:
    """Every declared property name at every level of a JSON Schema, `$defs` included."""
    names: list[str] = []
    if isinstance(schema, dict):
        names += list(schema.get("properties", {}))
        for value in schema.values():
            names += property_names(value)
    elif isinstance(schema, list):
        for item in schema:
            names += property_names(item)
    return names


@pytest.mark.parametrize("kind", sorted(PAYLOAD_MODELS))
def test_no_span_payload_field_is_named_for_reasoning(kind):
    names = property_names(PAYLOAD_MODELS[kind].model_json_schema())
    assert names, kind
    assert [name for name in names if name.lower() in FORBIDDEN] == []


@pytest.mark.parametrize("model", RESPONSE_SCHEMAS, ids=lambda model: model.__name__)
def test_no_constrained_json_schema_asks_for_reasoning(model):
    names = property_names(strict_json_schema(model))
    assert names, model.__name__
    assert [name for name in names if name.lower() in FORBIDDEN] == []
    assert "rationale_summary" in names, "every constrained shape carries the one operational line"


@pytest.mark.parametrize("template", prompts.TEMPLATES)
def test_no_prompt_asks_the_model_to_think_out_loud(template):
    body = (prompts.PROMPT_DIR / template).read_text(encoding="utf-8").lower()
    assert not any(f"{name} " in body or f"{name}:" in body for name in FORBIDDEN), template
    assert "step by step" not in body and "step-by-step" not in body


def test_the_rationale_is_capped_and_collapsed_to_one_line():
    assert MAX_RATIONALE_CHARS == 200
    long = "because " * 60
    assert len(clamp_rationale(long)) == MAX_RATIONALE_CHARS
    assert "\n" not in clamp_rationale("first line\nsecond line")
    assert clamp_rationale("  spaced   out  ") == "spaced out"


def test_a_chatty_router_is_clamped_before_it_reaches_a_span():
    decision = RouteDecision(
        intent="policy_qa",
        workflow=None,
        multi_doc=False,
        needs_employee_data=False,
        needs_clarification=False,
        out_of_scope=False,
        sensitive=False,
        target_employee_id=None,
        selected_tools=["search_policy_documents", "not_a_tool"],
        rationale_summary="Let me think about this. " * 40,
    )
    cleaned = normalise(decision, catalog_names=["search_policy_documents"], message="How much PTO?")
    assert len(cleaned.rationale_summary) <= MAX_RATIONALE_CHARS
    assert cleaned.selected_tools == ["search_policy_documents"], "an invented tool never reaches a span"


@pytest.mark.parametrize("fixture", sorted(TRACES.glob("*.json")), ids=lambda path: path.stem)
def test_the_committed_golden_traces_carry_no_reasoning_field(fixture):
    body = json.loads(fixture.read_text(encoding="utf-8"))
    for span in body["spans"]:
        # The fixtures carry the payload inline as an object; the store column is the JSON of it.
        raw = span["payload_json"]
        payload = json.loads(raw) if isinstance(raw, str) else raw
        assert [key for key in keys(payload) if key.lower() in FORBIDDEN] == [], span["id"]
        rationale = payload.get("rationale_summary")
        assert rationale is None or len(rationale) <= MAX_RATIONALE_CHARS


async def test_a_real_turn_writes_no_reasoning_field_and_a_short_rationale(run_agent, spans):
    """The same two clauses, over the spans the loop actually persisted."""
    response = await run_agent(
        "out_of_scope.json",
        ChatRequest(message="Who won the 1998 World Cup final?", employee_id="E1042"),
    )

    records = spans(response.turn_id)
    assert records
    for kind, _, payload in records:
        assert [key for key in keys(payload) if key.lower() in FORBIDDEN] == [], kind
        rationale = payload.get("rationale_summary")
        assert rationale is None or len(rationale) <= MAX_RATIONALE_CHARS, kind

    plans = [payload for kind, _, payload in records if kind == "plan"]
    assert plans, "a turn always records its planning decision"
    assert all(set(plan) >= {"intent", "workflow", "step_summaries", "selected_tools"} for plan in plans)
