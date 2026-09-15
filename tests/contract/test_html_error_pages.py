"""**P6 — no dead-end error.** Every HTML navigation that fails comes back as a page (UX W1).

Before W1 every refusal on this app answered with a bare JSON body: a browser that followed a
citation chip, a stale deep link or a rate-limited retry was shown `{"code":"ADMIN_REQUIRED"}` as
plain text — no `<html lang>`, no heading, no landmark, nothing focusable, and no way back other
than the browser's own Back button.

The fix is content negotiation, not a second contract. `Accept: text/html` gets
`templates/refused.html` — the shared masthead, a plain sentence and a route back — and everything
else gets the identical JSON body it always got. The detection rule of the plan's §1 is exactly
what is asserted here: `content-type: text/html` and a body containing `href="/"`.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.anyio

HTML = {"Accept": "text/html,application/xhtml+xml"}
JSON = {"Accept": "*/*"}
TOKEN = "html-error-token"


def _gated() -> dict:
    return {"app_access_token": SecretStr(TOKEN), "app_env": "local"}


def _bearer() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def _assert_is_a_page(response) -> None:
    assert response.headers["content-type"].startswith("text/html"), response.headers["content-type"]
    body = response.text
    assert '<html lang="en">' in body, "a themed page, not a fragment"
    assert 'href="/"' in body, "a route back"
    assert 'class="masthead"' in body, "the shared masthead travels with every refusal"


async def test_the_admin_write_403_is_a_page_for_a_browser_and_json_for_a_client(web):
    async with web() as client:
        page = await client.post("/api/dev/reset-sandbox", json={}, headers=HTML)
        body = await client.post("/api/dev/reset-sandbox", json={}, headers=JSON)

    assert page.status_code == 403
    _assert_is_a_page(page)
    assert "ADMIN_REQUIRED" not in page.text, "the code is for the client, the sentence is for the human"

    assert body.status_code == 403
    assert body.headers["content-type"].startswith("application/json")
    assert body.json() == {"code": "ADMIN_REQUIRED"}


async def test_a_404_navigation_is_a_page_for_a_browser_and_json_for_a_client(web):
    """The class that used to be worst: a deep link to a session that retention has pruned."""
    async with web() as client:
        page = await client.get("/dashboard/sessions/" + "0" * 32, headers=HTML)
        body = await client.get("/dashboard/sessions/" + "0" * 32, headers=JSON)

    assert page.status_code == 404
    _assert_is_a_page(page)

    assert body.status_code == 404
    assert body.json() == {"code": "UNKNOWN_SESSION", "session_id": "0" * 32}


async def test_the_missing_token_403_is_a_page_for_a_browser_and_json_for_a_client(web):
    """`APP_ENV=render` with no `APP_ACCESS_TOKEN`: every gated route is refused (§11.4)."""
    async with web(app_env="render", app_access_token=None) as client:
        page = await client.get("/dashboard", headers=HTML)
        body = await client.get("/dashboard", headers=JSON)

    assert page.status_code == 403
    _assert_is_a_page(page)
    # The env-var name is an operator's detail, never a visitor's (jargon-and-exposure-17).
    assert "APP_ACCESS_TOKEN" not in page.text

    assert body.status_code == 403
    assert body.json()["code"] == "ACCESS_TOKEN_MISSING"


async def test_the_rate_limit_429_is_a_page_for_a_browser_and_json_for_a_client(web):
    async with web("rag_only.json", access_rate_limit_per_min=1) as client:
        await client.post("/chat", json={"message": "What is the weather in Berlin?"})
        page = await client.post("/chat", json={"message": "What is the weather in Berlin?"}, headers=HTML)
        body = await client.post("/chat", json={"message": "What is the weather in Berlin?"}, headers=JSON)

    assert page.status_code == 429
    _assert_is_a_page(page)

    assert body.status_code == 429
    assert body.json()["code"] == "RATE_LIMITED"


async def test_the_missing_key_401_is_still_the_key_page_and_never_a_refusal(web):
    """401 is the one refusal with a *forward* route: the key form, not a link back to `/`."""
    async with web(**_gated()) as client:
        page = await client.get("/dashboard", headers=HTML)
        body = await client.get("/dashboard", headers=JSON)

    assert page.status_code == 401
    assert page.headers["content-type"].startswith("text/html")
    assert 'action="/access"' in page.text
    assert '<html lang="en">' in page.text

    assert body.status_code == 401
    assert body.json()["code"] == "ACCESS_REQUIRED"


async def test_a_refusal_page_carries_the_identity_and_the_sign_out_the_masthead_owns(web):
    """The refusal is inside the shell, so the way back is the same one every page offers."""
    async with web(**_gated()) as client:
        page = await client.post("/api/dev/reset-sandbox", json={}, headers={**HTML, **_bearer()})

    assert page.status_code == 403
    _assert_is_a_page(page)
    assert 'action="/access/logout"' in page.text
    assert 'id="dashboard-link"' in page.text
