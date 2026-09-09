"""Live MCP sessions over both real transports (spec §8.1, §16.4).

Neither helper fakes anything: `stdio_session` spawns `python mcp/server_entrypoint.py --stdio` as a
separate OS process and talks JSON-RPC over its pipes, and `http_session` runs the very
`build_mounted_app()` the deployed service mounts, on a real uvicorn over loopback, and connects with
the SDK's Streamable HTTP client. Both yield a `ClientSession`, so a test written once runs against
both and the parametrisation is what makes "on both transports" true rather than asserted.

Both use the raw transport functions rather than the high-level `Client`, because unpacking exactly
two names from the yield is the live half of the 2.x arity check in
`tests/contract/test_mcp_api_shape.py`.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "mcp" / "server_entrypoint.py"

#: The three `_meta` keys of §8.7, with the defaults a turn that set no options would send.
BASE_META: dict[str, object] = {
    "mosaic/trace": {"trace_id": "0" * 32, "turn_id": "1" * 32, "parent_span_id": "2" * 16},
    "mosaic/actor": {"employee_id": "E1042", "source": "explicit"},
    "mosaic/retrieval": {"strategy": None, "k_override": None},
}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@asynccontextmanager
async def stdio_session() -> AsyncIterator[ClientSession]:
    """A session against a real subprocess — the demo video's "visibly separate process"."""
    parameters = StdioServerParameters(command=sys.executable, args=[str(ENTRYPOINT), "--stdio"], cwd=str(REPO_ROOT))
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


@asynccontextmanager
async def http_session() -> AsyncIterator[ClientSession]:
    """A session against `build_mounted_app()` on loopback — the graded topology, minus `web/`."""
    from sse_starlette.sse import AppStatus

    from hrmosaic.mcpserver.asgi import build_mounted_app

    # `sse_starlette.AppStatus.should_exit` is a process-global latch: stopping one uvicorn sets it
    # and every later SSE stream in the process drains immediately. One server per process is the
    # only case its authors had in mind; a test module starts several, so the latch is cleared here.
    AppStatus.should_exit = False
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(build_mounted_app(), host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        url = f"http://127.0.0.1:{port}/mcp-server/mcp"
        async with streamable_http_client(url) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            yield session
    finally:
        server.should_exit = True
        await serving
        AppStatus.should_exit = False


#: The two transports every discovery and tool-call test runs against.
TRANSPORTS = {"stdio": stdio_session, "http": http_session}


@pytest.fixture(params=sorted(TRANSPORTS), ids=sorted(TRANSPORTS))
def open_session(request):
    """The transport under test, as a callable returning an async context manager."""
    return TRANSPORTS[request.param]
