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
