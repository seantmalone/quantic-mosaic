# Phase brief: P8

## Spec sections to read first (authoritative): §11 (the access gate and personas lead-in, 11.1 /chat, 11.2 /chat/confirm, 11.3 /chat/stream, 11.4 /health and /ready, 11.5 chat UI, 11.8 endpoint list), §8.6 confirmation gate (web mints tokens), §10.3 turn lifecycle, §17 (access, identity, DoS rows), §18 — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P8.

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

