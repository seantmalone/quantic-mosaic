# P23 brief — fixes from the independent grade card (2026-09-11)

An independent grading pass (`grade-card-2026-09-11.md` beside this brief; read its "unmet" section)
scored the project band 5 overall but found concrete, checkable defects. Fix every item below; each
is deterministic and cheap. The grade card is the requirements source for this wave; the spec stays
authoritative for contracts.

## Items
1. **MCP mount returns HTTP 421 to external clients (R5.5; caps two rubric bullets).** Reproduced:
   `POST https://mosaic-hr-copilot.onrender.com/mcp-server/mcp` with a valid bearer and
   `Accept: application/json, text/event-stream` → 421 "Invalid Host header". Cause: the SDK's
   Streamable HTTP session manager enables DNS-rebinding protection with a loopback-only host
   allowlist by default (`mcp/server/transport_security.py`), and `mount_mcp` / `build_mounted_app`
   (src/hrmosaic/mcpserver/asgi.py, server.py) pass no `TransportSecuritySettings`. Fix: pass
   `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=[...],
   allowed_origins=[...])` built from settings — a new `MCP_ALLOWED_HOSTS` setting (comma-separated;
   default `127.0.0.1:*,localhost:*`; the Render service gets `mosaic-hr-copilot.onrender.com` via
   `render.yaml` and the env table). Keep protection ON (do not disable it). Contract test: a request
   with `Host: mosaic-hr-copilot.onrender.com` is accepted when the host is allowed and 421 when it is
   not; the loopback client still works. Then make the five documentation claims true and precise
   (mcp/README.md:32 and :211, design-and-evaluation.md:289, deployed.md:103-104,
   docs/architecture.html:1531) and fix mcp/README.md:200-206's wrong reasoning about the SDK
   defaults. Link `mcp/README.md` from README.md and design-and-evaluation.md (one line each).
2. **Stale counts (R1.3).** `pytest --collect-only -q` collects 1,942 tests (re-measure after your
   changes); README.md:48 says 1,917, ai-tooling.md:174 says 1,911, design-and-evaluation.md:726 and
   docs/requirements-traceability.md:143 say 1,917; README.md:52's statement count differs from
   coverage.xml. Refresh every number and extend the docs-completeness contract test so EVERY document
   that states the test count or the statement count asserts the collected/measured value.
3. **Headcount contradiction.** README.md:3 and design-and-evaluation.md:8 say "120-person";
   corpus/README.md:3, mock_data/README.md:4 and the spec (line ~279) say "420-person";
   docs/demo-script.md:54 scripts "120-person". The corpus is the policy truth: use 420 everywhere
   (and say "24 employee records in the mock data" where the record count is meant).
4. **Traceability row S.5 / SUB.3.** The quantic-grader collaborator has `read` permission and no
   pending invitation (`gh api repos/seantmalone/quantic-mosaic/collaborators/quantic-grader/permission`);
   docs/requirements-traceability.md:191 still says "planned" and docs/pre-submission-checklist.md's
   SUB.3 box is unticked. Mark both done with the evidence command.
5. **Run provenance (`git_sha: "dev"`).** The harness records `git_sha` from a tree it calls "dev".
   Make it record the real `git rev-parse HEAD` of the harness tree AND the target's `/health` git_sha
   (`target_git_sha`) for remote targets; write both into the run file and REPORT's run header. Do
   not rewrite the committed run files' data — add a one-line note in deployed.md that runs before
   this commit carry the sha in prose (da0dca2 for r_1789086979_baseline).
6. **Labeller wording.** evaluation/reference_labels.yaml:22-24 and reference_labels_hard.yaml:25-27
   call the labeller "a third model family independent of both the agent…"; it is a Claude Opus 5
   session, the agent's vendor. Reword to "the same vendor as the agent, a different model, in an
   independent session that read only the packet"; keep the schema's keys; mirror the wording in
   evaluation/REPORT.md's generated text if the runner emits it (fix the template, not the output).
7. **Architecture page claims.** docs/architecture.html loads Google Fonts while
   design-and-evaluation.md:48 says the page needs no network access — inline the font stack (system
   fonts with a real fallback) so the claim is true; correct the two inspector annotations the card
   names (see the card's R10.2 entry).
8. **AI-tooling audit trail pointer (P.2).** ai-tooling.md:190 points at `.superpowers/sdd/…`, which
   is git-ignored. Commit the process trail: copy the ledger (`progress.md`), every `P*-brief.md`,
   `P*-report.md`, `final-review-brief.md`, the grade card and `constraints.md` into
   `docs/process/sdd/` (tracked), after running `scripts/pii_check.py`-style and gitleaks-style greps
   over them for tokens/keys (redact anything that looks like a secret — there should be none; the
   handoff JSON is NOT copied). Repoint ai-tooling.md:190 and the spec/README lines that mention the
   trail.
9. **Demo-2 citation expectation overstated.** Live demo-2 turns cite one document
   (pto-and-holidays); docs claim two. State the live behaviour honestly in docs/demo-script.md,
   design-and-evaluation.md's demo-2 expectation and tests/e2e/test_demo_tasks.py's docstring; do not
   weaken the stub assertion silently — if the stub asserts ≥2 distinct docs, keep it but say in its
   docstring that the recorded script is the design expectation while live runs cite one.
10. **KEEP_ALIVE_URL in the blueprint.** Add `KEEP_ALIVE_URL` (value: the public URL) and
    `KEEP_ALIVE_INTERVAL_S` (600) to render.yaml's env list so a blueprint redeploy keeps the
    self-ping; update the deploy-manifest contract test's expected set and deployed.md's sentence
    that says the variable "ships unset".
11. **Pinned end-to-end evidence.** Run `BASE_URL=https://mosaic-hr-copilot.onrender.com
    APP_ACCESS_TOKEN=<from README's link> sh scripts/demo_task_1.sh` and `demo_task_2.sh` ONCE each
    against the live service (two chat turns ≈ $0.03; allowed for this item only), save the redacted
    transcripts (no token) as `docs/evidence/demo-task-1-live-2026-09-11.txt` and
    `demo-task-2-live-2026-09-11.txt`, and link them from README's evidence list and the traceability
    rows for the two demo tasks.
12. **Grade card into the repo.** Copy `grade-card-2026-09-11.md` to `docs/evidence/` and link it from
    `docs/pre-submission-checklist.md` as the independent pre-submission assessment.

## Definition of done
`ruff check .` / `ruff format --check` clean; `pytest -q` pristine; `make coverage` ≥ 90%;
`check_facts.py`, `pii_check.py`, `--verify-manifest` unchanged; `make demo1` then `make demo2`
(separately) green; a gitleaks 8.30.1 run (binary in the scratchpad from P17) over the tree is clean
after item 8. Commits `P23(<scope>): …` on `main`; never push; never read or print `.env`; live URL
calls only as item 11 and item 1's verification allow (GET /health, MCP initialize). No subagents.
Report to `.superpowers/sdd/2026-09-08-implementation-roadmap/P23-report.md`.
