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

**Access.** The whole prefix is gated *and* admin-only: `web/api.py`'s pure-ASGI
`AccessGateMiddleware` refuses `/dashboard/*` and `/api/*` with **403** `{"code": "ADMIN_REQUIRED"}`
outside the admin persona before any handler runs. So the three write controls are never rendered
dead — reaching their host page already proves the persona.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from hrmosaic.agent.client import McpUnavailable
from hrmosaic.agent.orchestrator import preview_value, summarise_span
from hrmosaic.core import corpusread
from hrmosaic.core import trace as trace_module
from hrmosaic.core.db import Store, get_store, now_micros
from hrmosaic.core.models import DiscoveredTool, ServerInfo
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

#: §11.6's eleven pages, in order: the nav, and the only place the ordering is written down.
NAV: tuple[tuple[int, str, str], ...] = (
    (1, "Overview", "/dashboard"),
    (2, "Sessions", "/dashboard/sessions"),
    (3, "Session detail", "/dashboard/sessions"),
    (4, "Turns", "/dashboard/turns"),
    (5, "LLM calls", "/dashboard/llm"),
    (6, "Retrieval", "/dashboard/retrieval"),
    (7, "Tools", "/dashboard/tools"),
    (8, "Safety", "/dashboard/safety"),
    (9, "MCP", "/dashboard/mcp"),
    (10, "Corpus", "/dashboard/corpus"),
    (11, "Evaluations", "/dashboard/evals"),
)

#: Page 3 has no standalone URL of its own — it is opened from page 2 — so the nav renders it as
#: a plain label everywhere except on page 3 itself. Skipping it would leave a "where is 3?" gap in
#: the middle of a nav a demo narrates by number.
DETAIL_ONLY_PAGES = (3,)

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


# --------------------------------------------------------------------------------------
# Jinja filters — the display vocabulary the eleven pages share
# --------------------------------------------------------------------------------------


def _f_ts(value: Any) -> str:
    """Epoch **microseconds** (§10.1's unit) rendered UTC, to the second."""
    if value in (None, ""):
        return "—"
    try:
        return datetime.fromtimestamp(int(value) / 1_000_000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


def _f_ms(value: Any) -> str:
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
    return f"{milliseconds:.0f} ms"


def _f_num(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.3f}".rstrip("0").rstrip(".")
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _f_pct(value: Any) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def _f_usd(value: Any) -> str:
    """Always presented as an estimate (§9.8) — the label lives beside it on every page."""
    return "—" if value is None else f"${float(value):,.4f}"


def _f_orna(value: Any) -> str:
    """A metric that was not computed reads as an em dash, never as a fabricated zero."""
    return "—" if value is None else str(value)


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
    return summarise_span(span.get("kind", ""), span.get("name", ""), span.get("payload") or {})


for _name, _filter in (
    ("ts", _f_ts),
    ("ms", _f_ms),
    ("num", _f_num),
    ("pct", _f_pct),
    ("usd", _f_usd),
    ("orna", _f_orna),
    ("compact", _f_compact),
    ("pretty", _f_pretty),
    ("clamp", _f_clamp),
    ("span_summary", _f_span_summary),
):
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
        """The current filter state as a query string — how the pager keeps the filters."""
        state = {**self.as_dict(), **overrides}
        parts = [
            f"{key}={value if not isinstance(value, bool) else 'true'}"
            for key, value in state.items()
            if value not in (None, "", False) and not (key == "page" and value == 1)
        ]
        return "&".join(parts)


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
    provider: str | None
    model: str | None
    purpose: str | None
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int | None
    ttfb_ms: int | None
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
    query: str
    started_at: int


class RetrievalView(_View):
    rows: list[RetrievalRow]
    top_documents: list[DocumentHits]
    zero_evidence_queries: list[ZeroEvidenceQuery]


class ToolRollup(_View):
    tool_name: str
    calls: int
    error_rate: float
    p50_ms: float | None
    p95_ms: float | None
    last_called_at: int | None


class ToolCallRow(_View):
    span_id: str
    turn_id: str
    tool_name: str
    arguments: dict[str, Any]
    result_preview: str
    is_error: bool
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
    payload: dict[str, Any]


class SafetyView(_View):
    by_rule: list[RuleCount]
    injection_hits: list[InjectionHit]
    confirmations: list[ConfirmationRow]
    mock_writes: list[MockWriteRow]


class HandshakeRow(_View):
    span_id: str
    turn_id: str
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
    judge_agreement_rate: float | None = None
    judge_agreement_n: int = 0
    est_cost_usd: float | None = None


class EvalRunRow(_View):
    run_id: str
    label: str
    variant: str
    target: str
    git_sha: str
    created_at: int
    n_items: int
    headline: dict[str, int | float | None]
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


class EvalRunDetailView(_View):
    run: EvalRunRow
    metrics: EvalMetrics
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
        ("t.intent", filters.intent),
        ("t.workflow", filters.workflow),
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
            "SELECT id, turn_id, duration_ms, payload_json FROM spans "
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
                provider=row["payload"].get("provider"),
                model=row["payload"].get("model"),
                purpose=row["payload"].get("purpose"),
                prompt_tokens=int(row["payload"].get("prompt_tokens") or 0),
                completion_tokens=int(row["payload"].get("completion_tokens") or 0),
                duration_ms=row["duration_ms"],
                ttfb_ms=row["payload"].get("ttfb_ms"),
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
            "SELECT id, turn_id, started_at, payload_json FROM spans "
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


def build_tools(request: Request, filters: Filters) -> ToolsView:
    store = _store(request)
    time_sql, time_params = _span_time_clause(filters)
    where, params = time_sql, list(time_params)
    if filters.tool:
        where += " AND json_extract(payload_json, '$.tool_name') = ?"
        params.append(filters.tool)
    if filters.errors_only:
        where += " AND json_extract(payload_json, '$.is_error') = 1"

    spans = _payloads(
        store.execute(
            "SELECT id, turn_id, started_at, duration_ms, payload_json FROM spans "
            f"WHERE kind = 'tool_call'{where} ORDER BY started_at DESC",
            params,
        ).dicts()
    )
    durations: dict[str, list[int]] = defaultdict(list)
    errors: Counter[str] = Counter()
    calls: Counter[str] = Counter()
    last_called: dict[str, int] = {}
    recent: list[ToolCallRow] = []
    for span in spans:
        payload = span["payload"]
        name = payload.get("tool_name") or span.get("name") or "unknown"
        calls[name] += 1
        if payload.get("is_error"):
            errors[name] += 1
        if span["duration_ms"] is not None:
            durations[name].append(int(span["duration_ms"]))
        last_called[name] = max(last_called.get(name, 0), int(span["started_at"]))
        if len(recent) < ROW_LIMIT:
            recent.append(
                ToolCallRow(
                    span_id=span["id"],
                    turn_id=span["turn_id"],
                    tool_name=name,
                    arguments=payload.get("arguments") or {},
                    result_preview=preview_value(payload.get("result_json") or ""),
                    is_error=bool(payload.get("is_error")),
                    error_code=payload.get("error_code"),
                    duration_ms=span["duration_ms"],
                    actor_employee_id=payload.get("actor_employee_id"),
                )
            )
    by_tool = [
        ToolRollup(
            tool_name=name,
            calls=count,
            error_rate=round(errors[name] / count, 4) if count else 0.0,
            p50_ms=percentile(durations[name], 0.50),
            p95_ms=percentile(durations[name], 0.95),
            last_called_at=last_called.get(name),
        )
        for name, count in calls.most_common()
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
        "SELECT turn_id, tool_name, human_summary, user_response, created_at, used_at FROM confirmations "
        f"WHERE 1=1{confirmation_where} ORDER BY created_at DESC LIMIT ?",
        [*confirmation_params, ROW_LIMIT],
    ).dicts()

    writes = store.execute(
        "SELECT id, kind, employee_id, created_at, turn_id, payload_json FROM mock_writes "
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
                payload=json.loads(row["payload_json"] or "{}"),
            )
            for row in writes
        ],
    )


# --------------------------------------------------------------------------------------
# Page 9 — the live MCP catalog
# --------------------------------------------------------------------------------------


def _handshake_history(store: Store) -> list[HandshakeRow]:
    spans = _payloads(
        store.execute(
            "SELECT id, turn_id, payload_json FROM spans WHERE kind = 'mcp_discovery' ORDER BY started_at DESC LIMIT 25"
        ).dicts()
    )
    return [
        HandshakeRow(
            span_id=span["id"],
            turn_id=span["turn_id"],
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


def _dataset_labels() -> dict[str, tuple[str | None, str | None]]:
    """`item_id → (question, gold_answer_short)` from `evaluation/dataset.yaml` (§13.1).

    The dataset is a P10 deliverable. Until it exists the two columns are empty rather than
    fabricated from the stored answer, which would make the page agree with itself by construction.
    """
    if not DATASET_PATH.exists():
        return {}
    try:
        import yaml

        document = yaml.safe_load(DATASET_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("could not read %s", DATASET_PATH, exc_info=True)
        return {}
    items = document.get("items") if isinstance(document, dict) else document
    labels: dict[str, tuple[str | None, str | None]] = {}
    for item in items or []:
        if isinstance(item, dict) and item.get("id"):
            labels[str(item["id"])] = (item.get("question"), item.get("gold_answer_short"))
    return labels


def _run_row(row: dict[str, Any]) -> EvalRunRow:
    metrics = EvalMetrics.model_validate(json.loads(row["metrics_json"] or "{}"))
    return EvalRunRow(
        run_id=row["id"],
        label=row["label"],
        variant=row["variant"],
        target=row["target"],
        git_sha=row["git_sha"],
        created_at=int(row["created_at"]),
        n_items=int(row["n_items"] or 0),
        headline={name: getattr(metrics, name) for name in HEADLINE_METRICS},
        judged=metrics.judged,
        judge_model=row["judge_model"],
        duration_s=row["duration_s"],
        est_cost_usd=metrics.est_cost_usd,
    )


RUN_COLUMNS = "id, created_at, git_sha, label, variant, target, n_items, metrics_json, judge_model, duration_s"


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
            )
        )
    if filters.failures_first:
        items.sort(key=lambda item: (item.passed, item.item_id))
    return EvalRunDetailView(
        run=_run_row(run),
        metrics=EvalMetrics.model_validate(json.loads(run["metrics_json"] or "{}")),
        items=items,
        latency=_latency_block(store, rows),
        rss_series=_rss_series(store, rows),
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
    api_url: str,
    filters: Filters | None = None,
    **extra: Any,
) -> Response:
    """Render the page from the **same dict** the matching `/api/*` route returns."""
    payload = view.model_dump(mode="json")
    context = {
        "view": payload,
        "page_number": page_number,
        "page_title": title,
        "api_url": api_url,
        "nav": NAV,
        "detail_only_pages": DETAIL_ONLY_PAGES,
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
    return _page(request, "overview.html", view, page_number=1, title="Overview", api_url="/api/traces/overview")


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
        api_url=f"/api/traces/sessions?{filters.query_string()}",
        filters=filters,
        pages=max(1, math.ceil(view.total / PAGE_SIZE)),
    )


# -- page 3 --------------------------------------------------------------------------------


@router.get("/api/traces/sessions/{session_id}")
async def api_session_detail(request: Request, session_id: str) -> JSONResponse:
    return _json(build_session_detail(request, session_id))


@router.get("/dashboard/sessions/{session_id}", response_class=HTMLResponse)
async def page_session_detail(request: Request, session_id: str) -> Response:
    view = build_session_detail(request, session_id)
    longest = max((turn.duration_ms or 0) for turn in view.turns) if view.turns else 0
    return _page(
        request,
        "session_detail.html",
        view,
        page_number=3,
        title=f"Session {session_id[:12]}…",
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
        title="LLM calls",
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
        title="Safety",
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
    return _page(request, "mcp.html", view, page_number=9, title="MCP catalog", api_url="/api/mcp/discovery")


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


@router.get("/dashboard/corpus", response_class=HTMLResponse)
async def page_corpus(request: Request) -> Response:
    filters = Filters.from_request(request)
    return _page(
        request,
        "corpus.html",
        build_corpus(filters),
        page_number=10,
        title="Corpus",
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
        api_url=f"/api/eval/runs?{filters.query_string()}",
        filters=filters,
        compare=build_eval_compare(request).model_dump(mode="json"),
        judged_metrics=JUDGED_METRICS,
        deterministic_metrics=DETERMINISTIC_METRICS,
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
        title=f"Run {view.run.variant}",
        api_url=f"/api/eval/runs/{run_id}",
        filters=filters,
        headline_metrics=HEADLINE_METRICS,
        judged_metrics=JUDGED_METRICS,
        deterministic_metrics=DETERMINISTIC_METRICS,
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
