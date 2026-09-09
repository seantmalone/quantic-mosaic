# Mosaic HR Copilot

An agentic HR assistant for a fictional 120-person company. It answers employee policy questions
from a hand-authored HR corpus using hybrid retrieval (sqlite-vec + FTS5, fused with Reciprocal
Rank Fusion), reaches structured HR data through nine tools on its own **MCP server**, and shows
every step it took — routing decision, retrieval, tool calls, guardrails — in a full audit trail.
State-changing actions are mock and pass a one-time human confirmation gate before anything is
written.

Deployed: TBD-before-submission
Demo video: TBD-before-submission
Repo: https://github.com/seantmalone/quantic-mosaic

Documentation: `design-and-evaluation.md` (architecture, RAG and MCP design, evaluation results),
`deployed.md` (the live deployment, access and cold start), `ai-tooling.md` (AI-use disclosure),
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

## Deployment

The service runs as a Docker image on Render's free tier, built from the committed `Dockerfile`
and `render.yaml`, deployed only by a CI job that `needs: [test, docker]`.

```bash
make docker            # build the image
make docker-run-512    # run it under the 512 MB memory gate
```

**Cold start.** The free instance spins down after 15 minutes idle, so the first request after an
idle period takes roughly 35–70 seconds. Open `/health` first and wait for a 200 before chatting;
the UI shows a cold-start banner with an elapsed counter while that happens.

## Evaluation

```bash
make eval        # the 26-item dataset against EVAL_TARGET_BASE_URL
make ablation    # compares the baseline run against the two ablation variants
```

Results are committed under `evaluation/results/` and rendered by the dashboard's evaluation
pages; `evaluation/REPORT.md` carries the written analysis.

## Third-party components

- **Runtime:** FastAPI, uvicorn, Pydantic, pydantic-settings, httpx, Jinja2, `mcp` 2.2.0,
  fastembed (`BAAI/bge-small-en-v1.5`), sqlite-vec, `anthropic`, `openai`, pypdf,
  beautifulsoup4, markdownify, PyYAML, jsonschema — all pinned in `requirements.txt`.
- **Frontend:** htmx, Alpine.js and Chart.js, vendored at pinned versions with no runtime CDN.
  Versions, upstream URLs and full licence texts are in
  `src/hrmosaic/web/static/vendor/LICENSES.md`.
- **Development only:** pytest, ruff and fpdf2, pinned in `requirements-dev.txt`, which never
  enters the Docker image.
