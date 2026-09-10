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

from pathlib import Path

import pytest

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


async def test_the_metrics_tab_reads_latency_from_the_run_and_the_decomposition_from_the_turns(seeded):
    payload = await _get(seeded, "/api/eval/runs/r_p9fixture_baseline")
    latency = payload["latency"]
    assert latency["n_warm"] == 6
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
    # `question` / `gold` come from `evaluation/dataset.yaml`, a P10 deliverable: empty, not invented
    assert item["question"] is None and item["gold"] is None


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
