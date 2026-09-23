# Task 17 — the sixteen sentences the fourth grade could falsify

Brief: fix the sixteen text defects in `.superpowers/sdd/2026-09-21-grade-5/regrade3-defects.json`.
No new collected tests (3,469 before and after). The provenance pathspec
(`src/**`, `mcp/tools`, `mcp/server_entrypoint.py`, `mcp/run_*.sh`, `corpus/**`,
`data/index/chunks.manifest.jsonl`, `Dockerfile`, `render.yaml`, `requirements.txt`) was not touched;
the four defects whose evidence sits inside it are fixed on the document side and the stale source
comment is recorded as stale-at-`34d50fb` in `design-and-evaluation.md`.

Measurements re-derived before writing them down (`data/index/chunks.manifest.jsonl`): 205 chunks,
29 continuation windows grouped by `(doc_id, heading_path)`, 28 of them opening lowercase, 200 chunks
over the 320-character snippet cap, median `n_chars` 983. Judge calls over the committed judged
baselines: 232, 249, 252, 263, 264, 266, 268, 273, 291, 296 → min 232, max 296, n = 10.

## Per defect

**1 — chunk overlap described as landing on sentence boundaries.**
- `design-and-evaluation.md:237–244` (*Ingestion and chunking*): now says only the window **end** is
  cut back to a sentence boundary, the continuation **start** is a raw character offset 150 characters
  back from that end (citing `chunk.py:155`'s `start = max(end - overlap_chars, start + 1)`), that all
  29 continuation windows open mid-sentence and 28 mid-word, and that the consequence is confined to
  the 320-character `snippet_of()` display subset while the stored `text` a citation resolves against
  is whole.
- `design-and-evaluation.md:2167–2170` (*Chunking strategy*): same correction in one clause.
- `.env.example:56`: `CHUNK_OVERLAP_CHARS` comment rewritten to the same mechanism plus the 29/28
  figures.
- `design-and-evaluation.md:1978` (new Known limitation 15): records `src/hrmosaic/rag/chunk.py:6–7`'s
  docstring as stale as of build `34d50fb`, corrected at the next application rebuild.
- Ledger: `docs/process/sdd/G5-grade-5/progress.md` is a copy and was **not** edited; its ruling
  ("fixed by describing what the code does") is now true — the wording landed in this task. The
  controller re-copies the ledger.

**2 — remote-004's failing clause in the demo script.**
- `docs/demo-script.md:241–245`: `get_policy_section` is optional because a `search_policy_documents`
  hit already carries the whole chunk; `remote-004` scores tool recall **1.00** on the published run,
  as does every item, and fails the workflow-completion clause at document recall 0.50. The "read the
  names on screen" instruction is kept.
- `docs/demo-script.md:386`: "failing its workflow-completion clause, with document recall 0.50 — say
  that out loud rather than around it."

**3 — the tool-schema "loose end" the published build closed.**
- `design-and-evaluation.md:483–487`: the five-line loose-end paragraph replaced by one sentence —
  the description names `device_age_months` and `days_since_final_day` as of `6a4821a`, an ancestor of
  `34d50fb` (verified with `git merge-base --is-ancestor` and `git show 34d50fb:…schema.json`).
- Known Limitation 14 deleted; the old 15 (bare-balance clarification) renumbered to **14**; the
  retirement recorded in the closed-limitations account at `design-and-evaluation.md:2019–2024`. No
  other text cross-references limitations 14/15 by number.
- `docs/optimization-log.md:1068–1073`: the third copy dated — "corrected 2026-09-22" — rather than
  silently deleted, since it is a wave record.

**4 — p50 in the demo script.**
- `docs/demo-script.md:134`: "p50 was 22.6 s at its worst and is **13.8 s** now, down from 15.5 s last
  round." No new test (user direction).

**5 — the two-job deploy gate.**
- `scripts/provision_render.py:414` (runtime error string) → `needs: [test, docker, ux]`.
- `tests/unit/test_provision_render.py:222` (docstring) → same.
- `render.yaml:7` left untouched (frozen pathspec) and recorded in the design doc's CI/CD section at
  `design-and-evaluation.md:1051–1055` as stale as of build `34d50fb`, with `ci.yml:188` and
  `test_deploy_manifests.py:330` named as the authority meanwhile.

**6 — G1's refuse-and-redirect.**
- `design-and-evaluation.md:811` (G1 guardrail row): "naming five fixed corpus topics from a constant
  tuple and linking `/policy`, with **no index read** — the redirect is not derived from the document
  list."
- `g1.py:84`'s `coverage()` clause recorded in Known limitation 15.

**7 — task-2 tool order.**
- `docs/demo-script.md:341`: "… then — after the confirmation spans — `lookup_employee_profile`, and
  finally `create_mock_hr_ticket` again, this time `ok`", matching
  `docs/evidence/demo-task-2-live-2026-09-22.txt` (seq 20 paused, seq 23 lookup, seq 28 ok).

**8 — the process-trail README's coverage count.**
- `docs/process/sdd/G5-grade-5/README.md:45`: **30 reports**, 12 briefs (recounted with `ls … | wc -l`).
- `:47–48`: round 3's inventory added — tasks **14, 15, 16** plus measurement sub-task **5e**.
- `:55–63`: the "not all here yet" paragraph rewritten in past tense, naming `f7852bb` as the commit
  that brought them and stating that they are all present.

**9 — "three different clauses, one each".**
- `docs/demo-script.md:155–157` and `docs/optimization-log.md:1006–1007`: "groundedness once, workflow
  completion twice, and behaviour class once on top of it".

**10 — the trailer-narrowing disclosure.**
- `ai-tooling.md:371`: "all three rounds, `G5(…)`, `G5b(…)` and `G5c(…)`".

**11 — the demo panel.**
- `README.md:146–149`: one dashed, muted *Demo & grader controls* section below the conversation,
  **always expanded**, no collapsed state, below the fold.

**12 — the folded-agreement disclosure.**
- `design-and-evaluation.md:1412–1414`: past tense and pinned — "the eight labels it was folded against
  were authored for `r_1790074972_baseline`'s answers, not for that run's (the current label file is
  bound to the published run `r_1790130220_baseline`'s `turn_id`s, 8 of 8, as recorded below)",
  reconciling with `:1582`.

**13 — the ablation banner.**
- `evaluation/ablation.py:57`: first clause → "did not move Workflow completion **past §13.9's bar**".
- Regenerated: `run_eval.py evaluation.ablation` (exit **1**, expected — the bar is not met), then
  `run_eval.py evaluation.runner --report r_1790130220_baseline`. `evaluation/REPORT.md` changed in
  exactly the banner clause and the rank-14 cost sentence (`git diff --stat` → 5 insertions, 5
  deletions); `evaluation/results/comparison.json` changed only in `generated_at`.

**14 — the hardcoded judge-call range.**
- `evaluation/runner.py:1244–1262`: new `_judge_call_span(results_dir)` reads `judge_calls` off every
  committed `r_*_baseline.json` with `judge_status == "judged"` and renders the min/max, the count and
  the cost at the measured per-call rate (`JUDGE_COST_MEASURED_USD / JUDGE_COST_MEASURED_CALLS`, new
  constant `JUDGE_COST_MEASURED_USD = 0.16`). `judge_cost_note()` gained an optional
  `results_dir` keyword, so its two existing unit tests call it unchanged. The literal is gone:
  `REPORT.md:120` now reads "the 10 committed judged baselines ran **232–296** calls and
  **≈ $0.14–$0.18** at that per-call rate".
- Unscoped copies scoped and corrected: `deployed.md:485`, `:494`, `:636`;
  `design-and-evaluation.md:686`; `docs/requirements-traceability.md:55`, `:139` — all now
  "≈ $0.14–$0.18 a pass (232–296 calls over the ten committed judged baselines)". Run-scoped
  mentions of 249 (`CHANGELOG.md:905`, `docs/optimization-log.md:272`) are true of their run and left.

**15 — the stale chunk count in a prompt comment.**
- `tests/contract/test_prompt_golden.py:216–222` docstring: "200 of the 205 committed chunks are longer
  than that (median 983)", plus a note that `synthesize.j2:11` still carries the pre-repair figures and
  is recorded as stale-at-`34d50fb`.
- `src/hrmosaic/agent/prompts/synthesize.j2:11` recorded in Known limitation 15 (inside a Jinja comment,
  so it never reaches a model).

**16 — `make setup`.**
- `README.md:37–38`: "`make setup` runs the same install, plus a `pip install --upgrade pip` first; the
  `.env` copy stays manual."

## Verification

```
$ .venv/bin/python scripts/paste_eval_numbers.py --check
OK — the results table matches evaluation/results/latest.json

$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
322 files already formatted

$ .venv/bin/pytest -q -p no:cacheprovider tests/contract tests/unit/test_provision_render.py
590 passed in 155.11s (0:02:35)

$ .venv/bin/pytest -q -p no:cacheprovider \
    tests/contract/test_published_run_commands.py::test_the_application_tree_has_not_moved_since_the_measured_build
1 passed

$ .venv/bin/pytest -q -p no:cacheprovider --collect-only -m "" | tail -1
3469 tests collected

$ git diff --stat 34d50fb..HEAD -- src mcp/tools mcp/server_entrypoint.py mcp/run_stdio.sh \
    mcp/run_http.sh corpus ':!corpus/README.md' data/index/chunks.manifest.jsonl \
    Dockerfile render.yaml requirements.txt
(empty)
```
