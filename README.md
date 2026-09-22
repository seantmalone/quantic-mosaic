# Mosaic HR Copilot

An agentic HR assistant for a fictional 420-person company. It answers employee policy questions
from a hand-authored HR corpus using hybrid retrieval (sqlite-vec + FTS5, fused with Reciprocal
Rank Fusion), reaches structured HR data through nine tools on its own **MCP server**, and shows
every step it took — routing decision, retrieval, tool calls, guardrails — in a full audit trail.
State-changing actions are mock and pass a one-time human confirmation gate before anything is
written.

Deployed: https://mosaic-hr-copilot.onrender.com/?access=FaGQUENKinWIfcD5yp3XMzD-GqH9oxJDXesOIinFKcY
Demo video: pending: gate 6 — the walkthrough is recorded from [`docs/demo-script.md`](docs/demo-script.md) and its link is pasted on this line at submission
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
compiled from the authoritative `pyproject.toml` with `uv pip compile`. Then build the index:

```bash
make ingest       # python -m hrmosaic.rag.ingest — writes data/index/hr_index.sqlite
```

**The index is built, not committed.** `data/index/` is git-ignored apart from
`chunks.manifest.jsonl`, the manifest CI re-verifies with `ingest --verify-manifest`, so a fresh
clone has no `hr_index.sqlite` and `rag/index.py` raises rather than indexing on demand: without
this step the app boots and `/health` answers 200, but every question comes back as a failed turn.
It needs no credential: the embeddings are computed locally by the ONNX model fastembed
downloads into `FASTEMBED_CACHE_PATH` on first use, so the first run is slower than the rest.

## Local Run

```bash
make ingest       # build the index first — `make run` cannot answer without it
make run          # uvicorn on http://127.0.0.1:8000
make run-stdio    # the same MCP server over stdio, for MCP Inspector or the demo
make lint         # ruff check . && ruff format --check .
make test         # pytest -q over the whole suite
make coverage     # the same suite under coverage, then the 90% gate and coverage.xml
```

**Tests and coverage.** `make test` runs the whole suite in one command — 3,410 tests as of
2026-09-22, unit, contract, integration, architecture and e2e-with-stub, every one of them against
the scripted stub provider, so no credential is involved. 299 of those are the browser-based UX
principle suite (`make ux`, marked `ux`): they need a chromium build, so `make test` deselects them
and CI runs them in a job of their own that never blocks `test` or `deploy`. `make coverage` runs that same suite
under `coverage run --branch --source=src/hrmosaic`, writes `coverage.xml`, and then enforces
`coverage report --fail-under=90`. Measured on 2026-09-16: **95% of statements and 87% of branches
over 10,213 statements**, which `coverage report` prints as the combined **94%** the gate reads. The
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
`Authorization: Bearer $APP_ACCESS_TOKEN`. Each one asks the instance for its own demo prompt
before it starts, the same self-dated question the chat page's Demo 1 / Demo 2 buttons carry, so
the dates are always far enough ahead for the notice rules to pass and the verdicts hold against
the deployed service as well as against the pinned replays. `--recorded` (or `DEMO_RECORDED=1`)
sends the frozen wording the stub scripts were recorded against instead; the `make` targets do
not need it, because they pin `MOCK_TODAY=2026-09-01` on their own server and the prompt they
fetch from it comes back byte for byte the recorded one.

**Pinned evidence — both tasks run live against the deployed service on 2026-09-11**, transcripts
committed with the bearer token redacted and nothing else edited:
[`docs/evidence/demo-task-1-live-2026-09-11.txt`](docs/evidence/demo-task-1-live-2026-09-11.txt)
(8 citations across 3 documents, 30 spans, a `conditional` verdict) and
[`docs/evidence/demo-task-2-live-2026-09-11.txt`](docs/evidence/demo-task-2-live-2026-09-11.txt)
(the confirmation gate, then `MOCK-HR-000005`, 4 citations across 2 documents, 29 spans). Demo
task 2 was then **re-run on the build being submitted** —
[`docs/evidence/demo-task-2-live-2026-09-12.txt`](docs/evidence/demo-task-2-live-2026-09-12.txt)
(the same gate, then `MOCK-HR-000006`, 4 citations across 2 documents, 32 spans, 40 s), run
against `/health` sha `f5e86c3`. The trace store rolls, so these are the record of what the deployed
instance actually did. The fourth pinned transcript is the **external MCP session** —
[`docs/evidence/mcp-external-session-2026-09-12.txt`](docs/evidence/mcp-external-session-2026-09-12.txt)
(plain `curl` from outside the service: `initialize` 200, `notifications/initialized`, `tools/list`
returning all nine tools, a real `search_policy_documents` call with its retrieval span) — which is
what makes the "attachable by an external MCP client" claim checkable rather than asserted. Its own
header states which calls from that session were *not* captured and are therefore attributed to the
build ledger rather than pinned.

## The interface

Two surfaces and one shell: a **chat** page that is nothing but the conversation, and an
**observability dashboard** holding every technical detail the chat page does not show. The masthead
is the same partial on both, the `Chat | Dashboard` switch is on every page in every persona, and
the demo-only controls — the persona picker, the scripted prompts, the deep link into the record —
live in one labelled *Demo & grader controls* panel at the foot of the chat page, collapsed by
default, so nothing a real user would never see is mixed into the product.

The final screen set is committed under
[`docs/evidence/ux-final/`](docs/evidence/ux-final/) — chat at rest, an answered turn with its
sources, the confirmation card, a refusal, a failed turn, the policy reader, all thirteen dashboard
routes, five phone screens, and nine of the same surfaces again in the **dark** palette. They are
reproducible rather than curated: `make ux-capture` re-photographs all 69 screen ids from four stub
servers on loopback with `LLM_PROVIDER=stub`, and its own `index.json` records the geometry
(`body_horizontal_scroll` false on every screen at 1440x900, 1280x800 and 390x844).

Accessibility is measured, not asserted. `pytest -m ux` drives a real browser and checks the skip
link, the focus indicator on every keyboard stop, 44 px tap targets at 390 px, the 13 px type floor,
`prefers-reduced-motion`, form labels, and WCAG AA contrast on the colours the browser actually
painted in both colour schemes; `pytest -q` recomputes every brand colour pair from the shipped
tokens (`tests/contract/test_brand_contrast.py`) and holds the design document's published table to
what the tokens really measure.

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
three transports and the host allowlist in full. The observability dashboard is reachable from the
`Chat | Dashboard` switch in the masthead, in any persona; only the three write controls need
**HR admin**. Full details, every environment variable and the measured numbers are in
`deployed.md`.

**Cold start.** The free instance spins down after 15 minutes idle. Measured on the live service
three times — n=3, 2026-09-10 and 2026-09-11, without a keep-alive, each probe after 1,000 s of
idle — waking it took a median **44.8 s** to the first `GET /health` 200, **0.1 s** more for
`/ready`, and **23.9 s** for the first `POST /chat` — and, as three separately measured wall clocks,
a median **71.0 s** from cold to first answer (67.5–77.6 s across the three; the segment medians are
taken per segment, so they do not sum to it), against **22.5 s** for a warm turn (22.5–23.9 s). Open `/health`
first and wait for a 200 before chatting; the UI shows a cold-start banner with an elapsed counter
while that happens. `deployed.md` carries the per-probe table and its provenance, and a two-layer
keep-alive (added 2026-09-11 *after* these figures were published) holds the instance awake: the app
pings its own public `/health` every ten minutes from inside the process, with
`.github/workflows/keepalive.yml` behind it as a best-effort second layer because GitHub's cron
skipped most of its scheduled runs. That primary layer has been **armed on the live service since
2026-09-11 14:26Z**, when `KEEP_ALIVE_URL=https://mosaic-hr-copilot.onrender.com` and
`KEEP_ALIVE_INTERVAL_S=600` were set on it with a single-key PUT — `/health`'s `app.uptime_ms` read
60 minutes at 18:37Z and 124.5 minutes at 00:51Z the next day, spanning windows with no traffic but
a health read, which is well past the 15-minute spin-down. `render.yaml` carries the same value so a
blueprint apply cannot undo it, and the `Dockerfile` deliberately does not, because a baked origin
would start the loop in every container a developer runs. The numbers above are what a visitor gets
if the loop is ever turned off: delete the variable on the service and no task is created on the
next boot, and the workflow is stopped from the repository's **Actions** tab.

## Evaluation

```bash
make eval        # drive the 28-item dataset against EVAL_TARGET_BASE_URL — no judging
make ablation    # compare the committed baseline run against the two ablation variants
```

**The whole recipe, and the credential each step needs.** `make eval` is
`python -m evaluation.runner --variant baseline`: it drives the 28 items as one
`POST $EVAL_TARGET_BASE_URL/chat` each, carrying `Authorization: Bearer $APP_ACCESS_TOKEN` and
`X-Actor: admin`, and scores every deterministic metric. It does **not** judge — `--judge-inline` is
off by default, so a judge-provider outage cannot leave a half-judged run whose composite cannot be
computed — which means groundedness, citation accuracy, partial match and clarification accuracy
come back `null` until a second pass runs. The full sweep, in the order it was run for the published
figures:

```bash
EVAL_TARGET_BASE_URL="$DEPLOY_URL" make eval                        # (a) drive   — APP_ACCESS_TOKEN
.venv/bin/python -m evaluation.runner --judge <run_id>              # (b) judge   — JUDGE_API_KEY
.venv/bin/python -m evaluation.runner --variant dense_only_k2       # arm 1, same build
.venv/bin/python -m evaluation.runner --variant no_structured_tools # arm 2, same build
make ablation                                                       # writes comparison.json
.venv/bin/python -m evaluation.runner --report <run_id>             # re-render REPORT.md
.venv/bin/python scripts/paste_eval_numbers.py                      # refresh the design doc's table
```

Both passes read the turn and its spans back out of **the same trace store the target wrote them
to**, so against a deployed target the runner needs the service's own `TURSO_DATABASE_URL` and
`TURSO_AUTH_TOKEN` and refuses the run when the target's `/health` reports a different backend. The
judge is a second vendor on its own key — `JUDGE_PROVIDER`, `JUDGE_BASE_URL`, `JUDGE_MODEL`,
`JUDGE_API_KEY` in `.env.example`. **Every drive rewrites
[`evaluation/REPORT.md`](evaluation/REPORT.md)**, so finishing a sweep with an ablation arm leaves
the report describing that arm; `--report <run_id>` restores the published one and spends nothing.
Two more passes spend nothing either: `--cold-probes` runs the three cold-start probes, and
`--recompute-agreement <run_id> --metric judge_agreement_rate[_hard]` folds a reference-label file
into a judged run. `make ablation` only compares runs that already exist, and asserts they share
`target`, `dataset_sha` and `target_git_sha` before it writes anything.

Results are committed under `evaluation/results/` and rendered by the dashboard's evaluation
pages; [`evaluation/REPORT.md`](evaluation/REPORT.md) carries the written analysis and
[`design-and-evaluation.md`](design-and-evaluation.md) carries the methodology, the 28 questions
with their expected answers, the judge-agreement figures and the known limitations.

**The published run** is `r_1790074972_baseline` (2026-09-22) — 28 items, `target: deployed`, judged
by `gemini-3.5-flash-lite` over 268 judge calls, served by commit `8a89310`, which is the build the
live service reports at `/health`. `evaluation/results/latest.json` names it, and
`python scripts/paste_eval_numbers.py --check` exits 0 against the design document's results
table. Beside it is the pre-optimization deployed baseline `r_1789055103_baseline`, run on the same
instance before any of the quality or performance work, over the 26 items the dataset held then:

| Metric | Before (`r_1789055103_baseline`) | Published (`r_1790074972_baseline`) |
|---|---|---|
| Strict pass rate (target ≥ 0.85) | 0.692 | **0.893** |
| Groundedness | 0.979 | 0.963 (n = 18) |
| Citation accuracy | 0.847 | 0.875 (n = 18) |
| Citation resolvability | 0.923 | 1.000 (n = 28) |
| Document recall | 0.855 | 0.947 (n = 19) |
| Tool selection (F1) | 0.926 | 0.993 (n = 28) |
| Workflow completion | 0.769 | **0.964** (n = 28) |
| Over-refusal / missed-refusal | 0.111 / 0.000 | 0.000 / 0.000 |
| Latency p50 / p95 | 17.6 s / 47.7 s | 15.3 s / 26.0 s |
| Judge agreement (blind seed subset) | 1.00 (n = 7) | 1.000 (n = 8) |
| Judge agreement (hard subset, selection disclosed) | 1.00 (n = 8) | 0.875 (n = 8) |

Every judged row carries its own `n` because a judge that fails twice on an item records a `null`
verdict and the item leaves that metric's denominator. The two metrics with the smallest
denominators are named rather than implied: clarification accuracy is **1.000 over the 3 ambiguous items**, and
the action-safety pass rate is **1.000 over the 1 write item** — not over 28. The blind seed subset
came back unanimous, so its 1.000 cannot discriminate a good judge from one that answers `grounded`
to everything; the disclosed hard-case subset exists for that, and its one disagreement is
`expenses-002`.

The project's own ≥ 0.85 strict-pass target is met. Three of the 28 items still fail the composite,
each recomputed by the same `deterministic.strict_pass_causes()` that decides the `passed` flag:
`remote-002` (workflow completion 0.00 — its answer cites 2 distinct documents where that item's
end state requires 3, and 2 of its 4 gold documents), `expenses-002` (groundedness 0.79 < 0.85) and
`equipment-001` (groundedness 0.69 < 0.85).

**The ablation, on the same build.** Both arms were re-driven on `8a89310` against the same dataset
sha. Removing the structured tools costs **0.143 of workflow completion** (0.964 → 0.821) and 0.107
of strict pass (0.893 → 0.786); narrowing retrieval to dense-only k=2 costs nothing measurable here
(strict pass 0.929, workflow completion 0.964). The design's own prediction was that the first delta
would exceed 0.25, so `evaluation/ablation.py`'s check reports **not supported** and `REPORT.md`
prints that banner rather than softening the claim. The judged metrics are computed on `baseline`
only, which is why two of the three strict-pass failures flip to a pass on both arms — a judged
clause is vacuously true on an unjudged run.

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
