# Task 8 — the sweep: the leftovers the reviewers found outside their own files

**Scope.** Nine items (eight from the brief, one added mid-task by the controller). Files touched:
`design-and-evaluation.md`, `docs/requirements-traceability.md`, `docs/evidence/README.md` (new),
`docs/evidence/grade-card-2026-09-21.md` (header only), `ai-tooling.md`, `docs/optimization-log.md`,
`deployed.md`, `docs/process/sdd/G5-grade-5/` (new, 28 files). Not touched: `README.md`,
`docs/demo-script.md`, the 2026-09-22 transcripts, `evaluation/runner.py`, any test file.

---

## 1 — Span-rail leakage

The chat page since UX W2 is one conversation column with the **Sources (n)** strip, the confirmation
card and one `#turn-status` line; the SSE stream feeds that line and the answer deltas; tool names,
arguments and outputs are on `/dashboard/sessions/{id}`. Verified against
`src/hrmosaic/web/templates/chat.html` (`id="turn-status"`, no rail; the only `role="status"` on the
page), `_turn.html:213` (`Sources ({{ turn.citations | length }})`), `_demo_controls.html:93`
(`dashboard_url` behind *"Open this conversation in the dashboard"*), and
`tests/contract/test_chat_page_renders.py`, which asserts the `<select>`, both demo buttons,
`id="turn-status"`, `html.count('role="status"') == 1`, no `aria-live`, no `class="badge`, the
`answer-block-*` sections, the literal footnote and source links matching `/policy/…#c_…`.

* `design-and-evaluation.md:40` — mermaid `UI` node: `act-as selector · citation chips` /
  `live span rail (SSE) · confirm card` → `act-as selector · Sources (n) strip` /
  `status line + streamed answer (SSE) · confirm card`.
* `design-and-evaluation.md:118` — the five-readers table: *"the live span rail the demo narrates
  from"* → *"the one in-flight status line, and the answer as it is written"*.
* `docs/requirements-traceability.md:122` (**R6.2**) — spec column now lists the Sources strip and the
  one `#turn-status` line and records that UX W2 deleted the 22 rem rail and the trace panel (§11.5
  itself says so); the verification column now describes what the test actually asserts, including
  the single `role="status"`, the absence of `class="badge`, and the W1 reader deep link
  `/policy/{doc_id}#{chunk_id}` in place of "citation chip whose href is the chunk's `source_url`".
* `docs/requirements-traceability.md:126` (**R6.6**) — requirement text *"and the rail narrates each
  step"* → *"and one status line narrates each step"*.
* `docs/requirements-traceability.md:184` (**DEMO.6**) — spec column: *"the SSE span rail is the
  narration surface"* → the SSE stream is the **in-flight** narration surface (one status line) and
  the surface showing tool names/arguments/outputs is the session record; verification column now
  says the status line narrates while the turn runs and `/dashboard/sessions/{id}` — reached by the
  `dashboard_url` link — shows tool names, durations and expanding payloads, a source link jumping
  into the policy reader. This matches `docs/demo-script.md`'s own split (④⑤ on the chat page, ①–③ on
  the record).

**grep for `rail` afterwards.** `design-and-evaluation.md`: only `guardrail` / `audit trail`.
`docs/requirements-traceability.md`: only `guardrail`, `trailer`, and the two deliberate historical
mentions inside R6.2's new text. **Not changed, and why:** `docs/optimization-log.md:350`, `:353`,
`:368` narrate a 2026-09-11 browser session under a dated heading, three days before W2 existed; the
log is excluded from the number guard for exactly that reason (`NUMBER_DOCS` in
`test_docs_completeness.py`) and rewriting dated history would be the wrong fix.

## 2 — `docs/evidence/README.md` (new)

An index of **all 40 top-level artifacts** (files and directories) in date order, with `Date`,
`Build` and `What it shows`. It opens by naming the three headers that each call a different sha *"the
final build"* — `f5e86c3` (2026-09-12), `bd4ac93` (2026-09-16), `da0dca2` (cold-start probes 2–3,
Waves 1–2) — instructing the reader to read any such header as *final as of that date*, and states
that the published evaluation run measures **`8a89310`** (`r_1790074972_baseline`, the run
`latest.json` points at). No transcript and no JSON was edited.

Builds come from each artifact's own header where it states one (`e13a772`, `f5e86c3`, `4058404`,
`ebd665a`, `d8a2ca3`, `bd4ac93`, `bf85ffd`/`da0dca2`, `8782177`, the session JSONs' `app_version`),
and otherwise from `git log --diff-filter=A -1 --` on the path, quoted as "added at `<sha>`". Both
grade cards are in the table (`grade-card-2026-09-11.md`, `grade-card-2026-09-21.md` and its gaps
JSON), as are the three 2026-09-22 transcripts Task 7a added — they existed on disk when this index
was written and were committed at `e6ece93` before this commit, and a line under the table marks them
as the wave's own live re-capture. Two honesty notes are included: there is no `ux-w5/` (W5 was the
accessibility pass; its evidence is tests plus the dark captures in `ux-final/`), and `ux-final/` is
the **W5-era** set, not the last screens taken.

One row was added to `design-and-evaluation.md`'s `## Evidence` table pointing at the new index, so it
is reachable from the graded document.

## 3 — Grade-card header

`docs/evidence/grade-card-2026-09-21.md:3`, one new line after **Graded:**, body byte-identical
(`tail -n +4` of the card diffs clean against `grade-report.md` apart from the separator). It states
that the wave's fixes landed as the `G5(…)` commits between `98c893f` and the tip of `main` — **26
through `e947ecd`**, with `git log --oneline 98c893f..HEAD | wc -l` given as the recount at any later
tip — and that every ranked gap's status is in `docs/process/sdd/G5-grade-5/progress.md`. The count is
anchored to a sha rather than stated as "N at HEAD" because three agents were committing to `main`
concurrently (it was 26 when the line was written, 28 by the time this task committed).

## 4 — `ai-tooling.md`

* `:3` — **Period:** `2026-09-08 → 2026-09-21` → `2026-09-08 → 2026-09-22`.
* §8's closing sentence (`:337-338`) — *"…are in the git-ignored `.superpowers/sdd/` working directory
  until the wave's process trail is copied into `docs/process/sdd/`…"* → they **are** committed, copied
  verbatim into `docs/process/sdd/G5-grade-5/`, with that directory's README naming what was left out
  and how everything was scanned first; plus one clause recording that every implementer, reviewer and
  re-reviewer subagent in the wave was dispatched with `model: opus`.
* `:277` — the suite-size line **verified, not changed**: `.venv/bin/pytest --collect-only -q -m ""`
  reports **3415** (`-m ux` reports `299/3415`, so 3,116 + 299), and the as-of date stays 2026-09-22.
  `test_docs_completeness.py`'s suite-size test passes over all four `NUMBER_DOCS`.

## 5 — Process trail copy

`docs/process/sdd/G5-grade-5/` = `progress.md`, `grade-report.md`, `gaps.json`, `run_eval.py`,
`measure.sh`, 9 `task-*-brief.md` (1, 1b, 1c, 2, 3, 4, 5, 5b, 6) and 13 `task-*-report.md` (1, 1b, 1c,
2, 3, 4, 5, 5b, 6a–6e), plus an authored `README.md` in the style of `docs/process/sdd/README.md`.
`cmp` is clean on every copied file, so the copy is verbatim. Tasks 7a and 8 were briefed in their
dispatch messages, not in files, so they have no brief; this task's own report is left for the wave's
final commit, which re-copies the ledger anyway — the README says both things.

Deliberately **not** copied, and said so in the README: `labels-seed-final.yaml`,
`labels-hard-final.yaml` and the four `packet-*.md` (served answers + evidence; the committed
`evaluation/reference_labels*.yaml` carry the labels), the eleven `measure-*.log` (provider
endpoints), the sixteen `review-*.diff` (reproducible as `git diff`, tens of MB — the same exclusion
the P0–P27 trail makes), and `confirmed-gaps-raw.json`.

**Secret scan — clean.** Every copied file was grepped for `sk-`, `AIza`, `rnd_`, `ghp_`, `xox[baprs]-`,
`Bearer `, `eyJ`, `-----BEGIN`, `TURSO_AUTH`, `access=`, `libsql://`, `turso.io`,
`generativelanguage`, `api.anthropic.com`, the README `?access=` token **by exact match** (43 chars),
and `[A-Za-z0-9_-]{32,}` with hex ids filtered out. Findings: the `sk-` hits are all the substring in
`task-`; `AIza`/`ghp_`/`xox` appear only inside `task-6d-report.md`'s own list of shapes it scanned
for; `Bearer ` only as `Authorization: Bearer $APP_ACCESS_TOKEN`; `TURSO_AUTH_TOKEN` only as a
variable name (`run_eval.py:28`, `task-6a-report.md:60`, and `:244`'s `"<the service's>"`
placeholder); `access=` only as `run_eval.py`'s regex and one *"append `?access=<the README token>`"*
instruction; every 32-char-plus run is a test function name, a spec filename or a run id. **The live
access token appears nowhere.** No `rnd_`, no JWT, no private-key header, no provider URL. The two
helpers were read line by line: `run_eval.py` loads `data/runtime/provision_turso.json` **by path**
into `os.environ` and prints nothing; `measure.sh` only sequences `run_eval.py` invocations. Neither
contains a token or key string. `gitleaks` is not installed in this environment, so the scan is the
grep set above; `ruff check` and `ruff format --check` pass on the copied `run_eval.py` (it is now a
tracked `.py` file and `extend-exclude` only covers `*.md`).

## 6 — `docs/optimization-log.md:739`

**Anchored rather than bumped:** `3,111 + 299` → `3,111 + 299 (collected at `1660a13`)`. That figure
is exactly what the suite collected at `1660a13` (its README says 3,410 = 3,111 + 299), and Task 5b
was adding tests to `tests/unit/test_hard_case_agreement_subset.py` while this task ran, so a bumped
figure in a dated log would have gone stale within the hour. The rest of that table was checked
against `evaluation/results/r_1790074972_baseline.json` and **every other cell is right**: strict pass
0.893 (25/28 — three items fail), groundedness 0.963, citation accuracy 0.875, partial match 0.801,
document recall 0.947, tool selection 0.993, workflow completion 0.964, clarification 1.000, 0/0
over/missed refusal, action safety 1.00, judge agreement 1.000 (n=8) and 0.875 (hard n=8), p50 15.3 s
/ p95 26.0 s, cost **$0.773082 → $0.77**, ablation −0.1429 → −0.143 (`comparison.json`), and the
failing items are `remote-002`, `expenses-002`, `equipment-001` (the three with `passed: false`).

## 7 — Traceability header census

Recounted mechanically from the last cell of every table row: **89 rows** — 72 `built`, 6 `verified`,
1 `done`, 10 `planned — verified at publish`. Of the 6 `verified`, two are the project-added rows
(**R6.6**, **DOCS.10**), so within the 87 checklist items it is 72 + 4 + 1 + 10 = 87, which is what the
header already claimed and what the four named `verified` rows (R7.1, SUB.2, RUBRIC5.1, RUBRIC5.6) and
the one `done` row (SUB.3) are. **The numbers were already correct**; what was missing was the
accounting for the two extra rows, so the paragraph now also states the 89-row split, and the date
line now says the statuses were *recounted row by row* at the 2026-09-22 publish rather than merely
*re-read*.

## 8 — `TBD` / `TODO` / `pending:` / `XXX` / stale suite counts

Swept `README.md`, `design-and-evaluation.md`, `deployed.md`, `ai-tooling.md`, `docs/*.md` and
`evaluation/REPORT.md`.

* No `TBD`, `TODO` or `XXX` anywhere except as the **name** of the retired `TBD-before-submission`
  placeholder inside three verification cells and one checklist line, all of which describe a guard
  that asserts the placeholder is gone. Left alone.
* `pending:` — two. `README.md:11` is the video line and must stay `pending: gate 6 …`. The other was
  `deployed.md:580`, a bare `` `pending: an authenticated AI Studio session`. `` line; it is a real
  blocked state, not an unfinished document, so the fact is kept and the machine-placeholder form is
  gone: *"So the row waits on an authenticated AI Studio session, not on a measurement this project
  could take."* (`docs/process/sdd/P14-report.md` quotes the old string as content P14 kept; a dated
  report is not falsified by a later documentation fix.)
* **No stale suite count** — none of 3,339 / 3,352 / 3,367 / 3,370 / 3,383 / 3,389 / 3,392 / 3,396 /
  3,398 / 3,401 / 3,405 / 3,409 / 3,410 appears in any of those files, with or without the comma.

## 9 — Added by the controller mid-task: the `refused` outcome disclosure

`design-and-evaluation.md` `### Known limitations`, new **item 12**. A cancelled (or failed) confirmed
write closes the turn as `refused`: `TurnOutcome` (`src/hrmosaic/core/models.py:38`) has no value for
*"the write did not happen because the person said no"*, and a `draft_hr_email` turn retrieves
nothing, so `_refuse` finishes it with `outcome="refused"` and a `G1_evidence_gate verdict=refuse`
span even though task 1c's fix makes the **receipt replace** the gate's sentence
(`orchestrator.py:2987-3001`). The served answer is right; the filing is not. Evidence:
`docs/evidence/draft-hr-email-live-2026-09-22.txt` — the cancelled turn shows `outcome: refused`,
span 14 `verdict=refuse`, one `notice` block (*"Cancelled — nothing was created."*), no
`draft_hr_email · ok` span, and a write ledger that agrees nothing was created. The item names the fix
— a dedicated `TurnOutcome` value carried through the store, the `/chat` contract and the dashboard's
outcome column and filter — as a schema change deferred beyond this wave. The item's lead says "not a
run figure but a live finding" so it does not contradict the list's own preamble that every item is
read off `r_1790074972_baseline`.

---

## Commit

`a040074` — *G5(sweep): the leftovers the reviewers found outside their files — span rail, evidence
index, the process trail*. 35 files, +4,178 / −12, trailer `Co-Authored-By: Claude Fable 5.1`, no
`Claude-Session` trailer. Staged by explicit path; nothing from Task 7a or Task 5b is in it.

## Verification

```
$ .venv/bin/python scripts/paste_eval_numbers.py --check
OK — the results table matches evaluation/results/latest.json

$ .venv/bin/pytest --collect-only -q -m ""        → 3415 tests collected
$ .venv/bin/pytest --collect-only -q -m ux        → 299/3415 tests collected (3116 deselected)

$ .venv/bin/ruff check docs/process/sdd/G5-grade-5/run_eval.py          → All checks passed!
$ .venv/bin/ruff format --check docs/process/sdd/G5-grade-5/run_eval.py → 1 file already formatted

$ .venv/bin/pytest -q -p no:cacheprovider tests/contract
555 passed
```

## Concerns

1. **`ai-tooling.md`'s 3,415 will need a bump if Task 5b's new tests land after this commit.** It was
   exact at commit time (and `test_docs_completeness.py` holds all four `NUMBER_DOCS` to the collected
   count, so CI will catch it). Task 5b's brief already owns that bump.
2. **`progress.md` and `task-5b-report.md` were still being written** when they were copied. The copy
   is verbatim as of this commit; the wave's **final commit** must re-copy `progress.md` and bring
   across the reports written after it, including this one — the new README says so in as many words.
3. `docs/optimization-log.md:350/353/368` still say "the rail" inside a 2026-09-11 dated entry. Left
   as history on purpose (see item 1).
4. The evidence index's `Build` column is "added at `<sha>`" for the screen sets, because their own
   READMEs record a harness, a date and sometimes a `before-` commit rather than a service sha. Every
   such value comes from `git log --diff-filter=A`, and the header says that is how it was filled.
