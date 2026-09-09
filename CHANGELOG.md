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
