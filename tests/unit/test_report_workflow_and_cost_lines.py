"""Two lines of `REPORT.md` that used to state a number nothing in the run supports.

* **workflow completion by workflow** was a bare `json.dumps` of the dict, printed with no `n` in a
  Behaviour section a grader reads for rubric bullet 3. Each workflow has exactly one tagged item
  in `evaluation/dataset.yaml`, so `{"remote_work_eligibility": 0.0}` is one item — not a workflow
  that never completes — and every other judged row on the page carries its `n`.
* **What the judge pass cost** hard-coded a *264*-call pass inside a paragraph that claimed to
  describe "this pass", in a report whose own header said 249: the literal was carried over from an
  earlier run (`r_1789055103_baseline`, where 264 was true) when the published run changed.

Both now come from the run and the dataset, so neither can go stale behind a new published run.
"""

from __future__ import annotations

import evaluation.runner as runner
from evaluation.schema import ItemResult, RunConfig, RunFile, RunMetrics

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


def _run(*, by_workflow: dict[str, float], judge_calls: int = 249, item_ids: tuple[str, ...] = ()) -> RunFile:
    return RunFile(
        run_id="r_test",
        created_at=0,
        git_sha="dev",
        label="",
        variant="baseline",
        target="deployed",
        target_base_url="https://example.invalid",
        dataset_sha="0" * 64,
        config=CONFIG,
        n_items=26,
        judge_calls=judge_calls,
        metrics=RunMetrics(judged=True, workflow_completion_by_workflow=by_workflow, n_scored={"items": 26}),
        items=[ItemResult(id=f"r_test::{item_id}", item_id=item_id, category="simple_policy") for item_id in item_ids],
    )


def test_each_workflow_figure_carries_its_n_and_the_item_behind_it():
    line = runner._workflow_completion_line(
        _run(
            by_workflow={"pto_request": 1.0, "remote_work_eligibility": 0.0},
            item_ids=("pto-003", "remote-004"),
        )
    )

    assert "`pto_request` 1.00 (n = 1, `pto-003`)" in line
    assert "`remote_work_eligibility` 0.00 (n = 1, `remote-004`)" in line
    assert "single-item indicators, not rates" in line
    # The shortfall is attributed to the item it belongs to, and only to that item.
    assert "the shortfall on `remote-004`" in line
    assert "pto-003" not in line.split("the shortfall on")[1]
    # Not a JSON dump of a dict any more.
    assert '{"' not in line


def test_a_workflow_whose_item_was_not_scored_is_not_credited_with_an_item():
    line = runner._workflow_completion_line(_run(by_workflow={"pto_request": 1.0}, item_ids=()))

    assert "`pto_request` 1.00" in line
    assert "n = " not in line, "no item id is invented for a run that did not score one"


def test_no_workflow_tag_at_all_says_so_rather_than_printing_an_empty_dict():
    assert "no scored item" in runner._workflow_completion_line(_run(by_workflow={}))


def test_the_cost_note_states_this_runs_call_count_and_names_the_measured_run():
    note = runner.judge_cost_note(_run(by_workflow={}, judge_calls=249))

    assert "This run's\njudge pass made 249 calls" in note.replace("**", "")
    # The token totals are a different run's, and it is named rather than left floating.
    assert runner.JUDGE_COST_MEASURED_RUN in note
    assert f"{runner.JUDGE_COST_MEASURED_CALLS} calls" in note
    # And the arithmetic a reader would redo is still on the page.
    assert "$0.30/1M" in note and "$2.50/1M" in note


def test_a_different_call_count_changes_the_paragraph():
    note = runner.judge_cost_note(_run(by_workflow={}, judge_calls=296))

    assert "296 calls" in note
    assert "made 264 calls" not in note.replace("**", "")
