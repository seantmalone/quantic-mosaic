## Task 5b — Reference labels carry a turn binding, and the report's protocol prose is held to the label files

Closes the mechanical half of gap **9** (rank 9 in gaps.json: "the labels carry no turn binding").

1. `evaluation/schema.py::ReferenceLabel` gains an optional `turn_id: str | None = None` (keep `extra="forbid"`), and the two label files (`evaluation/reference_labels.yaml`, `evaluation/reference_labels_hard.yaml`) carry the `turn_id` of the served answer each label was authored against — read them from `evaluation/results/r_1790074972_baseline.json` (`items[].turn_id`) and add the field to every entry (verdicts and rationales unchanged).
2. `evaluation/runner.py`'s `--recompute-agreement` path refuses (clear SystemExit message) when a label's `turn_id` is set and does not equal the run's turn for that item — so labels authored for one run can never be scored against another run's answers silently. Labels without `turn_id` keep working (older files).
3. A contract test asserting that `evaluation/REPORT.md`'s two protocol paragraphs equal the label files' `protocol.labeller`/`blinding` fields (the runner renders them verbatim), so the report cannot drift from the labels.
4. Unit tests: the guard refuses a mismatched turn_id; accepts a matching one; accepts a missing one.
5. Re-run `--recompute-agreement` for both metrics on `r_1790074972_baseline` (through the wrapper `.venv/bin/python .superpowers/sdd/2026-09-21-grade-5/run_eval.py evaluation.runner …` if it needs the trace store; the figures must be unchanged: seed 1.000 n=8, hard 0.875 n=8) and `--report r_1790074972_baseline`; `scripts/paste_eval_numbers.py --check` exits 0.

Run `make lint` and the contract + unit suites. Bump the suite-size figure in the four documents (README.md, ai-tooling.md, design-and-evaluation.md, docs/requirements-traceability.md; currently 3,410) if you add tests, and update `docs/requirements-traceability.md`'s row for the reference labels if it describes the binding. Commit as `G5(eval): reference labels are bound to the turn they were authored against`. Never read `.env` or `data/runtime/provision_turso.json`.
