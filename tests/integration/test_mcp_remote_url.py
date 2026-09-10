"""The third transport: a **remote** MCP server over `MCP_SERVER_URL` (spec §16.4, R7.3).

The deployed default mounts the server in-process, but the same `build_hr_server()` factory serves
stdio and a genuinely separate HTTP endpoint. This file boots a **second** uvicorn on another port,
points `MCP_SERVER_URL` at it, and asserts that discovery and a real `tools/call` succeed with
`sessions.mcp_transport == 'remote'` — R7.3's evidence that the transport choice is a configuration
value and not a hard-wired assumption.

`mcp_transport_effective` is `remote` **iff** `MCP_SERVER_URL` was explicitly set to something other
than the computed loopback default, so the test sets the same private flag `settings.py` sets when
the variable comes from the environment.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import mounted_server

pytestmark = pytest.mark.anyio

QUESTION = "How much PTO do full-time employees accrue each month?"


@pytest.fixture
async def remote_url():
    """A second uvicorn, on its own port, serving nothing but the MCP mount."""
    async with mounted_server() as url:
        yield url


async def test_discovery_and_a_call_succeed_against_a_remote_server(web, store, monkeypatch, remote_url):
    from hrmosaic.settings import settings as live_settings

    monkeypatch.setattr(live_settings, "_mcp_server_url_explicit", True)
    async with web("rag_only.json", mcp_server_url=remote_url) as client:
        health = await client.get("/health")
        response = await client.post("/chat", json={"message": QUESTION})

    assert health.status_code == 200
    assert health.json()["mcp"]["connected"] is True
    assert health.json()["mcp"]["url"] == remote_url

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "answered"
    assert body["citations"]

    rows = store.execute(
        "SELECT kind, name, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (body["turn_id"],)
    ).dicts()
    discovery = next(json.loads(row["payload_json"]) for row in rows if row["kind"] == "mcp_discovery")
    assert discovery["tool_count"] == 9
    assert discovery["url"] == remote_url
    assert discovery["transport"] == "remote", "the client knows it is talking to another process"

    calls = [json.loads(row["payload_json"]) for row in rows if row["kind"] == "tool_call"]
    assert calls, "a real tools/call crossed the wire to the other process's port"
    # `tool_call.transport` is the **server's** own view of how it was reached (§8.7), which is
    # `http` on either side of a remote URL; the client's view is the discovery span above.
    assert all(call["transport"] == "http" for call in calls)
    assert all(call["result_json"] for call in calls)


async def test_the_session_records_the_remote_transport(web, store, monkeypatch, remote_url):
    from hrmosaic.settings import settings as live_settings

    monkeypatch.setattr(live_settings, "_mcp_server_url_explicit", True)
    assert live_settings.mcp_transport_effective == "http"  # before the override

    async with web("rag_only.json", mcp_server_url=remote_url) as client:
        assert live_settings.mcp_transport_effective == "remote"
        body = (await client.post("/chat", json={"message": QUESTION})).json()

    assert store.execute("SELECT mcp_transport FROM sessions WHERE id = ?", (body["session_id"],)).scalar() == "remote"
