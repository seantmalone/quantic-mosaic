# Task 1b report — the clarification infers the workflow when the router names none

Branch `main`, one commit — **5b66ee6** (base c427b15), 10 files, +179/-10, prefix `G5(agent):`.
Closes the remaining half of gap **4** (clarification accuracy 0.667 on the shipped build).

## What changed

`src/hrmosaic/agent/orchestrator.py` — one new table, one new reader, one branch in the builder.

* **`CLARIFY_TOPIC_WORDS`** (new, beside `CLARIFY_INTENT_ORDER`): the brief's table verbatim —
  `remote_work_eligibility` ← ("remote work", "work from", "working from", "abroad", "another
  country", "another state"); `pto_request` ← ("time off", "pto", "leave", "vacation", "days off");
  `expense_claim` ← ("expense", "reimburse", "claim"). A tuple of pairs, not a dict, because the
  order is the order it is tested in: "work from" decides before "leave", so a remote-work question
  that mentions taking leave is still a remote-work question.
* **`clarify_topic_workflow(*texts)`** (new, beside `rationale_slot`, exported in `__all__`): lowers
  and joins the strings it is given and returns the first workflow name whose topic words appear, or
  `None`. Read as **data only** — the sole thing taken from either string is which of three closed
  workflow names it points at.
* **`_clarification_text`** (line ~2862): when the workflow order *and* the intent order are both
  empty, it now calls `clarify_topic_workflow(decision.rationale_summary, turn.request.message)`
  first; on a match it walks `unfilled_slots(inferred, known=…, has_record=…)` — the same `known`
  set and `has_record` test as the normal path, now hoisted to one local. The `rationale_slot`
  fallback is the `else` branch, unchanged, so it is exactly what is left when no topic matches.

Served text for amb-002 with the deployed run's own routing (`policy_qa`, `workflow: null`):

> Happy to check — where would you be working from? I will also need to know how long you would be
> there, and from when.

Before: *"Happy to check — where would you be working from?"* — the rationale named only
`destination_country`, so that was the whole question.

Nothing else was touched: no change to `route.j2`, `RouteDecision`, `router.py`, `CLARIFY_QUESTIONS`,
`CLARIFY_ALSO`, `CLARIFY_NEXT_STEPS`, `CLARIFY_CHIPS`, or anything outside `agent/orchestrator.py`.

## Tests

All four in the Task 1 dataset-driven file, `tests/unit/test_clarification_names_every_missing_slot.py`
(8 → 12 tests), plus three fixture scripts.

| test | what it pins |
|---|---|
| `test_amb_002_names_both_slots_when_the_router_names_no_workflow` | amb-002's question/persona read from `evaluation/dataset.yaml`, replayed through the deployed run's exact router JSON (`workflow: null`, the brief's rationale verbatim) — the answer names the destination **and** "how long you would be there, and from when", with one `?` |
| `test_an_expense_rationale_that_names_only_the_amount_still_names_the_amount` | an expense question, no workflow, a rationale naming only the amount → `CLARIFY_QUESTIONS["amount_usd"]` is served and the reader's own id is never asked for |
| `test_a_time_off_question_with_no_workflow_names_the_dates_and_the_day_count` | a `pto_request`-topic question whose rationale names **no** slot at all → "which dates are you thinking of" plus `CLARIFY_ALSO["days"]`, one `?` (it served `CLARIFY_FALLBACK` before) |
| `test_the_topic_table_only_ever_names_a_workflow_with_a_slot_order` (extra guard) | every `CLARIFY_TOPIC_WORDS` value is a `CLARIFY_SLOT_ORDER` key — a topic mapped to a workflow with no order would walk an empty order and serve the fallback again, silently — plus the four positive/negative lookups |

New fixtures: `tests/fixtures/llm_scripts/clarify_remote_no_workflow.json` (amb-002 as
`r_1790062696_baseline` recorded it), `clarify_expense_no_workflow.json`,
`clarify_pto_no_workflow.json`. One `route` completion each; nothing runs after a clarification.

`clarify_remote_missing_details.json`'s `_note` was corrected: Task 1 wrote it as "the published run
recorded", but the run recorded `workflow: null`. It now says it pins the path where the router
**does** name the workflow, and points at the new fixture for the run's actual shape. Only the note
string changed; the completion is byte-identical.

**Would-have-failed-before proof.** With `inferred` forced to `None` (the one-line neutering of the
new branch), the amb-002 test and the time-off test both fail — the latter on
`CLARIFY_FALLBACK`: *"could you tell me a little more about what you are after?"* The expense test
passes either way by construction, and says so in its docstring: the inferred order and the rationale
words agree on that turn, and the point of the test is that the inference does not lose what already
worked.

## Commands run

```
.venv/bin/pytest -q tests/unit/test_clarification_names_every_missing_slot.py   -> 12 passed in 5.90s
  (same file with `inferred = None`)                                            -> 2 failed, 10 passed
.venv/bin/pytest -q tests/contract/test_docs_completeness.py \
    tests/contract/test_chat_has_no_jargon.py tests/unit/test_session_context.py \
    tests/integration/test_fault_ambiguous.py                                   -> 85 passed in 17.31s
make lint                                                                       -> All checks passed! / 318 files already formatted
.venv/bin/pytest --collect-only -q -m ""                                        -> 3396 tests collected
make test                                                                       -> 3097 passed, 299 deselected in 338.28s
```

Suite size: 3,392 → **3,396** (4 new tests), so the four documents
`test_docs_completeness.py::test_every_document_that_states_the_suite_size_states_the_collected_one`
pins were bumped: README.md:50, ai-tooling.md:277, design-and-evaluation.md:801,
docs/requirements-traceability.md:146. The "as of" dates beside them were left alone (the disclosure
task's call, as in Task 1). A later task in this wave that adds tests bumps the same four again.

## Self-review of `git show 5b66ee6`

Four docs (one number each), one source file, one test file, three new fixtures, one fixture note.
Nothing in `web/`, `evaluation/`, `mcpserver/`, `rag/` or the prompts. The working tree's in-progress
measurement files (`evaluation/REPORT.md`, `evaluation/results/latest.json`, the untracked
`evaluation/results/r_1790062696_baseline.json`) were **not** staged — every path was added
explicitly and `git status` after the commit still shows all three unstaged/untracked.
`design-and-evaluation.md` had no uncommitted change of its own when I edited it, so the one line
committed is mine.

Scope check against the brief: table + one inference step (no new slot, no new question, no new
fragment, no third parallel dict), the rationale path kept as the fallback, no router prompt or
`RouteDecision` change, the dataset-driven test file reused.

## Assumptions

1. **Intent order still wins over the topic.** The inference runs only when `CLARIFY_SLOT_ORDER` and
   `CLARIFY_INTENT_ORDER` are both empty, so amb-003 (`employee_data`, no workflow) keeps Task 1's
   "which balance do you mean" question and the topic table cannot override it. That preserves every
   existing clarification and is why no other test moved.
2. **The fallback is keyed on "no topic matched", not on "no slot came back".** Per the brief's item
   2, the `rationale_slot` path is the `else` of a matched topic. If a topic matches but every one of
   its slots is already settled, the turn serves `CLARIFY_FALLBACK` rather than re-asking for
   something the session holds (see concern 2).
3. **Both strings are read, rationale first.** The brief says "the rationale and the user's
   question"; I join them in that order, which only matters when the two point at different
   workflows — then the rationale's words win only if they come earlier in the table, since the table
   order, not the string order, decides. Documented in the constant's comment.
4. **I wrote a fourth test.** The brief asked for three; the extra is the `CLARIFY_TOPIC_WORDS` ⊆
   `CLARIFY_SLOT_ORDER` invariant, which is the one way a future edit to the table could reintroduce
   the fallback-that-names-nothing without any test noticing. It is a pure assertion on two
   constants, and it is why the suite grew by 4 rather than 3.

## Concerns

1. **The user's question is now read for a routing-shaped decision.** It is read as data (three
   closed names, and the only effect is which of six closed questions is asked), but a reader who
   writes "expense" into a remote-work question can steer which clarification they are served. The
   blast radius is one question and one chip pair — no tool, no write, no policy — and the turn ends
   in `clarify` either way.
2. **A matched topic whose slots are all settled serves the fallback.** Before this change such a
   turn would have asked about whatever slot the rationale words named, even if the session already
   held it (which was C12's defect). I think the fallback is the honest answer there, but it is a
   behaviour change on a path no test exercises, because the router asking to clarify a turn whose
   slots are all known did not occur in the run.
3. **"leave" is a broad word.** It fires on "leave the country" and on "when do I leave", which would
   route a remote-work question to `pto_request` if no remote-work word appeared first. The words are
   the brief's, and the remote-work row is tested before it, so amb-002's own phrasing is safe; a
   question saying only "before I leave" is not.
4. **The eval numbers do not move until someone re-runs.** Clarification accuracy is still the
   published 0.667 on `r_1790062696_baseline`; no result file was touched. Whether the judge answers
   `named_missing_information: true` on the new text is the measurement run's verdict, not this
   task's — the deterministic half (the words the judge must read) is what the tests assert.
5. **`duration_days` still stands in for the start date.** Task 1's assumption 2 is unchanged: the
   dataset expects "the start and end dates" and the workflow has no `start_date` slot, so
   `CLARIFY_ALSO["duration_days"]` says "how long you would be there, and from when". No slot was
   invented here either.

---

# Fix round 1 — the reviewer's Important and Minor

Commit **e85305b** on `main`, base 5b66ee6, 7 files (+96/-11). Both items landed, each with a test
that fails without it.

## Important — the inference gate was wider than the brief

The branch was `if not slots and decision is not None`, which is the **pre-existing** gate for the
rationale-word path. It is true of two different situations, not one: a turn with no order to walk
(the gap-4b case), and a turn whose workflow the router *did* name and whose every slot the session
has already settled. On the second, the topic words — including the reader's own message — could pick
a different workflow's order: a `pto_request` follow-up saying "expense" was asked *"how much is the
claim for?"*, about a claim nobody made.

`src/hrmosaic/agent/orchestrator.py` — the inference now runs under
`if not slots and decision is not None and workflow is None:`, and the comment plus the
`_clarification_text` docstring say so: *"A named workflow is never second-guessed: the inference does
not run at all when the router named one, even if the session has settled every slot of it."*

## Minor — the rationale path is the fallback on an empty result, not only on no match

The `else` became a second `if not slots and decision is not None:`. A turn whose **inferred** order
the session has fully settled can still have a rationale naming a slot outside that order, and that
slot is still what is missing. The two fallbacks are now one block with one comment covering both
entry conditions.

Net logic: named workflow / intent order → its unfilled slots; else topic-inferred order → its
unfilled slots; and whatever is still empty falls to `rationale_slot`, exactly as before gap 4b.

## Tests added

Both drive the same new three-turn fixture,
`tests/fixtures/llm_scripts/clarify_after_the_session_settled_the_slots.json`: turn 1 is
`followup_extend.json`'s first turn verbatim (it settles `start_date` and `days`, which is the only
way to reach a clarification whose workflow is named and whose order is nonetheless empty), then two
clarification turns in the same session. A local `clarifications_after_a_settled_session` fixture runs
all three through one `Orchestrator` against the mounted server, the pattern
`tests/unit/test_followup_inherits_the_session.py` already uses.

| test | what it pins |
|---|---|
| `test_a_named_workflow_is_never_re_keyed_by_a_word_in_the_message` | turn routed `pto_request`, all its slots settled, message *"Would the hotel for those days count as an expense?"* → no amount question, no "how much", the fallback instead |
| `test_the_rationale_still_asks_for_a_slot_outside_the_inferred_order` | turn routed `workflow: null`, message *"Could I take more time off in December as well?"* (topic `pto_request`, settled) with a rationale naming the destination country → `CLARIFY_QUESTIONS["destination_country"]` is served, not the fallback |

Failure proofs: dropping `and workflow is None` fails the first test only; turning the second
`if not slots` back into an `elif` fails the second test only.

## Commands run

```
.venv/bin/pytest -q tests/unit/test_clarification_names_every_missing_slot.py   -> 14 passed in 7.63s
  (gate widened back to the old condition)                                     -> 1 failed (the named-workflow test), 13 passed
  (the fallback made an `elif` again)                                          -> 1 failed (the rationale test), 13 passed
make lint                                                                      -> All checks passed! / 318 files already formatted
.venv/bin/pytest --collect-only -q -m ""                                       -> 3398 tests collected
make test                                                                      -> 3099 passed, 299 deselected in 338.36s
```

Suite size 3,396 → **3,398** in the same four documents. Only my paths were staged; the measurement
run's `evaluation/REPORT.md`, `evaluation/results/latest.json` and untracked
`evaluation/results/r_1790062696_baseline.json` are still unstaged/untracked after the commit.

## Concerns

1. Concern 1 of the first round is narrower now: the reader's message can only influence a turn the
   router attached to **no** workflow, so a named workflow is unreachable from the message.
2. The new fixture's turn 1 duplicates `followup_extend.json`'s first five completions. Sharing them
   would need a script-include mechanism the stub does not have; a copy in a fixture is the cheaper
   of the two, but if `followup_extend.json`'s first turn is ever re-recorded this copy will not
   follow it.
