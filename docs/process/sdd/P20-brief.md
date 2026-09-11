# P20 brief — coverage gate in CI, and tests for the least-covered modules

## Where this fits
After the final whole-branch review. Measured on 2026-09-11 (coverage 7.10.7, `--branch`, full suite):
93% lines / 85% branches over 7,081 statements. The rubric rewards test discipline; CI has no coverage
gate today. This wave adds one and lifts the weakest modules. Report: `coverage-2026-09-11.txt` and
`coverage-lowest-missing.txt` beside this brief.

## Required
1. **Tooling.** Add `coverage==7.10.7` to the dev/test dependency set the way the repo pins other test
   tools (pyproject + requirements as the repo does it; keep the bijection/pin tests green). A Makefile
   target `coverage` that runs `coverage run --branch --source=src/hrmosaic -m pytest -q` then
   `coverage report --fail-under=90` and writes `coverage.xml` (ignored by git).
2. **CI.** In `.github/workflows/ci.yml`'s `test` job, run the suite under coverage instead of plain
   pytest (same env: `LLM_PROVIDER=stub`), enforce `--fail-under=90` on line coverage, and upload
   `coverage.xml` as an artifact. Do not add third-party coverage services or badges that need tokens.
   Print the per-package table in the job log. Keep the job's existing steps (check_facts, pii_check,
   verify-manifest) unchanged.
3. **Tests for the least-covered modules** (behaviour tests, not line-hitting for its own sake; each
   test named for the behaviour it pins): `src/hrmosaic/rag/index.py` (76%: build/verify/mismatch guard paths),
   `src/hrmosaic/mcpserver/rules.py` (89%: rule branches the compliance engine never exercised in the
   suite), `src/hrmosaic/web/sse.py` (85%: queue-full drop, heartbeat, shutdown paths). Add any other module under 85% from the report. Target ≥ 90%
   lines on each module you touch; overall ≥ 93% must not drop.
4. **Document.** `README.md` test section: the measured coverage figure, the gate, and how to run it;
   `design-and-evaluation.md` testing section: one sentence. `docs/requirements-traceability.md`: the
   testing row cites the gate.
5. **Concurrency note (cheap check only).** A full suite run under coverage while another pytest run
   was active in the same checkout showed 43 transient failures; a rerun was clean. Spend at most 20
   minutes looking for a shared mutable path (a fixed temp file, `data/runtime/…`, a fixed port) in
   tests; if found, fix it with a per-test tmp path/free port; if not found, write that down and stop.

## Definition of done
`ruff check .` and `ruff format --check` clean; `make coverage` passes the gate locally (paste the
table); `pytest -q` pristine; `check_facts.py`, `pii_check.py`, `--verify-manifest` unchanged; the
CI YAML validates (`.venv/bin/python -c "import yaml;yaml.safe_load(open('.github/workflows/ci.yml'))"`)
and the existing workflow contract tests pass. Commits `P20(tests): …` on `main`; never push; never
read or print `.env`; no live LLM or live URL. No subagents. Report to
`.superpowers/sdd/2026-09-08-implementation-roadmap/P20-report.md`.

## Item 6 — proxy headers behind Render's edge (from the final review; deploy-scoped)
`Dockerfile` runs uvicorn without `--proxy-headers`, so behind Render's TLS-terminating edge
`request.url.scheme` is `http` and `request.client.host` is the edge address (the per-IP limiter then
keys every client onto one bucket). Add `--proxy-headers --forwarded-allow-ips='*'` to the uvicorn CMD
(the container port is reachable only through Render's edge, which always sets `X-Forwarded-For` /
`X-Forwarded-Proto`; say so in a Dockerfile comment). Keep the cookie-Secure fix P19 made (it must not
regress when the scheme is now https). Add a Dockerfile contract test for the two flags and update
`deployed.md`'s rate-limit sentence back to per-client keying (P19 wrote "one shared bucket behind the
edge"), plus `design-and-evaluation.md` / `docs/architecture.html` if they state the shared-bucket
wording. Do not change `ACCESS_RATE_LIMIT_PER_MIN`.
