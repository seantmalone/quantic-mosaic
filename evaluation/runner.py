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
from evaluation.judges import VERDICT_SCORES, Claim, Judge
from evaluation.schema import (
    COLD_PROBE_IDS,
    REPORT_PATH,
    RESULTS_DIR,
    VARIANT_OPTIONS,
    Dataset,
    EvalItem,
    ItemResult,
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


def resolve_target(base_url: str) -> str:
    """`local` for a loopback URL, `deployed` for anything else (§13.2)."""
    host = httpx.URL(base_url).host
    return "local" if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0") else "deployed"


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
        self.options.base_url = options.base_url or self.settings.eval_target_base_url
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
        scores: dict[str, Any] = {}
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
        chunk_text = dict(evidence)

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
                (chunk_id, chunk_text[chunk_id])
                for chunk_id in citations_by_claim.get(claim.id, [])
                if chunk_id in chunk_text
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

        metrics = RunMetrics(
            judged=self._judge_enabled,
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
            strict_pass_rate=det.mean([float(entry.result.passed) for entry in run_phase_scored]),
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
                "groundedness": len(groundedness),
                "citation_accuracy": len(cit_accuracy),
                "cit_resolve": len(cit_resolve),
                "doc_recall": len(doc_recall),
                "partial_match": len(partial),
                "clarification": len(clarification),
                "tool_selection": len(selection),
                "arg_correctness": len(arg_rates),
                "workflow": len(workflow),
                "safety": len(safety),
                "behaviour": len(pairs),
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


def _evidence_of(turn: det.TurnRecord) -> list[tuple[str, str]]:
    """The chunk text **actually present in the synthesis prompt**, read from the retrieval spans.

    `synthesize.j2` renders `chunk.text` — the whole stored chunk — so resolving each retrieved,
    non-quarantined id through `core.corpusread` reproduces the evidence the model saw, byte for
    byte, with **no re-retrieval** (§13.3).
    """
    evidence: list[tuple[str, str]] = []
    seen: set[str] = set()
    for span in turn.of_kind("retrieval"):
        for chunk in span.payload.get("chunks") or []:
            chunk_id = chunk.get("chunk_id")
            if not chunk_id or chunk_id in seen or chunk.get("quarantined"):
                continue
            seen.add(chunk_id)
            row = corpusread.get_chunk(chunk_id)
            evidence.append((chunk_id, row.text if row is not None else chunk.get("snippet") or ""))
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


def fmt(value: Any, digits: int = 3) -> str:
    """One metric cell: `None` renders as an em dash, never as 0."""
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


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
    lines = ["| Metric | Value | n |", "|---|---|---|"]
    lines += [f"| {name} | {fmt(value)} | {fmt(n)} |" for name, value, n in rows]
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
    labels = load_reference_labels()
    protocol = labels.protocol if labels is not None else None
    metrics = run.metrics
    thresholds = (
        f"MIN_EVIDENCE_SCORE = {run.config.min_evidence_score} · MIN_SUPPORT_SCORE = {run.config.min_support_score}"
    )
    protocol_line = (
        f"Protocol: labeller `{protocol.labeller}`, labelled {protocol.labelled_on}. {protocol.blinding}"
        if protocol is not None
        else "_`evaluation/reference_labels.yaml` is not present._"
    )
    judged_note = (
        "Judged metrics are computed on `baseline` only (§13.9): judging all three arms would "
        "roughly triple the judge volume against a free-tier daily cap, and DocRecall, "
        "ToolSelection and Workflow — the judge-free metrics — are precisely what the two arms move."
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
| Judge model | `{run.judge_model or "—"}` · {run.judge_calls} judge calls |
| Retrieval | `{run.config.retrieval_strategy}`, k = {run.config.retrieval_k} |
| Guardrail thresholds | {thresholds} |
| Limiter | LLM_RPM = {run.config.llm_rpm} |
| Estimated spend | ${fmt(metrics.est_cost_usd, 4)} |
| Wall clock | {fmt(run.duration_s, 1)} s |
| git sha | `{run.git_sha}` |

## Headline metrics

{_metric_table(run)}

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

**Judge validation is an agreement rate, not a κ.** `judge_agreement_rate` =
**{fmt(metrics.judge_agreement_rate)}** with `judge_agreement_n` = **{metrics.judge_agreement_n}**.
The reference labels were authored by an independent model subagent, blind to the judge's verdicts;
at n = 8 a κ's confidence interval is wide enough to be meaningless, while an agreement rate with
its n stated is honest (§13.7, §22). This is **never** "human-vs-judge".

{protocol_line}

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
    runner = Runner(options)
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
    parser.add_argument("--no-judge", action="store_true", help="skip the judged metrics entirely")
    parser.add_argument("--cold-probes", action="store_true", help="run the three §13.5 cold probes")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR))
    return parser


async def _main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = get_store(default_settings)
    migrate(store)
    trace_module.set_writer(TraceWriter(store))
    runner = Runner(
        RunOptions(
            variant=args.variant,
            base_url=args.base_url or default_settings.eval_target_base_url,
            label=args.label,
            judge=not args.no_judge,
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
    "Runner",
    "RunOptions",
    "build_parser",
    "fmt",
    "main",
    "render_report",
    "resolve_target",
    "run_id_for",
    "smoke_run",
    "write_report",
]
