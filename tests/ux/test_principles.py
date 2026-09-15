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
* **P8** (UX W3) the demo controls are quarantined and labelled — one panel, collapsed at every
  viewport, so the conversation keeps its room.

Every test is marked `ux` and deselected from `pytest -q` (see `pyproject.toml`); CI runs them in a
job of its own that installs chromium.
"""

from __future__ import annotations

import re

import pytest

from tests.ux.conftest import TOKEN, VIEWPORTS, resolve

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
    # The page is an app, not a growing document: the transcript scrolls, not the page. Since UX W7
    # (Addendum 2) the demo panel is always expanded and the transcript keeps an 18rem floor, so
    # the page *may* scroll by what the panel costs once it carries a turn's summary — that is the
    # panel's room, the same after one turn as after three, and it is bounded by the panel itself.
    # What may never happen is the transcript's content leaking into the page's height, which is
    # what `min-height: 0` on `.conversation` (W2) and `contain: size` on `.transcript` (W7) stop.
    geometry = fresh_page.evaluate(
        """() => ({
          doc: document.documentElement.scrollHeight, inner: window.innerHeight,
          panel: document.querySelector('section.demo-panel').getBoundingClientRect().height,
          transcript: document.getElementById('transcript').clientHeight,
          content: document.getElementById('transcript').scrollHeight })"""
    )
    assert geometry["content"] > geometry["transcript"], f"the transcript is not what scrolls: {geometry}"
    assert geometry["transcript"] >= 18 * 16 - 1, f"the transcript is below its floor: {geometry}"
    assert geometry["doc"] - geometry["inner"] < geometry["panel"], f"the page grew with the conversation: {geometry}"

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


# `test_p12_body_type_scales_with_the_browser_default` lived here from W2 until W5, when
# `tests/ux/test_accessibility.py::test_the_stylesheet_declares_no_pixel_type` replaced it with the
# stronger statement it was a special case of: *no* declaration sizes type in pixels, not merely the
# one `body { font: 16px/… }` rule the brand sweep removed.


def test_p12_no_two_disclosures_on_a_turn_share_an_accessible_name(fresh_page, fresh_server):
    fresh_page.goto(f"{fresh_server}/", wait_until="networkidle")
    _ask(fresh_page, DEMO_1)
    names = fresh_page.eval_on_selector_all("#messages summary", "els => els.map(e => e.textContent.trim())")
    assert names, "the answer offers its sources"
    assert len(names) == len(set(names)), f"two disclosures share a name: {names}"


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
    expected = (
        r"How this answer was produced: \d+ tools? used, \d+ policy sections? read, "
        r"in (under a second|\d+\.\d+ (seconds|minutes))\. "
        r"\d+ of the 6 safety checks applied to this answer; (all \d+|\d+ of the \d+) passed\."
    )
    assert re.fullmatch(expected, produced), produced


#: The panel as painted: what it holds, whether every control is on the page without a click, and
#: what is left of the conversation beside it.
PANEL_JS = r"""
() => {
  const panel = document.querySelector("section.demo-panel");
  const transcript = document.getElementById("transcript");
  const painted = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0; };
  const controls = ["#actor-select", ".demo-button", "#demo-no-turn", ".demo-env", ".demo-signout button"];
  return {
    disclosures: panel.querySelectorAll("details, summary").length,
    scripts: panel.querySelectorAll("script").length,
    heading: panel.querySelector("h2").textContent.trim(),
    note: panel.querySelector(".demo-note").textContent.trim(),
    note_painted: painted(panel.querySelector(".demo-note")),
    unpainted: controls.filter((s) => !Array.from(panel.querySelectorAll(s)).every(painted)),
    panel_scroll: panel.scrollHeight,
    panel_client: panel.clientHeight,
    transcript: transcript.getBoundingClientRect().height,
    transcript_overflow: getComputedStyle(transcript).overflowY,
    starters: document.querySelectorAll(".starter").length,
    send: document.getElementById("send-button").getBoundingClientRect().toJSON(),
    doc: document.documentElement.scrollHeight,
    inner: window.innerHeight,
  };
}
"""

#: Each starter question, scrolled to by the reader's own means and then measured against the
#: viewport: a starter is reachable when scrolling brings the whole of it on screen.
STARTERS_REACHABLE_JS = r"""
() => Array.from(document.querySelectorAll(".starter")).map((el) => {
  el.scrollIntoView({ block: "nearest" });
  const r = el.getBoundingClientRect();
  return r.top >= -1 && r.bottom <= window.innerHeight + 1;
})
"""

PANEL_VIEWPORTS = (("desktop", 1440, 900), ("laptop", 1280, 800), ("phone", 390, 844))


def test_p8_the_panel_is_always_expanded_and_the_conversation_keeps_its_floor(browser, ux_server):
    """UX W7, Addendum 2 — the owner's decision, overriding the collapsed `<details>` of W3 and its
    remembered open state: the panel is a plain section with every control on the page at every
    viewport, and the conversation is not what pays for it. `.transcript` has an 18rem floor, so on
    a viewport the panel does not fit beside, the page scrolls; on a phone it already did."""
    for label, width, height in PANEL_VIEWPORTS:
        context = browser.new_context(viewport={"width": width, "height": height})
        tab = context.new_page()
        try:
            tab.goto(f"{ux_server}/?access={TOKEN}", wait_until="networkidle")
            tab.wait_for_timeout(250)
            panel = tab.evaluate(PANEL_JS)
            assert panel["disclosures"] == 0, f"{label}: the panel still has a collapsed state: {panel}"
            assert panel["scripts"] == 0, f"{label}: the panel still carries a script (nothing to remember)"
            assert "Demo" in panel["heading"], f"{label}: the section says what it is: {panel['heading']!r}"
            assert panel["note_painted"], f"{label}: the disclaimer is not painted: {panel}"
            assert panel["note"] == "For evaluation only — a real user never sees this panel.", panel["note"]
            assert not panel["unpainted"], f"{label}: controls not on the page without a click: {panel['unpainted']}"
            assert panel["panel_scroll"] <= panel["panel_client"] + 1, (
                f"{label}: the panel scrolls inside itself: {panel}"
            )
            assert panel["starters"] == 4, "the plan's §3.1 wireframe is four starter questions"
            assert not _document_scrolls_sideways(tab), f"{label}: the document scrolls sideways"
            assert panel["send"]["bottom"] <= height + 1, f"{label}: the composer is off screen on arrival: {panel}"
            if label == "phone":
                assert panel["transcript_overflow"] == "visible", "on a phone the page is the scroller"
                assert panel["doc"] > panel["inner"], f"the phone page does not scroll: {panel}"
            else:
                assert panel["transcript"] >= 18 * 16 - 1, f"{label}: the transcript is below its floor: {panel}"
            if label == "desktop":
                assert panel["doc"] <= panel["inner"] + 1, f"at 1440x900 the page grew to fit the panel: {panel}"
            reachable = tab.evaluate(STARTERS_REACHABLE_JS)
            assert all(reachable), f"{label}: a starter question cannot be scrolled into view: {reachable}"
        finally:
            context.close()


def test_p8_the_panel_has_no_collapsed_state_to_remember(browser, ux_server):
    """It used to remember an explicit open in `localStorage`. There is no open to remember: a
    reload and a second browser profile both show the same expanded panel."""
    for _profile in range(2):
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        try:
            tab = context.new_page()
            tab.goto(f"{ux_server}/?access={TOKEN}", wait_until="networkidle")
            before = tab.evaluate(PANEL_JS)
            tab.reload(wait_until="networkidle")
            after = tab.evaluate(PANEL_JS)
            for panel in (before, after):
                assert panel["disclosures"] == 0 and not panel["unpainted"], panel
            remembered = tab.evaluate(
                "() => { try { return Object.keys(window.localStorage).filter(k => k.includes('demo')); }"
                " catch (e) { return []; } }"
            )
            assert remembered == [], f"the page still remembers a panel state: {remembered}"
        finally:
            context.close()


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
        # No direction in it: the line is visually hidden once the turn has finished, so "see
        # below" pointed at the composer (UX W7, cpux2-3).
        "I can't answer that one.",
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


# -- P2 and P13, on the painted page ----------------------------------------------------


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


# -- UX W7: the phone, and the viewport that changes under the page ---------------------------
#
# cpux2-1 = a11y-re2-2 (the wave's Critical), cpux2-2 = a11y-re2-4 and npo3-03 = dgc-r2-4 were all
# W6 regressions this file could not see: every chat test above loads the page at 1440x900, and
# where the suite looked at a phone at all it *resized* an already-loaded page — a state no reader
# reaches by loading (the scorer's §6). Each test below is a fresh load at its own viewport, and the
# one that does resize is testing the resize.

#: The newest turn's bottom edge against the viewport, and how far the document has scrolled.
NEWEST_TURN_JS = """
() => {
  const turns = document.querySelectorAll('#messages .turn');
  const box = turns[turns.length - 1].getBoundingClientRect();
  return { bottom: Math.round(box.bottom), viewport: window.innerHeight, scrollY: Math.round(window.scrollY) };
}
"""

#: Whether the composer's box holds its placeholder. An empty textarea's `scrollHeight` measures
#: its empty value, not the two lines the placeholder wraps to at 390px — which is how W6's on-load
#: `autogrow()` shipped green while the placeholder was clipped mid-glyph on 17 of the 29 phone
#: screens (npo3-03). The placeholder is therefore measured *as* the value, with the box's own
#: height left exactly as the page set it.
COMPOSER_FIT_JS = """
() => {
  const box = document.getElementById('message');
  const value = box.value;
  box.value = box.placeholder;
  const fit = { scrollHeight: box.scrollHeight, clientHeight: box.clientHeight, height: box.style.height };
  box.value = value;
  return fit;
}
"""

CHAT_SCREENS = ("/", "{conversation}")


def _fresh_tab(browser, base_url: str, width: int, height: int):
    """A signed-in tab whose FIRST paint is at this viewport."""
    context = browser.new_context(viewport={"width": width, "height": height})
    tab = context.new_page()
    tab.goto(f"{base_url}/?access={TOKEN}", wait_until="networkidle")
    return context, tab


def _transcript_is_stuck(page) -> bool:
    return bool(page.eval_on_selector("#transcript", "e => e.scrollHeight - e.scrollTop - e.clientHeight <= 48"))


def test_the_newest_turn_is_brought_into_view_on_a_phone_and_jump_to_latest_works(browser, fresh_server):
    """cpux2-1 = a11y-re2-2 — Critical. W6 rightly made a phone a document (the transcript stops
    being a scroll box below 30rem), and every scroll mechanism went on writing
    `transcript.scrollTop` — a no-op on a box that does not scroll. `atBottom()` then said "yes"
    forever, `#jump-latest` never appeared, and a reader who sent a question was left looking at it
    with the answer a screen below and nothing offering to take them there."""
    context, page = _fresh_tab(browser, fresh_server, 390, 844)
    try:
        _ask(page, DEMO_1)
        overflow = page.eval_on_selector("#transcript", "e => getComputedStyle(e).overflowY")
        assert overflow == "visible", "on a phone the document is the scroller, not the transcript"
        newest = page.evaluate(NEWEST_TURN_JS)
        assert newest["scrollY"] > 0, f"the page never moved after the turn landed: {newest}"
        assert newest["bottom"] <= newest["viewport"], f"the newest turn's end is below the fold: {newest}"
        assert page.eval_on_selector("#jump-latest", "e => e.hidden"), "at the bottom there is nothing to jump to"

        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(250)
        assert not page.eval_on_selector("#jump-latest", "e => e.hidden"), "scrolled up, the way back is offered"
        # The button rides the viewport above the composer on a phone, so it is in view from the
        # top of the transcript and this is a real click — not a scroll-into-view then a click,
        # which would have been the mechanism under test doing the test's work.
        offered = page.eval_on_selector("#jump-latest", "e => e.getBoundingClientRect().toJSON()")
        assert 0 <= offered["top"] and offered["bottom"] <= 844, f"the way back is off screen: {offered}"
        page.click("#jump-latest")
        page.wait_for_timeout(300)
        newest = page.evaluate(NEWEST_TURN_JS)
        assert newest["bottom"] <= newest["viewport"], f"Jump to latest did not: {newest}"
        assert page.eval_on_selector("#jump-latest", "e => e.hidden")
    finally:
        context.close()


@pytest.mark.parametrize("label,width,height", VIEWPORTS, ids=[label for label, _, _ in VIEWPORTS])
@pytest.mark.parametrize("route", CHAT_SCREENS, ids=("at-rest", "with-an-answer"))
def test_the_composer_holds_its_placeholder_on_a_fresh_load(browser, surfaces, route, label, width, height):
    """npo3-03 = dgc-r2-4 = a11y-re2-4: at 390px the placeholder wraps to two lines, and the box
    opened one line tall with the second line cut through the middle of its glyphs — the first
    thing a phone reader saw of the primary control."""
    context, page = _fresh_tab(browser, surfaces["base_url"], width, height)
    try:
        page.goto(surfaces["base_url"] + resolve(route, surfaces), wait_until="networkidle")
        page.wait_for_timeout(300)
        fit = page.evaluate(COMPOSER_FIT_JS)
        assert fit["scrollHeight"] <= fit["clientHeight"], (
            f"{route} at {label}: the placeholder overflows the box: {fit}"
        )
    finally:
        context.close()


def test_the_transcript_and_the_composer_follow_the_viewport_across_the_phone_breakpoint(browser, fresh_server):
    """cpux2-2 = a11y-re2-4: both were made viewport-dependent at W6 and neither was re-run on
    resize. Narrowed across 30rem the answer stayed clipped with the document at 0; widened back,
    the transcript sat pinned at its top and the composer kept a phone-sized inline height."""
    context, page = _fresh_tab(browser, fresh_server, 1440, 900)
    try:
        _ask(page, DEMO_1)
        assert _transcript_is_stuck(page)

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(500)  # `RESIZE_SETTLE_MS` is 120
        newest = page.evaluate(NEWEST_TURN_JS)
        assert newest["bottom"] <= newest["viewport"], f"narrowed to a phone, the newest turn is off screen: {newest}"
        fit = page.evaluate(COMPOSER_FIT_JS)
        assert fit["scrollHeight"] <= fit["clientHeight"], f"narrowed, the composer keeps a desktop height: {fit}"
        assert page.eval_on_selector("#jump-latest", "e => e.hidden")

        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(500)
        assert _transcript_is_stuck(page), "widened back, the transcript is pinned at its top"
        assert page.eval_on_selector("#jump-latest", "e => e.hidden")
        fit = page.evaluate(COMPOSER_FIT_JS)
        assert fit["scrollHeight"] <= fit["clientHeight"], f"widened, the composer keeps a phone height: {fit}"
    finally:
        context.close()
