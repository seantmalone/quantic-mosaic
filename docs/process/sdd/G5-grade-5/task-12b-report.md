# Task 12b — round-2 documentation: the design document, the optimization log, the frozen spec

**Commit `edd99a4`** on `main` — `G5b(docs-design): the design document reads the 30-item published run,
gains a linked TOC, and the frozen spec says it is frozen`. Four files, explicitly `git add`-ed:
`design-and-evaluation.md`, `docs/optimization-log.md`,
`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` (banner only),
`tests/contract/test_docs_completeness.py` (one test extended, no new collected test). Trailer
`Co-Authored-By: Claude Fable 5.1`, no `Claude-Session`. Nothing else in the tree was touched; the
concurrent agents' commit `e9ee3b3` landed mid-task and is untouched by this one.

## Verification

| Command | Result |
|---|---|
| `.venv/bin/python scripts/paste_eval_numbers.py --check` | `OK — the results table matches evaluation/results/latest.json`, **exit 0** |
| `.venv/bin/pytest -q -p no:cacheprovider tests/contract` (one process) | **558 passed in 150.66s** |
| `.venv/bin/pytest --collect-only -q -p no:cacheprovider` | **3139/3438 tests collected (299 deselected)** — unchanged |
| `.venv/bin/pytest -q tests/contract/test_docs_completeness.py` | 49 passed (same count as before; the TOC assertions live inside an existing test) |
| `ruff check` / `ruff format --check` on the edited test file | clean |

## design-and-evaluation.md — what changed, by gap

* **5c/5d's stale-prose concerns + gap 12**: the document now reads the published 30-item run
  `r_1790110325_baseline` (build `80a5a71`, dataset sha `2c897314…`) everywhere. The history table gained
  a **seventh** column (30 items, strict 0.900, groundedness 0.986, citation 0.889, partial 0.820, doc
  recall 0.908, tool selection 0.984, workflow 0.933, safety 1.00 **n = 2**, seed/hard agreement
  1.000/**0.750**, p50/p95 15.5/29.6 s, ablation −0.167, $0.80), column 6 relabelled "After the
  grade-and-fix wave", and a column 6 → 7 paragraph explains which movements are the dataset's (two new
  items, the equipment corpus fix) and which are two turns' sampling. The small-denominator paragraph now
  says safety **n = 2**, escalation **n = 2**, and `pto_request` **1.00 over n = 3 of which two are
  confirmation-gate checks, not three completed requests**.
* **Strict-pass causes** rebuilt from the run file: `expenses-002` (groundedness 0.78 — 7 of 9 claims
  supported, one partial, one contradicted — plus the 3-citation/3-document end state), `remote-004`
  (never called `get_policy_section`; tool recall 0.75, doc recall 0.50, workflow 0.00), `unsafe-001`
  (stopped at the card correctly, but no `search_policy_documents`: tool recall 0.75, doc recall 0.00).
  `equipment-001` is explicitly named as no longer on the list (groundedness 0.688 → **1.000**, passes).
* **Gap 6**: corpus headline and 14-row table repasted from `scripts/corpus_stats.py` — **63.9 pages,
  30,938 words, 176 sections**, with a paragraph stating that the table now equals the committed index's
  `documents` table row for row (verified: 14 / 176 / 30,938 / 63.9 / 205 from `hr_index.sqlite`) and
  naming the superseded 64.2 / 31,007 reading. **205 chunks** in the diagram, the manifest sentence, the
  chunk sweep and the evidence table. Facts ledger **58 → 60** (`check_facts.py` prints 60).
* **Gap 19**: a linked **Contents** list after "How to read this document" — one line per `##` with the
  ten design-justification `###` nested, using GitHub auto-slugs including the three `-1` duplicates.
  "The eight `##` sections" → "The first eight".
* **Gap 2**: a new `### Clarification — what the question left out, named deterministically` in §Agent
  orchestration: every unfilled slot; message-first topic inference (with the `amb-001`-served-`amb-002`
  defect stated); and `is_bare_balance_ask`'s four conditions read off `orchestrator.py`.
* **Gap 14**: `catalog_reopened_rate` **0.000** with the test that covers the path, the `pto_request`
  predicate's `lookup_employee_profile` clause, and the diagram's memory label as a dateless band
  (`~300-320 MB live / 512 MB`); limitation 8 now dates the 293.6 MB live reading.
* **Gap 8**: the pasted `search_policy_documents` schema shows the `anyOf` number/null with
  `"default": null`, and the prose names `MIN_SUPPORT_SCORE` 0.45 as the effective floor.
* **Gaps 16/9/7**: the `ux` row no longer claims "never blocks"; `deploy` carries
  `needs: [test, docker, ux]` in all three places; a paragraph states the withdrawn rationale with run
  35723846982 as what it bought and the ~11-minute cost; a paragraph explains `*.md` leaving
  `paths-ignore`; the `lint` row and the security-posture bullet describe **two** gitleaks scans, the
  whole-history one on every run.
* **Gap 17**: "one `mcp_discovery` span per turn **pass**" with the resumed turn's second span (demo task
  2, seq 1 and seq 27), and `mcp_session_id` captured from the `Mcp-Session-Id` response header by an
  httpx hook, `null` on stdio.
* **Gap 18**: "**Three** declarative specs", naming `expense_claim`, each predicate unit-tested.
* **Gap 13**: a new paragraph names `r_1790067656_baseline`'s committed `judge_agreement_rate` 1.000
  (n = 8) as folded from labels authored against `r_1790074972_baseline`'s turns (8/8 turn-id mismatch),
  states it is **not** a published figure for that run, and records that the dashboard now prints each
  rate beside its subset (or "subset not recorded") and renders the hard figure.
* **Gap 15**: the header line is now "**Design of record as approved (frozen 2026-09-09)**", and
  `/dashboard/corpus`'s row says a citation chip deep-links into the `/policy` reader (verified:
  `g2.py:49` `SOURCE_URL = "/policy/{doc_id}#{chunk_id}"`).
* **Judge methodology** rewritten for this run: the blinding paragraph now states the label files' own
  timings (seed packet 21:16:08Z **while the judge pass was in flight**, first judge call 21:00:23Z,
  judged run file 21:27:40Z, hard packet 21:27:58Z) instead of "judge_status pending"; the hard subset's
  membership is listed; the two disagreements are described in **opposite directions**
  (`expenses-002` judge stricter, `expenses-001` labeller stricter); "no agreed `not_grounded` in either
  matrix"; 16 of 18 judged items at exactly 1.0 (others 0.969, 0.778); and the two blind sessions'
  disagreement with **each other** on `expenses-001` is disclosed. The `next_steps` paragraph no longer
  says "neither recurs" — this run lost an agreement to exactly that class.
* **Coordinator's mid-task note**: `n_cold = 3` is now explained rather than denied. The three cold turns
  are `pto-001`, `remote-001`, `benefits-001` — `run_phase: scored`, tagged from
  `turns.process_uptime_ms < 60000` after the instance was replaced under the drive (the first `/chat`
  was answered **502** and retried, `measure-baseline5.log`), excluded from p50/p90/p95/p99 (which
  `runner.py:859` computes over warm rows only) and published as **cold p50 13,889 ms**, below the warm
  p50. Limitation 10 says a young process is not a spin-down cold start. `remote-004`, not `remote-002`,
  is named as the multi-document miss throughout.
* **Ablation**: new trio, new table, six deltas (−0.154 … −0.167), ten flips with `expenses-002`'s two
  read against the unjudged-arm sentence and `unsafe-001`'s `dense_only_k2` pass identified as real
  (tool recall 1.00 there). The *Retrieval k* justification no longer says the two arms tie.

## The contract test (no new collected test)

`test_design_document_has_the_eight_docs3_sections` → `…_and_a_toc_that_resolves`, same single test,
plus two module helpers: `_github_slugs()` (lower-case, delete everything outside `[a-z0-9 _-]`, spaces
to hyphens, duplicates numbered `-1`, `-2`, … in document order) and `_design_toc()` (the text between
`**Contents.**` and `**A note on honesty.**`). It asserts every `## ` heading's slug is linked in the
contents list, and that **every** `](#anchor)` in the file resolves to a heading that exists. Verified
the slug function against the document's own headings: `#mcp-server-design` vs `#mcp-server-design-1`,
`#tool-schemas` vs `#tool-schemas-1`, `#safety-guardrails` vs `#safety-guardrails-1`,
`#evaluation-questions-expected-answers-and-results`.

## docs/optimization-log.md

A dated `## 2026-09-22 — Round 2 of the grade-and-fix pass…` section in the file's Question / Evidence /
Decision / measured-tables style: the re-grade (band 4, **20 ranked gaps**, the amb-001 finding stated as
the one that mattered), the four change groups, a drives table (`r_1790106448` on `7ada32e` — never
judged, `judge_calls` 0, discarded by ruling for `amb-003` answering the balance and `unsafe-002`'s gold
expecting a retrieval the task does not need; `r_1790110325` on `80a5a71` published), the published
measurements beside the `r_1790074972` column (with the test cell **3,139 + 299, collected at
`44e5e9f`**), the re-driven ablation, the chunk sweep, cost (**$2.28** for the trio, 266 judge calls at
≈ $0.16–$0.18, ≈ $2.5 for round 2 and ≈ $7.5 across both rounds), and *What we still did not get*.

## The frozen spec

A dated block quote at the top: frozen 2026-09-09 as the pre-implementation design of record, "where it
disagrees with design-and-evaluation.md, that document is current", then the named disagreements — §2's
span rail (UX W2), §15.1's "four jobs" against five with `ux` gating deploy, §18/§18.3's demo table
superseded by `docs/demo-script.md`, the citation chip now reaching the `/policy` reader, "~280 chunks"
→ 205, "15.8 s" ingest → the measured 107.6 s at build time, and a note that `Status: approved for
implementation` is part of the frozen record. Every quoted spec string was grepped in the file first
(`:106`, `:121`, `:437-438`, `:2903`, `:3162`+).

## Concerns

1. **`expenses-002`'s workflow clause is inferred, not read from a stored field.** The run file keeps the
   answer text but not its citation array, so I wrote that the served answer "did not span three"
   documents from the scorer's definition (`deterministic.py:468-474` — `min_citations` 3 and
   `min_distinct_docs` 3, with `workflow = 0.0`) plus `doc_recall = 1.00` being measured over *retrieved*
   docs (`runner.py:516` → `retrieved_doc_ids`). Which of the two floors it missed is not recoverable
   from a committed artifact; the prose says only what the score implies.
2. **The three cold turns' cause is a reading of the logs, and I said so in the words I used.** The
   502-then-retry at 13:52:30 PDT in `measure-baseline5.log`, the absence of a "warm-up poll gave up"
   note, and three `cold = 1` scored rows together support "the instance was replaced under the drive";
   no Render event log was read (the credential rule). A reader who wants it harder would need the
   platform's own restart record.
3. **`design-and-evaluation.md` line 1069's `n_warm` claim was corrected in passing** — the metric family
   row said latency is "split cold vs warm with `n_cold`/`n_warm`" and no `n_warm` field exists; it now
   describes what the run file actually carries. Nothing else in the metric-families table was touched.
4. **Two design-doc statements still name figures nobody guards.** The corpus table and headline now
   match `corpus_stats.py --json`, but no test asserts it (gap 6's fix card suggested one; adding a
   collected test was outside this brief's "no new collected test" rule). Same for the 205-chunk figure
   in prose, which `--verify-manifest` proves for the manifest but not for the sentence.
5. **The optimization log attributes round 2's ruling to "Sean, 2026-09-22"**, following the file's
   existing convention; the ledger records those rulings as the controller's.
6. **Shared-file risk is nil but cross-document consistency is not mine to close.** Three other agents
   own README / deployed / traceability / ai-tooling / CHANGELOG / mcp README / evidence index, the demo
   script and `architecture.html`. Figures a grader will compare across documents — 30 items, 205
   chunks, 63.9 pages / 30,938 words / 176 sections, 60 facts, `needs: [test, docker, ux]`, the
   published run id and build, safety `n = 2` — are stated here as above; the final review should diff
   them across all seven documents.

---

## Fix round 1 — commit `97177e5`

`G5b(docs-design): fix round 1 — latency n is the warm count, and the predicate claim says what the
suite asserts` · 3 files, +62 / −27, explicitly `git add`-ed: `design-and-evaluation.md`,
`docs/optimization-log.md`, `scripts/paste_eval_numbers.py`. No collected test added or removed.

### Important 1 — the latency row's `n`

`Runner.assemble()` builds its latency list from the scored turns `if not entry.result.cold`
(`evaluation/runner.py:859-863`), so the percentiles on this run cover **27** turns, not 30. The
script's row printed `counts['items']`. Both rows of that pair now read correctly, and the generated
block is:

```
| Latency p50 / p95 (ms) | 15,544 / 29,600 | 27 warm | – |
| Cold turns, excluded from those percentiles | n_cold = 3 | cold p50 13,889 ms | reported separately |
```

`items = counts.get("items") or run["n_items"]`, `warm = items - int(metrics.get("n_cold") or 0)`, with
a five-line comment naming the runner lines that make it so. The second row was relabelled in the same
edit — "Cold turns **in the distribution**" contradicted "27 warm" — and now carries `cold_p50_ms`,
which the run file has always held and the block never printed. Nothing else in the block moved: the
row is appended outside `ROWS`, so `test_results_block_carries_every_row_the_script_declares` is
unaffected, and `--check` exits 0 after a regeneration. Limitation 7 ("the 27 **warm** turns of the
30") and the metric-families row (percentiles "over the **warm** turns … cold ones counted as
`n_cold`") already agreed; the optimization log's latency row now states both columns' denominators
(28 warm / `n_cold` 0 against 27 warm / `n_cold` 3, cold p50 13.9 s).

### Important 2 — the predicate claim

Verified with `grep -rn is_complete tests/`: `expense_claim.SPEC.is_complete` has its own three-state
test (`test_expense_claim_is_scored.py:80,84,91`); `PTO.is_complete` is asserted **both** ways in
`test_agent_nudge.py` (True at `:276`, `:638`; False at `:385`, `:488`, `:516`, `:635`); `REMOTE`'s is
asserted **only** False, at `:539`. The sentence now says exactly that, and keeps the one claim that is
true of all three — they are pure functions over recorded tool results, which is what makes them
assertable.

### Minors

3. The judged-mean attribution is split: groundedness 0.963 → 0.986 and citation accuracy 0.875 →
   0.889 on `equipment-001`, `travel-001`, `pto-002`; partial match 0.801 → 0.820 on `inj-001`
   (0.00 → 1.00) **against** `equipment-001`'s own 1.00 → 0.60 and `onboarding-001`'s 0.50 → 0.25
   (computed per item from both run files). The optimization log gained the same disclosure — a
   stricter five-key gold costs a point on the metric that counts gold facts.
4. Limitation 11: "`expenses-002` accounts for **two of the ten** strict-pass flips".
5. `expenses-002`'s workflow clause now says it "missed one of the two" citation floors
   (`min_citations` 3 / `min_distinct_docs` 3) and that the run file cannot say which — which retires
   concern 1 of the original report by stating the limit in the document itself.
6. The cold-turn cause is hedged: the 502-then-retry is "consistent with the instance having been
   replaced under the drive, which is as far as the drive log evidences it".
7. Six over-long lines re-wrapped (the four named, plus two the edits had merged into their
   neighbours). No prose line the fix touched now exceeds 106 characters, in a file whose existing
   convention wraps at 100 and whose tables and mermaid source run longer.
8. The contents list nests `#results`, `#judge-methodology`, `#the-two-demo-tasks` and
   `#known-limitations` under section 8; the contract test's link-resolution half covers them.

### Verification

| Command | Result |
|---|---|
| `.venv/bin/python scripts/paste_eval_numbers.py` then `--check` | regenerated, then `OK — the results table matches evaluation/results/latest.json`, **exit 0** |
| `make lint` | `All checks passed!` · `321 files already formatted` |
| `.venv/bin/pytest -q -p no:cacheprovider tests/contract tests/unit/test_paste_eval_numbers.py` | **564 passed in 152.09s** |
| `.venv/bin/pytest --collect-only -q -p no:cacheprovider` | **3139/3438** — unchanged |

### Concerns from this round

1. **Nothing asserts the latency row's `n` semantics.** The fix is correct at this commit, but a future
   change to how `Runner.assemble()` filters cold rows would silently re-introduce the mismatch;
   `tests/unit/test_paste_eval_numbers.py` covers the source-selection logic only. A one-line assertion
   that the rendered row's `n` equals `items - n_cold` would close it, and would add a collected test —
   deliberately not done under this wave's suite-count rule.
2. **`cold_p50_ms` now appears in a graded document for the first time.** It is read straight from the
   run file and `--check` holds it, but any prose that quotes it (limitation 10 does) is hand-written and
   unguarded, like every other narrative figure outside the markers.
