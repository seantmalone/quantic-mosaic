# Changelog

Dated, human-written notes for anything a later phase must not rediscover: resolved dependency
versions, vendored asset substitutions, CI evidence run URLs and live facts that were verified
rather than assumed.

## 2026-09-09 — P0 Skeleton + CI

- Toolchain resolved on the build day with `uv` 0.12.12 and CPython **3.12.14** (`.python-version`).
- `requirements.txt` / `requirements-dev.txt` compiled from `pyproject.toml` with `uv pip compile`
  and committed with exact pins.
- Two pins in spec §3 do not exist on PyPI as written and were resolved to the nearest published
  release, verified 2026-09-09: **PyYAML 6.0.4 → 6.0.3** (latest published) and
  **jsonschema 4.27.0 → 4.26.0** (latest published). `anthropic` is specified as "1.x" and resolved
  to **1.4.0**.
- Frontend assets vendored at their pinned versions — htmx 2.0.9, Alpine.js 3.15.2, Chart.js 4.5.1 —
  with no substitution needed; the inventory is in `src/hrmosaic/web/static/vendor/LICENSES.md`.

- 2026-09-09 — CI evidence: green `pull_request` run recorded on https://github.com/seantmalone/quantic-mosaic/pull/1 (run https://github.com/seantmalone/quantic-mosaic/actions/runs/34396802226) and green `push` run on main (https://github.com/seantmalone/quantic-mosaic/actions/runs/34396798026).

## 2026-09-09 — P1 core/ (trace store)

- **RSS reader, measured 2026-09-09.** `python -m hrmosaic.core.procstat` on **Linux**
  (`docker run --rm -v $PWD/src:/src:ro -e PYTHONPATH=/src python:3.12-slim`, the same
  `python:3.12-slim` base the P11 image uses):
  `{"rss_mb": 16.4, "rss_peak_mb": 16.3, "source": "/proc/self/status", "platform": "linux",
  "uptime_ms": 0, "pid": 1}` — a bare interpreter plus `core/procstat.py`, i.e. the floor the
  §14.3 budget (`rss_mb < 420` with the ONNX model resident) is measured from. The same command
  on the development machine (macOS arm64, Python 3.12.14) reports
  `{"rss_mb": 18.2, "rss_peak_mb": 18.2, "source": "resource.getrusage", "platform": "darwin"}`.
- **Two readers, and the reading names its source.** Linux has `/proc/self/status` `VmRSS`
  (current RSS — the number the §14.3 gate asserts); macOS has no `/proc`, so `rss_mb()` falls
  back to `resource.getrusage` (`ru_maxrss`, a *peak* in **bytes** on Darwin and in **kB** on
  Linux). A macOS `rss_mb` is therefore a high-water mark, not a live reading.
- Turso is exercised only against an httpx `MockTransport` speaking the real Hrana
  `/v2/pipeline` shape; no test has ever contacted a live Turso database.

## 2026-09-09 — P2 Policy corpus

- **Corpus size, measured 2026-09-09** with `python scripts/corpus_stats.py`: **14 documents · 64.2
  pages · 31,007 words**, split `md` 11 (46.9 pp) · `html` 1 (5.0 pp) · `pdf` 1 (7.0 pp) · `txt` 1
  (5.3 pp). Pages are words ÷ 500 for the three text formats plus the **real** `pypdf` page count for
  the PDF, the §5.3 convention. `tests/unit/test_corpus_stats.py` asserts the band 5–20 files and
  30–120 pages, not these figures, so wording edits never fail the build.
- `corpus/facts.yml` carries **56** entries, not the "~40" of §5.2: the seven `rules.yml` scenarios
  alone consume 36 distinct `fact_key`s, and every one of the 14 documents needed at least one entry
  so that no document is uncitable by a gold answer.
- **Heading-path convention, resolved here and binding on P4.** A document's title is *not* part of a
  `heading_path` — it travels separately as `doc_title` in every citation — so `##`/`###` in Markdown
  yields two components (`"Accrual > Standard Accrual Rates"`), matching every example in §5.2, §8.4
  and §18.1. The `.txt` convention is `=` underline → title, `-` underline → level 1, an ALL-CAPS line
  → level 2. Both are documented in `corpus/README.md` and implemented in `scripts/check_facts.py`.
- **`workplace-conduct.pdf` is deterministic.** `scripts/build_pdf.py` pins the PDF creation date to
  2026-01-01, so two consecutive runs produced byte-identical output (`sha1
  58d72a36e7c35ecd3692e343d0b9fa8e1a3de58f`, 14,111 bytes, 7 pages, fpdf2 2.8.4). It uses fpdf2 core
  fonts only, so `workplace-conduct.src.md` is written in Latin-1-safe characters and no font file is
  vendored. The running footer it stamps is stripped by `scripts/check_facts.py` before quote
  comparison — the §6.2 "drop the boilerplate footer" cleaning, needed because a sentence spanning a
  page break otherwise has the footer spliced into it.
- CI's `test` job gained one step, `python scripts/check_facts.py`, ahead of `pytest -q` (roadmap §3).
- **`corpus/rules.yml` carries no evaluation semantics — that decision belongs to P5, and is open.**
  P2 first shipped a documented evaluation grammar in the file (`check.subject` / `check.operator` /
  `check.compare_to`, an `applies_when` guard, a `blocking` flag, and verdict-derivation rules). It was
  removed at the P2 gate: §8.4 fixes the tool's input and output schemas and says only that each
  requirement names a `fact_key`, a `doc_id` and a `heading_path`, and two of those operators decided
  when `check_policy_compliance` answers `conditional` rather than `compliant` — a **user-facing
  verdict**, which the standing brief says to report rather than resolve unilaterally. A requirement is
  now exactly `id · text · fact_key · doc_id · heading_path`; a scenario is `title · topics ·
  escalate_to · requirements · approvals_required · next_steps`, with `next_steps` a list of plain
  strings, matching the §8.4 output schema. The removed grammar survives as a **non-binding proposal**
  in the P2 report §7.5 for P5 to adopt, amend or ignore. `REQUIREMENT_KEYS` in
  `scripts/check_facts.py` (asserted by `tests/unit/test_facts_quotes.py`) fails the build if an
  evaluation field reappears in the data file, so putting one there is always a deliberate, reviewed act.
- **Two subjects P5 will need that no employee record carries** (found while removing the grammar, and
  worth writing down because P3 authors `mock_data/` in parallel): the benefits waiting period is 90
  **days** but §8.4 tool 5 exposes only `tenure_months_at_as_of`, so P5 must derive tenure days from
  `hire_date` against the `as_of: 2026-09-01` snapshot; and a PTO balance check needs `remaining_days`,
  which is an output of `check_pto_balance` (§8.4 tool 6, `mock_data/pto_balances.json`), not a field of
  the employee profile. Neither name may be read off `lookup_employee_profile`.
## 2026-09-09 — P3 mock data (the 2026-09-01 snapshot)

- **The datasets are byte-idempotent, verified 2026-09-09.** `python scripts/gen_mock_data.py`
  followed by `git diff --exit-code mock_data/` leaves the tree clean; so does
  `python scripts/gen_mock_schemas.py`. Everything that varies comes from one
  `random.Random(1729)`, so *any* change to the roster, the draw order or the number of RNG
  calls reshuffles ids, phones and balances wholesale. Re-generate deliberately, review the
  diff, and re-check `E1042 → 13.5`. Six files, 84 KB in total (the §5.4 budget is 300 KB).
- **Three `corpus/facts.yml` keys are a cross-phase contract with P2.** Every PTO record names
  its accrual band through `accrual_fact_key`, and
  `tests/unit/test_pto_balance_arithmetic.py` asserts the rate equals the `facts.yml` value.
  The keys used, with the value and `unit: days_per_month` each must carry, are
  **`pto.accrual.ft_3y_plus` = 1.50** (named in spec §5.2), **`pto.accrual.ft_under_3y` = 1.25**
  (the "under-3y 1.25" of §8.4 tool 6) and **`pto.accrual.part_time_prorated` = 0.75** (the
  three part-time employees). That test skips while `corpus/facts.yml` is absent, so it must be
  re-run after P2 merges.
- **Anchors other phases hard-code:** `E1042` Priya Raghavan (hired 2022-11-13, 45 months at
  the snapshot, 13.5 days remaining), manager `E1007` Dana Whitfield, skip-level `E1002`
  Miguel Ferreira, and `E1108` Marcus Feldman (hired 2026-08-15, `waiting_period_ends`
  2026-11-13, still inside the 90-day waiting period at the snapshot). The remaining 20 ids are
  sampled, so they are *not* stable across a regeneration — never hard-code one.
## 2026-09-09 — P6 core/llm/ (provider abstraction)

- **`python scripts/probe_provider.py` — PASS, run 2026-09-09.** One `claude-haiku-4-5` call
  carrying the nine published tools (as §8.4 publishes them, **no `strict`**) **and** an
  `output_config` JSON schema, a second identical call, and one `gemini-3.5-flash-lite` judge call.
  Both Haiku calls returned schema-valid JSON (`in=2479 out=59`, ≈ $0.0028 each) and the judge
  returned schema-valid JSON through strict `response_format` with no prompted-JSON fallback.
- **Measured cacheable prefix: 2172 tokens** (`messages.count_tokens` over *tools → system*),
  against `claude-haiku-4-5`'s **4096-token minimum cacheable prefix**. The prefix is *below* the
  floor, so the cache assertion is **not armed** and both calls reported
  `cache_creation_input_tokens: 0` / `cache_read_input_tokens: 0` — exactly the silent no-op §9.8
  predicts, recorded as a measurement rather than a failure. §9.8 expected nine compact schemas plus
  the system prompt to clear the floor; on this system prompt they do not. Caching starts paying
  once the stable head passes 4096 tokens — P7's real system prompt and P5's full tool descriptions
  are the next chance, and the probe re-measures at P10 step 0.
- **`input_schema` does not support `oneOf` / `allOf` / `anyOf` at the top level** — a hard 400 from
  the Messages API, verified live 2026-09-09 (`tools.1.custom.input_schema: input_schema does not
  support oneOf, allOf, or anyOf at the top level`). §8.4's `get_policy_section` publishes a root
  `oneOf`, so `AnthropicAdapter` drops those three keys from the top level of a tool schema on the
  way out and changes nothing else; the published MCP schema keeps the `oneOf` and the selector rule
  stays enforced server-side, where §8.4 already returns `INVALID_ARGUMENTS`. **`default` values and
  the open `parameters` sub-schema are accepted as published** — only the combinators are rejected.
- **The API echoes a dated snapshot id**: `model: "claude-haiku-4-5"` comes back as
  `claude-haiku-4-5-20251001` (also `models.retrieve`, 2026-09-09). `llm_call` spans therefore record
  the **configured** id, which is what §10.1's span name shows, what `LLM_MODEL` pins and what
  `MODEL_PRICES` keys on — an echoed snapshot id would silently estimate every call at $0.00.
- `anthropic` 1.4.0 and `openai` 2.54.0 both ship **`httpx2`** (2.12.0, already pinned transitively)
  as their HTTP layer, not `httpx`: an `httpx.Client` is rejected outright with
  `Invalid http_client argument`. Every MockTransport fixture uses `httpx2.MockTransport`.

## 2026-09-09 — P2/P3 merge fix (part-time PTO accrual)

- `corpus/facts.yml` gains **`pto.accrual.part_time_prorated`** — 0.75 `days_per_month`, quoting the
  existing `Accrual > Part-Time and Prorated Accrual` section of `pto-and-holidays.md`. P2 and P3 were
  built in parallel: `mock_data/pto_balances.json` names three `accrual_fact_key` bands and the index
  carried only the two full-time ones, so
  `tests/unit/test_pto_balance_arithmetic.py::test_accrual_rate_matches_the_facts_yml_band` failed. No
  policy prose changed — the document already stated the proration rule with a checkable number.

## 2026-09-09 — P3 mock data (part-time PTO accrual follows the corpus)

- `scripts/gen_mock_data.py` now sets `accrual_rate_days_per_month` to `round(fte x band_rate, 2)`
  and `accrual_fact_key` to the **tenure band** for every employee, part-time included — the rule
  `corpus/pto-and-holidays.md` states under "Accrual > Part-Time and Prorated Accrual". `E1132` and
  `E1175` (0.8 FTE, three-year-plus band) were flat-rated at 0.75 d/mo and now accrue **1.20**;
  `E1096` (0.6 FTE, under-three-year band) keeps 0.75 but now quotes `pto.accrual.ft_under_3y`. No
  balance record names `pto.accrual.part_time_prorated` any more; the fact stays in `facts.yml` as
  the document's own 0.6-FTE worked example. `fte` is **not** copied onto the balance — it already
  lives in `employees.json`, and the test derives the expected rate from there.
- **The seeded stream is shared across datasets, so a data fix ripples.** `random.randint`
  rejection-samples, so widening two employees' `used_ytd` draw range (`int(available * 2 * 0.6)`,
  8 → 12 half-days) consumes a different number of words and shifts every later draw. Regenerating
  therefore also moved the sampled `used_ytd` / `pending_days` / carryover of six unrelated PTO
  records (`E1133`, `E1138`, `E1145`, `E1162`, `E1172`, `E1192`) and the sampled plan/tier/dependants
  of 17 `benefits_elections` records. **Nothing pinned is affected**: all 24 ids and the record order
  are byte-identical, the four anchor PTO records are untouched, `E1042` is still 13.5 days at
  1.50 d/mo, and `E1108`'s benefits record is still `elections: []` with `waiting_period_ends`
  2026-11-13. Anyone changing an accrual rate again should expect the same ripple — the alternative
  (a per-dataset or per-employee stream) would churn every sampled value once, which is why it was
  not done here.

## 2026-09-09 — P4 `rag/` (parsing, chunking, embedding, hybrid index)

- **The query-embedding branch is measured, not assumed (§6.4).** With **fastembed 0.8.0** and
  `BAAI/bge-small-en-v1.5`, `TextEmbedding.query_embed()` returns a vector **identical** to
  `.embed()` for the same string (`numpy.allclose` → `True`, cosine 1.0): the library delegates and
  applies no instruction prefix. So `embed_query()` prepends the literal
  `"Represent this sentence for searching relevant passages: "` itself, and `index_meta.query_convention`
  records **`prefix:Represent this sentence for searching relevant passages: `**.
  `tests/unit/test_query_embed_is_asymmetric.py` re-measures the delegation on every run and pins the
  constant to whichever branch the installed library forces, so a fastembed bump cannot switch the
  convention silently — and `open_index()`'s guard refuses to serve an index built under the other one.
- **Chunk count: 204 over 14 documents**, below the `~240–320` the spec estimates in §6.3, with the four
  chunk constants exactly as specified (1,400 max / 1,100 window / 150 overlap / 120 floor). The corpus
  itself is the size §6.1 predicted — 30,840 words against the illustrative 31,500, per format
  md 23,276 · html 2,515 · pdf 2,425 · txt 2,624 — so the difference is granularity, not missing prose:
  the corpus's leaf sections average ~940 characters, and a leaf within `CHUNK_MAX_CHARS` is emitted
  whole. Only 24 chunks come from windowing. Per-format chunks: md 153 · html 17 · pdf 15 · txt 19.
- **Measured wall clock** (M-series laptop, `.venv`, warm model cache): a full
  `python -m hrmosaic.rag.ingest` — parse, chunk, embed 204 chunks at `batch_size=8`, write the index —
  takes **30.9 s**; the retrieval self-test embeds one query in **249 ms** and searches in **1.4 ms**.
  That is the §6.1 argument for building at Docker build time rather than at boot, restated on this
  corpus.
- **`--verify-manifest` is the R1.4 gate and now runs in CI ahead of `pytest`.** It runs the whole
  pipeline into `INDEX_PATH` and compares the manifest byte for byte, printing a unified diff on any
  difference; the comparison is on chunking only, never vectors, so `EMBED_PROVIDER=fake` still
  produces a valid manifest.
- **A windowing defect the corpus found.** With the overlap subtracted from a cut that landed early —
  a leaf whose only full stop is in its first sentence, e.g. `hr-escalation-and-case-handling`'s
  "What Must Be Escalated" — the next window's cut search reached the *same* sentence boundary, so the
  window crawled forward one character at a time and emitted colliding `chunk_id`s (the `chunks.chunk_id`
  UNIQUE constraint caught it). The cut is now required to land past the previous window's end;
  `tests/unit/test_chunking.py::test_a_leaf_whose_only_full_stop_is_early_still_advances` is the
  regression, and it produced 35 pieces with 30 distinct offsets before the fix and 5 after.
- **Self-test result:** `"How many consecutive days abroad require Tax & Legal review?"` → top-1
  `tax-and-location-addendum`, `dense_score` **0.7640** (floor `SELFTEST_MIN_DENSE_SCORE` 0.25),
  `index_meta.chunk_count` 204 = the committed manifest's line count, `index_version` `2026.1+920c`.

## 2026-09-09 — P1 core (credential hygiene) + P0 `download_model.py`

- **Every §12.3 credential field is now `pydantic.SecretStr`** — `ANTHROPIC_API_KEY`, `LLM_API_KEY`,
  `LLM_FALLBACK_API_KEY`, `JUDGE_API_KEY`, `TURSO_AUTH_TOKEN`, `APP_ACCESS_TOKEN` (the complete set of
  fields whose name ends `_api_key`, `_token` or `_secret`; `tests/unit/test_settings_secrets.py`
  asserts the set is complete, so a new credential field cannot be added as a plain `str`). Found in
  the P4 review: a failing pytest assertion whose expression mentions `settings` prints the whole
  `Settings` repr into the report, and a CI log is a public artifact. `repr()`, `str()` and
  `model_dump()` now render `**********`. Defaults and optionality are unchanged, and so is the
  §12.3 rule that credentials are validated **lazily**: `settings.secret_value()` opens a
  `SecretStr` at the point of use — in the three `core/llm/` factories, in `build_store()` and in
  `scripts/probe_provider.py` — and an unset key still builds an adapter that reports
  `configured is False`. `secret_value()` maps an **empty** credential to `None`, so `KEY=` in an
  untouched `.env` reads as "not configured" exactly as the plain-`str` version did.
- `rag/download_model.py` constructs `TextEmbedding` with **`threads=1`**, matching `rag/embed.py`:
  every construction in the repository now pins the ONNX thread count, so the single-core container
  of §14.3 cannot have a thread pool spawned behind its back on the cache-warming path either.

## 2026-09-09 — P5 `mcpserver/`: nine tools, three transports, the confirmation gate

- **Measured against `mcp` 2.2.0 today, and it contradicts one line of the spec.** §8.2 step 5 records
  an earlier probe finding `structured_content` populated over HTTP but `None` over stdio. Measured on
  2026-09-09 against this server, **both transports populate it** — because every tool returns an
  explicit `CallToolResult` carrying `structured_content` *and* a JSON `TextContent`. The fallback path
  the spec requires stays, and `tests/integration/test_mcp_tool_call.py` asserts the two paths agree on
  both transports, so a client written against either is correct.
- **A schema violation is `isError: true` with a text message, not a JSON-RPC `-32602`.** §8.3 describes
  it as "`isError: true` with JSON-RPC `-32602`". In 2.2.0 the pydantic `ValidationError` is caught by
  `MCPServer._handle_call_tool` and returned as `CallToolResult(content=[TextContent(...)],
  is_error=True)`; the `-32602` code never reaches the wire. Nothing downstream changes — the
  orchestrator keys on `is_error` — but `mcp/README.md` now records the observed shape.
- **The SDK grep §17 asked for, before any MCP code was written: a native `Host`/`Origin` allowlist
  exists.** `mcp/server/transport_security.py` defines `TransportSecuritySettings`
  (`enable_dns_rebinding_protection`, `allowed_hosts`, `allowed_origins` with a `host:*` wildcard-port
  form), applied by `TransportSecurityMiddleware`, and `streamable_http_app(transport_security=…)`
  accepts it. Three caveats, all recorded in `mcp/README.md`: it is **off** unless asked for
  (`TransportSecurityMiddleware(None)` disables rebinding protection "for backwards compatibility");
  `streamable_http_app()` auto-fills an allowlist only when its `host` **bind** argument is loopback,
  which a Render deployment's public hostname is not; and the endpoint is behind the app's own access
  gate and per-IP limit anyway. So the control this project relies on is the gate, and the SDK's
  allowlist is documented as available rather than configured.
- **`sqlite-vec` probe on this platform** (`python scripts/probe_sqlite_vec.py`, the script CI's P11
  `docker` job runs inside a bare `python:3.12-slim`): sqlite3 **3.53.1** · sqlite-vec **v0.1.9** ·
  python **3.12.14**; a `vec0` table declared `distance_metric=cosine` returns distance **0.0** to an
  identical vector and **1.0** to an orthogonal one — cosine, not the L2 default, which would have
  given ≈1.414 and moved every calibrated threshold in the project.
- **The `_trace` envelope is an object, not a bare list.** §8.7 says the server returns nested spans
  "under a `_trace` key"; the same envelope also has to carry the actor and `server_timing_ms`, which
  the `tool_call` payload of §10.2 declares, so `_trace` is
  `{spans[], server_timing_ms, actor{}, server, transport}` and lives **inside the result body** rather
  than in the result's `_meta`, so it survives both read paths of §8.2 step 5.
- **The confirmation gate is a wire-level check.** It compares the **raw arguments of the request**
  against `confirmations.arguments_json`: the handler sees schema defaults already applied, so
  comparing those would let a caller who omitted `priority` mismatch a token minted from what the
  client actually sent. Consequence for P8: `web/` mints from the gated attempt's `tool_call` span
  `arguments`, and the SDK's in-process `server.call_tool(...)` shortcut always rejects (the fail-safe
  direction), which is why every gate test runs over a real session.
- **`sse_starlette.AppStatus.should_exit` is a process-global latch.** Stopping one uvicorn sets it and
  every later SSE stream in the same process drains immediately — after exactly three mounted-HTTP
  sessions, the fourth `initialize` failed with "SSE stream ended without a response". One server per
  process is the only case its authors had in mind. `tests/integration/conftest.py` clears the latch
  around each mounted-HTTP session; nothing in `src/` is affected, because the app runs one server.
- **`ruff`'s isort had to be told `mcp` is third-party.** The repository has a top-level `mcp/`
  directory (DOCS.8), so isort classified the SDK as first-party by directory name and moved
  `from mcp import Client` into the local block. `[tool.ruff.lint.isort] known-third-party = ["mcp",
  "mcp_types"]` is the fix — the linter's version of the §4.1 shadowing hazard.
- **Suite after P5: 771 tests, `make lint` clean, `pytest -q` pristine** (from 590 at P6). The nine
  tool schemas are generated from a live `tools/list` and committed under `mcp/tools/`, and
  `python scripts/gen_tool_schemas.py && git diff --exit-code mcp/tools/` is clean.
