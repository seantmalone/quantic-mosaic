"""Mounting the MCP server inside the FastAPI process (spec §8.1).

The graded topology is **one process**: uvicorn serves `/chat`, `/dashboard/*` and the MCP endpoint
at `/mcp-server/mcp`, and the agent reaches its own tools over loopback Streamable HTTP. That is why
every tool handler is `async def` with its blocking work inside `asyncio.to_thread` — the MCP server
shares the event loop with the web app, so a synchronous read in a tool would stall the page that is
waiting for it.

Two helpers, and both are used by tests as well as by the app, so the topology under test is the
topology that ships:

* `mount_mcp(app, server)` — the mount itself, one line, so `web/main.py` cannot mount it differently.
* `build_mounted_app(deps)` — a minimal FastAPI carrying only the MCP mount and the session-manager
  lifespan. `web/main.py` (P8) builds its own app and composes `mcp_lifespan` into a wider lifespan
  that also registers the SSE span listener, applies migrations, imports committed eval results and
  starts the retention sweep.

`session_manager` raises unless `streamable_http_app()` has already been called, so the mount happens
at construction time and the lifespan only enters the manager it produced.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer

from hrmosaic.mcpserver.server import ServerDeps, build_hr_server

#: Where the mount lives. The endpoint is `<MOUNT_PATH>/mcp` — the SDK's own default sub-path.
MOUNT_PATH = "/mcp-server"


def mount_mcp(app: FastAPI, server: MCPServer) -> None:
    """Mount the Streamable HTTP app at `/mcp-server`, serving `/mcp-server/mcp`."""
    app.mount(MOUNT_PATH, server.streamable_http_app())


@contextlib.asynccontextmanager
async def mcp_lifespan(server: MCPServer) -> AsyncIterator[None]:
    """Run the Streamable HTTP session manager for as long as the app is up."""
    async with server.session_manager.run():
        yield


def build_mounted_app(deps: ServerDeps | None = None) -> FastAPI:
    """A FastAPI app carrying the MCP mount and nothing else — the P5 half of the deployed topology."""
    server = build_hr_server(deps)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_lifespan(server):
            yield

    app = FastAPI(title="Mosaic HR Copilot — MCP", lifespan=lifespan)
    mount_mcp(app, server)
    app.state.mcp_server = server
    return app


__all__ = ["MOUNT_PATH", "build_mounted_app", "mcp_lifespan", "mount_mcp"]
