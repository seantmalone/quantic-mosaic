"""`REPORT.md` must print §13.8's target beside the figure it grades.

The composite is the one metric in §13 that has a published target — `strict_pass_rate ≥ 0.85` on
the 26-item set — and a report that prints `0.538` with no reference number reads as a result
rather than as a shortfall. So the target is rendered in the table *and* stated as a gap in prose,
and an unjudged variant says why its figure is not comparable (§13.9).
"""

from __future__ import annotations

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


def _run(*, strict: float | None, judged: bool) -> RunFile:
    return RunFile(
        run_id="r_test",
        created_at=0,
        git_sha="dev",
        label="",
        variant="baseline" if judged else "dense_only_k2",
        target="local",
        target_base_url="http://127.0.0.1:8000",
        dataset_sha="0" * 64,
        config=CONFIG,
        n_items=26,
        metrics=RunMetrics(judged=judged, strict_pass_rate=strict, n_scored={"items": 26}),
    )


def test_the_target_is_published_in_the_table():
    assert runner.STRICT_PASS_TARGET == 0.85
    table = runner._metric_table(_run(strict=0.538, judged=True))
    row = next(line for line in table.splitlines() if "Strict pass rate" in line)
    assert row.endswith("| ≥ 0.85 |")
    # Every other row carries an em dash rather than a number invented for it.
    others = [line for line in table.splitlines()[2:] if "Strict pass rate" not in line]
    assert others and all(line.endswith("| – |") for line in others)


def test_a_shortfall_is_named_as_a_shortfall():
    note = runner._strict_pass_note(_run(strict=0.538, judged=True))
    assert "0.312 below" in note
    assert "≥ 0.85" in note
    assert "not comparable" not in note


def test_meeting_the_target_says_so():
    note = runner._strict_pass_note(_run(strict=0.900, judged=True))
    assert "meets" in note
    assert "+0.050" in note


def test_an_unjudged_variant_says_why_its_figure_is_not_comparable():
    # §13.8's groundedness clause is vacuously true on an arm that was never judged (§13.9), which
    # is exactly why the two arms can score *higher* than the judged baseline.
    note = runner._strict_pass_note(_run(strict=0.692, judged=False))
    assert "not comparable" in note


def test_no_note_at_all_when_there_is_no_composite():
    assert runner._strict_pass_note(_run(strict=None, judged=True)) == ""


# --------------------------------------------------------------------------------------
# The judge's cost line (P14 item 1)
# --------------------------------------------------------------------------------------
#
# `MODEL_PRICES["gemini-3.5-flash-lite"]` was $0 while the judge project sat on the Gemini free
# tier. Paid billing was enabled on 2026-09-10 and the entry now carries the paid standard rates —
# but cost is priced at *write* time in `core/llm/base.py`, so every judge span already in the
# store keeps the $0 it was written with. The report has to say so, or a reader adds up
# `est_cost_usd` and concludes the judge was free.


def test_the_judge_section_says_the_recorded_judge_cost_is_zero_and_prices_the_pass():
    report = runner.render_report(_run(strict=0.692, judged=True))
    section = report.split("## Judge methodology", 1)[1].split("### What the tool", 1)[0]
    assert "$0" in section, "a reader must be told the recorded judge spans carry no cost"
    assert "$0.16" in section, "and what the pass actually cost, from its token counts"
    assert "$0.30" in section and "$2.50" in section, "with the rates the figure comes from"
