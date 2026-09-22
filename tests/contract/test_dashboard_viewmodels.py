"""Every `/api/*` payload is exactly its typed view-model (spec §11.6, §11.8, §13.9).

§11.6's rule is that *every page renders from the typed Pydantic view-model produced by the same
`/api/*` endpoint that serves its JSON*. This file is the other half of that contract: it validates
each endpoint's JSON against the class `web/dashboard.py` declares — every one of which is
`extra="forbid"`, so a payload with a stray or renamed field fails here rather than silently
diverging from the page — and it pins down page 11's metric block:

* the **four judged aggregates** are `Optional[float]` beside `judged: bool` and `n_scored{}`, and
  are `null` on the two ablation arms because judging happens on `baseline` only (§13.9) — never a
  fabricated zero;
* the **five deterministic aggregates** are non-null on **every** variant.

It also holds `GET /api/traces/turns/{turn_id}` to the field set P8's callers already read — the
202 fallback of §9.4 and `scripts/demo_task_*.sh` poll it — while P9 grows it into page 3's full
view-model.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import BaseModel

from hrmosaic.web import dashboard as dash

pytestmark = pytest.mark.anyio

ADMIN = {"X-Actor": "admin"}
EVAL_RUNS = Path(__file__).resolve().parents[1] / "fixtures" / "eval_runs"

DEMO_1 = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"

VARIANT_RUNS = {
    "baseline": "r_p9fixture_baseline",
    "dense_only_k2": "r_p9fixture_dense_only_k2",
    "no_structured_tools": "r_p9fixture_no_structured_tools",
}

#: The fields `scripts/demo_task_*.sh` and §9.4's 202 fallback already read off the single-turn
#: route. P9 may add to this set; it may never drop from it.
P8_TURN_FIELDS = {
    "turn_id",
    "session_id",
    "seq",
    "started_at",
    "ended_at",
    "duration_ms",
    "user_message",
    "final_answer",
    "answer_blocks",
    "citations",
    "outcome",
    "stop_reason",
    "intent",
    "workflow",
    "resumed_count",
    "rollups",
    "spans",
    "dashboard_url",
}


@pytest.fixture
async def seeded(web, store):
    """One real turn, the three committed run fixtures, and the eval rows wired to that turn."""
    from hrmosaic.core import archive
    from hrmosaic.core.db import Statement

    async with web("demo_task_1.json") as client:
        answered = await client.post("/chat", json={"message": DEMO_1, "client_label": "demo"})
        assert answered.status_code == 200, answered.text
        turn = answered.json()

        report = archive.import_results(store=store, results_dir=EVAL_RUNS)
        assert len(report.imported) >= 3, report
        # §13.2's "one click from any eval row to its full audit trace": point one scored row at the
        # real turn, so the metrics tab's by-kind decomposition and RSS series have rows to read.
        store.batch(
            [
                Statement(
                    "UPDATE eval_results SET session_id = ?, turn_id = ? "
                    "WHERE run_id = 'r_p9fixture_baseline' AND item_id = 'remote-004'",
                    (turn["session_id"], turn["turn_id"]),
                )
            ]
        )
        chunk_id = turn["citations"][0]["chunk_id"]
        yield {"client": client, "turn": turn, "chunk_id": chunk_id}


async def _get(seeded, url: str) -> dict:
    response = await seeded["client"].get(url, headers=ADMIN)
    assert response.status_code == 200, f"{url}: {response.text[:400]}"
    return response.json()


# --------------------------------------------------------------------------------------
# Every endpoint validates against its declared view-model
# --------------------------------------------------------------------------------------


async def test_every_api_payload_validates_against_its_typed_view_model(seeded):
    session_id = seeded["turn"]["session_id"]
    turn_id = seeded["turn"]["turn_id"]
    cases = [
        ("/api/traces/overview", dash.OverviewView),
        ("/api/traces/sessions", dash.SessionsView),
        (f"/api/traces/sessions/{session_id}", dash.SessionDetailView),
        ("/api/traces/turns", dash.TurnsView),
        (f"/api/traces/turns/{turn_id}", dash.TurnDetail),
        ("/api/traces/llm", dash.LlmView),
        ("/api/traces/retrieval", dash.RetrievalView),
        ("/api/traces/tools", dash.ToolsView),
        ("/api/traces/safety", dash.SafetyView),
        ("/api/mcp/discovery", dash.McpDiscoveryView),
        ("/api/corpus/documents", dash.CorpusView),
        ("/api/corpus/documents/pto-and-holidays", dash.CorpusDocumentView),
        (f"/api/corpus/chunks/{seeded['chunk_id']}", dash.CorpusChunkView),
        ("/api/eval/runs", dash.EvalRunsView),
        ("/api/eval/runs/r_p9fixture_baseline", dash.EvalRunDetailView),
        ("/api/eval/compare", dash.EvalCompareView),
    ]
    for url, model in cases:
        payload = await _get(seeded, url)
        # `extra="forbid"` throughout: a stray or renamed field fails here, not on the page.
        assert model.model_validate(payload), url


async def test_every_page_exports_the_json_of_the_endpoint_it_renders(seeded):
    """The Export JSON button of §11.6 points at the endpoint that produced the page's model."""
    import re

    pages = {
        "/dashboard": "/api/traces/overview",
        "/dashboard/sessions": "/api/traces/sessions",
        f"/dashboard/sessions/{seeded['turn']['session_id']}": (f"/api/traces/sessions/{seeded['turn']['session_id']}"),
        "/dashboard/turns": "/api/traces/turns",
        "/dashboard/llm": "/api/traces/llm",
        "/dashboard/retrieval": "/api/traces/retrieval",
        "/dashboard/tools": "/api/traces/tools",
        "/dashboard/safety": "/api/traces/safety",
        "/dashboard/mcp": "/api/mcp/discovery",
        "/dashboard/corpus": "/api/corpus/documents",
        "/dashboard/corpus/pto-and-holidays": "/api/corpus/documents/pto-and-holidays",
        "/dashboard/evals": "/api/eval/runs",
        "/dashboard/evals/r_p9fixture_baseline": "/api/eval/runs/r_p9fixture_baseline",
    }
    for page, api in pages.items():
        response = await seeded["client"].get(page, headers=ADMIN)
        assert response.status_code == 200, page
        match = re.search(r'id="export-json"[^>]*href="([^"]+)"', response.text)
        assert match, page
        assert match.group(1).split("?")[0] == api, page
        assert (await seeded["client"].get(match.group(1), headers=ADMIN)).status_code == 200, page


# --------------------------------------------------------------------------------------
# The single-turn route P8's callers poll
# --------------------------------------------------------------------------------------


async def test_the_single_turn_route_still_carries_every_field_p8_shipped(seeded):
    payload = await _get(seeded, f"/api/traces/turns/{seeded['turn']['turn_id']}")
    assert P8_TURN_FIELDS <= set(payload)
    assert payload["outcome"] == "answered"
    assert payload["dashboard_url"].startswith(f"/dashboard/sessions/{payload['session_id']}#turn-")
    assert {"llm_calls", "tool_calls", "retrievals", "guardrail_hits"} <= set(payload["rollups"])
    assert payload["spans"], "the turn recorded no spans"
    for span in payload["spans"]:
        assert {"span_id", "seq", "kind", "name", "status", "duration_ms", "offset_ms", "payload"} <= set(span)


async def test_the_single_turn_route_is_the_same_record_as_the_session_page(seeded):
    """USER.4: the concise trace, page 3 and this route are one set of rows, not three."""
    turn_id = seeded["turn"]["turn_id"]
    single = await _get(seeded, f"/api/traces/turns/{turn_id}")
    session = await _get(seeded, f"/api/traces/sessions/{seeded['turn']['session_id']}")
    matching = [turn for turn in session["turns"] if turn["turn_id"] == turn_id]
    assert matching == [single]
    assert {span["seq"] for span in single["spans"]} == {entry["seq"] for entry in seeded["turn"]["trace"]}


async def test_an_unknown_turn_and_session_answer_404_with_a_typed_code(seeded):
    missing_turn = await seeded["client"].get(f"/api/traces/turns/{'0' * 32}", headers=ADMIN)
    missing_session = await seeded["client"].get(f"/api/traces/sessions/{'0' * 32}", headers=ADMIN)
    assert missing_turn.status_code == 404
    assert missing_turn.json()["code"] == "UNKNOWN_TURN"
    assert missing_session.status_code == 404
    assert missing_session.json()["code"] == "UNKNOWN_SESSION"


# --------------------------------------------------------------------------------------
# Page 11's metric block — the judged / deterministic split (§11.6, §13.9)
# --------------------------------------------------------------------------------------


async def test_the_four_judged_aggregates_are_null_on_every_variant_that_was_not_judged(seeded):
    assert dash.JUDGED_METRICS == (
        "groundedness_mean",
        "citation_accuracy_mean",
        "partial_match_mean",
        "clarification_accuracy",
    )
    for variant, run_id in VARIANT_RUNS.items():
        metrics = (await _get(seeded, f"/api/eval/runs/{run_id}"))["metrics"]
        assert metrics["judged"] is (variant == "baseline"), variant
        for name in dash.JUDGED_METRICS:
            if variant == "baseline":
                assert metrics[name] is not None, f"{variant}.{name}"
            else:
                # never a fabricated zero: the field is absent-as-null and the page says so
                assert metrics[name] is None, f"{variant}.{name}"


async def test_the_five_deterministic_aggregates_are_non_null_on_all_three_variants(seeded):
    assert dash.DETERMINISTIC_METRICS == (
        "cit_resolve_mean",
        "blocks_dropped_by_g2",
        "tool_selection_accuracy",
        "arg_correctness_rate",
        "strict_pass_rate",
    )
    for variant, run_id in VARIANT_RUNS.items():
        metrics = (await _get(seeded, f"/api/eval/runs/{run_id}"))["metrics"]
        for name in dash.DETERMINISTIC_METRICS:
            assert metrics[name] is not None, f"{variant}.{name}"


async def test_n_scored_is_reported_beside_every_judged_metric(seeded):
    """§13.7: a verdict that could not be parsed excludes the item — never a silent zero."""
    metrics = (await _get(seeded, "/api/eval/runs/r_p9fixture_baseline"))["metrics"]
    assert metrics["n_scored"], "n_scored must accompany the judged aggregates"
    assert metrics["n_scored"]["groundedness"] >= 1
    arm = (await _get(seeded, "/api/eval/runs/r_p9fixture_dense_only_k2"))["metrics"]
    assert "groundedness" not in arm["n_scored"]


async def test_the_metric_block_carries_the_whole_of_section_11_6(seeded):
    metrics = (await _get(seeded, "/api/eval/runs/r_p9fixture_baseline"))["metrics"]
    for name in (
        "escalation_matrix",
        "escalation_n_excluded",
        "over_refusal_rate",
        "over_refusal_n",
        "missed_refusal_rate",
        "missed_refusal_n",
        "action_safety_pass_rate",
        "workflow_completion_by_workflow",
        "recommendation_labeled_rate",
        "router_matrix",
        "catalog_reopened_rate",
        "n_scored",
        "judge_agreement_rate",
        "judge_agreement_n",
        "est_cost_usd",
    ):
        assert name in metrics, name
    assert len(metrics["escalation_matrix"]) == 5, "the 5×5 escalation matrix of §13.4"
    assert metrics["est_cost_usd"] is not None


async def test_each_judge_agreement_figure_is_rendered_beside_the_subset_it_was_computed_over(seeded):
    """§13.7's two figures are two samples, and the page says which (G5b, gap 13).

    The tile printed `judge_agreement_rate` alone, so a run whose `judge_agreement_subset` is null —
    `r_1790067656_baseline`, whose 1.000 over n = 8 was folded in from a label file authored against
    **another run's** served answers — rendered as an uncaveated figure one click from the published
    run. And the hard-case figure every run file carries reached no template at all, which is the same
    defect from the other side: the blind subset came back 8/8 on both sides, so it is the disclosed
    hard-case subset that carries the information, and it was the one not shown.
    """
    metrics = (await _get(seeded, "/api/eval/runs/r_p9fixture_baseline"))["metrics"]
    assert (metrics["judge_agreement_subset"], metrics["judge_agreement_subset_hard"]) == (
        "seed_1729_8",
        "judge_lowest_8",
    )

    page = await seeded["client"].get("/dashboard/evals/r_p9fixture_baseline", headers=ADMIN)
    block = re.search(r'id="behaviour-metrics".*?</dl>', page.text, re.S)
    assert block, "the behaviour-and-safety list still renders"
    body = " ".join(block.group(0).split())
    assert dash.METRIC_LABELS["judge_agreement_rate"] in body
    assert "seed 1729 8 subset" in body, body
    assert dash.METRIC_LABELS["judge_agreement_rate_hard"] in body, "the hard figure reaches the page"
    assert "judge lowest 8 subset" in body, body


async def test_the_headline_strip_is_the_eight_metrics_the_spec_names(seeded):
    runs = (await _get(seeded, "/api/eval/runs"))["runs"]
    baseline = next(run for run in runs if run["run_id"] == "r_p9fixture_baseline")
    assert set(baseline["headline"]) == set(dash.HEADLINE_METRICS)
    arm = next(run for run in runs if run["variant"] == "dense_only_k2")
    assert arm["headline"]["groundedness_mean"] is None
    assert arm["headline"]["cit_resolve_mean"] is not None


# --------------------------------------------------------------------------------------
# The compare and metrics tabs
# --------------------------------------------------------------------------------------


async def test_the_compare_tab_carries_one_run_per_variant_the_flips_and_the_chunk_sweep(seeded, monkeypatch):
    monkeypatch.setattr(dash, "RESULTS_DIR", EVAL_RUNS)
    payload = await _get(seeded, "/api/eval/compare")
    assert [row["variant"] for row in payload["variants"]][0] == "baseline"
    assert {row["variant"] for row in payload["variants"]} == set(VARIANT_RUNS)
    assert payload["flips"], "the ablation arms must move at least one item"
    for flip in payload["flips"]:
        assert flip["baseline_passed"] != flip["variant_passed"]
    assert [point["chunk_chars"] for point in payload["chunk_size"]] == [700, 1100, 1600]


#: The two builds of G5 gap 8: the published `baseline` was re-driven on `bd4ac93` while both arms
#: stayed on `34717b5`, and the compare tab paired them with no sha anywhere in the payload.
BUILD_A = "bd4ac9336e87f1233f848ef4e5635c29e07cd15b"
BUILD_B = "34717b52eb01312097ec41fe8a07394843d215d6"


async def _compare_run_ids(seeded) -> dict[str, str]:
    """Which run the tab shows per variant — the newest of each, whatever the store holds."""
    payload = await _get(seeded, "/api/eval/compare")
    return {row["variant"]: row["run_id"] for row in payload["variants"]}


def _results_dir(tmp_path, builds: dict[str, str] | None = None, comparison: dict | None = None):
    """A results directory holding exactly the provenance the compare tab reads from disk.

    `eval_runs` predates `target_git_sha` (`core/archive.py` has no column to import it into), so the
    build behind an arm is read back from `evaluation/results/<run_id>.json` and the published check
    from `comparison.json`. Those two files are what this builds, keyed by the run ids the tab is
    actually showing.
    """
    import json

    for run_id, sha in (builds or {}).items():
        (tmp_path / f"{run_id}.json").write_text(
            json.dumps({"run_id": run_id, "target_git_sha": sha}), encoding="utf-8"
        )
    if comparison is not None:
        (tmp_path / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
    return tmp_path


async def test_the_compare_tab_names_each_arms_build_and_says_so_when_they_differ(seeded, monkeypatch, tmp_path):
    """**G5 gap 8**: a cross-build pairing is visible, not implied.

    The tab takes the newest run of each variant, which is exactly how a `baseline` re-driven on a
    later commit came to sit beside two arms from an earlier one while `dense_only_k2` appeared to
    *beat* it on tool selection — a difference between two builds of the assistant, read as the
    effect of dropping the sparse retriever.
    """
    runs = await _compare_run_ids(seeded)
    builds = {runs["baseline"]: BUILD_A, runs["dense_only_k2"]: BUILD_B, runs["no_structured_tools"]: BUILD_B}
    monkeypatch.setattr(dash, "RESULTS_DIR", _results_dir(tmp_path, builds=builds))

    payload = await _get(seeded, "/api/eval/compare")
    assert {row["variant"]: row["target_git_sha"] for row in payload["variants"]} == {
        "baseline": BUILD_A,
        "dense_only_k2": BUILD_B,
        "no_structured_tools": BUILD_B,
    }
    assert payload["builds_differ"] is True

    page = await seeded["client"].get("/dashboard/evals?tab=compare", headers=ADMIN)
    assert page.status_code == 200, page.text[:400]
    assert 'id="ablation-build-notice"' in page.text, "the page must say the arms are on two builds"
    assert 'id="ablation-builds-table"' in page.text
    # The short form beside each arm, with the full sha one hover away.
    assert BUILD_A[:8] in page.text and BUILD_B[:8] in page.text


async def test_one_shared_build_still_names_it_and_raises_no_notice(seeded, monkeypatch, tmp_path):
    runs = await _compare_run_ids(seeded)
    monkeypatch.setattr(dash, "RESULTS_DIR", _results_dir(tmp_path, builds=dict.fromkeys(runs.values(), BUILD_B)))
    payload = await _get(seeded, "/api/eval/compare")
    assert {row["target_git_sha"] for row in payload["variants"]} == {BUILD_B}
    assert payload["builds_differ"] is False

    page = await seeded["client"].get("/dashboard/evals?tab=compare", headers=ADMIN)
    assert 'id="ablation-build-notice"' not in page.text, "one build is not a mixed pairing"
    assert 'id="ablation-builds-table"' in page.text, "the build is named either way"


async def test_a_build_no_run_file_records_is_unknown_rather_than_shared(seeded, monkeypatch, tmp_path):
    """A `local` run and every run file written before 2026-09-11 carry no `target_git_sha`, and a
    dashboard smoke run has no file at all. None of that is evidence that two arms agree."""
    monkeypatch.setattr(dash, "RESULTS_DIR", _results_dir(tmp_path))  # no run files, no comparison
    payload = await _get(seeded, "/api/eval/compare")
    assert all(row["target_git_sha"] is None for row in payload["variants"])
    assert payload["builds_differ"] is False
    assert payload["workflow_check"] is None

    page = await seeded["client"].get("/dashboard/evals?tab=compare", headers=ADMIN)
    assert 'id="ablation-build-notice"' not in page.text
    assert 'id="workflow-completion-check"' not in page.text, "no published comparison to quote"


async def test_the_compare_tab_charts_both_arms_hypothesis_metrics(seeded, monkeypatch):
    """**G5 gap 25**: `workflow_completion` and `doc_recall_mean` reach the page at all.

    `EvalMetrics` is `extra="ignore"`, so the two figures the arms exist to move were dropped on
    validation: the demo's closing beat said a workflow-completion delta that was on no chart.
    """
    monkeypatch.setattr(dash, "RESULTS_DIR", EVAL_RUNS)
    payload = await _get(seeded, "/api/eval/compare")
    for row in payload["variants"]:
        assert row["metrics"]["workflow_completion"] is not None, row["variant"]
        assert row["metrics"]["doc_recall_mean"] is not None, row["variant"]

    page = await seeded["client"].get("/dashboard/evals?tab=compare", headers=ADMIN)
    series = re.search(r'id="chart-ablation-series"[^>]*>(.*?)</script>', page.text, re.S)
    assert series, "the compare tab still declares its shared series list"
    assert "workflow_completion" in series.group(1) and "doc_recall_mean" in series.group(1)
    # One list, read by the chart and by the read-out table beside it (UX W5).
    assert dash.METRIC_LABELS["workflow_completion"] in page.text
    assert dash.METRIC_LABELS["doc_recall_mean"] in page.text


async def test_the_compare_tab_publishes_the_pre_registered_workflow_check(seeded, monkeypatch, tmp_path):
    """**G5 gap 25**: §13.9's delta and its bar, from `comparison.json`, which nothing in `src/` read.

    The check names the two runs it was computed on, because they are not always the newest run of
    each variant the tab charts above it — which is the whole of gap 8.
    """
    comparison = {
        "target": "deployed",
        "dataset_sha": "0" * 64,
        "target_git_sha": BUILD_B,
        "variants": [{"variant": name, "run_id": run_id} for name, run_id in VARIANT_RUNS.items()],
        "workflow_completion_check": {
            "supported": False,
            "reason": None,
            "baseline": 1.0,
            "no_structured_tools": 0.8333,
            "delta": -0.1667,
            "threshold": 0.25,
        },
    }
    monkeypatch.setattr(dash, "RESULTS_DIR", _results_dir(tmp_path, comparison=comparison))
    check = (await _get(seeded, "/api/eval/compare"))["workflow_check"]
    assert check == {
        "supported": False,
        "reason": None,
        "baseline": 1.0,
        "no_structured_tools": 0.8333,
        "delta": -0.1667,
        "threshold": 0.25,
        # The published check's own inputs — `r_p9fixture_*` here — which are **not** the newest run
        # of each variant the tab charts above it. That is gap 8 in one payload.
        "baseline_run_id": VARIANT_RUNS["baseline"],
        "no_structured_tools_run_id": VARIANT_RUNS["no_structured_tools"],
    }

    page = await seeded["client"].get("/dashboard/evals?tab=compare", headers=ADMIN)
    assert 'id="workflow-completion-check"' in page.text
    # The delta and the pre-registered bar, through the page's one rate formatter.
    assert dash._f_pct(-0.1667) in page.text and dash._f_pct(0.25) in page.text
    assert VARIANT_RUNS["baseline"] in page.text, "the check names the run it was computed on"


async def test_a_cold_latency_cell_with_no_samples_says_it_was_not_measured():
    """**G5 gap 25**: every published run has `n_cold = 0`, so both cold percentiles read `n=0` —
    a cell a grader reads as a measured zero, or as a defect. `n=0` alone is not a measurement."""
    assert dash._f_ms_n(None, 0) == "not measured (n=0)"
    assert dash._f_ms_n(4200, 0) == "not measured (n=0)", "no cold probe ran; there is nothing to print"
    assert dash._f_ms_n(4200, 3) == "n=3", "P14's small-sample rule is unchanged"
    assert dash._f_ms_n(4200, 40) == "4.20 s"


async def test_the_metrics_tab_reads_latency_from_the_run_and_the_decomposition_from_the_turns(seeded):
    payload = await _get(seeded, "/api/eval/runs/r_p9fixture_baseline")
    latency = payload["latency"]
    # 7 since W10 (addendum, DR4-03): the run carries one more item — the `unsafe_action` one the
    # action-safety guard needs a sample of its own from.
    assert latency["n_warm"] == 7
    assert latency["n_cold"] == 3
    assert latency["p50"] is not None and latency["p95"] is not None
    assert latency["cold_p50"] is not None
    # `remote-004` was pointed at the real turn in the fixture, so the store-derived blocks fill in
    assert set(latency["by_kind"]) == {"llm_ms", "retrieval_ms", "tool_ms", "store_ms"}
    assert [point["turn_id"] for point in payload["rss_series"]] == [seeded["turn"]["turn_id"]]


async def test_the_item_rows_carry_the_scores_verdicts_and_a_trace_link(seeded):
    items = (await _get(seeded, "/api/eval/runs/r_p9fixture_baseline"))["items"]
    linked = [item for item in items if item["item_id"] == "remote-004" and item["run_phase"] == "scored"]
    assert len(linked) == 1
    item = linked[0]
    assert item["scores"]
    assert item["verdicts"]["groundedness"]["judge_model"] == "gemini-3.5-flash-lite"
    assert item["trace_url"] == f"/dashboard/sessions/{seeded['turn']['session_id']}#turn-{item['turn_id']}"
    # `question` / `gold` come from `evaluation/dataset.yaml` — never from the stored answer, which
    # would make the page agree with itself by construction. P10 landed the dataset, so the two
    # columns are the dataset's own text for this item id.
    assert item["question"] == "I want to work from Berlin from 3 November to 14 December 2026 — can I?"
    assert item["gold"] and item["gold"].startswith("Conditional")


# --------------------------------------------------------------------------------------
# The trace pages read back what `core/trace.py` wrote
# --------------------------------------------------------------------------------------


async def test_the_overview_kpis_come_from_the_stored_rollups(seeded, store):
    payload = await _get(seeded, "/api/traces/overview")
    kpis = payload["kpis"]
    assert kpis["turns"] == store.execute("SELECT COUNT(*) AS n FROM turns").scalar()
    # §11.6 carry-forward: `guardrail_blocks` maps from `turns.guardrail_hits`, never a re-count
    assert kpis["guardrail_blocks"] == store.execute("SELECT COALESCE(SUM(guardrail_hits), 0) AS n FROM turns").scalar()
    assert kpis["tool_calls"] == store.execute("SELECT COUNT(*) AS n FROM spans WHERE kind = 'tool_call'").scalar()
    assert kpis["llm_daily_call_cap"] > 0
    assert len(payload["turns_per_hour"]) == 24
    assert payload["health"]["mcp_up"] is True
    assert payload["health"]["doc_count"] == 14


async def test_the_llm_retrieval_and_tool_pages_project_the_spans_of_the_turn(seeded, store, spans):
    recorded = spans(seeded["turn"]["turn_id"])
    llm = await _get(seeded, "/api/traces/llm")
    retrieval = await _get(seeded, "/api/traces/retrieval")
    tools = await _get(seeded, "/api/traces/tools")

    assert len(llm["rows"]) == len([row for row in recorded if row[0] == "llm_call"])
    assert {row["model"] for row in llm["by_model"]} == {row["model"] for row in llm["rows"]}
    # §11.6 page 5 reads `ttfb_ms` and `streamed` together: on a streamed call TTFB is the first
    # token, on one that did not stream it is the whole round trip (W2-E).
    assert all(row["ttfb_ms"] is not None for row in llm["rows"])
    # Only the synthesis call is given a delta sink — it is the only one whose output is prose a
    # person reads — so it is the only stubbed row that says it streamed.
    streamed = {row["purpose"] for row in llm["rows"] if row["streamed"]}
    assert streamed == {"synthesize"}
    assert len(retrieval["rows"]) == len([row for row in recorded if row[0] == "retrieval"])
    assert retrieval["top_documents"], "the demo-1 turn retrieves from at least one document"
    called = {row[2]["tool_name"] for row in recorded if row[0] == "tool_call"}
    assert {row["tool_name"] for row in tools["by_tool"]} >= called


async def test_the_session_row_carries_auth_mode_and_actor_role(seeded):
    rows = (await _get(seeded, "/api/traces/sessions"))["rows"]
    row = next(row for row in rows if row["session_id"] == seeded["turn"]["session_id"])
    assert row["auth_mode"] == "open"
    assert row["actor_role"] == "employee"
    assert row["client_label"] == "demo"
    assert row["outcomes"] == ["answered"]


# --------------------------------------------------------------------------------------
# P15 — the technical record is never destroyed, only relocated
# --------------------------------------------------------------------------------------
#
# UX W4 rounds numbers, renames labels and reorders columns across all thirteen pages. The
# principle that makes that safe is **P15**: every value removed from a *page* still exists,
# unrounded, in `/api/*` and in Export JSON. The two tests below are what hold it — a view-model
# may grow a field, and may never lose one, and no field may start carrying a formatted string
# where it carried a number.
#
# `BASE_FIELDS` is the snapshot: every field of every view-model at 42ca1fe, the commit W4 starts
# from, read off that revision's `web/dashboard.py` rather than typed out. A wave that needs to
# remove a field has to delete a line here, in a diff a reviewer reads.
BASE_FIELDS: dict[str, frozenset[str]] = {
    "ChunkSizePoint": frozenset(
        {
            "chunk_chars",
            "doc_recall_mean",
        }
    ),
    "ConfirmationRow": frozenset(
        {
            "action",
            "created_at",
            "human_summary",
            "turn_id",
            "used_at",
            "user_response",
        }
    ),
    "CorpusChunk": frozenset(
        {
            "char_end",
            "char_start",
            "chunk_id",
            "heading_path",
            "n_chars",
            "text",
        }
    ),
    "CorpusChunkView": frozenset(
        {
            "char_end",
            "char_start",
            "chunk_id",
            "doc_id",
            "doc_title",
            "heading_path",
            "n_chars",
            "section",
            "snippet",
            "text",
        }
    ),
    "CorpusDocument": frozenset(
        {
            "chunk_count",
            "doc_id",
            "doc_title",
            "estimated_pages",
            "section_count",
            "source_format",
            "topics",
        }
    ),
    "CorpusDocumentDetail": frozenset(
        {
            "chunk_count",
            "doc_id",
            "doc_title",
            "effective_date",
            "estimated_pages",
            "full_text",
            "section_count",
            "source_format",
            "topics",
            "version",
        }
    ),
    "CorpusDocumentView": frozenset(
        {
            "chunks",
            "document",
        }
    ),
    "CorpusView": frozenset(
        {
            "documents",
            "formats",
            "topics",
        }
    ),
    "DocumentHits": frozenset(
        {
            "doc_id",
            "doc_title",
            "hits",
        }
    ),
    "EvalCompareView": frozenset(
        {
            "chunk_size",
            "flips",
            "variants",
        }
    ),
    "EvalItemRow": frozenset(
        {
            "answer",
            "category",
            "cold",
            "gold",
            "item_id",
            "latency_ms",
            "passed",
            "question",
            "run_phase",
            "scores",
            "session_id",
            "trace_url",
            "turn_id",
            "verdicts",
        }
    ),
    "EvalMetrics": frozenset(
        {
            "action_safety_pass_rate",
            "arg_correctness_rate",
            "blocks_dropped_by_g2",
            "catalog_reopened_rate",
            "cit_resolve_mean",
            "citation_accuracy_mean",
            "clarification_accuracy",
            "escalation_matrix",
            "escalation_n_excluded",
            "est_cost_usd",
            "groundedness_mean",
            "judge_agreement_n",
            "judge_agreement_n_hard",
            "judge_agreement_rate",
            "judge_agreement_rate_hard",
            "judge_agreement_subset",
            "judge_agreement_subset_hard",
            "judged",
            "missed_refusal_n",
            "missed_refusal_rate",
            "n_scored",
            "over_refusal_n",
            "over_refusal_rate",
            "partial_match_mean",
            "recommendation_labeled_rate",
            "router_matrix",
            "strict_pass_rate",
            "tool_selection_accuracy",
            "workflow_completion_by_workflow",
        }
    ),
    "EvalRunDetailView": frozenset(
        {
            "items",
            "latency",
            "metrics",
            "rss_series",
            "run",
        }
    ),
    "EvalRunRow": frozenset(
        {
            "created_at",
            "duration_s",
            "est_cost_usd",
            "git_sha",
            "headline",
            "judge_model",
            "judged",
            "label",
            "n_items",
            "run_id",
            "target",
            "variant",
        }
    ),
    "EvalRunsView": frozenset(
        {
            "runs",
        }
    ),
    "Flip": frozenset(
        {
            "baseline_passed",
            "item_id",
            "variant",
            "variant_passed",
        }
    ),
    "HandshakeRow": frozenset(
        {
            "cached",
            "catalog_sha",
            "discovered_at",
            "handshake_ms",
            "span_id",
            "tool_count",
            "turn_id",
        }
    ),
    "HourBucket": frozenset(
        {
            "hour",
            "turns",
        }
    ),
    "InjectionHit": frozenset(
        {
            "chunk_id",
            "doc_id",
            "matched_pattern",
            "span_id",
        }
    ),
    "LatencyBlock": frozenset(
        {
            "by_kind",
            "cold_p50",
            "cold_p95",
            "n_cold",
            "n_warm",
            "p50",
            "p90",
            "p95",
            "p99",
        }
    ),
    "LlmRow": frozenset(
        {
            "cache_hit",
            "completion_tokens",
            "duration_ms",
            "finish_reason",
            "limiter_wait_ms",
            "model",
            "prompt_tokens",
            "provider",
            "provider_failover",
            "purpose",
            "retry_count",
            "span_id",
            "streamed",
            "ttfb_ms",
            "turn_id",
        }
    ),
    "LlmView": frozenset(
        {
            "by_model",
            "rows",
        }
    ),
    "McpDiscoveryView": frozenset(
        {
            "connected",
            "discovered_at",
            "handshake_history",
            "handshake_ms",
            "last_error",
            "protocol_version",
            "server",
            "tools",
            "transport",
            "url",
        }
    ),
    "MockWriteRow": frozenset(
        {
            "created_at",
            "employee_id",
            "id",
            "kind",
            "payload",
            "turn_id",
        }
    ),
    "ModelRollup": frozenset(
        {
            "calls",
            "est_cost_usd",
            "model",
            "tokens_in",
            "tokens_out",
        }
    ),
    "OverviewHealth": frozenset(
        {
            "chunk_count",
            "data_as_of",
            "doc_count",
            "git_sha",
            "mcp_up",
            "rss_mb",
            "store_backend",
            "tool_count",
            "uptime_ms",
        }
    ),
    "OverviewKpis": frozenset(
        {
            "error_rate",
            "escalations",
            "est_cost_usd",
            "guardrail_blocks",
            "llm_calls_today",
            "llm_daily_call_cap",
            "p50_ms",
            "p95_ms",
            "pending_confirmations",
            "sessions_24h",
            "sessions_total",
            "spend_7d_usd",
            "spend_today_usd",
            "tokens_in",
            "tokens_out",
            "tool_calls",
            "turns",
        }
    ),
    "OverviewView": frozenset(
        {
            "health",
            "kpis",
            "latest_sessions",
            "turns_per_hour",
        }
    ),
    "RetrievalRow": frozenset(
        {
            "docs",
            "embed_ms",
            "k",
            "k_source",
            "max_dense_score",
            "n_hits",
            "query",
            "search_ms",
            "span_id",
            "strategy",
            "turn_id",
        }
    ),
    "RetrievalView": frozenset(
        {
            "rows",
            "top_documents",
            "zero_evidence_queries",
        }
    ),
    "RssPoint": frozenset(
        {
            "rss_mb",
            "turn_id",
        }
    ),
    "RuleCount": frozenset(
        {
            "count",
            "rule_id",
            "rule_name",
            "verdict",
        }
    ),
    "SafetyView": frozenset(
        {
            "by_rule",
            "confirmations",
            "injection_hits",
            "mock_writes",
        }
    ),
    "SessionDetailView": frozenset(
        {
            "session",
            "turns",
        }
    ),
    "SessionRow": frozenset(
        {
            "actor_role",
            "auth_mode",
            "client_label",
            "employee_id",
            "has_error",
            "n_turns",
            "outcomes",
            "session_id",
            "started_at",
            "tokens",
            "total_ms",
        }
    ),
    "SessionSummary": frozenset(
        {
            "actor_role",
            "app_version",
            "auth_mode",
            "client_label",
            "cold_start",
            "created_at",
            "deploy_mode",
            "employee_id",
            "eval_run_id",
            "last_activity_at",
            "mcp_transport",
            "n_turns",
            "session_id",
        }
    ),
    "SessionsView": frozenset(
        {
            "page",
            "rows",
            "total",
        }
    ),
    "SpanRow": frozenset(
        {
            "duration_ms",
            "kind",
            "name",
            "offset_ms",
            "parent_span_id",
            "payload",
            "seq",
            "span_id",
            "status",
        }
    ),
    "ToolCallRow": frozenset(
        {
            "actor_employee_id",
            "arguments",
            "duration_ms",
            "error_code",
            "is_error",
            "result_preview",
            "span_id",
            "tool_name",
            "turn_id",
        }
    ),
    "ToolRollup": frozenset(
        {
            "calls",
            "error_rate",
            "last_called_at",
            "p50_ms",
            "p95_ms",
            "tool_name",
        }
    ),
    "ToolsView": frozenset(
        {
            "by_tool",
            "recent",
        }
    ),
    "TurnDetail": frozenset(
        {
            "answer_blocks",
            "citations",
            "dashboard_url",
            "duration_ms",
            "ended_at",
            "final_answer",
            "intent",
            "outcome",
            "resumed_count",
            "rollups",
            "seq",
            "session_id",
            "spans",
            "started_at",
            "stop_reason",
            "turn_id",
            "user_message",
            "workflow",
        }
    ),
    "TurnRollups": frozenset(
        {
            "guardrail_hits",
            "llm_calls",
            "llm_ms",
            "retrieval_ms",
            "retrievals",
            "store_ms",
            "tokens_in",
            "tokens_out",
            "tool_calls",
            "tool_ms",
        }
    ),
    "TurnRow": frozenset(
        {
            "duration_ms",
            "guardrail_hits",
            "intent",
            "llm_calls",
            "outcome",
            "retrievals",
            "seq",
            "session_id",
            "started_at",
            "tool_calls",
            "turn_id",
            "user_message",
            "workflow",
        }
    ),
    "TurnsView": frozenset(
        {
            "page",
            "rows",
            "total",
        }
    ),
    "VariantMetrics": frozenset(
        {
            "metrics",
            "run_id",
            "variant",
        }
    ),
    "ZeroEvidenceQuery": frozenset(
        {
            "query",
            "span_id",
            "started_at",
            "turn_id",
        }
    ),
}


def _view_models() -> dict[str, type[BaseModel]]:
    return {
        name: member
        for name, member in vars(dash).items()
        if inspect.isclass(member) and issubclass(member, BaseModel) and member.model_fields
    }


def test_no_view_model_has_lost_a_field_since_the_wave_began():
    """**P15**: additive only. A page may stop showing a number; the record may not stop holding it."""
    models = _view_models()
    missing_models = sorted(set(BASE_FIELDS) - set(models))
    assert not missing_models, f"these view-models no longer exist: {missing_models}"

    lost = {
        name: sorted(fields - set(models[name].model_fields))
        for name, fields in BASE_FIELDS.items()
        if fields - set(models[name].model_fields)
    }
    assert not lost, (
        "these fields were dropped from the JSON rather than from the page — the technical record "
        f"is relocated, never destroyed (P15): {lost}"
    )


def test_every_number_in_the_json_is_still_a_number():
    """**P15**'s other half: the formatting lives in Jinja, and never in the payload.

    `_f_num` rounds a float to two places and `_f_usd` to two decimals *for the page*. If either
    ever reached the view-model, Export JSON would hand a grader a rounded string and the unrounded
    figure would be gone from the system entirely. So a field whose **name** says it holds a
    quantity or a moment must be typed as one.
    """
    quantity = re.compile(r"_(ms|usd|rate|mean|count|accuracy|pages|tokens|n|s)$|^(calls|turns|total|page|seq|count)$")
    stringly: list[str] = []
    for name, model in _view_models().items():
        for field, info in model.model_fields.items():
            if not quantity.search(field):
                continue
            annotation = info.annotation
            if annotation is str or str in get_args(annotation):
                stringly.append(f"{name}.{field}")
    assert not stringly, (
        "these payload fields hold a formatted string where the record should hold the number "
        f"itself (P15): {sorted(stringly)}"
    )


def test_the_page_rounds_a_figure_the_payload_still_carries_in_full():
    """The principle end to end, on one real number rather than on the type system."""
    raw = 0.9839181286549706
    assert dash._f_num(raw) == "0.98", "the page rounds"
    assert dash.EvalMetrics(groundedness_mean=raw).groundedness_mean == raw, "the payload does not"
