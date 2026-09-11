# P14 report — final fix wave (carry-forwards + performance Wave 1)

Branch `main`. Two commits on top of `98b7678`:

| sha | subject |
|---|---|
| `e1dc630` | `P14(deploy): declare httpx2, and make the smoke's /ready wait accountable` |
| `c53b03d` | `P14(final-fix-wave): carry-forwards, measured expectations and performance Wave 1` |

`HEAD = c53b03d23f655ee07abbc76da584da498a2eb0fd`. Nothing pushed. `.env` never read, printed or
staged. No live LLM call and no request to the deploy URL. `evaluation/REPORT.md`,
`evaluation/results/*.json` and `latest.json` were left alone — the concurrent sweep owns them, and
`git status` shows them dirty and untracked-new for that reason, not because of anything here.

---

## 1 · What landed, item by item

### Item 1 — Gemini price table

`src/hrmosaic/core/models.py`: `MODEL_PRICES["gemini-3.5-flash-lite"]` goes from
`{input 0.0, output 0.0, …}` to `{input 0.30, output 2.50, cache_write 0.0, cache_read 0.0}`.

Both cache buckets are 0.0 with the reason in the comment, per the brief's conditional: the
OpenAI-compatible adapter never asks for Gemini context caching, and
`openai_compat.py:224-234` reads only `prompt_tokens` and `completion_tokens` off `usage` — there is
no code path on which a Gemini call can bill a cache write or a cache read.

The REPORT.md note went into the **generator** (`evaluation/runner.py`'s new `JUDGE_COST_NOTE`,
rendered inside `## Judge methodology`), not into the committed `evaluation/REPORT.md`, which the
sweep owns and which the publish step regenerates. It states that judge spans recorded before
2026-09-10 carry `cost_usd_estimate = $0` because cost is priced at write time, and gives the pass
cost from the token counts: **≈ $0.16 = 369k × $0.30/1M + 20k × $2.50/1M**.

### Item 2 — LLM rate limiter: document the service override, keep the code default

The six committed statements of "10" that the performance plan enumerates now carry the deployed
configuration beside the default:

| file | what changed |
|---|---|
| spec §9.4 | new paragraph after the token-bucket one: default 10, deployed service 60/30 (2026-09-10, Render API), the account's 10,000 RPM / 10M ITPM read from response headers, the sweep's 3.9 s/turn mean bucket wait at 10 (p90 12.2 s), spend bounded by `LLM_DAILY_CALL_CAP` |
| spec §12.3 env table | the `LLM_RPM` and `LLM_BURST` rows name the deployed 60 / 30 |
| `design-and-evaluation.md:435` ff | same paragraph, shortened |
| `deployed.md:298` | the judge-limiter sentence now distinguishes the harness's 10 from the service's 60/30 |
| `docs/architecture.html:1561` | "Pacing and spend" |
| `docs/architecture.html:1660` | "Limiter" |

The regenerated `evaluation/REPORT.md` is the publish step's, as the brief says; untouched.

**W1-A provenance fix.** `RunConfig.llm_rpm` is read from the harness's settings
(`runner.py:904`), so a run driven against a remote target now appends `REMOTE_RATE_NOTE` to
`Runner.notes` → `RunFile.notes` → `eval_runs.notes`. It says `config.llm_rpm` is the harness's rate
and records the target's effective rate as `unknown; service env`.

**W1-A publish gate.** `evaluation.runner.contamination_findings(run, store=…)` reads the `llm_call`
spans of the run's *own item turns* and returns one line per cause: any `provider_failover`, any
`retry_count > 0`, or any `model` other than `run.config.llm_model`. `rewrite_report()` — the
`--report` publish path — raises `SystemExit` listing them before it writes anything. Judge spans
hang off the synthetic `eval_judge` session, never off an item turn, so the judge's Gemini model
cannot trip the pin check. `--report`'s argparse help says the gate exists.

### Item 3 — P11c minors (commit `e1dc630`)

- **m1** `test_a_smoke_whose_ready_never_greens_exits_1_and_says_why` drives `smoke_deployed.main()`
  with `--ready-timeout 0` against a `/health`-then-503 fake and asserts exit 1, the endpoint's own
  `reason` on stderr, and the `/ready: never green` line on stdout. It passed on first run — the
  wiring was already right; what was missing was the assertion that it is.
- **m2** `ready_timeout_default()` now prints one `WARN — …` line on stderr for an unparseable
  `SMOKE_READY_TIMEOUT_S` before falling back. An **unset** variable warns about nothing (a separate
  test pins that), which is why the `KeyError`/`ValueError` tuple had to be split.
- **m3** `httpx2==2.12.0` is a direct dependency in `pyproject.toml` (`agent/client.py:45` imports
  it at module level). `requirements.txt` regenerated with the exact committed command
  `uv pip compile pyproject.toml -o requirements.txt`; the diff is one line — `httpx2`'s `# via`
  block gains `hrmosaic (pyproject.toml)`.

### Item 4 — P13 carry-forwards

- **p1 was already implemented at `b24ad32`** and is not re-landed. `orchestrator.py` carries both
  `SEARCH_BREADTH` ("…you have searched the corpus once.") and `SEARCH_BREADTH_UNSEARCHED`
  ("…you have not searched the corpus yet."), sharing one `_BREADTH_DEBT` string, and
  `tests/unit/test_agent_nudge.py:583,721,732-750` tests both wordings and the shared debt. Verified
  by reading and by running that file; no change was needed.
- **p2** `Orchestrator._absorb_async` is the new async boundary. For a `check_policy_compliance`
  result it resolves the engine's candidate chunks (`_engine_evidence_rows`, split out of
  `_engine_evidence`) and runs `score_chunk_ids` under `asyncio.to_thread`, then hands the scores to
  the unchanged synchronous `_absorb`/`_engine_evidence`. The two coroutine call sites (`_act`'s
  tool loop, and the post-confirmation resume) now `await` it; the **rehydrate** path
  (`orchestrator.py:1544`) keeps the synchronous call, because it has no loop to block, and so do
  the unit call sites — as the brief required.

### Item 5 — §14.4 expectations table

The "Warm turn | **~1.5–5 s** (≥ 90 % provider time)" row is replaced with **22.5 s** on the free
instance (cold-start probe, 2026-09-10) and **turn p50 17.6 s** on both the local and the deployed
26-item runs, plus a paragraph naming the provenance: the old range came from `StubAdapter` turns
whose mean was **292 ms**, so it described the harness. The "≥ 90 % provider time" share is kept and
sourced (88.9 % of the deployed median turn), with the note that part of the published p50 is eval
harness limiter pacing (§9.4). `deployed.md`'s cold-start section is untouched.

### Item 6 — Performance Wave 1

**W1-B — query-vector memo.** In `rag/embed.py` only:
`_embed_query_cached(model, convention, embed_dim, text)` under
`functools.lru_cache(maxsize=16)`; `embed_query` returns `list(...)` of it; `clear_query_cache()`
and `query_cache_hits()` exposed. `embed_dim` is in the key because `model_name()` collapses every
fake configuration onto `fake-hash-384` while `_fake_embed` reads `settings.embed_dim`. The fastembed
call stays literally inside `rag/embed.py`, so `tests/architecture/test_conventions.py`'s grep is
unaffected (it passes). Measurement hook: `RetrievalResult.embed_cache_hit` →
`RetrievalPayload.embed_cache_hit` (defaulted, so old rows still parse). It is stamped on the
**span** only — `SearchOutput` is bytes the model reads and was deliberately not touched.

**W1-C(a) — daily cap as a fast negative.** `DailyCallCounter` in `core/llm/limiter.py`, one
process-wide instance behind `daily_calls()`. `RecordingAdapter._check_daily_cap` consults it first;
it returns `True` only when the provider has been seeded this UTC day, the seed is fresher than
`RESEED_EVERY = 100` calls, and its own count is under the cap. Every other answer falls through to
`count_calls_today`, seeds from it, and raises `DailyCapExceeded` from **that** number.
`record_llm_call` — the single writer of `llm_call` spans, cache-hit and total-failure paths
included — increments it, keyed on `completion.provider`, never `self.provider`.
`/health.llm.agent.calls_today` still calls `count_calls_today` unchanged. The reasoning for why
§9.8's "no second counter to drift" stays literally true is in the class docstring, as the brief
asked.

**W1-C(c) — rollups from the buffer.** `TurnBuffer.close()` builds a `totals` mapping once,
publishes it as `self.close_totals`, and the `TURN_CLOSE` statement is built *from that mapping* —
so the response and the audit row are the same numbers by construction, not by promise.
`Orchestrator._rollups` reads `close_totals` instead of re-SELECTing `turns`.

**Not implemented, by instruction:** W1-C(b) (deferred) and W1-C(d) (rejected); nothing from Wave 2
or Wave 3.

---

## 2 · TDD evidence

Every behavioural change was written test-first and watched fail. The failures, as recorded during
the run:

**Item 1** — `tests/unit/test_models.py::test_the_judge_model_is_priced_at_the_paid_standard_rates`

```
E       AssertionError: the free-tier $0 entry is no longer true
E       assert (0.0 > 0.0)
tests/unit/test_models.py:175: AssertionError
1 failed, 3 passed, 12 deselected in 0.04s
```

**Item 1 (report note)** — `test_the_judge_section_says_the_recorded_judge_cost_is_zero_and_prices_the_pass`

```
E       AssertionError: a reader must be told the recorded judge spans carry no cost
E       assert '$0' in '\n\nThe judge is **—** on `JUDGE_API_KEY`, …'
1 failed, 5 passed in 0.73s
```

**Item 2** — `tests/unit/test_publish_gate.py`, all nine red before the runner change:

```
FAILED tests/unit/test_publish_gate.py::test_a_clean_run_has_no_findings
FAILED tests/unit/test_publish_gate.py::test_a_failover_invalidates_the_run
FAILED tests/unit/test_publish_gate.py::test_a_retry_invalidates_the_run
FAILED tests/unit/test_publish_gate.py::test_a_model_other_than_the_pinned_one_invalidates_the_run
FAILED tests/unit/test_publish_gate.py::test_a_run_whose_spans_are_not_in_this_store_is_not_checkable_and_says_nothing
FAILED tests/unit/test_publish_gate.py::test_report_refuses_to_publish_a_contaminated_run
FAILED tests/unit/test_publish_gate.py::test_report_publishes_a_clean_run
FAILED tests/unit/test_publish_gate.py::test_a_deployed_run_records_that_its_llm_rpm_is_the_harnesss
FAILED tests/unit/test_publish_gate.py::test_a_local_run_records_no_such_caveat_because_the_harness_is_the_target
9 failed in 0.87s
```

**Item 3 (m2)** — `test_a_ready_timeout_that_is_not_a_number_warns_before_it_falls_back`

```
E       AssertionError:
E       assert 0 == 1
E        +  where 0 = len([])
1 failed, 38 passed in 0.07s
```

(m1's test passed on first run; that is the finding — the wiring was correct and simply unasserted.)

**Item 4 p2** — `tests/unit/test_compliance_evidence_is_scored.py`

```
E           AttributeError: 'Orchestrator' object has no attribute '_absorb_async'
2 failed, 6 passed in 1.43s
```

**Item 6 W1-B** — `tests/unit/test_query_vector_memo.py`

```
E       AttributeError: module 'hrmosaic.rag.embed' has no attribute 'clear_query_cache'
7 errors in 0.04s
```

and, for the measurement hook, after the memo landed:

```
E       pydantic_core._pydantic_core.ValidationError: … (RetrievalPayload had no embed_cache_hit)
2 failed, 8 passed in 0.17s
```

**Item 6 W1-C(a)** — `tests/unit/test_daily_cap_fast_negative.py`

```
E   ImportError: cannot import name 'DailyCallCounter' from 'hrmosaic.core.llm.limiter'
1 error in 0.67s
```

**Item 6 W1-C(c)** — `tests/unit/test_turn_rollups_from_buffer.py`

```
E       assert (Usage(prompt_...retrievals=99) == Usage(prompt_... retrievals=1)
2 failed in 1.02s
```

(the second test's red is the point: the response was reading the corrupted `turns` row.)

---

## 3 · Definition of done — real output

**`.venv/bin/ruff check .`**

```
All checks passed!
```

**`.venv/bin/ruff format --check .`**

```
225 files already formatted
```

**`.venv/bin/pytest -q`**

```
........................................................................ [ 86%]
........................................................................ [ 90%]
........................................................................ [ 94%]
........................................................................ [ 99%]
.................                                                        [100%]
1745 passed in 147.17s (0:02:27)
```

Pristine — no warnings, no skips, no xfails.

**Test count.** The brief's baseline is "1,703 at `b24ad32`". Measured directly: a detached worktree
at `98b7678` (this branch's parent; the two intervening commits are docs-only) collects **1,708**,
and the tree here collects **1,744** — exactly the 36 tests added, before the one added during
self-review (§5), which brings the run to 1,745. The +5 against the brief's figure predates this
phase; it is not something P14 introduced.

**`.venv/bin/python scripts/check_facts.py`**

```
  travel-policy                      md     12 sections
  workplace-conduct                  pdf    13 sections

14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
```
exit 0

**`.venv/bin/python scripts/pii_check.py`**

```
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
```
exit 0

**`.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest`**

```
  txt          1      19     2624
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
```
exit 0

---

## 4 · Files changed

**Source**

- `src/hrmosaic/core/models.py` — Gemini paid rates + comment; `RetrievalPayload.embed_cache_hit`.
- `src/hrmosaic/core/llm/limiter.py` — `RESEED_EVERY`, `DailyCallCounter`, `daily_calls()`.
- `src/hrmosaic/core/llm/base.py` — `_check_daily_cap` consults the counter first and seeds from the
  SQL; `record_llm_call` increments it on `completion.provider`.
- `src/hrmosaic/core/trace.py` — `TurnBuffer.close_totals`; `TURN_CLOSE` built from that mapping.
- `src/hrmosaic/agent/orchestrator.py` — `_absorb_async`, `_engine_evidence_rows`, optional
  `engine_scores`/`scores`; `_rollups` reads `close_totals`.
- `src/hrmosaic/rag/embed.py` — `QUERY_CACHE_SIZE`, `_embed_query_cached`, `clear_query_cache`,
  `query_cache_hits`, `embed_query` returns a copy.
- `src/hrmosaic/rag/retrieve.py` — `RetrievalResult.embed_cache_hit`, stamped in `retrieve()`.
- `src/hrmosaic/mcpserver/tools/search_policy_documents.py` — `embed_cache_hit` on the span payload
  (either pass), not on `SearchOutput`.
- `evaluation/runner.py` — `REMOTE_RATE_NOTE`, `CONTAMINATION_SQL`, `contamination_findings()`, the
  `--report` refusal and its help text, `JUDGE_COST_NOTE` in the judge section.
- `scripts/smoke_deployed.py` — `ready_timeout_default()` warns before falling back.

**Packaging** — `pyproject.toml`, `requirements.txt` (`httpx2==2.12.0`).

**Docs** — `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` (§9.4, §12.3 env rows,
§14.4), `design-and-evaluation.md`, `deployed.md`, `docs/architecture.html`.

**Tests** — new: `tests/unit/test_publish_gate.py`, `test_query_vector_memo.py`,
`test_daily_cap_fast_negative.py`, `test_turn_rollups_from_buffer.py`. Changed:
`tests/conftest.py` (autouse `_empty_process_caches`), `test_models.py`,
`test_report_states_the_target.py`, `test_deploy_health_scripts.py`,
`test_compliance_evidence_is_scored.py`.

---

## 5 · Self-review — what I found and fixed

1. **`DailyCallCounter.record()` could vouch for an unseeded provider.** The first draft incremented
   `_since_seed` unconditionally, so a call recorded by a *capless* adapter (the judge) opened a
   window of trust for that provider, and the first capped call would then skip the authoritative
   count it exists to take. Fixed: `record()` advances `_since_seed` only for a provider that has
   already been seeded, and a new test — `test_a_call_recorded_before_any_seed_does_not_open_a_window_of_trust`
   — pins it. This is the test that takes the suite from 1,744 to 1,745.
2. **A test was going to touch the live trace store.** The two provenance tests constructed a
   `Runner` without a store, which would have opened and migrated `data/runtime/traces.sqlite` —
   the database the concurrent sweep is writing. Both now take the `store` fixture.
3. **The embed-cache reset fixture was too narrow.** The plan says "next to `fake_embedder`"
   (`tests/unit/conftest.py`); I put it at `tests/conftest.py` instead, so the contract and
   integration suites — which also retrieve — cannot leak a vector into a unit test. The same fixture
   resets the daily-call counter, for the identical reason: both are process-wide state that outlives
   a test's store.
4. **`--report`'s help did not mention the gate.** A CLI that can now refuse should say so; one
   sentence added.
5. **A test asserted the wrong thing.** `_absorb_async` returns `_absorb`'s value — the *retrieval*
   chunks — while the engine's evidence lands in `turn.citable()`. The first draft asserted on the
   return value and failed for a reason unrelated to the change; corrected to assert on
   `turn.citable()`, matching the neighbouring tests.
6. **Unused fixture parameter** (`monkeypatch` on a provenance test) removed.
7. Confirmed `get_store` is still used in `orchestrator.py` after `_rollups` stopped calling it
   (three other call sites), so no dead import.
8. Confirmed `RetrievalResult` has exactly one construction site and no positional callers, so
   inserting a field mid-dataclass is safe.

---

## 6 · Ambiguities resolved, and how

1. **The brief says to add a note to `evaluation/REPORT.md`; the environment says that file is
   off-limits.** Resolved by putting the note in the **generator** (`evaluation/runner.py`'s judge
   section), which is where every other sentence of that section lives. The committed report is the
   publish step's to regenerate, exactly as the brief says for item 2's sixth statement of "10".
2. **"§11/§21 env table rows".** The spec's env-var table is §12.3 (`LLM_RPM` / `LLM_BURST` rows);
   §11 and §21 carry no such rows in the current document. I updated §12.3's, which is the table the
   performance plan points at by line number.
3. **Which six statements of "10".** I took the performance plan's own enumeration verbatim (spec
   §9.4, spec env table, `design-and-evaluation.md:435`, `deployed.md:298`,
   `docs/architecture.html` ×2). Spec §9.8 line 1286 also contains "`LLM_RPM` 10" but it is a
   parenthetical cross-reference asserting the *code default*, which has not changed, so it is
   correct as written and was left alone.
4. **"record the target's effective rate (or 'unknown; service env')".** There is no way for the
   harness to read the service's limiter settings — `/health` publishes none — so the note records
   the literal `unknown; service env`, together with the statement that `config.llm_rpm` is the
   harness's number. No new flag or env var was invented for a value nothing can supply.
5. **The publish gate has no override.** The brief asked for a check that "fails a run"; I made it a
   hard `SystemExit` on the `--report` path with no `--allow-contaminated` escape, because an escape
   hatch is exactly the silence the gate exists to prevent. `write_artifacts`' own `write_report`
   call is deliberately *not* gated: it fires mid-sweep for every arm, and the brief scopes the gate
   to the publish path.
6. **`_absorb_async` resolves the engine's chunks twice** (once to score them in a thread, once
   inside `_engine_evidence`). The brief said to move the scoring "without rewriting the unit call
   sites"; threading rows as well as scores through both signatures would have done exactly that
   rewriting. `corpusread.get_chunk` is a handful of indexed reads against ~600 ms of ONNX, so the
   duplication is documented rather than optimised away.
7. **W1-A's numbers.** The plan says `LLM_RPM=20` / `LLM_BURST=12`; the brief says the service was
   actually set to **60/30** on 2026-09-10. The brief is the later fact and is what the docs record.

---

## 7 · Concerns

1. **Fifteen or so places still describe the judge as free-tier / zero cost**, which item 1 has now
   made false. The brief scoped item 1 to the price table and the REPORT note, so I did not sweep
   them; they should be corrected at the publish step. The list:
   `design-and-evaluation.md:475`; `deployed.md:185`, `:193` (the `$0` cost row), `:289`;
   `docs/architecture.html:1561` ("Judge and failover … on the free tier"), `:1774` (`Cost`,
   "zero: the judge runs entirely on the free tier"), `:1785`; spec `:138` (decision 7), `:1260`
   (§9.8 table), `:2227`, `:2297`, `:2787` (R-5), `:2851` (decision 47). The honest replacement is
   small — the judge is now billed, at ≈ $0.16 per 264-call pass — but it touches published cost
   claims and a decision table, which is a publish-step call rather than mine.
2. **The gate cannot check a run whose spans are not in this store.** A committed run file carried
   to another machine, or one whose trace store has since been pruned by §10.5's retention, produces
   no findings and a `WARNING` in the log. That is by design (proving contamination is possible;
   proving its absence from missing rows is not), but a publish step that relies on the gate should
   confirm it actually read spans rather than trusting a silent pass.
3. **The daily cap can now be overshot by up to `RESEED_EVERY` (100) calls on a multi-worker
   deployment**, because the in-process counter sees only its own calls between re-seeds. The single
   Render worker makes this moot today; it is written down in the class docstring, and the plan
   itself specified the re-seed as the bound.
4. **W1-B's saving is not observable in a 26-item run p50.** The plan says so explicitly (bootstrap
   CI [0, 480] ms) and the lever is gated on the span-level invariant instead — `embed_cache_hit` on
   the retrieval span. Anyone reading the next sweep's p50 for a −304 ms step will not find one.
5. **`embed_ms` on `SearchOutput` will move** for the ~23-of-28 spans that backfill, and it is a wire
   field the synthesis prompt carries. The plan's disclosure covers this: it is wall-clock telemetry,
   already nondeterministic run-to-run, and the change moves it *into* the band six deployed spans
   already occupied. No graded field changes.
6. **W1-C(b) is still open.** The turn-open batch remains synchronous on the request path; the plan
   costs it at a `TurnBuffer` constructor and resume-path refactor, and the brief deferred it. The
   Wave 1 arithmetic in the plan counts (a)+(b) together as the in-metric figure, so the measured
   saving from what landed here will be below the plan's −111 ms p50 line.
7. **`web/api.py::_turn_rollups` still re-SELECTs.** It serves the `/chat/confirm` decline path,
   which has no `TurnBuffer` in hand, so W1-C(c) does not apply to it; left unchanged deliberately.

---

# Fix round 1/3 — review findings

Two findings, both **Important**, both closed. One code change, one documentation sweep.

## F1 — the resume path still blocked the loop, and three places said it did not

**The finding.** `_absorb_async`'s docstring, this report's §1 item 4 and
`tests/unit/test_compliance_evidence_is_scored.py`'s section comment all justified leaving
`_absorb` / `_engine_evidence` synchronous with "the **rehydrate** path calls it with no loop to
block". That is false. `_rehydrate` is called from `async def resume_turn` (`orchestrator.py:556`),
which `web/api.py:849`'s `/chat/confirm` handler awaits, and `_rehydrate` calls
`self._engine_evidence(turn, body)` directly — so `score_chunk_ids` → `embed_query` ran its ≈ 0.6 s
ONNX embed on the event loop thread, on exactly the path the comment at `_rehydrate` exists to
serve. The brief's literal target was fixed; the claim about the other caller was wrong.

**Chosen fix: hoist, not annotate.** The finding offered the alternative of correcting the three
statements and disclosing the block. That is the worse answer: it leaves a 0.6 s stall on the confirm
path with no owner. The seam `_absorb_async` opened (`scores=` on `_engine_evidence`, `engine_scores=`
on `_absorb`) already had everything needed to close it.

- **`Orchestrator._rehydrate_scores(turn_id)`** (new, async) is the resume path's async boundary.
  It reads the turn's `tool_call` spans, collects the chunk ids every non-gated
  `check_policy_compliance` body names in its per-requirement `evidence`, and runs `score_chunk_ids`
  under `asyncio.to_thread`. `resume_turn` awaits it and passes the result into `_rehydrate`.
- **`_rehydrate(..., *, scores=None)`** threads that mapping into its `_engine_evidence` call.
  Left `None` — every synchronous call site — it scores for itself, exactly as before.
- **`_cited_evidence_ids(body)`** (new, module-level) is the one reader of the requirement →
  `evidence.chunk_id` walk, shared by `_engine_evidence_rows` and `_rehydrate_scores`, so the two
  cannot drift apart.

**Why a pre-pass is safe.** `_rehydrate_scores` cannot know which ids a later `retrieval` span will
have already supplied, so it collects a **superset** of what `_engine_evidence_rows` resolves during
the walk. `score_chunk_ids` is a per-chunk `1 − cosine_distance` between the query vector and each
chunk's stored embedding (`rag/retrieve.py:88-117`) — no normalisation across the input set — so a
wider input changes no chunk's score, and `_engine_evidence` still admits only the ids it resolves
itself. Cost: one extra indexed read of the same `spans` rows. Span ordering is untouched, so the
edge case where an engine chunk and a retrieval chunk share an id still resolves the way it did.

**The three false statements.** `_absorb_async`'s docstring now names `_rehydrate` as the *other*
caller that runs on a loop and points at its own boundary; the test file's section comment says the
same and names the test that proves it; this report's §1 item 4 is corrected below.

### Covering test — red first

`tests/integration/test_resume_rehydrates_from_the_store.py::test_the_resumed_engine_scoring_does_not_run_on_the_event_loop`
parks an engine-grounded turn at §8.6's gate (the existing `compliance_confirm_resume.json` script,
whose turn never retrieves — so the engine is the only source of evidence), then resumes it with
`retrieve.score_chunk_ids` patched to record `threading.get_ident()`. The fixture was split into an
`an_engine_grounded_park` async context manager so the **resume** happens inside the patch.

Against the pre-fix `turn = self._rehydrate(session_id, buffer)`:

```
        assert scored_on, "the parked turn's engine evidence still has to be scored"
>       assert all(thread != loop_thread for thread in scored_on), "and never on the thread running the loop"
E       AssertionError: and never on the thread running the loop
E       assert False
E        +  where False = all(<generator object ...>)

tests/integration/test_resume_rehydrates_from_the_store.py:416: AssertionError
1 failed in 1.76s
```

The test also asserts `len(scored_on) == 1` — scored once, ahead of the walk — so a regression that
re-scored inside `_rehydrate` fails even if the pre-pass stayed.

## F2 — the judge is billed; the published documents still said it was free

Item 1 made `MODEL_PRICES["gemini-3.5-flash-lite"]` non-zero, and §7 concern 1 of this report
deferred the sweep of the ~15 places that assert the opposite. The brief's preamble is binding —
"the spec is authoritative and must be amended in the same commit where an item changes it" — so the
sweep lands here. Every replacement states the same three facts: the paid standard rates
**$0.30 / $2.50 per 1M tokens**, the **≈ $0.16 per 264-call judge pass** figure from token counts
(369k in / 20k out), and that paid billing was enabled on the judge Cloud project on **2026-09-10**.

| file | what changed |
|---|---|
| `docs/architecture.html:1561` | `Judge and failover` — "on the free tier" removed; the paid rates and the per-pass figure named |
| `docs/architecture.html:1774` | `Model` — trailing ", free tier" dropped; **`Cost`** — "zero: the judge runs entirely on the free tier" → the ≈ $0.16 figure, with the write-time-pricing caveat that makes pre-2026-09-10 spans read $0 |
| `docs/architecture.html:1785` | `Judged metrics` — "against the judge model's free-tier daily quota" → quota then, cost and wall-clock now |
| spec §9.8 allocation table | **Judge** row: "(free tier)" → the paid rates; "Zero cost" → ≈ $0.16 per 264-call pass. **Agent failover** row: "(free)" dropped, with the honest note that `MODEL_PRICES` is keyed on the *model*, so a failover span is priced at the paid rates even though `LLM_FALLBACK_API_KEY` is on its own still-free project — an upper bound on that project's bill |
| spec §9.8, new paragraph | why the recorded cost has a discontinuity: cost is priced at write time, so pre-2026-09-10 judge spans carry $0 and the pass cost is stated from token counts. Both cache buckets 0.0 — the OpenAI-compatible adapter never asks for Gemini context caching |
| spec decision 7 (`:138`) | Version column "free tier" → `$0.30 / $2.50 per MTok`; rationale "Zero cost" → the per-pass figure and the billing date |
| spec decision 47 (`:2851`) | "on the free tier for both … both at zero cost" → the judge project on paid billing, ≈ $0.16 a pass; the independence and no-contention arguments are unchanged, because they never depended on the price |
| spec R-5 (`:2787`) | risk restated as quota **then**, spend **now**; the mitigation's "the free Gemini judge stays well inside its RPD" → rate limits plus the ≈ $0.16 pass cost; "failover to free Gemini" → "failover to Gemini" |
| spec §13.9 (`:2233`) and §14.1 (`:2303`) | the judged-metrics-scoping rationale and `deployed.md`'s `## Cost` description follow the same correction |
| `deployed.md` `## Cost` | the "$0 of infrastructure" paragraph no longer claims a free judge and free failover — infrastructure is still $0, the models are the spend; the judge row is now the ≈ $0.16 figure dated 2026-09-10 instead of "**$0** free tier" |
| `design-and-evaluation.md:475, :957` | the allocation table's judge row, and the same judged-metrics rationale |
| `docs/requirements-traceability.md` PD.4, R7.4, USER.7 | three evidence cells that cited "the free judge, free failover" / "two free Google keys" |
| `evaluation/runner.py:1523` | the generator's `judged_note`, so the regenerated report agrees with the spec rather than contradicting it |

**Not touched, deliberately.** `evaluation/REPORT.md` and `evaluation/results/*` (the concurrent
sweep owns them; the judge cost note is already in the generator from item 1, and `REPORT.md:120-124`
carries it). `CHANGELOG.md:468, :516, :530` and `docs/superpowers/plans/…roadmap.md:638` are dated
historical records of what was true when written. `docs/project-requirements.md` is the assignment
brief. Every remaining "free tier" hit in the tree is about Render, Turso, GitHub Actions, or the
still-documented zero-cost `LLM_PROVIDER=openai_compat` path a grader can run on their own free key
— all still true.

> **Correction (fix round 2, §F3 below).** That last sentence was false when written: the sweep
> above was partial: seventeen further edits across nine files were still needed — including
> `docs/architecture.html:1786`, whose `Judge` key contradicted the `p:` on the line directly above
> it. §F3 finishes the sweep and lists every location.

`docs/architecture.html`'s inline data blocks were re-checked with `node --check` after the edits.

## Correction to §1 item 4 above

The last sentence of item 4's **p2** paragraph read: "the **rehydrate** path (`orchestrator.py:1544`)
keeps the synchronous call, because it has no loop to block". That was wrong — `_rehydrate` runs
inside the awaited `resume_turn`. It now has its own async boundary, `_rehydrate_scores`, described
under F1. The unit call sites are still synchronous, which is the part of that sentence that held.

## Definition of done — real output, after the fixes

**`.venv/bin/ruff check .`**

```
All checks passed!
```

**`.venv/bin/ruff format --check .`**

```
225 files already formatted
```

**Tests covering the amended code**

```
$ .venv/bin/python -m pytest -q tests/integration/test_resume_rehydrates_from_the_store.py \
    tests/unit/test_compliance_evidence_is_scored.py tests/contract/test_docs_completeness.py \
    tests/unit/test_models.py
73 passed in 6.22s
```

**`.venv/bin/pytest -q`**

```
........................................................................ [ 94%]
........................................................................ [ 98%]
..................                                                       [100%]
1746 passed in 148.16s (0:02:28)
```

1,745 → **1,746**: the one new integration test. Pristine — no warnings, no skips, no xfails.

**`.venv/bin/python scripts/check_facts.py`**

```
  travel-policy                      md     12 sections
  workplace-conduct                  pdf    13 sections

14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
```
exit 0

**`.venv/bin/python scripts/pii_check.py`**

```
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
```
exit 0

**`.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest`**

```
  txt          1      19     2624
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
```
exit 0

## Files changed in this round

**Source** — `src/hrmosaic/agent/orchestrator.py` (`_cited_evidence_ids`, `_rehydrate_scores`,
`_rehydrate(scores=)`, `resume_turn`, three docstrings/comments); `evaluation/runner.py`
(`judged_note`).

**Docs** — `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`, `docs/architecture.html`,
`deployed.md`, `design-and-evaluation.md`, `docs/requirements-traceability.md`.

**Tests** — `tests/integration/test_resume_rehydrates_from_the_store.py` (fixture split into
`an_engine_grounded_park`, new off-the-loop test), `tests/unit/test_compliance_evidence_is_scored.py`
(the corrected section comment).

Nothing pushed. `.env` never read, printed or staged. No live LLM call and no request to the deploy
URL. `evaluation/REPORT.md` and `evaluation/results/*` left dirty and unstaged for the sweep.

## Concerns from this round

1. **The failover project's recorded cost is now an upper bound.** `MODEL_PRICES` is keyed on the
   model id, so a `provider_failover` span on `gemini-3.5-flash-lite` prices at the judge's paid
   rates even though `LLM_FALLBACK_API_KEY` lives on a second Cloud project that was not switched to
   paid billing. Stated as an upper bound in §9.8 rather than modelled — per-key pricing would need a
   price table keyed on `(provider, model, key)`, which is more machinery than the truth is worth.
2. **`_rehydrate_scores` reads the `spans` rows a second time.** One indexed read against the ≈ 0.6 s
   of ONNX it takes off the loop. Threading the rows through `_rehydrate`'s signature would have been
   the rewrite of the synchronous call sites the brief's item 4 forbade.
3. **The concurrent sweep's `evaluation/REPORT.md` was generated before `judged_note` changed**, so
   until the publish step regenerates it, `REPORT.md:53` still reads "against a free-tier daily cap"
   while the spec no longer does. That file is the publish step's by the brief's own rule; the
   generator is correct as of this commit.

## F3 — the free→billed sweep, finished (fix round 2)

The round-1 sweep (F2) was partial, and at line granularity it contradicted itself: the commit
rewrote `docs/architecture.html:1785` (the f5-m2 `p:`, now "quota while the judge project was on the
free tier, and cost and wall-clock now that it is billed") and left the very next key,
`:1786`'s `["Judge", … "and free"]`, untouched. The same shape appeared in the spec — §13.9's
:2233-2234 was corrected while :2236 two lines later still budgeted "~260 **free** Gemini judge
calls" — and in `design-and-evaluation.md`, whose :475 allocation row carried the paid rates while
its architecture mermaid at :57 still rendered "(free, OpenAI-compat)".

Round 1's closing claim ("every remaining 'free tier' hit in the tree is about Render, Turso,
GitHub Actions, or the zero-cost `openai_compat` path — all still true") was therefore false when
written. It is now marked with an inline correction pointing here.

The brief's binding rule — "the spec is authoritative and must be amended in the same commit where
an item changes it" — covers the whole spec, not the rows a review happened to cite, so this pass
was driven by a grep over the tree (`-iE "free"` ∩ `gemini|judge|failover|fallback|flash-lite`)
rather than by the finding's list alone. Seventeen edits across nine files — the eight
locations the finding named, plus nine more the grep turned up:

| file:line | before | after |
|---|---|---|
| `docs/architecture.html:408-409` | SVG tile `judge + failover:` / `gemini-3.5-flash-lite (free)` | `judge (paid) + failover (free):` / `gemini-3.5-flash-lite (OpenAI-compat)` — the split the tile could not express before |
| `docs/architecture.html:1786` | f5-m2 `Judge` key "…it scores, and free" | "…it scores; its Cloud project has been on paid billing since 2026-09-10 — $0.30 / $2.50 per MTok, about $0.16 for a 264-call pass" |
| `design-and-evaluation.md:57` | mermaid `LLM` node "(free, OpenAI-compat)" | "(OpenAI-compat — judge billed, failover free)" |
| spec `:91` | the same mermaid node in §2 | same replacement |
| spec `:168` | §3.1 facts-to-read row: free-tier RPM/RPD/TPM "bounds the **judge and the failover path only**" | the free-tier figures bound the **failover path only**; the judge project moved to paid billing on 2026-09-10 and reads its paid-tier limits from the same page |
| spec `:1860` | §21 env table, `JUDGE_PROVIDER` row: "Gemini `gemini-3.5-flash-lite` (free)" | "(paid billing since 2026-09-10 — $0.30 / $2.50 per MTok, §9.8)" |
| spec `:2236-2239` | §13.9 budget: "~260 **free** Gemini judge calls"; "The Gemini RPD/TPM arithmetic … bounds **only the judge and the failover path**" | "~260 **billed** Gemini judge calls (**≈ $0.16** at §9.8's paid rates, from token counts)"; the RPD/TPM sentence is now scoped to the **failover path only**, with the judge bounded by that ≈ $0.16 and the wall clock rather than a daily cap |
| spec `:2293-2294` | render.yaml excerpt comments "# Gemini, free" ×2 | "# Gemini judge — paid billing since 2026-09-10 (§9.8)" and "# Gemini failover — its own Cloud project, still free" |
| spec `:2756` | §19.1 gate 1: "two Google AI Studio keys … (**both free**)" | "(the judge's Cloud project on **paid billing** since 2026-09-10 — ≈ $0.16 a 264-call judge pass; the failover's project still **free**)" |
| spec `:2766` | "so the judge and the agent's failover path never contend for the same **free quota**" | "…never contend for the same quota or bill (the judge's project moved to paid billing on 2026-09-10; the failover's is still free)" |
| `render.yaml:26-27` | the two live comments the spec excerpt mirrors | same two replacements, so the excerpt and the file still agree byte-for-byte in substance |
| `ai-tooling.md:15` | "on two **free** Google AI Studio keys from two Cloud projects" | "on two Google AI Studio keys from two Cloud projects — the judge's project on paid billing since 2026-09-10 (≈ $0.16 a judge pass), the failover's still free" |
| `NEEDS-FROM-USER.md:69` | "never contend for the same **free quota**. All three validated that day." | the quota-or-bill wording, with the 2026-09-10 billing change named and the validation date spelled out |
| `NEEDS-FROM-USER.md:227` | "Gemini **free-tier** judge quotas" (a row in the still-needs-a-session table) | "Gemini rate limits and billing state for the two Cloud projects (judge: paid since 2026-09-10; failover: free)" |
| `evaluation/judges.py:41-46` | the `JUDGE_RPM` rationale ended "The default leaves headroom under the free tier's published limit; raise it with `JUDGE_RPM` on a paid key" — advice that had already been overtaken | the 2026-09-10 incident narrative is kept (both projects *were* free that afternoon); the live-tense clause now says the judge's project moved to paid billing later that day and the default stays 10 because the paid-tier per-minute limit has not been read (§3.1) |
| `src/hrmosaic/core/llm/openai_compat.py:76` | class docstring "Defaults to the **free** Gemini model of §9.8" | "Defaults to the Gemini model of §9.8" — the adapter has no business asserting a price |
| `deployed.md:291` | unverified-facts row "Gemini free-tier limits **for the judge model**" | "…for `gemini-3.5-flash-lite` — since 2026-09-10 these bound the **failover** project only, the judge's project being on paid billing". The row's body (the rate-limit page no longer publishing a table, the unverified 15 RPM / 250k TPM / 1k RPD figure) and its 2026-09-09 read date are unchanged; only the scope of the fact moved |

**Still not touched, and why.** `CHANGELOG.md:468, :516, :530, :627, :639, :729` and
`ai-tooling.md:117-118` are dated narrative of what was true when written — the judge project
*did* hit a free daily cap mid-evaluation on 2026-09-10, which is the event that led to billing
being enabled. `docs/superpowers/plans/*.md` (roadmap `:638`, performance plan `:531`) are
point-in-time plans, not the authoritative description of the system. `ai-tooling.md:123` and
spec `:1309`, `:1277` describe the **failover** path and the zero-cost `LLM_PROVIDER=openai_compat`
agent path, both still genuinely free. `tests/unit/test_model_allocation.py::test_the_failover_is_the_free_gemini_path`
asserts only that the failover adapter is the Gemini one — still true, so the name still holds; the
same goes for `core/llm/__init__.py:88`'s "(free Gemini)", which documents `build_fallback_model`.
`tests/unit/test_judge_rate_limiting.py`'s module docstring and `evaluation/runner.py:1152, :1160,
:1894, :2066` are dated accounts of the free-tier era, and `runner.py:1523`'s `judged_note` was
already corrected in round 1.
`evaluation/REPORT.md` and `evaluation/results/*` belong to the sweep running concurrently and were
not staged.

**Verification of the HTML.** `docs/architecture.html`'s two inline `<script>` blocks were extracted
and re-checked with `node --check` (both `OK`), as in round 1; `render.yaml` was re-parsed with
`yaml.safe_load` to prove the comment edits left the three `sync: false` key entries intact.

### Definition of done — real output, after F3

**`.venv/bin/ruff check .`**

```
All checks passed!
```

**`.venv/bin/ruff format --check .`**

```
225 files already formatted
```

**Tests covering the amended code** — the docs/manifest contracts, the deploy manifests
(`render.yaml`), the judge pacing and the adapter whose docstrings moved:

```
$ .venv/bin/python -m pytest -q tests/unit/test_judge_rate_limiting.py \
    tests/unit/test_two_pass_judging.py tests/unit/test_openai_compat_tool_schema.py \
    tests/unit/test_adapter_tool_call_shapes.py tests/unit/test_model_allocation.py \
    tests/contract/test_docs_completeness.py tests/contract/test_deploy_manifests.py
120 passed in 1.66s
```

**`.venv/bin/pytest -q`**

```
........................................................................ [ 94%]
........................................................................ [ 98%]
..................                                                       [100%]
1746 passed in 146.43s (0:02:26)
```

Unchanged at **1,746** — F3 is documentation and comments, so it adds no test and removes none.
Pristine: no warnings, no skips, no xfails.

> A first attempt at this run reported `45 failed`. It was run concurrently with
> `scripts/check_facts.py` and `-m hrmosaic.rag.ingest --verify-manifest`, which rebuild an index and
> contend for the same read-only `data/index/hr_index.sqlite`; the failures were all in
> `tests/unit/test_topic_soft_filter.py` and friends and did not reproduce. Run serially — twice,
> before and after the two comment edits — the suite is green at 1,746 both times. The gate commands
> below were then run one at a time.

**`.venv/bin/python scripts/check_facts.py`**

```
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
```

**`.venv/bin/python scripts/pii_check.py`**

```
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
```

**`.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest`**

```
OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
```

**`node --check` on `docs/architecture.html`'s inline scripts**

```
script blocks: 2
0 OK
1 OK
```

**`render.yaml` re-parsed**

```
[{'key': 'ANTHROPIC_API_KEY', 'sync': False}, {'key': 'JUDGE_API_KEY', 'sync': False}, {'key': 'LLM_FALLBACK_API_KEY', 'sync': False}]
```

**Staged files.** Only the nine this fix touched. `evaluation/REPORT.md`,
`evaluation/results/comparison.json`, `evaluation/results/latest.json` and three new
`evaluation/results/r_*.json` were dirty in the working tree throughout — they belong to the
evaluation sweep running concurrently against the deployed service and were deliberately left
unstaged. `.env` was never read.

---

## Fix round 3 — the free→billed judge sweep's own dependent lines

One Important finding, and it is the same defect class the round-2 finding named: round 2 rewrote a
line and left the line six rows below it quoting the deleted wording.

### F1 — `deployed.md:297-298` misquoted the §13.9 it had just amended (Important)

Round 2 rewrote spec §13.9 (`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md:2237`) to
scope the free-tier Gemini RPD/TPM arithmetic to **the failover path only**, and rewrote
`deployed.md:291` to match. It left `deployed.md:297-298` — six lines below, in the same section —
asserting *"§13.9 is explicit that the Gemini RPD/TPM arithmetic bounds **only the judge and the
failover path**"*: a verbatim quote of the sentence round 2 deleted, contradicting line 291 on the
same page. The paragraph's continuation ("so ≤ 600 judge calls/hour against a reported 15 RPM
ceiling") likewise still reasoned about the judge against a free-tier ceiling that no longer applies
to it.

**`deployed.md`** — the paragraph now says what the amended §13.9 says:

- the **free-tier** RPD/TPM arithmetic bounds **only the failover path**;
- the judge is bounded by the **≈ $0.16 a 264-call pass** (the cost row above it in the same file)
  and the wall clock, since its Cloud project moved to paid billing on **2026-09-10** — not by a
  free daily request cap;
- the agent is bounded by `LLM_DAILY_CALL_CAP` (1,500 Anthropic calls/UTC day) and the prompt cache;
- the failover project is the one still on a free key, exercised only when an Anthropic call fails
  and recorded as `provider_failover` on the span — so the unverified 15 RPM / 1,000 RPD figure sits
  on the one path where it cannot affect a published run;
- the "≤ 600 judge calls/hour against a reported 15 RPM ceiling" clause is **deleted**. The
  `LLM_RPM = 10` code default / `LLM_RPM=60` · `LLM_BURST=30` deployed-override sentence (P14 item 2)
  is kept intact, as is the observed-429 record and the `pending: an authenticated AI Studio session`
  line.

### Two more dependent lines, found by grepping rather than by the cited rows

The finding is about lines left behind, so I re-grepped the tree for every live-tense claim that the
judge is free rather than trusting the cited row. Two survived round 2's sweep:

- **`docs/superpowers/specs/…-hr-agentic-rag-design.md:1302` (§9.8 "Expected spend")** — *"The judge
  and the failover path cost nothing."* Now: the **failover** path costs nothing (its project is
  still on a free key); the **judge** has cost ≈ $0.16 per 264-call pass since 2026-09-10, which the
  under-$10 total already absorbs.
- **`docs/requirements-traceability.md:150` (R9.5)** — *"of which only ~260 are **free** Gemini judge
  calls"*. Now: ~260 Gemini judge calls on a dedicated key, free until 2026-09-10 and ≈ $0.16 a pass
  since.
- **`docs/superpowers/plans/2026-09-10-performance-plan.md:531`** — the Wave-1/2 sweep budget said
  "264 **free** Gemini judge calls". It is a forward-looking budget for sweeps that run *after* the
  billing change, so it is corrected too: 264 billed judge calls at ≈ $0.16 a sweep, three sweeps
  ≈ $1.41 of Haiku + ≈ $0.48 of judge.

**Deliberately not touched.** `CHANGELOG.md:516,530` and
`docs/superpowers/plans/2026-09-08-implementation-roadmap.md:577,638` are dated historical records of
what was true and what was planned *before* 2026-09-10 — rewriting them would falsify the log, not
correct it. `ai-tooling.md:117-118` and `:167` are likewise past-tense narrative ("hit its free daily
cap mid-evaluation") and a role description, both still accurate.

No code changed in this round: the four edits are prose in four documents.

### Covering tests

Documentation-fact tests, all green:

```
$ .venv/bin/python -m pytest -q tests/contract/test_docs_completeness.py tests/contract/test_published_run_commands.py tests/architecture/
....................................................                     [100%]
52 passed in 1.26s
```

### Definition of done — real output

**`.venv/bin/ruff check .`**

```
All checks passed!
```

**`.venv/bin/ruff format --check .`**

```
225 files already formatted
```

**`.venv/bin/python -m pytest -q`**

```
........................................................................ [ 86%]
........................................................................ [ 90%]
........................................................................ [ 94%]
........................................................................ [ 98%]
..................                                                       [100%]
1746 passed in 146.94s (0:02:26)
```

**`.venv/bin/python scripts/check_facts.py`**

```
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
```

**`.venv/bin/python scripts/pii_check.py`**

```
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
```

**`.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest`**

```
OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
```

**Staged files.** Only the four documents this round edited (this report lives under the
git-ignored `.superpowers/`). The concurrent
evaluation sweep's artefacts (`evaluation/REPORT.md`, `evaluation/results/*.json`) stayed dirty and
unstaged, as in the previous rounds. `.env` was never read.
