"""The access gate (spec §11 lead-in, §16.1, §17 *Access*).

One shared secret, three presentations, each compared with `secrets.compare_digest`:
`?access=<token>` (exchanged once for the HttpOnly cookie and **stripped from the URL**), the
`mosaic_access` cookie, and `Authorization: Bearer`. `/health`, `/ready`, `/static/*` and the key
page stay open, because a deployment that cannot report its own health is worse than an open one.

All the data behind the gate is synthetic, so this is a speed bump against scanners and drive-by
quota burn on a public repo — not secrecy. It still has to work exactly as documented, because the
grader's link is a tokenized URL and `deployed.md` promises the parameter disappears.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.anyio

TOKEN = "test-access-token-9f2c1b7e"
HTML = {"accept": "text/html,application/xhtml+xml"}


def _gated(**overrides):
    return {"app_access_token": SecretStr(TOKEN), **overrides}


def _bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


async def test_the_gate_is_off_locally_when_no_token_is_set(web):
    """`APP_ENV=local` with no `APP_ACCESS_TOKEN`: the gate is off and `/` is open (§11)."""
    async with web() as client:
        response = await client.get("/")
    assert response.status_code == 200


async def test_an_ambient_app_access_token_does_not_switch_the_gate_on_for_the_suite(web, monkeypatch):
    """An exported `APP_ACCESS_TOKEN` must not reach a test that never asked for the gate.

    `settings` is loaded from the environment at import, so before `tests/conftest.py` pinned the
    field the variable leaked into every `web()` app: the gate switched on, the fixtures' bare
    `X-Actor` headers carried no credential, and five gate tests plus all four of
    `test_smoke_eval_endpoint` went red with 401 `ACCESS_REQUIRED` — including under the Appendix A
    form of P11's own definition-of-done line, which runs that module with `APP_ACCESS_TOKEN` set.
    Patching the live settings object here is exactly what importing with the variable exported
    does, so this fails if the pin is ever removed.
    """
    from hrmosaic.settings import settings as live_settings

    monkeypatch.setattr(live_settings, "app_access_token", SecretStr("ambient-token-from-the-shell"))
    async with web() as client:
        response = await client.get("/")
    assert response.status_code == 200


async def test_a_gated_route_without_a_token_is_401_and_the_key_page(web):
    async with web(**_gated()) as client:
        page = await client.get("/", headers=HTML)
        api = await client.post("/chat", json={"message": "hello"})

    assert page.status_code == 401
    assert "Access key" in page.text and "<form" in page.text
    assert api.status_code == 401
    assert api.json()["code"] == "ACCESS_REQUIRED"


async def test_the_access_parameter_is_exchanged_for_a_cookie_and_stripped_from_the_url(web):
    async with web(**_gated()) as client:
        response = await client.get("/", params={"access": TOKEN, "keep": "me"})

    assert response.status_code == 302
    assert response.headers["location"] == "/?keep=me"
    assert "access" not in response.headers["location"]
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("mosaic_access=")
    assert TOKEN in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie or "SameSite=Lax" in cookie
    assert "Path=/" in cookie
    # http, not https, in the test: `Secure` would make the cookie unusable over loopback.
    assert "Secure" not in cookie


async def test_a_wrong_access_parameter_is_401_and_the_key_page(web):
    async with web(**_gated()) as client:
        response = await client.get("/", params={"access": "not-the-token"}, headers=HTML)

    assert response.status_code == 401
    assert "not recognised" in response.text
    assert "set-cookie" not in response.headers


async def test_the_cookie_alone_opens_a_gated_route(web):
    async with web(**_gated()) as client:
        client.cookies.set("mosaic_access", TOKEN)
        response = await client.get("/")
    assert response.status_code == 200


async def test_the_bearer_header_alone_opens_a_gated_route(web):
    async with web(**_gated()) as client:
        response = await client.get("/", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200


async def test_a_wrong_bearer_is_refused(web):
    async with web(**_gated()) as client:
        response = await client.get("/", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


async def test_health_ready_static_and_the_key_page_stay_open_with_the_gate_on(web):
    async with web(**_gated()) as client:
        health = await client.get("/health")
        ready = await client.get("/ready")
        static = await client.get("/static/app.css")
        key_page = await client.get("/access")

    assert health.status_code == 200
    assert ready.status_code in {200, 503}
    assert static.status_code == 200
    assert key_page.status_code == 200


async def test_the_key_form_sets_the_cookie_and_redirects_to_the_chat_page(web):
    async with web(**_gated()) as client:
        accepted = await client.post("/access", data={"access": TOKEN})
        refused = await client.post("/access", data={"access": "wrong"})

    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/"
    assert accepted.headers["set-cookie"].startswith("mosaic_access=")
    assert refused.status_code == 401


async def test_logout_clears_both_cookies(web):
    async with web(**_gated()) as client:
        response = await client.post("/access/logout")

    assert response.status_code == 303
    cookies = response.headers.get_list("set-cookie")
    assert any(header.startswith("mosaic_access=") and "Max-Age=0" in header for header in cookies)
    assert any(header.startswith("mosaic_actor=") and "Max-Age=0" in header for header in cookies)


async def test_render_with_no_token_fails_closed_and_health_says_so(web):
    """§11.4's fifth degradation string: the deployment is unusable and says so, at 200."""
    async with web(app_env="render", app_access_token=None) as client:
        gated = await client.get("/")
        health = await client.get("/health")

    assert gated.status_code == 403
    assert gated.json()["code"] == "ACCESS_TOKEN_MISSING"
    assert "APP_ACCESS_TOKEN" in gated.json()["detail"]
    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert "access_token_missing" in health.json()["degradations"]


async def test_the_dashboard_prefix_is_gated_before_it_is_admin_checked(web):
    """The gate runs before the persona check, and both run before the page (§11, §11.8)."""
    async with web(**_gated()) as client:
        anonymous = await client.get("/dashboard")
        employee = await client.get("/dashboard", headers={"Authorization": f"Bearer {TOKEN}"})
        as_admin = await client.get("/dashboard", headers={"Authorization": f"Bearer {TOKEN}", "X-Actor": "admin"})

    # No token at all is a 401 from the gate — the persona is never even consulted.
    assert anonymous.status_code == 401
    # Past the gate, the employee persona is refused by the admin check with §11's code.
    assert employee.status_code == 403
    assert employee.json() == {"code": "ADMIN_REQUIRED"}
    # Past both, page 1 renders.
    assert as_admin.status_code == 200


async def test_the_per_ip_rate_limit_covers_post_chat(web):
    """§17's denial-of-service row: `ACCESS_RATE_LIMIT_PER_MIN`, per IP, on `POST /chat`."""
    # An out-of-corpus question is refused by the deterministic pre-check before any model call
    # (§9.1 step 0), so three of them consume no stub entries and the limit is what is measured.
    async with web("rag_only.json", access_rate_limit_per_min=2) as client:
        statuses = [
            (await client.post("/chat", json={"message": "What is the weather in Berlin?"})).status_code
            for _ in range(3)
        ]
        # The limit is on `POST /chat` and the MCP mount, not on the whole app.
        page = await client.get("/")

    assert statuses[-1] == 429
    assert page.status_code == 200


# --------------------------------------------------------------------------------------
# The limit is keyed on the client address — and the app's own MCP client is on loopback
# --------------------------------------------------------------------------------------


async def test_four_turns_in_a_row_all_answer_because_the_apps_own_loopback_client_is_exempt(web):
    """The app must never 429 itself (§17).

    The limit is keyed on `request.client.host`, and the agent reaches its own MCP mount over
    loopback: `initialize`, `tools/list`, the long-lived `GET`, every `tools/call`, and the
    `client.discover()` behind each `GET /health` all arrive from `127.0.0.1`. Sharing one bucket
    with the visitor means a single tool-using turn spends ~10 of the budget, so a grader who asks
    a few questions in a minute silently gets `partial` answers with the tools refused underneath.

    Four turns under a per-IP limit of **four** is the proof: exactly four `POST /chat` requests,
    so the visitor-facing budget is spent to the last unit and nothing is left over for the app's
    own traffic. Every turn must still be `answered`.
    """
    async with web("four_turns.json", access_rate_limit_per_min=4) as client:
        outcomes = []
        for _ in range(4):
            response = await client.post("/chat", json={"message": "How much PTO do full-time employees accrue?"})
            assert response.status_code == 200, response.text
            outcomes.append(response.json()["outcome"])
            assert (await client.get("/health")).status_code == 200

    assert outcomes == ["answered"] * 4


async def test_a_forged_loopback_nonce_spends_the_budget_like_anyone_else(web):
    """The nonce is minted per process and never leaves it, so an outsider cannot guess it."""
    from hrmosaic.web import api

    call = {
        "json": {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        "headers": {"Accept": "application/json, text/event-stream", api.LOOPBACK_HEADER: "not-the-nonce"},
    }
    async with web("rag_only.json", access_rate_limit_per_min=1) as client:
        first = await client.post("/mcp-server/mcp", **call)
        second = await client.post("/mcp-server/mcp", **call)

    assert first.status_code != 429, "the first request is within the budget"
    assert second.status_code == 429, "a wrong nonce is not an exemption"


async def test_the_real_nonce_does_not_exempt_post_chat(web):
    """Only the MCP mount is ever exempt: `POST /chat` is the surface §17's limit exists for."""
    from hrmosaic.web import api

    headers = {api.LOOPBACK_HEADER: api.LOOPBACK_NONCE}
    async with web("rag_only.json", access_rate_limit_per_min=1) as client:
        question = {"message": "What is the weather in Berlin?"}
        first = await client.post("/chat", json=question, headers=headers)
        second = await client.post("/chat", json=question, headers=headers)

    assert (first.status_code, second.status_code) == (200, 429)


# --------------------------------------------------------------------------------------
# The gate is on but no token is configured — and an empty credential is not a key
# --------------------------------------------------------------------------------------


async def test_the_gate_with_no_token_configured_refuses_every_empty_credential(web):
    """`APP_ENV=docker` with `APP_ACCESS_TOKEN` unset: the gate is on and nothing opens it.

    `gate_enabled()` is true for any `APP_ENV` that is not `local`, but `gate_misconfigured()`
    fails closed for `render` **only** — §11.4 scopes the `access_token_missing` degradation to the
    deployed environment. `docker` is a documented value (`.env.example`, `settings.py`), so the
    gate could be on with the resolved token an empty string, and `compare_digest(x, "")` succeeds
    for an empty `x`: a bare `Authorization: Bearer`, `Cookie: mosaic_access=` and `?access=` each
    opened a gate that had just refused the anonymous request one line earlier.

    httpx refuses to send `"Bearer "` with its trailing space (`LocalProtocolError: Illegal header
    value`), so the bare scheme is used — `header.partition(" ")` reaches the same empty value.
    """
    async with web(app_env="docker", app_access_token=None) as client:
        anonymous = await client.get("/")
        bearer = await client.get("/", headers={"Authorization": "Bearer"})
        client.cookies.set("mosaic_access", "")
        cookie = await client.get("/")
        client.cookies.clear()
        parameter = await client.get("/", params={"access": ""})
        form = await client.post("/access", data={"access": ""})

    assert anonymous.status_code == 403
    assert bearer.status_code == 403, "an empty bearer is not a credential"
    assert cookie.status_code == 403, "an empty cookie is not a credential"
    assert parameter.status_code == 403, "an empty `?access=` is not a credential"
    assert form.status_code == 403, "the key form does not mint a cookie for an empty field"
    for refused in (anonymous, bearer, cookie, parameter, form):
        assert "set-cookie" not in refused.headers
        assert "APP_ACCESS_TOKEN" in refused.text


# --------------------------------------------------------------------------------------
# `Secure` behind a TLS-terminating edge
# --------------------------------------------------------------------------------------


async def test_the_cookie_is_marked_secure_when_the_edge_terminated_tls(web):
    """Constraint 9's *"Secure on https"* has to hold on Render, where ASGI only ever sees http.

    Render terminates TLS at its edge and forwards plain http into the container; uvicorn's
    `ProxyHeadersMiddleware` rewrites `scope["scheme"]` only for a trusted peer (`127.0.0.1` by
    default), which the edge is not. `request.url.scheme` is therefore `http` on the deployed
    service, and every cookie shipped without `Secure` — while `deployed.md` published the
    opposite. `request_is_https()` reads `X-Forwarded-Proto` for this, and for nothing else:
    forging the header only makes the forger's own cookie `Secure`.
    """
    https = {"X-Forwarded-Proto": "https"}
    async with web(**_gated()) as client:
        exchanged = await client.get("/", params={"access": TOKEN}, headers=https)
        form = await client.post("/access", data={"access": TOKEN}, headers=https)
        actor = await client.post("/session/actor", json={"actor": "admin"}, headers={**https, **_bearer()})

    assert "Secure" in exchanged.headers["set-cookie"]
    assert "Secure" in form.headers["set-cookie"]
    assert "Secure" in actor.headers["set-cookie"], "the act-as cookie travels the same wire"
    # And the loopback case is unchanged: a `Secure` cookie over plain http is simply dropped.
    async with web(**_gated()) as client:
        plain = await client.get("/", params={"access": TOKEN})
    assert "Secure" not in plain.headers["set-cookie"]


# --------------------------------------------------------------------------------------
# The MCP mount is gated, and that is the protection `mcp/README.md` says it relies on
# --------------------------------------------------------------------------------------


async def test_the_mcp_mount_is_refused_without_a_credential(web):
    """§17's *MCP endpoint exposure* row, and the reason no DNS-rebinding allowlist is configured.

    `mcp/README.md` says in as many words that the SDK's own `allowed_hosts`/`allowed_origins`
    guard is left unconfigured because *"the protection this project relies on is the gate"*. That
    sentence is only true while the mount is actually behind the gate, and until now every test of
    the mount ran with the gate off.
    """
    call = {
        "json": {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        "headers": {"Accept": "application/json, text/event-stream"},
    }
    async with web(**_gated()) as client:
        anonymous = await client.post("/mcp-server/mcp", **call)
        credentialed = await client.post("/mcp-server/mcp", json=call["json"], headers={**call["headers"], **_bearer()})

    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "ACCESS_REQUIRED"
    assert credentialed.status_code != 401
