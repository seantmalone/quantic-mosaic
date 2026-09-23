# The grade-and-fix wave — briefs, reports and the ledger (2026-09-21 → 23, three rounds)

This directory is the **committed audit trail** behind the wave that worked through the independent
grade card of 2026-09-21 ([`docs/evidence/grade-card-2026-09-21.md`](../../evidence/grade-card-2026-09-21.md),
ranked gaps in [`grade-card-2026-09-21-gaps.json`](../../evidence/grade-card-2026-09-21-gaps.json)) —
and then through **two further re-grades of its own output**, each of which sent the wave round again.
It is a verbatim copy of the working directory that wave ran out of — `.superpowers/sdd/2026-09-21-grade-5/`,
which is git-ignored — so a reader can check `ai-tooling.md`'s disclosure against the artifacts
rather than take it on trust. Nothing below was edited on the way across; `cmp` says so file by file.

The plan these documents implement is tracked at
[`docs/superpowers/plans/2026-09-21-grade-5.md`](../../superpowers/plans/2026-09-21-grade-5.md), and
the fixes themselves are three commit ranges: **round 1** is the `G5(…)` commits from `98c893f`
onward, **round 2** the `G5b(…)` commits from `9dcd8dd` onward, and **round 3** the `G5c(…)` commits
from `39dc61c` onward.

## The three rounds

| Round | Graded at | Card | Verdict | Fixes land as |
|---|---|---|---|---|
| 1 | `98c893f` | [`grade-card-2026-09-21.md`](../../evidence/grade-card-2026-09-21.md) · `gaps.json` here | band 4, 27 ranked gaps | `G5(…)` from `98c893f` |
| 2 | `2dee277` | [`grade-card-2026-09-22.md`](../../evidence/grade-card-2026-09-22.md) · `regrade-gaps.json` here | band 4, 20 ranked gaps | `G5b(…)` from `9dcd8dd` |
| 3 | `39dc61c` | `regrade2-report.md` / `regrade2-gaps.json` here | band 4, 37 ranked gaps | `G5c(…)` from `39dc61c` |

Rounds 2 and 3 exist because a fix wave is a change like any other: each re-grade read the repository
the previous round left, and each found a fresh set of one-command-falsifiable claims. Round 3's list
is the largest of the three and the least about capability — three of the four items that capped it
were defects in code or in a committed artifact rather than in prose. `progress.md` carries every
ruling of all three rounds in one chronological ledger.

## What is here

| File | What it is |
|---|---|
| `progress.md` | The ledger: every ruling, every task's implemented / reviewed / fix-round / complete lines with their commits, and the status of each ranked gap |
| `task-<n>-brief.md` | The requirements handed to the implementing session for that task — written before the diff |
| `task-<n>-report.md` | What that session changed, the command output pasted verbatim, its self-review and the concerns it raised |
| `grade-report.md` | Round 1's grading workflow report, of which the committed grade card is the copy |
| `gaps.json` | The machine twin of round 1's ranked gap list, the same file as `docs/evidence/grade-card-2026-09-21-gaps.json` |
| `regrade-report.md` / `regrade-gaps.json` | The same pair for **round 2**'s grade of `2dee277`; the report is the source of `docs/evidence/grade-card-2026-09-22.md` |
| `regrade2-report.md` / `regrade2-gaps.json` | The same pair for **round 3**'s grade of `39dc61c`. No `docs/evidence/` grade card was cut for this one — the report here is the record |
| `run_eval.py` | The operational helper the measurement chain ran through: it loads the Turso handoff **by path** into the process environment, reads the `?access=` token out of `README.md`, and prints nothing |
| `measure.sh` | The sequential chain Task 4 measured with — baseline drive, judge pass, both ablation arms, ablation, report |

**Coverage: 12 briefs and 26 reports** at this commit. Round 1 is tasks **1, 1b, 1c, 2, 3, 4, 5, 5b,
6a–6e, 7a, 8, 9**; round 2 is **10, 11, 11b, 12a–12d, 13** plus the measurement sub-tasks **5c** and
**5d** that re-drove and re-labelled its published run. Briefs exist for 1, 1b, 1c, 2, 3, 4, 5, 5b,
6 (one file covering 6a–6e), 10, 11 and 11b; every other task was briefed in its dispatch message
rather than in a file, which from round 2 onward is the norm because each report quotes its own brief
at the head. Task 5's brief is one paragraph because its subject is the label files. Count the copy
rather than trusting this paragraph: `ls docs/process/sdd/G5-grade-5/task-*-brief.md | wc -l` and the
same for `-report.md`.

**Round 3's task files are not all here yet, and that is structural rather than an omission.**
`progress.md` is re-copied whole by each round's **final commit**, which is the only way a ledger that
is still being written can be current here, and the same commit brings across the reports written since
the previous copy. Round 3's own reports — tasks **14**, **15**, **16** and the measurement sub-task
**5e** — are therefore copied by the commit that closes the round, not by the commits that wrote them.
Round 3's grade artifacts (`regrade2-report.md`, `regrade2-gaps.json`) are here now because they were
inputs rather than outputs. What is always current here is the ledger and the two grade pairs; what can
lag by one commit is the report of whichever task performed the copy.

**The credential scan was re-run over each round's copy**, not only over round 1's: the same pattern
list below, over every file brought across in rounds 2 and 3, with the same result — names, never
values.

**Who wrote what.** Per `progress.md`'s own line — *"every implementer, reviewer and re-reviewer
subagent was dispatched with `model: opus`"* — every task in this wave was implemented by an Opus
subagent and reviewed by an independently dispatched Opus subagent, with a fix-and-re-review loop
until the reviewer had nothing open. The coordinating session is Claude Fable 5.1, and the wave's
plan fixes the commit trailer to the coordinating session's model, which is why every `G5(…)`,
`G5b(…)` and `G5c(…)` commit names Fable rather than the model that wrote the diff. `ai-tooling.md` §8 states that narrowing
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
