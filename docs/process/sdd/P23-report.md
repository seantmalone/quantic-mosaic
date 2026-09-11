# P23 report — fixes from the independent grade card (2026-09-11)

**Base:** `e13a772` on `main` · **Commits:** `861de00`, `4df629f`, `7cb8f9b` (+ `docs/process` copy of this
report in a final commit) · **Nothing pushed.**

---

## 1. What landed, item by item

### 1. MCP mount returns HTTP 421 to external clients (R5.5)

**Reproduced against the live service first** (one `initialize` POST, which item 1 allows):

```
$ TOKEN=$(sed -n 's/^Deployed: .*?access=//p' README.md) && curl … https://mosaic-hr-copilot.onrender.com/health
health: 200
status ok git_sha e13a772e736a759b32f199039926d9622aa2dca7 degradations []
$ curl -X POST https://mosaic-hr-copilot.onrender.com/mcp-server/mcp \
    -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json, text/event-stream' …
mcp initialize: 421
Invalid Host header
```

**Cause, verified in the installed SDK.** `mcp/server/lowlevel/server.py:742-746`: `streamable_http_app()`
fills in a loopback allowlist whenever its `host` argument is `127.0.0.1` / `localhost` / `::1` — and
`host` **defaults to `127.0.0.1`**. So `server.streamable_http_app()` with no arguments is not "no
allowlist"; it is the loopback allowlist. The claim in `mcp/README.md:200-206` that "passing nothing
gets you nothing" was exactly backwards.

**Fix.**

* `src/hrmosaic/settings.py` — new `mcp_allowed_hosts: str = "127.0.0.1:*,localhost:*"` plus an
  `mcp_allowed_hosts_list` property that drops blanks (so a trailing comma cannot put `""` on the list).
* `src/hrmosaic/mcpserver/asgi.py` — new `transport_security(allowed_hosts=None)` builds
  `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=…, allowed_origins=…)`;
  `mount_mcp` and `build_mounted_app` take an optional `allowed_hosts` and pass it through.
  **Protection stays on**; `allowed_origins` is derived from the same list as `http://<host>` /
  `https://<host>` so the two cannot drift apart.
* `.env.example` — `MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*` (the bijection test is green).
* `render.yaml` — `MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*,mosaic-hr-copilot.onrender.com`. The two
  loopback entries stay because the agent reaches its own tools at `http://127.0.0.1:${PORT}`.
* Contract test `tests/contract/test_mcp_host_allowlist.py` (7 tests) — real `initialize` POSTs through
  the real mount: the public hostname accepted (200 with `serverInfo`), an unlisted `Host` refused
  (421 `Invalid Host header`), loopback unchanged on the shipped default; plus the settings default,
  the derived origins, and blank-dropping.
* Docs made true and precise: `mcp/README.md` (transports row + the whole *Native Host/Origin
  allowlist* section rewritten, including an explicit "this paragraph used to say it was, and that
  was wrong"), `design-and-evaluation.md:289` + the mount snippet, `deployed.md`'s Access section,
  `docs/architecture.html`'s `f1-mcpserver` endpoint line and the two inspector annotations
  (`f1-inspector`, `f1-e-inspect`), and the spec's transports table and §12.3 env table.
* `mcp/README.md` is now linked from `README.md` (Documentation line) and from
  `design-and-evaluation.md` (the MCP-server section) — one line each.

**Honesty point recorded in every one of those documents:** the running service was created over the
REST API before this setting existed, and a code deploy does not change a service's environment, so
the live endpoint **still answers 421** until an operator sets the variable. That is a three-minute
dashboard action, written up as the new optional gate **2b** in `NEEDS-FROM-USER.md`. The documents
tell a grader to demonstrate MCP over `mcp/run_stdio.sh` or `/dashboard/mcp` until then.

### 2. Stale counts (R1.3)

`pytest --collect-only -q` collects **1,962** after this phase's new tests; `coverage.xml` measures
**7,265** statements. Refreshed in `README.md` (×2), `ai-tooling.md`, `design-and-evaluation.md` (×2)
and `docs/requirements-traceability.md`.

Three new assertions in `tests/contract/test_docs_completeness.py` hold **every** occurrence in
**every** listed document (not just the first):

* `test_every_document_that_states_the_suite_size_states_the_collected_one` — runs
  `pytest --collect-only -q` in a child process (~2.4 s) and compares.
* `test_every_document_that_states_the_statement_count_states_the_measured_one` — compares against
  `coverage.xml`'s `lines-valid`.
* `test_every_published_coverage_percentage_matches_coverage_xml` — the `95% of statements and 87% of
  branches` pair, truncated the way `coverage report` prints it.

`CHANGELOG.md`, `docs/optimization-log.md` and `docs/process/sdd/**` are deliberately **not** scanned:
they record what was true on a date.

### 3. Headcount contradiction

420 everywhere: `README.md:3`, `design-and-evaluation.md:8`, `docs/demo-script.md:54` (the on-camera
line). `mock_data/README.md` gains one sentence saying its **24 employee records** are a slice of that
420-person company, so the two numbers cannot be read as a contradiction. New test
`test_every_document_that_names_the_company_size_names_the_same_one` over the five documents.

### 4. Traceability row S.5 / SUB.3

```
$ gh api repos/seantmalone/quantic-mosaic/collaborators/quantic-grader/permission
{"permission":"read", … ,"role_name":"read"}
$ gh api repos/seantmalone/quantic-mosaic/invitations
[]
```

`docs/requirements-traceability.md`'s SUB.3 row is **done** with that evidence; the checklist box is
`- [x]` and says why an empty `invitations` list is what distinguishes accepted from sent.
`test_pre_submission_checklist_has_a_line_per_demo_and_sub_id` now accepts `- [x]` as well as `- [ ]`
(a done item stays on the list rather than leaving it).

### 5. Run provenance (`git_sha: "dev"`)

* `evaluation/runner.py` — `harness_git_sha()` returns `git rev-parse HEAD` of the harness tree, with
  `settings.git_sha` as the fallback for a tree that is not a checkout; `assemble()` uses it.
* `Runner.record_target_git_sha()` reads `app.git_sha` from `/health` for every non-`local` target. It
  **is** the warm-up's first probe, which used to be discarded — no extra request.
* `evaluation/schema.py` — `target_git_sha: str | None = None` (optional, so every committed run file
  still validates).
* `REPORT.md`'s header prints `Harness git sha` and `Target git sha`; a run from before the field
  existed renders `— (not recorded; deployed.md names the commit that served this run)`.
* `judge_run()` and `scripts/refresh_eval_fixtures.py` carry the new field alongside `git_sha`.
* `deployed.md` — the *Which commit served which evaluation run* paragraph now explains both shas and
  states plainly that the committed run files are **not** rewritten; the three-row deploy ledger stays.
* `evaluation/REPORT.md` regenerated from the fixed template with `python -m evaluation.runner --report
  r_1789086979_baseline`, which reads only and spends nothing. The ablation block is preserved by
  `write_report`; the only diff is the two header rows and the two labeller sentences.

### 6. Labeller wording

Both `evaluation/reference_labels.yaml` and `reference_labels_hard.yaml` (schema keys unchanged) now
read: *"the same vendor as the agent (Anthropic claude-haiku-4-5), a different model, in an independent
session that read only the packet — and a different vendor and family from the judge"*. The runner
emits `protocol.labeller` verbatim, so fixing the data fixed the generated text; `REPORT.md` was
regenerated rather than hand-edited. `design-and-evaluation.md`'s *Judge methodology* paragraph says
the same and names the old wording as wrong, and says why the distinction matters.

### 7. Architecture page claims

`docs/architecture.html` no longer loads Google Fonts — the two `preconnect` links and the `css2`
stylesheet are gone and the three font variables are system stacks with real fallback chains, so
`design-and-evaluation.md:80`'s "no build step and no network access" is true. `grep` for
`https://fonts` / `cdn` / `unpkg` / `jsdelivr` in the file returns nothing. The two inspector
annotations named by the card are corrected (see item 1).

### 8. AI-tooling audit trail pointer (P.2)

`docs/process/sdd/` now holds `progress.md`, all 21 `P*-brief.md`, all 24 `P*-report.md`,
`final-review-brief.md`, `constraints.md`, `grade-card-2026-09-11.md` and a `README.md` index that says
what is there, what is deliberately not (the review `.diff`s, reproducible from `git diff`; the
controller handoff JSON) and how it was scanned. `ai-tooling.md`'s *Where the process is auditable*
paragraph points at it.

Scanned before copying: `sk-ant-` / `sk-…` / `AIza` / JWT / `ghp_`/`github_pat_` shapes, and the live
access token by exact match. The only matches are deliberately synthetic placeholders quoted inside
test output (`sk-ant-api03-AAAA…`, `ci-access-token`). gitleaks' `curl-auth-header` rule flags three
`Bearer ci-access-token` lines pasted into `P11-report.md` from the CI docker job's own log, so
`.gitleaks.toml`'s existing rule/path/line carve-out for that exact literal is extended to
`^docs/process/sdd/` and nothing else — the alternative was editing the trail, which defeats the point
of committing it.

### 9. Demo-2 citation expectation

Stated as observed, not as designed, in `docs/demo-script.md` (beat ④), `design-and-evaluation.md`
(a new *What a live run actually cites* paragraph in the demo-2 section) and
`tests/e2e/test_demo_tasks.py` (module docstring + a comment on `min_distinct_docs_cited`). **The stub
assertion is unchanged at 2** — the docstring says the recorded script is the design expectation while
live turns vary. The live run captured today cited **two** documents (`pto-and-holidays`,
`manager-approval-matrix`), which is *better* than the card's observation of one; the documents say
breadth is non-deterministic and tell the presenter to read the chips on screen.

### 10. `KEEP_ALIVE_URL` in the blueprint

`render.yaml` gains `KEEP_ALIVE_URL=https://mosaic-hr-copilot.onrender.com` and
`KEEP_ALIVE_INTERVAL_S=600`. The deploy-manifest contract test's expected plain-value set is updated
and two new assertions were added (the allowlist carries the public hostname *and* both loopback
entries; the blueprint carries the keep-alive). `tests/unit/test_provision_render.py`'s `plain_env`
expectation follows — without it a re-provision would strip both.

`tests/contract/test_keep_alive.py` previously asserted that **no** repository file sets the variable,
and said in its own docstring that setting it in `render.yaml` must fail there and be fixed in the same
commit. It is: the test now asserts the blueprint carries it and the `Dockerfile` never does (a baked
origin would start the loop in every container a developer runs), and the published-documents check
keeps its conditional requirement. `README.md`, `deployed.md` (×3), `docs/architecture.html` and the
spec (×3) are corrected from "this repository does not set it" to "`render.yaml` carries it for a
blueprint apply; it is not set on the live service".

### 11. Pinned end-to-end evidence

Both scripts run **once** each against the live service (the only chat turns this phase spent):

* `docs/evidence/demo-task-1-live-2026-09-11.txt` — `answered`, `conditional` verdict, 8 citations
  across **3** documents, 30 spans, 6 model calls / 8 tool calls, 39.4 s.
* `docs/evidence/demo-task-2-live-2026-09-11.txt` — the confirmation gate (`CONFIRMATION_REQUIRED`,
  nothing written), then `MOCK-HR-000005`, 4 citations across **2** documents, 29 spans, 30.1 s.

Each carries a provenance header naming the command, the date, the target's `/health` sha and the
redaction. The token is sent as a header and was asserted absent from both transcripts
(`grep -qF "$APP_ACCESS_TOKEN"` → no match) before they were written. Linked from README's demo-task
section and from the `R6.5` and `DEMO.5` traceability rows.

### 12. Grade card into the repo

`docs/evidence/grade-card-2026-09-11.md`, linked from `docs/pre-submission-checklist.md` as the
independent pre-submission assessment, with a pointer to its §4 (what the video must show) and §6
(what a grader trips over).

---

## 2. TDD evidence

**Item 1 — the allowlist.** The bug was reproduced through the real mount before any code changed:

```
$ .venv/bin/python scratchpad/probe_mount.py
loopback: 200 event: message data: {"jsonrpc":"2.0","id":1,"result":{"capabilities":…
render host: 421 Invalid Host header
```

Then the test was written against the intended API and watched fail:

```
$ .venv/bin/pytest -q tests/contract/test_mcp_host_allowlist.py
E   ImportError: cannot import name 'transport_security' from 'hrmosaic.mcpserver.asgi'
1 error in 0.39s
```

and after the implementation:

```
$ .venv/bin/pytest -q tests/contract/test_mcp_host_allowlist.py tests/contract/test_env_example_covers_settings.py
..........                                                               [100%]
10 passed in 1.12s
```

**Item 5 — run provenance.** `tests/unit/test_run_provenance.py` written first, all five red:

```
$ .venv/bin/pytest -q tests/unit/test_run_provenance.py
FAILED … ::test_the_harness_sha_is_the_working_tree_s_real_head
FAILED … ::test_a_tree_that_is_not_a_checkout_falls_back_rather_than_raising
FAILED … ::test_the_run_file_carries_both_shas_and_target_sha_is_optional
FAILED … ::test_the_report_header_prints_the_harness_sha_and_the_target_sha
FAILED … ::test_a_local_run_says_so_rather_than_printing_an_empty_cell
5 failed in 0.77s
```

green after the implementation (a sixth test for the pre-2026-09-11 fallback was added with its
message):

```
$ .venv/bin/pytest -q tests/unit/test_run_provenance.py
......                                                                   [100%]
6 passed in 0.79s
```

**Item 2 — the number assertions.** Written before the numbers were refreshed, and red on the real
staleness:

```
E   AssertionError: README.md says ['7,135'] statements; coverage.xml measures 7,256
E   AssertionError: README.md: statements % is stale
FAILED … ::test_every_document_that_states_the_suite_size_states_the_collected_one
3 failed, 40 passed in 3.26s
```

**Item 10 — the keep-alive doc-claim test** failed on the `render.yaml` edit exactly as its own
docstring predicted it would, and was rewritten with the documents in the same commit.

**Item 4** — `test_pre_submission_checklist_has_a_line_per_demo_and_sub_id` failed on the `- [x]` tick
(`needs exactly one - [ ] SUB.3 line`) before being widened to accept a ticked box.

The headcount test was written after the three files were already fixed, so it was never red; it is a
regression guard, not a discovery. Recorded here rather than dressed up.

---

## 3. Definition of done — real output

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
248 files already formatted

$ .venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers

$ .venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)

$ .venv/bin/pytest --collect-only -q | tail -1
1962 tests collected in 1.75s
```

```
$ .venv/bin/pytest -q
........................................................................ [ 99%]
..................                                                       [100%]
1962 passed in 171.01s (0:02:51)
```

Pristine: no warnings, no skips, no xfails.

```
$ make coverage
…
src/hrmosaic/web/sse.py                                     117      0     28      0   100%
-------------------------------------------------------------------------------------------
TOTAL                                                      7265    315   1470    166    94%
```

94 % combined against the 90 % gate (95 % of statements, 87 % of branches, 7,265 statements).

```
$ make demo1 ; echo "exit=$?"
demo1 exit=0
-- outcome: answered
-- citations (6 from 3 document(s))
-- usage: 5 model call(s), 7 tool call(s), 5 retrieval(s), 31985→1797 tokens in 618 ms

$ make demo2 ; echo "exit=$?"
demo2 exit=0
-- outcome: answered
-- the confirmed write is reported as done: MOCK-HR-000023 is named in the answer
-- citations (3 from 2 document(s))
-- usage: 7 model call(s), 6 tool call(s), 2 retrieval(s), 38858→1713 tokens in 486 ms
```

**gitleaks 8.30.1** (the P17 binary in the scratchpad), over full history including the three new
commits:

```
$ gitleaks detect --source . --config .gitleaks.toml --redact --no-banner
INF 141 commits scanned.
INF scanned ~8201004 bytes (8.20 MB) in 854ms
INF no leaks found
```

and over the working tree, to catch anything not yet committed:

```
$ gitleaks dir . --config .gitleaks.toml --no-banner --redact --report-format json --report-path …
WRN leaks found: 23
$ # every finding, checked against `git check-ignore`:
IGNORED  .env
IGNORED  .superpowers/sdd/2026-09-08-implementation-roadmap/P11-report.md
IGNORED  .superpowers/sdd/2026-09-08-implementation-roadmap/review-*.diff        (6 files)
IGNORED  data/runtime/post_gate_results.json
IGNORED  data/runtime/provision_turso.json
→ 0 findings in any tracked or newly-added path
```

Before the `.gitleaks.toml` carve-out was extended, the same scan reported **26**, the extra three
being the `Bearer ci-access-token` lines in `docs/process/sdd/P11-report.md`. That is the finding the
carve-out answers, and the scan proves it is the only one.

**Live calls made (exactly the four the brief allows):** one `GET /health`, one MCP `initialize` POST
(item 1's verification), and one run each of `demo_task_1.sh` / `demo_task_2.sh` (item 11). Two chat
turns, ≈ $0.03. `.env` was never read, printed or committed; the access token was read from README's
`Deployed:` line into an environment variable inside a single shell command and never echoed.

---

## 4. Files changed

**Code**

| File | Change |
|---|---|
| `src/hrmosaic/mcpserver/asgi.py` | `transport_security()`; `mount_mcp` / `build_mounted_app` take `allowed_hosts`; module docstring explains the SDK default |
| `src/hrmosaic/settings.py` | `mcp_allowed_hosts` + `mcp_allowed_hosts_list` |
| `evaluation/runner.py` | `harness_git_sha()`, `Runner.record_target_git_sha()`, both shas into `assemble()` / `judge_run()` / the REPORT header |
| `evaluation/schema.py` | `RunFile.target_git_sha` |
| `scripts/refresh_eval_fixtures.py` | carries `target_git_sha` with the source run's provenance |

**Manifests and config**

`.env.example` (`MCP_ALLOWED_HOSTS`), `render.yaml` (`MCP_ALLOWED_HOSTS`, `KEEP_ALIVE_URL`,
`KEEP_ALIVE_INTERVAL_S`), `.gitleaks.toml` (the `docs/process/sdd/` path on the existing
`curl-auth-header` carve-out).

**Tests**

| File | Change |
|---|---|
| `tests/contract/test_mcp_host_allowlist.py` | **new** — 7 tests, real `initialize` through the mount |
| `tests/unit/test_run_provenance.py` | **new** — 6 tests |
| `tests/contract/test_docs_completeness.py` | +4 tests (suite size, statement count, coverage %, headcount); ticked checklist boxes accepted |
| `tests/contract/test_deploy_manifests.py` | plain-value set updated; +2 tests |
| `tests/contract/test_keep_alive.py` | doc-claim test split: the blueprint carries the URL / the image never does, and the documents stay conditional |
| `tests/unit/test_provision_render.py` | `plain_env` expectation |
| `tests/e2e/test_demo_tasks.py` | docstring + comment on live vs recorded citation breadth (no assertion weakened) |

**Documents**

`README.md`, `ai-tooling.md`, `deployed.md`, `design-and-evaluation.md`, `mcp/README.md`,
`mock_data/README.md`, `NEEDS-FROM-USER.md`, `docs/architecture.html`, `docs/demo-script.md`,
`docs/pre-submission-checklist.md`, `docs/requirements-traceability.md`,
`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`, `evaluation/REPORT.md` (regenerated),
`evaluation/reference_labels.yaml`, `evaluation/reference_labels_hard.yaml`.

**New artifacts**

`docs/evidence/demo-task-1-live-2026-09-11.txt`, `docs/evidence/demo-task-2-live-2026-09-11.txt`,
`docs/evidence/grade-card-2026-09-11.md`, `docs/process/sdd/` (52 copied files + a `README.md` index).

`docs/optimization-log.md` was not touched.

---

## 5. Ambiguities resolved, and how

1. **"Keep protection ON" vs. a reachable endpoint.** The brief's default
   (`127.0.0.1:*,localhost:*`) does **not** include the Render hostname, and a service's environment
   is not changed by deploying code. So the code fix alone cannot make the live endpoint answer. I
   took the simplest reading that satisfies the spec: ship the setting, put the hostname in
   `render.yaml` (the brief's own instruction), and make every document state the *current* live
   behaviour — 421 until an operator sets the variable — rather than the behaviour the fix enables.
   The operator action is written up as optional gate **2b**.
2. **`allowed_origins` was not specified.** Derived from the same host list as `http://<host>` and
   `https://<host>`. An absent `Origin` is accepted by the SDK middleware regardless, so this only
   constrains a browser-sent one, and deriving it means the two lists cannot drift.
3. **"README's evidence list"** — README has no single evidence list; its evidence links are inline.
   The two transcripts are linked from the *two demo tasks* section, which is where a reader looking
   for them would be.
4. **"Fix the template, not the output" (item 6) vs. a false claim in `REPORT.md`.** I fixed the
   template (the YAML the runner emits verbatim) and then **regenerated** `REPORT.md` with the
   offline `--report` command, which re-renders from the committed run file, spends nothing and
   preserves the ablation block. Hand-editing it would have been the thing the instruction forbids;
   leaving a document a grader reads carrying the wrong claim seemed worse than re-running a
   generator. The diff is exactly four lines.
5. **`coverage.xml` is git-ignored.** The statement-count and percentage tests therefore cannot
   assume it exists — in CI the suite runs *before* `coverage xml` is written. They fall back to
   asserting the documents agree with one another, and say so in the docstring; `make coverage` is
   where the figures meet the measurement, and it is a definition-of-done command. Both paths were
   exercised (the file was moved aside and the suite re-run).
6. **`24 employee records`.** No document conflated the record count with the headcount, so there was
   nothing to correct; instead `mock_data/README.md` now says explicitly that 24 records are a slice of
   the 420-person company, which is where a reader would otherwise see a contradiction.
7. **Demo-2 breadth.** The card observed one cited document; today's live run cited two. Rather than
   assert either, the documents now say breadth is non-deterministic, name what the committed
   transcript shows, and tell the presenter to read the chips on screen.
8. **Commit attribution.** This session's harness instruction names
   `Co-Authored-By: Claude Opus 5 (1M context)` and states it replaces earlier attribution guidance;
   `constraints.md` line 14 names `Claude Fable 5.1`. I followed the session instruction, because the
   alternative is a factually wrong co-author line. **This breaks the repository's 138-commit
   convention and is visible in `git log`** — flagged rather than buried; say the word and I will
   amend the three commits.

---

## 6. Self-review findings (and what I did about them)

* `asgi.py`'s module docstring said "`render.yaml` sets it on the live service". It does not — it is a
  blueprint value and the live service was created by API. **Reworded** to "carries the deployment's
  hostname".
* `Runner.record_target_git_sha()` returned the `/health` dict that no caller used. **Changed to
  `-> None`.**
* The first draft of the blank-dropping test asserted `transport_security([]) == []`, which tests the
  helper rather than the parsing it was named for. **Rewritten** to parse
  `Settings(mcp_allowed_hosts="127.0.0.1:*, ,host,")`.
* `mock_data/README.md`'s new sentence first read "a 24-employee records slice", which is not English.
  **Fixed.**
* The spec edit for the keep-alive left a stray `)` mid-sentence. **Fixed**, and every
  "set nowhere in this repository" variant was re-grepped to zero.
* Item 10's change silently falsified five *other* documents' "this repository does not set it"
  sentences and would have left `test_keep_alive`'s published-docs check passing on a stale premise.
  Caught by re-grepping the phrase rather than by a test; **all five corrected in the same commit**.
* `.gitleaks.toml`: the three `Bearer ci-access-token` findings in the copied `P11-report.md` would
  have entered *history* on commit and failed CI's own gitleaks job, not just my local scan. Caught by
  scanning the staged tree before committing.

---

## 7. Concerns

1. **The 421 is still live.** Everything is in place, but the deployed endpoint keeps refusing
   external MCP clients until `MCP_ALLOWED_HOSTS` is set on the Render service — an action that needs
   `RENDER_API_KEY` (in `.env`, which I must not read) or the dashboard. Gate 2b. Every document that
   mentions the endpoint states this plainly, so nothing is over-claimed, but the grade card's "421
   trap" is mitigated by disclosure rather than removed.
2. **`KEEP_ALIVE_URL` in `render.yaml` is a loaded gun for a blueprint apply.** Applying the blueprint
   now arms a keep-alive that spends ~744 of the workspace's 750 free instance-hours per month. That is
   the brief's explicit instruction and the arithmetic is documented in `deployed.md`, but anyone who
   re-applies the blueprint without reading it will spend the month's budget.
3. **`evaluation/REPORT.md` still shows `Harness git sha: dev`** for the published run, because the
   committed run file predates the field and is not rewritten. `deployed.md` carries the serving
   commit for all three deployed runs. The new provenance only starts paying off on the *next* run.
4. **The suite-size test costs ~2.4 s** (a child `pytest --collect-only`). It runs once per suite, so
   the cost is small, but it does mean `pytest tests/contract/test_docs_completeness.py` spawns a
   second pytest.
5. **`docs/process/sdd/` adds 1.2 MB and 53 files to the repository.** CI's `paths-ignore` covers
   `docs/**`, so it costs no build minutes, but it is a large addition to what a grader browses. The
   index `README.md` is there to stop it reading as dumped state.
6. **The live evidence is a single sample each.** Both transcripts are one run; demo-1 cited 3
   documents and demo-2 cited 2, which are the *good* outcomes on a non-deterministic behaviour. The
   documents say so rather than generalising from n=1.
7. **Item 4's traceability row is marked done from a `gh api` read taken today.** If the grader's
   access is ever revoked the row goes stale with nothing to catch it — no test can assert a GitHub
   permission offline.
