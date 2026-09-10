# Mosaic HR Copilot — Implementation Roadmap (v2)

**Project:** `quantic-mosaic` · Quantic "AI Engineering Techniques and Architectures"
**Date:** 2026-09-09 · **Status:** ready for autonomous execution
**Source of design truth:** [`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`](../specs/2026-09-08-hr-agentic-rag-design.md) (v2)
**Traceability:** [`docs/requirements-traceability.md`](../../requirements-traceability.md)

> The **execution plan**, not the design: every "what" and "why" lives in the spec; this file answers **in what order**, **proved by which command**,
> **by whom**, and **what the human must do and when**. Where the two appear to disagree, **the spec wins** and this file is corrected. The spec's
> design rule binds here too — so there is no step-ownership table, no branch protection, no frozen clock, no CI job that writes to the repo, and no
> phase whose definition of done names an artifact a later phase produces (spec §21 row 43, §22).

---

## 1. Executive summary

1. Build **Mosaic HR Copilot**: a deployed, free-tier, agentic HR assistant for the fictional *Mosaic Robotics, Inc.* — policy RAG over a
   14-document / ~63-page corpus in four formats, plus an agent that plans, calls **9 real MCP tools** over real JSON-RPC, and cites resolvably.
2. One Python 3.12 process, one container, one Render free web service: FastAPI + Jinja/htmx UI, orchestrator, MCP client, an **in-process-mounted
   Streamable-HTTP MCP server** (plus stdio and remote `MCP_SERVER_URL`), a read-only sqlite-vec + FTS5 index, committed mock data, a Turso trace store.
3. The **trace/audit model is built first (P1), before anything that can log** — one writer (`core/trace.py`), five readers (`/chat`'s `trace[]`, the
   SSE rail, the 11-page dashboard, the eval scorers, the demo narration), kept true by one grep-based conventions test.
4. Safety is **architectural, not prompted**: a mock write needs a random one-time `confirmation_token`, minted only in `web/` after a human click and
   validated **inside the MCP server** against the exact tool name and arguments — ~60 lines, three unit tests, one integration test.
5. Six guardrails (evidence gate · citation resolvability · fact-vs-recommendation · injection shield · sensitive escalation · redaction), each a pure
   function emitting a `guardrail` span, each with a unit test.
6. The corpus is **authored directly and committed**; `corpus/facts.yml` indexes ~40 facts with verbatim quotes and one test asserts every quote still
   appears in its document — which is what keeps gold answers, compliance rules and corpus prose from contradicting each other.
7. **No frozen clock:** real wall clock everywhere, employee data carrying an explicit `as_of: 2026-09-01` snapshot, and absolute dates in every eval
   question and demo prompt, so gold answers never rot.
8. A 26-item evaluation over all six metric families, a 3-variant ablation plus a zero-LLM chunk-size comparison, and judge validation by **agreement
   rate on 8 independently-labelled items**. It runs via `make eval`; the **main session** commits results — no CI job writes to the repo.
9. **P0–P9 build and pass CI with zero API keys** (`StubAdapter`). CI is one workflow, four jobs (`lint`, `test`, `docker`, `deploy`); `test` runs the
   whole pytest suite offline apart from the cached embedding model; `deploy` is gated `needs: [test, docker]`, Render auto-deploy off, red run recorded.
10. Thirteen phases (P0–P12), ≈ 50 agent-hours, each ending green, committed and independently demoable.

---

## 2. How execution is organised

### 2.1 Roles

| Actor | Does |
|---|---|
| **Main session** (this session) | Reads the spec sections, writes the phase brief, dispatches subagents, reviews diffs, runs the acceptance gate, **commits**, updates `CHANGELOG.md` and `NEEDS-FROM-USER.md`, and commits eval results. |
| **Opus subagent** (`model: "opus"` on every Agent / Workflow call, per `CLAUDE.md`) | Implements one phase or sub-phase. Reads the spec sections named in its brief plus `mcp/README.md` where relevant. **Never commits.** |
| **Human (Sean)** | Only the gates in §5 — five sub-10-minute pastes plus the demo recording and submission. Everything else is scripted. |

### 2.2 The standing subagent brief (prepended to every phase dispatch)

```
Read docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md sections: <list>.
That spec is authoritative; do not redesign. Implement exactly what it specifies.
Write ONLY the files named in your deliverables list. Never commit; never touch .git.
Every span write goes through core/trace.py. Real wall clock everywhere: there is no clock module and
no NOW_OVERRIDE; date-bearing data computes against the mock_data `as_of` snapshot.
Add tests to the existing suite under tests/; do NOT edit .github/workflows/ci.yml unless your
deliverables say so (job `test` already runs the whole suite with `pytest -q`).
Run the acceptance commands yourself and paste the real output; never claim green without it.
If the spec is ambiguous, take the simplest reading that satisfies the requirements and list the choice in your
report. STOP and report only when the ambiguity would change a user-facing contract (/chat or /health JSON,
an MCP tool schema, a dashboard route) or when a definition-of-done command cannot pass as written.
Scratch work goes in the scratchpad directory, never in the repo.
```

### 2.3 Standing acceptance criterion (from P4 onward)

> *The expected spans were persisted, with the expected kinds and payload shapes.* — checked in every phase gate from P4 on; it is what stops a later
> subagent inventing a parallel logging path, the failure USER.4 forbids.

### 2.4 Commit message pattern

Every phase commits with:

```
P<n>(<scope>): <what landed>

- <one bullet per deliverable>
Gate: <the exact command(s) that proved it> — green
Reqs: <comma-separated requirement ids from docs/requirements-traceability.md>

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RnJs3hSPUc8kca4BtF5oAM
```

Scopes: `skeleton`, `core`, `corpus`, `mockdata`, `rag`, `mcpserver`, `llm`, `agent`, `web`, `dashboard`, `eval`, `deploy`, `docs`. Sub-phases use
`P9a(dashboard):` etc. Fix-ups inside a phase reuse the scope with a `fix:` prefix on the subject. Results commits use `P11(eval): published run`.

### 2.5 Size key

| Size | Agent-hours | Phases |
|---|---|---|
| **S** | ≤ 2 h | P0, P3 |
| **M** | 3–4 h | P1, P2, P4, P6, P8, P11, P12 |
| **L** | 5 h | P5, P7, P9, P10 |

Per-phase estimates are spec Appendix A's and sum to **≈ 50 agent-hours** (2+4+4+2+4+5+3+5+4+5+5+3+4). ⚠ **"Agent-hours" means attention, not elapsed
time**, and the two diverge in exactly one place: **P11 carries ≈ 2.5 h of additional *unattended* wall-clock** — ~560–710 sequential provider calls
behind a 10 RPM token bucket, three `cold_probe` re-runs each preceded by `EVAL_COLD_IDLE_S = 1000 s` of idling, plus provisioning and two Docker gate runs.

---

## 3. Phase dependency graph

```
P0 skeleton+CI → P1 core/ (trace FIRST) ─┬─ P2 corpus  ∥  P3 mock data ─┬─ P4 rag/  ∥  P6 core/llm/ ─┐
                                         └─────────────────────────────┘   (P5 needs P3+P4)         │
P5 mcpserver/ ← ┘   →   P7 agent/ (needs P5+P6)  →  P8 web/  →  P9 dashboard (needs P1+P8)  ────────┘
   →  P10 evaluation (needs P8, +P9 for the eval pages)  →  P11 deployment (needs P9+P10)  →  P12 docs + demo prep
```

**Parallelisable pairs:** `P2 ∥ P3` (two subagents, no shared files) and `P4 ∥ P6` (`rag/` and `core/llm/` share nothing). P9 splits internally into
`9a → 9b ∥ 9c`. Everything else is strictly sequential because each phase's gate consumes the previous phase's artifacts.

**The one cross-edge inside `P2 ∥ P3`:** `test_pto_balance_arithmetic` asserts each employee's `accrual_rate_days_per_month` equals the `corpus/facts.yml`
entry named by `accrual_fact_key`. P3 writes the test and the data; the main session runs that one file once P2 has also landed. No separate join gate,
no `--accrual-bands` mode.

**How CI grows.** P0 lands `.github/workflows/ci.yml` with jobs `lint` and `test` in their final shape apart from three data steps whose scripts do not
exist yet: **P2** adds `python scripts/check_facts.py`, **P3** adds `python scripts/pii_check.py`, **P4** adds `python -m hrmosaic.rag.ingest
--verify-manifest`, and **P11** adds the `docker` and `deploy` jobs with the `Dockerfile` and `render.yaml`. That is four one-line edits by the phase
that creates the artifact — not a step-ownership table (spec §22 row 14). Every phase's tests reach CI with no workflow edit at all, because the `test`
job's test step is `pytest -q` over the whole suite.

---

## 4. Build phases

> Every phase ends: gate green → main session reviews the diff → `CHANGELOG.md` line → **commit** → `NEEDS-FROM-USER.md` refreshed. `git status` is
> clean at every boundary (USER.5), and every definition of done below references **only artifacts that exist at that phase**.

### P0 — Skeleton + CI · **S** (2 h) · deps none · ∥ none · no key · commit `P0(skeleton): …`

**Goal.** A repository that lints, tests on an empty suite, and runs CI green on **push and pull request** from commit one.

**Scope.** `pyproject.toml`, `requirements{,-dev}.txt`, `.python-version`, `Makefile`, `.env.example`, `.gitignore`, `.dockerignore`, `README.md`,
`NEEDS-FROM-USER.md`, `CHANGELOG.md`, `.github/workflows/ci.yml`, `src/hrmosaic/settings.py`, `src/hrmosaic/rag/download_model.py`,
`scripts/vendor_assets.py`, `src/hrmosaic/web/static/`, `tests/architecture/test_conventions.py`,
`tests/contract/{test_env_example_covers_settings,test_readme_headings}.py`.

**Deliverables.**
- `settings.py` — every §12.3 variable, **structural validation at import, credential validation deferred**; the `MCP_SERVER_URL`, `GIT_SHA`,
  `LLM_BURST` and `mcp_transport_effective` validators; a 3.12 *warning* that never crashes. `.env.example` mirrors it field for field with
  `# REQUIRED`/`# OPTIONAL`, defaults and signup URLs — and no `SEED`, `NOW_OVERRIDE` or OTEL variable.
- `Makefile`: `setup run run-stdio lint test ingest eval ablation demo1 demo2 docker docker-run-512`. `.gitignore` carrying `data/index/*`,
  `!data/index/chunks.manifest.jsonl`, `data/runtime/`, `.cache/`, `.env` **literally** — a trailing-slash `data/index/` would kill the negation and
  make the manifest uncommittable three phases later.
- `README.md` with its five headings (`## Setup` naming `python3.12 -m venv .venv` literally) and the three first-20-line link lines, each accepting
  `TBD-before-submission`; `rag/download_model.py` (~15 lines — the first CI run is always a cache miss, so it cannot wait for P4); `vendor_assets.py`
  fetching htmx/Alpine/Chart.js at pinned tags into `static/vendor/` and appending `{file, version, upstream_url}` to the hand-authored `LICENSES.md`
  (on a 404 it resolves the nearest release, prints `PINNED <name> <version>` and records it in `CHANGELOG.md`).
- `ci.yml` — jobs `lint` (ruff + `gitleaks` over full history) and `test` (install from the committed manifests → `actions/cache` for
  `.cache/fastembed` → `download_model` → `pytest -q`), on `push: [main]` + `pull_request` + `workflow_dispatch` (`deploy_only`), with `paths-ignore`
  for `evaluation/results/**`, `evaluation/REPORT.md`, `docs/**`, `**/*.md`. `test_conventions.py` ships all five greps, trivially green.
- **The repo is already public** (verified 2026-09-08); no visibility change is ever made by script, and **there is no branch protection** — the deploy
  gate is `needs: [test, docker]` plus `autoDeploy: false`.

**Definition of done.**
```bash
make lint && make test                                        # ruff + ruff format --check; pytest over an empty suite
python -m hrmosaic.rag.download_model && test -d "${FASTEMBED_CACHE_PATH:-.cache/fastembed}"
pytest tests/contract/test_env_example_covers_settings.py tests/contract/test_readme_headings.py -q
pytest tests/architecture/test_conventions.py -q
gh api repos/seantmalone/quantic-mosaic --jq .private         # false — already public; nothing is changed
# the four lines below are run by the MAIN SESSION after it commits P0 — never by the subagent, which touches no git
git switch -c ci-evidence && git commit --allow-empty -m "ci: pull_request evidence" && git push -u origin ci-evidence
gh pr create --base main --head ci-evidence --title "CI evidence (pull_request)" --body "Records a green pull_request run."
gh pr checks --watch && gh pr view --json url -q .url >> CHANGELOG.md && gh pr close ci-evidence --delete-branch
gh run list --limit 5                                         # green on BOTH push and pull_request (RUBRIC5.7)
```

### P1 — `core/`: the trace store, built before anything that can log · **M** (4 h) · deps P0 · ∥ none · no key · commit `P1(core): …`

**Goal.** The Session → Turn → Span audit model, its two backends and its readers' entry points exist before any component can emit a record.

**Scope.** `src/hrmosaic/core/`: `db.py` (`SqliteStore` + `TursoHTTPStore` behind one `execute`/`batch` interface), `migrations/00N_*.sql` (the whole
§10.1 schema, `sessions.auth_mode` and `sessions.actor_role` included — both `NOT NULL` with their `CHECK` vocabularies, so P8 and P9 have the columns
they render and filter on), `trace.py`, `models.py`, `redact.py`, `ids.py`, `procstat.py`, `archive.py`, `retention.py`; `tests/fixtures/traces/`;
`tests/fixtures/eval_runs/sample_run.json`.

**Deliverables.**
- `trace.py` — the writer, the buffered turn lifecycle (one small batch at turn start, one batched flush at turn end), `register_span_listener()`,
  `reopen_turn(turn_id, awaiting_ms)`, `install_shutdown_handlers()` / `flush_open_turns()` / `sweep_stale_turns()`, and the closing `UPDATE` that
  samples `turns.rss_mb_at_end`.
- `models.py` — the `payload_json` union on `kind`, the view-models, `strict_json_schema()`, `MODEL_PRICES`; `redact.py` — key-name denylist, value
  regexes, the `os.environ` sweep, the preserved token counts; `ids.py` — `secrets` ids plus `SEED = 1729` (no env var).
- `archive.py` — the idempotent boot importer for `evaluation/results/*.json` keyed on `import_state.sha256`; `retention.py` — the cascading sweep that
  never prunes an eval-linked, `eval_judge` or `maintenance` session.
- `tests/fixtures/traces/` — ≥ 2 hand-authored golden traces, one carrying a complete confirmed-write chain (`confirmation` span + `confirmations` row
  + `mock_writes` row) with `llm_messages` for every `llm_call`. The single home for golden traces.

**Definition of done.**
```bash
pytest tests/unit/test_store_parity.py -q              # identical results from both backends (Turso via httpx MockTransport)
pytest tests/unit/test_g6_redact.py -q                 # leaked values scrubbed AND prompt/completion/total_tokens survive
pytest tests/unit/test_span_listener.py tests/unit/test_ids_unique.py -q
pytest tests/unit/test_retention.py tests/unit/test_turn_close_records_rss.py -q
pytest tests/integration/test_results_import.py -q     # idempotent; re-imports a changed file; skips an unchanged one
pytest tests/integration/test_process_exit_mid_turn.py -q      # store-level form (the subprocess form is P8's)
pytest tests/architecture/test_conventions.py -q       # the sole-span-writer grep now has a real target
python -m hrmosaic.core.procstat                       # paste the Linux/CI RSS value with its date into CHANGELOG.md
```

### P2 — Policy corpus · **M** (4 h) · deps P0 · ∥ P3 · no key · commit `P2(corpus): …`

**Goal.** 14 hand-authored policy documents in four formats, plus the ~40-fact index every gold answer and compliance rule cites.
**Scope.** `corpus/` (11 `.md`, 1 `.html`, 1 `.pdf` + its `.src.md`, 1 `.txt`), `corpus/{facts.yml,rules.yml,README.md}`,
`scripts/{build_pdf,corpus_stats,check_facts}.py`, `tests/unit/{test_facts_quotes,test_corpus_stats,test_corpus_topics,test_corpus_canary}.py`.

**Deliverables.**
- The 14 documents of §5.3, each with the standard header and ≥ 6 concrete checkable statements — a review criterion, not a build gate. No generator.
- `facts.yml` — ~40 entries `{id, value, unit, doc_id, section, quote}` with the quote reproduced **verbatim**; `rules.yml` — the requirements behind
  tool 4's seven scenarios, each naming a `fact_key`, `doc_id` and `heading_path`; `README.md` — the topic → document map, outlines, format rationale.
- The **injection canary** inside `security-acceptable-use.txt`, in a labelled "example of a phishing lure" section short enough to be one chunk.
- `check_facts.py` — one check: every quote verbatim, every `section` a real heading path, every `rules.yml` `fact_key` resolvable. Any phase may run
  it; **P2 adds it to `ci.yml`'s `test` job.**

**Definition of done.**
```bash
python scripts/check_facts.py                          # quotes verbatim, sections real, every fact_key resolves
python scripts/corpus_stats.py                         # 14 files · ~63 pages · md/html/pdf/txt
python scripts/build_pdf.py && test -s corpus/workplace-conduct.pdf         # generated once from .src.md, then committed
pytest tests/unit/test_facts_quotes.py tests/unit/test_corpus_stats.py -q   # band: 5<=files<=20, 30<=pages<=120
pytest tests/unit/test_corpus_topics.py tests/unit/test_corpus_canary.py -q # all 10 PD.2 topics mapped; canary < CHUNK_MAX_CHARS
```

### P3 — Synthetic mock data · **S** (2 h) · deps P0 · ∥ P2 · no key · commit `P3(mockdata): …`

**Goal.** Six committed, immutable, obviously-synthetic datasets carrying the `as_of: 2026-09-01` snapshot that stabilises every date-bearing answer.

**Scope.** `scripts/{gen_mock_data,gen_mock_schemas,pii_check}.py`, `mock_data/*.json`, `mock_data/schemas/*.schema.json`, `mock_data/README.md`,
`tests/unit/{test_mock_schemas,test_pto_balance_arithmetic,test_mock_anchor_ids}.py`.

**Deliverables.**
- The six datasets of §5.4, each with the `_synthetic` / `_notice` / `_generator` / `as_of` banner, produced by a byte-idempotent `seed=1729` generator.
- 24 non-contiguous ids from `E1001`–`E1199` with the four anchors `E1002`, `E1007`, `E1042` (the demo persona, hired 2022-11-13, 45 months tenured at
  the snapshot, **13.5 days remaining** at 1.50 d/mo) and `E1108` (hired 2026-08-15, `waiting_period_ends` 2026-11-13 — still waiting at the snapshot).
- Synthetic conventions: `@mosaicrobotics.example` addresses, `+1-555-01xx` phones, **no SSN field in any schema**, no dates of birth, no addresses.
  `pii_check.py` fails the build on any hit; **P3 adds it to `ci.yml`'s `test` job.**
- `mock_data/README.md` — the SYNTHETIC DATA banner and the `as_of` convention: what it means, why every date-bearing tool reports it, and why nothing
  computes against "today".

**Definition of done.**
```bash
python scripts/gen_mock_data.py && git diff --exit-code mock_data/          # byte-idempotent regeneration
python scripts/gen_mock_schemas.py && python scripts/pii_check.py
pytest tests/unit/test_mock_schemas.py tests/unit/test_mock_anchor_ids.py -q     # schemas valid; anchors present; E1108 still waiting
pytest tests/unit/test_pto_balance_arithmetic.py -q      # the identity holds for all 24 at the snapshot; E1042 -> 13.5
```
That last file also checks each accrual rate against `corpus/facts.yml`, so the **main session runs it once P2 has landed**; nothing else in P3 touches
P2's files.

### P4 — `rag/`: parsing, chunking, embedding, hybrid index · **M** (4 h) · deps P2 (+P1) · ∥ P6 · no key · commit `P4(rag): …`

**Goal.** A deterministic committed chunk manifest, a read-only sqlite-vec + FTS5 index built at Docker build time, and hybrid RRF retrieval.

**Scope.** `src/hrmosaic/rag/`: `parse/{md,html,pdf,txt}.py`, `chunk.py`, `embed.py`, `index.py`, `retrieve.py`, `ingest.py`;
`src/hrmosaic/core/corpusread.py`; `data/index/chunks.manifest.jsonl`; `tests/fixtures/corpus_mini/`.

**Deliverables.**
- Four parser paths with heading extraction (the PDF path's heading set equals `workplace-conduct.src.md`'s); the heading-aware chunker (1,400 max /
  1,100 window / 150 overlap / 120 min, `heading_path` joined with `" > "` **before** hashing, `chunker_version = "2026.1"`) and the committed
  `chunks.manifest.jsonl` — text and hashes, never vectors.
- `embed.py`, the only module that touches fastembed: `embed_passages()` / `embed_query()`, `batch_size=EMBED_BATCH_SIZE` (8) on every call,
  `threads=1` on construction, `parallel=` never, plus `_fake_embed()` for `EMBED_PROVIDER=fake`.
- The index (`vec_chunks` with `distance_metric=cosine`, `chunks`, `chunks_fts`, `documents`, `index_meta`), `open_index()`'s mismatch guard,
  `--selftest`, and `ingest.py --verify-manifest` (chunking only, never vectors) writing `ingest_report.json`.
- The retriever — dense k=20 + BM25 k=20 → RRF k₀=60 → score-fill from **stored** vectors → filter on `min_dense_score` → truncate to k — and
  `core/corpusread.py`, the read-only reader G2, the rules engine and the corpus browser share.
- **P4 adds `python -m hrmosaic.rag.ingest --verify-manifest` to `ci.yml`'s `test` job**, ahead of `pytest`, since index-backed tests need a real index.

**Definition of done.**
```bash
python -m hrmosaic.rag.ingest --verify-manifest        # rebuild byte-identical to the committed manifest (R1.4)
python -m hrmosaic.rag.index --selftest                # top-1 doc_id, dense >= SELFTEST_MIN_DENSE_SCORE, counts match the manifest
git check-ignore -q data/index/chunks.manifest.jsonl || echo "manifest is tracked"    # must print
pytest tests/unit/test_chunking.py tests/unit/test_chunking_deterministic.py tests/unit/test_ingest_report.py -q
pytest tests/unit/test_query_embed_is_asymmetric.py -q # record the branch taken and the fastembed version in CHANGELOG.md
pytest tests/unit/test_fake_embedder.py tests/unit/test_chunk_citation_fields.py tests/unit/test_corpusread_contract.py -q
pytest tests/unit/test_retrieval_filters.py tests/unit/test_min_dense_score_is_not_rrf.py -q
pytest tests/architecture/test_conventions.py -q       # sole embed call site; no `parallel=` under src/
```

### P5 — `mcpserver/`: nine tools and the confirmation gate · **L** (5 h) · deps P3 + P4 · ∥ none · no key · commit `P5(mcpserver): …`

**Goal.** One `build_hr_server()` factory serving nine tools over three transports, with the write gate enforced **inside** the server.
**Scope.** `src/hrmosaic/mcpserver/`: `server.py`, `asgi.py`, `tools/*.py` (nine), `confirm.py`, `rules.py`, `stdio_main.py`; `mcp/server_entrypoint.py`,
`mcp/run_{stdio,http}.sh`, `mcp/README.md`, `mcp/tools/*.schema.json`; `scripts/{gen_tool_schemas,probe_sqlite_vec}.py`.

**Deliverables.**
- The nine tools of §8.4 with input **and** output schemas and annotations, every handler `async def`, and every CPU-bound call inside
  `await asyncio.to_thread(...)` — the rule the mounted-loopback topology depends on.
- `confirm.py` (~60 lines): mint (called only from `web/` later), validate (token exists, unused, unexpired, `user_response == "confirmed"`, tool name
  matches, canonical arguments minus `confirmation_token` equal `arguments_json`), consume. The `CONFIRMATION_REQUIRED` rejection carries **no token**.
- `rules.py` — the deterministic engine resolving each requirement's `(doc_id, heading_path)` to a real `chunk_id` via `core.corpusread`; all three
  `_meta` keys (`mosaic/trace`, `mosaic/actor` — audit only — and `mosaic/retrieval`) plus `_trace` span propagation on results.
- `mcp/README.md` — transport rationale, discovery flow, the full 1.x→2.x mapping table (read **before** any MCP code is written), the `_meta`
  conventions, and what the SDK grep found about a native `Host`/`Origin` allowlist; `gen_tool_schemas.py` → `mcp/tools/*.schema.json`.

**Definition of done.**
```bash
pytest tests/contract/test_mcp_api_shape.py tests/contract/test_tools_match_spec.py -q   # the four 2.x differences; REQUIRED_TOOL_NAMES vs a LIVE tools/list
python scripts/gen_tool_schemas.py && git diff --exit-code mcp/tools/
pytest tests/contract/test_tool_schemas_committed.py -q
pytest tests/integration/test_mcp_discovery.py -q      # discovery only: initialize + tools/list >= 5 over stdio AND mounted HTTP
                                                       #   (P8 adds this file's Authorization: Bearer assertion — spec 16.4)
pytest tests/integration/test_mcp_tool_call.py -q      # check_pto_balance(E1042) -> 13.5 with as_of; search hits all resolve — both transports
pytest tests/unit/test_confirmation_gate.py -q         # missing / mismatched / reused: CONFIRMATION_REQUIRED, nothing written
pytest tests/unit/test_get_policy_section_selectors.py tests/unit/test_rules_engine.py -q
pytest tests/architecture/test_conventions.py -q       # mcp/__init__.py absent
```

### P6 — `core/llm/`: the provider abstraction · **M** (3 h) · deps P1 · ∥ P4 · key #1 (supplied) for the probe only · commit `P6(llm): …`

**Goal.** One `ChatModel` protocol with four implementations, so the agent loop is testable with zero secrets and a real provider is one env var away.

**Scope.** `src/hrmosaic/core/llm/`: `base.py`, `openai_compat.py`, `anthropic.py`, `stub.py`, `cache.py`, `limiter.py`; `scripts/probe_provider.py`;
`tests/fixtures/llm_scripts/`.

**Deliverables.**
- `OpenAICompatAdapter` (Gemini/OpenRouter/Cerebras/OpenAI — the judge, the failover and the free agent path; tool-call arguments as a JSON string,
  always `json.loads`; strict `response_format` with a prompted-JSON fallback plus one repair round-trip) and **`AnthropicAdapter` — the agent's
  adapter** (spec §9.8's allocation table): `anthropic` SDK 1.x **sync** client called as `await asyncio.to_thread(client.messages.create, …)` so it
  never blocks the single worker's event loop (spec §2.1), `timeout=25` s with `max_retries=0` — the adapter's own one-backoff-then-failover is the
  single retry layer, bounding a logical call at ≈ 52 s inside `AGENT_WALL_CLOCK_S` — `temperature=0`, **no `strict` on the tool definitions** (the
  nine published schemas keep defaults, an open `parameters` sub-schema and a root `oneOf`; arguments are validated server-side instead — spec §8.4,
  §9.8), `output_config.format` JSON schema for route/synthesize/repair (**no prompted-JSON fallback here**), dict-shaped tool inputs, no extended
  thinking, `max_tokens` 1024/2048/512, and one `cache_control {type: ephemeral}` breakpoint on the **last system block**, so the cached prefix is
  *tools → system*; verified against an httpx `MockTransport`.
- `StubAdapter` replaying `tests/fixtures/llm_scripts/*.json`, selected by the test rather than by prompt matching — the keystone of key-free P0–P9.
- `CachedAdapter` — optional, **off by default** (`LLM_CACHE_TTL_S=0`), for demo warm-up and cheap re-runs; no test asserts a cache hit and no
  committed artifact depends on one. The token-bucket limiter (capacity `LLM_BURST`, refill `LLM_RPM/60` per second), failover to `LLM_FALLBACK_*`
  (free Gemini) recorded as `provider_failover`, the `LLM_DAILY_CALL_CAP` spend guard counted from `llm_call` spans, and exactly one `llm_call` span
  plus its `llm_messages` rows per call — carrying `cache_creation_input_tokens`, `cache_read_input_tokens` and `cost_usd_estimate` from
  `MODEL_PRICES` — emitted from inside the adapter.

**Definition of done.**
```bash
pytest tests/unit/test_adapter_tool_call_shapes.py -q  # string-args and object-args normalise to the same dict
pytest tests/unit/test_strict_schema_emission.py -q    # required == list(properties), additionalProperties false, at every level
pytest tests/unit/test_limiter_burst.py -q             # 6 back-to-back calls < 50 ms of sleep; the 7th-11th pace
pytest tests/unit/test_llm_span_emission.py -q         # one llm_call span + n llm_messages rows per call; failover flag recorded
python scripts/probe_provider.py                       # live: one Haiku call with the published tools (no strict) + an output_config JSON
                                                       #   schema; a second identical call whose cache assertion
                                                       #   (cache_creation > 0 then cache_read > 0) is armed only if the tools+system
                                                       #   prefix clears Haiku 4.5's 4096-token minimum, else the measured prefix size is
                                                       #   recorded and the probe passes; one Gemini judge JSON call.
                                                       #   Outcome, measured prefix size and date -> CHANGELOG.md.
```

### P7 — `agent/`: orchestrator, guardrails, workflows · **L** (5 h) · deps P5 + P6 · ∥ none · no key · commit `P7(agent): …`

**Goal.** Route → act → synthesize, with six guardrails and two declarative workflows; the demo sequences are asserted at P8.
**Scope.** `src/hrmosaic/agent/`: `client.py`, `router.py`, `orchestrator.py`, `guardrails/{g1..g6}.py`, `workflows/{remote_work,pto_request}.py`,
`prompts/{route,act,synthesize}.j2`; `tests/e2e/test_rag_only_makes_no_people_calls.py`.

**Deliverables.**
- `orchestrator.run_turn(req)` and `resume_turn(session_id, turn_id, confirmation_token)` — the two entry points `web/api.py` calls at P8, with
  `resume_turn` rehydrating from that turn's persisted `llm_messages`, `retrieval` and `tool_call` spans rather than re-retrieving.
- The MCP client: cached handshake but **one `mcp_discovery` span per turn**; the catalog → OpenAI-function conversion that *is* the model's tool
  array; `_meta` attachment; and the stripping of any model-supplied `confirmation_token`.
- The router gate (`intent == "policy_qa"` ⇒ tools 1–4 only) with the one-step `catalog_reopened` recovery path; guardrails G1–G6 as pure functions,
  each emitting a span, with G4's scoped patterns and G1's refusal reading `core.corpusread` so an out-of-scope turn makes **zero** tool calls.
- Both workflow specs, whose completion predicates require a structured-data tool result; the three Jinja prompts with the frozen prefix ordering; and
  the prompts' frozen prefix ordering. `DEMO_EXPECTATIONS` and its e2e test are P8's, the phase whose `/chat/confirm` can make demo 2 pass.

**Definition of done.**
```bash
pytest tests/unit/test_g1_evidence_gate.py tests/unit/test_g2_citation_resolvability.py tests/unit/test_g3_fact_vs_rec.py -q
pytest tests/unit/test_g4_injection.py tests/unit/test_g4_no_false_positives.py tests/unit/test_g5_sensitive.py -q   # the middle one runs over the whole manifest
pytest tests/unit/test_confirmation_token_stripped.py tests/contract/test_prompt_golden.py tests/contract/test_no_chain_of_thought.py -q
pytest tests/e2e/test_rag_only_makes_no_people_calls.py -q            # zero non-RAG tool calls on a pure policy question
pytest tests/architecture/test_conventions.py -q                      # agent/ imports no hrmosaic.mcpserver
```

### P8 — `web/`: `/chat`, `/chat/confirm`, SSE, `/health`, chat UI · **M** (4 h) · deps P7 · ∥ none · no key · commit `P8(web): …`

**Goal.** The contract endpoints, the confirm→write path, and a chat UI a grader can drive in one click.
**Scope.** `src/hrmosaic/web/`: `main.py`, `api.py`, `sse.py`, `templates/`, `static/app.css`; `scripts/demo_task_{1,2}.sh`; the four
`tests/integration/test_fault_*.py` files; `tests/e2e/test_demo_tasks.py` with its two `DEMO_EXPECTATIONS` records.

**Deliverables.**
- **The access gate and the two personas (spec §11).** `APP_ACCESS_TOKEN` presented as `?access=` (302 back to the same URL with the parameter
  stripped, after setting the HttpOnly `mosaic_access` cookie), as that cookie, or as `Authorization: Bearer`, compared with `secrets.compare_digest`;
  the key page `GET`/`POST /access` and `POST /access/logout`; `POST /session/actor` for the act-as selector; the admin persona (`mosaic_actor` /
  `X-Actor`) required for the privileged `/chat` options; the per-IP `ACCESS_RATE_LIMIT_PER_MIN` on `POST /chat` and the MCP mount; the fifth
  `degradations[]` string `access_token_missing`; `sessions.auth_mode` / `actor_role` written on every session.
- `POST /chat` (client-suppliable ids, the privileged-`options` matrix failing closed outside the admin persona, the four rubric-named top-level fields, and
  `trace[]` as the projection of **all** the turn's spans); `POST /chat/confirm` — **the only place a token is minted** — then `trace.reopen_turn` →
  `resume_turn`; `GET /chat/stream` with one listener registered in the lifespan; `GET /health` (always 200, the five-string `degradations[]`);
  `GET /ready` (503 until the model and index are resident, warmed by one loopback `tools/call`); and `GET /api/traces/turns/{turn_id}`.
- The chat UI: act-as selector over the 24 employees **plus HR admin** (default `E1042`, setting `mosaic_actor`; the dashboard nav link appears only
  in the admin persona), typed answer blocks with the "Recommendation — not company policy" badge, citation chips linking to
  `source_url`, the snapshot note under any `as_of`-bearing result, the live SSE rail, the Confirm/Cancel card, the cold-start banner, the two demo
  buttons; plus `demo_task_{1,2}.sh` — plain `curl`, parameterised by `BASE_URL` and sending `Authorization: Bearer $APP_ACCESS_TOKEN` on
  every call; their chat calls stay in the default employee persona, and the `GET /api/traces/turns/{turn_id}` poll of the 202 fallback — the one
  admin-only route they touch — additionally sends `X-Actor: admin`.
- **All four fault-injection files, authored once here**, each asserting the orchestrator behaviour *and* HTTP 200 — no phase owns half a file.
- **The one assertion P8 adds to `tests/integration/test_mcp_discovery.py`** (P5's file, discovery only until now): with the gate on, the in-process
  MCP client sends `Authorization: Bearer` on `tools/list` and on every `tools/call` (spec §16.4).

**Definition of done.**
```bash
pytest tests/contract/test_app_starts.py tests/contract/test_chat_page_renders.py tests/contract/test_health.py tests/contract/test_lifespan.py -q
pytest tests/contract/test_chat_contract.py tests/contract/test_chat_trace_projection.py -q   # RAG-only AND tool-using; the 7-row R4.3/R4.1 table; trace == spans-of-turn
pytest tests/contract/test_chat_privileged_options.py tests/contract/test_missing_key_is_graceful.py -q
pytest tests/contract/test_access_gate.py tests/contract/test_personas.py -q   # 401 + key page; ?access= -> 302 + Set-Cookie + stripped URL; cookie
                                                                              #   and bearer -> 200; /health + /ready open; APP_ENV=render with no
                                                                              #   token -> 403 + access_token_missing; /dashboard/* 403
                                                                              #   ADMIN_REQUIRED without admin, and 200 as X-Actor: admin on
                                                                              #   GET /api/traces/turns/{turn_id} (the dashboard pages are P9's,
                                                                              #   where test_dashboard_pages asserts 200-as-admin); /session/actor
pytest tests/integration/test_fault_mcp_down.py tests/integration/test_fault_unknown_employee.py \
       tests/integration/test_fault_empty_retrieval.py tests/integration/test_fault_ambiguous.py -q
pytest tests/integration/test_health_mcp_down.py tests/integration/test_sse.py tests/integration/test_mcp_remote_url.py -q
pytest tests/integration/test_mcp_discovery.py -q       # re-run for P8's bearer assertion on tools/list and every tools/call
pytest tests/integration/test_confirm_resume_lifecycle.py -q          # decline -> re-ask -> confirm; two turn rows (the declined turn, then the
                                                                      #   re-asked turn reopened on confirm); exactly one mock_writes row
pytest tests/integration/test_audit_completeness.py tests/integration/test_process_exit_mid_turn.py tests/unit/test_action_safety.py -q
pytest tests/e2e/test_demo_tasks.py -q                 # both sequences under the stub; demo 2 through confirm -> write
make demo1 && make demo2                               # each target starts its own server with its own LLM_STUB_SCRIPT
```

### P9 — Observability dashboard, 11 pages · **L** (5 h) · deps P1 + P8 · ∥ 9b ∥ 9c · no key · commits `P9a/P9b/P9c(dashboard): …`

**Goal.** USER.2 and USER.3 in full: every session, turn, LLM call, retrieval, tool call, guardrail and confirmation browsable, eval views included.

**Scope.** `src/hrmosaic/web/dashboard.py`, `web/templates/dashboard/`, the `/api/*` layer, `tests/fixtures/eval_runs/` (one run JSON per variant).
**9a** — the `/api/*` endpoints, the shared table + filter-bar partials, and **page 3 (session detail) first**, the centrepiece the demo depends on.
**9b** — pages 1, 2, 4–8. **9c** — pages 9 (MCP), 10 (corpus), 11 (evals: list, detail, compare tab, metrics tab). 9b ∥ 9c once 9a lands.

**Deliverables.**
- All 11 pages of §11.6, each rendering from the typed Pydantic view-model produced by the same `/api/*` endpoint that serves its JSON, each with an
  Export JSON button; Chart.js on pages 1, 8 and 11.
- Page 11's metric block, with the four judged aggregates typed `Optional[float]` beside `judged: bool` and `n_scored{}` — never fabricated zeros —
  and the deterministic metrics non-null on every variant.
- **The whole dashboard is admin-only**, reads included — every page and every `/api/traces\|eval\|corpus\|mcp/*` endpoint returns **403**
  `{"code": "ADMIN_REQUIRED"}` outside the admin persona, on top of P8's access gate; pages 1 and 2 show and filter on `auth_mode` and `actor_role`.
- The three admin-only write controls on their stated pages: **Reset sandbox** (8), **Re-discover now** (9, opening a synthetic `maintenance` session
  for its span), **Run smoke eval** (11, bounded by `EVAL_SMOKE_MAX_ITEMS`). They are never dead: reaching the host page already proves the persona.
- `tests/fixtures/eval_runs/` — one committed run JSON per variant, so page 11's tabs are built and tested before P10 has run anything.

**Definition of done.**
```bash
pytest tests/contract/test_dashboard_pages.py -q       # 11 pages 200 + key selectors as admin; 403 ADMIN_REQUIRED without the admin persona;
                                                       #   the three write controls wired; auth_mode / actor_role on the session rows
pytest tests/contract/test_dashboard_viewmodels.py -q  # every /api/* payload validates; the judged/n_scored contract; deterministic metrics non-null
# the bounded smoke-eval endpoint ships here, importing evaluation.runner lazily; its test is P10's (runner.py is a P10 deliverable)
```

### P10 — `evaluation/`: dataset, scorers, judges, ablation · **L** (5 h) · deps P8 (+P9 for the views) · ∥ none · **key #1** (supplied) · commit `P10(eval): …`

**Goal.** A 26-item harness whose deterministic scorers run offline, whose judged metrics state their `n`, and whose three variants are proved locally
before anything is published.

**Scope.** `evaluation/`: `dataset.yaml`, `schema.py`, `deterministic.py`, `judges.py`, `runner.py`, `ablation.py`, `reference_labels.yaml`, `results/`,
`REPORT.md`; `scripts/{chunk_size_sweep,gen_ablation_evidence}.py`. **Step 0:** read the live Gemini judge RPM/RPD/TPM **and the Anthropic
`claude-haiku-4-5` prices** (§3.1) and paste them with the date into `deployed.md`, and export `APP_ACCESS_TOKEN` — the runner sends
`Authorization: Bearer $APP_ACCESS_TOKEN` and `X-Actor: admin`, and every eval item's privileged `/chat` options fail closed outside the admin persona.

**Deliverables.**
- `dataset.yaml` — 26 items in fixed file order (7 `simple_policy`, 5 `multi_doc`, 6 `tool_task`, 3 `ambiguous`, 3 `out_of_scope`, 1 `unsafe_action`,
  1 `sensitive`), **absolute dates only**, gold facts citing `corpus/facts.yml` keys, and the two workflow mirrors `remote-004` and `pto-003`.
- The deterministic scorers with every §13.3/§13.4 edge case; the four judge prompts; the runner (sequential, limiter-backed, warming the target before
  item 1, three `cold_probe` re-runs that assert `process_uptime_ms < 60000` before tagging cold); `ablation.py`; the zero-LLM chunk-size sweep.
- `reference_labels.yaml` — 8 items selected with `SEED`, groundedness labels authored by a **separate Opus subagent blind to the judge's output**,
  with a `protocol` block naming the labeller, the date and the blinding. `judge_agreement_rate` is published with its n. No κ.
- `MIN_EVIDENCE_SCORE` calibrated from the observed score distribution; one **real** exchange per demo task recorded as a stub script; the first real
  runs at `target: local`, all three variants — plumbing and determinism evidence, never promoted to `latest.json`.

**Definition of done.**
```bash
pytest tests/unit/test_dataset.py -q                   # every §13.1 clause: counts, five expected_behavior classes, inj-001, no relative dates, probe ids
pytest tests/unit/test_scorer_edge_cases.py tests/unit/test_cold_probe_excluded.py -q          # green offline against tests/fixtures/traces/
pytest tests/unit/test_reference_subset_deterministic.py tests/unit/test_latest_points_at_deployed.py -q
make eval && python -m evaluation.runner --variant dense_only_k2 && python -m evaluation.runner --variant no_structured_tools
make ablation                                          # same target + dataset_sha; the workflow-completion delta, or REPORT.md's not-supported banner
python scripts/chunk_size_sweep.py && python scripts/gen_ablation_evidence.py
pytest tests/integration/test_smoke_eval_endpoint.py -q # 403 ADMIN_REQUIRED in the employee persona; a 1-item bounded run as admin
pytest tests/unit/test_action_safety.py tests/contract/test_dashboard_viewmodels.py -q         # over the real traces; refreshed fixtures still validate
grep -n 'judge_agreement_rate\|judge_agreement_n' evaluation/REPORT.md
ls evaluation/results/                                 # three <run_id>.json, comparison.json, chunk_size_comparison.json — and NO latest.json yet
```

### P11 — Deployment and the published run · **M** (3 h attention, ≈ 2.5 h unattended) · deps P9 + P10 · ∥ none · **keys #2, #3, #4** · commit `P11(deploy): …`

**Goal.** A live free-tier URL with the deploy genuinely gated on tests, and the one `deployed`-mode run every published figure comes from.

**Scope.** `Dockerfile`, `render.yaml`, the `docker` and `deploy` jobs in `ci.yml`, `scripts/{provision_render,provision_turso,wait_for_deploy,
wait_for_health,smoke_deployed,assert_health,measure_cold_start,check_render_hours}.py`, `docs/evidence/*.png`, `deployed.md`. **Step 0:** re-read and
date every §3.1 row naming a live source (spec Appendix A, P11 step 0).

**Deliverables.**
- The Dockerfile of §14.2 (model baked, index built at build time, `sh -c` so `${PORT}` expands) and `render.yaml` with `autoDeploy: false`,
  `healthCheckPath: /health` and every `sync: false` secret.
- The `docker` job (build → `probe_sqlite_vec.py` inside `python:3.12-slim` → run → `wait_for_health` → `assert_health`) and the `deploy` job
  (`needs: [test, docker]`, `if` push-to-`main`, curl the deploy hook → `wait_for_deploy` → `smoke_deployed`).
- Unattended provisioning: the Turso database and scoped token, the Render service, every env var, the deploy hook, and `gh secret set` for
  `RENDER_DEPLOY_HOOK_URL`, `DEPLOY_URL`, `RENDER_API_KEY`. `provision_render.py` generates `APP_ACCESS_TOKEN` with `secrets.token_urlsafe(32)` and
  sets it on Render — no user step — and the full tokenized link `https://<app>.onrender.com/?access=<token>` goes into `README.md`'s `Deployed:` line
  and `deployed.md`'s `## Access`. The deployed eval run fails closed without the token and `X-Actor: admin`.
- **The published run:** `make eval` and `make ablation` against the live URL, all three variants, `baseline` judged, the three cold probes included,
  committed by the main session with `latest.json`, `comparison.json` and `REPORT.md`; plus the three evidence screenshots and the R8.4 red-run pair.

**Definition of done.**
```bash
make docker-run-512                                    # docker run -m 512m with APP_ACCESS_TOKEN set (APP_ENV stays local): /ready green,
                                                       #   one stubbed POST /chat over Authorization: Bearer, /health.app.rss_mb < 420
docker run --rm -d -e PORT=10000 -e LLM_PROVIDER=stub -p 10000:10000 mosaic-hr && python scripts/assert_health.py --url http://127.0.0.1:10000
python scripts/provision_turso.py && python scripts/provision_render.py
python scripts/smoke_deployed.py --url "$DEPLOY_URL"   # bearer header; 200; mcp.connected; git_sha != "dev"; /health lists no access_token_missing
EVAL_TARGET_BASE_URL="$DEPLOY_URL" make eval
EVAL_TARGET_BASE_URL="$DEPLOY_URL" python -m evaluation.runner --variant dense_only_k2
EVAL_TARGET_BASE_URL="$DEPLOY_URL" python -m evaluation.runner --variant no_structured_tools
EVAL_TARGET_BASE_URL="$DEPLOY_URL" make ablation                       # ablation.py only compares runs that already exist
jq -r '.target, .variant' evaluation/results/latest.json                # deployed  baseline
jq -r '.target, (.variants[].variant)' evaluation/results/comparison.json   # deployed, then the three variants
python scripts/measure_cold_start.py && python scripts/check_render_hours.py     # numbers and dates into deployed.md
git push origin HEAD:ci-red-evidence && gh workflow run ci.yml --ref ci-red-evidence -f deploy_only=true   # red run: deploy skipped, "dependent job failed"
EVAL_TARGET_BASE_URL=http://127.0.0.1:8000 pytest tests/integration/test_smoke_eval_endpoint.py -q   # against the running image
ls docs/evidence/*.png                                 # three committed screenshots
```

> **The second `jq` was corrected at source on 2026-09-10 (P11 fix round 2).** It read
> `jq -r '.runs[].config_json.target' … # deployed x3`, which cannot pass against any
> `comparison.json` this project writes: `evaluation/ablation.py` emits
> `{generated_at, target, dataset_sha, variants[], workflow_completion_check, flips, note}` —
> no `runs`, no `config_json` — so the old line died in `jq: error … Cannot iterate over null`.
> `target` is a *single shared top-level field* precisely because `ablation.py` refuses to
> compare runs whose targets differ (§13.9), which is the "three runs sharing `target:
> deployed`" property the line is asking for. See P11-report.md §16.

### P12 — Documentation, demo prep, publish · **M** (4 h) · deps P11 · ∥ none · no key · commit `P12(docs): …`

**Goal.** Every graded document written by hand, every heading asserted, both demo scripts proved against the live URL, and the grader invited.
**Scope.** `README.md`, `design-and-evaluation.md`, `ai-tooling.md`, `deployed.md`, `NEEDS-FROM-USER.md`, `docs/demo-script.md`,
`docs/pre-submission-checklist.md`, `scripts/paste_eval_numbers.py`, `tests/contract/test_docs_completeness.py`.

**Deliverables.**
- `design-and-evaluation.md` — the mermaid diagram naming all seven components, the ten R10.1 `###` justification subsections (each carrying its
  rejected alternative from spec §3), all eight DOCS.3 subjects, the generated tool schemas, both demo sequences matching `DEMO_EXPECTATIONS`, the judge
  methodology naming the labeller and the blinding, and the three evidence screenshots.
- `README.md` final (five headings, the real deployed URL, third-party components); `ai-tooling.md` (`## What worked well`, `## What did not work`, the
  AI-use and ownership disclosure); `deployed.md` final (six headings with the measured cold start and its ISO date, the MCP-transport rationale,
  `## Access` — the tokenized link, the cookie, the bearer header for API clients and MCP Inspector, the two personas and the rotation step — and
  `## Cost` with the dates observed); `design-and-evaluation.md`'s `### Security posture` subsection (no user accounts by design, the requirements are
  silent, the three controls — access token, persona roles, confirmation gate — and what production would add: SSO, employee-scoped data access, a
  retention policy).
- `docs/demo-script.md` (the §18.3 segment table, the production note, a per-task five-element DEMO.6 sub-checklist) and
  `docs/pre-submission-checklist.md` with one line per DEMO.* and SUB.* id; `tests/contract/test_docs_completeness.py`, authored here in full because
  this is the phase where every asserted document exists; `scripts/paste_eval_numbers.py`. **No CI diff-check of documentation anywhere.**

**Definition of done.**
```bash
python scripts/paste_eval_numbers.py                   # the results table filled from evaluation/results/latest.json
pytest tests/contract/test_docs_completeness.py -q     # ten ### + eight ## headings + ### Security posture; README's five + three link lines
                                                       #   (Deployed: carrying ?access=); deployed.md's six;
                                                       #   ai-tooling.md's three; demo script and pre-submission checklist present and complete
grep -c 'TBD-before-submission' README.md              # 0
BASE_URL="$DEPLOY_URL" bash scripts/demo_task_1.sh && BASE_URL="$DEPLOY_URL" bash scripts/demo_task_2.sh   # both send the bearer header
gh api -X PUT repos/seantmalone/quantic-mosaic/collaborators/quantic-grader
gh api repos/seantmalone/quantic-mosaic/collaborators/quantic-grader/permission
gh workflow run ci.yml -f deploy_only=true && curl -s "$DEPLOY_URL/health" | jq '.trace_store.eval_runs_imported'   # matches the committed count
```

## 5. Gates requiring the user

Seven tracked gates, **two fully discharged — G1 is scripted and G4's keys were provided on 2026-09-09** — so **five reach a human**: three are a
single paste or click under 10 minutes (G2 ~5 min, G3 ~3 min, G5 ~2 min), **G6 is ~20 minutes**, and **G7 is the one substantial human task, budgeted
at 60–90 minutes**. **Nothing in P0–P9 blocks on any of them** — the build never idles.

| Gate | Requested | Needed | What Sean does (time) | What Claude Code does meanwhile |
|---|---|---|---|---|
| **G1 — `quantic-grader` share** (§19.1 item 5) | **P0** | **P12** | **Nothing — scripted.** The repo was verified **already public** on 2026-09-08, so no visibility change is ever made. Claude Code sends the invite at P12 on the authenticated `gh` session. Accepting it is the grader's action; confirming it went out is folded into G7. | Re-asserts `gh api repos/seantmalone/quantic-mosaic --jq .private` → `false` at P0; sends the invite and reads back the permission at P12. |
| **G2 — Render account + install the Render GitHub App** (item 2) | **P0** | **P11** | ~5 min: open `https://github.com/apps/render/installations/new`, sign in (no card), grant access to `seantmalone/quantic-mosaic`. Browser-only — **no API can install a GitHub App**. | P0–P10 in full. `make docker-run-512` proves the exact image locally with no host at all. |
| **G3 — Turso account + Platform API token** (item 3) | **P0** | **P11** (usable any time after P1) | ~3 min: `https://turso.tech` → GitHub SSO (no card) → create a Platform API token → paste. | `scripts/provision_turso.py` then does database creation, scoped-token minting, `gh secret set` and Render env-var population unattended. Until then `SqliteStore` is the coded fallback. |
| **G4 — Model API keys** (item 1) — **✅ PROVIDED 2026-09-09** | **P0** | **P6 probe** | **Nothing — already supplied.** An `ANTHROPIC_API_KEY` (agent, `claude-haiku-4-5`) plus two Google AI Studio keys from two different Cloud projects (`JUDGE_API_KEY`, `LLM_FALLBACK_API_KEY`), all three validated on 2026-09-09 and living only in the git-ignored `.env`. | P0–P9 build and pass CI on `LLM_PROVIDER=stub` regardless; the live probe runs at **P6**. The free Gemini keys carry the judge on both sweeps at ~260 calls each, comfortably inside the free RPD on a dedicated key (spec §13.9); the paid agent is bounded instead by `LLM_DAILY_CALL_CAP` and prompt caching. |
| **G5 — Render API key** (item 4) | **P10** | **P11** | ~2 min: Render dashboard → Account Settings → API Keys → *Create* → paste. **The access gate adds no gate:** `provision_render.py` generates `APP_ACCESS_TOKEN` itself with `secrets.token_urlsafe(32)`. | `provision_render.py` creates the service, populates env vars, reads back the deploy hook and sets every GitHub secret. Fallback: ~15 min of manual Blueprint clicking per iteration. |
| **G6 — Optional upgrade** (item 8) | **P10** | before **P12** | **~20 min** adjudicating the 8 reference groundedness labels (spec §19.2). The three key items that used to sit here are **provided** (G4). | The labels stay model-authored by an independent Opus subagent **and are named as such** — accurate and defensible, never described as human. Judge independence is unaffected: agent and judge are already different vendors and families (spec §13.7). |
| **G7 — Record the demo + submit** (items 6, 7) | **P12** | after **P12** | **★ 60–90 min** — 7–10 min of footage plus setup, retakes, upload and submission. Follow `docs/demo-script.md` (webcam overlay throughout, ID held ≥ 3 s at ~0:15, both tasks one-click against the live URL). Accept/confirm the `quantic-grader` invite, paste the video link into README's `Demo video:` line, submit both links. | Pre-stages both link lines, warms both demo prompts, verifies the live URL, the dashboard and the eval pages, and walks the pre-submission checklist. |

`NEEDS-FROM-USER.md` is created at **P0** with the **minimum viable set at the top — the model keys (already provided), a Render account and a Turso
token, the last two free and card-free** — carries a time estimate per gate, marks **G1** *scripted — no user action* and **G4** *provided 2026-09-09
(Anthropic + two Google AI Studio keys)*, and is refreshed at every phase boundary. It is USER.1's mechanical artifact.

---

## 6. Per-phase verification

The push path is key-free and offline apart from the cached embedding model; nothing in CI replays recorded LLM output, and no CI job writes to the repo.

| Phase | Primary verification instrument |
|---|---|
| P0 | `ruff` + `gitleaks`; `.env.example` ↔ `Settings` bijection; README headings and link lines; the five conventions greps; a **recorded green `pull_request` run** (RUBRIC5.7's second event) |
| P1 | Store parity across both backends; redaction in both directions; span-listener ordering and isolation; id uniqueness across two interpreters; cascading retention; idempotent eval-results import; store-level process-exit recovery; the dated Linux RSS reading in `CHANGELOG.md` |
| P2 | `check_facts.py` (quotes verbatim, sections real, `fact_key`s resolve); corpus size **band**; all ten PD.2 topics mapped; the canary under `CHUNK_MAX_CHARS` |
| P3 | Byte-idempotent generation; JSON-Schema validation; PII grep; the four anchors and 24 well-formed ids; the PTO identity at the snapshot with `E1042` → 13.5 |
| P4 | Byte-identical manifest rebuild (`--verify-manifest`); `--selftest`; heading-path propagation and overlap; per-format ingest report summing to totals; the `query_embed` asymmetry branch recorded; exact-`k` filter-then-truncate; `min_dense_score` ≠ `rrf_score`; seven citation fields on every chunk; manifest genuinely tracked |
| P5 | MCP 2.x API shape; `REQUIRED_TOOL_NAMES ⊆ tools/list`; discovery **and** a call on both transports; committed schemas equal a live `tools/list`; the three confirmation-gate cases; the rules engine's chunk ids resolving and all seven scenarios reachable |
| P6 | Both wire shapes normalised to one dict; strict-schema emission; limiter burst then pacing; exactly one `llm_call` span plus its `llm_messages` per call carrying the cache-token and `cost_usd_estimate` fields; the live probe — Haiku tool call (no `strict`) + `output_config` JSON, a cache hit on the repeat call **when the prefix clears the 4096-token minimum** (otherwise the measured prefix size recorded), and a Gemini judge JSON call |
| P7 | Six guardrail suites plus `test_g4_no_false_positives` over the committed manifest; both demo sequences under the stub against `required_tools` + `precedence_edges` + `forbidden_tools`, task 2 stopping at `awaiting_confirmation`; RAG-only makes zero people-tool calls; no chain-of-thought; the golden prompt snapshot |
| P8 | `/chat` contract for RAG-only **and** tool-using; the four-row privileged-options matrix; the access gate (401 → `?access=` 302 + cookie → bearer, `/health` and `/ready` open, `access_token_missing` under `APP_ENV=render`) and the two personas; `trace[]` ≡ spans-of-turn plus the seven-row R4.3/R4.1 mapping; the four fault injections at HTTP 200; `/health` degradations vocabulary and the MCP-down flip; SSE live path and fallback; confirm-resume producing exactly one `mock_writes` row; audit completeness; action safety over the fixtures |
| P9 | All 11 pages rendering committed fixture data with their key selectors **as admin**, and 403 `ADMIN_REQUIRED` without the admin persona; every view-model validating; page 11's `judged` / `n_scored` contract with deterministic metrics non-null; the three write controls wired and admin-only; the eval-row → trace deep link; the bounded smoke-eval endpoint |
| P10 | Dataset shape and the no-relative-dates rule; every scorer edge case; cold probes excluded from quality means; `latest.json` never written for a `local` run; three local variants completing with the ablation's same-target/same-dataset assertions; action safety over real traces; `judge_agreement_rate` with its n |
| P11 | `docker run -m 512m` with `rss_mb < 420`; injected-`PORT` health; live smoke with `git_sha != "dev"`; `latest.json` naming a `deployed` `baseline` run; `comparison.json` naming `deployed` three times; non-null `sessions.eval_run_id` on the published run; the red-run evidence pair; three committed screenshots; dated §3.1 values in `deployed.md` |
| P12 | `test_docs_completeness` (ten `###`, eight `##`, README/`deployed.md`/`ai-tooling.md` headings, demo script and checklist); no `TBD-before-submission` left; both demo scripts against the live URL; the grader permission read back; `eval_runs_imported` matching the committed count |

## 7. End-to-end acceptance checklist (mirrors rubric level 5)

Signed off at P12 before submission. Each row names an artifact a grader can open.

| # | Rubric level-5 bullet | Passes when | Artifact |
|---|---|---|---|
| 1 | Deployed agentic HR system with cited, grounded responses | Groundedness ≥ 0.90 mean; `cit_resolve_mean` ≥ 0.95; `strict_pass_rate` ≥ 0.85 — **all from the single `deployed` `baseline` run** | `evaluation/results/<run_id>.json` + `latest.json` + dashboard page 11 |
| 2 | MCP fully functional — discovery, calls, traces, graceful errors | 9 tools via a real `tools/list`; every turn's `tools/call` on the wire; the four fault-injection tests green | `mcp_discovery` + `tool_call` spans; `/dashboard/mcp`; `docs/evidence/mcp-discovery-page.png` |
| 3 | Two end-to-end agentic tasks, multi-step, RAG + mock data | Each ≥ 4 tool calls, ≥ 1 retrieval, ≥ 1 structured-data tool; task 2 writes only behind the confirmation gate | `tests/e2e/test_demo_tasks.py` (two expectation records), the two UI buttons, the two curl scripts, the video |
| 4 | Excellent RAG ingestion, indexing, retrieval, citations, guardrails | Byte-identical manifest rebuild; hybrid RRF retrieval; six guardrail suites green; tuned `k` demonstrated | `test_chunking_deterministic`, the guardrail suites, `comparison.json` + `chunk_size_comparison.json` |
| 5 | Excellent architecture, clear separation | Six packages, dependencies strictly downward, the conventions test green | `tests/architecture/test_conventions.py` + the mermaid diagram |
| 6 | Free-tier deployment, env vars and cold start documented | Live URL 200; `/health` + `/ready`; every env var in `.env.example` **and** `deployed.md`; measured cold and warm numbers | `deployed.md`, `render.yaml`, `scripts/measure_cold_start.py` |
| 7 | CI/CD on push **and** PR, build/start + MCP tests, deploy gated | Green on both events (the PR half is P0's recorded run); `test_app_starts`; `test_mcp_discovery`; `deploy` declares `needs: [test, docker]`; a recorded red run with deploy skipped for "dependent job failed" | `gh run list`; the P0 run URL in `CHANGELOG.md`; `docs/evidence/ci-deploy-skipped.png` |
| 8 | Excellent evaluation across all six metric families | 26 items; groundedness, citation accuracy, tool selection, workflow completion, escalation/safety, latency p50/p95 cold vs warm; three-variant ablation; judge agreement with its n | `evaluation/results/`, `evaluation/REPORT.md`, dashboard page 11 |
| 9 | Excellent docs + demo meeting every DEMO.* item | `test_docs_completeness` green; video 7–10 min, on camera throughout, ID shown, both tasks live, design/deploy/CI/eval walkthroughs | `design-and-evaluation.md`, `README.md`, `ai-tooling.md`, `deployed.md`, the video link |
| 10 | **USER.2 / USER.3 / USER.4** — full audit logs and evaluation in one dashboard, one trace model | Every record type present for a freshly executed chat; all six metric families, cold/warm p50/p95 and the ablation browsable; `/chat`'s trace, the dashboard and the eval report derive from one `trace_id` | `test_audit_completeness`, `test_dashboard_viewmodels`, `/dashboard/sessions/{id}` |
| 11 | **USER.1** — autonomous buildability | `NEEDS-FROM-USER.md` lists only the seven gates, two fully discharged (G1 scripted, G4 keys provided 2026-09-09) and five reaching a human (the access token is generated by `provision_render.py`, never pasted); every other step is a scripted command; CI reproduces build → index → test with no manual step | `NEEDS-FROM-USER.md`, `.github/workflows/ci.yml` |

---

## 8. Risk register

Severity and mitigation follow spec §20 (ids match). **Trigger** is the observable signal; **Fallback** is decided now, not at the moment of failure.

| # | Risk | Sev | Trigger (observable) | Fallback (pre-decided) | Owner |
|---|---|---|---|---|---|
| R-1 | Memory/CPU figures are macOS inferences, not Linux cgroup measurements | High | `make docker-run-512` reporting `rss_mb ≥ 420`, or a stubbed six-tool-call turn under `--cpus 0.1` exceeding ~30 s | Memory: default `EMBED_WARMUP=0` and lazy-load; if still over, move embeddings to a hosted API (one extra key, documented). CPU: raise `AGENT_WALL_CLOCK_S` toward the Render timeout, adopt the documented `202 + SSE` pattern, drop `AGENT_MAX_STEPS` to 4 | P11 |
| R-2 | `mcp` 2.2.0 is a breaking rewrite; model priors target 1.x | High | `test_mcp_api_shape` red, or `ImportError: FastMCP` | `mcp==2.2.0` pinned; the P5 subagent reads `mcp/README.md`'s 1.x→2.x table **before** writing code; the shape test fails in seconds | P5 |
| R-3 | fastembed footguns (default batch → 1,477 MB; `parallel=1` hangs) | High | RSS spike during ingest, or an ingest exceeding 600 s | One call site hard-coding `batch_size=8`, `threads=1`, never `parallel=`; two greps in `test_conventions.py` keep it true; ingestion runs at Docker build time, never at boot | P4 |
| R-4 | Ephemeral disk vs "full audit logs for every session" | High | Turso credentials absent at P11, or `/health.trace_store.backend == "sqlite"` in production | `SqliteStore` is the coded fallback and committed eval results still populate the evaluation pages; the UI labels live sessions *"session-scoped on the free tier"* and `deployed.md` states exactly which part of USER.2 is unmet; `make demo1 && make demo2` refills the session pages in seconds | P1 / P11 |
| R-5 | Overspend on the paid agent model, or free-tier quota exhaustion on the judge — mid-sweep or live on camera | High | `/health.llm.agent.calls_today` approaching `daily_call_cap`; HTTP 429 with `Retry-After`; 429s accumulating in `eval_runs.notes` | `LLM_DAILY_CALL_CAP` (1500/UTC day) with a graceful 200 `outcome: "error"` turn; prompt caching on the tools → system prefix, which is what holds a sweep to $2–4; judged metrics scoped to `baseline`, so a sweep spends only ~260 free judge calls (~560–710 provider calls in total); `JUDGE_API_KEY` and `LLM_FALLBACK_API_KEY` on two separate Cloud projects; sequential execution behind the token bucket; failover to free Gemini recorded as `provider_failover`; the optional cache warms the two demo prompts before recording, badged honestly | P10 / P11 |
| R-6 | Judge credibility — the self-preference objection on the most heavily weighted rubric bullet | Medium | — (standing) | **Answered by construction:** the agent is Anthropic `claude-haiku-4-5` and the judge is Google `gemini-3.5-flash-lite`, so no model grades its own output; six metric families are judge-free (citation resolvability, DocRecall, tool selection, argument correctness, workflow completion, action safety) and four are judged; 8 reference labels authored by an independent Opus subagent — a third, independent model, and a different family from the Gemini judge its labels are compared against — blind to the judge, published as an **agreement rate with its n**; optional item #8 upgrades to human adjudication | P10 |
| R-7 | AI-authored corpus drifts into vagueness or contradiction | High | `check_facts.py` red, or a gold answer contradicting a cited chunk | `corpus/facts.yml` pins the ~40 facts the system depends on, each with a verbatim quote; gold answers and `rules.yml` both cite fact ids, so a corpus edit that moves a number fails the test first; ≥ 6 checkable statements per document | P2 |
| R-8 | Untyped Jinja/htmx boundary across 11 dashboard pages | Medium | A page rendering with a missing field while tests stay green | Every page renders from a typed view-model produced by the same `/api/*` endpoint; pages 2, 4–8 are thin configurations of one shared partial; **page 3 is built first** | P9 |
| R-9 | Platform and provider facts partly unverified | Medium | A §3.1 row contradicted by the live dashboard at P10/P11 step 0 | §3.1 is the complete list with where and when to read each; P10 step 0 and P11 step 0 paste the observed values with dates into `deployed.md`; documented host fallbacks: a native Python service on Render, then Cloud Run with the same image | P10 / P11 |
| R-10 | Two Render budgets — 750 instance-hours and 500 build minutes per month | Medium | `check_render_hours.py` projecting > 600 h or > 400 build minutes | One service, no keep-alive cron, `autoDeploy: false`, and `paths-ignore` on `evaluation/results/**` and `docs/**` so a results or docs commit spends no build; the script warns (never fails); both figures re-read and dated at P11 step 0 with the per-build wall-clock in `## Cost` | P11 |
| R-11 | Autonomous-build drift across 13 phases and many subagents | High | A second logging path appearing; a demo sequence silently changing; a corpus number moving under a gold answer | The trace is built at P1 with the conventions test in place from the same phase; the standing per-phase span criterion; `test_demo_tasks` compares actual traces against the documented sequences; `test_facts_quotes` locks the corpus; `test_tool_schemas_committed` locks the schemas; `test_chunking_deterministic` locks the manifest | all |
| R-13 | Stub-vs-real divergence hiding a prompt regression | Medium | A real run failing on tool-call shape while `tests/e2e` is green | At P10 one **real** exchange per demo task is recorded and committed as a stub script, so the stub is a recording; the golden prompt snapshot forces a deliberate re-review on any prompt change; every `make eval` exercises the real provider end to end | P10 |

Spec §20's remaining rows (R-12 the exposed MCP endpoint, R-14 late-phase schedule, R-15 over-refusal) are standing conditions rather than plan
triggers, mitigated by design: the mount sits behind the access gate and MCP Inspector attaches with the bearer header, the write tools are unusable
without a human-minted token, P9 splits into three sub-phases, `MIN_EVIDENCE_SCORE` is calibrated at
P10 with over/missed-refusal reported, and the spec's design rule (§1) governs every review round.

---

## 9. Cross-references

- **Design truth:** `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` (v2)
- **Requirement → phase → verification:** `docs/requirements-traceability.md`
- **Human gates, live checklist:** `NEEDS-FROM-USER.md` (created at P0)
- **Per-phase landing log and dated measurements:** `CHANGELOG.md`
