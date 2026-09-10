# What Mosaic HR Copilot needs from Sean

**Final, at P12.** Nothing blocked P0–P10: every phase up to the evaluation harness builds, tests
and passes CI with `LLM_PROVIDER=stub`, and P10's real runs used the model keys already supplied.
**P11 is where the remaining gates start to bite.** Everything P11 and P12 could build and prove
without an account is built and proven — the Dockerfile, `render.yaml`, the CI `docker` and
`deploy` jobs, both provisioning scripts, the deploy-time health scripts, the 512 MB memory gate
run against the real image (294.9 MB, measured 2026-09-10), and all five documentation files.
What is left is listed here, each with the **exact command** that runs the moment its gate is
satisfied.

Item numbering follows design spec §19.1, so a number here means the same thing there.

---

## Open gates

- [ ] **2 — Render account + install the Render GitHub App on `seantmalone/quantic-mosaic`.**
      A browser-only OAuth grant; no API can install a GitHub App. Without it Render cannot read
      the repo and no deploy is possible. **~5 minutes.**
      Do it at: https://github.com/apps/render/installations/new → grant access to the repo.
      Needed by: **P11**. Requested: 2026-09-09.
      If it never arrives: no deployment, so RUBRIC5.6 and much of 5.9 fail. The documented
      fallback is Google Cloud Run (same image, but it needs a card), and `make docker-run-512`
      proves the exact image locally regardless — it already has.

- [ ] **3 — Turso account + platform token → `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`.**
      Render's free tier has no persistent disk and wipes the filesystem on every 15-minute
      spin-down, so without Turso any chat session the grader creates is lost. Free, no card,
      provisioned unattended by `scripts/provision_turso.py` from one pasted platform token.
      **~5 minutes.**
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
      budget check. Needs gate 2 first. **~2 minutes.**
      Do it at: Render dashboard → Account Settings → API Keys → Create → paste it in.
      Needed by: **P11**, right after gate 2. Requested: 2026-09-10.
      If it never arrives: roughly fifteen minutes of manual clicking per deploy iteration through
      the committed `render.yaml` Blueprint flow, which stays a supported path precisely for this.

- [ ] **6 — Record the 7–10 minute demo video.**
      On camera, audible narration, government ID shown, **both agentic tasks executed live
      against the deployed URL**, plus design / deployment / CI-CD / evaluation walkthroughs.
      Irreducibly human. **~60–90 minutes including rehearsal and retakes.**
      Follow [`docs/demo-script.md`](docs/demo-script.md), which is time-boxed segment by segment
      and carries a five-element sub-checklist per task; tick
      [`docs/pre-submission-checklist.md`](docs/pre-submission-checklist.md) as you go.
      Needed by: submission. Blocked by gates 2 + 4 — the URL must be live first.
      If it never arrives: automatic fail on every demo bullet. There is no substitute.

- [ ] **7 — Submit the two links** through the Quantic dashboard's *Submit Project* button.
      Only the enrolled student can submit. **~2 minutes.** Both links are pre-staged in the first
      20 lines of `README.md`, so it is a copy-paste.
      Needed by: the deadline. Blocked by gate 6.

## Discharged

- [x] **1 — Model API keys.** Provided **2026-09-09**: an Anthropic key (`ANTHROPIC_API_KEY`, the
      agent on `claude-haiku-4-5`) and **two** Google AI Studio keys from two different Cloud
      projects, one for `JUDGE_API_KEY` and one for `LLM_FALLBACK_API_KEY`, so the judge and the
      agent's failover path never contend for the same quota or bill — the judge's project moved to
      paid billing on 2026-09-10, the failover's is still free. All three validated on 2026-09-09.
      They live only in the git-ignored `.env`.
- [x] **5 — `quantic-grader` collaborator invite.** Scripted, **no user action**: run at P12 with
      `gh api -X PUT repos/seantmalone/quantic-mosaic/collaborators/quantic-grader`, read back
      with `…/collaborators/quantic-grader/permission`. The repository was verified **already
      public** on 2026-09-08, and **no visibility change is ever made by script**. Your only
      action is confirming at submission time that the invite shows as sent or accepted — that is
      the `- [ ] SUB.3` line in `docs/pre-submission-checklist.md`.

**The access gate adds nothing to this list.** `scripts/provision_render.py` generates
`APP_ACCESS_TOKEN` itself with `secrets.token_urlsafe(32)` and sets it on the service alongside
the other `sync: false` variables — no key to create, no value to paste, and one environment
change to rotate it after grading.

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
line. Paste it into `README.md`'s `Deployed:` line (replacing the `pending: gate 2 + 4` marker)
and into `deployed.md`'s `## Access`, then delete `data/runtime/provision_turso.json`.

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
python scripts/paste_eval_numbers.py                                        # refresh the results
                                                                            #   table in
                                                                            #   design-and-evaluation.md
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

### 4. Get the results onto the live dashboard, and prove they arrived

A results commit deliberately does **not** trigger a rebuild (`ci.yml` carries `paths-ignore` for
`evaluation/results/**`, `evaluation/REPORT.md`, `docs/**` and repo-root `*.md`), so it spends no
build minutes. Push the results, then dispatch a deploy explicitly and check the import:

```sh
gh workflow run ci.yml -f deploy_only=true
curl -s "$DEPLOY_URL/health" | jq '.trace_store.eval_runs_imported'   # matches the committed count
```

### 5. Then record and submit

Gate 6, then gate 7 — `docs/demo-script.md` and `docs/pre-submission-checklist.md`.

---

## The R8.4 red-run evidence pair, and the screenshots

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

All three are named in the repository, in four different files: the design document names all
three (§*Evidence*), `deployed.md` names the third, and
`docs/requirements-traceability.md`'s **RUBRIC5.2** row names the second — *"`/dashboard/mcp`
renders live discovery with all nine JSON Schemas (captured as
`docs/evidence/mcp-discovery-page.png`)"* — as does the roadmap's rubric table. Earlier drafts of
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
| `design-and-evaluation.md`'s results table, from the published run | 2 + 4 | `scripts/paste_eval_numbers.py` |
| Both demo scripts run against the live URL | 2 + 4 | `BASE_URL="$DEPLOY_URL" bash scripts/demo_task_{1,2}.sh` |
| `/health.trace_store.eval_runs_imported` matching the committed count | 2 + 4 | the block in step 4 above |
| The R8.4 red-run screenshot and `docs/evidence/*.png` | 2 (a repo push is enough for the graph) | the block above |
| The demo video, and therefore `README.md`'s `Demo video:` link | 6 | `docs/demo-script.md` |
| The submission itself | 7 | the Quantic dashboard |
| Gemini rate limits and billing state for the two Cloud projects (judge: paid since 2026-09-10; failover: free) | an authenticated AI Studio session | https://aistudio.google.com/rate-limit |
