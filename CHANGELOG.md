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
