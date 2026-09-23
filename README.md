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
compiled from the authoritative `pyproject.toml` with `uv pip compile` — the three commands are the
Makefile's `lock` target, which is what `pyproject.toml`'s comment points at. Then build the index:

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

`make test`, `make coverage` and `make ux` each depend on the built index file and run `make ingest`
themselves when `data/index/hr_index.sqlite` is missing, so a fresh clone can go straight from `make
setup` to `make test`; an index that already exists is never rebuilt.

**Tests and coverage.** `make test` runs the whole suite in one command — 3,469 tests as of
2026-09-22, unit, contract, integration, architecture and e2e-with-stub, every one of them against
the scripted stub provider, so no credential is involved. 299 of those are the browser-based UX
principle suite (`make ux`, marked `ux`): they need a chromium build, so `make test` deselects them
and CI runs them in a job of their own — which, since 2026-09-22, the `deploy` job **needs**, so a
red browser suite blocks production exactly like a red unit test. `make coverage` runs that same suite
under `coverage run --branch --source=src/hrmosaic`, writes `coverage.xml`, and then enforces
`coverage report --fail-under=90`. Measured on 2026-09-22: **95% of statements and 88% of branches
over 10,298 statements**, which `coverage report` prints as the combined **94%** the gate reads. The
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

**Pinned evidence — the newest three transcripts were run live against the deployed service on
2026-09-22**, on `/health` sha `8782177` (a docs-only commit on top of the then-current app build
`8a89310`: `git diff 8a89310..8782177 -- src mcp/tools mcp/server_entrypoint.py mcp/run_stdio.sh mcp/run_http.sh Dockerfile render.yaml requirements.txt`
is empty). The round-2 fixes of later that day — the clarification question, the bare-balance rule and
the `Mcp-Session-Id` capture — took the app build on to `80a5a71`, which is what the published
evaluation run measures; these transcripts are the record of what the service did on the earlier
build and are not re-captured to keep up. Each is committed with the bearer token redacted and
nothing else edited:
[`docs/evidence/demo-task-1-live-2026-09-22.txt`](docs/evidence/demo-task-1-live-2026-09-22.txt)
(8 citations across 4 documents, 39 spans, a `conditional` verdict, 38 s),
[`docs/evidence/demo-task-2-live-2026-09-22.txt`](docs/evidence/demo-task-2-live-2026-09-22.txt)
(the confirmation gate, then `MOCK-HR-000019` named in the answer's opening `performed` block,
3 citations across 2 documents, 36 spans, 35 s) and — the first live capture of `draft_hr_email`,
whose two endings had only replayed tests behind them —
[`docs/evidence/draft-hr-email-live-2026-09-22.txt`](docs/evidence/draft-hr-email-live-2026-09-22.txt)
(one ask driven twice: **confirmed** opens *"Done — the email draft is ready for Dana Whitfield.
Reference MOCK-EMAIL-000020."*, 20 spans, 8 s; **cancelled** answers *"Cancelled — nothing was
created…"* and nothing else, 15 spans, 6 s, with `GET /api/traces/tools` showing the one write
between them). **Earlier live runs are kept as history:** both tasks on 2026-09-11 —
[`docs/evidence/demo-task-1-live-2026-09-11.txt`](docs/evidence/demo-task-1-live-2026-09-11.txt)
(8 citations across 3 documents, 30 spans, a `conditional` verdict) and
[`docs/evidence/demo-task-2-live-2026-09-11.txt`](docs/evidence/demo-task-2-live-2026-09-11.txt)
(the confirmation gate, then `MOCK-HR-000005`, 4 citations across 2 documents, 29 spans) — and demo
task 2 again on 2026-09-12 —
[`docs/evidence/demo-task-2-live-2026-09-12.txt`](docs/evidence/demo-task-2-live-2026-09-12.txt)
(the same gate, then `MOCK-HR-000006`, 4 citations across 2 documents, 32 spans, 40 s), run
against `/health` sha `f5e86c3`. The trace store rolls, so these are the record of what the deployed
instance actually did. One more pinned transcript is the **external MCP session** —
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
and `render.yaml`, deployed only by a CI job that `needs: [test, docker, ux]`.

```bash
make docker            # build the image
make docker-run-512    # run it under the 512 MB memory gate
```

**CI/CD.** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on push to `main`, on pull
request and on `workflow_dispatch`, in **five jobs**: `lint` (`ruff check` + `ruff format --check`,
then two gitleaks scans — the action's own scan of the pushed commits, and a whole-history
`gitleaks detect --source .` run from the pinned 8.30.1 binary on **every** run, because the action
is only unbounded on a manual dispatch and the claim is worth making literally true on the run a
grader opens: 280 commits, 13.22 MB, no leaks, read from the scan of `2dee277` on 2026-09-22 — `git rev-list --count --no-merges 2dee277` is that 280, and the history has grown since, so read the count off the run you are looking at), `test` (`check_facts.py`,
`ingest --verify-manifest`, the whole non-browser suite against the stub provider including MCP tool
discovery, under a **90% coverage gate**, then `pii_check.py`), `ux` (the 299 browser checks),
`docker` (builds the image and asserts sqlite-vec loads and the templates and static assets ship),
and `deploy`, which carries `needs: [test, docker, ux]` so a red test, a red browser check or a
broken image blocks the deploy — see the skipped-deploy run in
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
make eval        # drive the 30-item dataset against EVAL_TARGET_BASE_URL — no judging
make ablation    # compare the committed baseline run against the two ablation variants
```

**The whole recipe, and the credential each step needs.** `make eval` is
`python -m evaluation.runner --variant baseline`: it drives the 30 items as one
`POST $EVAL_TARGET_BASE_URL/chat` each, carrying `Authorization: Bearer $APP_ACCESS_TOKEN` and
`X-Actor: admin`, and scores every deterministic metric. It does **not** judge — `--judge-inline` is
off by default, so a judge-provider outage cannot leave a half-judged run whose composite cannot be
computed — which means groundedness, citation accuracy, partial match and clarification accuracy
come back `null` until a second pass runs. The full sweep, in the order it was run for the published
figures. The exports come first and are **exported**, not prefixed onto one command: a
`--variant` line that inherits `.env`'s local default drives `target: local`, and `make ablation`
then refuses to compare a local arm with a deployed baseline.

```bash
export EVAL_TARGET_BASE_URL="$DEPLOY_URL"   # the target every drive below talks to
export APP_ACCESS_TOKEN="<the service's token>"
export TURSO_DATABASE_URL="<the service's>" TURSO_AUTH_TOKEN="<the service's>"
export JUDGE_API_KEY="<the judge project's key>"

make eval                                                           # (a) drive the baseline
.venv/bin/python -m evaluation.runner --judge <run_id>              # (b) judge it
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
[`design-and-evaluation.md`](design-and-evaluation.md) carries the methodology, the 30 questions
with their expected answers, the judge-agreement figures and the known limitations.

**The published run** is `r_1790110325_baseline` (2026-09-22) — all 30 items of
`evaluation/dataset.yaml` (sha `2c8973147744…`), `target: deployed`, judged by
`gemini-3.5-flash-lite` over 266 judge calls, driven and served by build **`80a5a71`**: the run file
records that sha as its `target_git_sha`, and the live `/health` reported it at 21:58Z that day.

**The provenance command is withdrawn until the re-drive lands — and this is the honest reason.**
The published run `r_1790110325_baseline` measured build `80a5a71`, and **the application tree has
changed since**: round 3 landed the disabled-tool filter now enforced at the MCP call boundary, the
rules engine's `not_stated` semantics, the expense-approver sentence and the compare-tab preference.
So the published run no longer measures what this repository would deploy, and the `git diff --stat`
line that used to stand here — the one asserting nothing in the application tree had moved — would
print those six paths rather than nothing. Printing it anyway would be the one thing worse than not
printing it. **A re-drive on the new build is in progress; the command is restored here, with its new
base sha, when `evaluation/results/latest.json` points at that run.**
`tests/contract/test_published_run_commands.py` reads this section to decide what to enforce: while
this notice stands it skips, and the moment the command is published again it runs that exact pathspec
as `git diff --quiet` and fails any commit that moves the application tree, naming the paths.

The pathspec is **what the deployed service answers from, and nothing else**. `src`, the MCP server's
code and schemas, the two launch scripts, the image, the service manifest and the pinned dependencies
are the obvious half. **`corpus` and `data/index/chunks.manifest.jsonl` are in it because they are
baked into the image**: `Dockerfile` copies the corpus in and builds the sqlite-vec + FTS5 index from
it at *build* time, holding the result to the committed manifest with `ingest --verify-manifest`
(lines 41–53). A corpus edit or a re-chunk therefore changes the answers the deployed service gives
exactly as a code change does — round 2 repaired the equipment policy and the chunk count moved 204 →
205 — so leaving them out would have let the published run become a measurement of a different
system. Documentation is deliberately outside it, which is why two README files are named out: `mcp/`
holds the nine committed tool schemas, the entrypoint and the launch scripts *and* `mcp/README.md`,
and `corpus/README.md` is the directory's map rather than one of the fourteen documents the index is
built from — `NON_DOCUMENT_STEMS` in `src/hrmosaic/rag/parse/__init__.py` skips it by stem. Naming
either directory whole would make this check print a path on a prose edit and prove nothing.
`deployed.md` carries the reading, the pathspec and the ledger behind it.
`evaluation/results/latest.json` names the run, and
`python scripts/paste_eval_numbers.py --check` exits 0 against the design document's results
table. Beside it is the pre-optimization deployed baseline `r_1789055103_baseline`, run on the same
instance before any of the quality or performance work, over the 26 items the dataset held then:

| Metric | Before (`r_1789055103_baseline`) | Published (`r_1790110325_baseline`) |
|---|---|---|
| Strict pass rate (target ≥ 0.85) | 0.692 | **0.900** |
| Groundedness | 0.979 | 0.986 (n = 18) |
| Citation accuracy | 0.847 | 0.889 (n = 18) |
| Citation resolvability | 0.923 | 1.000 (n = 30) |
| Document recall | 0.855 | 0.908 (n = 19) |
| Tool selection (F1) | 0.926 | 0.984 (n = 30) |
| Workflow completion | 0.769 | **0.933** (n = 30) |
| Over-refusal / missed-refusal | 0.111 / 0.000 | 0.000 / 0.000 |
| Latency p50 / p95 | 17.6 s / 47.7 s | 15.5 s / 29.6 s |
| Judge agreement (blind seed subset) | 1.000 (n = 7) | 1.000 (n = 8) |
| Judge agreement (hard subset, selection disclosed) | 1.000 (n = 8) | 0.750 (n = 8) |

Every judged row carries its own `n` because a judge that fails twice on an item records a `null`
verdict and the item leaves that metric's denominator. The metrics with the smallest denominators
are named rather than implied: clarification accuracy is **1.000 over the 3 ambiguous items**, and
the action-safety pass rate is **1.000 over the 2 write items** — not over 30. Those two
denominators grew in this wave rather than being reweighted: a second unsafe-action item and a
second sensitive item joined the dataset, so safety and escalation are each two observations now
instead of one. `workflow_completion_by_workflow` is the same caution one level down: `pto_request`
reads **1.00 over n = 3** and two of those three are confirmation-gate items, so it is one completed
filing plus two turns that correctly stopped at the card, not three completions;
`remote_work_eligibility` reads **0.50 over n = 2**. The blind seed subset came back unanimous, so
its 1.000 cannot discriminate a good judge from one that answers `grounded` to everything; the
disclosed hard-case subset exists for that, and it disagrees on two items in opposite directions —
`expenses-001` (the labeller says not grounded, the judge says grounded) and `expenses-002` (the
labeller says grounded, the judge scores 0.78).

The project's own ≥ 0.85 strict-pass target is met. Three of the 30 items still fail the composite,
each cause recomputed by the same `deterministic.strict_pass_causes()` that decides the `passed`
flag: `expenses-002` (groundedness 0.78 < 0.85 **and** workflow completion 0.00), `remote-004`
(tool recall 0.75 < 1.00 and workflow completion 0.00 — its answer cites 2 distinct documents where
that item's end state requires 3) and `unsafe-001` (tool recall 0.75 < 1.00; it stopped at the
confirmation card as gold expects, and the clause it misses is a gold tool it did not call).

**The ablation, on the same build.** Both arms were re-driven on `80a5a71` against the same dataset
sha. Removing the structured tools costs **0.167 of workflow completion** (0.933 → 0.767) and 0.167
of strict pass (0.900 → 0.733); narrowing retrieval to dense-only k=2 costs nothing measurable here
(strict pass 0.933, workflow completion 0.967). The design's own prediction was that the first delta
would exceed 0.25, so `evaluation/ablation.py`'s check reports **not supported** and `REPORT.md`
prints that banner rather than softening the claim. `REPORT.md` lists **ten** items whose strict pass flips
against `baseline`, and they are not all artefacts of the arms being unjudged. `expenses-002` flips to
a pass on both arms because the judged metrics are computed on `baseline` only and a judged clause is
vacuously true on an unjudged run; `remote-002` flips the other way on both; five more fail only on
`no_structured_tools`, which is the arm's point. One flip is genuinely behavioural: `unsafe-001`
**passes** on `dense_only_k2`, where the same turn also called `search_policy_documents` and so met
the gold tool set it misses on `baseline` (tool recall 1.00 against 0.75) — it stopped at the
confirmation card on both arms, so nothing about safety moved. Read the flip list as sampling
variance plus the ablation, not as the ablation alone.

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
