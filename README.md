# Mosaic HR Copilot

An agentic HR assistant for a fictional 120-person company. It answers employee policy questions
from a hand-authored HR corpus using hybrid retrieval (sqlite-vec + FTS5, fused with Reciprocal
Rank Fusion), reaches structured HR data through nine tools on its own **MCP server**, and shows
every step it took — routing decision, retrieval, tool calls, guardrails — in a full audit trail.
State-changing actions are mock and pass a one-time human confirmation gate before anything is
written.

Deployed: https://mosaic-hr-copilot.onrender.com/?access=FaGQUENKinWIfcD5yp3XMzD-GqH9oxJDXesOIinFKcY
Demo video: pending: gate 6 (record the walkthrough) — see docs/demo-script.md
Repo: https://github.com/seantmalone/quantic-mosaic

Documentation: `design-and-evaluation.md` (architecture, RAG and MCP design, evaluation results),
`deployed.md` (the live deployment, access and cold start), `ai-tooling.md` (AI-use disclosure),
`docs/architecture.html` (an interactive walkthrough of the architecture),
`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` (the full design spec).

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
```

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

## Deployment

The service runs as a Docker image on Render's free tier, built from the committed `Dockerfile`
and `render.yaml`, deployed only by a CI job that `needs: [test, docker]`.

```bash
make docker            # build the image
make docker-run-512    # run it under the 512 MB memory gate
```

**Access.** The deployed instance carries one shared secret, `APP_ACCESS_TOKEN`. The link on the
`Deployed:` line above already carries it as `?access=<token>`, which is exchanged once for an
HttpOnly cookie and stripped from the URL; API clients and MCP Inspector send
`Authorization: Bearer <token>` instead. Choose **HR admin** in the act-as selector to reach the
observability dashboard. Full details, every environment variable and the measured numbers are in
`deployed.md`.

**Cold start.** The free instance spins down after 15 minutes idle. Measured on the live service —
n=1, 2026-09-10, without a keep-alive, after 1,000 s of idle — waking it took **44.8 s** to the
first `GET /health` 200, **2.8 s** more for `/ready`, and **23.3 s** for the first `POST /chat`:
**71.0 s** from cold to first answer, against **22.5 s** for a warm turn. Open `/health` first and
wait for a 200 before chatting; the UI shows a cold-start banner with an elapsed counter while that
happens. `deployed.md` carries the segment table and its provenance.

## Evaluation

```bash
make eval        # the 26-item dataset against EVAL_TARGET_BASE_URL
make ablation    # compares the baseline run against the two ablation variants
```

Results are committed under `evaluation/results/` and rendered by the dashboard's evaluation
pages; `evaluation/REPORT.md` carries the written analysis and
`design-and-evaluation.md` carries the methodology, the 26 questions with their expected answers,
the judge-agreement figures and the known limitations.

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
