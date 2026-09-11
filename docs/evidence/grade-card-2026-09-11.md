# Grade card — Mosaic HR Copilot (quantic-mosaic)

**Repo:** `/Users/sean/Projects/quantic-mosaic` · HEAD `e13a772` · **Live:** https://mosaic-hr-copilot.onrender.com (`/health` 200, `git_sha` = HEAD, `degradations: []`)
**Rubric:** `/Users/sean/Projects/quantic-mosaic/docs/project-requirements.md`
**Graded:** 2026-09-11, independent examiner, read-only. Demo video assumed recorded and done well (per instruction); the checklist it must satisfy is in §4.

---

## 1. Overall grade

# **5 / 5**

**Grading rule applied.** The document states **no formula** — no average, no weights, no explicit minimum. It defines **one holistic 0–5 band** for the whole project, selected on two axes named in each band header: *breadth of coverage* AND *level of quality*. The only explicit rule is the pass line ("Scores 2 and above are considered passing"). Because each band lists its bullets conjunctively ("including:" + bullets), the operative reading is weakest-link-like — the highest band **all** of whose bullets hold — but the document never says so, so the band is stated as a holistic judgment with the capping bullets named.

| Reading | Value | What it yields |
|---|---|---|
| **Mean** of the ten bullet scores | **4.86** | Band **5** |
| **Minimum** of the ten bullet scores | **4.50** | Band **5** if rounded; band **4** under a strict no-rounding weakest-link read |
| **Holistic best fit (awarded)** | — | **5** |

**Which a typical course would use:** the holistic band. With a single "Score / Description" table and no per-dimension sub-scores, graders in practice pick the band that best fits breadth × quality rather than computing a floor. Coverage here is effectively total (every requirement met or assumed-by-video; exactly one is unmet, and it is an action outside the repository), and quality is outstanding on 7 of 10 bullets. Band 4's wording — "MOST of the project requirements at a very good level" — materially understates this work.

**Bullets that capped it (named, per the rule's instruction):** **RB1** (multi-document citation breadth; two grounded policy facts destroyed by the citation guardrail; out-of-corpus refusal exercised only on non-HR trivia) and **RB10** (the demo-video link is still a `pending` placeholder in the README and the dashboard submission has not been made; two documentation contradictions a moderator can check in seconds). A strict examiner who refuses to round a weakest-link floor would land on **4**; I do not, because both capping bullets are high 4s on a 5-band scale and the shortfalls are disclosed by the student rather than concealed.

**Where scores came from:** where a verifier re-checked a grade and they differed, **the verifier's agreed score is used** (the verifier saw the grader's work; the grader did not see the verifier's). RB2 had no grade/verdict pair; I graded it directly this session (evidence in its row below).

---

## 2. Per-rubric-bullet table

| # | Rubric bullet | Score | One line |
|---|---|---|---|
| **RB1** | Deployed agentic HR system: policy RAG with correct, cited, grounded responses | **4.5** | Live, healthy, groundedness 0.982 and citation resolvability 1.000 over 26 answers — but two flagship multi-doc answers drop a required source and gold facts, G2 destroyed 2 grounded policy facts, and out-of-corpus refusal is only tested on trivia. |
| **RB2** | MCP integration: discovery, correct tool calls, traces, graceful error handling | **4.8** | Nine real MCP tools over a real wire (stdio + Streamable HTTP), all eight requirement-named tools present, discovery/call/fault tests green (78 passed), `/health` reports MCP connectivity — docked only because four documents claim the deployed MCP endpoint is externally attachable and it returns HTTP 421. |
| **RB3** | At least two end-to-end agentic tasks completed in the deployed demo | **5** | Both tasks complete on the deployed instance with live traces, including a confirmation-gated mock write (`MOCK-HR-000004`, 18:06Z today); citation-breadth shortfalls belong to the RAG bullet, not to completion. |
| **RB4** | RAG ingestion, indexing, retrieval, citations, guardrails | **5** | 14 docs / 4 formats / 64.2 pp, byte-deterministic 204-chunk manifest, local free embeddings in sqlite-vec + FTS5, hybrid RRF retrieval, six wired guardrails, live citation anchors resolve — every figure re-derived from source. |
| **RB5** | Architecture and clear separation of the seven components | **4.8** | Separation is structurally enforced (passing architecture tests; `agent/**` never imports `mcpserver`), diagram labels all seven components — same 421 documentation defect, with its supporting reasoning in `mcp/README.md` also wrong. |
| **RB6** | Free-tier deployment with env vars and cold start documented | **5** | One free Render Docker service serving the whole stack, SQLite fallback proven by a local boot, env-var bijection machine-checked, cold start measured n=3 with raw probe data. |
| **RB7** | CI/CD on push/PR with build/start checks and an MCP tool test | **5** | Four-job pipeline on push/PR/dispatch, real index build + Docker build + container run + health assertions, 1,942 tests under a 90% coverage gate, live MCP discovery *and* tool-call tests, deploy gated and demonstrably skipped on red. |
| **RB8** | Evaluation: groundedness, citations, tool selection, workflow, safety, latency | **5** | All six metric families against the deployed service; every headline mean and all four latency percentiles recomputed from per-item data and matched; three-arm ablation plus a chunk sweep, with a pre-registered hypothesis honestly marked NOT SUPPORTED. |
| **RB9** | Design documentation and demo presentation | **5** | README is a working grader entry point; 1,380-line design doc covers all eight required subjects, ten justifications with rejected alternatives, all 26 questions with gold answers, both demo call sequences; timed 9:15 demo script. |
| **RB10** | Completion and academic integrity | **4.5** | Nowhere near the 0 condition — no plagiarism indicator, no committed secret across 142 commits, synthetic data verified clean, candid AI-use disclosure, `quantic-grader` confirmed read-collaborator — held back by the pending video link, the unmade submission, and checkable doc contradictions. |

**Mean 4.86 · Minimum 4.50 · Awarded band 5.**

---

## 3. Requirements not fully met (final status after verification)

Ordered by grade impact. "Partial" = the requirement is substantially satisfied with a verified shortfall; "unmet" = not done.

| ID | Requirement | Status | Evidence | Cheapest fix | Grade impact |
|---|---|---|---|---|---|
| **S.14** | Submit via the dashboard "Submit Project" button | **unmet** | `NEEDS-FROM-USER.md:31-35` gate 7 open; `docs/pre-submission-checklist.md` SUB.1 unticked | Click submit after recording (2 min) | **Blocking for credit** — the work is ungraded until done. No rubric-band effect once done. |
| **S.1** | Submit two links (presentation + repo) | **partial** | `README.md:11` reads `Demo video: pending: gate 6 (record the walkthrough)`; repo link present at `README.md:12` | Paste the video URL over the placeholder | Caps RB10; a grader reading "pending" may doubt the demo exists |
| **R5.5** | Document MCP architecture, transport, schemas, discovery/call flow | **partial** | Reproduced live: `POST /mcp-server/mcp` with valid bearer → **HTTP 421 "Invalid Host header"**, contradicting `mcp/README.md:32`, `mcp/README.md:211`, `design-and-evaluation.md:289`, `deployed.md:103-104`, `docs/architecture.html:1531`. Worse: `mcp/README.md:200-206`'s supporting reasoning is itself wrong — the SDK's `streamable_http_app()` defaults `host="127.0.0.1"` (`mcp/server/lowlevel/server.py:733,742-746`), so passing nothing at `src/hrmosaic/mcpserver/asgi.py:38` auto-enables the loopback allowlist | Either pass `TransportSecuritySettings(allowed_hosts=["mosaic-hr-copilot.onrender.com"])` at `asgi.py:38`, **or** amend the five claims to "loopback-only; use `/dashboard/mcp` or the stdio entrypoint" | Caps RB2 and RB5 at 4.8; a grader who tries Inspector hits a hard failure against an explicit invitation |
| **R3.4** | Guardrails refuse/redirect out-of-corpus, limit unsupported claims | **partial** | All three `out_of_scope` items are non-HR trivia (capital of France, reverse a linked list, Boston weather) — the adjacent-but-absent HR case where parametric leakage occurs is never probed; my own probe "file my personal US tax return" scores 0.670 and passes G1 (threshold 0.60). `blocks_dropped_by_g2 = 2` cost the user gold facts (inj-001 `partial_match` 0.0; remote-004 loses the encrypted-device/VPN requirement). Live refusals render behind the literal prefix "Recommendation — not company policy:" and amb-001 leaks internal plumbing ("I need: employee profile, PTO balance, … (optional, gated) a created ticket") | Add one out-of-scope item on an HR topic the corpus lacks (401(k) match rate, tuition reimbursement); drop the recommendation prefix from refusal/clarification bodies | Principal cap on RB1 |
| **R3.3 / R3.5** | Answers cite documents; multi-document questions | **partial (answers)** | Dataset side fully met (5 `multi_doc` items, doc recall 1.0). Served answers under-cite: `expenses-002` cites 2 distinct docs vs `min_distinct_docs: 3` (missing `manager-approval-matrix`); `onboarding-001` cites 2 vs 3 required / 4 gold and omits the MFA and 36-month-refresh gold facts (`partial_match` 0.5). Note `doc_recall` is scored over *retrieval* spans (`evaluation/deterministic.py:260-284`), so its 1.0 is not evidence of citation breadth | Nudge synthesis to cite every document its evidence set spans | Second principal cap on RB1 |
| **R4.2** | Two multi-step HR workflows | **partial (published run)** | Headline run `r_1789086979_baseline` reports `workflow_completion_by_workflow = {pto_request: 1.0, remote_work_eligibility: 0.0}`. A run where both read 1.00 **does exist** (`r_1789069158_baseline`, deployed target, same dataset sha, `blocks_dropped_by_g2: 0`) — it is simply not the one the README publishes | Publish the run where both workflows complete, or fix the 3-doc clause and re-run | Minor; disclosed at `evaluation/REPORT.md:79` |
| **(project's own bar)** | Demo-2 citation breadth | **partial** | All three live demo-2 turns cite exactly **one** document (`pto-and-holidays`) against the project's own executable bar `min_distinct_docs_cited=2` (`tests/e2e/test_demo_tasks.py:100`). The e2e test passes only because it replays a recorded stub (`:199,:219`), not the live model | Relax the documented bar honestly, or make demo-2 retrieve the approval matrix | Reduces demo polish; does not unmeet a rubric requirement |
| **(answer quality)** | pto-003 demo answer | **partial** | Self-disclosed at `CHANGELOG.md:905`: the answer "states a notice-counting condition the evidence does not contain and a deadline date no evidence item carries" — an unsupported claim inside a demo-task answer that reported groundedness did not catch | Ground or drop the condition | Small RB1 drag |
| **R1.3 / S.7** | Published numbers match their source | **partial** | `pytest --collect-only` → **1,942**; `README.md:48` says "1,917", `ai-tooling.md:174` "1,911", `design-and-evaluation.md:726` "1,917". `coverage.xml` `lines-valid=7256`; `README.md:52` says "7,135 statements" (the 95%/87% percentages do still hold) | Refresh four numbers; add a contract test asserting the count | Cosmetic but grader-visible |
| **(doc accuracy)** | Company headcount | **partial** | `README.md:3` and `design-and-evaluation.md:8` say "120-person"; `corpus/README.md:3`, `mock_data/README.md:4` and the design spec say "420-person"; the wrong figure is scripted into on-camera narration at `docs/demo-script.md:54` | Pick one number, fix five files, fix the script line | First sentence of the two most-read documents; cheap to fix, embarrassing if read aloud |
| **P.2** | AI-use disclosure auditability | **partial** | `ai-tooling.md:190` offers `.superpowers/sdd/2026-09-08-implementation-roadmap/` as the audit trail; `.gitignore:43` excludes `.superpowers/` and git tracks nothing there | Repoint to `CHANGELOG.md` + `docs/superpowers/`, or commit the briefs | Minor |
| **(doc accuracy)** | Architecture diagram self-description | **partial** | `docs/architecture.html` lines 7-10 load Google Fonts while `design-and-evaluation.md:48` calls it "no network access" | Inline the font stack or drop the claim | Trivial |
| **(doc accuracy)** | Judge/labeller independence wording | **partial** | `evaluation/reference_labels.yaml:22-24` describes the labeller as "a third model family independent of both the agent" while being a Claude Opus 5 session against a Claude Haiku 4.5 agent — same vendor. The vendor is named verbatim, so disclosed not hidden | Reword to "same vendor, different model and session" | Trivial; no rubric requires an independent labeller |
| **(provenance)** | Published run ↔ commit linkage | **partial** | `r_1789086979_baseline.json` records `git_sha: "dev"`; the `da0dca2` attribution rests on prose — though corroborated by timestamps (commit 17:27:36, run 17:44:19 the same evening) | Record the real sha in the harness | Trivial |
| **S.5** | Share repo with `quantic-grader` | **met** (doc stale) | `gh api .../collaborators/quantic-grader/permission` → `read`; invitations `[]`. But `docs/requirements-traceability.md:191` still says "planned" | Update the traceability row | None |

**Not a shortfall, recorded for completeness:** strict pass rate **0.808** misses the project's **own self-set 0.85 target** (no rubric target exists). The five failing items and the clause each failed are tabled in `evaluation/REPORT.md` — disclosure, not concealment.

---

## 4. What the demo video must show (for the "assumed met" items to hold)

Every demo requirement (O.5, O.6, EX.0, S.4–S.4.6) was treated as met. That assumption holds **only if** the recording shows all of the following.

**Setup and identity**
- [ ] Total runtime **between 7:00 and 10:00** (script plans 9:15).
- [ ] Presenter **on camera for the full recording**, with continuous voiceover — not just an intro card.
- [ ] **Government ID** held legibly still for ≥3 seconds.
- [ ] The **deployed URL** `mosaic-hr-copilot.onrender.com` visible in the address bar — not `localhost`, not a stub.

**Task 1 — remote-work eligibility (live, on the deployed app)**
- [ ] Runs end to end to a finished answer in the browser.
- [ ] Presenter names the **MCP tool names** off the span rail: `lookup_employee_profile`, `search_policy_documents`, `get_policy_section`, `check_policy_compliance`.
- [ ] Reads the **arguments actually sent** (e.g. `duration_days: 42`, `destination_country: Germany`).
- [ ] Shows the **returned results** and the **final answer**, narrated as MCP calls.
- [ ] Opens **at least one citation chip** into the corpus browser to show the cited passage.
- [ ] ⚠️ Reads the citations **actually on screen**. Live runs cite 2 documents, not the 3 the design doc promises — do not narrate the documented expectation as if observed.

**Task 2 — PTO request with mock write (live, on the deployed app)**
- [ ] Runs end to end; `check_pto_balance` returns the balance (13.5 days as of 2026-09-01).
- [ ] The **confirmation card appears before the write**, and the presenter shows **Cancel → re-ask → Confirm**.
- [ ] The confirmed `create_mock_hr_ticket` produces a **`MOCK-HR-<n>` id named in the answer**, and the row appears in the admin mock-action log.
- [ ] Tool names, arguments, outputs and citations narrated as for task 1.
- [ ] ⚠️ Live demo-2 turns cite **one** document; do not claim two.

**Walkthrough segments (S.4.6)**
- [ ] **Design** — the seven-component diagram (`docs/architecture.html` or `design-and-evaluation.md:37-79`), naming web app, agent orchestrator, MCP client, MCP server, RAG index, mock data, LLM provider.
- [ ] **Deployment** — live `/health` payload on screen (`status ok`, `mcp.connected`, `tool_count 9`, `index.chunk_count 204`), plus the free-tier spin-down and the measured cold-start numbers **with n=3**.
- [ ] **CI/CD** — the Actions run graph (lint / test / docker / deploy) and the gate: deploy skipped when tests are red.
- [ ] **Evaluation** — `/dashboard/evals` live, narrating the real figures **including** strict pass 0.808 against the 0.85 target.

**Two things the presenter must NOT say**
- [ ] Do **not** claim the deployed `/mcp-server/mcp` endpoint is externally attachable by MCP Inspector — it returns HTTP 421. Demonstrate MCP via the stdio process (`mcp/run_stdio.sh`) or `/dashboard/mcp` instead.
- [ ] Do **not** read `docs/demo-script.md:54`'s "120-person" verbatim until the headcount contradiction is resolved.

---

## 5. Strengths

1. **Every published number reconciles with its source.** Groundedness 0.982, citation accuracy 0.925, doc recall 0.974, tool F1 0.992, workflow 0.846, latency p50 16,698.5 ms / p95 32,377.75 ms — all recomputed independently from the 26 per-item score blocks and matched to the digit, as did all four ablation deltas and the cold-start medians. Unflattering figures (remote-work workflow 0.00, strict pass under target, an ablation hypothesis marked NOT SUPPORTED) are published, not buried.
2. **MCP is a real wire, not a wrapper.** Nine tools — all eight the requirements name, plus `list_policy_documents` — served by one `build_hr_server()` factory over stdio, mounted Streamable HTTP, and a configurable remote URL; the boundary is enforced by a passing architecture test proving `agent/**` never imports `hrmosaic.mcpserver`. I ran discovery, tool-call and four fault-injection suites: **78 passed**.
3. **Safety is enforced at the server, not in the prompt.** `create_mock_hr_ticket` returns `isError CONFIRMATION_REQUIRED` without a one-time token minted only at `/chat/confirm`; the live ledger shows four confirmations each with distinct `created_at`/`used_at` and four `MOCK-HR-*` writes. Action-safety is a four-clause deterministic check, not a vacuous 1.000.
4. **Determinism where it is checkable.** `ingest --verify-manifest` rebuilds the 204-chunk manifest byte-identically; `SEED = 1729` is a real constant consumed by evaluation sampling and mock-data generation; a repo-wide RNG scan found no unseeded sampling.
5. **CI/CD is exercised, not decorative.** Four jobs on push/PR/dispatch, a real index build and Docker build, the container actually run and health-asserted, 1,942 tests under a 90% coverage gate — and run history proves the gate: two runs with `test: failure` → `deploy: skipped`, with the live `git_sha` equal to the green run's head.
6. **Corpus and data hygiene are verifiable.** 14 hand-authored documents across four formats, 64.2 pages; `check_facts.py` confirms every published quote is verbatim and every heading path real; `pii_check.py` reports clean; reserved `.example` domain and `+1-555` numbers throughout.
7. **Documentation depth is unusual.** Ten design justifications each naming the rejected alternative, all 26 evaluation questions with gold answers, both demo tasks' expected MCP sequences pinned by an executable test, eight itemised known limitations, and a candid `ai-tooling.md` that accepts responsibility for correctness, security and integrity.
8. **Integrity is clean under adversarial check.** No plagiarism indicator; the only third-party code is three vendored frontend libraries with full licence texts; no secret in any of 142 commits; `quantic-grader` confirmed as a read collaborator on a public repo.

---

## 6. Risks a grader might trip over

| Risk | Detail | Mitigation to ship |
|---|---|---|
| **Cold start** | First request after 15 min idle takes a median **44.8 s** to `/health` and **71.0 s** to a first answer. A grader clicking the README link cold may think it is down. | Documented in README + `deployed.md`; the demo must narrate it. Consider setting `KEEP_ALIVE_URL` (shipped but unset). |
| **The 421 trap** | The docs *invite* the grader to attach MCP Inspector to the deployed endpoint; it fails with `Invalid Host header`. This is the single most likely "the student's claim is false" moment. | Fix the allowlist or the five claims (§3, R5.5). |
| **Findability** | `mcp/README.md` — the deepest MCP document — is linked from **neither** `README.md` nor `design-and-evaluation.md`; a grader reaches it only by browsing `mcp/`. | Add one link. |
| **Access token** | Every page except `/health` and `/ready` needs the bearer token, supplied only as the `?access=` query on `README.md:10`. A grader who copies the bare hostname gets 401. | Keep the tokenised link prominent; the demo should open it that way. |
| **Stale numbers** | 1,917/1,911 tests vs 1,942; 7,135 statements vs 7,256. A grader who runs `pytest --collect-only` sees the mismatch immediately. | Refresh (§3). |
| **Headcount contradiction** | 120 vs 420 in the first sentence of the two most-read documents, and in the demo script. | Fix five files (§3). |
| **Non-deterministic demo-1 breadth** | Across four committed runs, demo-1 cited 3 of 4 expected docs three times and 2 once. What a grader sees on one click is not fixed. | Script the presenter to read the chips on screen. |
| **Transient trace-store blip** | One `/health` probe during grading returned `trace_store_unreachable` (Turso 502); it recovered on re-probe (287 sessions / 6,330 spans). A blip mid-demo would look like a crash. | Know the failure mode; `/health` degrades to a status string, never a 5xx. |
| **Pending video placeholder** | `README.md:11` still reads "pending". A grader may conclude the demo was never recorded. | Paste the link. |
| **Rolling trace store** | End-to-end claims rest on the live trace store's contents, which roll. | Commit a captured `demo_task_*.sh` transcript under `docs/evidence/`. |

---

## 7. Bottom line

Coverage is effectively complete and quality is outstanding across seven of ten rubric dimensions, with the remaining three at a high 4. **Awarded band: 5** (mean 4.86, minimum 4.50). The one genuinely unmet item — clicking "Submit Project" — is a two-minute action outside the repository, and until it and the video link are done the work is not submitted at all. The two fixes with the best ratio of effort to grader impact are the **MCP 421 claim** and the **README video link**; the two cheapest are the **headcount** and the **stale test counts**.
