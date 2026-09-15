"""A write the deterministic layer refuses is never proposed (W8, C02).

`fresh:a771d87b…:1`, demo 2 for E1108 Marcus, live on 2026-09-15:

    engine   pto.request.balance — blocking — remaining_days 0.25 against a 3-day request
             verdict: non_compliant
    product  MOCK-HR-000011 created
    answer   "Done — your request is with the HR Time Off team. Reference MOCK-HR-000011."
             …then, four lines down: "You do not have sufficient accrual to cover this request."

The gate asked "did a human confirm?" and never "may this be done at all?". `non_compliant` **is**
the blocking-requirement condition — §8.4 defines it as an evaluable `blocking` requirement that is
unmet — so the verdict alone is the test, and the refusal happens at the call boundary rather than
being talked about afterwards.
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
async def blocked(run_agent, mounted_mcp_url, store):
    response = await run_agent(
        "write_blocked.json", ChatRequest(message=QUESTION, employee_id="E1108"), url=mounted_mcp_url
    )
    spans = store.execute(
        "SELECT kind, name, status, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (response.turn_id,)
    ).dicts()
    return response, [{**row, "payload": json.loads(row["payload_json"])} for row in spans]


async def test_no_card_is_shown_and_nothing_is_written(blocked, store):
    response, spans = blocked

    assert response.outcome != "awaiting_confirmation"
    assert response.confirmation is None
    assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 0
    assert store.execute("SELECT COUNT(*) AS n FROM confirmations").scalar() == 0
    assert "MOCK-HR" not in response.answer

    gated = [span for span in spans if span["kind"] == "tool_call" and span["name"] == "create_mock_hr_ticket"]
    assert len(gated) == 1, "the model proposed it once and the gate answered CONFIRMATION_REQUIRED"
    confirmations = [span for span in spans if span["kind"] == "confirmation"]
    assert confirmations == [], "and the orchestrator never turned it into a card"


async def test_the_answer_says_why_in_the_products_own_voice(blocked):
    """The reader is told what did not happen and why, before the answer about what did."""
    response, _spans = blocked
    lede = response.answer_blocks[0]

    assert lede.type == "notice"
    assert lede.text.startswith("I have not opened the request:")
    assert "0.25" in lede.text and "3" in lede.text
    assert "people-ops@mosaicrobotics.example" in lede.text, "and what the policy allows instead"


async def test_the_refusal_is_recorded(blocked):
    response, spans = blocked
    errors = [span["payload"] for span in spans if span["kind"] == "error"]

    assert "write_blocked" in [error["error_kind"] for error in errors]
    assert response.outcome == "answered", "the question is still answered"


async def test_the_answer_never_claims_the_balance_covers_the_request(blocked):
    """The recorded synthesis says it does. The engine says it does not, and the engine decides."""
    response, _spans = blocked

    assert "covers the three days" not in response.answer
    assert "0.25" in response.answer and "the policy asks for at least 3" in response.answer
