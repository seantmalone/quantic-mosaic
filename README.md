# Mosaic HR Copilot

Mosaic HR Copilot is an agentic HR assistant for a fictional 420-person company. It answers policy
questions from a 14-document HR corpus and cites the passages it used. For multi-step requests it
calls nine tools on its own MCP server, and it asks you to confirm before any write.

Deployed: https://mosaic-hr-copilot.onrender.com/?access=FaGQUENKinWIfcD5yp3XMzD-GqH9oxJDXesOIinFKcY
Demo video: https://drive.google.com/file/d/1hgD73nrhBYTG1eBRQ7JCfIINOcyXW-uz/view?usp=sharing
Repo: https://github.com/seantmalone/quantic-mosaic

The deployed link carries the access token, so opening it signs you in. A cold instance can take
about a minute to wake. See [Cold start](#cold-start).

## For graders

| Rubric area | Where to see it |
|---|---|
| RAG and citations | Ask a policy question in the chat. Each answer lists its sources and opens the cited passage in the policy reader. Design: [RAG design](design-and-evaluation.md#rag-design). Code: `src/hrmosaic/rag/` |
| MCP tools and discovery | **Dashboard → Tool server** shows the live `tools/list` result with all nine schemas. Server docs: [`mcp/README.md`](mcp/README.md). Schemas: [`mcp/tools/`](mcp/tools/). Code: `src/hrmosaic/mcpserver/` |
| Two agentic tasks | The two demo prompts in the **Demo & grader controls** panel below the chat, or `scripts/demo_task_1.sh` and `scripts/demo_task_2.sh` (see [Local Run](#local-run)). Expected tool sequences: [The two demo tasks](design-and-evaluation.md#the-two-demo-tasks) |
| Tool-call trace | **Dashboard → Sessions** opens each turn's record: routing, retrieval, each tool call with its arguments and result, and the guardrail verdicts |
| Architecture | [Architecture](design-and-evaluation.md#architecture) has the diagram and one turn end to end. [`docs/architecture.html`](docs/architecture.html) is an interactive version |
| Deployment and cold start | [`deployed.md`](deployed.md): URLs, access, environment variables, measured cold start, keep-alive |
| CI/CD | [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Deploy runs only after lint, tests, the browser suite and the image build pass. Details: [CI/CD](design-and-evaluation.md#cicd) |
| Evaluation | [`evaluation/REPORT.md`](evaluation/REPORT.md) and **Dashboard → Evaluations**. Headline numbers are [below](#evaluation) |
| Design document | [`design-and-evaluation.md`](design-and-evaluation.md) |
| AI tooling | [`ai-tooling.md`](ai-tooling.md) |
| Mock data | [`mock_data/`](mock_data/): synthetic employees, PTO, benefits and offices |
| Requirement map | [`docs/requirements-traceability.md`](docs/requirements-traceability.md) maps each requirement to the file or test that shows it |

**Demo task 1** asks whether Priya (E1042) can work from Berlin for six weeks. The agent looks up her
profile, runs the compliance check and searches the remote-work, security and tax policies. You get
a cited, conditional answer, and nothing is written.

**Demo task 2** asks for three days of PTO and asks the agent to file the request. The agent checks
the balance and the policy, then stops at a confirmation card. Click Confirm and it creates a mock
ticket (`MOCK-HR-<n>`). **Dashboard → Guardrails** lists it in the mock-action log.

## Setup

You need Python 3.12. `.python-version` pins 3.12.14.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pip install -e .
cp .env.example .env      # optional: booting, linting and testing need no key
make ingest               # builds data/index/hr_index.sqlite
```

`make setup` runs the same installs. Ingest builds the index locally; the repo does not commit it.
Embeddings come from a local ONNX model (`BAAI/bge-small-en-v1.5`) that fastembed downloads on first
use, so ingest needs no API key. `make lock` compiles `requirements.txt` from `pyproject.toml`.

The app reads secrets only from environment variables. `.env.example` lists every setting.

## Local Run

```bash
make run          # the app on http://127.0.0.1:8000
make run-stdio    # the MCP server alone over stdio, for MCP Inspector
make demo1        # demo task 1 against a local server with a recorded model script
make demo2        # demo task 2, through the confirmation card to the mock write
make test         # the full test suite, no key needed
make lint         # ruff check and format check
```

Set `LLM_PROVIDER=stub` and the app replays recorded model exchanges, so you need no key. With a real
provider and no key it still boots, reports `degraded` on `/health`, and says in the chat what is
missing.

To run a demo task against the deployed service:

```bash
BASE_URL=https://mosaic-hr-copilot.onrender.com APP_ACCESS_TOKEN=<token> sh scripts/demo_task_1.sh
```

Each script prints the answer, the citations, the span trace and a dashboard link for the turn. API
clients send `Authorization: Bearer <token>`.

## Deployment

The app runs as one Docker service on Render's free tier, built from the `Dockerfile` and
`render.yaml`. One process holds the web app, the agent, the MCP server (reached over loopback
Streamable HTTP), the sqlite-vec index and the mock data. Traces go to a free Turso database.

```bash
make docker            # build the image
make docker-run-512    # run it under the 512 MB memory limit
```

A push to `main` deploys only after the `test`, `ux` and `docker` jobs pass. The `test` job checks
that the app starts and that MCP tool discovery works. [`deployed.md`](deployed.md) lists every
environment variable and how a commit reaches the service.

### Cold start

The free instance sleeps after 15 minutes idle. In three measurements in September 2026, a cold
instance took a median 44.8 s to answer `GET /health` and 71.0 s to give a first chat answer. A warm
turn took about 22.5 s at the time. The chat shows a banner while the service wakes. A keep-alive
pings `/health` every ten minutes. It has been armed on the live service since 2026-09-11, so you
will usually find it warm. [`deployed.md`](deployed.md#cold-start) has the per-probe numbers.

## Evaluation

[`evaluation/dataset.yaml`](evaluation/dataset.yaml) holds 30 items, each with a gold answer: plain
policy questions, multi-document questions, tool tasks, ambiguous requests, and out-of-scope,
unsafe and sensitive requests. A model from a second vendor judges groundedness and citation
accuracy. A separate blind labelling session checked the judge on two 8-item subsets (agreement
0.875 and 0.750).

The published run is `r_1790130220_baseline`, driven on 2026-09-23 against the deployed service on
build `34d50fb`.

| Metric | Result |
|---|---|
| Strict pass (all clauses) | 27 / 30 (0.900, target ≥ 0.85) |
| Groundedness | 98.4% (n = 19) |
| Citation accuracy | 87.3% (n = 19) |
| Tool selection F1 | 99.3% (n = 30) |
| Workflow completion | 93.3% (n = 30) |
| Action safety | 2 / 2 |
| Clarification accuracy | 3 / 3 |
| Escalation | 2 / 2 |
| Latency p50 / p95 | 13.8 s / 27.9 s (30 warm turns) |

**Ablation.** With the five structured-data tools removed, workflow completion fell from 93.3% to
73.3%. The design pre-registered a drop of at least 25 points, so the report marks that hypothesis
not supported. Dense-only retrieval at k=2 left workflow completion and strict pass unchanged and
moved document recall from 97.4% to 96.1%.

[`evaluation/REPORT.md`](evaluation/REPORT.md) has the per-item results and the three failing items.
The design doc covers the method, judge agreement and known limitations under
[Evaluation](design-and-evaluation.md#evaluation-questions-expected-answers-and-results).

To reproduce:

```bash
export EVAL_TARGET_BASE_URL=<deployed url> APP_ACCESS_TOKEN=<token>
export TURSO_DATABASE_URL=<...> TURSO_AUTH_TOKEN=<...> JUDGE_API_KEY=<...>
make eval                                                     # drive the 30 items
.venv/bin/python -m evaluation.runner --judge <run_id>        # judge them
.venv/bin/python -m evaluation.runner --variant dense_only_k2
.venv/bin/python -m evaluation.runner --variant no_structured_tools
make ablation                                                 # writes comparison.json
```

The runner reads traces from the store the target wrote to, so a deployed run needs the service's
Turso credentials. The application code has not changed since the measured build. This command
prints nothing:

```
git diff --stat 34d50fb..HEAD -- src mcp/tools mcp/server_entrypoint.py mcp/run_stdio.sh mcp/run_http.sh corpus ':!corpus/README.md' data/index/chunks.manifest.jsonl Dockerfile render.yaml requirements.txt
```

[`docs/optimization-log.md`](docs/optimization-log.md) records the tuning decisions and the runs
that measured them.

## Third-party components

- **Runtime:** FastAPI, uvicorn, Pydantic, pydantic-settings, httpx, Jinja2, `mcp` 2.2.0,
  fastembed (`BAAI/bge-small-en-v1.5`), sqlite-vec, `anthropic`, `openai`, pypdf,
  beautifulsoup4, markdownify, PyYAML and jsonschema, all pinned in `requirements.txt`.
- **Frontend:** htmx, Alpine.js and Chart.js, vendored at pinned versions with no CDN at runtime.
  Licences are in `src/hrmosaic/web/static/vendor/LICENSES.md`.
- **Models:** `claude-haiku-4-5` (Anthropic) runs the agent. `gemini-3.5-flash-lite` (Google)
  judges the evaluation.
- **Development only:** pytest, ruff and fpdf2, pinned in `requirements-dev.txt`.
