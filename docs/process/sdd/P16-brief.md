# P16 brief — performance Wave 2, lever W2-E: stream the answer to the browser (approved by Sean 2026-09-10)

## Where this fits
Last lever of Wave 2. It does not change the final answer or any graded metric; it changes when the
user first sees prose (−3.0 s p50 / −17 s p95 to first visible answer text). It reverses spec §1.4's
non-goal bullet 1 ("token-level streaming buys cosmetics") — Sean approved the reversal on
2026-09-10; amend §1.4 and §11.3 accordingly in the same commit.

## Requirements
`docs/superpowers/plans/2026-09-10-performance-plan.md` §3 W2-E is the requirements text; every
"Required changes applied" bullet is binding: render only complete blocks through a JS mirror of
`render_answer()` (recommendation prefix preserved); stream `blocks[].text`/`citations` only, never raw
`rationale_summary`; coalesce deltas (~100 ms / ~40 chars) so `sse.py`'s `QUEUE_MAX` never drops
frames; mark the streamed answer provisional and hard-replace it on `turn_completed`; keep
`ttfb_ms = first_delta_ms or round_trip_ms` and add `streamed: bool` to the span payload; use
`stream.get_final_message()` — never a hand-rolled accumulator; rewrite the §16.2 stub keystone
first so the 36 `wire(...)` sites serve streams. The failover adapter (OpenAICompat) may stay
non-streaming; `streamed=false` on its spans.

## Second deliverable — live progress narration (approved by Sean 2026-09-10)
Today the chat page's span rail lists each span only after it closes, in technical form
(`tool_call · search_policy_documents — 5 hits`). Add plain-language, forward-looking status lines
at the START of each step, so a user watching the page sees what the assistant is doing while it does it:
- Emit a `step_started` SSE frame when a span opens (router, each tool call, the guardrail pass, the
  synthesis call, and the confirmation wait), via the same single `core.trace` listener seam as
  `span` (§11.3 — do not add a second publication path; extend `SpanEvent`/`_publish` with a phase
  field or add a sibling event on span open, whichever keeps "one listener" literally true).
- The label comes from ONE mapping module (`web/narration.py` or similar) keyed on span kind + name,
  with sensible defaults, e.g.: router → "Understanding your question…"; `search_policy_documents` →
  "Searching the policy library…"; `get_policy_section` → "Reading the {document title} section…";
  `list_policy_documents` → "Listing the policy library…"; `lookup_employee_profile` → "Looking up
  your employee record…"; `check_pto_balance` → "Checking your PTO balance…"; `lookup_benefits_status`
  → "Checking your benefits status…"; `check_policy_compliance` → "Checking this request against the
  rules…"; `create_mock_hr_ticket` / `draft_hr_email` → "Preparing the ticket / email for your
  confirmation…"; guardrails → "Verifying every claim against the policy text…"; synthesize →
  "Writing the answer…". Labels never include tool arguments or employee data — only a document
  title (from the index) where shown. Unknown spans get a neutral "Working…".
- The rail renders the in-progress line with a live elapsed counter and a subtle spinner; when the
  span closes, the same list item is replaced by today's closed-span line (keep the technical detail —
  it is part of the observability story — but put the friendly label first). `aria-live` stays polite.
- Streaming (the first deliverable) shows the answer text under the rail as it arrives; the rail's
  synthesis line switches to "Writing the answer…" at first delta.
- Tests: the mapping covers every tool in the committed catalog (`mcp/tools/*.schema.json`) — a test
  fails when a tool has no label; a contract test asserts the SSE frame order for a stub turn
  (`turn_started`, `step_started` … `span` … `turn_completed`) and that no `step_started` label
  contains an argument value from the stub script; the chat-page render test asserts the rail markup.
- Spec: one paragraph in §11.3 describing `step_started` and the narration mapping; the dashboard is
  untouched.

## Tests (mandatory)
- `test_stream_completion_parity`: text, tool_call args, stop_reason, all token counts,
  `cost_usd_estimate`, `structured_output_mode` identical between `create` and `stream` on one
  recorded response.
- `test_sse_delta_coalescing_under_queue_max`: a 2,000-delta synthesis delivers every block with no
  dropped frame.
- Provisional-then-replaced rendering: a turn whose G2 strips a block ends with the final answer, not
  the provisional one (contract test on the SSE frame sequence).
- `ttfb_ms` non-null on both adapters; `streamed` flag correct.
- The dashboard's TTFB view (§11.6 page 5) labels streamed vs non-streamed spans.

## Definition of done
- `.venv/bin/ruff check .` / `ruff format --check` clean; `.venv/bin/pytest -q` green, pristine;
  `scripts/check_facts.py`, `scripts/pii_check.py`, manifest verify unchanged. `make demo-1` /
  `make demo-2` (stub) still pass end to end.
- Commits `P16(web): …` / `P16(llm): …`. Never push. Never read or print `.env`. Never touch
  `evaluation/results/**` or `evaluation/REPORT.md`. Do not edit `docs/optimization-log.md`.
- No subagents. Report to `.superpowers/sdd/2026-09-08-implementation-roadmap/P16-report.md`.

## Small carry-forward from P15 (own commit `P16(core): …`, do first)
`core/trace.py` §10.5 `MAX_STRING_BYTES = 8 KB` now truncates the `search_policy_documents` tool_call
span's `result_json` at the default k=5 (whole chunks ≈ 8.3 KB), so the dashboard's span detail shows a
truncation marker for every search. Raise it to 24 KB (keep the 32 KB payload cap and the marker
behaviour), amend the §10.5 sentence and its rationale, and add a test that a k=5 search result with
five 1,384-char chunks is stored whole while a 40 KB string is still truncated with the marker.
