# Task 6b — design-and-evaluation.md and docs/optimization-log.md

**Commit `cbbd3cb`** on `main`: `G5(docs-design): the design document and the optimization log publish the run on the shipped build`. Two paths, explicitly added: `design-and-evaluation.md`, `docs/optimization-log.md`. Trailer `Co-Authored-By: Claude Fable 5.1`, no `Claude-Session`. The EVAL-NUMBERS block was not touched; `--check` exits 0.

## Per gap, what changed (line numbers are post-commit)

### Gap 1 — the design doc publishes the run on the shipped build
- `:19-21` header: published run is `r_1790074972_baseline`, commit `8a89310`, judged 2026-09-22.
- `:22-26` "A note on honesty": "three earlier columns" → "five earlier columns".
- `:982-1006` the history table: `### Reading the four columns` → `### Reading the six columns`, two new columns — `r_1789555212_baseline` / `bd4ac93` (W8–W10) and `r_1790074972_baseline` / `8a89310` (published). Every cell from the run files: strict 0.893/0.893, groundedness 0.975/0.963, citation 0.883/0.875, partial match 0.796/0.801, doc recall 0.921/0.947, tool selection 0.981/0.993, workflow 0.964/0.964, nudge 0.571/0.571, p50 19.2/15.3 s, p95 35.7/26.0 s, agreement seed-hard 1.000-0.875 both, cost $0.72/$0.77. New rows: clarification accuracy and action-safety `n`. Column 1's seed agreement is `n=7` as the run file records.
- `:1055-1086` two new paragraphs: **column 4 → 5** (the W1–W10 waves; `remote-004`'s end state met, the confirmation-card miss closed in W10, `remote-003` the one workflow 0.00 left, the judged drift, the clarification regression, no ablation delta) and **column 5 → 6** (this wave: clarification 1.000, the three write-path repairs, the arms re-driven, the latency read as spread not win).
- `:1272-1276` ablation arm ids → `r_1790074972_baseline`, `r_1790075436_dense_only_k2`, `r_1790075830_no_structured_tools`, all on `8a89310`.

### Gap 2 — the ablation disclosure
- `:1278-1288` the ablation table regenerated from `comparison.json` (baseline 0.963 / 0.875 / 1.000 / 0.947 / 0.993 / 1.000 / 0.964 / 0.000 / 0.893; `dense_only_k2` 1.000 / 0.974 / 0.988 / 1.000 / 0.964 / 0.000 / 0.929; `no_structured_tools` 0.964 / 0.987 / 0.942 / 1.000 / 0.821 / 0.000 / 0.786).
- `:1290-1297` banner: observed 0.964 vs 0.821, delta −0.143 against the 0.25 bar, `supported: false`; five deltas side by side.
- `:1272-1276` the `target_git_sha` assertion in `evaluation/ablation.py` is named as the guard added after the mixed-build block was found.
- `:1311-1319` the twelve flips, and the two (`expenses-002`, `equipment-001`) that are absences of a judge rather than behaviour — which is the whole of `dense_only_k2`'s 0.929.
- `:1096-1104` disclosure 2 of three: column 5's arms were never driven.

### Gap 3 — Known limitations rewritten from the published run
- `:1421-1490`. Eleven items, all read off `r_1790074972_baseline`: (1) the three composite failures; (2) the corpus/dataset conflict behind `equipment-001`; (3) `next_steps` not grounded against the evidence set; (4) the single-item denominators; (5) a metric can regress without failing the composite; (6) judge validation rests on one discriminating cell; (7) 28 items and the one-item margins, with the latency caveat; (8) the arm64 memory gate; (9) prompt caching; (10) cold start — and that none of the three probes is on the published build (`n_cold` = 0); (11) the ablation.
- `:1478-1490` a closing paragraph: what closed and when — confirmation-card miss (W10, and that `unsafe-001` still failed on tool recall 0.75 on 2026-09-16), `remote-003`'s declined lookup (G5 gap 11 profile debt; tool recall 1.00 and passing, and no item in the run scores below 1.00 on tool recall), clarification 0.333 (G5 Tasks 1/1b), the mixed-build ablation block, and the two write-path defects.
- `:1118-1150` the strict-pass causes table replaced with `remote-002` (workflow 0.00), `expenses-002` (groundedness 0.79), `equipment-001` (0.69), each with a paragraph. `expenses-002`'s 0.79 is explained by the −0.5 `contradicted` weight (`evaluation/judges.py:98`), six supported of seven → 5.5/7.

### Gap 4b — the clarification disclosure
- History-table row `:991` (0.667 / 1.000 / 1.000 / 0.667 / 0.333 / 1.000, n = 3 in every column), the column 4 → 5 and 5 → 6 paragraphs, limitation 5, and the closure paragraph.
- `docs/optimization-log.md:577` the 2026-09-16 published-measurements table gains `| Clarification accuracy (n = 3) | 0.667 | 0.333 |`, and `:596-600` a paragraph saying why it was missing.

### Gap 10 — real n everywhere
- History table row `:993` action safety with its n (26 / 26 / 26 / 28 / **1** / **1**); `:1015-1024` a paragraph on why the denominator narrowed (quoting `evaluation/runner.py`'s own reason), that clarification is n = 3 and escalation `sens-001` alone, and that `workflow_completion_by_workflow` is two single-item indicators; limitation 4. No "28" is left beside a safety figure.

### Gap 16 — the MCP claims
- `:348-354` discovery step 5: both transports populate `structured_content` in `mcp` 2.2.0 (measured 2026-09-09, `mcp/README.md`), the text fallback kept and tested.
- `:398-404` error semantics: `isError: true` with the validator's text, **no `-32602` on the wire**, caught in `MCPServer._handle_call_tool`, orchestrator keys on `is_error`.
- `:541-545` and `:1547-1557` the server-side validation claim softened to the signature-derived model the committed schemas are generated from, with the root `oneOf` published for clients and enforced in `get_policy_section`'s handler (neither → `INVALID_ARGUMENTS`; both deliberately accepted, `chunk_id` wins) — and the note that `evaluation/deterministic.py`'s `tool_input_schema` validates against the committed file, so it would score a both-selectors call incorrect.

### Gap 27 — stale figures in my two files
- `:177` fact count 57 → **58** (`.venv/bin/python scripts/check_facts.py` → "14 documents · 58 facts · 7 rule scenarios · 34 requirements").
- `:150` corpus words **31,007** verified unchanged (`scripts/corpus_stats.py` → "14 files · 64.2 pages · 31,007 words").
- `:834` suite line: number kept at 3,410, as-of date 2026-09-16 → **2026-09-22** (`.venv/bin/pytest --collect-only -q -m ""` → `3410 tests collected`).

### Task 1c reviewer's note — the performed-write exemption
- `:102` the §9.1 step list, step 3: "G1 evidence gate over the accumulated chunk set — exempt if this turn performed the write".
- `:649` the G1 row: the one exemption, G1 still runs once and records its measured figures with the reason prefixed `PERFORMED_WRITE`.
- `:657-667` a paragraph: `grounded_by_write` set only where `outcome.performed_write()` finds a performed write, the live `MOCK-EMAIL-000018` turn refused at `candidates: 0`, the measured clause kept behind the prefix, and that a cancelled or failed write is **not** exempt.

### Gap 19 — the confirmation-refusal reasons
- `:669-677` one paragraph where the refusal reasons are listed: `NO_EVIDENCE`/`WEAK_EVIDENCE` → the searched-the-library sentence, `OUT_OF_SCOPE` → the boundary alone, `CONFIRMATION_INVALID`/`CONFIRMATION_MISSING` → `CONFIRMATION_REFUSAL` ("nothing was created or sent"), and what they fell through to before.

### Gap 24 — the dashboard-only runs
- `:1152-1170` "Every judged drive of this dataset, and which one is published": the three 2026-09-22 drives with builds and figures, why the lowest-scoring is published, the three trace-store-only runs (`r_1790062696` `82994ce`/0.964, `r_1789547562` `6355c41`/0.893, `r_1789534779` `1a2a8fb`/0.821), why none can be reconstructed, and the **22** committed run files. `82994ce` is used for the diagnostic drive's build with the note that its successors to `c427b15` are documentation-only (progress.md says `82994ce`; task-5-report says `c427b15` — same app code).

### Judge methodology, brought into line with the re-authored labels (task-5 concerns 1 and 3)
- `:1199-1213` the blinding paragraph: the builder guarantee stated, the "`judge_status: pending`, no judge output upstream" wording explicitly **withdrawn**, the 04:25:16Z / 04:37:44Z file order given, and the hard packet's necessary ordering.
- `:1215-1250` subset table seed **1.000** / hard **0.875**, the no-discriminating-cell reading, `expenses-002` as the one disagreement, `equipment-001` as the one discriminating agreement, the four shared items, and "14 of the 18 judged items at exactly 1.0 (the other four are 0.950, 0.917, 0.786, 0.688)".

### docs/optimization-log.md — the wave's section
- `:615-757` `## 2026-09-21 to 2026-09-22 — The grade-and-fix pass…`: question / evidence (the 82-agent grading, band 4, 27 gaps, the committed grade card, the four caps) / decision / the code changes that could move a metric / the three drives table (`r_1790062696` `82994ce` 0.964-0.667-1.000, `r_1790067656` `e85305b` 0.893-1.000-0.964, `r_1790074972` `8a89310` 0.893-1.000-0.964) / why the highest-scoring drive is not published / the re-driven ablation with deltas / cost ($2.19 + $2.24 agent spend, 252 and 268 judge calls at ≈$0.16–0.18, ≈$5 total) / the published-measurements table beside the `r_1789555212` column / reading it / what we did not get.

## Verification
```
.venv/bin/python scripts/paste_eval_numbers.py --check
OK — the results table matches evaluation/results/latest.json      # exit 0
.venv/bin/pytest -q -p no:cacheprovider tests/contract
554 passed in 177.42s
```
Markdown table column counts checked programmatically across both files: no mismatched rows.

## Concerns
1. **Gap 9's mechanical half is still open** (a `turn_id`/answer-sha binding on `ReferenceLabel`): the design doc's blinding prose now matches the label files, but the binding is still by prose and protocol. Task 5b owns it.
2. **`equipment-001` is a live corpus/dataset conflict that documentation cannot close.** `equipment-and-asset` puts the USD 500 director threshold under *Requesting Additional Equipment* and makes a 36-month refresh an automatic ticket, `manager-approval-matrix` routes an early laptop refresh to the direct manager alone, and the dataset's `gold_answer_short` conflates them. I documented it as a limitation rather than editing the gold answer; a reviewer may reasonably want the corpus fixed and the item re-driven.
3. **The diagnostic drive's build sha is recorded two ways** in the wave's own artifacts (`82994ce` in progress.md, `c427b15` in task-5-report.md). I used `82994ce` with a note that the commits between are documentation-only. If 6a's `deployed.md`/`NEEDS-FROM-USER.md` text says `c427b15`, one of the two should be aligned.
4. **`/health.trace_store.eval_runs_imported` is stated as a direction, not a number** (it exceeds the 22 committed run files). Task 5 could not query `/health`; if 6a pastes the live value, the design doc's sentence could carry it too.
5. **The latency improvement is framed as drive-to-drive spread, not a win** (p50 19.2 → 15.3 s, p95 35.7 → 26.0 s, nothing in the wave targeted latency). If anyone would rather claim it, the claim needs a cause this wave can point at; I could not find one.
6. **Three prose figures in my files trace to `.superpowers/` artifacts rather than committed ones**: the diagnostic drive's metrics (progress.md), the 04:25:16Z / 04:37:44Z packet timings (`measure-judge3.log`), and the two uncommitted 2026-09-16 runs' strict-pass figures (task-5-report.md). The directory is git-ignored, so a reader cannot check them; the grade card and gaps json are committed under `docs/evidence/`, the rest is not.

---

## Fix round 1 — commit `e947ecd`

`G5(docs-design): fix round 1 — four sentences held to the artifacts they cite`. Two files, explicitly added. HEAD was `f1dcb34`; Task 5b's suite bump to **3,415** at `:834` was left untouched.

**IMPORTANT 1 (verified, fixed).** `comparison.json` `flips` records `{item_id: remote-002, variant: no_structured_tools, baseline_passed: false, variant_passed: true}`, and `r_1790075830_no_structured_tools.json` gives that item workflow 1.0, doc recall 1.0, tool recall/precision 1.0. `:1324-1333`: "Two of those flips are an artefact" → "**Two items across four of those flips**", `remote-002` named as a third and genuinely real gain (more searching met the three-document end state), and the closing sentence narrowed to "Every **other** `no_structured_tools` flip is a pass that becomes a failure". Arithmetic checks: 25 baseline passes − 6 losses + 3 gains = 22 = 0.786.

**IMPORTANT 2 (verified, fixed).** `orchestrator.py:1131-1134` (step-0 pre-filter) and `:1168` (router `decision.out_of_scope`) both call `_refuse(turn, g1.OUT_OF_SCOPE, …)`, which calls `g1.refusal()` — copy only; the span is emitted by `g1.check()` alone (`g1.py:191-212`). `:656-659` now reads "**G1 decides every turn that reaches the gate — two refusals are decided before it, and one kind of turn it measures without deciding**", naming both pre-gate refusals and that neither emits a `guardrail` span.

**IMPORTANT 3 (verified, fixed).** `r_1790067656_baseline` p95 = 24,164 ms = 24.2 s, below the published run's 26.0 s. `:1088-1091`: "**The p50 is the lowest of the six published columns**" with p95 given and the e85305b figure named as the project low.

**IMPORTANT 4 (verified, fixed).** `:1143-1145`: "missed it on both **post-fix (committed)** 2026-09-22 drives — the uncommitted diagnostic drive that morning scored it 1.00".

**Minors.** `:985` "sixth judged" → "sixth published measurement". `:666-668` the exemption quotes the constant's value (*"the write this turn performed is the evidence for the answer: …"*, `g1.PERFORMED_WRITE`) instead of the token. `:1120-1123` keeps "six clauses" — `evaluation/runner.py:1354` generates that wording into `REPORT.md:40` — with a note that the tool clause fails two ways so `strict_pass_causes()` runs seven checks over those six; the other three "six clauses" mentions (`:947`, `:1461`) stay consistent with the generator. `:1134-1136` names the actual clauses (tool recall, forbidden tool, `blocks_dropped_by_g2`, action safety, behaviour) and excepts `remote-002`'s workflow clause instead of inventing "argument" and "citation-resolvability" clauses.

`docs/optimization-log.md:707-711` gains the `remote-002` gain beside the two judged-clause artefacts; nothing else in the log repeated the four false sentences.

```
.venv/bin/python scripts/paste_eval_numbers.py --check   → OK (exit 0)
.venv/bin/pytest -q -p no:cacheprovider tests/contract   → 555 passed in 173.68s
```
Markdown table column counts re-checked: no mismatched rows.
