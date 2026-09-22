"""The second, disclosed judge-validation subset and the metric it feeds (spec §13.7).

The blind `SEED`-sampled subset came back 8/8 `grounded` on both sides. Every cell of its agreement
matrix but the top-left is empty, so `judge_agreement_rate = 1.000` over it measures agreement on
the half of the decision a judge is least likely to get wrong and cannot separate a good judge from
one that answers `grounded` to everything. `judge_lowest_subset()` is the answer to that: the items
with the **lowest judge groundedness in the run**, so whatever disagreement the run contains has a
chance of being inside the sample.

That selection is a sort, and a sort over a population with ties — sixteen items, fourteen of them
scored exactly 1.000 — is only reproducible if the tie-break is specified. It is: `(groundedness,
item_id)`. These tests pin that, pin the population it sorts, and pin the wiring that keeps the two
figures apart: two metric names, two `n`s, two subset labels, two label files, and a refusal to
publish one subset's labels under the other's name.

The last section pins the other refusal, the turn binding: a label carries the `turn_id` of the
served answer it was authored against, so labels written about one run's answers can never be scored
against another run's.
"""

from __future__ import annotations

import json

import pytest

import evaluation.runner as runner
from evaluation import deterministic as det
from evaluation.schema import (
    AGREEMENT_METRICS,
    REFERENCE_SUBSET_SIZE,
    AgreementMetric,
    ItemResult,
    RunConfig,
    RunFile,
    RunMetrics,
    judge_lowest_subset,
    load_dataset,
    load_reference_labels,
    reference_subset,
)

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

#: The gold-`answer` items, in `dataset.yaml` file order — the population both subsets draw from.
ANSWER_ITEMS = [
    "pto-001",
    "remote-001",
    "benefits-001",
    "inj-001",
    "expenses-001",
    "leave-001",
    "travel-001",
    "remote-002",
    "expenses-002",
    "onboarding-001",
    "equipment-001",
    "conduct-001",
    "profile-001",
    "pto-002",
    "pto-003",
    "remote-003",
    "remote-004",
    "benefits-002",
]


def _row(
    item_id: str,
    groundedness: float | None,
    *,
    run_phase: str = "scored",
    category: str = "simple_policy",
    turn_id: str | None = None,
):
    return ItemResult(
        id=f"r_test::{item_id}",
        item_id=item_id,
        category=category,
        run_phase=run_phase,  # type: ignore[arg-type]
        turn_id=turn_id,
        scores={"groundedness": groundedness},
    )


def _run(rows: list[ItemResult], **metrics) -> RunFile:
    return RunFile(
        run_id="r_test_baseline",
        created_at=0,
        git_sha="dev",
        label="",
        variant="baseline",
        target="local",
        target_base_url="http://127.0.0.1:8000",
        dataset_sha="0" * 64,
        config=CONFIG,
        n_items=len(rows),
        judge_status="judged",
        metrics=RunMetrics(judged=True, n_scored={"items": len(rows)}, **metrics),
        items=rows,
    )


# --------------------------------------------------------------------------------------------
# The selection
# --------------------------------------------------------------------------------------------


def test_the_subset_is_the_lowest_scoring_items_hardest_first():
    dataset = load_dataset()
    scores = {"pto-001": 0.4, "remote-001": 0.9, "benefits-001": 0.1, "inj-001": 0.7, "expenses-001": 1.0}
    run = _run([_row(item_id, score) for item_id, score in scores.items()])

    assert judge_lowest_subset(run, size=3, dataset=dataset) == ["benefits-001", "pto-001", "inj-001"]


def test_ties_break_by_item_id_and_not_by_the_order_the_rows_happen_to_be_in():
    """Fourteen of the sixteen judged items scored exactly 1.000, so the tie-break *is* the subset.

    The rows are handed in reverse-id order on purpose: a sort keyed on the score alone is stable,
    so it would return them in that reverse order and the "same" subset would differ between two
    runs whose rows merely arrived differently.
    """
    dataset = load_dataset()
    tied = ["travel-001", "profile-001", "onboarding-001", "leave-001", "conduct-001"]
    run = _run([_row(item_id, 1.0) for item_id in tied])

    assert judge_lowest_subset(run, size=3, dataset=dataset) == ["conduct-001", "leave-001", "onboarding-001"]


def test_a_lower_score_always_outranks_the_tie_break():
    dataset = load_dataset()
    run = _run([_row("travel-001", 0.5), _row("conduct-001", 1.0), _row("benefits-001", 1.0)])

    chosen = judge_lowest_subset(run, size=2, dataset=dataset)

    assert chosen == ["travel-001", "benefits-001"], "the 0.5 leads, then the alphabetically first tie"


def test_an_item_the_judge_could_not_score_is_not_in_the_subset():
    """A `null` verdict leaves every judged denominator (§13.7); it cannot be a *hard* case."""
    dataset = load_dataset()
    run = _run([_row("remote-003", None), _row("equipment-001", None), _row("pto-001", 1.0)])

    assert judge_lowest_subset(run, size=8, dataset=dataset) == ["pto-001"]


def test_the_population_is_the_gold_answer_items_exactly_as_the_blind_subset_draws_from():
    """The only difference between the two subsets must be *how* the 8 are chosen, not from what."""
    dataset = load_dataset()
    rows = [_row(item.id, 0.5, category=item.category) for item in dataset.items]

    chosen = judge_lowest_subset(_run(rows), size=26, dataset=dataset)

    assert sorted(chosen) == sorted(ANSWER_ITEMS)
    assert set(reference_subset(dataset)) <= set(chosen), "the blind subset is drawn from the same population"


def test_a_cold_probe_row_is_not_a_scored_item():
    dataset = load_dataset()
    run = _run([_row("pto-001", 0.2, run_phase="cold_probe"), _row("remote-001", 0.9)])

    assert judge_lowest_subset(run, size=8, dataset=dataset) == ["remote-001"]


def test_the_subset_is_bounded_by_size_and_defaults_to_eight():
    dataset = load_dataset()
    rows = [_row(item_id, 1.0) for item_id in ANSWER_ITEMS]

    assert len(judge_lowest_subset(_run(rows), dataset=dataset)) == REFERENCE_SUBSET_SIZE
    assert len(judge_lowest_subset(_run(rows), size=3, dataset=dataset)) == 3
    assert len(judge_lowest_subset(_run(rows[:2]), size=8, dataset=dataset)) == 2, "never pads"


def test_the_selection_is_stable_across_repeated_calls():
    dataset = load_dataset()
    rows = [_row(item_id, 1.0 if index % 2 else 0.9) for index, item_id in enumerate(ANSWER_ITEMS)]

    first = judge_lowest_subset(_run(rows), dataset=dataset)

    assert all(judge_lowest_subset(_run(rows), dataset=dataset) == first for _ in range(5))


def test_the_committed_baseline_selects_the_eight_items_the_hard_packet_was_built_from():
    """The published figure's population, pinned: a silent change here republishes a different n."""
    path = runner.RESULTS_DIR / "r_1789032950_baseline.json"
    run = RunFile.model_validate(json.loads(path.read_text(encoding="utf-8")))

    assert judge_lowest_subset(run) == [
        "inj-001",
        "pto-003",
        "benefits-001",
        "benefits-002",
        "conduct-001",
        "expenses-001",
        "expenses-002",
        "leave-001",
    ]


# --------------------------------------------------------------------------------------------
# The second metric
# --------------------------------------------------------------------------------------------


LABELS_HARD = """
protocol:
  labeller: blind-opus-labeller — a separate Claude Opus 5 session
  labelled_on: "2026-09-10"
  blinding: the packet carried no judge output
  selection: judge_lowest_subset()
  seed: null
  method: binary, answer-level
  subset: judge_lowest_8
  selection_disclosed: true
labels:
  - item_id: inj-001
    verdict: grounded
    rationale: every claim traces to a passage in the packet
  - item_id: pto-003
    verdict: grounded
    rationale: every claim is in the evidence
  - item_id: conduct-001
    verdict: grounded
    rationale: every claim is in the evidence
"""

LABELS_SEED = LABELS_HARD.replace("subset: judge_lowest_8", "subset: seed_1729_8").replace(
    "selection_disclosed: true", "selection_disclosed: false"
)


@pytest.fixture
def judged_run(tmp_path):
    """A judged run on disk whose scores put `inj-001` below §13.8's threshold and the rest above."""
    run = _run(
        [_row("inj-001", 0.83), _row("pto-003", 0.93), _row("conduct-001", 1.0)],
        judge_agreement_rate=1.0,
        judge_agreement_n=7,
        judge_agreement_subset="seed_1729_8",
    )
    (tmp_path / f"{run.run_id}.json").write_text(json.dumps(run.model_dump(mode="json")), encoding="utf-8")
    return run


@pytest.fixture
def no_report(monkeypatch):
    """`recompute_agreement` rewrites REPORT.md; a unit test must not touch the committed one."""
    written: list[RunFile] = []
    monkeypatch.setattr(runner, "write_report", lambda run, **_: written.append(run))
    return written


def test_the_hard_metric_writes_its_own_three_fields_and_leaves_the_blind_ones_alone(tmp_path, judged_run, no_report):
    labels = tmp_path / "reference_labels_hard.yaml"
    labels.write_text(LABELS_HARD, encoding="utf-8")

    run = runner.recompute_agreement(
        judged_run.run_id,
        results_dir=tmp_path,
        metric="judge_agreement_rate_hard",
        labels_path=labels,
    )

    assert run.metrics.judge_agreement_rate_hard == pytest.approx(2 / 3), "inj-001 is the one disagreement"
    assert run.metrics.judge_agreement_n_hard == 3
    assert run.metrics.judge_agreement_subset_hard == "judge_lowest_8"
    assert (run.metrics.judge_agreement_rate, run.metrics.judge_agreement_n) == (1.0, 7)
    assert run.metrics.judge_agreement_subset == "seed_1729_8", "the blind figure is untouched"


def test_both_figures_survive_in_the_run_file_on_disk(tmp_path, judged_run, no_report):
    labels = tmp_path / "reference_labels_hard.yaml"
    labels.write_text(LABELS_HARD, encoding="utf-8")

    runner.recompute_agreement(
        judged_run.run_id, results_dir=tmp_path, metric="judge_agreement_rate_hard", labels_path=labels
    )
    body = json.loads((tmp_path / f"{judged_run.run_id}.json").read_text(encoding="utf-8"))["metrics"]

    assert body["judge_agreement_rate"] == 1.0 and body["judge_agreement_n"] == 7
    assert body["judge_agreement_rate_hard"] == pytest.approx(2 / 3) and body["judge_agreement_n_hard"] == 3
    assert body["judge_agreement_subset"] == "seed_1729_8"
    assert body["judge_agreement_subset_hard"] == "judge_lowest_8"


def test_folding_the_wrong_labels_into_a_metric_is_refused_rather_than_mislabelled(tmp_path, judged_run, no_report):
    """A figure whose population is not the one it is published under is worse than no figure."""
    labels = tmp_path / "reference_labels.yaml"
    labels.write_text(LABELS_SEED, encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        runner.recompute_agreement(
            judged_run.run_id, results_dir=tmp_path, metric="judge_agreement_rate_hard", labels_path=labels
        )

    assert "seed_1729_8" in str(raised.value) and "judge_lowest_8" in str(raised.value)
    assert "wrong population" in str(raised.value)


def test_an_unknown_metric_names_the_ones_that_exist(tmp_path, judged_run, no_report):
    with pytest.raises(SystemExit) as raised:
        runner.recompute_agreement(judged_run.run_id, results_dir=tmp_path, metric="kappa")

    assert "judge_agreement_rate_hard" in str(raised.value)


# --------------------------------------------------------------------------------------------
# The turn binding (gap 9)
# --------------------------------------------------------------------------------------------
#
# A reference label is a verdict on one served answer. Until `ReferenceLabel.turn_id` existed, the
# only thing tying a verdict to the text it was written about was the prose in `protocol.blinding` —
# so folding labels authored against run A into run B produced a figure that looked exactly like a
# real one. These three pin the refusal, the accepted match, and the older files that carry no
# binding at all.

LABELS_HARD_BOUND = LABELS_HARD.replace(
    "  - item_id: inj-001\n", "  - item_id: inj-001\n    turn_id: turn-inj-001\n"
).replace("  - item_id: pto-003\n", "  - item_id: pto-003\n    turn_id: turn-pto-003\n")

#: The same bound labels under the blind subset's declaration — the file the *seed* metric may read.
LABELS_SEED_BOUND = LABELS_HARD_BOUND.replace("subset: judge_lowest_8", "subset: seed_1729_8").replace(
    "selection_disclosed: true", "selection_disclosed: false"
)


@pytest.fixture
def judged_run_with_turns(tmp_path):
    """The same run, with each item recording the turn whose answer it served."""
    run = _run(
        [
            _row("inj-001", 0.83, turn_id="turn-inj-001"),
            _row("pto-003", 0.93, turn_id="turn-pto-003"),
            _row("conduct-001", 1.0, turn_id="turn-conduct-001"),
        ],
        judge_agreement_rate=1.0,
        judge_agreement_n=7,
        judge_agreement_subset="seed_1729_8",
    )
    (tmp_path / f"{run.run_id}.json").write_text(json.dumps(run.model_dump(mode="json")), encoding="utf-8")
    return run


def _driven_row(item_id: str, turn_id: str) -> runner.ScoredItem:
    """One finished, judged drive row — the shape `Runner.assemble()` folds labels into."""
    item = load_dataset().by_id(item_id)
    assert item is not None
    usage = det.ToolUsage(called=list(item.expected_tools), gated=[], failed=[], ok_spans=[])
    return runner.ScoredItem(
        result=ItemResult(
            id=f"r_drive::{item_id}",
            item_id=item_id,
            category=item.category,
            session_id="s" * 32,
            turn_id=turn_id,
            run_phase="scored",
            answer="an answer",
            latency_ms=3000,
            cold=0,
            scores={"cit_resolve": 1.0, "outcome": "answered", "tools_called": list(item.expected_tools)},
            verdicts=None,
            passed=1,
        ),
        item=item,
        turn=None,
        gold_behavior=item.expected_behavior,
        predicted_behavior="answer",
        tool=det.tool_scores(item, usage),
        doc_recall=1.0,
        workflow=1.0,
        groundedness=1.0,
        citation_accuracy=1.0,
        partial_match=1.0,
        clarification=None,
        cost_usd=0.0,
    )


def test_labels_authored_against_another_runs_answers_are_refused(
    tmp_path, judged_run_with_turns, no_report, store, monkeypatch
):
    """The wrong-run figure gap 9 names: a verdict on text this run never served.

    Both directions the labels can meet a run are asserted here, because the right answer differs.
    `--recompute-agreement` has spent nothing and is folding one file into one run, so it **refuses**.
    A drive — or a `--judge` over an older run — has already been paid for, so `assemble()` leaves
    the figure uncomputed and names the items instead; a `SystemExit` there would throw the run away.
    """
    labels = tmp_path / "reference_labels_hard.yaml"
    labels.write_text(
        LABELS_HARD_BOUND.replace("turn_id: turn-inj-001", "turn_id: turn-from-an-older-run"), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as raised:
        runner.recompute_agreement(
            judged_run_with_turns.run_id,
            results_dir=tmp_path,
            metric="judge_agreement_rate_hard",
            labels_path=labels,
        )

    message = str(raised.value)
    assert "inj-001" in message and "turn-from-an-older-run" in message and "turn-inj-001" in message
    assert "pto-003" not in message, "only the mismatched label is named"
    assert no_report == [], "a refused fold-in does not rewrite REPORT.md"
    on_disk = json.loads((tmp_path / f"{judged_run_with_turns.run_id}.json").read_text(encoding="utf-8"))
    assert on_disk["metrics"]["judge_agreement_rate_hard"] is None, "and writes no figure to the run file"

    # The drive-time fold-in, with the same stale labels: uncomputed, not wrong, and not fatal.
    monkeypatch.setattr(runner, "load_reference_labels", lambda *_, **__: load_reference_labels(labels))
    drive = runner.Runner(
        runner.RunOptions(variant="baseline", base_url="http://127.0.0.1:8000", judge=False),
        store=store,
        dataset=load_dataset(),
        judge=None,
    )
    drive._judge_enabled = True

    built = drive.assemble([_driven_row("inj-001", "t" * 32)], duration_s=1.0)

    assert built.metrics.judge_agreement_rate is None, "a figure over another run's answers is no figure"
    assert built.metrics.judge_agreement_n == 0
    assert built.notes is not None
    assert "inj-001 (label turn-from-an-older-run, run tttttttttttttttttttttttttttttttt)" in built.notes
    assert "--recompute-agreement" in built.notes, "the note says how to put the figure back"


def test_labels_whose_turn_matches_the_run_are_folded_in(tmp_path, judged_run_with_turns, no_report):
    """And the fold-in **retracts** the drive-time note that said the figure was not computed.

    The drive that produced `r_1790110325_baseline` found the committed labels bound to other turns,
    so it left the blind figure uncomputed and said so in `notes`. Re-authoring the packet and
    folding the labels in then wrote 1.000 and *kept the sentence*, because the retraction matched
    only lines starting `judge_agreement_rate=` — and REPORT.md, which prints `run.notes` verbatim,
    published the figure and "is not computed on this run" a hundred lines apart (G5b task 5d). The
    retraction is per metric: recomputing the hard subset must leave the blind subset's note alone,
    because that figure really is still uncomputed.
    """
    labels = tmp_path / "reference_labels_hard.yaml"
    labels.write_text(LABELS_HARD_BOUND, encoding="utf-8")
    path = tmp_path / f"{judged_run_with_turns.run_id}.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["notes"] = (
        "A finding from the drive pass. "
        + runner._degraded_agreement_note("judge_agreement_rate", ["inj-001 (label turn-older, run turn-inj-001)"])
        + " Judged in a second pass on 2026-09-10."
    )
    path.write_text(json.dumps(body), encoding="utf-8")

    run = runner.recompute_agreement(
        judged_run_with_turns.run_id,
        results_dir=tmp_path,
        metric="judge_agreement_rate_hard",
        labels_path=labels,
    )

    assert run.metrics.judge_agreement_rate_hard == pytest.approx(2 / 3), "inj-001 is still the one disagreement"
    assert run.metrics.judge_agreement_n_hard == 3
    assert run.notes is not None
    assert "judge_agreement_rate is not computed" in run.notes, "the blind figure is still uncomputed"

    seed_labels = tmp_path / "reference_labels.yaml"
    seed_labels.write_text(LABELS_SEED_BOUND, encoding="utf-8")

    run = runner.recompute_agreement(
        judged_run_with_turns.run_id,
        results_dir=tmp_path,
        metric="judge_agreement_rate",
        labels_path=seed_labels,
    )

    assert run.metrics.judge_agreement_rate == pytest.approx(2 / 3), "the blind figure is computed now"
    assert run.metrics.judge_agreement_n == 3
    assert run.notes is not None
    assert "not computed" not in run.notes, "a computed figure cannot be published beside its own retraction"
    assert "judge_agreement_rate=" in run.notes and "judge_agreement_rate_hard=" in run.notes
    assert run.notes.startswith("A finding from the drive pass."), "the prose either side of the note stands"
    assert "Judged in a second pass on 2026-09-10." in run.notes
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert "not computed" not in (on_disk["notes"] or ""), "and the retraction reaches the file REPORT.md reads"


def test_labels_carrying_no_turn_id_are_compared_on_the_old_terms(tmp_path, judged_run_with_turns, no_report):
    """Label files authored before the field existed keep working, binding or no binding."""
    labels = tmp_path / "reference_labels_hard.yaml"
    labels.write_text(LABELS_HARD, encoding="utf-8")

    run = runner.recompute_agreement(
        judged_run_with_turns.run_id,
        results_dir=tmp_path,
        metric="judge_agreement_rate_hard",
        labels_path=labels,
    )

    assert run.metrics.judge_agreement_rate_hard == pytest.approx(2 / 3)
    assert run.metrics.judge_agreement_n_hard == 3


def test_the_committed_labels_are_bound_to_the_published_runs_own_turns():
    """Both committed files, against `latest.json` — the binding the blinding paragraph claims.

    Republishing a run without re-authoring the packet leaves these turn ids pointing at the old
    run's answers, and this is where that is caught: `--recompute-agreement` would refuse, but only
    if someone ran it.
    """
    pointer = runner.RESULTS_DIR / "latest.json"
    if not pointer.exists():
        pytest.skip("no published run yet; latest.json lands at P11")
    run_id = json.loads(pointer.read_text(encoding="utf-8"))["run_id"]
    published = RunFile.model_validate(json.loads((runner.RESULTS_DIR / f"{run_id}.json").read_text(encoding="utf-8")))
    turns = {item.item_id: item.turn_id for item in published.items}

    for metric in AGREEMENT_METRICS.values():
        labels = load_reference_labels(metric.labels_path)
        if labels is None:
            continue
        wrong = [
            (label.item_id, label.turn_id, turns.get(label.item_id))
            for label in labels.labels
            if label.turn_id != turns.get(label.item_id)
        ]
        assert wrong == [], f"{metric.labels_path.name} is not bound to {run_id}'s turns: {wrong}"


def test_each_metrics_note_is_idempotent_and_leaves_the_other_metrics_note_standing():
    blind = AGREEMENT_METRICS["judge_agreement_rate"]
    hard = AGREEMENT_METRICS["judge_agreement_rate_hard"]

    notes = runner._agreement_note("A finding from the drive pass.", blind, "judge_agreement_rate=1.0 over n=7.")
    notes = runner._agreement_note(notes, hard, "judge_agreement_rate_hard=0.875 over n=8.")
    twice = runner._agreement_note(notes, hard, "judge_agreement_rate_hard=0.875 over n=8.")

    assert twice == notes, "a second fold-in of the same figure changes nothing"
    assert twice.count("judge_agreement_rate=1.0") == 1, "the blind note is not stacked or lost"
    assert twice.count("judge_agreement_rate_hard=") == 1
    assert twice.startswith("A finding from the drive pass.")


def test_the_pre_two_subset_inline_note_is_replaced_rather_than_duplicated():
    """Before the second subset existed the note was appended inline to the end of the prose."""
    blind = AGREEMENT_METRICS["judge_agreement_rate"]
    legacy = "A finding from the drive pass. judge_agreement_rate=1.0 over n=7 reference labels."

    folded = runner._agreement_note(legacy, blind, "judge_agreement_rate=1.0 over n=7 (subset seed_1729_8).")

    assert folded.count("judge_agreement_rate=") == 1
    assert "reference labels." not in folded
    assert folded.startswith("A finding from the drive pass.")


def test_the_cli_takes_a_metric_and_a_labels_path():
    args = runner.build_parser().parse_args(
        ["--recompute-agreement", "r_x", "--metric", "judge_agreement_rate_hard", "--labels", "some.yaml"]
    )

    assert (args.recompute_agreement, args.metric, args.labels) == ("r_x", "judge_agreement_rate_hard", "some.yaml")
    assert runner.build_parser().parse_args([]).metric == "judge_agreement_rate", "the blind subset is the default"


def test_the_two_metrics_name_two_different_files_and_two_different_subsets():
    blind = AGREEMENT_METRICS["judge_agreement_rate"]
    hard = AGREEMENT_METRICS["judge_agreement_rate_hard"]

    assert isinstance(blind, AgreementMetric)
    assert {blind.subset, hard.subset} == {"seed_1729_8", "judge_lowest_8"}
    assert blind.labels_path != hard.labels_path
    assert {blind.n_field, hard.n_field} == {"judge_agreement_n", "judge_agreement_n_hard"}


# --------------------------------------------------------------------------------------------
# What the report says about the pair
# --------------------------------------------------------------------------------------------


#: A blind label set on which the reference and the judge are unanimous `grounded` — the shape the
#: real `seed_1729_8` subset came back in, and the one whose matrix has no discriminating cell.
LABELS_SEED_UNANIMOUS = LABELS_SEED.replace(
    """  - item_id: inj-001
    verdict: grounded""",
    """  - item_id: conduct-001
    verdict: grounded""",
).replace(
    """  - item_id: conduct-001
    verdict: grounded
    rationale: every claim is in the evidence""",
    """  - item_id: pto-001
    verdict: grounded
    rationale: every claim is in the evidence""",
)


def _rendered(tmp_path, monkeypatch, *, seed_labels: str, hard_labels: str | None, rows, **metrics) -> str:
    """`render_report` with both label files pointed at temporary copies."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "reference_labels.yaml").write_text(seed_labels, encoding="utf-8")
    if hard_labels is not None:
        (tmp_path / "reference_labels_hard.yaml").write_text(hard_labels, encoding="utf-8")
    for name, filename in (
        ("judge_agreement_rate", "reference_labels.yaml"),
        ("judge_agreement_rate_hard", "reference_labels_hard.yaml"),
    ):
        slot = AGREEMENT_METRICS[name]
        monkeypatch.setitem(
            AGREEMENT_METRICS,
            name,
            AgreementMetric(
                name=slot.name,
                n_field=slot.n_field,
                subset_field=slot.subset_field,
                labels_path=tmp_path / filename,
                subset=slot.subset,
                definition=slot.definition,
            ),
        )
    return runner.render_report(_run(rows, **metrics))


ROWS = [_row("inj-001", 0.83), _row("pto-003", 0.93), _row("conduct-001", 1.0), _row("pto-001", 1.0)]


@pytest.fixture
def report(tmp_path, monkeypatch):
    return _rendered(
        tmp_path,
        monkeypatch,
        seed_labels=LABELS_SEED,
        hard_labels=LABELS_HARD,
        rows=ROWS,
        strict_pass_rate=0.654,
        judge_agreement_rate=1.0,
        judge_agreement_n=7,
        judge_agreement_subset="seed_1729_8",
        judge_agreement_rate_hard=2 / 3,
        judge_agreement_n_hard=3,
        judge_agreement_subset_hard="judge_lowest_8",
    )


def test_the_report_publishes_both_figures_each_with_its_n_and_its_subset(report):
    assert "`judge_agreement_rate` = **1.000** · `judge_agreement_n` = **7** · subset `seed_1729_8`" in report
    assert "`judge_agreement_rate_hard` = **0.667** · `judge_agreement_n_hard` = **3** · subset `judge_lowest_8`" in (
        report
    )


def test_the_report_says_why_the_second_subset_exists(report):
    assert "lowest judge groundedness" in report
    assert "not blind" in report and "selection_disclosed: true" in report
    assert "averaging the two would mean nothing" in report
    assert "whatever disagreement the run contains is inside the sample" in report


def test_the_blind_subsets_weakness_is_read_off_its_own_matrix_not_asserted(tmp_path, monkeypatch):
    """The sentence that motivates the whole second subset must be a measurement, not a claim.

    Rendered twice over two different blind label sets: unanimous, which is how the real
    `seed_1729_8` subset came back, and one carrying a `not_grounded`. The report says a different
    thing each time, so it cannot go on describing a matrix the run no longer has.
    """
    unanimous = _rendered(
        tmp_path / "a",
        monkeypatch,
        seed_labels=LABELS_SEED_UNANIMOUS,
        hard_labels=LABELS_HARD,
        rows=ROWS,
        strict_pass_rate=0.654,
        judge_agreement_rate=1.0,
        judge_agreement_n=2,
    )
    discriminating = _rendered(
        tmp_path / "b",
        monkeypatch,
        seed_labels=LABELS_SEED,
        hard_labels=LABELS_HARD,
        rows=ROWS,
        strict_pass_rate=0.654,
        judge_agreement_rate=2 / 3,
        judge_agreement_n=3,
    )

    assert "every one of those was a unanimous `grounded`" in unanimous
    assert "no discriminating cell" in unanimous
    assert "**1** of those carried a `not_grounded` on either side" in discriminating
    assert "every one of those was a unanimous `grounded`" not in discriminating


def test_the_report_marks_which_selection_was_blind_and_which_was_disclosed(report):
    blind_block = report.split("#### `judge_agreement_rate` —", 1)[1].split("#### ", 1)[0]
    hard_block = report.split("#### `judge_agreement_rate_hard` —", 1)[1].split("### ", 1)[0]

    assert "selection is blind (`selection_disclosed: false`)" in blind_block
    assert "selection is disclosed" in hard_block
    assert "sampled with `SEED = 1729`" in blind_block
    assert "ties\nbroken by item id" in hard_block or "ties broken by item id" in hard_block


def test_a_missing_hard_label_file_is_a_stated_absence_not_a_crash(tmp_path, monkeypatch):
    slot = AGREEMENT_METRICS["judge_agreement_rate_hard"]
    monkeypatch.setitem(
        AGREEMENT_METRICS,
        "judge_agreement_rate_hard",
        AgreementMetric(
            name=slot.name,
            n_field=slot.n_field,
            subset_field=slot.subset_field,
            labels_path=tmp_path / "nothing_here.yaml",
            subset=slot.subset,
            definition=slot.definition,
        ),
    )

    body = runner.render_report(_run([_row("inj-001", 0.83)], strict_pass_rate=0.654))

    assert "nothing_here.yaml` is not present" in body
    assert "has not been computed" in body


def test_the_committed_blind_labels_still_declare_the_blind_subset():
    """The seed file gained two protocol keys; it must not have gained the hard subset's values."""
    labels = load_reference_labels()

    assert labels is not None
    assert labels.protocol.subset == "seed_1729_8"
    assert labels.protocol.selection_disclosed is False
    assert labels.protocol.seed == 1729


def test_the_hr_adjacent_out_of_scope_items_are_in_neither_subset():
    """P24's `oos-004` / `oos-005` are refusals: there is no policy claim in them to label.

    Both subsets draw from the gold-`answer` population, so adding two `refuse` items to
    `dataset.yaml` must leave `reference_subset()`'s seed-1729 selection and the disclosed
    hard-case selection untouched — which is what keeps the committed reference labels valid
    across a dataset that grew.
    """
    dataset = load_dataset()
    added = {"oos-004", "oos-005"}
    assert added <= {item.id for item in dataset.items}, "the two HR-adjacent items are in the dataset"
    assert all(item.expected_behavior == "refuse" for item in dataset.items if item.id in added)

    rows = [_row(item.id, 0.1 if item.id in added else 0.9, category=item.category) for item in dataset.items]
    assert not added & set(reference_subset(dataset))
    assert not added & set(judge_lowest_subset(_run(rows), size=len(dataset.items), dataset=dataset))
