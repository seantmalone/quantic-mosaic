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

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from tests.conftest import mounted_server

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "mcp" / "server_entrypoint.py"

#: The three `_meta` keys of §8.7, with the defaults a turn that set no options would send.
BASE_META: dict[str, object] = {
    "mosaic/trace": {"trace_id": "0" * 32, "turn_id": "1" * 32, "parent_span_id": "2" * 16},
    "mosaic/actor": {"employee_id": "E1042", "source": "explicit"},
    "mosaic/retrieval": {"strategy": None, "k_override": None},
}


@asynccontextmanager
async def stdio_session() -> AsyncIterator[ClientSession]:
    """A session against a real subprocess — the demo video's "visibly separate process"."""
    parameters = StdioServerParameters(command=sys.executable, args=[str(ENTRYPOINT), "--stdio"], cwd=str(REPO_ROOT))
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


@asynccontextmanager
async def http_session() -> AsyncIterator[ClientSession]:
    """A `ClientSession` against that mount, connected with the SDK's Streamable HTTP client."""
    async with mounted_server() as url:
        async with streamable_http_client(url) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            yield session


#: The two transports every discovery and tool-call test runs against.
TRANSPORTS = {"stdio": stdio_session, "http": http_session}


@pytest.fixture(params=sorted(TRANSPORTS), ids=sorted(TRANSPORTS))
def open_session(request):
    """The transport under test, as a callable returning an async context manager."""
    return TRANSPORTS[request.param]
