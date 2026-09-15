"""**P10**: one convention per concept — every number on a dashboard page goes through a filter.

`docs/superpowers/plans/2026-09-14-ux-remediation-plan.md` §1 P10 states the rule mechanically:
*"No bare `{{ value }}` for a numeric or temporal expression in any template — every one goes
through a registered Jinja filter."* It is the principle behind most of W4's numeric findings: a
rate that read `1.0` on one page and `50.0%` one click away, money at four decimal places on one
tile and two on another, thousands separators on the tile and not on the row below it. Those are
not formatting bugs one at a time; they are the absence of a single formatter path, and this file
is what keeps the path single.

**How it is decided, rather than asserted by hand.** The set of numeric and temporal names is read
off the view-models themselves — every `int` / `float` field of every `_View` in `web/dashboard.py`,
plus the metric keys of `EvalMetrics`. A template expression that names one of them and is rendered
into the page's *text* must pipe it through one of the registered numeric filters. Expressions
inside an attribute (`id="turn-{{ turn.seq }}"`) and inside a `<script>` block (`{{ rows|tojson }}`)
are not text a reader reads, and are exempt.

So a view-model that grows a field grows this check with it: the thirteenth page cannot print a raw
float without failing here first.
"""

from __future__ import annotations

import inspect
import re
import typing

from pydantic import BaseModel

from hrmosaic.web import dashboard
from hrmosaic.web.api import PACKAGE_DIR

TEMPLATES = PACKAGE_DIR / "templates" / "dashboard"

#: The filters that render a number or a moment. `plural` and `counted` are here because a count
#: that agrees with its noun has gone through a formatter as surely as one with separators has.
NUMERIC_FILTERS = frozenset(
    {"num", "ms", "ms_n", "secs", "pct", "rate", "score", "usd", "orna", "ts", "clamp", "counted", "plural"}
)

#: Filters that render something else entirely and are therefore not evidence of formatting.
NON_NUMERIC_FILTERS = frozenset({"tojson", "pretty", "payload_pretty", "compact", "string", "length"})

#: Names that are numeric on a model but are rendered as identity, not as quantity. Each one is a
#: deliberate exception, written down rather than silently allowed.
RENDERED_AS_IDENTITY = frozenset(
    {
        "version",  # `CorpusDocumentDetail.version` is a document version string, not a number
    }
)

EXPRESSION = re.compile(r"\{\{(.*?)\}\}", re.S)
#: `{{ t.table(...) }}` / `{{ f.bar(...) }}` — a call into an imported macro. The field names inside
#: its column list are *arguments*, not rendered values; the macro that renders them is
#: `_table.html`, which this file scans like every other template.
MACRO_CALL = re.compile(r"^\s*[a-z]\.[a-z_]+\(", re.S)
SCRIPT = re.compile(r"<script\b.*?</script>", re.S | re.I)
FILTERED = re.compile(r"\|\s*([a-z_]+)")
#: A quoted literal inside an expression is a *key*, not a value — `{{ 'over_refusal_rate'|metric_label }}`
#: renders the metric's English label and no number at all.
LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")


def _numeric_field_names() -> set[str]:
    names: set[str] = set(dashboard.METRIC_LABELS)
    for member in vars(dashboard).values():
        if not (inspect.isclass(member) and issubclass(member, BaseModel)):
            continue
        for name, field in member.model_fields.items():
            if _is_numeric(field.annotation):
                names.add(name)
    return names - RENDERED_AS_IDENTITY


def _is_numeric(annotation: object) -> bool:
    """`int`, `float`, `int | None`, `float | None` — and never `bool`, which renders as a word."""
    if annotation in (int, float):
        return True
    args = typing.get_args(annotation)
    return bool(args) and any(argument in (int, float) for argument in args)


def _text_expressions(body: str) -> list[tuple[str, str]]:
    """Every `{{ … }}` a reader is shown: not in a tag's attributes, not inside a `<script>`."""
    body = SCRIPT.sub(lambda match: " " * len(match.group(0)), body)
    found = []
    for match in EXPRESSION.finditer(body):
        before = body[: match.start()]
        if before.rfind("<") > before.rfind(">"):
            continue  # inside a tag — an id, an href, a title, a style
        if MACRO_CALL.match(match.group(1)):
            continue
        found.append((match.group(0), match.group(1)))
    return found


def test_every_numeric_expression_a_dashboard_page_prints_goes_through_a_filter():
    numeric = _numeric_field_names()
    assert {"duration_ms", "est_cost_usd", "error_rate", "n_turns"} <= numeric, (
        "the field set is read off the view-models; if this fails the reader below is broken"
    )

    bare: dict[str, list[str]] = {}
    for template in sorted(TEMPLATES.glob("*.html")):
        for rendered, expression in _text_expressions(template.read_text(encoding="utf-8")):
            values = LITERAL.sub(" ", expression)
            mentioned = {name for name in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", values) if name in numeric}
            if not mentioned:
                continue
            filters = set(FILTERED.findall(expression))
            if filters & NUMERIC_FILTERS or filters & NON_NUMERIC_FILTERS:
                continue
            bare.setdefault(template.name, []).append(rendered.strip())

    assert not bare, (
        "these dashboard expressions print a number with no formatter, so the page has as many "
        f"conventions as it has templates (P10): {bare}"
    )


def test_the_registered_filter_table_is_the_whole_display_vocabulary():
    """Every filter this suite trusts is actually registered, and every numeric one is named here."""
    registered = dict(dashboard.DASHBOARD_FILTERS)
    assert set(dashboard.TEMPLATES.env.filters) >= set(registered), "the table is installed on the environment"
    assert NUMERIC_FILTERS <= set(registered), f"unregistered: {sorted(NUMERIC_FILTERS - set(registered))}"


def test_one_date_convention_and_one_money_convention_for_the_whole_dashboard():
    """The two conventions the plan singles out, asserted on the formatters rather than on a page."""
    assert dashboard._f_ts(1_757_000_000_000_000).endswith(" UTC")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC", dashboard._f_ts(1_757_000_000_000_000))

    assert dashboard._f_usd(0) == "$0.00"
    assert dashboard._f_usd(0.0004) == "<$0.01"
    assert dashboard._f_usd(12.3456) == "$12.35"
    assert dashboard._f_usd(None) == "—"


def test_a_duration_is_shown_in_the_largest_unit_that_still_says_something():
    assert dashboard._f_ms(0) == "<1 ms"
    assert dashboard._f_ms(0.4) == "<1 ms"
    assert dashboard._f_ms(7) == "7 ms"
    assert dashboard._f_ms(1_500) == "1.50 s"
    assert dashboard._f_ms(90_000) == "1.5 min"
    assert dashboard._f_secs(569.4) == "9.5 min"


def test_a_count_carries_its_separators_and_a_float_a_fixed_number_of_places():
    assert dashboard._f_num(45_497) == "45,497"
    assert dashboard._f_num(0.9839181286549706) == "0.98"
    assert dashboard._f_num(1.0) == "1.00"
    assert dashboard._f_num(None) == "—"
    assert dashboard._f_score(0.7612) == "0.76"


def test_a_small_sample_shows_its_denominator_and_a_small_percentile_shows_its_n():
    """**P14**, on the formatters that carry it."""
    assert dashboard._f_rate(0.5, 2, "call") == "50.0% (1 of 2 calls)"
    assert dashboard._f_rate(0.1111, 9, "turn") == "11.1% (1 of 9 turns)"
    assert dashboard._f_rate(0.5, 200) == "50.0%", "a sample of 200 speaks for itself"
    assert dashboard._f_rate(0.5, None) == "50.0%"

    assert dashboard._f_ms_n(4200, 1) == "n=1"
    assert dashboard._f_ms_n(4200, 40) == "4.20 s"


def test_a_noun_agrees_with_the_count_beside_it():
    """**P9**: no page renders `row(s)`."""
    assert dashboard._f_counted(1, "row") == "1 row"
    assert dashboard._f_counted(9, "row") == "9 rows"
    assert dashboard._f_counted(0, "row") == "0 rows"
    for template in sorted(TEMPLATES.glob("*.html")):
        assert "(s)" not in template.read_text(encoding="utf-8"), template.name
