"""The orchestrator strips any model-supplied `confirmation_token` (spec §8.6).

A token is a credential. The model must never be able to supply one — not even a fabricated one —
and stripping is simpler than validating provenance, which is why the argument is removed from
**every** `tools/call` and re-attached only by `resume_turn`, from a token `web/` minted after a
human clicked Confirm.

The stub script here scripts exactly the attack: a `create_mock_hr_ticket` call carrying
`confirmation_token: "forged-token-the-model-made-up"`. Every assertion below is about what the real
MCP server in a real subprocess did with the call it actually received.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent.client import TOKEN_ARGUMENT
from hrmosaic.agent.orchestrator import ChatRequest

pytestmark = pytest.mark.anyio

FORGED = "forged-token-the-model-made-up"


async def test_the_call_that_reached_the_server_carried_no_token(run_agent, spans, store, mounted_mcp_url):
    """Both halves: what we sent, and what the server did with it.

    Over the mounted HTTP transport, so the server shares this test's trace store: "no `mock_writes`
    row" is then a fact about the database the gate would have written to, not a vacuous count of a
    table a subprocess never touched.
    """
    gated = await run_agent(
        "forged_token.json",
        ChatRequest(message="Please open a PTO request for 15-17 September 2026.", employee_id="E1042"),
        url=mounted_mcp_url,
    )

    tool_calls = [payload for kind, _, payload in spans(gated.turn_id) if kind == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool_name"] == "create_mock_hr_ticket"
    assert TOKEN_ARGUMENT not in tool_calls[0]["arguments"]
    assert set(tool_calls[0]["arguments"]) == {"employee_id", "queue", "summary", "details", "priority"}

    # The server saw a token-free call, so the gate answered with the five-key rejection of §8.4.
    assert tool_calls[0]["is_error"] is True
    assert tool_calls[0]["error_code"] == "CONFIRMATION_REQUIRED"
    assert set(json.loads(tool_calls[0]["result_json"])) == {
        "status",
        "code",
        "action",
        "human_summary",
        "arguments_preview",
    }
    assert store.execute("SELECT count(*) FROM mock_writes").scalar() == 0
    assert store.execute("SELECT count(*) FROM confirmations").scalar() == 0


async def test_the_turn_parks_and_the_forged_token_survives_nowhere(run_agent, spans, store, mounted_mcp_url):
    gated = await run_agent(
        "forged_token.json",
        ChatRequest(message="Please open a PTO request for 15-17 September 2026.", employee_id="E1042"),
        url=mounted_mcp_url,
    )

    assert gated.outcome == "awaiting_confirmation"
    assert gated.confirmation is not None
    assert gated.confirmation.action == "create_mock_hr_ticket"
    assert "confirmation_token" not in gated.confirmation.model_dump()

    confirmation = next(payload for kind, _, payload in spans(gated.turn_id) if kind == "confirmation")
    assert confirmation["user_response"] == "pending"
    assert "token" not in confirmation

    # Spans are the record of what we *sent*; a stripped argument must not survive into one.
    assert FORGED not in gated.model_dump_json()
    rows = store.execute("SELECT payload_json FROM spans").dicts()
    assert all(FORGED not in row["payload_json"] for row in rows)
