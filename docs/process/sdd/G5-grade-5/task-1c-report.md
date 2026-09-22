# Task 1c report — a confirmed `draft_hr_email` is narrated, not refused

Commit **54a2895** on `main` (base `e353a3d`), 8 files, +210/-8, prefix `G5(agent):`. Nothing under
`.superpowers/` is committed.

## Diagnosis, from the trace, before any code changed

`GET /api/traces/turns/87992de4dc8a7844370b5ed49b9a555d` (deployed, README bearer, 200) records the
whole turn: `outcome refused`, `stop_reason refused`, `intent action`, `workflow pto_request`,
`resumed_count 1`, and `rollups` `{"tool_calls": 4, "retrievals": 0, "guardrail_hits": 1}`. Seventeen
spans. The resume side is four of them, in this order:

| seq | kind | name | what it says |
|---|---|---|---|
| 14 | `mcp_discovery` | mosaic-hr | the resumed turn re-discovers the catalog |
| 15 | `tool_call` | `draft_hr_email` | `is_error: false`, `{"status": "drafted", "draft_id": "MOCK-EMAIL-000018", "to_role": "manager", "to_name": "Dana Whitfield", …}` — **the write happened** |
| 16 | `guardrail` | `G1_evidence_gate` | `verdict: refuse`, `reason: "no policy evidence was retrieved for this question"`, `details: {"max_dense_score": 0.0, "supporting_chunks": 0, "candidates": 0, …}` |
| 17 | `guardrail` | `G6_pii_secret_redaction` | over the refusal that was then served |

So the refusal is **G1 at §9.1 step 3**, not the topic gate and not a missing "Done:" template.
`orchestrator._resume` re-issues the gated call, absorbs the result and hands the turn to `_answer`;
`_answer`'s step 3 was `verdict = g1.check(turn.citable(), turn=turn.buffer)` followed by
`if not verdict.passed: return self._refuse(turn, verdict.reason, …)`. The ask — *"Can you draft an
email to my manager Dana…"* — searches nothing (`retrievals: 0`; the router picked
`["check_pto_balance", "draft_hr_email"]` and the act loop called exactly those two, plus the
orchestrator's own profile-debt `lookup_employee_profile`), so `turn.citable()` is empty, the
`NO_EVIDENCE` clause fires at `candidates: 0`, and `refusal_text(NO_EVIDENCE)` is `USER_REFUSAL` —
*"I could not find anything in Mosaic's policy library that answers this…"*. The §9.2 one-step
recovery never ran because it is gated on `decision.rag_only`, and this turn is an `action` turn.
`create_mock_hr_ticket` escapes the same defect only by accident of its questions: a PTO ask retrieves
policy, so the gate passes and step 5e gets to speak. `PerformedWrite.statement` (`agent/outcome.py`)
has had a `draft_hr_email` branch all along; it was simply never reached. Two things were therefore
lost at once: the reader was told a search had come back empty on a turn that searched nothing, and
the refusal is the one answer shape that cannot carry the `MOCK-EMAIL-*` reference, so a real side
effect went unreported.

## The fix

The gate's rule is *"is there enough retrieved policy to ground an answer about policy"*; a turn
whose gated write has already been performed is grounded by that write.

* `src/hrmosaic/agent/guardrails/g1.py` — `evaluate()` and `check()` gain
  `grounded_by_write: bool = False`, and one new reason constant `PERFORMED_WRITE` (*"the write this
  turn performed is the evidence for the answer"*). When the flag is set and the evidence clauses
  would have refused, the verdict passes and the reason becomes
  `"{PERFORMED_WRITE}: {the measured clause}"` — e.g. *"…: no policy evidence was retrieved for this
  question"*. The clauses are still evaluated and `details` still carries `max_dense_score`,
  `supporting_chunks` and `candidates`, so the span says exactly what the retrieval was worth on a
  turn the retrieval did not decide.
* `src/hrmosaic/agent/orchestrator.py::_answer` step 3 — one extra line plus the comment:
  `performed = outcome_consistency.performed_write(turn.envelopes)` and
  `g1.check(…, grounded_by_write=performed is not None)`. Nothing else in the step moved: the
  `rag_only` recovery branch and the `_refuse` call are untouched, and they are unreachable with a
  performed write because the first verdict passes.

**Why not skip the gate on such a turn.** That was the first attempt and it regressed
`test_resume_rehydrates_from_the_store.py::test_a_confirmed_engine_grounded_turn_is_not_refused_for_want_of_evidence`,
which asserts the resumed turn carries a G1 span and that every one of them is `allow` — the pin on
the earlier `citable()`-across-the-park fix. Keeping `check()` as the single caller means every turn
still emits exactly one gate span, `guardrail_hits` is unchanged for turns that answer, and the
dashboard never shows a `refuse` verdict on an answered turn.

Nothing else was touched: no tool schema, no MCP server, no `route.j2`, no `web/`, no `evaluation/`.

The served answer, from the new test's own run:

```
Done — the email draft is ready for Dana Whitfield. Reference MOCK-EMAIL-000001.

The draft is addressed to Dana Whitfield and asks for the three days from 6 to 8 October 2026.

Next steps:
- Let me know if you would like the wording changed.
```

First block `performed`, second retyped `record` by step 5e's backstop.

## Tests

`tests/integration/test_draft_email_confirmed_is_narrated.py` (new, 4 tests) — the manager-message
ask to the card, `POST /chat/confirm`, then:

| test | asserts |
|---|---|
| `test_the_ask_reaches_a_draft_hr_email_card_and_writes_nothing` | `awaiting_confirmation`, card `action: draft_hr_email`, no token anywhere in the body |
| `test_the_confirmed_turn_is_answered_and_opens_with_the_draft_reference` | `outcome answered`, same `turn_id` reopened, first block starts *"Done — the email draft is ready"* and names both `MOCK-EMAIL-` and `Dana Whitfield` |
| `test_the_confirmed_turn_never_serves_a_refusal` | `g1.USER_REFUSAL`, `g1.OUT_OF_SCOPE_REFUSAL` and `g1.CONFIRMATION_REFUSAL` all absent, and not every `example_topics()` noun present (no refuse-and-redirect) |
| `test_the_evidence_gate_never_refuses_a_turn_whose_write_has_happened` | one `mock_writes` row, `kind hr_email`, id `MOCK-EMAIL-*`, in that turn; exactly one G1 span and its verdict is `allow`; its reason starts with `PERFORMED_WRITE` and still contains `NO_EVIDENCE`; `details.candidates == 0`; `turns.outcome == "answered"` |

`tests/fixtures/llm_scripts/draft_email_confirm.json` (new, 4 completions). The first three are the
**deployed turn's own**, copied from its `llm_call` spans: the router's
`selected_tools ["check_pto_balance","draft_hr_email"]` with its real `rationale_summary`, the act
step that reads the balance, and the act step that proposes the write with the exact `purpose`,
`key_points` and `tone` the live call carried. The fourth — the resumed turn's `synthesize` — is
**authored**, and the fixture's `_note` says so: the live turn was refused before it ever made one,
so there is nothing to record. No breadth-repair entry is needed; `_broaden` makes no call when
`citable()` is empty.

Verified as a regression test: with both source files stashed, **3 of the 4 fail** (the opener, the
refusal copy, and the G1 verdict); only the gated-card premise passes.

## Commands run

```
.venv/bin/pytest -q tests/integration/test_draft_email_confirmed_is_narrated.py          -> 4 passed
  (same file with the fix stashed                                                        -> 3 failed, 1 passed)
.venv/bin/pytest -q tests/integration/test_draft_email_confirmed_is_narrated.py \
    tests/integration/test_resume_rehydrates_from_the_store.py \
    tests/integration/test_confirm_resume_lifecycle.py tests/unit/test_g1_evidence_gate.py
                                                                                         -> 43 passed
.venv/bin/pytest -q tests/contract/test_docs_completeness.py tests/contract/test_chat_has_no_jargon.py
                                                                                         -> 56 passed
make lint                                                                                -> All checks passed! / 320 files already formatted
make test                                                                                -> 3106 passed, 299 deselected in 342.32s
```

`pytest --collect-only -q -m ""` reports **3,405** (was 3,401), so the four `NUMBER_DOCS`
(`README.md:50`, `ai-tooling.md:277`, `design-and-evaluation.md:801`,
`docs/requirements-traceability.md:146`) were bumped. Only the count is guarded; the stale "as of"
dates beside it (2026-09-15 in README, 2026-09-16 in two, 2026-09-21 in `ai-tooling.md`) were left
for the documentation task, as task 4's report already flags.

## Self-review of `git diff e353a3d..HEAD`

Two source files, both inside `src/hrmosaic/agent/`; one new test; one new fixture; four one-token
documentation edits. The new keyword defaults to `False`, so every other caller of `g1.evaluate` /
`g1.check` — there is exactly one production caller, and the unit suite — behaves identically. No
refusal copy changed, no `REFUSAL_COPY` key was added or removed, and `CONFIRMATION_REFUSAL` and the
two `CONFIRMATION_*` reasons task 1 added are untouched. `performed` is a single-use local kept for
the line length rather than inlined. The whole `make test` suite is green, which includes
`tests/contract` (545+), `test_action_safety.py`, the dashboard view-model tests that read guardrail
spans, and both demo-script tests.

## Concerns

1. **The decline path still has the defect.** `decline_turn` does not re-issue the write, so
   `performed_write` is `None` and the gate still refuses a cancelled "draft me an email" turn with
   *"I could not find anything in Mosaic's policy library that answers this"* — where the truthful
   answer is the `CANCELLED_NOTICE` lede and nothing else. Same for `turn.write_failed`, whose
   `WRITE_FAILED_NOTE` a refusal also swallows. Both are outside this brief (which scopes the
   confirmed write) and neither has a live trace behind it; each would be one more predicate on the
   same flag.
2. **No live confirmation.** Every test here replays a script. The fix is only observable on the
   deployed service after a redeploy and one more confirmed `draft_hr_email` turn; the trace cited
   above is still the refused one, and gap 21's *"honest wart"* paragraph in task 4's report stays
   true of that turn for ever. If the wave wants live evidence, the same ask has to be driven again
   against the new build.
3. **The synthesize completion in the fixture is authored, not recorded.** It cannot be otherwise —
   the live turn never reached synthesis — but it means the block wording the test's opener assertion
   sits beside is mine, not a model's. The assertions that matter (`Done — the email draft is ready`,
   `MOCK-EMAIL-`, the recipient) are all produced by `PerformedWrite.statement` from the **tool
   result**, not by the scripted block, so they do not depend on the authored text.
4. **No unit test for the `grounded_by_write` flag in isolation.** `tests/unit/test_g1_evidence_gate.py`
   is untouched; the flag is pinned end to end by the integration file, including the reason string
   and the preserved `candidates: 0`. A pure-rule test would be two lines if a reviewer wants the
   exemption pinned without a server.
5. **The eval numbers do not move.** No dataset item exercises `draft_hr_email` (every one lists it
   under `forbidden_tools`), so nothing in `evaluation/results/` changes and the published 0.893
   stands.

---

# Fix round 1 — the reviewer's Important 1 and three Minors

Commit **dcc5d9c** on `main` (base `54a2895`), 8 files, +134/-9. `make lint` clean; `make test` →
**3110 passed, 299 deselected in 343s**.

## Important 1 — a cancelled or failed write is answered by its receipt

The reviewer's path is exactly right, and confirmed by running the test before the fix: cancelling
the manager-message ask served *"I could not find anything in Mosaic's policy library that answers
this…"* and the reader was never told nothing had been created. `decline_turn` → `_answer` → step 3
`g1.check` (`citable()` empty, `rag_only` false, `performed_write` **None** — correctly, nothing was
written) → `_refuse`, and the `CANCELLED_NOTICE` / `WRITE_FAILED_NOTE` ledes live at step 5l, which a
refusal never reaches.

Fixed on the refusal side, as instructed; `grounded_by_write` was **not** widened.
`orchestrator._refuse` now builds the turn's receipts and, where there are any, they **replace** the
refusal's notice block:

```python
answer = g1.refusal(reason)
receipts = [
    *([WRITE_FAILED_RECEIPT] if turn.write_failed else []),
    *([turn.write_blocked] if turn.write_blocked else []),
    *([CANCELLED_NOTICE] if turn.declined else []),
]
if receipts:
    answer = answer.model_copy(update={"blocks": [AnswerBlock(type=NOTICE, text=t, citations=[]) for t in receipts]})
```

Four decisions inside those five lines, all disclosed:

1. **Replaced, not stacked.** The reviewer's own test spec asks for `USER_REFUSAL` **absent**, and it
   is the right call: a search that did not happen is not why the reader is looking at this answer,
   and the two sentences together are two accounts of one turn. The redirect `next_steps` are kept —
   they are the only other thing such a turn has to offer — and `rationale_summary` still carries the
   gate's own reason, so the record says why there was no answer to keep.
2. **Three branches, not two.** The reviewer named `declined` and `write_failed`; I added
   `write_blocked` in step 5l's order, because that is the exact set `_unsupported` exempts at
   `orchestrator.py:1837` (the comment the reviewer pointed at) and because a compliance-blocked
   write is the case where the swallowed sentence carries the most information — *why* the request
   was not filed. One extra line. Say so if it should come back out.
3. **A new constant, `WRITE_FAILED_RECEIPT`.** `WRITE_FAILED_NOTE` ends *"Here is what I established;
   try again or contact the owning team"* — a promise of an answer that, on this path, is not there.
   The new constant is that sentence minus the promise; the original is untouched and still used at
   step 5l.
4. **Outcome and `stop_reason` unchanged** (`refused` / `refused`). The reviewer scoped the copy, and
   re-labelling a cancelled turn `answered` here would move a §13.4 population. Noted as a concern.

## Minor 2 — the clause has unit tests

`tests/unit/test_g1_evidence_gate.py`, beside the existing clause tests:

* `test_a_performed_write_grounds_a_turn_the_evidence_clauses_would_refuse` — `evaluate([],
  grounded_by_write=True)` passes, reason is exactly `f"{PERFORMED_WRITE}: {NO_EVIDENCE}"`, and
  `(max_dense_score, supporting, candidates) == (0.0, 0, 0)`; the weak-evidence branch keeps
  *"evidence-gate score 0.58 < 0.60"* behind the exemption.
* `test_the_exemption_changes_nothing_when_it_is_not_set` — `evaluate([])` equals
  `evaluate([], grounded_by_write=False)`, and a passing candidate set is byte-identical with the
  flag set, so the exemption only ever rescues a verdict that failed.

## Minor 3 — the recovery re-check

The second `g1.check` at step 3 (the §9.2 one-step recovery) is now passed the same flag, **re-read**
from `turn.envelopes` rather than carried in the local, so the gate cannot mean one thing before the
recovery act step and another after it. It is the same `None` in practice — a gated call parks the
turn, so the recovery step cannot perform a write — and the comment says so.

## Minor 4 — the honest name

`test_the_ask_reaches_a_draft_hr_email_card_and_writes_nothing` →
`test_the_ask_reaches_a_draft_hr_email_card_with_no_token`, with a docstring pointing at what does
assert the writes-nothing half. The new cancelled test asserts zero `mock_writes` **both** while the
card is on the screen and after the decline, so this ask now has the property
`test_confirm_resume_lifecycle.py::test_nothing_is_written_while_a_turn_is_awaiting_confirmation`
gives the ticket.

## The two new integration tests

Both in `tests/integration/test_draft_email_confirmed_is_narrated.py`, on the same ask and the same
committed script (the cancel and write-failed paths reach no synthesis, so the script's fourth entry
simply goes unused — no new fixture was needed):

| test | asserts |
|---|---|
| `test_a_cancelled_draft_is_answered_by_its_receipt_and_not_by_an_evidence_refusal` | zero `mock_writes` while parked **and** after the decline; `CANCELLED_NOTICE` in the served answer; `USER_REFUSAL` and `OUT_OF_SCOPE_REFUSAL` absent; the redirect topics survive |
| `test_a_write_that_fails_after_the_confirmation_says_so_rather_than_refusing` | `WRITE_FAILED_RECEIPT` served, `USER_REFUSAL` absent, **no** `MOCK-EMAIL-*` named (none was allocated), zero `mock_writes` |

The write-failed variant **was** cheap: `monkeypatch.setattr(confirm_gate, "consume", explode)` — the
fault-injection `test_resume_rehydrates_from_the_store.py::write_failed_after_confirmation` already
uses, at the shipped gate's last step, over the real transport — so no stand-in for the thing under
test. Verified both fail with `orchestrator.py` stashed: the cancelled one fails on
*"the receipt is the answer"*, with the full `USER_REFUSAL` in the diff.

## Commands run

```
.venv/bin/pytest -q tests/integration/test_draft_email_confirmed_is_narrated.py tests/unit/test_g1_evidence_gate.py
                                                                          -> 19 passed
  (the two new integration tests with orchestrator.py stashed              -> 2 failed)
.venv/bin/pytest -q <the eight touched/related files>                      -> 68 passed
make lint                                                                  -> All checks passed! / 320 files already formatted
make test                                                                  -> 3110 passed, 299 deselected in 343.31s
```

`pytest --collect-only -q -m ""` = **3,409** (was 3,405); the same four documents were bumped.

## Concerns

1. **A cancelled turn still closes `refused` / `refused`** when it had no answer to keep, and a
   failed write closes `refused` rather than §9.4's `partial`. The copy is now right and the record
   is arguably not: §13.4's over-refusal population counts these, and the dashboard shows a
   *Refused* turn whose answer says *"Cancelled — nothing was created"*. Changing it means choosing a
   `TurnOutcome` for "the reader cancelled and there was nothing else to say", which is a wider call
   than the copy fix and was not in the brief.
2. **`write_blocked` went in on my judgement**, one line beyond the two the reviewer named. Same
   class, same mirror of `_unsupported`, and it is the branch whose swallowed sentence matters most —
   but it is scope I added rather than scope I was given.
3. **Still no live evidence.** Everything here replays a script; the deployed service needs a
   redeploy before any of the three endings can be shown on a real turn.

---

# Fix round 2 — the HTML surface

Commit **8a89310** on `main` (base `dcc5d9c`), 6 files. The re-review was right: fix round 1's
receipt made a second contradiction visible on the rendered page.

`src/hrmosaic/web/api.py::resolved_decision` suppressed `DECISION_LINES["confirmed"]` — *"You
approved this — it went ahead."* — only when a block equalled `g1.CONFIRMATION_REFUSAL`. A confirmed
turn whose write then failed closes with `WRITE_FAILED_RECEIPT` as its only block, so the fragment
rendered the approval line directly above *"…the action itself did not complete, so nothing was
created."* The same pairing has been shipping on §9.4's non-refused `partial` path with
`WRITE_FAILED_NOTE`, which this also fixes.

One tuple, in one place:

```python
NOTHING_WAS_CREATED: tuple[str, ...] = (
    g1.CONFIRMATION_REFUSAL,
    agent.WRITE_FAILED_NOTE,
    agent.WRITE_FAILED_RECEIPT,
)
...
return None if any(block.text in NOTHING_WAS_CREATED for block in response.answer_blocks) else decision
```

Equality against a whole block, never a substring of prose. The `response.outcome == "refused"`
condition is **gone**: the two write-failure paths close `refused` and `partial` respectively and are
the same fact on the page, so the predicate reads what the turn says instead of how it was labelled.
`NOTHING_WAS_CREATED` is exported in `__all__`. Nothing replaces the suppressed line — the receipt is
the whole account, and a second sentence saying it again is chat-production-ux-9's defect.

`tests/integration/test_draft_email_confirmed_is_narrated.py::test_a_failed_write_is_never_rendered_as_having_gone_ahead`
(+1 test) drives the ask to the card, injects the `confirm.consume` failure, POSTs `/chat/confirm`
with `HX-Request: true`, and asserts on the fragment: `DECISION_LINES["confirmed"]` absent,
`WRITE_FAILED_RECEIPT` present, `USER_REFUSAL` absent, zero `mock_writes`. With `api.py` stashed it
fails on *"nothing went ahead, so the page may not say so"*, quoting the rendered
`<p class="…resolved">You approved this — it went ahead.</p>`. The two tests that keep the line where
it is earned — `test_the_two_lines_a_resolved_card_can_still_carry` and the lifecycle's own rendered
Confirm — are untouched and pass.

```
.venv/bin/pytest -q tests/integration/test_draft_email_confirmed_is_narrated.py \
    tests/integration/test_confirm_resume_lifecycle.py        -> 22 passed
make lint                                                     -> All checks passed! / 320 files already formatted
.venv/bin/pytest -q tests/contract tests/integration          -> 723 passed in 289.27s
```

Suite size 3,409 → **3,410**, bumped in the same four documents.

**Concern.** `WRITE_FAILED_NOTE`'s membership in the tuple is the one branch with no test of its own:
it is the `partial` path (a ticket write that fails with policy evidence behind it), which no fixture
in this file reaches. It is asserted only by construction — same predicate, same equality test — and
the reviewer asked for it explicitly. Concern 1 of fix round 1 still stands: the copy is right on both
paths now, but a cancelled or failed no-retrieval turn still closes `refused`/`refused`.
