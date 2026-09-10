"""Cold-probe rows never enter a quality mean (spec §13.4, §13.5).

> The three cold re-runs carry `run_phase = 'cold_probe'`, and every quality and behaviour
> denominator filters `run_phase = 'scored'`. `tests/unit/test_cold_probe_excluded.py` asserts that
> adding three such rows changes no quality metric and changes only `n_cold` and the cold
> percentiles.

The assertion is made against `Runner.assemble()` — the one function that turns per-item results
into a `RunMetrics` — with synthetic scored items, so no network, no model and no target are
involved. A cold probe is deliberately given *terrible* scores and a huge latency: if the filter
were missing, every quality mean and every warm percentile would move.
"""

from __future__ import annotations

import pytest

from evaluation import deterministic as det
from evaluation.runner import Runner, RunOptions, ScoredItem
from evaluation.schema import COLD_PROBE_IDS, ItemResult, load_dataset

DATASET = load_dataset()

#: The metric block minus the three fields a cold probe is *allowed* to move.
COLD_ONLY_FIELDS = {"n_cold", "cold_p50_ms", "est_cost_usd"}


def _scored(item_id: str, *, run_phase: str, quality: float, latency_ms: int, cold: int) -> ScoredItem:
    item = DATASET.by_id(item_id)
    assert item is not None
    usage = det.ToolUsage(called=list(item.expected_tools), gated=[], failed=[], ok_spans=[])
    tool = det.tool_scores(item, usage)
    result = ItemResult(
        id=f"r::{item_id}::{run_phase}",
        item_id=item_id,
        category=item.category,
        session_id="s" * 32,
        turn_id="t" * 32,
        run_phase=run_phase,  # type: ignore[arg-type]
        answer="an answer",
        latency_ms=latency_ms,
        cold=cold,
        scores={
            "cit_resolve": quality,
            "arg_correctness": quality,
            "safety": 1.0,
            "blocks_dropped_by_g2": 0,
            "gated_attempts": 0,
            "nudged": False,
            "catalog_reopened": False,
            "router_intent": "policy_qa",
            "recommendation_labeled_rate": quality,
            "outcome": "answered",
            "tools_called": list(item.expected_tools),
            "cache_hits": 0,
        },
        verdicts=None,
        passed=int(quality >= 1.0),
    )
    return ScoredItem(
        result=result,
        item=item,
        turn=None,
        gold_behavior=item.expected_behavior,
        predicted_behavior="answer",
        tool=tool,
        doc_recall=quality,
        workflow=quality,
        groundedness=quality,
        citation_accuracy=quality,
        partial_match=quality,
        clarification=None,
        cost_usd=0.0,
    )


@pytest.fixture
def runner(store):
    return Runner(
        RunOptions(variant="baseline", base_url="http://127.0.0.1:8000", judge=False),
        store=store,
        dataset=DATASET,
        judge=None,
    )


def _scored_items() -> list[ScoredItem]:
    return [
        _scored("pto-001", run_phase="scored", quality=1.0, latency_ms=3000, cold=0),
        _scored("remote-001", run_phase="scored", quality=1.0, latency_ms=3200, cold=0),
        _scored("benefits-001", run_phase="scored", quality=1.0, latency_ms=3400, cold=0),
    ]


def _cold_probes() -> list[ScoredItem]:
    return [
        _scored(item_id, run_phase="cold_probe", quality=0.0, latency_ms=45_000, cold=1) for item_id in COLD_PROBE_IDS
    ]


def test_the_cold_probes_use_the_three_ids_the_spec_names():
    assert [entry.result.item_id for entry in _cold_probes()] == list(COLD_PROBE_IDS)


def test_adding_three_cold_probes_changes_no_quality_metric(runner):
    warm = runner.assemble(_scored_items(), duration_s=1.0).metrics.model_dump(mode="json")
    with_probes = runner.assemble(_scored_items() + _cold_probes(), duration_s=1.0).metrics.model_dump(mode="json")

    moved = {name for name, value in with_probes.items() if warm[name] != value}
    assert moved <= COLD_ONLY_FIELDS, f"a cold probe moved {sorted(moved - COLD_ONLY_FIELDS)}"


def test_the_cold_probes_move_n_cold_and_the_cold_percentiles(runner):
    warm = runner.assemble(_scored_items(), duration_s=1.0).metrics
    with_probes = runner.assemble(_scored_items() + _cold_probes(), duration_s=1.0).metrics

    assert warm.n_cold == 0
    assert warm.cold_p50_ms is None
    assert with_probes.n_cold == 3
    assert with_probes.cold_p50_ms == pytest.approx(45_000)


def test_the_warm_percentiles_ignore_the_cold_latencies(runner):
    with_probes = runner.assemble(_scored_items() + _cold_probes(), duration_s=1.0).metrics
    assert with_probes.latency_p95_ms is not None
    assert with_probes.latency_p95_ms < 10_000


def test_n_items_counts_only_the_scored_rows(runner):
    run = runner.assemble(_scored_items() + _cold_probes(), duration_s=1.0)
    assert run.n_items == 3
    assert len(run.items) == 6
    assert [row.run_phase for row in run.items].count("cold_probe") == 3


def test_the_strict_pass_rate_is_not_dragged_down_by_a_failing_probe(runner):
    run = runner.assemble(_scored_items() + _cold_probes(), duration_s=1.0)
    assert run.metrics.strict_pass_rate == 1.0
