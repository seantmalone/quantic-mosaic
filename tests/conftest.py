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


@asynccontextmanager
async def web_server(settings) -> AsyncIterator[str]:
    """`web/main.py`'s **whole** app on a real uvicorn — the deployed topology, in one process.

    Not `ASGITransport`: the agent reaches its own MCP mount over **loopback HTTP**, so the app
    under test has to be listening on a real port or the very wire P8 exists to serve would be the
    one thing not exercised. It is also the only way the access gate can be observed on the mount.
    """
    from sse_starlette.sse import AppStatus

    from hrmosaic.core import trace as trace_module
    from hrmosaic.web.main import create_app

    # As in `mounted_server()`: the latch is process-global and a stopped server sets it for every
    # later stream in the process.
    AppStatus.should_exit = False
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=settings.port, log_level="warning")
    )
    serving = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        yield f"http://127.0.0.1:{settings.port}"
    finally:
        # Both latches, and neither by way of `handle_exit`. The agent's own MCP session holds a
        # long-lived `GET /mcp-server/mcp` open, and uvicorn will not finish a graceful shutdown
        # while it is serving that stream; only `sse_starlette`'s process-global
        # `AppStatus.should_exit` drains it. Calling `server.handle_exit()` would set both — and
        # then uvicorn 0.52 re-raises every captured signal once its handlers are restored
        # (`server.py:339`), killing the pytest process with 143. A real SIGTERM on Render wants
        # exactly that replay; a test does not.
        AppStatus.should_exit = True
        server.should_exit = True
        await serving
        AppStatus.should_exit = False
        trace_module.clear_span_listeners()
        trace_module.set_writer(None)
        # The lifespan installs the SIGTERM/atexit handlers, and `_handlers_installed` is a module
        # global: leaving it set would silently turn a later test's own `install_shutdown_handlers()`
        # into a no-op. uvicorn's `capture_signals` has already restored the handler it wrapped.
        trace_module.reset_shutdown_handlers()


@pytest.fixture
def web(store, monkeypatch):
    """Factory: `async with web(script="demo_task_1.json") as client:` — a live app and a client.

    Every keyword after `script` is a `settings` override applied for the duration of the server,
    so a test can turn the access gate on, point `MCP_SERVER_URL` elsewhere, or ask for the real
    warm-up without reaching for the environment.
    """
    import httpx

    from hrmosaic.settings import settings as live_settings

    @asynccontextmanager
    async def start(script: str = "demo_task_1.json", **overrides) -> AsyncIterator[httpx.AsyncClient]:
        port = free_port()
        defaults = {
            "port": port,
            "mcp_server_url": f"http://127.0.0.1:{port}/mcp-server/mcp",
            "llm_provider": "stub",
            "llm_stub_script": LLM_SCRIPTS / script,
            # `/ready`'s warm-up loads the real ONNX model; the tests that want it ask for it.
            "embed_warmup": False,
        }
        for key, value in {**defaults, **overrides}.items():
            monkeypatch.setattr(live_settings, key, value)
        async with web_server(live_settings) as base_url:
            async with httpx.AsyncClient(base_url=base_url, timeout=120.0) as client:
                yield client

    return start


@pytest.fixture
def spans(store):
    """Every span of a turn, in `seq` order, as `(kind, name, payload)` — what the gates assert on."""

    def read(turn_id: str) -> list[tuple[str, str, dict]]:
        rows = store.execute(
            "SELECT kind, name, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (turn_id,)
        ).dicts()
        return [(row["kind"], row["name"], json.loads(row["payload_json"])) for row in rows]

    return read
