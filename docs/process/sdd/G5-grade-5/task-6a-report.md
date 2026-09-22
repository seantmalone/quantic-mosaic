# Task 6a — README, deployed.md, traceability, checklist, NEEDS-FROM-USER, corpus README, CHANGELOG

**Commit `1660a13`** on `main` (parent `d4f8ed9`, Task 6c's commit — no rebase, disjoint files).

Files touched (explicitly added, nothing else): `README.md`, `deployed.md`,
`docs/requirements-traceability.md`, `docs/pre-submission-checklist.md`, `NEEDS-FROM-USER.md`,
`corpus/README.md`, `CHANGELOG.md`. **`mcp/README.md` and `mock_data/README.md` were read and left
unchanged** — see *Concerns* 4. `design-and-evaluation.md` and `docs/demo-script.md` were never
opened for writing (they were dirty in the working tree from the concurrent tasks and are not in the
commit).

## Per gap, what changed

### Gap 1 (README part) + the traceability/checklist rows naming the published run

| Where | Change |
|---|---|
| `README.md:236-241` | `**The published run** is r_1790074972_baseline (2026-09-22)` — 28 items, `target: deployed`, judged by `gemini-3.5-flash-lite` over **268** judge calls, served by `8a89310`; `latest.json` names it and `paste_eval_numbers.py --check` exits 0 |
| `README.md:243-254` | the before/after table: "Before" column unchanged (`r_1789055103_baseline`), published column re-read from the new run file, with a new `Citation resolvability` row |
| `README.md:257-263` | the small-n disclosure: clarification 1.000 over **3** items, action safety 1.000 over **1** item, and why the blind 1.000 discriminates nothing |
| `README.md:265-269` | the three strict-pass failures with their §13.8 clause |
| `README.md:271-279` | the ablation paragraph: both arms on `8a89310`, the two deltas, and the **not supported** hypothesis |
| `deployed.md:48-49` | the published run's two shas → `8a8931076bac9d271f8a03da7ecfa0d3a723d811` |
| `deployed.md:63-66` (table rows) | the serving-commit ledger gains `r_1789555212_baseline` (`bd4ac93`, 2026-09-16), `r_1790067656_baseline` (`e85305b`, 2026-09-22 09:08Z, superseded) and the published `r_1790074972_baseline` (`8a89310`, 11:10Z); the 2026-09-11 row loses its bold |
| `deployed.md:19-20` (table) | the eval rows' *Observed* column: "2026-09-11, re-driven 2026-09-16 and again 2026-09-22 on the final build" / "re-pasted 2026-09-22" |
| `docs/requirements-traceability.md:219` (RUBRIC5.1) | re-verified on the new run: groundedness **0.963 (n = 18)** ≥ 0.90, `cit_resolve_mean` **1.000 (n = 28)** ≥ 0.95, strict pass **0.893** ≥ 0.85; failing items now `remote-002` / `expenses-002` / `equipment-001`; "pointed at by `latest.json`" is true again |
| `docs/requirements-traceability.md:212` (DOCS.10 row) | the log's four judged columns are kept as history, with one added sentence saying they are the run that measured each wave, not the published headline — `latest.json` names `r_1790074972_baseline` |
| `docs/requirements-traceability.md:4` | header: statuses re-read against the final build at the 2026-09-22 publish |
| `docs/pre-submission-checklist.md:36-40` | the run box: re-done 2026-09-22, `r_1790074972_baseline`, 28 items, judged, strict pass 0.893, driven and served by `8a89310`, `--check` exits 0 |
| `docs/pre-submission-checklist.md:13-25` | both grade cards are named (2026-09-11 and 2026-09-21), what the second one capped the build on, and that the run box is the receipt |

Every DEMO.*/SUB.* box is untouched and unticked except the pre-existing `- [x] SUB.3`.

### Gap 6 — `make ingest`

- `README.md:37-49`: `make ingest` immediately after the `make setup` paragraph, with the reason —
  `data/index/` is git-ignored apart from `chunks.manifest.jsonl`, `rag/index.py` raises rather than
  indexing on demand, so a fresh clone boots and `/health` answers 200 while every question comes
  back a failed turn. No credential needed (local ONNX embeddings, fastembed's cache).
- `README.md:53-54`: `make ingest` as the first line of the `## Local Run` block, before `make run`.
- No timing figure is published: I did not run `make ingest` (it would rewrite
  `data/index/hr_index.sqlite` under the other agents' concurrent test runs), so the "~30 s" from the
  gap text is not stated.

### Gap 7 — the demo-script paragraph

`README.md:88-97` carries Task 3's sentence verbatim (the scripts fetch the server-dated prompt, so
the verdicts hold against the deployed service), plus one sentence on `--recorded` /
`DEMO_RECORDED=1`. **I did not copy Task 3's last clause as written**: `make demo1` / `make demo2`
do *not* pass `--recorded` (`Makefile` `define demo` → `sh scripts/demo_task_1.sh` with
`MOCK_TODAY=2026-09-01`), so the README says the targets do not need the flag because the prompt they
fetch comes back byte for byte the recorded one — which is what `scripts/demo_task_1.sh:18-26` says.

### Gap 15 — the evaluation recipe

`README.md:200-232`: `make eval` = `python -m evaluation.runner --variant baseline`, drives only
(`--judge-inline` off by default, quoting the runner's own reason), then the seven-line sweep —
drive → judge → the two variants → `make ablation` → `--report <run_id>` →
`scripts/paste_eval_numbers.py` — with the credential each step needs (`APP_ACCESS_TOKEN`,
`JUDGE_API_KEY`, and the service's `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` because both passes read
the turn back out of the same store, with the runner's backend mismatch check named), the note that
**every drive rewrites `REPORT.md`** and `--report` restores it, and one line for `--cold-probes` and
`--recompute-agreement --metric … --labels …`. Flags verified against
`.venv/bin/python -m evaluation.runner --help`.

### Gap 22 — the live sha in a document

`deployed.md:73-81`, new paragraph *What is serving right now*: the `/health` read of **2026-09-22
11:52Z** — `app.git_sha 8a8931076bac9d271f8a03da7ecfa0d3a723d811`, `status: ok`,
`deploy_mode: render`, `mcp.connected: true` with 9 tools, 14 docs / 204 chunks,
`trace_store.backend: turso`, `degradations[]` empty — plus the fact that
`git diff 8a89310..HEAD -- src mcp Dockerfile render.yaml requirements.txt` is empty, so a later sha
on `/health` is a rebuild of the same application tree. (I did **not** dispatch CI; that half of
gap 22 is an operator action.)

### Gap 24 — the dashboard-only runs

`NEEDS-FROM-USER.md:199-215`: the step-4 check is now `eval_runs_imported ≥ the committed count`
with `ls evaluation/results/r_*.json | wc -l` beside it, and a paragraph saying why they differ —
**25 imported against 22 committed run files**, read 2026-09-22 11:52Z — naming the three drives
with no committed file (`r_1790062696_baseline` this wave's pre-fix diagnostic drive;
`r_1789547562_baseline` `6355c41` and `r_1789534779_baseline` `1a2a8fb`, both 2026-09-16) and why
none can be reconstructed (`GET /api/eval/runs/{run_id}` serves the view-model, no `dataset_sha`, no
`target_git_sha`). The *Which gate produced what* table's two rows follow (`r_1790074972_baseline`
on `8a89310`; "at least the committed run-file count, with the published run among them"). I did not
publish the uncommitted runs' metrics — no committed artifact carries them.

### Gap 26 — the trace store as a hard dependency

`deployed.md:374-395`, new `### The hosted trace store is a hard dependency of /chat`: `PERSIST_BACKEND`
at `auto` is resolved **once at boot** by `core/db.py::build_store()` (verified at
`src/hrmosaic/core/db.py:314-324` — no retry, no demotion); an unreachable Turso makes the
end-of-turn flush raise, the composed answer is discarded and the reader gets the typed 200
`INTERNAL_ERROR` turn (`api.py:1450` `INTERNAL_ERROR_TEXT`, `api.py:1488-1530`), with
`tests/contract/test_unmodelled_failure_is_graceful.py` patching `store.batch` as the pin;
`/health` reports `trace_store.reachable: false` (`api.py:2176-2192`) and the soft degradation
`trace_store_unreachable` (`api.py:2091`); `PERSIST_BACKEND=sqlite` is the one-variable recovery,
with the ephemerality of that file stated.

### Gap 27 — the figures in my files

| Figure | Was | Now | Verified by |
|---|---|---|---|
| `corpus/README.md:18` fact count | "~56" | **58** | `.venv/bin/python scripts/check_facts.py` → `14 documents · 58 facts · 7 rule scenarios · 34 requirements`; `corpus/facts.yml`'s `facts` map has 58 keys |
| `corpus/README.md:255` | "Roughly fifty-six entries" | **58** entries, naming the script that prints it | same |
| `docs/requirements-traceability.md:50` (PD.1) | "~63 pages" | **64.2 pages**, "the figures `scripts/corpus_stats.py` prints" | `.venv/bin/python scripts/corpus_stats.py` → `14 files · 64.2 pages · 31,007 words` |
| `README.md:62-63` suite as-of date | 2026-09-15 | **2026-09-22** | `.venv/bin/python -m pytest --collect-only -q -p no:cacheprovider -m ""` → `3410 tests collected`; `-m ux` → `299/3410` — so 3,410 and 299 are unchanged and only the date moved |

### CHANGELOG.md

Three dated bullets appended in the file's current style (dated bullets, not `##` headings, which is
how everything after P10 fix round 4 is written):

1. **2026-09-21 — what the grade found**: the 82-agent read-only pass at `98c893f`, band 4 at the top
   of the band, the two published runs and the eight drifted figures, `--check` exiting 1, the three
   secondary caps, and the committed card + gaps json + plan (`82994ce`).
2. **2026-09-22 — what each task changed**: Tasks 1 (`2557d0c`, `e4007f1`), 1b (`5b66ee6`,
   `e85305b`), 1c (`54a2895`, `dcc5d9c`, `8a89310`), 2 (`b0261d6`), 3 (`7678e0c`, `e923bc3`,
   `ef917a3`), 6d (`e348655`, `501e18d`, `c427b15`), 4 (`e353a3d`), 5 (`8782177`), and 6a–d named by
   their commit subjects rather than by shas that did not exist yet. Descriptions are the commit
   subjects plus the ledger's own wording.
3. **2026-09-22 — the published run**: every headline figure with its `n`, the strict-pass causes, the
   two agreement figures, the unsupported ablation claim, $0.773 / 439.9 s, and the list of documents
   republished from it, ending with the suite census (3,410 collected; 3,111 in `make test`, 299 in
   `make ux`).

## Figures, and the artifact each came from

| Figure | Artifact |
|---|---|
| run id `r_1790074972_baseline`, `target: deployed`, 28 items, judge `gemini-3.5-flash-lite`, 268 calls, `$0.7731`, 439.9 s, both shas `8a8931076bac…` | `evaluation/REPORT.md` header + `evaluation/results/r_1790074972_baseline.json` |
| strict 0.893 · groundedness 0.963 (18) · citation accuracy 0.875 (18) · cit resolve 1.000 (28) · doc recall 0.947 (19) · tool selection 0.993 · workflow 0.964 · refusals 0.000/0.000 · clarification 1.000 (3) · action safety 1.000 (1) | `evaluation/REPORT.md` *Headline metrics* + `metrics`/`n_scored` in the run file |
| p50 15.3 s / p95 26.0 s | run file `latency_p50_ms 15314.0`, `latency_p95_ms 26035.0` |
| agreement 1.000 (n = 8, `seed_1729_8`, blind) and 0.875 (n = 8, `judge_lowest_8`, disclosed), disagreement `expenses-002` | `evaluation/REPORT.md` judge-methodology section; run file `judge_agreement_rate` / `_hard` |
| strict-pass causes `remote-002` / `expenses-002` / `equipment-001` | `evaluation/REPORT.md` causes table (`deterministic.strict_pass_causes()`) |
| `remote-002`: 2 distinct docs against an end state needing 3, 2 of 4 gold docs | run file item `remote-002` (`doc_recall 0.5`, `workflow 0.0`) + `evaluation/dataset.yaml` (`min_distinct_docs: 3`, four `expected_docs`) |
| ablation 0.929 / 0.786 strict, 0.964 / 0.821 workflow, delta −0.143, **not supported** | `evaluation/REPORT.md` ABLATION block + `evaluation/results/comparison.json` |
| "Before" column figures (0.692, 0.979, 0.847, 0.923, 0.855, 0.926, 0.769, 0.111/0.000, 17.6/47.7 s) | `evaluation/results/r_1789055103_baseline.json` — the table's existing column, re-checked rather than re-typed |
| run history shas `bd4ac93`, `e85305b`, `8a89310` and the two 2026-09-22 timestamps | the three run files' `target_git_sha` / `created_at` |
| live `/health` payload, 2026-09-22 11:52Z | `curl -s https://mosaic-hr-copilot.onrender.com/health` (public route, GET only) |
| 25 imported vs 22 committed | the same `/health` read; `ls evaluation/results/r_*.json` → 22 |
| 58 facts · 64.2 pages · 31,007 words | `scripts/check_facts.py`, `scripts/corpus_stats.py` |
| 3,410 / 299 / 3,111 tests | `pytest --collect-only -q -m ""` and `-m ux` |
| grade-card facts (band 4, 82 agents, the two published runs, 0.333 clarification) | `docs/evidence/grade-card-2026-09-21.md` |
| task shas and one-line descriptions | `git log --oneline 98c893f..HEAD`, the wave ledger `progress.md` |
| trace-store mechanics | `src/hrmosaic/core/db.py:314-324`, `src/hrmosaic/web/api.py:1450,1488-1530,2091,2176-2192`, `tests/contract/test_unmodelled_failure_is_graceful.py:102-125` |

## Tests

```
.venv/bin/pytest -q -p no:cacheprovider tests/contract
554 passed in 175.06s
```
(re-run after the last three edits — see the commit message's own note; both runs green.)
`.venv/bin/python scripts/paste_eval_numbers.py --check` → `OK`, exit 0.

## Concerns

1. **The video line could not be phrased exactly as the brief asked.** `Demo video: link added at
   submission` fails **two** contract tests:
   `tests/contract/test_readme_headings.py::test_three_link_lines_are_present_and_filled` requires
   `https://` or `^pending: gate \d`, and
   `test_docs_completeness.py::test_demo_video_link_is_recorded_or_names_an_open_gate` requires the
   pending value to name a gate `NEEDS-FROM-USER.md` still lists as open. Line 11 therefore reads
   `Demo video: pending: gate 6 — the walkthrough is recorded from docs/demo-script.md and its link
   is pasted on this line at submission`: reader-facing after the marker, but the marker is still
   there. Removing it means editing a test I do not own.
2. **`deployed.md`'s "the last commit to change application code" is true at this commit and could
   age.** It is stated with the command that checks it (`git diff 8a89310..HEAD -- src mcp Dockerfile
   render.yaml requirements.txt`) and dated, but Task 5b (the gap-9 schema binding) is planned for
   `evaluation/` after this wave; that path is deliberately not in the diff list, so the sentence
   stays true, while a *later* app change would falsify it. Whoever lands one should re-read that
   paragraph and the live sha.
3. **This commit touches `corpus/README.md`, which is not covered by `ci.yml`'s `paths-ignore`**
   (`*.md` does not cross a `/`), so pushing it triggers a full CI run **including `deploy`**. That
   is harmless — the image is built from an unchanged application tree — but it will move the live
   `/health` `git_sha` off `8a89310` to this commit, which is exactly what concern 2's paragraph
   covers in advance. If the controller wants `/health` to keep reporting `8a89310`, do not push this
   commit alone with a deploy, or re-read the sha afterwards.
4. **`mcp/README.md` and `mock_data/README.md` needed nothing.** I checked both against the live
   artifacts: `mcp/README.md`'s error-semantics table already states `isError: true` with the
   validator's text (gap 16's wording, which is 6b's file), the nine tools match `/health`'s
   `tool_names`, and the host-allowlist section matches `render.yaml`; `mock_data/README.md`'s counts
   (24 records × 4 files, 2 calendars, 6 schemas) match the directory and are already asserted by
   `tests/unit/test_mock_schemas.py` / `test_pto_balance_arithmetic.py`. `MCP_TOOLS_DISABLED`
   (Task 3) is an **agent-side** filter (`agent/router.py:201-211`), not a server-side one, so it
   does not belong in the MCP server's README.
5. **`docs/requirements-traceability.md`'s row census was not recomputed.** The header still says
   72 built + 4 verified + 1 done + 10 planned = 87, and I changed no row's *Status*, so the census
   is unchanged — but RUBRIC5.1's cell now says "re-verified 2026-09-22", which is a stronger claim
   than the summary paragraph's date. Cosmetic.
6. **Gap 22's other half is untouched**: `docs/evidence/mcp-external-session-2026-09-12.txt:8`,
   `docs/evidence/final-2026-09-16/README.md:1` and `docs/evidence/cold-start-probes.json:5,17`
   still each call a different sha "the final build". Those files are not in Task 6a's ownership
   list.

---

# Fix round 1

**Commit `90498b8`** on `main` (parent `f1dcb34`). Five files, explicitly added: `README.md`,
`deployed.md`, `docs/pre-submission-checklist.md`, `docs/requirements-traceability.md`,
`CHANGELOG.md`. `design-and-evaluation.md`, `docs/optimization-log.md` and `docs/architecture.html`
were dirty in the tree from the concurrent tasks and are not in the commit.

## Important 1 — the measured build is dated, not asserted live

The reviewer is right: `/health`'s sha moves with every push that clears `ci.yml`'s `paths-ignore`,
so "the build the live service reports" cannot be written in a committed document. All four places
now state the *relation*, which is checkable at any commit:

- `README.md:243-249` — "driven and served by build **`8a89310`**: the run file records that sha as
  its `target_git_sha`, and the live `/health` still reported it at 11:52Z that day. Later commits on
  `main` change documentation, evaluation tooling and tests only, so the sha `/health` reports may
  have moved on while the application tree is identical —
  `git diff 8a89310..HEAD -- src mcp Dockerfile render.yaml requirements.txt` is empty; `deployed.md`
  carries the reading and the ledger behind it."
- `docs/pre-submission-checklist.md:38-46` — the run box says "measured on build `8a89310`" and
  carries the same two-clause relation plus the pointer to `deployed.md`.
- `docs/requirements-traceability.md:219` (RUBRIC5.1) — "measured on build `8a89310` — the run file's
  own `target_git_sha`, read from the service's `/health` while the run was driven — … later commits
  on `main` are documentation, evaluation tooling and tests only, so the live sha may differ while
  `git diff …` stays empty — see `deployed.md`".
- `deployed.md:73-85` — the heading is now **What was serving at 2026-09-22 11:52Z** (a reading, not
  a present-tense claim), and a second paragraph, *The live sha moves; the application tree does not*,
  states why (`paths-ignore`, a deploy per qualifying push) and what is invariant (`8a89310` is the
  last commit to change application code; a later sha is a rebuild of the identical tree with
  documentation, evaluation tooling and tests on top).

Re-verified at `f1dcb34`: `git diff --name-only 8a89310..HEAD` lists only `*.md`,
`docs/architecture.html`, `evaluation/**` (results, `REPORT.md`, label files, `runner.py`,
`schema.py`) and two test files — no `src/`, `mcp/`, `Dockerfile`, `render.yaml` or
`requirements.txt`, so the diff named in all four places is empty. That is why the wording says
"documentation, evaluation tooling **and tests**" rather than "documentation only".

## Important 2 — the sweep block is copy-pasteable

`README.md:207-224`. The four exports the recipe needs now sit above the commands in the same fenced
block, and the inline `EVAL_TARGET_BASE_URL="$DEPLOY_URL"` prefix is gone:

```bash
export EVAL_TARGET_BASE_URL="$DEPLOY_URL"   # the target every drive below talks to
export APP_ACCESS_TOKEN="<the service's token>"
export TURSO_DATABASE_URL="<the service's>" TURSO_AUTH_TOKEN="<the service's>"
export JUDGE_API_KEY="<the judge project's key>"
```

and the prose above the block names the failure the reviewer found: "a `--variant` line that inherits
`.env`'s local default drives `target: local`, and `make ablation` then refuses to compare a local
arm with a deployed baseline."

## Minor — decimals

`README.md:254-255`: both judge-agreement rows read three decimal places
(`1.000 (n = 7)` / `1.000 (n = 8)` in the Before column). The values are the run file's own
`judge_agreement_rate` 1.0 (n = 7) and `judge_agreement_rate_hard` 1.0 (n = 8) from
`evaluation/results/r_1789055103_baseline.json` — the rendering changed, not the figure.

## Not asked for, but done in the same pass

`CHANGELOG.md:931`: the entry's suite census is anchored to when it was written
("Suite when this entry was written (2026-09-22, at `1660a13`): **3,410 collected** …, the
reference-label binding added later the same day took it past that") rather than to "this commit",
because Task 5b took the suite to **3,415** (`pytest --collect-only -q -m ""`) after my first commit.
`README.md:62` and `docs/requirements-traceability.md:147` were already re-synced to 3,415 by Task 5b
and I left them alone.

## Tests

```
.venv/bin/pytest -q -p no:cacheprovider tests/contract
555 passed in 174.38s
```
(554 → 555: Task 5b's new label-binding contract test.)
