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


async def test_the_gate_is_off_locally_when_no_token_is_set(web):
    """`APP_ENV=local` with no `APP_ACCESS_TOKEN`: the gate is off and `/` is open (§11)."""
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
    """The dashboard pages are P9's; the prefix answers the gate from P8 (§11.8)."""
    async with web(**_gated()) as client:
        anonymous = await client.get("/dashboard")
        as_admin = await client.get("/dashboard", headers={"Authorization": f"Bearer {TOKEN}", "X-Actor": "admin"})

    assert anonymous.status_code == 401
    # Past the gate and past the persona check, the page itself does not exist until P9.
    assert as_admin.status_code == 404


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
