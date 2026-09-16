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


#: Every cell of the eval-run page that prints a rate, and the text it prints. The three blocks the
#: W7 ruling named — the headline strip, the behaviour-and-safety list and the workflow rows — plus
#: the run verdict, so a figure cannot escape by moving.
EVAL_RATES_JS = """
() => {
  const cells = [
    ...document.querySelectorAll("#metric-block .metric-value"),
    ...document.querySelectorAll("#behaviour-metrics dd"),
    ...document.querySelectorAll("#workflow-completion li"),
  ];
  return cells
    .map((el) => ({ where: el.closest("[data-metric]")?.dataset.metric || el.textContent.trim().slice(0, 40),
                    text: el.textContent.replace(/\\s+/g, " ").trim() }))
    .filter((cell) => /\\d+(\\.\\d+)?%/.test(cell.text));
}
"""


def test_p14_no_rate_on_the_eval_run_page_is_printed_without_its_sample(dashboard):
    """npo4-02 = re-audit #3's I6, against a written W7 ruling ("every rate on the eval-run page
    through `pct_of` with its denominator; n = 1 shown as 1 of 1").

    What shipped was a footer legend three screens below the figures, not denominators in the cells:
    `ACTION-SAFETY PASS RATE 100.0%` and `TOOL CATALOG REOPENED 0.0%` sat beside
    `OVER-REFUSAL RATE 0.0% (0 of 18 items)`, `Argument correctness 100.0%` was computed over 19 —
    under P14's own threshold — and both `Workflow completion` rows printed a bare `0.0%` over a
    footer line that was not their denominator. This page's whole subject is how a figure was
    computed, so the threshold does not apply to it: every rate states its sample, whatever its size.
    """
    run = next((route for route in dashboard.routes if "/dashboard/evals/" in route), None)
    assert run, "the committed evaluation runs are imported at boot"
    tab = dashboard.visit(run)
    tab.wait_for_timeout(120)
    rates = tab.evaluate(EVAL_RATES_JS)
    assert rates, "the run page prints rates"
    bare = [cell for cell in rates if " of " not in cell["text"]]
    assert not bare, f"these rates carry no denominator: {bare}"


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

#: Tables the owner exempted from the width budget, by the `id` the macro stamps on them.
#:
#: **One entry, and it is a ruling, not a convenience** (W8 fix round, npo4-01 = DR3-06 = I5).
#: `ux-W7-brief.md`: "numbers-precision-overflow-10 (evals table scrolls inside its container at
#: 1440): BY RULING, stays — a column picker is a feature." `eval-items-table` is that table: 13
#: columns, three of them prose and two of them the run's raw score and verdict objects, and the
#: only thing that fits it in a viewport is the column picker the owner deferred. Every other table
#: in the product, the evals *headline* table included, now fits its container at both desktop
#: widths with nothing scrolling sideways at all.
WIDTH_EXEMPT_TABLES = ("eval-items-table",)

#: Every element in `main` that is wider than its box without the scroll affordance; every
#: `.table-scroll` that has anything to scroll at all; and every cell of any class, narrower than
#: 6rem, that holds a sentence.
#:
#: The last two are W8's (I5). W7's probe allowed anything inside `.table-scroll` — which is where
#: every table lives — so four tables grew past their containers between the two captures with the
#: guard green throughout; and it measured `narrowProse` over `.cell-text` alone, so the squeeze
#: simply moved to the column beside it: `td.cell-list` had no width rule of any kind, DOCUMENTS
#: collapsed to ~105px and broke each document slug at its hyphens into a 210px-tall row.
TABLE_BUDGET_JS = """
(exempt) => {
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
  const overWide = [];
  for (const box of document.querySelectorAll(".table-scroll")) {
    if (box.clientWidth === 0 || getComputedStyle(box).display === "none") continue;
    const table = box.querySelector("table");
    if (table && exempt.includes(table.id)) continue;
    const over = box.scrollWidth - box.clientWidth;
    if (over > 0) overWide.push({ table: (table && table.id) || "?", over: over, box: box.clientWidth });
  }
  const narrowProse = Array.from(document.querySelectorAll(".data-table tbody td"))
    .filter((td) => td.innerText.trim().length > 24)
    .map((td) => ({
      col: td.dataset.col,
      cls: td.className,
      width: Math.round(td.getBoundingClientRect().width),
      lines: Math.round(td.getBoundingClientRect().height / parseFloat(getComputedStyle(td).lineHeight || 16)),
    }))
    .filter((cell) => cell.width > 0 && cell.width < 96);
  return { sideways: sideways.slice(0, 8), overWide: overWide.slice(0, 8), narrowProse: narrowProse.slice(0, 8) };
}
"""

DESKTOPS = (("1440x900", 1440, 900), ("1280x800", 1280, 800))

#: The tab panels a dashboard route hides behind `?tab=` — and the reason this test measured half
#: the tables it thought it did (UX W8, W7 review). A hidden panel's elements have `clientWidth`
#: 0, which the probe above skips by construction, so `eval-items-table` — the widest table in the
#: product, and the one whose QUERY column the defect was found in — was never measured at all.
#: The tab is chosen server-side from `?tab=`, so each panel is reachable as its own URL.
TAB_PANELS: tuple[str, ...] = ("items", "system", "compare")


def _tabbed(route: str) -> list[str]:
    """`route`, then `route?tab=…` for each panel it has. A route with no tabs is just itself."""
    joiner = "&" if "?" in route else "?"
    return [route, *(f"{route}{joiner}tab={panel}" for panel in TAB_PANELS)]


@pytest.mark.parametrize("label,width,height", DESKTOPS, ids=[label for label, _, _ in DESKTOPS])
def test_no_table_overflows_without_the_affordance_and_no_narrow_column_holds_prose(
    browser, dashboard, label, width, height
):
    """npo3-02 (UX W7), and npo4-01 = DR3-06 = re-audit #3's I5.

    `/dashboard/retrieval` overflowed its container at 1280 and the QUERY column was shredded into a
    55px ribbon of word fragments once the humanised STRATEGY label beside it grew. W8's half is the
    other direction: between the two captures retrieval went 1,219→1,394, model calls 1,399→1,497
    and turns 1,311→1,395, all inside containers of 1,199 and 1,359 — and this test stayed green,
    because a `.table-scroll` was allowed to scroll by construction and the prose measurement looked
    at one cell class. A container a reader has to scroll to see a column is a budget nobody kept:
    every table fits, `WIDTH_EXEMPT_TABLES` names the one the owner ruled otherwise, and every cell
    class is measured. Fresh load at each desktop width, every dashboard route, every tab panel."""
    context = browser.new_context(viewport={"width": width, "height": height})
    tab = context.new_page()
    try:
        tab.goto(f"{dashboard.base_url}/?access={TOKEN}", wait_until="networkidle")
        offenders: dict[str, dict] = {}
        for route in dashboard.routes:
            # Every tab panel, not only the one the route opens on: a hidden panel measures 0 wide,
            # so `eval-items-table` was skipped by the probe's own `clientWidth === 0` guard.
            for url in _tabbed(route):
                tab.goto(dashboard.base_url + url, wait_until="networkidle")
                tab.wait_for_timeout(100)
                measured = tab.evaluate(TABLE_BUDGET_JS, list(WIDTH_EXEMPT_TABLES))
                if measured["sideways"] or measured["overWide"] or measured["narrowProse"]:
                    offenders[url] = measured
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


# -- UX W8 fix round: the four geometry residuals of re-audit #3 (C4, I1, I2, I3, I8, I14) --------

#: One span of the desktop waterfall: how tall its row is, and how far its disclosure sits from the
#: step number it belongs to. `drift` is the whole of DR3-01: `.span-row` placed every child in a
#: column and none of them in a row, so sparse auto-placement gave each span three bands — an empty
#: one carrying only the chevron, then seq/kind/name/duration, then the summary and the bar — and
#: the chevron painted a whole band above its own step number, reading as the trailing control of
#: the span before it. Measured against `.span-seq` rather than against the `<li>` box, because the
#: `<li>` spans all three bands and so contains the chevron either way: what changed is that the
#: chevron and the number it belongs to are on one line.
DESKTOP_WATERFALL_JS = """
() => {
  const rows = Array.from(document.querySelectorAll("ol.waterfall > li.span-row"));
  const middle = (el) => { const box = el.getBoundingClientRect(); return box.top + box.height / 2; };
  const drift = rows.map((row) => {
    const summary = row.querySelector(".span-payload > summary");
    const seq = row.querySelector(".span-seq");
    return summary && seq ? Math.abs(middle(summary) - middle(seq)) : 0;
  });
  return {
    rows: rows.length,
    open: document.querySelectorAll(".span-payload[open]").length,
    height: document.documentElement.scrollHeight,
    drift: Math.round(Math.max(0, ...drift)),
    pitch: Math.round(Math.max(0, ...rows.map((row) => row.getBoundingClientRect().height))),
  };
}
"""

#: The ruling's bound for the desktop session page with the demo-1 data (W8 addendum, DR3-01). The
#: capture that failed the gate measured **4,372px** at this viewport against 3,220 before W7.
DESKTOP_SESSION_MAX_PX = 3400


def test_the_desktop_waterfall_paints_one_row_per_span(browser, dashboard):
    """DR3-01 = re-audit #3's C4, and the guard that could not see it.

    W7's phone guard (above) passed throughout: the ≤70rem block declares `grid-row` for every item
    and the phone was right. The desktop block declared columns only, so one span became three
    bands, the page grew 36% and the chevron left its own row — none of which a row *count* can
    detect, because the `<li>` count never changed. Three measurements, at the viewport the
    regression was captured at: the page's height, one `<li>` per span, and the disclosure on the
    same centre line as the row it belongs to.
    """
    api = dashboard.visit("/api/traces/sessions/" + dashboard.session_route.rsplit("/", 1)[1])
    spans = api.evaluate("() => JSON.parse(document.body.innerText).turns.reduce((n, t) => n + t.spans.length, 0)")
    assert spans > 0, "the seeded session has steps"

    context = browser.new_context(viewport={"width": 1440, "height": 900})
    tab = context.new_page()
    try:
        tab.goto(f"{dashboard.base_url}/?access={TOKEN}", wait_until="networkidle")
        tab.goto(dashboard.base_url + dashboard.session_route, wait_until="networkidle")
        tab.wait_for_timeout(200)
        measured = tab.evaluate(DESKTOP_WATERFALL_JS)
    finally:
        context.close()

    assert measured["rows"] == spans, f"{measured['rows']} waterfall rows for {spans} steps"
    assert measured["open"] == 0, "payloads ship closed, so the payload track costs no row"
    assert measured["height"] <= DESKTOP_SESSION_MAX_PX, (
        f"the session page is {measured['height']}px tall at 1440x900 (bound {DESKTOP_SESSION_MAX_PX}): {measured}"
    )
    # A couple of pixels for two boxes of different heights on one centre line; a band apart is ~30.
    assert measured["drift"] <= 6, (
        f"the disclosure is {measured['drift']}px off its own step's line — the row is banded: {measured}"
    )


#: Is the page nav one row, and does every group sit on it? `offsetTop` is measured against the
#: same offset parent for all four `<ul>`s, so a wrapped group is simply a second value.
NAV_ROW_JS = """
() => {
  const nav = document.getElementById("dash-nav");
  const groups = Array.from(nav.querySelectorAll("ul.dash-nav-group"));
  const style = getComputedStyle(nav);
  const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
  const tallest = Math.max(...groups.map((group) => group.offsetHeight));
  return {
    height: nav.offsetHeight,
    oneRowHeight: Math.ceil(tallest + padding),
    tops: [...new Set(groups.map((group) => group.offsetTop))],
    chrome: document.getElementById("app-chrome").offsetHeight,
  };
}
"""

#: Every desktop width the audit and the owner's ruling name: the row must fit at 1280 and up.
NAV_DESKTOPS = (("1440x900", 1440, 900), ("1280x800", 1280, 800))


@pytest.mark.parametrize("label,width,height", NAV_DESKTOPS, ids=[label for label, _, _ in NAV_DESKTOPS])
def test_the_page_nav_fits_one_row_on_every_desktop(browser, dashboard_server, label, width, height):
    """nav-r3-1 = re-audit #3's I1.

    W7's bordered pills, 0.9rem of padding on both sides of every divider and a 0.35rem eyebrow tail
    took four groups and ten page links to ~1,463px — wider than the viewport they had to fit — so
    REFERENCE wrapped alone onto a second row beside ~1,200px of empty ground and the pinned chrome
    grew from 108 to **147px of a 900px viewport** before the page's first sentence. The row is a
    budget; this is the only thing that can hold it to one.
    """
    context = browser.new_context(viewport={"width": width, "height": height})
    tab = context.new_page()
    try:
        tab.goto(f"{dashboard_server}/?access={TOKEN}", wait_until="networkidle")
        tab.goto(f"{dashboard_server}/dashboard", wait_until="networkidle")
        # The row wraps when the brand webfont lands, not when the page parses (see I2 below).
        tab.wait_for_timeout(400)
        measured = tab.evaluate(NAV_ROW_JS)
    finally:
        context.close()

    assert len(measured["tops"]) == 1, f"at {label} the nav groups sit on {len(measured['tops'])} rows: {measured}"
    assert measured["height"] <= measured["oneRowHeight"], f"at {label} the nav is taller than one row: {measured}"


#: Where a `#turn-N` deep link actually landed, against the chrome that is pinned over it.
LANDING_JS = """
() => {
  const chrome = document.getElementById("app-chrome").getBoundingClientRect();
  const card = document.getElementById("turn-1");
  const head = card && card.querySelector(".turn-head");
  return {
    chromeBottom: Math.round(chrome.bottom),
    cardTop: card ? Math.round(card.getBoundingClientRect().top) : null,
    headTop: head ? Math.round(head.getBoundingClientRect().top) : null,
    published: getComputedStyle(document.documentElement).getPropertyValue("--dash-nav-h").trim(),
  };
}
"""

LANDING_VIEWPORTS = (("1440x900", 1440, 900), ("1280x800", 1280, 800), ("390x844", 390, 844))


@pytest.mark.parametrize("label,width,height", LANDING_VIEWPORTS, ids=[label for label, _, _ in LANDING_VIEWPORTS])
def test_a_deep_link_lands_below_the_chrome_pinned_over_it(browser, dashboard, label, width, height):
    """nav-r3-2 = DR3-02 = re-audit #3's I2 — the goal-(c) regression.

    `_chrome_height.html` published `--dash-nav-h` during parse and re-measured only on `resize`.
    Both are the wrong moment: the script runs while the brand webfont is still loading, so at 1440
    the nav still fitted one row (110px) as it was measured and reflowed to two (147px) when the
    font arrived — with no resize to notice it. The card then landed 25px behind the chrome with
    "Turn 1 · answered" sliced in half.

    **A context of its own per viewport, with an empty HTTP cache**, because that race is exactly
    what a warm cache hides: reuse a tab and the font is already there when the measurement runs.
    """
    context = browser.new_context(viewport={"width": width, "height": height})
    tab = context.new_page()
    try:
        tab.context.add_cookies([{"name": "mosaic_access", "value": TOKEN, "url": dashboard.base_url}])
        tab.goto(f"{dashboard.base_url}{dashboard.session_route}#turn-1", wait_until="load")
        tab.wait_for_timeout(500)
        measured = tab.evaluate(LANDING_JS)
    finally:
        context.close()

    assert measured["cardTop"] is not None, "the deep link names a turn this page renders"
    assert measured["cardTop"] >= measured["chromeBottom"], (
        f"at {label} the turn landed {measured['chromeBottom'] - measured['cardTop']}px behind the chrome: {measured}"
    )
    assert measured["headTop"] >= measured["chromeBottom"], (
        f"at {label} the turn's own header is under the chrome: {measured}"
    )


#: The section a citation named, the heading it owns, and whether the browser lit it.
READER_LANDING_JS = """
(id) => {
  const target = document.getElementById(id);
  if (!target) return null;
  const section = target.closest(".reader-section") || target;
  const heading = section.querySelector("h3");
  const passage = section.querySelector(".reader-passage");
  const chrome = document.getElementById("app-chrome").getBoundingClientRect();
  const landed = target.tagName === "SECTION" ? heading : passage;
  return {
    chromeBottom: Math.round(chrome.bottom),
    headingTop: Math.round(heading.getBoundingClientRect().top),
    landedTop: Math.round(landed.getBoundingClientRect().top),
    landedOn: target.tagName.toLowerCase(),
    background: getComputedStyle(section).backgroundColor,
    accentSoft: getComputedStyle(document.documentElement).getPropertyValue("--accent-soft").trim(),
  };
}
"""

READER_DOC = "/policy/remote-and-hybrid-work"


def _rgb(value: str) -> tuple[int, ...]:
    """`#d5e6e2` or `rgb(213, 230, 226)` → `(213, 230, 226)`, so the two can be compared."""
    value = value.strip()
    if value.startswith("#"):
        return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


@pytest.mark.parametrize("label,width,height", LANDING_VIEWPORTS, ids=[label for label, _, _ in LANDING_VIEWPORTS])
def test_a_citation_lands_on_its_section_and_lights_it(browser, dashboard, label, width, height):
    """nav-r3-3 = DR3-03 = re-audit #3's I3 — the surface every chat citation points at.

    W7 moved the chunk id off the `<section>` and onto an `<a class="anchor">` placed *after* the
    `<h3>`, so the browser aligned the anchor and the heading went under the masthead — 18px of it
    at 1440, the whole line at 390 — and `.reader-section:target` could never match again, because
    the fragment named the `<a>`. Both halves are measured here: where the reader lands, and whether
    the product says which passage they followed a link to.
    """
    context = browser.new_context(viewport={"width": width, "height": height})
    tab = context.new_page()
    try:
        tab.context.add_cookies([{"name": "mosaic_access", "value": TOKEN, "url": dashboard.base_url}])
        tab.goto(dashboard.base_url + READER_DOC, wait_until="networkidle")
        fragments = tab.evaluate(
            "() => Array.from(document.querySelectorAll('.reader-contents a')).map(a => a.getAttribute('href'))"
        )
        assert fragments, "the reader lists its sections"
        for fragment in fragments[:3]:
            tab.goto(dashboard.base_url + READER_DOC + fragment, wait_until="load")
            tab.wait_for_timeout(350)
            measured = tab.evaluate(READER_LANDING_JS, fragment[1:])
            assert measured, f"{fragment} names nothing on the page"
            assert measured["headingTop"] >= measured["chromeBottom"], (
                f"at {label} {fragment} put its heading "
                f"{measured['chromeBottom'] - measured['headingTop']}px under the chrome: {measured}"
            )
            assert _rgb(measured["background"]) == _rgb(measured["accentSoft"]), (
                f"at {label} {fragment} landed on a section the page does not light: {measured}"
            )
    finally:
        context.close()


#: Every sideways scroller inside `main`, with the two affordances the product standardised on in
#: W7: the permanent thin scrollbar and the edge gradients that cancel themselves at the ends.
SCROLLER_AFFORDANCE_JS = """
() => {
  const out = [];
  for (const el of document.querySelectorAll("main *")) {
    const style = getComputedStyle(el);
    if (style.display === "none" || el.clientWidth === 0) continue;
    if (el.closest(".visually-hidden")) continue;
    if (el.scrollWidth <= el.clientWidth + 1) continue;
    const scrolls = style.overflowX === "auto" || style.overflowX === "scroll";
    if (!scrolls) continue;
    out.push({
      el: el.tagName.toLowerCase() + (el.className ? "." + String(el.className).split(" ")[0] : ""),
      over: el.scrollWidth - el.clientWidth,
      scrollbar: style.scrollbarWidth === "thin",
      shade: (style.backgroundImage || "none").includes("gradient"),
    });
  }
  return out;
}
"""


def test_every_sideways_scroller_on_a_phone_says_that_it_scrolls(browser, dashboard):
    """npo4-05 = re-audit #3's I8, and the reason W7's overflow guard never saw it.

    W7 turned the session page's "Show these steps" filters into a nowrap row that scrolls sideways
    and gave it neither affordance: at 390x844 it measured 870/311 with five of the nine toggles
    invisible and the row clipped mid-label. The existing container guard runs at 1440 and 1280
    only, and allows anything inside `.table-scroll` — so the one viewport the defect lives at was
    not measured at all. A box may scroll; it may not scroll in silence.
    """
    context = browser.new_context(viewport={"width": 390, "height": 844})
    tab = context.new_page()
    silent: dict[str, list] = {}
    try:
        tab.goto(f"{dashboard.base_url}/?access={TOKEN}", wait_until="networkidle")
        for route in dashboard.routes:
            tab.goto(dashboard.base_url + route, wait_until="networkidle")
            tab.wait_for_timeout(100)
            mute = [box for box in tab.evaluate(SCROLLER_AFFORDANCE_JS) if not (box["scrollbar"] and box["shade"])]
            if mute:
                silent[route] = mute
    finally:
        context.close()
    assert not silent, f"these boxes scroll sideways with no affordance at 390x844: {silent}"


#: Every in-place definition on the page: the term, whether it can take focus, and the sentence the
#: accessibility tree will read out for it.
DEFINITIONS_JS = """
() => Array.from(document.querySelectorAll("[aria-describedby]")).flatMap((el) => {
  const bubble = document.getElementById(el.getAttribute("aria-describedby"));
  if (!bubble || bubble.getAttribute("role") !== "tooltip") return [];
  const style = getComputedStyle(el);
  const box = el.getBoundingClientRect();
  return [{
    term: (el.textContent || el.getAttribute("value") || el.id || "").trim().slice(0, 40),
    focusable: el.tabIndex >= 0,
    described: bubble.textContent.trim(),
    painted: style.display !== "none" && box.width > 0 && box.height > 0,
  }];
})
"""

#: …the per-table legend the phone card layout prints above the stack of cards, and every place a
#: definition is still nothing but a `title=`.
#:
#: The `title_only` selector is deliberately narrow: a column header, the label of a filter control
#: and anything wearing the `.has-help` affordance are where this product puts definitions. A
#: `title` elsewhere is a different thing and stays — the unrounded figure behind a rounded metric
#: tile, the full timestamp behind a one-line run label — which is **P15**, not this defect.
PHONE_LEGEND_JS = """
() => ({
  legends: Array.from(document.querySelectorAll(".table-legend")).map((el) => ({
    painted: getComputedStyle(el).display !== "none",
    terms: Array.from(el.querySelectorAll("dt")).map((dt) => dt.textContent.trim()),
    empty: Array.from(el.querySelectorAll("dd")).filter((dd) => !dd.textContent.trim()).length,
  })),
  title_only: Array.from(document.querySelectorAll("th [title], label [title], .has-help[title]"))
    .filter((el) => el.tabIndex < 0)
    .map((el) => el.tagName.toLowerCase() + ":" + el.getAttribute("title").slice(0, 40)),
})
"""

DEFINITION_VIEWPORTS = (("1440x900", 1440, 900), ("390x844", 390, 844))


@pytest.mark.parametrize(
    "label,width,height", DEFINITION_VIEWPORTS, ids=[label for label, _, _ in DEFINITION_VIEWPORTS]
)
def test_every_in_place_definition_is_a_control_a_reader_can_reach(browser, dashboard, label, width, height):
    """DR3-07 = re-audit #3's I14, the last of `dashboard-readability-5`.

    The owner ruled out a glossary page, so a term a grader cannot be expected to know carries its
    definition where it is used — and all 27 of them were a bare `title=` on a non-focusable
    `<span>`. No tab stop, no `aria-describedby`, nothing at all under a thumb, and nothing
    whatsoever at 390px, where the card layout clips the entire `<thead>` that carried them. Each
    one is a `<dfn tabindex="0">` with a `role="tooltip"` beside it now, and on a phone the columns'
    definitions are printed once above the cards their rows become.
    """
    context = browser.new_context(viewport={"width": width, "height": height})
    tab = context.new_page()
    unreachable: dict[str, list] = {}
    mute: dict[str, list] = {}
    try:
        tab.goto(f"{dashboard.base_url}/?access={TOKEN}", wait_until="networkidle")
        for route in dashboard.routes:
            tab.goto(dashboard.base_url + route, wait_until="networkidle")
            tab.wait_for_timeout(100)
            definitions = tab.evaluate(DEFINITIONS_JS)
            broken = [item for item in definitions if not item["focusable"] or not item["described"]]
            if broken:
                unreachable[route] = broken
            page = tab.evaluate(PHONE_LEGEND_JS)
            if page["title_only"]:
                mute[route] = page["title_only"]
            for legend in page["legends"]:
                # The header is clipped away at 390, so the definitions are printed above the cards
                # — and only there: on a desktop each one belongs to the column it explains.
                assert legend["painted"] == (width < 640), (
                    f"{route} at {label}: the column legend is {'hidden' if width < 640 else 'painted'}: {legend}"
                )
                assert legend["terms"] and not legend["empty"], f"{route} at {label}: an empty legend: {legend}"
    finally:
        context.close()

    assert not unreachable, f"at {label} these definitions are not reachable: {unreachable}"
    assert not mute, f"at {label} these definitions are still hover-only `title=` attributes: {mute}"
