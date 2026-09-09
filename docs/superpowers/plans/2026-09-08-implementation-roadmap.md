# Mosaic HR Copilot — Implementation Roadmap

**Project:** `quantic-mosaic` · Quantic "AI Engineering Techniques and Architectures"
**Date:** 2026-09-08 · **Status:** ready for autonomous execution
**Source of design truth:** [`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`](../specs/2026-09-08-hr-agentic-rag-design.md)
**Traceability:** [`docs/requirements-traceability.md`](../../requirements-traceability.md)

> This document is the **execution plan**, not the design. Every "what" and "why" lives in the spec;
> this file answers **in what order**, **proved by which command**, **by whom (main session vs Opus
> subagent)**, and **what the human must do and when**. Where this roadmap and the spec appear to
> disagree, **the spec wins** and this file is corrected.

---

## 1. Executive summary

1. Build **Mosaic HR Copilot**: a deployed, free-tier, agentic HR assistant for the fictional
   *Mosaic Robotics, Inc.* — policy RAG over a 14-document / 63-page corpus in four formats, plus an
   agent that plans, calls **9 real MCP tools** over real JSON-RPC, and answers with resolvable citations.
2. One Python 3.12 process, one container, one Render free web service: FastAPI + Jinja/htmx UI,
   agent orchestrator, MCP client, an **in-process-mounted Streamable-HTTP MCP server**, a read-only
   sqlite-vec + FTS5 index, committed synthetic mock data, and a durable Turso trace store.
3. The **trace/audit model is built first (P1), before anything that can log**, with an AST test
   proving `core/trace.py` is the sole writer — one writer, five readers (`/chat` trace, SSE, the
   13-page dashboard, the eval scorers, the demo narration).
4. Safety is **architectural, not prompted**: mock writes require an HMAC `confirm_token` minted only
   after a human click, verified *inside* the MCP server; action safety is a build-blocking CI gate at 1.0.
5. Seven guardrails (evidence gate, citation resolvability, fact-vs-recommendation, injection shield,
   sensitive escalation, identity scope, redaction) each emit a span and each has a unit test.
6. A **single fact ledger** (`corpus/_facts.yml`) generates the corpus prose insertions, the
   deterministic compliance rules and the eval gold answers, so gold-vs-corpus contradiction is impossible.
7. A 26-item evaluation with 9 metrics across all six rubric families, a 3-variant ablation plus a
   zero-LLM chunk-size comparison, judge validation by Cohen's κ, and byte-reproducible committed results.
8. **Phases P0–P9 build and pass CI with zero API keys** (`StubAdapter` + frozen clock); credentials
   are needed only from P10 (one Gemini key) and P11 (Render + Turso).
9. CI runs on push **and** PR, is offline and deterministic after the first cache fill, and `deploy`
   is gated `needs: [test, docker]` with recorded red-run evidence.
10. Thirteen phases, ≈51 agent-hours, each ending green, committed, and independently demoable.

---

## 2. How execution is organised

### 2.1 Roles

| Actor | Does |
|---|---|
| **Main session** (this session) | Reads the spec §, writes the phase brief, dispatches subagents, reviews diffs, runs the acceptance gate, **commits**, updates `CHANGELOG.md` and `NEEDS-FROM-USER.md`. |
| **Opus subagent** (`model: "opus"` on every Agent/Workflow call, per `CLAUDE.md`) | Implements one phase or one sub-phase. Reads the spec sections named in its brief plus `mcp/README.md` where relevant. **Never commits.** |
| **Human (Sean)** | Only the seven gates in §5. Everything else is scripted. |

### 2.2 The standing subagent brief (prepended to every phase dispatch)

```
Read docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md sections: <list>.
That spec is authoritative; do not redesign. Implement exactly what it specifies.
Write ONLY the files named in your deliverables list. Never commit; never touch .git.
Every wall-clock read goes through core.clock.now(). Every span write goes through core/trace.py.
Run the acceptance commands yourself and paste the real output; do not claim green without it.
Extend .github/workflows/ci.yml job `test` with the spec §15.1 steps this phase's tests occupy
(see the step -> phase table in roadmap §6.1), then paste the green run URL. A test that a phase
gate ran locally but CI does not run cannot gate the deploy, and the two suites must not diverge.
If the spec is ambiguous or wrong, STOP and report — do not resolve it yourself.
Scratch work goes in the scratchpad directory, never in the repo.
```

### 2.3 Standing acceptance criterion (from P4 onward)

> *The expected spans were persisted, with the expected kinds and payload shapes.*

This is checked in every phase gate from P4 on, and is the mechanism that prevents a later subagent
inventing a parallel logging path (the failure USER.4 forbids).

### 2.4 Commit message pattern

Every phase commits with:

```
P<n>(<scope>): <what landed>

- <bullet per deliverable>
Gate: <the exact command(s) that proved it> — green
Reqs: <comma-separated requirement ids from docs/requirements-traceability.md>

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RnJs3hSPUc8kca4BtF5oAM
```

Scopes: `skeleton`, `core`, `corpus`, `mockdata`, `rag`, `mcpserver`, `llm`, `agent`, `web`,
`dashboard`, `eval`, `deploy`, `docs`. Sub-phases use `P9a(dashboard):` etc.
Fix-up commits inside a phase use the same scope with a `fix:` prefix on the subject.

### 2.5 Size key

| Size | Agent-hours | Phases |
|---|---|---|
| **S** | ≤ 3 h | P0, P3, P11 |
| **M** | 3–4 h | P1, P2, P4, P6, P8, P12 |
| **L** | 5–6 h | P5, P7, P9, P10 |

Total ≈ **51 agent-hours** (2+4+4+2+4+5+3+6+4+5+5+3+4), matching Appendix A of the spec.

---

## 3. Phase dependency graph

```
P0 skeleton
 └─ P1 core/ (trace FIRST)  ──────────────────────────────────┐
     ├─ P2 corpus ────┐                                       │
     ├─ P3 mock data ─┤ (P2 ∥ P3)                             │
     │                └─ P4 rag/ ──┐                          │
     ├─ P6 core/llm/ ──────────────┤ (P4 ∥ P6)                │
     │                 P3+P4 ──── P5 mcpserver/ ──┐           │
     │                                            └─ P7 agent/ (needs P5+P6)
     │                                                └─ P8 web/
     └────────────────────────────────────────────────── P9 dashboard (needs P1+P8)
                                                            └─ P10 evaluation (needs P7, +P9 for views)
                                                                └─ P11 deployment (needs P9+P10)
                                                                    └─ P12 docs + demo prep
```

**Parallelisable pairs:** `P2 ∥ P3` (two subagents, no shared files) and `P4 ∥ P6` (two subagents;
`rag/` and `core/llm/` share nothing). P9 splits into `9a → 9b ∥ 9c` internally. Everything else is
strictly sequential because each phase's acceptance gate consumes the previous phase's artifacts.

---

## 4. Build phases

> Each phase ends with: acceptance gate green → **`.github/workflows/ci.yml` job `test` extended with
> the §15.1 steps this phase's tests occupy (§6.1's step → phase table), with the green run URL
> pasted** → main session reviews the diff → `CHANGELOG.md` line added → **commit** →
> `NEEDS-FROM-USER.md` refreshed. `git status` must be clean at every phase boundary (USER.5).
>
> **CI grows with the build; it is not retrofitted.** P0 lands the skeleton (steps 1, 1b, 2, 3) and
> P11 adds the `docker`, `fresh-clone` and `deploy` jobs, but **steps 4–19 of job `test` belong to
> the phase that introduces the tests they run** — otherwise the deploy-gating suite silently lags
> the suite a phase gate ran locally, which is exactly the R8.2 / USER.5 failure. The mapping is
> normative and lives in §6.1.

---

### P0 — Skeleton, CI, repo policy · **S** (2 h) · deps: none · no key

**Goal.** A repository that lints, tests (on an empty suite), runs CI on push *and* PR, and enforces
its own documentation and dependency invariants from commit one — so every later phase inherits a
green baseline rather than building one.

**Scope.** `pyproject.toml`, `requirements.txt` (`uv pip compile`, committed), `requirements-dev.txt`,
`.python-version` (3.12.14), `Makefile`, `src/hrmosaic/settings.py`, `.env.example`, `.gitignore`,
`.dockerignore`, `.github/workflows/ci.yml` (skeleton), `README.md` stub, `NEEDS-FROM-USER.md`,
`CHANGELOG.md`, `scripts/vendor_assets.py`, `src/hrmosaic/web/static/vendor/`.

**Deliverables.**
- `settings.py` — pydantic-settings, every §12.3 variable, **structural validation at import,
  credential validation deferred**; the `sys.version_info[:2] != (3, 12)` warning (never a crash);
  the `MCP_SERVER_URL` / `GIT_SHA` / `LLM_FALLBACK_API_KEY` / `JUDGE_FALLBACK_API_KEY` /
  `mcp_transport_effective` `model_validator`s.
- `.env.example` — every settings field, `# REQUIRED` / `# OPTIONAL`, default, signup URL,
  **including `EMBED_PROVIDER` and `GROQ_API_KEY`**.
- `Makefile` targets: `setup run run-stdio test test-smoke lint ingest eval ablation demo1 demo2
  docker docker-run` (every `make` target named anywhere in the spec must exist here).
- `README.md` stub whose **first 20 lines** carry `Deployed:`, `Demo video:` and `Repo:` lines with
  the literal placeholder `TBD-before-submission`.
- `scripts/vendor_assets.py` downloads htmx 2.0.9, Alpine 3.15.2, Chart.js 4.5.1 at exact tags and
  writes `{file, version, upstream_url, sha256}` into `static/vendor/LICENSES.md`.
- **Repo visibility: already public** (verified with `gh api repos/seantmalone/quantic-mosaic --jq
  .private` → `false` on 2026-09-08), so no visibility change is made. P0 only re-asserts it in the
  definition of done. The grader invite (`gh api -X PUT
  repos/seantmalone/quantic-mosaic/collaborators/quantic-grader`) is sent by script at **P12**, once
  the deliverables exist, so the grader never lands on an empty repo. The user's only remaining action
  is **confirming the invite went out at G7** (§19.1 item 5).
- **Branch protection applied** to `main` making the `test` job a required status check and
  forbidding force-pushes.
- `.github/workflows/ci.yml` **skeleton = §15.1 steps 1, 1b, 2, 3 plus the empty `tests/unit` and
  `tests/contract` steps (6, 13)**; steps 4–19 are added by the phases that own them (§6.1).

**Definition of done.**
```bash
make lint && make test && make test-smoke
pytest tests/contract/test_env_example_covers_settings.py -q     # both directions
pytest tests/unit/test_vendor_asset_hashes.py -q
pytest tests/contract/test_docs_completeness.py -q -k readme_link_lines
gh api repos/seantmalone/quantic-mosaic --jq .private              # false (already public; no change made)
gh api repos/seantmalone/quantic-mosaic/branches/main/protection | jq '.required_status_checks.contexts'  # ["test"]
gh run list --limit 5                                             # push AND pull_request runs green
```

**Parallelism.** None (single small subagent). **Commit:** `P0(skeleton): …`

---

### P1 — `core/`: the trace store, built before anything that can log · **M** (4 h) · deps: P0 · no key

**Goal.** Make the audit model the foundation, not an afterthought — plus retire the highest-severity
risk (R-1) by measuring Linux memory *and* 0.1-CPU wall-clock before ~40 more agent-hours are spent.

**Scope.** `core/db.py`, `core/migrations/00N_*.sql`, `core/trace.py`, `core/models.py`,
`core/redact.py`, `core/ids.py`, `core/clock.py`, `core/corpusread.py`, `core/archive.py`,
`core/retention.py`, `tests/architecture/`, `tests/unit/`, `tests/integration/`.

**Deliverables.**
- `db.py` — `execute()` / `batch()` over `SqliteStore` and `TursoHTTPStore` (hand-written httpx
  client against `POST <db>/v2/pipeline`, ~130 lines).
- Migrations for all 12 tables incl. `llm_messages`, `import_state`, `mock_writes.action_digest`,
  `turns.resumed_count`, `turns.awaiting_ms`, `eval_results.run_phase`, and `pending_actions`'
  composite `(session_id, turn_id, action_digest)` primary key.
- `trace.py` — sole writer; SSE publish hook; SIGTERM/SIGINT/`atexit` flush bounded at 3 s; turn
  reopen; and the explicit replay API `import_session / import_turn / import_span /
  import_llm_messages / import_mock_write / import_pending_action`.
- `models.py` — the span-payload discriminated union + `strict_json_schema(model)` emitter.
- `clock.py` — the **only** legal wall-clock read; honours `EVAL_FIXED_NOW` → `NOW_OVERRIDE` → real.
- `archive.py` — idempotent upsert **containing no SQL of its own** (it calls the replay API).
- `retention.py` — **cascading** sweep: spans → `llm_messages` → turns → `pending_actions` /
  `used_confirm_tokens` → sessions, in one batch.
- **R-1 measurements** recorded with dates in `CHANGELOG.md`: (a) `docker run -m 512m
  --memory-swap 512m` with the model resident; (b) `docker run -m 512m --cpus 0.1` serving one
  stubbed six-tool-call turn; (c) the `python:3.12-slim` sqlite-vec loadable-extension probe.

**Definition of done.**
```bash
pytest tests/architecture -q          # sole-writer over src/** AND evaluation/**, WITHOUT an archive.py carve-out
pytest tests/unit/test_store_parity.py tests/unit/test_redact_preserves_token_counts.py \
       tests/unit/test_rss_reader.py tests/unit/test_pending_action_collision.py -q
pytest tests/integration/test_archive_roundtrip.py tests/integration/test_archive_idempotent.py \
       tests/integration/test_archive_updates.py tests/integration/test_retention.py \
       tests/integration/test_process_exit_mid_turn.py tests/integration/test_lifespan_order.py -q
grep -E 'RSS|0\.1 CPU|vec_version' CHANGELOG.md   # the three R-1 numbers, dated
```
`test_retention.py` must assert **zero orphaned `llm_messages`**; `test_archive_roundtrip.py` must
assert `messages_ref.n_messages == count(llm_messages for that span_id)` with non-empty content.

**Parallelism.** One subagent (the sole-writer invariant is easier to hold with one author).
**Commit:** `P1(core): …`

---

### P2 — Policy corpus and the fact ledger · **M** (4 h) · deps: P0 · no key · ∥ P3

**Goal.** A corpus whose every number is authored exactly once, so gold answers, compliance rules and
prose can never contradict each other (mitigation for R-7).

**Scope.** `corpus/_facts.yml`, `corpus/_spec/*.yaml`, `corpus/_numeric_allowlist.yml`, the 14
documents, `corpus/README.md`, `scripts/gen_corpus.py`, `scripts/build_pdf.py`,
`scripts/gen_rules.py`, `scripts/corpus_stats.py`, `scripts/check_facts.py`.

**Deliverables.**
- `_facts.yml` incl. **both** accrual bands (`pto.accrual.ft_under_3y`, `pto.accrual.ft_3y_plus`)
  each with its `tenure_band`, plus `approved_countries` and `cross_references`.
- **The 14 documents' prose authored ONCE and committed** (no LLM runs inside the generator);
  `gen_corpus.py` is a deterministic renderer that only injects ledger statements, stamps headers and
  emits the PDF/HTML derivatives.
- `_rules.yml` generated from the ledger; `_numeric_allowlist.yml` with a `reason` per entry.
- The **injection canary** pinned into its own leaf section sized between `CHUNK_MIN_CHARS` (120) and
  `CHUNK_MAX_CHARS` (1400).
- Topic → document map in `corpus/README.md` covering all ten PD.2 topics.

**Definition of done.**
```bash
python scripts/gen_corpus.py && git diff --exit-code corpus/     # idempotency gate
python scripts/corpus_stats.py                                    # 5<=files<=20, round(pages)==stated, 30..120
python scripts/check_facts.py                                     # every scoped numeric ledgered; xrefs resolve;
                                                                  # canary occurs in exactly one manifest chunk
pytest tests/unit/test_corpus_stats.py tests/unit/test_corpus_topics.py \
       tests/unit/test_numeric_allowlist.py -q
```

**Parallelism.** Runs **in parallel with P3** (disjoint file trees). Within P2, one subagent authors
prose for documents 1–7 and a second for 8–14 against the same `_spec` files, then the main session
runs `check_facts.py` over the union. **Commit:** `P2(corpus): …`

---

### P3 — Synthetic mock data · **S** (2 h) · deps: P0 (+ P2's ledger for the accrual cross-check) · no key · ∥ P2

**Goal.** Six committed, immutable, obviously-synthetic JSON datasets that are arithmetically
consistent with the fact ledger at the frozen clock.

**Scope.** `scripts/gen_mock_data.py`, `mock_data/*.json`, `mock_data/schemas/*.schema.json`,
`mock_data/README.md`, `scripts/gen_mock_schemas.py`, `scripts/pii_check.py`.

**Deliverables.** `employees.json` (24), `pto_balances.json`, `benefits_elections.json`,
`org_manager_map.json`, `offices.json`, `holidays_2026.json` — **no `tickets.seed.json`**; each with
the `_synthetic` / `_notice` / `_generator` banner; Pydantic models → generated JSON Schemas;
`pii_check.py`. **Employee ids: 24 non-contiguous ids from the `E1001`–`E1199` space, every one
matching `^E1[0-9]{3}$` (the same pattern in `mock_data/schemas/*.schema.json` and in every §8.4 tool
schema), with the four fixed anchors `E1002`, `E1007`, `E1042` (the demo/eval persona) and `E1108`
(the benefits waiting-period fixture) emitted first — §5.4.** Do **not** emit `E1001`–`E1024`
sequentially: `E1042` and `E1108` are load-bearing in both demo tasks, eval item `pto-003`,
`test_mcp_tool_call`, `test_demo_tasks` and the archived traces.

**Definition of done.**
```bash
python scripts/gen_mock_data.py && git diff --exit-code mock_data/    # byte-idempotent
pytest tests/unit/test_mock_schemas.py tests/unit/test_pto_balance_arithmetic.py \
       tests/unit/test_mock_anchor_ids.py -q          # ★ {E1002,E1007,E1042,E1108} present; all 24 ids
                                                      #   unique and ^E1[0-9]{3}$; E1042 -> 13.5 at frozen now
python scripts/pii_check.py                                           # no SSN/real-email/non-555 phone
python scripts/check_facts.py --accrual-bands                         # all 24 employees match their ledger band
```

**Parallelism.** One subagent, in parallel with P2. **Commit:** `P3(mockdata): …`

---

### P4 — `rag/`: parsing, chunking, embedding, hybrid index · **M** (4 h) · deps: P2 (+P1) · no key · ∥ P6

**Goal.** A deterministic, byte-reproducible index with hybrid retrieval whose score scale and
threshold semantics are unambiguous.

**Scope.** `rag/parse/{md,html,pdf,txt}.py`, `rag/chunk.py`, `rag/embed.py`, `rag/index.py`,
`rag/retrieve.py`, `rag/ingest.py`, `rag/download_model.py`, `data/index/chunks.manifest.jsonl`.

**Deliverables.**
- Four parser paths with heading extraction; the PDF path validated against
  `workplace-conduct.src.md`'s heading set.
- Heading-aware chunker (1400/1100/150/120) with `chunk_id = "c_" + sha256(...)[:16]`.
- `embed.py` — the **only** module permitted `.embed(` / `.query_embed(` / `.passage_embed(`;
  `batch_size=8`, `threads=1`, `cache_dir=`, **never** `parallel=`.
- sqlite-vec `vec0` (`distance_metric=cosine`) + FTS5 + `chunks` + `documents` + `index_meta`
  (incl. `vector_backend` and `query_convention`), with the **NumPy brute-force fallback** wired if
  P1's loadable-extension probe failed.
- RRF retriever with **filter-then-truncate** `min_dense_score` semantics and the score-fill step.
- `ingest.py` emitting `data/index/ingest_report.json` + `index_meta.format_counts_json`.

**Definition of done.**
```bash
make ingest && pytest tests/unit/test_chunking_deterministic.py -q     # manifest byte-identical
pytest tests/unit/test_query_embed_is_asymmetric.py -q                 # ★ P4 ACCEPTANCE GATE
pytest tests/unit/test_dense_score_scale.py tests/unit/test_min_dense_score_is_not_rrf.py \
       tests/unit/test_retrieval_filters.py tests/unit/test_ingest_report.py \
       tests/unit/test_chunk_citation_fields.py -q
pytest tests/unit/test_vector_backend_parity.py -q                     # only if the numpy fallback is active
python -m hrmosaic.rag.index --selftest
```
**Gate discipline:** P4 does **not** complete until `test_query_embed_is_asymmetric` has run and the
branch taken (`fastembed.query_embed` vs `prefix:…`), the fastembed version and the date are written
into `CHANGELOG.md` and §3 row 8's confidence tag is updated.

**Parallelism.** Runs **in parallel with P6**. **Commit:** `P4(rag): …`

---

### P5 — `mcpserver/`: nine tools, HMAC confirmation, identity binding · **L** (5 h) · deps: P3+P4 · no key

**Goal.** A real MCP 2.2.0 server whose safety properties are enforced at the tool boundary, so a
fully prompt-injected agent still cannot write state or read another employee's record.

**Pre-step (before any code is written).** Grep the installed `mcp==2.2.0` for
`TransportSecuritySettings` / `allowed_hosts` / `allowed_origins`; record the exact API found **or its
absence** with the date and confidence in `mcp/README.md`. If absent, the §17 claim is *replaced* by a
FastAPI `Host`/`Origin` allowlist + per-IP rate limit on the `/mcp-server` mount.

**Scope.** `mcpserver/server.py`, `mcpserver/tools/*.py` (9), `mcpserver/rules.py`,
`mcpserver/confirm.py`, `mcpserver/identity.py`, `mcpserver/stdio_main.py`,
`mcp/server_entrypoint.py`, `mcp/run_{stdio,http}.sh`, `mcp/tools/*.schema.json`, `mcp/README.md`,
`mcp/inspector.md`, `scripts/gen_tool_schemas.py`.

**Deliverables.** The nine tools with in/out schemas and annotations; the deterministic rules engine
over `_rules.yml`; HMAC `mint`/`verify` (mint referenced from **zero** modules in this phase — it is
called only from `web/api.py` at P8; **P5 therefore must NOT write
`tests/architecture/test_mint_sole_caller.py`** — the §15.1 step-5 assertion "`confirm.mint`
referenced from exactly one module (`web/api.py`)" is unsatisfiable until `web/api.py` exists, so
authoring it here turns `pytest tests/architecture` red on every push from P5 through P7. It is a
**P8** deliverable); identity binding on **tools 4–9**; all four `_meta` keys
(`mosaic/trace`, `mosaic/actor`, `mosaic/retrieval`, `mosaic/confirm`) and the `_trace` span envelope;
`mcp/README.md` with the full 1.x→2.x mapping table and the `_meta` conventions.

**Definition of done.**
```bash
pytest tests/contract/test_mcp_api_shape.py tests/contract/test_tools_match_spec.py -q
pytest tests/integration/test_mcp_discovery.py -q          # >=5 tools over stdio AND mounted HTTP
pytest tests/integration/test_mcp_tool_call.py -q          # check_pto_balance -> remaining_days == 13.5, both transports
pytest tests/unit/test_confirm_hmac.py tests/unit/test_g6_identity.py tests/unit/test_rules_engine.py -q
pytest tests/architecture/test_tool_handlers_async.py tests/architecture/test_no_mcp_init.py -q
python scripts/gen_tool_schemas.py && git diff --exit-code mcp/tools/
```
Plus: write-without-token returns `CONFIRMATION_REQUIRED` **carrying no token field**; a
cross-employee read returns `FORBIDDEN_IDENTITY` **including through `check_policy_compliance`**;
`_meta.mosaic/retrieval.k_override` beats a model-supplied `k`.

**Parallelism.** Sub-split by tool group across two subagents (tools 1–4 corpus, tools 5–9 people +
writes) after `server.py` / `confirm.py` / `identity.py` land from one author.
**Commit:** `P5(mcpserver): …`

---

### P6 — `core/llm/`: the provider abstraction · **M** (3 h) · deps: P1 · key #1 for the gate only · ∥ P4

**Goal.** Four adapters behind one protocol, with the `StubAdapter` that makes P0–P9 credential-free
and the `CachedAdapter` that makes the eval replayable offline.

**Scope.** `core/llm/{base,openai_compat,anthropic,stub,cache,limiter}.py`,
`scripts/probe_provider.py`, `tests/fixtures/llm_scripts/`.

**Deliverables.** `ChatModel` protocol; `OpenAICompatAdapter`; `AnthropicAdapter` (httpx
`MockTransport`-tested, no key); `StubAdapter`; `CachedAdapter` with three sources and
`EVAL_CACHE_ONLY`; token-bucket limiter (capacity `LLM_BURST`, refill `LLM_RPM`/60, **keyed on the
resolved API key**); failover to `LLM_FALLBACK_*`; exactly one `llm_call` span emitted **from inside
the adapter**, plus its `llm_messages` rows and `structured_output_mode`.

**Definition of done.**
```bash
pytest tests/unit/test_adapters.py tests/unit/test_limiter_burst.py \
       tests/unit/test_strict_schema_emission.py tests/unit/test_cache_key_stable_across_days.py -q
pytest tests/contract/test_no_cot.py -q
```
**Live gate (needs key #1):** `python scripts/probe_provider.py` must (a) `GET /models` and confirm
`LLM_MODEL` exists, (b) issue **one** request carrying both `tools` and a strict `response_format`,
(c) write the outcome + endpoint + date into `CHANGELOG.md`. **If key #1 is not yet pasted, P6 ships
the prompted-JSON fallback path and this gate defers to the start of P10** — it never blocks the phase.

**Parallelism.** Runs **in parallel with P4**. **Commit:** `P6(llm): …`

---

### P7 — `agent/`: orchestrator, guardrails, workflows · **L** (6 h) · deps: P5+P6 · no key

**Goal.** The plan → act → synthesize loop that reaches tools **only** through the MCP client, with
seven guardrails and four tested failure paths, all at HTTP 200.

**Scope.** `agent/client.py`, `agent/router.py`, `agent/orchestrator.py`,
`agent/guardrails/g1..g7.py`, `agent/workflows/{remote_work,pto_request}.py`, `agent/prompts/*.j2`.

**Deliverables.** MCP client with per-turn `mcp_discovery` span (cached handshake, per-turn span);
router that **gates** the catalog to tools 1–4 on `policy_qa` with the one-step reopen recovery;
act loop with budgets (6 steps / 8 tool calls / 90 s); G1–G7 each emitting a `guardrail` span;
confirmation flow; two declarative workflow specs whose `is_complete` predicates **require a
structured-data tool result**; three Jinja prompts with a golden snapshot.

**Definition of done.**
```bash
pytest tests/unit/test_g1_evidence_gate.py tests/unit/test_g2_citation_resolvability.py \
       tests/unit/test_g3_fact_vs_rec.py tests/unit/test_g4_injection.py \
       tests/unit/test_g4_no_false_positives.py tests/unit/test_g5_sensitive.py \
       tests/unit/test_g6_identity.py tests/unit/test_g7_redact.py -q
pytest tests/e2e/test_demo_tasks.py tests/e2e/test_rag_only_makes_no_people_calls.py -q   # LLM_PROVIDER=stub
pytest tests/integration/test_fault_mcp_down.py tests/integration/test_fault_unknown_employee.py \
       tests/integration/test_fault_empty_retrieval.py tests/integration/test_fault_ambiguous.py -q
pytest tests/architecture -q          # agent/** imports no hrmosaic.rag.*, no hrmosaic.mcpserver
pytest tests/contract/test_prompt_golden.py tests/contract/test_no_cot.py -q
```
`test_g4_no_false_positives` runs over the **whole committed manifest** and asserts every quarantine
is a canary chunk in `security-acceptable-use` and nothing else is quarantined.

**Parallelism.** After `client.py` + `orchestrator.py` land from one author, G1–G7 split cleanly
across two subagents (G1–G3 answer-shape, G4–G7 safety), and the two workflow specs across a third.
**Commit:** `P7(agent): …`

---

### P8 — `web/`: `/chat`, `/chat/confirm`, SSE, `/health`, `/ready`, chat UI · **M** (4 h) · deps: P7 · no key

**Goal.** The four rubric-named response fields, the live span rail that makes the demo watchable, and
a `/health` that never 5xxs.

**Scope.** `web/main.py` (the written-out lifespan), `web/api.py`, `web/sse.py`,
`web/templates/{base,chat}.html`, `web/templates/partials/`, `scripts/demo_task_1.sh`,
`scripts/demo_task_2.sh`.

**Deliverables.** `POST /chat` with client-supplied ids, the **four-row privileged-options matrix**
(fail-closed on an empty token), and the `trace[]` = all-spans projection; `POST /chat/confirm` as the
**only** `confirm.mint` call site, reopening the same turn; **`tests/architecture/test_mint_sole_caller.py`**
— the §15.1 step-5 / §16.1 assertion that `confirm.mint` is referenced from exactly one module —
**authored here, not at P5**, because `web/api.py` is its only legal caller and it cannot pass before
this phase; `GET /chat/stream` SSE with grace window,
late-subscriber replay, bounded queues and `turn_resumed`; `/health` (always 200) and `/ready`
(503 until warm, with `EMBED_WARMUP=0` opt-out); the chat UI with persona picker, typed answer blocks,
citation chips deep-linking to the corpus browser, confirm card, cold-start banner and two demo buttons.

**Definition of done.**
```bash
pytest tests/contract/test_chat_contract.py tests/contract/test_chat_privileged_options.py \
       tests/contract/test_chat_trace_projection.py tests/contract/test_retrieval_options_reach_the_tool.py \
       tests/contract/test_chat_page_renders.py tests/contract/test_health.py \
       tests/contract/test_missing_key_is_graceful.py -q
pytest tests/integration/test_sse_spans_arrive_before_post_returns.py \
       tests/integration/test_sse_fallback.py tests/integration/test_loopback_concurrency.py \
       tests/integration/test_ready_warms_up.py tests/integration/test_confirm_resume_lifecycle.py \
       tests/integration/test_health_mcp_down.py tests/integration/test_mcp_remote_url.py -q
pytest tests/unit/test_confirm_token_never_leaked.py -q
pytest tests/architecture/test_mint_sole_caller.py -q     # ★ first phase in which this can pass
bash scripts/demo_task_1.sh && bash scripts/demo_task_2.sh   # against a local uvicorn, LLM_PROVIDER=stub
```

**Parallelism.** One subagent for the API + SSE, a second for the Jinja/htmx chat page against the
frozen response schema. **Commit:** `P8(web): …`

---

### P9 — Observability dashboard, 13 pages · **L** (5 h) · deps: P1+P8 · no key

**Goal.** USER.2 and USER.3 in full: every session, turn, LLM call, retrieval, tool call, guardrail
decision and final answer browsable — and the entire evaluation browsable in the same UI.

**Sub-phases (independently committable, and this is R-14's schedule mitigation):**

| Sub | Scope | Pages |
|---|---|---|
| **9a** | `/api/*` endpoints, typed Pydantic view-models, shared table + filter partials, **page 3 first** (the centrepiece the demo depends on) | 3 |
| **9b** | Overview + explorers | 1, 2, 4, 5, 6, 7, 8 |
| **9c** | MCP page (incl. the synthetic maintenance turn), corpus browser, eval pages, compare, metrics; retention job; bounded smoke-eval endpoint | 9, 10, 11, 12, 13 |

**Deliverables.** All 13 routes and their `/api/*` siblings; Chart.js on 1, 11, 12, 13; the page-11
metric panel with the headline aggregate strip and the `Optional[float]` + `judged: bool` +
`n_scored{}` contract; `POST /api/eval/runs` capped at `EVAL_SMOKE_MAX_ITEMS`;
`POST /api/mcp/rediscover`; `POST /api/dev/reset-sandbox` (the archive-preserving two-statement form);
`POST /api/dev/retention` (token-gated, invoking `core/retention.py`'s cascading sweep and returning
rows deleted **per table**) — **all four** §11.6 write controls therefore have an endpoint, so none
ships as the dead control §11.6 forbids.

**Definition of done.**
```bash
pytest tests/contract/test_dashboard_viewmodels.py tests/contract/test_dashboard_pages.py -q
pytest tests/integration/test_reset_sandbox_preserves_archive.py \
       tests/integration/test_smoke_eval_endpoint.py tests/integration/test_retention_endpoint.py -q
pytest tests/integration/test_audit_completeness.py -q     # ★ USER.2's own verification note
```
`test_dashboard_pages.py`'s selector assertions cover **all four** write controls — *Run smoke eval*,
*Re-discover now*, *Reset sandbox*, *Run retention* — asserting each is present, wired to its
endpoint, and rendered disabled-with-tooltip when `DASHBOARD_TOKEN` is unset (§11.6).
`test_retention_endpoint.py` asserts `POST /api/dev/retention` is 401 without the token, returns the
per-table `deleted` counts with it, and leaves every archived and eval-linked session untouched.
`test_audit_completeness` posts a real stubbed turn and asserts the **per-turn, outcome-conditional
span census**, payload completeness for all five named span kinds, the turn record's
`final_answer`/`answer_blocks_json`/`citations_json`, and that `/chat`'s `trace[]` span ids equal the
dashboard payload's (USER.4). Pages 11–13 are built against **committed fixture JSON** so P9 does not
wait on P10.

**Parallelism.** 9b ∥ 9c after 9a lands — two subagents, disjoint templates, one shared partial.
**Commits:** `P9a(dashboard): …`, `P9b(dashboard): …`, `P9c(dashboard): …`

---

### P10 — `evaluation/`: dataset, scorers, judges, runs, ablation · **L** (5 h) · deps: P7 (+P9 for views) · **key #1** (+#8, #9)

**Goal.** All six rubric metric families, a falsifiable ablation, validated judging, and results that
a grader can reproduce offline with no key. **P10 proves the harness end to end in `target: local`
mode; the run that is *published* (and the `comparison.json` beside it) is produced at P11 in
`target: deployed` mode — §13.2 forbids a `local` run reaching `latest.json`, and §13.9 forbids
`comparison.json` mixing targets.**

**Step 0 (before anything else).** Read the live Gemini quotas from
`https://aistudio.google.com/rate-limit` and paste the observed numbers **with the date** into
`deployed.md`.

**Scope.** `evaluation/{dataset.yaml,schema.py,judges.py,deterministic.py,runner.py,ablation.py,
kappa.py,reference_labels.yaml}`, `evaluation/cache/`, `evaluation/results/`,
`scripts/{chunk_size_sweep,gen_ablation_evidence,export_archive,gen_eval_docs}.py`,
`tests/fixtures/traces/`, **`.github/workflows/eval.yml`** (§15.2 — the harness's own dispatch
surface; it lands here, not at P11, because P10's ablation gate is what exercises it).

**Deliverables.** The 26-item dataset (8/5/6/3/3/1) with **absolute dates only**, gold facts resolving
to ledger keys, and the two mirrored workflow items `remote-004` and `pto-003`; every deterministic
scorer including all §13.3/§13.4 edge cases; the four judge prompts through `CachedAdapter`;
the runner with `EVAL_TARGET_BASE_URL`, the three `cold_probe` re-runs and the coldness assertion;
`ablation.py` with the same-target/same-dataset assertion **and** the workflow-moved assertion;
`eval.yml` (`workflow_dispatch` only, the `schedule` block committed disabled) with its `target` /
`variants` / `judge` inputs, the two post-run gates (`cit_resolve_post == 1.00`, the workflow-moved
assertion) and the results-by-PR flow;
`reference_labels.yaml` authored by an **independent Opus subagent** with its `protocol` block;
`kappa.py`; the zero-LLM chunk-size sweep; `export_archive.py` producing `data/archive/eval_traces.jsonl`;
the golden trace fixtures (≥ 1 carrying `mock_writes` + `llm_messages` + `pending_actions`);
`MIN_EVIDENCE_SCORE` calibrated from the observed distribution; one **real** provider exchange per
demo task recorded as a stub fixture (R-13).

**Definition of done.**
```bash
pytest tests/unit/test_dataset.py tests/unit/test_scorer_edge_cases.py \
       tests/unit/test_cold_probe_excluded.py tests/unit/test_run_id.py \
       tests/unit/test_eval_ordering_deterministic.py -q
pytest tests/unit/test_action_safety_gate.py -q                  # must be 1.0
pytest tests/integration/test_eval_replay_from_cache.py -q       # offline, keyless, byte-identical .deterministic.json,
                                                                 # >=1 judge-purpose cache hit, back-dated entry still served
EVAL_TARGET_BASE_URL=http://127.0.0.1:8000 python evaluation/ablation.py   # ★ target: local — all three
                                                                 # variants local; committed as DETERMINISM evidence
                                                                 # only, never promoted to latest.json (§13.2).
                                                                 # Asserts same target + dataset_sha; workflow-moved
python scripts/chunk_size_sweep.py
python evaluation/kappa.py                                       # reference-vs-judge Cohen's kappa reported
```
Plus the post-run gate `cit_resolve_post == 1.00` over items with ≥ 1 citation, with
`blocks_dropped_by_g2` reported separately.

**Parallelism.** Dataset authoring ∥ scorer implementation ∥ reference-label authoring (the labeller
**must** be a separate session, blind to judge output, for the κ claim to be honest).
**Commit:** `P10(eval): …`

---

### P11 — Deployment · **S** (3 h) · deps: P9+P10 · **keys #2, #3, #4**

**Goal.** A live, shareable, $0 URL whose CI-gated deploy is provable, plus the single `deployed`-mode
`eval.yml` dispatch that supplies every published figure — headline metrics *and* the ablation.

**Step 0.** Re-verify in the live dashboards and paste the observed values **with dates** into
`deployed.md`: Render (Docker on Hobby, bandwidth, build RAM, **and the documented HTTP request/idle
timeout**) and the Turso free-tier figures. **Cap `AGENT_WALL_CLOCK_S` below the observed Render
timeout**; if that timeout is < 90 s, ship the documented `202 Accepted` + SSE fallback.

**Scope.** `Dockerfile`, `render.yaml`, `.github/workflows/ci.yml` (`docker`, `fresh-clone`, `deploy`
jobs), `scripts/{provision_render,provision_turso,wait_for_deploy,
smoke_deployed,check_render_hours,measure_cold_start}.py`, `docs/evidence/`.
(`.github/workflows/eval.yml` itself lands at **P10**; P11 *dispatches* it.)

**Deliverables.** The single-stage Dockerfile (`sh -c` CMD for `${PORT}`, `PYTHONPATH=/app/src:/app`,
`ARG GIT_SHA`, model baked, index built with `--verify-manifest`, index self-test); `render.yaml`;
unattended provisioning of Render + Turso + all `gh secret set` calls; **one `eval.yml` dispatch with
`target: deployed` covering all three variants** (`baseline` judged; `dense_only_k2` and
`no_structured_tools` deterministic-only, per §13.9's quota scoping) incl. the three `cold_probe`
re-runs — this single dispatch is what produces `latest.json` **and** `comparison.json`, so §13.9's
same-target assertion holds by construction; `export_archive.py` against the two recorded
demo sessions → `data/archive/demo_traces.jsonl`; measured cold-start numbers; the **three evidence
screenshots** captured by Claude Code with the browser tool and committed under `docs/evidence/`.

**Definition of done.**
```bash
docker build -t mosaic . && docker run -m 512m -p 8000:8000 mosaic   # /ready 200 -> one turn -> rss_mb < 420
docker run -m 512m -e PORT=10000 -p 10000:10000 mosaic               # /health mcp.connected == true
python scripts/smoke_deployed.py "$DEPLOYED_URL"                     # 200, mcp.connected, git_sha != "dev",
                                                                     # archive_manifest_sha matches local
python scripts/measure_cold_start.py "$DEPLOYED_URL"
gh api repos/seantmalone/quantic-mosaic/branches/main/protection | jq '.required_status_checks.contexts'
ls docs/evidence/ci-deploy-skipped.png docs/evidence/mcp-discovery-page.png docs/evidence/mcp-discovery-4-tools.png
```
Plus, on the eval dispatch itself:
```bash
python evaluation/ablation.py                                        # green: same config_json.target + dataset_sha
                                                                     # across all three runs; workflow-moved assertion
jq -r '.runs[].config_json.target' evaluation/results/comparison.json  # "deployed" x3, no other value
```
Plus: `latest.json` names a `target: deployed`, `variant: baseline` run; that run produced rows with
**non-null `sessions.eval_run_id`** (proving the eval token was configured); and the R8.4 evidence
pair exists — a failing PR to `main` (genuinely unmergeable under branch protection) **and** a
`workflow_dispatch` run on `main` with `FORCE_TEST_FAILURE=1` whose deploy-job skip reason reads
**"dependent job failed"**, not "if condition not met".

**Parallelism.** None (a single deploy identity; concurrent provisioning would race).
**Commit:** `P11(deploy): …`

---

### P12 — Documentation, demo prep, publish · **M** (4 h) · deps: P11 · no key

**Goal.** Every graded document present, generated where possible, and asserted by a test — plus a
time-boxed demo script that ticks every DEMO.* item.

**Scope.** `README.md`, `design-and-evaluation.md`, `ai-tooling.md`, `deployed.md`,
`NEEDS-FROM-USER.md`, `static/vendor/LICENSES.md`, `docs/demo-script.md`, the pre-submission checklist.

**Deliverables.** README's four headings + `## Third-party components` + the three link lines with the
placeholders **retired**; `design-and-evaluation.md` with the mermaid diagram (all seven components),
the **ten `###` R10.1 justification subsections**, **all eight `##` DOCS.3 subjects** (8a and 8b
generated by `gen_eval_docs.py`), the facts/sources/confidence table, the judge-validation methodology
naming the labeller, both κ values, the rejected alternatives and both demo sequences;
`ai-tooling.md` with `## What worked well`, `## What did not work` and the DOCS.9 ownership
disclosure; `deployed.md` with all five required headings; the timed demo script including the
standing webcam-overlay production note.

**Definition of done.**
```bash
python scripts/gen_tool_schemas.py && python scripts/gen_eval_docs.py && python scripts/corpus_stats.py
git diff --exit-code                                        # docs-check: zero drift
pytest tests/contract/test_docs_completeness.py -q          # 10 R10.1 + 8 DOCS.3 + README + deployed.md x5 + LICENSES
grep -c 'TBD-before-submission' README.md                   # must be 0
bash scripts/demo_task_1.sh "$DEPLOYED_URL" && bash scripts/demo_task_2.sh "$DEPLOYED_URL"
```
**Final step of the whole build:** after the eval-results PR is merged, dispatch `ci.yml` with
`deploy_only: true` and verify the live `/health.trace_store.archive_manifest_sha` equals the locally
computed manifest sha — `paths-ignore` means the merge itself triggers nothing.

**Parallelism.** Three subagents, one document each (`design-and-evaluation.md` is the long pole).
**Commit:** `P12(docs): …`

---

## 5. Gates requiring the user

Seven tracked gates. **G1 is fully scripted and needs nothing from the user** (§19.1 item 5), so six
actually reach a human: **five are a single paste or click taking under 10 minutes, and G7 (record +
submit) is the one substantial human task, budgeted at 60–90 minutes including retakes** — the only
irreducible human bottleneck in the plan, to be scheduled rather than squeezed in. (G6 is under
10 minutes for items #8–#10; its *optional* item #11 adds ~20 minutes of label adjudication, §19.2.)
**Nothing in P0–P9 blocks on any of them** — the build never idles.

| Gate | When requested | When actually needed | What Sean does (time) | What Claude Code does while waiting |
|---|---|---|---|---|
| **G1 — Repo public + `quantic-grader`** (§19.1 item 5) | **P0** | pre-submission (invite) | **Nothing.** The repo is already public (verified 2026-09-08), so there is no visibility change. The grader invite is scripted: `gh api -X PUT repos/seantmalone/quantic-mosaic/collaborators/quantic-grader`, run by Claude Code on the already-authenticated gh 2.96 session at **P12**. The grader's side (**accepting the invite**) is a person's action and is folded into **G7**. | Re-asserts `gh api repos/seantmalone/quantic-mosaic \| jq .private` → `false` at P0; sends the invite at P12 and reads back `gh api repos/seantmalone/quantic-mosaic/collaborators/quantic-grader/permission`. |
| **G2 — Render account + install the Render GitHub App** (item 2) | **P0** | **P11** | Open `https://github.com/apps/render/installations/new`, sign in / sign up (no card), grant access to `seantmalone/quantic-mosaic`. Browser-only: **no API can install a GitHub App**. | P0–P10 in full. `make docker-run` proves the exact image locally under `-m 512m` with no host at all. |
| **G3 — Turso account + Platform API token** (item 3) | **P0** | any time after **P1**; hard-needed at **P11** | `https://turso.tech` → GitHub SSO (no card) → create a **Platform API token** → paste to Claude Code. | `scripts/provision_turso.py` then does database creation, scoped-token minting, `gh secret set` and Render env-var population unattended. Until then `SqliteStore` + the committed archive are the fallback. |
| **G4 — Google AI Studio key → `LLM_API_KEY`** (item 1) | **P0** (so P6's gate can run early) | **P6 gate** (deferrable) / hard at **P10** | `https://aistudio.google.com/apikey` → sign in → *Create API key* → paste to Claude Code. Free, no card. | P0–P9 build and pass CI entirely on `LLM_PROVIDER=stub`. If it arrives late, P6 ships the prompted-JSON fallback and the live gate runs at P10 step 0. |
| **G5 — Render API key** (item 4) | **P10** | **P11** | Render dashboard → Account Settings → API Keys → *Create* → paste. | `provision_render.py` then creates the service, populates env vars, reads back the deploy hook and sets every GH secret. Fallback: ~15 min of manual Blueprint clicking per iteration. |
| **G6 — Optional upgrades** (items 8–11) | **P10** | before **P10**'s judged run (8, 9, 10); before **P12** (11) | *(~6 min for #8–#10; **+~20 min** for #11)* #8 Groq key (`https://console.groq.com/keys`, ~2 min) · #9 second Gemini key from a *different* Cloud project (~2 min) · #10 Anthropic key (~$5) · #11 ~20 min adjudicating 8 groundedness labels. | Each has a documented degradation: judge stays in-family (κ still published, named *reference-vs-judge*); judged metrics stay scoped to `baseline`; `AnthropicAdapter` stays MockTransport-tested; labels stay model-authored **and are named as such**. |
| **G7 — Record the demo + submit** (items 6, 7) | **P12** | after **P12** | **★ Budget 60–90 min** (7–10 min of footage, plus setup, retakes, upload and submission — the one gate that is not a single paste). Accept the `quantic-grader` collaborator invite (G1's scripted half already sent it). Follow `docs/demo-script.md` (7–10 min, webcam overlay throughout, ID held ≥ 3 s at ~0:15, both tasks one-click). Then paste the video link into `README.md`'s `Demo video:` line and submit the two links via the Quantic dashboard. | Pre-stages both link lines at the top of `README.md`; warms both demo prompts through the cache; verifies the live URL, the dashboard and the eval pages; runs the pre-submission checklist. |

**`NEEDS-FROM-USER.md`** is created at P0 with the **minimum viable set stated at the top — one
Google AI Studio key, a Render account, a Turso token, all free and card-free** — and is updated at
every phase boundary. **It carries a time estimate per gate**, so the user can schedule the only
substantial one: G2–G5 at ~2–5 minutes each, G6 at ~6 minutes (+~20 for optional item #11), and
**G7 at 60–90 minutes** (recording, retakes, upload, submission). G1 is listed as *scripted — no
user action*, with the grader-invite acceptance folded into G7. This file is USER.1's mechanical
artifact, and "stays minimal" is measured against it.

---

## 6. Verification strategy

### 6.1 Per phase

| Phase | Primary verification instrument |
|---|---|
| P0 | Lint + empty-suite CI green on push **and** PR; `.env.example` ↔ `Settings` bijection; vendored-asset sha256; branch-protection API read-back |
| P1 | Store parity across both backends; **AST sole-writer** over `src/**` and `evaluation/**`; archive round-trip / idempotency / update; cascading-retention orphan check; process-exit recovery; the three dated R-1 measurements in `CHANGELOG.md` |
| P2 | `git diff --exit-code corpus/` after regeneration; ledger resolution over scoped numerics; `round(measured) == stated` pages; canary-in-exactly-one-chunk |
| P3 | JSON-Schema validation; PII grep; generator byte-idempotency; **anchor ids `E1002`/`E1007`/`E1042`/`E1108` present and all 24 matching `^E1[0-9]{3}$`**; PTO arithmetic at the frozen clock; accrual-band cross-check for all 24 employees |
| P4 | Byte-identical chunk manifest; **the `query_embed` asymmetry gate**; dense-score scale; `min_dense_score` ≠ `rrf_score`; exact-`k` filter-then-truncate; per-format ingest report |
| P5 | MCP 2.x API shape; `REQUIRED_TOOL_NAMES ⊆ tools/list`; discovery + call on **both** transports; token-free `CONFIRMATION_REQUIRED`; `FORBIDDEN_IDENTITY` incl. tool 4; generated schemas diff-clean; async-handler AST |
| P6 | Both wire shapes normalised; exactly one span per call; limiter burst + shared bucket; strict-schema emission; cache-key stability across days; **live provider probe** |
| P7 | Seven guardrail suites; four fault injections at HTTP 200; both demo sequences under the stub; RAG-only makes zero people-tool calls; no-CoT; import boundaries |
| P8 | `confirm.mint` sole-caller AST test (first phase where it can pass); `/chat` contract for RAG-only **and** tool-using; four-row privileged-options matrix; `trace[]` = spans-of-turn + the R4.3 six-element mapping; SSE-before-POST-returns; loopback concurrency; confirm resume lifecycle; keyless graceful degradation |
| P9 | View-model schema contracts (incl. page 11's `judged: bool` / `n_scored{}`); page renders; all **four** §11.6 write controls present, wired and disabled-with-tooltip when the token is unset; **`test_audit_completeness`** round trip; reset-sandbox preserves the archive; retention endpoint token-gated and archive-safe; smoke-eval endpoint against the built image |
| P10 | Dataset shape + no relative dates; every scorer edge case; **action-safety gate = 1.0**; offline keyless replay byte-identity incl. a judge-purpose hit; ablation same-target + workflow-moved assertions; κ |
| P11 | `docker run -m 512m` RSS < 420 with the model resident; injected-`PORT` health; live smoke incl. `git_sha != "dev"` and `archive_manifest_sha`; non-null `sessions.eval_run_id`; the R8.4 evidence pair; three committed screenshots |
| P12 | `docs-check` zero-diff across three generators; ten `###` + eight `##` headings; README link lines with no placeholder; `deployed.md`'s five headings; `LICENSES.md` completeness; both demo scripts against the live URL |

**Which phase wires which §15.1 `test` step.** Job `test` has **20 ordered steps** (`1, 1b, 2–19`,
with `7c` between 7 and 8 — §15.1). P0 lands the first four; every other step is added by the phase
that introduces its tests, in that phase's own commit:

| §15.1 step(s) | What it runs | Added by |
|---|---|---|
| 1, 1b, 2, 3 | install; fastembed model cache + conditional download; `ruff`; `gitleaks` | **P0** (skeleton) |
| 6 | `pytest tests/unit` | **P0** creates the step (`test_vendor_asset_hashes`); **every later phase extends the suite in place** |
| 13 | `pytest tests/contract` | **P0** creates the step (`test_env_example_covers_settings`, `test_docs_completeness`); extended in place by **P5, P8, P9, P12** |
| 5 | `pytest tests/architecture` | **P1** creates the step (sole span writer, clock sole-caller); extended in place by **P4** (embed call site, no `parallel=`), **P5** (async handlers, no `mcp/__init__.py`, mock-writes ownership), **P7** (import boundaries), **P8** (`test_mint_sole_caller.py` — see P5/P8 below) |
| 14 | `pytest tests/integration` | **P1** creates the step (archive round-trip, retention, process-exit); extended in place by **P5, P7, P8, P9, P10** |
| 17 | corpus + data checks (`corpus_stats`, `check_facts`, topic map) | **P2**; **P3** adds `pii_check.py`; **P7** adds `test_g4_no_false_positives` over the committed manifest |
| 7, 7c, 8 | chunk-manifest determinism; full-corpus index provisioning; mini-corpus ingest smoke | **P4** |
| 4 | `test_mcp_api_shape` | **P5** |
| 10, 11 | MCP discovery (stdio) and tool call (stdio + mounted HTTP) | **P5** |
| 16 | `pytest tests/e2e` under `LLM_PROVIDER=stub` | **P7** |
| 9, 12, 19 | `test_app_starts`; `test_mcp_remote_url`; the RSS-with-model-resident gate (all three need a bootable `web/` app) | **P8** — P1 owns the `rss_mb` reader itself (`test_rss_reader`, step 6) |
| 15 | action-safety gate + `test_confirm_token_never_leaked` | **P8** authors `test_confirm_token_never_leaked`; **P10** wires the step, because the gate scores over `tests/fixtures/traces/`, `evaluation/results/*.deterministic.json` and `data/archive/*.jsonl`, none of which exist before P10 |
| 18 | `docs-check` | **P12** |
| jobs `docker`, `fresh-clone`, `deploy` | — | **P11** |

A phase whose row is empty for a step must not add that step early: a step whose test does not yet
exist turns the push path red for every phase in between (see P5 ↔ P8 on `test_mint_sole_caller.py`).

### 6.2 Continuous (every phase, every push)

`ruff` · `gitleaks` over full history · `tests/architecture` · the growing unit/contract/integration
suites · `docs-check` · the **action-safety 1.0 gate** · RSS < 420 MB with the model resident.
Everything on the push path is **key-free, deterministic, and offline after the first cache fill**.

---

## 7. End-to-end acceptance checklist (mirrors the rubric level-5 bullets)

Signed off in P12 before submission. Each row names the artifact a grader can open.

| # | Rubric level-5 bullet | Passes when | Artifact |
|---|---|---|---|
| 1 | Outstanding deployed agentic HR system with cited, grounded responses | Groundedness ≥ 0.92 mean; `cit_resolve_post` = 1.00 over items with ≥ 1 citation; run-level `cit_resolve_pre` ≥ 0.95; ≥ 0.90 strict-pass — **all from the single `deployed` baseline run** | `evaluation/results/<run_id>.deterministic.json` + `latest.json` + dashboard pages 11–12 |
| 2 | MCP fully functional, clear traces, graceful errors | 9 tools discovered via real `tools/list`; every turn's `tools/call` on the wire; 4 fault-injection tests green | `mcp_discovery` + `tool_call` spans; `/dashboard/mcp`; `docs/evidence/mcp-discovery-page.png` |
| 3 | Two end-to-end agentic tasks, multi-step, RAG + mock data | Each ≥ 4 tool calls, ≥ 1 retrieval, ≥ 1 structured-data tool; task 2 writes behind a confirmation gate | `tests/e2e/test_demo_tasks.py` (two per-task expectation records) + `data/archive/demo_traces.jsonl` + the video |
| 4 | Excellent RAG ingestion, indexing, retrieval, citations, guardrails | Byte-identical rebuild; hybrid retrieval; 7 guardrails green; tuned `k` demonstrated | `test_chunking_deterministic`, guardrail suites, `dense_only_k2` + `chunk_size_comparison.json` |
| 5 | Excellent architecture, clear separation | Six components in six packages, **zero cross-layer imports** | `tests/architecture/test_import_boundaries.py` + the mermaid diagram |
| 6 | Free-tier deployment fully functional, env vars + cold start documented | Live URL 200; `/health` + `/ready`; every env var in `.env.example` **and** `deployed.md`; measured cold/warm numbers | `deployed.md`, `render.yaml`, `scripts/measure_cold_start.py` |
| 7 | CI/CD on push/PR with build/start + MCP tests, deploy gated | Green on both events; `test_app_starts`; `test_mcp_tool_discovery`; `deploy` declares `needs: [test, docker]`; a recorded red run with deploy skipped for **"dependent job failed"** | `gh run list`; `docs/evidence/ci-deploy-skipped.png` |
| 8 | Excellent evaluation across all six metric families | 26 items; groundedness, citation accuracy, tool selection, workflow completion, escalation/safety, latency p50/p95 cold vs warm; ablation; κ | `evaluation/results/`, `evaluation/REPORT.md`, dashboard pages 11–13 |
| 9 | Excellent docs + demo meeting every DEMO.* item | `docs-check` green; video 7–10 min, on camera throughout, ID shown, both tasks live, design/deploy/CI/eval walkthroughs | `design-and-evaluation.md`, `README.md`, `ai-tooling.md`, `deployed.md`, the video link |
| 10 | **USER.2/3/4** — full audit logs + eval in the dashboard, one trace model | Every record type present for a freshly executed chat; all six metric families + cold/warm p50/p95 + ablation browsable; `/chat` trace, dashboard and eval report derive from one `trace_id` | `test_audit_completeness`, `test_dashboard_viewmodels`, `/dashboard/sessions/{id}` |
| 11 | **USER.1** — autonomous buildability | `NEEDS-FROM-USER.md` lists only the seven human gates; every other step is a scripted command; CI reproduces build → index → test → eval with no manual step | `NEEDS-FROM-USER.md`, `.github/workflows/*.yml` |

---

## 8. Risk register (triggers and fallbacks)

Severity and mitigation follow §20 of the spec. **"Trigger"** is the observable signal that the
fallback must be taken; **"Fallback"** is decided now, not at the moment of failure.

| # | Risk | Sev | Trigger (observable) | Fallback (pre-decided) | Owner phase |
|---|---|---|---|---|---|
| R-1 | Memory/CPU figures are macOS inferences, not Linux cgroup measurements | **High** | P1's `docker run -m 512m` RSS ≥ 420 MB with the model resident, **or** the `--cpus 0.1` six-tool-call turn exceeds ~30 s | Memory: drop `EMBED_WARMUP` default to 0 and lazy-load; if still over, move embeddings to the Gemini embedding API (one extra key, documented). CPU: raise `AGENT_WALL_CLOCK_S` toward the Render timeout and adopt the `202 Accepted` + SSE pattern; reduce `AGENT_MAX_STEPS` to 4 | P1 |
| R-2 | `mcp` 2.2.0 is a breaking rewrite; model priors target 1.x | **High** | `test_mcp_api_shape` red, or `ImportError: FastMCP` | Pin `mcp==2.2.0`; the P5 subagent reads `mcp/README.md`'s 1.x→2.x mapping **before** writing code; the shape test fails in seconds rather than at integration | P5 |
| R-3 | fastembed footguns (default batch → 1477 MB; `parallel=1` hangs) | **High** | RSS spike during ingest, or an ingest run exceeding 600 s | Hard-coded `batch_size=8`, `threads=1`, **never** `parallel=`; two AST tests enforce it permanently; ingestion runs on the 8 GB builder so a regression cannot OOM runtime | P4 |
| R-4 | Ephemeral disk vs "full audit logs for EVERY session" | **High** | Turso credentials absent at P11, or `/health.trace_store.backend == "sqlite"` in production | `SqliteStore` + the boot-imported committed archive (~80 drillable sessions incl. both demo tasks and all three eval variants); UI labels live sessions *"session-scoped on the free tier"*; `deployed.md` states exactly which part of USER.2 is then unmet | P1 / P11 |
| R-5 | Free-tier quota exhaustion mid-eval or live on camera | **High** | HTTP 429 with `Retry-After`, or `eval_runs.notes` accumulating 429s | Judged metrics scoped to `baseline` (~700 calls/day); content-addressed cache + committed replay JSONL make re-runs free; sequential execution behind the limiter; failover to Groq recorded as `provider_failover`; **both demo prompts cache-warmed and narrated honestly via the `cache_hit` badge** | P10 / P11 |
| R-6 | Judge credibility (agent and judge share the Gemini family) | Medium | — (standing) | 7 of 9 metrics are judge-free; 8 reference labels authored by an independent Opus subagent in a **different family**, blind to judge output, reported as *reference-vs-judge* κ; `GROQ_API_KEY` adds a cross-family re-judge; optional item #11 upgrades to human adjudication | P10 |
| R-7 | AI-authored corpus drifts into vagueness or contradiction | **High** | `check_facts.py` red, or an eval item's gold contradicting a cited chunk | The fact ledger is the single authoring point for every number; corpus, rules and gold all derive from it; ≥ 6 checkable `required_facts` per document | P2 |
| R-8 | Untyped Jinja/htmx boundary across 13 pages | Medium | A dashboard page rendering with a missing field, green tests notwithstanding | Every page renders from a typed Pydantic view-model produced by the same `/api/*` endpoint; pages 2/4/5/6/7/8 are thin configurations of one shared partial; **page 3 is built first** | P9 |
| R-9 | Platform/provider facts partly unverified (Render, Gemini limits, Turso) | Medium | A `[medium]` claim contradicted by the live dashboard at P10/P11 step 0 | Every such claim is tagged and reproduced in the facts/sources/confidence table; **P10 step 0 and P11 step 0 read the live values and paste them with dates**; documented host fallbacks: native Python service on Render, then Google Cloud Run (same image) | P10 / P11 |
| R-10 | 750 instance-hours/workspace/month exhaustion suspends *all* free services | Medium | `check_render_hours.py` projecting > 600 h month-to-date | One service only; **no keep-alive cron**; CI warns (never fails) above 600 h, leaving 150 h margin | P11 |
| R-11 | Autonomous-build drift across 13 phases and many subagents | **High** | A second logging path appearing; `docs-check` diffing; a demo sequence silently changing | Trace built in P1 with a sole-writer AST test; the standing per-phase span criterion; docs turned into tests (`gen_tool_schemas`, `gen_eval_docs`, `corpus_stats` all diff-checked); `test_demo_tasks` compares actual against documented sequences | all |
| R-12 | Public `/mcp-server/mcp` endpoint | Low | An unexpected `tools/call` in the trace store from an unknown actor | Read tools expose only synthetic data; identity binding; the HMAC gate (unforgeable without `CONFIRM_SECRET`, never leaked in a rejection); `Host`/`Origin` allowlist + per-IP rate limit as middleware — **with the SDK capability verified before P5, not assumed** | P5 |
| R-13 | Stub-vs-real divergence hiding a prompt regression | Medium | A real `eval.yml` run failing on tool-call shape while `tests/e2e` is green | One **real** provider exchange per demo task recorded as a fixture at P10 (the stub becomes a recording); the golden prompt snapshot forces deliberate re-review on any prompt change | P10 |
| R-14 | Schedule risk in the late phases (dashboard, eval, docs) | Medium | P9 or P10 running materially over its estimate | Smallest-scope approach (~51 h); every phase ends green and committed so partial progress ships; **P9 splits into 9a/9b/9c**; pages 11–13 render committed fixture JSON so they precede P10; P0–P9 need no credentials so no phase blocks on a human | P9 / P10 |
| R-15 | Over-refusal from a mis-tuned evidence threshold | Medium | `OverRefusalRate` > 0.10 on the baseline run | `MIN_EVIDENCE_SCORE` **calibrated at P10** from the observed score distribution rather than guessed; over/missed-refusal are first-class metrics beside a 5-class confusion matrix; the threshold is env-configurable so the ablation can move it | P10 |
| R-16 | **Python 3.14.6 on the dev machine vs the 3.12 pin** | Low | A package failing to resolve, or `settings.py`'s version warning firing locally | The pin is enforced in three places (README's `python3.12 -m venv`, CI's `python-version-file`, the runtime warning); `uv` manages 3.12.14 locally; the `fresh-clone` CI job runs the README commands verbatim on a clean runner | P0 |
| R-17 | **sqlite-vec loadable extensions unavailable on `python:3.12-slim`** | Medium | P1's probe failing `enable_load_extension` / `vec_version()` | The **NumPy brute-force vector backend** (~40 lines, same `retrieve.py` interface, `index_meta.vector_backend='numpy'`, parity-tested) — a config branch, never an architecture re-decision | P1 / P4 |

---

## 9. Cross-references

- **Design truth:** `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`
- **Requirement → phase → verification:** `docs/requirements-traceability.md`
- **Human gates, live checklist:** `NEEDS-FROM-USER.md` (created at P0)
- **Per-phase landing log + dated measurements:** `CHANGELOG.md`
