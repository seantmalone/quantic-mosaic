"""The plan's principles, asserted on the **rendered** page (`pytest -m ux`).

`docs/superpowers/plans/2026-09-14-ux-remediation-plan.md` §1 states each principle with a
mechanical detection rule. The contract suite already asserts the server's bytes; this suite asserts
what a browser actually paints, at the three viewports the audit measured, because that is where the
defects were found:

* **P3** one global nav on every page — identical markup, identical position;
* **P4** one gate, not two — the role gates writes, never reads and never navigation;
* **P5** no link is offered to a persona that cannot follow it;
* **P6** no dead-end error;
* **P7** nothing overflows — the document never scrolls sideways.
* **P11** (UX W2) the primary surface owns the page — one centred column at a readable measure, a
  sticky composer, the newest message in view, and no rail of technical output beside it;
* **P12** (UX W2) keyboard and screen-reader parity — Enter sends, focus returns, one live region,
  one plain-language announcement per turn, distinct names on every disclosure, type in `rem`;
* **P2 / P13** (UX W2) nothing technical survives onto the painted page;
* **P8** (UX W3) the demo controls are quarantined and labelled — one panel, and the conversation
  keeps its room on a phone.

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


def test_the_access_token_opens_the_suite_at_all(browser, ux_server):
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


# -- P11 --------------------------------------------------------------------------


def _ask(page, question: str) -> None:
    before = page.eval_on_selector_all("#messages .turn", "els => els.length")
    page.fill("#message", question)
    page.click("#send-button")
    page.wait_for_function("n => document.querySelectorAll('#messages .turn').length > n", arg=before, timeout=180_000)
    page.wait_for_timeout(800)


DEMO_1 = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"


def test_p11_the_conversation_owns_the_page_at_a_readable_measure(page, ux_server):
    """navigation-and-ia-18 / chat-production-ux-16: 836 of 1440px, at 99–107 characters."""
    page.goto(f"{ux_server}/", wait_until="networkidle")

    assert page.query_selector("aside.rail") is None, "the technical rail is not co-resident with the product"
    box = page.eval_on_selector(".conversation", "e => e.getBoundingClientRect().toJSON()")
    assert 37 * 16 <= box["width"] <= 40 * 16 + 1, f"the measure is {box['width']}px"
    centre = box["left"] + box["width"] / 2
    assert abs(centre - 1440 / 2) <= 2, f"the column is not centred: {box}"


def test_p11_the_composer_stays_reachable_and_the_newest_message_stays_in_view(fresh_page, fresh_server):
    """chat-production-ux-2: after one answer the document was 1406px against a 900px viewport."""
    fresh_page.goto(f"{fresh_server}/", wait_until="networkidle")
    assert fresh_page.eval_on_selector("#chat-form", "e => getComputedStyle(e).position") == "sticky"

    for question in (DEMO_1, "And what about the notice period?", "And carrying unused days over?"):
        _ask(fresh_page, question)

    assert fresh_page.eval_on_selector_all("#messages .turn", "els => els.length") == 3
    assert not _document_scrolls_sideways(fresh_page)
    grew = fresh_page.evaluate("() => document.documentElement.scrollHeight > window.innerHeight + 1")
    assert not grew, "the page is an app, not a growing document: the transcript scrolls, not the page"

    send = fresh_page.eval_on_selector("#send-button", "e => e.getBoundingClientRect().toJSON()")
    assert send["top"] >= 0 and send["bottom"] <= 900 + 1, f"the send control is off screen: {send}"

    stuck = fresh_page.eval_on_selector("#transcript", "e => e.scrollHeight - e.scrollTop - e.clientHeight <= 48")
    assert stuck, "the newest message is not in view"


# -- P12 --------------------------------------------------------------------------------


def test_p12_enter_sends_and_focus_comes_back_to_the_composer(page, ux_server):
    """chat-production-ux-3: Enter inserted a newline and there was no hint that it did."""
    page.goto(f"{ux_server}/", wait_until="networkidle")
    before = page.eval_on_selector_all("#messages .turn", "els => els.length")
    page.fill("#message", DEMO_1)
    page.press("#message", "Enter")
    page.wait_for_function("n => document.querySelectorAll('#messages .turn').length > n", arg=before, timeout=180_000)
    page.wait_for_timeout(500)

    assert page.evaluate("() => document.activeElement && document.activeElement.id") == "message"
    assert page.eval_on_selector("#message", "e => e.value") == "", "the composer is cleared for the next question"


def test_p12_the_page_has_exactly_one_live_region(page, ux_server):
    """accessibility-and-responsive-3: the rail was an `aria-live` firehose, 46 additions a turn."""
    page.goto(f"{ux_server}/", wait_until="networkidle")
    regions = page.eval_on_selector_all(
        "[role=status], [role=alert], [aria-live]", "els => els.map(e => e.id || e.className)"
    )
    assert regions == ["turn-status"], f"one live region, not a rail of them: {regions}"


def test_p12_the_finished_answer_is_announced_once_in_plain_language(fresh_page, fresh_server):
    """…and the rail never announced the answer at all — only the steps that produced it."""
    fresh_page.goto(f"{fresh_server}/", wait_until="networkidle")
    _ask(fresh_page, DEMO_1)

    assert fresh_page.eval_on_selector("#turn-status", "e => e.textContent") == "Answer ready."


def test_p12_body_type_scales_with_the_browser_default(page, ux_server):
    """A `px` body size ignores the reader's own font setting."""
    css = page.evaluate("url => fetch(url).then(r => r.text())", f"{ux_server}/static/app.css")
    assert "font: 16px/" not in css, "body copy is declared in rem, through the brand type tokens"
    assert "var(--text-body)" in css


def test_p12_no_two_disclosures_on_a_turn_share_an_accessible_name(fresh_page, fresh_server):
    fresh_page.goto(f"{fresh_server}/", wait_until="networkidle")
    _ask(fresh_page, DEMO_1)
    names = fresh_page.eval_on_selector_all("#messages summary", "els => els.map(e => e.textContent.trim())")
    assert names, "the answer offers its sources"
    assert len(names) == len(set(names)), f"two disclosures share a name: {names}"


# -- P2 and P13, on the painted page ----------------------------------------------------


# -- P8, on the painted page ------------------------------------------------------------


DEMO_CONTROL_SELECTORS = ("#actor-select", ".demo-button", 'a[href*="#turn-"]')


def _outside_the_panel(page, selector: str) -> int:
    return page.evaluate(
        "selector => Array.from(document.querySelectorAll(selector))"
        ".filter(el => !el.closest('section.demo-panel')).length",
        selector,
    )


def test_p8_every_demo_control_the_browser_paints_is_inside_the_panel(fresh_page, fresh_server):
    """The contract suite asserts the bytes of the page at rest; this asserts the live DOM, after a
    turn, when the deep link and the summary have been written into the panel by script."""
    fresh_page.goto(f"{fresh_server}/", wait_until="networkidle")
    _ask(fresh_page, DEMO_1)

    panel = fresh_page.query_selector("section.demo-panel")
    assert panel is not None, "one visually distinct section, and it is on the page"
    heading = fresh_page.eval_on_selector("section.demo-panel h2", "e => e.textContent")
    assert "Demo" in heading, f"the section says what it is: {heading!r}"

    for selector in DEMO_CONTROL_SELECTORS:
        loose = _outside_the_panel(fresh_page, selector)
        assert loose == 0, f"{loose} `{selector}` outside the demo panel"

    link = fresh_page.eval_on_selector(
        "#demo-dashboard-link", "e => ({href: e.getAttribute('href'), hidden: e.hidden})"
    )
    assert not link["hidden"] and re.match(r"^/dashboard/sessions/[0-9a-f]+#turn-\d+$", link["href"] or ""), link
    produced = fresh_page.eval_on_selector("#demo-produced", "e => e.textContent.trim()")
    assert re.fullmatch(r"Used \d+ tools?, read \d+ policy sections? and passed \d+ safety checks?\.", produced), (
        produced
    )


def test_p8_the_panel_is_collapsed_on_a_phone_so_the_conversation_keeps_its_room(browser, ux_server):
    """W2's review: `body.chat` has a definite height, so the panel spends the transcript's budget."""
    measurements = {}
    for label, width, height in (("desktop", 1440, 900), ("phone", 390, 844)):
        context = browser.new_context(viewport={"width": width, "height": height})
        tab = context.new_page()
        try:
            tab.goto(f"{ux_server}/?access={TOKEN}", wait_until="networkidle")
            tab.wait_for_timeout(250)
            measurements[label] = {
                "open": tab.eval_on_selector("#demo-details", "e => e.open"),
                "panel": tab.eval_on_selector("section.demo-panel", "e => e.getBoundingClientRect().height"),
                "transcript": tab.eval_on_selector("#transcript", "e => e.getBoundingClientRect().height"),
                "sideways": _document_scrolls_sideways(tab),
                "heading": tab.eval_on_selector("section.demo-panel h2", "e => e.textContent"),
            }
        finally:
            context.close()

    phone, desktop = measurements["phone"], measurements["desktop"]
    assert desktop["open"] is True, "there is room for it on a desktop, so it is open"
    assert phone["open"] is False, "and it is collapsed on a phone"
    assert "Demo" in phone["heading"], "with the same heading, which is the summary"
    assert phone["panel"] < desktop["panel"], f"the collapsed panel is not smaller: {measurements}"
    assert phone["transcript"] > 844 / 2, f"the conversation keeps its room: {measurements}"
    assert not phone["sideways"] and not desktop["sideways"]


def test_p8_a_demo_prompt_fills_the_composer_and_sends_nothing(page, ux_server):
    """navigation-and-ia-19: one click used to submit someone else's question into the reader's
    conversation. It fills the box; the reader still presses Send."""
    page.goto(f"{ux_server}/", wait_until="networkidle")
    before = page.eval_on_selector_all("#messages .turn", "els => els.length")

    page.click(".demo-button")
    page.wait_for_timeout(400)

    prompt = page.eval_on_selector(".demo-button", "e => e.dataset.prompt")
    assert page.eval_on_selector("#message", "e => e.value") == prompt
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == "message"
    assert page.eval_on_selector_all("#messages .turn", "els => els.length") == before, "nothing was sent"


def test_p8_the_deep_link_opens_the_dashboard_at_this_turn(fresh_page, fresh_server):
    """demo-and-grader-controls-4: the grader's route from a conversation to its record."""
    fresh_page.goto(f"{fresh_server}/", wait_until="networkidle")
    _ask(fresh_page, DEMO_1)

    href = fresh_page.eval_on_selector("#demo-dashboard-link", "e => e.getAttribute('href')")
    response = fresh_page.goto(fresh_server + href, wait_until="domcontentloaded")
    assert response is not None and response.status == 200, href
    anchor = href.split("#")[1]
    assert fresh_page.query_selector(f"#{anchor}") is not None, f"{href} lands on nothing"


# -- P12, the outcome sentences ----------------------------------------------------------


#: One recording per outcome the live region has a sentence for, and the question that reaches it.
ANNOUNCEMENT_CASES = (
    ("demo_task_1.json", DEMO_1, "Answer ready."),
    (
        "demo_task_2.json",
        "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
        "— and can you open the request for me?",
        "Waiting for your confirmation.",
    ),
    (
        "out_of_corpus_tuition.json",
        "What is Mosaic's tuition reimbursement cap for a part-time master's degree, and how many "
        "years of service do I need to qualify?",
        "I can't answer that one — see below.",
    ),
    ("fault_ambiguous.json", "Can I take some time off soon?", "Could you clarify?"),
)


@pytest.mark.parametrize(
    "scripted_server,question,expected",
    ANNOUNCEMENT_CASES,
    indirect=["scripted_server"],
    ids=[script.removesuffix(".json") for script, _, _ in ANNOUNCEMENT_CASES],
)
def test_p12_the_live_region_announces_the_outcome(scripted_page, scripted_server, question, expected):
    """Every outcome used to be announced as *"Answer ready."*, three of five of them falsely."""
    scripted_page.goto(f"{scripted_server}/", wait_until="networkidle")
    _ask(scripted_page, question)

    assert scripted_page.eval_on_selector("#turn-status", "e => e.textContent") == expected


@pytest.mark.parametrize("scripted_server", ["fault_ambiguous.json"], indirect=True)
def test_p12_a_failed_turn_is_announced_as_one(scripted_page, scripted_server):
    """`fault_ambiguous` holds one scripted reply; the second question exhausts it (§12.3)."""
    scripted_page.goto(f"{scripted_server}/", wait_until="networkidle")
    _ask(scripted_page, "Can I take some time off soon?")
    _ask(scripted_page, "And what about carrying unused days into next year?")

    assert scripted_page.eval_on_selector("#messages .turn:last-child", "e => e.dataset.outcome") == "error"
    assert scripted_page.eval_on_selector("#turn-status", "e => e.textContent") == (
        "Something went wrong — you can retry."
    )


def test_p2_and_p13_nothing_technical_survives_onto_the_painted_page(fresh_page, fresh_server):
    """The contract suite asserts the bytes; this asserts what a person is actually shown."""
    from tests.contract.test_chat_has_no_jargon import TEXT_FORBIDDEN

    fresh_page.goto(f"{fresh_server}/", wait_until="networkidle")
    _ask(fresh_page, DEMO_1)
    fresh_page.eval_on_selector_all("details", "els => els.forEach(d => { d.open = true; })")
    # The demo panel is labelled scaffolding and W3 owns it; everything else is the product.
    fresh_page.evaluate("() => { const d = document.querySelector('section.demo-panel'); if (d) d.remove(); }")
    fresh_page.wait_for_timeout(200)

    painted = fresh_page.evaluate("() => document.body.innerText")
    for pattern in TEXT_FORBIDDEN:
        found = re.findall(pattern, painted, flags=re.I)
        assert not found, f"the painted page says {pattern!r} — {found[:3]}"
