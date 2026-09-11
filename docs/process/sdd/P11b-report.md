# P11b — post-gate deployment, the published run · implementation report

All three user gates landed on 2026-09-10: the Render GitHub App is installed on
`seantmalone/quantic-mosaic`, and `TURSO_PLATFORM_TOKEN` / `RENDER_API_KEY` are in the git-ignored
`.env`. This report is the record of what the post-gate commands actually did, pasted as they ran.
No secret value appears here: tokens are reported as a SHA-256 fingerprint and a length, and the
tokenized deployed link lives only in `data/runtime/post_gate_results.json` (git-ignored, 0600).

- Head at start: `5419ec5` (P11), with P12's docs commit `a3df454` on top.
- Working rule: only `scripts/provision_*.py`, `scripts/wait_for_deploy.py`,
  `scripts/smoke_deployed.py`, `scripts/measure_cold_start.py`, `scripts/check_render_hours.py`,
  `render.yaml`, `Dockerfile`, `evaluation/**` and their tests are touched here; P12 owns every
  root document.

---

## 1. `python scripts/provision_turso.py` — the database, the token, the first live parity answer

### 1.1 The first run failed, and the live API shape is why

```
$ python scripts/provision_turso.py
FAIL — POST /v1/organizations/seantm/databases answered 400: {"error":"group not found"}
```

`provision_turso.py` carried the comment *"Every Turso workspace is created with a `default`
group; the free tier allows exactly one."* That is not true of a workspace made through the
current signup flow:

```
$ curl -sS -H "Authorization: Bearer $TURSO_PLATFORM_TOKEN" \
    https://api.turso.tech/v1/organizations/seantm/groups | jq .
{
  "groups": []
}
```

There were no groups at all, so `POST …/databases` had nothing to create the database *into*. This
is exactly the class of thing P11 flagged as unverifiable without an account — the script was
written against the documented shapes and the docs do not say a workspace starts empty.

### 1.2 The minimal fix

`scripts/provision_turso.py` gained `ensure_group()`, three client methods (`groups`,
`create_group`, `get_group`) and a `--location`:

- a workspace with no group gets one, named by `--group` (default `default`);
- it is created in `DEFAULT_LOCATION = aws-us-west-2` — `https://region.turso.io` reports
  `{"server":"aws-us-west-2","client":"sjc"}` as the closest of the six `GET /v1/locations`
  offers, and Render's free plan places services in Oregon (US West), so the instance and its
  database sit in the same region instead of crossing the continent on every Hrana round trip;
- creating a group provisions a machine, so the group is polled (3 s, 90 s ceiling) until the API
  stops reporting it pending — otherwise the next `POST …/databases` races it;
- an existing group is adopted and never duplicated: the free tier allows exactly one.

Four new unit tests in `tests/unit/test_provision_turso.py`, and the `RecordingApi` fixture now
**starts with no groups** and returns the live `400 {"error":"group not found"}` if a database
create ever again arrives for a group that does not exist:

```
$ .venv/bin/pytest tests/unit/test_provision_turso.py -q
...............                                                          [100%]
15 passed in 0.04s
```

### 1.3 The re-run · **GREEN**

```
$ python scripts/provision_turso.py
  organization=seantm  database=mosaic-hr  created
  group=default  created in aws-us-west-2
  TURSO_DATABASE_URL=libsql://mosaic-hr-seantm.aws-us-west-2.turso.io
  TURSO_AUTH_TOKEN=sha256:fff6fd23a688 (348 chars)
  parity smoke: round trip ok · PRAGMA foreign_keys=1 · orphan INSERT rejected=True

OK — Turso is provisioned. The two values were written to data/runtime/provision_turso.json (mode
0600, git-ignored); `python scripts/provision_render.py` reads them from there and sets them on the
service. Delete the file once the deploy is green.
```

### 1.4 P1's carry-forward, answered: **foreign keys ARE enforced on the Hrana path**

This is the first time anything in this project has spoken to a live Turso database. The open
question since P1 was whether `TursoHTTPStore` — which has no connection to issue
`PRAGMA foreign_keys=ON` on, unlike `SqliteStore.__init__` — gets foreign-key enforcement at all.

**It does.** `PRAGMA foreign_keys` returned **1**, and the probe's real orphan-child INSERT
(`INSERT INTO _mosaic_fk_probe_child (id, parent_id) VALUES (1, 999999)` against an empty parent
table) was **rejected** by the server. The smoke therefore raised **no warning**. Turso's Hrana/HTTP
front end enables foreign keys per connection itself, so the audit trail's parent-before-child
ordering in `core/trace.py` (§10.1, §10.3) is a belt to the platform's braces rather than the only
thing holding the referential integrity of `sessions → turns → spans` together.

---

## 2. `python scripts/provision_render.py` — BLOCKED on a gate nobody had listed

### 2.1 The failure

```
$ python scripts/provision_render.py
FAIL — POST /v1/services answered 402: {"message":"Payment information is required to complete
this request. To add a card, visit https://dashboard.render.com/billing"}
```

### 2.2 It is not a script bug

Reproduced against the API by hand, with the exact payload the script sends:

```
$ curl -sS -X POST https://api.render.com/v1/services \
    -H "Authorization: Bearer $RENDER_API_KEY" -H "Content-Type: application/json" \
    -d '{"type":"web_service","name":"mosaic-hr-copilot","ownerId":"tea-dahckv7qj5pc73a64jd0",
         "repo":"https://github.com/seantmalone/quantic-mosaic","branch":"main","autoDeploy":"no",
         "serviceDetails":{"runtime":"docker","plan":"free","region":"oregon","numInstances":1,
                           "healthCheckPath":"/health",
                           "envSpecificDetails":{"dockerfilePath":"./Dockerfile","dockerContext":"."}}}'
HTTP 402
{"message":"Payment information is required to complete this request. To add a card, visit
https://dashboard.render.com/billing"}
```

### 2.3 What was ruled out first

| Hypothesis | Check | Result |
|---|---|---|
| the script adopted the wrong owner | `GET /v1/owners` | exactly one: `tea-dahckv7qj5pc73a64jd0` "Sean's workspace", type `team`. There is no second personal workspace to fall back to |
| a pre-existing service is consuming the free allowance | `GET /v1/services` | `0` services |
| gate 2 (the GitHub App) is the real cause | the 402 body | it is not: the 402 is returned *before* any repository check, and it names payment explicitly. Gate 2 stays **unverified** — the first successful create is what will prove it |
| a paid plan would go through | not attempted | deliberately: retrying with `plan: starter` would have created a billable service without approval |

### 2.4 The verdict

This is **not** the "repository is not accessible" case the brief anticipated. It is Render's
current anti-abuse policy: a workspace must carry a verified payment method before it can create
*any* service, free instances included. Render does not charge for a free instance; the card is
verification only. No API can add it — it is a browser step at
`https://dashboard.render.com/billing`, and therefore a **new user gate** that
`NEEDS-FROM-USER.md`'s gate list never anticipated (gate 4 assumed the API key was the last thing
Render needed).

Escalated to the controller with the exact error. Steps 3–6 are all downstream of a live service,
so nothing below this line could run; every one of them is **BLOCKED-BY-GATE (Render billing)**
rather than skipped. `provision_render.py` is idempotent and adopts-or-creates, so the re-run is a
single command once the card is on file.

**There is no card-free path to a live URL.** `NEEDS-FROM-USER.md`'s documented fallback is Google
Cloud Run, which also requires a card. `make docker-run-512` continues to prove the exact image
locally and that evidence is already committed (P11 §2.1).

### 2.5 The gate was satisfied — and the guards that went in before the re-run

Sean added a payment method at `dashboard.render.com/billing`. The controller attached a hard
constraint to the go-ahead: *"do not deploy anything that will cost me money."* Adding the card
turns a plan mistake from a rejected request into a monthly bill, so that constraint went into the
script as executable checks rather than being held in the operator's head:

| Guard | Where |
|---|---|
| `render.yaml`'s plan must be `free` | first line of `provision()`, before any request is made |
| the create payload must carry `plan: free`, `numInstances: 1`, no `disk`, no `autoscaling` | `assert_free_payload()`, called inside `RenderClient.create_service()` so no caller can route around it |
| the **created** service is re-read from the API and its own reported plan asserted | `client.get_service(service_id)` → `assert_free_service(context="after creating the service")` |
| an **adopted** service's plan is asserted the same way, and never patched | same call, `context="adopting the existing service"` |
| `PATCH /v1/services/{id}` refuses `plan`, `numInstances`, `disk`, `autoscaling`, `instanceType`, `region` — nested under `serviceDetails` too | `RenderClient.update_service()`; `autoDeploy` remains the one legitimate write |

Everything raises `BillablePlan`, which deletes nothing and changes nothing. Seven new unit tests
in `tests/unit/test_provision_render.py` (25 in the file, all green), including a service that
comes back on `starter` and one adopted on `standard` — both stop the run before a single `PUT`.

### 2.6 The re-run · **GREEN**

```
$ python scripts/provision_render.py
  service=mosaic-hr-copilot (srv-dahcsj95efls73dibqeg)  created
  plan=free as reported by the service (asserted, not assumed)
  url=https://mosaic-hr-copilot.onrender.com  auto_deploy=OFF (R8.4) as reported by the service
  APP_ACCESS_TOKEN generated: sha256:1852be7c431e (43 chars)
  github secrets set: DEPLOY_URL, RENDER_API_KEY

  Deployed: https://mosaic-hr-copilot.onrender.com/?access=<redacted — see
            data/runtime/post_gate_results.json>
  TODO — set the RENDER_DEPLOY_HOOK_URL repository secret by hand: `gh secret set
         RENDER_DEPLOY_HOOK_URL` — copy it from the Render dashboard (Service → Settings → Deploy
         Hook); the REST API does not expose it (§14.6)
```

The service as the API reports it, immediately after creation — this is the cost evidence, read
back rather than asserted from the payload:

```
$ curl -sS -H "Authorization: Bearer $RENDER_API_KEY" \
    https://api.render.com/v1/services/srv-dahcsj95efls73dibqeg | jq .serviceDetails
{
  "plan": "free",
  "numInstances": 1,
  "region": "oregon",
  "runtime": "docker",
  "buildPlan": "starter",
  "healthCheckPath": "/health",
  "envSpecificDetails": { "dockerfilePath": "./Dockerfile", "dockerContext": "." },
  "pullRequestPreviewsEnabled": "no",
  "previews": { "generation": "off" },
  "url": "https://mosaic-hr-copilot.onrender.com"
}
… "autoDeploy": "no", "autoDeployTrigger": "off", "suspended": "not_suspended"
```

`plan: free`, one instance, no `disk` key at all, PR previews off (each preview would be another
service), auto-deploy off at both the old `autoDeploy` field and the newer `autoDeployTrigger`.
`buildPlan: starter` is Render's name for the build tier included with a free service, not a paid
selection — no request this script makes ever names a build plan.

All ten environment variables arrived (names only; four plain from `render.yaml`, five `sync: false`
credentials, one generated token):

```
$ curl -sS … /env-vars | jq -r '.[].envVar.key' | sort
ANTHROPIC_API_KEY  APP_ACCESS_TOKEN  APP_ENV  JUDGE_API_KEY  LLM_FALLBACK_API_KEY
LLM_MODEL  LLM_PROVIDER  OMP_NUM_THREADS  TURSO_AUTH_TOKEN  TURSO_DATABASE_URL
```

**Gate 2 is confirmed by this**: creating the service with `repo:
https://github.com/seantmalone/quantic-mosaic` succeeded and Render immediately began building
commit `5419ec5` from `main`, which it could not read without the GitHub App installation.

### 2.7 `RENDER_DEPLOY_HOOK_URL` — still the one value no API exposes

Two of the three §15.2 secrets were set by the script (`DEPLOY_URL`, `RENDER_API_KEY`). The third
was not, and P11's finding is re-confirmed against the live account rather than against the docs —
every plausible endpoint 404s:

```
$ for p in deploy-hook deployHook hooks deploy-hooks settings; do
    curl -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $RENDER_API_KEY" \
      "https://api.render.com/v1/services/srv-dahcsj95efls73dibqeg/$p"; done
404
404
404
404
404
```

`GET /v1/services/{id}` returns no `deployHookUrl` field either (its full body is above). So the
single remaining manual step of §14.6 stands: copy the hook from the dashboard at
`https://dashboard.render.com/web/srv-dahcsj95efls73dibqeg` → Settings → Deploy Hook, then
`gh secret set RENDER_DEPLOY_HOOK_URL`. Until it exists, CI's `deploy` job fails on its first step
naming `NEEDS-FROM-USER.md`, deliberately.

---

## 3. The deploy-hook ruling, and the two changes it produced

The controller ruled against waiting for a browser step: CI should trigger deploys through the
Render API, which needs only credentials `provision_render.py` already holds, keeping the hook as
an equivalent alternative.

### 3.1 `.github/workflows/ci.yml` — an OR guard and a two-path trigger

`The deploy secrets must exist` now passes when **either** `RENDER_DEPLOY_HOOK_URL` is set **or**
`RENDER_API_KEY` and `RENDER_SERVICE_ID` are both set, and fails with the same
`NEEDS-FROM-USER.md` message otherwise. `Trigger Render deploy` prefers the hook and otherwise
`POST`s `/v1/services/$RENDER_SERVICE_ID/deploys`. `AUTH_HEADER` is built into a variable rather
than written on the curl line, exactly as the Makefile's memory gate does, so gitleaks'
`curl-auth-header` rule has nothing token-shaped to read.

R8.4 is untouched: `needs: [test, docker]` still gates the job and Render's own Auto-Deploy is still
off (`autoDeploy: "no"`, `autoDeployTrigger: "off"`, both read back from the live service), so a
commit reaches production only by passing through this job.

Four contract tests changed or added in `tests/contract/test_deploy_manifests.py` (30 green): the
guard names all three credentials; the OR is asserted as an OR (a lone `RENDER_API_KEY` without the
service id is still not enough); the trigger step carries both paths and runs before the wait and
the smoke; and no bearer token sits on a curl line.
`test_no_model_key_and_no_access_token_is_a_ci_secret` grew from an exact three-name list to five
plus an explicit forbidden set — the invariant it always meant is that **nothing CI holds is a
credential the application answers with**, and `RENDER_API_KEY` / `RENDER_SERVICE_ID` both address
Render's control plane.

### 3.2 `scripts/provision_render.py` — `RENDER_SERVICE_ID`, and a deploy that carries the variables

The live run exposed a real bug that no `MockTransport` could have: **Render starts a deploy one
second after the service is created, before the env-var `PUT` lands**. That first build came up
green and useless —

```
$ python scripts/smoke_deployed.py --url "$DEPLOY_URL"
FAIL — 1 problem(s):
  - GET / without a token answered HTTP 200, expected 401 — the access gate is not on
  status=degraded  git_sha=5419ec5…  deploy_mode=local  uptime_ms=98059
  degradations=['llm_api_key_missing']
```

`deploy_mode=local`, `llm.agent.configured=false`, `trace_store.backend=sqlite`, gate off. Nothing
went red; the deploy was `live`. So `provision()` now ends by calling
`POST /v1/services/{id}/deploys` (`clearCache: do_not_clear`, which keeps Render's layer cache and
creates no resource), suppressible with `--no-deploy`, and reports the deploy id. `GITHUB_SECRETS`
gained `RENDER_SERVICE_ID`. Six unit tests cover it, including the ordering assertion that the
`PUT` precedes the deploy.

### 3.3 The API trigger, proven live — this is the exact command CI runs

```
$ AUTH_HEADER="Authorization: Bearer $RENDER_API_KEY"
$ curl -fsS -X POST "https://api.render.com/v1/services/srv-dahcsj95efls73dibqeg/deploys" \
    -H "$AUTH_HEADER" -H 'Content-Type: application/json' -d '{"clearCache":"do_not_clear"}'
{ "id": "dep-dahcukqfngtc7390n740", "status": "build_in_progress",
  "commit": "5419ec5ec84c78d56486413405eb2405bdb686e4", "trigger": "api" }
```

`trigger: "api"` is the proof the path works end to end. It went `build_in_progress` →
`update_in_progress` → `live`, and the smoke below is against that deploy.

```
$ gh secret list
DEPLOY_URL         2026-09-10T15:35:44Z
RENDER_API_KEY     2026-09-10T15:35:45Z
RENDER_SERVICE_ID  2026-09-10T15:39:38Z
```

---

## 4. Step 3 — the deployed instance, verified

### 4.1 `wait_for_deploy.py` and `smoke_deployed.py` · **GREEN**

```
$ python scripts/wait_for_deploy.py --url "$DEPLOY_URL" --sha 5419ec5ec84c78d56486413405eb2405bdb686e4
waiting for https://mosaic-hr-copilot.onrender.com to report git_sha 5419ec5ec84c78d56486413405eb2405bdb686e4
https://mosaic-hr-copilot.onrender.com is serving git_sha 5419ec5ec84c78d56486413405eb2405bdb686e4 after 0s

$ python scripts/smoke_deployed.py --url "$DEPLOY_URL"
  status=ok  git_sha=5419ec5ec84c78d56486413405eb2405bdb686e4  deploy_mode=render  uptime_ms=41277
  mcp.connected=True  tool_count=9
  degradations=[]
  access gate: checked with APP_ACCESS_TOKEN from the environment

OK — https://mosaic-hr-copilot.onrender.com is serving a real build with its MCP server connected.
```

The deployed sha is `5419ec5`, which is the remote `main` — the brief's "5419ec5 or newer". The two
local commits above it (P12's `a3df454` and this phase's own) are unpushed by design; the controller
pushes.

### 4.2 By hand, with curl

```
$ curl -sS "$DEPLOY_URL/health" | jq '{status, deploy_mode: .app.deploy_mode, …}'
{
  "status": "ok",
  "git_sha": "5419ec5ec84c78d56486413405eb2405bdb686e4",
  "deploy_mode": "render",
  "rss_mb": 293.6,
  "mcp":   { "connected": true, "tool_count": 9, "protocol": "2025-11-25", "handshake_ms": 599 },
  "index": { "loaded": true, "doc_count": 14, "chunk_count": 204 },
  "llm":   { "agent_configured": true, "judge_configured": true, "separate_key": true },
  "trace_store": { "backend": "turso", "reachable": true, "eval_runs_imported": 3 },
  "degradations": []
}
```

Every value the brief asked for: `/health` 200 and **open** (no bearer sent), `status: ok`,
`mcp.connected: true`, `tool_count: 9`, `index.doc_count: 14`, **`trace_store.backend: turso`**.
`separate_key: true` confirms the judge and the agent failover are on different Google projects.
`rss_mb` 293.6 on the live free instance, against the local image's 291.3 and a 512 MB cap.

```
$ curl -sS -o /dev/null -w 'HTTP %{http_code}\n' "$DEPLOY_URL/"
HTTP 401
   body: {"code":"ACCESS_REQUIRED","detail":"This deployment needs an access key."}

$ curl -sS -H 'Accept: text/html' "$DEPLOY_URL/"      # the key page, not the JSON error
HTTP 401  content-type: text/html; charset=utf-8
   <title>Mosaic HR Copilot — access key</title>   <h1>Mosaic HR Copilot</h1>   name="access"

$ curl -sS -o /dev/null -D - "$DEPLOY_URL/?access=<token>"
HTTP 302
location: /
set-cookie: mosaic_access=<redacted>; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax; Secure
```

401 anonymous with the key page (content-negotiated: JSON to an API client, HTML to a browser),
302 with the token, and the cookie is `HttpOnly` + `Secure` + `SameSite=lax` with a 30-day life.

### 4.3 Both demo tasks, live, against the real Anthropic provider

Not the stub: `LLM_PROVIDER=anthropic`, `claude-haiku-4-5`, the key from `.env` on the service.

**Demo task 1 — international remote-work eligibility.** `outcome: answered`, 26 spans.

Tool sequence: `lookup_employee_profile` → `check_policy_compliance` → `search_policy_documents`
× 5 (tenure, 30-day Tax & Legal threshold, approved countries, device requirements, the rolling
90-day limit). 5 model calls, 7 tool calls, 5 retrievals, **31 985 → 1 834 tokens in 40.2 s**.

Guardrails, in order: G4 on the user message (allow), G4 on 15 retrieval chunks (allow), G1
evidence gate (max dense 0.801, 15 supporting chunks), G2 **10/10 citations resolved**, G3 8 blocks
with every `policy_fact` cited, G6 nothing to redact. Six citations from three documents. The
answer correctly computes 42 consecutive days > 30 → director approval **and** Tax & Legal review,
names the 21-day filing deadline and the 90-day rolling limit, and separates the one
"Recommendation — not company policy" block from the policy facts.

**Demo task 2 — PTO request with a confirmation-gated mock write.** 28 spans, two turns.

Turn 1 ends `awaiting_confirmation`: `create_mock_hr_ticket` returns
`CONFIRMATION_REQUIRED` (span 17, `error`), span 18 records the pending confirmation, and the
script's own assertion that **no `confirmation_token` appears anywhere in the `/chat` body**
passed. The card showed the exact arguments — `employee_id E1042`, `queue hr-timeoff`,
`summary "PTO Request: 3 days, 15–17 September 2026"`.

Turn 2, after `POST /chat/confirm`: span 22 `confirmation · confirmed`, span 23 the tool call
succeeding — `{"status":"created","ticket_id":"MOCK-HR-000001", …}`. Tool sequence
`check_pto_balance` → `check_policy_compliance` → `search_policy_documents` × 2 →
`create_mock_hr_ticket` (refused) → `create_mock_hr_ticket` (confirmed). 7 model calls, 6 tool
calls, 2 retrievals, **39 078 → 1 816 tokens in 35.4 s**. G2 5/5 citations resolved, G3 4 blocks.

Combined demo spend ≈ **$0.09** at Haiku pricing (71 063 input / 3 650 output tokens).

---

## 5. `check_render_hours.py` — a second wrong URL, found the same way

```
$ python scripts/check_render_hours.py
could not read Render usage (GET /v1/resources/metrics/instance-count answered 404: 404 page not
found); skipping the budget check.
```

`/v1/resources/metrics/instance-count` does not exist; the real path has no `resources` segment.
The script's warn-never-fail rule — right for an outage — had turned a wrong URL into a shrug. Two
minimal fixes, two tests:

* `INSTANCE_COUNT_METRIC = "/v1/metrics/instance-count"`, pinned by a test so the next live run
  does not rediscover it. (`instance-count` is also the *only* name that endpoint accepts for a web
  service: `cpu-usage`, `memory-usage` and `http-request-count` each answer
  `400 invalid metric name`.)
* an empty series is now reported as **UNAVAILABLE**, not as `~0.0 of 750`. Render answers `200 []`
  for this free service at every resolution tried (60 s, 300 s, 3600 s) and over every window tried
  (six hours, the month to date) — the instance-count metric carries no samples for a free instance
  type — and printing zero hours used would be a measurement the script never made.

```
$ python scripts/check_render_hours.py
  since 2026-09-01T00:00:00Z
  instance hours UNAVAILABLE of 750 — /v1/metrics/instance-count answered 200 with no samples for
                 this service; the Render dashboard's own usage page is the figure to read
  build minutes  ~3.9 of 500 (496.1 left) — derived from deploy wall-clock, an upper bound

Both figures are approximations of the dashboard's own; the dashboard is authoritative.
exit=0
```

**The free-tier limits, confirmed as the script's own constants:** 750 instance-hours per workspace
per calendar month (`INSTANCE_HOURS_BUDGET`, warning at 600) and 500 build-pipeline minutes
(`BUILD_MINUTES_BUDGET`, warning at 400). Build minutes used so far: **~3.9 of 500**, from three
deploys. Instance-hours cannot be derived from the API for a free service and must be read off the
dashboard.

**Turso**: organisation `seantm` is on the free **Starter** plan; database `mosaic-hr`, one group
`default` in `aws-us-west-2`, the only database in the workspace.

---

## 6. For the publish step — wording for the three P12-owned files

`CHANGELOG.md`, `deployed.md` and `NEEDS-FROM-USER.md` belong to P12 while this phase runs, so the
wording is here rather than in the files.

### 6.1 `CHANGELOG.md`, under the P11 entry

> **Deploys are triggered by the Render API from CI; a Deploy Hook is an equivalent alternative**
> (2026-09-10, post-gate). Render publishes a service's deploy hook URL in the dashboard and
> through no REST endpoint — re-confirmed against the live account, where `deploy-hook`,
> `deployHook`, `hooks`, `deploy-hooks` and `settings` under `/v1/services/{id}` all return 404 and
> `GET /v1/services/{id}` carries no `deployHookUrl` — so `ci.yml`'s `Trigger Render deploy` step
> now curls `$RENDER_DEPLOY_HOOK_URL` when that secret exists and otherwise `POST`s
> `/v1/services/$RENDER_SERVICE_ID/deploys` with `RENDER_API_KEY`. `provision_render.py` sets
> `RENDER_SERVICE_ID` itself, so provisioning needs no browser step at all. R8.4 is unchanged:
> `needs: [test, docker]` still gates the job and Render Auto-Deploy is still off.
>
> **New user gate, discovered post-gate: Render requires a payment method before it will create any
> service, free ones included** (`402 Payment information is required`). Added by Sean on
> 2026-09-10; the workspace stays on the free plan and the service is `plan: free`, asserted from
> the API's own read-back rather than from the request.
>
> **Turso workspaces are created with no group.** `provision_turso.py` believed every workspace had
> a `default` group; `GET /v1/organizations/seantm/groups` returned `{"groups": []}` and the
> database create answered `400 group not found`. It now creates the group in `aws-us-west-2` — the
> region Render's free plan deploys into — and waits for it to stop reporting itself pending.
>
> **P1's carry-forward, answered against a live database: foreign keys ARE enforced on the Hrana
> path.** `PRAGMA foreign_keys` = 1 and a real orphan-child INSERT was rejected by the server.
>
> **`check_render_hours.py` was reading a URL that does not exist**
> (`/v1/resources/metrics/instance-count` → 404; the real path has no `resources` segment), and an
> empty metric series is now reported as UNAVAILABLE rather than as `~0.0 of 750`.

### 6.2 `deployed.md`

`## Access` and the `Deployed:` line take the tokenized URL from
`data/runtime/post_gate_results.json`. Suggested wording for the two paragraphs this phase changes:

> **Deploy trigger.** Render Auto-Deploy is off (`autoDeploy: "no"`, `autoDeployTrigger: "off"`,
> read back from the live service). CI's `deploy` job triggers production through
> `POST /v1/services/{id}/deploys` with `RENDER_API_KEY` and `RENDER_SERVICE_ID`; a Deploy Hook is
> an equivalent alternative and wins when `RENDER_DEPLOY_HOOK_URL` is set. Either way the job
> carries `needs: [test, docker]`, so a red suite cannot reach production.
>
> **Cost.** The service is `plan: free`, one instance, no disk, PR previews off, region `oregon`.
> Free-tier budgets are 750 instance-hours per workspace per calendar month and 500 build-pipeline
> minutes; build minutes used to date **~3.9 of 500**. Render's instance-count metric returns no
> samples for a free instance type, so instance-hours must be read from the dashboard rather than
> derived — `check_render_hours.py` now says so instead of printing zero. The Turso organisation is
> on the free **Starter** plan with `overages: false` and holds one database.

### 6.3 `NEEDS-FROM-USER.md`

Gate 2 and gate 4 are **discharged**. A gate the file never had should be recorded as discharged
too:

> - [x] **2a — A payment method on the Render workspace.** Render refuses to create any service,
>       free ones included, without one (`402 Payment information is required`). No API can add it.
>       Provided **2026-09-10**. The workspace stays on the free plan; nothing is billable.

Gate 3 is discharged. `RENDER_DEPLOY_HOOK_URL` is **no longer required** — the "two irreducibly
manual steps" sentence should become one, with the hook demoted to an optional alternative.

---

## 7. Step 4 — the published run, against the deployed URL

### 7.1 One more live-shape correction before the first item ran

```
$ EVAL_TARGET_BASE_URL="$DEPLOY_URL" make eval
the runner's trace store is 'sqlite' but the target reports 'turso'. Configure the same database
before a deployed run (§13.2).
```

Not a bug — a guard doing its job, and worth writing down because it is the one operator step the
deployed run needs that no document listed. Scoring reads spans back out of the trace store, so the
runner has to be pointed at the **same** database the instance writes to. The two values come out of
the mode-0600 handoff:

```sh
export TURSO_DATABASE_URL="$(jq -r .TURSO_DATABASE_URL data/runtime/provision_turso.json)"
export TURSO_AUTH_TOKEN="$(jq -r .TURSO_AUTH_TOKEN  data/runtime/provision_turso.json)"
```

### 7.2 The deployed baseline · `r_1789055103_baseline`

```
$ EVAL_TARGET_BASE_URL="$DEPLOY_URL" make eval
[baseline] 1/26 pto-001  …  [baseline] 26/26 sens-001
wrote evaluation/results/r_1789055103_baseline.json
wrote evaluation/results/latest.json
wrote evaluation/REPORT.md
{ "run_id": "r_1789055103_baseline", "variant": "baseline", "target": "deployed", "n_items": 26,
  "strict_pass_rate": null, "doc_recall_mean": 0.8553, "workflow_completion": 0.7692,
  "judge_calls": 0, "est_cost_usd": 0.4656, "duration_s": 533.5 }

$ jq -r '.target, .variant' evaluation/results/latest.json
deployed
baseline
```

`latest.json` is written **only** for a deployed baseline run, and this is the first time in the
project's life that file has existed. `strict_pass_rate` is `null` and `judge_status` is `pending`
because §13.2's two-pass shape drives first and judges second — the judge pass is §7.4 below.

Judge-free metrics from the deployed run: DocRecall **0.855** (n = 19), ToolSelection F1 **0.926**
(n = 26), ArgCorrectness **1.000** (n = 18), WorkflowCompletion **0.769** (n = 26), ActionSafety
**1.000** (n = 26), CitResolve **0.923** (n = 26), `blocks_dropped_by_g2` **1**, OverRefusal
**0.111** (n = 18), MissedRefusal **0.000** (n = 4), `tool_discovery_ok` true,
`injection_quarantined` true, `catalog_reopened_rate` 0.038, `nudge_rate` 0.115.
Latency p50 **17.6 s**, p90 **37.6 s**, p95 **47.7 s**, p99 **55.2 s** — the free instance's 0.1 CPU
against P10's local numbers.

### 7.3 `dense_only_k2` · `r_1789055650_dense_only_k2`

```
{ "run_id": "r_1789055650_dense_only_k2", "variant": "dense_only_k2", "target": "deployed",
  "n_items": 26, "strict_pass_rate": 0.7308, "doc_recall_mean": 0.8421,
  "workflow_completion": 0.8077, "judge_calls": 0, "est_cost_usd": 0.4319, "duration_s": 610.0 }
```

### 7.4 `no_structured_tools` · `r_1789056318_no_structured_tools`

```
{ "run_id": "r_1789056318_no_structured_tools", "variant": "no_structured_tools",
  "target": "deployed", "n_items": 26, "strict_pass_rate": 0.6154,
  "doc_recall_mean": 0.7895, "workflow_completion": 0.6154, "judge_calls": 0,
  "est_cost_usd": 0.4698, "duration_s": 557.3 }
```

Three arms, one target. Agent spend across the sweep: **$0.4656 + $0.4319 + $0.4698 = $1.3673**,
inside the approved $1.3–1.6 band.

### 7.5 Deployed baseline against P10's local baseline, judge-free metrics only

| Metric | local `r_1789032950` | deployed `r_1789055103` |
|---|---|---|
| Document recall | 0.842 | **0.855** |
| Tool selection (F1) | 0.926 | 0.926 |
| Citation resolvability | 0.923 | 0.923 |
| Workflow completion | 0.808 | 0.769 |
| Latency p50 | 17.67 s | 17.58 s |
| Latency p95 | 42.43 s | 47.73 s |

The free instance is not meaningfully slower at p50 — the wall clock is dominated by the model, not
by the 0.1 CPU — and p95 drifts out by ~5 s on the long multi-tool items. Doc recall and tool
selection are stable across the move, which is the point of running the published set against the
thing the grader actually opens.

---

## 8. The judge pass, and the third live-shape defect it exposed

### 8.1 The first attempt aborted at item 2 of 26

```
$ export JUDGE_API_KEY="$LLM_FALLBACK_API_KEY"
$ python -m evaluation.runner --judge r_1789055103_baseline
judge provider answered 8/8 probes; starting the judge pass
[judge r_1789055103_baseline] 1/26 pto-001
WARNING judge citation_support for pto-001 failed twice; recording a null verdict
WARNING judge gold_fact_entailment for pto-001 failed twice; recording a null verdict
[judge r_1789055103_baseline] 2/26 remote-001
WARNING judge decompose for remote-001 failed twice; recording a null verdict
WARNING judge gold_fact_entailment for remote-001 failed twice; recording a null verdict
judge pass aborted at item 2/26 (remote-001): 4 verdicts lost, budget 3. … NOTHING was written —
r_1789055103_baseline keeps `judge_status: pending`, and the pass is idempotent, so run it again
when the provider recovers.
```

The 8-probe/2 s gate passed and then the pass fell over immediately, which is the signature of a
*rate* limit rather than an outage.

### 8.2 What the provider was actually saying

```
$ curl -X POST "${JUDGE_BASE_URL}chat/completions" -H "$AUTH_HEADER" -d '{"model":"gemini-3.5-flash-lite",…}'
HTTP 429
{"error":{"code":429,"status":"RESOURCE_EXHAUSTED","message":"You exceeded your current quota …
  Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests,
  limit: 500, model: gemini-3.5-flash-lite  Please retry in 26.320228186s."}}
```

`Please retry in 26 s` reads like a per-minute meter, and that reading was wrong — see §8.5. A
sequential ten-call burst showed the throttling was real and that swapping keys would not help:

```
$ probe JUDGE_API_KEY 10        → ok=4 fail=6
$ probe LLM_FALLBACK_API_KEY 10 → ok=4 fail=6
```

Both Google projects, equally throttled, at roughly one call per second.

### 8.3 The defect

`Judge._ask` caught `ProviderError` and treated every one of them as a malformed reply: it spent
its **one repair retry** re-sending the prompt with a JSON parse-error note appended — advice a
rate limiter has no use for — and then counted a **lost verdict**. Four lost verdicts against
`JUDGE_FAILURE_BUDGET = 3` ended the pass. Nothing was wrong with the answers, the prompts or the
schema; the pass was simply firing calls back to back with no pacing at all.

### 8.4 The fix, in `evaluation/judges.py`

* **`Pacer`** — a floor on the *gap* between calls, `JUDGE_RPM` (default 10) → one call every six
  seconds. Deliberately not a token bucket: a bucket spends the minute's allowance in two seconds
  and is refused for the next fifty-eight, which is exactly the shape that failed.
* **`is_rate_limited()` and `Judge._complete()`** — a 429 re-sends the *identical* prompt after a
  wait (`retry_after` when the provider gives one, otherwise 8 s doubling to a 64 s ceiling), up to
  `JUDGE_RATE_LIMIT_ATTEMPTS = 5`. It does **not** consume the repair attempt and does **not**
  count as a lost verdict. `Judge.rate_limited` counts the absorbed refusals so a slow pass is
  explicable.
* §13.7's floor is untouched: a provider that only ever 429s still ends in a `None` verdict, the
  item still leaves that metric's denominator, and `n_scored` is still reported beside it.

Eleven new tests in `tests/unit/test_judge_rate_limiting.py`, including the two that keep the paths
apart: a 429 costs no repair and re-sends an unchanged two-message prompt; a genuine parse failure
still buys exactly one repair and the prompt grows to three messages.

### 8.5 The re-run, and what the quota actually is · **`judge_status: pending`**

With the pacer in place the pass never got past its own probe gate, and the refusal finally carried
the machine-readable detail the earlier ones had not:

```
$ python -m evaluation.runner --judge r_1789055103_baseline
judge provider probe 1/8 failed against gemini-3.5-flash-lite: 429 RESOURCE_EXHAUSTED …
  'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests',
                  'quotaId':     'GenerateRequestsPerDayPerProjectPerModel-FreeTier',
                  'quotaDimensions': {'location': 'global', 'model': 'gemini-3.5-flash-lite'},
                  'quotaValue': '500'}]
The judge pass was NOT started; the run file keeps `judge_status: pending`.
```

**`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, value 500 — this is the daily cap, per
project, per model, and both Google projects have spent theirs today.** The `Please retry in 7s`
hint is Google's generic backoff advice and says nothing about which meter tripped; the `quotaId`
does. My §8.2 reading of it as a per-minute meter was wrong, and the ten-call burst's `ok=4 fail=6`
was the daily counter dripping, not a per-minute window.

So this is exactly the case the brief anticipated, and its instruction is followed literally:
**`r_1789055103_baseline` keeps `judge_status: pending`** and the controller re-judges after the
daily reset (midnight Pacific for the free tier). The command is unchanged and idempotent:

```sh
export JUDGE_API_KEY="$LLM_FALLBACK_API_KEY"   # or the first project; both reset together
export TURSO_DATABASE_URL="$(jq -r .TURSO_DATABASE_URL data/runtime/provision_turso.json)"
export TURSO_AUTH_TOKEN="$(jq -r .TURSO_AUTH_TOKEN  data/runtime/provision_turso.json)"
python -m evaluation.runner --judge r_1789055103_baseline
python -m evaluation.runner --recompute-agreement r_1789055103_baseline --metric judge_agreement_rate
python -m evaluation.runner --recompute-agreement r_1789055103_baseline --metric judge_agreement_rate_hard
python -m evaluation.ablation
```

**The pacing fix is still the right change and is kept**, because it fixes a real defect that a
quota reset would not: without it a *transient* 429 spends the repair retry on advice a rate limiter
cannot use and is counted as a lost verdict, so three unlucky throttles anywhere in 232 calls abort
a pass that has nothing wrong with it. It does not — and does not claim to — conjure quota out of an
exhausted daily allowance.

**Consequences for the published run**, stated plainly rather than papered over:

* `judge_status: pending`; `strict_pass_rate`, `groundedness_mean`, `citation_accuracy_mean`,
  `partial_match_mean` and `clarification_accuracy` are `null` on the deployed baseline.
* Every **judge-free** metric is present and is a real measurement of the deployed instance:
  DocRecall, ToolSelection, ArgCorrectness, WorkflowCompletion, ActionSafety, CitResolve, the
  behaviour matrix, over/missed refusal, latency percentiles.
* `--recompute-agreement` folds reference labels into a *judged* run, so both agreement figures wait
  on the same reset. They are **not** run here: recomputing agreement against null verdicts would
  write a figure with no judge in it.
* `make ablation` is unaffected — §13.9 judges `baseline` only, and the three arms' comparison rests
  on the judge-free metrics precisely so an arm comparison never depends on a free-tier quota.

**Option not taken, and why.** Judging on a different Gemini model would have its own separate
daily allowance (the quota is per project *per model*), but §13.7 names `gemini-3.5-flash-lite` as
the judge and every committed judged artifact was produced by it. Swapping the judge to make a
deadline would silently break comparability with P10's numbers and with the reference labels. That
is a design decision for the controller, not a fix, so it is recorded here and not made.

---

## 9. `make ablation`, and a fourth defect: REPORT.md described the wrong run

### 9.1 The comparison · **GREEN**

```
$ EVAL_TARGET_BASE_URL="$DEPLOY_URL" make ablation
wrote evaluation/results/comparison.json
updated evaluation/REPORT.md
the no_structured_tools variant did not move workflow completion past the 0.25 threshold;
REPORT.md carries the not-supported banner
{ "supported": false, "reason": null, "baseline": 0.7692, "no_structured_tools": 0.6154,
  "delta": -0.1538, "threshold": 0.25 }
```

| Variant | DocRecall | ToolSelection | WorkflowCompletion | CitResolve |
|---|---|---|---|---|
| `baseline` | **0.855** | **0.926** | 0.769 | **0.923** |
| `dense_only_k2` | 0.842 | 0.926 | **0.808** | 0.923 |
| `no_structured_tools` | 0.789 | 0.840 | 0.615 | 0.885 |

Removing the five structured-data tools costs 0.066 of document recall, 0.086 of tool-selection F1
and 0.154 of workflow completion — a real, consistent degradation, but **below the pre-registered
0.25 threshold**, so `workflow_completion_check.supported` is `false` and REPORT.md carries the
not-supported banner rather than a claim the data does not make. That is the hypothesis being
falsified as designed, and it is reported as such.

`dense_only_k2` costs 0.013 of document recall and nothing at all on tool selection or citation
resolvability — the same finding as P10's local sweep, reproduced against the deployed instance.

### 9.2 The DoD commands

```
$ jq -r '.target, .variant' evaluation/results/latest.json
deployed
baseline

$ jq -r '.target, (.variants[].variant)' evaluation/results/comparison.json
deployed
baseline
dense_only_k2
no_structured_tools
```

Both print exactly what §13.9 and `NEEDS-FROM-USER.md` say they must.

### 9.3 The defect the sweep exposed in `REPORT.md`

After `make ablation`, `evaluation/REPORT.md` read:

```
Generated by `evaluation/runner.py` from `evaluation/results/r_1789056318_no_structured_tools.json`.
| Run     | `r_1789056318_no_structured_tools` |
| Variant | `no_structured_tools` |
```

§13.10 makes REPORT.md the human-readable face of the **published** run, but `write_artifacts`
calls `write_report` for *every* run, so a sweep that finishes on an ablation arm leaves the report
describing that arm. P10 never saw this because its judge pass ran last and rewrote the report from
the baseline. Here the judge pass could not run at all (§8.5), and the only two paths back —
`--judge` and `--recompute-agreement` — **both require a judge**. A run left `judge_status: pending`
by an exhausted quota therefore had no way whatsoever to publish its own report.

**`python -m evaluation.runner --report <RUN_ID>`** is the fix: it reads a committed run file and
rewrites REPORT.md from it. It drives nothing, judges nothing and spends nothing — one test
monkeypatches `Runner` to explode and asserts the path never constructs one. Five tests in
`tests/unit/test_two_pass_judging.py`, including the one that matters most here: a
`judge_status: pending` run can publish its report.

```
$ python -m evaluation.runner --report r_1789055103_baseline && python -m evaluation.ablation
{ "run_id": "r_1789055103_baseline", "variant": "baseline", "target": "deployed",
  "judge_status": "pending" }

$ head -9 evaluation/REPORT.md | tail -4
| Run     | `r_1789055103_baseline` |
| Variant | `baseline` |
| Target  | `deployed` — `https://mosaic-hr-copilot.onrender.com` |
```

`write_report`'s `path=` keyword was already there and `rewrite_report` now takes it too, so the
tests write into `tmp_path` instead of the repository's own REPORT.md — which the first draft of
those tests did clobber, and which is why the keyword is threaded rather than assumed.

### 9.4 Index-only regenerations: deliberately skipped

`scripts/chunk_size_sweep.py` and `scripts/gen_ablation_evidence.py` were **not** re-run. Both are
index-only and nothing about the index moved: the deployed instance reports
`corpus_sha256 88fe9266fa41d9f5…` and `manifest_sha256 920caf37d9d15971…`, byte-identical to the
committed manifest, and `docs/evidence/mcp-discovery-4-tools.json` describes an MCP catalog that no
change in this phase touches. Re-running them would rewrite committed artifacts with identical
content and a new timestamp, which is churn, not evidence.

---

## 10. Step 5 — cold start, and a fifth defect found by running it

### 10.1 The first probe produced no number at all

```
=========== COLD PROBE 1 of 3 — 16:45:32Z ===========
  idling 1000s so Render spins the instance down (§14.4)…
FAIL — https://mosaic-hr-copilot.onrender.com could not be measured: GET /ready never answered 200
within 180s: the model or the index never became resident, so there is no cold-start figure to
publish
```

`ready_timeout_s = 180.0` was chosen against the local image, where `/ready` greens in **2.6 s**.
The free instance is a different machine: 0.1 of a CPU, and `/health` — which is Render's own
health-check path, deliberately 200 while degraded so the service never restart-loops — answers
long before the ONNX session and the sqlite-vec index are resident. So Render marks the container
live, `measure_cold_start.py` starts its stopwatch, and the model load runs past a ceiling that was
never sized for that hardware.

The refusal to publish a timeout as if it were a measurement is correct and was kept — a P11 fix
put it there deliberately. What was wrong was the ceiling. **A limit that stops the measurement
before the thing being measured has finished is a missing number, not a safeguard.**

`DEFAULT_READY_TIMEOUT_S` is now 900 s (`COLD_READY_TIMEOUT_S` to override) and `--ready-timeout`
exposes it on the CLI, where it previously existed only as a keyword argument no caller could
reach. Two tests added to `tests/unit/test_measure_cold_start.py`.

**That change was harmless and is kept, but it was not the cause and could not have been the fix.**
The second probe failed at 900 s exactly as the first failed at 180 s. Raising a ceiling cannot
help when the thing being waited for never happens — §10.2 is what was actually wrong.

### 10.2 `/ready` is latched at 503 by a 5-second timeout · **BLOCKED, owned by P11c**

The second probe's refusal named the reason, and it is not a slow model load:

```
$ curl -sS https://mosaic-hr-copilot.onrender.com/ready
HTTP 503
{"ready":false,"reason":"warm-up call failed: search_policy_documents could not be called:
 SSE stream ended without a response"}
```

One second later, on the same instance, the same tool over the same loopback client:

```
$ curl -sS -X POST "$DEPLOY_URL/chat" -H "$AUTH" \
    -d '{"message":"How many days of paid time off do I accrue each year?","client_label":"api"}'
HTTP 200
{ "outcome": "answered", "n_citations": 4,
  "tools": [ {"name":"search_policy_documents","summary":"search_policy_documents · ok"},
             {"name":"get_policy_section","summary":"get_policy_section · ok"} ],
  "ms": 26263 }
```

`/health` alongside it: `status ok`, `degradations []`, index loaded, 14 docs / 204 chunks,
`mcp.connected true`, `tool_count 9`. **The 503 is a fossil.**

**Root cause** (confirmed by the controller against the Render logs, and correcting my first
reading of it):

* **Primary — `src/hrmosaic/agent/client.py::_http_client`** builds
  `httpx2.AsyncClient(headers=…)` and so inherits httpx2's **default `Timeout(5.0)`**, rather than
  the SDK's `create_mcp_http_client` timeouts (30 s connect/write/pool, **300 s read**). Any
  loopback tool call that goes five seconds without a byte dies. The first embed on a 0.1-CPU free
  instance is simply the first call slow enough to hit it — the log shows a
  `GET stream disconnected` line **5 s after** each of the 17:02:45Z and 17:29:05Z boots.
* **Amplifier — `src/hrmosaic/web/main.py::_warm_up`** retries the MCP *handshake* in a loop until
  `ready_warmup_timeout_s`, but gives the warm-up **`call_tool` exactly one attempt**. So that one
  timeout latches `app.state.ready = False` for the life of the process, and nothing ever re-tries.
* **Why no local gate caught it:** the model loads in 2.6 s locally, comfortably inside the 5 s
  default, so the loopback call never times out on a developer's machine. `make docker-run-512`
  polls `/ready` and has always gone green.

**The spin-down itself was observed and is healthy.** Render's last health-check line is
**17:20:59Z** — about fifteen minutes after the last inbound request — then silence, then
`Started server process` at **17:29:05Z**, and the probe's `GET /health` answered 200 at 17:29:11Z,
**≈ 49 s** after the idle ended. That is the §14.4 spin-up expectation (~30–60 s) met on the first
real measurement. What could not be measured is everything downstream of `/ready`.

**Why this was invisible until now:** nothing in the deploy path checks `/ready`.
`wait_for_deploy.py` asserts `/health.app.git_sha` and `smoke_deployed.py` asserts `/health`
fields. The published eval sweep (78 items), both demo tasks and every dashboard page ran green
against an instance reporting `ready: false` from its very first boot.

**Disposition.** P11c owns both fixes — the httpx2 timeout and the warm-up retry — plus a `/ready`
assertion in `smoke_deployed.py` so this can never again pass a smoke. Cold start is re-measured
after that ships. Per the controller's ruling I stopped the probe loop rather than spend another
forty minutes collecting the same non-answer, and touched neither `client.py` nor `main.py`.

**The one cold-start-adjacent figure that is real and unblocked:** a **warm** `POST /chat` on the
free instance is **26.3 s** for the retrieval-only question with two tool calls, against the
**1.5–5 s** §14.4's table expects. That gap is Render's 0.1 CPU and is worth publishing on its own.

A half-built `--allow-not-ready` flag — which would have recorded the `/ready` segment as
*unmeasured* and published the other three — was written and then **reverted** when the ruling came
back as "fix it properly in P11c". Only the `--ready-timeout` change remains in
`measure_cold_start.py`.
