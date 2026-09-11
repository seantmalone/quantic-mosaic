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

**The host allowlist is configured, not defaulted.** `streamable_http_app()` auto-enables DNS
rebinding protection whenever its `host` argument is loopback — and `host` defaults to `127.0.0.1`
— so passing no `TransportSecuritySettings` silently installs a loopback-only allowlist and answers
`421 Invalid Host header` to every request carrying the deployment's public hostname. The
protection is worth keeping, so it stays **on** and `MCP_ALLOWED_HOSTS` names the hostnames this
deployment answers on (`render.yaml` carries the deployment's hostname). The default is loopback-only,
which is what a developer running `make run` needs and nothing more.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from hrmosaic.mcpserver.server import ServerDeps, build_hr_server
from hrmosaic.settings import settings

#: Where the mount lives. The endpoint is `<MOUNT_PATH>/mcp` — the SDK's own default sub-path.
MOUNT_PATH = "/mcp-server"


def transport_security(allowed_hosts: Sequence[str] | None = None) -> TransportSecuritySettings:
    """The SDK's rebinding guard, built from `MCP_ALLOWED_HOSTS` unless a caller names the hosts.

    `allowed_origins` is derived from the same list rather than left empty: an absent `Origin` is
    always accepted by the middleware, so the derived list only ever constrains a browser-sent one,
    and deriving it means the allowlist cannot drift apart from itself.
    """
    hosts = list(allowed_hosts) if allowed_hosts is not None else settings.mcp_allowed_hosts_list
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"{scheme}://{host}" for host in hosts for scheme in ("http", "https")],
    )


def mount_mcp(app: FastAPI, server: MCPServer, *, allowed_hosts: Sequence[str] | None = None) -> None:
    """Mount the Streamable HTTP app at `/mcp-server`, serving `/mcp-server/mcp`."""
    app.mount(MOUNT_PATH, server.streamable_http_app(transport_security=transport_security(allowed_hosts)))


@contextlib.asynccontextmanager
async def mcp_lifespan(server: MCPServer) -> AsyncIterator[None]:
    """Run the Streamable HTTP session manager for as long as the app is up."""
    async with server.session_manager.run():
        yield


def build_mounted_app(deps: ServerDeps | None = None, *, allowed_hosts: Sequence[str] | None = None) -> FastAPI:
    """A FastAPI app carrying the MCP mount and nothing else — the P5 half of the deployed topology."""
    server = build_hr_server(deps)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_lifespan(server):
            yield

    app = FastAPI(title="Mosaic HR Copilot — MCP", lifespan=lifespan)
    mount_mcp(app, server, allowed_hosts=allowed_hosts)
    app.state.mcp_server = server
    return app


__all__ = ["MOUNT_PATH", "build_mounted_app", "mcp_lifespan", "mount_mcp", "transport_security"]
