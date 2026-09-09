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
