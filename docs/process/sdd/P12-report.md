# P12 report — Documentation, demo prep, publish

**Phase:** P12 (`P12(docs)`) · **Base:** `4ef6e8a` · **Head after this phase:** `a3df454`
**Date:** 2026-09-10 · **Commits:** 1 · **Suite:** 1,622 passed, 1 skipped, pristine

---

## 1. What was built

| File | Status | What it carries |
|---|---|---|
| `design-and-evaluation.md` | **new**, 1,262 lines | The eight DOCS.3 `##` subjects, the ten R10.1 `###` justifications each with its rejected alternative, the mermaid diagram labelling all seven R10.2 components, the generated tool schemas, the 26 questions with expected answers, the results table (marker-filled), the judge methodology, the ablation and chunk-size null results, both demo sequences, `### Security posture`, known limitations, the evidence table |
| `README.md` | rewritten | Five headings, three link lines with the placeholder retired, an `## Access` paragraph under `## Deployment`, a link to `docs/architecture.html`, third-party components |
| `ai-tooling.md` | **new**, 190 lines | `## What worked well`, `## What did not work`, `## AI use and ownership` — a dated account, not marketing |
| `deployed.md` | extended | New `## What is blocked, by which gate, and the command that fills it`; a `### How a commit reaches the service` subsection referencing `ci-deploy-skipped.png`; a dashboard-access paragraph in `## Access` |
| `NEEDS-FROM-USER.md` | rewritten as final | Gates 2/3/4/6/7 open with time estimates, 1 and 5 discharged, the ordered post-gate sequence extended with `paste_eval_numbers.py` and the `deploy_only` dispatch |
| `docs/demo-script.md` | **new** | The §18.3 segment table (0:00–9:15), the standing production note, a five-element DEMO.6 sub-checklist per task, the safety beat, a failure-mode table |
| `docs/pre-submission-checklist.md` | **new** | One `- [ ]` line per DEMO.1–7 and SUB.1–3, plus pre-record and post-submit steps |
| `scripts/paste_eval_numbers.py` | **new** | Fills the results table between `<!-- EVAL-NUMBERS:BEGIN/END -->` from `latest.json`, falling back to the newest committed baseline with a `BLOCKED-BY-GATE` banner; `--check` mode |
| `tests/contract/test_docs_completeness.py` | **new**, 32 tests | The whole file, authored here |
| `tests/contract/test_readme_headings.py` | 1 assertion widened | Accepts a `pending: gate N` marker now that `TBD-before-submission` is retired |

**Nothing else was touched.** `CHANGELOG.md`, `docs/evidence/`, the `ci-red-evidence` branch,
`docs/superpowers/` and `docs/requirements-traceability.md` were deliberately left to the main
session, per the dispatch.

## 2. TDD evidence

`tests/contract/test_docs_completeness.py` was written **first**, against documents that did not
exist, and watched fail:

```
$ .venv/bin/pytest tests/contract/test_docs_completeness.py -q
...
FAILED tests/contract/test_docs_completeness.py::test_readme_carries_no_submission_placeholder
FAILED tests/contract/test_docs_completeness.py::test_readme_has_its_three_link_lines
FAILED tests/contract/test_docs_completeness.py::test_deployed_link_is_tokenized_or_names_an_open_gate
FAILED tests/contract/test_docs_completeness.py::test_demo_video_link_is_recorded_or_names_an_open_gate
FAILED tests/contract/test_docs_completeness.py::test_design_document_has_the_eight_docs3_sections
FAILED tests/contract/test_docs_completeness.py::test_design_document_has_the_ten_r10_1_justifications
FAILED tests/contract/test_docs_completeness.py::test_every_justification_carries_its_rejected_alternative
FAILED tests/contract/test_docs_completeness.py::test_architecture_diagram_labels_all_seven_components
FAILED tests/contract/test_docs_completeness.py::test_architecture_section_links_the_interactive_page
FAILED tests/contract/test_docs_completeness.py::test_security_posture_subsection_is_complete
FAILED tests/contract/test_docs_completeness.py::test_judge_methodology_names_the_labeller_and_the_blinding
FAILED tests/contract/test_docs_completeness.py::test_design_document_references_all_three_evidence_screenshots
FAILED tests/contract/test_docs_completeness.py::test_documented_demo_sequences_match_the_executable_records
FAILED tests/contract/test_docs_completeness.py::test_results_table_carries_the_metric_families
FAILED tests/contract/test_docs_completeness.py::test_paste_eval_numbers_markers_are_intact
FAILED tests/contract/test_docs_completeness.py::test_deployed_references_the_ci_evidence_screenshot
FAILED tests/contract/test_docs_completeness.py::test_ai_tooling_has_its_three_sections
FAILED tests/contract/test_docs_completeness.py::test_ai_tooling_names_the_tools_and_the_workflow
FAILED tests/contract/test_docs_completeness.py::test_ai_tooling_carries_the_ownership_disclosure
FAILED tests/contract/test_docs_completeness.py::test_demo_script_carries_the_segment_table_and_the_production_note
FAILED tests/contract/test_docs_completeness.py::test_demo_script_carries_a_five_element_sub_checklist_per_task
FAILED tests/contract/test_docs_completeness.py::test_pre_submission_checklist_has_a_line_per_demo_and_sub_id
22 failed, 10 passed in 0.19s
```

Then green after the documents were written (§3).

**The tests verify behaviour, not shape.** Two are worth naming because they can genuinely catch
rot rather than only absence:

- `test_documented_demo_sequences_match_the_executable_records` loads the **live**
  `DEMO_EXPECTATIONS` from `tests/e2e/test_demo_tasks.py` by path and asserts every
  `required_tools` entry appears in the documented sequence. Renaming a tool in the record, or
  adding a required tool, fails the docs test — R10.3's rot risk, closed.
- `_assert_pending_names_only_open_gates` parses the unticked `- [ ] **N —` gate list out of
  `NEEDS-FROM-USER.md` and asserts a `pending: gate N` link line names **only gates that are still
  open**. Tick gate 6 in `NEEDS-FROM-USER.md` without replacing the `Demo video:` link and the
  suite goes red.

## 3. Definition of done — real output

### 3.1 `python scripts/paste_eval_numbers.py`

```
$ .venv/bin/python scripts/paste_eval_numbers.py
wrote design-and-evaluation.md's results table from evaluation/results/r_1789032950_baseline.json (target: local)

$ .venv/bin/python scripts/paste_eval_numbers.py --check
OK — the results table matches evaluation/results/r_1789032950_baseline.json
```

`latest.json` does not exist (it can only ever name a `target: deployed` run, gate 2 + 4), so the
script used its documented fallback and wrote a `BLOCKED-BY-GATE` banner above the table. The
block it produced is in §5.

### 3.2 `pytest tests/contract/test_docs_completeness.py -q`

```
$ .venv/bin/pytest tests/contract/test_docs_completeness.py -q
................................                                         [100%]
32 passed in 0.30s
```

Coverage of the brief's checklist: ten `###` R10.1 headings ✓ (plus each one asserted to state a
rejected alternative) · eight `##` DOCS.3 headings ✓ · `### Security posture` with all six required
subjects ✓ · README's five headings ✓ and three link lines ✓ (`Deployed:` held to `?access=` when
it is an https URL) · `deployed.md`'s six ✓ (plus the access strings, a measured cold-start number
with an ISO date, the MCP-transport rationale, `$0` cost) · `ai-tooling.md`'s three ✓ · demo script
✓ and pre-submission checklist ✓ complete.

### 3.3 `grep -c 'TBD-before-submission' README.md`

```
$ grep -c 'TBD-before-submission' README.md
0
```

(`grep -c` exits 1 on a zero count, as expected for a `-c` with no matches.)

### 3.4 Whole suite and lint

```
$ .venv/bin/pytest -q
1622 passed, 1 skipped in 139.30s (0:02:19)

$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
216 files already formatted
```

Pristine — no warnings. The single skip is pre-existing and gate-related:
`tests/unit/test_latest_points_at_deployed.py:30: no published run yet; latest.json lands at P11`.
Net test delta: 1,590 → 1,622 (+32, all from this phase's new file).

### 3.5 `gh api -X PUT …/collaborators/quantic-grader` and the permission read-back

```
$ gh api -X PUT repos/seantmalone/quantic-mosaic/collaborators/quantic-grader
{"id":332539032, … "invitee":{"login":"quantic-grader","id":227221966, …},
 "inviter":{"login":"seantmalone", …}, "permissions":"write",
 "created_at":"2026-09-10T15:21:59Z",
 "html_url":"https://github.com/seantmalone/quantic-mosaic/invitations"}
EXIT=0

$ gh api repos/seantmalone/quantic-mosaic/collaborators/quantic-grader/permission
{"permission":"read","user":{"login":"quantic-grader","id":227221966, …,
 "permissions":{"admin":false,"maintain":false,"push":false,"triage":false,"pull":true},
 "role_name":"read"},"role_name":"read"}
EXIT=0

$ gh api repos/seantmalone/quantic-mosaic/invitations --jq '.[] | {id, invitee: .invitee.login, permissions, created_at}'
{"created_at":"2026-09-10T15:21:59Z","id":332539032,"invitee":"quantic-grader","permissions":"write"}
```

**The invite is sent and pending.** The read-back reports `read` because the repository is public
and the invitation has not been accepted — a public repo already grants `pull` to everyone, and the
pending invitation carries `write`, which takes effect on acceptance. No visibility change was made
(`gh api repos/seantmalone/quantic-mosaic --jq .private` → `false`, unchanged). Acceptance is the
`- [ ] SUB.3` line in `docs/pre-submission-checklist.md`. See §7 concern 1 about the `write` default.

### 3.6 `BASE_URL="$DEPLOY_URL" bash scripts/demo_task_1.sh && … demo_task_2.sh`

**BLOCKED-BY-GATE (2 + 4).** `$DEPLOY_URL` does not exist: no Render service has been created.
What *was* proved is that both scripts run green end to end against a live instance and that both
send the bearer header on every call — `make demo1` / `make demo2` run the identical scripts
against a locally started server:

```
$ grep -n 'Authorization: Bearer' scripts/demo_task_1.sh scripts/demo_task_2.sh
scripts/demo_task_1.sh:34:  -H "Authorization: Bearer ${APP_ACCESS_TOKEN:-}" \
scripts/demo_task_1.sh:45:      -H "Authorization: Bearer ${APP_ACCESS_TOKEN:-}" \
scripts/demo_task_2.sh:35:  -H "Authorization: Bearer ${APP_ACCESS_TOKEN:-}" \
scripts/demo_task_2.sh:45:      -H "Authorization: Bearer ${APP_ACCESS_TOKEN:-}" \
scripts/demo_task_2.sh:86:  -H "Authorization: Bearer ${APP_ACCESS_TOKEN:-}" \

$ make demo1
== Demo task 1 — international remote-work eligibility
-- outcome: answered
-- citations (6 from 3 document(s))
-- trace (26 spans)
   20  guardrail      G4_injection_shield     0 ms  verdict=allow · 15 retrieval chunks clean
   22  guardrail      G1_evidence_gate        0 ms  verdict=allow · max dense score 0.801, 15 supporting chunk(s)
   24  guardrail      G2_citation_resolvability 0 ms verdict=allow · 8/8 citations resolved
   25  guardrail      G3_fact_vs_recommendation 0 ms verdict=allow · 7 block(s), every policy_fact cited
   26  guardrail      G6_pii_secret_redaction 0 ms  verdict=allow · final answer carried nothing to redact
-- usage: 5 model call(s), 7 tool call(s), 5 retrieval(s), 31985→1797 tokens in 284 ms

$ make demo2 ; echo EXIT=$?
== Demo task 2 — PTO request with a confirmation-gated mock write
-- the confirmation card (nothing has been created yet, and there is no token in this body)
-- Confirm: POST /chat/confirm mints the one-time token and the write happens
INFO:     127.0.0.1:61149 - "POST /chat/confirm HTTP/1.1" 200 OK
-- outcome: answered
-- citations (3 from 2 document(s))
-- trace (28 spans)
   18  confirmation   create_mock_hr_ticket   0 ms  create_mock_hr_ticket · pending
   22  confirmation   create_mock_hr_ticket   0 ms  create_mock_hr_ticket · confirmed
        result {"status": "created", "ticket_id": "MOCK-HR-000005", "queue": "hr-timeoff", …}
-- usage: 7 model call(s), 6 tool call(s), 2 retrieval(s), 38858→1713 tokens in 224 ms
EXIT=0
```

Demo 1 cites 3 documents (floor 3) with no write and no confirmation; demo 2 cites 2 (floor 2) and
ends in exactly one confirmed mock write. Both match `DEMO_EXPECTATIONS`.

### 3.7 `gh workflow run ci.yml -f deploy_only=true && curl -s "$DEPLOY_URL/health" | jq …`

**Not run — main-session step, and BLOCKED-BY-GATE.** Dispatching CI is the coordinating session's
role in this build (subagents never push), the `deploy_only` run is what the main session is
already using for the R8.4 red-run evidence, and the `curl` half needs a `$DEPLOY_URL` that does
not exist. The command is written into `NEEDS-FROM-USER.md` §4 (*Get the results onto the live
dashboard, and prove they arrived*) with the `eval_runs_imported` check beside it, and into
`deployed.md`'s blocked-by-gate table.

## 4. Structural check of the rendered documents

`gh markdown` is not a subcommand, so instead of a preview I ran a structural check over all seven
documents — balanced code fences, no ragged markdown tables, and every relative link resolving to
a file that exists:

```
README.md: 104 lines, 7 headings, fences=10 -> OK
design-and-evaluation.md: 1246 lines, 52 headings, fences=14 -> OK
ai-tooling.md: 190 lines, 6 headings, fences=0 -> OK
deployed.md: 302 lines, 13 headings, fences=2 -> OK
NEEDS-FROM-USER.md: 226 lines, 14 headings, fences=12 -> OK
docs/demo-script.md: 145 lines, 8 headings, fences=0 -> OK
docs/pre-submission-checklist.md: 67 lines, 5 headings, fences=0 -> OK
```

The mermaid block in `design-and-evaluation.md` is spec §2's diagram verbatim apart from two
figures updated to the measured values (`~345 MB` → `294.9 MB`, `~280 chunks` → `204 chunks`) and
the LLM node relabelled `LLM Provider` (singular) so the R10.2 component name appears literally.

## 5. The results block `paste_eval_numbers.py` produced

```
> ⚠ **`BLOCKED-BY-GATE` — these are the `target: local` proving-run figures, not the published
> ones.** … (gates 2 and 4 of `NEEDS-FROM-USER.md`) …

**The run below.** `r_1789032950_baseline` · variant `baseline` · target `local` · 26 items ·
agent `claude-haiku-4-5` · judge `gemini-3.5-flash-lite` · dataset sha `a501f288a6589730…` ·
estimated spend $0.4355.

| Metric | Value | n | Target |
|---|---|---|---|
| Groundedness (mean, claim-level) | 0.985 | 16 | ≥ 0.90 |
| Citation accuracy (CitResolve × F1) | 0.899 | 16 | – |
| Citation resolvability (served answer) | 0.923 | 26 | ≥ 0.95 |
| Document recall | 0.842 | 19 | – |
| Partial match (gold facts entailed) | 0.781 | 16 | – |
| Tool selection (F1, order-insensitive) | 0.926 | 26 | – |
| Argument correctness | 1.000 | 18 | – |
| Workflow completion | 0.808 | 26 | – |
| Action safety pass rate | 1.000 | 26 | 1.00 |
| Clarification accuracy | 0.667 | 3 | – |
| Over-refusal rate | 0.111 | 18 | lower is better |
| Missed-refusal rate | 0.000 | 4 | lower is better |
| Strict pass rate (composite) | 0.654 | 26 | ≥ 0.85 |
| Latency p50 / p95 (ms) | 17,670 / 42,430 | 26 | – |
| Cold turns in the distribution | n_cold = 0 | – | reported separately |
```

Plus a behaviour line (`nudge_rate` 0.115, `catalog_reopened_rate` 0.038, `gated_attempts` 1,
`injection_quarantined` true, `blocks_dropped_by_g2` 1, per-workflow completion) and the
non-representative-latency warning.

## 6. Ambiguities resolved, and how

1. **`Deployed:` must carry `?access=` and `TBD-before-submission` must be gone — but the link
   cannot exist.** Both DoD lines are unsatisfiable together while gates 2 and 4 are open.
   Resolution: retire the placeholder and replace it with `pending: gate 2 + 4 (Render account +
   API key) — see NEEDS-FROM-USER.md`, which is strictly more informative than the placeholder was.
   `test_deployed_link_is_tokenized_or_names_an_open_gate` **branches**: an `https://` value is
   held to the full `?access=` requirement; a pending value is held to naming only gates
   `NEEDS-FROM-USER.md` still lists as open. This is an assertion, not a skip — the moment gate 2
   is ticked without the link being replaced, the test fails.
2. **The same for `Demo video:`**, whose gate is 6 (record the walkthrough).
3. **This forced a one-assertion edit to `tests/contract/test_readme_headings.py`** (P0's file,
   outside the brief's scope line). Its link check accepted only an `https://` URL or the literal
   placeholder, and its capture group was `(\S+)`, so any marker at all failed it. It now also
   accepts a `pending: gate N` value, with a comment explaining why. **This does not weaken the
   test** — it already accepted a non-URL placeholder — and `test_docs_completeness.py` adds the
   strictness the placeholder never had. Flagged here because it is a scope deviation.
4. **`latest.json` does not exist, so `paste_eval_numbers.py` needs a defined behaviour.** It
   falls back to the newest committed `*_baseline.json`, exits 0, prints which source it used, and
   writes a `BLOCKED-BY-GATE` banner. It never presents a `local` run as the published one, and
   the `target == "deployed"` branch renders the clean published header instead.
5. **Three of the ten R10.1 `###` names collide with three of the eight DOCS.3 `##` names**
   (*MCP server design*, *Tool schemas*, *Safety guardrails*) — the two requirement lists name the
   same subjects. Resolution: the eight `##` sections **describe**; a final
   `## Design justifications` section holds all ten `###` subsections, which **justify** against a
   rejected alternative. A paragraph in that section says so explicitly, and every heading
   assertion in the test matches **whole lines**, so `### Tool schemas` can never satisfy an
   assertion for `## Tool schemas`.
6. **`ai-tooling.md`'s third required section had no name in the brief** (it says "the AI-use and
   ownership disclosure"). Chosen: `## AI use and ownership`, asserted alongside the two named
   headings, with the test additionally requiring the words *correctness*, *security* and
   *integrity* — the three the plagiarism policy names.
7. **Which numbers the design document publishes.** It publishes the `target: local` figures,
   labelled as such in three places (the results banner, the latency warning, known limitation 8),
   because those are the only real numbers that exist. No figure was rounded, adjusted or omitted.
8. **`CHANGELOG.md` was not touched.** Roadmap §2.1 assigns it to the main session, and it is not
   in the brief's scope line — as is `docs/evidence/` and the `ci-red-evidence` branch, per the
   dispatch.

## 7. Self-review findings (found and fixed before commit)

1. **The test count was stale.** The design document and `ai-tooling.md` both claimed 1,590 tests,
   which was true at P11 and is not true after this phase adds 32. Corrected to 1,623 collected
   where it describes the current suite; `ai-tooling.md`'s *"grew from 72 at P1 to 1,590 at P11"*
   is a historical statement and stands.
2. **The CI step order was wrong.** I had written `pytest` → `pii_check.py` → `check_facts.py`.
   `ci.yml` actually runs `check_facts.py` → `ingest --verify-manifest` → `pytest -q` →
   `pii_check.py`. Corrected against the workflow file.
3. **The tool schema was labelled "in full" but is abridged.** I had reflowed property order and
   elided the generated `title` keys and the per-hit sub-schemas. The lead-in now says so and
   points at the committed file as authoritative.
4. **The chunk-size sweep was described qualitatively and vaguely** ("did not move materially",
   plus a claim about section lengths that the data does not support — the chunk count moves 235 →
   204 → 180, so windowing plainly does happen). Replaced with the actual three-row table:
   DocRecall is **identical at 0.8947** at all three sizes, and the honest reading — the *heading*
   boundary does the work, and DocRecall is too coarse to separate window sizes — is stated.
5. **Latency rendered as `17670.000 ms`.** Added a `_ms()` formatter; percentiles now render as
   `17,670`.
6. **`_demo_expectations()` crashed on `@dataclass`.** Loading `test_demo_tasks.py` by path
   without registering it in `sys.modules` makes `dataclasses` raise
   `'NoneType' object has no attribute '__dict__'`. Fixed by registering the module and popping it
   in a `finally`.
7. **A case-sensitivity bug in my own test.** `### Security posture` was checked for the literal
   `employee-scoped` while the document writes *Employee-scoped* at the start of a sentence. The
   phrase list is now matched case-insensitively.
8. **The DEMO.6 sub-checklist assertion pinned a heading level.** It required exactly
   `### Task 1 — …`; the document uses `##`. Relaxed to any heading line naming the task and
   carrying `DEMO.6 sub-checklist`, which is what the requirement actually cares about.

## 8. Concerns for the controller

1. **The grader invite grants `write`, not `read`.** `gh api -X PUT …/collaborators/<user>`
   defaults to `permissions: write`, and that is exactly the command the spec (§19.1 item 5), the
   roadmap and this brief all pin, so I ran it verbatim rather than deviating. A grader needs only
   `pull`. If you want it tightened, the command is
   `gh api -X PUT repos/seantmalone/quantic-mosaic/collaborators/quantic-grader -f permission=pull`
   — re-inviting replaces the pending invitation. Worth a ruling before submission.
2. **The `Deployed:` and `Demo video:` lines are markers, not links.** Everything is staged so
   that satisfying gate 2 + 4 is a paste (`provision_render.py` prints the exact line) and gate 6
   likewise, but the README ships today without a live link and `test_docs_completeness.py` will
   only *hold you to it* once the gates are ticked in `NEEDS-FROM-USER.md`. Someone must
   actually do the replacement.
3. **`design-and-evaluation.md` publishes `target: local` numbers.** They are labelled in three
   places, but the rubric's headline expectation is the deployed run. After the gates land, the
   whole fix is: run the block in `NEEDS-FROM-USER.md` §3, then
   `python scripts/paste_eval_numbers.py` — which will detect `latest.json`, switch to the
   published-run header, and drop the banner and the latency caveat automatically.
4. **The 0.654 strict pass rate is published as-is**, with the nine per-item causes and a
   *Known limitations* section listing all eight gaps (including the G1 over-refusal on
   `remote-003` and the three disputed `expected_tools`). This is a deliberate honesty choice
   under the standing ruling; if the controller would rather the dataset review land first, the
   document's limitation 3 is the paragraph to revise.
5. **One P0 test file was edited** — one assertion in `tests/contract/test_readme_headings.py`.
   See §6 item 3.
6. **`docs/requirements-traceability.md` still says every row is `planned`.** Flipping rows to
   `built` / `verified` is not in this brief's scope line, but P12 is the last phase, so someone
   should decide whether the matrix ships with a `planned` status vocabulary that the rest of the
   repository contradicts.
7. **`ai-tooling.md` names me (the model) and the process in detail.** It is written in Sean's
   voice as the author, which is what the disclosure requirement asks for, but it makes strong
   factual claims about how the build ran (dates, agent collisions, the voided labelling round).
   Every one is sourced from `progress.md`, `CHANGELOG.md` or a phase report — worth a read-through
   before submission all the same, because it is the document a grader will read for integrity.
