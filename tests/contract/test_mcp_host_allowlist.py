"""The mounted MCP endpoint answers the hostname the deployment is reached on (spec §8.1, R5.5).

The SDK's `streamable_http_app()` auto-enables DNS-rebinding protection whenever its `host`
argument is a loopback address — and `host` defaults to `127.0.0.1`. Passing no
`TransportSecuritySettings` therefore does **not** mean "no allowlist": it means the loopback
allowlist (`127.0.0.1:*`, `localhost:*`, `[::1]:*`), which answers `421 Invalid Host header` to
every request that arrives with the public hostname in its `Host` header. That is exactly what a
grader attaching MCP Inspector to the deployed service sees, so the allowlist is configured here
rather than left to a default, and the protection stays **on**: `MCP_ALLOWED_HOSTS` names the
hostnames this deployment answers on and nothing else is accepted.

The requests below are real `initialize` calls over a real ASGI transport against the very app
`web/main.py` mounts, so what is asserted is the response an external client gets.
"""

from __future__ import annotations

import httpx
import pytest

from hrmosaic.mcpserver.asgi import build_mounted_app, transport_security
from hrmosaic.settings import Settings, settings

pytestmark = pytest.mark.anyio

RENDER_HOST = "mosaic-hr-copilot.onrender.com"

#: A minimal, valid `initialize` — enough to get past the transport into the protocol.
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "allowlist-contract", "version": "0"},
    },
}
MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


async def _initialize(*, allowed_hosts: list[str] | None, host: str) -> httpx.Response:
    """POST one `initialize` at the mount, with `Host` set to what an external client would send."""
    app = build_mounted_app(allowed_hosts=allowed_hosts)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            return await client.post("/mcp-server/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "host": host})


# --- the wire ----------------------------------------------------------------------------


async def test_the_deployed_hostname_is_accepted_when_the_allowlist_carries_it():
    """R5.5: with the public hostname allowed, an external `initialize` completes."""
    response = await _initialize(allowed_hosts=["127.0.0.1:*", "localhost:*", RENDER_HOST], host=RENDER_HOST)
    assert response.status_code == 200, response.text
    assert '"serverInfo"' in response.text or '"server_info"' in response.text


async def test_a_hostname_outside_the_allowlist_is_still_refused_with_421():
    """Protection stays on: an unlisted `Host` is refused, which is the rebinding defence itself."""
    response = await _initialize(allowed_hosts=["127.0.0.1:*", "localhost:*", RENDER_HOST], host="evil.example.com")
    assert response.status_code == 421
    assert "Invalid Host header" in response.text


async def test_the_loopback_client_still_reaches_the_default_mount():
    """The agent's own client speaks to `127.0.0.1:${PORT}`; the shipped default must not break it."""
    response = await _initialize(allowed_hosts=None, host="127.0.0.1:8000")
    assert response.status_code == 200, response.text


# --- the settings the mount is built from -------------------------------------------------


def test_the_default_allowlist_is_loopback_only():
    assert settings.mcp_allowed_hosts == "127.0.0.1:*,localhost:*"
    assert settings.mcp_allowed_hosts_list == ["127.0.0.1:*", "localhost:*"]


def test_protection_is_enabled_and_origins_are_derived_from_the_hosts():
    """`allowed_origins` is not left empty: an Origin that is present must match a listed host."""
    security = transport_security([RENDER_HOST])
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == [RENDER_HOST]
    assert security.allowed_origins == [f"http://{RENDER_HOST}", f"https://{RENDER_HOST}"]


def test_blank_entries_are_dropped_so_a_trailing_comma_cannot_admit_an_empty_host():
    """`MCP_ALLOWED_HOSTS=a,,b,` is three hosts to a naive split, and one of them matches nothing."""
    parsed = Settings(mcp_allowed_hosts=f"127.0.0.1:*, ,{RENDER_HOST},")
    assert parsed.mcp_allowed_hosts_list == ["127.0.0.1:*", RENDER_HOST]


def test_the_mount_is_built_from_the_settings_when_no_hosts_are_passed():
    assert transport_security(None).allowed_hosts == settings.mcp_allowed_hosts_list
