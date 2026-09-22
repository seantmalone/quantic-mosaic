# Task 5 — the published run on the final build, blind labels re-authored, agreement recomputed

**Commit `8782177`** on `main`: `G5(eval): the published run on the final build — r_1790074972_baseline (8a89310), arms on the same build, blind labels re-authored, agreement recomputed`. Nine paths, explicitly added: the three new run files, `comparison.json`, `latest.json`, `evaluation/REPORT.md`, both label files, `design-and-evaluation.md`. Nothing under `.superpowers/`. Working tree clean afterwards.

## The runs

| Run | Variant | Target | Harness sha | Target sha | Judged | Items |
|---|---|---|---|---|---|---|
| `r_1790074972_baseline` | `baseline` | `deployed` | `8a89310` | **`8a89310`** | judged, 268 judge calls | 28 |
| `r_1790075436_dense_only_k2` | `dense_only_k2` | `deployed` | `8a89310` | **`8a89310`** | `not_applicable` (§13.9) | 28 |
| `r_1790075830_no_structured_tools` | `no_structured_tools` | `deployed` | `8a89310` | **`8a89310`** | `not_applicable` (§13.9) | 28 |

All three on dataset sha `e83cc9fc4833e548…`, agent `claude-haiku-4-5`, judge `gemini-3.5-flash-lite`. Baseline duration 439.9 s, `est_cost_usd` 0.773082. `latest.json` → `r_1790074972_baseline`.

The previous commit `e353a3d` published `r_1790067656_baseline` on `e85305b`; those files stay committed as history but are **no longer the published run**.

## Headline metrics, with n (from `metrics.n_scored`)

| Metric | Value | n |
|---|---|---|
| Strict pass rate (§13.8 composite) | **0.893** | 28 |
| Groundedness (mean, claim-level) | 0.963 | 18 |
| Citation accuracy (CitResolve × F1) | 0.875 | 18 |
| Citation resolvability (served answer) | 1.000 | 28 |
| Document recall | 0.947 | 19 |
| Partial match (gold facts entailed) | 0.801 | 18 |
| Tool selection (F1, order-insensitive) | 0.993 | 28 |
| Argument correctness | 1.000 | 19 |
| Workflow completion | 0.964 | 28 |
| Clarification accuracy | 1.000 | 3 |
| Action-safety pass rate | 1.000 | 1 |
| Over-refusal rate | 0.000 | 18 |
| Missed-refusal rate | 0.000 | 6 |
| Behaviour class (escalation matrix) | diagonal, `escalation_n_excluded` = 0 | 28 |

Also: `nudge_rate` 0.571, `catalog_reopened_rate` 0.000, `blocks_dropped_by_g2` 0, `gated_attempts` 1, `injection_quarantined` true, `recommendation_labeled_rate` 0.253, `n_cold` 0, latency p50/p90/p95/p99 = 15,314 / 24,146 / 26,035 / 27,457 ms.

## Strict-pass causes (3 of 28 failed)

Recomputed by `deterministic.strict_pass_causes()` — the same function the `passed` flag is defined by — and rendered in REPORT.md:

| Item | Category | §13.8 clause failed |
|---|---|---|
| `remote-002` | `multi_doc` | workflow completion 0.00 < 1.00 |
| `expenses-002` | `multi_doc` | groundedness 0.79 < 0.85 |
| `equipment-001` | `multi_doc` | groundedness 0.69 < 0.85 |

## Per-workflow completion

`workflow_completion_by_workflow` = `{"pto_request": 1.0, "remote_work_eligibility": 1.0}`, each over **n = 1** workflow instance (`n_scored["workflow:pto_request"] = 1`, `n_scored["workflow:remote_work_eligibility"] = 1`). The aggregate `workflow_completion` = 0.964 is over n = 28 items — `remote-002` is the single item scoring 0.

## Ablation, regenerated on the same build

`comparison.json` · `target_git_sha` `8a89310` for all three arms · dataset sha identical.

| Metric | baseline | `dense_only_k2` (Δ) | `no_structured_tools` (Δ) |
|---|---|---|---|
| Strict pass | 0.8929 | 0.9286 (**+0.0357**) | 0.7857 (**−0.1071**) |
| Workflow completion | 0.9643 | 0.9643 (0.0000) | 0.8214 (**−0.1429**) |
| Tool selection | 0.9929 | 0.9878 (−0.0051) | 0.9418 (**−0.0510**) |
| Document recall | 0.9474 | 0.9737 (+0.0263) | 0.9868 (+0.0395) |
| Citation resolvability | 1.0000 | 1.0000 (0.0000) | 0.9643 (−0.0357) |
| Argument correctness | 1.0000 | 1.0000 (0.0000) | 1.0000 (0.0000) |
| Over-refusal | 0.0000 | 0.0000 (0.0000) | 0.0000 (0.0000) |
| Groundedness / citation accuracy | 0.9633 / 0.8753 | `null` (not judged) | `null` (not judged) |

`workflow_completion_check`: baseline 0.9643, `no_structured_tools` 0.8214, **delta −0.1429**, threshold 0.25 → **`supported: false`**, `reason: null`. The design claim that removing the structured tools costs ≥ 0.25 of workflow completion is **not supported by this run**, and the check says so rather than being softened — as designed. Twelve strict-pass flips are recorded in `comparison.json` (three for `dense_only_k2`, nine for `no_structured_tools`); note that both arms *gain* `expenses-002` and `equipment-001`, the two groundedness failures, because judged clauses are vacuously true on an unjudged arm.

## Judge agreement — both figures recomputed against `r_1790074972_baseline`

| Metric | Rate | n | Subset | Selection |
|---|---|---|---|---|
| `judge_agreement_rate` | **1.000** | **8** | `seed_1729_8` | blind (`selection_disclosed: false`) |
| `judge_agreement_rate_hard` | **0.875** | **8** | `judge_lowest_8` | disclosed (`selection_disclosed: true`), labelling blind |

**Disagreements.** Seed subset: **none** — all 8 are unanimous `grounded`, so the matrix again has no discriminating cell and REPORT.md says so in the words it generates. Hard subset: **one**, `expenses-002` (reference `grounded`, judge `not_grounded` — judge groundedness 0.786, below the 0.85 binarisation threshold). The one genuinely discriminating agreement in the run is `equipment-001`: the labeller called it `not_grounded` (the answer asserts director + manager sign-off for a USD 1,200 laptop *refresh*, while the approval matrix assigns a refresh to the direct manager alone) and the judge scored it 0.688, i.e. `not_grounded` too.

Both figures are in the run file (`judge_agreement_subset` = `seed_1729_8`, `judge_agreement_subset_hard` = `judge_lowest_8`) and in `latest.json`'s notes.

**Gap 9 prose, fixed.** Each label file's `protocol.blinding` now names exactly **one** run — `r_1790074972_baseline`, deployed commit `8a89310` — and states plainly that the packet carried *that* run's own served answers; `labelled_on: "2026-09-22"` in both. REPORT.md's two protocol paragraphs (lines 126–141 region) render one run each, verified by reading the regenerated file.

*Timing claim, stated only as far as it can be shown.* The seed packet is **judge-free by construction of the builder** — `scripts/gen_label_packet.py` reads the dataset, the run file's `item_id → turn_id` and served answer, and the trace store's spans, and never reads `scores` or `verdicts`. The only timing I can evidence is file order: `packet-seed-final.md` was written at 04:25:16Z and the judged run file at 04:37:44Z (`measure-judge3.log`), so the packet predates the judged run file. The judge pass itself was already running (it started 04:10:34Z), so the blinding paragraph does **not** claim "before any judge verdict existed" — it claims what the builder guarantees plus the file order, which is what the logs support. The hard packet was necessarily built after judging (04:38:02Z), as its subset requires; its blinding paragraph says so and records that the criterion and the score ordering were withheld from the labeller (items rendered in item-id order).

**Recounted.** The seed subset `{benefits-001, benefits-002, conduct-001, expenses-001, pto-001, remote-001, remote-002, remote-003}` and the hard subset `{benefits-001, benefits-002, conduct-001, equipment-001, expenses-001, expenses-002, pto-002, travel-001}` intersect on **four of eight**: `benefits-001`, `benefits-002`, `conduct-001`, `expenses-001` — which is exactly what REPORT.md computes independently ("share 4 of 8 items"). The judge-score sentence is now **14 of the 18 answered items at 1.0** (only `equipment-001` 0.688, `expenses-002` 0.786, `travel-001` 0.917 and `pto-002` 0.950 sit below), replacing the invented "25 of 26"; the four ceiling ties that fill the hard subset are broken by item id and happen to be the four the seed draw also took.

## Dashboard-only runs — disclosure sentence, updated

Task 4's gap-24 sentence needs two corrections: `r_1790067656_baseline` **is** committed now (in `e353a3d`, as history — it is no longer the published run), and the `c427b15`-era `r_1790062696_baseline` still is **not**. Replacement text for the documentation task (`design-and-evaluation.md` §13 and/or `docs/optimization-log.md`; `NEEDS-FROM-USER.md:201,253` carries the same check):

> The published figures are quoted from `r_1790074972_baseline` alone (2026-09-22, build `8a89310`). Three further judged 28-item baseline drives against the deployed service are retained in the trace store with **no committed result file**: `r_1790062696_baseline` (2026-09-22 07:45Z, build `c427b15`, strict pass 0.964) — the diagnostic drive that exposed gap 4b, driven *before* this wave's two clarification fixes, which is why its file was not kept even though it scores higher than the published run — plus `r_1789547562_baseline` (2026-09-16 08:41Z, build `6355c41`, strict pass 0.893) and `r_1789534779_baseline` (2026-09-16 05:07Z, build `1a2a8fb`, strict pass 0.821), both of which predate the published build. Earlier published runs, including `r_1790067656_baseline` (build `e85305b`), **are** committed and are kept as history rather than as the published figure. None of the three dashboard-only runs can be reconstructed into a valid run file: `GET /api/eval/runs/{run_id}` serves the dashboard's view-model, which carries neither `dataset_sha` nor `target_git_sha`. That is why `/health.trace_store.eval_runs_imported` exceeds the committed run-file count, which is **22** after this commit.

I did not re-query `/health` for the current `eval_runs_imported` value — the call was blocked by the sandbox's credential rule — so the sentence states the direction of the gap and the verifiable committed count (22 files, `ls evaluation/results/r_*.json`) rather than a number I could not check. The documentation task should paste the live value.

## `paste_eval_numbers.py`

```
$ .venv/bin/python scripts/paste_eval_numbers.py
unchanged — the results table already matches evaluation/results/latest.json
$ .venv/bin/python scripts/paste_eval_numbers.py --check
OK — the results table matches evaluation/results/latest.json     # exit 0
```

(The paste itself was already applied to `design-and-evaluation.md` before this task; the diff on that file is the EVAL-NUMBERS block only, and it is in this commit.)

## Tests

```
.venv/bin/pytest -q -p no:cacheprovider tests/contract \
  tests/unit/test_latest_points_at_deployed.py tests/unit/test_run_provenance.py \
  tests/unit/test_strict_pass_causes.py tests/unit/test_reference_subset_deterministic.py \
  tests/unit/test_hard_case_agreement_subset.py tests/unit/test_ablation_comparability.py
619 passed in 181.80s
```

**No failing contract test**, and so nothing to list under "prose disagrees with new numbers" for the gate. That is not the same as the prose being correct — see below.

## Concerns for the documentation task (task 6)

1. **`design-and-evaluation.md` prose is stale against the new run, and no test catches it.** Per the brief I did not touch prose. Line 969's comparison row reads `Judge agreement, seed / hard | … | 0.875 (n=8) / 0.875 (n=8)` for the published column, and the §13.7 subset table at lines 1090–1091 gives `judge_agreement_rate` = **0.875** for `seed_1729_8`. Both are now wrong: the seed figure is **1.000 (n=8)**. The paragraph beneath them ("on this run it came back 0.875 with exactly **one** compared item carrying a `not_grounded`…") describes the *seed* subset and is now false of it — that description fits the **hard** subset instead, and the sentence "A subset that came back all-unanimous — as the blind one did on every earlier run —" must now include this run.
2. **Same file, same column, other metrics.** Line 959 onwards still shows groundedness 0.984, citation accuracy 0.905, document recall 0.961, workflow completion 0.893, partial match 0.798, latency p50/p95 17.6/38.7 s for the published column; the new run is 0.963 / 0.875 / 0.947 / 0.964 / 0.801 and 15.3/26.0 s. The auto-pasted EVAL-NUMBERS block above it is correct — the hand-written comparison table below it is not, and the two now contradict each other inside one document.
3. **The blinding paragraph in `design-and-evaluation.md` (around line 1080) still asserts the packet "was built by `scripts/gen_label_packet.py` while the run was still `judge_status: pending`, so no judge output existed anywhere upstream of it."** That is the claim gap 9 asks not to make beyond what the logs show. For this run the judge pass was in flight when the seed packet was built. The label files now word it correctly; this paragraph should be brought into line with them rather than the reverse.
4. **The ablation's headline claim remains unsupported** (−0.143 against a 0.25 bar) and the `no_structured_tools` arm is unjudged by design, so two of the three strict-pass failures flip to "pass" on both arms for want of a judge rather than for merit. The report already says judged metrics are baseline-only; anyone reading the flip list should be pointed at that sentence.
5. **Gap 9's mechanical binding was not implemented.** The fix text also asks for a `turn_id` (or answer-text sha) on `evaluation.schema.ReferenceLabel` plus a check that REPORT.md's rendered protocol prose equals the labels' blinding fields. `ReferenceLabel` is `extra="forbid"` with only `item_id` / `verdict` / `rationale`, and this task's steps did not include the schema change, so the binding between a label and the turn it describes is still by prose and by protocol rather than mechanically checkable. It is the remaining half of gap 9.
