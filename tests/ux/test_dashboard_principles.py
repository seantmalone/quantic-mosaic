"""P1, P9, P10 and P14 on the **rendered** dashboard (`pytest -m ux`, UX W4).

`docs/superpowers/plans/2026-09-14-ux-remediation-plan.md` §1 writes each principle as a rule a
machine can check, and each of these four is about what a page *prints*:

* **P1** human precision — no number carries more significant digits than its purpose supports;
* **P9** summaries agree with their detail — a count and the list it counts come from one source,
  the label names the unit it measures, and plurals follow the count;
* **P10** one convention per concept — one date format, one rate unit, one duration helper;
* **P14** honest statistics — a rate over fewer than twenty samples shows its denominator, and a
  percentile over fewer than five shows `n=` instead of a figure.

The contract suite asserts the server's bytes and the formatters in isolation
(`tests/contract/test_formatter_coverage.py`). This file asserts the text a browser actually paints
across **every** dashboard route at once, which is the only place a second convention shows up: a
formatter can be perfect and one page still print a raw float, and no per-page test would see it.

One server, one question asked, every route visited once; `LLM_PROVIDER=stub`, loopback only.
"""

from __future__ import annotations

import re

import pytest

from tests.ux.conftest import TOKEN, _serve

pytestmark = pytest.mark.ux

DEMO_1 = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"

#: Four decimal places or more is a stored score, never a number anyone reads (**P1**).
MACHINE_PRECISION = re.compile(r"\d+\.\d{4,}")
#: Money beyond the cent (**P1**).
MACHINE_MONEY = re.compile(r"\$\d+\.\d{3,}")
#: Every percentage a page prints, and the single shape they must all take (**P1**, **P10**).
ANY_PERCENT = re.compile(r"\d+(?:\.\d+)?%")
ONE_DECIMAL_PERCENT = re.compile(r"\d{1,3}\.\d%")
#: Every moment a page prints (**P10**): one format, stated in UTC, everywhere.
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC")
#: The date shapes that would mean a *second* convention had crept in.
OTHER_DATE = re.compile(r"\d{4}-\d{2}-\d{2}T|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
#: Milliseconds are whole, or `<1 ms`; a fraction of one is `numbers-precision-overflow-5` again.
FRACTIONAL_MS = re.compile(r"\d+\.\d+ ms\b")
#: `row(s)` — a plural nobody speaks (**P9**).
LAZY_PLURAL = re.compile(r"\(s\)")


@pytest.fixture(scope="module")
def dashboard_server(tmp_path_factory):
    """A server of this module's own, so the question it asks is not one another test wanted."""
    with _serve(tmp_path_factory.mktemp("ux-dash"), "demo_task_1.json") as base_url:
        yield base_url


@pytest.fixture(scope="module")
def dashboard(browser, dashboard_server):
    """One signed-in tab with one real turn behind it, on every dashboard route in turn."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    tab = context.new_page()
    try:
        tab.goto(f"{dashboard_server}/?access={TOKEN}", wait_until="networkidle")
        tab.fill("#message", DEMO_1)
        tab.click("#send-button")
        tab.wait_for_selector("#messages .turn", timeout=180_000)
        tab.wait_for_timeout(1500)
        yield _Dashboard(tab, dashboard_server)
    finally:
        context.close()


class _Dashboard:
    """Every dashboard route, and the text a browser paints on it."""

    ROUTES = (
        "/dashboard",
        "/dashboard/sessions",
        "/dashboard/turns",
        "/dashboard/llm",
        "/dashboard/retrieval",
        "/dashboard/tools",
        "/dashboard/safety",
        "/dashboard/mcp",
        "/dashboard/corpus",
        "/dashboard/corpus/remote-and-hybrid-work",
        "/dashboard/evals",
    )

    def __init__(self, tab, base_url: str) -> None:
        self.tab = tab
        self.base_url = base_url
        self.routes = [*self.ROUTES]
        session = tab.eval_on_selector("#demo-dashboard-link", "e => e.getAttribute('href')")
        assert session, "the demo panel's deep link is where the session route comes from"
        self.session_route = session.split("#")[0]
        self.routes.insert(2, self.session_route)
        self.text = {route: self._text_of(route) for route in self.routes}
        run = self._first_run()
        if run:
            self.routes.append(run)
            self.text[run] = self._text_of(run)
        self.values = {route: self._collect(route, self.VALUES) for route in self.routes}
        self.chrome = {route: f"{self.values[route]} | {self._collect(route, self.LABELS)}" for route in self.routes}

    def _text_of(self, route: str) -> str:
        """The page **as painted**, disclosures closed — the same dump the audit measured.

        A closed `<details>` holding a span payload is the technical record, not a rendered number:
        **P15** is that it stays there unrounded, and rounding it would be the defect. What a reader
        is shown without clicking is what P1 and P10 are about.
        """
        response = self.tab.goto(self.base_url + route, wait_until="networkidle")
        assert response is not None and response.status == 200, f"{route} answered {response and response.status}"
        self.tab.wait_for_timeout(120)
        return self.tab.evaluate("() => document.body.innerText")

    #: The elements that hold a figure the dashboard itself formatted.
    VALUES = (
        ".kpi-value, .kpi-sub, .metric-value, .pager-state, .verdict-line, .verdict-delta, .data-table td, .facts dd"
    )
    #: …and the ones that name it. A label may legitimately say "Slowest 5% of turns"; a *value*
    #: may not print a percentage in a second shape.
    LABELS = ".kpi-label, .metric-label, .data-table th, .facts dt, .dash-lede"

    def _collect(self, route: str, selector: str) -> str:
        """Only the text the *app* composes — never model prose or policy text.

        A policy document says "25% of base salary" and an answer quotes it; that is content, and a
        percentage convention is about the figures the dashboard itself formats.
        """
        self.tab.goto(self.base_url + route, wait_until="networkidle")
        return self.tab.evaluate(
            "selector => Array.from(document.querySelectorAll(selector))"
            ".filter(el => !el.querySelector('pre'))"
            ".map(el => el.innerText).join(' | ')",
            selector,
        )

    def _first_run(self) -> str | None:
        self.tab.goto(f"{self.base_url}/dashboard/evals", wait_until="networkidle")
        return (
            self.tab.eval_on_selector("#eval-runs-table a[href^='/dashboard/evals/']", "e => e.getAttribute('href')")
            if self.tab.query_selector("#eval-runs-table a[href^='/dashboard/evals/']")
            else None
        )

    def visit(self, route: str):
        self.tab.goto(self.base_url + route, wait_until="networkidle")
        return self.tab


def _matches(dashboard, pattern: re.Pattern[str], *, chrome: bool = False) -> dict[str, list[str]]:
    """Every route whose text matches, with the first few offending tokens."""
    source = dashboard.chrome if chrome else dashboard.text
    return {route: pattern.findall(text)[:3] for route, text in source.items() if pattern.search(text)}


# -- P1 ----------------------------------------------------------------------------------


def test_p1_no_dashboard_route_prints_a_stored_score_or_a_fractional_cent(dashboard):
    """`numbers-precision-overflow-1`: `0.9839181286549706` was the headline of a stat tile."""
    offenders = _matches(dashboard, MACHINE_PRECISION)
    assert not offenders, f"four decimal places or more on a human surface: {offenders}"

    money = _matches(dashboard, MACHINE_MONEY)
    assert not money, f"money beyond the cent: {money}"


def test_p1_a_duration_never_prints_a_fraction_of_a_millisecond(dashboard):
    offenders = _matches(dashboard, FRACTIONAL_MS)
    assert not offenders, f"milliseconds are whole, or `<1 ms`: {offenders}"


# -- P10 ---------------------------------------------------------------------------------


def test_p10_every_percentage_on_every_route_is_written_the_same_way(dashboard):
    """`numbers-precision-overflow-2`: a rate rendered `1.0`, `0.0%` and `11.1%` across three pages."""
    ragged = {}
    for route, text in dashboard.values.items():
        odd = [token for token in ANY_PERCENT.findall(text) if not ONE_DECIMAL_PERCENT.fullmatch(token)]
        if odd:
            ragged[route] = odd[:3]
    assert not ragged, f"one rate convention, one decimal place: {ragged}"


def test_p10_every_moment_on_every_route_is_written_the_same_way(dashboard):
    """One date format per audience — the dashboard's is the second, stated in UTC."""
    seen = 0
    other = {}
    for route, text in dashboard.text.items():
        seen += len(TIMESTAMP.findall(text))
        if OTHER_DATE.search(text):
            other[route] = OTHER_DATE.findall(text)[:3]
    assert seen, "the routes visited do print timestamps, or this test proves nothing"
    assert not other, f"a second date convention: {other}"


# -- P9 ----------------------------------------------------------------------------------


def test_p9_no_route_renders_a_plural_nobody_speaks(dashboard):
    offenders = _matches(dashboard, LAZY_PLURAL, chrome=True)
    assert not offenders, f"the noun agrees with its count, or it is not printed: {offenders}"


def test_p9_the_guardrail_figures_agree_with_the_checks_listed_below_them(dashboard):
    """`numbers-precision-overflow-15`: `GUARDRAIL HITS 0` sat above seven guardrail spans.

    The rollup counts *blocks* — a verdict that was not `allow`. Labelled "hits" above a list of
    every check that ran, it read as a contradiction. Both figures are named and both are countable
    from the very rows beneath them.
    """
    tab = dashboard.visit(dashboard.session_route)
    figures = tab.evaluate(
        "() => Object.fromEntries(Array.from(document.querySelectorAll('.rollups > div'))"
        ".map(d => [d.querySelector('dt').textContent.trim(), d.querySelector('dd').textContent.trim()]))"
    )
    checks_rendered = tab.eval_on_selector_all('.span-row[data-kind="guardrail"]', "els => els.length")

    assert "Guardrail blocks" in figures and "Safety checks" in figures, figures
    # "5 of 6 applied · 7 checks run" (UX W7, npo3-04): the spans that ran are the third figure.
    blocks = int(figures["Guardrail blocks"])
    applied = re.fullmatch(r"(\d+) of 6 applied · (\d+) checks? run", figures["Safety checks"])
    assert applied, figures["Safety checks"]
    checks = int(applied.group(2))
    assert checks == checks_rendered, f"the count and the list it counts disagree: {checks} vs {checks_rendered}"
    assert blocks <= checks, f"more blocks than checks: {figures}"


def test_p9_the_pager_counts_the_rows_it_is_paging(dashboard):
    tab = dashboard.visit("/dashboard/sessions")
    state = tab.eval_on_selector(".pager-state", "e => e.textContent")
    rendered = tab.eval_on_selector_all(
        "#sessions-table tbody tr:not(.empty-row):not(.detail-row)", "els => els.length"
    )

    stated = re.search(r"(\d+) rows?\b", state)
    assert stated, f"the pager states its total: {state!r}"
    assert int(stated.group(1)) == rendered, f"{state!r} against {rendered} rendered rows"
    assert "row(s)" not in state


def test_p9_the_error_rate_tile_agrees_with_the_turns_tile_beside_it(dashboard):
    tab = dashboard.visit("/dashboard")
    tile = tab.eval_on_selector('[data-kpi="error_rate"]', "e => e.textContent")
    turns = int(tab.eval_on_selector('[data-kpi="turns"] .kpi-value', "e => e.textContent.replace(/,/g, '')"))

    stated = re.search(r"(\d+) of ([\d,]+) turns?", tile)
    assert stated, f"the rate names its denominator: {tile!r}"
    assert int(stated.group(2).replace(",", "")) == turns, f"{tile!r} against {turns} turns"


# -- P14 ---------------------------------------------------------------------------------


def test_p14_a_rate_over_a_small_sample_carries_its_denominator(dashboard):
    """`numbers-precision-overflow-14`: `50.0%` from one of two calls, and overview rates with no n."""
    tab = dashboard.visit("/dashboard/tools")
    rows = tab.evaluate(
        "() => Array.from(document.querySelectorAll('#by-tool-table tbody tr'))"
        ".filter(tr => !tr.classList.contains('empty-row'))"
        ".map(tr => ({"
        "  calls: Number((tr.querySelector('[data-col=calls]') || {}).textContent || 0),"
        "  rate: ((tr.querySelector('[data-col=error_rate]') || {}).textContent || '').trim()"
        "}))"
    )
    assert rows, "the demo turn calls at least one tool"
    for row in rows:
        if row["calls"] < 20:
            assert " of " in row["rate"], f"a rate over {row['calls']} calls with no denominator: {row}"


def test_p14_a_percentile_over_fewer_than_five_samples_prints_its_n(dashboard):
    tab = dashboard.visit("/dashboard/tools")
    rows = tab.evaluate(
        "() => Array.from(document.querySelectorAll('#by-tool-table tbody tr'))"
        ".filter(tr => !tr.classList.contains('empty-row'))"
        ".map(tr => ({"
        "  calls: Number((tr.querySelector('[data-col=calls]') || {}).textContent || 0),"
        "  p95: ((tr.querySelector('[data-col=p95_ms]') || {}).textContent || '').trim()"
        "}))"
    )
    assert rows
    for row in rows:
        if row["calls"] < 5:
            assert row["p95"].startswith("n="), f"a p95 over {row['calls']} calls printed as a figure: {row}"


def test_p14_the_overview_percentiles_say_what_they_were_computed_over(dashboard):
    tab = dashboard.visit("/dashboard")
    p95 = tab.eval_on_selector('[data-kpi="p95_ms"]', "e => e.textContent")
    assert re.search(r"over \d+ turns?", p95), f"the percentile tile names its sample: {p95!r}"


# -- the waterfall's geometry ------------------------------------------------------------


def test_the_waterfall_axis_measures_the_column_the_bars_are_drawn_in(dashboard):
    """`dashboard-readability-9`, held to its own arithmetic (UX W4 review, fix round 1).

    The axis and the rows are two separate six-column grids. The axis emitted five children and
    leaned on auto-placement, so its ticks landed in column 4 — the summary text — and the total
    landed where the bars are: `0 · 175 ms · 350 ms · 526 ms · 701 ms` painted across the prose and
    stopping before the first grey track began. An axis that does not line up with the bars it
    measures reads worse than no axis, and no assertion in the suite looked at geometry.
    """
    tab = dashboard.visit(dashboard.session_route)
    boxes = tab.evaluate(
        "() => {"
        " const axis = document.querySelector('.span-axis-track');"
        " const track = document.querySelector('.span-row .span-track');"
        " const total = document.querySelector('.span-axis-total');"
        " const duration = document.querySelector('.span-row .span-duration');"
        " if (!axis || !track || !total || !duration) return null;"
        " const box = el => { const r = el.getBoundingClientRect(); return [r.left, r.right]; };"
        " return {axis: box(axis), track: box(track), total: box(total), duration: box(duration)};"
        "}"
    )
    assert boxes, "the session waterfall draws an axis and at least one span track"
    for name, edge in (("left", 0), ("right", 1)):
        assert abs(boxes["axis"][edge] - boxes["track"][edge]) <= 1, (
            f"the tick scale's {name} edge is {boxes['axis'][edge]} and the bars' is "
            f"{boxes['track'][edge]}: the axis is labelling another column"
        )
        assert abs(boxes["total"][edge] - boxes["duration"][edge]) <= 1, (
            f"the turn total's {name} edge is {boxes['total'][edge]} and the per-span durations' is "
            f"{boxes['duration'][edge]}"
        )


def test_a_deep_linked_turn_is_highlighted_and_not_merely_scrolled_to(dashboard):
    """`dashboard-readability-29`: scrolling a turn into view never said *which* turn.

    W1 landed the `scroll-margin-top` half. This is the other one — `:target` was styled for
    `.reader-section` alone, so the chat's `#turn-N` link put the right card under the reader's eye
    and then left them to count.
    """
    tab = dashboard.visit(dashboard.session_route)
    plain = tab.eval_on_selector(".turn-card", "e => getComputedStyle(e).backgroundColor")
    tab.goto(f"{dashboard.base_url}{dashboard.session_route}#turn-1", wait_until="networkidle")
    tab.wait_for_timeout(120)
    targeted = tab.eval_on_selector("#turn-1", "e => getComputedStyle(e).backgroundColor")

    assert targeted != plain, f"the deep-linked turn is painted like every other one: {targeted}"


# -- P7 and the W5 accessibility findings, on the same server ------------------------------
#
# These share the module's one server and its one real turn rather than booting another: the
# `ux` CI job already starts several, and a wave that adds a suite should not also add a minute.


VIEWPORTS = (("1440x900", 1440, 900), ("1280x800", 1280, 800), ("390x844", 390, 844))


def test_p7_no_dashboard_route_scrolls_the_document_sideways(dashboard):
    """**P7** at the three viewports the audit measured, over every route at once.

    `tests/ux/test_principles.py` asserts this on chat, which is where the finding was; the
    dashboard was clean at the audit and has been rewritten twice since. W4's own `.span-axis`
    regressed it on four screens and only the capture harness noticed.
    """
    sideways = []
    try:
        for label, width, height in VIEWPORTS:
            dashboard.tab.set_viewport_size({"width": width, "height": height})
            for route in dashboard.routes:
                dashboard.tab.goto(dashboard.base_url + route, wait_until="networkidle")
                dashboard.tab.wait_for_timeout(80)
                if dashboard.tab.evaluate(
                    "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
                ):
                    sideways.append(f"{route}@{label}")
    finally:
        dashboard.tab.set_viewport_size({"width": 1440, "height": 900})

    assert not sideways, f"the document scrolls sideways on: {sideways}"


def test_the_waterfall_keeps_its_durations_on_a_phone(dashboard):
    """`accessibility-and-responsive-9`, and W4's own carry-over.

    Below 1120px the waterfall used to **delete** the duration bar and the millisecond value, so the
    one thing a step's row is for was missing on exactly the viewport that has least room for the
    prose beside it. W4 then hid the axis too, to stop a six-column grid 46rem wide scrolling the
    document sideways. W5's restack is four explicit columns: the track — the only decorative part —
    is what goes, the number comes back, and the axis keeps its label and its total inside the
    container.
    """
    try:
        dashboard.tab.set_viewport_size({"width": 390, "height": 844})
        tab = dashboard.visit(dashboard.session_route)
        tab.wait_for_timeout(120)
        measured = tab.evaluate(
            "() => {"
            " const box = el => el ? el.getBoundingClientRect() : null;"
            " const durations = Array.from(document.querySelectorAll('.span-duration'))"
            "   .filter(el => getComputedStyle(el).display !== 'none');"
            " const axis = document.querySelector('.span-axis');"
            " const card = document.querySelector('.turn-card');"
            " return {"
            "  durations: durations.length,"
            "  texts: durations.slice(0, 3).map(el => el.textContent.trim()),"
            "  tracks: Array.from(document.querySelectorAll('.span-track'))"
            "    .filter(el => getComputedStyle(el).display !== 'none').length,"
            "  axis: box(axis) && {right: box(axis).right, width: box(axis).width},"
            "  card: box(card) && {right: box(card).right},"
            " };"
            "}"
        )
    finally:
        dashboard.tab.set_viewport_size({"width": 1440, "height": 900})

    assert measured["durations"] > 0, "the duration column is gone again on a phone"
    assert all(text for text in measured["texts"]), f"the durations are painted but empty: {measured}"
    assert measured["tracks"] == 0, "the proportional track has no room at 390px and is decorative"
    assert measured["axis"] and measured["axis"]["width"] > 0, "the axis went with the track again"
    assert measured["axis"]["right"] <= measured["card"]["right"] + 1, (
        f"the axis is wider than the card it is drawn in: {measured}"
    )


def test_every_chart_hands_its_numbers_over_in_words(dashboard):
    """`accessibility-and-responsive-19`: six canvases exposed no data at all.

    A `<canvas>` is a bitmap and an `aria-label` on it names the picture, not the figures. Each one
    is now decorative, inside a `figure.chart-figure` whose visually-hidden caption is either the
    table of the same values or the sentence saying where on the page they already are.
    """
    naked = []
    for route in dashboard.routes:
        tab = dashboard.visit(route)
        naked += tab.evaluate(
            "route => Array.from(document.querySelectorAll('canvas')).filter(el => {"
            "  const figure = el.closest('figure.chart-figure');"
            "  if (!figure) return true;"
            "  if (el.getAttribute('aria-hidden') !== 'true') return true;"
            "  const caption = figure.querySelector('figcaption');"
            "  return !caption || !caption.textContent.trim();"
            "}).map(el => route + ' ' + el.id)",
            route,
        )
    assert not naked, f"these charts show numbers no reader can reach: {naked}"


def test_a_deep_link_moves_focus_to_the_turn_it_names(dashboard):
    """`accessibility-and-responsive-10`: the viewport moved and the reading position did not.

    Both link shapes, because they land on different elements: the chat panel's `#turn-<seq>` is the
    card, and the turns listing's `#turn-<turn_id>` is the `visibility: hidden` anchor inside it —
    which cannot take focus, so the card takes it instead.
    """
    tab = dashboard.visit(dashboard.session_route)
    turn_id = tab.eval_on_selector(".turn-card .anchor", "e => e.id")

    for fragment in ("#turn-1", f"#{turn_id}"):
        tab.goto(f"{dashboard.base_url}{dashboard.session_route}{fragment}", wait_until="networkidle")
        tab.wait_for_timeout(150)
        landed = tab.evaluate("() => document.activeElement && document.activeElement.className.toString()")
        assert "turn-card" in (landed or ""), f"{fragment} left focus on {landed!r}"


# -- UX W7: the nav's group labels are labels, its page links are targets, and every link stays in the product --

#: One eyebrow and one page link, with what the browser resolved for each, plus the same link's
#: colours while hovered and while focused from the keyboard.
NAV_STYLES_JS = """
() => {
  const nav = document.getElementById("dash-nav");
  const eyebrow = nav.querySelector(".dash-nav-eyebrow");
  const link = nav.querySelector(".dash-nav-link:not([aria-current])");
  const paint = (el) => {
    const s = getComputedStyle(el);
    return { cursor: s.cursor, underline: s.textDecorationLine, color: s.color, border: s.borderColor,
             background: s.backgroundColor, outline: s.outlineStyle, tag: el.tagName.toLowerCase() };
  };
  return {
    eyebrow: { ...paint(eyebrow), tabIndex: eyebrow.tabIndex, hidden: eyebrow.getAttribute("aria-hidden"),
               href: eyebrow.getAttribute("href") },
    link: { ...paint(link), tabIndex: link.tabIndex, href: link.getAttribute("href") },
    groups: Array.from(nav.querySelectorAll("ul.dash-nav-group")).map((ul) => ul.getAttribute("aria-label")),
  };
}
"""


NAV_VIEWPORTS = (("1440x900", 1440, 900), ("390x844", 390, 844))

#: The focus ring on the page link that has keyboard focus — or `null` when focus is elsewhere.
FOCUSED_NAV_LINK_JS = """
() => {
  const el = document.activeElement;
  if (!el || !el.classList.contains("dash-nav-link")) { return null; }
  const s = getComputedStyle(el);
  return { outline: s.outlineStyle, width: s.outlineWidth, shadow: s.boxShadow };
}
"""


@pytest.mark.parametrize("label,width,height", NAV_VIEWPORTS, ids=[label for label, _, _ in NAV_VIEWPORTS])
def test_the_nav_group_labels_read_as_labels_and_the_page_links_as_targets(
    browser, dashboard_server, label, width, height
):
    """UX W7, Addendum 2 — the owner's decision: ACTIVITY / UNDER THE HOOD / QUALITY / REFERENCE
    must not look clickable. Measured on a fresh load at each viewport: the eyebrow has an arrow
    cursor, no underline and no focus stop; the page link has a pointer, a visibly different paint
    under the mouse, and the accent ring when reached from the keyboard."""
    context = browser.new_context(viewport={"width": width, "height": height})
    tab = context.new_page()
    try:
        tab.goto(f"{dashboard_server}/?access={TOKEN}", wait_until="networkidle")
        tab.goto(f"{dashboard_server}/dashboard/tools", wait_until="networkidle")
        styles = tab.evaluate(NAV_STYLES_JS)
        eyebrow, link = styles["eyebrow"], styles["link"]
        assert styles["groups"] == ["Activity", "Under the hood", "Quality", "Reference"], styles["groups"]

        assert eyebrow["tag"] == "li" and eyebrow["href"] is None and eyebrow["hidden"] == "true", eyebrow
        assert eyebrow["tabIndex"] < 0, f"{label}: the group label is a focus stop: {eyebrow}"
        assert eyebrow["cursor"] == "default", f"{label}: the group label invites a click: {eyebrow}"
        assert eyebrow["underline"] == "none", f"{label}: the group label is underlined: {eyebrow}"

        assert link["tag"] == "a" and link["href"] and link["tabIndex"] == 0, link
        assert link["cursor"] == "pointer", f"{label}: the page link does not read as one: {link}"
        assert link["border"] != "rgba(0, 0, 0, 0)" and link["background"] != "rgba(0, 0, 0, 0)", (
            f"{label}: the page link has no pill to be: {link}"
        )

        tab.hover(".dash-nav-link:not([aria-current])")
        tab.wait_for_timeout(120)
        hovered = tab.evaluate(NAV_STYLES_JS)["link"]
        assert (hovered["border"], hovered["background"], hovered["color"]) != (
            link["border"],
            link["background"],
            link["color"],
        ), f"{label}: hovering the page link changes nothing: {link} → {hovered}"

        # From the keyboard: Tab from the top of the document until a page link has focus.
        tab.evaluate("() => { document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); }")
        focused = None
        for _ in range(12):
            tab.keyboard.press("Tab")
            focused = tab.evaluate(FOCUSED_NAV_LINK_JS)
            if focused:
                break
        assert focused, f"{label}: no page link is reachable from the keyboard within twelve stops"
        assert focused["outline"] != "none" or focused["shadow"] != "none", f"{label}: no focus ring: {focused}"
    finally:
        context.close()


@pytest.mark.parametrize("route", ("/dashboard/evals", "/dashboard/corpus", "/dashboard/mcp"))
def test_the_current_nav_item_is_scrolled_into_view_on_a_phone(browser, dashboard_server, route):
    """nav-r2-4 = a11y-re2-3: the one-row nav opened at scrollLeft 0 on every page, so on seven of
    the ten pages the lit item was off screen and the row said only "Overview Sessions Turns"."""
    context = browser.new_context(viewport={"width": 390, "height": 844})
    tab = context.new_page()
    try:
        tab.goto(f"{dashboard_server}/?access={TOKEN}", wait_until="networkidle")
        tab.goto(f"{dashboard_server}{route}", wait_until="networkidle")
        tab.wait_for_timeout(150)
        boxes = tab.evaluate(
            "() => { const nav = document.getElementById('dash-nav').getBoundingClientRect();"
            " const cur = document.querySelector('#dash-nav [aria-current]').getBoundingClientRect();"
            " return { nav: nav.toJSON(), current: cur.toJSON() }; }"
        )
        nav, current = boxes["nav"], boxes["current"]
        assert nav["left"] - 1 <= current["left"] and current["right"] <= nav["right"] + 1, (
            f"{route}: the current item is outside the nav's box on arrival: {boxes}"
        )
    finally:
        context.close()


def test_no_link_inside_the_page_leads_into_the_raw_json_api(dashboard):
    """nav-r2-1: five pages linked the turn-id chip to `/api/traces/turns/…` — an unstyled JSON
    document with no masthead and no route back — while the sixth linked the same chip to the
    session record. Only the labelled export control may leave the product for the API."""
    offenders: dict[str, list[str]] = {}
    for route in dashboard.routes:
        tab = dashboard.visit(route)
        loose = tab.evaluate(
            "() => Array.from(document.querySelectorAll('main a[href]'))"
            ".filter(a => a.getAttribute('href').startsWith('/api/') && a.id !== 'export-json')"
            ".map(a => a.getAttribute('href')).slice(0, 5)"
        )
        if loose:
            offenders[route] = loose
    assert not offenders, f"links into the raw API from inside the page: {offenders}"


# -- UX W7: tables keep their columns, the waterfall keeps its rows, the reader keeps its prose --

#: Every element in `main` that is wider than its box without the scroll affordance, and every
#: prose cell narrower than 6rem that holds a sentence.
TABLE_BUDGET_JS = """
() => {
  const sideways = [];
  for (const el of document.querySelectorAll("main *")) {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || el.clientWidth === 0) continue;
    // A visually-hidden element is a 1px clip box: it "overflows" by construction and paints nothing.
    if (el.closest(".visually-hidden")) continue;
    if (el.scrollWidth > el.clientWidth + 1) {
      const allowed = el.closest(".table-scroll, pre, .chart-figure, .dash-nav");
      const name = el.className ? "." + String(el.className).split(" ")[0] : "";
      if (!allowed) sideways.push(el.tagName.toLowerCase() + name);
    }
  }
  const narrowProse = Array.from(document.querySelectorAll(".data-table td.cell-text"))
    .filter((td) => td.innerText.trim().length > 24)
    .map((td) => ({ col: td.dataset.col, width: Math.round(td.getBoundingClientRect().width) }))
    .filter((cell) => cell.width > 0 && cell.width < 96);
  return { sideways: sideways.slice(0, 8), narrowProse: narrowProse.slice(0, 8) };
}
"""

DESKTOPS = (("1440x900", 1440, 900), ("1280x800", 1280, 800))


@pytest.mark.parametrize("label,width,height", DESKTOPS, ids=[label for label, _, _ in DESKTOPS])
def test_no_table_overflows_without_the_affordance_and_no_narrow_column_holds_prose(
    browser, dashboard, label, width, height
):
    """npo3-02 (UX W7). `/dashboard/retrieval` overflowed its container at 1280 and the QUERY
    column was shredded into a 55px ribbon of word fragments once the humanised STRATEGY label
    beside it grew. Measured on a fresh load at each desktop width, on every dashboard route."""
    context = browser.new_context(viewport={"width": width, "height": height})
    tab = context.new_page()
    try:
        tab.goto(f"{dashboard.base_url}/?access={TOKEN}", wait_until="networkidle")
        offenders: dict[str, dict] = {}
        for route in dashboard.routes:
            tab.goto(dashboard.base_url + route, wait_until="networkidle")
            tab.wait_for_timeout(100)
            measured = tab.evaluate(TABLE_BUDGET_JS)
            if measured["sideways"] or measured["narrowProse"]:
                offenders[route] = measured
        assert not offenders, f"at {label}: {offenders}"
    finally:
        context.close()


def test_the_waterfall_costs_one_row_per_step_and_the_session_page_fits_a_phone(browser, dashboard):
    """DR2-02 (UX W7). Every span emitted a full-width second row for its payload — 28 spans, 56
    rows — and the session page ran to 7,600px at 390x844. The disclosure is a seventh column
    now, a closed payload costs no row, and the page the chat deep link lands on is under 5,000px."""
    api = dashboard.visit("/api/traces/sessions/" + dashboard.session_route.rsplit("/", 1)[1])
    spans = api.evaluate("() => JSON.parse(document.body.innerText).turns.reduce((n, t) => n + t.spans.length, 0)")
    assert spans > 0, "the seeded session has steps"
    context = browser.new_context(viewport={"width": 390, "height": 844})
    tab = context.new_page()
    try:
        tab.goto(f"{dashboard.base_url}/?access={TOKEN}", wait_until="networkidle")
        tab.goto(dashboard.base_url + dashboard.session_route, wait_until="networkidle")
        tab.wait_for_timeout(150)
        rows = tab.eval_on_selector_all("ol.waterfall > li.span-row", "els => els.length")
        assert rows == spans, f"{rows} waterfall rows for {spans} steps"
        open_rows = tab.eval_on_selector_all(".span-payload[open]", "els => els.length")
        assert open_rows == 0, "payloads ship closed"
        height = tab.evaluate("() => document.documentElement.scrollHeight")
        assert height < 5000, f"the session page is {height}px tall at 390x844"
    finally:
        context.close()
