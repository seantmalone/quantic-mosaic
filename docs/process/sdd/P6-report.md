# P6 report — `core/llm/`: the provider abstraction

**Branch** `p6` (worktree `/Users/sean/Projects/quantic-mosaic-wt/P6`) · **HEAD** `a2fc302e426d3eb0396dc447c439085515074dd1` · **base** `54f514d`
**Status** DONE · one commit · nothing pushed · `.env` never read aloud, printed or committed.

---

## 1. What was built

### `src/hrmosaic/core/llm/`

| File | What it holds |
|---|---|
| `base.py` | The `ChatModel` protocol; the provider-neutral wire types (`Message`, `ToolSchema`, `ToolCall`, `Completion`, `CompletionRequest`); `ProviderError` / `MissingCredentialError`; **the one recording call path** (`RecordingAdapter`) — spend guard → limiter → one backoff → failover → exactly one `llm_call` span; `record_llm_call()`, the single seam that writes it through `core/trace.py`. |
| `anthropic.py` | `AnthropicAdapter` — the agent's adapter. Sync SDK 1.4.0 client behind `await asyncio.to_thread(...)`, `timeout=25` s, `max_retries=0`, `extra_body={"temperature": 0}`, **no `strict`** on the tool definitions, `output_config.format` JSON schema with **no** prompted fallback, dict-shaped tool inputs, no extended thinking, `max_tokens` 1024 / 2048 / 512, one `cache_control {"type": "ephemeral"}` breakpoint on the **last system block**. Also `count_prefix_tokens()` for the probe. |
| `openai_compat.py` | `OpenAICompatAdapter` — the judge, the failover and the free agent path. Tool-call arguments always `json.loads`-ed; strict `response_format` → prompted JSON → **one** repair round trip, each recorded in `structured_output_mode`. |
| `stub.py` | `StubAdapter`, replaying `tests/fixtures/llm_scripts/*.json` in order, selected by the test / `LLM_STUB_SCRIPT` and never by prompt matching. It is a `RecordingAdapter`, so a stubbed turn writes the same span and `llm_messages` rows a live turn writes. |
| `cache.py` | `CachedAdapter` — off at `LLM_CACHE_TTL_S=0` (the default) and then a pure pass-through; keyed `sha256(provider\|model\|temperature\|messages\|tools)` against `llm_cache`. |
| `limiter.py` | `TokenBucket` (capacity `LLM_BURST`, refill `LLM_RPM / 60` per second, injectable clock and sleep) and the `LLM_DAILY_CALL_CAP` spend guard — `count_calls_today()` / `DailyCapExceeded` — counted from `llm_call` spans, no second counter. |
| `__init__.py` | `build_agent_model()` / `build_judge_model()` / `build_fallback_model()` / `shared_limiter()` — the §9.8 allocation table read in exactly one place. |

### Other files

- `scripts/probe_provider.py` — P6's live gate (below).
- `tests/fixtures/llm_scripts/adapter_smoke.json` — P6's own three-entry route → act → synthesize script.
- `tests/fixtures/llm_scripts/demo_task_1.json` — the §18.1 tool sequence, so `LLM_STUB_SCRIPT`'s default resolves and `make demo1` has something to replay. Marked in-file as authored at P6, re-shaped by P7 and **replaced by a real recording at P10** (§16.2).
- `tests/unit/conftest.py` — the `httpx2.MockTransport` fixtures (`wire`, `anthropic_response`, `openai_response`).
- Six unit test files; `CHANGELOG.md` appended with the dated live measurements.

**No** `.github/workflows/ci.yml` edit (P6's brief names none; `pytest -q` already runs the whole suite) and **no** `pyproject.toml` edit (no new dependency — see Concerns).

---

## 2. Definition of done — real output

### `pytest tests/unit/test_adapter_tool_call_shapes.py -q`
```
........                                                                 [100%]
8 passed in 0.81s
```

### `pytest tests/unit/test_strict_schema_emission.py -q`
```
.........                                                                [100%]
9 passed in 0.79s
```

### `pytest tests/unit/test_limiter_burst.py -q`
```
....                                                                     [100%]
4 passed in 0.56s
```

### `pytest tests/unit/test_llm_span_emission.py -q`
```
.............                                                            [100%]
13 passed in 3.95s
```

### `python scripts/probe_provider.py` — **live, PASS, exit 0**
```
probe_provider — 2026-09-09

Anthropic claude-haiku-4-5
  tools offered: 9 (as published, no `strict`)
  measured tools+system prefix: 2172 tokens (minimum cacheable prefix 4096) — cache assertion not armed
  call 1: finish=end_turn in=2479 out=59 cache_write=0 cache_read=0 mode=output_config_json_schema cost=$0.002774 ttfb=3165 ms
  call 2: finish=end_turn in=2479 out=59 cache_write=0 cache_read=0 mode=output_config_json_schema cost=$0.002774 ttfb=2827 ms
  cache: not asserted — the prefix is below the floor, so no entry is written and the two counters are expected to be 0 (recorded, not a failure)

Judge gemini-3.5-flash-lite at https://generativelanguage.googleapis.com/v1beta/openai/
  judge: finish=stop in=67 out=52 cache_write=0 cache_read=0 mode=json_schema_strict cost=$0.000000 ttfb=1353 ms
  verdict: score=1 rationale='The evidence explicitly states that full-time employees with three or more years'

PASS
CHANGELOG line: 2026-09-09 — `scripts/probe_provider.py` PASS: claude-haiku-4-5 with the nine published tools (no `strict`) and an `output_config` JSON schema; tools+system prefix 2172 tokens; cache assertion not armed (cache_write 0 / cache_read 0); gemini-3.5-flash-lite judge returned schema-valid JSON.
exit=0
```

### `make lint` and `make test` (whole suite, pristine)
```
$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
45 files already formatted

$ make test
.venv/bin/pytest -q
........................................................................ [ 51%]
.....................................................................    [100%]
141 passed in 5.01s
```

No warnings, no skips, no xfails anywhere in the suite.

**Live spend:** 8 paid Haiku calls in total across the whole phase (two failed probe runs during development, three passing runs × 2 calls, plus a free `models.retrieve` and three free `count_tokens` calls) — roughly **$0.02**. The judge and the failover path cost nothing.

---

## 3. TDD evidence

Genuine red → green cycles, all driven by the live probe and by the tests themselves:

1. **The probe's first run failed red against the real API** with
   `400 tools.1.custom.input_schema: input_schema does not support oneOf, allOf, or anyOf at the
   top level` (request id `req_011CetXNF2nBpmngY16WfS2A`). Fixed by `_tool_payload()` in
   `anthropic.py`, then covered by a new unit test
   (`test_a_root_level_oneof_is_dropped_and_nothing_else_is`) that asserts the request bytes drop
   only the combinator and that the published `ToolSchema` itself is untouched.
2. **The probe's second run printed `cost=$0.000000` for a 2479-token Haiku call** — visibly wrong.
   Root cause: the API echoes `claude-haiku-4-5-20251001`, which is not a `MODEL_PRICES` key, and
   the adapter was recording the echoed id. Confirmed with a free `models.retrieve`
   (`id = claude-haiku-4-5-20251001`), fixed by recording the **configured** id, and locked by
   `test_the_span_records_the_configured_model_not_the_dated_snapshot`, which feeds a snapshot id
   through the MockTransport and asserts `cost_usd_estimate > 0`.
3. `test_limiter_burst.py` was written against the spec's numbers before the bucket existed
   (6 free, then pacing); the injected-clock design came out of making the 7th–11th assertion
   testable without 30 s of wall clock.
4. Honest note on ordering: `base.py`, the three adapters and the two wrappers were written
   **before** their tests rather than test-first, because the brief specifies the module shapes
   precisely. Every behavioural fix after that point was test-first, and the four DoD test files
   were each run and read before being accepted.

---

## 4. Files changed

Created:
```
scripts/probe_provider.py
src/hrmosaic/core/llm/__init__.py
src/hrmosaic/core/llm/anthropic.py
src/hrmosaic/core/llm/base.py
src/hrmosaic/core/llm/cache.py
src/hrmosaic/core/llm/limiter.py
src/hrmosaic/core/llm/openai_compat.py
src/hrmosaic/core/llm/stub.py
tests/fixtures/llm_scripts/adapter_smoke.json
tests/fixtures/llm_scripts/demo_task_1.json
tests/unit/conftest.py
tests/unit/test_adapter_tool_call_shapes.py
tests/unit/test_cached_adapter.py
tests/unit/test_limiter_burst.py
tests/unit/test_llm_span_emission.py
tests/unit/test_model_allocation.py
tests/unit/test_strict_schema_emission.py
```
Modified: `CHANGELOG.md` (appended a `## 2026-09-09 — P6 core/llm/` section only).

Nothing else was touched. No file owned by P2 or P3 was read or written.

---

## 5. Live facts discovered (all recorded in `CHANGELOG.md`)

| Fact | Value, verified 2026-09-09 |
|---|---|
| Measured cacheable *tools → system* prefix | **2172 tokens** — **below** Haiku 4.5's 4096-token floor, so the cache assertion is **not armed** and both counters read `0`, exactly the silent no-op §9.8 predicts. §9.8 *expected* nine compact schemas plus the system prompt to clear the floor; on this system prompt they do not. |
| Tool `input_schema` combinators | The Messages API returns **400** on `oneOf` / `allOf` / `anyOf` **at the top level**. §8.4's `get_policy_section` publishes a root `oneOf`. `default` values and the open `parameters` sub-schema are accepted as published. |
| Model id echo | `model: "claude-haiku-4-5"` comes back as `claude-haiku-4-5-20251001`. |
| HTTP layer | `anthropic` 1.4.0 and `openai` 2.54.0 both ship **`httpx2` 2.12.0**, not `httpx`; an `httpx.Client` is rejected with `Invalid http_client argument`. |
| Gemini strict mode | Gemini's OpenAI-compat endpoint **accepted** `response_format: {type: json_schema, strict: true}` — the prompted-JSON fallback was not needed live. It is still implemented and unit-tested, because §9.8 requires it. |
| SDK 1.4.0 `messages.create` | Has no `temperature` keyword (confirmed by introspection); `output_config`, `cache_control`, `tools`, `extra_body` all present as the constraints file states. |

---

## 6. Ambiguities resolved (simplest reading that satisfies the spec)

1. **The protocol's signature.** §9.8 shows `complete(messages, *, tools, response_schema, temperature)`, but §10.2's `llm_call` payload requires a `purpose` and §9.8 sets `max_tokens` *by* purpose, and the span has to be written into the turn it belongs to. Resolved by keeping the spec's signature as a **strict prefix** and adding two keyword-only parameters with defaults: `purpose: LlmPurpose = "act"` and `turn: TurnBuffer | None = None`. Any caller written to the spec's shape still compiles.
2. **Where failover and span emission live.** The brief's file list names no `failover.py`, so both live in `base.py` as a shared `RecordingAdapter`, with each adapter implementing a single-round-trip `invoke()`. The fallback is injected as a `ChatModel` (no import cycle) and is called through `invoke()`, so a failover is **one** span and **one** limiter token, not two.
3. **`max_tokens` for purposes §9.8 does not name.** Named: route 1024, synthesize 2048, repair 512. `act`, `judge` and `decompose` take the route budget (1024) — a tool-use turn emits small `tool_use` blocks, not prose.
4. **The daily cap without a store.** The guard counts `llm_call` spans, which implies a trace store, which implies a turn. So the cap is enforced whenever `turn is not None` and `daily_call_cap` is set — the live probe and unit tests run unmetered. It is wired only on the Anthropic path, matching §12.3's "Anthropic calls per UTC day".
5. **Which model id the span records.** The **configured** id, not the API's dated snapshot: it is what §10.1's span-name example shows (`anthropic:claude-haiku-4-5`), what `LLM_MODEL` pins and what `MODEL_PRICES` keys on. The snapshot id is recorded once, dated, in `CHANGELOG.md`.
6. **`ttfb_ms` on a retried or failed-over call.** It times the round trip that *answered*, never the backoff sleep in front of it; the span's own `duration_ms` already covers the whole logical call. A test asserts `ttfb_ms < 500` while `duration_ms >= 1000` on a failed-over call.
7. **Root `oneOf` on the Anthropic wire.** The published schema is authoritative and the API rejects the keyword, so the **adapter** drops the top-level combinators on the way out and changes nothing else. The MCP server still validates the selector rule server-side, which is exactly where §8.4 puts it (`isError {"code": "INVALID_ARGUMENTS"}` when neither selector is given).
8. **Stub script strictness.** Entries are consumed in order and each declares its `purpose`; a mismatch raises `StubScriptError` rather than silently replaying the wrong completion. Token counts are optional and default to `0` — a stub must never invent numbers a cost estimate would treat as real.
9. **`demo_task_1.json` at P6.** `settings.llm_stub_script` defaults to it and `make demo1` needs it, and P6 is the phase that owns the script format, so it is authored here to §18.1's tool table and flagged in-file for P7 (loop shape) and P10 (real recording).
10. **`CachedAdapter` on a hit.** It emits the `llm_call` span itself, with `cache_hit: true`, so "exactly one span per logical call" holds on both branches. **No test asserts a cache hit**, per §22.

---

## 7. Self-review — what I found and fixed

| Found | Fix |
|---|---|
| `record_llm_call` carried a stray `from hrmosaic.core.trace import ErrorPayload` that nothing used | removed |
| `openai_compat.py` exported an unused `ResponseSchema` alias (YAGNI) | removed, with its `pydantic` import |
| `@runtime_checkable` on `ChatModel` with data members — never `isinstance`-checked, and would raise if it were | decorator dropped |
| Cost silently estimated at `$0.00` for every real Haiku call | record the configured model id; regression test added |
| `ttfb_ms` included the 1 s backoff sleep, so a retried call looked like a slow provider | `_Attempts.round_trip_ms` times only the answering attempt; assertion added |
| Both providers down recorded `provider_failover: false`, hiding that a failover was attempted | flag set to `true` on that path; `test_both_providers_down_is_still_one_span_flagged_as_a_failover` added |
| `RETRYABLE_STATUSES` included `409`, which §9.8 does not name | narrowed to `{408, 429}` plus every 5xx |
| `ToolSchema`'s docstring claimed schemas are "passed through unaltered", untrue after the `oneOf` fix | docstring corrected to state exactly what an adapter may drop and why |
| `shared_limiter`'s docstring over-claimed that any settings change yields a fresh bucket | reworded to what the `(rpm, burst)` key actually does |
| A test reached into `StubAdapter._entries` | rewritten against the public `remaining` plus `load_script()` |

Also checked and correct: no second span-writing path (`tests/architecture/test_conventions.py` still green — the only SQL against `spans` outside `trace.py` is the cap's `SELECT COUNT(*)`); no `parallel=`; `.env.example` ↔ `Settings` bijection untouched and green; every span payload parses back through `core/models.parse_payload`; turn rollups (`llm_calls`, `total_tokens_in/out`, `provider`, `provider_failover`) all populated by the adapter's span.

---

## 8. Concerns for the reviewer / later phases

1. **Prompt caching does not pay yet.** At 2172 tokens the stable prefix is 47 % of the 4096-token floor, so *every* call is billed at full input price and §9.8's "largely cache reads" spend estimate does not hold today. P7 owns the real system prompt and P5 the full tool descriptions; if the combined prefix still lands under 4096 after both, the honest options are (a) accept it and say so in `design-and-evaluation.md`, or (b) deliberately lengthen the stable head. **This is a decision for P7/P10, not a P6 defect** — the probe is built to re-measure and to arm the assertion automatically once the prefix clears the floor.
2. **`httpx2` is a transitive pin, not a declared dependency.** `tests/unit/conftest.py` imports it directly (it is the only way to build a MockTransport for either SDK). It is exact-pinned at 2.12.0 in `requirements.txt` and is guaranteed present by `anthropic==1.4.0`, so nothing is broken — but I did **not** add it to `pyproject.toml`, to keep the shared file free of merge conflicts with the two sibling worktrees. Adding `httpx2==2.12.0` as an explicit test dependency would be a defensible one-line follow-up at merge time.
3. **`demo_task_1.json` is a P6-authored placeholder**, not a recording. Its act-step grouping (2 + 2 + 1 tool calls over three steps) is my reading of §18.1 against `AGENT_MAX_STEPS=6`; P7 should re-shape it to the loop it actually builds, and P10 replaces it outright.
4. **`get_policy_section`'s `oneOf` never reaches the model.** The constraint survives only in the tool's *description* and in the server-side validator. P5 must therefore write a description that states "exactly one of `heading_path` or `chunk_id`" in prose, or the model will guess. Worth a note in `mcp/README.md`.
5. **`RESPONSE_SCHEMAS` in `test_strict_schema_emission.py` is a hand-maintained list** (`AnswerSchema`, `AnswerBlock`, `Citation` today). P7 must add its router and repair schemas to that constant when it creates them, or they ship unchecked. The file says so in a comment.
6. **The `error` span for a provider failure is P7/P8's**, not P6's: the adapter emits the `llm_call` span with `status='error'` and then raises `ProviderError` / `DailyCapExceeded`. `DailyCapExceeded.error_kind == "daily_cap_reached"` is provided ready for `POST /chat` to put on its `error` span, per §9.8.
7. **`/health.llm.agent`** has everything it needs at P8: `adapter.configured`, `adapter.provider`, `adapter.model`, and `count_calls_today(store, "anthropic")` beside `settings.llm_daily_call_cap`.

---

# P6 fix round 1 — the logical-call bound (review finding, `base.py:424-449` / `openai_compat.py:116-138`)

**Branch** `p6` (worktree `/Users/sean/Projects/quantic-mosaic-wt/P6`) · **HEAD** `68beb09ca543aa85b26ad538530e54417e088abc` · **base** `a2fc302`
**Status** DONE · one commit (`P6(llm): fix: bound a logical call at 52 s with a real deadline, not arithmetic`) · nothing pushed · `.env` never read aloud, printed or committed.

## 1. The finding, and what was actually wrong

The brief bounds a logical call at ≈ 52 s (25 + 2 + 25) inside `AGENT_WALL_CLOCK_S` (= 90,
`settings.py:105`). The shipped code did not honour that bound in three distinct ways:

1. **Three round trips, not two.** `_call_with_failover` ran the primary at attempt 0, backed off,
   ran the primary again at attempt 1, and *then* ran the fallback — 25 + 2 + 25 + 25 = **77 s** on
   the pinned Anthropic path. `test_failover_is_one_span_carrying_the_flag` had that wrong shape
   pinned in an assertion (`len(primary_recorded) == 2`), so the test defended the defect.
2. **The fallback's degradation ladder was unbounded.** The fallback runs through
   `OpenAICompatAdapter.invoke()`, whose strict → prompted → one-repair ladder is up to three
   25 s round trips of its own: 25 + 2 + 25 + 75 = **≈ 127 s**, past `AGENT_WALL_CLOCK_S`.
3. **`LLM_PROVIDER=openai_compat` was worse still.** With that ladder as the *primary*, two attempts
   plus the backoff is 2 × 75 + 2 = **152 s**.

The review's diagnosis is right on all three counts, and the root cause is the same one each time:
the bound was **arithmetic over an assumed round-trip count**, so any adapter that grew a step, or
any transport that ignored its own timeout, silently broke it.

## 2. What changed

The bound is now a **deadline**, enforced at three levels, and the round-trip count is exclusive as
the brief's arithmetic implies. Both halves of the review's suggested fix, because either alone
still leaves a hole: an `asyncio.timeout` alone would cut a call mid-ladder with no per-step
accounting, and an exclusive choice alone would still let one `invoke()` spend 75 s.

### `src/hrmosaic/core/llm/base.py`

- **`LOGICAL_CALL_BUDGET_S = REQUEST_TIMEOUT_S + MAX_BACKOFF_S + REQUEST_TIMEOUT_S` (= 52.0)** — the
  brief's number, written as the sum it comes from rather than as a literal.
- **`Deadline`** — a frozen dataclass holding one monotonic expiry, minted per `complete()` and
  handed down to every round trip, so an adapter with a multi-step `invoke()` spends *the same*
  budget the retry layer is spending rather than a fresh 25 s per step.
- **`round_trip_timeout(deadline, what=…)`** — `min(25 s, what is left)`. With nothing left it
  raises a **non-retryable** `ProviderError` (with the budget gone there is no time for a failover
  either) *before* anything reaches the wire.
- **`RecordingAdapter.__init__(…, call_budget_s=LOGICAL_CALL_BUDGET_S)`** and
  **`invoke(request, deadline=None)`** — the subclass seam now carries the budget. `deadline=None`
  keeps the live probe and bare unit tests on the plain 25 s per request.
- **`complete()`** wraps the whole call in `async with asyncio.timeout(self.call_budget_s)` and
  fills `_Attempts` **in place**, so a call the timeout cuts short still writes its one `llm_call`
  span with `status='error'` — the standing acceptance criterion holds on the new failure path too.
- **`_call_with_failover`** is now: primary once → at most one bounded backoff → **exactly one more
  attempt**, the fallback when one is configured and the primary again when none is. Two round
  trips, never three. The backoff is additionally skipped when it would eat the budget the second
  attempt needs (`delay < deadline.remaining_s`), on top of the existing `Retry-After` cap.
- **`_invoke_fallback(fallback, request, deadline)`** passes the remaining budget down.

### `src/hrmosaic/core/llm/anthropic.py`, `openai_compat.py`, `stub.py`

- Both live adapters send every request with `timeout=round_trip_timeout(deadline, …)`, so a second
  attempt gets what is *left* of the 52 s rather than a fresh 25 s. Verified against the real API
  by the probe below — both SDKs accept the per-request `timeout` override.
- `OpenAICompatAdapter.invoke()` threads that one deadline through **all three** ladder steps, so
  strict → prompted → repair degrades in however many steps it has time for and never one more.
  (Incidental tidy-up in the same function: the `STRICT if response_format is not None else mode`
  expression was duplicated; it is computed once as `resolved_mode` and used for both the timeout
  label and `_to_completion`.)
- `StubAdapter.invoke()` accepts and ignores the deadline — a replay makes no round trip — with a
  comment saying so, so the signature is not mistaken for dead weight.

### `src/hrmosaic/core/llm/__init__.py`
`Deadline` and `LOGICAL_CALL_BUDGET_S` exported, so P7's agent loop can read the same bound rather
than re-deriving it.

## 3. Covering tests

`tests/unit/test_llm_span_emission.py` — one amended assertion, one strengthened test, and a new
section of four that assert **the deadline itself**, which is exactly what the finding asked for
("a test that asserts the total deadline, not just the round-trip count").

| Test | What it pins |
|---|---|
| `test_the_call_budget_fits_inside_the_agent_wall_clock` | `LOGICAL_CALL_BUDGET_S == 25 + 2 + 25` **and** `< settings.agent_wall_clock_s`. The arithmetic the brief states, asserted rather than commented. |
| `test_a_logical_call_never_outlives_its_budget` | Real `AnthropicAdapter` + real `OpenAICompatAdapter` fallback over `MockTransport` handlers that **hang** 0.8 s. With `call_budget_s=0.25`: the call raises inside the budget (`BUDGET_S <= elapsed < HANG_S`), and the one span is still written with `status='error'` and `budget` in `error_message`. Timed *inside* the loop, because `asyncio.run` joins the stalled worker thread on the way out — that is the hanging provider's time, not the caller's. |
| `test_the_structured_output_ladder_is_bounded_by_the_same_budget` | `OpenAICompatAdapter` as **primary** with a response schema: strict is rejected (400), prompted hangs. The call ends inside the budget and **exactly 2** requests reach the wire — "the repair round trip had no budget left to spend". This is the ≈ 127 s / 152 s path from the finding. |
| `test_an_expired_deadline_puts_nothing_on_the_wire` | `invoke(request, Deadline.after(0.0))` raises `budget is spent` and `recorded == []`. Zero wall clock, and it pins the "refuse rather than start what you cannot finish" rule. |
| `test_failover_is_one_span_carrying_the_flag` (amended) | `len(primary_recorded) == 1` — the assertion that used to defend the 3-round-trip shape now forbids it, with the 77 s arithmetic in the comment. Everything else about that test is unchanged and still green: one span, `provider_failover` true, `retry_count == 1`, `ttfb_ms < 500` while `duration_ms >= 1000`. |
| `test_a_total_failure_still_records_the_attempt` (strengthened) | `len(recorded) == 2` — with **no** fallback configured the second of the two round trips is the primary again, so the exclusive choice never costs a retry the old code would have made. |

Unchanged and still green, which is the point: `test_a_long_retry_after_fails_over_without_parking`
(45 s `Retry-After` → `retry_count == 0`, one primary request), `test_a_non_retryable_status_never_fails_over`,
`test_both_providers_down_is_still_one_span_flagged_as_a_failover`, and the daily-cap test.

## 4. Definition of done — real output, re-run after the fix

### `pytest tests/unit/test_adapter_tool_call_shapes.py -q`
```
........                                                                 [100%]
8 passed in 0.84s
```

### `pytest tests/unit/test_strict_schema_emission.py -q`
```
.........                                                                [100%]
9 passed in 0.84s
```

### `pytest tests/unit/test_limiter_burst.py -q`
```
....                                                                     [100%]
4 passed in 0.60s
```

### `pytest tests/unit/test_llm_span_emission.py -q`  (13 → 17)
```
.................                                                        [100%]
17 passed in 5.57s
```

### `python scripts/probe_provider.py` — **live, PASS, exit 0**
```
probe_provider — 2026-09-09

Anthropic claude-haiku-4-5
  tools offered: 9 (as published, no `strict`)
  measured tools+system prefix: 2172 tokens (minimum cacheable prefix 4096) — cache assertion not armed
  call 1: finish=end_turn in=2479 out=59 cache_write=0 cache_read=0 mode=output_config_json_schema cost=$0.002774 ttfb=3032 ms
  call 2: finish=end_turn in=2479 out=59 cache_write=0 cache_read=0 mode=output_config_json_schema cost=$0.002774 ttfb=2734 ms
  cache: not asserted — the prefix is below the floor, so no entry is written and the two counters are expected to be 0 (recorded, not a failure)

Judge gemini-3.5-flash-lite at https://generativelanguage.googleapis.com/v1beta/openai/
  judge: finish=stop in=67 out=50 cache_write=0 cache_read=0 mode=json_schema_strict cost=$0.000000 ttfb=5342 ms
  verdict: score=1 rationale='The evidence explicitly confirms that full-time employees with three or more yea'

PASS
CHANGELOG line: 2026-09-09 — `scripts/probe_provider.py` PASS: claude-haiku-4-5 with the nine published tools (no `strict`) and an `output_config` JSON schema; tools+system prefix 2172 tokens; cache assertion not armed (cache_write 0 / cache_read 0); gemini-3.5-flash-lite judge returned schema-valid JSON.
exit=0
```
The probe is the live proof that the per-request `timeout` override reaches both real SDKs
(`messages.create(timeout=…)` and `chat.completions.create(timeout=…)`) without a `TypeError` and
without changing the measured prefix, the cost or the modes. Measurements are identical to the
pre-fix run, so **no CHANGELOG line was appended** — the same facts, already recorded on 2026-09-09.
Live spend for this fix round: 2 paid Haiku calls (~$0.006) plus one free Gemini judge call.

### `make lint` and `make test` (whole suite, pristine)
```
$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
45 files already formatted

$ make test
.venv/bin/pytest -q
........................................................................ [ 49%]
........................................................................ [ 99%]
.                                                                        [100%]
145 passed in 6.65s
```
141 → 145: the four new budget tests. No warnings, no skips, no xfails.

## 5. Files changed

Modified only (no new files, no deletions) — `git diff --numstat`:
```
4	0	src/hrmosaic/core/llm/__init__.py
12	2	src/hrmosaic/core/llm/anthropic.py
127	48	src/hrmosaic/core/llm/base.py
23	7	src/hrmosaic/core/llm/openai_compat.py
4	2	src/hrmosaic/core/llm/stub.py
116	4	tests/unit/test_llm_span_emission.py
```
No `ci.yml`, no `pyproject.toml`, no `CHANGELOG.md`, no `.env`. Nothing outside P6's scope.

## 6. Choices made, for the reviewer

1. **Exclusive second attempt, not "retry then fail over".** The brief names the layer
   "one-backoff-then-failover" *and* bounds it at 25 + 2 + 25, and only two round trips fit in that
   sum. So the backoff sits between the two attempts and the second attempt is the failover when
   one exists. With `LLM_FALLBACK_PROVIDER` unset the behaviour is unchanged from before the fix:
   primary, backoff, primary. This is a **deliberate behaviour change** on the failover path — the
   primary now gets one attempt rather than two before the fallback is tried — and it is the change
   the 52 s bound requires.
2. **Both belts, not one.** `Deadline` accounts the budget round trip by round trip (so the ladder
   degrades gracefully and an unsendable request is never sent); `asyncio.timeout` is the outer,
   unconditional bound (so a transport that ignores its own timeout — `MockTransport` is exactly
   such a transport, which is what makes the new tests possible — still cannot overrun). Belt alone
   would be advisory; braces alone would cut calls with no accounting.
3. **`call_budget_s` is a constructor parameter, not a setting.** The brief pins 52 s and
   `.env.example` ↔ `Settings` is a tested bijection; adding an env var would have touched files
   P6 does not own. The parameter exists so tests can shrink the budget to 0.25 s and so P7 can
   narrow it against a turn's remaining wall clock if it wants to.
4. **Cut-short calls still record.** `_Attempts` is passed in and filled in place rather than
   returned, so the `asyncio.timeout` path still writes its one span. Without that the new bound
   would have created a way to make a provider call that leaves no trace — the failure USER.4
   forbids and the exact thing §16.3 and the standing acceptance criterion exist to prevent.

## 7. Concerns

1. **A cut-short call leaves a worker thread running.** `asyncio.to_thread` cannot be cancelled, so
   when the outer timeout fires, the SDK thread lives until its own `timeout=` expires (≤ 25 s) and
   its result is discarded. That is bounded, off the event loop and invisible to the caller — the
   logical call *is* over — but it is worth knowing at P8 that a burst of timed-out calls holds
   threads briefly. The alternative (a truly cancellable async SDK client) is a bigger change than
   this finding warrants and would contradict the brief's "sync client via `asyncio.to_thread`".
2. **The concerns of the first report all still stand** — in particular §8.1 (the 2172-token prefix
   is below Haiku 4.5's 4096-token cache floor, a P7/P10 decision) and §8.2 (`httpx2` is a
   transitive pin the unit conftest imports directly). Nothing in this round touched either.
