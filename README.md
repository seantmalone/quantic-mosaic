# Mosaic HR Copilot

An agentic HR assistant for a fictional 420-person company. It answers employee policy questions
from a hand-authored HR corpus using hybrid retrieval (sqlite-vec + FTS5, fused with Reciprocal
Rank Fusion), reaches structured HR data through nine tools on its own **MCP server**, and shows
every step it took — routing decision, retrieval, tool calls, guardrails — in a full audit trail.
State-changing actions are mock and pass a one-time human confirmation gate before anything is
written.

Deployed: https://mosaic-hr-copilot.onrender.com/?access=FaGQUENKinWIfcD5yp3XMzD-GqH9oxJDXesOIinFKcY
Demo video: pending: gate 6 (record the walkthrough) — see [`docs/demo-script.md`](docs/demo-script.md)
Repo: https://github.com/seantmalone/quantic-mosaic

Documentation: [`design-and-evaluation.md`](design-and-evaluation.md) (architecture, RAG and MCP
design, evaluation results), [`deployed.md`](deployed.md) (the live deployment, access and cold
start), [`mcp/README.md`](mcp/README.md) (the MCP server: nine tools, three transports, the host
allowlist and the SDK behaviour behind it), [`ai-tooling.md`](ai-tooling.md) (AI-use disclosure),
[`docs/architecture.html`](docs/architecture.html) (an interactive walkthrough of the architecture),
[`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`](docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md)
(the full design spec),
[`docs/requirements-traceability.md`](docs/requirements-traceability.md) (every rubric bullet mapped
to the test, command or artifact that proves it), and
[`docs/process/sdd/`](docs/process/sdd/) (the committed process trail: every phase brief and report).

## Setup

Python 3.12 (`.python-version` pins 3.12.14). Create the virtual environment and install the
pinned dependencies:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pip install -e .   # puts `hrmosaic` on the import path for `python -m hrmosaic...`
cp .env.example .env      # optional: no credential is needed to boot, lint or test
```

`make setup` runs exactly those steps. Every dependency is pinned in `requirements.txt`, which is
compiled from the authoritative `pyproject.toml` with `uv pip compile`.

## Local Run

```bash
make run          # uvicorn on http://127.0.0.1:8000
make run-stdio    # the same MCP server over stdio, for MCP Inspector or the demo
make lint         # ruff check . && ruff format --check .
make test         # pytest -q over the whole suite
make coverage     # the same suite under coverage, then the 90% gate and coverage.xml
```

**Tests and coverage.** `make test` runs the whole suite in one command — 1,963 tests as of
2026-09-11, unit, contract, integration, architecture and e2e-with-stub, every one of them against
the scripted stub provider, so no credential is involved. `make coverage` runs that same suite
under `coverage run --branch --source=src/hrmosaic`, writes `coverage.xml`, and then enforces
`coverage report --fail-under=90`. Measured on 2026-09-11: **95% of statements and 87% of branches
over 7,265 statements**, which `coverage report` prints as the combined **94%** the gate reads. The
CI `test` job runs those same three commands, so the gate that blocks a deploy is the one a
developer runs locally; it prints the per-module table in the job log and uploads `coverage.xml` as
a build artifact, with no third-party coverage service and no badge token involved.

The app boots with no credentials: with `LLM_PROVIDER=stub` it replays a recorded script, and
with a real provider but no key it still boots, reports `degraded` on `/health` and answers
`/chat` with an actionable configuration message rather than an error.

**The two demo tasks.** Both are one-click buttons in the chat UI and both have a curl script.

```bash
make demo1        # international remote-work eligibility — multi-document, no write
make demo2        # a PTO request through the confirmation gate to a mock write

# or against any running instance, including the deployed one:
BASE_URL=https://<app>.onrender.com APP_ACCESS_TOKEN=<key> sh scripts/demo_task_1.sh
```

`make demo1` / `make demo2` each start their own server with their own recorded stub script, so
they need no key. The scripts are plain `curl`, parameterised by `BASE_URL`, and print the answer,
the citations, the full span trace and the `dashboard_url` for the turn. Every call sends
`Authorization: Bearer $APP_ACCESS_TOKEN`.

**Pinned evidence — both tasks run live against the deployed service on 2026-09-11**, transcripts
committed with the bearer token redacted and nothing else edited:
[`docs/evidence/demo-task-1-live-2026-09-11.txt`](docs/evidence/demo-task-1-live-2026-09-11.txt)
(8 citations across 3 documents, 30 spans, a `conditional` verdict) and
[`docs/evidence/demo-task-2-live-2026-09-11.txt`](docs/evidence/demo-task-2-live-2026-09-11.txt)
(the confirmation gate, then `MOCK-HR-000005`, 4 citations across 2 documents, 29 spans). The
trace store rolls, so these are the record of what the deployed instance actually did.

## Deployment

The service runs as a Docker image on Render's free tier, built from the committed `Dockerfile`
and `render.yaml`, deployed only by a CI job that `needs: [test, docker]`.

```bash
make docker            # build the image
make docker-run-512    # run it under the 512 MB memory gate
```

**CI/CD.** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on push to `main`, on pull
request and on `workflow_dispatch`: `lint` (`ruff check` + `ruff format --check`, then a
full-history gitleaks scan), `test` (`check_facts.py`, `ingest --verify-manifest`, the whole
suite against the stub provider including MCP tool discovery, under a **90% coverage gate**, then
`pii_check.py`),
`docker` (builds the image and asserts sqlite-vec loads and the templates and static assets ship),
and `deploy`, which carries `needs: [test, docker]` so a red test or a broken image blocks the
deploy — see the skipped-deploy run in
[`docs/evidence/ci-deploy-skipped.png`](docs/evidence/ci-deploy-skipped.png) and the `### CI/CD`
section of [`design-and-evaluation.md`](design-and-evaluation.md).

**Access.** The deployed instance carries one shared secret, `APP_ACCESS_TOKEN`. The link on the
`Deployed:` line above already carries it as `?access=<token>`, which is exchanged once for an
HttpOnly cookie and stripped from the URL; API clients and MCP Inspector send
`Authorization: Bearer <token>` instead. An external MCP client also needs its `Host` on
`MCP_ALLOWED_HOSTS` — see [`mcp/README.md`](mcp/README.md), which documents the MCP server, its
three transports and the host allowlist in full. Choose **HR admin** in the act-as selector to reach the
observability dashboard. Full details, every environment variable and the measured numbers are in
`deployed.md`.

**Cold start.** The free instance spins down after 15 minutes idle. Measured on the live service
three times — n=3, 2026-09-10 and 2026-09-11, without a keep-alive, each probe after 1,000 s of
idle — waking it took a median **44.8 s** to the first `GET /health` 200, **0.1 s** more for
`/ready`, and **23.9 s** for the first `POST /chat` — and, as three separately measured wall clocks,
a median **71.0 s** from cold to first answer (67.5–77.6 s across the three; the segment medians are
taken per segment, so they do not sum to it), against **22.5 s** for a warm turn (22.5–23.9 s). Open `/health`
first and wait for a 200 before chatting; the UI shows a cold-start banner with an elapsed counter
while that happens. `deployed.md` carries the per-probe table and its provenance, and a two-layer
keep-alive (added 2026-09-11 *after* these figures were published) keeps the instance warm **once
`KEEP_ALIVE_URL` is set on the service**: the app then pings its own public `/health` every ten
minutes from inside the process, with `.github/workflows/keepalive.yml` behind it as a second layer
because GitHub's cron skipped most of its scheduled runs. `render.yaml` now carries the value so a
blueprint apply cannot undo it, and the `Dockerfile` deliberately does not; but the live service was
created over the REST API and `autoDeploy: false` means no apply runs on its own, so
**`KEEP_ALIVE_URL` is still not set on the live service** — the in-process layer is not running and
the numbers above are exactly what a visitor gets. Setting it is one single-key PUT with no rebuild;
clearing it again and disabling that workflow puts the service back to them for good.

## Evaluation

```bash
make eval        # the 26-item dataset against EVAL_TARGET_BASE_URL
make ablation    # compares the baseline run against the two ablation variants
```

Results are committed under `evaluation/results/` and rendered by the dashboard's evaluation
pages; [`evaluation/REPORT.md`](evaluation/REPORT.md) carries the written analysis and
[`design-and-evaluation.md`](design-and-evaluation.md) carries the methodology, the 26 questions
with their expected answers, the judge-agreement figures and the known limitations.

**The published run** is `r_1789086979_baseline` — 26 items, `target: deployed`, judged by
`gemini-3.5-flash-lite`, served by commit `da0dca2`. Beside it is the pre-optimization deployed
baseline `r_1789055103_baseline`, run on the same instance and the same dataset before any of the
quality or performance work:

| Metric | Before (`r_1789055103_baseline`) | Published (`r_1789086979_baseline`) |
|---|---|---|
| Strict pass rate (target ≥ 0.85) | 0.692 | **0.808** |
| Groundedness | 0.979 | 0.982 |
| Citation accuracy | 0.847 | 0.925 |
| Document recall | 0.855 | 0.974 |
| Tool selection (F1) | 0.926 | 0.992 |
| Workflow completion | 0.769 | 0.846 |
| Over-refusal / missed-refusal | 0.111 / 0.000 | 0.000 / 0.000 |
| Latency p50 / p95 | 17.6 s / 47.7 s | **16.7 s** / **32.4 s** |
| Judge agreement (blind seed subset) | 1.00 (n = 7) | 1.00 (n = 8) |
| Judge agreement (hard subset, selection disclosed) | 1.00 (n = 8) | 0.875 (n = 8) |

**How it got there — and what it cost — is in [`docs/optimization-log.md`](docs/optimization-log.md)**:
every optimization question asked, the evidence gathered, the decision taken, and the run id that
measured it.

## Third-party components

- **Runtime:** FastAPI, uvicorn, Pydantic, pydantic-settings, httpx, Jinja2, `mcp` 2.2.0,
  fastembed (`BAAI/bge-small-en-v1.5`), sqlite-vec, `anthropic`, `openai`, pypdf,
  beautifulsoup4, markdownify, PyYAML, jsonschema — all pinned in `requirements.txt`.
- **Frontend:** htmx, Alpine.js and Chart.js, vendored at pinned versions with no runtime CDN.
  Versions, upstream URLs and full licence texts are in
  `src/hrmosaic/web/static/vendor/LICENSES.md`.
- **Development only:** pytest, ruff and fpdf2, pinned in `requirements-dev.txt`, which never
  enters the Docker image.
