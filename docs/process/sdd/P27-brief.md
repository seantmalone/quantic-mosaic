# P27 brief — residuals from the re-grade (docs only)

1. `ai-tooling.md` (~lines 203-206): the commit census in the academic-integrity disclosure is stale;
   recompute from `git log` (total commits, by Co-Authored-By line, merges) and make the docs-completeness
   test assert it from git so it cannot drift (skip gracefully if git is unavailable).
2. `docs/process/sdd/`: copy P24-brief/report, P25-brief/report, P26-brief/report, P27-brief (this),
   grade-card-2026-09-11.md if missing, and the current `progress.md` (the ledger) from
   `.superpowers/sdd/2026-09-08-implementation-roadmap/`; run the same secret greps as P23 before copying;
   update that directory's README index.
3. `docs/requirements-traceability.md` lines ~12-14: the summary sentence still counts SUB.3 among the
   planned rows while its row says done — fix the sentence and the counts.
4. MCP verification wording (RB5): where the docs say only "an external initialize answered HTTP 200",
   state the full verified session of 2026-09-11 (initialize 200 → notifications/initialized 202 →
   tools/list 9 tools → search_policy_documents and check_pto_balance calls → create_mock_hr_ticket
   without a confirmation token refused with CONFIRMATION_REQUIRED, and with a forged token likewise;
   401 without the bearer) in mcp/README.md, deployed.md and design-and-evaluation.md, one sentence each.
5. Pin today's live demo-2 transcript: copy
   `/private/tmp/claude-501/-Users-sean-Projects-quantic-mosaic/44fed378-5d63-4daa-b66b-91107d8f0a3a/scratchpad/demo-task-2-live-2026-09-12.txt`
   (already redacted) to `docs/evidence/demo-task-2-live-2026-09-12.txt`, link it beside the 2026-09-11
   transcripts in README's evidence list and the traceability row, and note in `docs/demo-script.md`'s
   demo-2 beat that on the final build the answer opens with the ticket id (MOCK-HR-000006, 4 citations
   from 2 documents, 40 s).
6. `CHANGELOG.md`: one line.

DoD: `ruff check .` clean; `pytest -q` pristine (2,001 baseline); `check_facts.py`, `pii_check.py` clean;
gitleaks-style grep over docs/process/ clean. Commit `P27(docs): …`; never push; never read `.env`; no live
calls. No subagents. Report to `.superpowers/sdd/2026-09-08-implementation-roadmap/P27-report.md`.
