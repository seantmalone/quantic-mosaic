# P1 report — `core/`: the trace store, built before anything that can log

**Branch** `main` · **base** `64c502e` · **HEAD** `c74af7b7a7254abb44355c9dcb1da9a4aceba0a3`
**Commits**

| sha | subject |
|---|---|
| `8683813` | `P1(core): the Session → Turn → Span trace store, both backends, redaction and retention` |
| `c74af7b` | `P1(core): fix: cover reopen_turn, and never leave a batch transaction open` |

Full suite: **72 passed**, no warnings; `make lint` green. Nothing pushed. `.env` was never read, printed or committed.

---

## 1. What I built

### `src/hrmosaic/core/db.py` — both backends behind one interface (§12.1)
* `execute(sql, params) -> Rows` and `batch(stmts) -> list[Rows]`; `Rows` is a frozen dataclass
  (`columns`, `rows`, `rows_affected`) with `dicts()`, `one()`, `scalar()` and iteration, so an
  equality comparison between backends is meaningful.
* `SqliteStore` — one file, `check_same_thread=False` + an `RLock` (async callers wrap in
  `asyncio.to_thread`, per §2.1), `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, explicit
  `BEGIN`/`COMMIT`/`ROLLBACK` for `batch`.
* `TursoHTTPStore` — real Hrana `POST <db>/v2/pipeline`: typed argument encoding
  (`null|integer|float|text|blob`) and decoding back to Python, `Authorization: Bearer`, and a
  **transactional batch** built as a Hrana `batch` request whose steps are `BEGIN`, each statement
  conditioned `{"type":"ok","step":i-1}`, a `COMMIT` conditioned on the last statement, and a
  `ROLLBACK` conditioned on the commit not having run. That is the construction the libSQL clients
  use, and it makes the end-of-turn flush one atomic round trip as §10.3 requires.
* `pipeline_url()` (`libsql://` → `https://…/v2/pipeline`), `migrate()` (idempotent, numbered,
  recorded in `schema_migrations`), `build_store()` (the §12.1 selection table verbatim, never
  raising — a forced `PERSIST_BACKEND=turso` without credentials logs a warning and falls back to
  SQLite, because boot must always succeed), and a process-wide `get_store()` / `set_store()`.
* `now_micros()` lives here: epoch micros is the unit every §10.1 timestamp column stores.

### `src/hrmosaic/core/migrations/001_initial.sql`
The complete §10.1 schema, copied verbatim from the spec (all eleven tables, all indexes, comments
included), with `sessions.auth_mode` and `sessions.actor_role` `NOT NULL` carrying their `CHECK`
vocabularies so P8 and P9 have the columns they render and filter on. `schema_migrations` itself is
created by the runner before any migration file is applied, so the file has no duplicate DDL.

### `src/hrmosaic/core/trace.py` — the one writer
* **Turn start** — one small batch: session upsert (`ON CONFLICT DO UPDATE` on
  `last_activity_at`), the `turns` insert (`INSERT … SELECT COALESCE(MAX(seq),0)+1 … FROM turns
  WHERE session_id = ?`, so `seq` is allocated inside the same transaction), and a read-back of the
  allocated `seq` — one round trip.
* **In flight** — `TurnBuffer.span(kind, name)` is a context manager giving a `SpanContext`
  (`set_payload`, `add_message`, `set_error`); `add_span(...)` records an already-timed span (what
  P6's adapters will use). Each closed span is redacted, size-controlled, appended to the buffer and
  **published to the listeners immediately**.
* **Turn end** — one batched flush: every span row, every `llm_messages` row, and the closing
  `UPDATE turns` with the rollups (`total_tokens_in/out`, `llm_calls`, `tool_calls`, `retrievals`,
  `guardrail_hits` — guardrail spans whose verdict is not `allow` —, `llm_ms`, `retrieval_ms`,
  `tool_ms`, `store_ms`, `provider`, `model`, `provider_failover`), `outcome`, `stop_reason`,
  `duration_ms` and `rss_mb_at_end` sampled from `procstat.rss_mb()`.
* `register_span_listener(fn) -> unregister`, `clear_span_listeners()`; a listener that raises is
  logged and skipped — persistence and its peers are untouched.
* `reopen_turn(turn_id, awaiting_ms)` — one batch: clear `ended_at`/`outcome`, `resumed_count += 1`,
  `awaiting_ms += …`, then read the turn's rollups back into the new buffer and continue `seq` from
  `MAX(seq)` of the turn's spans, so the second flush accumulates rather than overwrites.
* `install_shutdown_handlers()` (idempotent; SIGTERM/SIGINT chained to the previous handler —
  uvicorn's — plus `atexit`), `flush_open_turns()`, `sweep_stale_turns(older_than_s=300)`,
  `reset_shutdown_handlers()` (the test seam).
* Size control (§10.5): 8 KB per string, 32 KB per payload, 128 KB for `llm_call`;
  `payload_bytes` records the **pre-truncation** size and `truncated` is set honestly.

### `src/hrmosaic/core/models.py`
The nine-member discriminated union on `kind` with every field of the §10.2 table (plus the nested
`ServerInfo`, `DiscoveredTool`, `MessagesRef`, `ProposedToolCall`, `RetrievedChunk`), `extra="forbid"`
throughout, `parse_payload()`; the §7.3 answer view-models (`Citation`, `AnswerBlock` with its
policy-fact-must-cite validator, `AnswerSchema`) and the §11.1 `TraceEntry` projection model — all
with no defaults, as strict mode requires; `strict_json_schema()` (inlines `$defs`, asserts
`required == list(properties)` and `additionalProperties is False` at every level);
`MODEL_PRICES` (`claude-haiku-4-5` = 1.00 / 5.00 / 1.25 / 0.10 per MTok, `gemini-3.5-flash-lite` = 0)
and `estimate_cost_usd()`.

### `src/hrmosaic/core/redact.py`
Key-name denylist `(?i)(api[_-]?key|token|secret|password|authorization|cookie|bearer)`; value
regexes for `sk-ant-…`, `sk-…`, `AIza…`, JWTs and long base64 runs; the exact-match `os.environ`
sweep over every variable whose name ends `_KEY`/`_TOKEN`/`_SECRET`; `PRESERVED_KEYS` exempts the
integer token counts. Returns new objects — it never mutates its input.

### `src/hrmosaic/core/ids.py` · `procstat.py` · `archive.py` · `retention.py`
* `ids.py` — `secrets.token_hex` ids (32-hex session/turn, 16-hex OTel-shaped span),
  `user_agent_hash()` (`sha256[:16]`; raw UAs and IPs are never stored), `SEED = 1729` as a module
  constant with no environment variable anywhere in the module.
* `procstat.py` — `rss_mb()`, `rss_peak_mb()`, `uptime_ms()`, `snapshot()`, `python -m` entrypoint.
  Two sources, and the reading names the one it used (see §4).
* `archive.py` — `import_results()`: skips `latest.json` / `comparison.json` /
  `chunk_size_comparison.json` and anything whose top level lacks both `run_id` and `metrics`;
  skips an unchanged file by `import_state.sha256`; re-imports a changed one, replacing that run's
  `eval_results` rows; never raises (a malformed file is logged and skipped so boot still succeeds).
* `retention.py` — `sweep(store, keep)`: keeps the newest `TRACE_RETENTION_SESSIONS`, never prunes
  an eval-linked, `eval_judge`, `maintenance` or `mock_writes`-owning session, never deletes a
  `confirmations` row a `mock_writes` row references, and cascades children-first
  (`llm_messages` → `spans` → `confirmations` → `turns` → `sessions`).

### Fixtures
* `tests/fixtures/traces/remote_work_eligibility.json` — demo task 1: 9 spans
  (`mcp_discovery`, `llm_call`×2 with their `llm_messages`, `plan`, `tool_call`×2, `retrieval`,
  `guardrail`×2), `outcome: answered`, three resolvable citations across three documents.
* `tests/fixtures/traces/pto_request_confirmed_write.json` — demo task 2: the **complete
  confirmed-write chain** — the `CONFIRMATION_REQUIRED` `tool_call`, the `confirmation` span, the
  reopened turn (`resumed_count: 1`, `awaiting_ms: 25000`), the gated write, plus the
  `confirmations` row (`user_response: confirmed`) and the `mock_writes` row that references it.
  `llm_messages` for every `llm_call` in both files.
* `tests/fixtures/eval_runs/sample_run.json` — a three-item run object for the importer test.

---

## 2. Definition-of-done commands — real output

```text
$ pytest tests/unit/test_store_parity.py -q
.......                                                                  [100%]
7 passed in 0.07s

$ pytest tests/unit/test_g6_redact.py -q
........                                                                 [100%]
8 passed in 0.01s

$ pytest tests/unit/test_span_listener.py tests/unit/test_ids_unique.py -q
...........                                                              [100%]
11 passed in 0.11s

$ pytest tests/unit/test_retention.py tests/unit/test_turn_close_records_rss.py -q
...........                                                              [100%]
11 passed in 0.08s

$ pytest tests/integration/test_results_import.py -q
.......                                                                  [100%]
7 passed in 0.04s

$ pytest tests/integration/test_process_exit_mid_turn.py -q
.....                                                                    [100%]
5 passed in 0.03s

$ pytest tests/architecture/test_conventions.py -q
.....                                                                    [100%]
5 passed in 0.01s

$ python -m hrmosaic.core.procstat
{
  "rss_mb": 18.1,
  "rss_peak_mb": 18.1,
  "source": "resource.getrusage",
  "platform": "darwin",
  "uptime_ms": 0,
  "pid": 6603
}

$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
28 files already formatted

$ make test
.venv/bin/pytest -q
........................................................................ [100%]
72 passed in 0.34s
```

The **Linux/CI** RSS reading the DoD asks to record (also pasted into `CHANGELOG.md` with its date):

```text
$ docker run --rm -v "$PWD/src:/src:ro" -w / -e PYTHONPATH=/src python:3.12-slim \
    python -m hrmosaic.core.procstat            # 2026-09-09
{
  "rss_mb": 16.4,
  "rss_peak_mb": 16.3,
  "source": "/proc/self/status",
  "platform": "linux",
  "uptime_ms": 0,
  "pid": 1
}
```

`python:3.12-slim` is the same base the P11 image uses, so this is the floor the §14.3 budget
(`rss_mb < 420` with the ONNX model resident) is measured from. It is a bare-interpreter reading,
not a container memory gate — the gate itself is P11's, and no Dockerfile exists yet.

---

## 3. TDD evidence

Every test file was written before the module it exercises, and each was watched fail first.

| Test | RED (before the module existed) | GREEN |
|---|---|---|
| `test_store_parity.py` | `TypeError: hrmosaic.settings.Settings() got multiple values for keyword argument 'turso_database_url'` (the six store assertions passed against the just-written `db.py`; the selection test failed and was fixed) | `7 passed` |
| `test_ids_unique.py` | `ImportError: cannot import name 'ids' from 'hrmosaic.core'` | `4 passed` |
| `test_g6_redact.py` | `ModuleNotFoundError: No module named 'hrmosaic.core.redact'` | `8 passed` |
| `test_span_listener.py`, `test_turn_close_records_rss.py`, `test_process_exit_mid_turn.py` | `ImportError while loading conftest … cannot import name 'trace' from 'hrmosaic.core'` | `15 passed` |
| `test_retention.py` | `ImportError: cannot import name 'retention' from 'hrmosaic.core'` | `7 passed` |
| `test_results_import.py` | `ImportError: cannot import name 'archive' from 'hrmosaic.core'` | `7 passed` |

Two RED→GREEN cycles were about the assertion rather than the module, and both changed the *test*
after seeing real behaviour:

* `test_seed_is_a_module_constant_with_no_environment_variable` failed because `"environ"` is a
  substring of `"environment"` in the module docstring — narrowed to `os.environ` / `getenv`.
* `test_turn_close_records_rss_and_the_rollups` asserted `store_ms > 0`; the real measured value on
  a local SQLite file is **0 ms** (the start batch is well under a millisecond). Rather than fake a
  `+1`, `store_ms` now accumulates in microseconds and rounds at close, and the test asserts the
  column is recorded. That is the honest number.

`test_store_parity.py` deliberately does **not** mock the store: the `MockTransport` handler is a
small Hrana server that executes the SQL it receives against a real in-memory SQLite connection and
answers in the real wire shape (typed values, `step_results` / `step_errors`, conditions). Both
backends run the same sixteen-statement sequence — migrate, migrate again, insert, batch, select,
aggregate, join, cast, delete — and the two result lists are compared for equality. **No test ever
contacts a live Turso database.**

---

## 4. Files changed

**Added — `src/hrmosaic/core/`**
`__init__.py` · `db.py` · `migrations/001_initial.sql` · `trace.py` · `models.py` · `redact.py` ·
`ids.py` · `procstat.py` · `archive.py` · `retention.py`

**Added — tests**
`tests/conftest.py` (the migrated-store and writer fixtures) ·
`tests/unit/test_store_parity.py` · `test_g6_redact.py` · `test_ids_unique.py` ·
`test_span_listener.py` · `test_retention.py` · `test_turn_close_records_rss.py` ·
`test_trace_fixtures.py` · `tests/integration/test_results_import.py` ·
`tests/integration/test_process_exit_mid_turn.py`

**Added — fixtures**
`tests/fixtures/traces/remote_work_eligibility.json` ·
`tests/fixtures/traces/pto_request_confirmed_write.json` ·
`tests/fixtures/eval_runs/sample_run.json`

**Modified**
`tests/architecture/test_conventions.py` (one line **extended**, not duplicated: the sole-writer
grep now also asserts `core/trace.py` *does* contain `INSERT INTO spans|turns|sessions`, so a
vacuous pass can never be mistaken for the invariant holding) · `CHANGELOG.md` (the dated RSS
readings and the two-readers note).

No workflow edit — the `test` job already runs `pytest -q` over the whole suite. No settings or
`.env.example` change: P1 introduced no environment variable.

---

## 5. Self-review — what I found and fixed

1. **`reopen_turn` had no test.** It is a named deliverable and P8 is the first phase that would
   otherwise exercise it. Added
   `test_reopening_a_turn_continues_the_span_sequence_and_the_live_rail`: `seq` continues (1,2,3 →
   4), the resumed span reaches the listeners, rollups accumulate across both halves
   (`tool_calls == 2`), `resumed_count == 1`, `awaiting_ms == 25000`. Fixed in `c74af7b`.
2. **`SqliteStore.batch` only rolled back on `sqlite3.Error`.** A non-SQLite exception would have
   left the connection inside a transaction. Now rolls back on any exception and re-raises. `c74af7b`.
3. **A span recorded with no payload** wrote `{"kind": …}`, which cannot be parsed back into the
   §10.2 union. Losing the record would be worse, so the row is still written, but the writer now
   logs a warning naming the span. `c74af7b`.
4. **`store_ms` was faked with `+1`** so a test could assert `> 0`. Replaced with a microsecond
   accumulator and an honest assertion (see §3).
5. **`prepare_payload` had a redundant fast path** that serialised the payload three times; reduced
   to one capping pass plus the shed loop.
6. **`Store` was `@runtime_checkable`** while carrying a data member (`backend`), which makes any
   `isinstance` check raise `TypeError`. Nothing used it; removed the decorator.
7. **YAGNI sweep.** Dropped `last_insert_rowid` from `Rows` (every primary key in §10.1 is TEXT);
   left `confirmations`-minting out of `ids.py` (P5's `confirm.py` mints, P8's `web/` calls it);
   left `corpusread.py` and `core/llm/` to P4 and P6 as the roadmap assigns them.
8. **Test output is pristine**: 72 passed, zero warnings, no stray output; `git status` clean; no
   `.env`, `.venv`, cache, database or scratch file staged.

---

## 6. Ambiguities resolved (simplest reading that satisfies the spec)

1. **Sync store, not async.** §12.1 specifies `execute`/`batch` with no `await`, and §2.1 already
   mandates `asyncio.to_thread` for blocking calls. Both backends are therefore synchronous and
   thread-safe; `web/` will wrap them. Documented in both module docstrings.
2. **Redaction's preserved keys.** §10.4 names *three* integer token counts. Redacting
   `cache_creation_input_tokens` / `cache_read_input_tokens` — same class, same `token` pattern —
   would corrupt two integers the dashboard and `MODEL_PRICES` read, so `PRESERVED_KEYS` holds all
   five. The DoD's three are asserted explicitly; the two cache counters are asserted alongside.
   (This coupling is load-bearing: `trace.py` computes its token rollups from the **redacted**
   payload, so an over-eager denylist would silently zero every turn's token totals.)
3. **An exception inside a span body.** With no payload set, the span is recorded as an `error`
   span (`ErrorPayload.component` naming the kind that broke) rather than as an unparseable
   payload of the original kind. If the caller had already set a payload, the kind and payload are
   kept and only `status`/`error_message` change.
4. **`turns.duration_ms` excludes `awaiting_ms`**, since §10.1 says the parked time is "excluded
   from every latency stat".
5. **`store_ms`** is the store time this module measured for the turn (start batch + reopen),
   rounded to milliseconds; the closing flush's own duration cannot be inside the `UPDATE` it
   writes.
6. **The eval run-file shape.** §10.3 only fixes "top-level `run_id` and `metrics`". `archive.py`
   reads the `eval_runs` columns from the top level (`config` and `metrics` as objects →
   `config_json` / `metrics_json`) plus `items[]` → one `eval_results` row each; the shape is
   documented in the module docstring and instantiated by `tests/fixtures/eval_runs/sample_run.json`,
   which is what P10's `runner.py` must write.
7. **Retention's keep-window** counts *all* sessions (newest N are kept regardless of protection);
   only unprotected sessions outside it are deleted.
8. **The migration is one file** (`001_initial.sql`) carrying the whole §10.1 schema, since the spec
   describes the schema as a single unit and nothing pre-existed it.
9. **`tests/conftest.py`** was added to hold the two fixtures four test files share (a migrated
   `SqliteStore` in `tmp_path` and a `TraceWriter`), rather than duplicating them per file. No test
   touches `data/runtime/traces.sqlite`.
10. **Commit attribution.** The session's standing instruction (which states it replaces earlier
    attribution guidance) names `Co-Authored-By: Claude Opus 5 (1M context)`, while roadmap §2.4
    names `Claude Fable 5.1`. I followed the session instruction; the `Claude-Session:` line and the
    rest of the §2.4 pattern (subject, bullets, `Gate:`, `Reqs:`) are exactly as specified.

---

## 7. Concerns / notes for later phases

* **`TursoHTTPStore` has never met a real Turso database.** The wire shape is implemented from the
  Hrana v2 pipeline protocol and verified against a faithful mock. P11's provisioning is the first
  live exercise; if the deployed `/health.trace_store` reports unreachable, look here first.
  Related: the store does not send `PRAGMA foreign_keys=ON` to Turso (a stateless pipeline
  connection), so foreign-key enforcement is guaranteed locally and not asserted in production.
* **`import_state.path` is the path string as the caller passed it** (relative in production).
  A boot from a different working directory would re-import rather than skip — harmless, but P8
  should call `import_results()` with a stable path.
* **Signal handlers need the main thread.** `install_shutdown_handlers()` logs a warning and relies
  on `atexit` alone when called off it; P8's lifespan should call it on the main thread.
* **`sweep_stale_turns()` and `retention.sweep()` have no scheduler yet** — §10.5 says boot and
  every six hours; that wiring belongs to P8's lifespan.
* **Guardrail rollup semantics**: `turns.guardrail_hits` counts guardrail spans whose verdict is
  not `allow`. Dashboard page 1's KPI is named `guardrail_blocks`; P9 should map it from this
  column rather than recomputing.
* **Docker was used once**, for the Linux RSS reading only — it pulled `python:3.12-slim` and ran
  `procstat` with `src/` mounted read-only. No image was built and no container survives.

---

# P1 fix report — round 1 of 3

Three findings from the P1 task review, all fixed. Every finding was **reproduced first** against
the committed code, then re-run after the fix.

## 1. [Critical] `prepare_payload()` did not enforce the §10.5 cap and recorded `truncated` dishonestly

**Reproduced.** Two escapes in the same loop, exactly as the review described:

```text
$ .venv/bin/python scratchpad/repro.py          # before the fix
nested:   64791 bytes stored | pre-truncation 64791 | truncated=False | cap 32768
siblings: 17112 bytes stored | pre-truncation 60912 | truncated=False | marker present: True
```

* a payload whose bulk sits in a **nested** list (`structured_content.items`) gave
  `_longest_list_key() is None` — it only ever looked at top-level keys — so the loop capped
  strings at 256 and `break`'d **without re-checking the cap**: 64,791 bytes persisted against a
  32,768-byte cap, badged `truncated = 0`;
* a payload of many **small sibling strings** (all already ≤ 8 KB) hit the same `key is None`
  branch, *was* truncated to 17,112 bytes — the `…[truncated]` marker is in the stored JSON — and
  was still recorded `truncated = 0`.

**Fixed** (`src/hrmosaic/core/trace.py`). The loop now only ever exits *under the cap*:

* `_longest_list_key()` is replaced by `_every_list()` / `_shed_longest_list()`, which walk the
  whole payload, so a nested list sheds exactly like a top-level one (and long lists shed a slice
  at a time, so a 4,000-element payload converges in a bounded number of passes rather than 4,000);
* when nothing is left to shed, the per-string cap **halves** — 8 KB → … → `MIN_STRING_BYTES` (64) —
  re-capping an already-capped string at a smaller limit slices the old marker off, so exactly one
  `…[truncated]` survives;
* if even that will not fit, the payload is replaced by the stub
  `{"kind": …, "error_kind": "payload_oversize", "payload_bytes": …}` and a warning is logged;
* `truncated` is no longer a flag maintained by hand inside the loop — it is
  `serialised != original`, computed once at the return, so it cannot disagree with what is stored.

```text
$ .venv/bin/python scratchpad/repro.py          # after the fix
nested:   32067 bytes stored | pre-truncation 64791 | truncated=True | cap 32768
siblings: 32472 bytes stored | pre-truncation 60912 | truncated=True | marker present: True
```

**Covering test — `tests/unit/test_payload_size_control.py` (new, 9 tests).** There was previously
no size-control test anywhere in the suite. It covers each cap and each escape shape:

| test | what it pins |
|---|---|
| `test_a_single_string_field_is_capped_at_8_kb` | the 8 KB per-string cap; exactly one marker; `payload_bytes` is pre-truncation |
| `test_a_string_under_the_cap_is_untouched_and_not_flagged` | no false `truncated` |
| `test_a_nested_list_payload_is_shed_down_to_the_32_kb_cap` | escape (a): nested `structured_content.items` |
| `test_a_payload_of_many_small_sibling_strings_is_capped_and_flagged` | escape (b): no list at all |
| `test_a_payload_that_cannot_fit_becomes_the_oversize_stub` | the last-resort stub |
| `test_an_llm_call_keeps_what_a_default_payload_would_shed` | 128 KB for `llm_call` vs 32 KB default, same payload |
| `test_an_llm_call_over_128_kb_is_shed_to_its_own_cap` | the 128 KB cap is a cap, not a licence |
| `test_the_stored_row_is_under_the_cap_and_badged_truncated` | the actual `spans` row: size, `truncated = 1`, `payload_bytes` pre-truncation |
| `test_a_small_payload_is_stored_whole_and_not_badged` | the untruncated row is honest too |

Note recorded in the test module: `redact()` runs *before* the size control, and a long run of
`[A-Za-z0-9+/]` is a base64-credential shape it replaces wholesale — so `"x" * 60_000` arrives at
the cap as `[REDACTED]`. The fixtures use policy prose, not filler.

The §1 claim in the original report ("`truncated` is set honestly") was false as written; it is
true now, and pinned.

## 2. [Important] `answer_blocks_json` / `citations_json` were persisted unredacted

**Reproduced.** Closing a turn whose `final_answer`, `answer_blocks` and `citations` all carry the
same synthetic `sk-ant-api03-…` value:

```text
$ .venv/bin/python scratchpad/repro3.py         # before the fix
final_answer       clean  | Your key is [REDACTED].
answer_blocks_json LEAKED | [{"type": "recommendation", "text": "Your key is sk-ant-api03-…"}]
citations_json     LEAKED | [{"chunk_id": "c1", "snippet": "leak sk-ant-api03-…"}]
```

**Fixed.** `TurnBuffer.close()` now writes both columns through a new `_dump_redacted_json()`:
serialise (models, lists of models, dicts, strings — the existing `_dump_json` path), then
`redact()` the resulting structure; a value that is prose rather than JSON falls back to
`redact_text()`. §7.3 makes `blocks[].text` the text the UI renders, so this is the same prose as
`final_answer` and §10.4 / §17 require the same scrub.

```text
$ .venv/bin/python scratchpad/repro3.py         # after the fix
final_answer       clean | Your key is [REDACTED].
answer_blocks_json clean | [{"type": "recommendation", "text": "Your key is [REDACTED]."}]
citations_json     clean | [{"chunk_id": "c1", "snippet": "leak [REDACTED]"}]
```

**Covering test** — `test_every_answer_column_of_the_closing_update_is_scrubbed` in
`tests/unit/test_g6_redact.py` (so it runs under the redaction definition-of-done command). It
closes a real turn with a leaked key in `final_answer`, in an `AnswerBlock.text` and in a citation
snippet, and asserts all three columns come back scrubbed — **and** that `citations: ["c_1b7e"]`
survives, so the fix is a scrub and not a blanket erase.

## 3. [Important] `models.py` deliverables had zero test coverage

**Confirmed as missing coverage, not a live defect** — `strict_json_schema(AnswerSchema)` and
`strict_json_schema(Citation)` already succeeded, and `estimate_cost_usd('claude-haiku-4-5',
prompt_tokens=1_000_000) == 1.0` already held. Nothing pinned any of it.

**Added — `tests/unit/test_models.py` (15 tests).**

* `strict_json_schema(AnswerSchema)`: no `$defs`, no surviving `$ref` anywhere in the serialised
  schema, and at **every** object level — including `$.properties.blocks.items`, the level that
  only exists because inlining recursed — `required == list(properties)` and
  `additionalProperties is False`. This is what pins the two invariants P6's constrained-JSON path
  depends on: that Pydantic emits `required` in `properties` order, and that `$defs` inlining
  survives nesting. A Pydantic upgrade that breaks either now fails in P1.
* `strict_json_schema(Citation)`: strict, and its `required` matches `Citation.model_fields`.
* A model carrying a default (`TraceEntry`) raises `ValueError`; a model without `extra='forbid'`
  raises; a **nested** model without `extra='forbid'` raises at its own level.
* The §7.3 `AnswerBlock` contract: `type='policy_fact'` with `citations=[]` raises; a
  `recommendation` may stand uncited; an unknown `type` and an extra field are both rejected;
  `AnswerSchema` round-trips through JSON.
* `parse_payload`: returns the typed union member, rejects an unknown `kind`, rejects an extra field.
* `estimate_cost_usd`: every `MODEL_PRICES` entry billed per bucket per MTok, the pinned agent
  model's four buckets summed, the free judge model, an unpriced model, and a zero-token call.

## Files changed

**Modified** — `src/hrmosaic/core/trace.py` (`MIN_STRING_BYTES`, `_every_list()`,
`_shed_longest_list()`, `prepare_payload()`, `_dump_redacted_json()`, the two `TurnBuffer.close()`
bindings) · `tests/unit/test_g6_redact.py` (one new test + its imports).
**Added** — `tests/unit/test_payload_size_control.py` · `tests/unit/test_models.py`.

No production behaviour outside `core/trace.py` changed; `models.py` was not edited (finding 3 was
coverage, not a defect). No workflow, settings or `.env.example` change. Repro scripts stayed in
the scratchpad.

## Definition-of-done commands — real output

```text
$ pytest tests/unit/test_store_parity.py -q
.......                                                                  [100%]
7 passed in 0.10s

$ pytest tests/unit/test_g6_redact.py -q
.........                                                                [100%]
9 passed in 0.02s

$ pytest tests/unit/test_span_listener.py tests/unit/test_ids_unique.py -q
...........                                                              [100%]
11 passed in 0.12s

$ pytest tests/unit/test_retention.py tests/unit/test_turn_close_records_rss.py -q
...........                                                              [100%]
11 passed in 0.09s

$ pytest tests/integration/test_results_import.py -q
.......                                                                  [100%]
7 passed in 0.04s

$ pytest tests/integration/test_process_exit_mid_turn.py -q
.....                                                                    [100%]
5 passed in 0.03s

$ pytest tests/architecture/test_conventions.py -q
.....                                                                    [100%]
5 passed in 0.01s

$ pytest tests/unit/test_payload_size_control.py tests/unit/test_models.py -q      # the new coverage
........................                                                 [100%]
24 passed in 0.52s

$ python -m hrmosaic.core.procstat
{
  "rss_mb": 18.2,
  "rss_peak_mb": 18.2,
  "source": "resource.getrusage",
  "platform": "darwin",
  "uptime_ms": 0,
  "pid": 7167
}

$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
30 files already formatted

$ make test
.venv/bin/pytest -q
........................................................................ [ 74%]
.........................                                                [100%]
97 passed in 0.90s
```

Full suite **97 passed** (was 72), no warnings, no stray output. Nothing pushed. `.env` was never
read, printed or committed. The `CHANGELOG.md` Linux/CI RSS reading is unchanged — `procstat.py`
was not touched by this round, so the dated reading above it still stands.

## Notes for the next round

* The `payload_oversize` stub deliberately keeps the span's own `kind`, as the review's fix
  prescribed. That means the stub is **not** a parseable member of the §10.2 union
  (`extra='forbid'` rejects `error_kind` on a `tool_call`). It is a last-resort branch — reachable
  only by a payload that is still over cap with every string at 64 bytes and every list emptied,
  i.e. hundreds of dict keys — and losing the row entirely would be worse. If P9's dashboard
  parses `payload_json` eagerly it should treat `error_kind == 'payload_oversize'` as its own case.
* `_shed_longest_list()` sheds dict *values*' lists but never dict **keys**, so a payload whose
  bulk is a very wide flat object goes to the stub rather than being partially kept. No producer in
  the spec emits that shape; if one appears, shedding keys is the natural extension.
