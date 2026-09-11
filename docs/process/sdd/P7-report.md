# P7 — `agent/`: orchestrator, guardrails, workflows

**Status:** DONE. Two local commits on `main`, nothing pushed.
`c0b4dd5 P7(llm): strip the root combinator on the OpenAI-compatible path too`
`c1221fe P7(agent): route → act → synthesize with six guardrails and two workflows`
HEAD `c1221fec0f6d7092c6bcbb2067a577fb3267c120`. Suite **927 tests, pristine, ~37 s** (from 781 at P5).

---

## 1. What was built

### 1.1 `src/hrmosaic/agent/client.py` — the MCP client and discovery

* **Cached handshake, one `mcp_discovery` span per turn** (§8.2 step 3). `initialize` + `tools/list`
  run once per process and again after a failure; the span is emitted every turn with
  `cached=false` and a real `handshake_ms` on the turn that handshook, `cached=true` /
  `handshake_ms=0` afterwards, plus `catalog_sha`, `tool_count`, `protocol_version` and
  `server_info`.
* **The catalog → tool-array conversion that *is* the model's tool list** (R5.4).
  `DiscoveredCatalog.tool_schemas(allowed)` is the only source of the `tools` argument any adapter
  ever sees; the catalog is sorted by name so the cached prefix stays byte-stable, and each entry's
  `input_schema` is validated as a well-formed JSON Schema object at discovery.
* **The three `_meta` keys** of §8.7 on every `tools/call`, including `mosaic/retrieval`, which is
  the only path from `/chat`'s options to the retriever.
* **`_trace` lifting**: nested `retrieval` spans are re-parented under the `tool_call` span and
  persisted through `core/trace.py`; `server_timing_ms` and the echoed actor land on the
  `tool_call` payload.
* **`confirmation_token` is stripped from every call**, unconditionally, and re-attached only by
  `resume_turn`.
* **Why the session lives in its own task** (documented in the module docstring): `stdio_client`
  and `streamable_http_client` are anyio context managers holding cancel scopes, and anyio refuses
  to let a scope be exited by a task other than the one that entered it. A session cached across
  turns is entered on turn 1 and closed at shutdown — different tasks — so one background task owns
  the whole context-manager stack and every caller talks to the `ClientSession` it publishes.

### 1.2 `src/hrmosaic/agent/router.py` — the gate

`RouteDecision` is strict at every level (no defaults; optionality is a nullable union) and now sits
in `RESPONSE_SCHEMAS` in `tests/unit/test_strict_schema_emission.py`. `intent` is a closed
four-value vocabulary — `policy_qa` · `employee_data` · `workflow` · `action` — with `out_of_scope`,
`sensitive` and `needs_clarification` as **flags** rather than intents, because a turn can be out of
scope *and* have been a policy question, and §13.4's matrix scores the outcome.

`allowed_tools()` / `offered()` implement §9.2's hard restriction to tools 1–4 on `policy_qa`, plus
the per-turn `tools_disabled` ablation filter and the one-step `reopened` recovery.
`normalise()` caps the rationale at 200 characters and drops invented employee ids and tool names
before either reaches a span.

### 1.3 `src/hrmosaic/agent/orchestrator.py` — the loop

`run_turn(req)` and `resume_turn(session_id, turn_id, confirmation_token)`, exactly as §9.1 names
them, plus the §11.1 request/response models `web/api.py` imports at P8 (`ChatRequest`,
`ChatOptions`, `ChatResponse`, `ConfirmationCard`, `Usage`, `Timings`) — exported from
`hrmosaic.agent`, so P8 needs four names.

The pipeline, and the span it leaves, from a real turn (demo task 1 over stdio):

```
 1 mcp_discovery  mosaic-hr                    9 tools discovered over stdio
 2 guardrail      G4_injection_shield          allow · 1 user_message chunks clean
 3 llm_call       stub:stub                    purpose=route
 4 plan           router                       intent=workflow workflow=remote_work_eligibility
 5 llm_call       stub:stub                    purpose=act
 6 tool_call      lookup_employee_profile      ok
 7 tool_call      search_policy_documents      ok
 8 retrieval      search_policy_documents      5 chunks · top dense 0.7827 · 3 docs
 9 guardrail      G4_injection_shield          allow · 5 retrieval chunks clean
10 llm_call       stub:stub                    purpose=act
11 tool_call      get_policy_section           ok
12 tool_call      search_policy_documents      ok
13 retrieval      search_policy_documents      5 chunks · top dense 0.7707
14 guardrail      G4_injection_shield          allow · 5 retrieval chunks clean
15 llm_call       stub:stub                    purpose=act
16 tool_call      check_policy_compliance      ok
17 plan           act_summary                  3 act step(s), 5 tool call(s), stop_reason=answered
18 guardrail      G1_evidence_gate             allow · max dense 0.783, 10 supporting chunks
19 llm_call       stub:stub                    purpose=synthesize
20 guardrail      G2_citation_resolvability    allow · 5/5 citations resolved
21 guardrail      G3_fact_vs_recommendation    allow · 5 blocks, every policy_fact cited
22 guardrail      G6_pii_secret_redaction      allow · final answer carried nothing to redact
```

Budgets (`AGENT_MAX_STEPS=6`, `AGENT_MAX_TOOL_CALLS=8`, `AGENT_WALL_CLOCK_S=90`) are checked at the
top of every step and before every call; exceeding one produces §9.4's **graceful partial answer**
("I reached my step limit for this turn; here is what I established before stopping.") prepended as
a `recommendation` block, an `error` span carrying the reason, `outcome="partial"` and the matching
`stop_reason`. The one-step `catalog_reopened` recovery of §9.2 runs when G1 fails while
`intent == "policy_qa"`, records its own `plan` span and counts against `AGENT_MAX_STEPS`.

**`trace[]` is projected from the store, after the flush** — not from an in-memory collector. Three
things fall out of that and none is free any other way: the projection and the dashboard are
provably the same rows (USER.4); a resumed turn's response carries the **whole** turn rather than
only the spans written after the reopen, so §11.1's "equality holds again on the resumed response"
is true by construction; and the previews show the redacted, capped payload the record actually
holds (§10.4, §10.5). `usage` / `timings` come from the closed turn's own rollups for the same
reason.

`resume_turn` rehydrates from the store: the message array from the last `act` call's `llm_messages`
rows, the chunk set from the `retrieval` spans, prior tool results from the `tool_call` spans, and
the step counter from the count of `act`-purpose `llm_call` spans. It emits the **confirmed**
`confirmation` span immediately before re-issuing the gated call, because §13.4's action-safety
clause 1 requires it to be earlier by `seq` than the write it authorised and only that function
controls the ordering. The docstring states the contract with `web/` explicitly so P8 does not
double-emit: pending here, confirmed here, **declined is `web/`'s** (`resume_turn` is not called on
a decline).

### 1.4 Guardrails `g1..g6`

Each module exposes a **pure** decision function plus a `check()` that emits the `guardrail` span,
so a unit test asserts the rule without a store and the loop asserts the record with one. A clean
pass still emits a span with `verdict="allow"`: an absent span cannot distinguish "nothing matched"
from "nobody looked".

| id | shape | notes |
|---|---|---|
| G1 | `evaluate` / `check` / `refusal` | total by construction (§7.1's fill step); the refusal reads `core.corpusread.list_documents()` and makes **zero** `tools/call` |
| G2 | `resolve` / `apply` / `check` | resolves against the **real index**, not the retrieved set; the strip → drop → refuse cascade |
| G3 | `apply` / `check` | runs over **raw** blocks before `AnswerSchema` validation, because §7.3's validator would otherwise lose the whole answer instead of relabelling one block |
| G4 | `scan` / `scan_all` / `check` | the §7.4 pattern table verbatim, scoped to imperative-to-assistant forms; marks the chunk *before* the lifted `retrieval` span is persisted |
| G5 | `classify` / `evaluate` / `escalation` / `check` | the router decides *that* a turn is sensitive; the message only picks *which* inbox, and the four addresses are pinned against the corpus in both directions |
| G6 | `scrub` / `check` | delegates to `core/redact.py` (P1) and adds the audit record the other five have; `redact()` is idempotent, so `core/trace.py`'s own sweep on the closing UPDATE changes nothing |

### 1.5 Workflows and prompts

`remote_work_eligibility` and `pto_request` are declarative `WorkflowSpec`s — required slots, the
documents the evidence should span, `requires_tool_results`, and an `is_complete(LoopState)`
predicate that starts with "a result from *this* tool is in state", which is what makes the
`no_structured_tools` ablation move workflow completion rather than only ToolSelection (§13.9).

Each of the three prompts carries exactly two Jinja blocks and the split **is** the frozen prefix
ordering: `system` is byte-stable (no persona, no evidence, no question, no timestamp) so the cached
Anthropic prefix *tools → system* never moves, and `user` carries persona → evidence envelopes →
question. `render()` returns the pair and never a single blob, so a caller cannot accidentally put
per-turn bytes in front of the breakpoint. Six golden files under `tests/fixtures/prompts/` are
committed: a prompt edit shows up twice in a diff, once as the `.j2` change and once as the rendered
bytes, which is the deliberate re-review §7.2 asks for.

### 1.6 Outside `agent/`

* **`core/llm/base.py` + both adapters** — `ROOT_COMBINATOR_KEYS` / `without_root_combinators()`.
  See §3 for the TDD evidence.
* **`scripts/probe_provider.py`** — `SYSTEM_PROMPT` is now `act.j2`'s rendered system block rather
  than a hand-written stand-in, so the measured prefix is the one that ships.
* **`pyproject.toml`** — `[tool.setuptools.package-data] "hrmosaic.agent.prompts" = ["*.j2"]`.
  The prompts are loaded from disk relative to `prompts/__init__.py`; without this a non-editable
  install (the P11 Docker image) would ship a package with no prompts in it. The repo installs
  `-e .` so no test would have caught it.
* **`tests/conftest.py`** — `mounted_server()` / `mounted_mcp_url` (moved up from the integration
  conftest, which now imports it) and the `run_agent` / `spans` fixtures.
* **`tests/fixtures/llm_scripts/demo_task_1.json`** — re-recorded (§2.4).

---

## 2. Definition of done — real output

Every command below was run at `c1221fe` with a clean working tree.

```
$ pytest tests/unit/test_g1_evidence_gate.py tests/unit/test_g2_citation_resolvability.py tests/unit/test_g3_fact_vs_rec.py -q
..............................                                           [100%]
30 passed in 2.37s

$ pytest tests/unit/test_g4_injection.py tests/unit/test_g4_no_false_positives.py tests/unit/test_g5_sensitive.py -q
.........................................................                [100%]
57 passed in 2.83s

$ pytest tests/unit/test_confirmation_token_stripped.py tests/contract/test_prompt_golden.py tests/contract/test_no_chain_of_thought.py -q
.......................................                                  [100%]
39 passed in 2.45s

$ pytest tests/e2e/test_rag_only_makes_no_people_calls.py -q
...                                                                      [100%]
3 passed in 4.14s

$ pytest tests/architecture/test_conventions.py -q
.....                                                                    [100%]
5 passed in 0.03s
```

Beyond the brief's five, the standing CI path:

```
$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
138 files already formatted

$ pytest -q
[13 lines of dots]
927 passed in 36.89s

$ python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers

$ python -m hrmosaic.rag.ingest --verify-manifest
OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
```

And the live provider probe, re-measuring the prefix against P7's real system prompt (§2.5):

```
$ python scripts/probe_provider.py
probe_provider — 2026-09-10

Anthropic claude-haiku-4-5
  tools offered: 9 (as published, no `strict`)
  measured tools+system prefix: 3523 tokens (minimum cacheable prefix 4096) — cache assertion not armed
  call 1: finish=end_turn in=3830 out=64 cache_write=0 cache_read=0 mode=output_config_json_schema cost=$0.004150 ttfb=2161 ms
  call 2: finish=end_turn in=3830 out=64 cache_write=0 cache_read=0 mode=output_config_json_schema cost=$0.004150 ttfb=1378 ms
  cache: not asserted — the prefix is below the floor, so no entry is written and the two counters are expected to be 0 (recorded, not a failure)

Judge gemini-3.5-flash-lite at https://generativelanguage.googleapis.com/v1beta/openai/
  judge: finish=stop in=67 out=69 cache_write=0 cache_read=0 mode=json_schema_strict cost=$0.000000 ttfb=1349 ms
  verdict: score=1 rationale='The claim states that full-time employees accrue 1.50 PTO days per month after t'

PASS
```

Total live spend for the re-measure: **$0.0083** (three calls; the Gemini judge is free).

---

## 3. TDD evidence

### 3.1 The OpenAI-compatible root-combinator strip — red, then green

`tests/unit/test_openai_compat_tool_schema.py` was written first and the one-line change reverted to
the pre-P7 behaviour (`"parameters": tool.input_schema`) to watch it fail:

```
=== RED (stripping removed) ===
E         Left contains 1 more item:
E         {'oneOf': [{'required': ['heading_path']}, {'required': ['chunk_id']}]}
FAILED tests/unit/test_openai_compat_tool_schema.py::test_the_openai_shape_carries_no_root_combinator
FAILED tests/unit/test_openai_compat_tool_schema.py::test_a_nested_combinator_survives
FAILED tests/unit/test_openai_compat_tool_schema.py::test_both_adapters_send_the_same_stripped_schema_on_the_real_wire[get_policy_section]
3 failed, 4 passed in 1.03s

=== GREEN (stripping restored) ===
.......                                                                  [100%]
7 passed in 0.90s
```

The four that pass in both states are the guards that stop the test being vacuous — that the
committed schema *really does* carry a root `oneOf`, that nothing but the combinator is dropped,
that a schema without one is returned unchanged, and that the published schema is never rewritten.

### 3.2 The tests found two real bugs before the commit

* **A name collision in `client.py`.** `McpClient` already had `self._connection: _Connection | None`
  and I added a `_connection()` *method*; the attribute shadowed it and every turn died with
  `TypeError: 'NoneType' object is not callable` at `client.py:352`. Six tests went red at once;
  the method is now `_open_connection()`.
* **A failed tool result entering the workflow state.** An `isError` result that survived its one
  repair was still passed to `_absorb()`, so a rejected `check_policy_compliance` would have counted
  as "a compliance verdict is in state" for `is_complete`. It now goes back to the model (the only
  way it learns what went wrong) and nowhere near the state.

### 3.3 The guardrail tests are behaviour, not mocks

Every loop-level assertion runs against a **real** MCP server — a `python mcp/server_entrypoint.py
--stdio` subprocess, or the mounted `build_mounted_app()` on a real uvicorn. `StubAdapter` replaces
only the provider. So "an out-of-scope turn makes no tool call" and "the forged token never reached
the server" are facts about real `tools/call` traffic, not about a stand-in that could not have made
one.

`test_g4_no_false_positives.py` runs `scan()` over all **204** chunks of the committed manifest and
asserts the three clauses §7.4 names, deliberately without an exact count.

---

## 4. Files changed

**New — `src/hrmosaic/agent/`** (15 files): `__init__.py`, `client.py`, `router.py`,
`orchestrator.py`, `guardrails/{__init__,g1,g2,g3,g4,g5,g6}.py`,
`workflows/{__init__,remote_work,pto_request}.py`,
`prompts/{__init__.py,route.j2,act.j2,synthesize.j2}`.

**New — tests** (11 files): `tests/unit/test_g1_evidence_gate.py`,
`tests/unit/test_g2_citation_resolvability.py`, `tests/unit/test_g3_fact_vs_rec.py`,
`tests/unit/test_g4_injection.py`, `tests/unit/test_g4_no_false_positives.py`,
`tests/unit/test_g5_sensitive.py`, `tests/unit/test_confirmation_token_stripped.py`,
`tests/unit/test_agent_budgets.py`, `tests/unit/test_openai_compat_tool_schema.py`,
`tests/contract/test_prompt_golden.py`, `tests/contract/test_no_chain_of_thought.py`,
`tests/e2e/test_rag_only_makes_no_people_calls.py`,
`tests/integration/test_resume_rehydrates_from_the_store.py`.

**New — fixtures**: `tests/fixtures/prompts/*.txt` (6 golden files);
`tests/fixtures/llm_scripts/{out_of_scope,sensitive,rag_only,forged_token,injection_probe,confirm_resume,budget_probe}.json`.

**Modified**: `src/hrmosaic/core/llm/{base,anthropic,openai_compat}.py`,
`scripts/probe_provider.py`, `pyproject.toml`, `tests/conftest.py`,
`tests/integration/conftest.py`, `tests/unit/test_strict_schema_emission.py`,
`tests/fixtures/llm_scripts/demo_task_1.json`, `CHANGELOG.md`.

Nothing under `mcp/`, `corpus/`, `mock_data/`, `data/index/` or `.github/` was touched. `.env` was
never read, printed or committed.

---

## 5. Ambiguities resolved, and how

Each of these took the simplest reading that satisfies the spec; none changes a user-facing contract,
so none was a STOP case.

1. **"→ SYNTHESIZE" on the out-of-scope and sensitive branches (§9.1).** Read as *"jump to the
   answer-production step"*, not *"make a synthesize model call"*. Both branches produce their answer
   **deterministically**: there is no evidence to synthesize from, G1 explicitly forbids answering
   from parametric knowledge, and the pre-check branch is required to be zero-LLM. Consequences that
   argue for it: the out-of-scope turn issues zero `tools/call` (so §13.4's `ToolPrecision` scores
   1.0), the sensitive turn burns no tools and answers nothing directly, and both are testable
   without a stub script entry.
2. **How many `plan` spans a turn writes.** §9.1 puts one after routing, §9.2 requires one at a
   catalog reopen, and §9.7 says a `plan` span carries `step_summaries[]` — which cannot be filled
   at routing time, because the steps have not happened. Resolution: **a `plan` span per planning
   moment**, told apart by `step_index` — the router's (index 0, and the one §9.2's confusion matrix
   reads, named `router`), a reopen (`replan`, `catalog_reopened: true`), and one closing each act
   run (`act_summary`) carrying `step_summaries[]` and the tools actually called. Two spans on an
   ordinary tool-using turn, one on a refusal.
3. **What the `repair` purpose repairs (§9.1, §9.8).** §9.1 names exactly one repair — "isError
   (schema) → ONE repair round-trip with the error appended" — and §9.8 gives `repair` a **512-token**
   budget and constrained JSON. 512 tokens is far too small for a re-run act step and exactly right
   for a corrected argument object, so `repair` is a constrained-JSON `ToolCallRepair`
   (`tool_name`, `arguments`, `rationale_summary`). It is added to `RESPONSE_SCHEMAS` alongside
   `RouteDecision`.
4. **The `intent` vocabulary.** §9.2 names `policy_qa`; §11.1's example shows `intent=workflow`; the
   dataset's `category` is a different axis. Chosen: the closed four — `policy_qa`, `employee_data`,
   `workflow`, `action` — with out-of-scope / sensitive / clarification kept as flags. Adding them as
   intents would have made the two axes overlap and left "a policy question that turned out to be
   out of scope" unrepresentable.
5. **`pto_request.is_complete` vs. an explicit request to act (§9.3 vs §18.2).** The predicate as
   written — balance in state, a verdict, **and** either ≥ 2 citations *or* a confirmed write — is
   satisfied by a cited answer alone, so it would have closed demo task 2's turn one step before the
   confirmation gate the demo exists to show. Resolution: a completion predicate decides when the
   slots are filled; it does not get to drop a request the user made in words. When the router's
   intent is `action` and no write has been proposed yet, the loop keeps going. Implemented as one
   small, documented predicate (`_action_outstanding`).
6. **Who emits the confirmed `confirmation` span.** §11.2 describes `/chat/confirm` emitting it, but
   §13.4's action-safety clause 1 requires it to be *earlier by `seq`* than the write, and only
   `resume_turn` controls that ordering. `resume_turn` emits it; the docstring states the split
   (pending + confirmed here, declined in `web/`) so P8 does not double-emit.
7. **A tool the gate did not offer.** §9.2 says the catalog is restricted; it does not say what
   happens if the model asks anyway. Chosen: refuse at the call boundary, record an `error` span
   `tool_not_offered`, and hand the model a `TOOL_NOT_OFFERED` tool result so it can recover. The
   alternative — trusting the omission — would mean the e2e gate proves only that a well-behaved
   model behaves well.
8. **The out-of-corpus keyword pre-check (§9.1 step 0).** The spec names the list but not its
   contents. Eight unambiguous phrases (`weather`, `stock price`, `capital of`, …), each one a
   Mosaic HR corpus can never answer, with a comment saying G1 is the real gate and this only saves
   a model call. Kept deliberately narrow because a false positive here refuses a real question.

---

## 6. Self-review findings, and what changed because of them

1. **`trace[]` was collected in memory** by a registered span listener. Correct for a fresh turn,
   wrong for a resumed one: the listener registers at resume time, so the response would have
   carried only the post-reopen spans and §11.1's "equality holds again on the resumed response"
   would have been false. Replaced with a read from the store after the flush, which is also
   strictly better for USER.4 and for redaction fidelity. `test_the_resumed_response_carries_the_whole_turn`
   pins it.
2. **`_degraded()` claimed the tool server was unreachable on a synthesis failure**, and emitted a
   second `error` span with the wrong `error_kind`. It now takes the kind, the caveat and the
   component: the two ways a turn degrades say different things, and one shared sentence would have
   been a small lie in whichever case it did not describe.
3. **§9.4's graceful partial answer was missing.** The loop stopped at a budget and set
   `stop_reason`, but emitted no `error` span and prepended no note. Both added, plus
   `tests/unit/test_agent_budgets.py`.
4. **`project()` indexed `payload["arguments"]`.** §10.5 replaces an oversize payload with a stub, so
   one truncated `tool_call` span would have taken the whole response down. Now `.get`.
5. **The repair round trip could exceed `AGENT_MAX_TOOL_CALLS` by one.** It now checks the budget
   before starting a round trip whose result cannot be spent.
6. **A dead alias.** `UNSUPPORTED_TOOL_SCHEMA_KEYS` survived the `base.py` move with no callers;
   deleted, with its measured provenance moved onto the shared constant so the fact is recorded once.
7. **The `httpx2.AsyncClient` built for the access-gate header was never closed.** `streamable_http_client`
   closes only a client it made itself, so the connection now owns and closes ours.
8. **Two tests were asserting against the wrong database.** `test_confirmation_token_stripped` ran
   over stdio and asserted `SELECT count(*) FROM mock_writes == 0` — but the stdio subprocess has a
   trace store of its own, so the count was vacuous *and* a regression would have written a real row
   into the developer's `data/runtime/traces.sqlite`. Both confirmation tests now run against the
   mounted HTTP topology, which is the deployed one and the only one where the gate is observable.
   The reasoning is in the `mounted_server()` docstring and in `CHANGELOG.md` so P8 does not
   rediscover it.
9. **A hand-rolled fake in the G4 test.** The original quarantine test built an `Orchestrator` with
   `__new__` and a stub turn object. Replaced with a real turn through the real loop over a real
   server (`injection_probe.json`), which is also the shape eval item `inj-001` will take.

---

## 7. Concerns for the reviewer and for P8

1. **The prompts are placeholders in the sense that matters least and are frozen in the sense that
   matters most.** They are hand-authored, not tuned against the eval, and P10 will read the
   observed score distribution and may want to change them. The golden files make that a deliberate,
   reviewable act, which is what §7.2 asks for — but nobody has yet measured whether these prompts
   produce good answers from a live model. The only live check so far is the probe's one-sentence
   tool-choice question.
2. **The cacheable prefix is still below Haiku 4.5's floor: 3523 of 4096 tokens.** Recorded, not
   padded. Prompt caching therefore writes nothing today, exactly as §9.8 predicts, and the
   `llm_call` span will keep reporting zeros. If P10 or P12 lengthens the system prompt for other
   reasons it may cross the line by accident; the probe re-measures.
3. **Three P8 files depend on shapes I chose, not on shapes the spec pinned.** `ChatRequest` /
   `ChatResponse` field names, the `run_agent`-style construction of an `Orchestrator` in the app
   lifespan, and the pending/confirmed/declined split of the `confirmation` spans. All three are
   documented in docstrings, but a P8 reviewer should check them against §11.1 line by line rather
   than trusting me.
4. **`demo_task_2.json` is not written.** §18.2's fixture is P8's, with `test_demo_tasks.py`.
   `confirm_resume.json` is a smaller cousin used by P7's own resume test; P8 should author the demo
   script rather than widen mine, and the Makefile's `make demo2` target still points at a file that
   does not exist yet.
5. **`AGENT_WALL_CLOCK_S` is checked but not tested.** The three budgets share one code path and one
   `stop_reason` vocabulary, and the other two are tested; a test that burns 90 s of wall clock to
   prove the third would be the slowest thing in the suite by two orders of magnitude. Noted in the
   test module's docstring.
6. **The suite grew from 781 to 927 tests and from ~24 s to ~37 s.** Most of the increase is real MCP
   sessions: nine tests spawn a stdio subprocess or a uvicorn. I merged assertions to keep the count
   of spawns down; if CI time becomes a problem, the honest lever is to consolidate further rather
   than to swap in a fake client.
7. **Two files outside the brief's deliverables list.** `tests/unit/test_agent_budgets.py` and
   `tests/integration/test_resume_rehydrates_from_the_store.py` cover deliverables the brief names
   (the act loop's budgets; `resume_turn`) but for which it names no test. Shipping either untested
   seemed worse than the small scope stretch. `tests/integration/test_confirm_resume_lifecycle.py`
   remains P8's, unwritten.
8. **`pyproject.toml` gained a `package-data` entry.** Small, but it is a P0-owned file and the
   change is invisible to every current test, because the repo installs `-e .`. It matters only at
   P11, when the Docker image installs the package properly and would otherwise ship an
   `agent/prompts/` directory with no prompts in it.

---

# P7 — fix round 1/3

**Status:** all five findings addressed. One local commit on `main`, nothing pushed.
`ca13389 P7(agent): fix: legal wire conversations, §7.2's c.text, and a failed confirmed write`
HEAD `ca13389fab1ecbc307b9d7b7e3e66d7006f4b8c7`.
Suite **941 tests, pristine, ~42 s** (from 927). `make lint` clean. `.env` never read, printed or
committed; only the files listed in §F.4 were staged.

## F.1 What changed, finding by finding

### [Critical] Two consecutive `user` messages on a multi-tool act step

`src/hrmosaic/core/llm/anthropic.py` — `_split_system` now **coalesces consecutive same-role
messages** into one message whose content is the concatenation of their blocks, and flattens a
lone text block back to a plain string so every existing wire shape is byte-identical.

The fix is in the adapter rather than in the loop because the provider-neutral `Message` can only
carry **one** tool result (`tool_call_id` is singular), so the orchestrator physically cannot emit
one message holding two `tool_result` blocks without changing a P6-owned type. Coalescing at the
translation boundary also fixes `_repair`'s tool-results-then-user-text sequence, which was the
same violation in a second place, and protects any future caller.

Wire shape for one act step that asked for two tools, before → after:

```
before   assistant[tool_use c1, tool_use c2]   user[tool_result c1]   user[tool_result c2]
after    assistant[tool_use c1, tool_use c2]   user[tool_result c1, tool_result c2]
```

**Covering tests.** `tests/unit/test_wire_message_alternation.py` (new, 7 tests) asserts the two
documented Messages API rules over the bytes `httpx2.MockTransport` received — roles alternate, and
every `tool_use` id is answered by a `tool_result` in the *immediately following* message — for a
two-tool step, for the repair shape, for groupings of 1/2/3, and that a lone text message still
travels as a plain string. It also pins that the OpenAI-compatible failover is unaffected (it emits
real `role: "tool"` messages).
`tests/integration/test_act_loop_wire_shape.py` (new) closes the other half: it drives the **real**
act loop over a **real** stdio MCP server with the committed `demo_task_1.json` (act steps grouped
2 + 2 + 1 — the grouping the finding names) through a recorder that forwards to the same
`StubAdapter` the suite uses and keeps the array it was handed, then translates each act call with
the shipped `AnthropicAdapter.request_kwargs`. That is the test the suite could not previously have:
`StubAdapter` never looks at `messages`.

Red/green, with the coalescing removed and restored:

```
=== RED (conversation.append((role, list(blocks))) instead of the merge) ===
E       AssertionError: roles must alternate, got ['user', 'assistant', 'user', 'user', 'user']
FAILED tests/unit/test_wire_message_alternation.py::test_a_two_tool_step_answers_both_calls_in_one_user_message
FAILED tests/unit/test_wire_message_alternation.py::test_the_repair_round_trip_sends_one_assistant_turn_and_one_user_turn
FAILED tests/unit/test_wire_message_alternation.py::test_every_grouping_of_one_act_step_is_well_formed[2]
FAILED tests/unit/test_wire_message_alternation.py::test_every_grouping_of_one_act_step_is_well_formed[3]
4 failed, 3 passed in 1.05s

E       AssertionError: roles must alternate, got ['user', 'assistant', 'user', 'user']
FAILED tests/integration/test_act_loop_wire_shape.py::test_every_act_call_of_demo_task_1_is_a_legal_messages_request
1 failed in 1.98s

=== GREEN ===
7 passed in 0.94s
1 passed in 1.90s
```

### [Important] `_repair` re-appended the assistant message

`src/hrmosaic/agent/orchestrator.py` — `_repair` no longer appends
`Message(role="assistant", tool_calls=[call])`: `turn.messages` already ends with the assistant
message carrying that `tool_use`, because `_act` appends it before it runs the step's calls.

One thing the finding's prescription does not cover and the fix does: when the failing call is not
the **last** of its step, the step's other `tool_use` blocks are still unanswered at repair time, and
an unanswered `tool_use` is the same 400 as a duplicated id. So the repair request also carries a
placeholder result (`NOT_RUN_YET`, `{"status": "not_run", …}`) for every id of the in-flight step
that has no result yet, found by `_step_calls(turn)` minus the ids already answered. The repair
message list is local and thrown away, so a placeholder never reaches `turn.messages` or a span.

**Covering tests.** `tests/integration/test_repair_round_trip.py` (new, 3 tests) with
`tests/fixtures/llm_scripts/repair_round_trip.json` (new). The script's first act step asks for two
tools and the **first** of them carries `employee_id: "me"`, which the committed `check_pto_balance`
schema really rejects — so the loop is inside call 1 with call 2 unanswered, over a real stdio
server, and the repaired arguments really do succeed. The tests assert: both `tool_call` spans exist
(`is_error` True then False) with no `repair_failed` error span and exactly one `repair` purpose;
that the repair request translates to `["user", "assistant", "user"]` with every asked id answered
in order plus the corrective text last; and that no `tool_use` id is sent twice.

```
=== RED (assistant message re-appended, no placeholders) ===
E       AssertionError: ['toolu_rep_1', 'toolu_rep_2', 'toolu_rep_1']
E       assert 3 == 2
FAILED tests/integration/test_repair_round_trip.py::test_the_repair_request_is_a_legal_messages_request
FAILED tests/integration/test_repair_round_trip.py::test_the_assistant_turn_carrying_the_failed_call_is_sent_exactly_once
2 failed, 1 passed in 3.97s

=== GREEN ===
3 passed in 3.83s
```

### [Important] `synthesize.j2` rendered the 320-character snippet

`src/hrmosaic/agent/prompts/synthesize.j2` renders `{{ chunk.text }}` — §7.2's `c.text`, the whole
stored chunk — and the template header records why: `rag/chunk.py` caps a snippet at 320 characters
and 199 of the 204 committed chunks are longer (median 995), so the model was being shown roughly a
third of every chunk it was asked to ground an answer in. The snippet stays what it is: what a
citation shows a **reader**.

`tests/fixtures/prompts/synthesize.user.txt` was re-recorded, and the two chunks it pins are now
**real** chunks read out of the committed index the way `tests/unit/test_g2_citation_resolvability.py`
reads them — `tax-and-location-addendum` "Duration Thresholds > Stays Exceeding 30 Days"
(1285 characters of text against a 110-character snippet) and `security-acceptable-use`'s phishing
lure, quarantined. Pinning fabricated ids would have left the golden unable to catch the bug at all,
because `EvidenceChunk.text` falls back to the snippet for an id the index does not know. The golden
grew from 997 to 3,166 bytes and now shows a reviewer what the model actually reads.

**Covering tests.** `tests/contract/test_prompt_golden.py` — `CONTEXTS` became `context(template)`
with an `lru_cache`d `chunks()` so the index is read at test time, never at collection time; the
chunks are selected by `(doc_id, heading_path)` so a corpus move fails with "that heading moved"
rather than with an opaque id. New `test_the_document_envelope_carries_the_whole_chunk_not_the_snippet`
asserts `\n{chunk.text}\n</document>` is in the rendered prompt and that each pinned chunk is one the
snippet genuinely truncates, so the test cannot go vacuous. 39 → 40 tests in that DoD command.

### [Important] `_resume` absorbed a failed confirmed write

`src/hrmosaic/agent/orchestrator.py` — `_resume` now branches on `result.is_error` as `_act` does.
On a failure the body goes **only** to `turn.envelopes` (so the synthesis model can say what
happened) and never to `state.record`; an `error` span `tool_failed` / component `mcp` is written;
`turn.write_failed` is set and `stop_reason` becomes `tool_failed`; and `_answer` prepends §9.4's
graceful partial note (`WRITE_FAILED_NOTE`, a `recommendation` — it states no policy) and closes the
turn `partial` rather than `answered`.

**Covering tests.** Two added to `tests/integration/test_resume_rehydrates_from_the_store.py`, on the
mounted HTTP topology the confirmation gate requires. Reaching this state needed fault injection
rather than a mock of the code under test: bad arguments never park in the first place, so the only
way a write fails *after* its token validated is an infrastructure failure. `confirm.consume` — the
last step of tool 8 and the one that touches `mock_writes` — is made to raise
`sqlite3.OperationalError`, and the shipped server then returns a genuine `isError` over the real
transport. The tests assert zero `mock_writes` rows, `outcome == "partial"` and
`turns.stop_reason == "tool_failed"`, the leading note, exactly one `tool_failed` error span naming
the tool, and that the failure body reached the synthesis prompt while no `MOCK-HR-…` id appears
anywhere.

```
=== RED (self._absorb(turn, result) unconditionally) ===
E       AssertionError: assert 'answered' == 'partial'
FAILED tests/integration/test_resume_rehydrates_from_the_store.py::test_a_write_that_fails_after_confirmation_does_not_close_the_turn_answered
1 failed, 6 passed in 4.28s

=== GREEN ===
7 passed in 4.43s
```

### [Important] Scope beyond the brief — recorded, not reverted

`CHANGELOG.md` gained **## 2026-09-10 — P7 fix round 1 (agent/, and two accepted cross-phase
fix-ups)**, which states in the file whose stated purpose is "anything a later phase must not
rediscover":

* that `core/llm/base.py` owns `ROOT_COMBINATOR_KEYS` / `without_root_combinators()` and **both**
  adapters call it, with the reason (Gemini is judge *and* failover, so a one-adapter stripper would
  have sent the refused schema on exactly the path a live demo falls back to);
* that `core/llm/anthropic.py`'s `_split_system` now coalesces same-role messages, with the wire
  shape it fixes and the note that `StubAdapter` cannot see it;
* that `scripts/probe_provider.py`'s `SYSTEM_PROMPT` is `act.j2`'s rendered system block;
* **for P11 specifically**, that `pyproject.toml` gained
  `[tool.setuptools.package-data] "hrmosaic.agent.prompts" = ["*.j2"]`, that the repo installs `-e .`
  so **no test can catch its absence**, and that without it the Docker image ships
  `agent/prompts/` with no templates and every turn fails at `render()`.

The changes themselves are kept, as the finding directs. Nothing was reverted.

## F.2 Definition of done — real output, re-run at the fix commit

```
$ pytest tests/unit/test_g1_evidence_gate.py tests/unit/test_g2_citation_resolvability.py tests/unit/test_g3_fact_vs_rec.py -q
..............................                                           [100%]
30 passed in 2.33s

$ pytest tests/unit/test_g4_injection.py tests/unit/test_g4_no_false_positives.py tests/unit/test_g5_sensitive.py -q
.........................................................                [100%]
57 passed in 2.80s

$ pytest tests/unit/test_confirmation_token_stripped.py tests/contract/test_prompt_golden.py tests/contract/test_no_chain_of_thought.py -q
........................................                                 [100%]
40 passed in 2.42s

$ pytest tests/e2e/test_rag_only_makes_no_people_calls.py -q
...                                                                      [100%]
3 passed in 4.14s

$ pytest tests/architecture/test_conventions.py -q
.....                                                                    [100%]
5 passed in 0.03s
```

The tests covering the amended code, run together:

```
$ pytest tests/unit/test_wire_message_alternation.py tests/integration/test_act_loop_wire_shape.py \
         tests/integration/test_repair_round_trip.py tests/integration/test_resume_rehydrates_from_the_store.py \
         tests/contract/test_prompt_golden.py tests/unit/test_adapter_tool_call_shapes.py \
         tests/unit/test_strict_schema_emission.py tests/unit/test_llm_span_emission.py -q
........................................................................ [100%]
72 passed in 13.91s
```

And the standing CI path:

```
$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
141 files already formatted

$ pytest -q
[13 lines of dots]
941 passed in 42.29s

$ python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers

$ python -m hrmosaic.rag.ingest --verify-manifest
OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
```

No live provider call was made in this round: nothing changed in the credential, pricing or
prefix-measurement paths, and the prefix measurement recorded at `c1221fe` still stands (the act
system prompt is untouched; only `synthesize.j2`'s **user** half changed, which is outside the
cached prefix by construction).

## F.3 Judgement calls in this round

1. **The alternation fix lives in the adapter, not the loop.** The finding offered both. The loop
   cannot emit one message carrying two `tool_result` blocks without changing `Message` — a P6-owned
   type with a singular `tool_call_id` — and the adapter fix additionally repairs `_repair`'s
   results-then-text sequence and any future caller. It is one more P6 file touched, which is why it
   is written into `CHANGELOG.md` alongside the other cross-phase entries.
2. **The repair request answers the whole step, not just the failed call.** Prescribed fix plus one:
   see F.1. Without it the finding's own fix still 400s whenever the failing call is not the last of
   its step.
3. **The prompt golden pins real corpus chunks.** Fabricated ids make `EvidenceChunk.text` fall back
   to the snippet, so a golden built from them could never have caught this bug and could never catch
   its return. The cost is that a corpus edit touching those two chunks re-records that golden; the
   benefit is that the snapshot is now load-bearing. `chunks()` is selected by heading path so the
   failure message says what moved.
4. **Fault injection to reach the failed-confirmed-write branch.** `confirm.consume` is made to raise
   so the shipped server produces a real `isError` over the real wire. Bad arguments cannot reach
   this state (they never park), so there is no all-real route to it. What is faked is the failure,
   not the code under test.
5. **`stop_reason = "tool_failed"` is a new string in a free-text column.** `stop_reason` is not a
   `Literal` anywhere in `core/`, and the three budget stops are matched by membership in
   `BUDGET_STOPS`, so adding one is additive. `outcome` stays inside `TurnOutcome`.

## F.4 Files changed in this round

**Modified (7):** `src/hrmosaic/agent/orchestrator.py`, `src/hrmosaic/agent/prompts/synthesize.j2`,
`src/hrmosaic/core/llm/anthropic.py`, `tests/contract/test_prompt_golden.py`,
`tests/fixtures/prompts/synthesize.user.txt`,
`tests/integration/test_resume_rehydrates_from_the_store.py`, `CHANGELOG.md`.

**New (4):** `tests/unit/test_wire_message_alternation.py`,
`tests/integration/test_act_loop_wire_shape.py`, `tests/integration/test_repair_round_trip.py`,
`tests/fixtures/llm_scripts/repair_round_trip.json`.

Nothing under `mcp/`, `corpus/`, `mock_data/`, `data/index/` or `.github/` was touched, and
`pyproject.toml` and `scripts/probe_provider.py` were **not** touched again in this round — they are
recorded, not re-edited.

## F.5 Concerns carried forward

1. **Three new test files sit outside the brief's deliverables list**, for the same reason §7 item 7
   already records: the brief names the deliverables but no test for the act loop's wire shape, the
   repair round trip, or a confirmed write that fails. Shipping the fixes untested seemed worse.
2. **`tests/integration/test_repair_round_trip.py` and `test_act_loop_wire_shape.py` each spawn a
   stdio subprocess**, so the suite grew ~5 s (37 → 42 s). Both drive a real server on purpose; the
   honest lever if CI time bites is to consolidate spawns, not to swap in a fake client.
3. **The wire invariants are still asserted against `MockTransport`, never against live Haiku.** They
   encode the two documented Messages API rules, and the P10 live run is the first time the real API
   adjudicates them. The `assert_wire_is_well_formed` helper is written so a live 400 would point
   straight at it.
4. **`tests/integration/test_repair_round_trip.py` imports `_Recorder` from
   `test_act_loop_wire_shape.py` and `assert_wire_is_well_formed` from the unit test**, the way
   `tests/integration/conftest.py` already imports `mounted_server` from `tests/conftest.py`. If a
   later phase adds shared test helpers, those two belong there.
5. **P8 should re-read `_resume`'s new branch before writing `/chat/confirm`.** A confirmed turn can
   now close `partial` with `stop_reason="tool_failed"`, and the response's first block is the
   `WRITE_FAILED_NOTE` recommendation — the UI must not render that as a created ticket.
