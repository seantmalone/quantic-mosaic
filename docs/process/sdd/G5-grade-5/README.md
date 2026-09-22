# The grade-and-fix wave — briefs, reports and the ledger (2026-09-21 → 22)

This directory is the **committed audit trail** behind the wave that worked through the independent
grade card of 2026-09-21 ([`docs/evidence/grade-card-2026-09-21.md`](../../evidence/grade-card-2026-09-21.md),
ranked gaps in [`grade-card-2026-09-21-gaps.json`](../../evidence/grade-card-2026-09-21-gaps.json)).
It is a verbatim copy of the working directory that wave ran out of — `.superpowers/sdd/2026-09-21-grade-5/`,
which is git-ignored — so a reader can check `ai-tooling.md`'s disclosure against the artifacts
rather than take it on trust. Nothing below was edited on the way across; `cmp` says so file by file.

The plan these documents implement is tracked at
[`docs/superpowers/plans/2026-09-21-grade-5.md`](../../superpowers/plans/2026-09-21-grade-5.md), and
the fixes themselves are the `G5(…)` commits from `98c893f` onward.

## What is here

| File | What it is |
|---|---|
| `progress.md` | The ledger: every ruling, every task's implemented / reviewed / fix-round / complete lines with their commits, and the status of each ranked gap |
| `task-<n>-brief.md` | The requirements handed to the implementing session for that task — written before the diff |
| `task-<n>-report.md` | What that session changed, the command output pasted verbatim, its self-review and the concerns it raised |
| `grade-report.md` | The grading workflow's own report, of which the committed grade card is the copy |
| `gaps.json` | The machine twin of the ranked gap list, the same file as `docs/evidence/grade-card-2026-09-21-gaps.json` |
| `run_eval.py` | The operational helper the measurement chain ran through: it loads the Turso handoff **by path** into the process environment, reads the `?access=` token out of `README.md`, and prints nothing |
| `measure.sh` | The sequential chain Task 4 measured with — baseline drive, judge pass, both ablation arms, ablation, report |

**Coverage: 9 briefs and 13 reports** over tasks 1, 1b, 1c, 2, 3, 4, 5, 5b and 6a–6e (one `task-6-brief.md`
covers 6a–6e; Task 5's brief is one paragraph because its subject is the label files). Tasks 7a and 8
were briefed in their dispatch message rather than in a file, so they have no `task-*-brief.md`.
`progress.md` is re-copied whole by the wave's **final commit**, which is the only way a ledger that
is still being written can be current here; the same commit brings across the reports written after
this copy was made.

**Who wrote what.** Per `progress.md`'s own line — *"every implementer, reviewer and re-reviewer
subagent was dispatched with `model: opus`"* — every task in this wave was implemented by an Opus
subagent and reviewed by an independently dispatched Opus subagent, with a fix-and-re-review loop
until the reviewer had nothing open. The coordinating session is Claude Fable 5.1, and the wave's
plan fixes the commit trailer to the coordinating session's model, which is why every `G5(…)` commit
names Fable rather than the model that wrote the diff. `ai-tooling.md` §8 states that narrowing
explicitly; this directory is where a reader checks it.

## What is deliberately not here

* **The label packets and `labels-*.yaml`.** The packets carry the served answers and their evidence,
  and the reference labels were authored blind from them; the committed label files
  (`evaluation/reference_labels*.yaml`) are what the agreement figures are computed from and what
  `evaluation/REPORT.md` quotes their protocol out of.
* **The `measure-*.log` files.** They are the raw stdout of the measurement chain and carry provider
  endpoints; every figure they produced is in `evaluation/results/*.json`, `evaluation/REPORT.md` and
  the ledger.
* **The review diffs** (`review-<a>..<b>.diff`). Byte-for-byte reproducible as `git diff <a>..<b>`,
  and together tens of megabytes — the same exclusion the P0–P27 trail makes.
* **`confirmed-gaps-raw.json`**, the grading workflow's pre-synthesis working set. `gaps.json` is the
  ranked list the wave actually worked from.
* **`.env`, `data/runtime/provision_turso.json` and every credential.** Neither was read by this copy.
  Every file here was scanned before it was copied — for `sk-`, `AIza`, `rnd_`, `ghp_`, `xox[baprs]-`,
  `eyJ`, `-----BEGIN`, `Bearer `, `TURSO_AUTH`, `access=`, `libsql://` and for any 32-character-or-longer
  base64-shaped run of characters. The only matches are **names, not values**: the variable names
  `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` / `APP_ACCESS_TOKEN`, the shape list in
  `task-6d-report.md`'s own scan note, `run_eval.py`'s `?access=` regex and its `<the service's>`
  placeholders, and long strings that are test function names and run ids. The live access token
  appears nowhere by exact match.

## How to read it

Start at `progress.md` and read down: it is chronological, the rulings are in it with what each one
would cost if it turned out wrong, and each task's row names the commits its review covered. For any
task, the brief says what was asked and the report says what was delivered and shows the commands
that proved it. `CHANGELOG.md` is the narrative above all of this; `docs/optimization-log.md` carries
the wave's measurement history, including the runs that were discarded and why.

These are working documents, reproduced unedited. They record wrong turns, overturned findings and
disagreements between a reviewer and an implementer, which is the point of an audit trail.
