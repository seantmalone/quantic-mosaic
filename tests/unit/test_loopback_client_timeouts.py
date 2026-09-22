"""The loopback MCP client's transport timeouts (spec §11.4).

`streamable_http_client` takes an `httpx2.AsyncClient` rather than a headers mapping, so the
access-gate header of §11 — and, since G5b, the response hook that reads the MCP session id — force
`McpClient` to build the client itself on every http transport. A client built with
`httpx2.AsyncClient(headers=…)` alone inherits httpx2 2.12's default `Timeout(5.0)` on all four
phases. That default is wrong for this wire: a StreamableHTTP `tools/call` holds its response
stream open until the result arrives, and on Render's 0.1-CPU free instance the first embedding
call loads the ONNX session and goes well past five seconds without a byte. The read then times
out and the SDK reports `SSE stream ended without a response`, which is what left `/ready`
permanently 503 on the live deployment while `/chat` worked.

So these tests pin the numbers, not the mechanism: the same 30 s connect/write/pool and 300 s read
the SDK's own `create_mcp_http_client` uses, and an explicit assertion that the constant is not
httpx2's default — a refactor that dropped `timeout=` would otherwise regress silently and only on
a slow host.
"""

from __future__ import annotations

import httpx2
import pytest

from hrmosaic.agent.client import LOOPBACK_TIMEOUT, McpClient

pytestmark = pytest.mark.anyio

LOOPBACK_URL = "http://127.0.0.1:8000/mcp-server/mcp"


async def test_the_gated_loopback_client_reads_for_five_minutes():
    """The read phase is the one that matters: a silent stream is not a dead stream."""
    client = McpClient(transport="http", url=LOOPBACK_URL, headers={"Authorization": "Bearer x"})._http_client()
    assert client is not None
    try:
        assert client.timeout.read == 300.0
        assert (client.timeout.connect, client.timeout.write, client.timeout.pool) == (30.0, 30.0, 30.0)
    finally:
        await client.aclose()


async def test_the_ungated_client_is_still_ours_and_still_reads_for_five_minutes():
    """It used to return `None` when there was no header to send, and let the SDK build the client.

    Since G5b (gap 17) it is always ours, because the `Mcp-Session-Id` the discovery span records is a
    **response header** and a client the SDK builds has no hook on it — `mcp_session_id` was `null` on
    every recorded turn. The numbers are unchanged either way: `LOOPBACK_TIMEOUT` is
    `create_mcp_http_client`'s own 30 s / 300 s, so a client built here and one the SDK would have
    built wait exactly as long.
    """
    client = McpClient(transport="http", url=LOOPBACK_URL)._http_client()
    assert client is not None
    try:
        assert client.timeout.read == 300.0
        assert client.event_hooks["response"], "nothing would read the session id off the handshake"
    finally:
        await client.aclose()


async def test_the_timeout_is_not_httpx2s_default():
    """The regression guard: `AsyncClient(headers=…)` with no `timeout=` is `Timeout(5.0)`."""
    assert LOOPBACK_TIMEOUT != httpx2.Timeout(5.0)
    assert LOOPBACK_TIMEOUT == httpx2.Timeout(30.0, read=300.0)
