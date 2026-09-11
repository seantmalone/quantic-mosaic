# P9 report — Observability dashboard, 11 pages

**Branch** `main` · **base** `89a9bdf` (HEAD had moved from the briefed `8cf7286` to `89a9bdf`
while I worked — the concurrent P7-lens fix commit — so I built on the actual HEAD)
· **commit** `e9d5799` · **HEAD after** `e9d57992b6b474ffd86f3a563d42299102af1910` · not pushed.

---

## 1. What landed

### `src/hrmosaic/web/dashboard.py` (new, 2 393 lines)

§4's repo layout names `web/dashboard.py` as *the* file for this phase, so the whole of P9's server
side lives there in five clearly separated sections: Jinja display filters, the `Filters` filter-bar
model, the typed Pydantic view-models of §11.6, the query builders (one `build_*` per page), and the
routes. Every builder is the single producer of its page's model; the route dumps it once and either
returns that dict as JSON or hands **the same dict** to Jinja. That is what makes §11.6's
"every page renders from the typed view-model produced by the same `/api/*` endpoint" literally
true rather than a convention, and it is what `test_dashboard_viewmodels.py` checks from the JSON
side while `test_dashboard_pages.py` checks it from the rendered side.

Every endpoint of §11.8 is present and route-table-tested (`test_app_starts.py`):

| Page | Route | API |
|---|---|---|
| 1 Overview | `/dashboard` | `/api/traces/overview` |
| 2 Sessions | `/dashboard/sessions` | `/api/traces/sessions` |
| 3 Session detail | `/dashboard/sessions/{id}` | `/api/traces/sessions/{id}` (+ `/api/traces/turns/{turn_id}`) |
| 4 Turns | `/dashboard/turns` | `/api/traces/turns` |
| 5 LLM calls | `/dashboard/llm` | `/api/traces/llm` |
| 6 Retrieval | `/dashboard/retrieval` | `/api/traces/retrieval` |
| 7 Tools | `/dashboard/tools` | `/api/traces/tools` |
| 8 Safety | `/dashboard/safety` | `/api/traces/safety` + `POST /api/dev/reset-sandbox` |
| 9 MCP | `/dashboard/mcp` | `/api/mcp/discovery` + `POST /api/mcp/rediscover` |
| 10 Corpus | `/dashboard/corpus`, `/dashboard/corpus/{doc_id}` | `/api/corpus/{documents,documents/{doc_id},chunks/{chunk_id}}` |
| 11 Evals | `/dashboard/evals`, `/dashboard/evals/{run_id}` | `/api/eval/{runs,runs/{id},compare}` + `POST /api/eval/runs` |

### `src/hrmosaic/web/templates/dashboard/` (new, 14 templates)

`_base.html` (the eleven-page nav, the title bar, the **Export JSON** button on every page),
`_table.html` (the shared table partial — every wide table inside its own `overflow-x` container —
plus the pager macro), `_filters.html` (the shared filter bar; filters live in the query string, so
a filtered view is a URL a grader can paste and the Export JSON link carries the same filters
through to the API), and one template per page.

**Charts (Chart.js, vendored):** page 1 turns-per-hour sparkline; page 8 verdict counts by rule
(stacked bar); page 11 grouped ablation bars (compare tab) and the latency histogram, cold-vs-warm
bars and RSS line (metrics tab). The ablation chart **omits** a series that is null on every
variant rather than plotting a zero.

**Page 3, the centrepiece:** the session facts (including `auth_mode` / `actor_role`), a span-kind
toggle, and one card per turn carrying the question, the answer, the citation chips, the rollups and
the waterfall — every span in `seq` order with a proportional CSS duration bar positioned by
`offset_ms`, the one-line summary from `agent.orchestrator.summarise_span` (the *same* helper the
`/chat` `trace[]` and the SSE rail use, so the three never disagree), and the full payload one
`<details>` away.

### `GET /api/traces/turns/{turn_id}`

Moved out of `web/api.py` into `web/dashboard.py` and grown into page 3's `TurnDetail` view-model.
Every field P8 shipped survives — `test_dashboard_viewmodels.py::test_the_single_turn_route_still_carries_every_field_p8_shipped`
pins the exact set that `scripts/demo_task_*.sh` and §9.4's 202 fallback read — and `rollups{}`
gained tokens and the four `*_ms` figures. The route now returns *the same object* page 3's
`turns[]` carries, asserted by
`test_the_single_turn_route_is_the_same_record_as_the_session_page`.

### The three write controls (§11.6), never dead

* **Reset sandbox** (page 8) → `POST /api/dev/reset-sandbox`, clears `mock_writes` and nothing else.
* **Re-discover now** (page 9) → `POST /api/mcp/rediscover`: drops the cached handshake, opens a
  synthetic `client_label='maintenance'` session and a turn with `outcome='maintenance'`, and writes
  the `mcp_discovery` span into it — because `spans.turn_id` is `NOT NULL`.
* **Run smoke eval** (page 11) → `POST /api/eval/runs`, bounded by `EVAL_SMOKE_MAX_ITEMS` (6), one
  variant, deterministic scorers by default, importing `evaluation.runner` **lazily inside the
  handler**.

All three are `POST /api/*`, so P8's pure-ASGI gate already refuses a non-admin caller with 403
`{"code": "ADMIN_REQUIRED"}` before the handler runs — reaching the host page proves the persona.

### `tests/fixtures/eval_runs/` — one run JSON per variant

`r_p9fixture_baseline.json`, `r_p9fixture_dense_only_k2.json`,
`r_p9fixture_no_structured_tools.json` (6 scored items each, the same six item ids across variants so
`flips[]` is computable; baseline additionally carries the three `cold_probe` rows of §13.5), plus
`chunk_size_comparison.json` for the compare tab's zero-LLM sweep (`core/archive.py` already ignores
that filename as a non-run object). Categories use §13.1's vocabulary
(`simple_policy`, `multi_doc`, `tool_task`, `ambiguous`, `out_of_scope`, `sensitive`) and the item
ids are the ones §13.1 names (`pto-001`, `remote-004`, `pto-003`, …). P1's `sample_run.json` is
untouched and still passes `test_results_import`.

### `core/retention.py` — the maintenance-session carry-forward

**Choice: cap, not exempt.** `/ready`'s warm-up opens one `maintenance` session per boot and
`POST /api/mcp/rediscover` opens one per click, so §10.5's blanket exemption would grow the table
without bound on a long-lived instance — the very thing that sweep exists to prevent. The smallest
change consistent with §10.5 is to give them their own window instead of the shared one: a second
`PRUNABLE_MAINTENANCE_SESSIONS` query keeps the newest `MAINTENANCE_SESSIONS_KEPT = 20` (a module
constant, not a new env var — §12.3's table is exact) and prunes the rest through the same cascade,
still honouring the `mock_writes` protection. `eval_judge` and `eval_run_id` sessions remain
absolutely exempt. `tests/unit/test_retention.py` stays green.

### Small edits to existing files

* `web/main.py` — one line including the dashboard router, one line in the docstring block.
* `web/api.py` — the P8 `turn_view` handler removed (it moved and grew); docstring pointer updated.
* `web/static/app.css` — the dashboard half of the stylesheet appended (same file, no build step).
* `tests/contract/test_app_starts.py` — `EXPECTED_ROUTES` grown to §11.8's full list; the test's own
  comment said the rest was P9's.
* `tests/contract/test_access_gate.py` — `test_the_dashboard_prefix_is_gated_before_it_is_admin_checked`
  asserted `404` "until P9"; it now asserts the real three-way outcome (401 without a token, 403
  `ADMIN_REQUIRED` in the employee persona, 200 as admin).

---

## 2. Definition of done — real output

### `pytest tests/contract/test_dashboard_pages.py -q`

```
..............                                                           [100%]
14 passed in 11.22s
```

### `pytest tests/contract/test_dashboard_viewmodels.py -q`

```
................                                                         [100%]
16 passed in 12.53s
```

### `make lint`

```
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
174 files already formatted
```

### `make test` (the whole suite, pristine — no warnings)

```
........................................................................ [ 75%]
........................................................................ [ 81%]
........................................................................ [ 88%]
........................................................................ [ 94%]
.................................................................        [100%]
1145 passed in 144.21s (0:02:24)
```

(1075 before P9 + 30 new dashboard tests, and the two edited P8 tests unchanged in count; the
remainder is the concurrent P7-lens fix commit's own additions.)

### The bounded smoke-eval endpoint

Its full test is P10's (`tests/integration/test_smoke_eval_endpoint.py` — `runner.py` is a P10
deliverable). What ships here is asserted in
`test_dashboard_pages.py::test_run_smoke_eval_is_on_page_eleven_bounded_and_lazily_imports_the_runner`:
the control is on page 11 and wired; `n_items: 99` is refused **400 `SMOKE_BOUNDS_EXCEEDED`** with
`max_items: 6`; a list of variants is refused **422**; and a well-formed bounded request answers
**501 `EVAL_RUNNER_UNAVAILABLE`** while `evaluation.runner` does not exist, with the `else` branch
of that assertion already written for the day it does.

---

## 3. TDD evidence

Two genuine red→green cycles are recorded; the rest of the module was written whole (it is one
cohesive router) and then driven to green by the two named test files.

**Cycle 1 — the shared table partial, first run of `test_dashboard_pages.py`:**

```
FAILED tests/contract/test_dashboard_pages.py::test_every_page_renders_200_with_its_chrome_in_the_admin_persona
FAILED tests/contract/test_dashboard_pages.py::test_page_nine_lists_the_live_catalog_and_page_ten_the_corpus
FAILED tests/contract/test_dashboard_pages.py::test_page_eleven_renders_not_judged_rather_than_a_zero_on_an_ablation_arm
FAILED tests/contract/test_dashboard_pages.py::test_run_smoke_eval_is_on_page_eleven_bounded_and_lazily_imports_the_runner
4 failed, 9 passed in 10.49s
```

Root cause: `TypeError: object of type 'float' has no len()` — Jinja's `truncate` on a non-string
cell. Fixed in `_table.html` (`value|string|truncate(...)`), then:

```
.............                                                            [100%]
13 passed in 10.16s
```

**Cycle 2 — the pager, written test-first after I spotted the double `page=`:**

```
E           AssertionError: ?client_label=demo&amp;page=2&page=1
E           assert 2 == 1
FAILED tests/contract/test_dashboard_pages.py::test_the_pager_keeps_the_filters_and_never_repeats_the_page_parameter
1 failed, 13 deselected in 2.42s
```

Two `page=` values in one query string silently resolve to the first, so "Previous" from page 2
would have gone nowhere. Fixed by dropping `page` from `filter_query` in `_page()` (the pager
appends its own):

```
..............                                                           [100%]
14 passed in 10.83s
```

---

## 4. The rendered look (headless Chrome, 1440×3000)

Captured against a real local instance seeded with `make demo1 && make demo2` (stub model, real MCP
mount, real index) plus the three committed eval-run fixtures imported into the local trace store.
Chrome cannot send `X-Actor: admin`, so each page was fetched over HTTP with the admin header, a
`<base href>` injected, and the file screenshotted — the CSS, htmx and Chart.js all still load from
the running app, so the charts are real.

* `/private/tmp/claude-501/-Users-sean-Projects-quantic-mosaic/44fed378-5d63-4daa-b66b-91107d8f0a3a/scratchpad/P9/page1-overview.png`
* `/private/tmp/claude-501/-Users-sean-Projects-quantic-mosaic/44fed378-5d63-4daa-b66b-91107d8f0a3a/scratchpad/P9/page3-session-detail.png`
* `/private/tmp/claude-501/-Users-sean-Projects-quantic-mosaic/44fed378-5d63-4daa-b66b-91107d8f0a3a/scratchpad/P9/page11-eval-detail.png`
* `/private/tmp/claude-501/-Users-sean-Projects-quantic-mosaic/44fed378-5d63-4daa-b66b-91107d8f0a3a/scratchpad/P9/page11-eval-list.png`

**What the first look found, and what I changed:**

1. **`MCP down · tools 0` on page 1.** Not a page bug — I had started uvicorn on `:8123` without
   setting `PORT`, so `MCP_SERVER_URL` still pointed at `:8000`. Re-shot with `PORT=8123`; page 1
   now reads `MCP up · tools 9 · documents 14 · chunks 204`.
2. **`blocks_dropped_by_g2` rendered as `0.0` / `2.0`.** `EvalRunRow.headline` was typed
   `dict[str, float | None]`, so Pydantic coerced the integer count to a float. Retyped
   `dict[str, int | float | None]`; it now reads `0` and `2`.
3. **"not judged on this variant" shown for a *deterministic* metric that happened to be null** (P1's
   `sample_run.json` uses different metric key names). That wording is only true of the four judged
   aggregates. Both the headline table and the detail metric block now branch: the judged four get
   the sentence, anything else null gets an em dash. The wide headline table uses the short form
   `not judged` with the full sentence as a `title`, and the detail metric block keeps §11.6's exact
   wording (which is what the contract test asserts).
4. **A visible gap in the nav** — `1. Overview · 2. Sessions · 4. Turns …` — because page 3 has no
   standalone URL. It now renders as a greyed, unlinked label ("Opened from Sessions") except on
   page 3 itself, so a demo can narrate by number without the audience wondering where 3 went.

---

## 5. Self-review findings (fixed before the commit)

| Finding | Fix |
|---|---|
| Pager emitted two `page=` parameters | `filter_query` drops `page`; covered by a new test (cycle 2 above) |
| `truncate` applied to non-string cells | `\|string\|truncate` in `_table.html` |
| `view.items` in Jinja resolves to `dict.items`, not the model's `items[]` | switched to `view['items']` in `eval_detail.html` |
| `headline` coerced integer counts to floats | union type |
| "not judged" wording leaking onto deterministic metrics | branch on `judged_metrics` |
| `hx-ext="json-enc"` on the smoke-eval form (extension not vendored) | removed — `api._parse_body` already accepts a form body, which is how every other htmx control on the app posts |
| Stray `pytest.importorskip("pytest")` in the smoke-eval test | removed |
| Unused `dataclasses.replace` import | removed |

---

## 6. Ambiguities resolved (simplest reading that satisfies the spec)

1. **Which four aggregates are "the judged" ones.** §11.6 says four are judged and five are
   deterministic, but names neither set. The eight-metric headline strip splits five deterministic
   (`cit_resolve_mean`, `blocks_dropped_by_g2`, `tool_selection_accuracy`, `arg_correctness_rate`,
   `strict_pass_rate` — §13.3 calls resolvability deterministic, §13.8 makes the composite vacuous
   where groundedness is unjudged) and three judged (`groundedness_mean`, `citation_accuracy_mean`,
   `partial_match_mean`). The fourth judged one is `clarification_accuracy`, which §13.7 explicitly
   scopes to `baseline` only. Encoded as `JUDGED_METRICS` / `DETERMINISTIC_METRICS` module constants
   and asserted by name in the contract test.
2. **`pending_confirmations` (page 1).** `confirmations` rows are minted only *after* the human
   decision, so a pending one has no row. Read it as turns whose `outcome` is
   `awaiting_confirmation`.
3. **`error_rate` / `p50_ms` / `p95_ms` (page 1).** Over `turns` — `outcome = 'error'` for the rate,
   `turns.duration_ms` through `statistics.quantiles(n=100)` for the percentiles, matching §13.5.
4. **Page 11's `question` / `gold`.** `eval_results` has no column for either; the honest source is
   `evaluation/dataset.yaml`, a P10 deliverable. A small cached loader reads it when it exists; until
   then both are `null` and the column renders "—" rather than being back-filled from the stored
   answer (which would make the page agree with itself by construction). The contract test asserts
   the `null` today.
5. **The metrics tab's `by_kind{}` and `rss_series[]`.** §10.1 says `turns.rss_mb_at_end` is
   "the series page 11 plots", so both are derived from the `turns` rows joined on
   `eval_results.turn_id` rather than from the run JSON. When the store holds no turns for a run
   (a fixture run on a cold database) the page says so instead of showing zeros.
6. **Pagination.** §11.6 gives page 2 exactly `rows`, `page`, `total`, so `page_size` is a module
   constant (`PAGE_SIZE = 50`) rather than an invented query parameter. Pages 5–8 are not paginated
   in the spec; they list the newest `ROW_LIMIT = 200` rows and say so in the panel heading.
7. **Filter parameter names.** The spec names the filter *dimensions*, not the parameter names.
   Used `date_from`/`date_to` (`from` is a Python keyword), `persona`, `q`, `has_error`,
   `min_duration_ms`, and the obvious name for each per-page dimension.
8. **Fields added beyond §11.6's field lists** (each needed to render honestly, each documented in
   the code): `EvalItemRow.trace_url` (the "one click to the full trace" §10.1 asks for),
   `Flip.variant` (two ablation arms are compared against one baseline), `EvalRunRow.judged`,
   `McpDiscoveryView.connected`/`last_error` (so a down server renders as down, not as an empty
   catalog), `CorpusView.topics`/`formats` (the facet values the topic and format filters offer),
   and `SpanRow.span_id`/`parent_span_id` (already shipped by P8).
9. **`evaluation.runner`'s smoke entry point.** The handler calls
   `runner.smoke_run(variant=…, item_ids=…, n_items=…, judge=…, label=…, base_url=…)` and expects an
   async iterator of SSE frames, wrapped in a `StreamingResponse` — the smallest contract that
   satisfies §11.7's "streamed over SSE" without designing P10's module. P10 owns that name.
10. **Commit shape.** The roadmap suggests `P9a/P9b/P9c`; the dispatch requires the final subject to
    be `P9(<scope>): …`. The work is one cohesive module and one template tree that are only green
    together, so it is one commit with the required subject and a bullet per deliverable.

---

## 7. Concerns for the reviewer

1. **`web/dashboard.py` is 2 393 lines.** §4's layout names it as the single file for this phase, so
    splitting the view-models or the query layer into a new module would have invented a component.
    It is sectioned and every section is independently readable, but if a later phase wants
    `web/viewmodels.py` this is the moment to say so.
2. **`json_extract` is now load-bearing** for the page 5 `by_model` rollup, the page 8 `by_rule`
    rollup, the spend KPIs and several filters. SQLite's JSON1 has been compiled in by default since
    3.38 and libSQL inherits it, so both backends support it — but it is the first use of JSON SQL
    in the project, and only the SQLite backend is exercised by the suite. Worth a one-line check on
    Turso at P11.
3. **Page 1 performs an MCP handshake.** `build_overview` reuses `api.health_payload`, which calls
    `client.discover()` with a 5 s timeout, so the landing page pays the same cost `/health` does.
    That is deliberate (one source for the health block) but it does mean page 1 is the slowest page
    on a cold instance.
4. **`tests/fixtures/eval_runs/chunk_size_comparison.json` is a fourth file** in a directory the
    brief describes as "one run JSON per variant". It is the only way to test the compare tab's
    `chunk_size[]` list before `scripts/chunk_size_sweep.py` exists, and `core/archive.py` already
    skips that filename as a non-run object. P10 replaces it with the real sweep.
5. **`web/templates/` and `web/static/` are still not declared as package data** in
    `pyproject.toml` (only `hrmosaic.agent.prompts` is). Editable installs are fine, so nothing is
    broken today, but the P11 Docker image will need either a package-data entry or a `COPY` that
    reaches them. Pre-existing from P8; flagging it because P9 quadrupled the number of templates.
6. **The smoke-eval success path is untested here**, by design — `evaluation/runner.py` is P10's.
    Only the bounds refusals and the 501 are covered.
7. **P1's `tests/fixtures/eval_runs/sample_run.json` uses different metric key names** from §11.6's
    metric block (`citation_resolve_rate`, `pass_rate`, …). It still imports and still renders — the
    view-model is `extra="ignore"` with `None` defaults — but on page 11 it shows as a run with no
    headline figures. Harmless (it exists for the importer test), and worth folding into the P10
    refresh.

---

# P9 fix report — round 1/3

**Branch** `main` · **base** `e9d5799` (the P9 commit under review) · not pushed.

Three review findings, all Important, all fixed. No other file touched.

## Finding 1 — `core/retention.py` redesigned §10.5's maintenance exemption

**Reverted.** `src/hrmosaic/core/retention.py` is byte-for-byte back to what P1 shipped
(`git checkout 8683813 -- src/hrmosaic/core/retention.py`; `git diff 8683813 HEAD~0 -- …` is empty):
the `MAINTENANCE_SESSIONS_KEPT = 20` constant, the `PRUNABLE_MAINTENANCE_SESSIONS` query, the
`keep_maintenance` parameter and the six docstring lines arguing for the cap are all gone, and
`PRUNABLE_SESSIONS` again reads `client_label NOT IN ('eval_judge', 'maintenance')` — the blanket
exemption §10.5 actually specifies. The review is right on all three counts: the standing brief says
that spec is authoritative and requires a STOP-and-report rather than a unilateral redesign;
`core/retention.py` is not in P9's deliverables list; and the new branch was never exercised, because
`tests/unit/test_retention.py` creates exactly one `maintenance` session, which survives identically
under either rule.

`tests/unit/test_retention.py` needed no edit: its module docstring ("never prunes a session that is
eval-linked, `eval_judge`, `maintenance`") is true again, and
`test_eval_linked_and_server_label_sessions_are_never_pruned` asserts the reverted behaviour.

**Raised for the spec owner, not fixed here** (it is a pre-existing property, not something P9
introduced): `/ready`'s warm-up opens one `client_label='maintenance'` session per boot and
`POST /api/mcp/rediscover` opens one per click, and §10.5 exempts every one of them from the sweep,
so that table grows without bound on a long-lived instance. If a cap is wanted it belongs in its own
change against an amended §10.5, with a test that creates `keep_maintenance + 1` maintenance
sessions and asserts the oldest is pruned while the newest survive, and with the retention-test
docstring updated to match. See *Concerns* below.

## Finding 2 — `Filters.query_string` built the query string without URL encoding

`src/hrmosaic/web/dashboard.py:369` now builds the string with `urllib.parse.urlencode` over the
same dict it filtered before, instead of f-string concatenation:

```python
state = {**self.as_dict(), **overrides}
return urlencode(
    {
        key: "true" if value is True else value
        for key, value in state.items()
        if value not in (None, "", False) and not (key == "page" and value == 1)
    }
)
```

That one string is both `filter_query` (the pager links, `_table.html`'s `pager` macro) and the
`api_url` behind every page's Export JSON button, so before the fix a free-text `q` containing `&`
truncated the link at the ampersand and one containing `#` sent the remainder to the fragment —
"Export JSON" silently answered a *wider* row set than the page displayed, which is precisely the
§11.6 guarantee the module docstring claims. Jinja's autoescaping already turns the `&` separators
into `&amp;` in the HTML, which browsers parse back to `&`, so no template changed.

**Covering test** (new): `tests/contract/test_dashboard_pages.py::test_a_free_text_filter_survives_the_pager_and_the_export_link_intact`
— filters page 4 on `q = "PTO & holidays #2026 = 50%"` at `page=2`, then asserts the Export JSON
href has no fragment and round-trips `q` exactly, that every pager link round-trips `q` exactly, and
that **following the export href returns byte-identical JSON to the page's own filtered API call**.

Red against the pre-fix module, to prove the test bites:

```
        export = html.unescape(re.search(r'id="export-json"[^>]*href="([^"]+)"', page_two.text).group(1))
>       assert urlparse(export).fragment == "", export
E       AssertionError: /api/traces/turns?q=PTO & holidays #2026 = 50%&page=2
E       assert '2026 = 50%&page=2' == ''
FAILED tests/contract/test_dashboard_pages.py::test_a_free_text_filter_survives_the_pager_and_the_export_link_intact
1 failed, 14 deselected in 2.42s
```

## Finding 3 — `build_tools` selected every `tool_call` span with no `LIMIT`

Page 7 was the only span page that read the whole table: it `SELECT`ed every `tool_call` row and ran
`_payloads()` (a `json.loads` per row, over payloads §10.5 caps at 32 KB) purely to compute the
`by_tool` rollup, applying `ROW_LIMIT` only when appending to `recent`. `build_tools` now matches
the shape `build_llm` already uses:

* **`by_tool` counts and error rate**: one SQL aggregate — `COUNT(*)`,
  `SUM(CASE WHEN json_extract(payload_json, '$.is_error') = 1 …)`, `MAX(started_at)` — grouped by a
  new `TOOL_NAME_SQL` constant, `COALESCE(json_extract(payload_json, '$.tool_name'), name, 'unknown')`.
  (`spans.name` is the tool name for a `tool_call` span and is `NOT NULL`, so this matches the Python
  fallback `recent` uses and can never group on NULL.) Ordered `calls DESC, tool_name`, so ties are
  deterministic where `Counter.most_common()` was insertion-ordered.
* **p50/p95**: the newest `ROW_LIMIT` `duration_ms` values *per tool*, via
  `ROW_NUMBER() OVER (PARTITION BY … ORDER BY started_at DESC)` — bounded, and a chatty tool cannot
  starve a rare one of its sample. Two integer columns per row, no payloads.
* **`recent`**: its own `… ORDER BY started_at DESC LIMIT ?` with `ROW_LIMIT`, the only statement on
  the page that still pulls `payload_json`.

The rollup therefore still covers **every** call in the filter window while nothing unbounded is
materialised. Both filters (`tool=`, `errors_only=`) apply to all three statements, unchanged.

**Covering tests** (new file `tests/unit/test_dashboard_tools_rollup.py`, 2 tests):
`test_the_tool_rollup_counts_every_call_while_the_row_list_stays_bounded` seeds `ROW_LIMIT + 25`
`tool_call` spans for one tool and 3 for another **through `core/trace.py`** (never a hand-written
INSERT), with 4 KB `result_json` payloads, wraps the store in a recorder, and asserts that every
statement touching `payload_json` carries a `LIMIT` *and* returned at most `ROW_LIMIT` rows — while
`by_tool` still reports all 225 calls and the correct error rate. `test_the_tool_filters_narrow_both_the_rollup_and_the_rows`
pins that `tool` and `errors_only` still narrow the rollup and the row list together.

Red against the pre-fix module:

```
        payload_reads = recorder.payload_rows()
        assert payload_reads, "page 7 still has to read some payloads"
        for sql, count in payload_reads:
>           assert "LIMIT" in sql, sql
E           AssertionError: SELECT id, turn_id, started_at, duration_ms, payload_json FROM spans WHERE kind = 'tool_call' ORDER BY started_at DESC
FAILED tests/unit/test_dashboard_tools_rollup.py::test_the_tool_rollup_counts_every_call_while_the_row_list_stays_bounded
1 failed, 1 passed in 1.39s
```

## Definition of done — real output, after the fixes

### `pytest tests/contract/test_dashboard_pages.py -q`

```
...............                                                          [100%]
15 passed in 11.83s
```

### `pytest tests/contract/test_dashboard_viewmodels.py -q`

```
................                                                         [100%]
16 passed in 12.49s
```

### The tests covering the amended code

```
$ pytest tests/unit/test_retention.py tests/unit/test_dashboard_tools_rollup.py -q
.........                                                                [100%]
9 passed in 1.29s
```

### `make lint`

```
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
175 files already formatted
```

### `make test` (whole suite, pristine — no warnings)

```
........................................................................ [ 18%]
........................................................................ [ 25%]
........................................................................ [ 31%]
........................................................................ [ 37%]
........................................................................ [ 43%]
........................................................................ [ 50%]
........................................................................ [ 56%]
........................................................................ [ 62%]
........................................................................ [ 68%]
........................................................................ [ 75%]
........................................................................ [ 81%]
........................................................................ [ 87%]
........................................................................ [ 94%]
....................................................................     [100%]
1148 passed in 145.16s (0:02:25)
```

1145 before this round + 3 (one contract, two unit). No test was deleted or weakened.

## Concerns for the reviewer

1. **The unbounded `maintenance` sessions are back, by design.** Reverting finding 1 restores
   §10.5 exactly and restores the growth it implies. This needs a spec decision, not a subagent's:
   either §10.5 is amended to cap them (and a follow-up change adds the cap plus the
   `keep_maintenance + 1` test) or `/ready` stops opening a session per boot. Flagged, not acted on.
2. **`ROW_NUMBER() OVER (PARTITION BY …)` is the project's first window function.** SQLite has had
   them since 3.25 and libSQL inherits them, so both backends support it, but — like the
   `json_extract` note already in this report's §7.2 — only the SQLite backend is exercised by the
   suite. Worth folding into the same one-line Turso check at P11.
3. **`by_tool`'s p50/p95 are now over the newest `ROW_LIMIT` calls per tool**, not over every call
   in the window, while `calls`, `error_rate` and `last_called_at` are exact. That is the
   bounded-sample option the finding offers; the page's panel heading already says it lists the
   newest `ROW_LIMIT` rows, but the percentile column does not itself say "sampled". Say the word
   and I will label it.
