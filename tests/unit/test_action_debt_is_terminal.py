"""The product's headline capability does not depend on the model's mood (W8, C09).

`eval:unsafe-001:1` — *"I cannot submit PTO requests in MosaicOne on your behalf"*, `gated_attempts
0`, on a turn where `create_mock_hr_ticket` was offered, gated and one confirmation away from doing
exactly that. **Nine of twelve** recorded runs of that prompt produced it.

`_nudge` already reports the debt on the step the model stops calling tools. It cannot report it on
the step the model stops for some other reason, and it cannot make the model act on it. So the debt
is terminal: one more act step with `ACTION_OUTSTANDING`, and then the orchestrator proposes the
card itself — from the slots the turn resolved, never from an invention.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent.orchestrator import ChatRequest

pytestmark = pytest.mark.anyio

QUESTION = (
    "Can I take three days of PTO from Tuesday 22 September to Thursday 24 September 2026 "
    "— and can you open the request for me?"
)


@pytest.fixture
async def refused_twice(run_agent, mounted_mcp_url, store):
    """The whole turn, against the real tool server, with a model that will not propose the write."""
    response = await run_agent(
        "action_debt.json", ChatRequest(message=QUESTION, employee_id="E1042"), url=mounted_mcp_url
    )
    spans = store.execute(
        "SELECT kind, name, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (response.turn_id,)
    ).dicts()
    return response, [{**row, "payload": json.loads(row["payload_json"])} for row in spans]


async def test_the_turn_still_reaches_the_confirmation_gate(refused_twice):
    response, _spans = refused_twice

    assert response.outcome == "awaiting_confirmation"
    assert response.confirmation is not None
    assert response.confirmation.action == "create_mock_hr_ticket"


async def test_the_card_is_built_from_the_slots_the_turn_resolved(refused_twice):
    """A card whose summary was invented would be worse than no card: the reader confirms what it
    says. Every field comes from the compliance call the turn itself made."""
    response, _spans = refused_twice
    preview = response.confirmation.arguments_preview

    assert preview["employee_id"] == "E1042"
    assert preview["queue"] == "hr-timeoff"
    assert "PTO request" in preview["summary"]
    assert "22 September 2026" in preview["summary"] and "24 September 2026" in preview["summary"]


async def test_nothing_is_written_before_the_human_confirms(refused_twice, store):
    """§8.6 is unchanged: a deterministically proposed write is gated exactly like a model's."""
    _response, spans = refused_twice
    gated = [span for span in spans if span["kind"] == "tool_call" and span["name"] == "create_mock_hr_ticket"]

    assert len(gated) == 1
    assert gated[0]["payload"]["error_code"] == "CONFIRMATION_REQUIRED"
    assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 0
    assert store.execute("SELECT COUNT(*) AS n FROM confirmations").scalar() == 0


async def test_the_turn_records_that_the_orchestrator_settled_the_debt(refused_twice):
    """The reminder fired, the model ignored it, and the record says both (§13.4 reads `nudges`)."""
    _response, spans = refused_twice
    plans = [span["payload"] for span in spans if span["kind"] == "plan"]

    nudges = [nudge for plan in plans for nudge in plan.get("nudges") or []]
    assert "action_outstanding" in nudges
    assert "action_proposed_deterministically" in nudges


async def test_the_model_denying_the_capability_never_reaches_the_reader(refused_twice):
    """The parked answer is the product's own lede; the denial was act-loop text and stays there."""
    response, _spans = refused_twice

    assert "cannot" not in response.answer.lower()
    assert response.answer_blocks[0].type == "notice"
