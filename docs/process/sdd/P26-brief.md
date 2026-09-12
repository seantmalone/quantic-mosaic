# P26 brief — the keep-alive is armed on the live service; say so everywhere, coherently

## Fact
`KEEP_ALIVE_URL=https://mosaic-hr-copilot.onrender.com` and `KEEP_ALIVE_INTERVAL_S=600` were set on the
Render service on 2026-09-11 at 14:26Z (single-key PUT; also in render.yaml since P23). Evidence that
the in-process self-ping works: `/health` `app.uptime_ms` reached 60 min at 18:37Z, 69 min at 23:56Z →
86 min at 00:13Z (a 17-minute window with no traffic but two health reads, past Render's 15-minute
spin-down), and 124.5 min at 00:51Z on 2026-09-12. The documents still say the variable is NOT set,
and `tests/contract/test_keep_alive.py` pins that wording via CONDITIONAL_MARKERS.

## Required
1. Rewrite the keep-alive status prose in README.md (~line 131), deployed.md (the Keep-alive
   subsection and any sentence saying the layer is off / unset / "until an operator sets"),
   docs/architecture.html (the cold-start tile text at ~line 1821 and any tooltip), and
   docs/demo-script.md if it mentions it: the in-process layer IS armed on the live service since
   2026-09-11 14:26Z, verified by the uptime evidence above; the measured cold-start table stays as the
   no-keep-alive behaviour a visitor gets if the loop is ever disabled; the GitHub Actions layer is the
   second, best-effort layer; how to disable (remove the variable → the loop stops; the Actions workflow
   can be disabled in the Actions tab). Keep the 744-of-750-hour arithmetic and the "suspension, never a
   bill" sentence.
2. `tests/contract/test_keep_alive.py`: replace CONDITIONAL_MARKERS with markers that pin the new truth
   (e.g. "armed on the live service since 2026-09-11", "set on the live service") while keeping the
   invariant that the Dockerfile never bakes the origin and render.yaml carries the variable. Update the
   test's docstring to say why the wording flipped.
3. `docs/optimization-log.md` is already corrected by the main session — read it, do not edit it.
4. P25 minors: (a) design-and-evaluation.md's four-column table cell that says "not labelled" for the
   after-P13 column → "not published (labels are authored per published run)" plus one clause in the
   disclosures paragraph noting the run file's mechanically computed 1.00 (n=8) against labels authored
   for other answers; (b) tick SUB.2 in docs/pre-submission-checklist.md with the date, or add the
   clause naming the half still to be checked on the day, so the three documents agree.
5. `NEEDS-FROM-USER.md` / CHANGELOG: one line each.

## Definition of done
`ruff check .` clean; `pytest -q` pristine (2,001 baseline at 0b6de0a); `scripts/check_facts.py`,
`scripts/pii_check.py` clean. Commit `P26(docs): …` on `main`; never push; never read or print `.env`;
never call a live LLM; the live URL may be read with GET /health only. No subagents. Report to
`.superpowers/sdd/2026-09-08-implementation-roadmap/P26-report.md`.
