# P18 brief — publish step (live values into the graded documents)

## Where this fits
Every code phase is done and the final deployed sweep has been judged. This wave writes the live
facts into the documents the grader reads, ticks the user gates, and leaves the repo ready for the
final whole-branch review. Values come from the files named below — never invent a number; when a
value is not in a file, write "pending" and say why in the report.

## Sources (read-only)
- `data/runtime/post_gate_results.json` (git-ignored, mode 600): service id, DEPLOY_URL, the tokenized
  link (`?access=…`), GitHub secrets set, Turso database name/region, spend, publish-step wording for
  CHANGELOG / deployed.md / NEEDS-FROM-USER.md (`publish_step_wording`). Never copy the token or any
  secret into a tracked file EXCEPT the tokenized grader link into README's `Deployed:` line, which
  Sean explicitly designed as the grader's entry (§11) — that line only.
- `evaluation/results/latest.json`, `comparison.json`, the newest `r_*_baseline.json` (final run),
  `r_1789055103_baseline.json` (before), `r_1789069158_baseline.json` (after P13), `chunk_size_comparison.json`.
- `docs/optimization-log.md` (the before / after-P13 / final columns and the cold-start table).
- `.superpowers/sdd/2026-09-08-implementation-roadmap/progress.md` for rulings you must not contradict.
- Do NOT call the live URL at all (cold-start probes need it idle): take rss_mb from the final run's `/health` snapshot in `data/runtime/post_gate_results.json` (smoke.health) or the ledger, and the deployed git sha from the ledger (final run served by da0dca2).

## Required edits
1. `README.md`: `Deployed:` → the tokenized link; `Demo video:` stays "pending: gate 6"; the results
   block (`python scripts/paste_eval_numbers.py` regenerates it — run it) shows the FINAL run with the
   before column beside it; one line pointing at `docs/optimization-log.md`.
2. `deployed.md`: live URL, service plan (free), Render hours used (from `scripts/check_render_hours.py`
   with the API key from the environment — run it; never print the key), Turso database name/region
   and plan (starter, overages off), memory (rss at `/health`), the measured cold-start table (n=1 now;
   label it "n=1, measured 2026-09-10 without keep-alive; two further probes queued"), warm-turn
   figure 22.5 s, the eval run's deployed git sha (the run files record the harness tree's sha as
   "dev" — state the deployed sha from the deploy that served the run, recorded in the ledger:
   b24ad32 for the after-P13 run; the final run's sha is in the ledger's final-sweep entry), the
   judge billing note (paid standard tier on the judge project since 2026-09-10; ≈ $0.16–0.18 per pass),
   and the `LLM_RPM=60 / LLM_BURST=30` service setting with its reason.
3. `NEEDS-FROM-USER.md`: tick every gate that is done (accounts, keys, Render card gate 2a, Turso,
   deploy, judge billing); leave the demo video and the grader-invite confirmation open.
4. `CHANGELOG.md`: entries for P13, P14, P15, P16 (and the P11c defect) in the file's existing voice;
   one line each with the measured effect where known.
5. `docs/requirements-traceability.md`: rows that were "planned — verified at publish" → "verified"
   with the evidence file; add rows for streaming/narration (R6.x UX) and the optimization log.
6. `evaluation/REPORT.md`: do not hand-edit generated sections; add the human paragraph the runner
   leaves room for (or `design-and-evaluation.md` §results) that walks the three columns and names
   the ablation disclosure and the missing-agreement caveat on the intermediate column.
7. `docs/demo-script.md`: a short "optimization story" beat list from `docs/optimization-log.md`'s
   talking points (≤ 8 bullets), timed to fit the 7–10 minute video.
8. Regenerate `docs/architecture.html`'s numbers ONLY where it quotes a metric that changed (grep for
   the old values); do not restyle it.

## Definition of done
`ruff check .` clean; `pytest -q` green (the docs contract tests in tests/contract/test_docs_completeness.py
must pass with your edits); `scripts/check_facts.py` and `scripts/pii_check.py` clean (the tokenized
link must not trip pii_check — if it does, stop and report rather than allowlisting). Commit
`P18(docs): …` on `main`; never push. Never read or print `.env`. No subagents. Report to
`.superpowers/sdd/2026-09-08-implementation-roadmap/P18-report.md` with every value and its source file.
