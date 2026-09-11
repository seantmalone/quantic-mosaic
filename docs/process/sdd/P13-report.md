# P13 report — prompt and orchestration hardening for Haiku (R1–R7)

Base commit `bf85ffd` · head `8ac9357` · branch `main` (never pushed)

All seven approved changes are implemented, tested and committed. `pytest -q` is **1703 passed**
(1682 at the analysis baseline `395036d`, 1682 at `bf85ffd`, plus 21 new tests). Every
definition-of-done command assigned to this subagent was run at head and its real output is pasted
below. The deployed sweep is the main session's.

## Commits

| sha | subject |
|---|---|
| `6d3450e` | P13(agent): the router sees the corpus, and a tool value carries no citation |
| `3b68ae8` | P13(agent): pto_request is not complete until the employee record is in state |
| `af95de4` | P13(agent): a breadth reminder, and a G1 recovery step that is told why |
| `679f35b` | P13(agent): G1 counts the compliance engine's evidence — scored, never on trust |
| `8ac9357` | P13(agent): fix: self-review — an honest step summary, an unused parameter, three stale notes |

Two commits by the main session (`3d60f27`, `b56531b`, `333ad23`) landed on `main` between mine;
the final suite run above is at my head, with theirs in the tree.

## What was built

### R1 — `route.j2` names the corpus (`equipment-001`)
A **CORPUS** paragraph is inserted directly after the line that defines `out_of_scope`: *"the policy
library covers, and only covers:"* then the exact titles of the 14 indexed documents, then the two
directions the brief specifies verbatim (`Set out_of_scope only when …` and `Device refresh cycles,
asset return, spend limits and approval thresholds are IN the corpus.`). "and only covers" is kept.

The titles are rendered from `prompts.corpus_titles()` — `corpusread.list_documents()`, the same
`documents` table `list_policy_documents` reads — registered as a **Jinja global**, so `render()`'s
signature and every caller are unchanged and the `system` half stays byte-stable (the corpus is a
property of the deployment, not of the turn). `test_the_corpus_paragraph_lists_exactly_the_manifest_titles`
asserts the rendered list, split on `; `, equals the titles in the committed
`data/index/chunks.manifest.jsonl`, so the prompt and the manifest cannot drift.

### R2 — `synthesize.j2` rule 6b (`pto-002`)
Added verbatim, immediately after rule 6 (the `as_of` rule), wrapped to the file's column width.

### R3 — the `search_breadth` reminder (`remote-002`, `expenses-002`)
A third reminder in `Orchestrator._nudge`, recorded in `turn.nudges` and sent at most once per turn.
It fires only when neither other reminder fired on that step (the two earlier branches return first),
a corpus-search tool is in the permitted set, and the turn has made at most one corpus search. The
text is the brief's, verbatim; it names no tool, no document count and no `k`
(`test_the_breadth_reminder_names_no_tool_and_no_document_count`).

"a corpus search" is counted as successful `search_policy_documents` results in `LoopState.results`,
via the existing `workflows.EVIDENCE_TOOLS` constant — the same list the workflow debts already read
for "is retrieval reachable at all", so the reminder can never ask for a call the next boundary
would refuse.

### R4 — the G1 recovery step is told why (`remote-003`)
`_answer`'s reopen branch now appends one deterministic `Message(role="user", …)` with the brief's
text before re-running the act loop, and records `g1_recovery` in `turn.nudges`, so the recovery
`act_summary` plan span shows it.

### R5 — `pto_request` requires the employee profile (`pto-003`, `unsafe-001`)
`requires_tool_results` gains `lookup_employee_profile` (first, in slot order), `SLOT_DESCRIPTIONS`
gains the wording `remote_work.py` already uses, and `is_complete` gains the clause. See
*Ambiguities* below on why `is_complete` had to change too.

### R6 — `route.j2` names every missing detail (`amb-003`)
The `needs_clarification` line now reads: *"… Name EVERY missing detail in rationale_summary, not
only the first — the question the user is shown is built from that line."* The rest is unchanged.

### R7 — G1 counts compliance-engine evidence (`remote-003`, after R4)
New `rag.retrieve.score_chunk_ids(chunk_ids, *, query)`: §7.1's fill step applied to an explicit id
list — one query embedding, the chunks' **stored** vectors, `1 − cosine_distance`. Nothing is
re-embedded; an unknown id is simply absent; no embed happens at all when nothing resolves.

New `Orchestrator._engine_evidence`, called from `_absorb` for `check_policy_compliance` results:
collects the per-requirement `evidence.chunk_id`s that the turn does not already hold, resolves each
against the committed index with `corpusread.get_chunk`, scores them, runs the resolved **text**
through `g4.scan` (and emits one `guardrail` span with `source: compliance_evidence`), then writes
each into `turn.evidence` and `LoopState.note_evidence` exactly like a retrieved candidate.

G1's rule and both thresholds are untouched. A resolved chunk below `MIN_EVIDENCE_SCORE` still
refuses; a quarantined one is stored flagged and is never citable; an unknown id is ignored. The
engine's top-level `citations[]` is deliberately **not** admitted (see *Ambiguities*).

## Definition-of-done output (run at head `8ac9357`)

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
221 files already formatted

$ LLM_PROVIDER=stub .venv/bin/pytest -q
........................................................................ [ 97%]
...............................................                          [100%]
1703 passed in 141.20s (0:02:21)

$ .venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers

$ .venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  format    docs  chunks    words
  md          11     153    23276
  html         1      17     2515
  pdf          1      15     2425
  txt          1      19     2624
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)

$ git status --short
(clean)
```

Test output is pristine: no warnings, no skips, no xfails.

## TDD evidence

* **R1/R2/R6** — the four new prompt tests were written against the edited templates; the golden
  snapshot failed first and was the change's own proof:
  `FAILED test_the_rendered_prompt_matches_its_golden[system-route.j2]` and
  `[system-synthesize.j2]`, with the diff showing rule 6b and the CORPUS paragraph. Goldens
  regenerated from the templates (no trailing-newline drift: `act.system.txt` is untouched).
* **R5** — three tests written first, all three red before the change:
  `test_the_pto_workflow_is_incomplete_until_the_employee_record_is_in_state`,
  `test_the_pto_workflow_requires_all_three_tool_results`,
  `test_the_missing_employee_record_is_reported_as_a_debt_in_workflow_words` — then green.
* **R3** — seven tests written before the branch existed; the run before the fixture rework showed
  12 red, which is what surfaced every existing test that assumed "no reminder here" (see *Blast
  radius*).
* **R4** — the integration test passed on first run because the implementation was already in the
  tree, so it was verified by removing the two lines again:
  `FAILED tests/integration/test_fault_empty_retrieval.py::test_the_reopened_step_is_told_why_the_first_answer_was_refused`,
  then restored and green.
* **R7** — six tests written first; the run before the implementation was `5 failed, 1 passed`
  (the one that passed is the P8-narrowing control, which must stay green), then all six green.

## Files changed

Source
* `src/hrmosaic/agent/prompts/route.j2` — CORPUS paragraph (R1), `needs_clarification` line (R6)
* `src/hrmosaic/agent/prompts/synthesize.j2` — rule 6b (R2)
* `src/hrmosaic/agent/prompts/__init__.py` — `corpus_titles()` and the Jinja global
* `src/hrmosaic/agent/orchestrator.py` — `SEARCH_BREADTH`, `G1_RECOVERY`, `COMPLIANCE_TOOL`,
  `_nudge`'s third branch, `_searches`, the recovery message, `_engine_evidence`
* `src/hrmosaic/agent/workflows/pto_request.py` — R5
* `src/hrmosaic/rag/retrieve.py` — `score_chunk_ids`

Docs
* `docs/superpowers/specs/…-hr-agentic-rag-design.md` — §7.2 (the three prompt rules), §7.4 (G1's
  candidate widening), §9.1 (three reminders, one per step), §9.2 (the recovery message), §9.3
  (`pto_request`'s row and the structured-data note), §13.9 (the post-hoc disclosure)
* `CHANGELOG.md` — one P13 entry, R1–R7 with the dataset item each targets

Tests and fixtures
* `tests/contract/test_prompt_golden.py` (+4), `tests/fixtures/prompts/route.system.txt`,
  `synthesize.system.txt`
* `tests/unit/test_agent_nudge.py` (+10, several updated), `tests/unit/test_compliance_evidence_is_scored.py` (new, 6)
* `tests/integration/test_fault_empty_retrieval.py` (+1, one count updated)
* `tests/contract/test_unmodelled_failure_is_graceful.py` (docstring)
* `tests/fixtures/llm_scripts/`: `nudge_probe`, `rag_only`, `four_turns`, `repair_round_trip`,
  `injection_probe`, `fault_empty_retrieval`

## Blast radius of R3, and how each fixture moved

The breadth reminder fires on any turn that stopped after ≤ 1 search, which is the shape most stub
scripts had. Six scripts moved, in two ways, and each `_note` says which:

* **The model declines the reminder** — `nudge_probe` (a fourth prose act entry: all three reminders
  now fire before the loop lets it stop), `rag_only` and `four_turns` (`rag_only` × 4),
  `repair_round_trip`. This is the honest shape for a one-part question.
* **The turn searches both halves of a two-part question in one step**, so the reminder has nothing
  to report — `injection_probe` (which is the "never nudged" control, and must stay one),
  `fault_empty_retrieval` (whose extra step is the G1 reopen, not a nudge).

`tests/unit/test_agent_nudge.py`'s `a_turn()` fixture now takes `searches: int = 2`, so every test
that does not name it is about the reminder it names; the breadth tests set it themselves, and the
two "without retrieval" tests set `searches=0` so their names stay true.

`DEMO_EXPECTATIONS` was checked and **not** changed. Demo task 2 ends at the confirmation gate and
resumes through it, so `pto_request.is_complete` is not what closes that turn; the record
deliberately asserts the outcome rather than the one path the live recording takes, and
`tests/e2e/test_demo_tasks.py` is green unchanged. A live demo-2 turn will now be nudged for the
employee record, which is the intended effect of R5.

## Ambiguities resolved

1. **R3 fires at zero searches too.** The brief's condition is "the turn has made at most ONE corpus
   search so far", so a turn that searched none is included — but the mandated text opens "you have
   searched the corpus once", which is then not literally true. I followed the brief's condition
   (`<= 1`) and kept the text verbatim, because both are explicit and approved. The turn's own
   `step_summaries` line reports the real count, so the audit trail never claims a search that did
   not happen. If the wording matters more than the condition, changing `<= 1` to `== 1` is a
   one-character change and `test_a_turn_that_searched_once_is_reminded_…` still passes;
   `nudge_probe` would then need its fourth act entry removed again.
2. **R3's "tools are not disabled"** is read as *the retrieval tool is reachable in the permitted
   set* — `_permitted()` already applies §13.9's per-turn `tools_disabled` filter, so the two clauses
   are one condition. The stronger reading (silence the reminder on any turn with a non-empty
   `tools_disabled`) would give the `no_structured_tools` arm fewer reminders than the baseline and
   bias the ablation in the direction of its own prediction, which seemed clearly wrong.
3. **R5 required changing `is_complete`, not only `requires_tool_results`.** The brief says adding to
   `requires_tool_results` fixes the early `is_complete`, but the predicate is written out
   explicitly in `pto_request.py` and does not read that tuple (`requires_tool_results` drives the
   debts a reminder reports). The brief's own test — "`is_complete` false without the profile" —
   only passes if the clause is added, so I added both.
4. **R7 reads `requirements[].evidence`, not the top-level `citations[]`.** The brief names the
   per-requirement evidence blocks. `citations[]` is the union of requirement evidence *and*
   approval evidence, and admitting it would have hollowed out the P8 narrowing test that says a
   merely cited id is not evidence. Consequence: a chunk that backs only an *approval* row is not
   scored or admitted. `test_the_engines_own_citation_list_is_still_not_evidence` pins the choice
   with a **resolvable** chunk id, so it is a real assertion rather than an accident of a fake id.
5. **Where the scoring lives.** §4.2's docstring convention says `agent/**` should not import
   `hrmosaic.rag`. The dense score needs sqlite-vec (the `vec0` table) and the query embedding, both
   of which live in `rag/`, and `core/corpusread` deliberately opens a connection without the
   extension. I put the function in `rag/retrieve.py` (where the identical fill step already lives)
   and did the one import lazily inside `_engine_evidence`, with a comment — the shape
   `web/api.py::_index_block` and `mcpserver/server.py::ServerDeps.index` already use. The
   alternative was a tenth MCP tool whose only caller is that line, which would have put an extra
   `tools/call` on every compliance turn and cost §13.4's ToolPrecision. Flagging it for review as
   the one convention this wave bends.
6. **The CORPUS paragraph splits the FIELDS list.** The brief says "after the line that defines
   `out_of_scope`", which is inside that list, so the paragraph sits between the `out_of_scope` and
   `sensitive` field lines. I took the instruction literally — proximity to the field it governs is
   presumably the point.

## Concerns

* **`nudge_rate` and latency will rise**, as the brief anticipates. Most turns that stop after one
  search now cost one extra act step (one extra provider call). `AGENT_MAX_STEPS` is 6 and a turn
  can now spend three of them on reminders plus one on the G1 reopen, so a pathological turn has
  fewer steps left for tools than before. Nothing in the suite hits it; worth watching in the sweep.
* **`route.j2` now reads the index at render time.** If `data/index/hr_index.sqlite` were missing,
  the router step would raise instead of the turn failing later at the first tool call. It still
  answers HTTP 200 (the unmodelled-failure path), but as an `error` escalation rather than a clean
  `configuration_required`. The deployed image builds the index at build time and `/ready` gates on
  it, so this is a local-dev shape only. Not guarded, deliberately: an empty title list would put a
  false statement in the prompt.
* **R7 opens a read-only index connection per compliance result** (`index.open_index()` runs
  `check_meta` each time). One or two per turn; measured cost is dominated by the single embed. If
  the deployed 0.1-CPU instance shows it, a cached connection is the fix.
* **R7's embed runs on the event loop** inside `_absorb`, which is synchronous and called directly
  by several existing unit tests. Making it `async` to hand the embed to `asyncio.to_thread` would
  have rewritten those tests' call sites; I judged that out of scope for this wave.
* **The `no_structured_tools` arm changed meaning** (R5). Disclosed in §13.9 as a post-hoc change,
  with no restated prediction. Figures from P13 onward are not comparable arm-to-arm with P11's.
* **Two P13 changes push in opposite directions on `remote-002`**: R3 asks for more searches while
  R7 supplies evidence without one. Both target different items and neither disables the other, but
  the sweep is the only thing that can say what the combination does.

---

# P13 fix report — review round 1 of 3

Base `8ac9357` · head `b24ad32` · branch `main` (never pushed). Both open findings are fixed, both
are covered by tests that fail without the fix, and every definition-of-done command from the brief
was re-run at head with its real output pasted below. `pytest -q` is **1708 passed** (1703 at
`8ac9357` plus 5 new tests).

## Finding 1 — `_rehydrate` did not reproduce the engine's evidence (Important)

**What changed.** `orchestrator._rehydrate`'s `elif kind == "tool_call":` branch now calls
`self._engine_evidence(turn, body)` when `payload["tool_name"] == COMPLIANCE_TOOL`, directly after
`turn.state.record(...)` — the same one line `_absorb` runs live, so the resumed turn's candidate
set is rebuilt identically to the pre-park one.

**Why it mattered.** R7 made compliance-engine evidence count towards `pto_request.is_complete` and
towards G1, but that evidence is *scored*, never retrieved, so it never reaches a `retrieval` span
and `_rehydrate_retrieval` cannot bring it back. A `pto_request` turn could satisfy `evidence_met`
from two scored engine chunks with no search at all, close as complete, propose the ticket and park
at §8.6's confirmation gate — and then, after the human confirmed the write, `_answer` ran G1 over a
`citable()` set rebuilt from retrieval spans alone (empty) and refused with `no policy evidence was
retrieved`, on a write that had already happened. It also broke §9.1's stated property that the
resumed synthesize prompt carries the pre-confirmation evidence: `turn.evidence` lost the engine
chunks before synthesis. The reviewer's diagnosis was exact; nothing about it needed adjusting.

**Covering tests.** New fixture `tests/fixtures/llm_scripts/compliance_confirm_resume.json` — the
router selects no corpus-search tool, so the turn's *only* evidence is the engine's — plus three
tests in `tests/integration/test_resume_rehydrates_from_the_store.py`:

* `test_the_parked_turn_never_retrieved_and_still_holds_evidence` — the premise: no `retrieval` span
  exists on the turn, and the engine did name committed chunk ids.
* `test_a_confirmed_engine_grounded_turn_is_not_refused_for_want_of_evidence` — resumes through the
  confirmation; `outcome == "answered"`, one `mock_writes` row, **every** G1 `guardrail` span on the
  turn has verdict `allow`, and the answer's citations are a subset of the engine's chunk ids.
* `test_the_resumed_synthesize_prompt_still_carries_the_engine_chunks` — §9.1's property for engine
  evidence: every engine chunk id appears in the resumed synthesize prompt's `llm_messages` rows.

**The tests fail without the fix.** With the one call disabled the flow reproduces the finding
verbatim:

```
$ LLM_PROVIDER=stub .venv/bin/pytest -q tests/integration/test_resume_rehydrates_from_the_store.py
>       assert resumed.outcome == "answered"
E       AssertionError: assert 'refused' == 'answered'
E         - answered
E         + refused
FAILED tests/integration/test_resume_rehydrates_from_the_store.py::test_a_confirmed_engine_grounded_turn_is_not_refused_for_want_of_evidence
FAILED tests/integration/test_resume_rehydrates_from_the_store.py::test_the_resumed_synthesize_prompt_still_carries_the_engine_chunks
2 failed, 8 passed in 4.94s
```

Restored, all ten pass. The four engine chunk ids `pto_request` resolves score 0.60–0.67 against the
fixture's question on the same dense path retrieval uses, so G1's untouched thresholds are what admit
them — the test is not passing on a widened rule.

## Finding 2 — the breadth reminder told a turn it had searched when it had not (Important)

**The call I made, and why.** The reviewer left the choice open: narrow the condition to
`searches == 1`, or keep `<= 1` and split the opening clause. I kept the approved firing condition
and split the clause. Reason: the condition is the behavioural half — it is what the sweep measures
and what the brief chose deliberately ("at most ONE corpus search"), and narrowing it would silence
the reminder on every zero-search turn, whose only remaining safety net is a G1 refusal plus §9.2's
recovery, and that recovery only exists for `rag_only` decisions. The verbatim text, by contrast, was
written for the one-search state and stays byte-identical there; only the opening clause moves, and
only into the state the brief did not consider.

**What changed.** `SEARCH_BREADTH` keeps the brief's approved text exactly. A second constant
`SEARCH_BREADTH_UNSEARCHED` opens `"Not yet — you have not searched the corpus yet."`. Everything
after the opening clause — the debt itself, which is the part the ledger's non-negotiables govern —
is one shared string `_BREADTH_DEBT`, so the two forms cannot drift. `_nudge` picks the form from the
count it already computed. Both forms remain deterministic for the same inputs, name no tool, no
document count and no `k`. The step summary already reported the real count and is unchanged.

**Covering tests** in `tests/unit/test_agent_nudge.py`:

* `test_a_turn_that_has_not_searched_at_all_is_not_told_that_it_has` — a zero-search turn is nudged,
  gets `SEARCH_BREADTH_UNSEARCHED`, and `"searched the corpus once"` is not in the message.
* `test_both_forms_of_the_breadth_reminder_state_the_same_debt` — the shared-tail invariant.
* `test_the_breadth_reminder_names_no_tool_and_no_document_count` now runs over **both** forms.
* `test_a_turn_that_searched_once_is_reminded_that_the_corpus_is_federated` is unchanged and still
  asserts the brief's verbatim constant, so the approved text is still pinned.
* `test_a_turn_that_stops_calling_tools_is_told_what_it_still_owes` (the end-to-end `nudge_probe`
  run, a zero-search turn) now asserts `SEARCH_BREADTH_UNSEARCHED` reached the model. No stub script
  moved: `nudge_probe` keeps its fourth act entry and the third reminder keeps its end-to-end
  coverage.

## Spec and CHANGELOG

* §9.1 "Three reminders" — `search_breadth` has two forms of one debt; the opening clause states the
  real count because a reminder whose job is to correct the model's picture of its own history may
  not misstate that history.
* §9.1 `resume_turn` — compliance-engine evidence is re-scored on the way back, because it has no
  `retrieval` span to rebuild it from, and without it the evidence gate would mean two different
  things on the two sides of the park.
* `CHANGELOG.md` — one "P13 review fixes (round 1)" entry above the P13 entry, both findings.

## Definition-of-done output (run at head)

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
221 files already formatted

$ LLM_PROVIDER=stub .venv/bin/pytest -q
........................................................................ [  4%]
   … 23 identical lines …
....................................................                     [100%]
1708 passed in 139.13s (0:02:19)

$ LLM_PROVIDER=stub .venv/bin/pytest -q tests/integration/test_resume_rehydrates_from_the_store.py \
    tests/unit/test_agent_nudge.py tests/unit/test_compliance_evidence_is_scored.py \
    tests/integration/test_confirm_resume_lifecycle.py tests/integration/test_fault_empty_retrieval.py \
    tests/e2e/test_demo_tasks.py
76 passed in 20.04s

$ .venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers

$ .venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  format    docs  chunks    words
  md          11     153    23276
  html         1      17     2515
  pdf          1      15     2425
  txt          1      19     2624
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
```

Output is pristine: no warnings, no skips, no xfails. `DEMO_EXPECTATIONS` unchanged and
`tests/e2e/test_demo_tasks.py` green.

## Files changed

* `src/hrmosaic/agent/orchestrator.py` — `_rehydrate`'s engine-evidence call; `_BREADTH_DEBT`,
  `SEARCH_BREADTH_UNSEARCHED` and `_nudge`'s form choice
* `tests/fixtures/llm_scripts/compliance_confirm_resume.json` (new)
* `tests/integration/test_resume_rehydrates_from_the_store.py` (+3)
* `tests/unit/test_agent_nudge.py` (+2, three updated)
* `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` — §9.1 ×2
* `CHANGELOG.md`

## Concerns

* **A resumed compliance turn now re-embeds its query once.** `_engine_evidence` on the resume path
  costs the same one embedding the live path costs, so a parked-then-confirmed compliance turn pays
  it twice across its two HTTP requests. The alternative — persisting the scored chunks to a span so
  rehydration could read them back — would have introduced a new span shape and a second way for the
  candidate set to be built, which is the thing the finding is about. Flagging the cost, not the
  choice.
* **The resumed turn writes an extra `guardrail` span** (`source: compliance_evidence`), because
  `_engine_evidence` runs G4 over the resolved text on both sides of the park. That is the correct
  audit record — the quarantine check really did run again — and no test asserts a fixed span count
  on a resumed turn, but a §11 reader will see two G4 spans for one compliance result.
* **Finding 2 is a judgement call that is still Sean's to overturn.** If the verbatim string matters
  more than the firing condition, the one-character alternative is still available: `searches == 1`
  in `_nudge`, drop `SEARCH_BREADTH_UNSEARCHED`, and `nudge_probe.json`'s fourth act entry comes back
  out along with two of the new tests.
* Unchanged from the first report: `nudge_rate` and latency rise by design, and the P13 sweep is
  still the only thing that can say what R3 and R7 do in combination on `remote-002`.
