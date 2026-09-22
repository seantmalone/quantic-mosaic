# Task 5d — a recomputed agreement retracts the drive-time note; the sample-size contract test reads the threshold

Two fixes, both small, on `main`. Working tree clean afterwards apart from this report.

## 1. `evaluation/runner.py` — the degradation note is retracted when the figure is computed

The drive-path note is now built in one place and matched in one place:

* `_degraded_agreement_prefix(name)` → `f"{name} is not computed on this run:"` — the stable prefix.
* `_DEGRADED_AGREEMENT_TAIL` — the note's closing sentence (`Re-author the packet … (§13.7).`).
* `_degraded_agreement_note(name, mismatched)` — what `Runner.assemble()` now appends (byte-identical
  to the sentence it used to build inline, so the committed run file's own note matches it).
* `_retract_degraded_agreement_note(previous, name)` — cuts from the prefix to the tail, or to the end
  of the line if a hand-trimmed note has lost the tail (`re.MULTILINE`, no `DOTALL`, so the cut never
  crosses a line), consuming the whitespace before it so the surrounding prose reads normally.
* `_agreement_note()` calls the retraction for the slot it is folding in *before* its existing
  per-line replacement. The retraction is **per metric**: recomputing `judge_agreement_rate_hard`
  leaves a `judge_agreement_rate is not computed…` note standing, because that figure may really
  still be uncomputed. In practice `assemble()` only ever degrades the blind metric (it loads the
  seed label file alone), so there is one note, not two.

`assemble()`'s wording, the run file and REPORT.md all still say the same thing when the labels *are*
stale; the only change is that computing the figure removes the sentence.

### Unit test — extended, not added (collection stays 3,438)

`tests/unit/test_hard_case_agreement_subset.py::test_labels_whose_turn_matches_the_run_are_folded_in`
now writes the real drive-time note (built by `runner._degraded_agreement_note`) into the run file on
disk, folds the hard labels in — asserting the *blind* metric's note survives — then folds the blind
labels in (new `LABELS_SEED_BOUND`, the bound labels re-declared under `seed_1729_8`) and asserts:
`judge_agreement_rate` is set (2/3 over n=3), `"not computed" not in run.notes`, both
`judge_agreement_rate=` / `judge_agreement_rate_hard=` lines present, the prose either side of the
retracted sentence still standing, and the same absence in the JSON on disk that REPORT.md reads.

## 2. Re-run for the published run

```
--recompute-agreement r_1790110325_baseline --metric judge_agreement_rate      --labels evaluation/reference_labels.yaml
  → judge_agreement_rate 1.0, judge_agreement_n 8, subset seed_1729_8
--recompute-agreement r_1790110325_baseline --metric judge_agreement_rate_hard --labels evaluation/reference_labels_hard.yaml
  → judge_agreement_rate_hard 0.75, judge_agreement_n_hard 8, subset judge_lowest_8
--report r_1790110325_baseline  → r_1790110325_baseline, baseline/deployed, judged
```

Both figures **unchanged** (1.000 n=8; 0.750 n=8) — the fix removes a sentence, not a number.

* `grep -n "not computed" evaluation/REPORT.md` → **no match** (exit 1).
* `grep -c "not computed" evaluation/results/r_1790110325_baseline.json` → **0**.
* `scripts/paste_eval_numbers.py --check` → `OK — the results table matches …/latest.json`, **exit 0**
  (it changed nothing, so `design-and-evaluation.md` is untouched and is not in the commit).

The diff on both artifacts is one line each: the eight-turn "not computed" sentence leaves the notes
paragraph; `(§9.4).` is now followed directly by `Judged in a second pass on 2026-09-22 …`.

## 3. `tests/contract/test_dashboard_pages.py` — the sample-size test reads P14's threshold

`test_a_headline_rate_under_the_threshold_prints_its_sample_on_the_list_page` now imports
`SMALL_SAMPLE` from `hrmosaic.web.dashboard` and pairs each rendered `arg_correctness_rate` cell with
**its own run's** `n` from `/api/eval/runs` (the same view-model the page renders from), by splitting
the headline table into rows and reading the run id out of each row's link. Below the threshold the
sample is required *and* its denominator must equal that `n`; at or above it the sample must be
absent (the assertion now covers the other direction too, which the old one could not). Non-vacuity
is asserted explicitly: `assert under_threshold, "…vacuous"` — the committed runs do carry rates
under n=20, and the test passes with that assertion live. No change to `SMALL_SAMPLE` or to any
product code: the rendering was already right.

## 4. Verification

```
make lint                                              → ruff check: All checks passed; format: 321 files already formatted
pytest tests/contract/test_dashboard_pages.py tests/unit/test_hard_case_agreement_subset.py \
       tests/contract/test_docs_completeness.py tests/unit/test_run_provenance.py
                                                       → 113 passed in 30.62s
pytest tests/contract                                  → 558 passed in 150.24s
pytest --collect-only -q -m ""                         → 3438 tests collected
```

`tests/contract` is green — the failure Task 5c reported as concern 1 is gone, and concern 2 is fixed.

## Concerns left standing (unchanged by this task)

Task 5c's concerns 3–7 are untouched: `design-and-evaluation.md`'s hand-written §13.7 prose still
carries the previous run's agreement figures and subset membership (3), its blinding paragraph still
claims no judge output existed upstream of the seed packet (4), Task 5's report quotes PDT readings as
UTC (5), the ablation's §13.9 claim remains unsupported at −0.167 against the 0.25 bar (6), and gap
9's remaining edges — no trace-store check on a label's `turn_id`, no answer-text sha — are still open (7).
