# P8 report — `web/`: `/chat`, `/chat/confirm`, SSE, `/health`, the access gate, the chat UI

**Status:** DONE_WITH_CONCERNS · **Base:** `ca13389` · **HEAD:** `585293d2aafbcfc5d118345ea8aca9f82eace6d7`
**Suite:** 1075 passed in 116 s, pristine (was 927 at `ca13389`; **+148 tests**). `make lint` green.

Three commits, all local, nothing pushed:

| sha | subject |
|---|---|
| `b7b5fa7` | `P8(agent): fix: three live-only loop defects the stub could not show` |
| `65d7455` | `P8(web): the contract endpoints, the access gate, the SSE rail and the chat UI` |
| `585293d` | `P8(web): fix: a resumed turn keeps its own seq, and the act-as selector reloads` |

---

## 1. What was built

### 1.1 `src/hrmosaic/web/` (1 516 lines incl. templates and CSS)

**`main.py`** — `create_app(settings)` plus the module-level `app` uvicorn serves. The lifespan owns,
in this order, exactly what the carry-forwards named:

1. `trace.install_shutdown_handlers()` on the **main thread** (P1's carry-forward);
2. `get_store()` + `migrate()` + the one process-wide `TraceWriter`;
3. a maintenance task: `sweep_stale_turns()` → `retention.sweep()` → `archive.import_results()` with a
   **stable absolute path** (`REPO_ROOT/evaluation/results`, resolved), repeating every 6 h
   (`MAINTENANCE_INTERVAL_S`);
4. `broker.bind(loop)` and **one** `core.trace.register_span_listener()` registration (§11.3);
5. the `Orchestrator`, built once so the MCP handshake outlives a request, with
   `Authorization: Bearer` on its client whenever the gate is on;
6. the `/ready` warm-up — **one loopback `tools/call`** (`search_policy_documents`) inside a
   `client_label='maintenance'` session whose turn closes `outcome='maintenance'`.

The warm-up runs as a **background task**, not inline in the lifespan: uvicorn does not create its
listening socket until lifespan startup has returned, so a loopback call made inside the lifespan is
refused by a socket that is not listening yet. It polls `client.discover()` until the handshake
succeeds (bounded by `READY_WARMUP_TIMEOUT_S`) and then makes exactly one recorded call.

Teardown closes the broker, unregisters the listener, cancels both tasks, closes the MCP client,
flushes open turns and clears the process-wide orchestrator. FastAPI's three documentation routes
are disabled (`docs_url=None, redoc_url=None, openapi_url=None`) so the served route table is
**exactly** §11.8's list — `tests/contract/test_app_starts.py` asserts set equality.

**`api.py`** — the gate, the personas and every route P8 owns.

* `AccessGateMiddleware` is **pure ASGI**, not `BaseHTTPMiddleware`: it has to cover the mounted MCP
  endpoint and `/chat/stream`, both of which stream, and a middleware that wraps the response body is
  a new way for either to stall. It either short-circuits with a `Response` or hands the untouched
  scope on, writing the resolved `Identity` into `scope["state"]`.
* Three presentations, in §11's order, each `hmac.compare_digest`-compared: `?access=` on a gated GET
  → **302** to the same path with the parameter stripped (other parameters preserved) and
  `Set-Cookie: mosaic_access` (HttpOnly, SameSite=Lax, Path=/, Max-Age 30 d, `Secure` only on https);
  then the cookie; then `Authorization: Bearer`. Mismatch or absence → **401** and the key page (HTML
  when the caller accepts it, `{"code": "ACCESS_REQUIRED"}` otherwise — the MCP SDK asks for
  `application/json, text/event-stream`, so Inspector gets JSON).
* `APP_ENV=render` with no token → **403** `ACCESS_TOKEN_MISSING` on every gated route, and
  `access_token_missing` in `/health.degradations` — the fifth and last string.
* Personas: `X-Actor` beats the `mosaic_actor` cookie; malformed or absent → `E1042`. `/dashboard/*`
  and `/api/*` are **403** `{"code": "ADMIN_REQUIRED"}` outside the admin persona.
* `RateLimiter`: a per-IP 60-second sliding window on `POST /chat` and the MCP mount only, keyed by
  client address, dropping a key when its window empties so a long-lived instance does not accumulate
  one entry per visitor.
* `POST /chat` — a `ChatBody` that is **exactly §11.1's client-supplied half**. It is deliberately not
  `ChatRequest`: `ChatRequest` carries `auth_mode`, `actor_role` and `actor_source`, so a request model
  that accepted them from the wire would let any caller declare itself an admin. `web/` fills those in
  from the resolved `Identity`. Ids are validated (32-hex) and a reused `turn_id` is **409**.
* `POST /chat/confirm` — **the only place a token is minted**. It finds the turn's pending
  `confirmation` span, checks `expires_at`, walks `parent_span_id` to the **gated `tool_call` span**,
  and mints from that span's raw `arguments` (P5's carry-forward: the wire arguments, never
  `arguments_preview`, a display subset). Confirm → `trace.reopen_turn()` then
  `orchestrator.resume_turn()`; Cancel → the same row minted with `user_response="declined"`, a
  **second** `confirmation` span emitted through `core/trace.py`, and the turn closed
  (`outcome="refused"`, `stop_reason="declined"`) without resuming.
* `GET /chat/stream`, `GET /health`, `GET /ready`, `GET`/`POST /access`, `POST /access/logout`,
  `POST /session/actor`, `GET /api/traces/turns/{turn_id}` (admin-only, the shape the 202 fallback and
  the demo scripts poll).

**`sse.py`** — `SpanBroker`: `subscribe` / `publish` / `stream`, a 15-second heartbeat, bounded
per-subscriber queues (a browser that stopped reading loses frames, never the turn), `loop.call_soon_threadsafe`
so a span closed on a worker thread still reaches the loop, and a `close()` the lifespan calls so a
long-lived response cannot hold uvicorn's graceful shutdown open. Frames are built with
`orchestrator.summarise_span` / `preview_value`, so the live rail and `trace[]` describe a span
identically — `test_sse.py` asserts frame-by-frame equality against the POST response's `trace[]`.

### 1.2 The chat UI

One Jinja page plus a turn fragment and the key page, one hand-written stylesheet, vendored htmx, and
about 70 lines of vanilla JS. It carries every element §11.5 names: the act-as `<select>` over the 24
mock employees plus **HR admin**, typed answer blocks with the literal
*"Recommendation — not company policy"* badge, citation chips whose `href` is the chunk's
`source_url`, a citation drawer with the snippets, the *"Employee data as of 1 September 2026"*
snapshot note under any `as_of`-bearing turn, the live SSE rail, the Confirm / Cancel card showing the
exact `human_summary` and `arguments_preview`, the cold-start banner with an elapsed counter, both
one-click demo buttons, and a dashboard nav link rendered only in the admin persona (the server check
is the control).

The UI generates `turn_id`, opens `GET /chat/stream?turn_id=…` **first** and only then fires the POST,
exactly as §11.1 requires.

### 1.3 `scripts/`

`demo_task_1.sh` / `demo_task_2.sh` — POSIX `sh` (the Makefile runs them with `sh`; the brief runs
them with `bash`), parameterised by `BASE_URL`, `Authorization: Bearer $APP_ACCESS_TOKEN` on **every**
call, the chat calls in the default employee persona, and `X-Actor: admin` **only** on the
`GET /api/traces/turns/{turn_id}` poll of §9.4's 202 fallback. They pretty-print the answer, the
citations with their deep links, the full span trace with argument and result previews, the usage
rollup and the `dashboard_url`. Demo 2 additionally asserts, before confirming, that the response is
`awaiting_confirmation` and that **no `confirmation_token` appears anywhere in the body**.

`wait_for_health.py` — the Makefile's `demo1` / `demo2` / `docker-run-512` targets have called it
since P0 and it did not exist. Added here, because `make demo1 && make demo2` is P8's gate.

### 1.4 Tests (+148)

| File | What it pins |
|---|---|
| `tests/contract/test_app_starts.py` | the route table **is** §11.8's list; the MCP mount; a live app with no credentials |
| `tests/contract/test_health.py` | every block of §11.4; the live MCP catalog; the five-string vocabulary |
| `tests/contract/test_lifespan.py` | exactly one span listener, removed on exit; handlers on the main thread; the boot sweep; the warm-up as **one** `tools/call` in a maintenance turn |
| `tests/contract/test_chat_contract.py` | the response key set, both query shapes, the nine citation fields, client ids + 409, `k` bounded, no token anywhere |
| `tests/contract/test_chat_trace_projection.py` | R4.3's table **row by row**, the R4.1 row, trace ≡ spans, per-entry deep links |
| `tests/contract/test_chat_privileged_options.py` | §11.1's four-row matrix naming the code per row, plus `test_retrieval_options_reach_the_tool` |
| `tests/contract/test_access_gate.py` | the three presentations, the stripped redirect, the open routes, `APP_ENV=render`, the per-IP limit |
| `tests/contract/test_personas.py` | `/dashboard/*` and `/api/*` 403; 200 as `X-Actor: admin`; the default `E1042`; `POST /session/actor` |
| `tests/contract/test_chat_page_renders.py` | R6.2's named smoke test, on the server-rendered turn |
| `tests/contract/test_missing_key_is_graceful.py` | all three surfaces |
| `tests/integration/test_fault_{mcp_down,unknown_employee,empty_retrieval,ambiguous}.py` | §9.5's four rows, each **authored in full here**, each asserting HTTP 200 *and* its named span |
| `tests/integration/test_health_mcp_down.py` | 200 · `degraded` · `mcp_disconnected` |
| `tests/integration/test_sse.py` | the live path, the fallback, frame-vs-trace equality, a raising subscriber |
| `tests/integration/test_mcp_remote_url.py` | a second uvicorn, `sessions.mcp_transport == 'remote'` |
| `tests/integration/test_loopback_concurrency.py` | P5's carry-forward: two simultaneous `tools/call`s, and `/health` answering while they run |
| `tests/integration/test_confirm_resume_lifecycle.py` | decline → re-ask → confirm; two turn rows; one `mock_writes` row; the token minted from the gated arguments; the prefix/equality claim |
| `tests/integration/test_audit_completeness.py` | USER.2's own verification, nine assertions against the store |
| `tests/integration/test_process_exit_mid_turn.py` | **+ the subprocess form**: a real uvicorn, SIGTERM and SIGKILL |
| `tests/integration/test_mcp_discovery.py` | **+ 3 tests**: the mount is gated; the in-process client sends the bearer on `tools/list` and every `tools/call`; no header when the gate is off |
| `tests/unit/test_action_safety.py` | §13.4's four clauses over the golden traces, plus two negative controls |
| `tests/e2e/test_demo_tasks.py` | `DEMO_EXPECTATIONS` (two records, verbatim) and both sequences end to end |

Five new committed stub scripts: `demo_task_2.json`, `confirm_lifecycle.json`, and one per fault path.

---

## 2. Definition-of-done output (real, from `585293d`)

```
$ .venv/bin/pytest tests/contract/test_app_starts.py tests/contract/test_chat_page_renders.py tests/contract/test_health.py tests/contract/test_lifespan.py -q
.....................                                                    [100%]
21 passed in 11.88s

$ .venv/bin/pytest tests/contract/test_chat_contract.py tests/contract/test_chat_trace_projection.py -q
..............                                                           [100%]
14 passed in 10.32s

$ .venv/bin/pytest tests/contract/test_chat_privileged_options.py tests/contract/test_missing_key_is_graceful.py -q
..........                                                               [100%]
10 passed in 6.27s

$ .venv/bin/pytest tests/contract/test_access_gate.py tests/contract/test_personas.py -q
.....................                                                    [100%]
21 passed in 9.59s

$ .venv/bin/pytest tests/integration/test_fault_mcp_down.py tests/integration/test_fault_unknown_employee.py tests/integration/test_fault_empty_retrieval.py tests/integration/test_fault_ambiguous.py -q
....................                                                     [100%]
20 passed in 12.70s

$ .venv/bin/pytest tests/integration/test_health_mcp_down.py tests/integration/test_sse.py tests/integration/test_mcp_remote_url.py -q
..........                                                               [100%]
10 passed in 5.52s

$ .venv/bin/pytest tests/integration/test_mcp_discovery.py -q
.........                                                                [100%]
9 passed in 5.52s

$ .venv/bin/pytest tests/integration/test_confirm_resume_lifecycle.py -q
..........                                                               [100%]
10 passed in 8.14s

$ .venv/bin/pytest tests/integration/test_audit_completeness.py tests/integration/test_process_exit_mid_turn.py tests/unit/test_action_safety.py -q
......................                                                   [100%]
22 passed in 13.70s

$ .venv/bin/pytest tests/integration/test_loopback_concurrency.py -q
...                                                                      [100%]
3 passed in 2.82s

$ .venv/bin/pytest tests/e2e/test_demo_tasks.py -q
.....                                                                    [100%]
5 passed in 4.36s
```

`make demo1 && make demo2` — each starts its own server with its own `LLM_STUB_SCRIPT`, exit 0:

```
demo1: -- outcome: answered
       -- citations (4 from 3 document(s))
       -- usage: 5 model call(s), 5 tool call(s), 2 retrieval(s), 13516→768 tokens in 194 ms
       -- dashboard: /dashboard/sessions/1b0bc577cc9867052fc72793b987fbbe#turn-1
demo2: -- outcome: answered
       -- citations (3 from 2 document(s))
       -- usage: 5 model call(s), 6 tool call(s), 1 retrieval(s), 12240→514 tokens in 210 ms
       -- dashboard: /dashboard/sessions/7cfb50b043489e979675be64dd64bf36#turn-1
```

demo2's 25-span trace shows the gate on camera: span 14 `create_mock_hr_ticket · error`
(`CONFIRMATION_REQUIRED`), span 15 the `pending` confirmation, span 19 the re-discovery on the
reopened turn, span 20 the `confirmed` confirmation, span 21 the authorised write returning
`MOCK-HR-000001`.

Whole suite and lint:

```
$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
167 files already formatted

$ make test
1075 passed in 116.68s (0:01:56)
```

---

## 3. The live-provider check — and the three defects it found

Run 2026-09-09 against **`claude-haiku-4-5`** with the real key from the git-ignored `.env`
(`make run`, then `BASE_URL=http://127.0.0.1:8000 bash scripts/demo_task_{1,2}.sh`). No `.env` value
was read, printed or committed.

**The wire question the check existed to answer is answered: the Anthropic multi-turn tool shape is
correct.** 12 Haiku calls across the two tasks, **zero 400s**, every `tool_use` answered by a
`tool_result` in the immediately following message, including the act steps that group two calls.
P7's coalescing fix holds against the live endpoint.

### 3.1 Final measured results (on the committed code)

| Task | Outcome | Model calls | Tool calls | Retrievals | Citations | Wall clock | `cost_usd_estimate` |
|---|---|---|---|---|---|---|---|
| 1 — Berlin remote work | `answered` | 5 | 3 | 1 | 6 from 3 documents | 29.8 s | **$0.033894** |
| 2 — PTO + gated write | `answered` after Confirm | 7 | 5 | 1 | 5 from 2 documents | 34.0 s | **$0.043667** |

**Total spend for the pair: $0.077561** (12 `llm_call` spans; the warm-up turn costs nothing).

Task 1 tool sequence: `lookup_employee_profile` → `check_policy_compliance` → `search_policy_documents`
(10 chunks, top dense 0.788, three documents). Trace summary: 18 spans — `mcp_discovery`, G4, route,
`plan router` (`intent=workflow workflow=remote_work_eligibility`), three `act` calls, three tool
calls, one retrieval, G4, `plan act_summary`, **G1 allow** (max dense 0.788, 10 supporting), synthesize
(16.5 s), **G2 allow 8/8 resolved**, **G3 allow** (6 blocks, every `policy_fact` cited), G6 allow.

Task 2 tool sequence: `check_pto_balance` → `check_policy_compliance` → `search_policy_documents` →
`create_mock_hr_ticket` (**refused**, `CONFIRMATION_REQUIRED`) → *the human confirms* →
`create_mock_hr_ticket` (**ok**, `MOCK-HR-000001`). Trace summary: 26 spans across the two flushes;
span 16 `pending`, span 20 `confirmed`, span 21 the write; `turns.resumed_count = 1`; exactly one
`mock_writes` row whose `confirmation_token` resolves to a `confirmed`, spent `confirmations` row;
G1 allow (max dense 0.775), G2 allow 6/6, G3 allow, G6 allow.

### 3.2 What failed first, and what I changed (commit `b7b5fa7`)

On the first live run **both demo tasks refused** — task 1 `outcome: refused`, task 2 the same, both
with `G1 verdict=refuse · no policy evidence was retrieved`. Three defects, all in the agent loop, all
invisible under `StubAdapter` because every committed script searches the corpus first:

1. **The completion predicate and the evidence gate disagreed about "evidence".** `_absorb` fed the
   chunk ids that `get_policy_section` and `check_policy_compliance` *cite* into `LoopState`'s
   `evidence_chunk_ids` / `evidence_doc_ids`, which the workflow predicates count — but those chunks
   carry no dense score, so they never enter G1's candidate set. A turn that reached a compliance
   verdict without ever searching was therefore "complete", the act loop closed, and G1 then refused
   it. The fix is one shared meaning of evidence: only retrieved chunks count. (P7's own comment
   documented the split as intentional; live, it is what closes the turn one step early.)
2. **Nothing told the model what the workflow still needed.** `WorkflowSpec` knew, the conversation
   did not. `Orchestrator._nudge()` now sends one operational reminder, at most once per turn, on the
   step where the model tried to stop while the workflow was incomplete. (Safe on the wire:
   `anthropic.py` coalesces consecutive same-role messages, so a `user` note after a tool result
   merges into one message.)
3. **An outstanding write was dropped when the model simply answered.** `_action_outstanding` guarded
   the completion-predicate exit but not the "model returned no tool calls" exit — so task 2 wrote a
   perfectly good cited answer and **never proposed `create_mock_hr_ticket`**. The confirmation gate,
   the whole safety demo, never fired. `_nudge()` now covers that door with its own one-shot reminder.

Two prompt rules went with them, both goldens re-recorded: `act.j2` gains *"a policy claim needs the
policy TEXT, not a title"* (the live model kept reaching for `list_policy_documents`, which grounds
nothing), and `route.j2` gains *"`action` beats `workflow` when the user also asks for something to be
created"* — which is what puts task 2 back on the `intent="action"` path `_action_outstanding` keys on.

**These are P7 files.** I changed them because the brief's live check says a live failure is "a P7/P8
defect to fix … not to work around", and because two refusing demo tasks is a failure of the graded
deliverable, not a rough edge. The changes are small, each is anchored to an observed live trace, and
the whole suite stayed green through every one. They are called out as a concern below so the
controller can route them to a P7 re-review if it prefers.

---

## 4. TDD evidence

The gate-first files were written test-first and watched fail:

* `test_app_starts.py::test_the_route_table_is_exactly_the_endpoint_list_p8_owns` failed with
  `assert set() == {('GET', '/'), …}` — FastAPI 0.141 nests an included router under
  `_IncludedRouter.original_router`, which the first traversal did not walk.
* `test_app_starts.py::test_a_live_app_serves_the_chat_page_and_health_with_no_credentials` **hung**,
  then died with exit 143. Diagnosed to the `sse_starlette` / uvicorn interaction in §6 below and
  fixed in the shared helper before any other web test was written.
* `test_chat_trace_projection.py::test_row_4…` failed on `assert 'search_policy_documents' in
  {'dense_only', 'hybrid_rrf'}` — the retrieval span is named by the tool that produced it (P5), not
  by the strategy the §11.1 example shows. Resolved in favour of the normative table row (§7 below).
* `test_fault_empty_retrieval.py::test_the_guardrail_span_carries_the_observed_scores` failed with
  `candidates == 0`: raising `MIN_SUPPORT_SCORE` filters inside the *retriever*, producing an empty
  hit list rather than the low-score case §9.5 names. Switched to `MIN_EVIDENCE_SCORE`, which only G1
  reads, so the span carries the real observed scores.
* `test_missing_key_is_graceful.py` failed asserting `spans.name == 'configuration_required'` — the
  error span's `name` is its component (`llm`) and the kind is in the payload.
* `test_personas.py::test_the_x_actor_header_wins_over_the_cookie` failed with a `StubScriptError`
  (two full turns against a four-entry script); rewritten around out-of-corpus questions that consume
  no entries.
* `test_process_exit_mid_turn.py` (subprocess form) failed twice — first with zero flushed spans (the
  signal arrived before the first span closed), then with `('answered', 'answered')` (`StubAdapter`
  takes no limiter, so `LLM_RPM=1` does not pace it). Rewritten to leave a turn open
  **deterministically**, with no timing assumption at all.
* Both live demo failures in §3.2 are the same discipline at the integration level: observe the real
  failure, name it, fix the cause, re-run.

---

## 5. Files changed

**New — `src/hrmosaic/web/`:** `main.py` (262), `api.py` (1 066), `sse.py` (187),
`templates/chat.html` (157), `templates/_turn.html` (87), `templates/access.html` (25),
`static/app.css` (183).
**New — `scripts/`:** `demo_task_1.sh` (100), `demo_task_2.sh` (128), `wait_for_health.py` (60).
**New — tests:** 10 contract files, 9 integration files, `tests/unit/test_action_safety.py`,
`tests/e2e/test_demo_tasks.py`.
**New — fixtures:** `tests/fixtures/llm_scripts/{demo_task_2,confirm_lifecycle,fault_ambiguous,fault_empty_retrieval,fault_unknown_employee}.json`.
**Modified:** `tests/conftest.py` (the `web` fixture and `web_server()` helper),
`tests/integration/test_mcp_discovery.py` (+3 bearer tests),
`tests/integration/test_process_exit_mid_turn.py` (+the subprocess form),
`src/hrmosaic/agent/orchestrator.py` (§3.2 + the two published projection helpers),
`src/hrmosaic/agent/prompts/{act,route}.j2` and their two goldens, `README.md`, `CHANGELOG.md`.

---

## 6. Ambiguities resolved, and how

1. **`POST /chat` returns JSON *or* an HTML fragment.** §11.5's named smoke test asserts on *"the
   rendered turn"* after posting a message, and §11.8's endpoint list is exact — so there is no second
   "render this turn" route to add. `POST /chat` therefore returns the same `ChatResponse` as JSON to
   every API client and, to an `HX-Request: true` request from the page, that response rendered
   server-side. One endpoint, two representations; JSON remains the contract.
2. **The body's `employee_id` versus the persona.** §11.1 lists `employee_id` in the request; §11 says
   the header/cookie decide the persona. Resolution: the resolved persona is the default, an explicit
   body `employee_id` overrides it (it is audit-only and grants nothing — §8.7), and `actor_role`
   comes **only** from the persona, never from the body.
3. **A retrieval trace entry's `name`.** §11.1's example shows `hybrid_rrf`; the shipped span is named
   for the tool that produced it (P5). The table row is normative and is about the `summary` (k, top
   score, docs), which is asserted; the strategy is a payload field and a page-6 column. P5's span was
   left alone.
4. **Where "empty / low-score retrieval" comes from.** This embedding model's cosine floor over this
   corpus is ~0.52, so no phrasing produces a genuinely empty hit list. The fault is injected by
   raising `MIN_EVIDENCE_SCORE` — G1's own bar, and the only threshold the retriever does not also
   apply — which reproduces exactly the case §9.5 names and leaves the **observed** scores on the span.
5. **`POST /chat/confirm` error codes.** The spec names none for the sad paths. Unknown turn or no
   pending proposal → **404**; an expired proposal → **409** `CONFIRMATION_EXPIRED` with nothing
   minted. A decline closes the turn `outcome="refused"`, `stop_reason="declined"` — `refused` is the
   only `TurnOutcome` that fits a cancelled proposal.
6. **A malformed `X-Actor` / `mosaic_actor`.** Falls back to `E1042` rather than erroring: a stale
   cookie must not brick the page. `POST /session/actor` validates and returns 422, because that is
   the path where a bad value is a client mistake.
7. **The loopback-concurrency test P5's carry-forward asks for** is `tests/integration/test_loopback_concurrency.py`
   — the roadmap names the behaviour but no file. Three tests: two simultaneous `tools/call`s both
   complete, `/health` answers while they are in flight, and two concurrent `/chat` turns stay isolated.
8. **`sse_starlette` versus a hand-rolled SSE response.** `web/sse.py` hand-rolls it. One
   process-global latch that a stopped server sets for every other stream in the process is enough
   (P5's carry-forward); the broker ends its generators from the lifespan instead.
9. **The 202 fallback of §9.4 is not implemented** — it is contingent on a P11 measurement of Render's
   request timeout. `/chat` always answers 200. Both demo scripts nevertheless **handle** a 202, since
   §11.5 says they must, and that branch polls `GET /api/traces/turns/{turn_id}` with `X-Actor: admin`.
10. **`scripts/wait_for_health.py`** was referenced by the Makefile since P0 and absent. Written here
    rather than reported, because `make demo1 && make demo2` is P8's own gate.

---

## 7. Self-review findings (all fixed)

* **A resumed turn's `turn_started` frame reported the wrong `seq`** — the session's next rather than
  the reopened turn's own. Fixed in `585293d`.
* **The act-as selector set the cookie but did not reload**, so switching to HR admin left the
  dashboard nav link hidden until a manual refresh. Fixed in `585293d`.
* **The rate limiter never dropped an IP key**, accumulating one `deque` per distinct client address
  for the life of the process — a slow leak on a 512 MB instance. Now the key is dropped with its
  window.
* **A shared-fixture leak:** the lifespan's `install_shutdown_handlers()` sets a module-global flag,
  and leaving it set turned P1's `test_the_sigterm_handler_flushes_and_chains_to_the_previous_handler`
  into a silent no-op when the whole suite ran. The `web_server` teardown now calls
  `reset_shutdown_handlers()`. (Caught by running the full suite, not the file.)
* **`Citation` was imported into `api.py` and used only in `__all__`.** Removed.

---

## 8. Concerns

1. **I changed three P7 files** (`agent/orchestrator.py`, `agent/prompts/act.j2`,
   `agent/prompts/route.j2`) to make the live demos work — see §3.2. Each change is small and
   evidence-backed and the suite is green, but a P7 re-review is the right call, particularly on
   whether an injected `user` reminder inside the act loop is the shape P7 wants (the alternative is
   to make G1 accept the rules engine's cited evidence, which is a larger semantic change to the
   guardrail and its unit tests).
2. **The live tool sequence is shorter than §18.1 documents.** Live, demo 1 answered in three tool
   calls (profile → compliance → one search) rather than the five §18.1 lists, and cited three
   documents rather than four. `DEMO_EXPECTATIONS` is a floor and the e2e test runs against the
   committed stub scripts, so nothing is red — but P10 should re-record both scripts from a real
   exchange, and P12's documented tables should be checked against what the model actually does.
3. **`test_chat_page_renders` asserts on server-rendered HTML, not on the JavaScript path.** The
   fragment the test reads is the one htmx swaps in, so the badges and chips are the shipped ones —
   but nothing in the suite executes the page's JS (the SSE rail, the cold-start banner, the demo
   buttons). Those were exercised by hand during the live runs; a P9/P12 browser check would close it.
4. **The `/ready` warm-up writes one `maintenance` session per boot**, and `core/retention.py` never
   prunes a `maintenance` session (§10.5). Over many restarts these accumulate. Harmless at this scale
   and deliberate (it is the same out-of-turn pattern §11.6 specifies for `POST /api/mcp/rediscover`),
   but P9 may want a cap.
5. **`GET /api/traces/turns/{turn_id}` is the minimal shape P8 needs.** P9 grows it into page 3's full
   view-model; the demo scripts and the 202 fallback read only `outcome`, `final_answer`, `citations`,
   `spans[]` and `dashboard_url`, all of which are present.
6. **`StubScriptError` escapes as a 500.** When a stub script runs out mid-turn the exception is not
   one of the modelled failures, so `POST /chat` answers 500 and the turn is left open. That only
   happens under `LLM_PROVIDER=stub` with a script shorter than the turn needs — it is in fact how the
   subprocess process-exit test creates its open turn — but it is worth knowing that the "every failure
   path answers 200" rule has this test-only exception.

---

# P8 fix report — review round 1 of 3

**Base:** `585293d` · **HEAD:** `10679088e0c8005bdfb2710e3a381e5ac0356e85` · **Suite:** 1087 passed
in 121 s, pristine (was 1075; **+12 tests**). `make lint` green. `make demo1 && make demo2` exit 0.
One commit, local, nothing pushed: `1067908` `P8(web): fix: the app no longer rate-limits,
mis-counts or 500s on itself`.

Six findings arrived. Five are fixed in code with covering tests; the sixth (the P7 scope finding)
is a routing request the controller owns and is restated at the end.

---

## F1 — the app 429s its own MCP traffic (`api.py:_rate_limited`) · **fixed**

**The defect.** §17's per-IP limit is keyed on `request.client.host`, and the agent reaches its own
MCP mount over loopback — so `initialize`, `notifications/initialized`, `tools/list`, the long-lived
`GET`, every `tools/call`, and the `client.discover()` behind every `GET /health` all land in the
same `127.0.0.1` bucket as the grader's browser. Past a few turns a minute the app starts refusing
its own `tools/call` and the turn silently degrades.

**The fix.** `web/api.py` mints a per-process nonce at import (`LOOPBACK_NONCE`, `secrets.token_urlsafe(32)`)
and `web/main.py` hands it to the one client the lifespan builds, as `X-Mosaic-Loopback`.
`_rate_limited` skips the limit when — and only when — the request is on `MCP_MOUNT_PREFIX`, the
client address is a real loopback address (`ipaddress.ip_address(host).is_loopback`, never a
hostname and never a proxy header) **and** the header matches the nonce under `hmac.compare_digest`.
The nonce is not a credential: the bearer is still sent and still checked, and the exemption never
covers `POST /chat`.

**Measured, on the shipped code** (a spy on `is_own_loopback_client`, four turns plus a `/health`
each against one instance):

```
turn 1: mount requests exempted=5 billed=0
turn 2: mount requests exempted=1 billed=0
turn 3: mount requests exempted=1 billed=0
turn 4: mount requests exempted=1 billed=0
TOTAL {'exempt': 8, 'billed': 0}
```

**Covering tests** (`tests/contract/test_access_gate.py`, + a 16-completion fixture
`tests/fixtures/llm_scripts/four_turns.json`):

* `test_four_turns_in_a_row_all_answer_because_the_apps_own_loopback_client_is_exempt` — four turns
  under `ACCESS_RATE_LIMIT_PER_MIN=4`, so the visitor budget is spent to the last unit and nothing
  is left over for the app; every turn must be `answered`.
* `test_a_forged_loopback_nonce_spends_the_budget_like_anyone_else` — a wrong nonce is not an
  exemption.
* `test_the_real_nonce_does_not_exempt_post_chat` — only the mount is ever exempt.

Watched fail first, with the exemption disabled:

```
$ .venv/bin/pytest tests/contract/test_access_gate.py -q -k four_turns
E               AssertionError: {"code":"RATE_LIMITED","detail":"more than 4 requests in a minute"}
E               assert 429 == 200
1 failed, 15 deselected in 1.72s
```

`tests/integration/test_mcp_discovery.py`'s two header assertions moved from whole-dict equality to
`headers["Authorization"] == …` / `"Authorization" not in headers`, so they pin the credential
(which is what §16.4 is about) rather than the exact header set.

## F2 — a declined turn reported `resumed_count = 1` (`api.py:chat_confirm`) · **fixed**

`trace_module.reopen_turn()` was called before the confirmed/declined branch, and `TURN_REOPEN` does
`resumed_count = resumed_count + 1`. §11.2 is explicit that a decline "closes the turn without
reopening"; the reopen exists only so `_record_decline` can write the second `confirmation` span
through `core/trace.py`.

`core/trace.py` gains a second statement, `TURN_REOPEN_UNCOUNTED`, and
`TraceWriter.reopen_turn(..., resumed: bool = True)` selects between them; the module-level
`reopen_turn()` passes the flag through. `chat_confirm` now calls it with
`resumed=(body.decision == "confirmed")`. Nothing else changed on the confirm path.

**Covering test:** `test_a_decline_records_a_second_confirmation_span_and_closes_the_turn` now
asserts `row["resumed_count"] == 0`; the confirmed half is already pinned at
`test_a_confirm_reopens_that_turn_and_the_write_lands_in_it` (`resumed_count == 1`), so both
directions are covered and neither can drift.

## F3 — the rate-limiter key eviction was a no-op (`api.py:RateLimiter`) · **fixed**

`self._hits.pop(key, None)` was immediately undone by `window = self._hits[key]`, because `_hits`
was a `defaultdict`. Worse, the previous report's claim was over-stated in a second way: even with
the pop working, a key is only ever *re-created* on the same access, so a client that never comes
back is never dropped at all — which is exactly the drive-by scanner case §14.3's 512 MB budget
cares about.

So the fix is both halves the finding offers. `_hits` is a plain `dict`, so the `del` sticks; and
`_sweep()` drops every window that expired without the client returning, at most once per
`RATE_SWEEP_INTERVAL_S` (60 s), which makes the table bounded by *clients seen in the last minute*
rather than *clients seen since boot*. A limit of 0 now refuses without recording a key at all.

**Covering tests:** new `tests/unit/test_rate_limiter_eviction.py`, five tests asserting on
`len(limiter._hits)` directly — including
`test_a_thousand_one_shot_visitors_are_swept_and_do_not_accumulate` (1 000 keys → 1 after one
request a window later) and `test_the_sweep_keeps_a_client_that_is_still_inside_its_window`, plus
the burst behaviour, so the eviction cannot be "fixed" by weakening the limit.

## F4 — the tautological R4.3 row-1 assertion · **fixed**

`assert called <= selected | called` can never fail. It is now the real claim,
`assert called <= selected` — every tool the turn called is named on a `plan` span (the router's
`selected_tools`, or `act_summary`'s, which records what the act loop used) — and the row's second
half is asserted separately: `sorted(entry names of kind tool_call in trace) == sorted(names of the
turn's tool_call spans)`, so the projection is provably one entry per span rather than a
de-duplicated list. Both hold on the shipped `demo_task_1` turn.

## F5 — no catch-all handler; a 500 pinned as expected behaviour · **fixed**

**The fix.** `web/api.py` gains `unhandled_error_response()` and `UnhandledErrorMiddleware`, and
`web/main.py`'s `_install_error_handlers` installs the middleware alongside the two existing
handlers. `POST /chat` and `POST /chat/confirm` record their `turn_id` on `scope["state"]`, so the
catch-all can find the buffer the failure left open. It then writes an `error` span
(`error_kind="internal"`, component `web`, the exception's one-line message) through `core/trace.py`,
closes the turn `outcome="error" stop_reason="error" error_kind="internal"`, and answers **200**
with the same typed shape `_configuration_required` uses: a `recommendation` block and an
`escalation` block pointing at People Operations, plus the usual `trace[]`/`usage`/`timings`. Nothing
is left `ended_at IS NULL`.

**Why a middleware and not `app.add_exception_handler(Exception, …)`.** Starlette routes the
`Exception` key to `ServerErrorMiddleware`, which sends the response and then **re-raises** — the
connection is still torn down and the failure is still reported as a crash. Catching it in a pure
ASGI middleware ends the request cleanly. It is pure ASGI (never wraps the body) so `/chat/stream`
and the MCP mount stream through untouched, and it sits inside the access gate and outside
Starlette's `ExceptionMiddleware`, so `HTTPException` and `RequestValidationError` are already
mapped by the time anything reaches it. Once the response has started it re-raises, because nothing
can be substituted then. This is a deliberate deviation from the finding's literal wording; it is
installed from `_install_error_handlers`, as asked.

**The suite no longer depends on the violation.** `tests/integration/test_process_exit_mid_turn.py`
created its open turn by asserting `crashed.status_code == 500`. It now runs a new helper,
`tests/integration/uvicorn_with_open_turn.py`, which serves the real `hrmosaic.web.main:app` and
then opens one turn directly on the process-wide writer the lifespan installed, never closing it —
endpoint-free, no timing assumption, and no reliance on any request failing. The SIGTERM test's span
assertion becomes `["plan"]`; the hard-kill test's boot-sweep read now polls, because the sweep runs
on a worker thread and `/health` can answer before it lands.

**Covering tests:** new `tests/contract/test_unmodelled_failure_is_graceful.py`, four tests over a
turn whose model call raises `StubScriptError` (a plain `RuntimeError`, none of the modelled
failures): 200 with the two typed blocks and no stack trace in the answer; the turn closed with
`error_kind="internal"` and zero rows left open; exactly one `error` span named `web` carrying the
exception; and `trace[]` still equal to the spans the failed turn did write. §12.3's "never a stack
trace" is asserted on the answer — the exception's one-line message stays on the `error` span, which
is where every modelled failure already records its own, and so reaches `trace[]` and the dashboard
and nowhere else.

## F6 — commit `b7b5fa7` changes three P7 files · **routed, not fixed here**

No code change: the finding's own remedy is *"Route `b7b5fa7` to a P7 re-review before this phase is
accepted"*, which is the controller's call, and reverting it would put both demo tasks back to
`outcome: refused` against the live provider. **This fix round leaves `b7b5fa7` exactly as it was**
and restates the request. The two questions P7 should rule on:

1. Is an injected synthetic `role="user"` reminder inside the act loop (`Orchestrator._nudge`, with
   `WORKFLOW_INCOMPLETE` and `ACTION_OUTSTANDING`) the shape P7 wants — versus making G1 accept the
   rules engine's cited evidence, which is a larger semantic change to the guardrail and its unit
   tests?
2. Does removing the citation-derived evidence accounting from `_absorb` (tool-cited chunk ids no
   longer enter `LoopState.evidence_chunk_ids` / `evidence_doc_ids`) weaken any P7 workflow
   predicate that the committed stub scripts do not exercise?

Also in scope for that review: the two prompt rules added to `act.j2` and `route.j2` and their two
re-recorded goldens.

---

## Files changed in this round

**Modified:** `src/hrmosaic/core/trace.py` (the `resumed` flag, `TURN_REOPEN_UNCOUNTED`, and a
read-only module-level `open_turns()`), `src/hrmosaic/web/api.py` (the loopback nonce and its two
predicates, the rewritten `RateLimiter`, the catch-all response and middleware, the `turn_id` on
`scope["state"]`, the uncounted decline reopen), `src/hrmosaic/web/main.py` (the nonce on the
in-process client, the middleware installed from `_install_error_handlers`),
`tests/contract/test_access_gate.py`, `tests/contract/test_chat_trace_projection.py`,
`tests/integration/test_confirm_resume_lifecycle.py`, `tests/integration/test_mcp_discovery.py`,
`tests/integration/test_process_exit_mid_turn.py`.

**New:** `tests/contract/test_unmodelled_failure_is_graceful.py`,
`tests/unit/test_rate_limiter_eviction.py`, `tests/integration/uvicorn_with_open_turn.py` (a
subprocess helper, not a test module), `tests/fixtures/llm_scripts/four_turns.json`.

---

## Definition-of-done output (real, from this round's HEAD)

```
$ .venv/bin/pytest tests/contract/test_app_starts.py tests/contract/test_chat_page_renders.py tests/contract/test_health.py tests/contract/test_lifespan.py -q
21 passed in 11.79s

$ .venv/bin/pytest tests/contract/test_chat_contract.py tests/contract/test_chat_trace_projection.py -q
14 passed in 10.24s

$ .venv/bin/pytest tests/contract/test_chat_privileged_options.py tests/contract/test_missing_key_is_graceful.py -q
10 passed in 6.30s

$ .venv/bin/pytest tests/contract/test_access_gate.py tests/contract/test_personas.py -q
24 passed in 12.17s

$ .venv/bin/pytest tests/integration/test_fault_mcp_down.py tests/integration/test_fault_unknown_employee.py tests/integration/test_fault_empty_retrieval.py tests/integration/test_fault_ambiguous.py -q
20 passed in 12.74s

$ .venv/bin/pytest tests/integration/test_health_mcp_down.py tests/integration/test_sse.py tests/integration/test_mcp_remote_url.py -q
10 passed in 5.56s

$ .venv/bin/pytest tests/integration/test_mcp_discovery.py -q
9 passed in 5.53s

$ .venv/bin/pytest tests/integration/test_confirm_resume_lifecycle.py -q
10 passed in 8.08s

$ .venv/bin/pytest tests/integration/test_audit_completeness.py tests/integration/test_process_exit_mid_turn.py tests/unit/test_action_safety.py -q
22 passed in 13.10s

$ .venv/bin/pytest tests/e2e/test_demo_tasks.py -q
5 passed in 4.41s
```

The tests covering the amended code, run on their own:

```
$ .venv/bin/pytest tests/unit/test_rate_limiter_eviction.py -q
5 passed in 1.11s

$ .venv/bin/pytest tests/contract/test_unmodelled_failure_is_graceful.py -q
4 passed in 4.05s
```

`make demo1 && make demo2` — chained, exit 0:

```
$ make demo1 >/tmp/d1.log 2>&1 && make demo2 >/tmp/d2.log 2>&1; echo "exit=$?"
exit=0
/tmp/d1.log:-- outcome: answered
/tmp/d2.log:-- outcome: answered
```

demo 1: 22 spans, 4 citations from 3 documents, 5 model calls / 5 tool calls / 2 retrievals.
demo 2: 25 spans, 3 citations from 2 documents, the gate on camera and
`{"status": "created", "ticket_id": "MOCK-HR-000004", …}` on the authorised write.

Whole suite and lint:

```
$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
170 files already formatted

$ make test
.venv/bin/pytest -q
1087 passed in 121.40s (0:02:01)
```

---

## Concerns from this round

1. **`b7b5fa7` still needs a P7 re-review** (F6 above). Nothing in this round touched it.
2. **The catch-all is a middleware, not `app.add_exception_handler(Exception, …)`**, for the
   `ServerErrorMiddleware` re-raise reason in F5. If a reviewer wants the literal handler shape, the
   trade is a torn-down connection and a logged crash on every unmodelled failure.
3. **The catch-all swallows programmer errors into a 200.** That is what constraint 11 asks for, and
   the exception is logged at `ERROR` with its traceback and recorded on an `error` span with
   `error_kind="internal"` — but a genuinely broken handler now surfaces as a degraded answer rather
   than a red request, so P9's dashboard should make `error_kind="internal"` visible.
4. **`RATE_SWEEP_INTERVAL_S` is a constant, not a setting.** One sweep a minute over a table bounded
   by a minute's distinct addresses is cheap at this scale; if P11's load numbers say otherwise it
   should become a setting rather than a tuned literal.
5. **The loopback exemption trusts `request.client.host`**, which is the transport peer, not an
   `X-Forwarded-For` header — deliberately, so a proxy header can never fabricate it. If a future
   deployment ever puts the MCP mount behind a proxy on the same host, the exemption would widen to
   that proxy's loopback address; the nonce is what keeps that from being an open door.

---

# P8 fix report — review round 2 of 3

**Base:** `1067908` · **HEAD:** `9fb666573794699dfb9303ba229e5d2df5889a57` · **Suite:** 1103 passed
in 121.90 s, pristine (was 1087; **+16 tests**). `make lint` green. `make demo1 && make demo2`
exit 0. One commit, local, nothing pushed: `9fb6665` `P8(agent): fix: pin the act loop's two
reminders and its one meaning of evidence`. **No source file changed in this round.**

One finding arrived, the re-review of F6. It is a routing request, and routing is still the
controller's act — but the round did not stop there: the reason a P7 ruling is expensive is that
`b7b5fa7` landed an 80-line loop mechanism and a semantic narrowing of the evidence accounting with
**no assertion anywhere in the suite**, resting entirely on one live run against
`claude-haiku-4-5` that CI cannot repeat. That part was fixable here, and is fixed.

---

## F6 (re-review) — `b7b5fa7` changes three P7 files and adds a new mechanism · **routing still open; the mechanism is now pinned by tests**

**What the finding says, and what is true.** Confirmed, unchanged: `b7b5fa7` is still in history
untouched, and the mechanism is still live at HEAD —
`src/hrmosaic/agent/orchestrator.py:130` `WORKFLOW_INCOMPLETE`, `:140` `ACTION_OUTSTANDING`, `:796`
`def _nudge`, `:823` `turn.messages.append(Message(role="user", content=ACTION_OUTSTANDING))`.
Round 1 declined to act; the reviewer agreed that was the right call for an implementer and
recorded the finding as *not addressed* because the ruling has not happened. Both remain true. I am
not the controller and I cannot rule, so **the routing request stands and is restated in full
below**.

**What was fixable here, and was.** Before this round:

```
$ grep -rn "_nudge\|WORKFLOW_INCOMPLETE\|ACTION_OUTSTANDING\|action_reminded\|nudged" \
    --include="*.py" . | grep -v "src/hrmosaic/agent/orchestrator.py"
(no output)

$ grep -rn "note_evidence" --include="*.py" src tests
src/hrmosaic/agent/orchestrator.py:966:                turn.state.note_evidence(chunk.chunk_id, chunk.doc_id)
src/hrmosaic/agent/orchestrator.py:1362:            turn.state.note_evidence(chunk.chunk_id, chunk.doc_id)
src/hrmosaic/agent/workflows/__init__.py:49:    def note_evidence(self, chunk_id: str | None, doc_id: str | None) -> None:
```

Zero coverage on either half. A P7 reviewer asked to rule on the mechanism had nothing to read but
the diff and a prose account of a live run. `tests/unit/test_agent_nudge.py` (new, 16 tests) is
that evidence, offline and in CI:

*The workflow reminder* — sent once and only once even while the gap persists; names the workflow,
its missing `requires_tool_results` and its `policy_docs`, and equals `WORKFLOW_INCOMPLETE.format(…)`
exactly; a complete workflow is never reminded; a turn with no workflow and no action is never
reminded.

*The action reminder* — sent once and only once; equals `ACTION_OUTSTANDING`; never sent when a
write is already in state (`create_mock_hr_ticket` / `draft_hr_email`, parametrised) or when the
turn is already parked at the confirmation gate (`turn.pending`); the workflow reminder comes first
and the action reminder on the **next** step, never two in one message; and a reminder never
invents evidence — `state.evidence_chunk_ids`, `state.evidence_doc_ids` and `turn.evidence` are
untouched. `buffer` is `None` in the fixture turn on purpose: a reminder that ever reached the span
writer would raise here rather than pass quietly, which is the §9.7 boundary the commit claimed.

*One meaning of "evidence"* — the control (a retrieved chunk with a dense score enters both the
predicate's count and G1's candidate set); the change (a chunk id merely **cited** by
`get_policy_section` or `check_policy_compliance` enters neither, while the tool result itself is
still in state); and the live defect itself, reproduced offline for both workflows: a compliance
verdict reached without ever searching leaves `pto_request.is_complete` and
`remote_work_eligibility.is_complete` **false**, and `_nudge` is what tells the model so.

*The loop wiring* — `test_a_reminded_turn_takes_another_act_step_instead_of_closing` drives a whole
turn through `run_agent` on a new stub script, `tests/fixtures/llm_scripts/nudge_probe.json`: the
router picks `action` + `pto_request` and every act entry answers with prose and no tool call. The
loop takes **three** act steps rather than closing on the first, the `act_summary` span's
`step_summaries` read exactly

```
step 1: workflow incomplete, asked for check_pto_balance, check_policy_compliance
step 2: the requested action was still unproposed
step 3: no tool call, the model answered
```

both reminders are on the wire verbatim as `llm_messages` rows joined to that turn's spans, and the
turn still ends `refused` with `usage.tool_calls == 0` — the reminders manufacture nothing.

**Mutation-checked, because a test that cannot fail proves nothing.** Both halves of `b7b5fa7` were
reverted in turn against this file and the file was re-run each time (the source file was restored
from a scratchpad copy immediately after; `git diff --stat src/` was empty before the commit):

```
# `_nudge` short-circuited to `return False`
7 failed, 9 passed in 1.84s
FAILED tests/unit/test_agent_nudge.py::test_an_incomplete_workflow_is_reminded_once_and_only_once
FAILED tests/unit/test_agent_nudge.py::test_the_reminder_names_the_workflow_the_missing_tools_and_the_documents
FAILED tests/unit/test_agent_nudge.py::test_an_unproposed_action_is_reminded_once_and_only_once
FAILED tests/unit/test_agent_nudge.py::test_the_workflow_reminder_comes_first_and_the_action_reminder_on_the_next_step
FAILED tests/unit/test_agent_nudge.py::test_a_compliance_verdict_without_retrieval_does_not_complete_the_pto_workflow
FAILED tests/unit/test_agent_nudge.py::test_a_compliance_verdict_without_retrieval_does_not_complete_the_remote_work_workflow
FAILED tests/unit/test_agent_nudge.py::test_a_reminded_turn_takes_another_act_step_instead_of_closing

# the citation-derived evidence accounting put back into `_absorb`
4 failed, 12 passed in 1.82s
FAILED tests/unit/test_agent_nudge.py::test_a_merely_cited_chunk_id_is_not_evidence[get_policy_section-body0]
FAILED tests/unit/test_agent_nudge.py::test_a_merely_cited_chunk_id_is_not_evidence[check_policy_compliance-body1]
FAILED tests/unit/test_agent_nudge.py::test_a_compliance_verdict_without_retrieval_does_not_complete_the_pto_workflow
FAILED tests/unit/test_agent_nudge.py::test_a_compliance_verdict_without_retrieval_does_not_complete_the_remote_work_workflow
```

Either half being undone now fails a test instead of quietly re-opening the live defect. **That is
the whole of what an implementer can do about this finding.**

### The routing request, restated for the controller

`b7b5fa7` (`P8(agent): fix: three live-only loop defects the stub could not show`) touches three
P7-owned files plus two re-recorded goldens:

```
$ git diff --stat b7b5fa7~1 b7b5fa7
 src/hrmosaic/agent/orchestrator.py      | 80 ++++++++++++++++++++++++++++++---
 src/hrmosaic/agent/prompts/act.j2       |  3 +-
 src/hrmosaic/agent/prompts/route.j2     |  1 +
 tests/fixtures/prompts/act.system.txt   |  3 +-
 tests/fixtures/prompts/route.system.txt |  1 +
 5 files changed, 79 insertions(+), 9 deletions(-)
```

P7's own carry-forward in `progress.md` anticipated the prompt half — *"the three prompts are frozen
by golden files and untested against a live model beyond the probe; changing them is a deliberate
act"* — and P7's live-check carry-forward for P8 is what produced the change. The four questions a
P7 re-review should rule on:

1. **Is an injected synthetic `role="user"` reminder inside the act loop the shape P7 wants?**
   (`Orchestrator._nudge`, `WORKFLOW_INCOMPLETE`, `ACTION_OUTSTANDING`.) The alternative is making
   G1 accept the rules engine's cited evidence, which is a larger semantic change to the guardrail
   and its unit tests. The behaviour is now fully specified by `tests/unit/test_agent_nudge.py`, so
   the ruling is about shape, not about what it does.
2. **Does removing the citation-derived evidence accounting from `_absorb` weaken any P7 workflow
   predicate?** Both predicates are now asserted directly against a cited-but-unretrieved verdict
   (`test_a_compliance_verdict_without_retrieval_does_not_complete_the_*_workflow`), and both come
   out false — which is the intended reading of §9.3 against §7.3's G1, but P7 owns the call.
3. **The two prompt rules** added to `act.j2` (rule 6: a policy claim needs the policy text, not a
   title) and `route.j2` (rule 4: `action` beats `workflow` when the user also asks for something to
   be created), with their two re-recorded goldens.
4. **A documentation defect I am deliberately not fixing, to avoid adding to the churn this finding
   is about:** the new comments in `orchestrator.py` cite **§9.3** for the reminder mechanism
   (`orchestrator.py:125`, `:418`, `:797`, and the `_absorb` comment at `:983`). Spec §9.3 is *"The two
   workflows"* and says only *"The LLM chooses tools; the workflow spec decides when the turn is
   complete."* It does not describe a reminder. The mechanism is not forbidden by the spec, but the
   citation is wrong and should either move to §9.1 (the act loop) or be written into the spec by
   whoever rules on question 1.

Nothing else in P8 depends on the outcome: reverting `b7b5fa7` would put both demo tasks back to
`outcome: refused` against the live provider, but leaves the stub path, the whole suite and both
`make demo` targets green.

---

## Files changed in this round

**New:** `tests/unit/test_agent_nudge.py` (16 tests),
`tests/fixtures/llm_scripts/nudge_probe.json` (a stub script, not a test module).

**Modified:** none. No file under `src/` was touched.

---

## Definition-of-done output (real, from this round's HEAD `9fb6665`)

```
$ .venv/bin/pytest tests/contract/test_app_starts.py tests/contract/test_chat_page_renders.py tests/contract/test_health.py tests/contract/test_lifespan.py -q
21 passed in 11.71s

$ .venv/bin/pytest tests/contract/test_chat_contract.py tests/contract/test_chat_trace_projection.py -q
14 passed in 10.21s

$ .venv/bin/pytest tests/contract/test_chat_privileged_options.py tests/contract/test_missing_key_is_graceful.py -q
10 passed in 6.24s

$ .venv/bin/pytest tests/contract/test_access_gate.py tests/contract/test_personas.py -q
24 passed in 12.21s

$ .venv/bin/pytest tests/integration/test_fault_mcp_down.py tests/integration/test_fault_unknown_employee.py tests/integration/test_fault_empty_retrieval.py tests/integration/test_fault_ambiguous.py -q
20 passed in 12.68s

$ .venv/bin/pytest tests/integration/test_health_mcp_down.py tests/integration/test_sse.py tests/integration/test_mcp_remote_url.py -q
10 passed in 5.52s

$ .venv/bin/pytest tests/integration/test_mcp_discovery.py -q
9 passed in 5.49s

$ .venv/bin/pytest tests/integration/test_confirm_resume_lifecycle.py -q
10 passed in 8.05s

$ .venv/bin/pytest tests/integration/test_audit_completeness.py tests/integration/test_process_exit_mid_turn.py tests/unit/test_action_safety.py -q
22 passed in 12.86s

$ .venv/bin/pytest tests/e2e/test_demo_tasks.py -q
5 passed in 4.42s
```

The test covering the amended behaviour, run on its own:

```
$ .venv/bin/pytest tests/unit/test_agent_nudge.py -q
16 passed in 1.71s
```

`make demo1 && make demo2` — chained, exit 0:

```
$ make demo1 >d1.log 2>&1 && make demo2 >d2.log 2>&1; echo "exit=$?"
exit=0
d1.log:37:-- outcome: answered
d2.log:50:-- outcome: answered
```

Whole suite and lint:

```
$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
171 files already formatted

$ make test
.venv/bin/pytest -q
1103 passed in 121.90s (0:02:01)
```

---

## Concerns from this round

1. **The routing request is still open and is the controller's, not the implementer's.** Two rounds
   have now reported it. What changed is only that a P7 reviewer can now rule on shape rather than
   on behaviour, because the behaviour is asserted. If the controller wants P8 accepted without a
   P7 ruling, the honest form of that is a `Ruling:` line in `progress.md`, not silence.
2. **`orchestrator.py` cites §9.3 for a mechanism §9.3 does not describe** (question 4 above). Left
   unfixed on purpose — fixing it means a fourth P8 commit touching a P7 file, which is the finding.
3. **The four earlier concerns from round 1 stand unchanged** (the catch-all as middleware, the
   catch-all swallowing programmer errors into a 200, `RATE_SWEEP_INTERVAL_S` as a constant, and the
   loopback exemption trusting `request.client.host`).

---

# P8 fix report — review round 3 of 3

**Base:** `9fb6665` · **HEAD:** `8cf72861083f5c880c10ba61163ac0f580e83f6f` · **Suite:** 1103 passed
in 121.72 s, pristine (unchanged count — this round's only source edit is comments). `make lint`
green. `make demo1 && make demo2` exit 0. One commit, local, nothing pushed: `8cf7286`
`P8(agent): fix: cite the act loop, not §9.3, for the two reminders`.

One finding arrived again: the re-review of F6. **It is still open, and it is still the
controller's to close, not mine** — the reviewer says as much ("the implementer again correctly
declines to make it"). So this round did the two things an implementer still could: it closed the
one documentation defect round 2 identified and deliberately left open, and it **priced the
ruling** — including one material fact about `b7b5fa7` that neither earlier round recorded and that
changes what "revert it" costs.

---

## F6 (re-review) — routing still open · one documentation defect closed · the ruling now priced

### Still true, unchanged

`b7b5fa7` is in history untouched and the mechanism is live at HEAD. The routing request is
restated in full in round 2's section above ("The routing request, restated for the controller",
four numbered questions); nothing about it has changed and I am not repeating it here. Round 2's
`tests/unit/test_agent_nudge.py` (16 tests) still pins the behaviour, so the ruling is about shape.

### New this round (1) — `b7b5fa7` does a **fourth** thing, and P8 hard-depends on it

Both earlier rounds described `b7b5fa7` as three loop defects plus two prompt rules. Its own commit
body has a fourth bullet that neither round carried into the routing request:

```
$ git show b7b5fa7 -- src/hrmosaic/agent/orchestrator.py | grep -n "preview_value\|summarise_span"
21:    - `summarise_span` / `preview_value` published for `web/sse.py`, so the live rail and
154:+summarise_span = _summary
155:+preview_value = _preview
165:+    "preview_value",
171:+    "summarise_span",
```

`orchestrator.py` was only ever touched by three commits (`c1221fe`, `ca13389`, `b7b5fa7` —
`git log --oneline -- src/hrmosaic/agent/orchestrator.py`), so those two public names exist **only**
because of `b7b5fa7`, and `src/hrmosaic/web/sse.py:36` imports them. A full revert therefore does
not merely regress live behaviour — it breaks the build:

```
$ git diff b7b5fa7 b7b5fa7~1 -- src/hrmosaic/agent/orchestrator.py src/hrmosaic/agent/prompts/act.j2 \
      src/hrmosaic/agent/prompts/route.j2 tests/fixtures/prompts/act.system.txt \
      tests/fixtures/prompts/route.system.txt > revert.patch && git apply revert.patch
$ .venv/bin/pytest -q
src/hrmosaic/web/sse.py:36: in <module>
    from hrmosaic.agent.orchestrator import preview_value, summarise_span
E   ImportError: cannot import name 'preview_value' from 'hrmosaic.agent.orchestrator'
ERROR tests/contract/test_app_starts.py
ERROR tests/contract/test_health.py
ERROR tests/contract/test_lifespan.py
ERROR tests/integration/test_sse.py
ERROR tests/unit/test_agent_nudge.py
ERROR tests/unit/test_rate_limiter_eviction.py
!!!!!!!!!!!!!!!!!!! Interrupted: 6 errors during collection !!!!!!!!!!!!!!!!!!!!
6 errors in 1.99s
```

**This corrects a claim in round 2's report.** Its closing line — *"reverting `b7b5fa7` … leaves the
stub path, the whole suite and both `make demo` targets green"* — is false at HEAD. `b7b5fa7` is
two separable things, and only one of them is in dispute:

| half of `b7b5fa7` | what it is | in dispute? |
|---|---|---|
| `summarise_span` / `preview_value` + `__all__` | a P7→P8 interface publication, so one implementation describes a span for both the SSE rail and `trace[]` (§11.3) | no — P8 cannot exist without it, and §9.1's "public interface" block names only `run_turn`/`resume_turn`, so this is the *kind* of addition a P8 consumer is expected to need |
| `_nudge` + `WORKFLOW_INCOMPLETE` / `ACTION_OUTSTANDING` + the `_absorb` narrowing + the two prompt rules | the act-loop mechanism | **yes — this is the whole of question 1–3** |

### New this round (2) — the disputed half, priced

The loop half was reverted **on its own** (the reverse patch applied, then the two exports and their
`__all__` entries put back by hand) and the suite and both demo targets re-run against it:

```
$ .venv/bin/pytest -q                      # with the loop half reverted, exports kept
ImportError while importing test module 'tests/unit/test_agent_nudge.py'
E   ImportError: cannot import name 'ACTION_OUTSTANDING' from 'hrmosaic.agent.orchestrator'
1 error in 1.94s

$ .venv/bin/pytest -q --ignore=tests/unit/test_agent_nudge.py
1087 passed in 120.92s (0:02:00)

$ make demo1 >rev_d1.log 2>&1 && make demo2 >rev_d2.log 2>&1; echo "exit=$?"
exit=0
rev_d1.log:37:-- outcome: answered
rev_d2.log:50:-- outcome: answered
```

The source files were restored immediately afterwards and the tree verified clean
(`git checkout -- <the five files>; git status --porcelain` → empty) **before** this round's own
edit was made.

**So the price of ruling against the mechanism is exact and small offline:** drop
`tests/unit/test_agent_nudge.py` (16 tests, which import the two reminder constants and would go
with them), and the other 1087 tests, `make lint` and both `make demo` targets stay green under the
stub. The only thing that is actually lost is the live-provider behaviour those 16 tests now
describe — which is precisely the thing CI cannot re-measure, and precisely why the ruling is
worth making deliberately rather than by default.

### New this round (3) — the §9.3 mis-citation is fixed (round 2's concern 2, closed)

Round 2 identified it as a real defect and left it unfixed to avoid adding to the churn the finding
is about. In round 3 that trade reverses: a P7 reviewer is about to read those comments in order to
rule, and reading a wrong spec citation while ruling is worse than a six-line comment diff. Spec
§9.3 is *"The two workflows (R4.2)"* and says only *"The LLM chooses tools; the workflow spec decides
when the turn is complete."* The mechanism is a step of the **act loop**, §9.1 step 2.

`8cf7286` changes comments in `src/hrmosaic/agent/orchestrator.py` and nothing else — no
statement, no string, no signature, no golden:

| site | was | now |
|---|---|---|
| `:125` (`WORKFLOW_INCOMPLETE` docstring comment) | "the reminder the loop is allowed to inject (§9.3, P8's live check)" | "the act loop is allowed to inject (§9.1 step 2, P8's live check). It is a loop mechanism: §9.3 supplies the *gap* — its completion predicate — and says nothing about telling the model." |
| `:420` (`_Turn.nudged`) | "Each of the two reminders of §9.3" | "Each of the two act-loop reminders (§9.1 step 2)" |
| `:799` (`_nudge` docstring) | "what the turn still owes (§9.3)" | "…what the turn still owes." + "A step of the act loop (§9.1 step 2); the debt it reports is §9.3's completion predicate and, for the second reminder, the action the router recorded." |
| `:988` (`_absorb`) | "They no longer do (P8's live check, §9.3)." | "…(P8's live check: §9.3's predicate now reads evidence the same way §7.4's G1 does)." |

The two sites that were **already right** were left alone: `_action_outstanding`'s docstring
("§9.3's `pto_request` predicate is satisfied by a cited answer alone") genuinely is about §9.3.
§7.4 is where G1 is specified (`agent/guardrails/g1.py` cites it too), which is why the `_absorb`
comment now names both sections: the whole point of that change is that the predicate and the gate
read "evidence" the same way.

**What this does not do.** It does not close the finding. It is a fifth P8 commit touching a
P7-owned file, and it is inside whatever the P7 re-review rules on — it makes the material accurate,
not the routing question smaller.

---

## Files changed in this round

**Modified:** `src/hrmosaic/agent/orchestrator.py` (comments only; +19/−13, four comment blocks
re-cited and re-wrapped).

**New:** none. No test was added or changed — this round's edit is not executable, and the
behaviour it documents is already pinned by `tests/unit/test_agent_nudge.py` (16 tests) and
`tests/contract/test_prompt_golden.py`, both re-run below.

---

## Definition-of-done output (real, from this round's HEAD `8cf7286`)

```
$ .venv/bin/pytest tests/contract/test_app_starts.py tests/contract/test_chat_page_renders.py tests/contract/test_health.py tests/contract/test_lifespan.py -q
21 passed in 11.80s

$ .venv/bin/pytest tests/contract/test_chat_contract.py tests/contract/test_chat_trace_projection.py -q
14 passed in 10.32s

$ .venv/bin/pytest tests/contract/test_chat_privileged_options.py tests/contract/test_missing_key_is_graceful.py -q
10 passed in 6.38s

$ .venv/bin/pytest tests/contract/test_access_gate.py tests/contract/test_personas.py -q
24 passed in 12.18s

$ .venv/bin/pytest tests/integration/test_fault_mcp_down.py tests/integration/test_fault_unknown_employee.py tests/integration/test_fault_empty_retrieval.py tests/integration/test_fault_ambiguous.py -q
20 passed in 12.69s

$ .venv/bin/pytest tests/integration/test_health_mcp_down.py tests/integration/test_sse.py tests/integration/test_mcp_remote_url.py -q
10 passed in 5.58s

$ .venv/bin/pytest tests/integration/test_mcp_discovery.py -q
9 passed in 5.51s

$ .venv/bin/pytest tests/integration/test_confirm_resume_lifecycle.py -q
10 passed in 8.06s

$ .venv/bin/pytest tests/integration/test_audit_completeness.py tests/integration/test_process_exit_mid_turn.py tests/unit/test_action_safety.py -q
22 passed in 12.91s

$ .venv/bin/pytest tests/e2e/test_demo_tasks.py -q
5 passed in 4.40s
```

The tests covering the amended file, run on their own (the reminder mechanism, and the three
prompt goldens the amended file's neighbours produce):

```
$ .venv/bin/pytest tests/unit/test_agent_nudge.py tests/contract/test_prompt_golden.py -q
34 passed in 1.72s
```

`make demo1 && make demo2` — chained, exit 0:

```
$ make demo1 >d1.log 2>&1 && make demo2 >d2.log 2>&1; echo "exit=$?"
exit=0
d1.log:37:-- outcome: answered
d2.log:50:-- outcome: answered
```

Whole suite and lint:

```
$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
171 files already formatted

$ make test
.venv/bin/pytest -q
1103 passed in 121.72s (0:02:01)
```

---

## Concerns from this round

1. **F6 is open and rounds are spent.** Three fix rounds have now reported the same routing
   request; an implementer cannot close it. The precedent in this ledger is P5, which went
   3/3 with one open finding and was then **parked** with an explicit `Ruling:` line in
   `progress.md`. That is the shape this needs: either a ruling on questions 1–3 of round 2's
   restatement, or an explicit ratification of `b7b5fa7` as it stands. Round 3 has made both
   outcomes cheap — the behaviour is asserted (16 tests) and the revert is priced (1087 passed,
   both demos green, minus those 16 tests) — but it cannot choose between them.
2. **Only the loop half of `b7b5fa7` is rulable.** The `summarise_span` / `preview_value` export is
   a P8 build dependency; a ruling phrased as "revert `b7b5fa7`" would break `web/sse.py`. Phrase
   any revert as "revert the loop half, keep the two exports".
3. **Round 2's closing claim about the revert was wrong and is corrected above.** Anyone reading
   that paragraph without this one will under-price the revert.
4. **The four concerns from round 1 stand unchanged** (the catch-all as middleware, the catch-all
   swallowing programmer errors into a 200, `RATE_SWEEP_INTERVAL_S` as a constant, and the loopback
   exemption trusting `request.client.host`). Round 2's concern 2 (the §9.3 citation) is now closed.
