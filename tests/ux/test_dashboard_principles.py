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

    assert "Guardrail blocks" in figures and "Guardrail checks" in figures, figures
    blocks, checks = int(figures["Guardrail blocks"]), int(figures["Guardrail checks"])
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
