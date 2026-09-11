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
- **`check_policy_compliance`'s requirement grammar and verdict ladder are now in spec §8.4.** §8.4
  fixed the tool's input and output schemas and the four verdict *names*, but not how a verdict is
  derived; the grammar P2 authored and set aside, which P5 adopted, lived only in `corpus/rules.yml`'s
  header and the P5 report. Two new §8.4 paragraphs — "How a requirement is evaluated" and "How the
  verdict is derived" — publish the closed vocabularies (`check.subject`, `check.operator`,
  `check.compare_to`, `applies_when`), the two rules that stop an unmet requirement proving a violation
  (`manual` is never blocking; an absent subject is not evaluable) and the precedence
  `insufficient_evidence → non_compliant → conditional → compliant`. `rules.yml`'s header now restates
  §8.4 instead of defining the contract, and `tests/contract/test_rules_grammar_matches_spec.py` fails
  if the spec and `mcpserver/rules.py`'s own vocabularies ever drift apart — in either direction. No
  runtime behaviour changed; `src/` is byte-identical.

## 2026-09-10 — P7 agent/ (orchestrator, guardrails, workflows)

- **`python scripts/probe_provider.py` — PASS, re-run 2026-09-10 against P7's real system prompt.**
  The probe no longer carries a hand-written stand-in: `SYSTEM_PROMPT` is now
  `agent/prompts/act.j2`'s rendered **system** block, the longest of the three and the one every act
  step of every turn sends, so the number below is the prefix that actually ships.
- **Measured cacheable prefix: 3523 tokens** (`messages.count_tokens` over *tools → system*, the
  nine committed `mcp/tools/*.schema.json` as published plus the real act system prompt), against
  `claude-haiku-4-5`'s **4096-token minimum cacheable prefix**. Still **below** the floor by ~570
  tokens, so the cache assertion is **not armed** and both calls reported
  `cache_creation_input_tokens: 0` / `cache_read_input_tokens: 0` — the silent no-op §9.8 predicts.
  P6 measured 2172 with its own shorter stand-in prompt; the rest of the rise is P5's full tool
  descriptions, which the probe now reads from the committed schemas. **The prompt was deliberately
  not padded to clear the floor**: §9.8 makes caching best-effort and asserts nothing, and a system
  prompt written to hit a token count would be a worse prompt. Both calls returned schema-valid JSON
  (`in=3830 out=64`, ≈ $0.0042 each) and the `gemini-3.5-flash-lite` judge returned schema-valid JSON
  through strict `response_format`. Total live spend for the re-measure: **under one cent**.
- **The root-combinator strip is now shared, not Anthropic-only.** `get_policy_section` publishes a
  root `oneOf` (§8.4) and Gemini's OpenAI-compatible layer refuses one on
  `tools[].function.parameters` exactly as the Messages API refuses it on `input_schema` — and Gemini
  is *both* the judge and the agent's failover, so a stripper in one adapter would have sent the
  refused schema on precisely the path a live demo falls back to. `base.py` now owns
  `ROOT_COMBINATOR_KEYS` / `without_root_combinators()` and both adapters call it;
  `tests/unit/test_openai_compat_tool_schema.py` asserts it against the committed schemas and on the
  real wire for both adapters.
- **The confirmation gate can only be observed over the mounted HTTP transport.** The gate reads and
  writes `confirmations` / `mock_writes` in the **trace store**, and `mcp/server_entrypoint.py
  --stdio` is a separate OS process with a store of its own — so a stdio test asserting "no
  `mock_writes` row" would be counting a table the server never touched. `tests/conftest.py` grew a
  `mounted_mcp_url` fixture for that reason and both confirmation tests use it; everything else keeps
  the stricter stdio subprocess.
- **Two ambiguities in §9.1 resolved, both recorded in the P7 report:** the out-of-scope refusal and
  the G5 escalation are produced **deterministically** rather than by a synthesis call (there is no
  evidence to synthesize from, and G1 forbids answering from parametric knowledge), and a turn whose
  router intent is `action` is not closed by a workflow completion predicate before it has proposed
  the write the user asked for in words — otherwise `pto_request.is_complete`, which a cited answer
  alone satisfies, would end demo task 2 one step before its confirmation gate.
- **Suite after P7: 923 tests, `make lint` clean, `pytest -q` pristine, ~33 s** (from 781 at P5).

## 2026-09-10 — P7 fix round 1 (agent/, and two accepted cross-phase fix-ups)

- **Accepted cross-phase fix-up, P6-owned `core/llm/`.** P7's scope is `src/hrmosaic/agent/**`, but
  three P6 files carry production changes made during P7 and they are kept deliberately, not by
  oversight. P6's owner and any later reader should treat these as P6 surface that already moved:
  - `core/llm/base.py` grew the shared `ROOT_COMBINATOR_KEYS` / `without_root_combinators()`, and
    **both** adapters call it, so `get_policy_section`'s root `oneOf` (§8.4) is stripped on the
    Anthropic path *and* on the Gemini OpenAI-compatible path — which is both the judge and the
    agent's failover, so a stripper in one adapter would have sent the refused schema on exactly the
    path a live demo falls back to (commit `c0b4dd5`, ratified in the roadmap ledger).
  - `core/llm/anthropic.py`'s `_split_system` now **coalesces consecutive same-role messages** into
    one message with a block list. The Messages API requires alternating roles and requires every
    `tool_use` block to be answered by a `tool_result` block in the *immediately following* message;
    the provider-neutral `Message` carries one tool result each, so an act step that asked for two
    tools produced two consecutive `user` messages and left the second `tool_use` unanswered. The
    committed `demo_task_1.json` groups its act steps 2 + 2 + 1, so demo task 1's second act call
    would have been a 400 against live `claude-haiku-4-5`. `StubAdapter` never reads the message
    array, so nothing in the suite could see it; `tests/unit/test_wire_message_alternation.py` and
    `tests/integration/test_act_loop_wire_shape.py` now assert the wire bytes.
  - `scripts/probe_provider.py`'s `SYSTEM_PROMPT` is `agent/prompts/act.j2`'s rendered system block
    rather than a hand-written stand-in, so the measured cacheable prefix is the one that ships.
- **Accepted cross-phase fix-up, P0-owned `pyproject.toml`** — and **P11 needs to know**:
  `[tool.setuptools.package-data] "hrmosaic.agent.prompts" = ["*.j2"]`. The prompts are loaded from
  disk relative to `prompts/__init__.py`. The repo installs `-e .`, so **no test can catch its
  absence**; without it the P11 Docker image, which installs the package properly, would ship
  `agent/prompts/` with no templates in it and every turn would fail at `render()`.
- **The synthesis evidence envelope carries the whole chunk, not the snippet.** §7.2's template
  renders `c.text`; `synthesize.j2` had `{{ chunk.snippet }}`, and `rag/chunk.py` caps a snippet at
  320 characters while 199 of the 204 committed chunks are longer than that (median 995) — so the
  synthesis model was seeing roughly a third of every chunk it was asked to ground an answer in.
  Now `{{ chunk.text }}`. `tests/fixtures/prompts/synthesize.user.txt` was re-recorded, and the two
  chunks it pins are now **real** chunks read out of the committed index (as G2's tests read them),
  so the golden file pins the untruncated bytes and a regression to `snippet` is a diff. One
  consequence to know: a corpus edit that moves either of those two chunks now also re-records that
  golden, which is the same deliberate re-review the manifest already demands.

## 2026-09-09 — P8 web/ (`/chat`, `/chat/confirm`, SSE, `/health`, the access gate, the chat UI)

- **Live provider check, run 2026-09-09** against `claude-haiku-4-5` with the real key from the
  git-ignored `.env` (`make run`, then `BASE_URL=http://127.0.0.1:8000 bash scripts/demo_task_1.sh`
  and `scripts/demo_task_2.sh`). **The Anthropic multi-turn tool wire shape is confirmed correct**:
  12 Haiku calls across the two tasks, zero 400s, every `tool_use` answered by a `tool_result` in
  the immediately following message. Measured, on the committed code:

  | Task | Outcome | Model calls | Tool calls | Retrievals | Citations | Wall clock | `cost_usd_estimate` |
  |---|---|---|---|---|---|---|---|
  | 1 — Berlin remote work | `answered` | 5 | 3 | 1 | 6 from 3 documents | 29.8 s | $0.0339 |
  | 2 — PTO + gated write | `answered` after Confirm | 7 | 5 | 1 | 5 from 2 documents | 34.0 s | $0.0437 |

  Task 2 produced `MOCK-HR-000001` on the reopened turn (`resumed_count = 1`) with one `confirmed`,
  spent `confirmations` row. **Total for the pair: $0.0776.** G1/G2/G3 all `allow` on both.

- **Three live-only agent-loop defects the stub could never show, found by that check and fixed.**
  Under `StubAdapter` the scripted tool sequence always searched the corpus first, so all three
  were invisible; against the real model each one closed a turn that had not done what it was
  asked, and **both demo tasks refused** before the fixes:
  1. *The completion predicate and the evidence gate disagreed about "evidence".* `_absorb` fed the
     chunk ids that `get_policy_section` and `check_policy_compliance` **cite** into
     `LoopState.evidence_*`, which the workflow predicates count — but those chunks carry no dense
     score, so they never enter G1's candidate set. A turn that reached a compliance verdict without
     searching was therefore "complete" and then refused for want of evidence. The two now share one
     meaning of evidence: only retrieved chunks count.
  2. *Nothing told the **model** what the workflow still needed.* `WorkflowSpec` knew; the
     conversation did not. `Orchestrator._nudge()` now sends one operational reminder, at most once
     per turn, on the step where the model tried to stop while the workflow was incomplete.
  3. *An outstanding write was dropped when the model simply answered.* `_action_outstanding` guarded
     the completion-predicate exit but not the "model returned no tool calls" exit, so demo task 2
     answered without ever proposing `create_mock_hr_ticket` — the confirmation gate, i.e. the whole
     safety demo, never fired. `_nudge()` now covers that door too.
  Alongside them, two prompt rules (both re-recorded in `tests/fixtures/prompts/`): `act.j2` gains
  "a policy claim needs the policy TEXT, not a title" — the live model had been reaching for
  `list_policy_documents`, which grounds nothing — and `route.j2` gains "`action` beats `workflow`
  when the user also asks for something to be created", which is what puts demo task 2 back on the
  `intent="action"` path `_action_outstanding` keys on.

- **The documented tool sequence of §18.1 is the *expected* one, not a guarantee.** On the live run
  demo task 1 answered in three tool calls (profile → compliance → one search) rather than the five
  §18.1 lists, and cited three documents rather than four. `DEMO_EXPECTATIONS` is a floor
  (`min_tool_calls`, `required_tools`, `precedence_edges`), and `tests/e2e/test_demo_tasks.py` runs
  it against the committed stub scripts; P10 re-records both scripts from a real exchange.

- **`sse_starlette` patches `uvicorn.Server.handle_exit`, and uvicorn 0.52 replays captured signals.**
  Two facts that bite any test which stops a server holding an SSE stream open. The agent's own MCP
  session keeps a long-lived `GET /mcp-server/mcp` open, and uvicorn will not finish a graceful
  shutdown while serving it; only the process-global `AppStatus.should_exit` drains it, and that is
  set by `sse_starlette`'s patched **signal handler**, never by assigning `server.should_exit`.
  Calling `server.handle_exit()` by hand sets both — and then uvicorn re-raises every captured signal
  once its handlers are restored (`uvicorn/server.py:339`), killing the pytest process with 143. The
  test helper therefore sets **both latches directly**; a real SIGTERM on Render wants the replay.

- **`web/` hand-rolls its SSE response rather than using `sse_starlette`.** One process-global latch
  that a stopped server sets for every other stream is enough; `web/sse.py` ends its generators from
  the lifespan instead.

- **`scripts/wait_for_health.py` was missing.** The `Makefile`'s `demo1` / `demo2` / `docker-run-512`
  targets have called it since P0. Added here, because `make demo1 && make demo2` is P8's gate.

## 2026-09-10 — P7 fix round 2 (the act loop's two reminders)

- **A reminder names the debt, never the tool.** `WORKFLOW_INCOMPLETE` used to inject
  `check_pto_balance`, `check_policy_compliance` and "Make ONE `search_policy_documents` call", and
  `ACTION_OUTSTANDING` said "Call the write tool now" — so on a nudged turn the harness, not the
  model, authored the remaining tool sequence and §13.4's ToolSelection would have been scoring the
  hint. The wording now comes from the workflow spec's `slot_descriptions` / `evidence_description`
  ("no compliance verdict is in state yet"), and the evidence clause states what the predicate
  *actually* requires: "one search is enough" was false for `remote_work_eligibility`, which needs
  three distinct `doc_id`s. Every turn now records which reminders fired in the `plan` span's new
  `nudges[]` (defaulted, so older rows still parse), which is what lets P10 publish a `nudge_rate`
  beside the per-turn scores.
- **A reminder never asks for a tool the turn may not call.** `_nudge` reads the same
  `allowed_tools(...)` list the act step calls through, so under §13.9's `no_structured_tools`
  ablation the debts only a disabled tool could settle are dropped and the action reminder is
  silent — otherwise the ablation would have been reading `tool_not_offered` spans it manufactured
  itself.
- **An empty assistant turn never reaches the wire.** `_act` appends the assistant message before it
  knows whether the loop will let the model stop, so an empty completion followed by a reminder left
  a non-final `{"role": "assistant", "content": ""}` — a non-retryable 400 on the Messages API that
  escaped the loop's own handling and surfaced as `web/`'s catch-all. `_split_system` now drops a
  content-less, tool-call-less assistant entry, and `test_wire_message_alternation.py` asserts a
  third structural rule: no non-final message is empty.
- **A quarantined chunk is not evidence.** G2 strips every citation to one, so counting it let
  `is_complete` close a turn on support the answer is forbidden to use — the same defect as counting
  a merely *cited* chunk id. `LoopState.note_evidence` drops it and `turn.citable()` keeps it out of
  G1, while the `retrieval` span still carries the hit with its flag and the synthesis prompt still
  renders the labelled envelope.
- **Live provider check, run 2026-09-10** against `claude-haiku-4-5` with the real key from the
  git-ignored `.env` (`make run`, then `BASE_URL=http://127.0.0.1:8000 bash scripts/demo_task_1.sh`
  and `scripts/demo_task_2.sh`). **Both demo tasks completed with the reworded reminders.** Demo 1
  ended `answered` with 5 citations spanning 3 documents (`remote-and-hybrid-work`,
  `tax-and-location-addendum`, `security-acceptable-use`), 6 tool calls, 4 retrievals;
  `nudges: ["workflow_incomplete"]` — the model had the profile and the verdict but no retrieved
  text, was told so, and answered it with four searches. Demo 2 ended `answered` after the
  confirmation gate with `MOCK-HR-000012` created, 6 tool calls;
  `nudges: ["workflow_incomplete", "action_outstanding"]` — one reminder bought the policy
  passages, the other the gated proposal. Total spend for the live check, including one earlier
  refused run whose wording was too weak, **$0.12**.
- **The first wording refused, and why the second does not.** "Close each gap with the tools you
  were offered" left `claude-haiku-4-5` fetching sections by exact heading — `get_policy_section`
  returns no scored chunk, so G1 saw an empty candidate set and demo 1 refused. The shipped text
  says what only a search can give it: *"Only a passage retrieved by SEARCHING the policy corpus can
  be cited: a section fetched by its exact heading is not scored, grounds nothing, and an answer
  resting on one is refused."* Still no tool name — the capability, not the call.

## 2026-09-10 — P10 `evaluation/` (dataset, scorers, judges, ablation, the first real runs)

- **Step 0, live provider facts, read 2026-09-09** and pasted with their dates into `deployed.md`.
  Anthropic `claude-haiku-4-5` is **$1.00 / $5.00 / $1.25 / $0.10 per MTok** (input / output /
  cache-write / cache-read) — `core/models.py::MODEL_PRICES` already matched exactly, so nothing
  changed — and the **minimum cacheable prefix is 4,096 tokens**, confirmed on
  `platform.claude.com/docs/en/build-with-claude/prompt-caching`. The **Gemini free-tier RPM/TPM/RPD
  table is no longer published in the API documentation**: `ai.google.dev/gemini-api/docs/rate-limits`
  now says limits "can be viewed in Google AI Studio" and links to an authenticated page this
  environment cannot read. The observed behaviour is recorded instead (below), and P11 step 0
  re-reads the row from a signed-in session.

- **`MIN_EVIDENCE_SCORE` and `MIN_SUPPORT_SCORE` calibrated from the observed score distribution,
  measured 2026-09-09** (§7.4, §21, R-15). Retrieval only, no model: the 26 dataset questions plus
  8 extra out-of-corpus probes against the committed index. The two populations separate cleanly on
  `max_dense_score` —

  | population | n | min | median | max |
  |---|---|---|---|---|
  | in-scope (23 questions) | 23 | **0.6218** | 0.7273 | 0.9173 |
  | out-of-scope (3 dataset items + 8 probes) | 11 | 0.4662 | 0.5195 | **0.5835** |

  — leaving a clean gap of `[0.5835, 0.6218]`. The second-ranked score separates the same way
  (`[0.5705, 0.6038]`), and the noise floor across every out-of-scope top-5 hit is 0.2907 against an
  in-scope floor of 0.5742. **`MIN_EVIDENCE_SCORE` 0.32 → 0.60** (the midpoint of the gap) and
  **`MIN_SUPPORT_SCORE` 0.26 → 0.45** (above the noise floor, below every in-scope top-5 score, so
  no in-scope retrieval loses a chunk and `retrieve()`'s default `min_dense_score` still admits
  everything it admitted before). At `(0.60, 0.45)` the gate admits **23/23** in-scope questions and
  rejects **11/11** out-of-scope probes. **The shipped 0.32 / 0.26 sat below this embedding model's
  cosine floor over this corpus, so neither G1 score clause could ever fire** — the rule was a
  no-op, and out-of-scope questions were being caught by the router's flag alone. The published
  `min_dense_score` default on `search_policy_documents` stays **0.26**: it is a tool-schema
  contract (§8.4) and is not a G1 threshold.

- **The first real runs, 2026-09-10, `target: local`, all three variants** (§13.2, §13.9). One
  locally running app (real `claude-haiku-4-5`, real `gemini-3.5-flash-lite` judge on a separate
  `JUDGE_API_KEY`), the runner driving `POST /chat` sequentially with
  `Authorization: Bearer $APP_ACCESS_TOKEN` and `X-Actor: admin`.

  | variant | strict pass | groundedness | cit. accuracy | cit. resolve | doc recall | tool selection | workflow | over-refusal | nudge rate | judge calls | est. cost | wall clock |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | `baseline` | 0.538 | **0.912** | 0.862 | 0.923 | 0.746 | 0.918 | 0.731 | 0.111 | 0.077 | 252 | $0.432 | 3 335 s |
  | `dense_only_k2` | 0.692 | not judged | not judged | 0.923 | 0.759 | 0.926 | 0.731 | 0.111 | 0.115 | 0 | $0.402 | 531 s |
  | `no_structured_tools` | 0.577 | not judged | not judged | 0.885 | 0.746 | 0.840 | **0.615** | 0.167 | 0.115 | 0 | $0.434 | 530 s |

  `strict_pass_rate` is **not comparable across the rows**: §13.8 makes the groundedness clause
  vacuous on an unjudged variant, which is why the two arms score *higher* than the judged baseline.
  Baseline latency p50 **11 267 ms**, p95 **36 317 ms** — greyed out and labelled *local runner, not
  representative* everywhere it appears; 348 s of the run's 350 s of measured span time is provider
  time. `judge_agreement_rate` **1.00** over `judge_agreement_n` **7** of the 8 SEED-selected items
  (`remote-003` refused, so the judge produced no groundedness verdict and the item left the
  denominator). Action safety: **zero violations** across all **125** real turns in the local store,
  including 2 confirmed mock writes. `injection_quarantined` **true** on `inj-001` (G4's only eval
  evidence). `tool_discovery_ok` **true**. **Total P10 spend, everything included: $1.59** over 328
  Anthropic calls and 256 free judge calls.

- **The ablation's null result is published as a null result** (§13.9). `make ablation` exits
  non-zero and `evaluation/REPORT.md` carries the *not supported by this run* banner:
  `workflow_completion(no_structured_tools)` is **0.615** against a baseline of **0.731**, a delta
  of **−0.115** where §13.9 predicts worse than −0.25. The arm does move `tool_selection_accuracy`
  (0.918 → 0.840) and `over_refusal_rate` (0.111 → 0.167).

- **The zero-LLM chunk-size sweep found nothing, which is the finding.** 700 / 1 100 / 1 600
  characters all score `DocRecall` **0.8947** over the 19 dataset items that name `expected_docs`
  (235 / 204 / 180 chunks respectively). On a 14-document corpus at k = 5 the window does not change
  which documents come back. Each index was built into a temporary directory;
  `data/index/chunks.manifest.jsonl` is untouched.

- **Observed Gemini free-tier behaviour, in place of the quota page.** 256 judge calls over the
  sweep, paced by the shared token bucket at `LLM_RPM = 10`. **75 provider retries** were recorded,
  every one of them on the judge path and none on the Anthropic path; **no failover** to the
  fallback provider ever fired. 14 judge calls needed §13.7's one repair round trip and 12 of those
  recovered; **2 recorded a `null` verdict**, which is the designed behaviour — the item leaves that
  metric's denominator and `n_scored` says so — observed live rather than asserted.

- **Prompt caching never engaged, and the span data says why.** Across 328 Anthropic calls,
  `cache_creation_input_tokens` and `cache_read_input_tokens` were **0 every time**. Anthropic
  renders a request as *tools → system → messages* and the breakpoint sits on the last system block,
  so the cacheable prefix is the nine tool schemas plus the system prompt — and that prefix does not
  clear `claude-haiku-4-5`'s **4 096-token** minimum (observed whole-request `prompt_tokens` ran
  1 164 / 3 204 / 14 422 for min / median / max, with the growth coming from the *messages*, which
  are after the breakpoint). §9.8 anticipates exactly this: caching is best-effort, nothing asserts
  it, and the sweep's cost estimate holds either way. It also means the $2–4 sweep estimate was
  conservative — the real figure was **$1.27** for the three 26-item runs.

- **The agent retrieves across four documents and cites across two.** The single most actionable
  finding of the phase, and it shows up in three independent places: `remote-004` failed its
  `min_distinct_docs: 3` end state after searching four times across four documents; the same is
  true of `remote-002`, `expenses-002` and `onboarding-001`; and a live demo-task-1 recording cited
  `remote-and-hybrid-work` and `tax-and-location-addendum` only. `DocRecall` (retrieval) is 0.746
  while the citation-based end states fail — so this is a synthesis-side behaviour, not a retrieval
  one.

- **The demo stub scripts were NOT re-recorded, deliberately.** Three identical live recordings of
  demo task 1 and one of demo task 2 (2026-09-10) show that `claude-haiku-4-5` reproducibly does
  *not* follow §18's documented sequences: `get_policy_section` is never called on demo 1,
  `lookup_employee_profile` is never called on demo 2, `check_policy_compliance` is called *before*
  the searches rather than after them, demo 1 cites 2 documents where §18 requires ≥ 3, and
  `check_policy_compliance` is passed `destination_country: "Germany"` where §18.1 documents `"DE"`.
  Adopting those recordings as the committed fixtures would have required weakening
  `min_distinct_docs_cited` — R3.5's multi-document evidence — which is not a call this phase should
  make alone. The P7 fixtures stand; the measurement is recorded here and in the P10 report.

## 2026-09-10 — P10 fix round 2 (real demo recordings, the soft topic filter, two-pass judging)

- **`search_policy_documents.topic` became a SOFT filter (semantic change, §8.4).** It was a hard
  filter, which made the model's own topic guess the ceiling on what an answer could cite:
  `manager-approval-matrix` carries the topic `approvals` and nothing else, so a `pto` search could
  never see the approval rule that governs a PTO request, and a `remote_work` search could never see
  it either. The topic-filtered search still runs first and still leads the ranking; when it returns
  **fewer than `k` hits** or **`k` hits that all sit in one document**, the rest is backfilled from
  an unfiltered search of the same query — deduped by `chunk_id`, documents not yet represented
  first, capped at `k`; in the single-document case the top `ceil(k/2)` filtered hits keep their
  slots. `topic_backfilled` and `backfill_reason` (`fewer_than_k` | `single_document` | `null`) are
  on the tool result and on the §10.2 `retrieval` payload, both defaulted so rows written before the
  change still parse. `mcp/tools/search_policy_documents.schema.json` was regenerated deliberately;
  `doc_ids` is untouched and remains a hard filter.
  **Measured effect, live:** demo task 1 went from **2 to 3** distinct cited documents and demo task
  2 from **1 to 2**, with no prompt change and no change to `act.j2`.

- **Both demo stub scripts are now REAL recordings** (`tests/fixtures/llm_scripts/demo_task_{1,2}.json`),
  recorded 2026-09-10 against Anthropic `claude-haiku-4-5` on the live app at 127.0.0.1:8000. Only
  the opaque provider call ids are re-minted (`ProposedToolCall` is `{name, args}`, so the span
  record does not keep them); every purpose, text, tool argument, finish reason and token count is
  the provider's own. **Three** recordings of demo 1 at temperature 0 produced byte-identical tool
  sequences, so the shape below is the model's behaviour and not one sample:
  - demo 1 — `lookup_employee_profile` + `check_policy_compliance` in one act step, an act step that
    answered in prose and was pushed back by the `WORKFLOW_INCOMPLETE` reminder, then five
    `search_policy_documents` calls. `get_policy_section` is never called. 6 citations across
    `remote-and-hybrid-work`, `tax-and-location-addendum`, `manager-approval-matrix`.
  - demo 2 — `check_pto_balance` + `check_policy_compliance`, two `search_policy_documents` calls,
    the gated `create_mock_hr_ticket`, then the confirmed write. `lookup_employee_profile` is never
    called. 3 citations across `pto-and-holidays` and `manager-approval-matrix`.

- **§18's `DEMO_EXPECTATIONS` now require only what the workflow genuinely needs.**
  `get_policy_section` is optional on demo 1 (a search hit carries the whole chunk, not the
  320-character display snippet, so repeated searches ground the answer just as well);
  `lookup_employee_profile` is optional on demo 2 (the persona already carries the employee id and
  `check_pto_balance` answers the question); demo 2's `search_policy_documents →
  check_policy_compliance` edge is dropped (the engine returns citations of its own, so grounding
  the prose afterwards is a legitimate order). The `min_distinct_docs_cited` floors — **3** and
  **2** — were *not* touched, and both are met by the committed recordings.

- **Demo 1's answer carries no `escalation` block.** It states the Tax & Legal review and the
  director approval as cited `policy_fact`s instead. That is a labelling preference, not a missing
  capability, so the block-type assertion was to move to a demo-2 test that does produce one.
  (It did not: the assertion was dropped from demo 1 in this round and only *landed* on demo 2 in
  the following fix round — see "P10 fix round 3" below.)

- **`check_policy_compliance` normalises `destination_country` to an ISO 3166-1 alpha-2 code at the
  wire boundary.** `corpus/rules.yml`'s `remote.intl.destination` compares with `in` against the
  code list `DE,IE,NL,PT,ES,CA,MX`, and every live recording shows `claude-haiku-4-5` sending
  `"Germany"` — a wrong verdict produced by a spelling. The seven approved destinations are
  recognised by name in the spellings the corpus itself uses, a bare two-letter code is upper-cased,
  and anything else passes through untouched. The `tool_call` span keeps the caller's own bytes.

- **THE HARNESS IS NOW TWO-PASS (§13.2).** `make eval` / `--variant <v>` drives the 26 items and
  writes the run with `judge_status: "pending"` and no judged metrics; `python -m evaluation.runner
  --judge <run_id>` computes the judged half afterwards from the stored run plus the trace store,
  idempotently, re-driving nothing. A judge pass will not start until the provider answers **eight
  consecutive** bare probes. **`strict_pass_rate` is `null` on a pending run and `REPORT.md` renders
  "not computable — judge pending", never a number** — every clause of §13.8's composite is
  vacuously true for an item that does not define it, so an unjudged run would otherwise publish a
  figure that is high *because less was checked*.

- **GEMINI JUDGE OUTAGE AND FREE-TIER CAP, measured 2026-09-10.** `gemini-3.5-flash-lite` on
  `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` returned HTTP 500
  `INTERNAL` on almost every call from ~08:55 UTC, *intermittently* (a bare no-schema probe of
  `gemini-3.5-flash` succeeded 1 time in 3 at 09:25 UTC), and then 429 `RESOURCE_EXHAUSTED`:
  `Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests,
  limit: 500, model: gemini-3.5-flash-lite`, quotaId
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue "500"`, dimension
  `model=gemini-3.5-flash-lite`. `GET /v1beta/openai/models` answered 200 throughout and lists the
  model, so the key, the endpoint and the model id were never at fault. **The cap is per model, per
  project, per day**, and a judged 26-item baseline costs ~252 judge calls (26 decompose + one
  groundedness call per policy claim + one citation-support call per cited claim + 26 gold-fact
  entailments — the §13.3 per-claim fan-out, *not* retries: the repair loop is already capped at one
  retry per prompt, §13.7). Two judged baselines therefore do not fit in one free-tier day.
  A second Google project (the key in `LLM_FALLBACK_API_KEY`, essentially unused because Anthropic
  is the primary agent) has its own 500/day, and the controller ruled that today's judge calls be
  served from it with the model pin unchanged. That project's quota was never the constraint — the
  **outage** was: at 03:19 and again at 03:31 and 03:47 PDT, ten bare no-schema probes two seconds
  apart returned 500 `INTERNAL` seven times out of ten, and a schema-constrained probe behaves the
  same, so it is neither our request shape nor a quota. The committed baseline therefore ships
  `judge_status: "pending"` with the exact re-run recipe in `REPORT.md`.

- **§13.3's evidence set widened to everything the synthesis prompt carried.** It was the
  `retrieval` spans alone, which scored a correct fact the agent had read out of the employee's own
  benefits record as *unsupported* — penalising exactly the behaviour §9.6's workflows require — and
  made the §13.7 blind reference labels disagree with the judge by construction, since the two were
  shown different evidence. `evaluation/runner.py::_evidence_of` now returns four labelled classes:
  `retrieval` (the **whole** stored chunk, resolved through `core/corpusread.py`, never the
  320-character display snippet), `section` (`get_policy_section`), `compliance`
  (`check_policy_compliance` requirement evidence) and `structured_data` (`lookup_employee_profile`
  / `check_pto_balance` / `lookup_benefits_status`). A claim is supported if any item of any class
  supports it, and the judge prompt says so. `search_policy_documents` and `list_policy_documents`
  envelopes are excluded — the first is display snippets of chunks already present in full, the
  second returns titles and grounds nothing. The citation-support pass still indexes `retrieval`
  alone, because a chunk id is the only thing an answer can cite. The §13.7 labelling packet calls
  the same `_evidence_of`, so packet and judge cannot drift.

- **A chunking observation, from the blind labeller.** `c_f7ec2fe078c43c2d` (`workplace-conduct` ›
  Investigation Process) begins mid-sentence at *"of the report. Where an investigation will take
  longer…"*. That is §7.1's overlap window, not lost text: the head of the sentence —
  *"Investigations are targeted for completion within 30 calendar days of the report."* — survives
  in the overlapping sibling `c_faa7e3e074e0f281`, which the same search also retrieved. No figure
  is lost to the model or to the judge; a reader of the one chunk alone cannot see it.

- **A SIGTERM is a checkpoint, not a guillotine (§10.3).** `flush_open_turns()` closed every open
  turn and left the buffer closed, but under uvicorn a SIGTERM does not end the process: the server
  drains every in-flight request first. So the flush closed turns *under their own requests* — the
  next span raised `turn … is closed; reopen it before writing spans`, the answer degraded to
  §12.3's catch-all escalation, and a turn that completed was recorded as a process exit. On Render
  that was one broken answer per redeploy and per spin-down. Each buffer is now re-armed after its
  rows are written: nothing more arrives if the process really is dying and the row stays
  `error`/`error`, and if the request does finish its own `close()` overwrites that with the truth.

- **`canonical_arguments` moved to `core/canonical.py`.** `evaluation/deterministic.py` needs the
  same bytes the confirmation gate mints and §4.2 puts `evaluation/` on `core/` and the HTTP API.
  `mcpserver/confirm.py` re-exports it, and `tests/architecture/test_conventions.py` now greps
  `evaluation/**` for any import of `hrmosaic.{mcpserver,agent,web}`.

- **The synthesis prompt gained rules 8-9 and a CITATION COVERAGE block** — the inventory of citable
  documents the answer is being asked to cover, quarantined chunks excluded. Goldens re-recorded.

- **A judge pass now aborts on a flapping provider instead of grinding through it.**
  `JUDGE_FAILURE_BUDGET = 3`: a fourth lost verdict raises and writes **nothing**, so the run keeps
  the clean `pending` state the drive pass gave it. A judged 26-item baseline costs ~252 provider
  calls against a 500/day cap, so a pass that grinds on losing verdicts spends half of the day's
  only other attempt. The eight probes of the gate are also **spaced two seconds apart** now: fired
  back to back they proved only that the provider was up for 300 ms, which is exactly how the first
  gated pass got through and then met 500 on its first real call.

- **THE THREE COMMITTED RUNS** (all `target: local`, one `dataset_sha`, drive-only, same tree):
  `r_1789032950_baseline` ($0.4355, 547 s, `judge_status: pending`),
  `r_1789033498_dense_only_k2` ($0.4159, 609 s) and
  `r_1789034108_no_structured_tools` ($0.4650, 600 s). Baseline deterministic headline:
  **DocRecall 0.842** (0.746 before the soft topic filter), workflow completion **0.808** (0.731),
  `cit_resolve` 0.923, ToolSelection 0.926, `arg_correctness` 1.000, action-safety 1.000,
  `nudge_rate` 0.115, `blocks_dropped_by_g2` 1, injection quarantined, p50 17.7 s. 18 of the 26
  items pass every clause of §13.8 that does not need a judge; the composite itself is withheld
  until the judge pass runs.

- **`make ablation` is still the null result**, and the arm still did not move: workflow completion
  baseline **0.808** vs `no_structured_tools` **0.615**, delta **−0.192** against §13.9's 0.25
  threshold, so `REPORT.md` carries the not-supported banner and the target exits 1. What moved is
  the baseline (0.731 → 0.808), not the arm.

- **Over-refusal cause, named and counted.** Exactly one baseline item, `remote-003`, refused with
  *"no policy evidence was retrieved"* while `check_policy_compliance` had already returned a
  decided verdict whose **eight** citations all resolve to real chunks of the committed index. G1's
  evidence gate weighs `turn.citable()` — the retrieved chunks — so the engine's own evidence,
  which the synthesis prompt does carry, cannot clear it. `evaluation/deterministic.py::
  compliance_evidence_ids()` makes it countable and `runner.assemble()` publishes the count and the
  item ids as a run note. Counting compliance-resolved chunks as citable evidence for G1 is a
  candidate P11/P12 fix; nothing about G1 changed in this round.

- **The blind reference labels were re-authored twice, and the second re-author is the one that
  counts.** The first packet showed the labeller 320-character display snippets rather than chunks
  (see above); the second showed the retrieval class only. Both label sets were discarded.
  `evaluation/reference_labels.yaml` now carries labels authored against the four-class evidence
  set, by a fresh session that read only the packet, built from the run while it was still
  `judge_status: pending`. `judge_agreement_rate` is computed by `--recompute-agreement` once the
  judge pass lands.

- **Live spend for this round: about $1.55** — three 26-item sweeps at $0.4355 / $0.4159 / $0.4650,
  five live demo recordings (three of demo 1, two halves of demo 2) at roughly $0.01 each, and one
  abandoned sweep stopped after 5 items. The judge is free.

## 2026-09-10 — P10 fix round 3 (the demo-2 escalation assertion, judge-pass notes, a pending-safe flip list)

- **The demo-2 `escalation` assertion actually landed this time.** Fix round 2's entry above, the
  P10 report's §12 item 4 and the commit message all said the block-type assertion had "moved to
  demo 2". Only half of that happened: demo 1 stopped asserting it and demo 2 never started, so a
  capability three artifacts claimed was covered was covered by nothing. The recording does produce
  the block — `tests/fixtures/llm_scripts/demo_task_2.json` synthesises an `escalation` reading *"I
  cannot open PTO requests in MosaicOne on your behalf"* — and
  `test_demo_task_2_pto_request_through_confirm_to_write` now asserts it, on the reopened turn's
  answer where it exists rather than on the gated proposal. The round-2 CHANGELOG entry and the P10
  report are corrected in place; the commit message cannot be, having been pushed.

- **`--judge` no longer throws away the notes the judge pass produced.** `judge_run` restores the
  drive pass's provenance onto the file it rebuilds, and notes were being *replaced* rather than
  *unioned*: the `judge/reference disagreements: …` line that only a judged run can produce never
  reached the file, leaving `--recompute-agreement` as the only route by which it ever appeared.
  `_merge_notes()` keeps both halves and skips anything the file already carries, so the pass stays
  idempotent — three applications are byte-identical, which `tests/unit/test_two_pass_judging.py`
  now asserts, alongside a test that an aborted pass (`JUDGE_FAILURE_BUDGET + 1` lost verdicts)
  writes neither the run file nor `REPORT.md`.

- **REPORT.md's flip list is `not computable — judge pending` while the baseline is.** It was being
  computed from the pending baseline's per-item `passed`, which is the same *vacuous* `strict_pass`
  §13.8 withholds the composite over — every clause needing a judge is trivially true on an
  unjudged item. Six items were listed as flipping against a baseline whose pass state had not been
  measured. `evaluation/ablation.py::_flips()` now returns `null` in that state and
  `render_section()` says so and names the recipe. Regenerated with `make ablation`; the only
  changes are that list and `comparison.json`'s `generated_at`.

- **`backfill_reason` is set only when the widening added a hit.** `search_policy_documents` emitted
  it whenever a widening was *attempted*, while `topic_backfilled` reported whether anything was
  actually added — so a search whose unfiltered pool had nothing new claimed a widening the model
  never saw. The two fields now move together, in the tool result and in the `retrieval` span;
  `mcp/tools/search_policy_documents.schema.json` is regenerated for the changed description.

- **`core/trace.py::_flush()` says why it pops before `rearm()`.** The buffer is removed from
  `_open` before `flush_open_turns()` re-arms it, so the `atexit` hook after a SIGTERM finds no open
  turn: spans written after the checkpoint on a turn that then dies are lost, while the
  `error`/`process_exit` row §10.3 guarantees is already written and survives.

## 2026-09-10 — P11 Deployment (the image, the manifests, the provisioning scripts)

**No live deployment exists yet.** User gates 2 (Render account + GitHub App), 3 (Turso platform
token) and 4 (Render API key) are all still open, so everything that needs an account is listed in
`NEEDS-FROM-USER.md` with the exact command that runs once it lands. Everything that does **not**
need an account was built, run and measured here.

- **The 512 MB memory gate, measured 2026-09-10.** `make docker-run-512` — `docker run -m 512m
  --memory-swap 512m`, `/ready` polled green, one stubbed `POST /chat` through the access gate,
  then `/health` — reports **`rss_mb = 294.9`** against the §14.3 assertion of `< 420` and a budget
  of 345 MB: **217 MB of headroom** under the hard 512 MB cgroup limit. That is the figure the
  image built from this phase's final commit reported; its second run read 293.0 MB, and six
  earlier runs the same day, each on the image built from the commit whose `git_sha` that run
  printed, read 290.4, 291.3, 292.1, 292.1, 292.2 and 292.9 MB — a 4.5 MB spread across eight
  builds, so the figure is stable to a few megabytes. The reading is `/proc/self/status` `VmRSS` inside the container (Docker Desktop's
  `linux/arm64` VM, Docker
  29.6.1), i.e. the same real-Linux reader P1's entry describes, not the macOS `getrusage`
  high-water mark. The equivalent numbers on Render's `linux/amd64` builder are re-read at gate 2.
- **Two of the three evidence screenshots are committed.** `docs/evidence/mcp-discovery-4-tools.png`
  is §13.9's ablation catalog; `docs/evidence/mcp-discovery-page.png` is RUBRIC5.2's figure —
  `/dashboard/mcp` rendering live discovery against the running image: the server card (`connected
  yes`, protocol `2025-11-25`, a 32 ms handshake, 9 tools), all nine tools with their
  `input_schema` / `output_schema` / `annotations`, and the handshake-history row a real turn wrote.
  The third, `docs/evidence/ci-deploy-skipped.png`, needs the R8.4 red run and therefore a push.
- **Cold build wall-clock, measured 2026-09-10** on macOS arm64: `docker build --no-cache` takes
  **171.5 s** — `pip install` 46.2 s, the fastembed model bake 7.3 s, `ingest --verify-manifest` +
  `index --selftest` 107.6 s, export 9.5 s. At ~3 minutes a build the 500 included Render pipeline
  minutes are ~165 builds a month, which is the headroom arithmetic §14.1 asks `deployed.md` to
  carry.
- **Boot segments inside the container, measured 2026-09-10:** container start → `/health` 200 in
  **2.2 s**; `/health` → `/ready` green in a further **0.5 s** (a second run on the same image:
  2.1 s and the same 0.5 s). That half-second is what baking the ONNX model into the image buys
  against a 16–63 s download. Both segments are read off the same gate run `deployed.md` pastes
  verbatim, so the published figures and their evidence are one measurement.
- **`${PORT}` expansion proved on the real image.** `docker run -e PORT=10000` →
  `/health.mcp.connected: true` with `url: http://127.0.0.1:10000/mcp-server/mcp` and
  `tool_count: 9`. The `sh -c` form of `CMD` is what makes that work; the exec form would hand
  uvicorn the literal string `${PORT}`.
- **§3.1 rows P11 owns, re-read live on 2026-09-10** (full quotes and sources in `deployed.md`):
  Render **750** free instance-hours per workspace per calendar month and a **15-minute** spin-down;
  **500** included pipeline minutes on a Hobby workspace, after which "Render stops running pipeline
  tasks (including service builds!)" without a payment method; Render's documented request ceiling
  is **"HTTP responses to take up to 100 minutes"**, three orders of magnitude above
  `AGENT_WALL_CLOCK_S = 90`, so no change was needed; Turso free is **100 databases · 5 GB · 500 M
  rows read · 10 M rows written per month**. The Gemini judge-quota row is **still unreadable
  without an authenticated AI Studio session** and remains recorded as unverified.
- **P5's carry-forward is closed.** `mcp/run_stdio.sh` and `mcp/run_http.sh` default to
  `${PYTHON:-.venv/bin/python}`, a path that does not exist in the image; the Dockerfile now sets
  `ENV PYTHON=python`. Verified by piping an `initialize` frame into `docker run … sh
  mcp/run_stdio.sh` and reading back `serverInfo.name = mosaic-hr`.
- **P9's carry-forward is closed twice over.** `pyproject.toml` declares `hrmosaic.web`'s
  `templates/` and `static/` as package data for the non-editable case, the Dockerfile asserts both
  paths exist at build time, and CI's `docker` job renders `GET /` and `GET /dashboard` (page 1,
  which performs an MCP handshake on load) plus `GET /static/app.css` against the running image.
- **P0's `.dockerignore` negations are proved against Docker's own matcher**, not against a reading
  of the file: `COPY tests/fixtures/llm_scripts/` and `COPY data/index/chunks.manifest.jsonl` fail
  the build outright if `!tests/fixtures/llm_scripts/` or `!data/index/chunks.manifest.jsonl` stops
  re-including its path, and a `RUN test -f` after them fails if the paths arrive empty.
- **Render publishes no usage or billing API endpoint** (checked against `api-docs.render.com`'s own
  index on 2026-09-10), so `scripts/check_render_hours.py` *derives* both budgets — instance-hours
  by integrating `GET /v1/resources/metrics/instance-count` over the month to date, build minutes
  from the wall-clock of each deploy — and labels both as approximations of the dashboard's own
  numbers. It warns and never fails, per §14.1.
- **Render publishes no deploy-hook endpoint either.** `provision_render.py` sets the other two
  repository secrets and prints copying the hook from Service → Settings → Deploy Hook as the single
  remaining manual step, rather than pretending to have retrieved it.

## 2026-09-10 — P10 fix round 4 (judged fixtures, the label-packet builder, a disclosed hard-case judge subset)

- **The dashboard's eval fixtures are regenerated from the judged runs, by a committed script.**
  `scripts/refresh_eval_fixtures.py` rebuilds `tests/fixtures/eval_runs/r_p9fixture_<variant>.json`
  from the three committed P10 runs: six item rows copied verbatim, the run-level metrics re-derived
  over exactly those six by `Runner.assemble()` — the shipped aggregation, not a second description
  of it — and three synthetic `cold_probe` rows that each fixture's own note declares as the file's
  only invented content. The baseline fixture now carries `judge_status: judged` and real judged
  aggregates, so page 11's "not judged on this variant" assertions test the real distinction rather
  than a hand-set flag. Promoting the script is the point: the fixtures were derived artifacts that
  nobody could re-derive.

- **The blind labelling packet is built by a script in the repository too.**
  `scripts/gen_label_packet.py` reads three things and nothing else — the dataset, the run file's
  served answers, and the trace store — and calls `evaluation.runner._evidence_of` rather than
  re-deriving the evidence, because there is exactly one definition of "what the judge scores
  against" and a builder that re-implements it has already been wrong twice. `--subset seed`
  (default, `SEED = 1729`, unchanged) or `--subset judge_lowest`, with `--n`.

- **`judge_agreement_rate = 1.000 (n = 7)` was not the validation it looked like, and the report now
  says so from the data.** All seven compared items were a unanimous `grounded`: the agreement
  matrix had no discriminating cell, so the figure could not separate a good judge from one that
  answers `grounded` to everything. `evaluation.schema.judge_lowest_subset()` adds a second subset —
  the 8 gold-`answer` items with the **lowest judge groundedness in the run**, ties broken by item
  id — labelled blind from the same packet shape by the same independent model, and published as its
  own metric: **`judge_agreement_rate_hard` = 0.875 over n = 8**, one disagreement (`inj-001`:
  reference `grounded`, judge `not_grounded` at 0.833). The price is that the *selection* uses the
  judge's own scores and is therefore not blind. That is disclosed rather than smoothed over —
  `protocol.selection_disclosed: true` in `evaluation/reference_labels_hard.yaml`, both figures side
  by side in REPORT.md with their `n` and their subset definition, and never merged or averaged. The
  packet itself withholds the criterion and renders the items in item-id order: told "these are the
  eight the judge liked least", a labeller drifts toward `not_grounded` and manufactures the very
  disagreement the subset exists to detect.

- **`python -m evaluation.runner --recompute-agreement` takes `--metric` and `--labels`**, driven by
  a two-row table in `evaluation/schema.py`; it refuses to fold one subset's labels into the other's
  metric (`protocol.subset` is checked against the metric), and each figure's note in the run file is
  replaced idempotently without disturbing the other's.

- **REPORT.md attributes every §13.8 failure instead of only reporting the gap.** Strict pass rate
  0.654 is 0.196 below the ≥ 0.85 target, and the nine failing items now carry the clause each of
  them tripped — `inj-001` groundedness 0.83 < 0.85, `pto-002` a `policy_fact` block dropped by G2,
  five tool-recall shortfalls, five incomplete workflows, two behaviour mismatches. They are
  recomputed from the committed per-item scores by `deterministic.strict_pass_causes()`, which
  `strict_pass()` is itself now defined in terms of, so the cause column and the `passed` flag are
  one computation and cannot disagree.

- 2026-09-10 — P11 fix round (gitleaks false positives, the ablation block after the judge pass, two review minors): the three `curl-auth-header` findings were throwaway container tokens, not secrets, so the `Makefile` now builds its memory-gate header into `$AUTH_HEADER` *before* the `curl` and passes `-H "$AUTH_HEADER"` — nothing token-shaped is left on a curl line for the rule to read — while `.gitleaks.toml` carries one `[[allowlists]]` entry (`condition = "AND"` over the rule, the two build files and three line shapes) for the copies commit `16edf18` will hold for ever, and `ci.yml` pins `GITLEAKS_VERSION: 8.30.1` because the action's default **8.24.3** predates the `targetRules` form and because an unpinned scanner ruleset is what turned run 34481667075 red on a commit that touched nothing relevant. Verified with gitleaks 8.30.1: full-history `detect` **no leaks found**, the `--no-merges --first-parent` range scan CI runs **no leaks found**, a planted `sk-ant-api03-…` key under `src/` still caught, and — the check that says the carve-out is narrow — a *different* token behind `Bearer` in the `Makefile`, and `ci-access-token` in a file outside the two paths, both still caught. `make ablation` re-run now that the baseline is judged, so `evaluation/REPORT.md`'s ablation block carries the real baseline column (0.985 / 0.899 / 0.654) and a real eight-item flip list in place of `judge pending`, and the judge-methodology prose adds the caveat that the two agreement subsets share four items (`benefits-001`, `benefits-002`, `conduct-001`, `expenses-001`) and are therefore not independent samples; folding the blind subset back in also filled the `judge_agreement_subset` field, which had stayed `null`, and exposed that `_agreement_note`'s legacy-format cleanup never fired without `re.MULTILINE` (it appended a second copy of the note instead of replacing it). `scripts/provision_turso.py` prints `parity smoke: round trip ok` only once `report.problems` is clear — it used to announce a successful round trip one line above `FAIL — the database was created but is not usable` — and carries its sibling deploy scripts' `REPO_ROOT` bootstrap. `deployed.md`'s boot table (**2.2 s** container start → `/health`, **0.5 s** on to `/ready`) and its memory figure (**294.9 MB**, 217 MB of headroom; the same image's second run read 293.0 MB) are re-read off *this* commit's own image and stated to come from the run pasted beside them, so the published figures, their evidence and CHANGELOG's P11 entry are one measurement rather than three.

- 2026-09-10 — R8.4 deploy-gate evidence: branch `ci-red-evidence` (a deliberately failing test) dispatched with `deploy_only=true`; run https://github.com/seantmalone/quantic-mosaic/actions/runs/34485304411 shows `test` failed and `deploy` **skipped** (dependent job failed) with `lint` and `docker` green; screenshot committed as `docs/evidence/ci-deploy-skipped.png`.

- 2026-09-10 — P12 documentation fix round: `test_docs_completeness.py` now scopes the results assertions to the text between the `EVAL-NUMBERS` markers and checks them against the live `ROWS` table in `scripts/paste_eval_numbers.py` (deleting the block used to leave the old substring search green — verified by mutation); `ai-tooling.md` is held to its three `##` headings plus four distinct workflow facts (probes/proposals/judge panel, implementer → reviewer → fix rounds, blind labelling by separate sessions, and at least three concrete failures named under *What did not work*); all three `docs/evidence/*.png` are asserted to exist, and `design-and-evaluation.md` and `deployed.md` now carry run https://github.com/seantmalone/quantic-mosaic/actions/runs/34485304411 beside `ci-deploy-skipped.png` instead of forwarding to `CHANGELOG.md`. Gate numbering is `NEEDS-FROM-USER.md`'s throughout — recording is **gate 6**, submission **gate 7** — corrected in the test's docstring and in every G-number in `docs/requirements-traceability.md`, whose 87 rows are now **72 `built`** (verification green in CI at this commit) and **15 `planned — verified at publish`** (R7.1, SUB.1–SUB.3, DEMO.1–DEMO.7, RUBRIC5.1, 5.3, 5.6, 5.9 — the rows that need the live URL, the recording or the submission). `scripts/paste_eval_numbers.py` picks its fallback baseline run by the `created_at` inside the file (falling back to the `r_<epoch>_` run id, both normalised to seconds) rather than by `st_mtime`, which git does not preserve, with `tests/unit/test_paste_eval_numbers.py` pinning it; `deployed.md`'s `## Cost` rows for Render and Turso read `pending: gate 2/4` and `pending: gate 3` instead of claiming a 2026-09-10 observation of services that do not exist yet; and the rotting literal test counts in `docs/demo-script.md`, `design-and-evaluation.md` and `ai-tooling.md` are now dated phrasings (1,652 tests on 2026-09-10).

- 2026-09-10 — P11c loopback MCP client timeouts, warm-up retry, `/ready` in the smoke: `GET /ready` had been permanently **503** on every deploy since the first one — `{"ready": false, "reason": "warm-up call failed: search_policy_documents could not be called: SSE stream ended without a response"}` fifteen minutes after boot, while `/health` was `ok` with `degradations: []` and the index loaded (14 docs, 204 chunks) and a `POST /chat` answered 200 in 26.3 s. The evidence is in Render's own logs: the boot at 17:29:05Z handshakes over the loopback Streamable HTTP mount, issues the warm-up `tools/call` at 17:29:06Z, and logs `GET stream disconnected, reconnecting in 1000ms...` at 17:29:11Z — **five seconds** later, the same interval as the 17:02:45Z boot. Cause: `agent/client.py::_http_client` built `httpx2.AsyncClient(headers=…)` with no `timeout=`, so httpx2 2.12's default `Timeout(5.0)` applied to the read as well, and a Streamable HTTP `tools/call` holds its response stream open until the result arrives — on a 0.1-CPU free instance the first embed loads the ONNX session for longer than that (2.6 s locally, which is why no local gate ever saw it). It now passes `LOOPBACK_TIMEOUT = httpx2.Timeout(30.0, read=300.0)`, the same 30 s connect/write/pool and 300 s read the SDK's own `create_mcp_http_client` uses. The amplifier is fixed too: `web/main.py::_warm_up` gave the warm-up `call_tool` exactly one attempt, so a single failure latched `ready = False` for the life of the process — the call now retries every `WARMUP_RETRY_S` (1 s) inside the same `READY_WARMUP_TIMEOUT_S` (30 s) deadline the handshake already used, checked **between** attempts so a call on the wire is never cancelled. And nothing in the deploy path had ever looked at `/ready`: `scripts/smoke_deployed.py` now polls it until 200 within `--ready-timeout` (default 600 s, `SMOKE_READY_TIMEOUT_S`) and fails the smoke quoting the `reason`, so the next occurrence turns CI red instead of hiding behind a green `/health`.

- 2026-09-10 — P13 review fixes (round 1): two findings from the task review of P13. **Finding 1** `_rehydrate` now re-runs `_engine_evidence` over the compliance `tool_call` span, the same line `_absorb` runs live. R7 made engine evidence count towards §9.3's predicate and G1, but it is scored rather than retrieved and so never reached a `retrieval` span: a `pto_request` turn could ground itself on the engine, close as complete, park at §8.6's confirmation gate and then be refused with `no policy evidence was retrieved` on a write that had already happened. New fixture `compliance_confirm_resume.json` and three integration tests park on engine evidence, resume through the confirmation and assert the answer is not refused and that the resumed synthesize prompt still carries every engine chunk id. **Finding 2** `SEARCH_BREADTH` fires at *at most* one search but opened "you have searched the corpus once", so a turn that had searched none was told, in a prompt, about a search it never made. The approved firing condition is kept and the opening clause now states the real count — `SEARCH_BREADTH` / `SEARCH_BREADTH_UNSEARCHED` share one string for the debt itself, so the two forms cannot drift. Spec §9.1 carries both.

- 2026-09-10 — P13 prompt and orchestration hardening for `claude-haiku-4-5`: seven changes from the trace-level analysis of the judged local baseline (`r_1789032950_baseline`) and the deployed baseline (`r_1789055103_baseline`), which fail the same eight dataset items for the same causes. **R1** `route.j2` carries a CORPUS paragraph under the `out_of_scope` field naming the exact titles of the 14 indexed documents, rendered from `prompts.corpus_titles()` (the `documents` table `list_policy_documents` reads, asserted against the committed manifest) and keeping "and only covers" — targets `equipment-001`, the router's out-of-scope guess about a library it had never been shown. **R2** `synthesize.j2` rule 6b: a balance, accrual, date or eligibility value from a `<tool_result …>` envelope is employee data, stated with its `as_of` and carrying **no** citation — targets `pto-002`, whose balance was cited, stripped by G2 and dropped with its block. **R3** a third act-loop reminder, `search_breadth`, sent at most once per turn on a step where neither other reminder fired, while retrieval is permitted and the turn has searched at most once: the corpus is federated and one query reaches one or two documents — targets `remote-002` and `expenses-002` (two cited documents, three required); `nudge_rate` rises by design. **R4** §9.2's G1 recovery step now appends one deterministic message saying why the answer was refused and that only a searched passage can be cited, recorded as `g1_recovery` in `nudges` — the reopen used to append nothing and re-sent the conversation that had just produced the ungrounded answer; targets `remote-003`. **R5** `pto_request.is_complete` now requires a `lookup_employee_profile` result, the slot §9.3 always listed first — targets the `pto-003` and `unsafe-001` end states; disclosed in §13.9 because `no_structured_tools` disables the newly required tool. **R6** the router's `needs_clarification` line asks for EVERY missing detail in `rationale_summary`, because the question the user is shown is built from that line — targets `amb-003`. **R7** G1's candidate set now includes the compliance engine's per-requirement evidence: each committed `chunk_id` is resolved against the index, scored on the same dense path retrieval uses, run through G4 and passed to `note_evidence` exactly like a retrieved candidate, at a cost of one embedding per compliance result — the rule and both thresholds are untouched, a chunk below the bar still refuses, and the engine's top-level `citations[]` is still not evidence; targets `remote-003` alongside R4.

- 2026-09-11 — P13 measured: the seven Haiku mitigations, deployed on `b24ad32` and re-driven over the same 26 items against the same live instance (`r_1789069158_baseline`, judged), moved **strict pass 0.692 → 0.808**, groundedness 0.979 → 1.000, citation accuracy 0.847 → 0.914, document recall 0.855 → 0.974, tool selection 0.926 → 0.987, workflow completion 0.769 → 0.846 and over-refusal 0.111 → 0.000. The disclosed price is in two rows: the breadth reminder now fires on most single-search turns (`nudge_rate` 0.115 → 0.577) and each of those spends one more act step, so p50 rose 17.6 s → 22.6 s even with the service limiter raised; the tail improved (p95 47.7 s → 39.2 s) because the worst turns stopped stalling. The `no_structured_tools` ablation delta moved −0.154 → −0.192 against the pre-registered 0.25 bar, and the arm's **meaning** changed with R5, which is stated beside every figure rather than folded into them. This column carries no human-agreement figure by ruling: the blind reference labels are re-authored once, for the final published run.

- 2026-09-11 — P14, performance Wave 1 (1,745 tests): the query-embedding memo (the same question was being embedded twice on most turns — ≈270 ms per affected turn on 0.1 CPU), trace-store reads off the request path, `MODEL_PRICES["gemini-3.5-flash-lite"]` corrected to the paid standard rates ($0.30 / $2.50 per MTok) now that the judge project is billed, a publish gate that refuses to publish a run containing any provider failover or retry, and the limiter documented with the account limits actually read from Anthropic's response headers (10,000 RPM / 10M input tokens per minute against our self-imposed 10 RPM). Spec §14.4's warm-turn expectation was corrected from a **stub**-model figure (~1.5–5 s; the stub's own mean is 292 ms) to the measured **22.5 s** on the free instance.

- 2026-09-11 — P15, performance Wave 2 A–D (1,767 tests), one commit per lever: the act loop's closing step writes one sentence instead of a discarded 224-token answer (nearly half of all act-loop output tokens were an answer nothing read); the synthesis output diet on the two de-risked clauses; a search hit carries the **whole** passage so a `get_policy_section` round trip disappears — with the quarantine shield kept, so a poisoned chunk's text still never reaches the model; and the model-facing tool envelopes drop telemetry keys behind one shared definition of which envelopes count as evidence. Item 0 first: `embed_query_with_meta` decides the memo hit **inside** one locked lookup, because the old counter-diff attributed a concurrent thread's hit to this retrieval and would have reported ≈390 ms of real ONNX work as free.

- 2026-09-11 — P16, performance Wave 2 E and the live narration (1,814 tests): the answer streams to the browser block by block and is replaced by the guardrailed final version when G6 finishes — the streamed text passes G6 **before it leaves the process**, not after; the rail narrates each step as it *starts* ("Searching the policy library…", "Checking your PTO balance…", "Writing the answer…") from one label mapping, on the existing single-listener SSE seam; and §10.5's per-string span cap goes 8 KB → **24 KB** so a k=5 search result, ≈8.3 KB since W2-C, is stored whole instead of being badged truncated on every dashboard. Verified against the real Anthropic API on a local server (tests cannot prove a stream): first answer block arriving while later blocks were still being written, 11 progress lines, 4 answer-delta frames, 24 span frames, a fully cited answer, no errors.

- 2026-09-11 — The published run, after Waves 1 and 2 on one deploy (`da0dca2`): `r_1789086979_baseline`, judged, 249 judge calls. **Strict pass 0.808** (target ≥ 0.85), groundedness 0.982, citation accuracy 0.925, partial match 0.852, document recall 0.974, tool selection 0.992, workflow completion 0.846, action safety 1.000, over-refusal and missed-refusal both 0.000, **p50 16.7 s** (before 17.6, after-P13 22.6) and **p95 32.4 s** (47.7, 39.2). The performance waves gave back the five seconds the quality fixes cost at the median and cut the tail by a third with no quality metric moving more than noise. Blind reference labels were re-authored for these answers before the judge ran: agreement **1.00 on the seed subset (n=8)** and **0.875 on the hard `judge_lowest_8` subset**, whose single disagreement (`pto-003`) is a real judge miss — the answer states a notice-counting condition the evidence does not contain and a deadline date no evidence item carries. Ablation: workflow completion −0.231 against the pre-registered 0.25 threshold, still **not supported**, with the arm's changed meaning stated beside all three figures. Five items still fail strict pass: `inj-001` and `remote-004` lose a block to the citation guardrail, `expenses-002`, `onboarding-001` and `remote-003` miss the three-distinct-documents end state.

- 2026-09-11 — Publish step: the live values are in the graded documents. Deployed at `https://mosaic-hr-copilot.onrender.com` on `plan: free` (asserted from the API's read-back, not the request), Turso `mosaic-hr` on the free Starter plan with `overages: false`, `LLM_RPM=60` / `LLM_BURST=30` on the service (the pre-optimization sweep recorded 3.9 s per turn of our **own** token-bucket waiting at 10, p90 12.2 s, against an account limit of 10,000 RPM). **Cold start, n=1, measured 2026-09-10 without keep-alive:** 44.8 s spin-up → `/health`, 2.8 s on to `/ready`, 23.3 s for the first `POST /chat` — **71.0 s** cold to first answer, **22.5 s** warm; two further probes are queued. Live `rss_mb` **293.6** at `/health`, 1.3 MB from the local gate's 294.9 and 126 MB below the 420 MB assertion. Render build minutes **~11.5 of 500**; instance hours are **unavailable from the API** for a free instance type (`/v1/metrics/instance-count` answers 200 with no samples), so the dashboard is the figure to read and `check_render_hours.py` says so rather than printing zero. Model spend across the twelve committed runs: **$6.84**, plus ≈ $0.09 for the two live demo turns.

- 2026-09-11 — Cold start, measured three times: the queued probes landed and the published figure is now n=3. Probe 2 (02:19Z) and probe 3 (02:37Z) ran on `da0dca2`, the build that served the published evaluation run, each after 1,000 s of deliberate idle and with no keep-alive on the service: 43.5 / 52.4 s spin-up → `/health`, 0.1 / 0.1 s on to `/ready`, 23.9 / 25.2 s for the first `POST /chat`, **67.5 / 77.6 s** cold to first answer, 22.5 / 23.9 s warm. With probe 1 (`bf85ffd`, 2026-09-10) that is a median **71.0 s** cold to first answer over a 67.5–77.6 s range and **22.5 s** warm, which supersedes the `n=1` line above everywhere it was published — `deployed.md`, `README.md`, `NEEDS-FROM-USER.md`, `design-and-evaluation.md`, `docs/requirements-traceability.md` and `docs/architecture.html`. The raw segments, with each probe's timestamp and sha, are committed as `docs/evidence/cold-start-probes.json`. Sean's ruling of 2026-09-10 20:40Z — publish the no-ping measurement, then add a GitHub Actions keep-alive pinging `/health` every ten minutes (≈ 744 of the 750 free instance-hours a month; exhausting them suspends the service rather than billing) — is now stated in `design-and-evaluation.md` and `docs/optimization-log.md` instead of being contradicted there. **The keep-alive workflow itself is not in the repository:** `.github/workflows/` holds `ci.yml` only, and every published cold-start figure is the behaviour with nothing pinging the service.
