"""The application boots and serves the endpoint list of §11.8 — nothing more, nothing less.

A boot test earns its place here because §12.3's rule is that **boot always succeeds**: a missing
credential, an unbuilt index or an unreachable store degrades the surface that needs it and never
stops the process. So this file starts the real app on a real port with no credentials at all.
"""

from __future__ import annotations

import pytest

from hrmosaic.web.main import create_app

pytestmark = pytest.mark.anyio

#: Every path §11.8 lists. P8 owns the chat, access and health half; P9's `web/dashboard.py` adds
#: the eleven pages and the whole `/api/*` layer, including the full
#: `GET /api/traces/turns/{turn_id}` the 202 fallback and `scripts/demo_task_*.sh` poll.
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
    # the eleven dashboard pages (§11.6)
    ("GET", "/dashboard"),
    ("GET", "/dashboard/sessions"),
    ("GET", "/dashboard/sessions/{session_id}"),
    ("GET", "/dashboard/turns"),
    ("GET", "/dashboard/llm"),
    ("GET", "/dashboard/retrieval"),
    ("GET", "/dashboard/tools"),
    ("GET", "/dashboard/safety"),
    ("GET", "/dashboard/mcp"),
    ("GET", "/dashboard/corpus"),
    ("GET", "/dashboard/corpus/{doc_id}"),
    ("GET", "/dashboard/evals"),
    ("GET", "/dashboard/evals/{run_id}"),
    # the `/api/*` layer each page renders from (§11.8)
    ("GET", "/api/traces/overview"),
    ("GET", "/api/traces/sessions"),
    ("GET", "/api/traces/sessions/{session_id}"),
    ("GET", "/api/traces/turns"),
    ("GET", "/api/traces/turns/{turn_id}"),
    ("GET", "/api/traces/llm"),
    ("GET", "/api/traces/retrieval"),
    ("GET", "/api/traces/tools"),
    ("GET", "/api/traces/safety"),
    ("GET", "/api/eval/runs"),
    ("POST", "/api/eval/runs"),
    ("GET", "/api/eval/runs/{run_id}"),
    ("GET", "/api/eval/compare"),
    ("GET", "/api/corpus/documents"),
    ("GET", "/api/corpus/documents/{doc_id}"),
    ("GET", "/api/corpus/chunks/{chunk_id}"),
    ("GET", "/api/mcp/discovery"),
    ("POST", "/api/mcp/rediscover"),
    ("POST", "/api/dev/reset-sandbox"),
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


def test_the_route_table_is_exactly_the_endpoint_list_of_the_spec():
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
