# HR Copilot — Performance Plan

**Scope.** Latency of the deployed agent turn (`POST /chat`), measured by the existing 26-item eval
harness against the Render free instance. Every figure below is reconstructed from
`r_1789055103_baseline` (deployed, judged) and its trace store; nothing is taken from a proposer's
summary without independent recomputation.

**Filter applied.** Twenty-one candidate levers were each reviewed by two adversarial lenses
(latency-realism, quality-and-grading-risk). Only levers where **both** lenses returned
`keep` / `keep_with_changes` are scheduled. Nine survived; twelve were rejected. Savings quoted are
the **verifiers'** realistic figures (the lower of the two lenses where they disagree), never the
proposers'.

---

## 1. Baseline

Source: `evaluation/results/r_1789055103_baseline.json` (target `deployed`, `judge_status: judged`,
264 judge calls) and `scratchpad/perf/deployed.sqlite`.

| Quantity | Value | Provenance |
|---|---|---|
| `latency_p50_ms` | **17,584.5** | committed run file |
| `latency_p95_ms` | **47,725.0** | committed run file |
| p50 order-statistic bracket | 16,504 / 18,665 ms | ranks 13–14 of 26 |
| p95 order-statistic bracket | 40,357 / 50,181 ms | ranks 24–25 of 26 (`unsafe-001`, `remote-004`) |
| Scored items | 26, all `cold = 0` | `n_cold = 0` |
| `llm_call` spans | 94 (3.615/turn, median 4, max 8) | trace store |
| Total `TokenBucket` sleep | **100,551 ms** over 39 of 94 calls | `limiter_wait_ms` sum |
| **Service time excl. limiter, p50** | **14,112.5** | `perf/decomp/summary.json`, independently reproduced |
| **Service time excl. limiter, p95** | **35,930.8** | same |
| LLM share of median turn | 88.9 % (five strictly serial provider round trips) | `inj-001` serial chain |

### Quality position (the budget this plan is spending against)

| Metric | Deployed baseline | RUBRIC5.1 target | Status |
|---|---|---|---|
| `groundedness_mean` | 0.9794 | ≥ 0.90 | pass (+0.079) |
| `cit_resolve_mean` | 0.9231 | ≥ 0.95 | **already failing (−0.027)** |
| `strict_pass_rate` | 0.6923 | ≥ 0.85 | **already failing (−0.158)** |
| `citation_accuracy_mean` | 0.8475 | — | reference |
| `doc_recall_mean` | 0.8553 | — | reference |
| `tool_selection_accuracy` | 0.9258 | — | reference |
| `workflow_completion` | 0.7692 | — | reference |
| `over_refusal_rate` / `missed_refusal_rate` | 0.1111 / 0.0 | — | reference |

Two of three published thresholds are already unmet. **There is no quality headroom to spend**, which
is why every lever that traded schema enforcement, evidence breadth, or a guardrail input for latency
was rejected regardless of its arithmetic.

### Two framing facts that govern every number below

1. **The published p50/p95 are contaminated by the harness, not by the product.** `TokenBucket.acquire()`
   sleeps *before* the `llm_call` span opens, so 100,551 ms of pacing sits inside `turns.duration_ms`
   and outside `llm_ms`. The per-turn median limiter wait is **0 ms** — this is 26 eval items colliding
   with their own `LLM_RPM=10` bucket, not something an interactive user experiences.
2. **`p95` at n = 26 is one interpolation between two turns.** The same code produced p95 = 47,725 ms
   deployed and 42,430 ms locally. Every p95 claim here carries that ±5 s instability.

---

## 2. Wave 1 — zero cost, no change to graded behaviour

Nothing in Wave 1 alters a prompt byte the model reads as *content*, a tool catalog, a schema, a
guardrail input, or a threshold. One config value and two request-path fixes.

### W1-A · Raise `LLM_RPM` / `LLM_BURST` (measurement hygiene)

**Change.** Environment variables on the **Render service only**: `LLM_RPM=20`, `LLM_BURST=12`.
No application code. (`settings.py:72-73`; `llm_burst` defaults to `llm_rpm` at `settings.py:163-164`;
consumed by `TokenBucket` in `core/llm/limiter.py:65-106`, acquired at `core/llm/base.py:458`.)

**Why 20, not the proposed 30.** A bucket replay over the real 94-call arrival sequence gives zero
wait at 20 RPM and at every setting above it; the binding threshold is between 15 and 20. Twenty
buys the entire measured saving at half the 429 exposure, and the account's true RPM/ITPM limits were
never verified from the Console.

**Required changes applied** (both lenses):
- **Scope to the server.** `shared_limiter()` is one process-wide bucket for agent + failover + **judge**.
  The harness process that drives the sweep must run with `LLM_RPM=10` explicitly exported, or this
  paces the Gemini judge — which has already produced 75 rate-limit retries and an aborted deployed
  judge pass.
- **Add a publish gate for failover contamination.** `base.py:71` puts 429 in `RETRYABLE_STATUSES` and
  `base.py:517-541` escalates to `gemini-3.5-flash-lite`, violating the §9.8 model pin *silently*
  (`run.config.llm_model` still reads `claude-haiku-4-5`). Assert `SUM(provider_failover) = 0` and
  `SUM(retry_count) = 0` over the run's spans; a failover invalidates the run.
- **Fix provenance.** `runner.py:904` records `llm_rpm` from the *harness*, so a server-only change
  publishes a run file claiming `llm_rpm: 10` for a latency produced at 20. Record the target's rate,
  or note it in `eval_runs.notes`.
- **Update the six committed statements of "10"** (spec §9.4 lines 1195-1197 and the §21 env table
  1839-1840, `design-and-evaluation.md:435`, `deployed.md:298`, `docs/architecture.html:1561/1660`,
  regenerated `evaluation/REPORT.md`) — RUBRIC5.6 requires every env var documented.
- **Do not raise** `check_render_hours.py`'s 600/750 warn line (unrelated, and it is the only warning).

**Saving.** Mechanically exact, cross-checked by an independent script: p50 17,584.5 → **14,112.5**
(−3,472.0), p95 47,725.0 → **35,930.8** (−11,794.2).

**Honesty flag — read this before quoting the number.** The interactive saving is **0 ms at p50 and
0 ms at p95**. A think-time sweep shows that at the *current* 10/10 setting, any inter-turn pause
≥ 10 s already yields exactly zero limiter wait. This removes the eval harness's self-collision from
the published metric and protects genuinely concurrent traffic; it makes no single turn faster. It is
scheduled first because it defines the frame every later lever is measured in.

**Effort** hours. **Rollback** revert two env vars; instant.

### W1-B · Query-vector memo — kill the search backfill's double embed

**Change.** `src/hrmosaic/rag/embed.py` only: a private `_embed_query_cached(model, convention, dim, text)`
under `functools.lru_cache(maxsize=16)`; `embed_query(text)` returns `list(...)` of it. No change in
`search_policy_documents.py` or `retrieve.py` — they get the hit for free.

**Mechanism.** `search_policy_documents._blocking_search` calls `retrieve(query, …)` a **second** time
with the identical query string whenever `backfill_reason_for()` fires, and sums both into
`embed_ms`. 22 of 28 deployed retrievals backfill; backfilled `embed_ms` p50 is 679 ms against
390 ms for the 6 that do not.

**Required changes applied:**
- **Structural 0.50 attribution, not the 0.425 between-group ratio.** A length-controlled fit
  (`embed_ms = n_embeds × (232.5 + 2.378 × query_chars)`, R² 0.763) puts both groups on one line; the
  1.74× ratio was confounded (the non-backfilled queries are *longer*, median 70 vs 48 chars).
- **`maxsize=16`, not 256.** The entire win is intra-call (22 intra-call hits vs 2 cross-call over
  28 spans; **0** within-turn query repeats). 256 × 12,328 B = 3.16 MB resident on a 512 MB instance
  and retains 256 raw user query strings for the process lifetime.
- **Add `settings.embed_dim` to the key.** `model_name()` collapses every fake-provider configuration
  onto `FAKE_MODEL_NAME` while `_fake_embed` reads `settings.embed_dim` — a dim change is invisible to
  the key advertised as the staleness guard.
- **Expose `clear_query_cache()`** and call it from an autouse fixture next to `fake_embedder`, or the
  lever's own unit test is order-dependent under a process-wide LRU and passes vacuously.
- Keep the fastembed call literally inside `rag/embed.py` (`tests/architecture/test_conventions.py`
  greps that file).

**Saving.** **−304 ms p50 / −570 ms p95** (quality lens; latency lens 330/640 — the lower taken).
Robust statistic: mean **298 ms/turn** over all 26 turns, 436 ms over the 14 turns that retrieve-with-
backfill. 12 of 26 turns save exactly zero. Bootstrap CI is wide (p50 [0, 480]) because whether the
median-rank turn carries a backfilled retrieval is luck — **gate on the span-level invariant, not the
run p50** (see §5).

**Disclosure.** This is the one Wave 1 item whose bytes reach the model: `SearchOutput.embed_ms` is a
declared wire field that flows into the act conversation and the synthesize prompt, so `embed_ms` moves
on 23 of 28 spans / 14 of 26 items. It cannot *regress* — it is a wall-clock telemetry number that is
already nondeterministic run-to-run by construction, and the change moves it **into** the 393 ms band
that 6 deployed spans already occupy. A 28/28 offline replay proves rank, `chunk_id`, `dense_score`,
`rrf_score`, `bm25_rank` and backfill flags bit-identical. If the owner wants Wave 1 strictly
byte-invariant on the model's view, move W1-B to Wave 2 — the cumulative arithmetic is unchanged.

**Effort** hours. **Rollback** delete the decorator; one line.

### W1-C · Take the trace store off the request path

*(Merges `infra:INF-3` and `per-call:L5` — they are the same change and must not be double-counted:
L5's daily-cap SELECT is a strict subset of INF-3(a).)*

**Change, scoped to three parts:**
- **(a) Daily cap as a fast negative.** Replace the per-call `count_calls_today` (`core/llm/base.py:504-515`
  → `limiter.py:61`) with an in-process counter that **only** short-circuits while `counter < cap`;
  when `counter >= cap`, run the authoritative SQL and raise `DailyCapExceeded` from *that* number.
  Increment inside `record_llm_call` (`base.py:331`) — the single writer of `llm_call` spans, which
  also covers the cache-hit path — keyed on `completion.provider`, **never** `self.provider`.
  `/health.llm.agent.calls_today` keeps calling `count_calls_today` unchanged.
- **(b) Async turn-open batch.** `create_task(asyncio.to_thread(store.batch, …))` at
  `orchestrator.py:547`, **awaited before the first `add_span`** (behind the ~258 ms of catalog
  assembly + G4 scan in the median turn). Register the buffer in `TraceWriter._open` *before*
  dispatching, or `flush_open_turns()` cannot see a turn that dies in the window.
- **(c) In-memory rollups.** Build `Usage`/`Timings` from `TurnBuffer`'s stored close values rather
  than re-SELECTing the turns row. Must publish the exact `ended_at`/`duration_ms`/`store_us` that
  `TURN_CLOSE` wrote.

**Part (d) of the original proposal is DROPPED** (backgrounded flush + `trace[]` from memory). It is
**0 ms in-metric by construction** — `ended_at` is stamped at the top of `close()` before the flush —
and it races `evaluation/runner.py:344`'s `read_turn`, which fires microseconds after the response and
would silently score a raced item as a real turn with zero tools, zero docs, zero citations and
latency 0. It also breaks §11.1's "provably the same rows" property and the resume path.

**Corrections to the proposal's own text:** `CALLS_TODAY_SQL` is **not** a full-table `json_extract`
scan — `migrations/001_initial.sql:64` creates `ix_spans_kind ON spans(kind, started_at DESC)` and
`EXPLAIN QUERY PLAN` returns `SEARCH … USING INDEX ix_spans_kind`. The cost is pure RTT (~1.8 ms of
query) and does not grow with the table.

**Because (a) is a fast negative, §9.8's "counted from `llm_call` spans, so there is no second counter
to drift" stays literally true and needs no rewording.** Re-seed on the UTC-day rollover and every
N ≤ 100 calls anyway. Note that the cap now trips mid-turn rather than at a turn boundary (spans flush
at end of turn today) — pin that semantics with a test or snapshot the counter once per turn.

**Saving.** **−111 ms p50 / −136 ms p95** (quality lens; latency lens 118/140). Arithmetic:
`sum(store_ms) = 1,646` + `94 × 22 ms` = 3,714 ms run total → quantile shift 119.5 / 141.2, shaded.
Parts (a)+(b) are the whole in-metric figure; (c) is ~4 ms of user wall clock outside the metric.

**Effort** 1–2 days — `buffer.seq` is read out of the open batch's readback (`trace.py:721`) and has
four consumers, so (b) is a `TurnBuffer` constructor and resume-path refactor, not a one-liner.
**Rollback** revert; the counter is additive and the batch await can be made synchronous again.

### Wave 1 arithmetic

| Step | p50 (ms) | p95 (ms) |
|---|---|---|
| Baseline | 17,584.5 | 47,725.0 |
| − W1-A limiter (exact) | −3,472.0 → **14,112.5** | −11,794.2 → **35,930.8** |
| − W1-B query memo | −304 → **13,808.5** | −570 → **35,360.8** |
| − W1-C store off path | −111 → **13,697.5** | −136 → **35,224.8** |
| **After Wave 1** | **≈ 13,698** | **≈ 35,225** |

No double-counting: W1-A removes sleep, W1-B removes CPU, W1-C removes network RTTs — three disjoint
budgets, all strictly serial on a pipeline with no `asyncio.gather` anywhere on the request path.

**Real interactive improvement from Wave 1: 415 ms p50 / 706 ms p95.** The other 3,472 / 11,794 ms is
a harness artifact leaving the published metric.

**Cost** $0/month. **Re-eval required** yes — one deployed sweep to republish figures under §13.5 and
to prove the round-trip counter; the judge pass is for provenance, not correctness (no graded
behaviour changes).

**Tests to add**
- `test_query_embed_memo_hits_once`: one `search_policy_documents` call whose topic triggers a backfill
  invokes the fastembed model **once**, with `clear_query_cache()` in an autouse fixture.
- `test_query_memo_key_covers_dim`: flipping `settings.embed_dim` under the fake provider returns a
  correctly-sized vector.
- `test_daily_cap_counter_equals_spans`: after a scripted run (with `LLM_CACHE_TTL_S > 0` in at least
  one case), the in-process counter equals `SELECT COUNT(*) FROM spans WHERE kind='llm_call' AND
  provider=?`; and `/health.llm.agent.calls_today` still matches.
- `test_daily_cap_failover_not_miscounted`: a failover-recorded call does not increment the anthropic counter.
- `test_turn_row_visible_before_first_span`: the turns row is committed before the first `add_span`.
- `test_open_batch_flushed_on_sigterm`: a signal inside the deferred-open window still flushes the turn.
- `test_rollups_match_stored_row`: in-memory `usage`/`timings` equal the persisted turns row on
  **every** field (`total_tokens_in/out`, `retrievals`, `llm_ms`, `retrieval_ms`, `tool_ms`, `store_ms`,
  `total_ms`) — extending `tests/integration/test_audit_completeness.py:123-126`.
- Store-round-trip counter on `TursoHTTPStore._pipeline`, surfaced on `/health`, asserted to fall from
  p50 8 → p50 2 on the eval path.

**Rollback** all three are independently revertible without a redeploy of code for W1-A (env only);
W1-B and W1-C are single-commit reverts. No data migration, no index rebuild, no prompt golden.

---

## 3. Wave 2 — zero cost, changes graded behaviour, requires a re-run **and** the judge

Everything here moves bytes the model reads or writes. A full deployed 26-item sweep **plus** the
Gemini judge pass **plus** both §13.9 ablation arms is a correctness gate, not a formality —
`evaluation/ablation.py::assert_comparable` checks only `target` and `dataset_sha`, so a baseline-only
re-run silently publishes a mixed-code comparison.

### W2-A · Stop the act loop's closing step writing an answer that is thrown away

**Change.** `src/hrmosaic/agent/prompts/act.j2` rule 7 only. No code.

**Mechanism.** 21 of 53 deployed act calls close the loop with zero tool calls and emit a median
**224 output tokens / 784 chars** of prose — 48 % of all act output tokens — that no answer path reads
(`_synthesize` re-renders from `turn.chunks()`/`turn.envelopes`; `_clarification_text` uses the router's
rationale; `_park` uses the proposal; `_degraded` uses a constant). Act output costs 10.238 ms/token
(per-role fit, R² .857), cross-validated by the independent probe at 9.86–11.0 ms/token plain text.

**Required changes applied:**
- **Do not tell the model "a separate later step composes the answer."** It is false on the refuse /
  park / clarify paths (9 of 26 turns never synthesize), and it removes the incentive to draft — which
  is where evidence gaps surface. Keep `"Stop calling tools as soon as you have what the turn needs"`
  byte-for-byte and append only a **format** constraint on the closing sentence.
- **Do not add a blanket "must not restate policy."** Three in-conversation consumers read that text and
  the proposal names none of them: `_nudge` (`orchestrator.py:890-922`) `continue`s the loop so the
  closing text is the assistant turn the reminder answers; the G1 recovery path
  (`orchestrator.py:626-634`) appends `G1_RECOVERY` to the same conversation and the code comment says
  the reopen step is "spent blind" without context; `_rehydrate_messages` (`:1557`) replays it on resume.
  The closing sentence must still name *what was gathered*, specifically enough that a nudged step does
  not re-search covered ground.
- **Plan for ~40 output tokens, not 15.** 15 is below what "one short sentence naming what was gathered"
  produces.
- **Split the success metric by terminality.** Only 16 of the 21 zero-tool-call calls are terminal
  (median 178.5 out-tok); 5 are re-sent. Measuring the pooled median would report success by shortening
  messages the loop still reads.
- **Re-baseline on HEAD first** — see §5. `af95de4` added a *third* reminder (`SEARCH_BREADTH`, fires
  whenever the turn has searched ≤ once) and `G1_RECOVERY` after both measured runs. On HEAD, 12 of the
  18 act-loop turns had ≤ 1 search and no other reminder, so their closing message becomes an input to a
  further step rather than dead text.

**Saving.** **−1,450 ms p50 / −535 ms p95** (latency lens p50 1,450 / quality lens p95 535 — the lower
of each taken). The p95 is small and the quality lens is right about why: `remote-004`, the dominant
p95 anchor, exits its last act step *with* tool calls, and its only zero-tool-call step is consumed by
`workflow_incomplete`. **Effort** hours (one prompt rule + one golden fixture).

### W2-B · Output-token diet on synthesize (de-risked: 2 of 4 clauses shipped)

**Change.** `src/hrmosaic/agent/prompts/synthesize.j2` rule 7 only:
- cap `next_steps` at **3 items of ≤ 20 words** (not ≤ 12);
- tighten `rationale_summary` to **≤ 120 chars** (not ≤ 80).

**Two clauses of the original proposal are DROPPED:**
- **Citation ordinals — dropped.** They disarm the only deterministic mis-citation detector in the
  system. `g2.resolve` strips on `corpusread.get_chunk(chunk_id) is None`; a hallucinated 16-hex id
  resolves to `None`, but an ordinal in `[1..n]` **always** maps to a real in-prompt chunk, so an
  off-by-one ships a wrong-but-resolvable citation on the wrong passage. Worse, the proposal's own
  safety check is vacuous: `citation_resolvability` runs over `turn.citations`, which `g2.resolve`
  *builds from the index row*, so it is 1.0 by construction — proven by `pto-002`, which emitted the
  bogus citation `"tool_result: check_pto_balance"`, had a whole `policy_fact` block dropped, and still
  scored `cit_resolve = 1.0`.
- **`max_tokens['synthesize'] 2048 → 900` — dropped.** It is **0 ms** by the proposal's own basis
  (zero `max_tokens` stops in 185 calls) and converts the tail into a hard failure: a truncated
  `output_config` reply is invalid JSON → `_degraded(synthesis_failed)` → `outcome="partial"` with zero
  citations. 900 is 1.16× the observed max of 778 (vs 2.63× today). If a tail bound is wanted at all,
  1,200–1,400 with an explicit `finish_reason == "max_tokens"` branch.

**Do not trim rule 8** (work through CITATION COVERAGE one document at a time) or the coverage index:
13 of 16 gradeable answered turns sit at **exactly** `min_distinct_docs` and 2 are already below it.

**Saving.** **−470 ms p50 / −920 ms p95** — the de-risked figure: 4.4 % of synthesize output tokens ×
27.41 ms/output-token (today's rate) × median 390 / p95 760 output tokens. **Effort** hours.

### W2-C · Full chunk text in search results

**Change.** `src/hrmosaic/mcpserver/tools/search_policy_documents.py`: include full `chunk.text` on each
hit alongside the 320-char `snippet` (`rag/chunk.py:40 SNIPPET_CHARS = 320`; `retrieve.py`'s `Hit`
already carries `.text` from the same query, so the server does zero extra work). `act.j2` rule 6:
**retarget**, do not delete.

**Mechanism.** 10 of 53 act steps (on 7 turns) exist only to call `get_policy_section`, costing
21,618 ms across the run, purely because the snippet is 320 chars while 116 of 116 retrieved chunks
are longer (median 974).

**Required changes applied:**
- **BLOCKING — never put a quarantined chunk's full text on the wire.** The corpus's only quarantinable
  chunk is 630 chars and its `IGNORE ALL PREVIOUS INSTRUCTIONS…` imperative begins at char **355** —
  beyond `SNIPPET_CHARS`. Today `g4.scan(text[:320])` is `None` and the imperative never reaches the act
  conversation; under this change it does, and the wire body reports `"quarantined": false` because
  `_search` builds `SearchHit` with no `quarantined` kwarg (the flag is set client-side by `_mark`).
  Emit `text` only for chunks that scan clean; for a dirty chunk emit the snippet **and** set
  `quarantined: true`. The proposal's stated fix ("run `_scan` before the tool_result append") is a
  misdiagnosis — `_scan` only emits a span and redacts nothing.
- **Retarget rule 6, do not remove it.** 45.2 % of today's section bytes are *neighbour* bytes
  (10 of 14 `get_policy_section` calls pass `include_neighbors=true`) that a search hit cannot supply,
  and `onboarding-001` fetches heading paths no search in that turn returned. Keep the tool for the
  neighbour case; expect ~4 of the 10 steps to survive, which is why the saving is halved.
- **Do not render the full text twice.** Strip `text` from the search envelope in the synthesize
  `tool_results` loop so the banner-marked `<document>` block stays the single copy.
- **Cap the injected text** (top-N hits, or a `CHUNK_MAX_CHARS` clamp): the max-observed turn adds
  18,157 chars, and those tokens are re-billed on every subsequent act step.
- **Drop the `remote-004` dataset edit** from this lever entirely — `remote-004` calls
  `get_policy_section` in **neither** run; the proposal's stated ToolRecall risk does not exist and the
  edit would mask a real baseline miss (its `tool_recall` is already 0.75).
- Declare the contracts: §13.3 (spec line 1997) and `evaluation/runner.py:947-951`'s `ENVELOPE_KINDS`
  docstring both assert the search envelope holds display snippets of chunks already present in full —
  both become false. The committed `mcp/tools/search_policy_documents.schema.json` output schema and
  description change under `tests/contract/test_tool_schemas_committed.py`.

**Saving.** **−400 ms p50 / −700 ms p95** (latency lens, limiter-stripped and prefill-netted; quality
lens 700/3,200 — the lower taken). **Effort** 1 day.

### W2-D · Input diet — model-facing tool envelopes *(credited 0 ms; a cost lever)*

**Change.** (1) `ToolResult.prompt_text` alongside `text` — drop the 10 retrieval telemetry keys and the
7 per-hit score/offset keys from what the model sees; `text` stays whole for the §11.1 span, G4 and the
eval scorers. (2) In `synthesize.j2`'s EMPLOYEE CONTEXT loop, filter by the **complement of
`ENVELOPE_KINDS`** — drop **only** `search_policy_documents` and `list_policy_documents`.

**Part (3) of the proposal is DROPPED** (act-history digest): zero contribution at p50 (the median turn
has 2 act steps and pruning bites from step 3), while one induced re-call costs a whole extra act step
(2,430 ms median LLM + 4,054 ms tail) — 53× the entire saving.

**The proposal's own filter is the blocking defect.** "Employee-data and write tools only" deletes the
`check_policy_compliance` envelope, whose `verdict` / `requirements[].met` / `unmet` /
`approvals_required` / `escalate_to` / `as_of` / `rules_version` exist **nowhere else** in the prompt
(only `search_policy_documents` emits a `RetrievalPayload`, and `_absorb` populates `turn.evidence`
exclusively from `result.retrievals`), and deletes `get_policy_section` envelopes whose chunk ids are
absent from EVIDENCE on 3 of 14 calls. Export the tool→class map from **one** module that both
`runner.py` and the synth render import, with a contract test asserting the sets are equal — §13.3 says
`_evidence_of` is *the* definition, and a drift makes `groundedness` stop describing what the model saw.

**Saving.** **0 ms credited.** Both lenses measured 20–25 ms p50 and 0–50 ms p95; at 30 ms/1k input
tokens on TTFT and 6 ms/1k on total, ~982 tokens is a rounding error. It ships for **cost**
(−$2.8/month, ~9 % of input per turn) and for the `ENVELOPE_KINDS` unification, bundled here because
Wave 2 already pays for the re-run. **Effort** 1 day.

### W2-E · Stream the answer to the browser *(credited 0 ms; TTFA only)*

**Change.** `anthropic.py:invoke` → `client.messages.stream` (still in `asyncio.to_thread`,
`max_retries=0`), an `on_delta` on `CompletionRequest`, a separate **delta listener** in
`core/trace.py` (not `_publish`, which is typed on `SpanEvent` and whose only listener is
`publish_span`), a new `answer_delta` SSE frame, and provisional rendering in `chat.html`.

**Required changes applied:**
- **Render only complete blocks**, through a JS mirror of `orchestrator.py:423 render_answer()` so a
  recommendation carries its `"Recommendation — not company policy: "` prefix. Cost of the safety:
  19.2 % of synth output closes block 0, so the head start falls from 6,624 → 5,352 ms p50 (81 % kept).
- **Stream `blocks[].text`/`citations` only** — never raw `rationale_summary` (clamped to 200 chars only
  post-hoc, §9.7).
- **Coalesce** (~100 ms / ~40 chars): uncoalesced, 390–778 deltas overrun `sse.py`'s `QUEUE_MAX = 512`
  and `_offer` drops frames **silently** — measured: 2,000 frames → 512 delivered, 1,488 dropped.
- **Mark provisional, hard-replace on `turn_completed`.** 2 of 17 answered turns are revised after the
  last token (`pto-002` G2 strip, `profile-001` G3 relabel); 11 of 138 local synth turns diverge
  raw-vs-final; G2 retains a total-refusal branch.
- **Keep `ttfb_ms = first_delta_ms or round_trip_ms`** (the failover adapter does not stream and
  `test_llm_span_emission.py:189` asserts non-null), and add `streamed: bool` to the payload or
  §11.6 page 5 mixes two TTFB definitions.
- **Use `stream.get_final_message()`**, never a hand-rolled accumulator, with a golden parity test —
  a bad `input_json_delta` accumulator is the only path by which this can move ToolSelection.
- **Rewrite the §16.2 stub keystone first**: 36 `wire(...)` sites across 5 unit modules + 3 integration
  modules serve JSON bodies today and `messages.stream` raises `AssertionError` against them.
- **Spec:** this reverses §1.4 non-goal bullet 1 ("token-level streaming buys cosmetics"), not merely
  extends §11.3. Owner sign-off on the reversal.

**Saving.** **0 ms to turn completion** (marginally negative: ~+21 ms/turn client CPU locally,
~210–350 ms scaled by the 10–16× host penalty). What it buys is **time to first visible answer token:
−3,049 ms p50 / −17,161 ms p95** (first *prose*, after the JSON preamble and complete-block rule).
It is also the only change that makes `ttfb_ms` a real TTFB — today `ttfb_ms == duration_ms` on all 185
spans, the single biggest measurement gap in the evidence base. **Effort** days.
**Schedule last, and only if the owner wants the demo/UX win** — it is not a latency lever.

### Wave 2 arithmetic

| Step | p50 (ms) | p95 (ms) |
|---|---|---|
| After Wave 1 | 13,697.5 | 35,224.8 |
| − W2-A act closing-step diet | −1,450 → **12,247.5** | −535 → **34,689.8** |
| − W2-B synthesize output diet | −470 → **11,777.5** | −920 → **33,769.8** |
| − W2-C full chunk text | −400 → **11,377.5** | −700 → **33,069.8** |
| − W2-D input diet | 0 (cost lever) | 0 |
| − W2-E streaming | 0 (TTFA only) | 0 |
| **After Wave 2** | **≈ 11,378** | **≈ 33,070** |

**Overlap accounting.** W2-A acts on the terminal zero-tool-call act step's *output*; W2-B on
synthesize's *output*; W2-C removes *intermediate* `get_policy_section`-only act steps. Disjoint calls
and disjoint token classes, so additive. The one real interaction — W2-C's added chunk-text prefill
re-billed on the steps W2-A shortens — is ~54 ms and is **already netted inside W2-C's 400 ms**.
W2-D is credited 0 partly *because* it interacts with W2-C (one adds chunk text to the act result, the
other prunes envelopes), so no interaction term is being hidden.

**Cumulative from baseline: p50 −6,207 ms (−35.3 %), p95 −14,655 ms (−30.7 %).** Against the honest
limiter-stripped baseline (14,112.5 / 35,930.8) the genuine interactive improvement is
**−2,735 ms p50 (−19.4 %) and −2,861 ms p95 (−8.0 %)**.

**Cost** ≈ **−$4.4/month** (W2-A −$1.05, W2-B −$0.52, W2-D −$2.80; W2-C's claimed −$6.45 is credited 0
until re-derived — it nets only the act-side tokens and ignores the second copy the synth prompt
renders on 17 of 26 turns, and re-bills chunk text on every subsequent act step, not once per turn).

**Re-eval required** — mandatory and full: deployed 26-item sweep + judge pass + **both** §13.9 ablation
arms on the same `git_sha`, `LLM_CACHE_TTL_S=0`. Regenerate all six prompt golden fixtures. If
`ENVELOPE_KINDS` membership changes (W2-D), `evaluation/reference_labels.yaml` must be re-authored by an
independent blind labeller — `scripts/gen_label_packet.py` builds the packet from the same
`_evidence_of`, so the committed `judge_agreement_rate = 1.0` would no longer describe the system.

**Tests to add**
- `test_prompt_golden` regeneration for `act.j2` and `synthesize.j2` as a **deliberate re-review**;
  the act *system* half must stay byte-stable relative to the cache breakpoint.
- `test_search_hit_omits_text_for_quarantined_chunk` — the canary chunk returns snippet-only with
  `quarantined: true` (the highest-severity gate in the wave).
- `test_no_act_message_contains_unbannered_g4_pattern` — asserted directly over `llm_messages`.
- `test_envelope_partition_is_one_definition` — the set rendered into synth EMPLOYEE CONTEXT equals
  `evaluation.runner.ENVELOPE_KINDS`.
- `test_prompt_golden` fixture extended with `get_policy_section` and `check_policy_compliance`
  envelopes (today's single `check_pto_balance` envelope survives every proposed filter, so the suite
  would stay green while section and compliance envelopes vanished).
- `test_act_closing_step_is_short` — median `completion_tokens` of **terminal** zero-tool-call act spans
  ≤ 40, measured separately from consumed ones.
- Streaming: `test_stream_completion_parity` (text, tool_call args, stop_reason, all token counts,
  `cost_usd_estimate`, `structured_output_mode` identical between `create` and `stream` on one recorded
  response); `test_sse_delta_coalescing_under_queue_max`.

**Acceptance gates (per item, not on means).** `groundedness_mean ≥ 0.90`; `cit_resolve_mean ≥ 0.9231`;
`strict_pass_rate ≥ 0.6923`; `citation_accuracy_mean ≥ 0.8475`; `doc_recall_mean ≥ 0.8553`;
`tool_selection_accuracy ≥ 0.9258`; `workflow_completion ≥ 0.7692`; `over_refusal_rate ≤ 0.1111`;
`missed_refusal_rate == 0.0`; `injection_quarantined == true`; `blocks_dropped_by_g2 ≤ 1`;
`turns.total_tokens_out` per answered turn does not rise; zero turns with `outcome == "answered"` and
`len(blocks) == 0`; act steps/turn median stays 2.0 and tool_calls/turn stays 2.0. Watch by name:
`expenses-002`, `onboarding-001`, `remote-002`, `remote-004`, `conduct-001`, `pto-001`,
`expenses-001`, `inj-001`, `unsafe-001`, `pto-003`.

**Rollback** every item is a prompt or a single-module revert plus a golden regeneration; W2-C also
reverts the committed tool schema. **Ship W2-A, W2-B and W2-C in separate commits and, ideally,
separate sweeps** — n = 26 cannot attribute a regression to one of three simultaneous prompt edits.

---

## 4. Wave 3 — priced / policy-reversing · **owner approval required, NOT recommended**

> The owner said not to spend money without asking. **Nothing in this wave passed the two-lens filter
> and nothing here is credited toward the predicted p50/p95 above.** It is listed so the decision is
> the owner's, not an engineer's.

### W3-A · Move to a paid CPU tier — **$7.00/month** (Render Starter, 0.5 CPU / 512 MB)

One field in `render.yaml` (`plan: free` → `starter`), prorated to the second — a one-hour proof costs
$0.0096. Latency lens: **keep_with_changes at ~450 ms p50 / ~1,200 ms p95** (it corrected the
proposer's 985/1,723 by ~2.2× — `residual_python` is only 4.8× local, not the ≥14× a CFS-throttled
CPU section must show, because ~154 ms/turn of it is Turso RTT, not CPU).

**Quality lens: reject.** Reasons the owner must weigh:
- It trades **RUBRIC5.6** ("Free-tier deployment … with cold-start behavior documented") and the
  unconditional requirement "Deploy … to a free-tier or zero-cost host".
- It **destroys still-unmeasured required evidence**: `deployed.md` still reads `## Cold start:
  pending: gate 2`, and `scripts/measure_cold_start.py` idles 1,000 s *waiting for the free spin-down*.
  On a no-spin-down plan there is no cold segment to measure, ever.
- "No code" is false: `scripts/provision_render.py` hard-blocks a non-free plan in four places and
  seven unit tests pin that guard (one uses literally `plan="starter"`), plus
  `tests/contract/test_deploy_manifests.py:126`.
- Verification requires a re-run whose **measured** churn floor is 12 of 26 items and
  −5.13 pts of `citation_accuracy_mean`, with `unsafe-001`'s §8.6 confirmation gate already having
  flipped between the two existing runs.

**If approved:** change the plan on the **existing** service (never create a new one — six `sync: false`
secrets and `OMP_NUM_THREADS=1` would need repopulating, and a missed `OMP_NUM_THREADS` silently changes
ONNX reduction order and can move `dense_score` across G1's 0.60/0.45 thresholds); measure cold start
**first**; record the compute plan in `RunConfig` and in `ablation.assert_comparable`; re-drive all
three arms; decide the publication story before measuring (under the proposal's own protocol the plan is
downgraded afterwards, so the graded artifact would ship on free while a $7 host produced the table).

### W3-B · External keep-alive pinger — $0 cash, **730.5 of 750 free instance-hours/month**

Latency lens: **reject** — 0 ms on the published metric (all 26 rows are `cold=0` by construction), and
the benefit is on a path that has never been measured on the live host. Also reverses spec §14.4 and
risk R-10 explicitly. Two findings not in the proposal: `check_render_hours.py` **cannot read hours on a
free instance** (its own comment records `/v1/metrics/instance-count` returning `[]`), so the 750-hour
risk it creates has no working meter; and `GET /health` costs **five synchronous Turso round trips**,
so 4,320 pings/month is 21.6 M–432 M row reads against Turso free's 500 M/month.

**If the owner wants cold-start insurance anyway:** measure cold start first; window the cron to the
grading/demo hours (~176 h/month, 23 % of cap) rather than 24/7; ping `/ready`, not `/health`; make it
disableable in one step and **off** during every measurement run.

---

## 5. Measurement protocol

The claims above are 100–1,450 ms each against a run-to-run noise floor of seconds. **The eval's
`latency_p50_ms` / `latency_p95_ms` cannot prove most of them.** The protocol is therefore built on
paired per-item deltas and deterministic span-level invariants, with the quantiles reported as context.

### 5.1 Conditions and n

| Condition | Sweeps | Turns | `llm_call` spans | Purpose |
|---|---|---|---|---|
| `before` (HEAD, re-baselined) | 2 | 52 | ~188 | see §5.5 — the committed baselines are stale |
| `after` Wave 1 | 2 | 52 | ~188 | store/embed invariants + limiter zero |
| `after` Wave 2 | 3 | 78 | ~282 | the p95 claims need the extra n |

Cost per sweep: ~$0.47 of Haiku (`cost_usd_estimate` of the committed run) + 264 billed Gemini judge
calls at ≈ $0.16 (the judge project has been on paid billing since 2026-09-10). Three sweeps ≈ $1.41
of Haiku + ≈ $0.48 of judge over ~790 judge calls; budget the judge's `JUDGE_RPM=10` pacing (~9 min/arm)
and its recorded 429s.

### 5.2 Fixed conditions (all runs)

- Same 26 items, `evaluation/dataset.yaml`, **unchanged `dataset_sha`**.
- Target = the **deployed** instance (RUBRIC5.1 and §13.5 admit no other source).
- `LLM_CACHE_TTL_S=0` (§22).
- **Warm:** `runner.warm_up()` discards a `/health`, sends one throwaway `/chat`, then polls until
  `app.uptime_ms ≥ 60,000`. **Assert all 26 scored rows have `cold = 0`** before reading any number.
- **Harness `LLM_RPM=10` explicitly exported** even after W1-A, so the shared bucket does not pace the
  judge. Verify `default_settings.llm_rpm == 10` in the driving process as a pre-flight.
- Same `git_sha` across baseline and both ablation arms (`assert_comparable` will not catch a mismatch).

### 5.3 Primary comparison — paired, per item, limiter-stripped

For each of the 26 items compute

```
service_ms(item) = turns.duration_ms − Σ(llm_call.payload_json.limiter_wait_ms)
```

and report the **paired median delta** with a bootstrap CI over items, not the difference of quantiles.
Justification: `p50` is decided by ranks 13–14 (16,504 / 18,665 ms) and `p95` by ranks 24–25
(40,357 / 50,181 ms); a lever that helps 14 of 26 turns can move the quantile by anything from 0 to its
full per-turn value depending on which turn lands at the bracket. Drop-one jackknife on W1-A alone moves
`d_p50` across 1,591–5,353 ms.

### 5.4 Decomposition — `latency_by_kind` and the finer view

- `RunMetrics.latency_by_kind_ms` (`schema.py:310`, `runner.py:731-738`) is a **run-level sum** over four
  buckets (`llm_ms`, `retrieval_ms`, `tool_ms`, `store_ms`). Use it for the headline decomposition table
  and to show `llm_ms` is unchanged by Wave 1.
- For everything else use `perf/decompose.py`'s per-turn, per-kind CSV — it has the nine buckets that
  matter here (`retrieval_embed`, `retrieval_search`, `tool_wire`, `tool_body`, `guardrail`,
  `store_open_roundtrip`, `residual_python`, `llm_ms`, `llm_limiter_wait`) and is the only view that
  separates the limiter.
- **Caution:** `turns.tool_ms` and `turns.retrieval_ms` are **sums of span durations**, so they do not
  fall when work is overlapped — only when it is removed. W1-B's embed saving *does* show there; a
  parallelism lever would not.

### 5.5 Re-baseline on HEAD before measuring anything

Both committed baselines carry `git_sha: "dev"` and predate `6d3450e`, `3b68ae8`, `af95de4`, `679f35b` —
which changed the router prompt, the `pto_request` predicate, **added the `SEARCH_BREADTH` reminder and
the `G1_RECOVERY` step**, and changed what G1 counts. `CHANGELOG.md` says nudge rate "rises by design".
W2-A rewrites the act rule that governs when the agent stops gathering, against a nudge set that has
never been measured. **Run `before` on HEAD first**, or every acceptance criterion has no valid referent.

### 5.6 Per-lever deterministic gates (the actual proofs)

These are span-level, n-independent, and pass or fail cleanly:

| Lever | Gate |
|---|---|
| W1-A | `SUM(limiter_wait_ms) = 0` over the run's `llm_call` spans (100,551 ms today) **and** `SUM(provider_failover) = SUM(retry_count) = 0`, every span `model = claude-haiku-4-5` |
| W1-B | every backfilled `retrieval` span's `embed_ms` collapses from the ~679 ms two-embed band into the ~340–390 ms single-embed band; per-turn `retrieval_embed` p50 577.5 → ~289; **plus** the 28-span offline replay (rank/`chunk_id`/`dense_score`/`rrf_score`/`bm25_rank`/backfill flags identical, 28/28) run pre-merge |
| W1-C | `/health` pipeline counter: store round trips per turn p50 **8 → 2**; `residual_python` p50 370.5 → ~280 ms; `store_open_roundtrip` p50 22 → 0; counter == `SELECT COUNT(*) … kind='llm_call'` after the sweep |
| W2-A | median `completion_tokens` of **terminal** zero-tool-call act spans 178.5 → ≤ 40, their median duration 3,232 → ≤ 1,400 ms; act steps/turn median unchanged at 2.0 |
| W2-B | median synthesize `completion_tokens` 390 → ≤ 370; zero `finish_reason == "max_tokens"` |
| W2-C | act steps whose only tool is `get_policy_section` fall 10 → ≤ 6; zero act message containing an unbannered G4 pattern hit |
| W2-D | median synthesize `prompt_tokens` 4,415 → ≤ 3,400; act step-2 `prompt_tokens` 4,069 → ≤ 3,800 |
| W2-E | `ttfb_ms < duration_ms` on every `llm_call` span (equal on all 185 today); browser timestamp of first `answer_delta` vs `turn_completed` |

### 5.7 The noise floor — state it beside every result

Identical code, identical `dataset_sha`, two runs (`r_1789032950_baseline` local vs
`r_1789055103_baseline` deployed):

- `latency_p50_ms` **17,670.0 vs 17,584.5** — a −85.5 ms difference, *in the wrong direction*, despite
  a ~750 ms/turn swing in retrieval + tool + store time between the two hosts.
- `latency_p95_ms` **42,430 vs 47,725** — **±5,295 ms**.
- **12 of 26 items moved at least one judged score.** `citation_accuracy_mean` 0.8988 → 0.8475
  (−5.13 pts). `strict_pass_rate` 0.6538 → 0.6923. `unsafe-001` flipped
  `awaiting_confirmation → answered` with `workflow` and `behavior` both 1.0 → 0.0.
- Per-call: synthesize RMSE 3,163 ms (n = 17); the SE of its median is ~767 ms.

**Consequences.** (a) Any single-lever p50 claim under ~800 ms is unfalsifiable by one sweep — rely on
§5.6. (b) Any judged-metric movement inside ±1 item / ±3.8 pp / ±0.06 `citation_accuracy` is re-run
noise and must be reported as such, never as a lever effect. (c) Publish `before` and `after` from the
**same** measurement session.

---

## 6. Rejected levers

| Lever | Claimed p50/p95 | Verdicts | Why rejected |
|---|---|---|---|
| **Forced tool call instead of `output_config`** (route/synth/repair) | 5,147 / 7,521 → verified 2,800 / 6,500 | latency **keep_wc**, quality **reject** | **The largest lever in the whole plan, and it is one probe away from being live.** The 11.22 ms/output-token measurement was taken on a **non-strict** forced tool — i.e. the configuration that *removes* provider-side schema enforcement from `RouteDecision`, `AnswerSchema` and `ToolCallRepair`. The safe configuration (`strict: true`) is unmeasured, and the probe's own control shows constrained decoding at 24.93 vs 10.89 ms/token. The failure path is a gate bypass, not a degradation: a parse failure → `fallback_decision(intent="workflow")` → §9.2's tool gate **off** and `out_of_scope`/`sensitive`/`needs_clarification` cleared. Also introduces a silent-empty-answer path (`json.dumps({})` parses fine; `AnswerSchema(blocks=[])` validates; `outcome="answered"` with zero citations). **See uncertainty #1 — a ~$0.11 / 90-second probe decides it.** |
| Fold the router into act step 1 | 1,758 / 2,976 → verified 1,150 / 1,450 | latency **keep_wc**, quality **reject** | Same enforcement loss on `RouteDecision`, on the *most deterministic* part of the pipeline (identical intent on 26/26 items across two hosts). Both `cit_resolve` zeros (`equipment-001`, `remote-003`) are already router-gate failures. `tests/e2e/test_rag_only_makes_no_people_calls.py:56-58` fails outright. Decode priced at a coefficient (6.62 ms/tok) that appears nowhere in the evidence. |
| Terminal act step emits the answer; skip `synthesize` | 5,482 / 10,711 → verified 4,800 / 9,400 | latency **keep_wc**, quality **reject** | **Not buildable as written**: `act.j2` renders once, before any retrieval, so the CITATION COVERAGE index the change must move has nowhere to go. Silently kills all three §9.3 reminders (`emit_answer` is a `tool_use`, so `completion.tool_calls` is truthy and the nudge branch is dead) — and 4 of 18 act-loop turns acquire documents **only** from later steps. Bypasses G4 for chunks retrieved in the same step. *Safer substitute worth carrying forward:* keep `synthesize` and keep `output_config`, delete only the terminal "I have what I need" step by exiting the loop as soon as G1 passes — worth the observed 2,548 ms p50 / 6,751 ms p90 at near-zero grading risk. **Unverified; propose it as its own lever.** |
| Nudge pre-emption (workflow debt in the act prompt) | 0 / 7,533 → verified 0 / 2,500 | latency **keep_wc**, quality **reject** | p50 = 0 by construction. p95 not reconstructible: −5,617 ms deployed vs −518 ms local for identical behaviour, bootstrap `P(Δ≈0) = 24 %`. At step 0 `debts()` returns the **whole end state** (including "three distinct policy documents"), which §9.1 forbids a reminder from naming; it speaks to exactly the 3 items that carry `workflow_completion_by_workflow`. |
| Speculative retrieval overlapped with the route call | 350 / 0 | **both reject** | Saves 0 ms as written — `act.j2` has no evidence channel, so merged chunks never reach the act model and it still issues its own search. The variant that *does* save requires answering a `tool_use` the model did not make: 0 of 14 first-act searches used the raw user message as the query and 14 of 14 passed a `topic` hard filter. It is a retrieval-quality change in a latency costume; it also flips two refusals to answers. |
| Parallel tool calls within an act step (+ per-thread index conn) | 414 / 1,438 | **both reject** | Measured: serial 4 embeds = 232 ms wall / 232 ms CPU; gathered = 73 ms wall / **278 ms CPU**. Embedding is 100 % CPU-bound with zero I/O to overlap; under a 0.1-CPU CFS quota wall ≈ CPU/quota, so gathering is ~20 % *slower*. `deps.lock` is one process-wide RLock that the "lock-free" people tools also take via `deps.dataset()`. Shared-connection variant produced 6/120 **silently wrong** hit lists. |
| Delete the store round trips (standalone) | 121 / 148 | latency **reject** | Two of three components sit outside `turns.duration_ms` by construction. **Content subsumed by W1-C**, which keeps the in-metric half and drops the rest. |
| Prompt caching above the 4,096-token floor | 0 (self-declared) | **both reject** | Honest headline, unbuildable change. Measured with `count_tokens`: the corpus index is **110 tokens**, not ~470, so the 9-tool act prefix reaches 3,748 — still **348 below** the floor. Writes no cache entry; costs +$0.09/month instead of saving $1.10. Independently: cached input costs the same wall clock as uncached (paired A/B, median Δttft +6.2 ms). |
| int8-quantized bge-small ONNX | 137 / 603 | **both reject** | The 1.5× speedup is a literature band, never measured; `onnx` is not installed, so the gate is unreachable here. Amdahl: only 86.1 % of the span is quantizable, and dynamic quantization adds 324 `DynamicQuantizeLinear` passes. Moves every vector under a G1 gate calibrated on a **0.0383-wide** cosine gap, with `min_evidence_score` re-calibration unreproducible (the probe set is committed nowhere). |
| External keep-alive pinger | 0 / 0 | latency **reject** | 0 ms on the metric (all rows `cold=0`). See W3-B — surfaced as an owner decision. |
| `asyncio.gather` the tool calls of one act step | 43.5 / 165.7 | **both reject** | Self-refuting: the lever computes 7,025 → 509 ms lock-aware, then books 43.5/165.7 against the 0.1-CPU instance anyway. The residual is 100 % loopback wire in the **same process** — pure CPU on the same quota. Its one mandated mitigation (absorb in call order) cannot fix span order: `_absorb` never writes a span; `tool_call`/`retrieval` spans are written inside `client.call_tool`, so `spans.seq` becomes completion order — which `test_demo_tasks.py`'s `precedence_edges` (RUBRIC5.3's evidence) and `deterministic.py:594`'s `confirmation.seq < span.seq` both read. |
| Paid CPU tier | 985 / 1,723 → verified 450 / 1,200 | latency **keep_wc**, quality **reject** | See W3-A — surfaced as an owner decision at **$7/month**. |

---

## 7. Top uncertainties

1. **The `strict: true` decode rate is unmeasured, and it is worth more than this entire plan.**
   A 90-second, ~$0.11 probe (extend `perfplan/probe/probe2.py`: same prefix, 390 output tokens, forced
   `emit_answer` tool **with** `strict: true`) settles the single largest rejected lever. If it decodes
   near 11 ms/token, the `output_config` → strict-tool swap returns ~2,800 ms p50 / ~6,500 ms p95 with
   provider-side enforcement intact, and it should be re-proposed as Wave 2½ ahead of everything except
   W2-A. If it decodes near 24, the structured-output surcharge is simply the price of §7.3's typed
   answers and the matter is closed. **Run this before starting Wave 2.**

2. **Both measured baselines are stale relative to HEAD.** `af95de4` added `SEARCH_BREADTH` and
   `G1_RECOVERY` after both runs. On HEAD, 12 of 18 act-loop turns had ≤ 1 search and no other reminder,
   so their closing act message stops being dead text — which is W2-A's entire mechanism. W2-A's
   1,450 ms could be materially smaller on HEAD, and its acceptance criteria have no valid referent
   until the re-baseline lands.

3. **p95 is one order statistic at n = 26 and is not a stable estimate.** ±5,295 ms between two runs of
   identical code; drop-one jackknife on a single lever swings `d_p50` 3.4×. Every p95 figure in this
   plan should be read as a band, and the p95 target should be set on the paired per-item distribution,
   not on the quantile.

4. **The store-RTT unit price is a 3× band.** W1-C prices each removed round trip at the measured
   22 ms `turns.store_ms`, but that is a **3-statement write batch** including a replicated
   BEGIN/COMMIT; the measured *gap* before each `llm_call` (net of limiter) is only 3.8–6.8 ms, and a
   Turso probe puts the query itself at ~1.8 ms. W1-C is therefore somewhere in **[40, 140] ms** at p50.
   It ships for the event-loop-blocking fix regardless (a synchronous `httpx` POST on the single uvicorn
   worker head-of-line-blocks any concurrent request — invisible to a serial harness).

5. **W2-A's saving is prompt-compliance-dependent and two-sided.** The model may comply and shorten
   (+1,450 ms), keep drafting (0 ms), or keep calling tools instead of stopping (**−2,192 ms**, one extra
   act step). At n = 3 nudged turns the effect on `workflow_completion` is unmeasurable in this suite;
   treat any *rise* in completion rate as suspect and read the per-item answer-quality scores instead.

6. **W2-C's drop rate is the difference between 400 ms and 0 ms.** 10 of 14 `get_policy_section` calls
   pass `include_neighbors=true` and 45.2 % of section bytes are neighbour bytes a search hit cannot
   supply; `onboarding-001` fetches heading paths no search returned. The retargeted rule 6 is expected
   to remove ~4 of 10 steps. If the model keeps calling the tool at today's rate, W2-C is 0 ms and the
   added prefill is paid anyway.

7. **There is no quality headroom, and the re-run itself spends some.** Two of RUBRIC5.1's three
   thresholds already fail, and the measured re-run churn is 12 of 26 items and −5.13 pts of
   `citation_accuracy_mean` for *identical code*. A Wave 2 sweep that comes back slightly worse may be
   the lever or may be the dice; only the per-item gates in §5.6 and the named-item watch list can tell
   them apart, and only if W2-A/B/C ship in separate sweeps.

8. **`ttfb_ms == duration_ms` on all 185 spans.** Every ms-per-output-token figure underpinning W2-A,
   W2-B and the rejected structured-output lever is `total / output_tokens`, silently including prefill
   and queueing. W2-E is the only change that closes this gap — which is an argument for doing it early
   as *instrumentation*, not late as a UX feature.

9. **Ceiling.** After Wave 2, `turns.llm_ms` is ~91 % of the remaining p50 and ~93 % of the remaining
   p95, and LLM wall time is proven host-independent (`act@local` 2,158 ms vs `act@deployed` 2,192 ms at
   identical token distributions; `synthesize@local` is *slower*). **Nothing outside the model can go
   materially further.** The only remaining large levers are call-count reduction and the
   structured-output surcharge — i.e. the two families this review rejected on quality grounds, both of
   which hinge on uncertainty #1.
