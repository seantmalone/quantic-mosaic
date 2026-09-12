# What Mosaic HR Copilot needs from Sean

**Updated at the publish step, 2026-09-11.** Nothing blocked P0–P10: every phase up to the
evaluation harness builds, tests and passes CI with `LLM_PROVIDER=stub`, and P10's real runs used
the model keys already supplied. **Every infrastructure gate has now landed.** Sean supplied the
Render account, the GitHub App, a payment method, the Turso token and the Render API key on
2026-09-10, and enabled paid billing on the judge Cloud project the same day; the service is live
at `https://mosaic-hr-copilot.onrender.com`, the published evaluation sweep ran against it, and the
cold start was measured on it. **Two gates are left, both irreducibly human:** recording the demo
video (**gate 6**) and submitting (**gate 7**). The `quantic-grader` invitation is **accepted** —
re-verified 2026-09-11, `permission: read` with no pending invitation — and the last optional item
(**2b**, `MCP_ALLOWED_HOSTS` on the live service) was **discharged on 2026-09-11**: the deployed MCP
endpoint now accepts external MCP clients, verified at 20:32Z. The keep-alive variable that used to
sit beside it is an operator preference that moves no published number, and it is tracked in
`deployed.md` rather than as a gate.

Item numbering follows design spec §19.1, so a number here means the same thing there. A
**letter-suffixed** item (1a, 2a) is one the build discovered that §19.1 never anticipated; it is
numbered against the gate it belongs to rather than renumbering the list.

---

## Open gates

- [ ] **6 — Record the 7–10 minute demo video.**
      On camera, audible narration, government ID shown, **both agentic tasks executed live
      against the deployed URL**, plus design / deployment / CI-CD / evaluation walkthroughs.
      Irreducibly human. **~60–90 minutes including rehearsal and retakes.**
      Follow [`docs/demo-script.md`](docs/demo-script.md), which is time-boxed segment by segment
      and carries a five-element sub-checklist per task; tick
      [`docs/pre-submission-checklist.md`](docs/pre-submission-checklist.md) as you go.
      Needed by: submission. **Unblocked** — the URL has been live since 2026-09-10. Wake the
      instance with `GET /health` before you start recording; a cold start is ~71 s.
      If it never arrives: automatic fail on every demo bullet. There is no substitute.

- [ ] **7 — Submit the two links** through the Quantic dashboard's *Submit Project* button.
      Only the enrolled student can submit. **~2 minutes.** Both links are pre-staged in the first
      20 lines of `README.md`, so it is a copy-paste.
      Needed by: the deadline. Blocked by gate 6.

## Discharged

- [x] **1 — Model API keys.** Provided **2026-09-09**: an Anthropic key (`ANTHROPIC_API_KEY`, the
      agent on `claude-haiku-4-5`) and **two** Google AI Studio keys from two different Cloud
      projects, one for `JUDGE_API_KEY` and one for `LLM_FALLBACK_API_KEY`, so the judge and the
      agent's failover path never contend for the same quota or bill. All three validated on
      2026-09-09. They live only in the git-ignored `.env`.
- [x] **1a — Paid billing on the judge Cloud project.** Enabled by Sean on **2026-09-10** after
      both free projects' 500-requests-per-day quota was exhausted mid-sweep and the alternative
      was either waiting for the 07:10 UTC reset or swapping the judge model, which would have
      broken comparability with every earlier judged artifact. `gemini-3.5-flash-lite` now bills at
      the paid standard rates, $0.30 / $2.50 per MTok: **≈ $0.16–0.18 a judge pass**. The failover
      project is deliberately still on a free key — its spend would be unbounded.
- [x] **2 — Render account + the Render GitHub App.** Granted **2026-09-10**. Service
      `mosaic-hr-copilot` (`srv-dahcsj95efls73dibqeg`) created on `plan: free`, region `oregon`,
      live at `https://mosaic-hr-copilot.onrender.com`.
- [x] **2a — A payment method on the Render workspace.** A gate this file never had, discovered
      post-gate: Render refuses to create **any** service, free ones included, without one
      (`402 Payment information is required`). No API can add it. Provided **2026-09-10**. The
      workspace stays on the free plan; nothing is billable, and `plan: free` is asserted from the
      API's own read-back before and after the service was created rather than from the request.
- [x] **2b — `MCP_ALLOWED_HOSTS` on the live Render service.** *Optional; the project was complete
      without it, and every document said so.* Set on the service on **2026-09-11** — the service
      had been created over the REST API before the variable existed, and a code deploy does not
      change a service's environment, so it was one Environment entry (`render.yaml` carries the
      same value, so a blueprint apply or a re-run of `scripts/provision_render.py` sets it too).
      Value: `127.0.0.1:*,localhost:*,mosaic-hr-copilot.onrender.com`. The MCP SDK enables
      DNS-rebinding protection for a loopback-bound server, so without it the deployed
      `/mcp-server/mcp` answered **HTTP 421** to an external MCP Inspector session. **Verified at
      20:32Z**: an external `initialize` over the public hostname answered **HTTP 200**, a full
      external session listed all nine tools and ran two of them, a `create_mock_hr_ticket` without
      a confirmation token was refused `CONFIRMATION_REQUIRED` (and so was the same call with a
      forged token), and a request with no bearer got 401.
      **`KEEP_ALIVE_URL` is no longer carried here as a gate.** It arms the in-process self-ping,
      which would remove the ~71 s cold start for a grader's first click at a cost of ~744 of the
      workspace's 750 free instance-hours a month — a reversible operator preference, not a
      prerequisite for anything published: every cold-start figure in this repository is measured
      **without** it, so no number moves whichever way it is left. `render.yaml` carries it,
      `deployed.md` § *Cold start* → *Keep-alive* records its state and both menus that change it,
      and `tests/contract/test_keep_alive.py` holds the published wording to that state.
- [x] **3 — Turso account + platform token.** Provided **2026-09-10**. Database `mosaic-hr` in
      organisation `seantm`, group `default`, location `aws-us-west-2`, Starter plan with
      `overages: false`. The live parity smoke answered P1's carry-forward: foreign keys **are**
      enforced on the Hrana `/v2/pipeline` path.
- [x] **4 — Render API key.** Provided **2026-09-10**. Everything after it was scripted: service
      creation, every `sync: false` env var, `gh secret set` for `DEPLOY_URL`, `RENDER_API_KEY` and
      `RENDER_SERVICE_ID`, deploy triggering, log polling and the free-tier budget check.
      **`RENDER_DEPLOY_HOOK_URL` turned out not to be required**: no REST endpoint publishes it, so
      CI's `deploy` job triggers production with `POST /v1/services/{id}/deploys` instead and uses
      the hook only when that secret exists. The last irreducibly manual deploy step is therefore
      gone.
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

## The exact steps — all of these have now been run

Kept as the record of what was done, and as the recipe for a rebuild or a rotation.

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
line. It was pasted into `README.md`'s `Deployed:` line and into `deployed.md`'s `## Access`, and
`data/runtime/provision_turso.json` was deleted afterwards.

**There is no manual browser step left.** Render publishes the **deploy hook URL** in the dashboard
(Service → Settings → Deploy Hook) and through no REST endpoint — re-confirmed against the live
account on 2026-09-10, where `deploy-hook`, `deployHook`, `hooks`, `deploy-hooks` and `settings`
under `/v1/services/{id}` all answer 404 and `GET /v1/services/{id}` carries no `deployHookUrl`. So
CI's deploy step curls `$RENDER_DEPLOY_HOOK_URL` when that secret exists and otherwise POSTs
`/v1/services/$RENDER_SERVICE_ID/deploys` with `RENDER_API_KEY`, and `provision_render.py` sets
`RENDER_SERVICE_ID` itself. The hook is an **optional alternative**, not a requirement, and R8.4 is
unchanged: `needs: [test, docker]` still gates the job and Render Auto-Deploy is still off. Proven
live on 2026-09-10 — deploy `dep-dahcukqfngtc7390n740`, `trigger: api`.

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

All three screenshots are committed to `docs/evidence/`; the block above is kept as the recipe that produced the third.

| File | What it shows | Status |
|---|---|---|
| `mcp-discovery-4-tools.png` | §13.9's `tools/list` from the separate stdio server: 4 tools, the five structured-data tools genuinely absent from discovery | **committed** |
| `mcp-discovery-page.png` | `/dashboard/mcp` rendering live discovery: the server card (`connected yes`, protocol `2025-11-25`, 32 ms handshake, 9 tools), all nine tools with their `input_schema` / `output_schema` / `annotations`, and the handshake-history row | **committed** |
| `ci-deploy-skipped.png` | the job graph of the red run above, `deploy` skipped with the reason "dependent job failed" | **committed** — run [`actions/runs/34485304411`](https://github.com/seantmalone/quantic-mosaic/actions/runs/34485304411) |

All three are named in the repository, in four different files: the design document names all
three (§*Evidence*), `deployed.md` names the third, and
`docs/requirements-traceability.md`'s **RUBRIC5.2** row names the second — *"`/dashboard/mcp`
renders live discovery with all nine JSON Schemas (captured as
`docs/evidence/mcp-discovery-page.png`)"* — as does the roadmap's rubric table. Earlier drafts of
this line said "`ci-deploy-skipped.png` plus the two the design document references", which counted
the CI graph twice and sent two fix rounds hunting for a name that was never missing.

---

## Which gate produced what — and what is still open

| Deliverable | Gate | Produced by | State |
|---|---|---|---|
| The live service and its URL | 2 + 2a + 4 | `scripts/provision_render.py` | **done** 2026-09-10 |
| Every `sync: false` env var on Render | 2 + 4 (+ 3 for `TURSO_*`) | `scripts/provision_render.py` | **done** 2026-09-10 |
| `DEPLOY_URL` / `RENDER_API_KEY` / `RENDER_SERVICE_ID` repository secrets (`RENDER_DEPLOY_HOOK_URL` optional) | 2 + 4 | `scripts/provision_render.py` (`gh secret set`) | **done** 2026-09-10 |
| The tokenized `README.md` `Deployed:` link | 2 + 4 | printed by `scripts/provision_render.py` | **done** 2026-09-10 |
| The Turso database, its token, and the **first live FK/parity answer** | 3 | `scripts/provision_turso.py` | **done** 2026-09-10 — FKs enforced |
| Cold start and warm turn on the live instance | 2 | `scripts/measure_cold_start.py` | **done** 2026-09-10 and 2026-09-11 (n=3; median 71.0 s cold, 22.5 s warm) |
| Free-tier hours and build minutes from the account | 2 + 4 | `scripts/check_render_hours.py` | **done** 2026-09-11 — build minutes ~11.5 of 500; instance hours unavailable from the API |
| The published `target: deployed` eval run, `latest.json`, `comparison.json` | 2 + 4 | the block in step 3 above | **done** 2026-09-11 — `r_1789166880_baseline`, judged, 28 items |
| `design-and-evaluation.md`'s results table, from the published run | 2 + 4 | `scripts/paste_eval_numbers.py` | **done** 2026-09-11 |
| The deployed MCP endpoint reachable by an external client | 2b | one Environment entry (`MCP_ALLOWED_HOSTS`) | **done** 2026-09-11 — external `initialize` → HTTP 200 at 20:32Z |
| Both demo scripts run against the live URL | 2 + 4 | `BASE_URL="$DEPLOY_URL" bash scripts/demo_task_{1,2}.sh` | **done** 2026-09-10 — demo 2 wrote `MOCK-HR-000001` behind the gate |
| `/health.trace_store.eval_runs_imported` matching the committed count | 2 + 4 | the block in step 4 above | **done** 2026-09-10 |
| The R8.4 red-run screenshot and `docs/evidence/*.png` | 2 (a repo push is enough for the graph) | the block above | **done** — all three committed |
| The demo video, and therefore `README.md`'s `Demo video:` link | **6** | `docs/demo-script.md` | **open** |
| The `quantic-grader` invitation confirmed as sent or accepted | **7** | `docs/pre-submission-checklist.md` `- [x] SUB.3` | **done** — accepted, re-verified 2026-09-11 |
| The submission itself | **7** | the Quantic dashboard | **open** |
| Gemini rate limits for the failover project (the judge's is on paid billing since 2026-09-10) | an authenticated AI Studio session | https://aistudio.google.com/rate-limit | still unread — affects nothing a published run depends on |
