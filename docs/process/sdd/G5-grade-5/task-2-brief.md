## Task 2 — Evaluation compare: comparability by build, the hypothesis metric on the compare tab, cold cells

Closes gaps **8 (code half)** and **25**.

1. Gap 8 — `evaluation/ablation.py::assert_comparable` must also require a shared
   `target_git_sha` across the arms it compares. The dashboard compare view
   (`src/hrmosaic/web/dashboard.py::build_eval_compare` and its template) must show each arm's
   `target_git_sha` (short form) and must not silently pair arms from different builds: render a
   visible "arms measured on different builds" notice when they differ.
2. Gap 25 — add `workflow_completion` and `doc_recall_mean` to `EvalMetrics`
   (`evaluation/schema.py`) and to `ablation_series`, so the compare tab can chart the ablation's
   own hypothesis metric; surface `workflow_completion_check` (delta and the pre-registered bar) on
   the compare tab; and where the cold-latency cells read n=0, render "not measured (n=0)" rather
   than a bare 0.

Add or extend tests under `tests/contract/test_dashboard_viewmodels.py` and a unit test for
`assert_comparable`. Run `make lint`, the unit and contract suites. Commit as `G5(eval-compare): ...`.

