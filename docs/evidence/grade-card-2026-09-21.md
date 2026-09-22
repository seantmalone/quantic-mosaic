**What this is:** the independent grade card behind the 2026-09-21 grade-and-fix wave — a verbatim copy of the graded report, whose working copy lives in the git-ignored `.superpowers/` directory. The body below is unaltered; its ranked gap list is the machine twin [`grade-card-2026-09-21-gaps.json`](grade-card-2026-09-21-gaps.json).
**Graded:** 2026-09-21, read-only, at HEAD `98c893f`, by an independent 82-agent grading workflow — assessors over grouped rubric sections, one adversarial skeptic per flagged finding, one synthesising grader.

---

# Mosaic HR Copilot — final grade against the Quantic rubric

Graded 2026-09-21 against `docs/project-requirements.md` (Project Rubric band table), on the repository and deployment as they stand at `98c893f`. A solid demo video meeting every format requirement is assumed.

## Verdict

**Band 4 — high confidence, at the top of the band.**

The built system is genuinely band-5 work. Nine MCP tools over three real transports with the agent reaching them only through `ClientSession.call_tool`; hybrid retrieval with six guardrails and a closed citation contract; a separated orchestrator with an enforced RAG-only gate, three predicate-verified workflows and four tested failure paths; a single free Render service that is live and warm right now (`/health` 200, `git_sha 15bfed2`, `mcp.connected true`, 9 tools, 14 docs / 204 chunks, `degradations []`); and a five-job CI workflow that is itself under contract test.

What caps it is not capability but the final publish pass. `evaluation/results/latest.json` and `evaluation/REPORT.md` publish `r_1789555212_baseline`; `README.md`, `design-and-evaluation.md`, `deployed.md`, `docs/requirements-traceability.md`, `docs/pre-submission-checklist.md` and `docs/demo-script.md` all publish `r_1789166880_baseline`, with eight headline figures different. The block carrying the stale numbers ends with *"Figures written by `scripts/paste_eval_numbers.py` from `evaluation/results/latest.json`. Do not hand-edit."* — and the project's own checker disagrees:

```
$ python3 scripts/paste_eval_numbers.py --check
STALE — design-and-evaluation.md's results table does not match evaluation/results/latest.json
exit=1
```

The rubric's 5 requires **all** requirements at an outstanding level. A grader who opens `README.md` and then `evaluation/REPORT.md` finds contradictory headline evaluation results, four of them more flattering in the graded documents. `evaluation/REPORT.md` additionally contradicts itself: its ablation baseline column is a different run than its own headline, under the sentence *"Every figure below comes from that one run; nothing here is hand-edited."* That is a materially inconsistent evaluation claim, and it caps the grade at 4 on its own. Secondary caps: clarification accuracy 0.333 published nowhere but `REPORT.md`, a "Known limitations" list describing a superseded run's failures, and a documented local-run path that a fresh clone cannot execute.

Gaps 1-4 are roughly four hours of work and remove the cap. Nothing here requires rebuilding anything.

## Section scores

| Section | Band | Note |
|---|---|---|
| 1. Environment and Reproducibility | 4 | venv, `.python-version` 3.12.14, exact pins + three lockfiles, single `SecretStr` env reader with a bijection test, `.env` never in history. Deductions: a fresh clone cannot answer a question (`make ingest` undocumented, index untracked); `## Evaluation` publishes a run `latest.json` does not name. |
| 2. RAG ingestion and indexing | 5 | 14 files / 64.2 pages, four real parser paths, heading-aware chunking proved byte-identical, free local ONNX embeddings with a drift-guarded query convention, sqlite-vec + FTS5 with a passing self-test. Band enforced by tests. |
| 3. Retrieval, prompting, citations, guardrails | 5 | Dense + BM25 + RRF with pre-fusion filtering, threshold on `dense_score` with a pinned test, full chunk text plus metadata in the envelope, typed citations with snippets and live deep links, six guardrails with calibrated thresholds, five multi-doc items. |
| 4. Agentic system design | 4 | Enforced RAG-only gate, predicate-verified workflows, one projected span record, four fault-injection tests, a wire-level confirmation gate. Held at 4 by clarification accuracy 0.333 and a dead profile-debt repair that costs `remote-003` its workflow. |
| 5. MCP integration | 5 | Nine tools, three transports from one factory, real JSON-RPC at runtime with an architecture grep forbidding shortcuts, committed schemas byte-identical to the deployed `tools/list`, per-turn discovery span. Deductions are documentation-only. |
| 6. Web application | 5 | `/chat` returns answer, blocks, per-citation snippets and a non-CoT trace in one model rendered as JSON or htmx; `/health` far richer than required, with `/ready`. R6.5 satisfied via the self-dating UI buttons. |
| 7. Deployment | 5 | Live and warm; single free Docker service, model and index baked at build time, no paid DB, `autoDeploy: false` plus `needs: [test, docker]`, every env var tabled, measured n=3 cold-start table. |
| 8. CI/CD | 5 | Five green jobs on push and PR, real build/start/`/health` assertions, both named tests substantive, 90% branch gate, gitleaks over full history, and the workflow verified by the suite it runs. |
| 9. Evaluation | 4 | Method and coverage are 5-level. Capped by verifiability: two "published runs", `REPORT.md` self-contradicting, the one regressed metric omitted from the final table, `n=1` safety against a documented `n=28`, judge pass undocumented. |
| 10. Design documentation | 4 | All ten justifications with rejected alternatives and measured reasons, the diagram twice over, demo tasks as executable contracts, 48 contract tests. Capped by the stale run, wrong known-limitations causes, and `ai-tooling.md` ending five days early. |
| Submission files | 4 | Every required artifact present and over-delivered. One true placeholder: `README.md:11` `Demo video: pending: gate 6`. |
| Demo readiness | 4 | System is ready; the script is not — six references to a deleted span rail, a false "verbatim LLM messages" claim, four-jobs/1,800-tests, and superseded eval failure causes. |

## Gaps to full marks (ranked)

### 1. Three graded documents publish a superseded evaluation run — HIGH
**Costs marks because** it is a materially inconsistent evaluation claim in the first two files a grader opens, in a project whose stated premise is *"every number in the evaluation section comes from a committed run file; nothing is inferred."* Four of six drifted values flatter the submission, and `docs/requirements-traceability.md:219` verifies RUBRIC5.1 partly because the old run is *"pointed at by `latest.json`"* — now false.

**Evidence.** `latest.json` → `r_1789555212_baseline`; `REPORT.md:3` generated from it. Stale id at `README.md:187,192`; `design-and-evaluation.md:19,924,955,1132,1294`; `deployed.md:63`; `docs/requirements-traceability.md:211,219`; `docs/pre-submission-checklist.md:36`; `docs/demo-script.md:144,198`. Deltas: groundedness 0.984→0.975, citation accuracy 0.905→0.883, doc recall 0.961→0.921, tool selection 0.993→0.981, workflow completion 0.893→0.964, clarification 0.667→0.333, blind judge agreement 0.875→1.000, p95 38.7→35.7 s, action-safety n 28→1.

**Fix.**
```bash
python scripts/paste_eval_numbers.py        # regenerates the EVAL-NUMBERS block
python scripts/paste_eval_numbers.py --check # must now exit 0
```
Then hand-edit `README.md:187-203`, `design-and-evaluation.md:19-20` and `:955` (add a fifth history column for `r_1789555212_baseline` / `bd4ac93`, W8-W10), `deployed.md:45-63` (add the `bd4ac93` row; note `15bfed2` is live with HEAD docs-only on top), `docs/requirements-traceability.md:211,219`, `docs/pre-submission-checklist.md:36`, `docs/demo-script.md:144,198`. Add a contract test in `tests/contract/test_docs_completeness.py` asserting the run id inside the EVAL-NUMBERS markers equals `latest.json`'s `run_id`, and add `python scripts/paste_eval_numbers.py --check` to the CI `lint` job. **~90 min.**

### 2. `evaluation/REPORT.md` contradicts itself — HIGH
**Costs marks because** the one artifact whose whole purpose is provenance is self-refuting on inspection, and it is what the 7:40-8:45 segment puts on camera.

**Evidence.** Headline: 0.975 / 0.883 / 0.921 / 0.981 / 0.964. Same file, ABLATION block: 0.984 / 0.905 / 0.961 / 0.993 / 0.893. `comparison.json` `generated_at` 1789170296 (2026-09-11), `variants[0].run_id = r_1789166880_baseline`. Mechanism: `evaluation/runner.py` `write_report` — *"preserving whatever `ablation.py` last published"*; `git show --stat 15bfed2` does not touch `comparison.json`. The block names no run id, sha or date.

**Fix.** Re-drive the arms on the shipped build, then regenerate:
```bash
python -m evaluation.runner --variant dense_only_k2
python -m evaluation.runner --variant no_structured_tools
make ablation && git add evaluation/results/comparison.json evaluation/REPORT.md
```
(~18 min wall, ~$1.3.) If you will not re-drive, make `ablation.render_section` print each arm's `run_id`, `target_git_sha` and date inline and soften `REPORT.md:3` to "every headline figure". **~30 min.**

### 3. "Known limitations" describes a different system's failures — HIGH
**Costs marks because** the section calls itself "a complete list" and both understates the project (workflow completion 0.893 vs the real 0.964) and overstates a safety failure that no longer occurs.

**Evidence.** `design-and-evaluation.md:1272-1300` says `remote-004` *"cited 2 of its 4 expected_docs (doc recall 0.50) and so scored workflow completion 0.00"* and that `unsafe-001` *"answers where it should have stopped at the confirmation card."* In `r_1789555212_baseline.json`: `remote-004` groundedness 0.80 (the failing clause), doc_recall 0.75, workflow 1.0; `unsafe-001` tool_recall 0.75, `gated_attempts 1`, `escalation_matrix` confirm→confirm = 1; `workflow_completion_by_workflow = {pto_request: 1.0, remote_work_eligibility: 1.0}`. `REPORT.md:44-46` has the correct causes.

**Fix.** Rewrite limitations 1 and 3 from `deterministic.strict_pass_causes()` on the published run, and state that the confirmation-card miss was closed in W10. Consider generating the table inside markers as the results block already is. **~45 min.**

### 4. Clarification accuracy regressed to 0.333 and appears in no narrative document — HIGH
**Costs marks because** clarification/escalation accuracy is a rubric-named metric, the shipped build scores 1 of 3, and the only metric that got worse is the one dropped from the final summary table — which reads as selective reporting. `strict_pass` has no clarification clause, so 0.893 hides it.

**Evidence.** `r_1789555212_baseline.json` `clarification_accuracy = 0.3333`, `n_scored.clarification = 3`. `amb-003` served answer: *"Happy to help — could you tell me a little more about what you are after?"* with `named_missing_information = false`, yet `passed = 1` (`evaluation/deterministic.py:681-694`). `design-and-evaluation.md:937` says 0.667; `docs/optimization-log.md:193` says 1.000; the final table at `optimization-log.md:568-586` omits the row. Cause: `orchestrator.py:336-358` `unfilled_slot()` returns the **first** unfilled slot, and `CLARIFY_QUESTIONS` (`:203-215`) has no `employee_data` key, so that turn falls to `CLARIFY_FALLBACK` (`:253`) — which the code comment at `:237-239` itself calls the defect W10 set out to remove.

**Fix.** (a) Make `_clarification_text` join every unfilled slot; add an `employee_data`/balance entry to `CLARIFY_QUESTIONS`; add a test asserting `amb-002`'s question names both destination and dates. (b) Report 0.333 with `n = 3` in `README.md`, `design-and-evaluation.md` and `optimization-log.md`, explaining the gap against the clean 3/3 clarify row of the escalation matrix. Re-run and republish if you do (a). **2 h with repair; 20 min for disclosure alone.**

### 5. `docs/demo-script.md` stages both task segments on a deleted span rail — MEDIUM
**Costs marks because** three of DEMO.6's five elements are not on the chat surface at all, and the script points at a UI its own production note says was removed — so the most heavily graded moment is improvised, and no task segment budgets the dashboard switch.

**Evidence.** `docs/demo-script.md:26` (admits the deletion) vs `:57, :58, :121, :126, :130, :134, :179, :182, :186`. `src/hrmosaic/web/narration.py:9-24` — *"The rail is gone"*, *"Anything unmapped is `WORKING`, never a raw span name"*. `chat.html:90` is the single `role="status"` line; `_turn.html:7-10` records the removal of the "Agent activity" disclosure; `tests/contract/test_chat_page_renders.py:128` asserts exactly one live region. Real surface: `templates/dashboard/session_detail.html:140-176`. Leaked into graded docs at `design-and-evaluation.md:39,117`, `docs/architecture.html:1107,1507`, `docs/requirements-traceability.md:121,183`.

**Fix.** Rewrite both DEMO.6 sub-checklists twice-framed: chat page for the answer, `Sources (n)` and the confirm card; then `/dashboard/sessions/{id}#turn-N` (the `dashboard_url` every `ChatResponse` returns) for tool names, arguments and results. Re-cut the segment table to include the switch and back. Delete every remaining "rail" reference from the five files above. **~90 min.**

### 6. A fresh clone cannot answer a question — MEDIUM
**Costs marks because** it is the rubric's "must also run locally for development" and grader-reproducibility clause, and it removes `make demo1`/`make demo2` as a fallback if the deployed service is cold during recording.

**Evidence.** `.gitignore:24-25` (`data/index/*`, only `!chunks.manifest.jsonl`); `git ls-files data/` → one file. `grep -n -i ingest README.md` → line 135 only, describing the CI job. `Makefile setup:` has no ingest step. `src/hrmosaic/rag/index.py:232` raises `FileNotFoundError('no index at ...: run \`python -m hrmosaic.rag.ingest\`')` rather than building. `src/hrmosaic/web/api.py:2032-2052` has five degradation strings, none for a missing index — so `/health` says `ok` with `degradations []`. A `make ingest` target already exists; it is simply undocumented.

**Fix.** Add to `README.md ## Setup`, after `make setup`:
```bash
make ingest   # build the sqlite-vec + FTS5 index (~30 s, no API key needed)
```
Name it again in `## Local Run` before `make run`, or append it to the `setup:` target. Then add an `index_not_built` degradation in `api.py:2032-2052` so `/health` reports `degraded`, and surface the existing remediation hint instead of "Something went wrong". **15 min for the README; 45 min with the degradation and its test.**

### 7. `scripts/demo_task_2.sh` no longer reproduces its documented behaviour against the deployed service — MEDIUM
**Costs marks because** `README.md:72-74` invites the grader to run it against the live URL with no caveat, and the request is now in the past.

**Evidence.** `demo_task_2.sh:15-20` states the precondition itself; `:25` carries the fixed 15-17 September 2026 dates. `grep -n MOCK_TODAY README.md render.yaml deployed.md` → no hits; `Makefile:17` — *"Only the demo replays pin it; a real deployment leaves it unset."* Rules probe (E1042, 15-17 Sep): `submitted_on 2026-09-01` → notice met, 8 business days; today → notice unmet, `notice_business_days 0`, span text *"Monday 21 September to Tuesday 15 September: 0 business days' notice."* `corpus/rules.yml:265-271` leaves the notice row non-blocking, so the verdict stays `conditional` and the write is still proposed — the incoherence `tests/contract/test_demo_two_verdict_is_consistent.py` exists to prevent. `demo_task_1.sh` has the same shape with a fuse around 2026-10-13.

**Fix.** Cheapest: one sentence at `README.md:72-74` saying the scripts reproduce the recorded verdicts only against a server pinned to `MOCK_TODAY=2026-09-01` (`make demo1`/`make demo2`), and that the one-click Demo 1/2 buttons are the live path. Better: have both scripts read `data-prompt` from `GET /` (or a small JSON route) and keep the frozen wording behind `--recorded`. **10 min / 60 min.**

### 8. The ablation arms were measured on a different build, and the live compare tab pairs them silently — MEDIUM
`evaluation/ablation.py:96-107` guards target and `dataset_sha` — *"the two ways a comparison silently becomes a lie"* — but not `target_git_sha`. Published baseline is `bd4ac93`; both arms are `34717b5`. `dashboard.py:2972-3018` takes the newest run per variant with **no** comparability guard, so the live compare tab shows `dense_only_k2` tool_selection 0.9929 beating the baseline's 0.9806 — a pure build artifact. The demo's closing beat reads −0.143; against the shipped baseline it is −0.214.

**Fix.** Re-drive both arms (gap 2), extend `assert_comparable` to require a shared `target_git_sha`, and render `target_git_sha` per arm in `templates/dashboard/evals.html`. Update `docs/demo-script.md:63`. **~90 min.**

### 9. Judge-validation provenance is self-contradictory — MEDIUM
`evaluation/reference_labels.yaml:28-31` names `r_1789555212_baseline` (bd4ac93) and then, one sentence later, *"The packet was built from run `r_1789166880_baseline` (the final published run, deployed commit 34717b5)."* `runner.py` renders that verbatim into `REPORT.md:132`. `REPORT.md:147` is stale against `reference_labels_hard.yaml:31-33` (generated 29 s before that file was last edited). The hard file also says the subsets overlap on "five of eight" (actual 4, as `REPORT.md:112` says) and that *"the judge scored 25 of 26 answered items 1.0"* — a figure `docs/process/sdd/P18-report.md:225` already calls "an invented statistic" (it is 15 of 18).

**Fix.** Rewrite both blinding paragraphs to name one run and state which run's answers the packet carried; correct the overlap and judge-score sentences; regenerate `REPORT.md`; add a check that its protocol prose equals the labels' blinding fields; record each label's `turn_id` (or an answer-text sha) in `evaluation/schema.py`'s `ReferenceLabel`. **60 min + 45 min for the binding.**

### 10. Safety and escalation rest on n = 1 while the design doc advertises n = 28 — MEDIUM
`r_1789555212_baseline.json` `n_scored = {safety: 1, action_safety_pass_rate: 1, workflow:pto_request: 1, workflow:remote_work_eligibility: 1}`; `REPORT.md:34` shows `n = 1`; `design-and-evaluation.md:936` shows 28. `runner.py:558-561` documents the deliberate narrowing and calls the old figure *"a pass rate over 26 items that never called a write tool."* Regenerating the block (gap 1) fixes the number automatically. To strengthen rather than merely correct, add 2-3 `unsafe_action`/escalation items and a second item per workflow — the dataset is 28 of an allowed 30. **Included in gap 1; 3 h to widen and re-run.**

### 11. The deterministic profile-debt repair is dead for the case it was written for — MEDIUM
`_profile_outstanding` (`orchestrator.py:1840-1849`) requires a `PROFILE_FIRST_TOOLS` result body with a top-level `employee_id` equal to the actor. `check_pto_balance` emits it; `check_policy_compliance` cannot — `ComplianceOutput` (`check_policy_compliance.py:164-187`) declares no such field and `model_dump` drops extras. So on a `policy_qa` eligibility turn the profile is never read: exactly `remote-003` (tool_recall 0.667, workflow 0.0, `tools_called [check_policy_compliance, search_policy_documents]`), the run's single workflow non-completion. `tests/unit/test_profile_debt_is_settled.py` passes because its second fixture has the model script call the tool itself.

**Fix.** Key `_profile_outstanding` on the recorded call **arguments** rather than the result body (or add `employee_id` to `ComplianceOutput` plus the committed schema and its test). Add a test whose script calls only `check_policy_compliance` and asserts exactly one orchestrator-issued `lookup_employee_profile`. Correct `design-and-evaluation.md:1043-1045` and limitation 3, which blame the model. **~2 h.**

### 12. `ai-tooling.md` stops five days before the submitted build — MEDIUM
Headed *"Period: 2026-09-08 → 2026-09-11"* and *"Thirteen phases … P0-P12"*, while 85 of 249 commits landed 09-14/15/16 and `docs/process/sdd/` ships reports through P27 plus UX-W0-W7 and W8-W10. The omitted stretch is the project's strongest AI-tooling evidence: four independent AI UX re-audits (6/15 → 9/15) and a 16-persona demo-path logic review (5/16 → 13/16), both quantified in `docs/optimization-log.md`. The file also contradicts itself — line 3 caps the period at 09-11 while line 179 cites a count "as of 2026-09-16".

**Fix.** Update the header, add a section covering 09-14 → 09-16 (the wave process, the independent-auditor pattern, the two score trajectories, the cost), and add at least one honest failure from that stretch — the log supplies one: each re-audit kept finding residuals in the previous wave's fixes, and the UX gate never reached 15/15. Either advance the commit-census anchor or add a clause saying it is a snapshot at `5b1bd51`. **~90 min.**

### 13. The CI/CD and evaluation beats state numbers the screen contradicts — MEDIUM
`docs/demo-script.md:61` says "Four jobs" (`ci.yml` defines five: lint 24, test 47, ux 94, docker 118, deploy 145) and "over 1,800 tests" (`pytest --collect-only -q` → `3040/3339`). `:144` and `:198` quote the superseded run's failure causes. `:62` promises a cold/warm latency split the published run cannot show (`n_cold = 0`). The same "four jobs" claim sits in `docs/requirements-traceability.md:146` and `docs/architecture.html:1569` — the latter on screen in the 0:45-1:30 segment.

**Fix.** Say five jobs (naming `ux` and why it is outside `needs:`) and "~3,040 in the test job, 3,339 including the 299 browser tests". Refresh `:144` and `:198` from the published run. Move the cold/warm beat into the 6:15-7:00 segment. Fix the two other files. **~45 min.**

### 14. The script claims verbatim LLM messages are on the dashboard — MEDIUM
`docs/demo-script.md:59` puts that in the presenter's mouth during the observability segment. `record_llm_call` (`core/llm/base.py:355-375`) writes `messages_ref` (a pointer plus counts); bodies go to the `llm_messages` side table (`core/trace.py:92`). `grep -rn 'llm_messages' src/hrmosaic/web/` → no hits; no per-span route exists; `dashboard/llm.html` has no drill-down. The same false claim sits in `docs/requirements-traceability.md:85`, marked **built**.

**Fix.** Soften `:59` to "every model call with its purpose, the tools it was offered, its token counts and the text it returned", and correct `requirements-traceability.md:85` and `:236`. Or build the disclosure in `session_detail.html` reading the `llm_messages` rows. **15 min / 2 h.**

### 15-27. Lower-severity items

| # | Item | Fix | Effort |
|---|---|---|---|
| 15 | Judged metrics not reproducible from `README`'s commands (`make eval` does not judge and overwrites `REPORT.md`) | Document drive → judge → variants → ablation with env vars, or add `make eval-judged` / `make sweep` | 30 min |
| 16 | `design-and-evaluation.md:394` and `:347-349` carry MCP claims `mcp/README.md` retracts (`-32602`; `structured_content` None over stdio); `:1399-1401` and `:531-532` over-claim schema-side validation | Replace with the measured behaviour, citing `mcp/README`'s date; soften the validation sentences; note `evaluation/deterministic.py:414-440` repeats the over-claim | 30 min |
| 17 | Router plan span always records `selected_tools: []` (183/183 real-model turns) because `route.j2` is never shown the catalog; `orchestrator.py:1967` reads a dead field | Render `turn.catalog.names` into the user block, or drop the field and `design-and-evaluation.md:440`'s claim; tighten `test_chat_trace_projection.py` | 60 min |
| 18 | RAG-only gate's only reopen trigger is a G1 failure (`orchestrator.py:1099`), so a misrouted tool-task never regains people-data tools | Fixing #11 settles it; optionally add a non-G1 trigger when a compliance verdict was scored for the actor and the profile is unread | covered / 45 min |
| 19 | A refused confirmation token renders the policy-search refusal, sometimes under "You approved this — it went ahead" (`orchestrator.py:3159,3181`; `g1.py:83-98`; `api.py:1082,1863`) | Add `CONFIRMATION_REFUSAL` copy or a dedicated `_finish`; suppress the confirmed line; fix the `g1.refusal_text` docstring; one test per branch | 45 min |
| 20 | `MCP_TOOLS_DISABLED` is advertised in `.env.example:67` but read nowhere (`settings.py:126` is the only reference) | Read it as the default for `options.tools_disabled`, or delete it and point the env table at the per-request option | 20 min |
| 21 | `draft_hr_email` has no live-call evidence and no e2e/eval coverage (forbidden in every dataset item and in `test_demo_tasks.py:70`) | Run one confirmed `draft_hr_email` turn against the deployed service before recording | 10 min |
| 22 | Tip commit carries no `ci.yml` run (`paths-ignore: docs/**`); live sha `15bfed2` appears in no document; three different shas are each labelled "the final build" | Dispatch `ci.yml` on the tip (or drop `docs/**` from `paths-ignore`); add the live sha to `deployed.md`; relabel the three evidence headers | 30 min |
| 23 | `README.md:11` still reads `Demo video: pending: gate 6` (the contract test accepts it while the gate is open) | Paste the URL; tick gates 6-7 in `NEEDS-FROM-USER.md` and the checklist. Do **not** move `NEEDS-FROM-USER.md` — five tests resolve it by root path | 5 min |
| 24 | Two judged runs on the live dashboard have no committed file (18 imported vs 16 committed), breaking `NEEDS-FROM-USER.md:201`'s own check | Commit them or name the three 2026-09-16 drives and why the last is published; fix the stated check | 20 min |
| 25 | Compare tab omits `workflow_completion` / `doc_recall_mean` (`EvalMetrics` uses `extra='ignore'`), nothing reads `workflow_completion_check`, cold cells read `n=0` | Add both fields to `EvalMetrics` and `ablation_series`; surface the check; run `--cold-probes` once or move the beat to `deployed.md`'s table | 90 min |
| 26 | Turso is an uncaught hard dependency of `/chat`: a `StoreError` on flush discards the answer and returns `INTERNAL_ERROR` while `/health` shows only a soft degradation (a real 502 is on record in `docs/evidence/grade-card-2026-09-11.md:135`) | Document that an outage takes `/chat` down and that `PERSIST_BACKEND=sqlite` is the recovery; ideally buffer the turn locally on `StoreError` | 15 min / 3 h |
| 27 | Small stale figures: 57 vs 58 facts (`design-and-evaluation.md:176`); 31,007 vs 30,840 words from two parsers; "two declarative workflows" with three registered; `pyproject.toml:15` names a non-existent `lock` recipe; "one-click buttons" that only prefill; two stale admin-profile instructions | Derive the fact count from `check_facts.py`; point `corpus_stats.py` at `parse_corpus`; say "three"; add or remove `lock:`; fix the two script lines | 60 min |

## Considered and dismissed

These were raised by assessors and overturned on verification. Listed so you know they were checked and need no action.

- **Keep-alive exhausting the 750 free instance-hours.** 24 × 31 = 744 < 750, so a single always-on free service cannot exhaust the budget; `render.yaml` declares one service and `deployed.md:367-370` records the deliberate one-service choice. September's ceiling is 720. `check_render_hours.py` cannot read hours for a free instance and prints `UNAVAILABLE`.
- **No test that `requirements*.txt` matches `pyproject.toml`.** All 22 direct pins agree exactly; the rubric asks only that dependencies be listed.
- **Branch coverage stated as 87% when `coverage.xml` says 0.8788.** The repo documents and *enforces* truncation (`test_docs_completeness.py:871`); "88%" would turn a green contract test red in three documents.
- **Non-3.12 interpreter fails confusingly.** `filterwarnings = ["error"]` makes the intended message the single aborting error, printed once at the top — louder, not quieter.
- **Post-repair citation resolvability published without repair counts.** The rubric requires groundedness and citation accuracy, both reported; the prefix recovery is specified in the design spec's guardrail table and rendered per turn as "8 of 8 citation links resolved".
- **Chunk-size sweep measured on a superseded dataset.** The two appended items carry `expected_docs: []` and are filtered out by `chunk_size_sweep.py:49`; the scored population is byte-identical.
- **Both RAG ablations are null.** Four of five historical baseline-vs-`dense_only_k2` sweeps favour hybrid RRF at k=5 on DocRecall and none lose; `design-and-evaluation.md:1444-1447` quotes the discriminating numbers.
- **Act-loop narration is hidden chain-of-thought.** Extended thinking is off, `act.j2` rule 7 mandates one ≤30-word operational sentence, payloads are capped at 24 KB, and `response_text` is never projected into `/chat`'s trace.
- **G2 reads the index directly, bypassing MCP.** `core/corpusread.py` is a `core/` module; the documented boundary forbids `agent/**` → `hrmosaic.mcpserver` only, and the exemption is stated in three places including `agent/__init__.py`.
- **`mcp/README`'s hedged live-status narrative.** The four unhedged exchanges are covered by `test_access_gate.py:411-429` and `test_confirmation_gate.py`; a live probe confirms 401 on the mount without a bearer.
- **202 async fallback documented but unimplemented.** Spec §9.4 states it conditionally on Render's timeout; `deployed.md:483-486` records the measured 100 minutes and the "no change needed" decision.
- **Zero-key reproduction is only a stub replay.** The tokenized README link works for a grader with no credential and runs the live model on the deployed service.
- **Publishing the access token in a public README.** The trade-off is stated verbatim at `design-and-evaluation.md:709-712`, and the rubric asks for a *shareable* URL.
- **No mermaid rendering verification.** The fence renders fully to SVG under `securityLevel:'strict'` on mermaid 10 and 11, with all seven components present; the rubric also accepts "text-based architecture".
- **No in-document TOC in a 1,511-line design doc.** No rubric criterion; justifications are distributed through earlier sections and the "How to read this document" map exists.
- **11 vs 13 dashboard pages; 293.6 MB RSS.** Spec §11.6 defines 11 pages with two owning two routes each; the RSS figure is a dated live measurement, not a claimed constant.
- **Cold/warm split promised where `n_cold = 0`.** The script already routes the cold-start story to the 6:15 segment; the phrase at `:62` is a metric-family name.
- **No live end-to-end evidence for the deployed build.** `git diff bd4ac93..HEAD` over `src/` is empty, and the published run is 28 live deployed turns on that code including the confirmation gate.

## Strengths — show these on camera

- **CI/CD that is itself under test.** Five green jobs; a real image build, bare-Debian `sqlite-vec` probe, container run, `/health` assertion of `mcp.connected` / `tool_count == 9` / `doc_count == 14`, live page renders; a 90% branch gate byte-identical to `make coverage`; gitleaks over full history on a pinned version; and `tests/contract/test_deploy_manifests.py` asserting the job list, the gating, the trigger conditions and that no bearer token ever sits on a `curl` line.
- **Real MCP at runtime, not a wrapper.** `orchestrator._call` → `McpClient.call_tool` → `await session.call_tool(...)` on a genuine `mcp.ClientSession` over the SDK's own transport — real JSON-RPC over a loopback socket in the deployed topology — with an architecture grep making a direct-import shortcut structurally impossible, and a per-turn `mcp_discovery` span carrying `catalog_sha` and `handshake_ms`.
- **Schema fidelity end to end.** All nine `mcp/tools/*.schema.json` are byte-identical to the deployed `tools/list`, including the root `oneOf`.
- **Determinism proved, not asserted.** `ingest --verify-manifest` rebuilds the corpus and compares `chunks.manifest.jsonl` byte for byte: *"OK — byte-identical to the rebuild (204 chunks)."*
- **Workflow completion as a predicate over tool results**, not a judgement about answer text — which is what makes the metric real and what the `no_structured_tools` arm moves.
- **A confirmation gate the model cannot reach.** Enforced inside the MCP server against canonicalised wire arguments; `confirmation_token` stripped from every model-issued call; and `_refuse_write` never even proposes a write the turn's own compliance verdict forbids, recording it as a `write_blocked` span.
- **One span record, two projections.** `project()` reads spans back from the store after the flush, so `/chat`'s `trace[]` and the dashboard are provably the same rows — with the session page disclosing each tool call's full arguments and `structured_content` (chunk ids, doc ids, dense/rrf scores, retrieved text) and all six guardrail verdicts.
- **`/health` far beyond the requirement**, every block independently degradable, plus a `/ready` that 503s until the ONNX session and index are resident.
- **Cross-vendor, temperature-0, schema-constrained judging** with a null verdict that leaves the denominator, and two reference-label subsets published side by side with the blind-vs-disclosed distinction stated.
- **`corpus/facts.yml` + CI-gated `check_facts.py`** verifying 58 verbatim quotes, heading paths, blackout dates and accrual bands, so gold answers, the rules engine and the corpus cannot drift apart silently.
- **Honest null reporting built into the tooling.** `ablation.py` exits non-zero and `REPORT.md` prints a "NOT supported by this run" banner when the pre-registered delta fails.
- **Demo robustness engineered in.** `demo_prompts()` re-dates both questions against today; the image bakes the ONNX model and builds + manifest-verifies the index at build time, which is why `/ready` greens in 0.1 s.
- **Guardrail thresholds re-calibrated** after the originals were measured below the model's cosine floor, making G1 a no-op — a documented, measured self-correction.

## What the demo must show

From `docs/demo-script.md` and `docs/pre-submission-checklist.md`:

1. **7-10 minutes.** The segment table totals 9:15, with a documented cut (line 252) if it runs long.
2. **Presenter on camera throughout** (webcam PiP, lines 18-24) and **government ID held still ≥3 s** at ~0:15.
3. **Both agentic tasks end-to-end on the deployed URL.** Use the two one-click prompts in *Demo & grader controls* — they self-date. The curl scripts are date-broken against the live clock (gap 7). Note the buttons only *prefill* the composer; you still press Send.
4. **All five DEMO.6 elements per task.** Citations and the final answer/action are on the chat page (`Sources (n)`, answer blocks). Tool names, arguments and outputs are **not** — open `/dashboard/sessions/{id}` via "Open this conversation in the dashboard" and expand the span payloads. Budget the switch; the script does not (gap 5).
5. **Task 1** must visibly chain RAG and structured data: `lookup_employee_profile` → `check_policy_compliance` → `search_policy_documents`, ending in a conditional verdict citing ≥3 distinct documents.
6. **Task 2** must show the gate: the token-free `CONFIRMATION_REQUIRED` refusal, the card stating nothing has been created, then the confirmed write with its `MOCK-HR-…` reference and the "Done:" opener.
7. **Design** (0:45-1:30): `docs/architecture.html`, naming all seven required components.
8. **Deployment** (6:15-7:00): `render.yaml`, live `/health`, `deployed.md`. Tell the cold-start story **here** with the measured n=3 numbers (median 71.0 s cold-to-first-answer vs 22.5 s warm) — not in the evaluation segment, where `n_cold = 0`.
9. **CI/CD** (7:00-7:40): the Actions run page (**five** jobs), `deploy: needs: [test, docker]`, `autoDeploy: false`, `docs/evidence/ci-deploy-skipped.png`. Read the test count off the screen.
10. **Evaluation** (7:40-8:45): `/dashboard/evals` → run detail → compare tab. The dashboard fronts `r_1789555212_baseline`, so narrate **that** run (0.975 / 0.883 / 0.921 / 0.981 / 0.964, strict pass 0.893) — not the figures still printed in `README.md` (gap 1). State clarification accuracy 0.333 (n=3) yourself rather than letting a grader find it (gap 4).
11. **The video URL replaces `README.md:11`** before the repo is shared, and both links go through the Quantic dashboard — gates 6 and 7 in `NEEDS-FROM-USER.md`, DEMO.1-DEMO.7 and SUB.1 in the checklist, all currently unticked.
12. **Warm the instance first** (`/health`, `/ready`), and if you may need the local fallback, run `make ingest` before the session (gap 6).