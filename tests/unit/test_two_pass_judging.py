"""The harness is two-pass, and an unjudged run publishes no composite (spec §13.2, §13.8).

The 2026-09-10 outage is why. `gemini-3.5-flash-lite` returned HTTP 500 `INTERNAL` on almost every
call for over an hour, and a one-pass harness offers only bad choices at that moment: abandon the
26 Haiku turns and pay for them again later, or keep them and publish a **higher** composite than a
judged run would have produced — because every clause of `strict_pass` is *vacuously* true for an
item that does not define it, and an unjudged item defines no groundedness clause. So:

* the sweep drives the items and stores what judging needs — each item's `turn_id` and served
  answer here, the retrieval evidence in the trace store — and marks the run `judge_status:
  pending` with `strict_pass_rate: null`;
* `python -m evaluation.runner --judge <run_id>` computes the judged half afterwards from the
  stored run plus the traces, re-driving nothing;
* a judge pass will not start until the provider has answered eight bare probes in a row, **spaced
  two seconds apart**, because that outage was *intermittent*: an unspaced burst of eight proved
  only that the provider was up for 300 ms, and the first gated pass caught exactly such a window
  and then met HTTP 500 on its first real call. The gate is necessary, not sufficient — which is
  what makes the pass's idempotence load-bearing rather than a nicety.

An ablation arm is never pending: §13.9 judges `baseline` only, so an arm is complete as it stands.
"""

from __future__ import annotations

import pytest

import evaluation.runner as runner
from evaluation.schema import RunConfig, RunFile, RunMetrics

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


def _run(*, variant: str, judge_status: str, judged: bool, strict: float | None) -> RunFile:
    return RunFile(
        run_id="r_test_baseline",
        created_at=0,
        git_sha="dev",
        label="",
        variant=variant,
        target="local",
        target_base_url="http://127.0.0.1:8000",
        dataset_sha="0" * 64,
        config=CONFIG,
        n_items=26,
        judge_status=judge_status,  # type: ignore[arg-type]
        metrics=RunMetrics(judged=judged, strict_pass_rate=strict, n_scored={"items": 26}),
    )


# --------------------------------------------------------------------------------------------
# What a pending run publishes
# --------------------------------------------------------------------------------------------


def test_a_pending_run_publishes_a_sentence_where_the_composite_would_be():
    run = _run(variant="baseline", judge_status="pending", judged=False, strict=None)
    table = runner._metric_table(run)
    row = next(line for line in table.splitlines() if "Strict pass rate" in line)

    assert runner.PENDING_COMPOSITE in row
    assert "0." not in row.split("|")[2], "no number may appear in the composite's value cell"
    assert row.rstrip().endswith("| ≥ 0.85 |"), "the target still says what the figure will be graded against"


def test_a_pending_run_says_how_to_judge_it():
    note = runner._strict_pass_note(_run(variant="baseline", judge_status="pending", judged=False, strict=None))

    assert runner.PENDING_COMPOSITE in note
    assert "--judge r_test_baseline" in note, "the report carries the exact recipe"
    assert "vacuously true" in note, "and says why the number is withheld rather than estimated"


def test_the_report_carries_the_pending_banner_and_the_status():
    body = runner.render_report(_run(variant="baseline", judge_status="pending", judged=False, strict=None))

    assert "judge_status: pending" in body
    assert "This run has not been judged" in body
    assert "judge_agreement_rate` cannot be computed" in body


def test_an_ablation_arm_is_never_pending_and_still_publishes_its_composite():
    """§13.9 judges `baseline` only, so an arm is complete as it stands — with its caveat."""
    run = _run(variant="dense_only_k2", judge_status="not_applicable", judged=False, strict=0.692)
    note = runner._strict_pass_note(run)

    assert runner.PENDING_COMPOSITE not in note
    assert "0.692" in note
    assert "not comparable" in note


# --------------------------------------------------------------------------------------------
# `assemble()` decides the status
# --------------------------------------------------------------------------------------------


def test_assemble_marks_an_undriven_judge_pass_pending(monkeypatch):
    built = runner.Runner(
        runner.RunOptions(variant="baseline", base_url="http://127.0.0.1:8000", judge=False),
        judge=None,
    )
    run = built.assemble([], duration_s=1.0)

    assert run.judge_status == "pending"
    assert run.metrics.strict_pass_rate is None
    assert run.metrics.judged is False


def test_assemble_marks_an_arm_not_applicable():
    built = runner.Runner(
        runner.RunOptions(variant="dense_only_k2", base_url="http://127.0.0.1:8000", judge=False),
        judge=None,
    )
    run = built.assemble([], duration_s=1.0)

    assert run.judge_status == "not_applicable"
    assert run.metrics.judged is False


def test_a_judge_pass_that_lost_verdicts_stays_pending():
    """One failed verdict is one unscored groundedness clause — the composite must not be computed."""

    class _HalfFailedJudge:
        model_name = "gemini-3.5-flash-lite"
        calls = 104
        failures = 3

    built = runner.Runner(
        runner.RunOptions(variant="baseline", base_url="http://127.0.0.1:8000", judge=True),
        judge=_HalfFailedJudge(),  # type: ignore[arg-type]
    )
    assert built._judge_enabled is True

    run = built.assemble([], duration_s=1.0)

    assert run.judge_status == "pending"
    assert run.metrics.strict_pass_rate is None
    assert run.metrics.judged is False, "`judged` must not claim a half-finished pass"
    assert run.judge_calls == 104


def test_a_complete_judge_pass_is_judged():
    class _Judge:
        model_name = "gemini-3.5-flash-lite"
        calls = 252
        failures = 0

    built = runner.Runner(
        runner.RunOptions(variant="baseline", base_url="http://127.0.0.1:8000", judge=True),
        judge=_Judge(),  # type: ignore[arg-type]
    )
    run = built.assemble([], duration_s=1.0)

    assert run.judge_status == "judged"
    assert run.metrics.judged is True


# --------------------------------------------------------------------------------------------
# The probe gate and the judge pass's refusals
# --------------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_probe_gate_demands_eight_consecutive_successes(monkeypatch):
    calls: list[int] = []

    async def invoke(self, request, deadline=None):
        calls.append(1)
        return object()

    monkeypatch.setattr("hrmosaic.core.llm.openai_compat.OpenAICompatAdapter.invoke", invoke)
    monkeypatch.setattr(runner, "JUDGE_PROBE_INTERVAL_S", 0.0)  # the spacing is real time, not logic

    await runner.judge_provider_ready()

    assert len(calls) == runner.JUDGE_PROBE_ATTEMPTS == 8


@pytest.mark.anyio
async def test_the_probe_gate_stops_at_the_first_failure(monkeypatch):
    """The intermittent case: three good probes then a 500 is not a provider that is up."""
    calls: list[int] = []

    async def invoke(self, request, deadline=None):
        calls.append(1)
        if len(calls) == 4:
            raise RuntimeError("anthropic-style 500 INTERNAL")
        return object()

    monkeypatch.setattr("hrmosaic.core.llm.openai_compat.OpenAICompatAdapter.invoke", invoke)
    monkeypatch.setattr(runner, "JUDGE_PROBE_INTERVAL_S", 0.0)

    with pytest.raises(SystemExit) as raised:
        await runner.judge_provider_ready()

    assert len(calls) == 4, "it stops at the first failure rather than probing on"
    assert "probe 4/8" in str(raised.value)
    assert "judge_status: pending" in str(raised.value), "the operator is told the run is untouched"


@pytest.mark.anyio
async def test_the_judge_pass_refuses_an_ablation_arm(tmp_path):
    run = _run(variant="dense_only_k2", judge_status="not_applicable", judged=False, strict=0.5)
    (tmp_path / f"{run.run_id}.json").write_text(run.model_dump_json(), encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        await runner.judge_run(run.run_id, results_dir=tmp_path)

    assert "judges `baseline` only" in str(raised.value)


@pytest.mark.anyio
async def test_the_judge_pass_refuses_a_run_driven_against_a_different_dataset(tmp_path):
    """Judging answers against questions that have since changed would be silently wrong."""
    run = _run(variant="baseline", judge_status="pending", judged=False, strict=None)
    (tmp_path / f"{run.run_id}.json").write_text(run.model_dump_json(), encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        await runner.judge_run(run.run_id, results_dir=tmp_path)

    assert "different questions" in str(raised.value)


# --------------------------------------------------------------------------------------------
# What the pass writes, and what an aborted pass does not
# --------------------------------------------------------------------------------------------


def test_the_judge_passs_own_notes_survive_the_rewrite():
    """§13.7's disagreement list is produced by the judge pass, so only the pass can record it.

    `judge_run` rebuilds the run file from the pass and then restores the drive pass's provenance
    onto it. Notes are the one field where restoring means *union*: the drive pass's notes are
    still true and the pass has just written its own, and replacing one with the other used to drop
    `judge/reference disagreements:` on the floor — leaving `--recompute-agreement` as the only way
    it ever reached the file.
    """
    disagreement = "judge/reference disagreements: pto-002 (reference grounded, judge ungrounded)"

    merged = runner._merge_notes("the drive pass's own note.", [disagreement])

    assert merged == f"the drive pass's own note. {disagreement}"


def test_the_judge_pass_note_is_byte_identical_across_three_applications():
    """The pass is idempotent (§13.2), so its note has to be too — including the merged notes."""
    judged = _run(variant="baseline", judge_status="judged", judged=True, strict=0.73)
    judged.judge_model = "gemini-3.5-flash-lite"
    judged.judge_calls = 252
    produced = ["judge/reference disagreements: pto-002 (reference grounded, judge ungrounded)"]

    once = runner._judge_pass_note(runner._merge_notes("the drive pass's own note.", produced), judged)
    twice = runner._judge_pass_note(runner._merge_notes(once, produced), judged)
    thrice = runner._judge_pass_note(runner._merge_notes(twice, produced), judged)

    assert once == twice == thrice
    assert once.startswith("the drive pass's own note.")
    assert once.count(produced[0]) == 1, "the pass's own note is not stacked on a second application"
    assert once.count("Judged in a second pass") == 1, "nor is the pass sentence"


@pytest.mark.anyio
async def test_a_pass_that_blows_the_failure_budget_writes_nothing(tmp_path, writer, monkeypatch):
    """`JUDGE_FAILURE_BUDGET + 1` lost verdicts abort the pass, and the run file is untouched.

    A judged 26-item baseline costs ~252 provider calls against a 500/day cap, so a pass that
    grinds on while the provider flaps spends the day's only other attempt. Aborting is only safe
    if it leaves the clean `pending` state the drive pass gave the file — not a half-judged one.
    """
    dataset = runner.load_dataset()
    first = dataset.items[0]
    run = _run(variant="baseline", judge_status="pending", judged=False, strict=None)
    run.dataset_sha = dataset.sha256
    run.notes = "the drive pass's own note."
    run.items = [
        runner.ItemResult(
            id="er_1", item_id=first.id, category=first.category, session_id="s_1", turn_id="t_1", answer="…"
        )
    ]
    path = tmp_path / f"{run.run_id}.json"
    before = run.model_dump_json(indent=1)
    path.write_text(before, encoding="utf-8")

    class _FlappingJudge:
        model_name = "gemini-3.5-flash-lite"
        calls = 9
        failures = runner.JUDGE_FAILURE_BUDGET + 1
        run_id = ""

    async def ready(*args, **kwargs):
        return None

    async def score(self, item, response, turn, *, run_phase):
        return object()

    wrote: list[str] = []
    monkeypatch.setattr(runner, "judge_provider_ready", ready)
    monkeypatch.setattr(runner, "Judge", lambda **kwargs: _FlappingJudge())
    monkeypatch.setattr(runner.det, "read_turn", lambda store, turn_id: object())
    monkeypatch.setattr(runner.Runner, "_score", score)
    monkeypatch.setattr(runner, "write_report", lambda *args, **kwargs: wrote.append("REPORT.md"))
    monkeypatch.setattr(runner.Runner, "write_artifacts", lambda self, run: wrote.append("run file"))

    with pytest.raises(SystemExit) as raised:
        await runner.judge_run(run.run_id, results_dir=tmp_path)

    assert "NOTHING was written" in str(raised.value)
    assert "judge_status: pending" in str(raised.value)
    assert wrote == [], "an aborted pass writes no artifact at all"
    assert path.read_text(encoding="utf-8") == before, "the run file is byte-identical"
