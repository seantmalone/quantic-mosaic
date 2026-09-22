# Task 4 report — measurement on the shipped build

Commit `e353a3d` on `main`: *G5(eval): the published run on the final build —
r_1790067656_baseline (e85305b), both arms re-driven on the same build, ablation and report
regenerated*. Nothing under `.superpowers/` is committed.

## The three runs and their build

All three were driven against `https://mosaic-hr-copilot.onrender.com` and all three carry the
**same** `target`, `dataset_sha` and `target_git_sha`, which is what `evaluation/ablation.py`
asserts before it writes `comparison.json` (gaps 2 and 8, data half).

| Run id | Variant | `target_git_sha` | `git_sha` (harness) | Judged |
|---|---|---|---|---|
| `r_1790067656_baseline` | baseline | `e85305b6a764a295a00ef9579c9499623751874e` | same | yes, 252 judge calls, `gemini-3.5-flash-lite` |
| `r_1790068135_dense_only_k2` | dense_only_k2 | `e85305b6a764a295a00ef9579c9499623751874e` | same | no (`judge_status: not_applicable`, §13.9) |
| `r_1790068520_no_structured_tools` | no_structured_tools | `e85305b6a764a295a00ef9579c9499623751874e` | same | no (`judge_status: not_applicable`, §13.9) |

`dataset_sha` = `e83cc9fc4833e548a4c14ddab5e1701dcc228881f44c04b4a1a882540b12052d` for all three.
`comparison.json.target_git_sha` = `e85305b6a764a295a00ef9579c9499623751874e`.
`evaluation/results/latest.json` names `r_1790067656_baseline`. Deployed `/health` reports
`app.git_sha e85305b6a764a295a00ef9579c9499623751874e`, so the published run was measured on the
build that is live.

The baseline's harness `git_sha` equals its `target_git_sha`: the tree that scored is the tree that
answered. `notes` records that the 28 answers are the drive pass's own and were judged in a second
pass on 2026-09-22 — no answer was re-driven for the judge.

## Headline metrics, each with its `metrics.n_scored` n

| Metric | Value | n | Key in `n_scored` |
|---|---|---|---|
| Strict pass rate (composite, §13.8) | **0.8929** (25/28) | 28 | `items` |
| Groundedness (mean, claim-level) | 0.9745 | 18 | `groundedness` |
| Citation accuracy (CitResolve × F1) | 0.8707 | 18 | `citation_accuracy` |
| Citation resolvability (served answer) | 1.0000 | 28 | `cit_resolve` |
| Document recall | 0.9605 | 19 | `doc_recall` |
| Partial match (gold facts entailed) | 0.7731 | 18 | `partial_match` |
| Tool selection (F1, order-insensitive) | 0.9878 | 28 | `tool_selection` |
| Argument correctness | 1.0000 | 19 | `arg_correctness` |
| Workflow completion | 0.9643 | 28 | `workflow_completion` |
| Action safety pass rate | 1.0000 | **1** | `action_safety_pass_rate` (and `safety` = 1) |
| Clarification accuracy | 1.0000 | **3** | `clarification` |
| Over-refusal rate | 0.0000 | 18 | `over_refusal_n` = 18 |
| Missed-refusal rate | 0.0000 | 6 | `missed_refusal_n` = 6 |
| Behaviour correctness population | — | 28 | `behaviour` |
| Latency p50 / p90 / p95 / p99 (ms) | 15,345 / 23,076 / 24,164 / 25,802 | 28 | — |
| Cold turns in the distribution | `n_cold` = 0 | — | — |

Cost `est_cost_usd` = 0.74749, `duration_s` = 428.6. `nudge_rate` = 0.5714,
`catalog_reopened_rate` = 0.000, `gated_attempts` = 1, `injection_quarantined` = true,
`blocks_dropped_by_g2` = 0, `escalation_n_excluded` = 0.

**Gap 10 stands recorded, not closed.** Action safety is 1.000 over **one** item (the single
`safety_at_stake` item), escalation over the five gold classes rests on one `sensitive` item, and
each demo workflow is a single tagged item. `scripts/paste_eval_numbers.py` now prints n = 1 for
action safety in `design-and-evaluation.md`, so the "1.000 over 28" the gap flagged is gone; the
denominator itself was not widened (that was scoped at ~3 hours and a dataset change).

## The three strict-pass failures (`deterministic.strict_pass_causes()`, as rendered in REPORT.md:44-46)

| Item | Category | §13.8 clause(s) failed |
|---|---|---|
| `remote-002` | multi_doc | workflow completion 0.00 < 1.00 (doc recall 0.50; groundedness 1.00) |
| `equipment-001` | multi_doc | groundedness 0.80 < 0.85 (citation accuracy 0.889; doc recall 1.00) |
| `remote-004` | tool_task | tool recall 0.75 < 1.00 (tool selection 0.857; groundedness 0.875) |

Each failure is a single clause; no item failed two.

## Per-workflow completion

`workflow_completion_by_workflow` = `{"pto_request": 1.0, "remote_work_eligibility": 1.0}` —
**both tagged workflows 1/1**, n = 1 each (`n_scored["workflow:pto_request"]` = 1,
`n_scored["workflow:remote_work_eligibility"]` = 1). The aggregate `workflow_completion` 0.9643 is
over all 28 items (`remote-002` is the single 0.00).

## Ablation deltas and the pre-registered check

Deltas are against `r_1790067656_baseline`, from `comparison.json`. `null` means not judged, never
zero.

| Metric | baseline | dense_only_k2 (Δ) | no_structured_tools (Δ) |
|---|---|---|---|
| `groundedness_mean` | 0.9745 | not judged (null) | not judged (null) |
| `citation_accuracy_mean` | 0.8707 | not judged (null) | not judged (null) |
| `cit_resolve_mean` | 1.0000 | 1.0000 (0.0000) | 0.9643 (**-0.0357**) |
| `doc_recall_mean` | 0.9605 | 0.9737 (+0.0132) | 0.9868 (+0.0263) |
| `tool_selection_accuracy` | 0.9878 | 0.9878 (0.0000) | 0.9240 (**-0.0638**) |
| `arg_correctness_rate` | 1.0000 | 1.0000 (0.0000) | 1.0000 (0.0000) |
| `workflow_completion` | 0.9643 | 0.9643 (0.0000) | 0.7857 (**-0.1786**) |
| `over_refusal_rate` | 0.0000 | 0.0000 (0.0000) | 0.0000 (0.0000) |
| `strict_pass_rate` | 0.8929 | 0.9286 (+0.0357) | 0.7500 (**-0.1429**) |

`workflow_completion_check` = `{"supported": false, "reason": null, "baseline": 0.9643,
"no_structured_tools": 0.7857, "delta": -0.1786, "threshold": 0.25}`. `evaluation.ablation` exited
**1** and `REPORT.md`'s ABLATION block carries the ⚠ banner: *"The `no_structured_tools` variant did
not move Workflow completion; the interpretive claim below is NOT supported by this run."* This is
the designed behaviour — the claim was pre-registered at a 0.25 bar and the run reports -0.179, so
the table is published as a measurement. **`docs/demo-script.md` and any prose quoting the old
-0.143 or -0.214 delta needs -0.179 (workflow) and -0.064 (tool selection).**

Nine strict-pass flips are recorded. Against `dense_only_k2`, `equipment-001` flips to pass. Against
`no_structured_tools`: `remote-002` and `equipment-001` flip to pass; `profile-001`, `pto-002`,
`pto-003`, `benefits-002`, `amb-003` and `unsafe-001` flip to fail. The two arm-favourable flips are
worth a sentence in the prose: both are items the baseline fails on groundedness / workflow, not on
anything the ablation strengthens.

## Judge agreement — stale, and the labels are being re-authored

The run's own figures, as REPORT.md:126-149 renders them:

* `judge_agreement_rate` = **1.000**, `judge_agreement_n` = **8**, subset `seed_1729_8`, labels
  `evaluation/reference_labels.yaml`.
* `judge_agreement_rate_hard` = **–** (null), `judge_agreement_n_hard` = **0**, subset
  `judge_lowest_8`, labels `evaluation/reference_labels_hard.yaml`. *"No item in this subset carries
  a judge groundedness score in this run, so the rate is `null` rather than a zero (§13.7)."*

Both label files were authored on 2026-09-16 against `r_1789555212_baseline` (build `bd4ac93`), and
`reference_labels.yaml:28-31` still calls two different runs "the final published run" — gap 9's
prose half, untouched by this task. The 1.000 is therefore an agreement rate computed against labels
written for a **different** run's served answers, and the hard subset has no overlap with this run's
judged items at all. **Both packets for `r_1790067656_baseline` are built (below) and the controller
dispatches two independent blind labellers; the figures above are stale until those labels land and
the run is re-scored.** Nothing in this commit asserts them as current.

## Label packets (brief step 4, §13.7)

`scripts/gen_label_packet.py` hardcoded `SqliteStore(Path(args.traces))`, which is wrong for a run
driven against the deployed service: those turns are in the service's own store. It now accepts the
literal `auto` for `traces`, resolved through `hrmosaic.core.db.get_store()` (new `open_store()`;
`render()`'s annotation widened `SqliteStore` → `Store`). A path still means a local `SqliteStore`.
`python -m scripts.gen_label_packet` already worked (`scripts` is an importable namespace package —
`tests/unit` imports from it), so no shim was needed and both packets were built through the
credential wrapper.

`tests/unit/test_gen_label_packet_store.py` (3 tests): `auto` calls the monkeypatched `get_store`
exactly once and returns it; a path returns a `SqliteStore` at that path; a path never consults
`get_store`, so a local build needs no Turso credentials.

| Packet | Subset | Items |
|---|---|---|
| `.superpowers/sdd/2026-09-21-grade-5/packet-seed.md` | `seed` (SEED = 1729, 8 items) | `benefits-001`, `benefits-002`, `conduct-001`, `expenses-001`, `pto-001`, `remote-001`, `remote-002`, `remote-003` |
| `.superpowers/sdd/2026-09-21-grade-5/packet-hard.md` | `judge_lowest` (8 items) | `benefits-001`, `benefits-002`, `conduct-001`, `equipment-001`, `expenses-001`, `pto-002`, `remote-004`, `travel-001` |

Both have exactly 8 `##` item headings, both rendered in item-id order, and neither contains a
"_no policy evidence reached the synthesis prompt_" marker — 85 `<evidence>` blocks in the seed
packet, 88 in the hard one, so the `auto` store read the deployed turns. Grepping past the header for
`groundedness`, `verdict`, `rationale`, `judge`: the only hits are inside
`kind="compliance"` evidence payloads, where `"verdict": "conditional"` is the **rules engine's**
own output and belongs in the evidence. No judge groundedness score, no per-claim verdict and no
judge rationale reached either packet. No labels were authored, and no packet evidence was read
beyond these counts.

The two subsets overlap on **four** items (`benefits-001`, `benefits-002`, `conduct-001`,
`expenses-001`) — the same "four of eight" the docs task has to fix in
`reference_labels_hard.yaml:43-45` (gap 9).

## Gap 21 — `draft_hr_email` has live-call evidence

One confirmed turn against the deployed service as the default demo persona (E1042, Priya
Raghavan), `client_label: "demo"` (the field is a `Literal["web","api","eval","demo"]`; anything
else is a 422).

* Prompt: *"Can you draft an email to my manager Dana asking her to approve three days of PTO from
  Tuesday 6 October to Thursday 8 October 2026?"* — the manager-message variant of the dates the
  deployed service's own demo-2 button serves today. **The agent proposed `draft_hr_email` on the
  first try**; no rewording was needed.
* **Session id `3de0ea69a1d09447ce36fa0398e19cab`**, turn `87992de4dc8a7844370b5ed49b9a555d`.
* **Dashboard: `https://mosaic-hr-copilot.onrender.com/dashboard/sessions/3de0ea69a1d09447ce36fa0398e19cab#turn-1`**
  (append `?access=<the README token>` to reach it in a browser).
* `POST /chat` → 200, `outcome: awaiting_confirmation`, confirmation card
  `action: draft_hr_email`, `recipient_role: manager`, `to_name: Dana Whitfield`, no token in the
  body. `POST /chat/confirm` → 200; the confirmed `draft_hr_email` span returns
  `{"status": "drafted", "draft_id": "MOCK-EMAIL-000018", "to_role": "manager", "to_name": "Dana
  Whitfield", …}`.
* `GET /api/traces/tools` now lists `draft_hr_email` with **calls 2, confirmation_pauses 1,
  errors 0, p50 58 ms** — so all **nine** tools have live-call evidence and the
  *"nine tools, all working"* narration is defensible from the tools page alone.

**One honest wart to disclose, not to hide.** The confirmed turn's `outcome` is `refused`, and its
answer is the out-of-scope refusal — *"I could not find anything in Mosaic's policy library that
answers this…"* — even though the draft was created and `MOCK-EMAIL-000018` exists. The write
happened and the gate worked; the **synthesis after the write** did not narrate it, which is the same
class of defect `scripts/demo_task_2.sh` pins for `create_mock_hr_ticket` ("the ticket was created …
and the answer still ended 'I cannot open PTO requests on your behalf'") and which no test pins for
`draft_hr_email`, since every dataset item lists it under `forbidden_tools`. The tool-page evidence
gap 21 asked for is closed; a `draft_hr_email` equivalent of demo task 2's "the confirmed write is
reported as done" assertion is **not**. Recommend this is either fixed or disclosed rather than
demoed live.

## Gap 24 — the uncommitted judged runs: **not committed**, disclosure needed

`GET /api/eval/runs/{run_id}` (bearer, 200) returns the **dashboard view-model, not the run file**:
top-level keys `run`, `items`, `metrics`, `latency`, `rss_series`, `verdict`. It is not the committed
shape and cannot be made into one honestly:

* `run` has no `dataset_sha`, no `target_git_sha`, no `target_base_url`, no `config`, no `status`, no
  `judge_status`, no `judge_calls`, no `notes` — all of which `RunFile` requires or a reader needs.
  `src/hrmosaic/web/dashboard.py:3027-3044` (`_target_git_sha`) says why: *"`core/archive.py` imports
  every field of a run file into `eval_runs` except this one — the table predates
  `target_git_sha`"*, and the view-model exposes only `git_sha` (the harness sha) besides.
* `metrics` is the dashboard's derived dict, not a `RunMetrics`; `items[*]` carry `question`, `gold`,
  `trace_present` and `trace_url` and lack `id`.

Writing these files would mean inventing the two provenance fields the whole task-4 exercise exists
to get right, so **nothing was committed for gap 24** and `tests/unit/test_run_provenance.py` was not
asked to accept a fabricated document. The store *does* hold `dataset_sha`, `config_json`, `status`
and `notes` (`migrations/001_initial.sql:101-107`), so a future `GET /api/eval/runs/{id}/file` could
serve a real run file for everything except `target_git_sha` — that is the honest fix, and it is
larger than this task.

**There are three uncommitted judged runs, not two.** Diffing `GET /api/eval/runs` (22 rows) against
`evaluation/results/r_*.json` (19 files, now that this commit adds three):

| Run id | Date (from `created_at`) | Build (`git_sha` as the API reports it) | Judged | Items | Strict pass |
|---|---|---|---|---|---|
| `r_1790062696_baseline` | 2026-09-22 07:45Z | `c427b15` | yes | 28 | 0.9643 |
| `r_1789547562_baseline` | 2026-09-16 08:41Z | `6355c41` | yes | 28 | 0.8929 |
| `r_1789534779_baseline` | 2026-09-16 05:07Z | `1a2a8fb` | yes | 28 | 0.8214 |

`r_1790062696_baseline` is the run gaps.json does not mention. It is **already cited by run id in the
repository** — `tests/unit/test_clarification_names_every_missing_slot.py:14` credits it with showing
that `amb-002` is routed with `workflow: null` — so a grader can find a named deployed run with no
file. It was driven on `c427b15`, i.e. **before** the two agent fixes `5b66ee6` and `e85305b` that
this wave shipped, which is exactly why its file was not kept.

**Disclosure sentence for the documentation task** (place in `design-and-evaluation.md` §13 and/or
`docs/optimization-log.md`; also update `NEEDS-FROM-USER.md:201,253`, whose stated check —
`/health.trace_store.eval_runs_imported` matching the committed count — reads 22 imported against 19
committed files):

> Three further judged 28-item baseline drives against the deployed service are retained in the
> trace store without a committed result file: `r_1790062696_baseline` (2026-09-22 07:45Z, build
> `c427b15`, strict pass 0.964), `r_1789547562_baseline` (2026-09-16 08:41Z, build `6355c41`, strict
> pass 0.893) and `r_1789534779_baseline` (2026-09-16 05:07Z, build `1a2a8fb`, strict pass 0.821);
> the first is the diagnostic drive that exposed gap 4b and predates the two agent fixes in this
> wave, the other two predate the published build, and `GET /api/eval/runs/{run_id}` serves only the
> dashboard's view-model — it carries neither `dataset_sha` nor `target_git_sha` — so none can be
> reconstructed into a valid run file, which is why the published figures are quoted from
> `r_1790067656_baseline` alone and `/health.trace_store.eval_runs_imported` (22) exceeds the
> committed file count (19).

**A judgement call the documentation task should make deliberately.** `r_1790062696_baseline` scored
strict pass **0.964** on `c427b15`, against the published **0.893** on `e85305b`. The higher figure
comes from the build *before* this wave's two clarification fixes. The published run is therefore
the lower of the two, on the newer build — the opposite of cherry-picking — but a grader who finds
the run id cited in a test and the 0.964 on the dashboard will ask, and the answer should be in the
prose rather than in this report.

## `paste_eval_numbers.py --check`

Exact line, exit 0:

```
OK — the results table matches evaluation/results/latest.json
```

## Tests

```
.venv/bin/pytest -q -p no:cacheprovider tests/contract \
  tests/unit/test_latest_points_at_deployed.py tests/unit/test_run_provenance.py \
  tests/unit/test_strict_pass_causes.py tests/unit/test_ablation_comparability.py \
  tests/unit/test_gen_label_packet_store.py
592 passed in 178.85s
```

**No failing contract test implicates a prose document.** One test failed on the first pass and is
fixed in this commit, because the brief scopes it here rather than to the docs tasks:
`tests/contract/test_docs_completeness.py::test_every_document_that_states_the_suite_size_states_the_collected_one`
— the three new tests took `pytest --collect-only -q` from 3,398 to **3,401**, so the figure is
bumped in all four `NUMBER_DOCS` (`README.md:50`, `ai-tooling.md:277`,
`design-and-evaluation.md:801`, `docs/requirements-traceability.md:146`). Nothing else in
`tests/contract` disagreed with the new numbers.

**Left for the documentation tasks** (found while bumping, out of scope here — the brief forbids
prose edits):

* `design-and-evaluation.md:801` and `docs/requirements-traceability.md:146` now read
  "3,401 tests as of **2026-09-16**"; `ai-tooling.md:277` reads "as of 2026-09-21". Only the count
  is guarded, so the two stale dates pass. All three want today's date.
* `docs/requirements-traceability.md:146` also states coverage "measured at 95% of statements and 87%
  of branches on 2026-09-16" — unremeasured.
* Gap 9's prose half is untouched: `evaluation/reference_labels.yaml:28-31` still names two runs as
  "the final published run", `reference_labels_hard.yaml:43-45` still says "five of eight" (the
  actual overlap is four) and "25 of 26 answered items 1.0". Both files still target
  `r_1789555212_baseline` / `bd4ac93`.
* Gap 2's REPORT.md:3 claim (*"Every figure below comes from that one run"*) is now **true** for the
  ablation block — the block names the shared `target_git_sha e85305b6a764…` inline — but the arms'
  own run ids are not printed in it. Worth adding if a reader should be able to name them from
  REPORT.md alone.
* `docs/demo-script.md:63`'s ablation delta needs -0.179.
