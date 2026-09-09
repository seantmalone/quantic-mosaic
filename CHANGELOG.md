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
