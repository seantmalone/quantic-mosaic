# Final whole-branch review brief (after P18 and P17)

## Purpose
The last gate before the final push: an independent, whole-repository review of `main` against the
course requirements (`docs/project-requirements.md`, rubric 0–5 per bullet; target 5 on every
bullet), the design spec (`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`, authoritative),
and the project's own conventions (`tests/architecture/test_conventions.py`, spec §4.2). It is
read-only: reviewers never edit or commit. One fix wave follows, then a scoped re-review.

## Lenses (one reviewer each; all read the requirements first)
1. **Rubric and documents.** For every rubric bullet: is the evidence present, truthful and easy for
   a grader to find from `README.md` in under a minute? Check `README.md`, `deployed.md`,
   `design-and-evaluation.md`, `ai-tooling.md`, `evaluation/REPORT.md`, `docs/requirements-traceability.md`,
   `docs/demo-script.md`, `docs/architecture.html`, `NEEDS-FROM-USER.md`, `CHANGELOG.md`,
   `docs/optimization-log.md`. Every number quoted must match its source file (run ids named). Any
   claim that is stale after Waves 1–2 (e.g. "1.5–5 s", "free-tier judge", "no keep-alive",
   "spans arrive as they close", "10 RPM") is a finding.
2. **Code and architecture.** `src/hrmosaic/**`: correctness of the newest code paths (streaming
   assembler and provisional/hard-replace; narration; quarantine shield on search hits; G1 compliance
   evidence scoring; daily-cap fast negative; embed memo; loopback timeouts + warm-up retry;
   contamination gate), dependency direction (§4.2), error handling contract (§11.1: never a bare 5xx),
   secrets hygiene (nothing logs or returns a key; `SecretStr` everywhere), resource use on 0.1 vCPU /
   512 MB (anything new on the event loop that blocks).
3. **Tests and CI.** Run the full DoD: `.venv/bin/ruff check .`, `ruff format --check`,
   `.venv/bin/pytest -q` (pristine output), `scripts/check_facts.py`, `scripts/pii_check.py`,
   `-m hrmosaic.rag.ingest --verify-manifest`, `make demo1` then `make demo2` (separately). Read
   `.github/workflows/ci.yml` and `keepalive.yml`: gates, secrets usage, permissions, gitleaks config.
   Look for tests that assert nothing, duplicated logic, flaky patterns (sleeps, real clocks, network).
4. **Security and privacy.** Access gate and personas (§11), MCP mount gating, prompt-injection path
   (G4, the quarantine shield, the canary chunk), PII redaction (G6) on the streamed path, the
   tokenized grader link (only in README's Deployed line), `.gitleaks.toml` allowlists, anything in
   `git log -p` that leaked a secret (grep the history for key prefixes).

## Output (each reviewer)
Findings with severity (Critical / Important / Minor), `file:line`, the problem, the fix; what was
verified and how; what could not be verified. No praise-only sections. Critical = a rubric bullet
would score below 5, a contract is wrong, or a secret is exposed.

## After the reviews
The controller merges findings, rules on each, dispatches ONE fix agent for Critical + Important
(Minor batched only if trivial), then a scoped re-review of the fix diff. Then push, CI, deploy,
`scripts/smoke_deployed.py` against the live URL, and the final summary to Sean.
