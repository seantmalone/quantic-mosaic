# Task 2 report — evaluation compare: comparability by build, the hypothesis metrics, cold cells

**Status: DONE_WITH_CONCERNS** (one concern, below — it is a hand-off, not a defect).
**Commit:** `b0261d6` on `main` — `G5(eval-compare): comparability by build, the hypothesis metrics
on the compare tab, cold cells that say they were not measured`.

## Gap 8 — the build is part of comparability, and a cross-build pairing is visible

`evaluation/ablation.py`

* `assert_comparable` now guards a third field: `target_git_sha`. The message names which arm was on
  which build (`baseline=bd4ac9336e87, dense_only_k2=34717b52eb01`) rather than saying only "not
  comparable".
* `None` is treated as a value, not a wildcard: an all-`None` set (a `local` target, or any run file
  written before 2026-09-11) is still comparable; a **mix** of `None` and a sha is refused, because
  nothing in such a pair says the two runs were measured on the same code.
* `build_comparison` writes the one shared `target_git_sha` into `comparison.json` (top level, beside
  `target` and `dataset_sha`), and `render_section`'s footnote names it — so REPORT.md's claim about
  what the script asserts stays true. A `local` comparison prints "no `target_git_sha` (a local
  target)" instead of naming `None`.
* `AblationError`'s docstring and the module docstring were updated to the three guards.

`src/hrmosaic/web/dashboard.py`

* `VariantMetrics.target_git_sha` — read back from `evaluation/results/<run_id>.json` by the new
  `_target_git_sha()`. **`eval_runs` has no column for it** (`core/migrations/001_initial.sql` predates
  the field and `core/archive.py` imports every other run-file field), so the committed run file is
  the only place the tab can read it; a run with no file on disk (a dashboard smoke run) reports
  `None`. The path is confined to `RESULTS_DIR` (`path.parent != RESULTS_DIR` → `None`).
* `EvalCompareView.builds_differ` — true when more than one *recorded* sha appears among the arms.
  Unrecorded is treated as unknown, never as agreement and never as a difference.

`src/hrmosaic/web/templates/dashboard/evals.html`

* A new `ablation-builds-table` above the chart: Variant · Run · **Build measured** (the shared
  `kind: 'id'` 8-character chip, full sha in `title=`), with a `help` definition on the build column.
* `<p class="alert" id="ablation-build-notice">` when `builds_differ` — "These arms were measured on
  different builds…", rendered *before* the chart, because it decides whether the deltas mean
  anything. Verified against the real committed run files: the live tab pairs
  `r_1789555212_baseline` (`bd4ac933`) with two arms on `34717b52`, and the notice renders.
* No CSS was touched: `.alert`, `.facts`, `.flag`, `.id-chip` and the table macro's own classes are
  pre-existing (there is a one-directional orphan-class contract test, and `app.css` is not in this
  task's file set).

## Gap 25 — the hypothesis metrics, the pre-registered check, and the cold cells

* `EvalMetrics` (which lives in `src/hrmosaic/web/dashboard.py`, **not** in `evaluation/schema.py` —
  see assumptions) gained `workflow_completion` and `doc_recall_mean`. `extra="ignore"` had been
  discarding both, so the two figures the arms exist to move could not be charted.
* `METRIC_LABELS` gained "Workflow completion" and "Documents recalled"; `RATE_METRICS` gained both,
  so they render as percentages like every other 0–1 proportion.
* `ablation_series` in `evals.html` leads with `workflow_completion, doc_recall_mean` and keeps the
  six it had — one list, still read by both the chart and the read-out table (UX W5).
* `_published_workflow_check()` reads `comparison.json`'s `workflow_completion_check` — nothing in
  `src/` read it before — into a new `WorkflowCheck` view-model, rendered as a `.facts` block
  (`id="workflow-completion-check"`) with baseline, arm, **delta**, the **pre-registered bar** and a
  yes/no on the claim, plus a paragraph that spells out §13.9's inequality and the supported /
  not-supported reading.
* `WorkflowCheck` also carries `baseline_run_id` / `no_structured_tools_run_id`, and the page prints
  them as id chips. This is the one place I went past the literal minimum, and deliberately: the
  published check is computed on `r_1789166880_baseline` (89.3%) while the tab charts
  `r_1789555212_baseline` (96.4%), so printing the published delta with no provenance would have put
  two different baselines on one screen with nothing to reconcile them.
* `_f_ms_n` returns `not measured (n=0)` for a sample of zero; `n=1`…`n=4` and the formatted
  millisecond path are unchanged. This is the cold-latency cell of page 11 (`cold_p50`, `cold_p95`
  over `n_cold`), and it also covers the overview KPIs and the tools rollup when nothing was sampled.

## Docs

* Suite size 3,352 → **3,367** in `README.md`, `ai-tooling.md`, `design-and-evaluation.md`,
  `docs/requirements-traceability.md` (+15 tests: 9 unit, 6 contract). `pytest --collect-only -q -m ""`
  reports `3367 tests collected`; `test_every_document_that_states_the_suite_size_states_the_collected_one`
  is green.
* `docs/requirements-traceability.md` R9.5 said `ablation.py` "asserts every compared run shares
  `target` and `dataset_sha`" — now also `target_git_sha`, with the reason in one clause. Correcting a
  claim about the code I just changed; no other prose was touched.

## Tests added

`tests/unit/test_ablation_comparability.py` (new, 9 tests)

* one target / dataset / build is comparable; a mixed target, a moved dataset and **two builds** are
  each refused with their own message;
* the message names both builds;
* all-`None` builds stay comparable; a recorded build beside an unrecorded one is refused;
* `build_comparison` refuses the mixed trio (the guard is on the write path, not only in the helper);
* the comparison dict and REPORT.md's footnote name the one shared build, and a local comparison says
  it has none.

`tests/contract/test_dashboard_viewmodels.py` (6 added)

* `test_the_compare_tab_names_each_arms_build_and_says_so_when_they_differ` — per-arm shas in the
  payload, `builds_differ: true`, the notice and the table on the page, both short shas painted;
* `test_one_shared_build_still_names_it_and_raises_no_notice`;
* `test_a_build_no_run_file_records_is_unknown_rather_than_shared`;
* `test_the_compare_tab_charts_both_arms_hypothesis_metrics` — both metrics non-null on all three
  arms and both names in the shared `chart-ablation-series` list;
* `test_the_compare_tab_publishes_the_pre_registered_workflow_check` — the whole `workflow_check`
  payload, the delta and the bar on the page through `|pct`, and the run ids it was computed on;
* `test_a_cold_latency_cell_with_no_samples_says_it_was_not_measured` — the formatter, including the
  unchanged `n=3` / `4.20 s` paths.

A note on the test helpers: the compare tab shows the **newest** run of each variant, and the boot
import of `evaluation/results/` means those are the real committed runs, not the `r_p9fixture_*`
fixtures — so the new tests read the run ids off the payload first and then write the run files whose
provenance they want under a monkeypatched `RESULTS_DIR`. My first draft keyed on `VARIANT_RUNS` and
failed for exactly that reason.

## Commands run

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest tests/unit/test_ablation_comparability.py -q` | `9 passed in 0.80s` |
| `.venv/bin/python -m pytest tests/contract/test_dashboard_viewmodels.py -q` | `25 passed in 27.02s` |
| `make lint` (`ruff check .` + `ruff format --check .`) | `All checks passed!` · `315 files already formatted` |
| `make test` | `3068 passed, 299 deselected in 333.08s (0:05:33)` |
| `.venv/bin/python -m pytest tests/unit/test_ablation_comparability.py tests/contract/test_dashboard_viewmodels.py tests/contract/test_dashboard_pages.py tests/contract/test_docs_completeness.py tests/contract/test_published_run_commands.py -q` (after the last docstring edits) | `120 passed in 58.91s` |
| `.venv/bin/python -m pytest --collect-only -q -p no:cacheprovider -m ""` | `3367 tests collected` |

## Assumptions

1. **The brief says `EvalMetrics` is in `evaluation/schema.py`; it is not.** `evaluation/schema.py`'s
   `RunMetrics` has carried `workflow_completion` and `doc_recall_mean` since P10 (lines 286–290);
   the class that dropped them is `src/hrmosaic/web/dashboard.py::EvalMetrics`. I made the change
   there, so `evaluation/schema.py` is unchanged.
2. **The pre-registered check is the published one**, read from `comparison.json` (the gap's evidence
   is that nothing in `src/` reads that key), not recomputed from the two runs the tab charts. To keep
   that honest I added the check's own run ids to the payload and the page.
3. **`builds_differ` counts recorded shas only.** A mix of a recorded and an unrecorded build raises
   no notice on the page (it does refuse the *published* comparison in `ablation.py`, where both runs
   are in hand): on the page, unknown is not evidence of a difference.
4. **`not measured (n=0)` applies to every `ms_n` cell**, not only the cold ones — the formatter is
   the single path (P10) and "not measured" is the right reading for any percentile over no samples.
5. I did not regenerate `evaluation/results/comparison.json` and did not touch
   `docs/demo-script.md:63`'s delta — both belong to the task that re-drives the arms.

## Concerns

1. **`make ablation` cannot be run until the arms are re-driven** — which is the intended end state of
   gap 8, but worth stating plainly: with the committed results as they are, `assert_comparable` now
   *refuses* the published trio (baseline `bd4ac93` vs two arms on `34717b5`) and `make ablation`
   exits 2. `comparison.json` therefore keeps its current contents, still carrying no top-level
   `target_git_sha`, until the later task re-drives both arms on the shipped build and regenerates it.
   The dashboard handles that file exactly as it is (the compare tab was checked against it), and
   `docs/demo-script.md`'s −0.143 is still the stale pair's delta.
2. **Minor, cosmetic:** the chart now plots 8 series against a 6-colour palette
   (`window.chartPalette().series` in `_base.html`), so the two baseline-only judged series reuse the
   first two hues. `app.css` / `brand.css` are outside this task's file set, so I did not add
   `--series-7/8`; the visually-hidden read-out table beside the chart carries all eight series by
   name, which is the a11y path the chart's own comment relies on.
