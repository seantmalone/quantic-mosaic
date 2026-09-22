# Task 5b — reference labels carry a turn binding; the report's protocol prose is held to the label files

Closes the mechanical half of gap **9**. Commit `f1dcb34` on `main`.

## What changed

**1. `evaluation/schema.py::ReferenceLabel.turn_id`** — `str | None = None`, `extra="forbid"` kept. The
docstring says why it exists and why `None` stays legal (files authored before the field).

**2. Both label files carry the turn of the answer each label was authored against**, read from
`evaluation/results/r_1790074972_baseline.json`'s `items[].turn_id`. Every entry in
`evaluation/reference_labels.yaml` (8) and `evaluation/reference_labels_hard.yaml` (8) gained the
field; **no verdict, rationale or protocol field was touched**. Each file's `labels:` key gained a
five-line comment stating what the binding is and which run it is against, so the blinding
paragraph's "that run's own served answers" is now checkable rather than asserted.

**3. `evaluation/runner.py::_refuse_labels_from_another_turn()`**, called from `recompute_agreement()`
immediately after the existing wrong-subset refusal. It raises `SystemExit` naming every mismatched
item and both turns:

```
<labels path> was authored against different served answers than <run_id>: inj-001 (label X, run Y).
A reference label is a verdict on one answer, so it cannot be scored against another run's (§13.7).
Re-author the packet against this run, or fold these labels into the run they were written for.
```

Two cases are deliberately not errors, and the docstring says so: `turn_id: null` (older files, old
terms), and a label whose `item_id` this run never drove (already outside `judge_agreement()`'s
denominator, so it cannot move the rate — refusing would only block a legitimate label set from a
run over a subset of the dataset).

**4. Contract test** `tests/contract/test_docs_completeness.py::test_the_reports_protocol_paragraphs_are_the_label_files_own_words`
— `evaluation/REPORT.md` must carry exactly one `Protocol: labeller …` paragraph per committed label
file, in `AGREEMENT_METRICS` order, each carrying that file's `protocol.labeller` verbatim inside
backticks, its `labelled_on`, and **ending with** its `protocol.blinding` verbatim. It is pinned to
the label fields, not to the runner's connective format, so a renderer change plus a regeneration
does not fail it while a hand-edit of either label file does. Verified by mutating the tail of
`reference_labels.yaml`'s blinding paragraph: the test failed on `endswith`, and passed again on
restore.

**5. Four unit tests** in `tests/unit/test_hard_case_agreement_subset.py` (the file that already owns
`recompute_agreement`), under a new "The turn binding (gap 9)" section:

- a mismatched `turn_id` is refused — the message names the mismatched item and both turns, does not
  name the matching ones, and neither REPORT.md nor the run file is written;
- a matching `turn_id` folds in as before (rate 2/3, n 3);
- labels with no `turn_id` fold in as before;
- **the committed files are bound to `latest.json`'s run's own turns** — every label in both files,
  against the published run's `items[]`. Republishing a run without re-authoring the packet now
  fails in CI, not only when someone remembers to run `--recompute-agreement`.

## The two agreement figures, recomputed

Both through the wrapper, then `--report`:

```
run_eval.py evaluation.runner --recompute-agreement r_1790074972_baseline --metric judge_agreement_rate
  → judge_agreement_rate 1.0, judge_agreement_n 8, subset seed_1729_8
run_eval.py evaluation.runner --recompute-agreement r_1790074972_baseline --metric judge_agreement_rate_hard \
    --labels evaluation/reference_labels_hard.yaml
  → judge_agreement_rate_hard 0.875, judge_agreement_n_hard 8, subset judge_lowest_8
run_eval.py evaluation.runner --report r_1790074972_baseline
```

**Unchanged, as required: seed `1.000` n=8, hard `0.875` n=8.** `evaluation/results/r_1790074972_baseline.json`
and `evaluation/REPORT.md` came back **byte-identical** (`diff` against pre-run copies is empty), so
neither is in this commit and the ablation section survived untouched — nothing was hand-edited.

```
$ .venv/bin/python scripts/paste_eval_numbers.py --check
OK — the results table matches evaluation/results/latest.json     # exit 0
```

## Suite size

`pytest --collect-only -q -m ""` now collects **3,415** (was 3,410; +5 = 4 unit + 1 contract);
`-m ux` still 299, so the non-ux figure is 3,116. Bumped in `README.md`, `ai-tooling.md` (its stale
`as of 2026-09-21` moved to `2026-09-22` with the number), `design-and-evaluation.md`,
`docs/requirements-traceability.md` — and in **`docs/demo-script.md`**, which states the same figure
as `3,111 of 3,410` for the CI screen and would otherwise contradict the other four.
`test_every_document_that_states_the_suite_size_states_the_collected_one` covers only the four.

`docs/requirements-traceability.md`'s **RUBRIC5.8** row (the one that describes the reference labels)
now records the binding: each label carries the `turn_id` of the served answer it was authored
against and `--recompute-agreement` refuses to score it against another run's answers.

## Verification

- `make lint` — ruff check + format clean (320 files).
- `.venv/bin/pytest -q -p no:cacheprovider tests/contract tests/unit` — **2933 passed** in 220 s, no failures.
- `scripts/paste_eval_numbers.py --check` — exit 0.

## Concerns

1. **The drive-time fold-in is still unguarded, and it is the same bug.** `runner.py:874` folds
   `load_reference_labels()` into a run *during* the drive whenever the judge is enabled. Now that
   the committed labels are bound to `r_1790074972_baseline`'s turns, the next judged drive will
   compute a `judge_agreement_rate` over labels authored against a different run's answers — silently,
   exactly as gap 9 describes — until `--recompute-agreement` overwrites it. I left it alone because
   the brief scopes the refusal to `--recompute-agreement` and because a `SystemExit` there would
   discard a paid drive. The right shape is to *degrade* rather than refuse: if any label's `turn_id`
   mismatches, leave the rate `null` and append a note saying the labels were authored for another
   run and must be re-authored, then folded in. Roughly six lines plus one test.
2. **Nothing checks that a label's `turn_id` is a turn that exists in the trace store**, only that it
   equals the run file's. That is the binding gap 9 asks for; a stronger one (a sha of the answer
   text) would also catch a run file whose `turn_id` is right but whose stored answer changed.
3. **The guard is silent on labels for items the run never drove.** Documented in the helper, and it
   cannot inflate or deflate the published rate, but a label set from a *completely* different
   dataset would fold in as `n=0` rather than as a refusal.
4. The blinding prose still carries the timing claim Task 5 worded carefully (packet built 04:25:16Z,
   judged run file written 04:37:44Z, judge pass already in flight). The turn binding does not
   evidence *when* the packet was built, only *which* answers it carried; the paragraph is still the
   only source for the ordering.

---

## Fix round 1 — a judged drive never folds in labels bound to another run's turns

Commit `9bf1532` on `main`. Three files only, as instructed: `evaluation/runner.py`,
`tests/unit/test_hard_case_agreement_subset.py`, `tests/contract/test_docs_completeness.py`.
Nothing touched in `design-and-evaluation.md`, `docs/optimization-log.md`, `README.md` or
`docs/evidence`; `docs/optimization-log.md:739` left to the final sweep.

**Concern 1, closed.** The mismatch computation is now `_mismatched_turns(turns, labels) -> list[str]`,
read by both callers:

- `_refuse_labels_from_another_turn()` (the `--recompute-agreement` path) — unchanged behaviour,
  `SystemExit`. Nothing has been spent there and the operator is folding one file into one run.
- **`Runner.assemble()`** (the drive path, and therefore `--judge` too, which calls `assemble` at
  `runner.py:2042` with the original `turn_id`s re-attached by `_score`) — builds the item→turn map
  over **every driven row** and, when any label mismatches, leaves `judge_agreement_rate` `None` /
  `judge_agreement_n` `0` and appends a note naming each mismatched item with both turns and pointing
  at `--recompute-agreement`. **Never a `SystemExit` mid-drive**: a drive has already been paid for.
  The check is gated on `self._judge_enabled`, so an unjudged arm gains no note it cannot act on.

So a fresh judged drive, or a `--judge` over an older run, now publishes **no** agreement figure
rather than one computed against another run's served answers — and `write_report` can no longer put
that figure in REPORT.md. `r_1790074972_baseline` is unaffected: its turns are the ones the committed
labels carry, so a re-judge of it still computes 1.000 (n=8).

**MINOR 1.** The contract test now asserts `paragraph.endswith(f"labelled {labelled_on}. {blinding}")`
— one `endswith` over date *and* blinding, so nothing can be inserted between them.

**MINOR 2.** The label files are filtered to the committed ones *before* the `zip(..., strict=True)`,
with an `assert committed` guard, so an absent file can no longer raise `ValueError` ahead of the
intended message.

**MINOR 3.** `_mismatched_turns`'s docstring states that `turns` is every driven item's turn, not
only the scored ones, and why (an `unavailable` or cold-probe row still carries the turn a packet
would have rendered).

**No new collected items.** The drive-path assertions were added to the existing
`test_labels_authored_against_another_runs_answers_are_refused`, which now pins both directions —
refusal on the operator path, uncomputed-with-a-note on the drive path — via a `_driven_row()` helper
and a monkeypatched `load_reference_labels`. The file still collects 28 tests and the suite still
collects **3,415**, so the four NUMBER_DOCS need no bump.

### Verification (fix round 1)

- `make lint` — clean (320 files).
- `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_hard_case_agreement_subset.py tests/contract/test_docs_completeness.py tests/unit/test_run_provenance.py tests/unit/test_cold_probe_excluded.py tests/unit/test_two_pass_judging.py` → **108 passed**. The last two are the other tests that drive `assemble()` with the committed labels loaded, so they are where this change would have broken something.
- `.venv/bin/pytest -q -p no:cacheprovider tests/contract tests/unit` → **2933 passed** in 225 s, unchanged from the pre-fix count (no collected item added).
- `.venv/bin/pytest --collect-only -q -m ""` → **3415 tests collected**.
- `scripts/paste_eval_numbers.py --check` → exit 0. Agreement figures untouched (no run file or REPORT.md in this commit).

### Remaining concerns

Concerns 2–4 above still stand (no answer-text sha; a label for an item the run never drove is
accepted by design; the blinding prose is still the only evidence for *when* the packet was built).
One new, small one: the drive-path note is prose in `notes`, and nothing asserts a reader sees it —
REPORT.md renders the null rate as "no item in this subset carries a judge groundedness score in this
run", which is true but does not say *stale labels*. A future sweep could render the note's reason in
the agreement block instead.
