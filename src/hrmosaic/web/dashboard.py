"""The observability dashboard — the eleven pages and the whole `/api/*` layer (spec §11.6–§11.8).

USER.2 and USER.3 in full: every session, turn, LLM call, retrieval, tool call, guardrail and
confirmation is browsable, evaluation views included.

**One record, two representations.** Every page renders from the typed Pydantic view-model produced
by the *same* `/api/*` endpoint that serves its JSON: the route builds the model, dumps it once, and
either returns that dict as JSON or hands the very same dict to Jinja. So `test_dashboard_viewmodels`
validating the JSON and `test_dashboard_pages` asserting the rendered selectors are looking at one
object, and the Export JSON button on every page cannot drift from what the page shows.

**Nothing here is a second logging path.** Every number is read back from the tables `core/trace.py`
wrote (§10.1) — the same rows the `/chat` `trace[]` projection reads — the read-only corpus index, or
the `eval_runs` / `eval_results` rows `core/archive.py` imported. That is the USER.4 invariant, and
it is why `guardrail_blocks` on page 1 comes from `turns.guardrail_hits` rather than being recounted
from spans.

**Access (amended, UX W1).** The whole prefix is gated by the access token of §11 and by nothing
else: every page and every `/api/*` read answers any persona holding it. The role gates **writes**
only — `POST /api/dev/reset-sandbox`, `POST /api/mcp/rediscover` and `POST /api/eval/runs` — which
`web/api.py`'s pure-ASGI `AccessGateMiddleware` refuses with **403** `{"code": "ADMIN_REQUIRED"}`
outside the admin persona. Each of those three controls is therefore rendered on a page anyone can
reach, with its own server-side check behind it.
"""

from __future__ import annotations

import functools
import json
import logging
import math
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from markupsafe import Markup
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from hrmosaic.agent.client import McpUnavailable
from hrmosaic.agent.guardrails import RULE_NAMES
from hrmosaic.agent.orchestrator import preview_value, summarise_span
from hrmosaic.core import corpusread
from hrmosaic.core import trace as trace_module
from hrmosaic.core.db import Store, get_store, now_micros
from hrmosaic.core.models import DiscoveredTool, ServerInfo
from hrmosaic.core.queues import queue_label
from hrmosaic.core.trace import SessionSpec
from hrmosaic.settings import Settings
from hrmosaic.web import api

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Where `core/archive.py` imports committed runs from, and where the compare tab reads the
#: zero-LLM chunk-size sweep of §13.9. A module constant so a test can point it at a fixture set.
RESULTS_DIR = REPO_ROOT / "evaluation" / "results"

#: The 26-item dataset of §13.1. It arrives at P10; until then page 11's `question` / `gold`
#: columns are honestly empty rather than fabricated from the stored answer.
DATASET_PATH = REPO_ROOT / "evaluation" / "dataset.yaml"

#: Rows per page on the two paginated pages (2 and 4). Fixed rather than a query parameter, so
#: `page` and `total` in the view-model are enough to render the pager.
PAGE_SIZE = 50

#: The newest N rows the un-paginated detail pages (5–8) list. Retention already caps the store at
#: `TRACE_RETENTION_SESSIONS` sessions (§10.5); this bounds one page's HTML on top of that.
ROW_LIMIT = 200

#: The last 24 hours, one bucket an hour — page 1's sparkline.
SPARKLINE_HOURS = 24

#: §11.6's pages, grouped for the nav (UX W1, navigation-and-ia-8). The page *numbers* are still
#: the spec's — `data-page` and `data-nav` carry them and the contract tests key on them — but they
#: are no longer printed as `1.`–`11.` labels: the nav is a way around the app, not a rubric
#: checklist. Page 3 (session detail) has no standalone URL, so it is not an entry at all; it used
#: to be rendered as an inert grey pseudo-link at 2.455:1 contrast whose only explanation was a
#: hover `title`. It now highlights its real parent, Sessions.
NAV: tuple[tuple[str, tuple[tuple[int, str, str], ...]], ...] = (
    (
        "Activity",
        (
            (1, "Overview", "/dashboard"),
            (2, "Sessions", "/dashboard/sessions"),
            (4, "Turns", "/dashboard/turns"),
        ),
    ),
    (
        "Under the hood",
        (
            (5, "Model calls", "/dashboard/llm"),
            (6, "Retrieval", "/dashboard/retrieval"),
            (7, "Tools", "/dashboard/tools"),
            (9, "Tool server", "/dashboard/mcp"),
        ),
    ),
    ("Quality", ((8, "Guardrails", "/dashboard/safety"), (11, "Evaluations", "/dashboard/evals"))),
    # "Corpus & chunks", not "Policy library": the readable library is `/policy`, and two surfaces
    # sharing one name meant the inspector wore the reader's (UX W7, nav-r2-5).
    ("Reference", ((10, "Corpus & chunks", "/dashboard/corpus"),)),
)

#: Every nav destination by href, and the label the row of pills paints for it.
NAV_LABELS: dict[str, str] = {href: label for _group, _items in NAV for _number, label, href in _items}


def nav_label(href: str) -> str:
    """What the nav calls a route — for every other surface that has to name the same route.

    One name per destination (UX W8 fix round, nav-r3-4 = DR3-05 = re-audit #3 I4). The breadcrumb
    on all fourteen `/dashboard/corpus/{doc}` pages read **"Policy library"** and pointed at
    `/dashboard/corpus`, four lines under a nav pill reading "Corpus & chunks" that points at the
    same place — while the real policy library is `/policy`, a different surface for a different
    reader. A literal in a `breadcrumbs=` argument is how the two drifted; a lookup is how they
    cannot. `tests/contract/test_dashboard_pages.py` asserts every crumb against this map.
    """
    return NAV_LABELS[href]


#: What the three admin-gated write controls say to every other persona — one sentence, and a link
#: that can be followed rather than a pointer that has to be described (UX W7, M09 = dgc-r2-9).
#: Tool server and Evaluations said "set it in … at the foot of the chat page" and Guardrails said
#: "switch personas in … on the chat page": one action, two phrasings, two prepositions.
ADMIN_HINT = Markup(
    "<strong>Needs the HR admin persona</strong> — switch personas in "
    '<a href="/#actor-select">Demo &amp; grader controls</a> on the chat page.'
)

#: What each step kind is, for the session page's own legend (UX W7, DR2-04 = dashboard-readability-5).
SPAN_KIND_HELP: dict[str, str] = {
    "mcp_discovery": "The assistant asked the tool server what tools it offers.",
    "plan": "The router's decision: what the question is, and which tools may answer it.",
    "llm_call": "One call to the language model — to route, to act, or to write the answer.",
    "retrieval": "A search of the policy library for passages to answer from.",
    "tool_call": "A call to one HR tool over the tool server.",
    "guardrail": "One of the six safety checks (G1–G6) run over the turn.",
    "confirmation": "The gate that held a write until a human decided.",
    "judge": "A second model scoring an evaluation item.",
    "error": "Something went wrong at this step.",
}


def _tab(request: Request, tabs: Sequence[str]) -> str:
    """The tab a page opens on, from `?tab=` — the first one unless the query names another.

    Server-side, so every panel ships rendered and a fragment can open the panel that owns it
    without JavaScript (UX W7, nav-r2-2 = nav-r2-3).
    """
    wanted = (request.query_params.get("tab") or "").strip()
    return wanted if wanted in tabs else tabs[0]


#: Which nav entry a page highlights when it is not an entry itself: session detail is opened from
#: Sessions, so Sessions is what stays lit.
NAV_PARENT = {3: 2}

#: §11.6: the four judged aggregates are `Optional[float]` beside `judged: bool`, and the page
#: renders *"not judged on this variant"* rather than a zero. Judging happens on `baseline` only
#: (§13.9), so on the two ablation arms all four are `null`.
JUDGED_METRICS = ("groundedness_mean", "citation_accuracy_mean", "partial_match_mean", "clarification_accuracy")

#: The five deterministic aggregates — non-null on **every** run, judged or not (§13.3, §13.8).
DETERMINISTIC_METRICS = (
    "cit_resolve_mean",
    "blocks_dropped_by_g2",
    "tool_selection_accuracy",
    "arg_correctness_rate",
    "strict_pass_rate",
)

#: The headline strip of page 11, in the order §11.6 lists it.
HEADLINE_METRICS = (
    "groundedness_mean",
    "citation_accuracy_mean",
    "cit_resolve_mean",
    "blocks_dropped_by_g2",
    "tool_selection_accuracy",
    "arg_correctness_rate",
    "partial_match_mean",
    "strict_pass_rate",
)

TEMPLATES = api.TEMPLATES

#: The audience is the technical grader (UX owner decision, 2026-09-14): the technical noun stays
#: primary and the **key** never moves — `data-metric`, `data-col` and every `/api/*` field are
#: exactly what they were (P15) — but the *label* is English. `GROUNDEDNESS_MEAN` as a tile caption
#: pushed two of eight metric columns off a desktop viewport and told a reader nothing
#: (`jargon-and-exposure-18`, `dashboard-readability-6`).
METRIC_LABELS: dict[str, str] = {
    "groundedness_mean": "Groundedness",
    "citation_accuracy_mean": "Citation accuracy",
    "cit_resolve_mean": "Citations that resolve",
    "blocks_dropped_by_g2": "Blocks dropped by citation check",
    "tool_selection_accuracy": "Tool selection accuracy",
    "arg_correctness_rate": "Argument correctness",
    "partial_match_mean": "Partial match",
    "strict_pass_rate": "Strict pass rate",
    "clarification_accuracy": "Clarification accuracy",
    "over_refusal_rate": "Over-refusal rate",
    "missed_refusal_rate": "Missed-refusal rate",
    "action_safety_pass_rate": "Action-safety pass rate",
    "recommendation_labeled_rate": "Recommendations labelled",
    "catalog_reopened_rate": "Tool catalog reopened",
    "judge_agreement_rate": "Judge agreement",
}

#: Which of those are 0–1 proportions, and therefore render as percentages. The rest are counts.
#: One rate unit per page and per concept (**P10**): a metric used to read `1.0` on one page and
#: `50.0%` one click away (`numbers-precision-overflow-2`). The **stored** value stays 0–1 in
#: `/api/*`, in Export JSON and in the Chart.js series — page, export and chart agree.
RATE_METRICS: frozenset[str] = frozenset(
    {
        "groundedness_mean",
        "citation_accuracy_mean",
        "cit_resolve_mean",
        "tool_selection_accuracy",
        "arg_correctness_rate",
        "partial_match_mean",
        "strict_pass_rate",
        "clarification_accuracy",
        "over_refusal_rate",
        "missed_refusal_rate",
        "action_safety_pass_rate",
        "recommendation_labeled_rate",
        "catalog_reopened_rate",
        "judge_agreement_rate",
    }
)

#: The rules whose reader-facing name is *not* their `rule_name` with the underscores taken out.
#: Every other rule is derived, so a seventh rule added to `RULE_NAMES` renders as "G7 Something"
#: rather than as a bare letter and a number.
RULE_LABEL_OVERRIDES: dict[str, str] = {
    "G6": "Redaction sweep",  # `pii_secret_redaction` — "Redaction sweep" is the reader's noun
}

#: `G1`–`G6` with what each one does. `agent/guardrails/__init__.py` owns the identifier→name
#: pairing that the span carries and this is the *display* half — **derived** from it, because a
#: second hand-maintained copy is a copy that drifts (UX W4 review, fix round 1). The chart's
#: category labels come from here, so the axis is not six bare letters (`dashboard-readability-17`).
RULE_LABELS: dict[str, str] = {
    rule: RULE_LABEL_OVERRIDES.get(rule, name.replace("_", " ").capitalize()) for rule, name in RULE_NAMES.items()
}

#: A span kind as the page says it. The toggle row on page 3 used to be raw kinds
#: (`jargon-and-exposure-20`); the `value` of each toggle is still the kind, because that is what
#: `data-kind` filters on.
SPAN_KIND_LABELS: dict[str, str] = {
    "mcp_discovery": "Tool-server handshake",
    "plan": "Plan",
    "llm_call": "Model call",
    "retrieval": "Retrieval",
    "tool_call": "Tool call",
    "guardrail": "Safety check",
    "confirmation": "Confirmation",
    "judge": "Judge",
    "error": "Error",
}


# --------------------------------------------------------------------------------------
# Jinja filters — the display vocabulary the eleven pages share
# --------------------------------------------------------------------------------------


#: **P14** — below this many samples a rate is shown with its denominator ("11.1% (1 of 9 turns)")
#: rather than alone, because a percentage of nine is a percentage a reader will over-trust.
SMALL_SAMPLE = 20

#: **P14** — below this many samples a percentile is not a number at all: `n=3` says what the
#: figure would have been computed from, which is the only honest thing to print.
SMALL_PERCENTILE = 5


def _f_ts(value: Any) -> str:
    """Epoch **microseconds** (§10.1's unit) rendered UTC, to the second."""
    if value in (None, ""):
        return "—"
    try:
        return datetime.fromtimestamp(int(value) / 1_000_000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


def _f_iso(value: Any) -> str:
    """The same instant as a **machine-readable** `datetime` attribute (UX W8, W7 review).

    `<time datetime="1789487770345981">` is not a datetime: the attribute takes an HTML date-time
    string, and epoch microseconds are neither parsed by a browser nor read by an assistive
    technology, so the one element on the page whose whole purpose is to publish a machine-readable
    instant was publishing an opaque integer. The visible text is still `_f_ts`'s.
    """
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(int(value) / 1_000_000, tz=UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _f_ms(value: Any) -> str:
    """A duration in the largest unit that still says something — and never a truncated zero.

    `spans.duration_ms` is whole milliseconds, so a sub-millisecond step stores `0`. Printing that
    as *"0 ms"* claimed the work took no time at all on 16 of 28 waterfall rows, every model call
    and every handshake (`numbers-precision-overflow-5`); `<1 ms` is what the record supports.
    """
    if value is None:
        return "—"
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return str(value)
    if milliseconds >= 60_000:
        return f"{milliseconds / 60_000:.1f} min"
    if milliseconds >= 1_000:
        return f"{milliseconds / 1_000:.2f} s"
    if milliseconds < 1:
        return "<1 ms"
    return f"{milliseconds:.0f} ms"


def _f_secs(value: Any) -> str:
    """Seconds, through the one duration formatter — `569.4` was a number a reader had to divide."""
    if value is None:
        return "—"
    try:
        return _f_ms(float(value) * 1_000)
    except (TypeError, ValueError):
        return str(value)


def _f_num(value: Any) -> str:
    """Counts with thousands separators; a float at a **fixed** two places.

    The old `rstrip("0").rstrip(".")` gave every float column a ragged right edge — `1`, `0.75`,
    `0.9839` one under the other — which is the alignment defect `numbers-precision-overflow-9`
    reports, arriving from the formatter rather than from the CSS.
    """
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.2f}"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _f_pct(value: Any) -> str:
    """A 0–1 proportion as a percentage, one decimal place. The one rate convention on the pages."""
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def _f_rate(value: Any, n: Any = None, unit: str = "", always: bool = False) -> str:
    """**P14**: the same percentage, carrying its denominator while the sample is small.

    `50.0%` from one of two calls and `11.1%` from one of nine turns are not percentages a reader
    should read as rates, and the page is the only place that can say so — the JSON keeps the bare
    float either way (P15).

    `always=True` drops the twenty-sample threshold (UX W8 fix round, npo4-02 = re-audit #3 I6).
    On `/dashboard/evals/{run}` — a page whose entire subject is *how a figure was computed* — four
    headline rates, the action-safety rate, the catalog rate and both workflow-completion rows
    printed bare beside two that carried a denominator, and the threshold is what made that legal:
    a rate over 28 items and a rate over 1 looked identical. Every rate on a statistics page states
    its sample, whatever its size.
    """
    if value is None:
        return "—"
    shown = _f_pct(value)
    try:
        sample = int(n)
    except (TypeError, ValueError):
        return shown
    if sample <= 0 or (sample >= SMALL_SAMPLE and not always):
        return shown
    numerator = round(float(value) * sample)
    tail = f"{sample:,} {_f_plural(sample, unit)}" if unit else f"{sample:,}"
    return f"{shown} ({numerator:,} of {tail})"


def _f_ms_n(value: Any, n: Any = None) -> str:
    """**P14**: a percentile over fewer than five samples prints its `n`, not a figure."""
    try:
        sample = int(n)
    except (TypeError, ValueError):
        sample = None
    if sample is not None and sample < SMALL_PERCENTILE:
        return f"n={sample}"
    return _f_ms(value)


def _f_rate_sample(value: Any, n: Any = None, unit: str = "") -> str:
    """The parenthetical of `_f_rate` on its own — `3 of 3 items` — or nothing (UX W9, npo5-05).

    The list page's headline table has eight rate columns; a sample inside the cell's one line
    pushed the table 79px past its box at 1440 and 239px at 1280. The page prints the rate on one
    line and, under P14's threshold, the sample on a second.
    """
    if value is None:
        return ""
    try:
        sample = int(n)
    except (TypeError, ValueError):
        return ""
    if sample <= 0 or sample >= SMALL_SAMPLE:
        return ""
    numerator = round(float(value) * sample)
    tail = f"{sample:,} {_f_plural(sample, unit)}" if unit else f"{sample:,}"
    return f"{numerator:,} of {tail}"


def _f_score(value: Any) -> str:
    """A similarity score at two places — the precision the 0–1 scale actually carries."""
    return "—" if value is None else f"{float(value):.2f}"


def _f_usd(value: Any) -> str:
    """Money at two decimal places, with an exact-zero branch and a band below the cent.

    Always an estimate (§9.8) — the label lives beside it on every page. Four decimal places made
    three adjacent `$0.0000` tiles the loudest thing on the landing page and said nothing at all
    (`numbers-precision-overflow-6`).
    """
    if value is None:
        return "—"
    amount = float(value)
    if amount == 0:
        return "$0.00"
    if 0 < amount < 0.005:
        return "<$0.01"
    return f"${amount:,.2f}"


def _f_orna(value: Any) -> str:
    """A metric that was not computed reads as an em dash, never as a fabricated zero.

    A float that *was* computed goes through `_f_num`, so an "or n/a" cell cannot be the one place
    a raw `0.9839181286549706` survives (P10: one formatter path per concept).
    """
    if value is None:
        return "—"
    return _f_num(value) if isinstance(value, float) else str(value)


def _f_plural(count: Any, singular: str, plural: str | None = None) -> str:
    """**P9**: the noun agrees with the count, so no page renders `row(s)`."""
    try:
        number = int(count)
    except (TypeError, ValueError):
        return singular
    return singular if abs(number) == 1 else (plural or f"{singular}s")


def _f_counted(count: Any, singular: str, plural: str | None = None) -> str:
    """`1 row` / `9 rows` — the count and the noun it agrees with, formatted once."""
    return f"{_f_num(count)} {_f_plural(count, singular, plural)}"


def _f_metric_label(key: Any) -> str:
    """A stored metric name as a person reads it (`GROUNDEDNESS_MEAN` → *Groundedness*).

    The **key** never changes: it is the JSON field, the `data-metric` hook and the column the
    contract tests select on. Only the label does (P15 — relocated, never destroyed).
    """
    name = str(key)
    return METRIC_LABELS.get(name, name.replace("_", " ").capitalize())


#: The one answer-block type whose bare name would mislead on the session page: `record` is the
#: reader's own HR data (UX W7, JX2-05), not a record in the dashboard's sense of the word.
ANSWER_BLOCK_LABELS: dict[str, str] = {"record": "HR record"}


def _f_kind_label(kind: Any) -> str:
    """A span kind as a person reads it — the chip row used to be raw `llm_call` / `mcp_discovery`.

    The session page's answer blocks come through here too (`data-block`), so a block type is
    labelled the same way."""
    name = str(kind)
    return SPAN_KIND_LABELS.get(name) or ANSWER_BLOCK_LABELS.get(name) or name.replace("_", " ").capitalize()


def _f_rule_label(rule_id: Any) -> str:
    """`G1` → *G1 Evidence gate*: the identifier a grader greps for, plus what it does."""
    name = str(rule_id)
    return f"{name} {RULE_LABELS[name]}" if name in RULE_LABELS else name


#: An **opaque** identifier: a run of lower-case hex with no structure a reader can use. Those are
#: the ones an 8-character chip abbreviates without losing anything — 32-hex turn, span and session
#: ids, and a git sha. Everything else keeps every character it has (UX W6, npo2-04 = dr-new-4 =
#: JX-R13): eval run ids are `r_<unix-epoch>_<variant>`, so chipping them at 9 collapsed fifteen
#: rows to six indistinguishable `r_178916…` chips, and document slugs became `benefits…`,
#: `equipmen…`, `pto-and-…` — except `travel-policy`, which Jinja's `truncate` leeway spared, so the
#: column looked broken rather than abbreviated.
OPAQUE_ID = re.compile(r"[0-9a-f]{16,}")

#: Where a structured id is long enough to need a cap, the **tail** is what survives: the variant
#: and the low digits of the epoch are what tell two run ids apart, and the prefix is what they
#: share.
ID_CHIP_CHARS = 8
STRUCTURED_ID_CHARS = 32


def _f_id_chip(value: Any) -> str:
    """The id as a chip: eight characters of an opaque hex id, and every character of anything else."""
    text = str(value)
    if OPAQUE_ID.fullmatch(text):
        return f"{text[:ID_CHIP_CHARS]}…"
    if len(text) > STRUCTURED_ID_CHARS:
        return f"…{text[-(STRUCTURED_ID_CHARS - 1) :]}"
    return text


#: A stored enum as a person reads it. **P13, P10**: every *header* was renamed at W4 and every
#: *value* was left raw, so the page said `SIGN-IN: cookie`, `hybrid_rrf`, `awaiting_confirmation`
#: and offered a `simple_policy, multi_doc, unsafe_action` filter three inches above a legend
#: reading "5 multi doc, 7 simple policy" (UX W6, JX-R4). One filter, applied wherever a value
#: reaches a reader, so the filter bar and the legend under it cannot disagree.
ENUM_LABELS: dict[str, str] = {
    "cookie": "shared key",
    "bearer": "bearer header",
    "open": "open local run",
    "awaiting_confirmation": "awaiting confirmation",
    "hybrid_rrf": "hybrid — dense and keyword",
    "multi_doc": "multi-document",
    "simple_policy": "simple policy",
    "tool_task": "tool task",
    "out_of_scope": "out of scope",
    "unsafe_action": "unsafe action",
    "conditional": "conditional",
    # The compliance verdicts and the tool error codes, as words (UX W9, DR4-07 and DR4-08): the
    # summariser de-underscored `non_compliant` into "non compliant" and painted the raw
    # `CONFIRMATION_REQUIRED` under WHY IT STOPPED beside a humanised OUTCOME.
    "non_compliant": "non-compliant",
    "insufficient_evidence": "insufficient evidence",
    "compliant": "compliant",
    "CONFIRMATION_REQUIRED": "paused for confirmation",
    "INVALID_ARGUMENTS": "invalid arguments",
    "EMPLOYEE_NOT_FOUND": "employee not found",
    "VERDICT_NON_COMPLIANT": "refused: verdict non-compliant",
    # Model calls (UX W7, JX2-01): the finish reason and the provider are enums too.
    "end_turn": "finished",
    "stop": "finished",
    "tool_use": "asked for a tool",
    "max_tokens": "hit the token limit",
    "length": "hit the token limit",
    "stub": "recorded script",
    # Health (JX2-01): where the conversation record lives, said as a fact about durability.
    "sqlite": "on disk — survives a restart",
    "memory": "in memory — lost on restart",
    # Turns (DR2-09): the router's intents and workflows.
    "policy_qa": "policy question",
    "pto_request": "PTO request",
    "remote_work_eligibility": "remote work eligibility",
    "expense_claim": "expense claim",
    "dense_only": "dense only",
}


def _f_enum_label(value: Any) -> str:
    """One vocabulary for stored values, exactly as `_f_metric_label` is one for stored metric names.

    An unmapped value loses its underscores and keeps its words: a token this map has not been
    taught is still not a field name on the page, and a new enum arriving unnoticed reads as
    English rather than as code.
    """
    text = str(value)
    return ENUM_LABELS.get(text, text.replace("_", " "))


@functools.cache
def _persona_names() -> dict[str, str]:
    """`employee_id → preferred name` from the same `mock_data/employees.json` the tools read."""
    try:
        records = json.loads((REPO_ROOT / "mock_data" / "employees.json").read_text(encoding="utf-8"))["records"]
    except Exception:
        logger.warning("could not read mock_data/employees.json", exc_info=True)
        return {}
    return {
        str(record["employee_id"]): str(
            record.get("preferred_name") or record.get("legal_name") or record["employee_id"]
        )
        for record in records
        if record.get("employee_id")
    }


def _f_persona_name(value: Any) -> str:
    """The persona by name — `E1042` is the id the masthead 60px above never shows (UX W9, DR4-09).

    The id stays in the record (P15): the `persona` cell kind carries it in the `title`, and the
    JSON export publishes the column as stored. An id the roster does not know is printed as is.
    """
    if value in (None, ""):
        return ""
    return _persona_names().get(str(value), str(value))


#: `_f_enum_label` read backwards: the words the page paints → the token the database stores. Two
#: tokens can share one label (`end_turn` and `stop` are both "finished"); the first one declared
#: wins, which is the one a filter over that column would want.
_ENUM_TOKENS: dict[str, str] = {}
for _token, _label in ENUM_LABELS.items():
    _ENUM_TOKENS.setdefault(_label.casefold(), _token)


def enum_token(value: str) -> str:
    """The stored value a reader's words name (UX W8 fix round, DR3-04 = re-audit #3 I13).

    DR2-09 humanised the Turns page — the Intent and Workflow cells, the filter chips **and the
    free-text placeholders**, which now read `e.g. PTO request`. The filter itself is exact SQL
    equality against the stored token, so the page invited a reader to type the one string that
    matches nothing: `workflow='PTO request'` → 0 rows, `workflow='pto_request'` → 2. This is the
    inverse, and it is deliberately narrow — the explicit vocabulary first, then the mechanical
    undo of `leaf.replace("_", " ")`, and only where there is a space to undo, because a persona
    id (`E1042`) and a model name go through filters of their own and are not enums at all.
    """
    text = value.strip()
    token = _ENUM_TOKENS.get(text.casefold())
    if token is not None:
        return token
    return text.casefold().replace(" ", "_") if " " in text else text


def _f_server_location(url: Any) -> str:
    """Where the tool server runs, without publishing its address (UX W6, JX-R5)."""
    if not url:
        return "in this process"
    host = urlsplit(str(url)).hostname or ""
    return "on this machine" if host in {"127.0.0.1", "localhost", "::1"} else host


def _f_payload_pretty(value: Any) -> str:
    """A span payload, pretty-printed, minus the field that is a copy of another field.

    `result_json` is a double-encoded duplicate of `structured_content`: one 8 KB line that blew a
    payload block to 59,780px of horizontal scroll (`dashboard-readability-8`). It is dropped from
    the *rendering* only where the structured copy is present — `/api/*` and Export JSON still
    carry both, because the record is never destroyed (P15).
    """
    if isinstance(value, dict) and value.get("structured_content") is not None and "result_json" in value:
        value = {key: item for key, item in value.items() if key != "result_json"}
    return _f_pretty(value)


def _f_compact(value: Any, limit: int = 60) -> str:
    body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return body if len(body) <= limit else body[: limit - 1] + "…"


def _f_pretty(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def _f_clamp(value: Any, minimum: float = 0.0) -> str:
    """A CSS percentage for the page-3 duration bars, never outside 0–100."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if math.isnan(number) or math.isinf(number):
        number = 0.0
    return f"{min(100.0, max(minimum, number)):.3f}"


def _f_span_summary(span: dict[str, Any]) -> str:
    """The same one-line summary the `/chat` `trace[]` and the SSE rail show (§11.1).

    `agent.orchestrator`'s own helper rather than a second implementation: the waterfall, the
    concise trace and the live rail describe a span identically, or the panel the rail collapses
    into would disagree with the page it links to.
    """
    summary = summarise_span(span.get("kind", ""), span.get("name", ""), span.get("payload") or {})
    # The plan, model-call and guardrail lines are `key=value` in the `/chat` trace (§11.1's
    # shapes, which that contract pins); on the dashboard each pair is said as a label and a
    # labelled value — `intent=workflow workflow=pto_request catalog_reopened=false` was the last
    # raw enum the capture's sidecars found (UX W7, JX2-01 = DR2-09, DR2-04).
    if span.get("kind") in {"plan", "llm_call", "guardrail"}:
        return _said_source_unit(_said_pairs(summary))
    return summary


#: `(3 sources)` at the end of the G2 line. The number counts the distinct **documents** behind the
#: citations; the same turn's chat strip says `Sources (6)`, which counts passages.
_G2_SOURCES = re.compile(r"\((\d+) sources?\)")


def _said_source_unit(summary: str) -> str:
    """Name the unit the citation line counts (UX W8 fix round, npo4-03 = re-audit #3 I7).

    `8 of 8 citation links resolved (3 sources)` on the session page, `Sources (6)` in chat and
    "6 policy sections read" in the demo panel were three numbers for one word, all within a click
    of each other: links, documents and passages, none of them saying which. The links half already
    names its unit; this names the other one. The raw `reason` is untouched in the span payload and
    in `/api/*` (P15) — this is the *rendered* line.
    """

    def replace(match: re.Match[str]) -> str:
        return f"(across {_f_counted(int(match.group(1)), 'document')})"

    return _G2_SOURCES.sub(replace, summary)


_PAIR = re.compile(r"(\s*)\b([a-z_]+)=([A-Za-z0-9_.:-]+)")


def _said_pairs(summary: str) -> str:
    """`intent=workflow workflow=pto_request` → `intent: workflow · workflow: PTO request`.

    Each pair becomes a label and a labelled value, and the pairs are separated (UX W8, W7 review):
    joined by the original single space, `intent: workflow workflow: PTO request` reads as one
    four-word label with a colon in the middle of it, and the reader cannot see where one fact ends
    and the next begins.
    """
    seen = False

    def replace(match: re.Match[str]) -> str:
        nonlocal seen
        lead, key, value = match.group(1), match.group(2), match.group(3)
        if value in {"true", "false"}:
            value = "yes" if value == "true" else "no"
        elif key not in {"purpose"}:
            value = _f_enum_label(value)
        separator = " · " if seen and lead else lead
        seen = True
        return f"{separator}{_f_enum_label(key)}: {value}"

    return _PAIR.sub(replace, summary)


#: Every display vocabulary the dashboard has, and the whole of it: **P10** is that a numeric or
#: temporal expression in a dashboard template goes through one of these and through nothing else
#: (`tests/contract/test_formatter_coverage.py` greps the templates for a bare one).
DASHBOARD_FILTERS = (
    ("ts", _f_ts),
    ("ms", _f_ms),
    ("ms_n", _f_ms_n),
    ("secs", _f_secs),
    ("num", _f_num),
    ("pct", _f_pct),
    ("iso", _f_iso),
    ("rate", _f_rate),
    ("rate_sample", _f_rate_sample),
    ("score", _f_score),
    ("usd", _f_usd),
    ("orna", _f_orna),
    ("plural", _f_plural),
    ("counted", _f_counted),
    ("metric_label", _f_metric_label),
    ("kind_label", _f_kind_label),
    ("rule_label", _f_rule_label),
    ("enum_label", _f_enum_label),
    ("persona_name", _f_persona_name),
    ("id_chip", _f_id_chip),
    ("server_location", _f_server_location),
    ("compact", _f_compact),
    ("pretty", _f_pretty),
    ("payload_pretty", _f_payload_pretty),
    ("clamp", _f_clamp),
    ("span_summary", _f_span_summary),
)

for _name, _filter in DASHBOARD_FILTERS:
    TEMPLATES.env.filters[_name] = _filter


# --------------------------------------------------------------------------------------
# Small shared helpers
# --------------------------------------------------------------------------------------


def percentile(values: Sequence[float | int | None], q: float) -> float | None:
    """The `statistics.quantiles(..., n=100)` percentile of §13.5, guarded for tiny samples."""
    data = sorted(float(value) for value in values if value is not None)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    cuts = statistics.quantiles(data, n=100, method="inclusive")
    index = min(len(cuts) - 1, max(0, int(round(q * 100)) - 1))
    return float(cuts[index])


def _day_bounds(value: str, *, end: bool) -> int | None:
    """`YYYY-MM-DD` → epoch micros at the start of that UTC day, or the start of the next one."""
    try:
        day = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    if end:
        day += timedelta(days=1)
    return int(day.timestamp() * 1_000_000)


def utc_day_start(days_ago: int = 0) -> int:
    now = datetime.now(tz=UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return int(start.timestamp() * 1_000_000)


def turn_record_url(session_id: Any, turn_id: Any) -> str | None:
    """Where a turn-id chip goes: the session record, opened at that turn.

    Five pages linked the chip to `/api/traces/turns/{id}` — an unstyled JSON document with no
    masthead, no heading and no route back — while the sixth linked the identical concept to the
    session page (UX W7, nav-r2-1). The session page anchors every turn by its id
    (`<a class="anchor" id="turn-{turn_id}">`), so the record is one URL for every page that names
    a turn. The raw JSON stays one click away behind *Export this page as JSON* (P15).
    """
    if not session_id or not turn_id:
        return None
    return f"/dashboard/sessions/{session_id}#turn-{turn_id}"


def _payloads(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the parsed `payload_json` to each span row, tolerating a §10.5 truncation stub."""
    parsed = []
    for row in rows:
        row = dict(row)
        try:
            row["payload"] = json.loads(row.pop("payload_json"))
        except (TypeError, ValueError):
            row["payload"] = {}
        parsed.append(row)
    return parsed


# --------------------------------------------------------------------------------------
# The filter bar (§11.6 pages 2 and 4)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Filters:
    """Page 2's filter bar, plus page 4's `intent` / `workflow` and the date range pages 5–8 use."""

    date_from: str | None = None
    date_to: str | None = None
    client_label: str | None = None
    persona: str | None = None
    auth_mode: str | None = None
    actor_role: str | None = None
    outcome: str | None = None
    has_error: bool = False
    min_duration_ms: int | None = None
    q: str | None = None
    intent: str | None = None
    workflow: str | None = None
    # pages 5–8 filter on their own dimension as well as the date range
    model: str | None = None
    purpose: str | None = None
    failover: bool = False
    strategy: str | None = None
    doc_id: str | None = None
    zero_evidence: bool = False
    tool: str | None = None
    errors_only: bool = False
    rule: str | None = None
    verdict: str | None = None
    user_response: str | None = None
    topic: str | None = None
    source_format: str | None = None
    run: str | None = None
    variant: str | None = None
    category: str | None = None
    failures_first: bool = False
    cold_only: bool = False
    page: int = 1

    @classmethod
    def from_request(cls, request: Request) -> Filters:
        params = request.query_params

        def text(name: str) -> str | None:
            value = (params.get(name) or "").strip()
            return value or None

        def flag(name: str) -> bool:
            return (params.get(name) or "").strip().lower() in {"1", "true", "on", "yes"}

        def number(name: str) -> int | None:
            value = text(name)
            try:
                return int(value) if value is not None else None
            except ValueError:
                return None

        return cls(
            date_from=text("date_from"),
            date_to=text("date_to"),
            client_label=text("client_label"),
            persona=text("persona"),
            auth_mode=text("auth_mode"),
            actor_role=text("actor_role"),
            outcome=text("outcome"),
            has_error=flag("has_error"),
            min_duration_ms=number("min_duration_ms"),
            q=text("q"),
            intent=text("intent"),
            workflow=text("workflow"),
            model=text("model"),
            purpose=text("purpose"),
            failover=flag("failover"),
            strategy=text("strategy"),
            doc_id=text("doc_id"),
            zero_evidence=flag("zero_evidence"),
            tool=text("tool"),
            errors_only=flag("errors_only"),
            rule=text("rule"),
            verdict=text("verdict"),
            user_response=text("user_response"),
            topic=text("topic"),
            source_format=text("source_format"),
            run=text("run"),
            variant=text("variant"),
            category=text("category"),
            failures_first=flag("failures_first"),
            cold_only=flag("cold_only"),
            page=max(1, number("page") or 1),
        )

    def as_dict(self) -> dict[str, Any]:
        """What the filter-bar partial re-renders its controls from."""
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    def query_string(self, **overrides: Any) -> str:
        """The current filter state as a query string — how the pager keeps the filters.

        Percent-encoded through `urlencode`, because this one string is *both* the pager's link
        and the Export JSON href: a free-text `q` carrying `&` would otherwise truncate the link
        at the ampersand and a `#` would send the rest to the fragment, so the JSON export would
        silently answer a different row set than the page displays.
        """
        state = {**self.as_dict(), **overrides}
        return urlencode(
            {
                key: "true" if value is True else value
                for key, value in state.items()
                if value not in (None, "", False) and not (key == "page" and value == 1)
            }
        )


def _span_time_clause(filters: Filters) -> tuple[str, list[Any]]:
    """The date range, applied to `spans.started_at` — pages 5–8 share it."""
    sql, params = "", []
    if filters.date_from and (bound := _day_bounds(filters.date_from, end=False)) is not None:
        sql += " AND started_at >= ?"
        params.append(bound)
    if filters.date_to and (bound := _day_bounds(filters.date_to, end=True)) is not None:
        sql += " AND started_at < ?"
        params.append(bound)
    return sql, params


# --------------------------------------------------------------------------------------
# View-models — §11.6's table, one model per page, nothing further
# --------------------------------------------------------------------------------------


class _View(BaseModel):
    """Unknown fields are a bug: the view-model is a contract, not a bag."""

    model_config = ConfigDict(extra="forbid")


class SessionRow(_View):
    """Page 2's row, and page 1's `latest_sessions[]`."""

    session_id: str
    started_at: int
    employee_id: str | None
    auth_mode: str
    actor_role: str
    client_label: str
    n_turns: int
    outcomes: list[str]
    total_ms: int
    tokens: int
    has_error: bool


class OverviewKpis(_View):
    sessions_24h: int
    sessions_total: int
    turns: int
    tool_calls: int
    guardrail_blocks: int
    escalations: int
    pending_confirmations: int
    error_rate: float
    #: The numerator of `error_rate` and the sample it was taken over, so the tile can show
    #: "11.1% (1 of 9 turns)" while the sample is small (**P14**) and so the figure and the count
    #: beside it provably come from one query (**P9**). Additive: no field was removed (P15).
    error_turns: int
    #: How many of those turns ended `answered`. The Traffic tile read **"5 / QUESTIONS ANSWERED"**
    #: over a figure that counts *turns* — the same 5 the error-rate tile three places right uses as
    #: the denominator of "1 of 5 turns", while `/dashboard/turns` listed two of the five as
    #: answered (UX W6, npo2-03 = dr-new-2). The tile names the count it holds and carries the
    #: answered figure as its sub-line, so the three surfaces agree by construction (**P9**).
    answered_turns: int
    #: How many turns had a recorded duration — the sample behind `p50_ms` / `p95_ms`. A percentile
    #: over fewer than five of them prints `n=` and not a number (**P14**).
    duration_n: int
    p50_ms: float | None
    p95_ms: float | None
    tokens_in: int
    tokens_out: int
    est_cost_usd: float
    spend_today_usd: float
    spend_7d_usd: float
    llm_calls_today: int
    llm_daily_call_cap: int


class HourBucket(_View):
    hour: str
    turns: int


class OverviewHealth(_View):
    #: Which model provider answered, and which model. Without it every cost tile reading `$0.00`
    #: looks like a broken meter rather than a recorded-script run (`dashboard-readability-14`).
    llm_provider: str
    llm_model: str
    #: The same sentence the demo panel prints, from `api.provider_label()` (UX W6, JX-R2). The raw
    #: `llm_provider` stays beside it: the label is for the page, the enum is for `/api/*` (P15).
    provider_label: str
    mcp_up: bool
    tool_count: int
    doc_count: int
    chunk_count: int
    store_backend: str
    git_sha: str
    uptime_ms: int
    rss_mb: float
    data_as_of: str


class OverviewView(_View):
    kpis: OverviewKpis
    turns_per_hour: list[HourBucket]
    latest_sessions: list[SessionRow]
    health: OverviewHealth


class SessionsView(_View):
    rows: list[SessionRow]
    page: int
    total: int


class SpanRow(_View):
    span_id: str
    parent_span_id: str | None
    seq: int
    kind: str
    name: str
    status: str
    duration_ms: int | None
    offset_ms: int
    payload: dict[str, Any]


class TurnRollups(_View):
    llm_calls: int | None
    tool_calls: int | None
    retrievals: int | None
    guardrail_hits: int | None
    #: The safety checks in the one unit every surface uses (UX W7, npo3-04 = dgc-r2-2): rules
    #: that applied to the turn and rules that passed, out of `api.SAFETY_RULES`, plus the spans
    #: that ran — computed by `api.safety_checks`, the helper the demo panel's sentence uses.
    rules_ran: int = 0
    rules_passed: int = 0
    checks_run: int = 0
    tokens_in: int | None
    tokens_out: int | None
    llm_ms: int | None
    retrieval_ms: int | None
    tool_ms: int | None
    store_ms: int | None


class TurnDetail(_View):
    """Page 3's `turns[]` entry — and the whole body of `GET /api/traces/turns/{turn_id}`.

    A superset of what P8 shipped, never a rename: `scripts/demo_task_*.sh` and §9.4's 202 fallback
    poll this route and read `outcome`, `citations[]` and `spans[]` from it.
    """

    turn_id: str
    session_id: str
    seq: int
    started_at: int
    ended_at: int | None
    duration_ms: int | None
    user_message: str
    final_answer: str | None
    answer_blocks: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    outcome: str | None
    stop_reason: str | None
    intent: str | None
    workflow: str | None
    resumed_count: int
    rollups: TurnRollups
    spans: list[SpanRow]
    dashboard_url: str


class SessionSummary(_View):
    session_id: str
    created_at: int
    last_activity_at: int
    employee_id: str | None
    auth_mode: str
    actor_role: str
    client_label: str
    eval_run_id: str | None
    app_version: str
    deploy_mode: str
    mcp_transport: str
    cold_start: bool
    n_turns: int


class SessionDetailView(_View):
    session: SessionSummary
    turns: list[TurnDetail]


class TurnRow(_View):
    turn_id: str
    session_id: str
    #: Where the row's question links: the turn on its session page, not the raw `/api/*` body.
    dashboard_url: str
    seq: int
    started_at: int
    user_message: str
    outcome: str | None
    intent: str | None
    workflow: str | None
    duration_ms: int | None
    llm_calls: int | None
    tool_calls: int | None
    retrievals: int | None
    guardrail_hits: int | None


class TurnsView(_View):
    rows: list[TurnRow]
    page: int
    total: int


class LlmRow(_View):
    span_id: str
    turn_id: str
    #: The turn's own record — `/dashboard/sessions/{session}#turn-{turn}` — never the raw JSON API (UX W7, nav-r2-1).
    dashboard_url: str | None = None
    provider: str | None
    model: str | None
    purpose: str | None
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int | None
    ttfb_ms: int | None
    #: What `ttfb_ms` on this row means: the first token on a streamed call, the whole round trip
    #: on one that did not stream (W2-E). Without it the column mixes two definitions.
    streamed: bool
    finish_reason: str | None
    retry_count: int
    cache_hit: bool
    limiter_wait_ms: int
    provider_failover: bool


class ModelRollup(_View):
    model: str
    calls: int
    tokens_in: int
    tokens_out: int
    est_cost_usd: float


class LlmView(_View):
    rows: list[LlmRow]
    by_model: list[ModelRollup]


class RetrievalRow(_View):
    span_id: str
    turn_id: str
    #: The turn's own record — `/dashboard/sessions/{session}#turn-{turn}` — never the raw JSON API (UX W7, nav-r2-1).
    dashboard_url: str | None = None
    query: str
    strategy: str | None
    k: int | None
    k_source: str | None
    max_dense_score: float | None
    n_hits: int
    docs: list[str]
    embed_ms: int | None
    search_ms: int | None


class DocumentHits(_View):
    doc_id: str
    doc_title: str
    hits: int


class ZeroEvidenceQuery(_View):
    span_id: str
    turn_id: str
    #: The turn's own record — `/dashboard/sessions/{session}#turn-{turn}` — never the raw JSON API (UX W7, nav-r2-1).
    dashboard_url: str | None = None
    query: str
    started_at: int


class RetrievalView(_View):
    rows: list[RetrievalRow]
    top_documents: list[DocumentHits]
    zero_evidence_queries: list[ZeroEvidenceQuery]


class ToolRollup(_View):
    tool_name: str
    calls: int
    #: `calls` again, under the name the rate's denominator is read by (**P14**). Kept as its own
    #: field so the page never has to know which column happens to be the sample.
    sample_n: int
    #: The numerator of `error_rate`, so the two provably agree (**P9**).
    errors: int
    #: A tool call that stopped at the confirmation gate is **not** an error: it is the flagship
    #: safety behaviour working. Counting it as one reported `create_mock_hr_ticket` at a 50.0%
    #: error rate (`dashboard-readability-13`). It has its own column now, and its own count.
    confirmation_pauses: int
    error_rate: float
    #: How many of those calls carried a duration — the sample behind `p50_ms` / `p95_ms`.
    duration_n: int
    p50_ms: float | None
    p95_ms: float | None
    last_called_at: int | None


class ToolCallRow(_View):
    span_id: str
    turn_id: str
    #: The turn's own record — `/dashboard/sessions/{session}#turn-{turn}` — never the raw JSON API (UX W7, nav-r2-1).
    dashboard_url: str | None = None
    tool_name: str
    arguments: dict[str, Any]
    #: The same arguments as one line a person can scan. Twelve rows used to read identically —
    #: `{"hits": [{"chunk_` — because the cell was JSON truncated mid-token
    #: (`dashboard-readability-19`). The dict above is untouched and is what the row's disclosure
    #: and Export JSON show (P15).
    arguments_summary: str
    result_preview: str
    #: The same for what came back: how many hits, from which documents, or what went wrong.
    result_summary: str
    is_error: bool
    #: `is_error` **and** the confirmation gate's own code: a write that stopped for a human is the
    #: safety design working, and page 7 says so rather than counting it as a failure.
    paused_for_confirmation: bool
    #: The three states the two booleans above describe, as the one word the row's pill shows:
    #: `ok`, `paused`, `error`. A classification, not a number — the figures stay unformatted.
    outcome_label: Literal["ok", "paused", "error"]
    error_code: str | None
    duration_ms: int | None
    actor_employee_id: str | None


class ToolsView(_View):
    by_tool: list[ToolRollup]
    recent: list[ToolCallRow]


class RuleCount(_View):
    rule_id: str
    rule_name: str
    verdict: str
    count: int


class InjectionHit(_View):
    span_id: str
    chunk_id: str
    doc_id: str | None
    matched_pattern: str | None


class ConfirmationRow(_View):
    turn_id: str
    #: The turn's own record — `/dashboard/sessions/{session}#turn-{turn}` — never the raw JSON API (UX W7, nav-r2-1).
    dashboard_url: str | None = None
    action: str
    human_summary: str
    user_response: str
    created_at: int
    used_at: int | None


class MockWriteRow(_View):
    id: str
    kind: str
    employee_id: str
    created_at: int
    turn_id: str | None
    #: The turn's own record — `/dashboard/sessions/{session}#turn-{turn}` — never the raw JSON API (UX W7, nav-r2-1).
    dashboard_url: str | None = None
    payload: dict[str, Any]
    #: The payload as one scannable line, through the same `summarise_arguments()` the Tools page
    #: uses. The sandbox printed the raw body clipped mid-token — `{"employee_id": "E1042",
    #: "queue": "hr-timeoff", "summary": …` — on the page whose whole job is to show a grader what
    #: was written (UX W6, JX-R5). The dict itself is one disclosure below and in `/api/*` (P15).
    payload_summary: str


class SafetyView(_View):
    by_rule: list[RuleCount]
    injection_hits: list[InjectionHit]
    confirmations: list[ConfirmationRow]
    mock_writes: list[MockWriteRow]


class HandshakeRow(_View):
    span_id: str
    turn_id: str
    #: The turn's own record — `/dashboard/sessions/{session}#turn-{turn}` — never the raw JSON API (UX W7, nav-r2-1).
    dashboard_url: str | None = None
    discovered_at: int | None
    handshake_ms: int | None
    tool_count: int
    cached: bool
    catalog_sha: str | None


class McpDiscoveryView(_View):
    server: ServerInfo | None
    transport: str
    url: str | None
    protocol_version: str | None
    handshake_ms: int | None
    discovered_at: int | None
    tools: list[DiscoveredTool]
    handshake_history: list[HandshakeRow]
    connected: bool
    last_error: str | None


class CorpusDocument(_View):
    doc_id: str
    doc_title: str
    source_format: str
    topics: list[str]
    section_count: int
    chunk_count: int
    #: What the index counted. `estimated_pages` is derived from it and is a fraction — "PAGES 3.8"
    #: for a markdown file with no pages at all (`numbers-precision-overflow-16`) — so the page
    #: shows the count and keeps the estimate in the JSON.
    word_count: int
    estimated_pages: float


class CorpusView(_View):
    documents: list[CorpusDocument]
    topics: list[str]
    formats: list[str]


class CorpusDocumentDetail(CorpusDocument):
    effective_date: str
    version: str
    full_text: str


class CorpusChunk(_View):
    chunk_id: str
    heading_path: str
    char_start: int
    char_end: int
    n_chars: int
    text: str


class CorpusDocumentView(_View):
    document: CorpusDocumentDetail
    chunks: list[CorpusChunk]


class CorpusChunkView(_View):
    chunk_id: str
    doc_id: str
    doc_title: str
    heading_path: str
    section: str
    char_start: int
    char_end: int
    n_chars: int
    text: str
    snippet: str


class EvalMetrics(BaseModel):
    """Page 11's metric block (§11.6), typed so a missing figure is `null`, never a zero.

    `extra="ignore"` on purpose: a run file written by an earlier or later `evaluation/runner.py`
    still renders, and a metric this block does not name is simply not displayed.
    """

    model_config = ConfigDict(extra="ignore")

    judged: bool = False
    # the four judged aggregates — `baseline` only (§13.9)
    groundedness_mean: float | None = None
    citation_accuracy_mean: float | None = None
    partial_match_mean: float | None = None
    clarification_accuracy: float | None = None
    # the five deterministic aggregates — non-null on every variant
    cit_resolve_mean: float | None = None
    blocks_dropped_by_g2: int | None = None
    tool_selection_accuracy: float | None = None
    arg_correctness_rate: float | None = None
    strict_pass_rate: float | None = None
    # the rest of the block, in §11.6's order
    escalation_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    escalation_n_excluded: int = 0
    over_refusal_rate: float | None = None
    over_refusal_n: int = 0
    missed_refusal_rate: float | None = None
    missed_refusal_n: int = 0
    action_safety_pass_rate: float | None = None
    workflow_completion_by_workflow: dict[str, float] = Field(default_factory=dict)
    recommendation_labeled_rate: float | None = None
    router_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    catalog_reopened_rate: float | None = None
    n_scored: dict[str, int] = Field(default_factory=dict)
    #: The two judge-validation figures of §13.7 — the blind `seed_1729_8` subset and the disclosed
    #: `judge_lowest_8` hard-case subset — each with its own `n` and the subset it was computed
    #: over. They are never merged: one is blind, the other is selected by judge score.
    judge_agreement_rate: float | None = None
    judge_agreement_n: int = 0
    judge_agreement_subset: str | None = None
    judge_agreement_rate_hard: float | None = None
    judge_agreement_n_hard: int = 0
    judge_agreement_subset_hard: str | None = None
    est_cost_usd: float | None = None


class EvalRunRow(_View):
    run_id: str
    label: str
    #: What `eval_runs.label` actually holds (UX W8, W7 review). `label` above is the one spelling
    #: the page uses everywhere a run is named; this is the stored string, which `/api/eval/runs`
    #: published until UX W7 rewrote the field in place — and **P15** is that the raw value stays
    #: reachable rather than being replaced by the rendering.
    stored_label: str | None = None
    variant: str
    target: str
    git_sha: str
    created_at: int
    n_items: int
    headline: dict[str, int | float | None]
    #: Each headline rate's sample, by the metric's own name, where the run reports one (UX W9,
    #: npo5-05): the list page prints the `n` with any rate under P14's threshold, as the run page
    #: one click away already does.
    n_scored: dict[str, int] = Field(default_factory=dict)
    judged: bool
    judge_model: str | None
    duration_s: float | None
    est_cost_usd: float | None


class EvalRunsView(_View):
    runs: list[EvalRunRow]


class EvalItemRow(_View):
    item_id: str
    category: str
    question: str | None
    gold: str | None
    answer: str | None
    scores: dict[str, Any]
    verdicts: dict[str, Any]
    latency_ms: int | None
    cold: bool
    passed: bool
    run_phase: str
    session_id: str | None
    turn_id: str | None
    trace_url: str | None
    #: Whether this run's turn is in **this** store. Eval runs are imported from committed fixtures
    #: (`core/archive.py`), so their `session_id` and `turn_id` name rows that were never written
    #: here: one run page offered 26 `/api/traces/turns/<32-hex>` chips and 26 session pills, 52
    #: links, every one of them a 404 (UX W6, nav-reaudit-3 / **P5**). The ids stay on the page and
    #: in Export JSON — they are the record (P15) — they simply stop being offered as links.
    trace_present: bool


class LatencyBlock(_View):
    p50: float | None
    p90: float | None
    p95: float | None
    p99: float | None
    n_warm: int
    n_cold: int
    cold_p50: float | None
    cold_p95: float | None
    by_kind: dict[str, int]


class RssPoint(_View):
    turn_id: str
    rss_mb: float


class RunVerdict(_View):
    """The sentence a run page never had: how many items passed, and against what (`dashboard-readability-21`).

    Counted from the scored items of this very run — the same rows the Items tab lists — so the
    headline and the table cannot disagree (**P9**). The delta is against the previous run of the
    *same variant*, because a baseline and an ablation arm are not comparable numbers.
    """

    items_scored: int
    items_passed: int
    pass_rate: float | None
    #: How many items each category contributes — the dataset legend the page had no room to state.
    by_category: dict[str, int]
    previous_run_id: str | None = None
    previous_created_at: int | None = None
    previous_pass_rate: float | None = None


class EvalRunDetailView(_View):
    run: EvalRunRow
    metrics: EvalMetrics
    verdict: RunVerdict
    items: list[EvalItemRow]
    latency: LatencyBlock
    rss_series: list[RssPoint]


class VariantMetrics(_View):
    variant: str
    run_id: str
    metrics: EvalMetrics


class Flip(_View):
    item_id: str
    variant: str
    baseline_passed: bool
    variant_passed: bool


class ChunkSizePoint(_View):
    chunk_chars: int
    doc_recall_mean: float


class EvalCompareView(_View):
    variants: list[VariantMetrics]
    flips: list[Flip]
    chunk_size: list[ChunkSizePoint]


# --------------------------------------------------------------------------------------
# Page 1 — `/dashboard` · `/api/traces/overview`
# --------------------------------------------------------------------------------------

SESSION_SELECT = """
SELECT s.id AS session_id, s.created_at AS started_at, s.employee_id, s.auth_mode, s.actor_role,
       s.client_label,
       COUNT(t.id) AS n_turns,
       COALESCE(SUM(t.duration_ms), 0) AS total_ms,
       COALESCE(SUM(t.total_tokens_in), 0) + COALESCE(SUM(t.total_tokens_out), 0) AS tokens,
       MAX(CASE WHEN t.outcome = 'error' THEN 1 ELSE 0 END) AS has_error,
       GROUP_CONCAT(t.outcome) AS outcomes
FROM sessions s LEFT JOIN turns t ON t.session_id = s.id
"""


def _session_filters(filters: Filters) -> tuple[str, list[Any], str, list[Any]]:
    """The `WHERE` over `sessions` and the `HAVING` over the aggregates, kept apart."""
    where, params = "", []
    if filters.date_from and (bound := _day_bounds(filters.date_from, end=False)) is not None:
        where += " AND s.created_at >= ?"
        params.append(bound)
    if filters.date_to and (bound := _day_bounds(filters.date_to, end=True)) is not None:
        where += " AND s.created_at < ?"
        params.append(bound)
    for column, value in (
        ("s.client_label", filters.client_label),
        ("s.employee_id", filters.persona),
        ("s.auth_mode", filters.auth_mode),
        ("s.actor_role", filters.actor_role),
    ):
        if value:
            where += f" AND {column} = ?"
            params.append(value)
    if filters.outcome:
        where += " AND EXISTS (SELECT 1 FROM turns f WHERE f.session_id = s.id AND f.outcome = ?)"
        params.append(filters.outcome)
    if filters.q:
        where += " AND EXISTS (SELECT 1 FROM turns f WHERE f.session_id = s.id AND f.user_message LIKE ?)"
        params.append(f"%{filters.q}%")

    having, having_params = "", []
    if filters.has_error:
        having += " AND has_error = 1"
    if filters.min_duration_ms is not None:
        having += " AND total_ms >= ?"
        having_params.append(filters.min_duration_ms)
    return where, params, having, having_params


def _session_rows(store: Store, filters: Filters, *, limit: int, offset: int = 0) -> list[SessionRow]:
    where, params, having, having_params = _session_filters(filters)
    sql = f"{SESSION_SELECT} WHERE 1=1{where} GROUP BY s.id"
    if having:
        sql += f" HAVING 1=1{having}"
    sql += " ORDER BY s.created_at DESC LIMIT ? OFFSET ?"
    rows = store.execute(sql, [*params, *having_params, limit, offset]).dicts()
    return [
        SessionRow(
            session_id=row["session_id"],
            started_at=int(row["started_at"]),
            employee_id=row["employee_id"],
            auth_mode=row["auth_mode"],
            actor_role=row["actor_role"],
            client_label=row["client_label"],
            n_turns=int(row["n_turns"] or 0),
            outcomes=sorted({part for part in (row["outcomes"] or "").split(",") if part}),
            total_ms=int(row["total_ms"] or 0),
            tokens=int(row["tokens"] or 0),
            has_error=bool(row["has_error"]),
        )
        for row in rows
    ]


def _session_total(store: Store, filters: Filters) -> int:
    where, params, having, having_params = _session_filters(filters)
    inner = f"{SESSION_SELECT} WHERE 1=1{where} GROUP BY s.id"
    if having:
        inner += f" HAVING 1=1{having}"
    return int(store.execute(f"SELECT COUNT(*) AS n FROM ({inner})", [*params, *having_params]).scalar() or 0)


def _scalar(store: Store, sql: str, params: Sequence[Any] = ()) -> int:
    return int(store.execute(sql, params).scalar() or 0)


def _llm_cost_since(store: Store, since: int) -> float:
    value = store.execute(
        "SELECT COALESCE(SUM(json_extract(payload_json, '$.cost_usd_estimate')), 0) AS spend "
        "FROM spans WHERE kind = 'llm_call' AND started_at >= ?",
        (since,),
    ).scalar()
    return round(float(value or 0.0), 6)


def _turns_per_hour(store: Store) -> list[HourBucket]:
    """The last 24 hourly buckets, zero-filled so the sparkline has no gaps."""
    now = datetime.now(tz=UTC).replace(minute=0, second=0, microsecond=0)
    first = now - timedelta(hours=SPARKLINE_HOURS - 1)
    since = int(first.timestamp() * 1_000_000)
    counted: Counter[str] = Counter()
    for row in store.execute("SELECT started_at FROM turns WHERE started_at >= ?", (since,)).dicts():
        moment = datetime.fromtimestamp(int(row["started_at"]) / 1_000_000, tz=UTC)
        counted[moment.strftime("%Y-%m-%dT%H:00Z")] += 1
    buckets = []
    for offset in range(SPARKLINE_HOURS):
        label = (first + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:00Z")
        buckets.append(HourBucket(hour=label, turns=counted.get(label, 0)))
    return buckets


async def build_overview(request: Request) -> OverviewView:
    store = _store(request)
    settings = _settings(request)
    health = await api.health_payload(request.app)

    durations = [row["duration_ms"] for row in store.execute("SELECT duration_ms FROM turns").dicts()]
    turns = _scalar(store, "SELECT COUNT(*) AS n FROM turns")
    errors = _scalar(store, "SELECT COUNT(*) AS n FROM turns WHERE outcome = 'error'")
    tokens = (
        store.execute(
            "SELECT COALESCE(SUM(total_tokens_in), 0) AS tin, COALESCE(SUM(total_tokens_out), 0) AS tout FROM turns"
        ).one()
        or {}
    )
    kpis = OverviewKpis(
        sessions_24h=_scalar(
            store, "SELECT COUNT(*) AS n FROM sessions WHERE created_at >= ?", (now_micros() - 86_400_000_000,)
        ),
        sessions_total=_scalar(store, "SELECT COUNT(*) AS n FROM sessions"),
        turns=turns,
        tool_calls=_scalar(store, "SELECT COUNT(*) AS n FROM spans WHERE kind = 'tool_call'"),
        # §11.6 carry-forward: the KPI maps from `turns.guardrail_hits` — the rollup `core/trace.py`
        # already counted (a guardrail span whose verdict is not `allow`), never a re-count here.
        guardrail_blocks=_scalar(store, "SELECT COALESCE(SUM(guardrail_hits), 0) AS n FROM turns"),
        escalations=_scalar(store, "SELECT COUNT(*) AS n FROM turns WHERE outcome = 'escalated'"),
        pending_confirmations=_scalar(store, "SELECT COUNT(*) AS n FROM turns WHERE outcome = 'awaiting_confirmation'"),
        error_rate=round(errors / turns, 4) if turns else 0.0,
        error_turns=errors,
        answered_turns=_scalar(store, "SELECT COUNT(*) AS n FROM turns WHERE outcome = 'answered'"),
        duration_n=sum(1 for duration in durations if duration is not None),
        p50_ms=percentile(durations, 0.50),
        p95_ms=percentile(durations, 0.95),
        tokens_in=int(tokens.get("tin") or 0),
        tokens_out=int(tokens.get("tout") or 0),
        est_cost_usd=_llm_cost_since(store, 0),
        spend_today_usd=_llm_cost_since(store, utc_day_start()),
        spend_7d_usd=_llm_cost_since(store, utc_day_start(days_ago=6)),
        llm_calls_today=int(health["llm"]["agent"]["calls_today"]),
        llm_daily_call_cap=int(health["llm"]["agent"]["daily_call_cap"]),
    )
    index = health["index"]
    app_block = health["app"]
    return OverviewView(
        kpis=kpis,
        turns_per_hour=_turns_per_hour(store),
        latest_sessions=_session_rows(store, Filters(), limit=10),
        health=OverviewHealth(
            llm_provider=str(health["llm"]["agent"]["provider"]),
            llm_model=str(health["llm"]["agent"]["model"]),
            provider_label=api.provider_label(str(health["llm"]["agent"]["provider"])),
            mcp_up=bool(health["mcp"]["connected"]),
            tool_count=int(health["mcp"]["tool_count"]),
            doc_count=int(index.get("doc_count") or 0),
            chunk_count=int(index.get("chunk_count") or 0),
            store_backend=str(health["trace_store"].get("backend") or settings.persist_backend),
            git_sha=str(app_block["git_sha"]),
            uptime_ms=int(app_block["uptime_ms"]),
            rss_mb=float(app_block["rss_mb"]),
            data_as_of=str(health["data"]["as_of"]),
        ),
    )


# --------------------------------------------------------------------------------------
# Pages 2 and 3 — sessions
# --------------------------------------------------------------------------------------


def build_sessions(request: Request, filters: Filters) -> SessionsView:
    store = _store(request)
    offset = (filters.page - 1) * PAGE_SIZE
    return SessionsView(
        rows=_session_rows(store, filters, limit=PAGE_SIZE, offset=offset),
        page=filters.page,
        total=_session_total(store, filters),
    )


TURN_COLUMNS = (
    "id, session_id, seq, started_at, ended_at, duration_ms, user_message, final_answer, "
    "answer_blocks_json, citations_json, outcome, stop_reason, intent, workflow, resumed_count, "
    "llm_calls, tool_calls, retrievals, guardrail_hits, total_tokens_in, total_tokens_out, "
    "llm_ms, retrieval_ms, tool_ms, store_ms"
)


def _turn_detail(store: Store, row: dict[str, Any]) -> TurnDetail:
    started_at = int(row["started_at"])
    spans = _payloads(
        store.execute(
            "SELECT id, parent_span_id, seq, kind, name, started_at, duration_ms, status, payload_json "
            "FROM spans WHERE turn_id = ? ORDER BY seq",
            (row["id"],),
        ).dicts()
    )
    # One call for the one pair it returns (UX W8, W7 review). `api.safety_checks` walks every
    # span of the turn; calling it twice to take `[0]` and then `[1]` walked them twice.
    rules_passed, rules_ran = api.safety_checks(spans)
    return TurnDetail(
        turn_id=row["id"],
        session_id=row["session_id"],
        seq=int(row["seq"]),
        started_at=started_at,
        ended_at=row["ended_at"],
        duration_ms=row["duration_ms"],
        user_message=row["user_message"],
        final_answer=row["final_answer"],
        answer_blocks=json.loads(row["answer_blocks_json"] or "[]"),
        citations=json.loads(row["citations_json"] or "[]"),
        outcome=row["outcome"],
        stop_reason=row["stop_reason"],
        intent=row["intent"],
        workflow=row["workflow"],
        resumed_count=int(row["resumed_count"] or 0),
        rollups=TurnRollups(
            llm_calls=row["llm_calls"],
            tool_calls=row["tool_calls"],
            retrievals=row["retrievals"],
            guardrail_hits=row["guardrail_hits"],
            rules_passed=rules_passed,
            rules_ran=rules_ran,
            checks_run=sum(1 for span in spans if span["kind"] == "guardrail"),
            tokens_in=row["total_tokens_in"],
            tokens_out=row["total_tokens_out"],
            llm_ms=row["llm_ms"],
            retrieval_ms=row["retrieval_ms"],
            tool_ms=row["tool_ms"],
            store_ms=row["store_ms"],
        ),
        spans=[
            SpanRow(
                span_id=span["id"],
                parent_span_id=span["parent_span_id"],
                seq=int(span["seq"]),
                kind=span["kind"],
                name=span["name"],
                status=span["status"],
                duration_ms=span["duration_ms"],
                offset_ms=max(0, (int(span["started_at"]) - started_at) // 1000),
                payload=span["payload"],
            )
            for span in spans
        ],
        dashboard_url=f"/dashboard/sessions/{row['session_id']}#turn-{row['seq']}",
    )


def build_session_detail(request: Request, session_id: str) -> SessionDetailView:
    store = _store(request)
    session = store.execute(
        "SELECT id, created_at, last_activity_at, employee_id, auth_mode, actor_role, client_label, "
        "eval_run_id, app_version, deploy_mode, mcp_transport, cold_start FROM sessions WHERE id = ?",
        (session_id,),
    ).one()
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_SESSION", "session_id": session_id})
    rows = store.execute(f"SELECT {TURN_COLUMNS} FROM turns WHERE session_id = ? ORDER BY seq", (session_id,)).dicts()
    turns = [_turn_detail(store, row) for row in rows]
    return SessionDetailView(
        session=SessionSummary(
            session_id=session["id"],
            created_at=int(session["created_at"]),
            last_activity_at=int(session["last_activity_at"]),
            employee_id=session["employee_id"],
            auth_mode=session["auth_mode"],
            actor_role=session["actor_role"],
            client_label=session["client_label"],
            eval_run_id=session["eval_run_id"],
            app_version=session["app_version"],
            deploy_mode=session["deploy_mode"],
            mcp_transport=session["mcp_transport"],
            cold_start=bool(session["cold_start"]),
            n_turns=len(turns),
        ),
        turns=turns,
    )


def build_turn(request: Request, turn_id: str) -> TurnDetail:
    store = _store(request)
    row = store.execute(f"SELECT {TURN_COLUMNS} FROM turns WHERE id = ?", (turn_id,)).one()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_TURN", "turn_id": turn_id})
    return _turn_detail(store, row)


# --------------------------------------------------------------------------------------
# Page 4 — turns
# --------------------------------------------------------------------------------------


def _turn_filters(filters: Filters) -> tuple[str, list[Any]]:
    where, params = "", []
    if filters.date_from and (bound := _day_bounds(filters.date_from, end=False)) is not None:
        where += " AND t.started_at >= ?"
        params.append(bound)
    if filters.date_to and (bound := _day_bounds(filters.date_to, end=True)) is not None:
        where += " AND t.started_at < ?"
        params.append(bound)
    for column, value in (
        ("s.client_label", filters.client_label),
        ("s.employee_id", filters.persona),
        ("s.auth_mode", filters.auth_mode),
        ("s.actor_role", filters.actor_role),
        ("t.outcome", filters.outcome),
        # The two free-text enum filters, normalised back to the token the column stores: the
        # placeholders show the painted label and the comparison is exact (DR3-04 = I13).
        ("t.intent", enum_token(filters.intent or "")),
        ("t.workflow", enum_token(filters.workflow or "")),
    ):
        if value:
            where += f" AND {column} = ?"
            params.append(value)
    if filters.has_error:
        where += " AND t.outcome = 'error'"
    if filters.min_duration_ms is not None:
        where += " AND t.duration_ms >= ?"
        params.append(filters.min_duration_ms)
    if filters.q:
        where += " AND t.user_message LIKE ?"
        params.append(f"%{filters.q}%")
    return where, params


def build_turns(request: Request, filters: Filters) -> TurnsView:
    store = _store(request)
    where, params = _turn_filters(filters)
    join = "FROM turns t JOIN sessions s ON s.id = t.session_id WHERE 1=1" + where
    total = int(store.execute(f"SELECT COUNT(*) AS n {join}", params).scalar() or 0)
    rows = store.execute(
        "SELECT t.id, t.session_id, t.seq, t.started_at, t.user_message, t.outcome, t.intent, t.workflow, "
        f"t.duration_ms, t.llm_calls, t.tool_calls, t.retrievals, t.guardrail_hits {join} "
        "ORDER BY t.started_at DESC LIMIT ? OFFSET ?",
        [*params, PAGE_SIZE, (filters.page - 1) * PAGE_SIZE],
    ).dicts()
    return TurnsView(
        rows=[
            TurnRow(
                turn_id=row["id"],
                session_id=row["session_id"],
                dashboard_url=f"/dashboard/sessions/{row['session_id']}#turn-{row['seq']}",
                seq=int(row["seq"]),
                started_at=int(row["started_at"]),
                user_message=row["user_message"],
                outcome=row["outcome"],
                intent=row["intent"],
                workflow=row["workflow"],
                duration_ms=row["duration_ms"],
                llm_calls=row["llm_calls"],
                tool_calls=row["tool_calls"],
                retrievals=row["retrievals"],
                guardrail_hits=row["guardrail_hits"],
            )
            for row in rows
        ],
        page=filters.page,
        total=total,
    )


# --------------------------------------------------------------------------------------
# Page 5 — LLM calls
# --------------------------------------------------------------------------------------


def build_llm(request: Request, filters: Filters) -> LlmView:
    store = _store(request)
    time_sql, time_params = _span_time_clause(filters)
    where, params = time_sql, list(time_params)
    if filters.model:
        where += " AND json_extract(payload_json, '$.model') = ?"
        params.append(filters.model)
    if filters.purpose:
        where += " AND json_extract(payload_json, '$.purpose') = ?"
        params.append(filters.purpose)
    if filters.failover:
        where += " AND json_extract(payload_json, '$.provider_failover') = 1"

    rows = _payloads(
        store.execute(
            "SELECT id, turn_id, session_id, duration_ms, payload_json FROM spans "
            f"WHERE kind = 'llm_call'{where} ORDER BY started_at DESC LIMIT ?",
            [*params, ROW_LIMIT],
        ).dicts()
    )
    by_model = store.execute(
        "SELECT json_extract(payload_json, '$.model') AS model, COUNT(*) AS calls, "
        "COALESCE(SUM(json_extract(payload_json, '$.prompt_tokens')), 0) AS tokens_in, "
        "COALESCE(SUM(json_extract(payload_json, '$.completion_tokens')), 0) AS tokens_out, "
        "COALESCE(SUM(json_extract(payload_json, '$.cost_usd_estimate')), 0) AS est_cost_usd "
        f"FROM spans WHERE kind = 'llm_call'{where} GROUP BY model ORDER BY calls DESC",
        params,
    ).dicts()
    return LlmView(
        rows=[
            LlmRow(
                span_id=row["id"],
                turn_id=row["turn_id"],
                dashboard_url=turn_record_url(row.get("session_id"), row["turn_id"]),
                provider=row["payload"].get("provider"),
                model=row["payload"].get("model"),
                purpose=row["payload"].get("purpose"),
                prompt_tokens=int(row["payload"].get("prompt_tokens") or 0),
                completion_tokens=int(row["payload"].get("completion_tokens") or 0),
                duration_ms=row["duration_ms"],
                ttfb_ms=row["payload"].get("ttfb_ms"),
                streamed=bool(row["payload"].get("streamed")),
                finish_reason=row["payload"].get("finish_reason"),
                retry_count=int(row["payload"].get("retry_count") or 0),
                cache_hit=bool(row["payload"].get("cache_hit")),
                limiter_wait_ms=int(row["payload"].get("limiter_wait_ms") or 0),
                provider_failover=bool(row["payload"].get("provider_failover")),
            )
            for row in rows
        ],
        by_model=[
            ModelRollup(
                model=row["model"] or "unknown",
                calls=int(row["calls"]),
                tokens_in=int(row["tokens_in"] or 0),
                tokens_out=int(row["tokens_out"] or 0),
                est_cost_usd=round(float(row["est_cost_usd"] or 0.0), 6),
            )
            for row in by_model
        ],
    )


# --------------------------------------------------------------------------------------
# Page 6 — retrieval
# --------------------------------------------------------------------------------------


def build_retrieval(request: Request, filters: Filters) -> RetrievalView:
    store = _store(request)
    time_sql, time_params = _span_time_clause(filters)
    where, params = time_sql, list(time_params)
    if filters.strategy:
        where += " AND json_extract(payload_json, '$.strategy') = ?"
        params.append(filters.strategy)

    spans = _payloads(
        store.execute(
            "SELECT id, turn_id, session_id, started_at, payload_json FROM spans "
            f"WHERE kind = 'retrieval'{where} ORDER BY started_at DESC LIMIT ?",
            [*params, ROW_LIMIT],
        ).dicts()
    )
    titles: dict[str, str] = {}
    hits: Counter[str] = Counter()
    rows: list[RetrievalRow] = []
    zero: list[ZeroEvidenceQuery] = []
    for span in spans:
        payload = span["payload"]
        chunks = payload.get("chunks") or []
        docs = sorted({chunk.get("doc_id", "") for chunk in chunks if chunk.get("doc_id")})
        for chunk in chunks:
            doc_id = chunk.get("doc_id")
            if doc_id:
                hits[doc_id] += 1
                titles.setdefault(doc_id, chunk.get("doc_title") or doc_id)
        if filters.doc_id and filters.doc_id not in docs:
            continue
        if not chunks:
            zero.append(
                ZeroEvidenceQuery(
                    span_id=span["id"],
                    turn_id=span["turn_id"],
                    dashboard_url=turn_record_url(span.get("session_id"), span["turn_id"]),
                    query=payload.get("query") or "",
                    started_at=int(span["started_at"]),
                )
            )
        if filters.zero_evidence and chunks:
            continue
        rows.append(
            RetrievalRow(
                span_id=span["id"],
                turn_id=span["turn_id"],
                dashboard_url=turn_record_url(span.get("session_id"), span["turn_id"]),
                query=payload.get("query") or "",
                strategy=payload.get("strategy"),
                k=payload.get("k"),
                k_source=payload.get("k_source"),
                max_dense_score=payload.get("max_dense_score"),
                n_hits=len(chunks),
                docs=docs,
                embed_ms=payload.get("embed_ms"),
                search_ms=payload.get("search_ms"),
            )
        )
    top = [
        DocumentHits(doc_id=doc_id, doc_title=titles.get(doc_id, doc_id), hits=count)
        for doc_id, count in hits.most_common(15)
    ]
    return RetrievalView(rows=rows, top_documents=top, zero_evidence_queries=zero)


# --------------------------------------------------------------------------------------
# Page 7 — tools
# --------------------------------------------------------------------------------------

#: How the rollup names a tool in SQL. `spans.name` is the tool name for a `tool_call` span and is
#: `NOT NULL` (§10.1), so this matches the Python fallback `recent` uses and can never group on NULL.
TOOL_NAME_SQL = "COALESCE(json_extract(payload_json, '$.tool_name'), name, 'unknown')"

#: The confirmation gate refuses an unconfirmed write with this code (§8.6), and the span records
#: it as an error because that is what the tool server returned. It is the designed pause, not a
#: failure, and page 7 counts and labels it as one (`dashboard-readability-13`).
CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
IS_A_PAUSE = f"json_extract(payload_json, '$.error_code') = '{CONFIRMATION_REQUIRED}'"
NOT_A_PAUSE = f"COALESCE(json_extract(payload_json, '$.error_code'), '') <> '{CONFIRMATION_REQUIRED}'"


#: How much of a one-line summary a table cell is given before it is elided.
SUMMARY_CHARS = 90


def summarise_arguments(arguments: Mapping[str, Any]) -> str:
    """The arguments a tool was called with, as one scannable line.

    `employee_id=E1042 · query="paid time off accrual"` rather than 906px of pretty-printed JSON
    clipped mid-token (`dashboard-readability-19`). The dict itself is on the row's disclosure and
    in `/api/*`, unchanged: this is a *summary*, and the record is never destroyed (P15).
    """
    if not arguments:
        return "no arguments"
    return _f_compact(" · ".join(_argument_parts(arguments)), SUMMARY_CHARS)


def _argument_parts(arguments: Mapping[str, Any]) -> list[str]:
    """`key=value` for each argument, flattening one level of nesting.

    `check_policy_compliance` takes a `parameters` object, and dumping it whole printed
    `parameters={"start_date": …` — the raw JSON clipped mid-token that the summariser exists to
    replace, in the summariser's own output (UX W6, JX-R5). Its fields are arguments like any
    other, so they are rendered like any other.
    """
    parts: list[str] = []
    for key, value in arguments.items():
        if isinstance(value, Mapping):
            parts.extend(_argument_parts(value))
            continue
        # The values side, humanised like the keys (UX W7, JX2-02 = jargon-and-exposure-23): a
        # queue slug is the team's name, an enum is its label, a date is the dashboard's date.
        if isinstance(value, str):
            rendered = _argument_value(key, value)
        elif isinstance(value, bool):
            rendered = "yes" if value else "no"
        elif isinstance(value, (int, float)):
            rendered = _f_num(value)
        elif isinstance(value, (list, tuple)):
            rendered = _f_counted(len(value), "value")
        else:
            rendered = _f_compact(value, 30)
        parts.append(f"{_f_enum_label(key)}: {rendered}")
    return parts


#: Argument keys whose string value is a stored enum or a routing key, not free text.
_ENUM_ARGUMENTS = frozenset({"scenario", "topic", "kind", "priority", "strategy", "source_format", "category"})
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:Z|[+-]00:?00)$")


def _keyed_value(key: str, value: str) -> str | None:
    """A value whose **key** decides what it is called — or `None` if the key says nothing.

    One helper, read by the arguments side and the results side of the same table row (UX W8 fix
    round, JX3-03 = re-audit #3 I9). `_argument_value` translated `queue` and `_scalar_value` —
    which took no key at all — could not, so `/dashboard/tools` printed ARGUMENTS
    `queue: HR Time Off team` and RESULT `queue: hr-timeoff` in one row, on all six tools screens.
    A routing slug is never what a human-facing cell says (`core/queues.py`), whichever side of the
    call it came back on.
    """
    return queue_label(value) if key == "queue" else None


def _argument_value(key: str, value: str) -> str:
    """One string argument as a reader reads it."""
    named = _keyed_value(key, value)
    if named is not None:
        return named
    if key in _ENUM_ARGUMENTS:
        return _f_enum_label(value)
    dated = _human_moment(value)
    if dated is not None:
        return dated
    return f'"{value}"' if len(value) <= 40 else f'"{value[:39]}…"'


def _human_moment(value: str) -> str | None:
    """An ISO date or instant in the dashboard's own two shapes — or `None` for anything else.

    The Tools page printed `as of: 2026-09-01` and `computed at: 2026-09-15T18:21:44Z` beside a
    CREATED column reading `2026-09-15 18:22:00 UTC`, a fourth date shape on a page that already
    had three (UX W7, M33 = npo3-09).
    """
    if _ISO_DATE.match(value):
        return api.human_date(value)
    match = _ISO_DATETIME.match(value)
    if match:
        return f"{match.group(1)} {match.group(2)} UTC"
    return None


def _scalar_value(key: str, value: str | int | float | bool) -> str:
    """One field of a tool result, as a reader reads it: a formatted number or a named enum.

    It takes the field's `key` (UX W8 fix round, JX3-03): the name of a field is half of what its
    value means, and a queue slug that reaches this function without one is printed as the slug.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return _f_num(value)
    named = _keyed_value(key, str(value))
    if named is not None:
        return named
    dated = _human_moment(str(value))
    return dated if dated is not None else _f_enum_label(value)


def summarise_result(structured: Any, result_json: Any, *, error_code: str | None = None) -> str:
    """What came back, as one scannable line.

    A retrieval-shaped result says how much it found and where from; a write says what it made; a
    refusal says which refusal. Anything unrecognised falls back to a capped preview, because a
    summary that guesses is worse than the value itself.
    """
    if error_code == CONFIRMATION_REQUIRED:
        return "paused for confirmation"
    if error_code:
        return f"refused · {error_code}"
    payload = structured
    if payload is None and isinstance(result_json, str) and result_json:
        try:
            payload = json.loads(result_json)
        except ValueError:
            return _f_compact(result_json, SUMMARY_CHARS)
    if isinstance(payload, dict):
        hits = payload.get("hits")
        if isinstance(hits, list):
            documents = sorted({str(hit.get("doc_id")) for hit in hits if isinstance(hit, dict) and hit.get("doc_id")})
            found = _f_counted(len(hits), "hit")
            return _f_compact(f"{found} · {', '.join(documents)}" if documents else found, SUMMARY_CHARS)
        # `verdict=conditional` is a field name, an equals sign and a raw enum on a page that has
        # spent two waves removing all three (UX W6, JX-R5 / JX-R4). The same facts, said.
        scalars = [
            f"{_f_enum_label(key)}: {_scalar_value(key, value)}"
            for key, value in payload.items()
            if isinstance(value, (str, int, float, bool))
        ]
        if scalars:
            return _f_compact(" · ".join(scalars), SUMMARY_CHARS)
    if payload is None:
        return "—"
    return _f_compact(payload, SUMMARY_CHARS)


def build_tools(request: Request, filters: Filters) -> ToolsView:
    store = _store(request)
    time_sql, time_params = _span_time_clause(filters)
    where, params = time_sql, list(time_params)
    if filters.tool:
        where += " AND json_extract(payload_json, '$.tool_name') = ?"
        params.append(filters.tool)
    if filters.errors_only:
        # A call that stopped at the confirmation gate answers `is_error` — the MCP server refuses
        # an unconfirmed write (§8.6) — but it is the gate working, not a failure, so "Errors only"
        # does not list it and the rate below does not count it (`dashboard-readability-13`).
        where += f" AND json_extract(payload_json, '$.is_error') = 1 AND {NOT_A_PAUSE}"

    # The rollup is a SQL aggregate, not a Python loop over every row: a `tool_call` payload runs
    # to 32 KB (§10.5) and the store holds `TRACE_RETENTION_SESSIONS` sessions' worth of them, so
    # materialising the whole set to count calls would put the 512 MB instance under real pressure.
    # Every sibling builder (`build_llm`, `build_retrieval`, `build_safety`) is bounded; so is this.
    rollups = store.execute(
        f"SELECT {TOOL_NAME_SQL} AS tool_name, COUNT(*) AS calls, "
        f"SUM(CASE WHEN json_extract(payload_json, '$.is_error') = 1 AND {NOT_A_PAUSE} THEN 1 ELSE 0 END) AS errors, "
        f"SUM(CASE WHEN {IS_A_PAUSE} THEN 1 ELSE 0 END) AS pauses, "
        "MAX(started_at) AS last_called_at "
        f"FROM spans WHERE kind = 'tool_call'{where} "
        "GROUP BY tool_name ORDER BY calls DESC, tool_name",
        params,
    ).dicts()
    # p50/p95 over the newest `ROW_LIMIT` calls *per tool*, so a chatty tool cannot starve a rare
    # one of its sample and neither can flood memory.
    durations: dict[str, list[int]] = defaultdict(list)
    sample = store.execute(
        "SELECT tool_name, duration_ms FROM ("
        f"  SELECT {TOOL_NAME_SQL} AS tool_name, duration_ms, "
        f"         ROW_NUMBER() OVER (PARTITION BY {TOOL_NAME_SQL} ORDER BY started_at DESC) AS rn "
        f"  FROM spans WHERE kind = 'tool_call'{where}"
        ") WHERE rn <= ? AND duration_ms IS NOT NULL",
        [*params, ROW_LIMIT],
    ).dicts()
    for row in sample:
        durations[row["tool_name"]].append(int(row["duration_ms"]))

    recent_spans = _payloads(
        store.execute(
            "SELECT id, turn_id, session_id, name, duration_ms, payload_json FROM spans "
            f"WHERE kind = 'tool_call'{where} ORDER BY started_at DESC LIMIT ?",
            [*params, ROW_LIMIT],
        ).dicts()
    )
    recent = [
        ToolCallRow(
            span_id=span["id"],
            turn_id=span["turn_id"],
            dashboard_url=turn_record_url(span.get("session_id"), span["turn_id"]),
            tool_name=span["payload"].get("tool_name") or span.get("name") or "unknown",
            arguments=span["payload"].get("arguments") or {},
            arguments_summary=summarise_arguments(span["payload"].get("arguments") or {}),
            result_preview=preview_value(span["payload"].get("result_json") or ""),
            result_summary=summarise_result(
                span["payload"].get("structured_content"),
                span["payload"].get("result_json"),
                error_code=span["payload"].get("error_code"),
            ),
            is_error=bool(span["payload"].get("is_error")),
            paused_for_confirmation=span["payload"].get("error_code") == CONFIRMATION_REQUIRED,
            outcome_label=(
                "paused"
                if span["payload"].get("error_code") == CONFIRMATION_REQUIRED
                else ("error" if span["payload"].get("is_error") else "ok")
            ),
            error_code=span["payload"].get("error_code"),
            duration_ms=span["duration_ms"],
            actor_employee_id=span["payload"].get("actor_employee_id"),
        )
        for span in recent_spans
    ]
    by_tool = [
        ToolRollup(
            tool_name=row["tool_name"],
            calls=int(row["calls"]),
            sample_n=int(row["calls"]),
            errors=int(row["errors"] or 0),
            confirmation_pauses=int(row["pauses"] or 0),
            error_rate=round(int(row["errors"] or 0) / int(row["calls"]), 4) if row["calls"] else 0.0,
            duration_n=len(durations[row["tool_name"]]),
            p50_ms=percentile(durations[row["tool_name"]], 0.50),
            p95_ms=percentile(durations[row["tool_name"]], 0.95),
            last_called_at=int(row["last_called_at"]) if row["last_called_at"] is not None else None,
        )
        for row in rollups
    ]
    return ToolsView(by_tool=by_tool, recent=recent)


# --------------------------------------------------------------------------------------
# Page 8 — safety
# --------------------------------------------------------------------------------------


def _doc_of(chunk_id: str) -> str | None:
    """Resolve a quarantined chunk to its document; `None` when the index is not readable."""
    try:
        chunk = corpusread.get_chunk(chunk_id)
    except Exception:  # a missing or unreadable index must never break the safety page
        return None
    return chunk.doc_id if chunk else None


def build_safety(request: Request, filters: Filters) -> SafetyView:
    store = _store(request)
    time_sql, time_params = _span_time_clause(filters)
    where, params = time_sql, list(time_params)
    if filters.rule:
        where += " AND json_extract(payload_json, '$.rule_id') = ?"
        params.append(filters.rule)
    if filters.verdict:
        where += " AND json_extract(payload_json, '$.verdict') = ?"
        params.append(filters.verdict)

    by_rule = store.execute(
        "SELECT json_extract(payload_json, '$.rule_id') AS rule_id, "
        "json_extract(payload_json, '$.rule_name') AS rule_name, "
        "json_extract(payload_json, '$.verdict') AS verdict, COUNT(*) AS count "
        f"FROM spans WHERE kind = 'guardrail'{where} GROUP BY rule_id, rule_name, verdict "
        "ORDER BY rule_id, verdict",
        params,
    ).dicts()

    injections: list[InjectionHit] = []
    hits = _payloads(
        store.execute(
            "SELECT id, payload_json FROM spans WHERE kind = 'guardrail' "
            "AND json_extract(payload_json, '$.rule_id') = 'G4' "
            f"AND json_extract(payload_json, '$.verdict') = 'warn'{time_sql} ORDER BY started_at DESC LIMIT ?",
            [*time_params, ROW_LIMIT],
        ).dicts()
    )
    for span in hits:
        payload = span["payload"]
        for chunk_id in payload.get("details", {}).get("chunk_ids", []) or []:
            injections.append(
                InjectionHit(
                    span_id=span["id"],
                    chunk_id=chunk_id,
                    doc_id=_doc_of(chunk_id),
                    matched_pattern=payload.get("matched_pattern"),
                )
            )

    confirmation_where, confirmation_params = "", []
    if filters.user_response:
        confirmation_where += " AND user_response = ?"
        confirmation_params.append(filters.user_response)
    if filters.date_from and (bound := _day_bounds(filters.date_from, end=False)) is not None:
        confirmation_where += " AND created_at >= ?"
        confirmation_params.append(bound)
    if filters.date_to and (bound := _day_bounds(filters.date_to, end=True)) is not None:
        confirmation_where += " AND created_at < ?"
        confirmation_params.append(bound)
    confirmations = store.execute(
        "SELECT turn_id, session_id, tool_name, human_summary, user_response, created_at, used_at FROM confirmations "
        f"WHERE 1=1{confirmation_where} ORDER BY created_at DESC LIMIT ?",
        [*confirmation_params, ROW_LIMIT],
    ).dicts()

    writes = store.execute(
        "SELECT id, kind, employee_id, created_at, turn_id, session_id, payload_json FROM mock_writes "
        "ORDER BY created_at DESC LIMIT ?",
        (ROW_LIMIT,),
    ).dicts()

    return SafetyView(
        by_rule=[
            RuleCount(
                rule_id=row["rule_id"] or "?",
                rule_name=row["rule_name"] or "",
                verdict=row["verdict"] or "",
                count=int(row["count"]),
            )
            for row in by_rule
        ],
        injection_hits=injections,
        confirmations=[
            ConfirmationRow(
                turn_id=row["turn_id"],
                dashboard_url=turn_record_url(row.get("session_id"), row["turn_id"]),
                action=row["tool_name"],
                human_summary=row["human_summary"],
                user_response=row["user_response"],
                created_at=int(row["created_at"]),
                used_at=row["used_at"],
            )
            for row in confirmations
        ],
        mock_writes=[
            MockWriteRow(
                id=row["id"],
                kind=row["kind"],
                employee_id=row["employee_id"],
                created_at=int(row["created_at"]),
                turn_id=row["turn_id"],
                dashboard_url=turn_record_url(row.get("session_id"), row.get("turn_id")),
                payload=json.loads(row["payload_json"] or "{}"),
                payload_summary=summarise_arguments(json.loads(row["payload_json"] or "{}")),
            )
            for row in writes
        ],
    )


# --------------------------------------------------------------------------------------
# Page 9 — the live MCP catalog
# --------------------------------------------------------------------------------------


def _by_discovery(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The handshakes newest-discovered first — the order of the column the table is headed by.

    DISCOVERED, not the span's own start (UX W9, DR4-14 = npo5-08): a cached handshake carries the
    discovery time of the first one, so a history sorted by `started_at` printed 21:12 above
    21:09 above 21:12. A row with no `discovered_at` sorts last.
    """
    return sorted(spans, key=lambda span: int(span["payload"].get("discovered_at") or 0), reverse=True)


def _handshake_history(store: Store) -> list[HandshakeRow]:
    spans = _payloads(
        store.execute(
            "SELECT id, turn_id, session_id, payload_json FROM spans WHERE kind = 'mcp_discovery' "
            "ORDER BY started_at DESC LIMIT 25"
        ).dicts()
    )
    spans = _by_discovery(spans)
    return [
        HandshakeRow(
            span_id=span["id"],
            turn_id=span["turn_id"],
            dashboard_url=turn_record_url(span.get("session_id"), span["turn_id"]),
            discovered_at=span["payload"].get("discovered_at"),
            handshake_ms=span["payload"].get("handshake_ms"),
            tool_count=int(span["payload"].get("tool_count") or 0),
            cached=bool(span["payload"].get("cached")),
            catalog_sha=span["payload"].get("catalog_sha"),
        )
        for span in spans
    ]


async def build_mcp_discovery(request: Request) -> McpDiscoveryView:
    """The catalog as it is **now** — the cached handshake, never a stale copy of a span."""
    store = _store(request)
    settings = _settings(request)
    client = request.app.state.orchestrator.client
    try:
        catalog = await client.discover()
    except (McpUnavailable, TimeoutError, OSError) as exc:
        return McpDiscoveryView(
            server=None,
            transport=settings.mcp_transport_effective,
            url=settings.mcp_server_url,
            protocol_version=None,
            handshake_ms=None,
            discovered_at=None,
            tools=[],
            handshake_history=_handshake_history(store),
            connected=False,
            last_error=str(exc),
        )
    return McpDiscoveryView(
        server=catalog.server_info,
        transport=catalog.transport,
        url=catalog.url,
        protocol_version=catalog.protocol_version,
        handshake_ms=catalog.handshake_ms,
        discovered_at=catalog.discovered_at,
        tools=list(catalog.tools),
        handshake_history=_handshake_history(store),
        connected=True,
        last_error=None,
    )


# --------------------------------------------------------------------------------------
# Page 10 — the corpus browser
# --------------------------------------------------------------------------------------


def build_corpus(filters: Filters) -> CorpusView:
    try:
        documents = corpusread.list_documents()
    except Exception as exc:  # an unbuilt index renders an explanatory empty page, never a 500
        logger.warning("the corpus index could not be read: %s", exc)
        documents = []
    topics = sorted({topic for document in documents for topic in document.topics})
    formats = sorted({document.source_format for document in documents})
    needle = (filters.q or "").lower()
    selected = [
        document
        for document in documents
        if (not filters.topic or filters.topic in document.topics)
        and (not filters.source_format or document.source_format == filters.source_format)
        and (not needle or needle in document.doc_title.lower() or needle in document.full_text.lower())
    ]
    return CorpusView(
        documents=[
            CorpusDocument(
                doc_id=document.doc_id,
                doc_title=document.doc_title,
                source_format=document.source_format,
                topics=list(document.topics),
                section_count=document.section_count,
                chunk_count=document.chunk_count,
                word_count=document.word_count,
                estimated_pages=document.estimated_pages,
            )
            for document in selected
        ],
        topics=topics,
        formats=formats,
    )


def build_corpus_document(doc_id: str) -> CorpusDocumentView:
    try:
        document = corpusread.get_document(doc_id)
        chunks = corpusread.list_chunks(doc_id) if document else []
    except Exception as exc:
        raise HTTPException(status_code=404, detail={"code": "CORPUS_UNAVAILABLE", "detail": str(exc)}) from exc
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_DOCUMENT", "doc_id": doc_id})
    return CorpusDocumentView(
        document=CorpusDocumentDetail(
            doc_id=document.doc_id,
            doc_title=document.doc_title,
            source_format=document.source_format,
            topics=list(document.topics),
            section_count=document.section_count,
            chunk_count=document.chunk_count,
            word_count=document.word_count,
            estimated_pages=document.estimated_pages,
            effective_date=document.effective_date,
            version=document.version,
            full_text=document.full_text,
        ),
        chunks=[
            CorpusChunk(
                chunk_id=chunk.chunk_id,
                heading_path=chunk.heading_path,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                n_chars=chunk.n_chars,
                text=chunk.text,
            )
            for chunk in chunks
        ],
    )


def build_corpus_chunk(chunk_id: str) -> CorpusChunkView:
    try:
        chunk = corpusread.get_chunk(chunk_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail={"code": "CORPUS_UNAVAILABLE", "detail": str(exc)}) from exc
    if chunk is None:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_CHUNK", "chunk_id": chunk_id})
    return CorpusChunkView(
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        doc_title=chunk.doc_title,
        heading_path=chunk.heading_path,
        section=chunk.section,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        n_chars=chunk.n_chars,
        text=chunk.text,
        snippet=chunk.snippet,
    )


# --------------------------------------------------------------------------------------
# Page 11 — evaluations
# --------------------------------------------------------------------------------------


def _dataset_items() -> list[dict[str, Any]]:
    """The items of `evaluation/dataset.yaml` (§13.1), or none if it is not there yet."""
    if not DATASET_PATH.exists():
        return []
    try:
        import yaml

        document = yaml.safe_load(DATASET_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("could not read %s", DATASET_PATH, exc_info=True)
        return []
    items = document.get("items") if isinstance(document, dict) else document
    return [item for item in items or [] if isinstance(item, dict) and item.get("id")]


def _dataset_tags() -> dict[str, dict[str, Any]]:
    """`item_id → {workflow, category, behavior}` — what a rate's *own* sample is made of.

    For a run whose file predates the runner publishing per-metric denominators (UX W9, DR4-02 and
    DR4-03 — the R7 deferral): the per-workflow rows and the action-safety rate are recomputed from
    the items the dataset tags for them, not divided by the whole dataset.
    """
    return {
        str(item["id"]): {
            "workflow": item.get("workflow"),
            "category": item.get("category"),
            "behavior": item.get("gold_behavior") or item.get("behavior") or item.get("expected_behavior"),
        }
        for item in _dataset_items()
    }


def _dataset_labels() -> dict[str, tuple[str | None, str | None]]:
    """`item_id → (question, gold_answer_short)` from `evaluation/dataset.yaml` (§13.1).

    The dataset is a P10 deliverable. Until it exists the two columns are empty rather than
    fabricated from the stored answer, which would make the page agree with itself by construction.
    """
    items = _dataset_items()
    labels: dict[str, tuple[str | None, str | None]] = {}
    for item in items or []:
        if isinstance(item, dict) and item.get("id"):
            labels[str(item["id"])] = (item.get("question"), item.get("gold_answer_short"))
    return labels


def _run_row(row: dict[str, Any]) -> EvalRunRow:
    metrics = EvalMetrics.model_validate(json.loads(row["metrics_json"] or "{}"))
    return EvalRunRow(
        run_id=row["id"],
        # One spelling of one run, everywhere it is named — the list's RUN, the headline table's
        # RUN, the run page's title and breadcrumb — built here from the same `enum_label` the
        # VARIANT column beside it goes through. The stored label spelled the variant
        # `no_structured_tools · deployed` three inches from a cell reading "no structured tools"
        # (UX W7, npo3-01 = DR2-08 = JX2-06). The raw label stays in `eval_runs` (P15).
        label=f"{_f_enum_label(row['variant'])} · {_f_enum_label(row['target'])}",
        stored_label=row.get("label"),
        variant=row["variant"],
        target=row["target"],
        git_sha=row["git_sha"],
        created_at=int(row["created_at"]),
        n_items=int(row["n_items"] or 0),
        headline={name: getattr(metrics, name) for name in HEADLINE_METRICS},
        n_scored={
            name: n
            for name in HEADLINE_METRICS
            if (n := metrics.n_scored.get(name) or metrics.n_scored.get(RATE_DENOMINATORS.get(name, name)))
        },
        judged=metrics.judged,
        judge_model=row["judge_model"],
        duration_s=row["duration_s"],
        est_cost_usd=metrics.est_cost_usd,
    )


RUN_COLUMNS = "id, created_at, git_sha, label, variant, target, n_items, metrics_json, judge_model, duration_s"

#: Rate → the per-item score key whose presence says the item was scored for it (UX W7, npo3-07).
#:
#: Every rate the run page prints, not four of them (UX W8 fix round, npo4-02 = re-audit #3 I6).
#: The runner names its buckets by short key — `arg_correctness`, `cit_resolve`, `tool_selection` —
#: and the page looks each rate up by its own long name, so `n_scored.get("arg_correctness_rate")`
#: was `None` and `Argument correctness 100.0%`, computed over **19** items, rendered with no
#: denominator at all: under P14's own threshold, on P14's own page.
RATE_DENOMINATORS: dict[str, str] = {
    "groundedness_mean": "groundedness",
    "citation_accuracy_mean": "citation_accuracy",
    "cit_resolve_mean": "cit_resolve",
    "tool_selection_accuracy": "tool_selection",
    "arg_correctness_rate": "arg_correctness",
    "partial_match_mean": "partial_match",
    "clarification_accuracy": "clarification",
    "strict_pass_rate": "outcome",
    "action_safety_pass_rate": "safety",
    "catalog_reopened_rate": "catalog_reopened",
    "recommendation_labeled_rate": "recommendation_labeled_rate",
    "workflow_completion": "workflow",
}


def build_eval_runs(request: Request, filters: Filters) -> EvalRunsView:
    store = _store(request)
    where, params = "", []
    if filters.variant:
        where += " AND variant = ?"
        params.append(filters.variant)
    rows = store.execute(
        f"SELECT {RUN_COLUMNS} FROM eval_runs WHERE 1=1{where} ORDER BY created_at DESC", params
    ).dicts()
    return EvalRunsView(runs=[_run_row(row) for row in rows])


def _latency_block(store: Store, items: Sequence[dict[str, Any]]) -> LatencyBlock:
    scored = [row for row in items if (row["run_phase"] or "scored") == "scored"]
    cold = [row for row in items if row["cold"]]
    warm = [row["latency_ms"] for row in scored if not row["cold"]]
    by_kind: Counter[str] = Counter()
    turn_ids = [row["turn_id"] for row in items if row["turn_id"]]
    if turn_ids:
        placeholders = ",".join("?" for _ in turn_ids)
        for turn in store.execute(
            f"SELECT llm_ms, retrieval_ms, tool_ms, store_ms FROM turns WHERE id IN ({placeholders})",
            turn_ids,
        ).dicts():
            for kind in ("llm_ms", "retrieval_ms", "tool_ms", "store_ms"):
                by_kind[kind] += int(turn[kind] or 0)
    latencies = [row["latency_ms"] for row in scored]
    return LatencyBlock(
        p50=percentile(latencies, 0.50),
        p90=percentile(latencies, 0.90),
        p95=percentile(latencies, 0.95),
        p99=percentile(latencies, 0.99),
        n_warm=len(warm),
        n_cold=len(cold),
        cold_p50=percentile([row["latency_ms"] for row in cold], 0.50),
        cold_p95=percentile([row["latency_ms"] for row in cold], 0.95),
        by_kind=dict(by_kind),
    )


def _rss_series(store: Store, items: Sequence[dict[str, Any]]) -> list[RssPoint]:
    """`turns.rss_mb_at_end` — the series §10.1 says page 11 plots."""
    turn_ids = [row["turn_id"] for row in items if row["turn_id"]]
    if not turn_ids:
        return []
    placeholders = ",".join("?" for _ in turn_ids)
    rows = store.execute(
        f"SELECT id, rss_mb_at_end FROM turns WHERE id IN ({placeholders}) AND rss_mb_at_end IS NOT NULL "
        "ORDER BY started_at",
        turn_ids,
    ).dicts()
    return [RssPoint(turn_id=row["id"], rss_mb=float(row["rss_mb_at_end"])) for row in rows]


def build_eval_run_detail(request: Request, run_id: str, filters: Filters) -> EvalRunDetailView:
    store = _store(request)
    run = store.execute(f"SELECT {RUN_COLUMNS} FROM eval_runs WHERE id = ?", (run_id,)).one()
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_RUN", "run_id": run_id})
    rows = store.execute(
        "SELECT item_id, category, session_id, turn_id, run_phase, answer, latency_ms, cold, "
        "scores_json, verdicts_json, passed FROM eval_results WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).dicts()
    labels = _dataset_labels()
    # One query for the whole page rather than one per row: which of this run's turns this
    # deployment actually holds a trace for (**P5**).
    resident = {
        str(found["id"])
        for found in store.execute(
            "SELECT t.id AS id FROM turns t JOIN sessions s ON s.id = t.session_id WHERE s.eval_run_id = ?",
            (run_id,),
        ).dicts()
    }
    items = []
    for row in rows:
        if filters.category and row["category"] != filters.category:
            continue
        if filters.cold_only and not row["cold"]:
            continue
        question, gold = labels.get(row["item_id"], (None, None))
        items.append(
            EvalItemRow(
                item_id=row["item_id"],
                category=row["category"],
                question=question,
                gold=gold,
                answer=row["answer"],
                scores=json.loads(row["scores_json"] or "{}"),
                verdicts=json.loads(row["verdicts_json"] or "{}"),
                latency_ms=row["latency_ms"],
                cold=bool(row["cold"]),
                passed=bool(row["passed"]),
                run_phase=row["run_phase"] or "scored",
                session_id=row["session_id"],
                turn_id=row["turn_id"],
                trace_url=(
                    f"/dashboard/sessions/{row['session_id']}#turn-{row['turn_id']}" if row["session_id"] else None
                ),
                trace_present=str(row["turn_id"] or "") in resident,
            )
        )
    if filters.failures_first:
        items.sort(key=lambda item: (item.passed, item.item_id))
    metrics = EvalMetrics.model_validate(json.loads(run["metrics_json"] or "{}"))
    # Every rate on the page carries its denominator (**P14**; UX W7, npo3-07 = M14). The runner's
    # `n_scored` names its buckets by short key (`safety`, `workflow`) while the page looks each
    # rate up by its own name, so four rates rendered bare — one of them over a single item. The
    # denominator of a rate is the number of scored items that reported it, counted here from
    # the items' own score rows; the runner's figure wins where it exists.
    scored_items = [item for item in items if item.run_phase == "scored"]
    tags = _dataset_tags()
    # The per-workflow rows over the items tagged for THAT workflow (UX W9, DR4-02 = npo5-01), and
    # the action-safety rate over the items where an action was at stake (DR4-03): a run whose
    # file carries the runner's own per-metric denominators keeps them; an older file has the two
    # recomputed here from the dataset's tags and the items' own scores, and never divided by the
    # 28-item dataset again.
    for workflow in list(metrics.workflow_completion_by_workflow):
        key = f"workflow:{workflow}"
        if key in metrics.n_scored:
            continue
        members = [
            float(item.scores["workflow"])
            for item in scored_items
            if tags.get(item.item_id, {}).get("workflow") == workflow and item.scores.get("workflow") is not None
        ]
        if members:
            metrics.n_scored[key] = len(members)
            metrics.workflow_completion_by_workflow[workflow] = sum(members) / len(members)
    if "action_safety_pass_rate" not in metrics.n_scored:
        at_stake = [
            float(item.scores.get("safety", 1.0))
            for item in scored_items
            if item.scores.get("safety_at_stake")
            or tags.get(item.item_id, {}).get("category") == "unsafe_action"
            or tags.get(item.item_id, {}).get("behavior") == "confirm"
        ]
        if at_stake:
            metrics.n_scored["action_safety_pass_rate"] = len(at_stake)
            metrics.action_safety_pass_rate = sum(at_stake) / len(at_stake)
    for metric, score_key in RATE_DENOMINATORS.items():
        if metric in metrics.n_scored:
            continue
        # The runner's own short-key bucket where it has one (`arg_correctness` for
        # `arg_correctness_rate`), else counted off the items' own score rows. A bucket of zero is
        # not published: the metric it would belong to is `null` on this run, and an exported
        # `"groundedness_mean": 0` reads as a measurement rather than as an absence (I6).
        counted = metrics.n_scored.get(score_key)
        if counted is None:
            counted = sum(1 for item in items if item.run_phase == "scored" and item.scores.get(score_key) is not None)
        if counted:
            metrics.n_scored[metric] = counted
    return EvalRunDetailView(
        run=_run_row(run),
        metrics=metrics,
        verdict=_verdict(store, run, rows),
        items=items,
        latency=_latency_block(store, rows),
        rss_series=_rss_series(store, rows),
    )


def _scored_pass_rate(rows: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    """`(passed, scored)` over the rows of one run — the cold probe and any unscored phase excluded."""
    scored = [row for row in rows if (row["run_phase"] or "scored") == "scored"]
    return sum(1 for row in scored if row["passed"]), len(scored)


def _verdict(store: Store, run: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> RunVerdict:
    """The pass line, the dataset legend, and the delta against the previous run of this variant."""
    passed, scored = _scored_pass_rate(rows)
    categories: Counter[str] = Counter(
        row["category"] for row in rows if (row["run_phase"] or "scored") == "scored" and row["category"]
    )
    previous = store.execute(
        "SELECT id, created_at FROM eval_runs WHERE variant = ? AND created_at < ? ORDER BY created_at DESC LIMIT 1",
        (run["variant"], run["created_at"]),
    ).one()
    previous_rate = None
    if previous is not None:
        earlier = store.execute(
            "SELECT run_phase, passed FROM eval_results WHERE run_id = ?", (previous["id"],)
        ).dicts()
        was_passed, was_scored = _scored_pass_rate(earlier)
        previous_rate = round(was_passed / was_scored, 4) if was_scored else None
    return RunVerdict(
        items_scored=scored,
        items_passed=passed,
        pass_rate=round(passed / scored, 4) if scored else None,
        by_category=dict(sorted(categories.items())),
        previous_run_id=previous["id"] if previous is not None else None,
        previous_created_at=int(previous["created_at"]) if previous is not None else None,
        previous_pass_rate=previous_rate,
    )


def _chunk_size_points() -> list[ChunkSizePoint]:
    """`evaluation/results/chunk_size_comparison.json` — the zero-LLM sweep of §13.9."""
    path = RESULTS_DIR / "chunk_size_comparison.json"
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("could not read %s", path, exc_info=True)
        return []
    return [
        ChunkSizePoint(chunk_chars=int(row["chunk_chars"]), doc_recall_mean=float(row["doc_recall_mean"]))
        for row in document.get("variants") or []
        if row.get("chunk_chars") is not None and row.get("doc_recall_mean") is not None
    ]


def build_eval_compare(request: Request) -> EvalCompareView:
    """The newest run of each variant, and every item whose pass flips against `baseline`."""
    store = _store(request)
    rows = store.execute(f"SELECT {RUN_COLUMNS} FROM eval_runs ORDER BY created_at DESC").dicts()
    newest: dict[str, dict[str, Any]] = {}
    for row in rows:
        newest.setdefault(row["variant"], row)

    variants = [
        VariantMetrics(
            variant=variant,
            run_id=row["id"],
            metrics=EvalMetrics.model_validate(json.loads(row["metrics_json"] or "{}")),
        )
        for variant, row in sorted(newest.items(), key=lambda pair: pair[0] != "baseline")
    ]

    flips: list[Flip] = []
    baseline = newest.get("baseline")
    if baseline is not None:
        baseline_passed = {
            row["item_id"]: bool(row["passed"])
            for row in store.execute(
                "SELECT item_id, passed FROM eval_results WHERE run_id = ? AND run_phase = 'scored'",
                (baseline["id"],),
            ).dicts()
        }
        for variant, row in newest.items():
            if variant == "baseline":
                continue
            for result in store.execute(
                "SELECT item_id, passed FROM eval_results WHERE run_id = ? AND run_phase = 'scored'",
                (row["id"],),
            ).dicts():
                before = baseline_passed.get(result["item_id"])
                if before is None or before == bool(result["passed"]):
                    continue
                flips.append(
                    Flip(
                        item_id=result["item_id"],
                        variant=variant,
                        baseline_passed=before,
                        variant_passed=bool(result["passed"]),
                    )
                )
    flips.sort(key=lambda flip: (flip.variant, flip.item_id))
    return EvalCompareView(variants=variants, flips=flips, chunk_size=_chunk_size_points())


# --------------------------------------------------------------------------------------
# The bounded smoke-eval launch (§11.7)
# --------------------------------------------------------------------------------------


class SmokeEvalBody(BaseModel):
    """§11.7's bounded request. Anything outside the smoke bounds is refused, never trimmed."""

    model_config = ConfigDict(extra="forbid")

    variant: Literal["baseline", "dense_only_k2", "no_structured_tools"] = "baseline"
    n_items: int = 3
    item_ids: list[str] = Field(default_factory=list)
    judge: bool = False
    label: str = "dashboard smoke run"


# --------------------------------------------------------------------------------------
# Routing helpers
# --------------------------------------------------------------------------------------


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _store(request: Request) -> Store:
    return get_store(_settings(request))


def _json(view: BaseModel) -> JSONResponse:
    return JSONResponse(view.model_dump(mode="json"))


def _page(
    request: Request,
    template: str,
    view: BaseModel,
    *,
    page_number: int,
    title: str,
    lede: str,
    api_url: str,
    filters: Filters | None = None,
    breadcrumbs: Sequence[tuple[str, str]] | None = None,
    **extra: Any,
) -> Response:
    """Render the page from the **same dict** the matching `/api/*` route returns.

    Since UX W1 the context also carries the shell every authenticated page wears — `surface`,
    `actor_name`, `gate_on` — so `_masthead.html` renders identically here and on `/`. It never did
    before: the dashboard had its own masthead with a `Chat` link, a static `HR ADMIN` chip and no
    way to sign out.

    `lede` is **required** (UX W4, `dashboard-readability-15`). Eleven pages shared one seven-noun
    tagline and no page said what it was for; a positional requirement is what stops the twelfth
    page from shipping without one.
    """
    payload = view.model_dump(mode="json")
    context = {
        "view": payload,
        "page_number": page_number,
        "nav_current": NAV_PARENT.get(page_number, page_number),
        "page_title": title,
        "page_lede": lede,
        "breadcrumbs": list(breadcrumbs or ()),
        # A detail page lights its parent in the nav, and `aria-current="page"` on a link that is
        # not this page is a lie a screen reader repeats. Within-section is `true`
        # (`navigation-and-ia-10`).
        "nav_exact": not breadcrumbs,
        "api_url": api_url,
        "nav": NAV,
        # One sentence for the three admin-gated controls (UX W7, M09 = dgc-r2-9), the six-rule
        # denominator the session tile divides by (npo3-04), and what answered — the same label
        # the demo panel and the Overview print (M20 = DR2-14).
        "admin_hint": ADMIN_HINT,
        "safety_rules": api.SAFETY_RULES,
        "kind_help": SPAN_KIND_HELP,
        "provider_label": api.provider_label(str(_settings(request).llm_provider)),
        **api.shell_context(request, surface="dashboard"),
        "filters": (filters or Filters()).as_dict(),
        # `page` is always dropped here: the pager appends its own, and two `page=` values in
        # one query string would silently resolve to the first.
        "filter_query": (filters or Filters()).query_string(page=1),
        "page_size": PAGE_SIZE,
        "row_limit": ROW_LIMIT,
        **extra,
    }
    return TEMPLATES.TemplateResponse(request=request, name=f"dashboard/{template}", context=context)


router = APIRouter()


# -- page 1 --------------------------------------------------------------------------------


@router.get("/api/traces/overview")
async def api_overview(request: Request) -> JSONResponse:
    return _json(await build_overview(request))


@router.get("/dashboard", response_class=HTMLResponse)
async def page_overview(request: Request) -> Response:
    view = await build_overview(request)
    return _page(
        request,
        "overview.html",
        view,
        page_number=1,
        title="Overview",
        lede="The last 24 hours at a glance — traffic, quality and safety, speed and cost.",
        api_url="/api/traces/overview",
    )


# -- page 2 --------------------------------------------------------------------------------


@router.get("/api/traces/sessions")
async def api_sessions(request: Request) -> JSONResponse:
    return _json(build_sessions(request, Filters.from_request(request)))


@router.get("/dashboard/sessions", response_class=HTMLResponse)
async def page_sessions(request: Request) -> Response:
    filters = Filters.from_request(request)
    view = build_sessions(request, filters)
    return _page(
        request,
        "sessions.html",
        view,
        page_number=2,
        title="Sessions",
        lede="Every conversation the assistant has had.",
        api_url=f"/api/traces/sessions?{filters.query_string()}",
        filters=filters,
        pages=max(1, math.ceil(view.total / PAGE_SIZE)),
    )


# -- page 3 --------------------------------------------------------------------------------


@router.get("/api/traces/sessions/{session_id}")
async def api_session_detail(request: Request, session_id: str) -> JSONResponse:
    return _json(build_session_detail(request, session_id))


#: How much of the opening question the session-detail title shows before it is elided. The title
#: used to be `Session fd7a7cb56895…`, which names the record and not the conversation.
SESSION_TITLE_CHARS = 80

#: The chat surface's own path — the page the `#turn-N` deep link is clicked on.
CHAT_PATH = "/"


def _opened_from_chat(request: Request) -> bool:
    """Did this page's request come from the conversation it is the record of?

    `dashboard-readability-29` asks the deep-linked session page to offer a way *back to the chat*,
    not only up to the listing. The fragment never reaches the server, so the signal is the
    same-origin `Referer`: a click from `/` is the deep link, a click from `/dashboard/sessions` is
    the listing, and a pasted URL carries no referrer at all and gets the plain trail.
    """
    referer = request.headers.get("referer")
    if not referer:
        return False
    parsed = urlsplit(referer)
    if parsed.netloc and parsed.netloc != request.url.netloc:
        return False
    return (parsed.path or "/") == CHAT_PATH


@router.get("/dashboard/sessions/{session_id}", response_class=HTMLResponse)
async def page_session_detail(request: Request, session_id: str) -> Response:
    view = build_session_detail(request, session_id)
    longest = max((turn.duration_ms or 0) for turn in view.turns) if view.turns else 0
    opening = view.turns[0].user_message if view.turns else ""
    title = opening if len(opening) <= SESSION_TITLE_CHARS else opening[:SESSION_TITLE_CHARS].rstrip() + "…"
    trail = [(nav_label("/dashboard/sessions"), "/dashboard/sessions")]
    if _opened_from_chat(request):
        trail.insert(0, ("Opened from chat", CHAT_PATH))
    return _page(
        request,
        "session_detail.html",
        view,
        page_number=3,
        title=title or f"Session {session_id[:12]}…",
        lede="Every turn of this conversation, and every step behind each answer.",
        breadcrumbs=trail,
        api_url=f"/api/traces/sessions/{session_id}",
        kinds=sorted({span.kind for turn in view.turns for span in turn.spans}),
        longest_ms=longest,
    )


@router.get("/api/traces/turns/{turn_id}")
async def api_turn(request: Request, turn_id: str) -> JSONResponse:
    """The single-turn view-model page 3 renders — and what the 202 fallback polls (§11.8)."""
    return _json(build_turn(request, turn_id))


# -- page 4 --------------------------------------------------------------------------------


@router.get("/api/traces/turns")
async def api_turns(request: Request) -> JSONResponse:
    return _json(build_turns(request, Filters.from_request(request)))


@router.get("/dashboard/turns", response_class=HTMLResponse)
async def page_turns(request: Request) -> Response:
    filters = Filters.from_request(request)
    view = build_turns(request, filters)
    return _page(
        request,
        "turns.html",
        view,
        page_number=4,
        title="Turns",
        lede="Every question asked, and how each one was answered.",
        api_url=f"/api/traces/turns?{filters.query_string()}",
        filters=filters,
        pages=max(1, math.ceil(view.total / PAGE_SIZE)),
    )


# -- page 5 --------------------------------------------------------------------------------


@router.get("/api/traces/llm")
async def api_llm(request: Request) -> JSONResponse:
    return _json(build_llm(request, Filters.from_request(request)))


@router.get("/dashboard/llm", response_class=HTMLResponse)
async def page_llm(request: Request) -> Response:
    filters = Filters.from_request(request)
    return _page(
        request,
        "llm.html",
        build_llm(request, filters),
        page_number=5,
        title="Model calls",
        lede="Each call to the language model — which model, what for, how many tokens, how long.",
        api_url=f"/api/traces/llm?{filters.query_string()}",
        filters=filters,
    )


# -- page 6 --------------------------------------------------------------------------------


@router.get("/api/traces/retrieval")
async def api_retrieval(request: Request) -> JSONResponse:
    return _json(build_retrieval(request, Filters.from_request(request)))


@router.get("/dashboard/retrieval", response_class=HTMLResponse)
async def page_retrieval(request: Request) -> Response:
    filters = Filters.from_request(request)
    return _page(
        request,
        "retrieval.html",
        build_retrieval(request, filters),
        page_number=6,
        title="Retrieval",
        lede="Which policy passages each question pulled up, and how well they matched.",
        api_url=f"/api/traces/retrieval?{filters.query_string()}",
        filters=filters,
    )


# -- page 7 --------------------------------------------------------------------------------


@router.get("/api/traces/tools")
async def api_tools(request: Request) -> JSONResponse:
    return _json(build_tools(request, Filters.from_request(request)))


@router.get("/dashboard/tools", response_class=HTMLResponse)
async def page_tools(request: Request) -> Response:
    filters = Filters.from_request(request)
    return _page(
        request,
        "tools.html",
        build_tools(request, filters),
        page_number=7,
        title="Tool calls",
        lede="Every tool the assistant called, and what came back.",
        api_url=f"/api/traces/tools?{filters.query_string()}",
        filters=filters,
    )


# -- page 8 --------------------------------------------------------------------------------


@router.get("/api/traces/safety")
async def api_safety(request: Request) -> JSONResponse:
    return _json(build_safety(request, Filters.from_request(request)))


@router.get("/dashboard/safety", response_class=HTMLResponse)
async def page_safety(request: Request) -> Response:
    filters = Filters.from_request(request)
    return _page(
        request,
        "safety.html",
        build_safety(request, filters),
        page_number=8,
        title="Guardrails",
        lede="The six safety checks, what they allowed, and every human confirmation.",
        # Every rule, named, so the chart can plot a zero bar for one that did not fire
        # (`dashboard-readability-17`).
        rule_labels={rule_id: f"{rule_id} {name}" for rule_id, name in RULE_LABELS.items()},
        api_url=f"/api/traces/safety?{filters.query_string()}",
        filters=filters,
    )


@router.post("/api/dev/reset-sandbox")
async def reset_sandbox(request: Request) -> JSONResponse:
    """Page 8's **Reset sandbox** control: clear `mock_writes` and nothing else (§11.6)."""
    store = _store(request)
    removed = store.execute("DELETE FROM mock_writes").rows_affected
    return JSONResponse({"cleared": int(removed)})


# -- page 9 --------------------------------------------------------------------------------


@router.get("/api/mcp/discovery")
async def api_mcp_discovery(request: Request) -> JSONResponse:
    return _json(await build_mcp_discovery(request))


@router.post("/api/mcp/rediscover")
async def mcp_rediscover(request: Request) -> JSONResponse:
    """Page 9's **Re-discover now** control.

    `spans.turn_id` is `NOT NULL`, so out-of-turn re-discovery opens a synthetic
    `client_label='maintenance'` session and a turn with `outcome='maintenance'` and writes the
    `mcp_discovery` span into it (§11.6). That outcome is excluded from the eval escalation matrix.
    """
    identity = api.identity_of(request)
    client = request.app.state.orchestrator.client
    await client.reset()
    session = SessionSpec(
        employee_id=None,
        auth_mode=identity.auth_mode,
        actor_role=identity.actor_role,
        client_label="maintenance",
    )
    buffer = trace_module.start_turn(session, user_message="re-discover the MCP catalog")
    try:
        catalog = await client.discover(buffer)
    except (McpUnavailable, TimeoutError, OSError) as exc:
        buffer.close(outcome="maintenance", stop_reason="error", error_kind="tool_unavailable")
        return JSONResponse({"rediscovered": False, "error": str(exc), "session_id": session.id})
    buffer.close(outcome="maintenance", stop_reason="maintenance")
    return JSONResponse(
        {
            "rediscovered": True,
            "tool_count": len(catalog.tools),
            "handshake_ms": catalog.handshake_ms,
            "catalog_sha": catalog.catalog_sha,
            "session_id": session.id,
            "turn_id": buffer.turn_id,
        }
    )


@router.get("/dashboard/mcp", response_class=HTMLResponse)
async def page_mcp(request: Request) -> Response:
    view = await build_mcp_discovery(request)
    return _page(
        request,
        "mcp.html",
        view,
        page_number=9,
        title="Tool server",
        lede="The tool server the assistant is connected to, and the tools it offers.",
        api_url="/api/mcp/discovery",
    )


# -- page 10 -------------------------------------------------------------------------------


@router.get("/api/corpus/documents")
async def api_corpus_documents(request: Request) -> JSONResponse:
    return _json(build_corpus(Filters.from_request(request)))


@router.get("/api/corpus/documents/{doc_id}")
async def api_corpus_document(doc_id: str) -> JSONResponse:
    return _json(build_corpus_document(doc_id))


@router.get("/api/corpus/chunks/{chunk_id}")
async def api_corpus_chunk(chunk_id: str) -> JSONResponse:
    return _json(build_corpus_chunk(chunk_id))


# -- the policy reader ---------------------------------------------------------------------
#
# Not a dashboard page: the shared masthead, the document, and nothing else. It is where a citation
# goes (UX W1, navigation-and-ia-11). `/dashboard/corpus/{doc_id}` stays exactly as it is — it is a
# chunk inspector with offsets and ids, which is the right tool for the observability surface and
# the wrong one to hand a person who clicked "Remote & Hybrid Work Policy · Eligibility".


@router.get("/policy", response_class=HTMLResponse)
async def page_policy_index(request: Request) -> Response:
    """The library, listed once, where the refusal's *"See the full policy library"* link goes."""
    return TEMPLATES.TemplateResponse(
        request=request,
        name="policy_index.html",
        context={
            "documents": [
                {
                    "doc_id": document.doc_id,
                    "doc_title": document.doc_title,
                    "version": document.version,
                    "effective_date": document.effective_date,
                }
                for document in corpusread.list_documents()
            ],
            # The same way back the reader carries (UX W7, nav-r2-7): the index was the one route
            # of the three that offered none.
            "conversation_url": api.conversation_url(request),
            **api.shell_context(request, surface="chat"),
        },
    )


@router.get("/policy/{doc_id}", response_class=HTMLResponse)
async def page_policy_reader(request: Request, doc_id: str) -> Response:
    """One policy document, an anchor per chunk, gated by the access token and by nothing else."""
    view = build_corpus_document(doc_id)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="policy.html",
        context={
            "view": view.model_dump(mode="json"),
            # Where "Back to your conversation" goes. Built server-side from the persona's own most
            # recent conversation, because the reader is reached by a plain `href` from an answer
            # and carries nothing of the turn that sent it (UX W6, nav-reaudit-1).
            "conversation_url": api.conversation_url(request),
            **api.shell_context(request, surface="chat"),
        },
    )


@router.get("/dashboard/corpus", response_class=HTMLResponse)
async def page_corpus(request: Request) -> Response:
    filters = Filters.from_request(request)
    return _page(
        request,
        "corpus.html",
        build_corpus(filters),
        page_number=10,
        title="Corpus & chunks",
        lede="The policy documents the assistant is allowed to answer from, as the index holds them.",
        api_url=f"/api/corpus/documents?{filters.query_string()}",
        filters=filters,
    )


@router.get("/dashboard/corpus/{doc_id}", response_class=HTMLResponse)
async def page_corpus_document(request: Request, doc_id: str) -> Response:
    view = build_corpus_document(doc_id)
    return _page(
        request,
        "corpus_document.html",
        view,
        page_number=10,
        title=view.document.doc_title,
        lede="Every passage of this document a citation can point at.",
        breadcrumbs=[(nav_label("/dashboard/corpus"), "/dashboard/corpus")],
        api_url=f"/api/corpus/documents/{doc_id}",
    )


# -- page 11 -------------------------------------------------------------------------------


@router.get("/api/eval/runs")
async def api_eval_runs(request: Request) -> JSONResponse:
    return _json(build_eval_runs(request, Filters.from_request(request)))


@router.get("/api/eval/compare")
async def api_eval_compare(request: Request) -> JSONResponse:
    return _json(build_eval_compare(request))


@router.get("/api/eval/runs/{run_id}")
async def api_eval_run(request: Request, run_id: str) -> JSONResponse:
    return _json(build_eval_run_detail(request, run_id, Filters.from_request(request)))


@router.post("/api/eval/runs")
async def start_smoke_eval(request: Request) -> Response:
    """§11.7's bounded launch. Admin-only (the gate), and it hard-refuses the unbounded request.

    `evaluation.runner` is imported **lazily, inside the handler** so the whole dashboard boots
    without the P10 package: until it lands, a well-formed request answers **501**
    `{"code": "EVAL_RUNNER_UNAVAILABLE"}` rather than a stack trace.
    """
    settings = _settings(request)
    # The same JSON-or-form body parser every other POST uses, so the page's own control and a
    # JSON client reach one handler — §11.8's endpoint list is exact.
    body = await api._parse_body(request, SmokeEvalBody)
    cap = settings.eval_smoke_max_items
    requested = len(body.item_ids) or body.n_items
    if requested < 1 or requested > cap:
        raise HTTPException(
            status_code=400,
            detail={"code": "SMOKE_BOUNDS_EXCEEDED", "max_items": cap, "requested": requested},
        )
    try:
        from evaluation import runner
    except ImportError as exc:
        return JSONResponse(
            {
                "code": "EVAL_RUNNER_UNAVAILABLE",
                "detail": "evaluation/runner.py is not part of this build yet; it lands with the P10 harness.",
                "reason": str(exc),
            },
            status_code=501,
        )
    # P10 owns `smoke_run`: an async iterator of SSE frames over the same `POST /chat` path the
    # offline runner drives, so what the dashboard demonstrates is what `make eval` runs (§11.7).
    stream = runner.smoke_run(
        variant=body.variant,
        item_ids=list(body.item_ids),
        n_items=requested,
        judge=body.judge,
        label=body.label,
        base_url=settings.eval_target_base_url,
    )
    return StreamingResponse(stream, media_type="text/event-stream")


@router.get("/dashboard/evals", response_class=HTMLResponse)
async def page_evals(request: Request) -> Response:
    filters = Filters.from_request(request)
    view = build_eval_runs(request, filters)
    return _page(
        request,
        "evals.html",
        view,
        page_number=11,
        title="Evaluations",
        lede="Scored test runs — how accurate the answers are, and how well they cite.",
        api_url=f"/api/eval/runs?{filters.query_string()}",
        filters=filters,
        tab=_tab(request, ("runs", "compare")),
        compare=build_eval_compare(request).model_dump(mode="json"),
        headline_metrics=HEADLINE_METRICS,
        judged_metrics=JUDGED_METRICS,
        deterministic_metrics=DETERMINISTIC_METRICS,
        rate_metrics=RATE_METRICS,
        metric_labels=METRIC_LABELS,
        smoke_max_items=_settings(request).eval_smoke_max_items,
    )


@router.get("/dashboard/evals/{run_id}", response_class=HTMLResponse)
async def page_eval_detail(request: Request, run_id: str) -> Response:
    filters = Filters.from_request(request)
    view = build_eval_run_detail(request, run_id, filters)
    return _page(
        request,
        "eval_detail.html",
        view,
        page_number=11,
        title=view.run.label or f"Run {view.run.variant}",
        lede=f"{_f_counted(view.run.n_items, 'item')} from the committed dataset, scored end to end.",
        breadcrumbs=[(nav_label("/dashboard/evals"), "/dashboard/evals")],
        tab=_tab(request, ("metrics", "items", "system")),
        api_url=f"/api/eval/runs/{run_id}",
        filters=filters,
        headline_metrics=HEADLINE_METRICS,
        judged_metrics=JUDGED_METRICS,
        deterministic_metrics=DETERMINISTIC_METRICS,
        rate_metrics=RATE_METRICS,
        # The page's own vocabulary for the "Items scored per metric" legend, so it names the
        # metrics its tiles name (UX W8 fix round, M17 = DR3-08).
        rate_denominators=tuple(RATE_DENOMINATORS),
    )


__all__ = [
    "DETERMINISTIC_METRICS",
    "HEADLINE_METRICS",
    "JUDGED_METRICS",
    "PAGE_SIZE",
    "EvalMetrics",
    "Filters",
    "OverviewView",
    "SessionDetailView",
    "TurnDetail",
    "percentile",
    "router",
]
