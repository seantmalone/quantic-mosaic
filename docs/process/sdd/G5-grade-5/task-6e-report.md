# Task 6e — `docs/architecture.html`: every figure back to a committed artifact

One file touched: `docs/architecture.html`. 28 insertions, 27 deletions. No new external
reference — `grep` for `src=`/`href=` pointing at `//` returns nothing, so the page is still
self-contained with no network access. Both `<script>` blocks pass `node --check`, and all six
`<svg class="dg">` subtrees parse as XML before and after (same result as `HEAD`, so nothing was
broken in passing).

Line numbers below are post-edit.

## 1. The CI workflow has five jobs, not four

Source of truth: `.github/workflows/ci.yml`. Its `jobs:` keys are `lint`, `test`, `ux`, `docker`,
`deploy`. `ux` is the only job with no `needs:`, and the workflow says why in its own comment above
the job:

> Its own job because it is the only thing in the repo that needs a browser binary, and `needs:` is
> deliberately absent — it must never block `test` or `deploy`.

`deploy` still carries `needs: [test, docker]`, so the deploy gate claim was already right.

| Line | Was | Now | Decided by |
| --- | --- | --- | --- |
| 1156 (glance strip, fig 6) | `4` — "CI jobs: lint, test, docker, deploy" | `5` — "CI jobs: lint, test, ux, docker, deploy" | `ci.yml` `jobs:` |
| 1362 (SVG group title) | `ONE FILE, FOUR JOBS` | `ONE FILE, FIVE JOBS` | `ci.yml` `jobs:` |
| 1397 (new line inside the `ci.yml` box) | — | `ux — the browser suite; needs: is absent, so it never blocks test or deploy` | `ci.yml` `ux` job + its comment |
| 1570–1571 (`D["f1-ci"]`) | "One workflow with four jobs"; `Jobs: lint, test, docker, deploy` | "One workflow with five jobs"; `Jobs: lint, test, ux, docker, deploy`; new `ux` row quoting the comment verbatim | `ci.yml` |
| 1338 (fig 6 `aria-label`) | "…lint, test, docker and deploy jobs" | "…lint, test, ux, docker and deploy jobs; the ux job carries no needs and blocks nothing" | `ci.yml` |
| 1349 (`workflow_dispatch`/PR tile) | "runs lint, test, docker" | "runs lint, test, ux, docker" (dropped to 9.5px so the string stays inside the 190px tile) | `on: pull_request` with no per-job `if:` |
| 1376 (`test` job tile) | "pytest -q (the whole suite)" | "pytest -q (all but the ux suite)" | `pyproject.toml` `addopts = … -m "not ux"` |

**Deliberate limitation, flagged:** the `ux` job is named by a text line inside the `.github/workflows/ci.yml`
box, not drawn as a fifth hoverable tile. The box is `520 × 330` with two `234`-wide columns and two
tile rows; a third row needs the box to grow ~60px, which would collide with the `GitHub repository
secrets` / `Render environment` tiles below it and require re-routing two edge paths (`f6-e-sec`,
`f6-e-env`) in a file I cannot render here. The count in the title is now true and the fifth job is
visible and named; it has no tooltip of its own. `D["f1-ci"]` in figure 1 carries the full detail.

## 2. The chat page has no span rail (UX W2)

Verified against `src/hrmosaic/web/templates/chat.html` and `_turn.html` before writing any label:

* the conversation (`#transcript` / `#messages`), one live region `#turn-status` ("the page's ONE
  live region"), and nothing else technical;
* `_turn.html:213` — `<h3 class="sources-heading">Sources ({{ turn.citations | length }})</h3>`;
* `_turn.html:192` — `<h3 class="confirm-heading">Confirm before anything is written</h3>`;
* `_demo_controls.html:93` — `<a class="demo-link" id="demo-dashboard-link" href="{{ last.turn.dashboard_url }}">Open this conversation in the dashboard</a>`;
* `_turn.html`'s own header records what W2 removed: the `▸ Agent activity — 28 steps · 7 tool calls
  · 6 model calls` disclosure and its 28 rows of span kinds, guardrail ids and raw tool JSON, and the
  five uppercase `POLICY FACT` chips — "the dashboard is the single home for the technical record";
* the act-as `<select>` and the two demo buttons are inside `section.demo-panel`, which
  `tests/contract/test_demo_controls_are_quarantined.py` (P8) pins there and nowhere else.

The SSE stream still exists (`chat.html:452` opens an `EventSource` on `/chat/stream`) but its only
consumer on the page is `setStatus(...)` — one label, not a rail.

| Line | Was | Now |
| --- | --- | --- |
| 1107–1109 (fig 4, "Demo narration" tile) | "the live span rail names tools, arguments, outputs, / retrieved sources and the final answer's basis / dashboard_url on every response opens the waterfall" | "the chat page shows the answer and its Sources (n); / tool names, arguments and outputs are on the session / page, which dashboard_url opens on every response" |
| 1508 (`D["f1-chatui"]` `Controls`) | "act-as selector …, citation chips, live span rail, Confirm / Cancel card, cold-start banner, two demo buttons" | the conversation, the `Sources (n)` strip, the confirmation card, one status line, the cold-start banner, and the quarantined demo panel's act-as selector / two demo-prompt buttons / "Open this conversation in the dashboard" link; plus a new `Not here` row naming `/dashboard/sessions/{id}` and `dashboard_url` |
| 1580 (`D["f1-e-sse"]`) | "a span rail makes the agentic layer visible on camera" | "span events let one plain status line say what the agent is doing right now — since UX W2 that line is all the stream writes to the chat page" |
| 1745 (`D["f4-c2"]`) | "so the rail is real time" | "so the chat page's status line is real time" |
| 1751–1752 (`D["f4-c5"]`) | "reading the rail aloud"; `Shown: tool names, arguments, outputs …` | "reading the session page aloud"; `Shown` now says those live on `/dashboard/sessions/{id}`, not the chat page, and `Hinge` names the "Open this conversation in the dashboard" link as that URL |
| 1748 (`D["f4-c3"]`) | "where a citation chip deep-links" | "where a cited chunk_id resolves" — W2 deleted the chips; a chat source link goes to `/policy/{doc_id}#{chunk_id}` (`_turn.html`'s `citation.source_url`) |

## 3. Other stale figures

Checked every number on the page. **No test count, no coverage percentage and no eval `run_id`
appears anywhere in the file**, so the new published run (`r_1790074972_baseline` on build
`8a89310`) needed no edit here. What was wrong:

| Line | Was | Now | Source that decided it |
| --- | --- | --- | --- |
| 500 (glance) | `~280` chunks in the index | `204` | `data/index/ingest_report.json` `totals.chunk_count = 204`; `wc -l data/index/chunks.manifest.jsonl` = 204; `design-and-evaluation.md:55, :206` both say 204. `~280` survived from the pre-implementation spec (`…2026-09-08-hr-agentic-rag-design.md:94`) |
| 1544 (`D["f1-index"]` `Contents`) | "~280 chunks over 14 documents" | "204 chunks over 14 documents" | same |
| 1818 (`D["f6-build"]`) | "instead of indexing ~280 chunks" | "instead of indexing 204 chunks" | same |
| 1835 (`D["f6-e-boot"]`) | "Indexing ~280 chunks took 15.8 s in the probe" | "Embedding and verifying the 204 chunks took 107.6 s on the two-CPU builder" | the 15.8 s figure exists in **no** committed measurement — only in the design spec, paired with the same `~280` estimate. Replaced with the measured build cost: `deployed.md:445` (`ingest --verify-manifest` + `index --selftest`, whole corpus embedded, 107.6 s), `design-and-evaluation.md:795`, `docs/process/sdd/P11-report.md:232` |
| 503 (glance) | `345 MB` — "peak RSS against a 512 MB cap" | `294.9 MB` — "measured RSS against a 512 MB cap" | 345 MB is the §14.3 **budget**, not a reading. The measurement is 294.9 MB (`/proc/self/status` `VmRSS` under `docker run -m 512m`): `deployed.md:486`, `design-and-evaluation.md:803`. Live `linux/amd64` reading is 293.6 MB |
| 1621 (`D["f2-s6"]` `G1`) | "refuses when max_dense_score < 0.32 or fewer than 2 chunks clear 0.26" | "< 0.60 … clear 0.45" | `src/hrmosaic/settings.py:109–110` (`min_evidence_score=0.60`, `min_support_score=0.45`), `.env.example:50–51`, `design-and-evaluation.md:649`. `settings.py`'s own comment: "The shipped 0.32 / 0.26 were below the model's cosine floor over this corpus, which made G1's score clauses unreachable (§21)" |
| 1649 (`D["f2-f3"]` `Thresholds`) | "MIN_EVIDENCE_SCORE 0.32, MIN_SUPPORT_SCORE 0.26" | "0.60 / 0.45 — calibrated at P10 from the observed dense-score distribution" | same |
| 310–311 (fig 1, route list) | `GET /dashboard/*  (11 pages, admin persona)` and `GET /api/traces/* …  (admin)` | `(11 pages, any persona)` and `(any persona)` | UX W1. `src/hrmosaic/web/api.py:210–212` — `needs_admin()` exact-matches the three write endpoints of `ADMIN_ROUTES`, "everything else is a read". The page's own `D["f1-dash"]` and `D["f1-access"]` already said so, so figure 1 was contradicting its own tooltips |
| 1582 (`D["f1-e-dash"]`) | "Both halves need the admin persona … hiding the nav link is presentation, not access control" | "One gate, not two (UX W1): both halves are open to any persona holding the access token, and the role is checked server-side on the three write endpoints alone" | same |

Figures checked and left alone because they are right:

* `9` MCP tools — nine modules under `src/hrmosaic/mcpserver/tools/`; `ci.yml`'s `assert_health`
  comment asserts `tool_count == 9`; README "nine tools".
* `14` policy documents in `4` formats, `11` markdown ingested — `ingest_report.json`
  (md 11 / html 1 / pdf 1 / txt 1 = 14); `ls corpus/` minus `README.md`, `facts.yml`, `rules.yml`,
  `*.src.md`.
* `6` guardrails `G1–G6` — `grep -ohE '\bG[1-6]\b' src/hrmosaic/agent/` yields exactly G1…G6.
* `9` span kinds — `src/hrmosaic/core/models.py:24–34`, the `SpanKind` literal, in the same order
  the page lists them.
* `11` tables — `001_initial.sql` (sessions, turns, spans, llm_messages, confirmations,
  mock_writes, llm_cache, eval_runs, eval_results, import_state) plus `schema_migrations` from
  `core/db.py:42`.
* `7` `check_policy_compliance` scenarios — `corpus/rules.yml` `scenarios:` has seven keys;
  `check_policy_compliance.py:203` says "Which of the seven scenarios to evaluate."
* `28` evaluation items and the exact mix `7 simple_policy · 5 multi_doc · 6 tool_task ·
  3 ambiguous · 5 out_of_scope · 1 unsafe_action · 1 sensitive` — recounted from
  `evaluation/dataset.yaml`; matches item for item. `r_1790074972_baseline.json` `n_items = 28`.
* `8` reference-labelled items, `SEED = 1729`, `judge_agreement_rate` — the published run's
  `judge_agreement_rate=1.0 over n=8 reference labels (subset seed_1729_8)`.
* `gemini-3.5-flash-lite` as judge — the published run's `judge_model`.
* "Judged metrics — baseline only … on the two arms these render *not judged*" — still true:
  `r_1790075436_dense_only_k2` and `r_1790075830_no_structured_tools` both carry
  `judge_status: not_applicable`, `judge_calls: 0`, and both were driven on `8a89310`.
* `0.85` target strict pass rate — `design-and-evaluation.md:973, :991`.
* Cold-start block (`44.8 s` spin-up, `0.1 s` on to `/ready` with `2.8 s` on the readiness-fix
  build, `71.0 s` first request median `67.5–77.6`, `22.5 s` warm `22.5–23.9`, probes after
  `1,000 s` idle, `744` of `750` hours armed) — `deployed.md:194–205, :251, :278`.
* Agent budgets `6 steps / 12 tool calls / 90 s`, `llm_rpm` 10, `retrieval_k` 5 default,
  `min_dense_score` 0.26 as a **tool-schema** default (a different knob from the G1 thresholds) —
  `settings.py:77, 101, 119–121`; `design-and-evaluation.md:603`.
* `24` employees, snapshot `2026-09-01` — `mock_data/employees.json`: 24 records, `as_of`
  `2026-09-01`. `1.50 days per month` — `corpus/facts.yml:29`, verbatim.
* `Chart.js on pages 1, 8 and 11` — `chart` appears in `overview.html` (page 1), `safety.html`
  (page 8), `evals.html` + `eval_detail.html` (page 11 and its detail), matching the page order the
  `Pages` row lists.
* The keep-alive armed marker required by `tests/contract/test_keep_alive.py` is untouched.

## 4. Dashboard page count: 11 is correct, left as "Eleven"

`design-and-evaluation.md:41` ("11 pages · Chart.js · htmx filters") and `:1548` ("render 11
dashboard pages") both say **11**, so `D["f1-dash"]`'s "Eleven server-rendered pages", the
masthead's "eleven-page audit dashboard" (line 216), `D["f4-c3"]`'s "Eleven pages" and the four
`11 pages` labels in figures 1 and 4 are all consistent with the graded doc and with each other.
The distinction holds: `src/hrmosaic/web/dashboard.py` registers **13** `GET /dashboard…` routes —
the 11 pages plus `/dashboard/corpus/{doc_id}` and `/dashboard/evals/{run_id}`, which are detail
views of the corpus and evals pages. The page never says "routes", so nothing needed changing.

## Verification

```
.venv/bin/pytest -q -p no:cacheprovider tests/contract/test_docs_completeness.py tests/contract/test_keep_alive.py tests/contract/test_no_broken_links.py
59 passed in 15.71s
```

## Concerns

1. **The `ux` job is a text line, not a tile** (reasoning above). If a later pass is willing to
   grow figure 6's `viewBox` from 580 to ~640 and shift the two bottom tiles down, `ux` should
   become a real `<g class="node">` with a `D["f6-ux"]` entry so it behaves like its four peers on
   hover.
2. **No browser was available to check text metrics.** Every string I lengthened was sized by
   monospace advance (≈0.6em) against its tile's inner width, and two lines were dropped to 9.5px
   to stay inside their boxes (`runs lint, test, ux, docker` at line 1349, the new `ux` line at
   1397). The `ux`-marked Playwright suite does not cover `docs/architecture.html`, so overflow
   here is not test-detectable — worth one look on screen before the design segment is recorded.
3. **`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` still says `~280 chunks`** (lines
   94, 410, 2763) and is still the "15.8 s in the probe" source. It is the frozen pre-implementation
   spec and outside this task's one editable file, but the architecture page links to it in the
   footer, so a grader who follows that link meets the old estimate.
4. **`345 MB` is still quoted as a budget elsewhere** (`deployed.md`, `design-and-evaluation.md`),
   which is correct usage; only the architecture page's glance strip had mislabelled it a
   measurement. The two documents now differ in which number they lead with — intentionally, since
   the glance strip promises a measurement.

---

# Fix round 1 — five jobs in every place the page names them

The reviewer rendered the page and found the five-jobs fix incomplete in four
places, two of which contradicted tooltips I had already corrected. All four are
fixed, plus the connector collision. Line numbers are post-edit.

| Line | Was | Now | Why |
| --- | --- | --- | --- |
| 431 (fig 1, `f1-ci` tile) | `lint · test · docker · deploy` | `lint · test · ux · docker · deploy` | visible without hover, and its own `D["f1-ci"]` tooltip already said five |
| 1805 (`D["f6-t2"]`, Pull request) | `Runs: lint, test, docker` | `Runs: lint, test, ux, docker` | `on: pull_request` with no per-job `if:`, so every job runs on a PR |
| 1828 (`D["f6-e-t1"]`, `on: push`) | `Runs: lint, test, docker, and then deploy`; `c: […, "all four ci.yml jobs"]` | `Runs: lint, test, ux and docker, and then deploy`; `c: […, "all five ci.yml jobs"]` | same — `ux` has no `if:` either |
| 1829 (`D["f6-e-t2"]`) | `c: ["Pull request", "lint, test and docker"]` | `c: ["Pull request", "lint, test, ux and docker"]` | same |
| 1830 (`D["f6-e-t3"]`) | `c: [… , "lint, test and docker — deploy is reached only through needs"]` | `… "lint, test, ux and docker — …"` | same |

## The connector collision (minor 5) — diagnosed, then fixed by width, not by halo

The crossing line is **not** `f6-e-env` ("read once through settings.py"). Measured
in Chromium: that label's box is `x 630.4–782.0, y 422.5`, entirely below the
`ci.yml` box, and its vertical segment sits at `x = 816`, outside the box
altogether. The line that actually cut the `ux` text is **`f6-e-sec`** — "set by
`gh secret set` at provisioning" — whose path `M204,442 V416 H600 V360` runs a
vertical up through `x = 600` from `y 416` to `y 360`, straight across the text
band at `y ≈ 373–385`. The old string measured `x 292 → 720.8` at `5.717 px`
per character, which puts `x = 600` at character 53.9 — exactly the space between
`never` and `blocks`, matching the reviewer's `never|blocks` split precisely.

A `paint-order` halo alone could not have fixed it: the edge `<g>` elements are
later in document order than the node/annotation text, so the connector paints
*over* the text no matter what the text's stroke does. (`.elab` labels get away
with the halo because each one lives *inside* its own edge group, after its own
path.) So the text was shortened instead, to

> `ux — the browser suite; needs: absent, never blocks`

which measures `x 292 → 583.6` — clear of the `x = 600` lane by 16.4 px, and still
inside the box's `266–786`. The halo was added as well (`paint-order:stroke`,
`stroke:var(--fig-bg)`, 3px, round join), so the line survives the dashed box edge
and the tessellated background if anything ever moves. The full quotation from
`ci.yml` ("its own job because it is the only thing in the repo that needs a
browser binary, and `needs:` is deliberately absent — it must never block `test`
or `deploy`") is unchanged in the `D["f1-ci"]` tooltip.

## Grep sweep

`grep -niE "four|docker · deploy|docker, and then|test and docker|test, docker"`
returns 19 hits, every one of them legitimate and unrelated to the job count: the
four Corpus/RAG tools (1534, 1535, 1615, 1631), the four named failure paths (517,
1667, 1668), the four `ChatModel` implementations (1561), the four fixed employee
anchors (1550), the four rubric-named response fields (1622), the four judged
aggregates that are null on the arms (1787), `Corpus and RAG tools, one to four`
(345), and the literal `needs: [test, docker]` (1338, 1391, 1571, 1606, 1807,
1814). Nothing about the number of CI jobs survives.

## Verification

```
.venv/bin/pytest -q -p no:cacheprovider tests/contract/test_docs_completeness.py tests/contract/test_keep_alive.py tests/contract/test_no_broken_links.py
60 passed in 17.09s
```

(60 rather than the 59 of the first round — a concurrent agent added a case to one
of those three files.) Both `<script>` blocks still pass `node --check`.

Rendered in Chromium (`~/Library/Caches/ms-playwright/chromium-*`, via the repo's
own `.venv` Playwright) at a 1440 px viewport, `device_scale_factor=2`, and both
regions inspected in the PNG:

* **Figure 6, the `ci.yml` box** — title reads `ONE FILE, FIVE JOBS`; the four job
  tiles are unchanged; the `ux` line sits below them, unbroken, well to the left of
  the secrets connector that enters `deploy` from beneath; the `test` tile reads
  `pytest -q (all but the ux suite)`.
* **Figure 1, the `GitHub Actions — ci.yml` tile** — reads
  `lint · test · ux · docker · deploy`, measuring `302 → 516.8` inside a tile whose
  right edge is `610`, so 93 px of slack.
* **Whole page** — `viewBox` overflow check across all six figures returns `[]`, and
  `document.documentElement.scrollWidth > clientWidth` is `false`.

Concern 1 from the first round stands: `ux` is still a named text line rather than
a fifth hoverable tile, for the geometry reason given above. Concern 2 (unmeasured
text widths) is now retired — every string on this page was measured in a real
browser.
