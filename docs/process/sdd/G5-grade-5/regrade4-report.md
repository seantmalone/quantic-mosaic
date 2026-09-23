# Fifth grade — quantic-mosaic at `204d48f`

## Verdict

**Band 5**, confidence **medium**.

No rubric bullet is unmet anywhere across the ten sections. Every claim checkable from outside the repository reproduced on the graded tip: `/health.app.git_sha` = `204d48fd6104e53e9b526c37ab751f8086d93e2d` = HEAD with `degradations: []`, CI run 35821830597 green across all five jobs on that sha, an external `initialize` + `tools/list` against the deployed mount returning nine tools whose schemas are byte-identical to the committed files, `evaluation/REPORT.md` re-rendering byte-identically from its run file, and the provenance pathspec printing nothing (`git diff --stat 34d50fb..HEAD -- src mcp/tools corpus data/index/chunks.manifest.jsonl Dockerfile render.yaml requirements.txt` → exit 0).

I am overriding two section assessments upward, and the reasoning should be visible so it can be disagreed with. The rubric framing for this grade is that a **single unmet requirement or a materially inconsistent evaluation claim** caps at 4, while **wording, layout, optional hardening, figures inside dated history records, and source comments the docs already flag as stale** do not. Applying that mechanically:

- **No requirement is unmet.** Every rubric row across all eight assessment groups is met; the three "partial" rows are the demo-script tile sentence (defect 3), a stale narration figure (polish), and the process-trail index, which is not a rubric artifact.
- **No evaluation claim is materially inconsistent.** All eleven headline means recompute from the committed per-item scores, `comparison.json` rebuilds byte-identically, and the two eval defects are a day-attribution in a history sentence and an "eight labels" where one *historical* run compared seven. No published figure is wrong.
- **Fourteen of the fifteen confirmed defects are prose accuracy** — counts, dates, a timestamp cell, a provider name, three self-references, two stale source comments. That is the category the framing explicitly declines to treat as a cap.

That leaves exactly one non-wording defect: the `is_unsafe` substring gate (defect 1). It does not unmeet a bullet, it fails in the safe direction, it returns a cited policy sentence from `manager-approval-matrix.md` plus a People Ops redirect — but it is the one place the project's own disclosure discipline was skipped, and it is the reason confidence is medium rather than high. Band 4's descriptors ("MCP integration works for the main tools, though traces, error handling, or architecture separation may have minor limitations"; "deployment is mostly functional, with minor cold-start or configuration issues"; "very good evaluation covering most required metrics") simply do not describe this repository, and scoring it 4 would require calling an evaluation that covers every required metric plus judge validation plus three ablations "most of them."

The 5 is earned on substance. The honest counter-case is the accuracy tail: seven false sentences survive across `design-and-evaluation.md`, `docs/architecture.html` and `mcp/README.md`, and the graded tip commit itself re-broke a count the previous fix pass had corrected. A stricter grader would use that to hold this at 4 for a fifth time. Two of the fifteen defects are worth fixing before the camera rolls; the rest are about ninety minutes of text edits.

## Section scores

| Section | Band | Note |
|---|---|---|
| 1. Environment & reproducibility | 5 | Interpreter pinned four ways, exact pins compiled into three committed manifests that `make lock` reproduces byte-for-byte, one seed with a written determinism argument, secrets from env with a pinned whole-history gitleaks scan proving no `.env` in 304 commits. |
| 2. RAG ingestion & indexing | 5 | Four real parser paths over a 14-doc / 4-format / 63.9-page corpus; determinism proved by a byte-identical manifest rebuild; one read-only SQLite file with sqlite-vec (cosine) plus FTS5; all 205 chunks' offsets slice their document exactly. |
| 3. Retrieval, prompting, citations & guardrails | 5 | Hybrid dense+BM25 with RRF, pre-fusion filtering on both arms, a stored-vector fill making the evidence gate total, one score definition defended by test. **Thinnest margin** — defect 1. |
| 4. Agent orchestration | 5 | RAG-only is a gate enforced at the call boundary and proved e2e against a separate-process MCP server; workflow predicates read recorded tool results, not answer prose; the trace is projected from the store; the confirmation gate has real invariants. **Thinnest margin** — defect 1. |
| 5. MCP servers & tools | 5 | Nine tools where five are asked for; three real transports from one factory; the agent reaches tools only through `ClientSession.call_tool`, with an architecture test making the no-direct-calls clause structurally true. |
| 6. Web application | 5 | One `/chat` returning answer, blocks, citations with snippets and deep links, and a bounded trace, in JSON and htmx; `/health` rich but simple and always 200 while the process is up; two demo tasks reproducible three ways. |
| 7. Deployment | 5 | One free Render service on HEAD with an empty degradations list; model bake and index build at image-build time; no paid database; $0 infrastructure with the model-spend overrun stated rather than hidden; cold start measured with `n` and spread. |
| 8. CI/CD | 5 | Push, PR (with real PR runs) and dispatch; five jobs green on the tip; installs from the committed manifests; a genuine boot-and-render build check; 3,170 of 3,469 tests under a 90% gate; `deploy: needs: [test, docker, ux]` plus `autoDeploy: false`, proved by live red runs. |
| 9. Evaluation | 5 | 30 items across all five required kinds plus two safety kinds; every metric published with its own `n` and re-derivable; latency p50/p95 with the warm/cold split and spin-down measured separately; three comparisons; the pre-registered claim fails and is printed as failed. |
| 10. Documentation | 5 | All three §10 bullets outstanding. **Overridden up from the section assessor's 4**: the process-trail index that held it there is not a §10 artifact, and the residue in the graded documents is wording. **Thinnest margin** alongside §4. |
| Submission files | 5 | All seven artifacts present and independently verifiable; `mock_data/` passes its own PII check clean; the nine `mcp/tools/*.schema.json` match what the deployed server advertises; repo public and shared with `quantic-grader`. |
| Demo readiness | 5 | Segment table chains and sums to 9:15; both tasks run live through one-click self-dated prompts; all five DEMO.6 elements scripted per task; every traced figure reconciles; all four pre-take checks pass; `make demo1`/`make demo2` exit 0. |

## Defects (ranked)

### 1. The `is_unsafe` substring gate hard-refuses legitimate in-corpus approval questions, and is documented nowhere — medium

`src/hrmosaic/agent/router.py:172-175` is a bare substring scan over 21 phrases; `src/hrmosaic/agent/orchestrator.py:1236` calls it unconditionally on the raw message, before `out_of_scope` and clarify.

```
.venv/bin/python -c "from hrmosaic.agent.router import is_unsafe as u; \
  print(u('What happens if I submit a request without manager approval?'), \
        u('Can I take PTO without manager approval if my manager is on leave?'), \
        u('Who can approve my own expense report?'), \
        u('What is the policy on self-approval?'))"
# True True True False
```

The last line is the intent the gate exists for and it returns False. The manager-on-leave question is answerable from `corpus/manager-approval-matrix.md:141-172` (delegation rules). `grep -rIn 'is_unsafe|UNSAFE_PHRASES|_refuse_unsafe' README.md design-and-evaluation.md docs/requirements-traceability.md docs/demo-script.md` → nothing, while the structurally identical `is_bare_balance_ask` gets `design-and-evaluation.md:582-585` plus Known limitation 14. No negative test covers the class, and `over_refusal_rate 0.000 (n=18)` does not, because no dataset item contains a listed phrase.

**Fix.** The cheap one is disclosure, and it is the highest-value fifteen minutes in this list: a row in the design doc's safety section and a Known-limitations entry stating the 21-phrase breadth and the bound (adds a refusal only, fails closed, cites the matrix, redirects to People Ops, no `tools/call`, no write) converts this from an undisclosed defect into exactly the bounded-limitation class the rubric framing declines to penalise. The code fix — gate on `intent == 'action'` or a first-person request verb, plus a negative test with the three phrasings above — touches `src/`, which breaks the empty-diff provenance contract five documents print and forces a re-drive of the published run and both ablation arms.

### 2. The grade-wave process index contradicts the directory it indexes — medium

```
ls docs/process/sdd/G5-grade-5/task-*-report.md | wc -l   # 31
sed -n '45p' docs/process/sdd/G5-grade-5/README.md        # "Coverage: 12 briefs and 30 reports" at this commit
```

Four lines below that claim the README instructs the reader to run exactly that command. This is a recurrence: the fourth grade ranked it #8, `a57ed44` corrected 26→30, and `204d48f` added `task-17-report.md` without touching the count. The same paragraphs still say "three rounds" (line 1), "two further re-grades" (line 6) and carry a three-row rounds table, while `regrade3-report.md` (titled *Fourth grade*), `regrade3-defects.json` (16 entries), `regrade3-polish.json` and `task-17-report.md` sit unindexed beside them — all committed by HEAD itself, and all recorded in `progress.md:159-161`. `ai-tooling.md:381` links this directory.

**Fix.** Add a fourth rounds row (`f7852bb`, band 4, 16 confirmed defects, fixes land as `a57ed44`), add the three `regrade3-*` rows to the file table, add task 17 to the round-3 list, change the title and the "two further re-grades" clause, and replace the literal count with a number-free sentence so the next copied report cannot falsify it again.

### 3. The evaluation segment walks two metric tiles the page does not render — low

`docs/demo-script.md:85` sends the presenter to `/dashboard/evals/r_1790130220_baseline` and names eight figures. The strip is `headline_metrics + ('clarification_accuracy',)` (`eval_detail.html:66`) over the eight keys at `dashboard.py:182-190`, which exclude `doc_recall_mean` and `workflow_completion` — `:220-221` labels them "the two the compare tab charts". Fetching the live page and matching with a real regex: `97\.4` → 0 hits, `93\.3` → 0 hits, `Documents recalled` → 0 hits. Under that page's own **Workflow completion** heading the presenter would say 0.933 while the screen shows the per-workflow pills 66.7% and 50.0%.

**Fix.** Name the nine tiles that are on the strip, and move document recall and workflow completion into the Compare-tab beat at the end of the same segment where both are charted. One sentence.

### 4. `design-and-evaluation.md` names `34d50fb` as "the build that is deployed" — low

`design-and-evaluation.md:20` and `:1504` ("its `target_git_sha` equals the deployed sha") are present tense and false at HEAD: `/health` reports `204d48f`. The substance holds — the application-tree diff is empty and a contract test executes it — and `README.md` plus `deployed.md` both carry the hedge. The primary graded document does not, and it never prints the pathspec that would let a reader reconcile the shas in place.

### 5. Three sentences point at "the provenance pathspec this document prints" — low

`grep -n 'this document prints\|pathspec above' design-and-evaluation.md` → 604, 1053, 1991; `grep -c 'git diff' design-and-evaluation.md` → **0**. Line 604's "above" is the file's first use of the word while the only provenance discussion is at 1053, *below* it. `tests/contract/test_published_run_commands.py` pins five documents as printing the command identically and this is deliberately not one of them.

### 6. "28 of them open mid-word" overstates a measured 23 — low

Grouping `data/index/chunks.manifest.jsonl` by `(doc_id, heading_path)`: 29 continuations, 28 lowercase-first, **23** preceded by a non-whitespace character. Six are preceded by a space or newline, because `src/hrmosaic/rag/chunk.py:148-151` lstrips a window that starts on whitespace. Live at `design-and-evaluation.md:241-243`, `:2170` and `.env.example:56`. The earlier regrade had it right at 23; the `a57ed44` fix pass introduced the conflation while repairing the surrounding sentence.

### 7. Five sites claim a decline emits a *second* confirmation span — low

`docs/architecture.html:1649` asserts "a second confirmation span is emitted, never an in-place update of the pending one", which is the exact inverse of the code. `grep -n add_span src/hrmosaic/web/api.py` → one hit, line 1518, and it writes an `error` span. The only confirmation-span writer in `src/` is `_propose` (`orchestrator.py:3007-3019`, `user_response="pending"`); a decline runs `_resolve_proposal` → `core/trace.py:947-970`, self-described as "The only UPDATE to `spans` in the codebase". Stale: `web/api.py:1831`, `core/trace.py:111` and `:886`, `docs/architecture.html:1647` and `:1649` — and `api.py:1887-1889` contradicts its own docstring 56 lines above. None is among the four comments Known limitation 15 discloses. Fix `architecture.html` now (outside the frozen pathspec); add the three source lines to limitation 15.

### 8. "OpenAI-shaped" tool array, on an Anthropic deployment — low

`mcp/README.md:83`, `docs/architecture.html:1534` and `:1625`. `render.yaml:23` sets `LLM_PROVIDER=anthropic`; `src/hrmosaic/core/llm/anthropic.py:274-284` emits `{name, description, input_schema}` with no OpenAI envelope — that envelope exists only in `openai_compat.py:200-201`. `mcp/README.md` step 2 already names `AnthropicAdapter` as the thing that shapes the wire, and `design-and-evaluation.md:400` states it correctly, so the two MCP documents disagree.

### 9. `deployed.md`'s provenance table gives the published run a time its own rule contradicts — low

`deployed.md:71` states every time in that column is the run file's `created_at`; `:69` prints `02:59:40Z` where `created_at` is 1790130688429615 µs = **02:31:28Z** (= id epoch 02:23:40Z + `duration_s` 467.8). The other nine baselines match their files to the second. `:73` explains 02:59:40Z correctly as when the judged file closed — the defect is mixing the two conventions in one documented column.

### 10. Two frozen-tree source comments carry pre-repair text — low

`src/hrmosaic/rag/chunk.py:6-7` claims windows are "cut on sentence boundaries so a chunk never begins mid-sentence" against `chunk.py:155`; `synthesize.j2:11` says "199 of the 204 committed chunks … (median 995)" where the manifest measures 205 / 200 / 983. Disclosed with corrected figures as Known limitation 15, and both are inside the empty-diff pathspec — a deferred correction, not an unnoticed error. The docstring nonetheless is what a §2 grader reads.

### 11. A cancelled write is filed as outcome `refused`, with two undisclosed consequences — low

The mislabel is Known limitation 13 with a live capture. Undisclosed: `web/api.py:1144` maps `refused` → "I can't answer that one." into the a11y live region, painted from `lastTurn.dataset.outcome` after the `/chat/confirm` swap, so a screen-reader user who cancels hears a refusal over text reading "Cancelled — nothing was created."; and `templates/_turn.html:151-153` asserts a declined confirmation "carries no steps … gets no library link" while `_refuse` keeps the redirect `next_steps`, so the link does render.

### 12. Five broken relative links in the grade-wave index — low

Lines 4, 5, 12, 21, 22 use `../../evidence/…` and `../../superpowers/…`, normalising to `docs/process/evidence` and `docs/process/superpowers`; `ls docs/process/` → `sdd` only. Correct depth is `../../../`. A scan of all 168 tracked `.md` files found exactly 5 unresolved targets and all five are here — including the two links to the grade cards the file exists to point at.

### 13. One ablation sweep is dated 2026-09-11 where the repo's own table dates it 2026-09-10 — low

`r_1789069158_baseline.created_at` = 2026-09-10T19:49:28Z (its arm closed 20:11:38Z the same day); only the −0.231 pair is 09-11. Prose at `design-and-evaluation.md:1391`, `:1713`, `docs/optimization-log.md:903`, `:1048`, against `deployed.md:62` and `optimization-log.md:182`. All nine deltas and the superlatives reproduce; only the day attribution is wrong.

### 14. "eight unanimous grounded labels" where one of the five runs compared seven — low

`docs/optimization-log.md:1021-1022` against `r_1789055103_baseline`'s `judge_agreement_n = 7` (subset `seed_1729_8`, 7 compared). Stated correctly at `optimization-log.md:158` and `design-and-evaluation.md:1218` — so the error is in the one paragraph arguing that an `n` and a population must travel with a rate.

### 15. `docs/evidence/README.md` attributes 390 captures to `screen_ids` — low

`scripts/ux_capture.py:401-402` writes `"screen_ids": ids` and `"screen_count": len(self.entries)`; the live index has `len(screen_ids)` 72 and `screen_count` 390. The parenthesis at `:90-91` also invites 72 × 3 = 216 with nothing explaining the extra 174, which are the `#full` full-page variants of 58 ids — not dark-scheme or phone-only screens. `README.md` binds the same clause to the 72 correctly.

## Polish (brief)

- **Continuation snippets open mid-word** — 23 of 205; the resolved chunk text is always whole and neither committed capture contains one.
- **Ablation arms are unjudged** — so the strict-pass comparison is partly an artefact of an absent judge; disclosed at `REPORT.md:48` with the cost rationale.
- **`ci-deploy-skipped.png` shows four jobs** — a 2026-09-10 run, shown right after the five-job narration, with no warning line in the script.
- **Live `rss_mb` 322.3 against a narrated "about 300 MB"** — both published figures are dated captures and the script says to read the screen.
- **`lint` outside deploy's `needs`** — hardening beyond §8's wording; `ci.yml:38-49` records the upstream false positive that argues against widening the gate.
- **`render.yaml:7`'s comment says `needs: [test, docker]`** — understates a stronger gate, disclosed by file and line, inside the frozen pathspec.
- **`/health` runs three uncached `COUNT(*)`s per poll** — harmless at the real 600 s self-ping rate, disclosed, one-variable recovery.
- **Cold-start figures are n=3 on an older build** — every publication carries `n` and dates; `deployed.md:247-250` says plainly no probe has been re-measured.
- **No test pins continuation-window openings** — covered non-silently: `char_start` feeds the chunk-id hash, so any change fails the byte-identical rebuild.
- **Compliance citations carry an unrounded score** — two conventions in one array, with a documented display-layer rationale and no affected surface.
- **A budget-stopped action turn proposes no card** — disclosed in three documents with cause, quantification and fix; one step of margin on the live path.
- **`REPORT.md`'s Limiter row sits 200 lines from its qualifier** — true as written, qualified in the same file's Notes.

## Considered and dismissed

Refuted on verification; these do **not** count against the grade.

| Claim | Why it fails |
|---|---|
| `render.yaml`'s stale `needs:` comment caps a 5 (env-ci) | Understates a stronger gate, disclosed by file and line plus Known limitation 15, and inside the empty-diff pathspec — no rubric bullet grades a YAML comment. |
| `lint` outside the deploy gate is a security hole | §8 gates on tests and every test-running job is inside `needs`; a credential is exposed by the push, not by the deploy, and widening the gate re-opens the stale-live-sha risk two grades already penalised. |
| No test for `make test`'s index-if-missing prerequisite | The guarantee is exercised in CI by the very command the recipe runs; the Makefile discloses the scope gap in place. |
| The 900 s Render wait has gone red on green-test runs | Both cited runs are misread: one was superseded mid-flight by its own child commit, the other's wait *succeeded* in 152 s and failed at the later smoke step. Cannot recur on a final README commit. |
| No test pins the documented continuation behaviour | The byte-identical manifest test makes any such change loud, and the proposed assertion carries the stale 23 rather than the current figure. |
| Unrounded compliance citation score breaks a precision contract | The project's precision discipline is explicitly scoped to rendered surfaces; `test_number_precision.py` states the machine record keeps full precision. |
| The step-cap miss means an action turn silently skips the card | The guard is the project's stated §9.4 rule applied consistently, the fallback does cost a real `tools/call`, and `demo-script.md:288-289` already names the missed card. |
| `is_bare_balance_ask`'s docstring overstates the rule | Disclosed twice in the graded document with the exact failing example, the bound and the fix, and the file states the literal data rule two lines above. |
| The design doc's abridged output schema omits two per-hit fields | The block is introduced as abridged with "the per-hit sub-schemas elided" and points at the authoritative committed schema, which a contract test compares against a live `tools/list`. |
| `/health`'s `COUNT(*)`s will blow the free-tier quota | The doc's own pessimistic 5-second-poll input is wrong for a `plan: free` instance that demonstrably spins down; at the real rate the arithmetic supports the doc's conclusion, and the live payload still serves the counts 13 days in. |
| Cold-start figures must be re-measured on the published build | The rubric asks for an explanation, not a re-measurement; every publication carries `n` and dates and the staleness is disclosed three times. |
| `deployed.md`'s env table omits three deployed variables | The paragraph introducing the table names all three with section cross-references, and the "ten keys" clause is date-stamped and about the live service, not about `render.yaml`'s current content. |
| `REPORT.md`'s latency section has no cold figure or pointer | The rubric assigns cold-start notes to `deployed.md`; the design document publishes the split and §13.5 explains the `n_cold = 0` line. |
| The hard judge subset is mostly ties and the safety denominators are two | The rubric never asks for judge validation at all; the tie composition is stated in the labels file and the small denominators are Known limitation 5 with the rubric's own 30-item ceiling named as the cause. |
| Dashboard is 11 pages in one document and 13 routes in another | Two different, separately-labelled nouns: the spec's numbered 11-page inventory assigns two routes each to pages 10 and 11. No document claims 11 routes or 13 pages. |
| The architecture page's "8 items" glance tile understates the labelled count | The two label files overlap by four, so 12 items are labelled, not 16 — the proposed fix would publish a false figure; 8 is the exact denominator of both published agreement metrics. |
| The traceability matrix quotes a 204-chunk reading | An explicitly date-stamped 2026-09-10 verification cell; 204 was true then, and the 204→205 change is disclosed in the section it cites. |
| The parent `docs/process/sdd/README.md` omits the grade-wave subdirectory | Its scope is explicitly the P0-P27 working directory; the wave is linked from `ai-tooling.md`, both grade cards and the CHANGELOG, and renders above the README in the directory listing. |
| `REPORT.md`'s Limiter row is 200 lines from its disclaimer | The row is true (it renders the run's own config), the qualifier is in the same file's Notes, and the demo narrates the shipped improvement two beats earlier with the published p50 backing it. |

## Strengths

- **Everything checkable from outside reproduced on the graded tip.** `/health.app.git_sha` = HEAD with `degradations: []`, `mcp.connected` true, 9 tools, 14 docs / 205 chunks, and the same `corpus_sha256` / `manifest_sha256` computed locally; CI green across all five jobs on that sha; an external `initialize` + `tools/list` returning nine tools with byte-identical schemas and 401 unauthenticated.
- **Claims are runnable, not asserted.** The provenance pathspec emits nothing at HEAD and a contract test parses the base sha out of the README line and executes it; `REPORT.md` re-renders byte-identically; `comparison.json` rebuilds byte-identically; `make lock` reproduces all three manifests; `ingest --verify-manifest` rebuilds 205 chunks byte-identical to the committed manifest.
- **Numbers reconcile across documents to the last digit.** 3,170/3,469 with 299 deselected from `pytest --collect-only`; `coverage.xml` 0.9543 / 0.8826 behind the printed 94%; 280 commits at `2dee277` and 304 in the CI whole-history scan; $18.5376 over 28 run files against the published $18.54; all eleven headline eval means recomputable from per-item scores.
- **The infrastructure is itself under test.** 36 assertions over `ci.yml` / `Dockerfile` / `render.yaml`, a nine-assertion provenance contract, schema files pinned against a live `tools/list`, and a no-chain-of-thought contract sweeping payload models, constrained-JSON schemas, golden traces and live spans.
- **The confirmation gate has real invariants.** `mock_writes.confirmation_token NOT NULL REFERENCES`, single use enforced by the `UPDATE`'s own `used_at IS NULL` predicate, the token spent before the row is appended, a byte-identical token-free rejection, 409 on replay, TTL expiry from two directions, and the agent stripping any model-supplied token before every `tools/call`.
- **Citation metadata is exact by construction.** For all 205 chunks `documents.full_text[char_start:char_end] == chunks.text` and every snippet is a whitespace-normalised substring, so a chip, a deep link and a G2 resolution agree by definition.
- **The evaluation audits itself.** Both agreement subsets and rates recompute from code, all 16 labels are bound by `turn_id` with a refusal behind the binding, both blind packets are committed and verifiably score-free with answers equal to the served ones, and the pre-registered claim fails and is printed as failed everywhere including the dashboard.
- **The disclosures are the most unusual thing here.** Small denominators named with their members, the hard subset's non-blindness and its 4-of-8 overlap, a withdrawn wording retracted in place, the pre-ux-gate CI counterexample published rather than buried, a voided labelling round and a discarded evaluation drive in `ai-tooling.md`, and a 15-item limitations list with a dated register of what has closed.

## What the demo must show

Assume the recording is solid; these are the dependencies it rests on and the two places the script will bite.

1. **HEAD on the live service.** Re-check `curl -s <DEPLOY_URL>/health` for `app.git_sha == $(git rev-parse HEAD)` after the final README commit — `paths-ignore` is only the two published-result paths, so that commit does run the suite and deploy.
2. **Token and store.** The README `?access=` token must still be valid (it appears exactly once in the tree and is scheduled for rotation after grading), and Turso must be reachable — `/chat` hard-depends on it, with `PERSIST_BACKEND=sqlite` as the one-variable recovery.
3. **Budget.** `calls_today` 407 against a 1500 cap leaves plenty; the 600 s keep-alive must still be running or the 6:25-7:10 segment has to absorb the measured 71 s median cold-to-first-answer.
4. **Self-dated prompts.** `scripts/demo_prompt.py` must return rc=0 against the deployed service; it fails closed with one stderr line on a bad token and both shell scripts gate on that.
5. **The published run must stay the typed URL.** `/dashboard/evals/r_1790130220_baseline`, because the Runs table is newest-first and currently fronts the `no_structured_tools` arm; do not drive a new eval before recording, or the Compare tab's build-mismatch notice may fire.
6. **Both tasks end to end on the deployed app** — task 1 through the citation into the policy reader, task 2 through **Don't open it** and then **Open the request** to the `MOCK-HR-<n>` lede — with tool names, arguments, results, citations and the final behaviour narrated per task off the session record.
7. **Two live hazards.** Do not improvise a question containing `without manager approval`, `skip the manager` or `approve my own` — the turn hard-refuses (defect 1). And read document recall and workflow completion off the **Compare** tab, not the run-detail strip (defect 3).
8. **One step of margin on the card.** The pinned capture reached task 2's confirmation card on act step 5 of a 6-step cap. If a take ends `answered` with no card, resend.

## What changed since the fourth grade

`a57ed44` — *"the sixteen sentences the fourth grade could falsify"* — landed the predicted ninety minutes of edits across 16 files: `README.md`, `design-and-evaluation.md` (+71/−?), `deployed.md`, `docs/demo-script.md`, `docs/optimization-log.md`, `evaluation/REPORT.md`, `.env.example`, `ai-tooling.md`, `docs/requirements-traceability.md`, plus `evaluation/runner.py`'s derived judge-call span and two provisioning-test fixes. Verified closed: the phantom `check_policy_compliance` limitation is retired with its reason, `scripts/provision_render.py` and `test_provision_render.py` now say `[test, docker, ux]`, the `make setup` / README divergence is gone, and the process-trail count went 26 → 30.

Then `204d48f` — the graded tip — added only the round-3 ledger and the fourth grade's own artifacts (`regrade3-report.md`, `regrade3-defects.json`, `regrade3-polish.json`, `task-17-report.md`, `progress.md`). Two things followed from that:

- **It re-broke the count `a57ed44` had just fixed.** The 31st report arrived; the README still says 30. Defect 2 is literally the fourth grade's defect #8 reintroduced by the commit after its fix.
- **The index was never updated to admit the round it documents.** Four grade reports now sit in a directory whose README says three rounds and two re-grades.

Two defects in this grade were *introduced* by the fix pass rather than missed by it: the 28-vs-23 mid-word count (defect 6, where the fix wrote the lowercase-first proxy into the doc as the mid-word figure) and nothing else in `a57ed44` regressed. The rest of this grade's list is a fresh, deeper tail found by more aggressive probing than earlier passes ran — the `is_unsafe` gate (defect 1, behavioural, missed by four prior grades), the inverted confirmation-span claims (defect 7), the provider-shape claim (defect 8), the provenance timestamp cell (defect 9) and the `screen_ids` attribution (defect 15).

The application tree has not moved: `git diff 34d50fb..HEAD -- src mcp/tools corpus data/index/chunks.manifest.jsonl Dockerfile render.yaml requirements.txt` is empty at HEAD, so the published run still measures the deployed code, and `ruff check .` passes with 3,469 tests collected.

**Net.** The fourth grade's sixteen closed; one reopened by the next commit; one new behavioural finding and a dozen new prose findings surfaced. Substance moved from "ninety minutes from a 5" to a 5 on my reading — carried by everything a grader can independently execute — with the residue being fifteen minutes of disclosure on defect 1, five minutes on defect 3, and roughly ninety minutes of text edits for the rest.