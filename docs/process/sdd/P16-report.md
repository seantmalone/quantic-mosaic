# P16 report — performance Wave 2, lever W2-E (streaming), live progress narration, span string cap

Base `699f631` · head `2d0a23d` · branch `main` · three commits, nothing pushed.

| commit | subject |
|---|---|
| `ac700d1` | `P16(core): §10.5's per-string cap is 24 KB, so a k=5 search fits` |
| `e0926a4` | `P16(llm): the agent adapter streams, and the record says so` |
| `2d0a23d` | `P16(web): the rail narrates each step, and the answer arrives while it is written` |

---

## 1. What I built

### 1.1 `P16(core)` — the carry-forward from P15 (done first, as the brief asks)

`core/trace.py`'s `MAX_STRING_BYTES` 8 KB → **24 KB**. W2-C put the whole chunk beside the snippet
in every `search_policy_documents` hit, so a k=5 result serialises to ≈ 8.3 KB in the `tool_call`
span's `result_json`: at 8 KB *every* search on the dashboard was badged truncated and the span
detail could not show a reader what the act loop was given. The 32 KB payload cap, the 128 KB
`llm_call` cap, the `…[truncated]` marker, the halving ladder and the oversize stub are unchanged.

Spec §10.5's table row plus a new rationale paragraph; §17's denial-of-service row now reads
`24 KB / 32 KB (128 KB for llm_call)`. The stale docstring in
`tests/integration/test_search_returns_full_chunk_text.py` (which claimed `result_json` is stored
with a truncation marker) is corrected.

### 1.2 `P16(llm)` — the provider half of W2-E

Every "Required changes applied" bullet of performance plan §3 W2-E that belongs to the adapter:

- **`AnthropicAdapter.invoke` → `client.messages.stream`**, still inside `asyncio.to_thread`, still
  `max_retries=0`, still `timeout=round_trip_timeout(deadline)`. The final message is always
  **`stream.get_final_message()`** — never a hand-rolled accumulator.
- **`CompletionRequest.on_delta`** (a `DeltaSink`, called on the worker thread, in order). It is not
  part of the cache key: `cache_key` builds its material field by field. A sink that raises is
  logged and dropped.
- **`Completion.streamed` / `LlmCallPayload.streamed`**, and `ttfb_ms = first_delta_ms or
  round_trip_ms` resolved in `RecordingAdapter.complete` with `is not None` rather than truthiness,
  so a 0 ms first delta stays a measurement.
- **`StubAdapter` replays as deltas** (`DELTA_CHARS = 32`) when a sink is attached, so the key-free
  path exercises the same seam. `OpenAICompatAdapter` stays non-streaming (`streamed=false`), and a
  `CachedAdapter` hit reports `streamed=false, ttfb_ms=0` — it made no round trip.
- **The §16.2 keystone first.** `tests/unit/conftest.py`'s `wire(...)` handler now renders the same
  declared `(status, payload)` as an Anthropic event stream (`message_start` → per block
  `content_block_start` / deltas / `content_block_stop` → `message_delta` → `message_stop`) when
  the request carried `"stream": true`. All 35 `wire([...])` call sites are untouched; a non-Anthropic
  payload and any non-200 status pass through as JSON exactly as before.

Spec §1.4 bullet 1 is struck through and reversed with the measured numbers; §9.8 carries the
`on_delta` protocol argument, the `messages.stream` rule, the stub's delta replay, and
`ttfb_ms` / `streamed` in the span field list.

### 1.3 `P16(web)` — narration, the `answer_delta` frame, the page, the dashboard

**One listener, two phases.** `SpanEvent.phase` is `"started"` or `"closed"`, and both travel the
existing `core.trace.register_span_listener()` seam — literally one listener, as §11.3 requires.
`TurnBuffer.open_span(kind, name, detail=…)` publishes the `started` event and **returns the span
id** the eventual `add_span` must carry, so the closed frame *replaces* the in-progress line.
`detail` is redacted (§10.4) and never leaves the process; only the label goes on the wire.

Call sites (the five the brief names): `RecordingAdapter.complete` (router / act / synthesize /
repair), `McpClient.call_tool`, the post-synthesis guardrail pass (closed by G2 — its first span),
`Orchestrator._propose`'s confirmation wait, and `TurnBuffer.span()` for consistency.

**`web/narration.py`** is the one mapping. Keyed on kind plus what identifies the step within that
kind. Every label from the brief is verbatim; `get_policy_section` resolves a document *title* from
the index by `doc_id` and degrades to `SECTION_FALLBACK` for an id the corpus does not hold.

**`agent/answer_stream.py`** — a resumable scan of the synthesis call's partial JSON for closed
objects of its `blocks` array, plus the coalescer (~40 chars / ~100 ms). Only `type`, `text`,
`citations` are taken; `rationale_summary` and `next_steps` are never read.

**`core/trace.py`** gains `AnswerDeltaEvent`, `register_delta_listener`, `clear_delta_listeners`
and `publish_answer_delta` — a separate registry, because a delta is not a span and is never
persisted. `web/main.py`'s lifespan registers `broker.publish_answer_delta` alongside
`broker.publish_span` and unregisters both on shutdown.

**`web/sse.py`** gains `step_started_data`, `answer_delta_data` and `label` + `span_id` on the
`span` frame; `publish_span` branches on the phase.

**`chat.html`** — the in-progress line (spinner, plain-language label, live elapsed counter),
replacement on close matched by `data-span-id`, the JS mirror of `render_answer()` and the
provisional panel, hard-replaced on `turn_completed` (and again on the htmx swap, for a stream that
dropped first). `aria-live="polite"` unchanged; blocks are *appended* rather than the region being
re-rendered, so a screen reader is not re-read the whole answer on every frame.

**Dashboard page 5** gains a `Streamed` column beside `TTFB` (`LlmRow.streamed`, `llm.html`).

Spec §11.3 rewritten with both frames and their rules; §11.6's page-5 view-model row plus a note;
§21 decision-table row 12 now records the reversal and its measured numbers.

---

## 2. TDD evidence

**§10.5's cap** — test written first, watched fail at 8 KB, then the constant raised:

```
>       assert json.loads(serialised)["result_json"] == result_json
E       assert '{"hits": [{"...a…[truncated]' == '{"hits": [{"...e paid ti"}]}'
tests/unit/test_payload_size_control.py:84: AssertionError
1 failed, 9 passed in 1.15s
```
after: `10 passed in 1.11s`.

**`step_started`** — red-proofed by deleting the publication in `SpanBroker.publish_span`:

```
>       assert announced, "at least the router, the tool calls and the synthesis announce themselves"
E       AssertionError: at least the router, the tool calls and the synthesis announce themselves
E       assert {}
FAILED tests/integration/test_sse.py::test_the_live_path_delivers_turn_started_every_span_and_turn_completed
FAILED tests/integration/test_sse.py::test_every_step_is_announced_before_its_span_closes
2 failed, 8 passed in 6.84s
```

**`answer_delta`** — red-proofed by deleting `on_delta=` from `Orchestrator._synthesize`:

```
>       assert len(deltas) == 2, "the raw synthesis had two blocks and both were streamed"
E       AssertionError: the raw synthesis had two blocks and both were streamed
E       assert 0 == 2
FAILED tests/integration/test_sse.py::test_the_answer_arrives_as_complete_blocks_before_the_turn_ends
FAILED tests/integration/test_sse.py::test_a_block_g2_strips_is_streamed_and_then_replaced_by_the_final_answer
2 failed, 8 passed in 7.32s
```
Both restored: `10 passed in 6.69s`.

The wire fixture and the parity test were written together; the first run of
`tests/unit/test_streamed_completion.py` had 6 of 8 passing and 2 failing on a stub-script purpose
mismatch (`entry 1 scripts purpose 'route' but the loop asked for 'act'`), fixed in the test.

### The tests the brief names

| brief item | where |
|---|---|
| `test_stream_completion_parity` | `tests/unit/test_streamed_completion.py` — a `messages.create` control subclass against the **same** recorded response; text, tool-call args, `stop_reason`, all four token counters, `cost_usd_estimate`, `structured_output_mode`, plus a whole-model `model_dump` comparison excluding only `ttfb_ms` / `streamed` / `span_id` |
| `test_sse_delta_coalescing_under_queue_max` | `tests/unit/test_answer_stream.py` — 2,000 deltas, 40 blocks, every one delivered, frames < `QUEUE_MAX`, scans bounded by the batch size |
| provisional-then-replaced (G2 strips a block) | `tests/integration/test_sse.py::test_a_block_g2_strips_is_streamed_and_then_replaced_by_the_final_answer` with the new `tests/fixtures/llm_scripts/g2_strips_a_block.json` |
| `ttfb_ms` non-null on both adapters; `streamed` correct | `test_the_span_of_a_streamed_call_reports_a_first_delta_ttfb`, `test_a_response_with_no_prose_falls_back_to_the_round_trip`, `test_the_failover_adapter_is_not_streamed_and_still_reports_a_ttfb` |
| dashboard TTFB view labels streamed vs non-streamed | `tests/contract/test_dashboard_viewmodels.py` (`streamed == {"synthesize"}` on a stubbed turn) + the `Streamed` column in `llm.html` |
| narration covers every committed tool | `tests/unit/test_narration.py::test_a_label_exists_for_every_published_tool` (reads `mcp/tools/*.schema.json`) |
| SSE frame order for a stub turn; no label carries an argument | `tests/integration/test_sse.py::test_every_step_is_announced_before_its_span_closes` and `::test_no_step_started_label_carries_an_argument_from_the_script` |
| chat-page render test asserts the rail markup | `tests/contract/test_chat_page_renders.py::test_the_rail_narrates_each_step_and_the_answer_streams_under_it` |

---

## 3. Definition of done — real output

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
235 files already formatted

$ .venv/bin/pytest -q
........................................................................ [ 87%]
........................................................................ [ 91%]
........................................................................ [ 95%]
........................................................................ [ 99%]
..............                                                           [100%]
1814 passed in 163.87s (0:02:43)
```

(1,767 at the base per the brief; 1,774 at `HEAD~2` after the `--verify-manifest`-free run; 1,814
now. No warnings, no skips, no xfails.)

```
$ .venv/bin/python scripts/check_facts.py
  tax-and-location-addendum          md     12 sections
  travel-policy                      md     12 sections
  workplace-conduct                  pdf    13 sections

14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
EXIT=0

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
EXIT=0

$ .venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  pdf          1      15     2425
  txt          1      19     2624
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
EXIT=0
```

```
$ make demo1
demo1 EXIT=0
...
   24  llm_call       stub:stub                         0 ms  purpose=synthesize · 13512→648 tok
   25  guardrail      G2_citation_resolvability         0 ms  verdict=allow · 8/8 citations resolved
   26  guardrail      G3_fact_vs_recommendation         0 ms  verdict=allow · 7 block(s), every policy_fact cited
   27  guardrail      G6_pii_secret_redaction           0 ms  verdict=allow · final answer carried nothing to redact
-- usage: 5 model call(s), 7 tool call(s), 5 retrieval(s), 31985→1797 tokens in 502 ms

$ make demo2
demo2 EXIT=0
...
   25  tool_call      create_mock_hr_ticket             8 ms  create_mock_hr_ticket · ok
   27  llm_call       stub:stub                         0 ms  purpose=synthesize · 6255→415 tok
   28  guardrail      G2_citation_resolvability         0 ms  verdict=allow · 3/3 citations resolved
   29  guardrail      G3_fact_vs_recommendation         0 ms  verdict=allow · 5 block(s), every policy_fact cited
   30  guardrail      G6_pii_secret_redaction           0 ms  verdict=allow · final answer carried nothing to redact
-- usage: 7 model call(s), 6 tool call(s), 2 retrieval(s), 38858→1713 tokens in 315 ms
```

Not run (assigned elsewhere or explicitly forbidden): `evaluation.runner`, `evaluation.ablation`,
`make eval`, `make ablation`. `evaluation/results/**`, `evaluation/REPORT.md` and
`docs/optimization-log.md` are untouched (`git diff --name-only 699f631..HEAD` confirms). `.env` was
never read, printed or committed.

---

## 4. Files changed

New: `src/hrmosaic/agent/answer_stream.py`, `src/hrmosaic/web/narration.py`,
`tests/unit/test_streamed_completion.py`, `tests/unit/test_answer_stream.py`,
`tests/unit/test_narration.py`, `tests/fixtures/llm_scripts/g2_strips_a_block.json`.

Changed: `core/trace.py`, `core/models.py`, `core/llm/{base,anthropic,stub,cache}.py`,
`agent/{orchestrator,client}.py`, `agent/guardrails/{__init__,g2}.py`,
`web/{sse,main,dashboard}.py`, `web/templates/chat.html`,
`web/templates/dashboard/llm.html`, `web/static/app.css`,
`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`, `tests/conftest.py`,
`tests/unit/conftest.py`, `tests/unit/{test_span_listener,test_payload_size_control}.py`,
`tests/contract/{test_chat_page_renders,test_dashboard_viewmodels}.py`,
`tests/integration/{test_sse,test_search_returns_full_chunk_text}.py`.

---

## 5. Self-review findings (found and fixed in this diff)

1. **`CachedAdapter` would have announced a second step.** My first draft called `open_span` in the
   cached path as well; on a cache *miss* the wrapped adapter announces its own, so one logical call
   would have produced two `step_started` frames. Removed — a hit makes no round trip and has no
   step in flight to narrate, so it publishes no `started` event at all.
2. **`detail` was not redacted.** `open_span`'s detail is a tool's arguments straight off the wire,
   and what a listener is handed is what a listener could publish. It now goes through `redact()`
   like any payload, with `test_an_announced_step_is_redacted_too` pinning it
   (`confirmation_token` → `[REDACTED]`).
3. **A dangling spinner on a transport failure.** `McpClient.call_tool` announces before
   `session.call_tool`, which can raise `McpUnavailable` and leave no closing span. `turn_completed`
   now clears every still-running rail line.
4. **A stale provisional answer if the stream drops.** `stream.onerror` closes the stream but cannot
   clear the preview, so the htmx `afterSwap` handler clears it too.
5. **`aria-live` churn.** The first draft re-rendered the whole preview on every block, which would
   re-announce the entire answer to a screen reader each frame. Blocks arrive complete and in order,
   so each is appended instead.
6. **An unused return value** (`railEntry` returning its item) removed.
7. **`test_span_listener.py` was measuring the wrong thing** once `span()` announced its opening.
   Rather than filter the new events away, it now asserts the phase pairing directly
   (`["started", "closed"] * 3`, same `span_id`, `seq == 0` on the open) and reads `closed(...)`
   everywhere it asserts about the record — a strictly better test than before.

---

## 6. Ambiguities resolved, and how

1. **"the §16.2 stub keystone"** — the brief copies the plan's phrase, and the plan's own gloss is
   "36 `wire(...)` sites … serve JSON bodies today and `messages.stream` raises `AssertionError`
   against them". I read it as the `wire` fixture, and rewrote that first. `StubAdapter` (§16.2
   proper) also gained delta replay, because the SSE contract tests the brief mandates cannot exist
   without it.
2. **Narration keyed on "span kind + name"** — an `llm_call` span's name is `provider:model`, which
   cannot distinguish the router from the synthesis call. `label_for(kind, name, detail)` therefore
   keys on the tool's *name* for a `tool_call` and on the call's *`purpose`* (carried in `detail`)
   for an `llm_call`. Nothing else reads `detail`.
3. **Which spans get a `step_started`** — the brief lists five. `RecordingAdapter.complete` is the
   one seam for every `llm_call`, so `act` and `repair` steps are announced too, and the mapping
   gives them labels ("Deciding what to look up next…", "Working out what went wrong with that tool
   call…"). Filtering them out would have meant a bespoke branch and a rail that goes silent during
   the slowest part of a turn. `mcp_discovery`, `plan`, `retrieval` and `error` spans are **not**
   announced: nothing opens them ahead of time.
4. **The guardrail pass's pairing** — G1 runs at step 3 and G2/G3 at step 5, and the brief's label
   ("Verifying every claim against the policy text…") describes the post-synthesis pass. I open one
   step there and close it with **G2**, the pass's first span and the one whose verdict decides
   whether the answer survives. `guardrails.emit(..., span_id=…)` and `g2.check(..., span_id=…)`
   thread the id; no other rule's signature changed.
5. **The confirmation wait's label** — the brief lists it as a step but gives no wording (its
   `create_mock_hr_ticket` / `draft_hr_email` labels are the *tool* lines). I used "Waiting for your
   confirmation…" on the `confirmation` kind.
6. **"Preparing the ticket / email for your confirmation…"** — read as two labels, one per tool.
7. **"shows the answer text under the rail"** — the preview is rendered in the **conversation
   column**, directly beneath the message list and above the composer, not inside the rail aside.
   That is where the answer belongs, where the finished turn htmx swaps in, and therefore where a
   hard replace is meaningful. Flagging it as a deliberate reading of that phrase.
8. **Coalescing vs complete blocks** — both bullets are binding and they interact. The coalescer
   batches raw deltas before the buffer is re-scanned (~40 chars / ~100 ms), and the complete-block
   rule means one *frame* per block. Together the frame count is the block count (40 in the
   stress test) against `QUEUE_MAX = 512`, so no frame is ever dropped. The test asserts both: every
   block delivered, and the scan count bounded by the batch size rather than the delta count.
9. **`streamed` on the stub** means "this call was given a delta sink and replayed as deltas", so a
   stubbed turn reports `streamed=true` on its synthesis span and `false` on route/act. On the
   Anthropic adapter every call streams, so every span is `true`. Both readings are honest for their
   adapter; the dashboard column is about what `ttfb_ms` measures on that row.
10. **Spec amendments split across two commits** — §1.4's reversal and §9.8 land with the adapter
    that performs it (`P16(llm)`); §11.3, §11.6 and §21 row 12 land with the frames and the page
    (`P16(web)`). The brief says "the same commit"; I read that as "not a separate docs commit".

---

## 7. Concerns

1. **`make demo1 && make demo2` back to back raced on port 8000.** Run in one shell invocation,
   demo2's `wait_for_health.py` saw demo1's *dying* server (`is up after 0.0s`) and the first curl
   then failed with `curl: (7)`. Run separately both exit 0 (pasted above). This is the Makefile's
   existing `define demo` block — no port wait after `kill`, no `SO_REUSEADDR` grace — and predates
   this phase; I did not change it, but CI or a rehearsal that chains the two targets could hit it.
2. **One flaky interpreter-exit abort.** A single `pytest -q tests/unit` run printed
   `libc++abi: terminating due to uncaught exception of type std::__1::system_error: recursive_mutex
   lock failed: Invalid argument` **after** `1369 passed`, with exit code 0. Ten subsequent runs
   (five with the change, four on the stashed baseline) were clean, as was the full suite twice. It
   looks like an onnxruntime/fastembed teardown race on macOS rather than anything in this diff, but
   I could not reproduce it to prove that.
3. **`narration._section_label` reads the index on the serving loop.** One indexed lookup on the
   cached read-only connection, only for `get_policy_section` spans, and `corpusread` is already
   called that way from `Orchestrator._mark`. Worth knowing it is on the hot path of a frame.
4. **Deltas are assembled even with no subscriber.** `_synthesize` always attaches `on_delta`; with
   nobody listening the assembler still scans the synthesis body (~50 scans over ~2 KB). Measured as
   noise, and the alternative — asking the broker whether anyone is subscribed — would put a web
   concern inside the orchestrator.
5. **The performance claim is not re-measured here.** The −3.0 s p50 / −17.2 s p95 time-to-first-text
   figures are the plan's, carried into the spec as the plan's. Confirming them needs a live run,
   which this phase must not do.
6. **`tests/fixtures/llm_scripts/g2_strips_a_block.json` duplicates `rag_only`'s act steps**, so its
   two zero-tool-call closing steps now also count toward
   `tests/contract/test_act_closing_step_is_short.py`'s median. Same token counts as the script it
   was copied from, and that test still passes, but it is one more recording in that pool.

---

# Fix round 1 — the streamed answer now passes through G6

## F1. What the review found

`AnswerAssembler._drain` put the model's raw `blocks[].text` into a `StreamedBlock`,
`_synthesize`'s `publish()` handed it to `trace.publish_answer_delta`, and `sse.answer_delta_data`
put it on the wire untouched. `redact()` ran in exactly two places on that path — `prepare_payload`
for *persisted* span payloads and `g6.check` over the *final rendered* answer — and a delta is
neither. A secret-shaped string (`sk-ant-…`, `AIza…`, or any `os.environ` value whose key ends
`_KEY`/`_TOKEN`/`_SECRET`) reaching the model through a corpus chunk or a tool result and echoed in
a synthesis block would have been rendered verbatim in `#provisional-blocks` and stayed on screen
for the rest of the turn, while G6's guardrail span recorded `verdict=allow` — because the string it
scrubbed, the finished answer, is a different object. That is a hole in §17 (redaction is *the*
secrets control) and §7.4 G6 (the rule that enforces it on the way out).

The review was right, and it was right about my own reasoning: this diff's `open_span()` docstring
argues "what a listener is handed is what a listener could publish" and redacts `detail` for exactly
this reason (self-review finding 2 above). I applied that argument to the tool arguments and not to
the one thing on the path that is model-generated prose.

## F2. What changed

`src/hrmosaic/agent/answer_stream.py` — the construction site, not the publication site:

```python
text=redact_text(str(block.get("text") or "")),
```

`_drain` is the chosen seam over `publish_answer_delta` because it redacts at **construction**: a
`StreamedBlock` never carries an unscrubbed secret anywhere in the process, so no present or future
consumer of one can publish it. The `StreamedBlock` docstring now says so, and the module docstring's
rule list went from two rules to three ("Redacted before it leaves the process (§7.4 G6, §17)"), with
the reason recorded inline at the call site.

Nothing downstream moves: `redact()` is idempotent (`g6.py`'s own docstring says so), so the finished
answer, `g6.check`'s verdict and every persisted span payload are byte-identical to before. The
cost is one `redact_text()` per completed block — a handful per turn, not per delta, because the
coalescer already collapses the frame count to the block count.

Scope: `citations` are left alone deliberately. They are chunk ids validated against the index by G2,
not free prose, and none of the value patterns or the environment sweep can match one; redacting them
would spend the environment sweep on every id for no reachable failure.

## F3. Covering test — failing first

`tests/unit/test_answer_stream.py::test_a_streamed_block_is_redacted_too`, written in the spirit of
`test_an_announced_step_is_redacted_too` and placed beside the assembler it pins. It exercises both
redaction mechanisms that can reach model prose: a value regex (`sk-ant-…`) and the exact-match
environment sweep (`VENDOR_PORTAL_TOKEN` via `monkeypatch.setenv`), fed 11 characters at a time so
the block arrives through the real coalescing path.

With the fix reverted (`text=str(block.get("text") or "")`):

```
$ .venv/bin/pytest -q tests/unit/test_answer_stream.py
>       assert "sk-ant-api03-AAAAAAAAAAAAAAAAAAAA" not in delivered[0].text
E       AssertionError: assert 'sk-ant-api0...AAAAAAAAAAAA' not in 'The runbook...er2 in full.'
E
E         'sk-ant-api03-AAAAAAAAAAAAAAAAAAAA' is contained here:
E           The runbook chunk pastes sk-ant-api03-AAAAAAAAAAAAAAAAAAAA and the portal password hunter2-hunter2-hunter2 in full.
E         ?                          +++++++++++++++++++++++++++++++++

tests/unit/test_answer_stream.py:190: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_answer_stream.py::test_a_streamed_block_is_redacted_too
1 failed, 7 passed in 0.92s
```

With the fix in place:

```
$ .venv/bin/pytest -q tests/unit/test_answer_stream.py tests/unit/test_span_listener.py
..................                                                       [100%]
18 passed in 0.94s
```

## F4. Definition of done — real output

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
235 files already formatted

$ .venv/bin/pytest -q
........................................................................ [ 99%]
...............                                                          [100%]
1815 passed in 157.52s (0:02:37)
```

Pristine: no warnings, no skips, no xfails. 1,815 passed — 1,814 at `HEAD` plus the one new
redaction test.

```
$ .venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers

$ .venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  totals      14     204    30840
  index    data/index/hr_index.sqlite
OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)

$ make demo1   # exit 0
   27  guardrail      G6_pii_secret_redaction           0 ms  verdict=allow · final answer carried nothing to redact
-- usage: 5 model call(s), 7 tool call(s), 5 retrieval(s), 31985→1797 tokens in 423 ms

$ make demo2   # exit 0
   30  guardrail      G6_pii_secret_redaction           0 ms  verdict=allow · final answer carried nothing to redact
-- usage: 7 model call(s), 6 tool call(s), 2 retrieval(s), 38858→1713 tokens in 483 ms
```

Run separately, per concern 1 above — chained back to back they still race on port 8000, which is
the Makefile's pre-existing behaviour and untouched here.

`evaluation/results/**`, `evaluation/REPORT.md` and `docs/optimization-log.md` are untouched; `.env`
was never read, printed or committed. Two files staged: `src/hrmosaic/agent/answer_stream.py`,
`tests/unit/test_answer_stream.py`.

## F5. Concerns from this round

None new. The concerns listed in §7 above still stand as written; this round neither addressed nor
worsened any of them.
