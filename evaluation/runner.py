"""The harness (spec §13.2, §13.5, §13.10). `make eval` is `python -m evaluation.runner --variant baseline`.

Every item is one `POST {EVAL_TARGET_BASE_URL}/chat` carrying `client_label: "eval"`, the headers
`Authorization: Bearer $APP_ACCESS_TOKEN` and `X-Actor: admin`, and
`options: {k, retrieval_strategy, tools_disabled, eval_run_id, variant}`. **That is the only
configuration channel** — no process restart, no env mutation between variants and no global
`remove_tool` on the shared server (§13.2). So each item produces a real session and turn,
`sessions.eval_run_id` is populated, and every `eval_results` row links straight back to its audit
trace.

Items run **strictly sequentially**, in `dataset.yaml`'s file order, with exponential backoff
honouring `Retry-After`; the judge calls behind them are paced by the process-wide token bucket of
`core/llm/limiter.py`.

**Warm-up, then the cold probes.** The runner discards a `/health`, sends one throwaway `/chat` and
polls `/health` until `app.uptime_ms ≥ 60000`, so all 26 scored turns are warm by construction and
the warm-up turn is never written to `eval_results`. The three cold samples are re-runs of
`pto-001`, `remote-001` and `benefits-001` after an `EVAL_COLD_IDLE_S` idle; each **asserts
`process_uptime_ms < 60000` before tagging `cold = 1`**, never by construction, and records the
honest observation when the instance stayed warm.

**`latest.json` is written only for a `deployed` `baseline` run.** A local run is plumbing and
determinism evidence; it can never be promoted into the headline figures a grader reads, and
`tests/unit/test_latest_points_at_deployed.py` asserts that.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from evaluation import deterministic as det
from evaluation.judges import VERDICT_SCORES, Claim, EvidenceItem, Judge
from evaluation.schema import (
    AGREEMENT_METRICS,
    COLD_PROBE_IDS,
    REPORT_PATH,
    RESULTS_DIR,
    VARIANT_OPTIONS,
    AgreementMetric,
    Dataset,
    EvalItem,
    ItemResult,
    ReferenceLabels,
    RunConfig,
    RunFile,
    RunMetrics,
    load_dataset,
    load_reference_labels,
)
from hrmosaic.core import archive, corpusread
from hrmosaic.core import trace as trace_module
from hrmosaic.core.db import Store, get_store, migrate, now_micros
from hrmosaic.core.ids import SEED, new_session_id
from hrmosaic.core.models import ENVELOPE_KINDS as _ENVELOPE_KINDS
from hrmosaic.core.trace import SessionSpec, TraceWriter, TurnBuffer
from hrmosaic.settings import Settings, secret_value
from hrmosaic.settings import settings as default_settings

logger = logging.getLogger(__name__)

#: A whole turn may take `AGENT_WALL_CLOCK_S`; the client waits past it rather than tearing down a
#: turn the server is still writing.
HTTP_TIMEOUT_S = 240.0

#: The `POST /chat` retry ladder: 429 and 5xx only, honouring `Retry-After`.
MAX_HTTP_RETRIES = 3
BACKOFF_BASE_S = 2.0

#: §13.5's cold/warm boundary.
COLD_UPTIME_MS = 60_000

#: How long the warm-up poll waits for `app.uptime_ms` to clear the boundary.
WARMUP_POLL_TIMEOUT_S = 90.0

#: The claim→block mapping floor. A decomposed claim inherits the citations of the answer block it
#: overlaps most; below this Jaccard floor it inherits none, so `CitPrecision`'s denominator holds
#: only claims that really do carry citations (§13.3).
CLAIM_BLOCK_MATCH_FLOOR = 0.25

_WORD = re.compile(r"[a-z0-9]+")


# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------


@dataclass
class RunOptions:
    """One invocation of the harness."""

    variant: str = "baseline"
    base_url: str = ""
    label: str = ""
    judge: bool = True
    item_ids: list[str] = field(default_factory=list)
    n_items: int | None = None
    cold_probes: bool = False
    notes: str | None = None
    results_dir: Path = RESULTS_DIR
    write_report: bool = True


class BadTargetUrl(ValueError):
    """A target base URL that is empty or schemeless — named at the door, not a traceback later."""


def require_base_url(base_url: str) -> str:
    """Reject an empty or schemeless target before a single request is built.

    `EVAL_TARGET_BASE_URL="$DEPLOY_URL" make eval` with `DEPLOY_URL` unset used to reach `httpx`
    and die in `httpx.UnsupportedProtocol: Request URL is missing an 'http://' or 'https://'
    protocol` — and, worse, `resolve_target("")` labelled that run `deployed`, because an empty URL
    has no loopback host, so a run that never happened could have been filed as the published one.
    Both are impossible now. Same guard, same wording, as `scripts/wait_for_deploy.py` and
    `scripts/smoke_deployed.py` (P11).
    """
    url = (base_url or "").strip()
    if not url:
        raise BadTargetUrl(
            "EVAL_TARGET_BASE_URL is empty. That is usually "
            'EVAL_TARGET_BASE_URL="$DEPLOY_URL" with DEPLOY_URL unset — see NEEDS-FROM-USER.md '
            "(gates 2 and 4), then run scripts/provision_render.py."
        )
    if not url.startswith(("http://", "https://")):
        raise BadTargetUrl(f"EVAL_TARGET_BASE_URL {url!r} has no http:// or https:// scheme; it is not a base URL.")
    return url


def resolve_target(base_url: str) -> str:
    """`local` for a loopback URL, `deployed` for anything else (§13.2)."""
    host = httpx.URL(base_url).host
    return "local" if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0") else "deployed"


#: `RunConfig.llm_rpm` is read from the **harness's** settings, so a sweep driven against a remote
#: target publishes the rate this process was paced at while the latency it measured was produced
#: under the *service's* `LLM_RPM`. Since 2026-09-10 those are different numbers — the code default
#: is 10 and the Render service is configured at 60/30 — so a `deployed` run has to say so rather
#: than let a reader take `config.llm_rpm` for the rate behind `latency_p50_ms`. The service's
#: effective rate cannot be read back from `/health` (§11.4 publishes no limiter settings) and the
#: environment is not ours to introspect, so the note records it as unknown by name.
REMOTE_RATE_NOTE = (
    "config.llm_rpm is this harness's rate, not the target's: the run was driven against a remote "
    "service whose own LLM_RPM/LLM_BURST are set in its environment (effective target rate: "
    "unknown; service env). The latency in this run was produced under the target's rate (§9.4)."
)

#: What the publish gate refuses, and why each one invalidates a run rather than merely annotating
#: it. `core/llm/base.py` puts 429 in `RETRYABLE_STATUSES` and escalates to `LLM_FALLBACK_MODEL`, so
#: a paced or rate-limited sweep can answer some of its items on `gemini-3.5-flash-lite` while
#: `config.llm_model` still reads `claude-haiku-4-5` — §9.8's pin, violated silently. A retry is the
#: same problem one step earlier: it adds a backoff and a second round trip to the turn whose
#: latency the run publishes. Neither is anywhere in the run file; both are on the `llm_call` spans.
CONTAMINATION_SQL = """
SELECT json_extract(payload_json, '$.model')             AS model,
       json_extract(payload_json, '$.provider_failover') AS failover,
       json_extract(payload_json, '$.retry_count')       AS retries
FROM spans
WHERE kind = 'llm_call' AND turn_id IN ({placeholders})
"""


def contamination_findings(run: RunFile, *, store: Store | None = None) -> list[str]:
    """Why this run must not be published, one line per cause; empty means it is clean (W1-A).

    Only the items' own turns are read. The judge's calls hang off the synthetic `eval_judge`
    session of §13.2 and are a different model on purpose, so scoping to the item turns is what
    lets the pin be checked against the agent's own calls without tripping over the judge's.

    **Absent spans are silence, not a green light.** A committed run file carried to another machine
    has no spans in that machine's store, and a store this process cannot open is not a verdict
    either: both return no findings and say so in the log. The gate proves contamination; it cannot
    prove the absence of it from rows that are not there.
    """
    turn_ids = [item.turn_id for item in run.items if item.turn_id]
    if not turn_ids:
        logger.warning("no turn ids on %s: its spans cannot be checked for contamination", run.run_id)
        return []
    try:
        store = store or get_store()
        rows = store.execute(
            CONTAMINATION_SQL.format(placeholders=", ".join("?" for _ in turn_ids)), tuple(turn_ids)
        ).dicts()
    except Exception:
        logger.warning("could not read the spans of %s; contamination is unchecked", run.run_id, exc_info=True)
        return []
    if not rows:
        logger.warning("no llm_call spans for %s in this store; contamination is unchecked", run.run_id)
        return []

    findings: list[str] = []
    failovers = sum(1 for row in rows if row["failover"])
    if failovers:
        findings.append(
            f"{failovers} of {len(rows)} llm_call spans failed over to the fallback provider: the run "
            "answered some items on a model §9.8 does not pin"
        )
    retried = sum(1 for row in rows if int(row["retries"] or 0) > 0)
    if retried:
        findings.append(
            f"{retried} of {len(rows)} llm_call spans carry retry_count > 0: a backoff and a second "
            "round trip are inside the latency this run publishes"
        )
    strays = sorted({str(row["model"]) for row in rows if row["model"] and row["model"] != run.config.llm_model})
    if strays:
        findings.append(f"llm_call spans name {', '.join(strays)}, not the pinned {run.config.llm_model}")
    return findings


def run_id_for(variant: str, *, at: int | None = None) -> str:
    """`r_<epoch seconds>_<variant>` — sortable, and it names the arm in the filename."""
    return f"r_{int((at or now_micros()) / 1_000_000)}_{variant}"


# --------------------------------------------------------------------------------------
# The HTTP client
# --------------------------------------------------------------------------------------


class TargetClient:
    """`POST /chat` and friends against the target, with the eval headers on every request."""

    def __init__(self, base_url: str, *, settings: Settings) -> None:
        self.base_url = base_url.rstrip("/")
        self._settings = settings
        headers = {"X-Actor": "admin", "Content-Type": "application/json"}
        token = secret_value(settings.app_access_token)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=HTTP_TIMEOUT_S)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        response = await self._client.get("/health")
        return response.json()

    async def _post(self, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """One POST with the §13.2 backoff: 429 and 5xx, honouring `Retry-After`."""
        for attempt in range(MAX_HTTP_RETRIES):
            response = await self._client.post(path, json=dict(body))
            if response.status_code < 400:
                return response.json()
            if response.status_code in (429,) or response.status_code >= 500:
                delay = _retry_after(response.headers) or BACKOFF_BASE_S * (2**attempt)
                logger.warning("%s answered %s; retrying in %.1fs", path, response.status_code, delay)
                await asyncio.sleep(delay)
                continue
            raise RuntimeError(f"{path} answered {response.status_code}: {response.text[:400]}")
        raise RuntimeError(f"{path} did not succeed after {MAX_HTTP_RETRIES} attempts")

    async def chat(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self._post("/chat", body)

    async def confirm(self, *, session_id: str, turn_id: str, decision: str) -> dict[str, Any]:
        return await self._post("/chat/confirm", {"session_id": session_id, "turn_id": turn_id, "decision": decision})


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------


@dataclass
class ScoredItem:
    """One item's result plus the per-item numbers the aggregation needs."""

    result: ItemResult
    item: EvalItem
    turn: det.TurnRecord | None
    gold_behavior: str
    predicted_behavior: str | None
    tool: det.ToolScores
    doc_recall: float | None
    workflow: float | None
    groundedness: float | None
    citation_accuracy: float | None
    partial_match: float | None
    clarification: float | None
    cost_usd: float


class Runner:
    """One variant over one target. Constructed per run; never reused across variants."""

    def __init__(
        self,
        options: RunOptions,
        *,
        settings: Settings | None = None,
        store: Store | None = None,
        dataset: Dataset | None = None,
        judge: Judge | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.options = options
        self.options.base_url = require_base_url(options.base_url or self.settings.eval_target_base_url)
        self.dataset = dataset or load_dataset()
        self.target = resolve_target(self.options.base_url)
        self.run_id = run_id_for(options.variant)
        self.store = store or get_store(self.settings)
        self.client = TargetClient(self.options.base_url, settings=self.settings)
        self._judge_enabled = options.judge and options.variant == "baseline"
        self.judge = (
            judge
            if judge is not None
            else (Judge(run_id=self.run_id, settings=self.settings) if self._judge_enabled else None)
        )
        self._judge_session_id: str | None = None
        self._writer: TraceWriter | None = None
        self.notes: list[str] = [options.notes] if options.notes else []
        if self.target != "local":
            self.notes.append(REMOTE_RATE_NOTE)

    # -- lifecycle ---------------------------------------------------------------------

    async def aclose(self) -> None:
        await self.client.aclose()

    def _judge_writer(self) -> TraceWriter:
        """The writer the judge spans go through — `core/trace.py`, like every other span."""
        if self._writer is None:
            self._writer = trace_module.get_writer()
        return self._writer

    def _judge_session(self) -> SessionSpec:
        """The synthetic `eval_judge` session of §13.2, one per run."""
        if self._judge_session_id is None:
            self._judge_session_id = new_session_id()
        return SessionSpec(
            id=self._judge_session_id,
            employee_id=None,
            auth_mode="open",
            actor_role="admin",
            client_label="eval_judge",
            eval_run_id=self.run_id,
        )

    async def assert_store_matches_target(self) -> None:
        """§13.2: in `deployed` mode the runner must write judge spans where the app writes."""
        if self.target != "deployed":
            return
        health = await self.client.health()
        backend = (health.get("trace_store") or {}).get("backend")
        if backend and backend != self.store.backend:
            raise SystemExit(
                f"the runner's trace store is '{self.store.backend}' but the target reports "
                f"'{backend}'. Configure the same database before a deployed run (§13.2)."
            )

    # -- warm-up (§13.5) ----------------------------------------------------------------

    async def warm_up(self) -> None:
        """A discarded `/health`, one throwaway `/chat`, then a poll until the target is warm."""
        await self.client.health()
        await self.client.chat(
            {
                "message": "Warm-up: list the policy topics you cover.",
                "employee_id": "E1042",
                "client_label": "eval",
                "options": {"eval_run_id": f"{self.run_id}:warmup", "variant": self.options.variant},
            }
        )
        deadline = time.monotonic() + WARMUP_POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            health = await self.client.health()
            if int((health.get("app") or {}).get("uptime_ms") or 0) >= COLD_UPTIME_MS:
                return
            await asyncio.sleep(5.0)
        self.notes.append(
            f"warm-up poll gave up after {WARMUP_POLL_TIMEOUT_S:.0f}s below the {COLD_UPTIME_MS} ms "
            "uptime boundary; per-turn `cold` flags are still read from `turns.process_uptime_ms`."
        )

    # -- one item ------------------------------------------------------------------------

    def _options_for(self, item: EvalItem) -> dict[str, Any]:
        options = dict(VARIANT_OPTIONS[self.options.variant])
        options["eval_run_id"] = self.run_id
        options["variant"] = self.options.variant
        return options

    async def _drive(self, item: EvalItem) -> dict[str, Any]:
        """One `POST /chat`, plus the auto-confirm resume when the item asks for one."""
        response = await self.client.chat(
            {
                "message": item.question,
                "employee_id": item.persona,
                "client_label": "eval",
                "options": self._options_for(item),
            }
        )
        if response.get("outcome") == "awaiting_confirmation" and item.confirm_on_prompt:
            response = await self.client.confirm(
                session_id=response["session_id"], turn_id=response["turn_id"], decision="confirmed"
            )
        return response

    async def score_item(self, item: EvalItem, *, run_phase: str = "scored") -> ScoredItem:
        """Drive one item, then score it deterministically and (on `baseline`) judge it."""
        response = await self._drive(item)
        turn = det.read_turn(self.store, response["turn_id"])
        return await self._score(item, response, turn, run_phase=run_phase)

    async def _score(
        self,
        item: EvalItem,
        response: Mapping[str, Any],
        turn: det.TurnRecord | None,
        *,
        run_phase: str,
    ) -> ScoredItem:
        verdicts: dict[str, Any] = {}
        if turn is None:
            # The turn row is not visible to this store: `deployed` mode with the wrong database, or
            # a target that failed to persist. Recorded honestly rather than scored.
            self.notes.append(f"{item.id}: no turn row found for {response.get('turn_id')}; scored as unavailable")
            usage = det.ToolUsage(called=[], gated=[], failed=[], ok_spans=[])
            tool = det.tool_scores(item, usage)
            result = ItemResult(
                id=f"{self.run_id}::{item.id}",
                item_id=item.id,
                category=item.category,
                session_id=response.get("session_id"),
                turn_id=response.get("turn_id"),
                run_phase=run_phase,  # type: ignore[arg-type]
                answer=response.get("answer"),
                latency_ms=None,
                cold=0,
                scores={"unavailable": True},
                verdicts=None,
                passed=0,
            )
            return ScoredItem(
                result=result,
                item=item,
                turn=None,
                gold_behavior=item.expected_behavior,
                predicted_behavior=None,
                tool=tool,
                doc_recall=None,
                workflow=None,
                groundedness=None,
                citation_accuracy=None,
                partial_match=None,
                clarification=None,
                cost_usd=0.0,
            )

        usage = det.tool_usage(turn)
        tool = det.tool_scores(item, usage)
        cit_resolve = det.citation_resolvability(turn.citations, expects_citations=item.expects_citations)
        doc_recall = det.document_recall(det.retrieved_doc_ids(turn), item.expected_docs)
        workflow = det.workflow_completion(item, turn, usage)
        safety = 0.0 if det.action_safety_violations(self.store, turn_id=turn.turn_id) else 1.0
        predicted = det.behaviour_class(turn.outcome)
        valid_args, total_args = det.argument_correctness(item, usage)
        blocks_dropped = det.blocks_dropped_by_g2(turn)

        groundedness: float | None = None
        citation_accuracy: float | None = None
        partial_match: float | None = None
        clarification: float | None = None
        recommendation_labeled: float | None = None
        contradicted = False
        if self.judge is not None and run_phase == "scored":
            judged = await self._judge_item(item, turn)
            groundedness = judged["groundedness"]
            citation_accuracy = None if judged["cit_f1"] is None else cit_resolve * judged["cit_f1"]
            partial_match = judged["partial_match"]
            clarification = judged["clarification"]
            recommendation_labeled = judged["recommendation_labeled_rate"]
            contradicted = judged["contradicted"]
            verdicts = judged["verdicts"]

        scores = {
            "groundedness": groundedness,
            "groundedness_pass": None
            if groundedness is None
            else bool(groundedness >= det.GROUNDEDNESS_PASS and not contradicted),
            "cit_resolve": cit_resolve,
            "citation_accuracy": citation_accuracy,
            "doc_recall": doc_recall,
            "exact_match": det.exact_match(item.gold_answer_short, turn.final_answer),
            "partial_match": partial_match,
            "clarification": clarification,
            "tool_recall": tool.recall,
            "tool_precision": tool.precision,
            "tool_selection": tool.selection,
            "arg_correctness": None if total_args == 0 else valid_args / total_args,
            "workflow": workflow,
            "behavior": None if predicted is None else float(predicted == item.expected_behavior),
            "safety": safety,
            "blocks_dropped_by_g2": blocks_dropped,
            "gated_attempts": len(usage.gated),
            "nudged": det.nudged(turn),
            "catalog_reopened": det.catalog_reopened(turn),
            "router_intent": det.router_intent(turn),
            "recommendation_labeled_rate": recommendation_labeled,
            "outcome": turn.outcome,
            "tools_called": usage.called,
            "cache_hits": det.cache_hits(turn),
        }
        if item.asserts_injection_quarantined:
            scores["injection_quarantined"] = det.injection_quarantined(turn)

        passed = det.strict_pass(
            groundedness=groundedness,
            blocks_dropped=blocks_dropped,
            tool=tool,
            workflow=workflow,
            safety=safety,
            behaviour_correct=predicted == item.expected_behavior,
        )
        result = ItemResult(
            id=f"{self.run_id}::{item.id}" + ("::cold" if run_phase == "cold_probe" else ""),
            item_id=item.id,
            category=item.category,
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            run_phase=run_phase,  # type: ignore[arg-type]
            answer=turn.final_answer,
            latency_ms=turn.duration_ms,
            cold=int(turn.cold),
            scores=scores,
            verdicts=verdicts or None,
            passed=int(passed),
        )
        return ScoredItem(
            result=result,
            item=item,
            turn=turn,
            gold_behavior=item.expected_behavior,
            predicted_behavior=predicted,
            tool=tool,
            doc_recall=doc_recall,
            workflow=workflow,
            groundedness=groundedness,
            citation_accuracy=citation_accuracy,
            partial_match=partial_match,
            clarification=clarification,
            cost_usd=det.turn_cost_usd(turn),
        )

    # -- the judged half (§13.3, baseline only) -----------------------------------------

    async def _judge_item(self, item: EvalItem, turn: det.TurnRecord) -> dict[str, Any]:
        """Decompose, ground each policy claim, check the cited support, entail the gold facts."""
        assert self.judge is not None
        empty: dict[str, Any] = {
            "groundedness": None,
            "cit_f1": None,
            "partial_match": None,
            "clarification": None,
            "recommendation_labeled_rate": None,
            "contradicted": False,
            "verdicts": {},
        }
        buffer = self._judge_writer().start_turn(
            self._judge_session(), user_message=f"judge {item.id} ({turn.turn_id})"
        )
        try:
            return await self._judge_with(item, turn, buffer, empty)
        finally:
            buffer.close(outcome="answered", stop_reason="answered", intent="judge")

    async def _judge_with(
        self,
        item: EvalItem,
        turn: det.TurnRecord,
        buffer: TurnBuffer,
        empty: dict[str, Any],
    ) -> dict[str, Any]:
        verdicts: dict[str, Any] = {}
        result = dict(empty)

        # The clarification sub-check is the only judged metric on a turn with no answer text.
        if item.category == "ambiguous" and item.clarification_expects:
            named = await self.judge.clarification_names_missing(  # type: ignore[union-attr]
                missing=item.clarification_expects,
                question=turn.final_answer,
                item_id=item.id,
                scored_turn_id=turn.turn_id,
                turn=buffer,
            )
            result["clarification"] = None if named is None else float(named)
            verdicts["clarification"] = {
                "named_missing_information": named,
                "judge_model": self.judge.model_name,  # type: ignore[union-attr]
            }

        if turn.outcome not in ("answered", "partial") or not turn.final_answer.strip():
            result["verdicts"] = verdicts
            return result

        claims = await self.judge.decompose(  # type: ignore[union-attr]
            turn.final_answer, item_id=item.id, scored_turn_id=turn.turn_id, turn=buffer
        )
        if claims:
            recommendations = sum(1 for claim in claims if claim.kind == "recommendation")
            result["recommendation_labeled_rate"] = recommendations / len(claims)

        evidence = _evidence_of(turn)
        policy_claims = [claim for claim in claims if claim.kind == "policy_claim"]
        citations_by_claim = _citations_by_claim(claims, turn.answer_blocks)
        # Only chunk ids can be cited, so the citation-support pass indexes the retrieval class
        # alone: a tool envelope has no id an answer could ever name.
        chunk_text = {item.id: item for item in evidence if item.kind == "retrieval"}

        verdict_by_claim: dict[str, str] = {}
        scores: list[float] = []
        for claim in policy_claims:
            verdict = await self.judge.groundedness(  # type: ignore[union-attr]
                evidence=evidence,
                claim=claim.text,
                item_id=item.id,
                scored_turn_id=turn.turn_id,
                turn=buffer,
            )
            if verdict is None:
                continue
            verdict_by_claim[claim.id] = verdict
            scores.append(VERDICT_SCORES[verdict])
        if scores:
            result["groundedness"] = min(1.0, max(0.0, sum(scores) / len(scores)))
            result["contradicted"] = any(verdict == "contradicted" for verdict in verdict_by_claim.values())

        # Citation support: `CitPrecision` over the claims that carry citations, `CitRecall` over
        # the claims the groundedness pass called `supported` (§13.3).
        supported_with_citations = 0
        cited_claims = 0
        upheld = 0
        for claim in policy_claims:
            cited = [
                chunk_text[chunk_id] for chunk_id in citations_by_claim.get(claim.id, []) if chunk_id in chunk_text
            ]
            if not cited:
                continue
            cited_claims += 1
            ok = await self.judge.citation_support(  # type: ignore[union-attr]
                cited=cited,
                claim=claim.text,
                item_id=item.id,
                scored_turn_id=turn.turn_id,
                turn=buffer,
            )
            if ok:
                upheld += 1
            if verdict_by_claim.get(claim.id) == "supported":
                supported_with_citations += 1
        supported_total = sum(1 for verdict in verdict_by_claim.values() if verdict == "supported")
        if cited_claims or supported_total:
            precision = upheld / cited_claims if cited_claims else 0.0
            recall = supported_with_citations / supported_total if supported_total else 0.0
            result["cit_f1"] = det.f1(precision, recall)
            verdicts["citation_support"] = {
                "precision": round(precision, 3),
                "recall": round(recall, 3),
                "n_cited_claims": cited_claims,
                "judge_model": self.judge.model_name,  # type: ignore[union-attr]
            }

        if item.gold_facts:
            entailed: list[float] = []
            for key in item.gold_facts:
                fact = _fact_sentence(key)
                answer = await self.judge.entailed(  # type: ignore[union-attr]
                    fact=fact,
                    answer=turn.final_answer,
                    item_id=item.id,
                    scored_turn_id=turn.turn_id,
                    turn=buffer,
                )
                if answer is not None:
                    entailed.append(float(answer))
            if entailed:
                result["partial_match"] = sum(entailed) / len(entailed)

        verdicts["groundedness"] = {
            "score": result["groundedness"],
            "n_claims": len(policy_claims),
            "n_scored": len(scores),
            "per_claim": verdict_by_claim,
            "judge_model": self.judge.model_name,  # type: ignore[union-attr]
        }
        result["verdicts"] = verdicts
        return result

    # -- the whole run -------------------------------------------------------------------

    async def run(self) -> RunFile:
        started = time.monotonic()
        await self.assert_store_matches_target()
        await self.warm_up()

        items = self.dataset.select(self.options.item_ids or None, self.options.n_items)
        scored: list[ScoredItem] = []
        for index, item in enumerate(items, start=1):
            logger.info("[%s] %d/%d %s", self.options.variant, index, len(items), item.id)
            scored.append(await self.score_item(item))

        if self.options.cold_probes:
            scored.extend(await self._cold_probes())

        run = self.assemble(scored, duration_s=time.monotonic() - started)
        self.write_artifacts(run)
        return run

    async def _cold_probes(self) -> list[ScoredItem]:
        """§13.5's three cold samples: idle, re-run, and **assert** the uptime before tagging."""
        probes: list[ScoredItem] = []
        for item_id in COLD_PROBE_IDS:
            item = self.dataset.by_id(item_id)
            if item is None:
                continue
            for attempt in range(2):
                logger.info("cold probe %s: idling %ss", item_id, self.settings.eval_cold_idle_s)
                await asyncio.sleep(self.settings.eval_cold_idle_s)
                result = await self.score_item(item, run_phase="cold_probe")
                if result.turn is not None and result.turn.cold:
                    probes.append(result)
                    break
                observed = result.turn.process_uptime_ms if result.turn else -1
                if attempt == 0:
                    logger.info("cold probe %s came back warm (uptime %sms); retrying once", item_id, observed)
                    continue
                self.notes.append(
                    f"cold probe {item_id}: still warm after two attempts "
                    f"(process_uptime_ms={observed}); recorded with cold=0."
                )
                probes.append(result)
        return probes

    def assemble(self, scored: Sequence[ScoredItem], *, duration_s: float) -> RunFile:
        """Every §13.4 denominator filters `run_phase = 'scored'` — cold probes never enter one."""
        run_phase_scored = [entry for entry in scored if entry.result.run_phase == "scored"]
        cold_rows = [entry for entry in scored if entry.result.cold]

        pairs = [
            (entry.gold_behavior, entry.predicted_behavior)
            for entry in run_phase_scored
            if entry.predicted_behavior is not None
        ]
        excluded = len(run_phase_scored) - len(pairs)
        over_rate, over_n = det.over_refusal_rate(pairs)
        missed_rate, missed_n = det.missed_refusal_rate(pairs)

        groundedness = [entry.groundedness for entry in run_phase_scored if entry.groundedness is not None]
        cit_accuracy = [entry.citation_accuracy for entry in run_phase_scored if entry.citation_accuracy is not None]
        partial = [entry.partial_match for entry in run_phase_scored if entry.partial_match is not None]
        clarification = [entry.clarification for entry in run_phase_scored if entry.clarification is not None]
        cit_resolve = [entry.result.scores.get("cit_resolve") for entry in run_phase_scored]
        cit_resolve = [value for value in cit_resolve if value is not None]
        doc_recall = [entry.doc_recall for entry in run_phase_scored if entry.doc_recall is not None]
        workflow = [entry.workflow for entry in run_phase_scored if entry.workflow is not None]
        selection = [entry.tool.selection for entry in run_phase_scored]
        arg_rates = [
            entry.result.scores.get("arg_correctness")
            for entry in run_phase_scored
            if entry.result.scores.get("arg_correctness") is not None
        ]
        safety = [float(entry.result.scores.get("safety") or 0.0) for entry in run_phase_scored]
        recommendation = [
            entry.result.scores.get("recommendation_labeled_rate")
            for entry in run_phase_scored
            if entry.result.scores.get("recommendation_labeled_rate") is not None
        ]

        by_workflow: dict[str, float] = {}
        for entry in run_phase_scored:
            if entry.item.workflow and entry.workflow is not None:
                by_workflow[entry.item.workflow] = entry.workflow

        router: dict[str, dict[str, int]] = {}
        for entry in run_phase_scored:
            intent = entry.result.scores.get("router_intent")
            if intent:
                bucket = router.setdefault(entry.item.category, {})
                bucket[intent] = bucket.get(intent, 0) + 1

        latencies = [
            float(entry.result.latency_ms)
            for entry in run_phase_scored
            if entry.result.latency_ms is not None and not entry.result.cold
        ]
        by_kind: dict[str, int] = {"llm_ms": 0, "retrieval_ms": 0, "tool_ms": 0, "store_ms": 0}
        for entry in run_phase_scored:
            if entry.turn is None:
                continue
            by_kind["llm_ms"] += entry.turn.llm_ms
            by_kind["retrieval_ms"] += entry.turn.retrieval_ms
            by_kind["tool_ms"] += entry.turn.tool_ms
            by_kind["store_ms"] += entry.turn.store_ms

        agreement_rate, agreement_n, disagreements = (None, 0, [])
        labels = load_reference_labels()
        if labels is not None and self._judge_enabled:
            agreement_rate, agreement_n, disagreements = det.judge_agreement(
                labels.labels,
                {entry.item.id: entry.groundedness for entry in run_phase_scored},
            )
            if disagreements:
                self.notes.append(
                    "judge/reference disagreements: "
                    + "; ".join(
                        f"{row['item_id']} (reference {row['reference']}, judge {row['judge']})"
                        for row in disagreements
                    )
                )

        # §13.4's over-refusal discussion: a turn that refused for want of evidence while holding
        # the deterministic engine's own, resolvable citations. G1 weighs `turn.citable()` — the
        # retrieved chunks — and `check_policy_compliance`'s `citations[]` are not in it, although
        # the synthesis prompt carries the whole result. Counted, named, and left alone: changing
        # what G1 counts is a guardrail change, not an evaluation one.
        engine_only_refusals = [
            entry.item.id
            for entry in run_phase_scored
            if entry.predicted_behavior == "refuse"
            and entry.gold_behavior == "answer"
            and entry.turn is not None
            and det.compliance_evidence_ids(entry.turn)
            and not det.retrieved_doc_ids(entry.turn)
        ]
        if engine_only_refusals:
            self.notes.append(
                f"Over-refusal cause, {len(engine_only_refusals)} item(s) — {', '.join(engine_only_refusals)}: "
                "the turn refused with `no policy evidence was retrieved` while `check_policy_compliance` "
                "had already returned a decided verdict whose citations resolve to real chunks of the "
                "committed index. G1's evidence gate weighs the retrieved chunks only, so the engine's "
                "own evidence — which the synthesis prompt does carry — cannot clear it. Counting "
                "compliance-resolved chunks as citable evidence for G1 is a candidate P11/P12 fix."
            )

        cache_hit_total = sum(int(entry.result.scores.get("cache_hits") or 0) for entry in run_phase_scored)
        if cache_hit_total:
            self.notes.append(
                f"{cache_hit_total} llm_call span(s) reported cache_hit=true; §13.5 requires "
                "LLM_CACHE_TTL_S=0 during latency measurement."
            )
        injection = next(
            (
                entry.result.scores.get("injection_quarantined")
                for entry in run_phase_scored
                if entry.item.asserts_injection_quarantined
            ),
            None,
        )
        discovery = [det.tool_discovery_ok(entry.turn) for entry in run_phase_scored if entry.turn is not None]
        discovery_ok = (
            None
            if not any(value is not None for value in discovery)
            else all(value for value in discovery if value is not None)
        )

        # §13.9 judges `baseline` only, so an ablation arm is never "pending" — it is complete as
        # it stands. A baseline is `judged` only when the pass actually ran AND every verdict came
        # back: one `failures` is one item whose groundedness clause is unscored, which is exactly
        # the case the composite must not report a number for.
        judge_failures = self.judge.failures if self.judge is not None else 0
        judge_status = "not_applicable"
        if self.options.variant == "baseline":
            judge_status = "judged" if (self._judge_enabled and judge_failures == 0) else "pending"

        metrics = RunMetrics(
            judged=self._judge_enabled and judge_failures == 0,
            groundedness_mean=det.mean(groundedness),
            citation_accuracy_mean=det.mean(cit_accuracy),
            partial_match_mean=det.mean(partial),
            clarification_accuracy=det.mean(clarification),
            cit_resolve_mean=det.mean(cit_resolve),
            blocks_dropped_by_g2=sum(
                int(entry.result.scores.get("blocks_dropped_by_g2") or 0) for entry in run_phase_scored
            ),
            tool_selection_accuracy=det.mean(selection),
            arg_correctness_rate=det.mean(arg_rates),
            # §13.8's composite is published only when the judged half is complete. Every clause
            # of `strict_pass` is *vacuously* true for an item that does not define it, so a run
            # whose groundedness was never scored would report a composite that looks high
            # precisely because nothing was checked. `judge_status` says which case this is and
            # `render_report` prints "not computable — judge pending" rather than a number.
            strict_pass_rate=(
                None
                if judge_status == "pending"
                else det.mean([float(entry.result.passed) for entry in run_phase_scored])
            ),
            escalation_matrix=det.escalation_matrix(pairs),
            escalation_n_excluded=excluded,
            over_refusal_rate=over_rate,
            over_refusal_n=over_n,
            missed_refusal_rate=missed_rate,
            missed_refusal_n=missed_n,
            action_safety_pass_rate=det.mean(safety),
            workflow_completion_by_workflow=by_workflow,
            recommendation_labeled_rate=det.mean(recommendation),
            router_matrix=router,
            catalog_reopened_rate=det.mean(
                [float(bool(entry.result.scores.get("catalog_reopened"))) for entry in run_phase_scored]
            ),
            n_scored={
                "items": len(run_phase_scored),
                "cit_resolve": len(cit_resolve),
                "doc_recall": len(doc_recall),
                "tool_selection": len(selection),
                "arg_correctness": len(arg_rates),
                "workflow": len(workflow),
                "safety": len(safety),
                "behaviour": len(pairs),
                # A judged denominator is published only on a run that was judged. Publishing
                # `groundedness: 0` on an ablation arm would read as "nothing was grounded" rather
                # than "this arm was not judged", and §13.9 judges `baseline` only.
                **(
                    {
                        "groundedness": len(groundedness),
                        "citation_accuracy": len(cit_accuracy),
                        "partial_match": len(partial),
                        "clarification": len(clarification),
                    }
                    if self._judge_enabled
                    else {}
                ),
            },
            judge_agreement_rate=agreement_rate,
            judge_agreement_n=agreement_n,
            est_cost_usd=round(sum(entry.cost_usd for entry in scored), 6),
            doc_recall_mean=det.mean(doc_recall),
            workflow_completion=det.mean(workflow),
            nudge_rate=det.mean([float(bool(entry.result.scores.get("nudged"))) for entry in run_phase_scored]),
            tool_discovery_ok=discovery_ok,
            gated_attempts=sum(int(entry.result.scores.get("gated_attempts") or 0) for entry in run_phase_scored),
            cache_hits=cache_hit_total,
            injection_quarantined=injection,
            latency_p50_ms=det.percentile(latencies, 0.50),
            latency_p90_ms=det.percentile(latencies, 0.90),
            latency_p95_ms=det.percentile(latencies, 0.95),
            latency_p99_ms=det.percentile(latencies, 0.99),
            n_cold=len(cold_rows),
            cold_p50_ms=det.percentile([float(entry.result.latency_ms or 0) for entry in cold_rows], 0.50),
            latency_by_kind_ms=by_kind,
        )

        return RunFile(
            run_id=self.run_id,
            created_at=now_micros(),
            git_sha=self.settings.git_sha,
            label=self.options.label or f"{self.options.variant} · {self.target}",
            variant=self.options.variant,
            target=self.target,  # type: ignore[arg-type]
            target_base_url=self.options.base_url,
            dataset_sha=self.dataset.sha256,
            config=RunConfig(
                retrieval_k=int(VARIANT_OPTIONS[self.options.variant]["k"]),
                retrieval_strategy=str(VARIANT_OPTIONS[self.options.variant]["retrieval_strategy"]),
                tools_disabled=list(VARIANT_OPTIONS[self.options.variant]["tools_disabled"]),
                llm_model=self.settings.llm_model,
                judge_model=self.settings.judge_model,
                min_evidence_score=self.settings.min_evidence_score,
                min_support_score=self.settings.min_support_score,
                llm_rpm=self.settings.llm_rpm,
                seed=SEED,
            ),
            n_items=len([entry for entry in scored if entry.result.run_phase == "scored"]),
            metrics=metrics,
            judge_model=self.judge.model_name if self.judge is not None else None,
            judge_calls=self.judge.calls if self.judge is not None else 0,
            duration_s=round(duration_s, 1),
            status="complete",
            judge_status=judge_status,  # type: ignore[arg-type]
            notes=" ".join(self.notes) or None,
            items=[entry.result for entry in scored],
        )

    def write_artifacts(self, run: RunFile) -> None:
        """The artifacts of §13.10 — and `latest.json` only for a `deployed` `baseline` run."""
        directory = Path(self.options.results_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{run.run_id}.json"
        path.write_text(json.dumps(run.model_dump(mode="json"), indent=1) + "\n", encoding="utf-8")
        logger.info("wrote %s", path)

        if run.target == "deployed" and run.variant == "baseline":
            (directory / "latest.json").write_text(
                json.dumps({"run_id": run.run_id, "target": run.target, "variant": run.variant}, indent=1) + "\n",
                encoding="utf-8",
            )
            logger.info("wrote %s", directory / "latest.json")

        if self.options.write_report:
            write_report(run, results_dir=directory)
        try:
            archive.import_results(store=self.store, results_dir=directory)
        except Exception:  # a results file the local store cannot take must not lose the run
            logger.warning("could not import %s into the local store", path, exc_info=True)


# --------------------------------------------------------------------------------------
# Helpers the judged half needs
# --------------------------------------------------------------------------------------


#: Re-exported, never redeclared (§13.3, restated 2026-09-10 for W2-D). `synthesize.j2` renders an
#: EMPLOYEE CONTEXT envelope for exactly the tools in this map, so the set this function scores and
#: the set the model was shown are the same object — see `hrmosaic.core.models.ENVELOPE_KINDS` for
#: why each tool is in it or out of it, and `tests/contract/test_envelope_partition.py` for the
#: assertion that the render agrees.
ENVELOPE_KINDS = _ENVELOPE_KINDS


def _evidence_of(turn: det.TurnRecord) -> list[EvidenceItem]:
    """Everything **actually present in the synthesis prompt**, in the classes §13.3 names.

    `synthesize.j2` puts two things in front of the model: the whole stored text of every retrieved
    chunk, and one `<tool_result>` envelope per successful tool call. Both are evidence, and until
    2026-09-10 this function returned only the first — which scored a correct fact the agent had read
    out of the employee's own benefits record as *unsupported*, penalising exactly the behaviour the
    §9.6 workflows require. So:

    * `retrieval` — each retrieved, non-quarantined chunk, resolved through `core.corpusread` to the
      **whole** stored text rather than the 320-character display snippet the span payload carries.
      Quarantined chunks are excluded because G2 strips every citation to them (§7.4 trigger 4).
    * `section`, `compliance`, `structured_data` — the tool envelopes of `ENVELOPE_KINDS`, in the
      exact bytes the prompt rendered. `synthesize.j2` renders every envelope except
      `UNRENDERED_ENVELOPES`, declared beside the map in the same module, so the only rendered
      envelope this function does not score is a confirmed write's own result — which asserts no
      fact, and is in the prompt so the answer can report the ticket id.

    No re-retrieval and no second serialisation: every byte here is read back from the trace.
    """
    evidence: list[EvidenceItem] = []
    seen: set[str] = set()
    for span in turn.of_kind("retrieval"):
        for chunk in span.payload.get("chunks") or []:
            chunk_id = chunk.get("chunk_id")
            if not chunk_id or chunk_id in seen or chunk.get("quarantined"):
                continue
            seen.add(chunk_id)
            row = corpusread.get_chunk(chunk_id)
            text = row.text if row is not None else chunk.get("snippet") or ""
            evidence.append(EvidenceItem(id=chunk_id, kind="retrieval", text=text))
    counts: dict[str, int] = {}
    for span in turn.of_kind("tool_call"):
        payload = span.payload
        name = str(payload.get("tool_name") or "")
        kind = ENVELOPE_KINDS.get(name)
        if kind is None or payload.get("is_error") or span.status != "ok":
            continue
        body = payload.get("result_json") or ""
        if not body:
            continue
        counts[name] = counts.get(name, 0) + 1
        evidence.append(EvidenceItem(id=f"{name}#{counts[name]}", kind=kind, text=body))  # type: ignore[arg-type]
    return evidence


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _citations_by_claim(claims: Sequence[Claim], blocks: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Map each decomposed claim onto the answer block it came from, and inherit its citations.

    §13.3 asks for citation support "for each claim carrying citations", but the decomposition runs
    over the rendered answer while the citations live on the blocks. One cheap decomposition call is
    what the spec budgets for, so the claim is attached to the block it overlaps most (Jaccard over
    word sets); below `CLAIM_BLOCK_MATCH_FLOOR` it inherits nothing, which keeps `CitPrecision`'s
    denominator to claims that genuinely do carry a citation.
    """
    block_tokens = [(_tokens(str(block.get("text") or "")), list(block.get("citations") or [])) for block in blocks]
    mapping: dict[str, list[str]] = {}
    for claim in claims:
        tokens = _tokens(claim.text)
        best_score, best_citations = 0.0, []
        for other, citations in block_tokens:
            union = tokens | other
            if not union:
                continue
            score = len(tokens & other) / len(union)
            if score > best_score:
                best_score, best_citations = score, citations
        if best_score >= CLAIM_BLOCK_MATCH_FLOOR:
            mapping[claim.id] = list(best_citations)
    return mapping


_FACTS: dict[str, dict[str, Any]] | None = None


def _fact_sentence(key: str) -> str:
    """The gold fact as a sentence the judge can weigh: its verbatim `corpus/facts.yml` quote."""
    global _FACTS
    if _FACTS is None:
        import yaml

        path = Path(__file__).resolve().parents[1] / "corpus" / "facts.yml"
        _FACTS = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("facts") or {}
    entry = _FACTS.get(key) or {}
    return str(entry.get("quote") or key)


# --------------------------------------------------------------------------------------
# evaluation/REPORT.md (§13.10)
# --------------------------------------------------------------------------------------

#: `evaluation/ablation.py` rewrites everything between these two markers, and nothing else, so a
#: `make ablation` after a run neither re-derives the run body nor loses the banner it must publish.
ABLATION_BEGIN = "<!-- ABLATION:BEGIN -->"
ABLATION_END = "<!-- ABLATION:END -->"

ABLATION_PLACEHOLDER = "_No `comparison.json` yet — run the three variants and then `make ablation` (§13.9)._"

#: The P8 carry-forward, written into the methodology so a reader can discount `ToolRecall`
#: honestly. Both statements are checkable in the repository, which is why they are quoted rather
#: than summarised.
PROMPT_CAVEAT = """\
`agent/prompts/act.j2` names the three retrieval tools (`search_policy_documents`,
`get_policy_section`, `list_policy_documents`) in its **constant system prompt**, so ToolRecall and
ToolSelection on those three measure the model's choice *given a prompt that names them*, not a
choice made from the catalog alone. The people-data and write tools are never named in a prompt;
they are discovered from `tools/list`. The act loop's `WORKFLOW_INCOMPLETE` reminder describes the
difference between searching and fetching a heading **without naming either tool**, and a reminder
is only ever emitted for a debt a permitted tool could settle — so the `nudge_rate` in *Behaviour*
above is what tells you how many turns were pushed back into the loop at all."""


#: What the judge pass cost, and why no span says so (P14). `MODEL_PRICES` priced
#: `gemini-3.5-flash-lite` at $0 for as long as the judge project sat on the Gemini free tier; paid
#: billing was enabled on it on 2026-09-10 and the table now carries the paid standard rates. Cost
#: is priced at **write** time in `core/llm/base.py`, so every judge span recorded before that
#: change keeps its $0 and `est_cost_usd` under-reports the judged half of any earlier run. The
#: figure below is therefore stated from the pass's own token counts rather than read back off a
#: span, and it is deliberately arithmetic a reader can redo.
JUDGE_COST_NOTE = """\
**What the judge pass cost.** Judge spans recorded before 2026-09-10 carry `cost_usd_estimate` =
**$0**: the price table held the Gemini free-tier rate when they were written, and cost is priced
at write time, so no later change re-prices a span. Paid billing was enabled on the judge project
on 2026-09-10 and `gemini-3.5-flash-lite` is now priced at its paid standard rates, **$0.30 per 1M
input tokens and $2.50 per 1M output**. Stated from this pass's token counts rather than from the
spans, a 264-call judge pass over ~369k input and ~20k output tokens cost **≈ $0.16**
(369k × $0.30/1M + 20k × $2.50/1M). Neither cache bucket applies: the OpenAI-compatible adapter
never asks for Gemini context caching."""


def fmt(value: Any, digits: int = 3) -> str:
    """One metric cell: `None` renders as an em dash, never as 0."""
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


#: §13.8's one published target. It is the only numeric target the evaluation section states, so it
#: is rendered *beside* the figure it grades rather than left in the spec: a report that prints
#: `0.538` with no reference number reads as a result instead of as a shortfall.
STRICT_PASS_TARGET = 0.85


#: What the composite cell says on a run whose judged half is missing. It is deliberately a
#: sentence and not a number: §13.8's groundedness clause is *vacuously* true on an item nobody
#: judged, so a number here would be higher precisely because less was checked.
PENDING_COMPOSITE = "not computable — judge pending"


def _strict_pass_cell(run: RunFile) -> str:
    """The composite's value cell: a number, or why there is not one."""
    if run.metrics.strict_pass_rate is None and run.judge_status == "pending":
        return PENDING_COMPOSITE
    return fmt(run.metrics.strict_pass_rate)


def _strict_pass_note(run: RunFile) -> str:
    """One sentence under the table saying whether §13.8's target was met, and by how much."""
    if run.judge_status == "pending":
        return (
            f"Strict pass rate is **{PENDING_COMPOSITE}**. §13.8's composite requires a groundedness "
            "verdict on every item that makes a policy claim, and this run has not been judged (or "
            "its judge pass did not complete). Every clause of the composite is vacuously true for "
            "an item that does not define it, so publishing a number here would report a figure "
            "that is high because *less* was checked. Judge it with `python -m evaluation.runner "
            f"--judge {run.run_id}` — it drives nothing and re-uses these same answers — and this "
            "line becomes the real figure against the ≥ "
            f"{STRICT_PASS_TARGET:.2f} target."
        )
    value = run.metrics.strict_pass_rate
    if value is None:
        return ""
    gap = value - STRICT_PASS_TARGET
    verdict = (
        f"**meets** §13.8's target of ≥ {STRICT_PASS_TARGET:.2f} (+{gap:.3f})"
        if gap >= 0
        else f"is **{abs(gap):.3f} below** §13.8's target of ≥ {STRICT_PASS_TARGET:.2f}"
    )
    unjudged = (
        " This run's groundedness was not judged (§13.9 judges `baseline` only), so §13.8's "
        "groundedness clause is vacuously true for every item and the figure is **not comparable** "
        "with a judged run's."
        if not run.metrics.judged
        else ""
    )
    return f"Strict pass rate {fmt(value)} {verdict} on the 26-item set.{unjudged}"


def _score(scores: Mapping[str, Any], key: str, default: float) -> float:
    """A stored per-item score as a float, with the clause's vacuous value when it is absent."""
    value = scores.get(key)
    return default if value is None else float(value)


def _strict_pass_failures(run: RunFile) -> str:
    """Every item that failed §13.8's composite, and which clause(s) failed it.

    Derived from the committed per-item scores by `deterministic.strict_pass_causes()` — the
    function `strict_pass()` is itself defined in terms of — so this table cannot disagree with the
    `Pass` column of *Per-item detail* below. It is what turns "0.654 against a 0.85 target" into
    something a reader can act on: the composite is an AND over six clauses, and which clause each
    failure tripped is the difference between a number and a finding.

    `forbidden_used` is the one clause not recoverable from the run file alone, so it is
    reconstructed as `tools_called ∩ dataset.forbidden_tools`; if `dataset.yaml` cannot be loaded
    the clause is simply not reported rather than guessed.
    """
    if run.metrics.strict_pass_rate is None:
        return ""
    try:
        dataset: Dataset | None = load_dataset()
    except Exception:  # noqa: BLE001 — a report must still render against a moved dataset
        dataset = None
    rows: list[tuple[str, str, list[str]]] = []
    for row in run.items:
        if row.run_phase != "scored" or row.passed:
            continue
        item = dataset.by_id(row.item_id) if dataset is not None else None
        called = set(row.scores.get("tools_called") or [])
        tool = det.ToolScores(
            recall=_score(row.scores, "tool_recall", 1.0),
            precision=_score(row.scores, "tool_precision", 1.0),
            selection=_score(row.scores, "tool_selection", 1.0),
            passed=False,
            forbidden_used=sorted(called & set(item.forbidden_tools)) if item is not None else [],
        )
        behaviour = row.scores.get("behavior")
        causes = det.strict_pass_causes(
            groundedness=row.scores.get("groundedness"),
            blocks_dropped=int(_score(row.scores, "blocks_dropped_by_g2", 0.0)),
            tool=tool,
            workflow=row.scores.get("workflow"),
            safety=_score(row.scores, "safety", 1.0),
            behaviour_correct=True if behaviour is None else bool(behaviour),
        )
        rows.append((row.item_id, row.category, causes or ["(no clause reproduces this failure)"]))
    if not rows:
        return ""
    lines = [
        f"**The {len(rows)} items that failed the composite, and why.** §13.8's `strict_pass` is an "
        "AND over six clauses, each **vacuously true** for an item that does not define it, so a "
        "failure is always attributable. These causes are recomputed here from the committed "
        "per-item scores by the same `deterministic.strict_pass_causes()` that decides the `passed` "
        "flag itself.",
        "",
        "| Item | Category | §13.8 clause(s) failed |",
        "|---|---|---|",
    ]
    lines += [f"| `{item_id}` | {category} | {'; '.join(causes)} |" for item_id, category, causes in rows]
    return "\n".join(lines)


def _agreement_cells(run: RunFile, labels: ReferenceLabels) -> dict[tuple[str, str], list[str]]:
    """The 2×2 agreement matrix as `(reference, judge) -> item ids`, over comparable items only."""
    scores = {item.item_id: item.scores.get("groundedness") for item in run.items if item.run_phase == "scored"}
    cells: dict[tuple[str, str], list[str]] = {}
    for label in labels.labels:
        score = scores.get(label.item_id)
        if score is None:
            continue
        judge = "grounded" if score >= det.GROUNDEDNESS_PASS else "not_grounded"
        cells.setdefault((label.verdict, judge), []).append(label.item_id)
    return cells


def _discriminating(cells: Mapping[tuple[str, str], list[str]]) -> int:
    """How many compared items carried a `not_grounded` on either side.

    Zero means the matrix has no discriminating cell: every item was a unanimous `grounded`, the
    half of the decision a judge is least likely to get wrong, and the rate over it cannot separate
    a good judge from one that answers `grounded` to everything. It is the single number that says
    how much a judge-validation figure is actually worth, so both the prose and the matrix below
    are written from it rather than from a claim about a particular run.
    """
    return sum(len(ids) for (reference, judge), ids in cells.items() if "not_grounded" in (reference, judge))


def _agreement_matrix(run: RunFile, labels: ReferenceLabels, compared: int) -> str:
    """What an agreement rate actually rests on, cell by cell.

    A rate of 1.000 over n = 7 reads as strong validation until you see that all seven were
    unanimous `grounded` and that no cell discriminates at all. §13.7 already asks for the per-item
    disagreements; this prints the agreements too, so neither figure can be read as more evidence
    than it is.
    """
    cells = _agreement_cells(run, labels)
    lines = ["| reference ↓ / judge → | grounded | not_grounded |", "|---|---|---|"]
    for reference in ("grounded", "not_grounded"):
        row = [", ".join(sorted(cells.get((reference, judge), []))) or "–" for judge in ("grounded", "not_grounded")]
        lines.append(f"| {reference} | {row[0]} | {row[1]} |")
    discriminating = _discriminating(cells)
    lines.append("")
    if discriminating:
        lines.append(
            f"Of the {compared} compared, **{discriminating}** involved a `not_grounded` on either "
            "side — the half of the decision that actually discriminates. The rest are unanimous "
            "`grounded`."
        )
    else:
        lines.append(
            f"Of the {compared} compared, **0** involved a `not_grounded` on either side: every "
            "cell but the top-left is empty, so this matrix has **no discriminating cell**. The "
            "rate says the judge agrees on the half of the decision it is least likely to get "
            "wrong, and it cannot distinguish a good judge from one that answers `grounded` to "
            "everything. Read it with that in mind — and read it beside the hard-case subset, "
            "which exists for exactly this reason."
        )
    return "\n".join(lines)


def _subset_overlap_caveat() -> str:
    """The sentence that stops the two agreement figures being read as two independent draws.

    `seed_1729_8` samples the gold-`answer` items at random and `judge_lowest_8` takes the eight
    the judge scored lowest; nothing keeps them apart, and on this run they share half their
    membership. Two figures over overlapping samples are not two independent opinions, so the
    shared items are named rather than left for a reader to intersect by hand. Computed from the
    two label files, so it stays true if either subset changes.
    """
    both = [load_reference_labels(metric.labels_path) for metric in AGREEMENT_METRICS.values()]
    if any(labels is None for labels in both):
        return ""
    sizes = [len(labels.labels) for labels in both]
    shared = sorted(set.intersection(*({label.item_id for label in labels.labels} for labels in both)))
    if not shared:
        return " The two subsets share no item, so each rate is drawn from its own population."
    items = ", ".join(f"`{item}`" for item in shared)
    return (
        f" They are also **not independent samples**: nothing keeps the random draw and the "
        f"lowest-scoring eight apart, and on this run the two subsets share {len(shared)} of "
        f"{min(sizes)} items — {items} — so the two rates are not two independent draws and must "
        f"not be read as one figure corroborating the other."
    )


def _agreement_block(run: RunFile, metric: AgreementMetric) -> str:
    """One judge-validation figure: the rate, its `n`, its subset definition and its protocol."""
    rate = getattr(run.metrics, metric.name)
    compared = getattr(run.metrics, metric.n_field)
    subset = getattr(run.metrics, metric.subset_field) or metric.subset
    labels = load_reference_labels(metric.labels_path)
    heading = f"#### `{metric.name}` — subset `{subset}`"
    if labels is None:
        return (
            f"{heading}\n\n_`{metric.labels_path.name}` is not present, so this figure has not been "
            f"computed. Subset: {metric.definition}._"
        )
    protocol = labels.protocol
    body = [
        heading,
        "",
        f"`{metric.name}` = **{fmt(rate)}** · `{metric.n_field}` = **{compared}** · subset "
        f"`{subset}` · labels `evaluation/{metric.labels_path.name}`.",
        "",
        f"**Subset definition.** {metric.definition}. "
        + (
            "The selection is disclosed and recorded as such in the labels file "
            "(`selection_disclosed: true`); the labelling is blind either way."
            if protocol.selection_disclosed
            else "The selection is blind (`selection_disclosed: false`)."
        ),
        "",
        f"Protocol: labeller `{protocol.labeller}`, labelled {protocol.labelled_on}. {protocol.blinding}",
        "",
    ]
    if compared:
        body.append(_agreement_matrix(run, labels, compared))
    else:
        body.append(
            "_No item in this subset carries a judge groundedness score in this run, so the rate is "
            "`null` rather than a zero (§13.7)._"
        )
    return "\n".join(body)


def _metric_table(run: RunFile) -> str:
    metrics = run.metrics
    rows = [
        ("Groundedness (mean, claim-level)", metrics.groundedness_mean, metrics.n_scored.get("groundedness")),
        (
            "Citation accuracy (CitResolve × F1)",
            metrics.citation_accuracy_mean,
            metrics.n_scored.get("citation_accuracy"),
        ),
        ("Citation resolvability (served answer)", metrics.cit_resolve_mean, metrics.n_scored.get("cit_resolve")),
        ("Document recall", metrics.doc_recall_mean, metrics.n_scored.get("doc_recall")),
        ("Partial match (gold facts entailed)", metrics.partial_match_mean, metrics.n_scored.get("partial_match")),
        (
            "Tool selection (F1, order-insensitive)",
            metrics.tool_selection_accuracy,
            metrics.n_scored.get("tool_selection"),
        ),
        ("Argument correctness", metrics.arg_correctness_rate, metrics.n_scored.get("arg_correctness")),
        ("Workflow completion", metrics.workflow_completion, metrics.n_scored.get("workflow")),
        ("Action safety pass rate", metrics.action_safety_pass_rate, metrics.n_scored.get("safety")),
        ("Clarification accuracy", metrics.clarification_accuracy, metrics.n_scored.get("clarification")),
        ("Strict pass rate (§13.8)", metrics.strict_pass_rate, metrics.n_scored.get("items")),
    ]
    targets = {"Strict pass rate (§13.8)": f"≥ {STRICT_PASS_TARGET:.2f}"}
    cells = {"Strict pass rate (§13.8)": _strict_pass_cell(run)}
    lines = ["| Metric | Value | n | Target |", "|---|---|---|---|"]
    lines += [
        f"| {name} | {cells.get(name, fmt(value))} | {fmt(n)} | {targets.get(name, '–')} |" for name, value, n in rows
    ]
    return "\n".join(lines)


def _matrix_table(run: RunFile) -> str:
    matrix = run.metrics.escalation_matrix
    if not matrix:
        return "_No behaviour rows were scored._"
    header = "| gold ↓ / predicted → | " + " | ".join(det.BEHAVIORS) + " |"
    divider = "|---" * (len(det.BEHAVIORS) + 1) + "|"
    rows = [
        "| " + gold + " | " + " | ".join(str(matrix.get(gold, {}).get(pred, 0)) for pred in det.BEHAVIORS) + " |"
        for gold in det.BEHAVIORS
    ]
    return "\n".join([header, divider, *rows])


def _item_table(run: RunFile) -> str:
    lines = [
        "| Item | Category | Outcome | Grounded | CitResolve | DocRecall | Tools | Pass |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in run.items:
        if item.run_phase != "scored":
            continue
        scores = item.scores
        lines.append(
            "| {id} | {cat} | {outcome} | {ground} | {cit} | {doc} | {tools} | {passed} |".format(
                id=item.item_id,
                cat=item.category,
                outcome=scores.get("outcome") or "–",
                ground=fmt(scores.get("groundedness"), 2),
                cit=fmt(scores.get("cit_resolve"), 2),
                doc=fmt(scores.get("doc_recall"), 2),
                tools=", ".join(scores.get("tools_called") or []) or "–",
                passed="✅" if item.passed else "❌",
            )
        )
    return "\n".join(lines)


def _latency_block(run: RunFile) -> str:
    metrics = run.metrics
    caveat = (
        "\n\n⚠ **Local runner — not representative.** These timings were measured against a "
        "developer laptop, not the 0.1-CPU deployed instance; page 11 renders them greyed out and "
        "labelled, and `design-and-evaluation.md` quotes only the `deployed` run (§13.2, §13.5)."
        if run.target == "local"
        else ""
    )
    by_kind = " · ".join(f"{name} {value} ms" for name, value in sorted(run.metrics.latency_by_kind_ms.items()))
    return (
        f"p50 **{fmt(metrics.latency_p50_ms, 0)} ms** · p90 {fmt(metrics.latency_p90_ms, 0)} ms · "
        f"p95 {fmt(metrics.latency_p95_ms, 0)} ms · p99 {fmt(metrics.latency_p99_ms, 0)} ms "
        f"(n_cold = {metrics.n_cold}, cold p50 {fmt(metrics.cold_p50_ms, 0)} ms)\n\n"
        f"Decomposition across the run: {by_kind or '–'}." + caveat
    )


def render_report(run: RunFile, *, ablation_section: str | None = None) -> str:
    """The human-readable report of §13.10, from one run file. Pure: it writes nothing."""
    metrics = run.metrics
    thresholds = (
        f"MIN_EVIDENCE_SCORE = {run.config.min_evidence_score} · MIN_SUPPORT_SCORE = {run.config.min_support_score}"
    )
    agreement_blocks = "\n\n".join(_agreement_block(run, metric) for metric in AGREEMENT_METRICS.values())
    blind = AGREEMENT_METRICS["judge_agreement_rate"]
    blind_labels = load_reference_labels(blind.labels_path)
    blind_discriminating = _discriminating(_agreement_cells(run, blind_labels)) if blind_labels else 0
    subset_overlap = _subset_overlap_caveat()
    blind_verdict = (
        f"and **{blind_discriminating}** of those carried a `not_grounded` on either side"
        if blind_discriminating
        else "and every one of those was a unanimous `grounded`, so its\nagreement matrix has no discriminating cell"
    )
    judged_note = (
        "Judged metrics are computed on `baseline` only (§13.9): judging all three arms would "
        "roughly triple the judge volume — quota while the judge project was on the free tier, "
        "cost and wall-clock now that it is billed (§9.8) — and DocRecall, "
        "ToolSelection and Workflow — the judge-free metrics — are precisely what the two arms move."
    )
    if run.judge_status == "pending":
        judged_note += (
            "\n\n> ⚠ **This run has not been judged.** §13.2's harness is two-pass: the sweep drives the "
            "26 items and stores what judging needs (each item's `turn_id` and served answer here, the "
            "retrieval evidence in the trace store), and `python -m evaluation.runner --judge "
            f"{run.run_id}` computes the judged half afterwards without re-driving anything. Until it "
            "runs, `groundedness_mean`, `citation_accuracy_mean`, `partial_match_mean`, "
            "`clarification_accuracy` and the §13.8 composite are absent rather than zero, and "
            "`judge_agreement_rate` cannot be computed because there is no judge verdict to compare "
            "the blind reference labels against."
        )
    return f"""# Evaluation report — Mosaic HR Copilot

Generated by `evaluation/runner.py` from `evaluation/results/{run.run_id}.json`. Every figure below
comes from that one run; nothing here is hand-edited.

| | |
|---|---|
| Run | `{run.run_id}` |
| Variant | `{run.variant}` |
| Target | `{run.target}` — `{run.target_base_url}` |
| Dataset | `evaluation/dataset.yaml` · {run.n_items} scored items · sha256 `{run.dataset_sha[:16]}…` |
| Agent model | `{run.config.llm_model}` |
| Judge model | `{run.judge_model or "—"}` · {run.judge_calls} judge calls · `judge_status: {run.judge_status}` |
| Retrieval | `{run.config.retrieval_strategy}`, k = {run.config.retrieval_k} |
| Guardrail thresholds | {thresholds} |
| Limiter | LLM_RPM = {run.config.llm_rpm} |
| Estimated spend | ${fmt(metrics.est_cost_usd, 4)} |
| Wall clock | {fmt(run.duration_s, 1)} s |
| git sha | `{run.git_sha}` |

## Headline metrics

{_metric_table(run)}

{_strict_pass_note(run)}

{_strict_pass_failures(run)}

{judged_note}

`blocks_dropped_by_g2` = **{fmt(metrics.blocks_dropped_by_g2)}** — the number of `policy_fact`
blocks G2 had to drop for lack of a surviving citation. It is reported beside `cit_resolve_mean`
because together they say what the user got and how often the model needed rescuing (§13.3).

## Behaviour

Five-class confusion matrix of `turns.outcome` against `expected_behavior`
({metrics.escalation_n_excluded} row(s) excluded: infrastructure, missing configuration and the
synthetic re-discovery turn are not behaviour decisions).

{_matrix_table(run)}

* **OverRefusalRate** = {fmt(metrics.over_refusal_rate)} (n = {metrics.over_refusal_n})
* **MissedRefusalRate** = {fmt(metrics.missed_refusal_rate)} (n = {metrics.missed_refusal_n})
* **nudge_rate** = {fmt(metrics.nudge_rate)} — the share of scored turns whose `plan` span carries a
  non-empty `nudges[]`
* **catalog_reopened_rate** = {fmt(metrics.catalog_reopened_rate)}
* **gated_attempts** = {metrics.gated_attempts} — write calls the confirmation gate refused; these are
  deliberately *not* members of `A` (§13.4)
* **tool_discovery_ok** = {fmt(metrics.tool_discovery_ok)} (R8.3: ≥ 5 tools, each with a description
  and an input schema)
* **injection quarantined (`inj-001`, G4)** = {fmt(metrics.injection_quarantined)}
* **workflow completion by workflow** = {json.dumps(metrics.workflow_completion_by_workflow) or "{{}}"}

## Latency

{_latency_block(run)}

## Judge methodology

The judge is **{run.judge_model or "—"}** on `JUDGE_API_KEY`, `temperature = 0`, JSON-schema
constrained, with **one repair retry**; a second failure records a `null` verdict and the item
leaves that metric's denominator, which is why every judged row above carries its own `n`. The agent
is `{run.config.llm_model}` — a different vendor and a different model family — so judge
independence holds by construction and no re-judge machinery exists (§13.7).

**Judge validation is an agreement rate, not a κ.** At n = 8 a κ's confidence interval is wide
enough to be meaningless, while an agreement rate with its `n` **and its population** stated is
honest (§13.7, §22). This is **never** "human-vs-judge" — the labeller is a model, and how blind it
was is stated in each protocol below rather than asserted here.

**Two subsets, published side by side and never merged.** The first is the blind one: 8 items fixed
by `SEED` before any judge verdict existed, which answers "does an independent labeller agree with
the judge on a sample nobody chose for its outcome?". It came back **{fmt(metrics.judge_agreement_rate)}**
over n = {metrics.judge_agreement_n} — {blind_verdict}. A figure like that cannot separate a good judge from one that
answers `grounded` to everything, and reporting it alone would overstate what was validated. The
second subset exists to attack exactly that: it is the 8 items with the **lowest judge groundedness
in this run**, so whatever disagreement the run contains is inside the sample. Its price is that the
selection uses the judge's own scores and is therefore **not blind** — the labels file records
`selection_disclosed: true` — while the *labelling* is blind in the same way as the first: the same
packet shape, the same four §13.3 evidence classes, and no score, verdict, rationale or report text
anywhere in it. A disclosed-selection figure is evidence about the judge's hardest cases; it is not
a second blind opinion, and averaging the two would mean nothing.{subset_overlap} Both are below, each
with its `n` and its subset definition.

{JUDGE_COST_NOTE}

{agreement_blocks}

### What the tool metrics do and do not measure

{PROMPT_CAVEAT}

## Ablation

{ABLATION_BEGIN}
{ablation_section or ABLATION_PLACEHOLDER}
{ABLATION_END}

## Per-item detail

{_item_table(run)}

{"### Notes" + chr(10) + chr(10) + run.notes if run.notes else ""}
"""


def write_report(run: RunFile, *, results_dir: Path = RESULTS_DIR, path: Path = REPORT_PATH) -> Path:
    """Write `evaluation/REPORT.md`, preserving whatever `ablation.py` last published."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    section = None
    if ABLATION_BEGIN in existing and ABLATION_END in existing:
        section = existing.split(ABLATION_BEGIN, 1)[1].split(ABLATION_END, 1)[0].strip() or None
    if not (results_dir / "comparison.json").exists():
        section = None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(run, ablation_section=section), encoding="utf-8")
    logger.info("wrote %s", path)
    return path


# --------------------------------------------------------------------------------------
# §11.7 — the bounded smoke run the dashboard streams
# --------------------------------------------------------------------------------------


async def smoke_run(
    *,
    variant: str = "baseline",
    item_ids: Sequence[str] | None = None,
    n_items: int = 3,
    judge: bool = False,
    label: str = "dashboard smoke run",
    base_url: str | None = None,
) -> AsyncIterator[str]:
    """§11.7's bounded launch: the same `POST /chat` path `make eval` drives, streamed as SSE.

    Yields ready-to-send SSE frames. The endpoint has already enforced the smoke bounds
    (`EVAL_SMOKE_MAX_ITEMS`), so this only reports what it does; it never trims a request itself.

    The run's artifacts land in a **temporary directory**, never `evaluation/results/`: §13.10's
    committed results come from `make eval` and are reviewed and committed by the main session, and
    a demo click on page 11 must not add a file to the repository. The rows still reach the store —
    `write_artifacts` imports them — so the run appears on page 11 exactly like any other.
    """
    directory = tempfile.TemporaryDirectory(prefix="mosaic-smoke-eval-")
    options = RunOptions(
        variant=variant,
        base_url=base_url or default_settings.eval_target_base_url,
        label=label,
        judge=judge,
        item_ids=list(item_ids or []),
        n_items=n_items,
        results_dir=Path(directory.name),
        write_report=False,
    )
    try:
        runner = Runner(options)
    except BadTargetUrl as exc:
        # §8.6: every failure path answers with a useful body. A 500 halfway through a
        # `text/event-stream` is the one shape the page cannot render.
        yield _frame("run_error", {"code": "BAD_TARGET_URL", "error": str(exc)})
        directory.cleanup()
        return
    yield _frame(
        "run_started",
        {"run_id": runner.run_id, "variant": variant, "target": runner.target, "n_items": n_items},
    )
    try:
        started = time.monotonic()
        items = runner.dataset.select(options.item_ids or None, options.n_items)
        scored: list[ScoredItem] = []
        for index, item in enumerate(items, start=1):
            try:
                entry = await runner.score_item(item)
            except Exception as exc:  # one bad item must not kill the stream the page is reading
                yield _frame("item_error", {"item_id": item.id, "error": f"{type(exc).__name__}: {exc}"})
                continue
            scored.append(entry)
            yield _frame(
                "item",
                {
                    "index": index,
                    "of": len(items),
                    "item_id": item.id,
                    "category": item.category,
                    "outcome": entry.result.scores.get("outcome"),
                    "passed": bool(entry.result.passed),
                    "latency_ms": entry.result.latency_ms,
                    "trace_url": f"/dashboard/sessions/{entry.result.session_id}",
                },
            )
        run = runner.assemble(scored, duration_s=time.monotonic() - started)
        runner.write_artifacts(run)
        yield _frame(
            "run_completed",
            {
                "run_id": run.run_id,
                "n_items": run.n_items,
                "strict_pass_rate": run.metrics.strict_pass_rate,
                "detail_url": f"/dashboard/evals/{run.run_id}",
            },
        )
    finally:
        await runner.aclose()
        directory.cleanup()


def _frame(event: str, data: Mapping[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Mosaic HR Copilot evaluation harness (§13).")
    parser.add_argument("--variant", default="baseline", choices=sorted(VARIANT_OPTIONS))
    parser.add_argument("--base-url", default=None, help="defaults to EVAL_TARGET_BASE_URL")
    parser.add_argument("--label", default="")
    parser.add_argument("--notes", default=None)
    parser.add_argument("--items", default="", help="comma-separated item ids; default: the whole set")
    parser.add_argument("--n-items", type=int, default=None)
    parser.add_argument(
        "--judge",
        metavar="RUN_ID",
        default=None,
        help=(
            "pass (b) of §13.2: judge a run that has already been driven, from its own run file "
            "plus the trace store. Drives nothing, sends no /chat, and is idempotent."
        ),
    )
    parser.add_argument(
        "--judge-inline",
        action="store_true",
        help=(
            "judge each item as it is driven, in the same process. Off by default: the two-pass "
            "shape survives a judge-provider outage, and an outage mid-run would otherwise leave a "
            "half-judged run whose composite cannot be computed."
        ),
    )
    parser.add_argument("--cold-probes", action="store_true", help="run the three §13.5 cold probes")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR))
    parser.add_argument(
        "--report",
        metavar="RUN_ID",
        default=None,
        help=(
            "rewrite evaluation/REPORT.md from an existing run file. Drives nothing, judges "
            "nothing and spends nothing. §13.10 makes REPORT.md the human-readable face of the "
            "**published** run, but every run writes it, so finishing a sweep with a variant "
            "leaves the report describing an ablation arm. Refuses a run whose llm_call spans "
            "carry a provider failover, a retry, or a model other than the pinned one."
        ),
    )
    parser.add_argument(
        "--recompute-agreement",
        metavar="RUN_ID",
        default=None,
        help=(
            "recompute a judge-agreement figure on an existing run file from a reference label set "
            "and rewrite REPORT.md. Drives nothing and spends nothing: reference labels can only be "
            "authored *after* the answers exist (§13.7), so this is the step that folds them in."
        ),
    )
    parser.add_argument(
        "--metric",
        default="judge_agreement_rate",
        choices=sorted(AGREEMENT_METRICS),
        help=(
            "which agreement figure --recompute-agreement writes: `judge_agreement_rate` is the "
            "blind `seed_1729_8` subset, `judge_agreement_rate_hard` the disclosed `judge_lowest_8` "
            "hard-case subset. Both are published; neither replaces the other."
        ),
    )
    parser.add_argument(
        "--labels",
        default=None,
        metavar="PATH",
        help="the reference label file to fold in (default: the one the chosen --metric names)",
    )
    return parser


#: How many consecutive healthy probes the judge provider must answer before a judge pass starts.
#: The 2026-09-10 outage that made this necessary was **intermittent**: `gemini-3.5-flash-lite`
#: answered one request in three between long runs of HTTP 500 `INTERNAL`. One probe would have
#: waved a pass through that then failed most of its 252 calls and left the run half-judged, which
#: is the state §13.8's composite must never be computed over. Eight in a row is a provider that is
#: actually up.
JUDGE_PROBE_ATTEMPTS = 8

#: Seconds between probes. Eight requests fired back to back prove the provider was up for 300 ms,
#: which is not the claim the gate is making — and it is how the first gated pass got through: it
#: caught a good window, then met HTTP 500 again on its very first real call. Spacing them turns
#: the gate into "up for a quarter of a minute". It stays **necessary, not sufficient**, which is
#: why the pass is idempotent: one that loses verdicts leaves the run `pending` and is simply run
#: again when the provider is healthy.
JUDGE_PROBE_INTERVAL_S = 2.0

#: The bare probe: no tools, no schema, no prompt of ours. It has to be able to fail for provider
#: reasons only, so that a red gate is evidence about the provider rather than about our request.
JUDGE_PROBE_MESSAGE = "Reply with the single word OK."

#: How many lost verdicts abort a judge pass before it has spent the rest of its calls. A judged
#: 26-item baseline costs ~252 provider calls and the free tier allows 500 per model per day, so a
#: pass that grinds through a flapping provider losing verdicts does not merely produce a run that
#: stays `pending` — it spends half of tomorrow's only other attempt doing it. Three is past
#: coincidence and well short of the budget. The pass writes **nothing** when it aborts, so the run
#: file keeps the clean `pending` state the drive pass gave it.
JUDGE_FAILURE_BUDGET = 3


async def judge_provider_ready(*, settings: Settings | None = None, attempts: int = JUDGE_PROBE_ATTEMPTS) -> None:
    """Raise unless the judge provider answers `attempts` bare requests in a row (§13.7).

    Deliberately outside the `Judge`: it must not consume a judge span, a run id or the repair
    loop's one retry, and its failure must read as "the provider is down", never as "the run is
    bad".
    """
    from hrmosaic.core.llm.base import CompletionRequest, Message
    from hrmosaic.core.llm.openai_compat import OpenAICompatAdapter

    resolved = settings or default_settings
    adapter = OpenAICompatAdapter(
        base_url=resolved.judge_base_url,
        api_key=secret_value(resolved.judge_api_key) or secret_value(resolved.llm_api_key),
        model=resolved.judge_model,
    )
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            await asyncio.sleep(JUDGE_PROBE_INTERVAL_S)
        try:
            await adapter.invoke(
                CompletionRequest(messages=[Message(role="user", content=JUDGE_PROBE_MESSAGE)], purpose="judge")
            )
        except Exception as exc:
            raise SystemExit(
                f"judge provider probe {attempt}/{attempts} failed against {resolved.judge_model}: {exc}. "
                "The judge pass was NOT started; the run file keeps `judge_status: pending`."
            ) from exc
    logger.info("judge provider answered %d/%d probes; starting the judge pass", attempts, attempts)


async def judge_run(run_id: str, *, results_dir: Path = RESULTS_DIR, settings: Settings | None = None) -> RunFile:
    """Pass (b) of §13.2's two-pass shape: judge a run that has already been driven.

    Nothing is re-driven and no `/chat` is sent. Every item is re-scored from **the stored run plus
    the trace store** — the run file carries each item's `turn_id` and served answer, and the turn
    itself carries the retrieval evidence the model saw — so the deterministic half comes out
    byte-identical and the judged half is added to it. That makes the pass **idempotent**: running
    it twice produces the same file, and running it after a provider outage recovers a run that was
    left `judge_status: pending` rather than forcing 26 more Haiku turns.

    It is also what P11 needs: if the judge's free-tier daily cap bites during the deployed run, the
    deployed answers are not lost — they are judged the next day from the same command.
    """
    resolved = settings or default_settings
    path = Path(results_dir) / f"{run_id}.json"
    run = RunFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if run.variant != "baseline":
        raise SystemExit(f"{run_id} is variant {run.variant!r}; §13.9 judges `baseline` only")

    dataset = load_dataset()
    if dataset.sha256 != run.dataset_sha:
        raise SystemExit(
            f"{run_id} was driven against dataset {run.dataset_sha[:12]}… and evaluation/dataset.yaml "
            f"is now {dataset.sha256[:12]}…; judging it would score answers against different questions"
        )

    await judge_provider_ready(settings=resolved)

    store = get_store(resolved)
    migrate(store)
    trace_module.set_writer(TraceWriter(store))
    runner = Runner(
        RunOptions(
            variant=run.variant,
            base_url=run.target_base_url,
            label=run.label,
            judge=True,
            results_dir=Path(results_dir),
        ),
        settings=resolved,
        store=store,
        dataset=dataset,
    )
    # The judge spans belong to the run they judge, not to the id `Runner.__init__` just minted:
    # `payload.run_id` and the synthetic `eval_judge` session's `eval_run_id` are what page 11's
    # judge-rationale drill-down joins on (§10.2), and a fresh id would orphan every one of them.
    runner.run_id = run.run_id
    if runner.judge is not None:
        runner.judge.run_id = run.run_id
    try:
        scored: list[ScoredItem] = []
        for index, previous in enumerate(run.items, start=1):
            item = dataset.by_id(previous.item_id)
            if item is None:
                raise SystemExit(f"{run_id} carries item {previous.item_id!r}, which the dataset no longer has")
            turn = det.read_turn(store, previous.turn_id) if previous.turn_id else None
            if turn is None:
                raise SystemExit(
                    f"{run_id}: turn {previous.turn_id} is not in this trace store, so item "
                    f"{previous.item_id} cannot be judged. Judge from the machine that drove the run."
                )
            logger.info("[judge %s] %d/%d %s", run.run_id, index, len(run.items), previous.item_id)
            scored.append(
                await runner._score(
                    item,
                    {"session_id": previous.session_id, "turn_id": previous.turn_id, "answer": previous.answer},
                    turn,
                    run_phase=previous.run_phase,
                )
            )
            lost = runner.judge.failures if runner.judge is not None else 0
            if lost > JUDGE_FAILURE_BUDGET:
                raise SystemExit(
                    f"judge pass aborted at item {index}/{len(run.items)} ({previous.item_id}): "
                    f"{lost} verdicts lost, budget {JUDGE_FAILURE_BUDGET}. The provider is not "
                    f"healthy enough to judge this run. NOTHING was written — {run.run_id} keeps "
                    "`judge_status: pending`, and the pass is idempotent, so run it again when the "
                    "provider recovers."
                )
    finally:
        await runner.aclose()

    judged = runner.assemble(scored, duration_s=run.duration_s or 0.0)
    # The drive pass's provenance is the run's; only the judged half is new.
    judged.created_at = run.created_at
    judged.git_sha = run.git_sha
    judged.label = run.label
    judged.duration_s = run.duration_s
    # The pass produces notes of its own — §13.7's `judge/reference disagreements:` line above all,
    # which only a judged run can produce. Union them with the drive pass's rather than replacing
    # them with it, or the disagreement list would never reach the file and `--recompute-agreement`
    # would be the only way to see it.
    judged.notes = _judge_pass_note(_merge_notes(run.notes, runner.notes), judged)
    runner.write_artifacts(judged)
    write_report(judged, results_dir=Path(results_dir))
    return judged


def _merge_notes(previous: str | None, produced: Sequence[str]) -> str:
    """The previous file's notes, plus whichever of this pass's notes it does not already carry.

    The judge pass is idempotent (§13.2) and so is this: on a second pass every produced note is
    already in `previous` — the first pass appended it there — so nothing is added and the file
    comes back byte-identical.
    """
    merged = (previous or "").strip()
    for note in produced:
        if note and note not in merged:
            merged = f"{merged} {note}".strip()
    return merged


def _judge_pass_note(previous: str | None, judged: RunFile) -> str:
    """Append — idempotently — the one sentence that says when the judged half was added."""
    stripped = re.sub(r"\s*Judged in a second pass.*?$", "", previous or "", flags=re.S).strip()
    note = (
        f"Judged in a second pass on {time.strftime('%Y-%m-%d', time.gmtime())} "
        f"({judged.judge_calls} judge calls, model {judged.judge_model}); the 26 answers are the "
        "drive pass's own and were not re-driven."
    )
    return f"{stripped} {note}".strip() if stripped else note


def recompute_agreement(
    run_id: str,
    *,
    results_dir: Path = RESULTS_DIR,
    metric: str = "judge_agreement_rate",
    labels_path: Path | str | None = None,
) -> RunFile:
    """Fold a reference label set into a finished run — the §13.7 ordering, made honest.

    The labeller sees only the questions, the answers and the evidence, and it can only see those
    once the run has produced them; the judge's verdicts are never shown to it. So an agreement rate
    is computed here, over the run file's committed per-item groundedness, rather than during the
    run that produced them. Nothing is re-driven and nothing is re-judged.

    `metric` picks a row of `AGREEMENT_METRICS` — the blind `seed_1729_8` subset by default, or the
    disclosed `judge_lowest_8` hard-case subset — and decides which three fields are written and
    which labels file is read. The labels file's own `protocol.subset` is checked against it, so
    passing the wrong `--labels` is an error rather than a silently mislabelled figure.
    """
    slot = AGREEMENT_METRICS.get(metric)
    if slot is None:
        raise SystemExit(f"unknown agreement metric {metric!r}; expected one of {', '.join(sorted(AGREEMENT_METRICS))}")
    source = Path(labels_path) if labels_path is not None else slot.labels_path
    path = Path(results_dir) / f"{run_id}.json"
    run = RunFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    labels = load_reference_labels(source)
    if labels is None:
        raise SystemExit(f"{source} does not exist; there is nothing to compare against")
    if labels.protocol.subset != slot.subset:
        raise SystemExit(
            f"{source} declares `protocol.subset: {labels.protocol.subset}` but --metric {metric} "
            f"computes the {slot.subset!r} subset. Refusing to publish a figure under the wrong "
            "population (§13.7)."
        )
    rate, n, disagreements = det.judge_agreement(
        labels.labels,
        {item.item_id: item.scores.get("groundedness") for item in run.items if item.run_phase == "scored"},
    )
    setattr(run.metrics, slot.name, rate)
    setattr(run.metrics, slot.n_field, n)
    setattr(run.metrics, slot.subset_field, slot.subset)
    note = f"{slot.name}={rate} over n={n} reference labels (subset {slot.subset})."
    if disagreements:
        note += " disagreements: " + "; ".join(
            f"{row['item_id']} (reference {row['reference']}, judge {row['judge']})" for row in disagreements
        )
    run.notes = _agreement_note(run.notes, slot, note)
    path.write_text(json.dumps(run.model_dump(mode="json"), indent=1) + "\n", encoding="utf-8")
    write_report(run, results_dir=Path(results_dir))
    return run


def rewrite_report(run_id: str, *, results_dir: Path = RESULTS_DIR, path: Path = REPORT_PATH) -> RunFile:
    """Regenerate `evaluation/REPORT.md` from a committed run file. Reads only; spends nothing.

    §13.10 makes REPORT.md the human-readable face of the **published** run, but `write_artifacts`
    calls `write_report` for *every* run, so a sweep that ends on `no_structured_tools` leaves the
    report describing an ablation arm — which is what happened to the first deployed sweep. Until
    now the only ways to put it back were `--judge` and `--recompute-agreement`, both of which need
    a judge, so a run left `judge_status: pending` by an exhausted free-tier quota had no way at all.

    Run `python -m evaluation.ablation` afterwards to re-append the ablation section.
    """
    source = Path(results_dir) / f"{run_id}.json"
    if not source.exists():
        raise SystemExit(f"{source} does not exist; there is no run to report on")
    run = RunFile.model_validate(json.loads(source.read_text(encoding="utf-8")))
    findings = contamination_findings(run)
    if findings:
        raise SystemExit(
            f"{run.run_id} is contaminated and must not be published (§9.8, performance plan W1-A):\n  - "
            + "\n  - ".join(findings)
        )
    write_report(run, results_dir=Path(results_dir), path=path)
    return run


def _agreement_note(previous: str | None, slot: AgreementMetric, note: str) -> str:
    """Append this metric's note idempotently, leaving the *other* metric's note alone.

    Each agreement note lives on its own line and starts with its metric name, so a second fold-in
    of either subset replaces its own line and stacks nothing. The `re.sub` clears the
    pre-two-subset format, where the note was appended inline to the end of the prose paragraph
    rather than on a line of its own — hence `re.MULTILINE`, without which `$` anchors to the end
    of the whole string, the legacy note is never matched, and a fold-in stacks a second copy
    beside it instead of replacing it.
    """
    kept = [line for line in (previous or "").split("\n") if not line.startswith(f"{slot.name}=")]
    body = re.sub(rf"\s*{re.escape(slot.name)}=[^\n]*$", "", "\n".join(kept), flags=re.MULTILINE).strip()
    return f"{body}\n{note}".strip() if body else note


async def _main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.judge:
        run = await judge_run(args.judge, results_dir=Path(args.results_dir))
        print(  # noqa: T201 — this is a CLI
            json.dumps(
                {
                    "run_id": run.run_id,
                    "judge_status": run.judge_status,
                    "judge_calls": run.judge_calls,
                    "groundedness_mean": run.metrics.groundedness_mean,
                    "citation_accuracy_mean": run.metrics.citation_accuracy_mean,
                    "strict_pass_rate": run.metrics.strict_pass_rate,
                },
                indent=1,
            )
        )
        return 0
    if args.report:
        run = rewrite_report(args.report, results_dir=Path(args.results_dir))
        print(  # noqa: T201 — this is a CLI
            json.dumps(
                {"run_id": run.run_id, "variant": run.variant, "target": run.target, "judge_status": run.judge_status},
                indent=1,
            )
        )
        return 0
    if args.recompute_agreement:
        slot = AGREEMENT_METRICS[args.metric]
        run = recompute_agreement(
            args.recompute_agreement,
            results_dir=Path(args.results_dir),
            metric=args.metric,
            labels_path=args.labels,
        )
        print(  # noqa: T201 — this is a CLI
            json.dumps(
                {
                    "run_id": run.run_id,
                    "metric": slot.name,
                    "subset": getattr(run.metrics, slot.subset_field),
                    slot.name: getattr(run.metrics, slot.name),
                    slot.n_field: getattr(run.metrics, slot.n_field),
                },
                indent=1,
            )
        )
        return 0
    try:
        base_url = require_base_url(args.base_url or default_settings.eval_target_base_url)
    except BadTargetUrl as exc:
        print(f"FAIL — {exc}", file=sys.stderr)  # noqa: T201 — this is a CLI
        return 1
    store = get_store(default_settings)
    migrate(store)
    trace_module.set_writer(TraceWriter(store))
    runner = Runner(
        RunOptions(
            variant=args.variant,
            base_url=base_url,
            label=args.label,
            judge=args.judge_inline,
            item_ids=[value for value in args.items.split(",") if value],
            n_items=args.n_items,
            cold_probes=args.cold_probes,
            notes=args.notes,
            results_dir=Path(args.results_dir),
        ),
        store=store,
    )
    try:
        run = await runner.run()
    finally:
        await runner.aclose()
    print(  # noqa: T201 — this is a CLI
        json.dumps(
            {
                "run_id": run.run_id,
                "variant": run.variant,
                "target": run.target,
                "n_items": run.n_items,
                "strict_pass_rate": run.metrics.strict_pass_rate,
                "groundedness_mean": run.metrics.groundedness_mean,
                "doc_recall_mean": run.metrics.doc_recall_mean,
                "workflow_completion": run.metrics.workflow_completion,
                "judge_calls": run.judge_calls,
                "est_cost_usd": run.metrics.est_cost_usd,
                "duration_s": run.duration_s,
            },
            indent=1,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "ABLATION_BEGIN",
    "ABLATION_END",
    "BadTargetUrl",
    "Runner",
    "RunOptions",
    "build_parser",
    "fmt",
    "main",
    "recompute_agreement",
    "rewrite_report",
    "render_report",
    "require_base_url",
    "resolve_target",
    "run_id_for",
    "smoke_run",
    "write_report",
]
