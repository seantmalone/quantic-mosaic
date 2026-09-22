# Task 12d report — round-2 `docs/architecture.html` (G5b)

**Commit:** `a0b37a6` — *G5b(architecture-page): the walkthrough stops describing the CI gate, the discovery
span and the dataset it used to have* (parent `44e5e9f`). Branch `main`. Staged with an explicit
`git add docs/architecture.html`; nothing else was staged (README.md, deployed.md,
design-and-evaluation.md and docs/demo-script.md were dirty in the shared tree throughout and are
untouched by this commit).

34 changed lines, 35 claim edits. Every line number below is **post-commit**.

---

## 1. ci.yml — the deploy gate (gap 16)

Source: `.github/workflows/ci.yml:178` (`needs: [test, docker, ux]`), `:92-105` (the rewritten `ux`
rationale, run 35723846982).

| Line | Was | Is |
| --- | --- | --- |
| 1338 (figure-6 `aria-label`) | "the ux job carries no needs and blocks nothing; deploy needs test and docker" | "the ux browser job carries no needs of its own but deploy waits on it; deploy needs test, docker and ux" |
| 1391 (deploy tile title) | `deploy — needs: [test, docker]` | `deploy — needs: [test, docker, ux]` |
| 1397 (the free-floating `ux` label) | "ux — the browser suite; needs: absent, never blocks" | "ux — the browser suite; deploy needs it" |
| 1570 (`f1-ci` prose) | "a job that needs test and docker" | "a job that needs test, docker and ux" |
| 1571 (`f1-ci` — `Gate`) | `deploy needs: [test, docker]` | `deploy needs: [test, docker, ux]` |
| 1571 (`f1-ci` — `ux`) | quoted ci.yml: "needs: is deliberately absent — it must never block test or deploy" | it still declares no `needs:` of its own, but since G5b `deploy` needs it: 299 browser tests are tests, and run 35723846982 is the old arrangement on the record |
| 1807 (`f6-t3` — `Never skips`) | `needs: [test, docker] still holds on a dispatch` | `needs: [test, docker, ux] still holds on a dispatch` |
| 1814 (`f6-deploy` prose) | `needs: [test, docker]` is what makes … | `needs: [test, docker, ux]` is what makes … |
| 1815 (`f6-deploy`) | — | **new** `needs` key: "test, docker and ux — the browser suite joined the gate in G5b, after run 35723846982 paired a red ux with a green deploy" |

`grep -n "deliberately absent\|never block\|\[test, docker\]"` over the page now returns only an
unrelated "so it never blocks the event loop" (the Anthropic adapter's worker thread, line 1562).

**One layout decision.** The first attempt at line 1397 read *"ux — the browser suite; no needs: of its
own — but deploy needs it"*. Measured at 377 px it ran to x=669 and crossed the `f6-e-sec` connector's
vertical segment at x=600 (visible in the first render). Shortened to "deploy needs it" — 223 px, ends
at x=515, clear of the line. The nuance it dropped (ux declares no `needs:` of its own) is carried in
full by the `f1-ci` and `f6-deploy` nodes and by the figure's `aria-label`.

## 2. ci.yml — `paths-ignore` (gap 9)

Source: `.github/workflows/ci.yml:6-13` — `['evaluation/results/**', 'evaluation/REPORT.md', 'docs/**']`.

* **1344** — the push tile's second line was `*.md, evaluation/results/**`; it is now
  `evaluation/results/**` (the tile is 190 px wide and already elided `evaluation/REPORT.md`).
* **1802** (`f6-t1` prose) — "skips runs that changed nothing executable" → "…nothing but a published
  artifact".
* **1803** (`f6-t1` keys) — `paths-ignore` is the three published-artifact paths; `Not ignored` now says
  "corpus/** stays gated — and since G5b so does *.md at the repo root: the last commit before
  submission is a root README edit, and the docs contract tests are the guard that has to gate it";
  `Why` re-reasoned from "a documentation commit" to "rerunning the suite over a published result
  proves nothing".
* **1828** (`f6-e-t1` prose) — "keeps documentation commits off the build budget" → "keeps
  published-artifact commits off the build budget — docs/** and the two evaluation results paths, no
  longer every root-level *.md".

## 3. ci.yml — the whole-history gitleaks step (gap 7)

Source: `.github/workflows/ci.yml:30-42` (`GITLEAKS_VERSION: 8.30.1` on the job) and `:56-72` (the
action's range scan plus `gitleaks detect --source . --config .gitleaks.toml --redact --no-banner`;
280 commits / 13.22 MB / no leaks, verified there on 2026-09-22).

* **1369** (lint tile) — `gitleaks over full history` → `gitleaks 8.30.1, full history`.
* **1809** (`f6-lint` — `Secrets`) — "gitleaks over the full history, with fetch-depth: 0" → "two scans
  on one pinned 8.30.1 ruleset: the action over the pushed range, then an explicit
  `gitleaks detect --source .` over the whole history on every run — 280 commits, 13.22 MB, no leaks,
  which fetch-depth: 0 is what makes possible". `Gate` ("not in the deploy job's needs clause") is
  still true and unchanged.

## 4. MCP discovery (gap 17) and `catalog_sha` (gap 11)

Sources: `src/hrmosaic/agent/client.py:404-424` (`_http_client()` always ours, response event hook),
`:414-424` (`_note_session_id` reading `mcp-session-id`), `:429-435` (`discover()`'s "one span per turn
pass", seq 1 and seq 27 in demo task 2), `src/hrmosaic/core/redact.py:44-56, 91-99` (`DIGEST_KEYS`,
`SHA256_HEX`, `_is_public_digest`).

* **1616** (`f2-s4` prose) — "the span is emitted every turn regardless" → "…emitted once per turn pass
  regardless — and a turn resumed after a confirmation runs discovery again on the resume leg, so it
  carries two".
* **1617** (`f2-s4`) — **new** `Ids` key: "catalog_sha is the full 64-hex digest of the sorted catalog;
  mcp_session_id is read off the Mcp-Session-Id response header by an httpx event hook, and is null on
  stdio, which has no session id".
* **1672** (`f3-a0` — `Span`) — `mcp_discovery, one per turn` → `one per turn pass`.
* **1721** (`f4-k-disc` prose) — "Written every turn" → "Written once per turn pass … and a turn
  resumed after a confirmation carries two, at seq 1 and again on the resume leg (seq 27 in demo
  task 2)".
* **1722** (`f4-k-disc`) — `Cached` gains "…which is how a reader tells a resumed turn's second span
  from its first"; **new** `catalog_sha` key ("persisted in full, as 64 hex characters: redact() carves
  digest keys out of the value patterns a sha256 would otherwise trip") and **new** `mcp_session_id`
  key (the header, the httpx hook, null on stdio).
* **1553** (`f1-tracewriter` — `redact()`) — gains the carve-out clause: catalog_sha, corpus_sha256 and
  manifest_sha256 survive when the value is a bare 64-hex digest.
* **1757** (the span-model node — `Preserved`) — the three token-count fields "…and catalog_sha,
  corpus_sha256 and manifest_sha256 when the value is a bare 64-hex digest".

## 5. The evaluation nodes — 30 items, mix 7/5/6/3/5/2/2

Source: `evaluation/dataset.yaml` — 30 items; `Counter` over `category`: simple_policy 7, multi_doc 5,
tool_task 6, ambiguous 3, out_of_scope 5, unsafe_action 2, sensitive 2 (so the action-safety
denominator is n=2, as is the sensitive/escalation one).

* **745** (glance strip) `28` → `30` evaluation items.
* **1179** dataset tile "28 items, fixed order" → "30 items"; **1183** "1 unsafe · 1 sensitive" → "2
  unsafe · 2 sensitive" (the tile's other three lines already matched the new mix).
* **1193** runner tile "all 28 turns are warm" → "all 30".
* **1765** (`f5-s1` — `Mix`) → "… 2 unsafe_action, 2 sensitive".
* **1767** (`f5-s2` — `Warm-up`) "all 28 scored turns" → 30.
* **1785** (metrics — `Headline`) "target ≥ 0.85 over the 28 items" → 30.
* **1789** (latency — `Percentiles`) "across the 28 eval turns" → 30.

Left alone deliberately: **1787**'s "about $0.16 for a 264-call pass" is a measured cost of a past
judging pass, not a statement about the dataset size.

## 6. Chunks 204 → 205

Source: `data/index/ingest_report.json` (`totals.chunk_count: 205`) and `data/index/chunks.manifest.jsonl`
(205 lines).

* **500** glance strip; **1544** (`f1-index` — `Contents`) "205 chunks over 14 documents"; **1818**
  (`f6-build`) "instead of indexing 205 chunks".
* **1835** (`f6-e-boot`) — "Embedding and verifying the **204 chunks** took 107.6 s" became "Embedding
  and verifying **the index** took 107.6 s". The 107.6 s is a measurement taken over 204 chunks;
  restating it as "205 chunks took 107.6 s" would have invented a measurement, so the stale count was
  dropped and the measured number kept.

## 7. `min_dense_score` (gap 8)

Source: `mcp/tools/search_policy_documents.schema.json` — `"default": null`, `anyOf` number/null, and
the description naming MIN_SUPPORT_SCORE, 0.45 as shipped.

* **1535** (`f1-tools-rag`) — "min_dense_score default 0.26" → "min_dense_score — schema default null,
  and null (or omitted) means the server's own MIN_SUPPORT_SCORE floor, 0.45 as shipped". This is the
  page's only occurrence of 0.26; `f2-s6`'s "fewer than 2 chunks clear 0.45" and `f2-b-oos`'s
  "MIN_SUPPORT_SCORE 0.45" already agreed with it.

## 8. `check_policy_compliance` / `request_type` — no edit needed

The page never lists that tool's parameter set. `f1-tools-rag` describes it as "7 scenarios; verdict
…", and `f3-a5` / `f3-b4` list the arguments of the two demo scenarios only
(`international_remote`: duration_days, destination_country, start_date; `pto_request`: days,
start_date). Neither is an equipment scenario, so `request_type` does not appear and the new
`new | refresh | separation` wording has nothing to correct here.

---

## Verification

| Check | Result |
| --- | --- |
| `.venv/bin/pytest -q -p no:cacheprovider tests/contract/test_docs_completeness.py tests/contract/test_keep_alive.py tests/contract/test_no_broken_links.py` (one process, run after the final edit) | **`60 passed in 13.48s`** |
| `node --check` on both `<script>` blocks (extracted to temp files) | rc=0, rc=0 |
| Self-containment | `(src\|href)="https?:…"` over the page: **no matches**; no webfont, no CDN, no external script |
| Render, 1440 px, `~/Library/Caches/ms-playwright/chromium-*` via the repo's pinned Playwright, DSF 2 | page loads, **console errors: []** |

**Render inspection.** Screenshots read back with the Read tool: `#fig6 svg`, `#fig5 svg`, and the
pinned detail panels for `f6-deploy`, `f6-t1`, `f6-lint`, `f2-s4`, `f4-k-disc`, `f1-ci`, `f1-tools-rag`.

* The ci.yml box renders clean at 1440 px. `deploy — needs: [test, docker, ux]` measures 208.1 px from
  x=550 and ends at 758.1 against a tile edge of 772 (13.9 px clear). `gitleaks 8.30.1, full history`
  is 183.2 px, ending at 475.2 against 514. The push tile's two `paths-ignore` lines end at 167 and
  160.7 against 206. The `ux` label is 223 px, ending at 515, clear of the connector at x=600.
* A programmatic sweep of **every** `<text>` in every figure (`getComputedTextLength`, respecting
  `text-anchor`, against the enclosing `rect.tile`/`rect.box` with 6 px padding) flagged three strings
  — `demo_task_1.sh · _2.sh`, `gemini-3.5-flash-lite (OpenAI-compat)` and `catalog, transport` — all
  pre-existing, all 2.5–4.5 px inside their tiles, none touched by this commit. **Nothing I lengthened
  overflows.**
* The tooltips wrap normally in the pinned details panel: the `f4-k-disc` panel now shows Payload,
  Cached, catalog_sha, mcp_session_id and Out of turn with no clipping; `f2-s4` shows the new `Ids`
  row over three wrapped lines; `f1-ci`'s `ux` row wraps to four lines inside the panel column.
* Figure 5's dataset tile reads 30 / 7 simple · 5 multi_doc / 6 tool_task · 3 ambiguous /
  5 out_of_scope / 2 unsafe · 2 sensitive — which sums to 30.

## Assumptions and concerns

1. **The 107.6 s build measurement kept its number and lost its chunk count** (§6). If someone wants a
   205-chunk figure there, it has to be re-measured on a two-CPU builder.
2. **The `ux` label was shortened rather than kept verbatim** (§1) to avoid crossing an existing
   connector. The full rationale lives in two tooltips and the `aria-label`.
3. **The page is not covered by `NUMBER_DOCS`** in `tests/contract/test_docs_completeness.py`
   (README.md, ai-tooling.md, design-and-evaluation.md, docs/requirements-traceability.md). Nothing
   guards the 30 / 205 / 0.45 figures on this page against the next dataset or corpus change; the
   cheapest guard would be adding the file to `NUMBER_DOCS`, which would need the page to state the
   dataset size in a form `DATASET_COUNT_STATED` matches.
4. **The three contract tests were green including the dataset-size guard**, which Task 10 reported red
   — the documents owner fixed it before this commit, so the 60-test line above is not evidence about
   my own change to that guard.
