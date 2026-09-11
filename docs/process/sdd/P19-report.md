# P19 — the single fix wave after the final whole-branch review

**Base:** `8522c99653c59cd77cbb116769edd5a91210cf81`
**Head:** see `git log --oneline 8522c99..HEAD` — eight commits, all `P19(review-fixes): …`, all on `main`, none pushed.
**Working tree:** clean (`git status --porcelain` empty).
**Never touched:** `.env` (not read, not printed), `docs/optimization-log.md`. No live LLM call was made. The live
service was read once, `GET /health` only.

---

## Commits

| sha | subject |
|---|---|
| `d5dbe68` | the §11.1 catch-all can no longer fail inside itself |
| `1842164` | the rail and the answer stream survive the confirmation gate |
| `2365b71` | an empty secret is not a key, and the cookie is Secure behind Render's edge |
| `1e804f8` | pytest enforces the pristine-output constraint instead of asserting it |
| `25d4320` | REPORT.md's workflow row carries its n, and the cost note counts this run's calls |
| `080b5c6` | the graded documents say what a grader will actually see |
| `ca7f160` | the batched minors — bounds, redaction, stale figures, weak tests |
| `d455646` | the published test count is the one the suite collects |

---

## Definition of done — real output

| Command | Result |
|---|---|
| `./.venv/bin/ruff check .` | `All checks passed!` |
| `./.venv/bin/ruff format --check .` | `237 files already formatted` |
| `./.venv/bin/pytest -q` | `1844 passed in 162.12s (0:02:42)` — pristine, and now under `filterwarnings = ["error"]` + `--strict-markers --strict-config` |
| `./.venv/bin/python scripts/check_facts.py` | `14 documents · 57 facts · 7 rule scenarios · 33 requirements` / `OK — every quote is verbatim, every heading path is real, every fact_key resolves.` (exit 0) |
| `./.venv/bin/python scripts/pii_check.py` | `pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers` |
| `./.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest` | `OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)` |
| `make demo1` (own server) | exit 0 — `-- outcome: answered`, `-- citations (6 from 3 document(s))`, 27 spans, all six guardrails `allow` |
| `make demo2` (own server, separately) | exit 0 — gated proposal → confirm → `MOCK-HR-000012` in `hr-timeoff`, 30 spans |
| `GET https://mosaic-hr-copilot.onrender.com/health` | `200` in 17.4 s (cold) — `status ok`, `git_sha da0dca2…`, `rss_mb 292.2`, `degradations []`, `tool_count 9`. This is `origin/main`, i.e. **before** this wave; nothing here is deployed yet. |

Test count moved 1,826 → **1,844** (18 new tests, no test weakened or deleted).

---

## CONFIRMED findings — all fixed

### Critical — `src/hrmosaic/web/api.py:725`, the catch-all could raise inside itself
`unhandled_error_response`'s tail (from `buffer.add_span` through `_render_turn`) is wrapped in its own
`try/except` and falls back to a new `_internal_error_json(answer)`; `answer` is rendered before the `try` so the
fallback cannot raise. `UnhandledErrorMiddleware.__call__` wraps the handler call too, with a new
`_last_resort_error_response(scope)` built from literals alone — no store, no Jinja, no `render_answer` — returning
an HTML fragment for an `HX-Request` and JSON otherwise.

**Verified as a real defect, not an inspection claim.** The two new tests in
`tests/contract/test_unmodelled_failure_is_graceful.py` (stub-script exhaustion on turn 2 + `store.batch` raising
`StoreError` on the closing batch) were run against a temporarily reverted `api.py`:
`2 failed, 4 passed`, with uvicorn answering `500 Internal Server Error`. Against the fix: `6 passed`. As the
finding directs, nothing asserts on `ended_at` — the turn genuinely stays open when the store is unreachable, and
`sweep_stale_turns()` is the backstop.

### Important — `src/hrmosaic/web/api.py:786`, the rail went dark on the resumed half
Took option **(b)**, client-only, exactly as ruled. `chat.html`'s `htmx:configRequest` handler branches instead of
early-returning: `/chat/confirm` re-subscribes with `event.detail.parameters.turn_id` (the card's own hidden field
— nothing minted, `turnField` not overwritten), and `openStream(turnId, reset)` keeps the pre-gate rail lines when
`reset === false`. `api.py` and `sse.py` are untouched.

Tests: `tests/integration/test_sse.py` drives `/chat` to `awaiting_confirmation`, asserts the first stream ends and
`subscriber_count == 0`, then subscribes again and asserts the resumed frames (same `seq`, a `span` frame for
`create_mock_hr_ticket`, ≥1 `answer_delta`, `turn_completed` with `outcome == "answered"`). A second test covers
Cancel — note the declined outcome is `"refused"`, not `"declined"`, which the finding's sketch had wrong.
`tests/contract/test_chat_page_renders.py` pins the served page's re-subscribe.

### Important — `design-and-evaluation.md:1154`, limitation 3 named the wrong item and the wrong metric
Limitation 3 is rewritten against `remote-003` (tool recall 0.667 — verified as the **only** item below 1.00 in
`r_1789086979_baseline`), naming its three gold tools and the declined `lookup_employee_profile`. `remote-004` is
removed from it and its real residual — doc recall 0.50 over 4 `expected_docs`, one `policy_fact` block dropped by
G2, workflow completion 0.00 — moves into limitation 1 as a **document-breadth** case, with "tool recall and
precision both 1.00" stated so the old claim cannot be reconstructed.

### Important — `evaluation/REPORT.md:79`, the workflow row had no `n`
New `_workflow_completion_line(run)` in `evaluation/runner.py` replaces the bare `json.dumps`. It recomputes each
workflow's contributing item ids from the dataset's own `workflow:` tags against the run's scored items, so the
report now reads:

```
* **workflow completion by workflow** — `pto_request` 1.00 (n = 1, `pto-003`) · `remote_work_eligibility` 0.00 (n = 1, `remote-004`)
  Each demo workflow is mirrored by exactly one tagged item in `evaluation/dataset.yaml` (§13.1), so these are
  **single-item indicators, not rates**; the shortfall on `remote-004` is the §13.4 `expected_end_state` clause
  already itemised in the composite-failure table above.
```

`workflow_completion_by_workflow` itself is unchanged, so no results file and no schema moved. The "single-item
indicators" sentence is generated and disappears the moment a second item is tagged.

### Important — `evaluation/REPORT.md:120`, the stale 264-call literal
`JUDGE_COST_NOTE` became `judge_cost_note(run)`. The call count is `{run.judge_calls}`; the token totals, which
nothing records (`judges.py` tracks only `.calls`), are attributed to the run that was measured —
`r_1789055103_baseline`, 264 calls — so the arithmetic stays redoable and the number is attributable. REPORT.md
was **regenerated** with `python -m evaluation.runner --report r_1789086979_baseline`, not hand-edited; line 120
now agrees with line 12 (249). `design-and-evaluation.md:477`, `deployed.md:434` and two rows of
`docs/requirements-traceability.md` now quote the range `deployed.md`'s own cost table already publishes:
**≈ $0.16–$0.18 a pass (249–296 calls)**.

### Minor (fixed) — `README.md:14`, nothing a grader needed was clickable
All five named documents, `evaluation/REPORT.md` and `docs/demo-script.md` are markdown links;
`docs/requirements-traceability.md` is named for the first time; a CI/CD paragraph near Deployment names
`.github/workflows/ci.yml`, its four jobs **as the workflow actually declares them** (checked against the YAML
before writing), `needs: [test, docker]`, and the skipped-deploy evidence. `paths-ignore` untouched. Every relative
link was resolved against the filesystem: 13 links, 13 hits, 0 misses.

### Important — `docs/demo-script.md:52`, no persona switch anywhere in the script
Screen setup now calls for two browser profiles and states plainly that `mosaic_actor` is one cookie shared by chat
and dashboard; the 5:30, 7:40 and task-2 segment rows say to switch first; the per-turn `dashboard_url` bullet says
the link renders for every persona but 403s under `E1042`, and gives the two ways round it; the goes-wrong table
gains an `ADMIN_REQUIRED` row including the switch-back warning. `X-Actor` is **not** offered as a workaround.

### Minor (fixed) — `docs/demo-script.md:116`, the three-document certainty
Element ④ now hedges with the evidence on both sides (three of four published runs cite three;
`r_1789086979_baseline`'s `remote-004` cited two), tells the presenter to read the chips on screen, and the
goes-wrong table gains the fallback row. Retrieval, the synthesize prompt and G2 were **not** touched, and ④ was
not rewritten from a fresh `make demo1` draw.

### Minor (fixed) — `NEEDS-FROM-USER.md:197`, a gate state contradicted 27 lines later
Line 191 and the `ci-deploy-skipped.png` row both corrected; the row names the run
(`actions/runs/34485304411`), matching `deployed.md:80`. `CHANGELOG.md` untouched by this fix.
`tests/contract/test_docs_completeness.py` gains `test_the_gate_file_marks_a_committed_screenshot_as_committed`,
which pins every evidence row to what is on disk.

### Minor (fixed) — `pyproject.toml:81`, the pristine-output constraint was unenforced
`filterwarnings = ["error"]` and `addopts = "--strict-markers --strict-config"` added, with the rationale in
comments. The whole suite is green under all three.

### Minor (fixed) — `src/hrmosaic/web/api.py:326`, an empty secret opened the gate
Took the **narrow local fix**, not the `gate_misconfigured()` widening, exactly as ruled: `_authenticate` returns
403 with `MISSING_TOKEN_MESSAGE` before any comparison when the resolved token is empty, and `access_submit` gets
the same guard after its `gate_enabled` short-circuit so the gate-off redirect is preserved.
`test_the_gate_with_no_token_configured_refuses_every_empty_credential` covers bearer / cookie / `?access=` / form
— all 403, no `Set-Cookie` — using the bare `"Bearer"` header value, since httpx rejects the trailing-space form.
`/health`'s `access_token_missing` semantics and `tests/contract/test_health.py` are untouched.

### Minor (partly fixed) — `Dockerfile:57`, TLS terminated at Render's edge
- **Part 1 (done).** New `request_is_https(request)` reads `X-Forwarded-Proto` and is used at all three
  `set_cookie` sites (`mosaic_access` × 2 and `mosaic_actor`). `tests/contract/test_access_gate.py:79`'s
  "no `Secure` over loopback" stays green; a sibling test sends `X-Forwarded-Proto: https` and asserts `Secure` on
  all three cookies.
- **Part 3 (done).** `deployed.md:90` now says "marked `Secure` on the https deployment", and a new bullet explains
  the mechanism.
- **Part 2 (deliberately not implemented — see Skipped).**

---

## Minors batched in (trivial and safe)

| Where | What |
|---|---|
| `src/hrmosaic/core/injection.py:14` | the superseded §4.2 import-cost figure replaced with the ratified one plus its reproducible command |
| `src/hrmosaic/agent/orchestrator.py` | the §4.2 `agent/** → rag/` note now appears at all three crossing points, not one |
| `src/hrmosaic/agent/guardrails/g4.py:76` | the docstring's claim scoped to the `tool_call` record and the act conversation; says the synthesis prompt shows the text once, in the `quarantined="true"` envelope, and that it stays uncitable |
| `src/hrmosaic/web/api.py` (`/health`) | `mcp.last_error`, `index.error` ×2 and `trace_store.last_error` go through `redact_text` — the one open route that returns back-end exception text |
| `src/hrmosaic/web/api.py` (`ChatBody`) | `message` bounded at `MAX_MESSAGE_CHARS = 4000` (§17) |
| `src/hrmosaic/web/api.py` (`chat_stream`) | `turn_id` validated against `ID_PATTERN`, 422 `INVALID_ID` |
| `src/hrmosaic/web/sse.py:167` | `publish_span` / `publish_answer_delta` early-out when nobody is subscribed, before the frame is built |
| `src/hrmosaic/web/templates/chat.html:161` | `renderBlock` mirrors G3: an uncited `policy_fact` renders with the recommendation prefix |
| `scripts/demo_task_{1,2}.sh` | the 202 poll fall-through exits 1; demo 1 also fails on a non-`answered` outcome, an empty answer or no citations |
| `.github/workflows/ci.yml` | `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: false }` |
| `tests/architecture/test_conventions.py:3` | "Five greps" → "Six" |
| `tests/unit/test_scorer_edge_cases.py:473` | the one committed test with no assertion now bounds every score it computes |
| `tests/unit/test_limiter_burst.py:51` | 50 ms → 250 ms |
| `tests/unit/test_llm_span_emission.py:336` | `HANG_S` 0.8 → 2.0 |
| `README.md:80` | the cold-start segments no longer read as if they sum to 71.0 |
| `design-and-evaluation.md:42` | the Render box carries the figure measured on Render (293.6 MB live), not the local arm64 gate's 294.9 |
| `design-and-evaluation.md:175` | "~40 facts" → 57, the count `check_facts.py` prints |
| `design-and-evaluation.md:723`, `ai-tooling.md:174` | 1,815 → **1,844**; `docs/demo-script.md:54` now says "over 1,800 tests; read the count off the run on screen" |
| `ai-tooling.md:3` | period ends 2026-09-11 |
| `docs/pre-submission-checklist.md` | the three discharged pre-recording boxes ticked and dated; the intro's count matches the sections. The `DEMO.*`/`SUB.*` lines are left as `- [ ]` because `test_pre_submission_checklist_has_a_line_per_demo_and_sub_id` requires that literal prefix |
| `CHANGELOG.md:909` | a *(Superseded by the entry below…)* pointer appended rather than the dated entry rewritten |
| `docs/demo-script.md:53` | "about 300 MB … read the number on screen" instead of a fixed 293.6 beside a live payload |

---

## Skipped, and why

1. **`Dockerfile:57` part 2 — re-keying the rate limiter on a forwarded address.** Not trivial and not safe. On
   Render, `CF-Connecting-IP` is absent (that is Cloudflare), so the finding's preferred key is a no-op there;
   trusting a client-supplied `X-Forwarded-For` would hand any caller an unlimited supply of buckets, which is
   strictly worse than one shared bucket. The finding's own alternative — *"accept the behaviour and make the docs
   true"* — is what I took, but **only in `deployed.md`**, where a new bullet states the behaviour plainly (one
   shared 30/min bucket behind the edge; genuinely per IP locally and under Docker, and why splitting it on a
   forged header is worse). `docs/architecture.html`, `design-and-evaluation.md:634`, the spec's §11/§17 rows and
   `tests/contract/test_access_gate.py:175` still say "per IP", which is true of the code and of every non-Render
   topology. **Open for the controller:** whether to sweep that phrase through the remaining documents.

2. **`src/hrmosaic/agent/orchestrator.py:1080` — `AnswerAssembler` reset at a failover attempt boundary.** Real, but
   not a trivial edit: it needs a new hook plumbed through `CompletionRequest` / `complete()` / `_call_with_failover`
   on the most safety-critical path in the codebase, plus its own tests. The blast radius is bounded and documented
   — the deltas are provisional and hard-replaced on `turn_completed` (§11.3), and safety is unaffected — so the
   cost/benefit did not justify touching the provider call path in a fix wave. **Carry forward.**

3. **`tests/unit/test_publish_gate.py:29` — one `run_config()` factory for six `RunConfig` call sites.** Pure churn
   across six files for no behavioural gain, in a wave whose job is to land verified fixes. **Carry forward.**

4. **`tests/architecture/test_conventions.py` — the two missing greps (`mock_writes`, `confirmations`).** The
   docstring miscount is fixed. The greps are not added, because `constraints.md` line 6 (*"confirmations minted
   only in `web/`"*) is itself stale — both `INSERT INTO` statements live in `src/hrmosaic/mcpserver/confirm.py`,
   called from `POST /chat/confirm` — and `constraints.md` is the binding-constraints file for the whole roadmap.
   Correcting it is a controller decision, not a fix-wave edit. **Open for the controller.**

5. **The spec's own 264-call figure** (`docs/superpowers/specs/…:146, 1338, 1345, 1381, 2880, 2983`). The finding
   marked this step *"Optionally"*. The spec is the authoritative frozen design document and its 264 was true of the
   pass it measured; REPORT.md now names that run (`r_1789055103_baseline`) explicitly, so the number is
   attributable from the generated report. **Open for the controller** if the spec should name the run too.

6. **`tests/contract/test_zz_sec_probe.py`.** Already gone — `git status --porcelain` was empty at the start of this
   wave and is empty now. Nothing to delete.

7. **`.github/workflows/ci.yml` push-path gap (a).** Not a code change: it is a *push strategy* ("push the 12
   commits as one push"). The commits are unpushed by instruction, so this is the controller's call at push time.
   Worth restating: **HEAD is now a docs-and-code commit, so the `paths-ignore` filter does not skip this push**,
   and `ca7f160` touches `src/`, `scripts/`, `tests/` and the workflow itself. The concurrency group from gap (b)
   **is** implemented.

---

## Concerns for the controller

1. **Nothing in this wave is deployed.** `GET /health` reports `git_sha da0dca2…` = `origin/main`. The `Secure`
   cookie fix, the catch-all hardening and the empty-token refusal are all local until the push and the CI deploy.
2. **`evaluation/REPORT.md` was regenerated**, not hand-edited, and the regeneration dropped nothing: the ablation
   section is preserved by `write_report`'s marker splice and `comparison.json` is still present. Diff is 8
   insertions / 5 deletions, confined to the two lines named in the findings.
3. **`filterwarnings = ["error"]` is now load-bearing.** Any dependency bump that introduces a `DeprecationWarning`
   turns the suite red rather than printing a line. That is the point, but it is a new way for CI to fail.
4. **`make demo1` can now fail.** It asserts `outcome == "answered"`, a non-empty answer and ≥1 citation. I
   deliberately did **not** assert three distinct documents, because the same script is run against the live URL
   (`BASE_URL="$DEPLOY_URL" bash scripts/demo_task_1.sh`) where breadth varies — the very variance finding ④
   documents. If the controller wants the stricter check, it belongs behind a flag, not in the live path.
5. **The confirm-path stream fix is client-side JavaScript**, so it is pinned by a served-HTML assertion plus the
   server-frame integration tests — not by a browser. It should be eyeballed once in the browser before the take;
   the rail should keep its pre-gate lines and append the `create_mock_hr_ticket` span under them.
6. **`design-and-evaluation.md:634` and `docs/architecture.html` still say "per IP"** — see Skipped #1.
