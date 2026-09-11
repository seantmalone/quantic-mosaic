# Phase brief: P11

## Spec sections to read first (authoritative): §14 (all: host, Dockerfile, memory budget, cold start, CI-gated deploy), §15 (all), §12.3, §19 (what the user provides; provisioning scripts), §3.1 facts to re-verify — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P11.

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

## Standing acceptance criterion (from P4 onward)
### 2.3 Standing acceptance criterion (from P4 onward)

> *The expected spans were persisted, with the expected kinds and payload shapes.* — checked in every phase gate from P4 on; it is what stops a later
> subagent inventing a parallel logging path, the failure USER.4 forbids.


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


## How CI grows (roadmap §3 excerpt)
**How CI grows.** P0 lands `.github/workflows/ci.yml` with jobs `lint` and `test` in their final shape apart from three data steps whose scripts do not
exist yet: **P2** adds `python scripts/check_facts.py`, **P3** adds `python scripts/pii_check.py`, **P4** adds `python -m hrmosaic.rag.ingest
--verify-manifest`, and **P11** adds the `docker` and `deploy` jobs with the `Dockerfile` and `render.yaml`. That is four one-line edits by the phase
that creates the artifact — not a step-ownership table (spec §22 row 14). Every phase's tests reach CI with no workflow edit at all, because the `test`
job's test step is `pytest -q` over the whole suite.

---

## The phase (roadmap §4, verbatim)
### P11 — Deployment and the published run · **M** (3 h attention, ≈ 2.5 h unattended) · deps P9 + P10 · ∥ none · **keys #2, #3, #4** · commit `P11(deploy): …`

**Goal.** A live free-tier URL with the deploy genuinely gated on tests, and the one `deployed`-mode run every published figure comes from.

**Scope.** `Dockerfile`, `render.yaml`, the `docker` and `deploy` jobs in `ci.yml`, `scripts/{provision_render,provision_turso,wait_for_deploy,
wait_for_health,smoke_deployed,assert_health,measure_cold_start,check_render_hours}.py`, `docs/evidence/*.png`, `deployed.md`. **Step 0:** re-read and
date every §3.1 row naming a live source (spec Appendix A, P11 step 0).

**Deliverables.**
- The Dockerfile of §14.2 (model baked, index built at build time, `sh -c` so `${PORT}` expands) and `render.yaml` with `autoDeploy: false`,
  `healthCheckPath: /health` and every `sync: false` secret.
- The `docker` job (build → `probe_sqlite_vec.py` inside `python:3.12-slim` → run → `wait_for_health` → `assert_health`) and the `deploy` job
  (`needs: [test, docker]`, `if` push-to-`main`, curl the deploy hook → `wait_for_deploy` → `smoke_deployed`).
- Unattended provisioning: the Turso database and scoped token, the Render service, every env var, the deploy hook, and `gh secret set` for
  `RENDER_DEPLOY_HOOK_URL`, `DEPLOY_URL`, `RENDER_API_KEY`. `provision_render.py` generates `APP_ACCESS_TOKEN` with `secrets.token_urlsafe(32)` and
  sets it on Render — no user step — and the full tokenized link `https://<app>.onrender.com/?access=<token>` goes into `README.md`'s `Deployed:` line
  and `deployed.md`'s `## Access`. The deployed eval run fails closed without the token and `X-Actor: admin`.
- **The published run:** `make eval` and `make ablation` against the live URL, all three variants, `baseline` judged, the three cold probes included,
  committed by the main session with `latest.json`, `comparison.json` and `REPORT.md`; plus the three evidence screenshots and the R8.4 red-run pair.

**Definition of done.**
```bash
make docker-run-512                                    # docker run -m 512m with APP_ACCESS_TOKEN set (APP_ENV stays local): /ready green,
                                                       #   one stubbed POST /chat over Authorization: Bearer, /health.app.rss_mb < 420
docker run --rm -d -e PORT=10000 -e LLM_PROVIDER=stub -p 10000:10000 mosaic-hr && python scripts/assert_health.py --url http://127.0.0.1:10000
python scripts/provision_turso.py && python scripts/provision_render.py
python scripts/smoke_deployed.py --url "$DEPLOY_URL"   # bearer header; 200; mcp.connected; git_sha != "dev"; /health lists no access_token_missing
EVAL_TARGET_BASE_URL="$DEPLOY_URL" make eval
EVAL_TARGET_BASE_URL="$DEPLOY_URL" python -m evaluation.runner --variant dense_only_k2
EVAL_TARGET_BASE_URL="$DEPLOY_URL" python -m evaluation.runner --variant no_structured_tools
EVAL_TARGET_BASE_URL="$DEPLOY_URL" make ablation                       # ablation.py only compares runs that already exist
jq -r '.target, .variant' evaluation/results/latest.json                # deployed  baseline
jq -r '.target, (.variants[].variant)' evaluation/results/comparison.json   # deployed, then the three variants
python scripts/measure_cold_start.py && python scripts/check_render_hours.py     # numbers and dates into deployed.md
git push origin HEAD:ci-red-evidence && gh workflow run ci.yml --ref ci-red-evidence -f deploy_only=true   # red run: deploy skipped, "dependent job failed"
EVAL_TARGET_BASE_URL=http://127.0.0.1:8000 pytest tests/integration/test_smoke_eval_endpoint.py -q   # against the running image
ls docs/evidence/*.png                                 # three committed screenshots
```

> **The second `jq` was corrected at source on 2026-09-10 (P11 fix round 2).** It read
> `jq -r '.runs[].config_json.target' … # deployed x3`, which cannot pass against any
> `comparison.json` this project writes: `evaluation/ablation.py` emits
> `{generated_at, target, dataset_sha, variants[], workflow_completion_check, flips, note}` —
> no `runs`, no `config_json` — so the old line died in `jq: error … Cannot iterate over null`.
> `target` is a *single shared top-level field* precisely because `ablation.py` refuses to
> compare runs whose targets differ (§13.9), which is the "three runs sharing `target:
> deployed`" property the line is asking for. See P11-report.md §16.

