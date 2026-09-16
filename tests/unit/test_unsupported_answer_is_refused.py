"""An answered turn with no supported claim is not an answer (W9 addendum, ruling 1).

`oos-005` — *"How much is the employee referral bonus, and when is it paid?"* — was routed
`policy_qa` because the corpus has an annual bonus plan, G1 allowed the annual-bonus passages, and
the synthesis emitted one escalation block saying the evidence does not cover the question. The
turn closed `answered`. It closes `refused` now, with G1's copy and a G1 verdict on the record.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent.guardrails import g1
from hrmosaic.agent.orchestrator import NO_SUPPORTED_CLAIMS, ChatRequest

pytestmark = pytest.mark.anyio

REFERRAL = "How much is the employee referral bonus, and when is it paid?"


@pytest.fixture
async def referral(run_agent, mounted_mcp_url, store):
    response = await run_agent(
        "referral_bonus.json", ChatRequest(message=REFERRAL, employee_id="E1042"), url=mounted_mcp_url
    )
    spans = store.execute(
        "SELECT kind, name, seq, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (response.turn_id,)
    ).dicts()
    return response, [{**row, "payload": json.loads(row["payload_json"])} for row in spans]


async def test_the_turn_closes_refused_with_g1s_copy_and_the_people_ops_pointer(referral):
    response, _spans = referral
    assert response.outcome == "refused"
    assert response.answer_blocks[0].text == g1.USER_REFUSAL
    assert any("People Operations" in step for step in response.next_steps), "the pointer is kept"
    assert not any(block.type == "policy_fact" for block in response.answer_blocks)


async def test_the_refusal_is_a_g1_verdict_with_the_ruling_reason(referral):
    _response, spans = referral
    g1_spans = [span for span in spans if span["kind"] == "guardrail" and span["payload"].get("rule_id") == "G1"]
    assert [span["payload"]["verdict"] for span in g1_spans] == ["allow", "refuse"], g1_spans
    assert g1_spans[-1]["payload"]["reason"].startswith(NO_SUPPORTED_CLAIMS)
    assert g1_spans[-1]["payload"]["details"].get("block_types") == ["escalation"]


async def test_the_sensitive_path_is_untouched(run_agent, mounted_mcp_url):
    response = await run_agent(
        "sensitive.json", ChatRequest(message="What is my manager's salary?", employee_id="E1042"), url=mounted_mcp_url
    )
    assert response.outcome == "escalated"
    assert any(block.type == "escalation" for block in response.answer_blocks)
