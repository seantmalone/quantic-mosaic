# Task 12c (round 2) — `docs/demo-script.md`

**Status:** complete. **Commit:** `70b095c` on `main`, one file
(`docs/demo-script.md`, +57 / −34), trailer
`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`, no `Claude-Session`
trailer. No tests added.

**Tests:** `.venv/bin/pytest -q -p no:cacheprovider tests/contract/test_docs_completeness.py tests/unit/test_demo_prompts_are_dated.py`
→ `451 passed in 6.36s` (one process).

## Segment table

Unchanged in its boundaries, still chained end-to-start, nine segments, re-summed
mechanically:

```
0:00–0:45 0:45 · 0:45–1:25 0:40 · 1:25–3:40 2:15 · 3:40–6:00 2:20 · 6:00–6:25 0:25
6:25–7:10 0:45 · 7:10–7:50 0:40 · 7:50–8:50 1:00 · 8:50–9:15 0:25
```

**Sum = 9:15**, inside the 7:00–10:00 window, and the `Sum:` line under the table
states the same nine addends. The task-1 turn budget shrank (46.8 s → ~40 s), which
only adds slack *inside* the 2:15 segment, so no boundary had to move.

## Gap 3 — task 1's DEMO.6 ① and the timing budget

Both re-cut from `docs/evidence/demo-task-1-live-2026-09-22.txt` (the run the script
already pinned for beat ④):

- Chain: `mcp_discovery` → `lookup_employee_profile` → `search_policy_documents` →
  `check_policy_compliance` → **six** further `search_policy_documents` calls, each
  with its own `retrieval` row under it. Nine tool calls, seven retrievals, 39 spans
  (capture line 131 and the trace listing; six is the count of search spans after
  span 11, not the five a looser reading gives).
- `get_policy_section` is **hedged**, in task 2 ①'s own words: the pinned run never
  called it, and not calling it is exactly the tool recall 0.75 that fails the
  dataset twin `remote-004` on the published run. That ties the hedge to a published
  figure rather than leaving it as a caveat.
- Budget: "~40 s: the run pinned on this build took **38.2 s over 39 spans**; an
  earlier 2026-09-15 run took 46.8 s, so allow up to 50 s".
- Bonus correction in the same checklist: ② asserted
  `parameters: { …, duration_days: 42 }`. The capture's payload carries
  `start_date`/`end_date`, and `mcp/tools/check_policy_compliance.schema.json` says
  `duration_days` and `days` are *derived* from those two, so ② now points at the
  two dates and says why.

## Gap 4 — a pre-take check that can pass

The old check ("confirm the Runs table fronts `r_1790074972_baseline`") is
structurally impossible: `dashboard.py` orders `created_at DESC` and
`evaluation/ablation.py` drives the arms after the baseline. Replaced with two
checks that can pass — the newest **baseline · deployed** row is
`r_1790110325_baseline`, and no later dashboard-driven smoke run sits above the
three published arms — plus the reassurance that the row which legitimately fronts
the table reads **no structured tools · deployed**, carries **no** under **Judged**,
and shows **not judged** in **Headline metrics**. The evaluation segment now opens
`/dashboard/evals/r_1790110325_baseline` by URL (the "What is on screen" cell says
"typed, not clicked"), so a stray run cannot land the presenter on an arm; the
Compare tab's newest-of-each-variant pairing is named as the thing a stray drive
*would* change.

## Gaps 7 / 16 / 9 — the CI/CD beat

- **gitleaks** is narrated as what `ci.yml` now does: the action over the pushed
  commits, then an explicit `gitleaks detect` on the same pinned **8.30.1** binary
  over the **whole history on every run**, with the commit count to be read off the
  log (**280 commits / 13.22 MB / no leaks** when last checked on 2026-09-22, per
  the step's own comment).
- **`ux` in the gate.** "Say why `ux` is deliberately not in that list" is deleted.
  The beat now reads `needs: [test, docker, ux]` — verified at `ci.yml:178` — and
  says all 3,438 tests have to be green before anything ships, a red `ux` skipping
  the deploy as a red `test` does. It does **not** claim four jobs: `lint` is not in
  `needs:`.
- **The trigger.** One line: the filter ignores only `evaluation/results/**`,
  `evaluation/REPORT.md` and `docs/**`, so a root-level markdown edit runs the whole
  suite — which is what the submission commit is.

## Round-2 figures written, and where each was verified

Every number below was read out of `evaluation/REPORT.md`,
`evaluation/results/comparison.json`, `evaluation/results/r_1790110325_baseline.json`,
`evaluation/dataset.yaml`, `data/index/chunks.manifest.jsonl` or `.github/workflows/ci.yml`
before it was written.

| Written | Source |
|---|---|
| `r_1790110325_baseline`, build `80a5a71` | REPORT.md run table |
| 30 items, seven categories 7/5/6/3/5/2/2 | `Counter` over `dataset.yaml` (sums to 30) |
| strict 0.900 (27 of 30) | REPORT.md headline |
| groundedness 0.986 (n=18), citation accuracy 0.889 (n=18), doc recall 0.908 (n=19), tool selection 0.984 (n=30), workflow completion 0.933 (n=30), clarification 1.000 (n=3) | REPORT.md headline table |
| action safety 1.000 over **two items**, said as items not a rate | REPORT.md (n = 2) |
| p50 **15.5 s** / cold p50 13.9 s / n_cold 3 | REPORT.md *Latency* (15544 / 13889 ms) |
| `nudge_rate` 0.533 on the published run (was 0.571) | REPORT.md *Behaviour* |
| ablation workflow 0.933 → 0.767, delta **−0.167** vs 0.25, narrated as the null | comparison.json `workflow_completion_check` |
| tool selection 0.984 → 0.935, strict 0.900 → 0.733 | comparison.json arms |
| `expenses-002` groundedness 0.78 + workflow 0.00; `remote-004` tool recall 0.75 + workflow 0.00; `unsafe-001` tool recall 0.75 | REPORT.md's failing-clause table, cross-checked against the run file's per-item scores |
| `expenses-002` Verdicts: nine claims, `c6` contradicted, `c7` partially supported | run file `items[].verdicts.groundedness.per_claim` |
| `pto_request` workflow 1.00 over n = 3, two of them gate checks | REPORT.md *workflow completion by workflow* (`pto-003`, `unsafe-001`, `unsafe-002`, the last two `awaiting_confirmation`) |
| `remote_work_eligibility` 0.50 — implied by `remote-004` failing where `remote-003` passes | REPORT.md same line (1 of 2) |
| suite 3,139 of 3,438; 299 in `ux` | `pytest --collect-only` and `-m ux --collect-only`, run here |
| index 205 chunks | `wc -l data/index/chunks.manifest.jsonl` |
| Delta −16.7 %, Pre-registered bar *a drop past 25.0 %*, Claim supported **no** | `evals.html` renders these through the `pct` filter, so those are the strings on screen |

Two consequences worth flagging to the wave:

1. **The task-1 demo prompt's dataset twin now fails.** `remote-004` is one of the
   three failures (doc recall 0.50, tool recall 0.75). Beat ④, DEMO.6 ① and the
   "fewer citation chips" troubleshooting row all say so out loud — the old text had
   it passing at doc recall 0.75, and the troubleshooting row named `remote-002`,
   which now passes.
2. **`n_cold = 0` was no longer true.** The deployment segment justified narrating
   the cold/warm split with it. Rewritten to the true and stronger form: the run
   flags three cold turns at a cold p50 of 13.9 s, *below* its own 15.5 s p50, so
   none of them is a spin-up and the 71.0 s figure has to come from the deliberate
   probes.

## Out of scope, deliberately

- The **amb-003 bare-balance rule** and the **message-first clarification fix** are
  not demo beats and were not added.
- No UI label was invented. Labels used are the shipped ones, each checked in the
  template or view code this pass: **Runs** / **Compare** tabs, **Judged**,
  **Headline metrics**, **not judged**, "baseline · deployed" /
  "no structured tools · deployed" (composed in `_run_row`), **Verdicts**,
  **Trace**, "Ablation — three variants over the identical items", **Build
  measured**, "These arms were measured on different builds", "Workflow completion —
  the pre-registered check", **Delta**, **Pre-registered bar**, **Claim supported**.
- One minor tidy outside the gap list: `draft_hr_email` read "Deployed in `8a89310`",
  now "On the live build since `8a89310`", since `8a89310` is no longer the tip
  build.
