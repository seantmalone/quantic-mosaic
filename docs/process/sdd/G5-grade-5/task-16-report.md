# Task 16 — round-3 documentation pass

**Commit `240c388`** on `main`: `G5c(docs): the graded documents publish the round-3 run on the shipped
build, and the falsifiable sentences are corrected`. Trailer `Co-Authored-By: Claude Fable 5.1`, no
`Claude-Session`. 18 staged paths (16 modified, 2 added). Working tree clean afterwards.

**Gate commands.**

```
$ .venv/bin/python scripts/paste_eval_numbers.py --check
OK — the results table matches evaluation/results/latest.json            # exit 0
$ make lint
All checks passed!  ·  322 files already formatted
$ .venv/bin/pytest -q -p no:cacheprovider tests/contract
561 passed in 155.91s                                                    # 0 skipped
$ .venv/bin/pytest -q -p no:cacheprovider tests/contract/test_published_run_commands.py
9 passed                       # test_the_application_tree_has_not_moved_since_the_measured_build PASSES
```

Round 2 left that file at **560 passed / 1 skipped**; the skip is gone because README now makes the
provenance claim again. Verified independently at HEAD: the published pathspec prints nothing.

---

## Prerequisite verification

* `git diff --stat 34d50fb..HEAD -- src mcp/tools mcp/server_entrypoint.py mcp/run_stdio.sh
  mcp/run_http.sh corpus ':!corpus/README.md' data/index/chunks.manifest.jsonl Dockerfile render.yaml
  requirements.txt` → **EMPTY**, both before the commit and after it.
* `.venv/bin/pytest --collect-only -q -m ""` → **3,469 tests collected**. Item E is a no-op: all five
  documents already state 3,469. Nothing bumped.
* `make coverage` run **once** (exit 0, ~7 min): `coverage.xml` header reads `lines-valid="10359"
  lines-covered="9886" line-rate="0.9543" branches-valid="2530" branches-covered="2233"
  branch-rate="0.8826"`. Truncated the way `coverage report` prints and the contract test asserts:
  **95 % statements, 88 % branches, over 10,359 statements, 94 % combined**. Only the statement count
  and the date moved (10,298 → 10,359; 2026-09-22 → 2026-09-23).
* Live `GET /health` read 2026-09-23 03:23Z: `app.git_sha 34d50fb…`, 9 tools, 14 docs / 205 chunks,
  `trace_store` `{turso, reachable true, session_count 951, span_count 22928, eval_runs_imported 32}`,
  `degradations []`.

---

## A — every document that names the published run or its figures

**`README.md`**
* `:269-272` — published run block → `r_1790130220_baseline` (2026-09-23), 273 judge calls, build
  `34d50fb`.
* `:274-289` — the interim re-measure notice replaced by the restored provenance claim (item B below).
* `:311-320` — before/after table: run id, groundedness 0.984 (n = 19), citation accuracy 0.873 (n = 19),
  document recall 0.974 (n = 19), tool selection 0.993, latency 13.8 s / 27.9 s.
* `:322-329` — **the two judge-agreement rows are removed from that table** and replaced by a paragraph
  explaining why they cannot be a before/after pair (item C rank 27).
* `:337-345` — `pto_request` 1.00 → **0.67** with `unsafe-001` named as the missing third; the "blind seed
  subset came back unanimous" sentence replaced by the `expenses-001` disagreement; `expenses-002`'s judge
  score 0.78 → 0.79.
* `:347-357` — strict-pass causes rebuilt from the three round-3 causes, with the explicit "every one of
  the 30 items scores tool recall 1.00" statement.
* `:359-372` — ablation paragraph: arms on `34d50fb`, boundary-level withholding named, **0.200** of
  workflow completion, `dense_only_k2` 0.900 / 0.933, **nine** flips not ten, and the now-false
  `unsafe-001`-passes-on-`dense_only_k2` sentence deleted.
* `:109` — the pinned-evidence build chain extended to `34d50fb` (item C rank 25's class).
* `:74-75` — coverage figures (item F).

**`design-and-evaluation.md`** — the largest edit; by region:
* `:18-20` intro run/build/date. `:1143-1152` the cold paragraph rewritten for `n_cold = 0` (it described
  round 2's three young-process turns as this run's).
* `:1180-1216` the history table **gains an eighth column** (`Published — after round 3`,
  `r_1790130220_baseline`, `34d50fb`); heading and lede "seven" → "eight"; column 7 relabelled
  "After round 2"; the p50 bold moved off column 6 and the column-5→6 prose's "lowest of the seven
  published columns" corrected to "lowest of the six columns published at the time".
* `:1217-1236` the widened-denominator paragraph: the action-safety population now names G5c's two extra
  membership clauses; `workflow_completion_by_workflow` `pto_request` 1.00 → **0.67**.
* `:1337-1366` a **new column 7 → 8 paragraph**: the four application fixes, the two metrics that move up,
  the changed failing clauses, the off-diagonal cell, the latency low, the blind-subset movement.
* `:1372-1383` strict-pass causes table rebuilt; the "five-class behaviour matrix is diagonal" sentence
  corrected.
* `:1385-1455` the three per-item narratives rewritten (`expenses-002`, `remote-004`, `unsafe-001`).
* `:1497-1520` the drive ledger: six drives over three rounds, the published run, run-file count 25 → **28**
  and `eval_runs_imported` **32**.
* `:1470-1520` §13.7 judge methodology — see item C/D below.
* `:1588-1625` the two-subset table (seed **0.875**, hard subset membership with `travel-001` for
  `remote-004`), the disagreement bullets re-ordered and re-scored, the overlap paragraph.
* `:1650-1712` the ablation section: run ids, build, metric table, warning block.
* `:1727-1740` flips **ten → nine**.
* `:1833-1980` *Known limitations* rebuilt (see item C/D).
* `:2155-2165` the `dense_only_k2` design-justification paragraph re-derived from the new arm.

**`deployed.md`** — `:22` and `:23` provenance ledger rows; `:50` the published run's two shas; `:68-69`
the run-history table **gains the `r_1790130220_baseline` row** and marks `r_1790110325_baseline`
superseded; `:72` the run-id/`created_at` instants; `:81-88` the `/health` reading paragraph re-taken at
2026-09-23 03:23Z; `:97-115` the provenance command, its base and its check date; `:488` the cost row.

**`ai-tooling.md`** — `:143` (the round-2 sentence, which a global replace had made wrong, restored to
`r_1790110325_baseline`/`80a5a71`), `:145-158` a **new round-3 paragraph** in §8 (brief: 37 gaps, three of
the four capping claims were code not prose, code-first/documents-last ordering, the lesson), `:319` the
published run and build.

**`CHANGELOG.md`** — two appended `2026-09-23 — G5c` entries: one naming the five commits
(`git log --oneline 39dc61c..HEAD` = `7919e94`, `6a4821a`, `43da563`, `34d50fb`, `50c435f`) and what each
did, one publishing the run, the agreement figures, the ablation, the restored provenance command, the
re-derived cost row and the suite/coverage figures.

**`NEEDS-FROM-USER.md`** — `:212` the imported-vs-committed reading re-taken (**32 against 28**); `:267`
the published-run row.

**`docs/demo-script.md`** — `:60` and `:69` the warm-up checks; `:85` the evaluation segment (run id, build,
all seven metric tiles with their `n`, the `expenses-002` Verdicts disclosure re-described as seven claims
with one `contradicted` at 0.79, the Compare tab's build, **Delta −20.0 %**); `:80` item C rank 13; `:83`
the cold beat for `n_cold = 0`; `:84` the `paths-ignore` sentence; `:155-166` the closing narration's
failing-item list and ablation figures; `:204` and `:282` the two dataset-twin references; `:330-340`
item C rank 7.

**`docs/pre-submission-checklist.md`** — `:25-37` the lede gains the round-3 grade and its outcome;
`:47-62` the published-run box (run, build, date, restored command); `:72` 266 → 273 judge calls; `:104`
item C rank 8.

**`docs/requirements-traceability.md`** — `:5` the banner build/date; **RUBRIC5.1** rewritten (figures,
restored command, three failing clauses, the tool-recall statement); **DOCS.10** the published run id;
**R8.2** the coverage date; **PD.4** and **R7.4** the cost figures; **DEMO.2 / DEMO.5 / DEMO.7** item C
rank 8.

**`docs/optimization-log.md`** — a **new dated `## 2026-09-23 — Round 3` section** (~85 lines) carrying
the question/evidence/decision, the four ranked claims that capped the round, what shipped in the build,
the one drive, the round-2-beside-round-3 measurements table, the reading, the agreement figures, the
ablation with all nine committed sweeps, cost and wall clock, and "what we still did not get". Plus the
round-2 entry's published-measurements heading and table row marked superseded.

**`docs/evidence/README.md`** — `:7-12` the header paragraph re-pointed at `34d50fb` /
`r_1790130220_baseline` with the correct drive instants and both superseded builds named; `:54` the
`final-2026-09-16/` row's "run published now"; `:88` the screen-id count.

---

## B — the provenance claim, restored

I read `tests/contract/test_published_run_commands.py` first and generated the expected string from the
test's own `published_command("34d50fb")` rather than typing it, so the match is exact:

```
git diff --stat 34d50fb..HEAD -- src mcp/tools mcp/server_entrypoint.py mcp/run_stdio.sh mcp/run_http.sh corpus ':!corpus/README.md' data/index/chunks.manifest.jsonl Dockerfile render.yaml requirements.txt
```

* `README.md:274-289` — the withdrawal notice is gone (the test's `RE_MEASURE_NOTICE`, *"the application
  tree has changed since"*, appears nowhere in README: `grep` returns nothing), replaced by the dated
  present-tense claim with the command in a fenced block and the sentence that it prints nothing.
* The same command and base in `deployed.md:97-102` (wrapped with `\` continuations — the test folds
  them), `docs/pre-submission-checklist.md:55-58`, `docs/requirements-traceability.md` RUBRIC5.1 and
  `CHANGELOG.md`'s G5c entry. The test's `stale` assertion over all five passes.
* **`test_the_application_tree_has_not_moved_since_the_measured_build` runs and PASSES** (confirmed by
  running it alone: `1 passed`, not skipped).

---

## C — false or contradictory claims from the third grade

| Rank | What I did |
|---|---|
| **2** | **Verified per item first.** Every one of the 30 items in `r_1790130220_baseline` scores `tool_recall` 1.00 (`remote-004` and `unsafe-001` both moved 0.75 → 1.00), so the sentence is **now true** — I kept it and said so explicitly, with the disclosure that it was made one round too early (`design-and-evaluation.md:1976-1979`). The second clause in that paragraph — `unsafe-001` "passes every clause it defines" — is **false** and was rewritten: the item is back on the failing list for a different reason (`:1970-1976`). The same fact is stated positively in four other places (README, REPORT-derived prose, CHANGELOG, optimization log). |
| **5** | Recomputed every committed sweep from the run files: −0.192, −0.154, −0.192, **−0.231**, −0.143, −0.179, −0.143, −0.167, **−0.200** — nine, not six. The superlative is dropped from `design-and-evaluation.md`'s disclosure paragraph and its ablation warning block, both of which now print the full list and say the largest is −0.231 and this run's −0.200 is second-largest. `docs/optimization-log.md:899` (round 2's entry) is corrected in place, in past tense, naming its own omission. Its round-1 entry's "five sweeps" list was wrong the same way and is corrected too. |
| **6** | Read `src/hrmosaic/core/retention.py` (`PRUNABLE_SESSIONS`) and `GET /health`. Both sentences reworded to what retention actually bounds: 300 **prunable conversational** sessions, with every `eval_run_id`, `eval_judge`, `maintenance` and `mock_writes`-owning session exempt — and the live counts (951 / 22,928 / 32) printed beside them. The second instance also now discloses that the 379 k-rows-read reading is from 2026-09-10 against a near-empty store, names the three uncached `COUNT(*)`s, and states the three options that would make the arithmetic current. `deployed.md:583-593` and `:600-612`. |
| **7** | Re-cut demo task 2's ①-bullet off the cited 2026-09-22 capture: eight tool calls over 36 spans in the capture's own order, including the **three** `search_policy_documents` calls (verified: `grep -c` → 3, lines 79/83/87; the usage line reads "8 tool call(s), 3 retrieval(s)") and the trailing `lookup_employee_profile`. The "may not appear" hedge is moved to the 2026-09-15 run where it is true, and the `tests/e2e/test_demo_tasks.py` `required_tools` fact is stated. `docs/demo-script.md:330-340`. |
| **8** | `docs/demo-script.md`'s segment table is now the single source. The checklist's DEMO.7 line and the matrix's DEMO.2 / DEMO.5 / DEMO.7 rows **cite it instead of restating numbers**, and the §18.3 references are dropped. DEMO.5's live evidence is repointed from the 2026-09-11 captures to the 2026-09-22 pair. |
| **10** | `grep -n elapsed` over `chat.html` confirms only the removal comment. "with an elapsed counter" deleted from all three documents, each replaced with the reason it was removed (46 announcements a turn, UX W2): `README.md:203`, `design-and-evaluation.md:981`, `docs/architecture.html` `D["f6-cold"]`. |
| **11** | Added a real **`f6-ux` tile** (a focusable `g.node` with `data-id`, a rect and a title line) in the free strip inside the FIVE JOBS group box, a **`f6-e-need3` ux→deploy edge**, `f6-ux` in the push / PR / dispatch trigger edges' `data-to`, and `D["f6-ux"]` + `D["f6-e-need3"]` detail entries (299 checks, cached chromium, no needs of its own). No layout was moved and the page stays self-contained. **Rendered with the repo's Playwright/Chromium** at 1440×900: `uxNode: True, uxTabindex: 0, edge: True`, the detail panel populates on click, **zero console messages** (the page's own completeness check warns on any `data-id` without a `D` entry and stayed silent), and the screenshot shows five tiles under the heading with the `needs` arrow into `deploy`. |
| **13** | `docs/demo-script.md:80` — "the run pinned on this build" → "the run pinned on app build `8a89310`", with a clause saying neither capture is on `34d50fb` and pointing at `docs/evidence/README.md` for the per-file build. |
| **19** | `docs/architecture.html` footer → "Current design of record: `design-and-evaluation.md` · page last revised 2026-09-23 (published build `34d50fb`) · first generated 2026-09-09 from the since-superseded …". |
| **20** | `docs/process/sdd/G5-grade-5/README.md`: title dated through 23, a **three-rounds table** (graded-at sha, card, verdict, commit range), `regrade-*` and `regrade2-*` rows in the inventory, the coverage line restated as the **actual** 12 briefs / 26 reports with the `ls … \| wc -l` command to check it, the credential scan recorded as re-run over each round's copy, and an explicit paragraph on why round 3's own task files lag by one commit. I also **copied `regrade2-report.md` and `regrade2-gaps.json` across** (credential-scanned first — the only pattern hits are `task-N` substrings and two turn ids) so the new rows are true at this commit rather than at the controller's. |
| **22** | `design-and-evaluation.md:1976` — "stdio for local development and the demo video" → "for local development, MCP Inspector and the CI discovery test", with the sentence that the recording has no stdio beat. The **same false claim on `docs/architecture.html`** (`D["f1-stdio"]`: "It is what the demo video shows") was corrected too. `mcp/run_stdio.sh:3` and `stdio_main.py:4` were **not** touched — see "left" below. |
| **25** | Both prose sentences reworded: `deployed.md:248` and `docs/optimization-log.md:308` now say `da0dca2` was the build live when the probe ran and the build the *then*-published run measured, name `r_1790130220_baseline` on `34d50fb` as the run published now, and add "no cold probe has been re-measured since 2026-09-11". The artifact `docs/evidence/cold-start-probes.json` is untouched, as instructed. |
| **27** | The row is **dropped**, along with its seed-subset sibling, and replaced by a paragraph saying why the two figures cannot be a before/after pair (recomputed per run, different item sets, different blind sessions, different answers) and giving this run's two figures with their overlap. `README.md:322-329`. |
| **31** | `scripts/check_facts.py`: the per-document line now prints **"N heading paths"** instead of "N sections", with a comment naming the cause; the `:35` docstring sentence claiming to be `corpus_stats.py`'s reader is **corrected** — that script imports `hrmosaic.rag.parse.parse_corpus` — and the docstring now states that the two figures differ by design and points at `corpus_stats.py` for the graded one. Verified: `check_facts.py` prints "heading paths", `corpus_stats.py` still prints "176 sections". |
| **33** | Counted from the harness: `.ux-capture/index.json` records `screen_count` 390 over **72** unique `screen_ids`, and `scripts/ux_capture.py:1020` prints that count. Stated as **72** in `README.md:151-154` (with the source named), `docs/evidence/README.md:88` (was "69 to 71") and `docs/evidence/ux-final/README.md:8` and `:18`. The geometry line is restated as **0 of 390** captures scrolling sideways, which I re-derived from the index. |

---

## D — T14's owed sentences

1-3. **`paths-ignore`** — all three corrected to the two remaining entries: `deployed.md:89-93` (the
paragraph now also says root documents left the list in round 2 and `docs/**` in round 3),
`design-and-evaluation.md:1008-1020` (rewritten, and it now says the docs tree is **gated** rather than
exempted), `docs/demo-script.md:84` ("three paths" → "**two**"). Also propagated to
`docs/architecture.html` — the `f6-t1` tile text and both its `D` entries printed the old list.
4. **gap 4/29** — the *"A disclosed edge"* section (`design-and-evaluation.md:445-480`) is rewritten as a
**closed defect**: the guard now reads a `status`, the scope is stated as **18 guards across every
scenario** rather than the four equipment ones, both reproductions are given (including the
`international_remote` one, which reached `conditional` with Director and Tax & Legal beside `unmet: []`),
and `tests/unit/test_rules_engine.py:745-853` is cited. Limitation 13 is **deleted** and replaced by a
much smaller limitation 14 covering the one surviving half (the schema description that never names
`device_age_months`). A fourth "closed in round 3" paragraph was added to the closed-limitations list.
I verified the fix is in the tree before writing any of it (`guard_holds` reads `decided.get(rest) == kind`;
the refresh case asserts `approvals_required: []`, `next_steps: []`).
5. **`expenses-002`** — reframed from a judge/labeller argument to a **named code cause with a shipped
fix**: the lead sentence justified the authority from the USD 5,000 threshold while the USD 2,500 manager
limit was the row that failed, and `compliance.correct_authority` replaces such a sentence. I also state
that the item still scores 0.79, so the fix has not closed the clause. Its **workflow clause passes on
this run**, which is the other half the old text got wrong. Arithmetic corrected from the run file: **7
claims, 6 supported, 1 contradicted → 5.5/7 = 0.79** (the old text said "one claim of nine" plus a partial).
6. **`no_structured_tools` annotation** — the arm is described as genuinely withholding at the call
boundary in `design-and-evaluation.md`'s ablation lede, its limitation 12, README's ablation paragraph,
the optimization log's round-3 section and the CHANGELOG, each naming round 2's 8-of-30 leak as the reason
its numbers are superseded rather than annotated.
7. **REPORT.md's action-safety line** — checked; **not changed**. See "left" below.
8. **`.env.example`** — `MCP_TOOLS_DISABLED`'s comment now reads "withheld on every turn **AND refused at
the call boundary with TOOL_DISABLED**".
9. **`corpus/rules.yml`'s two header comment lines** — **not changed**. See "left" below.

---

## Items from the list I did not change, with the reason

1. **`corpus/rules.yml`'s two stale header comment lines (item D9).** `corpus` is inside the provenance
   pathspec this task was also asked to restore. Editing the file — even a comment — makes
   `git diff --stat 34d50fb..HEAD -- … corpus …` print a path, which falsifies the restored claim in five
   documents and turns `test_the_application_tree_has_not_moved_since_the_measured_build` **red**. Item B
   is explicit that the test must pass, so the two comment lines wait for the next build and re-drive.
   They are wrong in the same direction as the fixed code (`:78` still implies `unmet:` reads a boolean;
   `:98-99` still says an absent-subject row "lands in `unmet[]`"), and the corrected semantics are now
   stated at length in `design-and-evaluation.md` and in `rules.py`'s own docstrings, so a reader is not
   left without the truth — only the file's own header is stale.
2. **`mcp/run_stdio.sh:3` and `src/hrmosaic/mcpserver/stdio_main.py:4` (rank 22's code headers).** Same
   reason: both are inside the frozen pathspec. Only the two documents outside it were corrected.
3. **`evaluation/REPORT.md`'s action-safety population line (item D7).** Checked as asked: the regenerated
   REPORT carries `| Action safety pass rate | 1.000 | 2 | – |` and no population prose, so the
   regeneration did **not** add it. I judged this not a defect worth a code change: the row is not false,
   it carries its own `n`, §13.4's population is defined at length in `design-and-evaluation.md`
   (now including G5c's two new membership clauses), and adding the gloss means editing
   `evaluation/runner.py:1523` and regenerating a published artifact — a measurement-chain change, outside
   a documentation pass and outside this task's "documentation only" framing.
4. **The suite figure (item E).** `pytest --collect-only -q -m ""` returns **3,469**, which is what all
   five documents already say. No bump needed; nothing edited.
5. **The remaining 22 gaps of the third grade** (ranks 1, 3, 4, 9, 12, 14-18, 21, 23, 24, 26, 28-30,
   32, 34-37) — out of scope by the brief, which lists the fifteen to fix and says to skip the rest as
   polish. Rank 1 (the packet criterion leak) was already closed by `7919e94`/`50c435f`; I only describe
   it.

---

## Two errors of my own, caught before the commit

Both were superlatives I drafted from the Task 5e report and then checked against the run files:

1. *"the first published run whose behaviour matrix is not diagonal"* — **false**.
   `r_1789166880_baseline` (2026-09-11) carries the same `confirm → answer` cell. Corrected everywhere to
   "not diagonal for the first time since 2026-09-11", with the three intervening diagonal runs named.
2. *"the first time the blind seed subset has produced a disagreement"* — **false**. The same 2026-09-11
   run returned `judge_agreement_rate` 0.875. Corrected to "the second published run in eight to return
   anything but 1.000 there", with the earlier one named; the point being made (a populated discriminating
   cell beats a perfect rate without one) survives intact. The `next_steps`-history count was softened at
   the same time to the instances that are actually documented.

Derivations for both are `python -c` reads over `evaluation/results/r_*.json`, reproducible.

---

## Concerns

1. **`corpus/rules.yml`'s header and the two stdio code headers are the wave's remaining stale sentences**,
   and all three are frozen behind the provenance claim. They cost nothing today because the documents
   around them are now right, but they will need the next build-and-re-drive cycle, and that cycle also
   owes `mcp/tools/check_policy_compliance.schema.json` the `device_age_months` description
   (limitation 14).
2. **`evaluation/REPORT.md`'s judge-methodology lede still reads "8 items fixed by `SEED` before any judge
   verdict existed"** and, two sentences after reporting 0.875 with one discriminating label, still says
   "A figure like that cannot separate a good judge from one that answers `grounded` to everything". Both
   are generated by `runner.py` and are now slightly off-key against a non-unanimous blind subset — the
   first is defensible (the *draw* is a function of the dataset alone), the second is a template sentence
   written for the unanimous case. Neither is false enough to justify editing a generated artifact in a
   docs pass, but a future `runner.py` change should condition that sentence on the matrix.
3. **`deployed.md`'s Turso quota arithmetic is now honestly labelled rather than resolved.** The 379 k
   rows-read figure is still from 2026-09-10 against a near-empty store and the `/health` counts are still
   uncached. The paragraph says so and names the three fixes; someone should either re-read the usage page
   or cache the counts before the next publish.
4. **The demo script's task-1 and task-2 captures remain two app builds behind** (`8a89310` under a
   docs-only `8782177`). The sentences now say so precisely, but a re-capture on `34d50fb` would remove
   the hedging entirely and is cheap if the daily cap allows.
5. **The history table is now eight columns wide** and renders as a very wide table. It is still the most
   honest presentation available, but a ninth round would be a good moment to fold columns 1-3 into a
   single "before optimization" column.
