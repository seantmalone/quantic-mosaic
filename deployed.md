# Deployment notes — Mosaic HR Copilot

> **Status: live.** The service was provisioned on 2026-09-10 and every figure below was observed
> on it or on the image it runs. Nothing here is inferred or filled in from the spec's
> expectations — a number in this file was measured, and it names what measured it.

## What is live, and what produced it

Gates **2** (Render account + the Render GitHub App), **3** (Turso platform token) and **4**
(Render API key) all landed on 2026-09-10, plus a gate the file never had — **2a**, a payment
method on the Render workspace, which Render demands before it will create any service, free ones
included. Each row below names the command whose output it is; the full sequence is
`NEEDS-FROM-USER.md` §*The exact steps*.

| Value | Produced by | Observed |
|---|---|---|
| The live service `mosaic-hr-copilot` (`srv-dahcsj95efls73dibqeg`), its URL and the tokenized `?access=` link | `python scripts/provision_render.py` | 2026-09-10 |
| Every `sync: false` env var on Render, and the `gh secret set` calls (`DEPLOY_URL`, `RENDER_API_KEY`, `RENDER_SERVICE_ID`) | `python scripts/provision_render.py` | 2026-09-10 |
| The Turso database `mosaic-hr`, its token and the first live FK/parity answer | `python scripts/provision_turso.py` | 2026-09-10 |
| Measured cold start and warm turn on the live instance | `python scripts/measure_cold_start.py --url "$DEPLOY_URL"` | 2026-09-10 and 2026-09-11 (n=3) |
| Free-tier hours and build minutes read from the account | `python scripts/check_render_hours.py` | 2026-09-11 |
| The published `target: deployed` run, `latest.json`, `comparison.json` | `EVAL_TARGET_BASE_URL="$DEPLOY_URL" make eval`, then the two variants and `make ablation` | 2026-09-11 |
| `design-and-evaluation.md`'s results table, refreshed from the published run | `python scripts/paste_eval_numbers.py` | 2026-09-11 |

`RENDER_DEPLOY_HOOK_URL` is **optional**: no REST endpoint publishes it, so CI's `deploy` job
triggers production through `POST /v1/services/{id}/deploys` with `RENDER_API_KEY` and
`RENDER_SERVICE_ID` instead, and uses the hook only when that secret happens to exist. Either way
the job carries `needs: [test, docker]`, so a red suite cannot reach production.

## Deployed URLs

| Surface | Value |
|---|---|
| Web service | `https://mosaic-hr-copilot.onrender.com` |
| Health | `https://mosaic-hr-copilot.onrender.com/health` — open, always 200 while the process is up |
| Readiness | `https://mosaic-hr-copilot.onrender.com/ready` — open, 503 until the model and index are resident |
| Tokenized link | `https://mosaic-hr-copilot.onrender.com/?access=<token>` — the token is written out **once** in the repository, on `README.md`'s `Deployed:` line, which is the grader's entry point |

The service is described by the committed **`render.yaml`**: one Render Hobby (free) web service,
`runtime: docker`, `plan: free`, `healthCheckPath: /health`, **`autoDeploy: false`**. It was created
by `python scripts/provision_render.py`, which reads that same file so the Blueprint and the
API-created service cannot drift. Read back from the live service on 2026-09-10: `plan: free`, one
instance, region `oregon`, no disk, PR previews off, `autoDeploy: "no"`, `autoDeployTrigger: "off"`.

**Which commit served which evaluation run.** A run file carries two shas: `git_sha` is the
**harness tree's** `git rev-parse HEAD` — the code that scored the run — and `target_git_sha` is
what the target's own `/health` reported under `app.git_sha`, the build that answered the
questions. `evaluation/REPORT.md` prints both. The published run records both as
`34717b52eb01312097ec41fe8a07394843d215d6`: the harness ran from the same commit the service was
serving.

**Runs recorded before 2026-09-11 carry neither.** Until P23 the harness took `git_sha` from
`settings.git_sha`, which resolves `GIT_SHA` → `RENDER_GIT_COMMIT` → `"dev"`, and on the
development machine that is `"dev"`; there was no `target_git_sha` at all. The committed run files
are **not** rewritten — a result file is a record of what happened, not a document — so for those
three runs the serving commit lives here, in prose, taken from the deploy ledger:

| Run | Column | Deployed commit that served it | Recorded in the run file |
|---|---|---|---|
| `r_1789055103_baseline` | before optimization | `5419ec5` | no — prose only |
| `r_1789069158_baseline` | after the quality fixes (P13) | `b24ad32` | no — prose only |
| `r_1789086979_baseline` | after the performance waves | `da0dca2` | no — prose only |
| **`r_1789166880_baseline`** | **published — after the model-behaviour wave** | **`34717b5`** | **yes — `target_git_sha` and `git_sha`** |

`scripts/smoke_deployed.py` asserts the live `/health` reports a `git_sha` that is not `"dev"`
before any of those runs is allowed to count, which is what keeps the two shas from being confused.

**Rejected hosts**, and why (§14.1): Railway, Fly.io and Koyeb (no lasting free compute), Hugging
Face Spaces (same), Google Cloud Run (the documented fallback — the *same image* runs there, but it
needs a card), Vercel and Cloudflare Workers (a 10 s function cap, against a ~90 s agent budget).

### How a commit reaches the service

Two independent mechanisms, and both must hold. In the repository, the `deploy` job declares
`needs: [test, docker]` and runs only on a push to `main` (or an explicit dispatch). On the
platform, Render Auto-Deploy is **off** (`autoDeploy: "no"`, `autoDeployTrigger: "off"`, read back
from the live service), so Render never builds from a push on its own — the only path from a commit
to the running service is the deploy that job triggers. It triggers it through
`POST /v1/services/{id}/deploys` with `RENDER_API_KEY` and `RENDER_SERVICE_ID`; a Deploy Hook is an
equivalent alternative and wins when `RENDER_DEPLOY_HOOK_URL` is set. Proven live on 2026-09-10:
deploy `dep-dahcukqfngtc7390n740`, `trigger: api`. There is no branch protection: every phase of
this build pushed directly to `main`, so a rule exempting the owner would have been decorative.

The evidence is a **recorded red run**, not an assertion: a temporary branch carrying one
deliberately failing test, dispatched with `deploy_only: true`, whose job graph shows `test` red
and `deploy` **skipped with the reason "dependent job failed"**. It is committed as
[`docs/evidence/ci-deploy-skipped.png`](docs/evidence/ci-deploy-skipped.png), and the run is open
at
[`actions/runs/34485304411`](https://github.com/seantmalone/quantic-mosaic/actions/runs/34485304411),
so the job graph in the screenshot can be checked against the run that produced it.

## Access

One shared secret, `APP_ACCESS_TOKEN`, generated by `scripts/provision_render.py` with
`secrets.token_urlsafe(32)` and set on the service as a `sync: false` env var. **No user step.**

| Path in | How |
|---|---|
| Browser | `https://<app>.onrender.com/?access=<token>` — exchanged once for the HttpOnly, SameSite=Lax cookie `mosaic_access`, marked `Secure` on the https deployment, then redirected to a URL with the parameter stripped |
| API clients, MCP Inspector | `Authorization: Bearer <token>` on every request |
| Open routes (no token) | `/health`, `/ready`, `/static/*`, `/access` |

**Two personas**, selected by the `mosaic_actor` cookie or the `X-Actor` header: an employee
(`E1xxx`, default `E1042`) and `admin`. The dashboard, every `/api/*` route, the three write
controls, the bounded smoke eval and the privileged `/chat` options require `admin` and answer
`403 {"code": "ADMIN_REQUIRED"}` otherwise. A request with no access credential at all gets the
access-key page with **HTTP 401** — a different check from the 403, and `scripts/smoke_deployed.py`
asserts both.

The **observability dashboard is admin-only**, every page and every `/api/*` read, enforced
server-side on top of the access gate. All of its data is synthetic, so a grader browses freely:
follow the tokenized link, then choose **HR admin** in the act-as selector.

An MCP Inspector session attaches to `/mcp-server/mcp` with the same bearer header — Inspector
supports custom headers — **and with the service's own hostname on `MCP_ALLOWED_HOSTS`**. The MCP
SDK enables DNS-rebinding protection for a loopback-bound server, which the mounted topology is, so
the endpoint answers `421 Invalid Host header` to any `Host` the allowlist does not name; the
committed `render.yaml` carries
`MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*,mosaic-hr-copilot.onrender.com` and **the live service
carries it too**. **The public mount accepts external MCP clients**, verified on 2026-09-11 at
20:32Z, when an external `initialize` over the public hostname answered HTTP 200 — and that
session went the whole way from there: `notifications/initialized` **202**, `tools/list` returning
all **nine** tools, real `search_policy_documents` and `check_pto_balance` calls, then
`create_mock_hr_ticket` refused **`CONFIRMATION_REQUIRED`** with no confirmation token and refused
again with a forged one, while the same endpoint answered **401** to a request carrying no bearer.
So the bearer gate and the confirmation gate are verified against the deployed service, not only in
the test suite. The other
two ways to see the same nine tools are unchanged: `/dashboard/mcp` and the stdio entrypoint
(`mcp/run_stdio.sh`).

- Tokenized link: `https://mosaic-hr-copilot.onrender.com/?access=<token>`, written out in full on
  `README.md`'s `Deployed:` line and **nowhere else in the repository**. It is the grader's entry
  point by design: one click exchanges the parameter for the `mosaic_access` cookie and redirects
  to a URL with the parameter stripped.
- **`Secure` behind Render's edge, and a limit that is genuinely per visitor.** Render terminates
  TLS at its edge and forwards plain http into the container, so uvicorn has to be told to read the
  forwarded headers: the image's CMD carries `--proxy-headers --forwarded-allow-ips='*'`, which is
  safe precisely because the container port is reachable through that edge and through nothing
  else. With it the scheme is `https` again, so the `mosaic_access` cookie ships `Secure` as
  constraint 9 requires, and `ACCESS_RATE_LIMIT_PER_MIN` (30) is one bucket per client on Render as
  it already was locally and under Docker; before P20 it behaved as one shared 30/min bucket across
  every visitor, because the address uvicorn saw was the edge's. The limit does **not** rely on the
  flag to decide whose bucket it is: `'*'` is a broad grant, and under it uvicorn reports the
  **first** `X-Forwarded-For` entry as the client — which is whatever the caller sent, since each
  proxy appends. So `web/api.py`'s `rate_limit_key()` keys on the **last** entry, the one the edge
  itself appended, and no forged prefix can move a caller to a fresh budget. `request_is_https()`
  likewise reads `X-Forwarded-Proto` itself for the cookie flag, and for nothing else — every other
  way this app runs (`make run`, the test servers) passes no proxy flags, and forging that header
  only makes the forger's own cookie `Secure`. Nothing authorises on either value: the gate is
  `secrets.compare_digest` against `APP_ACCESS_TOKEN`, the write path is the confirmation gate, and
  every record behind both is synthetic.
- **Post-grading rotation:** `gh secret set` is not involved — the token is a Render env var. Rotate
  it with `RENDER_API_KEY=… python scripts/provision_render.py` after deleting `APP_ACCESS_TOKEN`
  from the service (the script generates a new one only when the service carries none, precisely so
  that a routine re-run cannot invalidate a link a grader is holding).

## Cold start

Measured by `scripts/measure_cold_start.py`, which idles `EVAL_COLD_IDLE_S` (1000 s ≈ 16.7 min,
past Render's 15-minute spin-down) and then times four segments in order: `GET /health`, `/ready`
polled to 200, the first `POST /chat`, and a second warm `POST /chat`. The published number is
distinct from §13.5's cold-*turn* p50, which is an eval metric over a warm instance.

### Measured without keep-alive

**On the live free instance — n=3, measured 2026-09-10 and 2026-09-11 without keep-alive.** The
service carried no keep-alive pinger when these ran, so this is the behaviour of the instance with
nothing touching it — and the behaviour a visitor gets whenever **both** keep-alive layers below
are off. That is not the live service's state today: the in-process layer has been armed on it
since 2026-09-11 14:26Z, and this table is what comes back the moment the variable is cleared
again. Probe 1 ran on `bf85ffd` (the readiness fix) at 18:55Z; probes 2 and 3
ran on `da0dca2`, the build that served the published evaluation run, at 02:19Z and 02:37Z:

| Segment | Probe 1 | Probe 2 | Probe 3 | Median |
|---|---|---|---|---|
| Spin-up → `GET /health` 200 | 44.8 s | 43.5 s | 52.4 s | **44.8 s** |
| `/health` 200 → `/ready` 200 | 2.8 s | 0.1 s | 0.1 s | **0.1 s** |
| First `POST /chat` (cold turn) | 23.3 s | 23.9 s | 25.2 s | **23.9 s** |
| **First request, total** | 71.0 s | 67.5 s | 77.6 s | **71.0 s** |
| Warm `POST /chat` immediately after | 22.5 s | 22.5 s | 23.9 s | **22.5 s** |

Every probe idled 1,000 s first, so three samples cost ~an hour of a deliberately idle instance —
which is why they ran after the evaluation sweeps rather than beside them. Medians are taken per
segment and each total is measured wall clock, so the segment medians do not add up to 71.0 s. The
spread is the honest headline: **67.5–77.6 s** cold to first answer, **22.5–23.9 s** warm, and the
figure is quoted with its `n` everywhere it appears. The 2.8 s to `/ready` on probe 1 is the only
row that moved materially: the final build answers `/ready` in 0.1 s once the instance is up, which
is what baking the model into the image buys.

Two things the first probe settled beyond the numbers. The spin-down is real and observable in Render's
own logs — its last health-check line at 17:20:59Z, ~15 minutes after the last inbound request,
then silence until `Started server process` at 17:29:05Z. And the first attempt at this measurement
found a **defect**, not a platform limit: `/ready` had been permanently 503 on every deploy since
the first one, because the loopback MCP client was built with httpx2's default 5 s timeout instead
of the SDK's 30 s connect / 300 s read, so the first embed on a 0.1-CPU instance outran it and the
one-shot warm-up latched readiness false for the life of the process. Everything else — `/health`,
`/chat`, the whole eval sweep — worked throughout, which is exactly why nothing had caught it. P11c
(commit `395036d`) fixed the timeouts, gave the warm-up a bounded retry and made
`scripts/smoke_deployed.py` fail a deploy whose `/ready` never greens; probe 1 above is the first
probe after that shipped, and probes 2 and 3 show the fix holding on the final build. The full
account, the three probes side by side and the keep-alive ruling are in
[`docs/optimization-log.md`](docs/optimization-log.md); the raw segments, with each probe's
timestamp and sha, are in
[`docs/evidence/cold-start-probes.json`](docs/evidence/cold-start-probes.json).

### Keep-alive

Two layers, and the order matters. Both exist to keep the instance from reaching Render's
15-minute idle timer, so a visitor gets the warm turn instead of the 71.0 s above. The primary
layer runs on one environment variable, which **the live service has carried since 2026-09-11
14:26Z** — the **Status** paragraph below carries the evidence that it is working. Both landed on
2026-09-11, **after** the table: Sean's ruling of 2026-09-10 20:40Z was to publish the measurement
first and mitigate it second, so every figure above is still the honest no-ping behaviour and
nothing was re-measured to look better.

**The primary layer is in the application.** `web/main.py` starts a background task in its lifespan
that GETs `{KEEP_ALIVE_URL}/health` every `KEEP_ALIVE_INTERVAL_S` (default 600 s) with a 30 s
timeout, logs the outcome at DEBUG, never raises and is cancelled at shutdown. The URL must be the
service's **public** origin, not loopback: Render counts traffic at its edge, so the ping has to
leave the container and come back to reset the idle timer. Unset `KEEP_ALIVE_URL` — the default,
and the case on a laptop and in CI — and the task is never created and nothing is pinged from
inside the process.

**Why the workflow below could not be the primary layer: it did not run.** GitHub's `schedule:` is
best-effort and de-prioritises low-traffic repositories. In the nine hours after
`.github/workflows/keepalive.yml` was pushed, its `*/10 * * * *` schedule produced **two** runs —
09:48Z and 13:53Z on 2026-09-11, both green — instead of the ~54 it asks for, and the live instance
was found spun down at 14:25Z. So the cron is kept as the **second** layer, where its one real
advantage lives: an in-process loop cannot run inside an instance that is already asleep, and an
external ping can wake one.

**The arithmetic below is unchanged by the addition.** Both layers target the same state — an
instance that is awake round the clock — so the ceiling is still 744 of 750 instance-hours in a
31-day month, and pinging twice as often costs nothing extra because it is wakefulness, not
requests, that is billed. It is the ceiling for the enabled case, and since 2026-09-11 14:26Z that
is the case this service is in.

**Status, 2026-09-11 14:26Z: the in-process layer is armed on the live service.**
`KEEP_ALIVE_URL=https://mosaic-hr-copilot.onrender.com` and `KEEP_ALIVE_INTERVAL_S=600` were set on
the service with a single-key PUT — no rebuild, no blueprint apply — and the loop has been running
since the boot that followed. The evidence is `/health`'s own `app.uptime_ms`: **60 minutes at
18:37Z**, then **69 minutes at 23:56Z → 86 minutes at 00:13Z**, a seventeen-minute window whose only
other traffic was those two health reads and which is past Render's 15-minute spin-down, and
**124.5 minutes at 00:51Z** on 2026-09-12. An instance with nothing pinging it cannot show an uptime
that crosses its own idle timer. `render.yaml` carries the same two values (P23), so re-applying the
blueprint arms the loop rather than clearing the operator's value; the `Dockerfile` deliberately
carries neither, because a baked origin would start the loop in every container a developer runs.
The table above therefore documents what a visitor gets if the loop is ever turned off — see *How
to turn it off* below — rather than what one gets today.

The cron job is one `curl` on `ubuntu-latest`: no checkout, no secret, and `permissions: {}`, because
`/health` is an open route. It reads the URL from the repository **variable** `DEPLOY_URL` and falls
back to the committed live origin, prints `status`, `app.cold_start` and `app.uptime_ms`, and
**never fails the repository's status** — a spun-down, deploying or suspended instance produces a
`::warning::`, an exit 0 and one line in the run's job summary, so the Actions tab shows the outage
without painting `main` red. `tests/contract/test_keepalive_workflow.py` pins all of that.

**What it costs — the 750-hour arithmetic.** The workspace gets 750 free instance-hours per calendar
month and an instance is counted only while it is awake, which is exactly what pinging round the
clock makes it: 24 × 31 = **744 hours** in a 31-day month, 24 × 30 = 720 in a 30-day one, against a
750-hour budget. The keep-alive therefore spends nearly the whole allowance, and the ~6 hours of
slack in a 31-day month is all that is left for anything else free in the workspace. Nothing is ever
billed for it: exhausting the 750 hours **suspends** every free service until the month resets, and
a suspended service answers nothing — which is what the warning line exists to make visible.
`scripts/check_render_hours.py` reports the month to date and warns above 600 of 750 (and above 400
of 500 build minutes) without ever failing a build, so the consumption is legible before it runs out.

**How to turn it off — both layers, and neither needs a commit.** Clear `KEEP_ALIVE_URL` in the
Render dashboard (Environment → the variable → *Delete* → *Save, rebuild, and deploy*) and the
in-process task is not created on the next boot; then GitHub → **Actions** → *keepalive* → ⋯ →
**Disable workflow** stops the schedule. With both off the service goes back to the spin-down
behaviour the table above measures, and the same two menus put it back. Deleting the workflow file
or dropping its `schedule:` trigger works too, but disabling is the reversible one, and that is the
whole point — the measurement is published, the mitigation is a switch.

### The part the image controls

Measured locally on 2026-09-10 — the floor the live figures above sit on, and the reason the gap
between them is Render's, not the image's. Both rows
are read off the **same** `make docker-run-512` run whose output is pasted verbatim under *Memory*
below — the first segment is that run's `is up after`, the second is the gap to its `/ready is green
after` — so the published figures and the evidence for them cannot drift apart:

| Segment | Observed | How |
|---|---|---|
| Container start → `/health` 200 | **2.2 s** | `docker run -m 512m`, then `scripts/wait_for_health.py` |
| `/health` 200 → `/ready` 200 (ONNX session + index open) | **0.5 s** | `wait_for_health.py --ready`, same run |

A second run on the same image read 2.1 s and the same 0.5 s.

Those 0.5 s are what baking the model into the image buys: without it the same segment is a 16–63 s
download from Hugging Face on 0.1 CPU, on every spin-up. Render's own spin-up is added on top, and
that is the whole of the difference: 2.2 s on the laptop against a median **44.8 s** (43.5–52.4 s
over three probes) on the free instance.

## Environment variables

Every variable of §12.3 is in `.env.example` with its default and a `REQUIRED`/`OPTIONAL` marker;
`tests/contract/test_env_example_covers_settings.py` asserts that bijection in both directions. What
the **deployed service** sets is the `render.yaml` list — read back from the live service on
2026-09-10 as exactly those ten keys — plus the two limiter variables added by a single-key PUT the
same day. Two further single-key PUTs followed on 2026-09-11: `MCP_ALLOWED_HOSTS` (§ *MCP
transport*) and the keep-alive pair described under the table. Every other variable runs at its
coded default:

| Variable | Deployed value | Set by |
|---|---|---|
| `APP_ENV` | `render` | `render.yaml` |
| `LLM_PROVIDER` | `anthropic` | `render.yaml` |
| `LLM_MODEL` | `claude-haiku-4-5` | `render.yaml` |
| `OMP_NUM_THREADS` | `1` | `render.yaml` |
| `ANTHROPIC_API_KEY` | set, `sync: false` (value never leaves the service) | `provision_render.py` from `.env` |
| `JUDGE_API_KEY` | set, `sync: false` | `provision_render.py` from `.env` |
| `LLM_FALLBACK_API_KEY` | set, `sync: false` | `provision_render.py` from `.env` |
| `TURSO_DATABASE_URL` | `libsql://mosaic-hr-seantm.aws-us-west-2.turso.io` | `provision_turso.py` → `provision_render.py` |
| `TURSO_AUTH_TOKEN` | set, `sync: false` | `provision_turso.py` → `provision_render.py` |
| `APP_ACCESS_TOKEN` | set, `sync: false` — generated, never supplied | `provision_render.py` |
| `LLM_RPM` / `LLM_BURST` | **`60` / `30`** (2026-09-10, single-key PUT on the live service) | operator, see below |
| `PORT` | injected by Render | the platform |
| `GIT_SHA` | resolved from `RENDER_GIT_COMMIT` | the platform + a `settings.py` validator |

**`KEEP_ALIVE_URL` is the one variable that switches a behaviour on rather than tuning one.** The
in-process keep-alive of § *Cold start* → *Keep-alive* is started only when it holds the service's
own **public** origin; unset — the default, and the state on a laptop and in CI — no task is
created and nothing is pinged. It **is set on the live service**, to
`https://mosaic-hr-copilot.onrender.com`, by a single-key PUT on **2026-09-11 at 14:26Z** with no
rebuild, exactly like the two limiter variables above; `KEEP_ALIVE_INTERVAL_S=600` was set in the
same PUT, which is also its coded default. `render.yaml` carries both, so a blueprint apply cannot
undo them.

**Why the service runs `LLM_RPM=60` / `LLM_BURST=30` while the code default stays 10.** The
pre-optimization deployed sweep recorded a **3.9 s per turn mean** of token-bucket waiting inside
the turn latency at `LLM_RPM=10` — 20 % of the run's wall clock, p90 12.2 s, max 14.0 s. The limit
being waited on was ours, not the provider's: the Anthropic account's own limits, read from
response headers on 2026-09-10, are **10,000 RPM and 10M input tokens per minute**, three orders of
magnitude above the self-imposed 10. Raising it on the service is an environment change with no
rebuild, and spend stays bounded independently by `LLM_DAILY_CALL_CAP` (1,500 Anthropic calls per
UTC day). The **code** default stays 10 because one local harness process shares its bucket with
the Gemini judge, whose account limits are much lower.

### Process environment that is not a `Settings` field

`OMP_NUM_THREADS=1` is read by ONNX Runtime's OpenMP layer, not by `settings.py`, so it is set in
both the Dockerfile and `render.yaml` and appears in neither `.env.example` nor the bijection test.
`ORT_INTRA_OP_NUM_THREADS` / `ORT_INTER_OP_NUM_THREADS` are deliberately **absent**: ORT does not
read them, and the pools that matter are sized by `TextEmbedding(threads=1)` in `rag/embed.py`.
The image also sets `FASTEMBED_CACHE_PATH=/app/models` (the repo default `./.cache/fastembed` is
right on a laptop and wrong in the container), `PYTHONPATH=/app/src:/app`, and `PYTHON=python` —
the last so `mcp/run_stdio.sh` and `mcp/run_http.sh`, whose default is a developer's
`.venv/bin/python`, work inside the image.

Two credentials are **operator** environment and belong to no runtime surface, so they are read
with `os.environ` in the provisioning scripts and are in neither `Settings` nor `.env.example`:
`RENDER_API_KEY` (gate 4) and `TURSO_PLATFORM_TOKEN` (gate 3).

## MCP transport

**The MCP server is not deployed as a second service, and that is a decision, not an omission.**
R7.2 explicitly permits a single service. The nine tools are served by the same `mcp` 2.2.0 server
object mounted inside the FastAPI process at `/mcp-server/mcp`, and the agent reaches it over
loopback Streamable HTTP — the same wire an external client would use, not an in-process shortcut.

Why not two services: Render's free tier grants **750 instance-hours per workspace per month**, so
two free services would *share* one budget, and each spins down independently after 15 minutes —
a request would then wait for two cold starts chained back to back rather than one. One service is
also one memory budget, one trace store and one `/health`.

**R7.3 is satisfied without a second deployment.** `MCP_SERVER_URL` points the client at any remote
MCP endpoint; when it is set to anything other than the computed loopback default, the session's
`mcp_transport_effective` records `remote`. That path is covered by the `test_mcp_remote_url` CI
test, and the stdio transport — a genuinely separate OS process, `mcp/run_stdio.sh` — is exercised
by `tests/integration/test_mcp_discovery.py` on both transports and shown in the demo video.

Proven on the built image on 2026-09-10, not asserted: with `docker run -e PORT=10000`,
`/health.mcp` reports `connected: true`, `tool_count: 9`, `transport: http`,
`url: http://127.0.0.1:10000/mcp-server/mcp` — which is also how the `sh -c` form of the
Dockerfile's `CMD` is proved to expand `${PORT}` at run time.

## Cost

**$0 of infrastructure.** Render Hobby free, Turso free, no paid database, embeddings computed
locally by a baked ONNX model, and free Actions minutes because the repository is public (verified
public 2026-09-08). The models are the only spend: the agent's Anthropic calls, and — since paid
billing was enabled on the judge Cloud project on 2026-09-10 — the Gemini judge, at ≈ $0.16–0.18 a
pass (249 to 296 calls, depending on how many answers the run had to decompose).

| Line | Amount | Observed |
|---|---|---|
| Render Hobby web service | **$0** — `plan: free`, asserted from the API's own read-back before and after creation, not from the request. A payment method is on the workspace because Render refuses to create *any* service without one (402 `Payment information is required`); nothing on it is billable | 2026-09-10 |
| Render free-tier budgets | **750 instance-hours** per workspace per calendar month and **500 build-pipeline minutes**. Build minutes used to date **~11.5 of 500** (`scripts/check_render_hours.py`, an upper bound derived from deploy wall-clock). Instance hours read **UNAVAILABLE**: `GET /v1/metrics/instance-count` answers 200 with no samples for a free instance type, so the dashboard's usage page is the figure to read — the script says so rather than printing zero | 2026-09-11 |
| Turso database | **$0** — organisation `seantm` on the free **Starter** plan with `overages: false`, holding one database (`mosaic-hr`, group `default`, `aws-us-west-2`) | 2026-09-10 |
| Embeddings | **$0** — `BAAI/bge-small-en-v1.5` runs in-process | — |
| Judge + failover (Gemini `gemini-3.5-flash-lite`) | **≈ $0.16–0.18 a judge pass** — $0.30 / $2.50 per MTok in / out, the paid standard rates on the judge project since **2026-09-10**; the failover project is still on a free key. A pass is 249–296 calls over ~369k input / ~20k output tokens. Judge spans written before that day carry `cost_usd_estimate` **$0** because cost is priced at write time, so the pass figure is stated from token counts | 2026-09-10 |
| Agent (Anthropic `claude-haiku-4-5`) | **$6.84 across the twelve committed evaluation runs** (the sum of their `est_cost_usd`, agent plus judge spans as priced at write time), plus **≈ $0.09** for the two live demo turns — well inside §9.8's "under $10 all-in" | 2026-09-11 |
| GitHub Actions | **$0** — public repository, no minute cap | 2026-09-08 |

**Build wall-clock, measured 2026-09-10** on the development machine (macOS arm64, Docker 29.6.1,
`linux/arm64`); the Render builder's own figure is the ~11.5 minutes over all deploys above. A cold `docker build
--no-cache` took **171.5 s (2 min 52 s)**, spent as:

| Build step | Wall-clock |
|---|---|
| `pip install -r requirements.txt` | 46.2 s |
| bake the `BAAI/bge-small-en-v1.5` ONNX model into `/app/models` | 7.3 s |
| `ingest --verify-manifest` + `index --selftest` (the whole corpus, embedded) | 107.6 s |
| export and unpack the image | 9.5 s |
| **total** | **171.5 s** |

**The build-minute arithmetic that follows.** At ~3 minutes a build, the 500 included pipeline
minutes are ~165 builds a month, and the `deploy` job fires at most once per push to `main`. The
two most expensive steps are exactly the two that keep a *cold start* cheap — the model bake and
the index build — so this is the budget being spent deliberately, once per deploy, rather than
0.1 CPU-seconds being spent on every spin-up. `scripts/check_render_hours.py` warns above 600 of
750 instance-hours and 400 of 500 build minutes and **never fails**; it derives both from the
metrics and deploys endpoints, because Render publishes no usage endpoint, and it says so on every
line it prints.

**The instance-hour arithmetic, now that the keep-alive is armed.** The keep-alive (§*Cold start*
→ *Keep-alive*) keeps the instance awake round the clock while `KEEP_ALIVE_URL` is set on the
service — which it has been since 2026-09-11 14:26Z, as that subsection's status paragraph records
with its uptime evidence — so the month's consumption trends to ~744 of the 750 free hours **by
design** rather than to the handful of hours an idle demo would use. That figure is the ceiling for
both layers together — an awake instance is counted once however many things ping it — and it did
not move when the in-process self-ping joined the GitHub schedule. Exhausting the 750 suspends the
free service until the month resets and bills nothing; the levers are one Render environment
variable and one Actions menu.

### Memory — the 512 MB gate, measured 2026-09-10

`make docker-run-512` runs the real image under `docker run -m 512m --memory-swap 512m` (swap equal
to the limit, so 512 MB is a hard ceiling), polls `/ready` so the ONNX session is resident, serves
one stubbed turn through `POST /chat` over `Authorization: Bearer`, and asserts
`/health.app.rss_mb < 420`:

```
http://127.0.0.1:8000 is up after 2.2s
http://127.0.0.1:8000/ready is green after 2.7s
  status=ok  git_sha=415f358322daeda3fdcbf236a7a27f431200740f  rss_mb=294.9  deploy_mode=local
  mcp.connected=True  tool_count=9  transport=http  url=http://127.0.0.1:8000/mcp-server/mcp
  index.loaded=True  doc_count=14  chunk_count=204  embed_model=BAAI/bge-small-en-v1.5
  degradations=[]

OK — MCP connected with 9 tools and the baked index carries all 14 documents · rss_mb 294.9 < 420.0.
```

**294.9 MB** against a §14.3 budget of 345 MB and a ceiling of 420 MB — **217 MB of headroom**
below the 512 MB limit. The published figure is the one the image built from **this** commit
reported, not an earlier one: two runs of the gate on it read **294.9** and **293.0** MB. Six
earlier runs the same day, each on the image built from the commit whose `git_sha` that run
printed, read **290.4**, **291.3**, **292.1**, **292.1**, **292.2** and **292.9** MB — so the
spread across eight builds is 4.5 MB, the figure is stable to a few megabytes and the assertion is
nowhere near its threshold. The reading is `/proc/self/status` `VmRSS` inside the container (a real
Linux cgroup, under Docker Desktop's `linux/arm64` VM), not the macOS `getrusage` high-water mark
that `CHANGELOG.md`'s P1 entry distinguishes.

**On Render's own `linux/amd64` instance: `rss_mb` 293.6**, read from the live `/health` payload by
`scripts/smoke_deployed.py` on 2026-09-10 alongside `status: ok`, `deploy_mode: render`,
`mcp.connected: true`, `tool_count: 9`, 14 documents / 204 chunks, `trace_store_backend: turso` and
an empty `degradations[]`. That is 1.3 MB from the local reading and 126 MB below the 420 MB
assertion, so the memory budget behaves the same on the platform as it does under the local gate.

### Live provider facts — read at P11 step 0

Every row of §3.1 that P11 owns, read live on the date shown. Nothing here is inferred.

| Fact | Observed | Read on | Source |
|---|---|---|---|
| Render free instance hours | **750 Free instance hours to each workspace per calendar month** (verbatim) | 2026-09-10 | https://render.com/docs/free |
| Render free spin-down | **"Render spins down a Free web service that goes 15 minutes without receiving any inbound traffic"** | 2026-09-10 | https://render.com/docs/free |
| Render build-pipeline minutes | **500 included Starter-tier pipeline minutes per month** on the Hobby workspace. When they run out and there is no payment method or the spend limit is reached, "Render stops running pipeline tasks (including service builds!) for the remainder of the current month." Overage is $5 / 1,000 minutes. | 2026-09-10 | https://render.com/docs/build-pipeline |
| Render documented HTTP request timeout | **"Render web services allow HTTP responses to take up to 100 minutes."** `/docs/web-services` carries no timeout section; this is the figure Render publishes. | 2026-09-10 | https://render.com/docs/render-vs-vercel-comparison |
| Turso free-tier limits | **100 databases · 5 GB storage · 500 M rows read/month · 10 M rows written/month** | 2026-09-10 | https://turso.tech/pricing |
| Measured container RSS under `docker run -m 512m` | **294.9 MB** on this commit's image (293.0 MB on its second run; 290.4, 291.3, 292.1, 292.1, 292.2 and 292.9 MB on six earlier runs of the same gate that day; see the memory section above) | 2026-09-10 | `make docker-run-512` |
| Measured cold start / warm turn on the live instance | median **71.0 s** cold to first answer (range 67.5–77.6; segment medians 44.8 s to `/health`, 0.1 s on to `/ready`, 23.9 s for the first `POST /chat`) and median **22.5 s** warm (22.5–23.9) — n=3, no keep-alive | 2026-09-10, 2026-09-11 | `scripts/measure_cold_start.py`, `docs/evidence/cold-start-probes.json` |
| Measured `rss_mb` on the live instance | **293.6 MB** at `/health`, `status: ok`, `degradations: []` | 2026-09-10 | `scripts/smoke_deployed.py` |
| Render plan details read back from the API | **`plan: free`**, one instance, region `oregon`, no disk, PR previews off, `autoDeploy: "no"` | 2026-09-10 | `GET /v1/services/{id}` |
| Render usage: instance hours | **UNAVAILABLE from the API** — `GET /v1/metrics/instance-count` answers 200 with no samples for a free instance type; the dashboard's usage page needs an authenticated session | 2026-09-11 | `scripts/check_render_hours.py` |

**What the 100-minute request timeout settles.** §3.1 lists it because it caps
`AGENT_WALL_CLOCK_S`. At 90 s the agent budget is three orders of magnitude inside Render's limit,
so **no change is needed** and the platform is not what bounds a turn — `AGENT_MAX_STEPS`,
`AGENT_MAX_TOOL_CALLS` and the token bucket are.

**What the Turso figures settle.** A published eval run writes on the order of 10³ rows; the free
tier's 10 M monthly writes and 5 GB are not a constraint this project can approach, and
`TRACE_RETENTION_SESSIONS = 300` bounds the store regardless.

**The one thing Turso had never been asked, answered.** Until 2026-09-10 `TursoHTTPStore` had been
exercised only against an httpx `MockTransport` (P1's carry-forward), so **whether foreign keys are
enforced on the Hrana `/v2/pipeline` path was unknown** — `SqliteStore` issues
`PRAGMA foreign_keys=ON` per connection and the HTTP store has no connection to issue it on.
`scripts/provision_turso.py`'s parity smoke asked on the first live run and the answer is **yes**:
`PRAGMA foreign_keys` returned **1** and a real orphan-child `INSERT` was **refused by the server**.
No warning was needed. (Had it come back unenforced it would have been recorded as a warning, not a
failure: every write goes through `core/trace.py`, which inserts parents before children by
construction.)

**Turso usage on the live database**, read 2026-09-10: 379k rows read and 10.5k written since the
period opened at 04:00Z that day — both eval sweeps plus Render's 5-second `/health` poll, which
costs five store queries each. Against the free tier's 500M reads and 10M writes a month, no quota
action is needed, and `TRACE_RETENTION_SESSIONS = 300` bounds the store regardless.

### Live provider facts — read at P10 step 0

| Fact | Observed | Read on | Source |
|---|---|---|---|
| Anthropic `claude-haiku-4-5` input | **$1.00 / MTok** | 2026-09-09 | https://claude.com/pricing (`https://www.anthropic.com/pricing` 301s here) |
| Anthropic `claude-haiku-4-5` output | **$5.00 / MTok** | 2026-09-09 | as above |
| Anthropic `claude-haiku-4-5` prompt-cache **write** (5-minute TTL) | **$1.25 / MTok** | 2026-09-09 | as above |
| Anthropic `claude-haiku-4-5` prompt-cache **read** | **$0.10 / MTok** | 2026-09-09 | as above |
| Anthropic minimum cacheable prefix for `claude-haiku-4-5` | **4,096 tokens** — the highest of any current model; below it a request silently writes no cache entry and returns `cache_creation_input_tokens: 0` with no error | 2026-09-09 | https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
| Gemini free-tier limits for `gemini-3.5-flash-lite` — since 2026-09-10 these bound the **failover** project only, the judge's project being on paid billing | **not published in the API documentation.** `https://ai.google.dev/gemini-api/docs/rate-limits` no longer carries a free-tier RPM/TPM/RPD table; it states that *"rate limits depend on a variety of factors (such as your usage tier) and can be viewed in Google AI Studio"* and links to `https://aistudio.google.com/rate-limit`, which requires an authenticated session and could not be read from this environment. Third-party trackers report **15 RPM · 250,000 TPM · 1,000 RPD** for the Flash-Lite tier; that figure is **unverified** and is not relied on. | 2026-09-09 | https://ai.google.dev/gemini-api/docs/rate-limits |

**`core/models.py::MODEL_PRICES` matches the observed Anthropic prices exactly** — `{input: 1.00,
output: 5.00, cache_write: 1.25, cache_read: 0.10}` — so no change was needed, and every
`cost_usd_estimate` on an `llm_call` span is computed from the prices above.

**What the unverified Gemini figure does and does not affect.** §13.9 is explicit that the
**free-tier** Gemini RPD/TPM arithmetic bounds **only the failover path**. It no longer bounds the
judge: the judge's Cloud project moved to paid billing on 2026-09-10, so what bounds the judge is
the **≈ $0.16–$0.18 a pass (249–296 calls)** costs (the cost row above) and the wall clock, not a free daily
request cap. What bounds the agent is `LLM_DAILY_CALL_CAP` (1,500 Anthropic calls per UTC day) and
the prompt cache. The failover project is the one still on a free key, and it is exercised only
when an Anthropic call fails — each such call recorded as `provider_failover` on the span — so the
unverified figure sits on the path where it can affect nothing a published run depends on. The P10
sweep issued its judge calls behind the same token-bucket limiter as everything else (`LLM_RPM = 10`
— the code default, which is what the harness process runs; the deployed service has been configured
at `LLM_RPM=60` / `LLM_BURST=30` since 2026-09-10, on the Anthropic account's own 10,000 RPM / 10M
input-tokens-per-minute limits read from response headers that day, after the deployed sweep
recorded a 3.9 s/turn mean of bucket waiting at 10, p90 12.2 s), and the observed behaviour — how
many judge calls the run made and whether any `429` / `Retry-After` was seen — is recorded in
`CHANGELOG.md` and in the run's `eval_runs.notes`. That observation is the honest substitute for a number this environment
could not read. **P11 step 0 re-read the row on 2026-09-10 and it is still unpublished**: the AI
Studio rate-limit page still requires an authenticated session that this environment does not have.
`pending: an authenticated AI Studio session`.
