"""§9.5 row 1 — the MCP server is unreachable, and the turn still answers at **HTTP 200**.

The orchestrator re-discovers once, records an `error` span `tool_unavailable`, and degrades to a
policy-only answer with an **explicit caveat block** and an escalation note. It never raises, never
hangs and never 5xxes: R4.4's whole point is that a failure is a documented answer, not a stack
trace the grader has to read.

Authored in full at P8, when `POST /chat` exists — no phase owns half a file (§22, principle 14).
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import free_port

pytestmark = pytest.mark.anyio

QUESTION = "Can I work from Berlin for six weeks this autumn?"


@pytest.fixture
def dead_mcp_url() -> str:
    """A port nothing is listening on. The mount inside the app is bypassed by pointing away."""
    return f"http://127.0.0.1:{free_port()}/mcp-server/mcp"


async def test_the_turn_answers_200_with_a_caveat_and_an_escalation(web, dead_mcp_url):
    async with web("rag_only.json", mcp_server_url=dead_mcp_url) as client:
        response = await client.post("/chat", json={"message": QUESTION})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "partial"
    types = [block["type"] for block in body["answer_blocks"]]
    assert types == ["recommendation", "escalation"]
    assert "unreachable" in body["answer_blocks"][0]["text"]
    assert "Nothing below is a statement of Mosaic Robotics policy" in body["answer_blocks"][0]["text"]
    assert "People Operations" in body["answer_blocks"][1]["text"]
    assert body["citations"] == [], "nothing was retrieved, so nothing is cited"


async def test_the_error_span_names_tool_unavailable_and_is_retryable(web, store, dead_mcp_url):
    async with web("rag_only.json", mcp_server_url=dead_mcp_url) as client:
        body = (await client.post("/chat", json={"message": QUESTION})).json()

    rows = store.execute(
        "SELECT name, status, payload_json FROM spans WHERE turn_id = ? AND kind = 'error'", (body["turn_id"],)
    ).dicts()
    payloads = [json.loads(row["payload_json"]) for row in rows]
    assert [payload["error_kind"] for payload in payloads] == ["tool_unavailable"]
    assert payloads[0]["component"] == "mcp"
    assert payloads[0]["retryable"] is True
    assert payloads[0]["message"], "the reason is on the record, not only in a log line"

    turn = store.execute("SELECT outcome, stop_reason, error_kind FROM turns WHERE id = ?", (body["turn_id"],)).one()
    assert (turn["outcome"], turn["stop_reason"], turn["error_kind"]) == ("partial", "error", "tool_unavailable")


async def test_health_still_answers_200_and_the_error_never_reaches_the_client_as_a_5xx(web, dead_mcp_url):
    async with web("rag_only.json", mcp_server_url=dead_mcp_url) as client:
        health = await client.get("/health")
        chat = await client.post("/chat", json={"message": QUESTION})

    assert health.status_code == 200
    assert chat.status_code == 200
    assert "mcp_disconnected" in health.json()["degradations"]


async def test_no_tool_call_span_was_written_for_a_server_that_was_never_reached(web, store, dead_mcp_url):
    async with web("rag_only.json", mcp_server_url=dead_mcp_url) as client:
        body = (await client.post("/chat", json={"message": QUESTION})).json()

    kinds = [
        row["kind"]
        for row in store.execute("SELECT kind FROM spans WHERE turn_id = ? ORDER BY seq", (body["turn_id"],)).dicts()
    ]
    assert "tool_call" not in kinds
    assert "mcp_discovery" not in kinds, "the handshake never completed, so nothing was discovered"
    assert "error" in kinds
