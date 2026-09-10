"""Fixtures shared by the store-backed tests.

Every test gets its own migrated `SqliteStore` in a temporary directory and its own
`TraceWriter`, so nothing touches `data/runtime/traces.sqlite` and no test can see another's
rows. The process-wide store and span-listener registries are reset around each test.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import uvicorn

from hrmosaic.core import trace as trace_module
from hrmosaic.core.db import SqliteStore, migrate, set_store


@pytest.fixture
def store(tmp_path):
    store = SqliteStore(tmp_path / "traces.sqlite")
    migrate(store)
    set_store(store)
    yield store
    set_store(None)
    store.close()


@pytest.fixture
def writer(store):
    writer = trace_module.TraceWriter(store)
    trace_module.set_writer(writer)
    yield writer
    trace_module.set_writer(None)
    trace_module.clear_span_listeners()


@pytest.fixture(scope="session")
def anyio_backend():
    """asyncio only — the MCP tests are async and the project runs no trio anywhere."""
    return "asyncio"


REPO_ROOT = Path(__file__).resolve().parents[1]
LLM_SCRIPTS = REPO_ROOT / "tests" / "fixtures" / "llm_scripts"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@asynccontextmanager
async def mounted_server() -> AsyncIterator[str]:
    """`build_mounted_app()` on a real uvicorn over loopback — the graded topology, minus `web/`.

    In-process is not only cheaper than a subprocess: it is the only topology in which the
    confirmation gate can be observed, because the gate reads and writes the **trace store** and a
    stdio subprocess has a store of its own. Any test that asserts about `confirmations` or
    `mock_writes` has to run against this mount, or it would be asserting about the wrong database.
    """
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
        yield f"http://127.0.0.1:{port}/mcp-server/mcp"
    finally:
        server.should_exit = True
        await serving
        AppStatus.should_exit = False


@pytest.fixture
async def mounted_mcp_url() -> AsyncIterator[str]:
    """The mounted endpoint, for a test that drives the agent's own `McpClient` against it."""
    async with mounted_server() as url:
        yield url


@pytest.fixture
def run_agent(writer):
    """Drive one whole agent turn: the stub model, and a **real** MCP server.

    Nothing here is a mock. `StubAdapter` replays a committed script — the keystone of the key-free
    path (§16.2) — while the tools, the retrieval, the rule engine and the confirmation gate are the
    shipped server, reached over a real MCP session. So a test that asserts "no people tool was
    called" is asserting about a real `tools/call`, not about a stand-in that could not have made
    one.

    `stdio` by default, because a separate OS process is the cheaper and stricter proof. Pass the
    `mounted_mcp_url` fixture as `url` for anything that reads `confirmations` or `mock_writes`:
    those live in the trace store, which only the in-process mount shares with the test.
    """
    from hrmosaic.agent.client import McpClient
    from hrmosaic.agent.orchestrator import Orchestrator
    from hrmosaic.core.llm.stub import StubAdapter

    async def drive(script: str, request, *, url: str | None = None):
        orchestrator = Orchestrator(
            client=McpClient(transport="http" if url else "stdio", url=url),
            model=StubAdapter(script_path=LLM_SCRIPTS / script),
        )
        try:
            return await orchestrator.run_turn(request)
        finally:
            await orchestrator.aclose()

    return drive


@pytest.fixture
def spans(store):
    """Every span of a turn, in `seq` order, as `(kind, name, payload)` — what the gates assert on."""

    def read(turn_id: str) -> list[tuple[str, str, dict]]:
        rows = store.execute(
            "SELECT kind, name, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (turn_id,)
        ).dicts()
        return [(row["kind"], row["name"], json.loads(row["payload_json"])) for row in rows]

    return read
