"""The application boots and serves the endpoint list of §11.8 — nothing more, nothing less.

A boot test earns its place here because §12.3's rule is that **boot always succeeds**: a missing
credential, an unbuilt index or an unreachable store degrades the surface that needs it and never
stops the process. So this file starts the real app on a real port with no credentials at all.
"""

from __future__ import annotations

import pytest

from hrmosaic.web.main import create_app

pytestmark = pytest.mark.anyio

#: Every path §11.8 lists that P8 owns. The dashboard pages and the rest of `/api/*` are P9's, and
#: their prefixes are refused by the persona check until then.
EXPECTED_ROUTES = {
    ("GET", "/"),
    ("POST", "/chat"),
    ("POST", "/chat/confirm"),
    ("GET", "/chat/stream"),
    ("GET", "/health"),
    ("GET", "/ready"),
    ("GET", "/access"),
    ("POST", "/access"),
    ("POST", "/access/logout"),
    ("POST", "/session/actor"),
    ("GET", "/api/traces/turns/{turn_id}"),
}


def _routes(app) -> set[tuple[str, str]]:
    """Every method/path pair the app answers. FastAPI 0.141 keeps an included router nested."""
    routes = []
    for route in app.routes:
        routes.extend(getattr(getattr(route, "original_router", None), "routes", [route]))
    return {
        (method, route.path)
        for route in routes
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"}
    }


def test_the_route_table_is_exactly_the_endpoint_list_p8_owns():
    app = create_app()
    assert _routes(app) == EXPECTED_ROUTES


def test_the_mcp_server_is_mounted_in_process():
    """§8.1: one process, and the agent reaches its own tools over loopback Streamable HTTP."""
    app = create_app()
    mounts = {mount.path for mount in app.routes if type(mount).__name__ == "Mount"}
    assert {"/static", "/mcp-server"} <= mounts


async def test_a_live_app_serves_the_chat_page_and_health_with_no_credentials(web):
    async with web() as client:
        page = await client.get("/")
        health = await client.get("/health")

    assert page.status_code == 200
    assert "Mosaic HR Copilot" in page.text
    assert health.status_code == 200
    assert health.json()["app"]["version"]
