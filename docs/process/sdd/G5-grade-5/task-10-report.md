# Task 10 report — round-2 code and configuration (G5b)

**Commit:** `6e71e0f` — *G5b(code): the clarification asks the reader's own question, and eight claims become true*
(parent `9dcd8dd`, Task 11's dataset/corpus commit). Branch `main`. Staged with explicit `git add`; nothing
under `corpus/`, `evaluation/dataset.yaml`, `data/index/chunks.manifest.jsonl`, `scripts/corpus_stats.py` or
`evaluation/results/chunk_size_comparison.json` was touched.

**Collected suite:** 3,415 → **3,435** (`pytest --collect-only -q -m ""`). +6 are mine, +14 came from Task 11's
dataset parametrisation. The `test` job runs **3,136** of them (299 `ux` deselected).

---

## 1. Gap 2 (high) — amb-001 was served amb-002's question

* `src/hrmosaic/agent/orchestrator.py:384` — `clarify_topic_workflow(text: str)` now takes **one** string
  (was `*texts` joined with `" ".join(...)`), and the docstring says why.
* `src/hrmosaic/agent/orchestrator.py:2947` — the call site is two calls, the reader's message first:
  `clarify_topic_workflow(turn.request.message) or clarify_topic_workflow(decision.rationale_summary or "")`.
* `src/hrmosaic/agent/orchestrator.py:288-303, 2899-2913` — the table comment and `_clarification_text`'s
  docstring record the order and the failure it fixes.
* New fixture `tests/fixtures/llm_scripts/clarify_pto_rationale_names_remote_work.json` replays the published
  routing for amb-001 (`policy_qa`, `workflow: null`, a rationale that mentions remote work in passing).
* New test `tests/unit/test_clarification_names_every_missing_slot.py:227` —
  `test_amb_001_asks_about_time_off_even_when_the_rationale_says_remote_work`: the question names the dates and
  the day count, does **not** name the destination or the duration, and asks one question.

**Evidence the test bites.** With the fix temporarily reverted to the old joined form, the new test failed with
the served answer *"Happy to check — where would you be working from? I will also need to know how long you
would be there, and from when."* — byte-identical to amb-001's `answer` in
`evaluation/results/r_1790074972_baseline.json`. Restored, all 15 tests in the file pass (amb-002 ×2 and amb-003
included).

**Assumption (stated as the brief allows).** The published run file carries no route span, and the deployed
trace API needs `APP_ACCESS_TOKEN`, which lives only in `.env` (never read, per the rules). The fixture's
`rationale_summary` is therefore a **reconstruction** of the shape the gap documents — a rationale whose topic
words point at remote work on a time-off question — not the recorded bytes; the fixture's `_note` says so. The
property under test (message beats rationale) is exactly the one the gap names, and the reproduction above
shows the fixture recreates the published answer under the old code.

## 2. Gap 8 — `min_dense_score` default 0.26 vs effective 0.45

* `src/hrmosaic/mcpserver/tools/search_policy_documents.py:194` — `float | None = None`.
* `:205` — `threshold = settings.min_support_score if min_dense_score is None else min_dense_score`
  (`rag/retrieve.py:133`'s idiom). `call.supplied()` no longer decides it, so an explicit `null` and an omitted
  argument now agree.
* `:81-89` — the published description names the effective default: *"Omit it (or send null) for the server's
  own support floor — MIN_SUPPORT_SCORE, 0.45 as shipped."* The number is written as a literal rather than
  interpolated from `settings`, so the committed schema bytes cannot depend on a developer's `.env`.
* `mcp/tools/search_policy_documents.schema.json` regenerated: `"default": null` plus the `anyOf` number/null.

No spec-side expectation needed updating: `tests/contract/test_tools_match_spec.py` never asserted the default,
and `tests/contract/test_tool_schemas_committed.py` compares the committed bytes to a live `tools/list`.

## 3. Gap 11 — `catalog_sha` persisted as `[REDACTED]`

* `src/hrmosaic/core/redact.py:44-56` — `DIGEST_KEYS = {"catalog_sha", "corpus_sha256", "manifest_sha256"}` and
  `SHA256_HEX`.
* `:91-99` — `_is_public_digest(key, value)` short-circuits `_walk` for those keys **when the value is a bare
  64-hex digest**, so the carve-out cannot hide a secret named `corpus_sha256`. Module docstring updated.
* `tests/unit/test_g6_redact.py:120` — new test: three digest keys survive; `FAKE_BASE64` under `catalog_sha`
  and a fake Anthropic key under `corpus_sha256` are still `[REDACTED]`; a digest under any other key is still
  swept.
* `tests/integration/test_audit_completeness.py:50` — the vacuous `assert payload["catalog_sha"]` is now
  `re.fullmatch(r"[0-9a-f]{64}", …)`, i.e. the digest **as persisted**.

## 4. Gap 17 — null session id, "one discovery span per turn", retry wording

Chose to **capture** the id rather than drop the field; capture is the smaller true change here (it leaves four
documents accurate instead of requiring four edits and two fixture rewrites).

* `src/hrmosaic/agent/client.py:404-424` — `_http_client()` always returns our own `AsyncClient` (same
  `LOOPBACK_TIMEOUT`, which mirrors `create_mcp_http_client`'s 30 s / 300 s) with a response event hook,
  `_note_session_id`, that records the `Mcp-Session-Id` header. Note `streamable_http_client` in **mcp 2.2.0
  yields only `(read, write)`** — there is no `get_session_id` callback to use, and `ClientSession` has no
  `session_id` attribute; the header is the only seam.
* `:369-371, :455, :479, :492` — the field, the per-handshake reset, and the reset on `reset()`.
* `:429-435` — `discover()`'s docstring now says **one span per turn pass**, and why a resumed turn carries two.
* `src/hrmosaic/agent/orchestrator.py:7-8` (the module diagram) and `:1592-1598` (`_discover`) say the same, and
  `_discover` now states the retry accurately: one re-discovery, and a failing `tools/call` degrades the turn.
* `tests/integration/test_audit_completeness.py:44-56` — asserts `payload["mcp_session_id"]` is non-empty.
* `tests/unit/test_loopback_client_timeouts.py:41` — the "`None` so the SDK builds its own" test became
  `test_the_ungated_client_is_still_ours_and_still_reads_for_five_minutes` (300 s read + the hook present).

Probe: a mounted-server handshake recorded `mcp_session_id = 2f2ba7aecaff45a1b0a70e590384c293`.

## 5. Gap 18 — "two declarative workflows"

* `src/hrmosaic/agent/router.py:44` — "The three declarative workflows of §9.3, plus 'no workflow'."
* `src/hrmosaic/agent/workflows/__init__.py:1, :11` — "three", and "All three predicates below…".
* `tests/unit/test_expense_claim_is_scored.py:69` — `test_the_predicate_closes_on_a_profile_a_verdict_and_two_citations`
  over empty / profile-only / complete. It is the first test that observes `expense_claim.SPEC.is_complete`
  returning `True`.

## 6. Gaps 16 + 9 — CI gating and the push filter

* `.github/workflows/ci.yml:178` — `needs: [test, docker, ux]`; `:197` — the R8.4 comment updated.
* `:92-105` — the "`needs:` is deliberately absent — it must never block `test` or `deploy`" rationale is
  rewritten: `ux` still has no `needs:` of its own, but `deploy` needs it, with run 35723846982 named.
* `:6-13` — `'*.md'` removed from `paths-ignore` (kept: `evaluation/results/**`, `evaluation/REPORT.md`,
  `docs/**`), with the submission-commit reasoning in the comment.
* `tests/contract/test_deploy_manifests.py` — `test_ci_has_the_four_jobs_of_15_1_plus_the_ux_suite` and
  `test_deploy_needs_every_job_that_runs_tests` (renamed from `…both_test_and_docker`) assert the new list; the
  module docstring's `needs: [test, docker]` bullet updated; **new** `test_a_root_readme_commit_still_runs_the_suite_and_deploys`.
* `tests/contract/test_keepalive_workflow.py` — unaffected (it parses `keepalive.yml` only); green.

## 7. Gap 7 — the full-history gitleaks scan

* `.github/workflows/ci.yml:30-42` — `GITLEAKS_VERSION: 8.30.1` moved to the **job** env so both scans share
  one pin (the action reads the name from the environment), with the existing pin rationale relocated there.
* `:56-72` — the action step keeps its per-push range scan; a new step
  `gitleaks over the whole history` downloads the pinned binary and runs
  `gitleaks detect --source . --config .gitleaks.toml --redact --no-banner`, the invocation both committed gate
  logs (P17, P23) used. `fetch-depth: 0` was already on the checkout.
* `tests/contract/test_deploy_manifests.py` — **new** `test_the_lint_job_scans_the_whole_history_on_every_run`
  (pin, `fetch-depth: 0`, the detect line, `$GITLEAKS_VERSION` in the download, and the action still present).

**Verified locally with the real binary** (downloaded to `/tmp`, not committed):

```
$ gitleaks version                       → 8.30.1
$ gitleaks detect --source . --config .gitleaks.toml --redact --no-banner
INF 280 commits scanned.
INF scanned ~13223437 bytes (13.22 MB) in 2.61s
INF no leaks found                        (exit 0)
```

YAML re-parsed after every edit with
`.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`.

## 8. Gap 20(a) — the Makefile `lock` recipe

* `Makefile:20` — `lock` added to `.PHONY`; `:28-41` — the target with the three commands taken verbatim from
  each manifest's own `uv pip compile` header (`requirements.txt`, `--group pyproject.toml:dev`,
  `--group pyproject.toml:ux`), and a comment on why `uv` is not a project dependency.
* `pyproject.toml:15`'s pointer ("see the `lock` recipe in the Makefile") is now true; left unedited.
* Verified with `make -n lock` (prints the three commands). **Not executed**: `uv` is not installed on this
  machine and running it would rewrite the committed pins.

## 9. Gap 13 (dashboard half) — an agreement figure without its subset

* `src/hrmosaic/web/templates/dashboard/eval_detail.html:136-151` — the blind figure prints
  `· <subset> subset` beside it (or `· subset not recorded` when `judge_agreement_subset` is null, which is
  exactly `r_1790067656_baseline`'s case), and the hard-case figure — carried by every run file and rendered by
  no template until now — appears with its own `n` and subset when it exists.
* `src/hrmosaic/web/dashboard.py:216-218` — `METRIC_LABELS["judge_agreement_rate_hard"] = "Judge agreement (hard cases)"`.
* `tests/fixtures/eval_runs/r_p9fixture_baseline.json:117-120` — the fixture's agreement block was **stale
  relative to its own source run**: `scripts/refresh_eval_fixtures.py` copies these six fields from
  `evaluation/results/r_1789032950_baseline.json`, which carries `seed_1729_8` / `0.875` / `8` /
  `judge_lowest_8` while the fixture still had `null` / `null` / `0` / `null`. Brought into line, so a regen is
  a no-op again.
* `tests/contract/test_dashboard_viewmodels.py:262` — extended the page-11 section with
  `test_each_judge_agreement_figure_is_rendered_beside_the_subset_it_was_computed_over`, which renders
  `/dashboard/evals/r_p9fixture_baseline` and asserts both labels and both subset names inside
  `#behaviour-metrics`. (One added collected test: the existing view-model tests assert payload fields only, and
  the rendered provenance is the thing gap 13 is about.)

## 10. Coordinator add-on — `check_policy_compliance` and `request_type`

* `src/hrmosaic/mcpserver/tools/check_policy_compliance.py:104-116` — `PARAMETERS_DESCRIPTION` now lists
  `request_type` among the scenario facts and names its closed set: `"new"` (additional or upgraded equipment),
  `"refresh"` (a device at or past its 36-month cycle), `"separation"` (a return), with the note that the
  equipment director-approval threshold is evaluated only for `"new"`. The three values were read off
  `corpus/rules.yml`'s `parameter_eq:request_type:*` guards (`new`, `refresh`, `separation` — no others).
* `mcp/tools/check_policy_compliance.schema.json` regenerated.

---

## Commands run, with their summary lines

| Command | Result |
| --- | --- |
| `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_clarification_names_every_missing_slot.py` | `15 passed in 7.82s` |
| …the same, with the fix reverted to the joined form | `1 failed, 14 passed` (served amb-002's question) |
| `.venv/bin/pytest -q … tests/unit/test_g6_redact.py` | `10 passed in 0.71s` |
| `.venv/bin/pytest -q … tests/unit/test_expense_claim_is_scored.py` | `4 passed in 3.29s` |
| `.venv/bin/pytest -q … tests/integration/test_audit_completeness.py` | `9 passed in 11.89s` |
| `.venv/bin/pytest -q … tests/unit/test_loopback_client_timeouts.py` | `3 passed in 1.10s` |
| `.venv/bin/pytest -q … tests/contract/test_deploy_manifests.py tests/contract/test_keepalive_workflow.py` | `47 passed in 1.08s` |
| `.venv/bin/pytest -q … tests/contract/test_tool_schemas_committed.py test_tools_match_spec.py test_prompt_golden.py` | `46 passed in 1.46s` |
| `.venv/bin/pytest -q … tests/contract/test_dashboard_viewmodels.py` | `26 passed in 27.97s` |
| `.venv/bin/pytest -q … tests/contract/test_formatter_coverage.py tests/contract/test_dashboard_pages.py` | green (in the 63-test dashboard run) |
| `make lint` | `All checks passed!` / `321 files already formatted` |
| `.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest` | `OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (205 chunks)` |
| `.venv/bin/pytest -q -p no:cacheprovider tests/contract tests/unit tests/integration tests/architecture` | `1 failed, 3127 passed in 340.41s` — the one failure is **Task 11's**, below |
| re-run **after** the commit: `… tests/contract tests/architecture` | `1 failed, 563 passed in 181.67s` (the same Task 11 failure) |
| re-run **after** the commit: `… tests/unit tests/integration` | `2564 passed in 162.09s` |
| `.venv/bin/pytest -q -p no:cacheprovider --collect-only -m ""` | `3435 tests collected` |
| `gitleaks detect --source . --config .gitleaks.toml --redact --no-banner` (8.30.1) | `280 commits scanned … no leaks found` |

**The one red test at my commit is not mine:**
`tests/contract/test_docs_completeness.py::test_every_document_that_states_the_dataset_size_states_the_one_in_dataset_yaml`
— *"README.md says ['28', '28'] dataset items; evaluation/dataset.yaml holds 30"*. It went red with Task 11's
commit `9dcd8dd` (28 → 30 items) and is the dataset/docs owner's to fix; the same sweep must cover every
document in `NUMBER_DOCS` (README.md, ai-tooling.md, design-and-evaluation.md,
docs/requirements-traceability.md), not README alone. The suite-size half of that guard
(`…states_the_suite_size…`) is **green** at 3,435.

---

## Document sentences the docs task must update

**`needs: [test, docker]` → `[test, docker, ux]`, and the "ux never blocks" rationale**

* `README.md:66` — *"…and CI runs them in a job of their own that never blocks `test` or `deploy`."*
* `README.md:157` — *"…deployed only by a CI job that `needs: [test, docker]`."*
* `README.md:170` — *"…`deploy`, which carries `needs: [test, docker]`…"* — and the same paragraph still
  enumerates lint/test/docker/deploy without naming `ux` at all (gap 16's second half).
* `design-and-evaluation.md:839` — the `ux` row of the jobs table ("no `needs:`, never blocks").
* `design-and-evaluation.md:841` — the `deploy` row: *"`needs: [test, docker]`, main pushes…"*.
* `design-and-evaluation.md:860` — *"`deploy` declares `needs: [test, docker]`."*
* `docs/requirements-traceability.md:149` (R8.2) — *"…`ux` carries no `needs:` by design — 'it must never block
  `test` or `deploy`'"*, twice in the row, and *"then `deploy` declares `needs: [test, docker]`"*.
* `docs/requirements-traceability.md:151` (R8.4) — *"The `deploy` job declares `needs: [test, docker]`…"*.
* `docs/requirements-traceability.md:228` (RUBRIC5.7) — the deploy-gate clause.
* `docs/demo-script.md:76` — *"**`deploy` declares `needs: [test, docker]`**"* **and** the spoken line
  *"Say why `ux` is deliberately **not** in that list — 'a browser suite must never be able to block a deploy…'"*
  (this is narrated on camera and is now false).
* `deployed.md:28` and `deployed.md:94` — *"the job carries `needs: [test, docker]`"*.
* `docs/architecture.html:1391` (`deploy — needs: [test, docker]` in figure 6), `:1397` (the `ux` sub-label
  *"needs: absent, never blocks"*), `:1571` (`["Gate","deploy needs: [test, docker]"]` and the `ux` key),
  `:1807` (*"Never skips: needs: [test, docker] still holds on a dispatch"*), `:1814`
  (`D["f6-deploy"]` prose).

**`paths-ignore` no longer lists `*.md`**

* `docs/architecture.html:1343` (figure label *"paths-ignore: docs/**,"* … continues with `*.md`) and `:1803`
  (`["paths-ignore","evaluation/results/**, evaluation/REPORT.md, docs/**, *.md at the repo root"]`), `:1828`
  (`on: push` node prose).
* `deployed.md:80` — the sentence about what `paths-ignore` keeps off the build budget (now one item shorter).

**The gitleaks claim is now literally true — but three sites describe the mechanism**

* `README.md:166`, `ai-tooling.md:282`, `design-and-evaluation.md:761` and `:837`,
  `docs/requirements-traceability.md:67`, `docs/demo-script.md:76`, `docs/architecture.html:1369` and `:1809`.
  They may keep the phrase "full history"; what is worth adding is *how* — the pinned 8.30.1 binary run
  explicitly in the `lint` job on every run, alongside the action's per-push range scan.

**MCP §5 claims (gap 17)**

* `mcp/README.md:65` — *"**Exactly one `mcp_discovery` span per turn.**"* → per turn **pass**; a turn resumed
  after a confirmation carries a second (demo task 2: seq 1 and seq 27).
* `design-and-evaluation.md:343` — the same bolded claim.
* `docs/architecture.html` — the discovery nodes carrying the same sentence.
* `mcp/README.md:136` — *"Transport failure | the client retries once…"* → the client **re-discovers** once at
  the discovery step; a `tools/call` that fails degrades the turn immediately (`design-and-evaluation.md:411`
  already words it correctly).
* `mcp_session_id` (mcp/README.md:67, design-and-evaluation.md:344, the architecture nodes) can stay as
  recorded span content — it is now populated on the HTTP transport. Worth one clause: it is `null` on stdio,
  which has no session id.

**Tool-schema figures (gap 8)**

* `design-and-evaluation.md:603` — the pasted `search_policy_documents` schema still shows
  `"min_dense_score": {"type": "number", …, "default": 0.26}`; repaste as the `anyOf` number/null with
  `"default": null` and the new description.
* `docs/architecture.html:1535` — the same 0.26.
* `tests/fixtures/traces/pto_request_confirmed_write.json` and `tests/fixtures/traces/remote_work_eligibility.json`
  record `min_dense_score: 0.26` in their retrieval spans; they are hand-built replay fixtures and nothing
  asserts the value, but they read as the effective threshold and are now misleading. (Left alone deliberately:
  they are trace fixtures, not documents, and regenerating them is out of this task's scope.)

**Traceability (gap 18)**

* `docs/requirements-traceability.md` R4.2 names two workflows; `expense_claim` should join the row, with
  `tests/unit/test_expense_claim_is_scored.py` as its evidence (that file now covers the predicate as well as
  the turn).

**Suite size — already done here**

`README.md:62`, `ai-tooling.md:279`, `design-and-evaluation.md:838`, `docs/requirements-traceability.md:149`
and `docs/demo-script.md:76` now say **3,435** / **3,136 of 3,435**. If anything adds or removes a collected
test after `6e71e0f`, all five move together.

---

## Assumptions

1. **amb-001's recorded rationale is unavailable**, so the new fixture reconstructs its shape rather than
   quoting it (§1 above). The reconstruction reproduces the published answer under the old code.
2. **Capture, not deletion, for `mcp_session_id`** (§4). The brief suggested `get_session_id` from
   `streamablehttp_client`; that callback does not exist in the installed mcp 2.2.0
   (`streamable_http_client` yields two streams), so the response-header hook is the equivalent, and it means
   `_http_client()` now always builds the client — behaviourally identical, since `LOOPBACK_TIMEOUT` is
   `create_mcp_http_client`'s own pair of timeouts.
3. **`0.45` is written as a literal** in the `min_dense_score` description rather than interpolated from
   `settings`, so the committed schema cannot vary with a local `MIN_SUPPORT_SCORE`.
4. **The docs rationale sentences were left alone** per the brief; they are listed above for the docs task.
   Only the five suite-size figures were edited in documents.
5. **`make lock` was not executed** (no `uv` on this machine; running it would rewrite committed pins).
   `make -n lock` and the manifests' own headers are the verification.

## Concerns

1. **The dataset-size guard is red on `main`** at my commit (Task 11's 28 → 30). Someone must sweep the four
   `NUMBER_DOCS`, not just README.
2. **The suite-size figure is now a joint number.** Task 11's tests are parametrised over `evaluation/dataset.yaml`,
   so any further dataset item moves the collected count and re-breaks the five documents I just updated. If
   another agent adds or removes a dataset item after `6e71e0f`, they own the next bump.
3. **`deploy` now waits on `ux` (~11 min).** Deploys get slower, and a flaky browser test can block production.
   That is the trade the gap asks for, but it is a real change to the shipping path; the chromium cache keeps
   the usual cost down.
4. **The whole-history gitleaks step downloads a binary from GitHub Releases on every lint run.** The URL and
   the tarball layout were verified against the live release (`gitleaks_8.30.1_linux_x64.tar.gz`, HTTP 200),
   and the version is pinned, but it is one more network dependency in CI. If that matters, the alternative is
   `ghcr.io/gitleaks/gitleaks:v8.30.1` under `docker run`.
5. **The `*.md` filter is gone, so every root-level document commit now runs the full pipeline and deploys.**
   That is gap 9's point (the docs contract tests gate the commits most likely to break them), but it spends
   Render build minutes on prose commits. `docs/**` still short-circuits.
6. **The trace fixtures still record `min_dense_score: 0.26`** (§ document list). Nothing asserts them, but a
   reader comparing a fixture span to the new schema will see a number the server no longer defaults to.
7. **Two ephemeral failures during the first broad run** (36 failed / 26 errors, all corpus- and index-related)
   were caused by Task 11 rebuilding `data/index/` in the shared working tree mid-run; a re-run with a settled
   tree was clean apart from the dataset-size guard. Worth knowing if a later run looks alarming.
8. **The pyproject → Makefile cross-reference now resolves, but nothing guards it.** A test asserting the
   `lock` recipe matches each manifest's `uv pip compile` header would prevent the next instance of this class;
   not added, to keep the collected-count bump small.
