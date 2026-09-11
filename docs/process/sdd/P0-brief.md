# Phase brief: P0 — Skeleton + CI

## Spec sections to read first (authoritative): §3 Technology decisions, §4 Repository layout (+4.1, 4.2), §11.5 (vendored assets), §12.3 Environment variables, §15 CI/CD, §16 Testing strategy, §17 Security and safety, Appendix A row P0 — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md

## Standing brief (roadmap §2.2, adapted: you DO commit locally, you never push)
### 2.2 The standing subagent brief (prepended to every phase dispatch)

```
Read docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md sections: <list>.
That spec is authoritative; do not redesign. Implement exactly what it specifies.
Write ONLY the files named in your deliverables list. Commit locally on the current branch using the commit pattern below; never push; never touch .env.
Every span write goes through core/trace.py. Real wall clock everywhere: there is no clock module and
no NOW_OVERRIDE; date-bearing data computes against the mock_data `as_of` snapshot.
Add tests to the existing suite under tests/; do NOT edit .github/workflows/ci.yml unless your
deliverables say so (job `test` already runs the whole suite with `pytest -q`).
Run the acceptance commands yourself and paste the real output; never claim green without it.
If the spec is ambiguous, take the simplest reading that satisfies the requirements and list the choice in your
report. STOP and report only when the ambiguity would change a user-facing contract (/chat or /health JSON,
an MCP tool schema, a dashboard route) or when a definition-of-done command cannot pass as written.
Scratch work goes in the scratchpad directory, never in the repo.
```

### 2.3 Standing acceptance criterion (from P4 onward)

## Commit pattern (roadmap §2.4)
### 2.4 Commit message pattern

Every phase commits with:

```
P<n>(<scope>): <what landed>

- <one bullet per deliverable>
Gate: <the exact command(s) that proved it> — green
Reqs: <comma-separated requirement ids from docs/requirements-traceability.md>

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RnJs3hSPUc8kca4BtF5oAM
```

Scopes: `skeleton`, `core`, `corpus`, `mockdata`, `rag`, `mcpserver`, `llm`, `agent`, `web`, `dashboard`, `eval`, `deploy`, `docs`. Sub-phases use
`P9a(dashboard):` etc. Fix-ups inside a phase reuse the scope with a `fix:` prefix on the subject. Results commits use `P11(eval): published run`.

### 2.5 Size key

## How CI grows (roadmap §3 excerpt)
**How CI grows.** P0 lands `.github/workflows/ci.yml` with jobs `lint` and `test` in their final shape apart from three data steps whose scripts do not
exist yet: **P2** adds `python scripts/check_facts.py`, **P3** adds `python scripts/pii_check.py`, **P4** adds `python -m hrmosaic.rag.ingest
--verify-manifest`, and **P11** adds the `docker` and `deploy` jobs with the `Dockerfile` and `render.yaml`. That is four one-line edits by the phase
that creates the artifact — not a step-ownership table (spec §22 row 14). Every phase's tests reach CI with no workflow edit at all, because the `test`
job's test step is `pytest -q` over the whole suite.

---

## The phase (roadmap §4, verbatim)
### P0 — Skeleton + CI · **S** (2 h) · deps none · ∥ none · no key · commit `P0(skeleton): …`

**Goal.** A repository that lints, tests on an empty suite, and runs CI green on **push and pull request** from commit one.

**Scope.** `pyproject.toml`, `requirements{,-dev}.txt`, `.python-version`, `Makefile`, `.env.example`, `.gitignore`, `.dockerignore`, `README.md`,
`NEEDS-FROM-USER.md`, `CHANGELOG.md`, `.github/workflows/ci.yml`, `src/hrmosaic/settings.py`, `src/hrmosaic/rag/download_model.py`,
`scripts/vendor_assets.py`, `src/hrmosaic/web/static/`, `tests/architecture/test_conventions.py`,
`tests/contract/{test_env_example_covers_settings,test_readme_headings}.py`.

**Deliverables.**
- `settings.py` — every §12.3 variable, **structural validation at import, credential validation deferred**; the `MCP_SERVER_URL`, `GIT_SHA`,
  `LLM_BURST` and `mcp_transport_effective` validators; a 3.12 *warning* that never crashes. `.env.example` mirrors it field for field with
  `# REQUIRED`/`# OPTIONAL`, defaults and signup URLs — and no `SEED`, `NOW_OVERRIDE` or OTEL variable.
- `Makefile`: `setup run run-stdio lint test ingest eval ablation demo1 demo2 docker docker-run-512`. `.gitignore` carrying `data/index/*`,
  `!data/index/chunks.manifest.jsonl`, `data/runtime/`, `.cache/`, `.env` **literally** — a trailing-slash `data/index/` would kill the negation and
  make the manifest uncommittable three phases later.
- `README.md` with its five headings (`## Setup` naming `python3.12 -m venv .venv` literally) and the three first-20-line link lines, each accepting
  `TBD-before-submission`; `rag/download_model.py` (~15 lines — the first CI run is always a cache miss, so it cannot wait for P4); `vendor_assets.py`
  fetching htmx/Alpine/Chart.js at pinned tags into `static/vendor/` and appending `{file, version, upstream_url}` to the hand-authored `LICENSES.md`
  (on a 404 it resolves the nearest release, prints `PINNED <name> <version>` and records it in `CHANGELOG.md`).
- `ci.yml` — jobs `lint` (ruff + `gitleaks` over full history) and `test` (install from the committed manifests → `actions/cache` for
  `.cache/fastembed` → `download_model` → `pytest -q`), on `push: [main]` + `pull_request` + `workflow_dispatch` (`deploy_only`), with `paths-ignore`
  for `evaluation/results/**`, `evaluation/REPORT.md`, `docs/**`, `**/*.md`. `test_conventions.py` ships all five greps, trivially green.
- **The repo is already public** (verified 2026-09-08); no visibility change is ever made by script, and **there is no branch protection** — the deploy
  gate is `needs: [test, docker]` plus `autoDeploy: false`.

**Definition of done.**
```bash
make lint && make test                                        # ruff + ruff format --check; pytest over an empty suite
python -m hrmosaic.rag.download_model && test -d "${FASTEMBED_CACHE_PATH:-.cache/fastembed}"
pytest tests/contract/test_env_example_covers_settings.py tests/contract/test_readme_headings.py -q
pytest tests/architecture/test_conventions.py -q
gh api repos/seantmalone/quantic-mosaic --jq .private         # false — already public; nothing is changed
# the four lines below are run by the MAIN SESSION after it commits P0 — never by the subagent, which touches no git
git switch -c ci-evidence && git commit --allow-empty -m "ci: pull_request evidence" && git push -u origin ci-evidence
gh pr create --base main --head ci-evidence --title "CI evidence (pull_request)" --body "Records a green pull_request run."
gh pr checks --watch && gh pr view --json url -q .url >> CHANGELOG.md && gh pr close ci-evidence --delete-branch
gh run list --limit 5                                         # green on BOTH push and pull_request (RUBRIC5.7)
```

