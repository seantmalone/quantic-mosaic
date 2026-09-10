"""The publish gate of the performance plan's W1-A, and the provenance it forces alongside it.

Two things a run file cannot say for itself:

* **`config.llm_rpm` is the harness's number, not the target's.** `Runner` reads it from its own
  `settings`, so a sweep driven against the deployed service publishes the rate the *laptop* was
  paced at while the latency it measured was produced under the service's own `LLM_RPM`. Since
  2026-09-10 those are different numbers (10 in code, 60/30 on the service), so a `deployed` run
  has to say in its notes that the recorded rate is not the one that produced the latency.
* **A failover is invisible.** `core/llm/base.py` treats 429 as retryable and escalates to
  `gemini-3.5-flash-lite`, so a rate-limited sweep can answer some of its items on the fallback
  model while `config.llm_model` still reads `claude-haiku-4-5`. A retry is the same problem one
  step earlier: it inflates the latency the run publishes. Both live only in the `llm_call` spans,
  which is why the gate reads them — and why `--report`, the publish path, refuses a run that
  carries either.
"""

from __future__ import annotations

import json

import pytest

import evaluation.runner as runner
from evaluation.schema import ItemResult, RunConfig, RunFile, RunMetrics
from hrmosaic.core.models import LlmCallPayload
from hrmosaic.core.trace import SessionSpec

CONFIG = RunConfig(
    retrieval_k=5,
    retrieval_strategy="hybrid_rrf",
    llm_model="claude-haiku-4-5",
    judge_model="gemini-3.5-flash-lite",
    min_evidence_score=0.6,
    min_support_score=0.45,
    llm_rpm=10,
    seed=1729,
)


def _payload(**overrides) -> LlmCallPayload:
    fields = {"provider": "anthropic", "model": "claude-haiku-4-5", "purpose": "act"}
    fields.update(overrides)
    return LlmCallPayload(**fields)


def _run_with(writer, *payloads) -> RunFile:
    """One scored item whose turn carries `payloads` as its `llm_call` spans."""
    turn = writer.start_turn(SessionSpec(eval_run_id="r_test_baseline"), user_message="q")
    for payload in payloads:
        turn.add_span("llm_call", f"{payload.provider}:{payload.model}", payload)
    turn.close(outcome="answered", stop_reason="answered")
    return RunFile(
        run_id="r_test_baseline",
        created_at=0,
        git_sha="dev",
        label="",
        variant="baseline",
        target="deployed",
        target_base_url="https://mosaic.onrender.com",
        dataset_sha="0" * 64,
        config=CONFIG,
        n_items=1,
        metrics=RunMetrics(),
        items=[
            ItemResult(
                id="r_test_baseline::pto-001",
                item_id="pto-001",
                category="policy_qa",
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                answer="…",
            )
        ],
    )


# --------------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------------


def test_a_clean_run_has_no_findings(writer, store):
    run = _run_with(writer, _payload(), _payload())
    assert runner.contamination_findings(run, store=store) == []


def test_a_failover_invalidates_the_run(writer, store):
    run = _run_with(writer, _payload(), _payload(provider_failover=True, model="gemini-3.5-flash-lite"))
    findings = runner.contamination_findings(run, store=store)
    assert any("failed over" in finding for finding in findings), findings


def test_a_retry_invalidates_the_run(writer, store):
    run = _run_with(writer, _payload(retry_count=1))
    findings = runner.contamination_findings(run, store=store)
    assert any("retry_count" in finding for finding in findings), findings


def test_a_model_other_than_the_pinned_one_invalidates_the_run(writer, store):
    run = _run_with(writer, _payload(model="claude-sonnet-4-5"))
    findings = runner.contamination_findings(run, store=store)
    assert any("claude-sonnet-4-5" in finding for finding in findings), findings


def test_a_run_whose_spans_are_not_in_this_store_is_not_checkable_and_says_nothing(store):
    """A committed run file from another machine: absent spans are silence, never a false green."""
    run = RunFile(
        run_id="r_elsewhere",
        created_at=0,
        git_sha="dev",
        label="",
        variant="baseline",
        target="deployed",
        target_base_url="https://mosaic.onrender.com",
        dataset_sha="0" * 64,
        config=CONFIG,
        n_items=0,
        metrics=RunMetrics(),
    )
    assert runner.contamination_findings(run, store=store) == []


# --------------------------------------------------------------------------------------------
# Wired into `--report`
# --------------------------------------------------------------------------------------------


def test_report_refuses_to_publish_a_contaminated_run(writer, store, tmp_path):
    run = _run_with(writer, _payload(provider_failover=True, model="gemini-3.5-flash-lite"))
    (tmp_path / f"{run.run_id}.json").write_text(json.dumps(run.model_dump(mode="json")), encoding="utf-8")
    report_path = tmp_path / "REPORT.md"

    with pytest.raises(SystemExit) as raised:
        runner.rewrite_report(run.run_id, results_dir=tmp_path, path=report_path)

    assert "failed over" in str(raised.value)
    assert not report_path.exists(), "a contaminated run must not leave a published report behind"


def test_report_publishes_a_clean_run(writer, store, tmp_path):
    run = _run_with(writer, _payload())
    (tmp_path / f"{run.run_id}.json").write_text(json.dumps(run.model_dump(mode="json")), encoding="utf-8")
    report_path = tmp_path / "REPORT.md"

    runner.rewrite_report(run.run_id, results_dir=tmp_path, path=report_path)
    assert run.run_id in report_path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------
# The provenance note
# --------------------------------------------------------------------------------------------


def test_a_deployed_run_records_that_its_llm_rpm_is_the_harnesss(store):
    notes = runner.Runner(runner.RunOptions(base_url="https://mosaic.onrender.com"), store=store).notes
    assert any(runner.REMOTE_RATE_NOTE == note for note in notes), notes
    assert "unknown; service env" in runner.REMOTE_RATE_NOTE


def test_a_local_run_records_no_such_caveat_because_the_harness_is_the_target(store):
    notes = runner.Runner(runner.RunOptions(base_url="http://127.0.0.1:8000"), store=store).notes
    assert runner.REMOTE_RATE_NOTE not in notes, notes
