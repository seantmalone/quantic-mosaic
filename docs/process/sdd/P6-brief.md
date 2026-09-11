# Phase brief: P6

## Spec sections to read first (authoritative): §9.8 provider abstraction (the model allocation table, AnthropicAdapter shape, caching, cost accounting, spend guard), §3 rows 5–7, §10.2 llm_call payload and llm_messages, §12.3 (LLM_*, ANTHROPIC_API_KEY, JUDGE_*, LLM_FALLBACK_*, LLM_DAILY_CALL_CAP), §16 — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P6.

## Standing brief (roadmap §2.2, adapted: you DO commit locally, you never push)
### 2.2 The standing subagent brief (prepended to every phase dispatch)

```
Read docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md sections: <list>.
That spec is authoritative; do not redesign. Implement exactly what it specifies.
Write ONLY the files named in your deliverables list. Commit locally on the current branch using the commit pattern below; never push; never touch .env.
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

## Standing acceptance criterion (from P4 onward)
### 2.3 Standing acceptance criterion (from P4 onward)

> *The expected spans were persisted, with the expected kinds and payload shapes.* — checked in every phase gate from P4 on; it is what stops a later
> subagent inventing a parallel logging path, the failure USER.4 forbids.


## Commit pattern (roadmap §2.4)
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


## How CI grows (roadmap §3 excerpt)
**How CI grows.** P0 lands `.github/workflows/ci.yml` with jobs `lint` and `test` in their final shape apart from three data steps whose scripts do not
exist yet: **P2** adds `python scripts/check_facts.py`, **P3** adds `python scripts/pii_check.py`, **P4** adds `python -m hrmosaic.rag.ingest
--verify-manifest`, and **P11** adds the `docker` and `deploy` jobs with the `Dockerfile` and `render.yaml`. That is four one-line edits by the phase
that creates the artifact — not a step-ownership table (spec §22 row 14). Every phase's tests reach CI with no workflow edit at all, because the `test`
job's test step is `pytest -q` over the whole suite.

---

## The phase (roadmap §4, verbatim)
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

