# Task 1 report — agent code: clarification, profile debt, refusal copy, router catalog

Branch `main`, one commit — **2557d0c** (base 98c893f), 18 files, +545/-43 — prefix `G5(agent):`. All five brief items implemented; no gap's fix was
deferred and nothing outside the five was touched except the four documents that pin the suite size
(a contract test forces that, see *Collateral* below).

## Gap 4a — `_clarification_text` names every missing slot

`src/hrmosaic/agent/orchestrator.py`

* `unfilled_slots(...)` (new) returns **every** still-empty slot in the order a person would be
  asked; `unfilled_slot(...)` is now `next(iter(unfilled_slots(...)), None)` so the existing callers
  and unit tests are untouched.
* `clarification_question(slots)` (new) builds the served text: the first slot asks the question,
  the rest are named after it as fragments from a new `CLARIFY_ALSO` dict —
  *"Happy to check — where would you be working from? I will also need to know how long you would be
  there, and from when."* One question mark, every slot named. (Two full questions in a row read as
  an interrogation, and `tests/integration/test_fault_ambiguous.py` asserts one `?`.)
* `CLARIFY_QUESTIONS` gains an **`employee_data`** key, with matching `CLARIFY_NEXT_STEPS`,
  `CLARIFY_CHIPS` and `CLARIFY_ALSO` entries (contract tests require those key sets to agree).
* `CLARIFY_INTENT_ORDER` (new) is what a turn with **no workflow** walks: `{"employee_data":
  ("identity", "employee_data")}`. That is amb-003's shape — the published run routed it
  `employee_data` with `workflow: null`, so there was no slot order at all and the turn served
  `CLARIFY_FALLBACK`, which names nothing. Keying on the intent is deterministic; the rationale-word
  path (W10, ruling 9) is still consulted *after* it, unchanged.
* `clarify_slot_of` now matches the **opening** question by prefix rather than by equality, because
  the stored text can name more than one slot and `web/api.py::_replayed_clarify_slot` recovers the
  chip key from it. None of the closed question set is a prefix of another.

Served text now, for the two failing items:

* amb-002 — *"Happy to check — where would you be working from? I will also need to know how long you
  would be there, and from when."*
* amb-003 — *"Happy to check — which balance do you mean: your time off, or something else on your
  record? If it is not your own record, tell me whose."*

Both name what the dataset's `clarification_expects` says is missing, which is the string the judge
is handed as MISSING INFORMATION (`evaluation/judges.py::CLARIFICATION_USER`), so
`named_missing_information` can be answered `true` from the text alone.

## Gap 11 — the profile debt keys on the recorded call arguments

* `src/hrmosaic/agent/workflows/__init__.py` — `LoopState` gains `arguments` (same shape as
  `results`, written beside it, so a failed call records neither) and `called_with(tool, key, value)`.
* `src/hrmosaic/agent/orchestrator.py` — `_absorb` passes `arguments=result.arguments`; the resume
  path (`_rehydrate`) passes the gated/recorded `tool_call` span's own `arguments`, so a resumed turn
  owes the same profile the live one did. `_profile_outstanding` is now
  `any(turn.state.called_with(name, "employee_id", actor) for name in PROFILE_FIRST_TOOLS)`.

Why it was dead: `ComplianceOutput` (`mcpserver/tools/check_policy_compliance.py`) declares no
`employee_id` and `_compliance` round-trips the body through it, so the old body test could never
match for `check_policy_compliance`. `employee_id` *is* a declared argument of the tool, so the
argument test is exact. The "somebody else's request" exclusion (W10 addendum, Minor) is preserved —
it is the same equality test, moved one field over.

## Gap 18 — nothing added

Per the brief, covered by gap 11: no extra reopen trigger, no change to `router.py`'s gate.

## Gap 19 — a refused confirmation is not reported as a failed policy search

`src/hrmosaic/agent/guardrails/g1.py` gains two reason constants — `CONFIRMATION_INVALID` ("the
confirmation could not be validated") and `CONFIRMATION_MISSING` ("there is no gated tool call on this
turn to confirm"), the two strings `_resume` already passed in — and one reader-facing
`CONFIRMATION_REFUSAL`, mapped from both in `REFUSAL_COPY`. `_resume` now refers to the constants
instead of repeating the literals. `refusal_text`'s docstring is corrected: the fallback is no longer
described as safe for every non-`OUT_OF_SCOPE` reason.

Copy: *"I could not act on that confirmation, so nothing was created or sent. A confirmation is good
for a few minutes and can only be used once — ask me again and I will put a fresh one in front of
you."*

## Gap 17 — the router is shown the catalog it selects from

* `src/hrmosaic/agent/prompts/route.j2` — a `CATALOG — the tools offered on this turn, and the only
  names selected_tools may carry: …` line in the **user** block, above `QUESTION:`, rendered only
  when `catalog_names` is non-empty. The `system` half is byte-identical, so the cached
  `tools → system` prefix does not move.
* `src/hrmosaic/agent/orchestrator.py::_route` passes `catalog_names=turn.catalog.names`
  (`turn.catalog` is set by `_discover` before routing).
* `tests/fixtures/prompts/route.user.txt` regenerated; `tests/contract/test_prompt_golden.py`'s
  route context now carries the nine committed tool names, read from `mcp/tools/*.schema.json` so the
  golden cannot drift from the server.
* `src/hrmosaic/agent/router.py` — the stale comment calling `selected_tools` "a field nothing
  consumes" is reconciled with `_requested_write`.

`selected_tools` is kept (not dropped from `RouteDecision`): the prompt golden cost was one
regenerated fixture, not disproportionate.

## Tests added

| file | what it pins |
|---|---|
| `tests/unit/test_clarification_names_every_missing_slot.py` (new, 7 tests) | amb-001/002/003 served text, read from `evaluation/dataset.yaml` (question, persona, `clarification_expects`); every unfilled slot named with one `?`; a session-settled slot is not re-asked; the no-order fallback; `CLARIFY_ALSO` covers the question key set |
| `tests/fixtures/llm_scripts/clarify_remote_missing_details.json`, `clarify_which_balance.json` (new) | amb-002's and amb-003's routing exactly as the published run recorded it (`policy_qa` + `remote_work_eligibility`; `employee_data` + no workflow) |
| `tests/unit/test_profile_debt_is_settled.py` (+2 tests) | the debt fires when the **only** profile-first tool is `check_policy_compliance` (one orchestrator-issued `lookup_employee_profile`, before synthesis, no extra act step); and does **not** fire when the verdict was scored for another employee |
| `tests/fixtures/llm_scripts/compliance_profile_debt.json` (new) | remote-003's shape: `policy_qa`-routed, compliance + two searches, no balance call, no profile call |
| `tests/integration/test_resume_rehydrates_from_the_store.py` (+2 tests) | both gap-19 branches: an unminted token, and a resumed turn with nothing to confirm — each shows `CONFIRMATION_REFUSAL` and never `USER_REFUSAL`, and nothing is written |
| `tests/contract/test_prompt_golden.py` (+2 tests) | the router's CATALOG line is in `user`, before the question, never in `system`; and the prompt still renders with an empty catalog |
| `tests/contract/test_chat_has_no_jargon.py` | `CLARIFY_ALSO` and `CONFIRMATION_REFUSAL` added to the P13 "the agent's own copy" list |

Two of the new tests are the "would have failed before" proof: the compliance-only profile debt
(dead by construction on the old body test) and the two confirmation branches (both returned the
policy-search refusal verbatim).

## Commands run

```
.venv/bin/pytest tests/contract/test_prompt_golden.py -q            -> 34 passed
.venv/bin/pytest tests/unit/test_profile_debt_is_settled.py -q      -> 7 passed
.venv/bin/pytest tests/unit/test_clarification_names_every_missing_slot.py -q -> 7 passed
.venv/bin/pytest tests/integration/test_resume_rehydrates_from_the_store.py -q -> 13 passed
.venv/bin/pytest tests/contract/test_chat_has_no_jargon.py -q       -> 8 passed
.venv/bin/pytest tests/contract/test_docs_completeness.py -q        -> 48 passed
make lint                                                           -> All checks passed! / 314 files already formatted
make test                                                           -> 3053 passed, 299 deselected in 324.90s
(re-run of the six touched files after a docstring rewrap: 117 passed)
```

## Collateral: the suite-size numbers

`tests/contract/test_docs_completeness.py::test_every_document_that_states_the_suite_size_states_the_collected_one`
pins `N tests` in README.md, ai-tooling.md, design-and-evaluation.md and
docs/requirements-traceability.md to what `pytest --collect-only -q -m ""` reports. The 13 new tests
took it from 3,339 to 3,352, so those four occurrences were updated. The "as of 2026-09-16" dates
beside them were left alone — that is the disclosure task's call, not this one's. **A later task in
this wave that adds tests will have to bump the same four numbers again.**

## Self-review of `git diff 98c893f..HEAD`

Five source files (`orchestrator.py`, `workflows/__init__.py`, `guardrails/g1.py`, `router.py`
comment, `prompts/route.j2`), eight test/fixture files, `route.user.txt`, and the four suite-size
numbers. No scope creep found: nothing in `web/`, `evaluation/`, `mcpserver/` or `rag/` was touched,
no `evaluation/results/*.json` was opened for writing, and each of the five brief items has at least
one test that would have failed before it. `unfilled_slot` is kept as a one-line wrapper so the three
existing call sites and `test_session_context.py` are unchanged.

## Assumptions

1. **amb-003's identity half.** The dataset expects *"which balance is meant and the employee id it
   belongs to"*, but the persona is E1042 and W10 ruling 9 forbids asking a signed-in reader for an
   id the app already knows (`test_fault_ambiguous.py` asserts `E1042` is not in the answer). The
   question therefore *names* the record it would be read against and offers the other branch — "If
   it is not your own record, tell me whose" — rather than asking for the reader's own id.
2. **amb-002's dates.** The dataset says "the start and end dates"; the workflow's tracked slots are
   `destination_country` and `duration_days` (`workflows/remote_work.py`), with no `start_date`. I did
   **not** invent a slot: `CLARIFY_ALSO["duration_days"]` is *"how long you would be there, and from
   when"*, which names the duration and the start without pretending to a slot the predicate does not
   have.
3. **`CLARIFY_INTENT_ORDER` over rationale words.** Gap 4's fix says "add an `employee_data` key so a
   balance/identity ambiguity gets its own question". I keyed it on the router **intent** rather than
   adding "balance" to `RATIONALE_SLOT_WORDS`: the intent is a closed enum the router already emits,
   whereas a rationale word would fire on any turn whose prose happens to say "balance".
4. The five-item scope was read as code + tests only. Gap 4's part (b) (disclosing 0.333 in README,
   design-and-evaluation.md and the optimization log) and gap 11's doc correction
   (design-and-evaluation.md:1043-1045 and limitation 3) belong to the wave's disclosure task and were
   left alone.

## Concerns

1. **The next step still names the first slot only.** A multi-slot clarification asks for everything
   in the question but its one `next_steps` line is still `CLARIFY_NEXT_STEPS[first_slot]` ("Reply
   with the destination and I will pick this up."). The docstring says *one* next step, and joining
   them would need a third parallel dict, so I left it. The judged text is the whole served answer,
   which does name everything in the question above it.
2. **The eval numbers are unchanged until someone re-runs.** Gap 4's repair only pays off on a new
   run; `evaluation/results/*.json` was not touched, and the published 0.333 is still the published
   figure. Gap 11 is in the same position for remote-003's tool recall and workflow completion.
3. **Gap 17's optional extras not done.** `tests/contract/test_chat_trace_projection.py` still unions
   `selected_tools` across all plan spans rather than asserting the router span alone, and
   design-and-evaluation.md:440's description of the span is unchanged (it is now accurate, since the
   field will be populated on real-model turns — but no test pins that against a real model).
4. **Real-model behaviour of the new CATALOG line is untested by construction.** Every test here
   replays a committed script, so what the line changes — a router that emits real tool names instead
   of category labels — can only be confirmed by a live run.

---

# Fix round 1 — the reviewer's Important and Minor

Commit **e4007f1** on `main`, base `b0261d6` (Task 2's dashboard/ablation commit), 7 files.

## Important — gap 19's contradiction on the rendered page

The reviewer was right: the orchestrator half of gap 19 was fixed and the *page* still contradicted
it. `chat_confirm` passed `decision=body.decision` — what the reader **clicked** — into
`_render_turn`, and `DECISION_LINES["confirmed"]` is a statement about the world, *"You approved this
— it went ahead."* On a Confirm whose token the gate then refuses, that line rendered directly above
the new *"I could not act on that confirmation, so nothing was created or sent."*

Fix, in `src/hrmosaic/web/api.py`:

* new `resolved_decision(decision, response)` beside `DECISION_LINES` — returns `None` when the
  resumed response is a refusal carrying `g1.CONFIRMATION_REFUSAL`, and the decision unchanged
  otherwise; exported in `__all__`;
* `chat_confirm`'s single render call now passes `decision=resolved_decision(body.decision, response)`.

Two things deliberately **not** changed:

1. **`_resolve_proposal(turn, "confirmed")` stays.** It is not what drives the line (the line came
   from `body.decision`), and the span is a true record of what the human said to the card — the same
   record the write-failed-after-confirmation branch keeps, and the one §13.4 action-safety clause 1
   reads as "an earlier `confirmation` span in the same turn". Rewriting it to something else would
   make the trace say the reader never confirmed, which is false.
2. **Nothing replaces the suppressed line.** The turn's own refusal copy is the whole account of what
   happened; a second sentence saying it again is chat-production-ux-9's defect.

The replay path (`_rehydrate` → `_turn_context`) already passes no `decision`, so a reloaded
transcript of that turn never carried the line and needs no change.

*Scope note:* this is the one edit outside `src/hrmosaic/agent/` in the task, made on the reviewer's
explicit instruction.

## Minor — the `startswith` invariant is pinned

`test_no_question_is_a_prefix_of_another` (in
`tests/unit/test_clarification_names_every_missing_slot.py`, beside the fragment-coverage test):
asserts no `CLARIFY_QUESTIONS` value starts with another, and that `clarify_slot_of` still recovers
each slot from that question **with a fragment appended** — the shape the replay path now sees.

## Tests added

| test | file |
|---|---|
| `test_a_confirm_the_gate_refuses_is_never_rendered_as_having_gone_ahead` | `tests/integration/test_confirm_resume_lifecycle.py` |
| `test_the_two_lines_a_resolved_card_can_still_carry` | same |
| `test_no_question_is_a_prefix_of_another` | `tests/unit/test_clarification_names_every_missing_slot.py` |

The first asserts on the **rendered** htmx fragment from `POST /chat/confirm` (`HX-Request: true`),
not on the orchestrator response: `DECISION_LINES["confirmed"]` absent, `CONFIRMATION_REFUSAL`
present, `USER_REFUSAL` absent, zero `mock_writes` rows, and the turn closed `refused`/`refused`. The
gate rejection is produced by the **shipped** gate — `confirm.mint` is wrapped so the token it issues
is spent immediately, which is the double-click race `validate`'s "token already used" check exists
for — rather than by a stand-in for the thing under test. Verified it fails without the fix: with
`decision=body.decision` restored, it fails at the "nothing went ahead" assertion.

The second uses the lifecycle fixture's real declined and confirmed turns, so the suppression cannot
swallow either line it should keep.

## Commands run

```
.venv/bin/pytest -q tests/integration/test_confirm_resume_lifecycle.py   -> 15 passed
.venv/bin/pytest -q tests/unit/test_clarification_names_every_missing_slot.py -> 8 passed
.venv/bin/pytest -q tests/integration/test_confirm_resume_lifecycle.py \
    tests/integration/test_resume_rehydrates_from_the_store.py \
    tests/unit/test_clarification_names_every_missing_slot.py \
    tests/unit/test_profile_debt_is_settled.py                           -> 43 passed
make lint                                                                -> All checks passed! / 315 files already formatted
.venv/bin/pytest -q tests/contract                                       -> 545 passed in 173.96s
.venv/bin/pytest -q tests/unit tests/integration tests/e2e tests/architecture -> 2526 passed in 159.60s
```

Suite size: 3 new tests took the collected count from Task 2's 3,367 to **3,370**, so the same four
documents (README.md, ai-tooling.md, design-and-evaluation.md, docs/requirements-traceability.md)
were bumped again. `test_docs_completeness.py` — 48 passed.

## Concerns

1. **The CONFIRMATION_MISSING branch is not reachable through the endpoint**, so the rendered test
   covers the INVALID branch only: `chat_confirm` returns 409 `NO_GATED_CALL` before `_resume` when
   there is no gated span. The MISSING branch keeps its orchestrator-level test from the first round.
   Both branches share one copy string and one suppression predicate, so the rendered assertion holds
   for either.
2. The suppression is keyed on the block text equalling `g1.CONFIRMATION_REFUSAL`. That is exact
   today (the refusal is built from `REFUSAL_COPY`), but it is a string comparison across a module
   boundary; a future refusal that prefixes or reformats that copy would silently stop matching. The
   alternative — a new field on `ChatResponse` — is a schema change the brief did not ask for.
