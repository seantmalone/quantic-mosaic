# What Mosaic HR Copilot needs from Sean

Nothing blocked P0–P10: every phase up to the evaluation harness builds, tests and passes CI with
`LLM_PROVIDER=stub`, and P10's real runs used the model keys already supplied. **P11 is where the
three remaining gates start to bite.** Everything P11 could build and prove without an account is
built and proven — the Dockerfile, `render.yaml`, the CI `docker` and `deploy` jobs, both
provisioning scripts, the deploy-time health scripts, and the 512 MB memory gate run against the
real image (291.3 MB, measured 2026-09-10). What is left is listed here with the **exact command**
that runs the moment each gate is satisfied.

---

## Open gates

- [ ] **2 — Render account + install the Render GitHub App on `seantmalone/quantic-mosaic`.**
      A browser-only OAuth grant; no API can install a GitHub App. Without it Render cannot read
      the repo and no deploy is possible.
      Do it at: https://github.com/apps/render/installations/new → grant access to the repo.
      Needed by: **P11**. Requested: 2026-09-09.
      If it never arrives: no deployment, so RUBRIC5.6 and much of 5.9 fail. The documented
      fallback is Google Cloud Run (same image, but it needs a card), and `make docker-run-512`
      proves the exact image locally regardless — it already has.

- [ ] **3 — Turso account + platform token → `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`.**
      Render's free tier has no persistent disk and wipes the filesystem on every 15-minute
      spin-down, so without Turso any chat session the grader creates is lost. Free, no card,
      provisioned unattended by `scripts/provision_turso.py` from one pasted platform token.
      Do it at: https://turso.tech → GitHub SSO → create a Platform API token → paste it in.
      Needed by: any time after **P1**; a pure environment change with no code change.
      Requested: 2026-09-09.
      If it never arrives: `SqliteStore` remains the coded fallback and committed eval results
      still populate the evaluation pages, but every session created after the last deploy —
      including every session the grader starts — is lost at the next spin-down, and
      `deployed.md` says so plainly.

- [ ] **4 — Render API key.**
      Turns every remaining deploy operation from clicking into scripting: service creation,
      env-var population, deploy-hook retrieval, `gh secret set`, log polling and the free-tier
      budget check. Needs gate 2 first.
      Do it at: Render dashboard → Account Settings → API Keys → Create → paste it in.
      Needed by: **P11**, right after gate 2. Requested: 2026-09-10.
      If it never arrives: roughly fifteen minutes of manual clicking per deploy iteration through
      the committed `render.yaml` Blueprint flow, which stays a supported path precisely for this.

Items 1 (model API keys, supplied 2026-09-09) and 5–7 (the grader invite, the demo recording and
the submission) are tracked in the design spec §19. The keys live only in the git-ignored `.env`.

---

## The exact steps, once the gates land

Two operator credentials are read straight from the process environment — they belong to no runtime
surface, so they are deliberately **not** `Settings` fields and are **not** in `.env.example`:

```sh
export TURSO_PLATFORM_TOKEN=…    # gate 3
export RENDER_API_KEY=…          # gate 4
```

### 1. Provision, in this order

```sh
python scripts/provision_turso.py     # creates the database, mints a non-expiring full-access
                                      #   token, runs the live parity smoke, writes a mode-0600
                                      #   handoff to data/runtime/provision_turso.json
python scripts/provision_render.py    # creates the free service from render.yaml, sets every
                                      #   sync:false env var (the three model keys from .env, the
                                      #   two TURSO_* from the handoff), generates APP_ACCESS_TOKEN
                                      #   with secrets.token_urlsafe(32), and runs `gh secret set`
```

`provision_render.py` prints the tokenized `Deployed: https://<app>.onrender.com/?access=<token>`
line. Paste it into `README.md`'s `Deployed:` line and `deployed.md`'s `## Access`, then delete
`data/runtime/provision_turso.json`.

**The second step no API can do** (re-confirmed against `api-docs.render.com` on 2026-09-10, and
ratified as an amendment to spec §14.6): Render publishes the **deploy hook URL** in the dashboard
(Service → Settings → Deploy Hook) and exposes it through no REST endpoint — the request for one is
still an open thread on Render's own community forum. Copy it and either export
`RENDER_DEPLOY_HOOK_URL` before running `provision_render.py` or run `gh secret set
RENDER_DEPLOY_HOOK_URL` afterwards; the script prints this as a `TODO` line when it cannot find it.
Until that secret exists, CI's `deploy` job **fails on its first step with a message naming this
file** — deliberately, so a missing deploy is never a silently skipped job.

### 2. Verify the deployment

```sh
export DEPLOY_URL=https://<app>.onrender.com
export APP_ACCESS_TOKEN=<the generated token>
python scripts/smoke_deployed.py --url "$DEPLOY_URL"   # git_sha != "dev"; mcp.connected;
                                                       #   no access_token_missing; 401 anonymous,
                                                       #   200 with the bearer
python scripts/measure_cold_start.py --url "$DEPLOY_URL"   # idles ~17 min, then times the four
                                                           #   segments; paste into deployed.md
python scripts/check_render_hours.py                       # warn-only free-tier budget report
```

### 3. The published evaluation run (§13.10)

```sh
EVAL_TARGET_BASE_URL="$DEPLOY_URL" make eval
EVAL_TARGET_BASE_URL="$DEPLOY_URL" python -m evaluation.runner --variant dense_only_k2
EVAL_TARGET_BASE_URL="$DEPLOY_URL" python -m evaluation.runner --variant no_structured_tools
EVAL_TARGET_BASE_URL="$DEPLOY_URL" make ablation
jq -r '.target, .variant' evaluation/results/latest.json                     # deployed  baseline
jq -r '.target, (.variants[].variant)' evaluation/results/comparison.json   # deployed, then the three variants
```

> **The second `jq` was corrected at source on 2026-09-10 (P11 fix round 2).** The P11 brief,
> roadmap §4 and `docs/requirements-traceability.md`'s R9.5 row all used to carry
> `jq -r '.runs[].config_json.target' evaluation/results/comparison.json   # deployed x3`, and that
> command *cannot* pass against any `comparison.json` this project writes — before or after the
> gates land. `evaluation/ablation.py` emits `{generated_at, target, dataset_sha, variants[],
> workflow_completion_check, flips, note}`: there is no `runs` key and no `config_json`, so the old
> command died in `jq: error (…): Cannot iterate over null`. `target` is a *single shared
> top-level field* precisely because `ablation.py` refuses to compare runs whose targets differ,
> which is the §13.9 "three runs sharing `target: deployed`" check the line is asking for. All four
> documents now print the command above, and
> `tests/contract/test_published_run_commands.py` asserts it stays runnable against the committed
> artifact. See P11-report.md §16.

Every eval item sends `Authorization: Bearer $APP_ACCESS_TOKEN` and `X-Actor: admin` and **fails
closed** without both — the privileged `/chat` options are admin-only by design.

### 4. The R8.4 red-run evidence pair, and the screenshots

```sh
git push origin HEAD:ci-red-evidence
gh workflow run ci.yml --ref ci-red-evidence -f deploy_only=true
# the branch carries one deliberately failing test; `test` goes red, and the job graph shows
# `deploy` skipped with the reason "dependent job failed". Screenshot that graph, then delete
# the branch.
```

Three screenshots are committed to `docs/evidence/`, and after this step all three exist:

| File | What it shows | Status |
|---|---|---|
| `mcp-discovery-4-tools.png` | §13.9's `tools/list` from the separate stdio server: 4 tools, the five structured-data tools genuinely absent from discovery | **committed** |
| `mcp-discovery-page.png` | `/dashboard/mcp` rendering live discovery: the server card (`connected yes`, protocol `2025-11-25`, 32 ms handshake, 9 tools), all nine tools with their `input_schema` / `output_schema` / `annotations`, and the handshake-history row | **committed** |
| `ci-deploy-skipped.png` | the job graph of the red run above, `deploy` skipped with the reason "dependent job failed" | needs the push in this step |

All three are named in the repository, in three different files: the design document names the
first and the third (§13.9, §14.5), and `docs/requirements-traceability.md`'s **RUBRIC5.2** row
names the second — *"`/dashboard/mcp` renders live discovery with all nine JSON Schemas (captured
as `docs/evidence/mcp-discovery-page.png`)"* — as does the roadmap's rubric table. Earlier drafts of
this line said "`ci-deploy-skipped.png` plus the two the design document references", which counted
the CI graph twice and sent two fix rounds hunting for a name that was never missing.

---

## Blocked by a gate, and by which

| Deliverable | Gate | Command that produces it |
|---|---|---|
| The live service and its URL | 2 + 4 | `scripts/provision_render.py` |
| Every `sync: false` env var on Render | 2 + 4 (+ 3 for `TURSO_*`) | `scripts/provision_render.py` |
| `RENDER_DEPLOY_HOOK_URL` / `DEPLOY_URL` / `RENDER_API_KEY` repository secrets | 2 + 4 | `scripts/provision_render.py` (`gh secret set`) |
| The tokenized `README.md` `Deployed:` link | 2 + 4 | printed by `scripts/provision_render.py` |
| The Turso database, its token, and the **first live FK/parity answer** | 3 | `scripts/provision_turso.py` |
| Cold start and warm turn on the live instance | 2 | `scripts/measure_cold_start.py` |
| Free-tier hours and build minutes from the account | 2 + 4 | `scripts/check_render_hours.py` |
| The published `target: deployed` eval run, `latest.json`, `comparison.json` | 2 + 4 | the block in step 3 above |
| The R8.4 red-run screenshot and `docs/evidence/*.png` | 2 (a repo push is enough for the graph) | the block in step 4 above |
| Gemini free-tier judge quotas | an authenticated AI Studio session | https://aistudio.google.com/rate-limit |
