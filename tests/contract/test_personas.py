"""The two personas (spec §11, §16.1, §17 *Identity*).

Authentication is the shared access token — **no user accounts, by design**. Authorization is the
persona: cookie `mosaic_actor` or header `X-Actor`, an `E1xxx` id or the literal `admin`,
defaulting to `E1042`. Admin-only, enforced server-side with **403** `{"code": "ADMIN_REQUIRED"}`:
the three write endpoints (`POST /api/dev/reset-sandbox`, `POST /api/mcp/rediscover`,
`POST /api/eval/runs`) and the privileged `POST /chat` options. Reads — every `/dashboard/*` page
and every `/api/*` GET — are open to any persona holding the access token (W1's *one gate*).

Inside the MCP tools the acting id stays audit-only: it is recorded on every `tool_call` span for
*who asked*, and grants and denies nothing, because the data is entirely synthetic (§8.7). What the
persona does gate is the observability surface, and `sessions.auth_mode` / `sessions.actor_role`
record both levels on every session.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio

QUESTION = "How much PTO do full-time employees accrue each month?"
ADMIN = {"X-Actor": "admin"}


async def _turn(client, **body):
    response = await client.post("/chat", json={"message": QUESTION, **body})
    assert response.status_code == 200, response.text
    return response.json()


def _session(store, session_id: str) -> dict:
    return store.execute(
        "SELECT employee_id, auth_mode, actor_role, client_label FROM sessions WHERE id = ?", (session_id,)
    ).one()


async def test_the_dashboard_prefix_is_open_to_every_persona_holding_the_token(web):
    """**P4** — the role gates writes, never reads and never navigation (W1).

    `/dashboard/sessions/abc` is an unknown id, so it is a 404 rather than a 200 — but a 404 from
    the *page*, not a 403 from the gate, which is the whole point: the employee persona now
    reaches the handler.
    """
    async with web() as client:
        employee = await client.get("/dashboard")
        deeper = await client.get("/dashboard/sessions/abc")

    assert employee.status_code == 200
    assert deeper.status_code == 404
    assert deeper.json() == {"code": "UNKNOWN_SESSION", "session_id": "abc"}


async def test_only_the_three_write_endpoints_still_require_the_admin_persona(web):
    """The exact `(method, path)` set `needs_admin()` matches, and nothing wider (W1).

    `GET /api/eval/runs` and `POST /api/eval/runs` share a path, so the pair is what the gate keys
    on: the read is open and the write is not.
    """
    async with web() as client:
        writes = {
            url: await client.post(url, json={})
            for url in ("/api/dev/reset-sandbox", "/api/mcp/rediscover", "/api/eval/runs")
        }
        read_on_a_write_path = await client.get("/api/eval/runs")

    for url, response in writes.items():
        assert response.status_code == 403, url
        assert response.json() == {"code": "ADMIN_REQUIRED"}, url
    assert read_on_a_write_path.status_code == 200


async def test_the_single_turn_view_model_reads_200_in_either_persona(web):
    """The route the 202 fallback and the demo scripts poll (§11.8)."""
    async with web("rag_only.json") as client:
        turn = await _turn(client)
        as_employee = await client.get(f"/api/traces/turns/{turn['turn_id']}")
        allowed = await client.get(f"/api/traces/turns/{turn['turn_id']}", headers=ADMIN)
        missing = await client.get(f"/api/traces/turns/{'0' * 32}", headers=ADMIN)

    # W1: a read is a read. The single-turn view-model is what the 202 fallback polls, and the
    # demo scripts reach it in the default persona.
    assert as_employee.status_code == 200
    assert as_employee.json()["turn_id"] == turn["turn_id"]
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["turn_id"] == turn["turn_id"]
    assert body["outcome"] == "answered"
    assert body["spans"] and body["spans"][0]["seq"] == 1
    assert body["dashboard_url"] == turn["dashboard_url"]
    assert missing.status_code == 404


async def test_an_absent_cookie_defaults_the_actor_to_e1042(web, store):
    async with web("rag_only.json") as client:
        turn = await _turn(client)

    row = _session(store, turn["session_id"])
    assert row["employee_id"] == "E1042"
    assert row["actor_role"] == "employee"
    assert row["auth_mode"] == "open"


async def test_post_session_actor_sets_the_mosaic_actor_cookie(web, store):
    async with web("rag_only.json") as client:
        response = await client.post("/session/actor", json={"actor": "E1108"})
        turn = await _turn(client)

    assert response.status_code == 200
    assert response.json() == {"actor": "E1108", "actor_role": "employee"}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("mosaic_actor=E1108")
    assert "HttpOnly" not in cookie  # the selector reads it; it grants nothing on its own
    assert _session(store, turn["session_id"])["employee_id"] == "E1108"


async def test_an_invalid_actor_is_refused_by_the_selector(web):
    async with web() as client:
        response = await client.post("/session/actor", json={"actor": "root"})
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


async def test_the_x_actor_header_wins_over_the_cookie(web, store):
    # The second turn asks an out-of-corpus question, refused by the deterministic pre-check
    # before any model call (§9.1 step 0), so one four-entry stub script covers both turns.
    async with web("rag_only.json") as client:
        turn = await _turn(client, session_id=None)
        client.cookies.set("mosaic_actor", "E1108")
        cookie_turn = await client.post("/chat", json={"message": "What is the weather in Berlin?"})
        header_turn = await client.post("/chat", json={"message": "What is the weather in Berlin?"}, headers=ADMIN)

    assert _session(store, turn["session_id"])["employee_id"] == "E1042"
    assert _session(store, cookie_turn.json()["session_id"])["employee_id"] == "E1108"
    assert _session(store, header_turn.json()["session_id"])["employee_id"] == "admin"
    assert _session(store, header_turn.json()["session_id"])["actor_role"] == "admin"


async def test_the_admin_persona_is_recorded_on_the_session(web, store):
    """`sessions.actor_role` is what dashboard pages 1-2 filter on (§10.1)."""
    async with web("rag_only.json") as client:
        turn = await _turn(client, client_label="api")

    row = _session(store, turn["session_id"])
    assert row["client_label"] == "api"
    assert row["actor_role"] == "employee"


async def test_the_admin_persona_chats_as_the_actor_admin(web, store):
    """§11: the admin persona chats as actor `admin`; the people tools still read their arguments."""
    async with web("rag_only.json") as client:
        response = await client.post("/chat", json={"message": QUESTION}, headers=ADMIN)
        assert response.status_code == 200, response.text

    row = _session(store, response.json()["session_id"])
    assert (row["employee_id"], row["actor_role"]) == ("admin", "admin")
