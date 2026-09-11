# Phase brief: P5

## Spec sections to read first (authoritative): §8 (all: transport, discovery, errors, the nine tools, mock actions, the confirmation gate, trace/actor propagation), §4.1 the mcp/ shadowing hazard, §7.1 retrieval inside search_policy_documents, §10.2 tool_call/retrieval payloads, §17 — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P5.

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

