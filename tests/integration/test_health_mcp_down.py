"""`/health` with the MCP server unreachable (spec §11.4).

The named test of §11.4: point the client at a dead port and `/health` is **200**, `degraded`, with
`mcp_disconnected` listed. That combination is the whole design of the endpoint — a provider hiccup
or a slow model load must never make Render restart-loop the instance, so degradation is a status
string and never a 5xx, and `healthCheckPath: /health` stays honest.
"""

from __future__ import annotations

import pytest

from tests.conftest import free_port

pytestmark = pytest.mark.anyio


@pytest.fixture
def dead_mcp_url() -> str:
    return f"http://127.0.0.1:{free_port()}/mcp-server/mcp"


async def test_health_is_200_degraded_and_lists_mcp_disconnected(web, dead_mcp_url):
    async with web(mcp_server_url=dead_mcp_url) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["degradations"] == ["mcp_disconnected"]


async def test_the_mcp_block_reports_what_it_could_not_reach(web, dead_mcp_url):
    async with web(mcp_server_url=dead_mcp_url) as client:
        mcp = (await client.get("/health")).json()["mcp"]

    assert mcp["connected"] is False
    assert mcp["tool_count"] == 0
    assert mcp["tool_names"] == []
    assert mcp["url"] == dead_mcp_url
    assert mcp["last_error"], "the reason is reported, not swallowed"


async def test_the_other_blocks_are_unaffected_by_an_unreachable_tool_server(web, dead_mcp_url):
    async with web(mcp_server_url=dead_mcp_url) as client:
        body = (await client.get("/health")).json()

    assert body["index"]["loaded"] is True
    assert body["trace_store"]["reachable"] is True
    assert body["data"]["employees"] == 24
    assert body["app"]["uptime_ms"] >= 0
