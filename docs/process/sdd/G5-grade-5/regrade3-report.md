# Fourth grade — quantic-mosaic at `f7852bb`

## Verdict

**Band 4 (top of band), confidence medium.** No rubric requirement is unmet. I re-verified the load-bearing claims myself against the running system, not the documents: live `/health` returns `status ok`, `git_sha f7852bb`, `mcp.connected true` with 9 tools, 14 documents / 205 chunks and `degradations []`; the committed manifest rebuilds byte-identically; all five CI jobs are green on the graded tip behind `needs: [test, docker, ux]` and `autoDeploy: false`; the published run's metrics reconcile item by item with `evaluation/results/r_1790130220_baseline.json`.

What holds it to 4 is the same class that capped the three previous rounds, now smaller but not gone: **sixteen confirmed sentences a grader can falsify with one command**, four of them material. The primary graded document carries a Known Limitation (`design-and-evaluation.md:1954-1963`) describing a tool-schema gap that commit `6a4821a` closed *inside the published build*, and a chunking description that the committed manifest contradicts 29 times out of 29. The one document that is read aloud tells the presenter two evaluation figures the published run refutes. The rubric's band-5 language asks for all requirements at an outstanding level, including excellent documentation and excellent demo presentation; a limitations list with a phantom entry and a narration script with round-2 numbers is very good, not excellent.

The distance to a 5 is about ninety minutes of text edits, itemised below. Nothing requires a code change, a re-ingest or a re-drive.

## Section scores

| Section | Band | Note |
|---|---|---|
| 1. Environment & Reproducibility | 5 | Fresh-clone path followed as written; byte-identical manifest rebuild; 69 exact pins across three compiled manifests; `SecretStr` + contract-tested `.env.example` bijection + pinned whole-history gitleaks (302 commits, no leaks) |
| 2. Corpus Ingestion & Indexing | 4 | Four parser paths, deterministic heading-aware chunking, cosine vec0 + FTS5 in one file, full citation metadata deep-linking to a live 200 — capped by the overlap description being false in `chunk.py`, the design doc twice, and `.env.example` |
| 3. RAG Retrieval, Prompting & Guardrails | 5 | Pre-fusion filtering proved empirically, RRF + BM25-arrival fill so the threshold is total, whole chunks in trust-labelled envelopes, six rails each with a pure rule, one span and passing tests |
| 4. Agent Orchestration | 5 | RAG-only gate enforced at the call boundary, three workflows whose predicates read tool results, store-backed trace with a no-hidden-CoT contract test, wire-level confirmation gate that makes an unconfirmed write unrepresentable |
| 5. MCP Servers & Tools | 5 | Nine tools, three transports, committed schemas byte-identical to the deployed catalog, `ClientSession.call_tool` over loopback Streamable HTTP with an architecture test forbidding the shortcut, session id now captured live |
| 6. Web Application | 5 | One `/chat` with answer, typed blocks, citations + snippets + source URLs and a span trace; rich `/health` incl. genuine MCP connectivity; `/ready`; demo reproducibility engineered with fail-closed scripts |
| 7. Deployment | 5 | One free Render Docker service fully described by `render.yaml`, index and model baked at build time, no paid database, cold start measured at n=3 before mitigation, cost row re-derivable to the cent |
| 8. CI/CD | 5 | Five jobs green on the tip, 3,170 tests + 90% gate (94% actual), 299 browser tests, container booted and asserted, deploy gated on all three and contract-tested |
| 9. Evaluation | 5 | 30 items across all five kinds with executable golds, every metric with its n, five-class matrix, two comparisons, pre-registered bar reported as MISSED, REPORT regenerates byte-identically |
| 10. Documentation & Design Justification | 4 | Ten justifications in order, contract-tested seven-component diagram plus a standalone page, both demo tasks test-enforced — capped by four false sentences in `design-and-evaluation.md` and a trail index its own printed command refutes |
| Submission files | 5 | All seven artifacts present and independently verifiable; README's suite, coverage, commit and provenance figures all reproduce |
| Demo readiness | 4 | Segment table sums to 9:15, 48 UI labels verbatim, `make demo1`/`demo2` green — capped by four round-2 figures in the script that is read aloud |

## Defects (ranked by threat to a 5)

### 1 — Chunk overlap described as landing on sentence boundaries, in four live places (medium)

`src/hrmosaic/rag/chunk.py:6-7` says windows "overlap by `CHUNK_OVERLAP_CHARS`, cut on sentence boundaries so a chunk never begins mid-sentence". Only the window *end* is snapped; `chunk.py:155` is `start = max(end - overlap_chars, start + 1)`, a raw offset. Over the committed manifest there are 29 continuation windows and all 29 open inside the previous sentence, 28 of them mid-word. `design-and-evaluation.md:238` and `:2145` repeat it; `.env.example:56` repeats it as the `CHUNK_OVERLAP_CHARS` comment. Because `snippet_of()` takes the first 320 characters, 28 stored snippets — the exact string a citation and the dashboard Retrieval table show a reader — open mid-word, and two committed demo captures already carry one. Worse for the trail: `docs/process/sdd/G5-grade-5/progress.md:148` rules the gap "fixed by describing what the code does" and no wording changed.

```
python3 -c "
import json,collections
rows=[json.loads(l) for l in open('data/index/chunks.manifest.jsonl')]
g=collections.defaultdict(list)
for r in rows: g[(r['doc_id'],r['heading_path'])].append(r)
cont=[c for v in g.values() for c in v[1:]]
print(len(rows),len(cont),sum(1 for c in cont if c['text'][:1].islower()))"   # 205 29 28
```

**Fix (20 min):** reword the four locations to say the window *end* is cut on a sentence boundary while the continuation start is a raw offset back by `CHUNK_OVERLAP_CHARS`; state the 29-window figure; add one assertion in `tests/unit/test_chunking.py` pinning the actual opening behaviour; correct `progress.md:148` to "left". Do **not** re-snap the chunker — that moves every `chunk_id`, the manifest, fixtures and pinned citations.

### 2 — Demo script attributes tool recall 0.75 to `remote-004` (medium)

`docs/demo-script.md:240-242`: "not calling it is exactly the tool recall 0.75 that fails the dataset twin `remote-004` on the published run"; `:383` repeats it and adds "say that out loud rather than around it". The published run scores `remote-004` at `tool_recall 1.0` and it *did* call `get_policy_section`; it fails on workflow completion alone. The same file already says so at `:164` and `:205-207`, and `evaluation/REPORT.md`'s clause table names only `workflow completion 0.00 < 1.00`.

```
python3 -c "
import json;d=json.load(open('evaluation/results/r_1790130220_baseline.json'))
i=[x for x in d['items'] if x['id'].endswith('remote-004')][0]
print({k:i['scores'][k] for k in ('tool_recall','tool_selection','workflow','doc_recall')})
print(set(x['scores']['tool_recall'] for x in d['items']))"   # 1.0 … {1.0}
```

**Fix (10 min):** `:240-242` → `get_policy_section` is optional because a search hit already carries the whole chunk; `:383` → "failing its workflow-completion clause, with document recall 0.50". Keep "read the names on screen".

### 3 — A tool-schema "loose end" published twice, once as Known Limitation 14 (medium)

`design-and-evaluation.md:477-481` and `:1954-1963` both state that `mcp/tools/check_policy_compliance.schema.json` "still names `request_type` and its three values without naming `device_age_months` … so it waits for the next build and re-drive rather than being slipped in under a published run". The schema names `device_age_months` twice and `days_since_final_day` twice; the change landed in `6a4821a`, which is an ancestor of the published build `34d50fb`, and the deployed catalog serves it now. `git log --oneline 34d50fb..HEAD -- mcp/ src/ corpus/` is empty, so the provenance excuse contradicts itself. A third copy sits at `docs/optimization-log.md:1068`. Commit `240c388`, titled "the falsifiable sentences are corrected", left both in place.

**Fix (10 min):** delete both paragraphs, replace with one sentence recording that the deciding fields are named as of `6a4821a` and therefore in `34d50fb`, and retire limitation 14 so the list carries no closed item.

### 4 — Demo script narrates p50 15.5 s (medium)

`docs/demo-script.md:134`: "p50 was 22.6 s at its worst and is **15.5 s** now." The published run records `latency_p50_ms 13833.0`; `evaluation/REPORT.md`, `README.md:321` and `docs/optimization-log.md:1000` all say 13.8 s, and the log lists 15.5 s as the superseded column. `:85` already pins the same segment to `r_1790130220_baseline`, so the page on screen renders 13,833 ms.

**Fix (10 min):** 13.8 s, and add `docs/demo-script.md` to `NUMBER_DOCS` in `tests/contract/test_docs_completeness.py` with an assertion against `latest.json`'s run.

### 5 — `render.yaml:7` states the gate as `needs: [test, docker]` (low)

The service manifest — the file a grader reads literally for the R8.4 argument — understates the real gate. `.github/workflows/ci.yml:188` is `needs: [test, docker, ux]`, and `ci.yml:207` twelve lines below already prints the correct form. The same stale text survives in `scripts/provision_render.py:414` (a runtime error string) and `tests/unit/test_provision_render.py:222`. **Fix (5 min):** update all three.

### 6 — G1's redirect described as read from the real document list (low)

`design-and-evaluation.md:805` — the guardrail-table row for requirement 3's refuse/redirect bullet — says the redirect names what the corpus covers "read from the real document list". `g1.refusal()` reads nothing: it builds `next_steps` from the hardcoded `EXAMPLE_TOPICS` tuple, its own docstring says "Since UX W6 it reads nothing at all", and `tests/contract/test_policy_library.py` asserts "topics, never document titles". `g1.py:84` still credits a `coverage()` function; `grep -rn 'def coverage' src/` is empty. **Fix (5 min):** reword `:805` to "naming five fixed corpus topics and linking `/policy`, with no `tools/call` and no index read"; drop the `coverage()` clause.

### 7 — Task-2 tool order reversed in the checklist (low)

`docs/demo-script.md:336-338` ends the chain "…`create_mock_hr_ticket` again, this time `ok`, and finally `lookup_employee_profile`". The pinned capture has `lookup_employee_profile` at seq 23 and the confirmed write at seq 28 — the last tool call of the turn. Spans render `ORDER BY seq` (`dashboard.py:1859`), and the next line asserts "the write comes **last**". **Fix (5 min):** swap the clause.

### 8 — Process-trail README count false, and it prints the command that proves it (low)

`docs/process/sdd/G5-grade-5/README.md:45` says "**Coverage: 12 briefs and 26 reports** at this commit" and invites the reader to count; `ls docs/process/sdd/G5-grade-5/task-*-report.md | wc -l` returns 30. `:54` adds "Round 3's task files are not all here yet" — but HEAD *is* the commit that brought tasks 14, 15, 16 and 5e. This file's count also drifted in the previous round. **Fix (10 min):** set 30, extend the inventory, rewrite the paragraph in past tense, and mirror the commit-census recount at `tests/contract/test_docs_completeness.py:881` with a glob recount.

### 9 — "Three different clauses, one each" (low)

`docs/demo-script.md:155` and `docs/optimization-log.md:1006`. `REPORT.md`'s table names workflow completion twice and gives `unsafe-001` two clauses — four clause failures over three items — and both documents say so two sentences later. **Fix (5 min):** "groundedness once, workflow completion twice, and behaviour class once on top of it."

### 10 — `ai-tooling.md:370` enumerates two grade rounds where three exist (low)

"both rounds, `G5(…)` and `G5b(…)`" while `:155` narrates round three and the trail README forwards readers here for the `G5c(…)` narrowing; all seven G5c commits carry the same trailer. **Fix (2 min):** "all three rounds, `G5(…)`, `G5b(…)` and `G5c(…)`".

### 11 — README calls the demo panel "collapsed by default" (low)

`README.md:146` versus `_demo_controls.html:18` ("**Always expanded** … No `<summary>`, no collapsed state"), `chat.html:552-553`, and `tests/contract/test_demo_controls_are_quarantined.py:89`, which forbids a collapsed state. The served page contains zero `<summary>`. **Fix (2 min):** describe it as one dashed, muted, always-expanded section below the fold.

### 12 — Folded-agreement disclosure names the wrong run for the label file (low)

`design-and-evaluation.md:1400-1403` says, present tense, that all eight of the label file's `turn_id`s belong to `r_1790074972_baseline`; they match `r_1790130220_baseline` 8/8 and that run 0/8, and `:1571` of the same document says so. **Fix (5 min):** past tense, pin the round.

### 13 — Ablation banner says the arm "did not move Workflow completion" (low)

`evaluation/REPORT.md`'s NOT-supported banner, generated from `evaluation/ablation.py:56-62`, then prints baseline 0.933, arm 0.733, delta −0.200. The arm moved it; it did not clear the 0.25 bar — which is what `design-and-evaluation.md:1694` and `ablation.py:341` already say. **Fix (5 min):** "did not move Workflow completion past §13.9's bar", then re-render.

### 14 — Hardcoded judge-call range excludes a committed judged run (low)

`evaluation/runner.py:1250` states "a pass runs 249–296 calls" beside a derived per-run count. `r_1789032950_baseline` is a complete judged run with `judge_calls 232`, and both range endpoints come from that same dataset generation, so a dataset-scoped reading does not rescue it; `rewrite_report` pointed at that run would emit a self-contradictory sentence. Unscoped copies at `deployed.md:493`, `:635`, `design-and-evaluation.md:680`, `docs/requirements-traceability.md:55`, `:139`. **Fix (15 min):** derive min/max from the committed judged runs at render time.

### 15 — Stale chunk count in a live prompt comment (low)

`src/hrmosaic/agent/prompts/synthesize.j2:11` says "199 of the 204 committed chunks are longer than that (median 995)"; the true figures are 200 of 205, median 983. Inside a Jinja comment, so never rendered; the same sentence is a docstring at `tests/contract/test_prompt_golden.py:218`. **Fix (5 min):** update at the next app-tree rebuild.

### 16 — "`make setup` runs exactly those steps" (low)

`README.md:37` after a four-line block; `Makefile:34-37` adds `pip install --upgrade pip` and omits the optional `cp .env.example .env`. **Fix (2 min):** soften the sentence.

## Polish (unranked)

- **Budget stop drops the requested write silently.** `_settle_action_debt` returns early on a `BUDGET_STOP` (`orchestrator.py:1856`) and `_complete` suppresses the budget lede, so an action turn at the cap serves a complete-looking policy answer with no card and no "nothing was created" receipt. Safe, disclosed as limitation 3 — but it is the shape of demo task 2.
- **Cold-start banner scope.** `README.md:205` implies the banner covers the spin-up wait; the banner lives in `chat.html` and can only appear after a page has been served.
- **`ai-tooling.md:3`** period ends 2026-09-22 while its own round-3 section and the published run run to 2026-09-23.
- **`deployed.md:89-97`** — the central provenance paragraph's em-dash aside swallowed two sentences; every fact in it is correct.
- **`docs/demo-script.md` is outside `NUMBER_DOCS`** (`tests/contract/test_docs_completeness.py:971`) even though `HEADCOUNT_DOCS` already reads it — which is how four narration figures went stale.
- **Demo-1 argument shape** documented as `duration_days: 42` in the design doc and as `end_date` ("the two dates, not a duration") in the script; both are real paths, neither says so.
- **The three pinned live transcripts** are on app build `8a89310`, two builds behind shipped — disclosed three times, and superseded by the 30-turn deployed run on `34d50fb`.
- **Live RSS ~322 MB** against dated 293.6 readings and a "~300-320 MB" band; the script says "about 300 MB" over the payload it puts on screen.

## Considered and dismissed

Each of these was raised by an assessor and refuted on verification; none counts against the band.

- **No `--generate-hashes` on the pinned manifests.** The rubric asks only that dependencies be *listed*; `grep -i hash` over `docs/project-requirements.md` returns nothing, and no document claims hash-verified installs. Optional supply-chain hardening, and the fix has real cost (hash-checking mode forbids unhashed requirements in the same invocation).
- **First `make test` in a fresh clone needs network for the ONNX model; a results-only push runs no CI.** Neither is a rubric bullet. The fetch is already stated in README Setup ("downloads into `FASTEMBED_CACHE_PATH` on first use"), a genuinely offline grader fails at `pip install` first, and `EMBED_PROVIDER=fake` is documented. `pull_request:` is unfiltered, so every path is gated on a PR; `docs/pre-submission-checklist.md:84-89` already forces a green run on the submission tip.
- **No live capture of the confirm→write path on the shipped build.** `tests/e2e/test_demo_tasks.py::test_demo_task_2_…` drives the full card→confirm→write with precedence edges and passes at HEAD, and `unsafe-002` in the published *deployed* run reached `awaiting_confirmation` with `gated_attempts 1`. The transcripts' build is disclosed in three places.
- **`/ready` warm-up bypasses the tool filter.** One read-only `search_policy_documents` call per boot, outside any turn, under a `maintenance` session label, disclosed in place at `orchestrator.py:2429-2433`; no ablation arm withholds that tool, and the knob is not a rubric requirement.
- **The bare-balance docstring overstates the code.** Behaviour is a clarification either way — the graceful branch the rubric asks for — and the overstatement is disclosed verbatim twice in the design doc with its impact bound and fix stated.
- **Evidence-index wording about "the separate stdio server of the ablation arm".** The same sentence supplies the contrast ("genuinely absent from discovery rather than filtered downstream"), and every authoritative statement of the mechanism elsewhere is correct.
- **Transcripts / RSS / "204 chunks" / cold-start-probe build field being stale.** All sit inside dated history records with per-field reconciliation in `docs/evidence/README.md`; the rubric's memory and probe asks are met, and `design-and-evaluation.md` states RSS as a band for exactly this reason.
- **`deployed.md`'s env table omits three variables.** The sentence introducing the table declares its scope and names the three additions; all three are additionally in `.env.example` under a bijection contract test, `render.yaml`, the README and two dedicated sections of `deployed.md`.
- **Turso quota arithmetic not re-derived.** Disclosed with date, mechanism, bound and two named remedies; live `/health` shows the store reachable and unthrottled at 24× the dated size, which is the property the rubric scores.
- **Agreement subsets are model-labelled / the discriminating item is "unadjudicated".** `design-and-evaluation.md:1613-1618` adjudicates it substantively and checkably against `corpus/expenses-and-reimbursement.md:16`, and the rubric asks for no inter-rater validation at all.
- **`architecture.html` has no numeric contract test; `deployed.md` keeps "204" in a dated reading; `ai-tooling.md` gives the round-3 verdict without a path.** All verified correct-as-of-HEAD or sourced elsewhere (`CHANGELOG.md:939`, `G5-grade-5/README.md:23`); prospective maintenance risk, not present shortfall.
- **Four eval runs in the live store are not in the repo.** Designed: `smoke_run()` writes to a temp dir by contract so a demo click cannot add a file; `variant` is a closed three-value Literal, the residue rows are older than the published trio, and the Compare tab's pairing rule is disclosed in the script.

## What the demo must show

1. **A warm instance.** Open `/health` and wait for 200 before recording — cold to first answer is a 71.0 s median (67.5–77.6 s). The in-page banner cannot cover the spin-up.
2. **Task 1 from the deployed UI**, using the server-dated Berlin prompt button (click prefills; the presenter presses Send), ending in citations across multiple documents with each chip clicked through to `/policy/{doc_id}#{chunk_id}`.
3. **Task 2 through the gate**: the card with "nothing has been created yet", then confirm, then the `MOCK-HR-…` id in the lede and in the tool result. Rehearse this — on the published run `unsafe-001` burned its step budget and served an answer with no card at all.
4. **Tool names, arguments, results and retrieval rows** from `/dashboard/sessions/{id}#turn-N`, and the discovery span showing 9 tools over HTTP. Set the access cookie via `?access=<README token>` first; a tokenless request is 401.
5. **The evaluation tiles and the Compare tab** at `/dashboard/evals/r_1790130220_baseline`, including the pre-registered check printed as *not supported* (delta −0.200 against a 0.25 bar).
6. **CI/CD**: five jobs, `deploy: needs [test, docker, ux]`, and the live `/health` `git_sha` equal to `git rev-parse HEAD`.
7. **Do not say** the four stale figures in `docs/demo-script.md` (`:134` p50, `:241`/`:383` remote-004, `:338` task-2 order, `:155` "three clauses"). Expect at least one mid-word snippet on screen.
8. Government ID legible ≥3 s at ~0:15, webcam for the whole take, 9:15 against a 7:00–10:00 window.

## What changed since the third grade

**Closed, and I confirmed each first-hand.** The round-3 headline cap is genuinely fixed: the disabled-tool guard now sits at `Orchestrator._call`, the only other `client.call_tool` site is the disclosed read-only `/ready` probe, and the republished `no_structured_tools` arm calls a withheld tool in **0 of 30** items where the previous arm leaked in 8. The rules engine's `not_stated` semantics now match the design doc sentence for sentence, with six characterisation tests. Corpus coherence was repaired at the data layer (`equipment-and-asset.md` scoping the USD 500 threshold and routing an early refresh to the direct manager, with two verbatim `facts.yml` keys and matching `rules.yml` guards). The ux job is now part of the deploy gate and that gate is contract-tested. The whole-history gitleaks scan, the empty published-run provenance pathspec with its own contract test, the `Mcp-Session-Id` capture (non-null on the deployed service), the re-derived `$18.54` cost row, and a full three-round process trail all landed. The run was re-driven on the shipped build `34d50fb` and the deployment now serves `f7852bb`.

**Did not close, and that is the whole of the remaining gap.** Three items are round-2 or round-3 residue that the fix wave missed rather than declined:

- The **chunk-overlap wording** is recorded in `progress.md:148` as "fixed by describing what the code does" — it was not; the gap appears in neither the round-3 docs rank list nor the explicitly-left polish tail, so it fell between them.
- The **`check_policy_compliance` loose end** was closed in code by `6a4821a` and then re-published as open by `240c388`, a commit whose own message says the falsifiable sentences were corrected.
- The **demo script** was migrated to the round-3 run everywhere except four figures, and the guard that would have caught them (`NUMBER_DOCS`) still omits the file even though a sibling guard in the same module already reads it.
- The **process-trail count** has now drifted in two consecutive rounds, and there is still no recount test — while the pattern for one exists twenty lines away at `tests/contract/test_docs_completeness.py:881`.

The engineering in this repository is at band 5 and has been verified as such against a live deployment. Two hours spent on the sixteen sentences above, plus one assertion each behind the chunk-overlap description, the demo script's eval figures and the trail count, closes the band.