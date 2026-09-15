"""The plan's principles, asserted on the **rendered** page (`pytest -m ux`).

`docs/superpowers/plans/2026-09-14-ux-remediation-plan.md` §1 states each principle with a
mechanical detection rule, and these are the first five of them. The contract suite already asserts
the server's bytes; this suite asserts what a browser actually paints, at the three viewports the
audit measured, because that is where the defects were found:

* **P3** one global nav on every page — identical markup, identical position;
* **P4** one gate, not two — the role gates writes, never reads and never navigation;
* **P5** no link is offered to a persona that cannot follow it;
* **P6** no dead-end error;
* **P7** nothing overflows — the document never scrolls sideways.

Every test is marked `ux` and deselected from `pytest -q` (see `pyproject.toml`); CI runs them in a
job of its own that installs chromium.
"""

from __future__ import annotations

import re

import pytest

from tests.ux.conftest import TOKEN, VIEWPORTS

pytestmark = pytest.mark.ux

MASTHEAD_JS = "() => document.querySelector('header.masthead').outerHTML"
ARIA_CURRENT = re.compile(r'\s*aria-current="page"')

DASHBOARD_ROUTES = (
    "/dashboard",
    "/dashboard/sessions",
    "/dashboard/turns",
    "/dashboard/llm",
    "/dashboard/retrieval",
    "/dashboard/tools",
    "/dashboard/safety",
    "/dashboard/mcp",
    "/dashboard/corpus",
    "/dashboard/evals",
)

#: The three write endpoints, and the reads that share a prefix — or, for `/api/eval/runs`, a path.
WRITE_ENDPOINTS = ("/api/dev/reset-sandbox", "/api/mcp/rediscover", "/api/eval/runs")
READ_ENDPOINTS = ("/api/traces/overview", "/api/traces/sessions", "/api/eval/runs", "/api/corpus/documents")


def _masthead(page) -> str:
    return ARIA_CURRENT.sub("", page.evaluate(MASTHEAD_JS))


def _document_scrolls_sideways(page) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"))


# -- P3 ---------------------------------------------------------------------------------


def test_p3_the_masthead_is_identical_on_every_authenticated_page(page, ux_server):
    page.goto(f"{ux_server}/", wait_until="networkidle")
    chat = _masthead(page)
    assert "Dashboard" in chat and "Chat" in chat

    for route in DASHBOARD_ROUTES:
        page.goto(ux_server + route, wait_until="networkidle")
        assert _masthead(page) == chat, f"the rendered masthead on {route} differs from the one on /"


def test_p3_the_masthead_is_on_screen_at_every_viewport(page, ux_server):
    """navigation-and-ia-12: at 390px the switch and Sign out used to sit outside the viewport."""
    for route in ("/", "/dashboard"):
        page.goto(ux_server + route, wait_until="networkidle")
        for label, width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(200)
            for selector in ("#chat-link", "#dashboard-link", ".identity-chip", ".signout-form button"):
                box = page.eval_on_selector(selector, "e => e.getBoundingClientRect().toJSON()")
                assert box["right"] <= width + 1, f"{selector} runs off {label} on {route}: {box}"
                assert box["left"] >= -1, f"{selector} starts off {label} on {route}: {box}"


# -- P4 ---------------------------------------------------------------------------------


def test_p4_every_dashboard_page_and_api_read_answers_200_in_the_default_persona(page, ux_server):
    for route in (*DASHBOARD_ROUTES, *READ_ENDPOINTS):
        response = page.goto(ux_server + route, wait_until="domcontentloaded")
        assert response is not None and response.status == 200, f"{route} answered {response and response.status}"


def test_p4_the_three_write_endpoints_still_refuse_the_default_persona(page, ux_server):
    for route in WRITE_ENDPOINTS:
        status = page.evaluate(
            "url => fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})"
            ".then(r => r.status)",
            ux_server + route,
        )
        assert status == 403, f"{route} answered {status} to a non-admin POST"


# -- P5 ---------------------------------------------------------------------------------


def test_p5_every_href_the_chat_page_renders_resolves_for_the_persona_shown_it(page, ux_server):
    page.goto(f"{ux_server}/", wait_until="networkidle")
    page.fill("#message", "I want to work from Berlin from 3 November to 14 December 2026 — can I?")
    page.click("#send-button")
    page.wait_for_selector("#messages .turn", timeout=180_000)
    page.wait_for_timeout(1500)

    hrefs = page.evaluate(
        "() => Array.from(document.querySelectorAll('a[href]'))"
        ".map(a => a.getAttribute('href'))"
        ".filter(h => h && h.startsWith('/'))"
    )
    assert any(href.startswith("/policy/") for href in hrefs), "the answer cites something"

    statuses = {
        href: page.evaluate("url => fetch(url).then(r => r.status)", ux_server + href) for href in sorted(set(hrefs))
    }
    assert all(200 <= status < 300 for status in statuses.values()), statuses


# -- P6 ---------------------------------------------------------------------------------


def test_p6_no_html_navigation_dead_ends(page, ux_server):
    """A themed page with the global nav and a route back — never a bare JSON body."""
    for route, expected in (
        ("/dashboard/nope", 404),
        (f"/dashboard/sessions/{'0' * 32}", 404),
        ("/policy/not-a-document", 404),
    ):
        response = page.goto(ux_server + route, wait_until="domcontentloaded")
        assert response is not None and response.status == expected, route
        assert page.query_selector("header.masthead") is not None, f"{route} has no global nav"
        assert page.query_selector('a[href="/"]') is not None, f"{route} offers no route back"
        body = page.evaluate("() => document.body.innerText")
        assert not body.strip().startswith("{"), f"{route} rendered a raw JSON body"


# -- P7 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("label,width,height", VIEWPORTS, ids=[label for label, _, _ in VIEWPORTS])
def test_p7_the_document_never_scrolls_sideways(page, ux_server, label, width, height):
    """26 of 26 chat screens scrolled the document sideways at 390px before W1."""
    page.set_viewport_size({"width": width, "height": height})
    sideways = []
    for route in ("/", "/access", "/dashboard", "/dashboard/sessions", "/dashboard/turns", "/dashboard/corpus"):
        page.goto(ux_server + route, wait_until="networkidle")
        page.wait_for_timeout(250)
        if _document_scrolls_sideways(page):
            sideways.append(route)
    assert not sideways, f"these routes scroll the document sideways at {label}: {sideways}"


def test_p7_an_answered_turn_does_not_scroll_the_document_sideways_on_a_phone(page, ux_server):
    page.goto(f"{ux_server}/", wait_until="networkidle")
    page.fill("#message", "I want to work from Berlin from 3 November to 14 December 2026 — can I?")
    page.click("#send-button")
    page.wait_for_selector("#messages .turn", timeout=180_000)
    page.wait_for_timeout(1500)

    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    assert not _document_scrolls_sideways(page)


def test_the_access_token_opens_the_suite_at_all(ux_server, browser):
    """A guard on the fixture itself: without the key every assertion above would be vacuous."""
    context = browser.new_context()
    tab = context.new_page()
    try:
        refused = tab.goto(f"{ux_server}/", wait_until="domcontentloaded")
        assert refused is not None and refused.status == 401
        allowed = tab.goto(f"{ux_server}/?access={TOKEN}", wait_until="domcontentloaded")
        assert allowed is not None and allowed.status == 200
    finally:
        context.close()
