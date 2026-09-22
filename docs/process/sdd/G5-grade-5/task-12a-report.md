# Task 12a report — round-2 documentation (G5b), README/deployed/checklist/traceability/needs/changelog/ai-tooling/corpus/mcp/evidence

**Commit:** `e9ee3b3` — *G5b(docs-readme): the published run is 80a5a71 over 30 items, provenance is a
dated command, and the cost row is honest* (parent `70b095c`, Task 12c's demo-script commit). Branch
`main`. Staged with explicit `git add` of the twelve owned paths only; `design-and-evaluation.md`,
`docs/optimization-log.md`, the frozen spec, `docs/demo-script.md`, `docs/architecture.html` and
`tests/contract/test_docs_completeness.py` were left in the working tree untouched by me. **No
collected test was added** — the suite figure stays 3,438 (`pytest --collect-only -q -m ""` re-read
at 3,438 during this task).

**Gate commands (one process, run twice — before and after the last two edits):**

| Command | Result |
| --- | --- |
| `.venv/bin/python scripts/paste_eval_numbers.py --check` | `OK — the results table matches evaluation/results/latest.json` (exit 0) |
| `.venv/bin/pytest -q -p no:cacheprovider tests/contract` | `558 passed in 146.45s` |

---

## Gap 1 — the provenance command (high)

Restated at every owned site as a **dated, runnable** check naming the exact pathspec, with the
reader told to run it. Verified myself: `git diff --stat 80a5a71..HEAD -- src mcp Dockerfile
render.yaml requirements.txt` is **empty** both at `44e5e9f` (the anchor the documents print) and at
the tip as I committed.

* `README.md:263-273` — published-run paragraph: *"the relation is a command rather than a promise:
  **`git diff 80a5a71..HEAD -- …` was empty at `44e5e9f` on 2026-09-22** — run it at whatever HEAD
  you are reading"*.
* `deployed.md:76-93` — *The live sha moves; the application tree does not* rewritten: the command is
  now a fenced block, dated at `44e5e9f`, and closes *"If it ever prints a path, that path is the
  honest answer and this paragraph is the thing that is stale."* The false strongest form
  ("`8a89310` is the last commit to change application code") is gone.
* `docs/pre-submission-checklist.md:46-55` — the ticked run box carries the same dated command.
* `docs/requirements-traceability.md` RUBRIC5.1 — same, plus the 21:58Z `/health` reading.
* `CHANGELOG.md` (new G5b entry 1) — explicitly **supersedes** the G5 entry's
  "`8a89310` … the last commit to change application code" sentence rather than rewriting history,
  which is the file's own convention (cf. the P27 entry superseding P25).
* `README.md:100-107` — the pinned-transcript paragraph no longer reads as though `8a89310` is the
  current app build: it names the round-2 build `80a5a71` and says the transcripts are not
  re-captured to keep up.

Artifacts: `git diff` at `80a5a71..44e5e9f` and `80a5a71..HEAD` (both empty); live `/health`
`app.git_sha 80a5a71c02f2…`, read 2026-09-22 21:58:44Z.

## Gap 5 — the cost row

`deployed.md:453` re-derived from the committed files (loop over `evaluation/results/r_*.json`,
`metrics.est_cost_usd`):

* **$16.2534 over 25 files** → published as **$16.25**; per-drive range **$0.415904–$0.892606** →
  published as $0.42–$0.89. (The grader's $13.98 is the first 22 files: 16.2534 − 0.801393 − 0.679880
  − 0.795521 = 13.9766.)
* Structure: **eight trios plus one lone baseline** (24 + 1 = 25), three trios driven on 2026-09-22.
* The two drives this wave discarded: **$0.801618** (`r_1790062696`, `measure-baseline.log:324,333`)
  and **$0.825258** (`r_1790106448`, `measure-baseline4.log:346,355`), attributed to the wave ledger
  because neither has a committed run file. The two 2026-09-16 store-only drives carry **no cost
  figure in any committed artifact** and the row says so.
* The `$10` expectation is restated honestly rather than dropped: *"This is past §9.8's 'under $10
  all-in' expectation, and the overrun is the honest number"*, with the reason (an ablation whose arms
  sit on different commits is refused by `evaluation/ablation.py`, so a code fix costs three drives)
  and the acceptance.
* The same honesty is carried to `docs/requirements-traceability.md` **PD.4** and **R7.4**, which had
  asserted "under $10 all in" as built.
* `/health.trace_store.eval_runs_imported` **29** vs **25** committed files: reconciled in
  `NEEDS-FROM-USER.md:206-215` and its Discharged row, naming all four store-only drives
  (`r_1790106448` 19:47Z `7ada32e` never judged; `r_1790062696` 07:38Z `82994ce`; `r_1789547562` and
  `r_1789534779`, 2026-09-16), with the reason none can be reconstructed (the dashboard API serves a
  view-model with no `dataset_sha` / `target_git_sha`).

I did **not** add a cost check to `scripts/check_facts.py` (the gap's optional half) — that would add
collected tests or change a script another task owns.

## Gap 7 — the gitleaks wording

The claim is now literally true (Task 10 added the whole-history step), so the documents describe the
**mechanism** rather than softening the claim:

* `README.md:164-175` — five jobs named, and `lint` described as two scans: the action's pushed-commit
  range scan, and `gitleaks detect --source .` from the pinned **8.30.1** binary on every run
  (**280 commits, 13.22 MB, no leaks, 2026-09-22** — Task 10's verified run, matching `ci.yml:56-72`).
* `ai-tooling.md:302-306` — the ownership disclosure's security clause says the same.
* `docs/requirements-traceability.md` **R1.5** — both scans, the pin, `fetch-depth: 0`, and the
  contract test that holds them.

## Gaps 9 + 16 — CI: `ux` in `deploy`'s `needs`, `*.md` out of `paths-ignore`

Every sentence in my files that stated the superseded rationale changed (the list came from
`task-10-report.md`'s document inventory, re-grepped):

* `README.md:66-67` (the "never blocks `test` or `deploy`" sentence), `:157`, `:170-173`.
* `deployed.md:28-29`, `:94`.
* `docs/requirements-traceability.md` **R8.2** (twice in the row, plus the `deploy` clause), **R8.4**,
  **RUBRIC5.7**.
* `NEEDS-FROM-USER.md:148`.
* `deployed.md:76-80` — the `paths-ignore` sentence is now one item shorter and says a repo-root
  document commit runs the suite and deploys.
* `NEEDS-FROM-USER.md:196-200` — the results-commit note likewise.
* `docs/pre-submission-checklist.md:60-66` — **new box**: after the README demo-video commit, confirm
  its own run is green and `/health.app.git_sha == git rev-parse HEAD`; nothing needs dispatching now,
  and `gh workflow run ci.yml -f deploy_only=true` is named as the fallback, never during a deploy.

## Gap 17 — MCP record-vs-doc drift

`mcp/README.md:65-79` (discovery step 3) and `:136-137` (error table):

* "Exactly one `mcp_discovery` span per turn" → **"One `mcp_discovery` span per turn pass"**, with the
  resumed-confirmation case named and evidenced: `docs/evidence/demo-task-2-live-2026-09-22.txt`
  lines 65 and 105 show `mcp_discovery` at **seq 1** and **seq 27** inside the same **36-span** turn
  (line 64: `-- trace (36 spans)`).
* `mcp_session_id` now documented as the `Mcp-Session-Id` response header captured by an **httpx
  response event hook** on the client's own `AsyncClient`, because mcp 2.2.0's
  `streamable_http_client` yields only `(read, write)` and `ClientSession` has no `session_id` (the
  1.x→2.x table's own row) — `null` on stdio, and `null` on HTTP in spans written before the hook
  landed, which is why `demo-task-1-live-2026-09-15-session.json` shows `null`.
* The retry row is split in two: **re-discovery once** at the discovery step, and **no retry** on a
  `tools/call` — it degrades the turn immediately, and a write is never re-sent.
* Gap 20(h) in the same file: the transports table and *Why stdio still exists* no longer promise the
  video shows a separate OS process (the script is driven against the deployed URL); they name
  `make run-stdio` / MCP Inspector and `tests/integration/test_mcp_discovery.py`.
* No `min_dense_score` / `0.26` sentence exists in `mcp/README.md` (grepped) — nothing to correct.

## Gap 18 — R4.2 names three workflows

`docs/requirements-traceability.md` **R4.2** rewritten: three registered workflows
(`remote_work_eligibility`, `pto_request`, `expense_claim`), `WorkflowName` as a three-member
`Literal`, and `tests/unit/test_expense_claim_is_scored.py` as `expense_claim`'s evidence — with the
honest note that it carries no dataset item, so its absence from
`workflow_completion_by_workflow{}` is deliberate rather than an omission.

## Gap 20 — residual cross-references

* (g) `NEEDS-FROM-USER.md:103` — SUB.3 is no longer described as `- [ ]`: it names the `- [x]` line
  and the 2026-09-11 read-back, and says nothing on that gate waits on the user.
* (a) `README.md:37-39` — the `uv pip compile` sentence now names the Makefile's **`lock`** target, so
  `pyproject.toml:15`'s pointer resolves in prose too.
* Timezones: no owned file quotes a packet mtime, so nothing needed converting. All times I added are
  UTC and named as such (`21:58Z` from the live `/health` read, `20:52Z` from the run id).

## Gap 6 — corpus figures

From `.venv/bin/python scripts/corpus_stats.py` (now reading `hrmosaic.rag.parse.parse_corpus`):
**14 files · 63.9 pages · 30,938 words · 176 sections** (html 1 / md 11 / pdf 1 / txt 1).

* `docs/requirements-traceability.md` **PD.1** — figures replaced and the parser change stated.
* `corpus/README.md:30-33` — the parity note with the four figures.
* `corpus/README.md:18` and `:255` — fact count **58 → 60**, the number
  `scripts/check_facts.py` prints (`14 documents · 60 facts · 7 rule scenarios · 34 requirements`).
* `corpus/README.md:148-153` — the equipment summary now matches the repaired policy (a scheduled
  refresh is an IT ticket whatever the machine costs; the USD 500 director threshold governs
  *additional* equipment), with the 2026-09-22 repair disclosed.
* `CHANGELOG.md` (new G5b entry 2) reconciles the two figures this file carried (the P2 entry's
  31,007 words came from the script-local reader).

## Gap 12 — small denominators

`README.md:292-303` publishes each with its `n` and what it is: clarification 1.000 over the 3
ambiguous items, action safety **1.000 over the 2 write items** — with the disclosure that safety and
escalation each grew from one observation to two in this wave — and
`workflow_completion_by_workflow` read out as `pto_request` **1.00 (n = 3) = one completed filing
plus two turns that correctly stopped at the card, not three completions**, and
`remote_work_eligibility` **0.50 (n = 2)**.

## Round-2 numbers — every figure and its artifact

All from `evaluation/results/r_1790110325_baseline.json` (`metrics`, `metrics.n_scored`,
`items[]`) and `evaluation/REPORT.md`; nothing hand-computed except the deltas noted.

| Figure | Value | Where it is published |
| --- | --- | --- |
| run / build / dataset sha | `r_1790110325_baseline` · `80a5a71` · `2c8973147744…` | README, deployed.md, checklist, RUBRIC5.1, NEEDS, evidence index, CHANGELOG |
| judge calls | 266 | README, CHANGELOG |
| strict pass | 0.900 (27/30) | README table, traceability header + RUBRIC5.1, checklist, CHANGELOG, ai-tooling |
| groundedness | 0.986 (n = 18) | README table, RUBRIC5.1, CHANGELOG |
| citation accuracy | 0.889 (n = 18) | README table, CHANGELOG |
| cit_resolve | 1.000 (n = 30) | README table, RUBRIC5.1, CHANGELOG |
| doc recall | 0.908 (n = 19) | README table, CHANGELOG |
| tool selection | 0.984 (n = 30) | README table, CHANGELOG |
| workflow completion | 0.933 (n = 30) | README table, CHANGELOG |
| clarification | 1.000 (n = 3) | README, CHANGELOG |
| action safety | 1.000 (n = 2) | README, CHANGELOG |
| refusals | 0.000 / 0.000 (n = 18 / 7) | README table, CHANGELOG |
| latency | p50 15.5 s / p95 29.6 s (15544 / 29600 ms) | README table, CHANGELOG |
| agreement | seed 1.000 (n = 8) · hard 0.750 (n = 8), disagreements `expenses-001`, `expenses-002` | README table + prose, CHANGELOG |
| failing items | `expenses-002` (groundedness 0.778, workflow 0.0), `remote-004` (tool recall 0.75, workflow 0.0, doc recall 0.5 of 4 gold docs against the predicate's 3-document floor), `unsafe-001` (tool recall 0.75; workflow 1.0) | README, RUBRIC5.1, CHANGELOG |
| ablation | baseline 0.933 → no_structured_tools 0.767 = **−0.167** against the 0.25 bar, **not supported**; dense_only_k2 strict 0.933 / workflow 0.967; flips: `expenses-002` to pass on both arms, `remote-002` to fail on both | README, CHANGELOG |
| drive cost | $0.801393 | CHANGELOG |
| live `/health` 21:58Z | `80a5a71`, 9 tools, 14 docs / **205** chunks, `rss_mb 317.8`, `eval_runs_imported 29`, `degradations []` | deployed.md, CHANGELOG, NEEDS |

`README.md:11` untouched (`Demo video: pending: gate 6 — …`). The "Before" column stays
`r_1789055103_baseline`; `r_1790074972_baseline` is now a history row in `deployed.md`'s
serving-commit ledger.

## `docs/evidence/`

* `docs/evidence/grade-card-2026-09-22.md` — `regrade-report.md` copied **verbatim** under a
  three-line header in the 09-21 card's style (what this is · graded 2026-09-22 read-only at HEAD
  `2dee277` by a 78-agent workflow, band 4, 20 ranked gaps · what was done about it, pointing at the
  wave ledger).
* `docs/evidence/grade-card-2026-09-22-gaps.json` — `regrade-gaps.json` byte-for-byte (re-parsed with
  `json.loads` before writing).
* Secret-scanned both: `grep -nEi 'sk-ant|sk-…|AIza|gh[pousr]_|xox[baprs]-|BEGIN … PRIVATE KEY|Bearer |\?access=|libsql://|eyJ…'` → the only hit is the phrase `?access=` inside a demo-setup sentence,
  with no token value; `grep -c` for the live access token → **0** in both files.
  `scripts/pii_check.py` → `clean`.
* `docs/evidence/README.md` — header paragraph re-pointed at the published run (`80a5a71`,
  `r_1790110325_baseline`, 20:52Z, 30 items) and explains why three transcripts still name `8a89310`;
  the three 2026-09-22 transcript rows say `8a89310` was superseded that evening by `80a5a71`; the
  `final-2026-09-16/` row's "the run published now" updated; **two new index rows** for the card and
  its gaps json; the closing sentence re-cut for the two rounds.
* `ai-tooling.md` and `docs/pre-submission-checklist.md` now name **three** grade cards, with the
  2026-09-22 one linked.

## `ai-tooling.md` §8 — the round-2 paragraph

Added *"And then graded again, because a fix wave is a change like any other (2026-09-22)"*: the
78-agent re-grade at `2dee277`, band 4 with 20 gaps, the three named caps, the round-2 task shape (one
Opus implementer per task, an independently dispatched Opus reviewer, fix rounds), and — honestly —
the **discarded drive** `r_1790106448` on `7ada32e`, why it was discarded (one item's gold demanded a
retrieval the task does not need; another turn had no deterministic rule behind gold's behaviour), and
that the replacement drive *did not score better*, which is the point. Also: the suite figure stays
**3,438 as of 2026-09-22**; the "published run was measured on the 28-item set" caveat is gone
(it drives all 30 now); the *Refusing to tune the number* bullet reads 0.900 and names the discarded
drive; the trailer paragraph now says **both rounds** (`G5(…)` and `G5b(…)`) carry
`Claude Fable 5.1` — verified by `git log --format='%h %s%n%b' 2dee277..HEAD`, all seven G5b commits
carry it — and the census anchored at `5b1bd51` is untouched and still recounted green by
`test_the_commit_census_is_the_one_git_log_reports`.

## `CHANGELOG.md`

Three bullets appended in the file's style (the file's entries are appended bullets, not new `##`
sections): the re-grade and what it found (with the explicit supersession of the `8a89310` sentence),
what each round-2 task changed (Tasks 11, 10, 11b, 5c/5d over `9dcd8dd`..`44e5e9f`), and the published
run with its full figure set, the durable provenance form, the re-derived cost row and the
`eval_runs_imported` reconciliation.

## Concerns

1. **The live service's Anthropic daily call cap was exhausted when I read `/health` at 21:58Z:**
   `llm.agent.calls_today: 1500`, `daily_call_cap: 1500`. `status` is still `ok` and
   `degradations` is empty, but a `/chat` turn on the deployed instance may be refusing on the cap
   until the UTC day rolls over. Worth a check before any further live capture or demo rehearsal.
2. **The provenance anchor is a commit, so it ages by design.** The documents say the diff was empty
   at `44e5e9f` and tell the reader to run the command at their own HEAD. If a later task changes
   anything under `src`, `mcp`, `Dockerfile`, `render.yaml` or `requirements.txt`, the published run's
   build must be re-stated (or re-driven) — the sentence no longer lies on its own, but it also no
   longer covers such a change. Gap 1's suggested contract test was **not** added, because this task
   may not add collected tests; that guard is still missing.
3. **The two 2026-09-16 store-only drives have no committed cost figure**, so the cost row states the
   committed total ($16.25) plus the two G5b drives from the ledger and says the 09-16 pair is
   unpriced rather than estimating them.
4. **`deployed.md` keeps its dated 2026-09-10 readings of 204 chunks** (the `docker run -m 512m`
   paste and the live `rss_mb` row) and `docs/requirements-traceability.md` R7.1 likewise. They are
   records of a date, not current claims, and the current reading (205 chunks) is published beside
   them in the *What was serving* paragraph — but a grader skimming for "205" will find both numbers.
5. **`r_1790074972_baseline`'s row in `deployed.md` keeps its original 11:10Z time** while the run id
   decodes to 11:02Z (the earlier task's figure, left as found). Every time I added is derived from
   the run id or a `/health` read and is UTC.

---

# Fix round 1 — commit `89ae235`

*G5b(docs-readme): fix round 1 — the provenance command names the application tree, and the evidence
index reads the 2026-09-22 capture* (parent `edd99a4`, Task 12b's design-document commit). Explicit
`git add` of eight owned files; `design-and-evaluation.md` untouched (its review is in flight). No
collected test added.

| Command | Result |
| --- | --- |
| `.venv/bin/python scripts/paste_eval_numbers.py --check` | `OK — the results table matches evaluation/results/latest.json` (exit 0) |
| `.venv/bin/pytest -q -p no:cacheprovider tests/contract` | `558 passed in 152.09s` |

## Important 1 — the published pathspec covered the README it was printed in

The reviewer is right, and the mechanism is worth recording: `git diff … -- src mcp …` treats `mcp` as
a directory prefix, and `mcp/` holds `mcp/README.md` alongside the code, so **the commit that landed
the fix falsified the fix**. At `e9ee3b3` the old form printed
`mcp/README.md | 29 +++++++-----` (21 insertions, 8 deletions).

The published pathspec is now the shipped application only:

```
src mcp/tools mcp/server_entrypoint.py mcp/run_stdio.sh mcp/run_http.sh Dockerfile render.yaml requirements.txt
```

Derived from `git ls-files mcp` — the directory holds exactly `README.md`, `run_http.sh`,
`run_stdio.sh`, `server_entrypoint.py` and `tools/*.schema.json` (nine schemas), so the pathspec
names every code and script path under it and excludes the one document.

`git diff --stat 80a5a71..HEAD -- <the pathspec>` is **EMPTY at `89ae235`** (verified after
committing), and was empty at `edd99a4`, which is the sha the documents now print as the check date.
It is also empty for the older `8a89310..8782177` claim at `README.md:103`, which was updated to the
same pathspec for consistency.

Sites changed:

* `README.md:271-283` — fenced two-line command, **"It printed nothing at `edd99a4`, checked
  2026-09-22"**, plus two sentences saying the pathspec is the application tree and why naming `mcp`
  whole would make the check fail on a prose edit.
* `deployed.md:90-108` — same command (line-continued), the `# empty` annotation **dropped** in favour
  of the dated sentence, and a new short paragraph *Why that pathspec and not `mcp` whole* that
  records the near-miss honestly.
* `docs/pre-submission-checklist.md:53-57`, `docs/requirements-traceability.md` RUBRIC5.1 — narrowed,
  dated at `edd99a4`, each noting that documents sit outside the pathspec by design.
* `CHANGELOG.md` G5b entry 3 — narrowed and dated, with the review catch stated: the first draft said
  `-- src mcp …` and editing `mcp/README.md` made the published command print a path, "the same class
  of self-falsifying claim the re-grade opened with, caught in review".
* `CHANGELOG.md:933` deliberately keeps the **wide** form inside its quotation of what the four
  documents used to print — that sentence is the record of the false claim, and the entry says it
  returned two files from `3aa6650`.

## Important 2 — the demo script's source of truth

`docs/evidence/README.md:46` (the `-p29` row) now reads: it *was* the row the script's timings and
breadth came from until 2026-09-22 (46.8 s / 35 spans / 10 passages), and the script now reads
**38.2 s over 39 spans, 8 passages across four documents** off
`demo-task-1-live-2026-09-22.txt`. Checked against `docs/demo-script.md:197-198` ("cited **8 passages
across four documents**") and `:228-234` ("nine tool calls and seven retrievals over 39 spans") — read
only, not edited. The `demo-task-1-live-2026-09-22.txt` row now carries those same three figures and
says the script reads them from it.

## Important 3 — "the published build" on the two 8a89310 rows

`docs/evidence/README.md:57-58` now say **"on the build carrying round one's fixes — the published
build for the ten hours before `80a5a71` replaced it"** (task 1) and "on the build carrying round
one's fixes" (task 2), which matches the third row's pattern and the Build column. Task 2's row also
gained the two `mcp_discovery` spans at seq 1 and seq 27, the artifact behind mcp/README's per-pass
wording.

## Minors

* **4** — `mcp/README.md`'s *Why stdio still exists* names `tests/integration/test_mcp_discovery.py`
  (`initialize` + `tools/list`) **and** `tests/integration/test_mcp_tool_call.py` (a real `tools/call`
  on stdio and on the mounted HTTP loopback — its own docstring: *"Both halves of R5.2, on stdio **and**
  on the mounted HTTP loopback"*).
* **6** — the round-2 range reads "from `9dcd8dd` — the code, dataset, corpus and measurement work
  through `44e5e9f`, then the T12 documentation commits that follow it (`a0b37a6` onward)".
* **7** — every `deployed.md` run-history row is dated by the run file's own `created_at`:
  15:53:57Z, 19:49:28Z, 00:44:19Z, 22:57:30Z, 10:49:27Z, 09:08:05Z, 11:10:12Z and **20:59:49Z** for
  `r_1790110325_baseline`. A new sentence states the distinction (`r_<epoch>` is the drive's *start*,
  so this run began 20:52Z and closed 20:59:49Z), `NEEDS-FROM-USER.md` labels the four store-only
  drives' times as id-derived because they have no `created_at`, and `docs/evidence/README.md` now
  says "started 20:52Z, run file written 20:59:49Z".
* **8** — `README.md`'s ablation paragraph names **ten** flips and separates their causes: the judged
  clause (`expenses-002` passes on both arms), `remote-002` failing on both, five more failing only on
  `no_structured_tools`, and the behavioural one — `unsafe-001` **passes on `dense_only_k2`**, where the
  turn also called `search_policy_documents` (tool recall 1.00 against 0.75, doc recall 1.00 against
  0.00) and still stopped at the confirmation card, so nothing about safety moved. Read off the three
  run files' `items[].scores`.

## Concerns carried

1. **Still unguarded.** Nothing in the suite executes the published pathspec, so the next commit that
   touches an application path silently re-opens gap 1. This round is the second time the class bit;
   a contract test remains the durable fix and is outside this task's remit (no collected tests).
2. The daily Anthropic call cap on the live service (1,500/1,500 at 21:58Z) is unchanged from the
   first report.
