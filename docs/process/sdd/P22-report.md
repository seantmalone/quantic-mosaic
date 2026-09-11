# P22 report — a confirmed write is reported as done; the gated write is not painted as an error

Branch `main`, three commits on top of `3409522`:

| sha | subject |
|---|---|
| `6d6d935` | P22(agent): a confirmed write is reported as done, not denied |
| `b009da4` | P22(web): the gated write reads "Needs your confirmation", not as an error |
| `8a88b8d` | P22(tests): the health contract waits for the boot import instead of racing it |

HEAD `8a88b8da9f493b8e5e7637d932ce76363c05b710`. Nothing pushed. `.env` was never read, printed or
touched; no live LLM and no live URL was called (every run below is `LLM_PROVIDER=stub` against a
local server).

---

## 1. What was built

### Item 1 — the deterministic outcome block (`src/hrmosaic/agent/outcome.py`, new)

A post-synthesis step with a **name and no G-number**: `STEP_NAME = "outcome_consistency"`. It emits
no `guardrail` span, and none of §7.4's six rules changed (G3 in particular is untouched — it still
only relabels an uncited `policy_fact`).

* `performed_write(envelopes)` — the **last** write envelope of the turn carrying a success status,
  read from `WRITE_SUCCESS = {"create_mock_hr_ticket": "created", "draft_hr_email": "drafted"}`
  plus an id (`ticket_id` / `draft_id`). A body that will not parse, or has no id, is ignored rather
  than raised over: this step must never be why an answer fails to reach the reader.
* `apply(blocks, envelopes)` returns an `Outcome(blocks, stated, replaced)` and mutates nothing:
  1. the answer opens with a `recommendation` block (tool data, not company policy) built from the
     result — `"Done: HR ticket MOCK-HR-000002 was opened in queue hr-timeoff (priority normal) —
     this is a mock ticket, nothing was sent outside this app."` — skipped when any of the model's
     own blocks already contains that id;
  2. an `escalation` block that denies the performed action becomes a `recommendation` pointing at
     what was created.
* The denial check is `denies(text, tool_name)`: a phrase from `DENIALS` (`cannot`, `can't`,
  `unable to`, `did not`, …) **and** a word from `ACTION_WORDS[tool_name]` (ticket/request/open/
  file/submit/raise/create; email/draft/message/write/send/compose). The second half is what keeps
  G5's sensitive-topic escalation — "I will not handle a discrimination concern here, contact
  People Operations…" — out of the rewrite when the same turn also opened a case ticket.

Wired in `orchestrator.py::_answer` as step **5b**, after `g3.check(...)` and before
`AnswerSchema` validation, so the inserted and rewritten blocks are validated like any other. It is
imported as `outcome_consistency` because `_answer` already has a local `outcome: TurnOutcome`.

**Why a success status is proof of a human confirmation** (so no second check is needed): the token
is minted only inside `POST /chat/confirm` after a click, `confirm.consume()` spends it before the
row is appended, and `mock_writes.confirmation_token` is `NOT NULL REFERENCES` — the server cannot
return `created` / `drafted` without one (§8.6). This is stated in the module docstring.

### Item 2 — `synthesize.j2` rule 10

Added verbatim from the brief (wrapped in the file's existing 3-space continuation style, as rules
6b/7/8 are). The **synthesize system** golden was regenerated —
`tests/fixtures/prompts/synthesize.system.txt`, +3 lines and nothing else, trailing-newline
convention preserved — and `act.system.txt` / `act.user.txt` are byte-identical (the golden test
asserts all six).

### Item 3 — the rail label for a gated write

`web/narration.py`: `NEEDS_CONFIRMATION_LABEL = "Needs your confirmation"` for a closed `tool_call`
whose payload carries `error_code: "CONFIRMATION_REQUIRED"`, plus `tone_for(kind, status, detail)`
→ `OK` / `PENDING` / `ERROR`, the single mapping from a span to how the rail paints it. The gate is
the only special case; a genuine tool failure is still red, and the `step_started` line (whose
detail is the arguments, not a result) still reads "Preparing the ticket for your confirmation…".

`web/sse.py` adds `tone` to the `span` frame **beside** the untouched `status`; `chat.html` paints
from `tone` (falling back to `status` when a frame has none); `app.css` adds `.span-pending` in
`var(--warn)`, the amber already used by the confirm card and the `confirmation` span. **No
recorded status changed** — `client.py` still writes `status="error"` for the `isError` result, and
`test_sse.py` asserts that on the wire.

### Item 4 — tests

| Test | What it pins |
|---|---|
| `tests/unit/test_outcome_consistency.py` (13) | created → block first with id, queue and priority; drafted → its own sentence; already-stated → no duplicate; denial escalation → replaced, `replaced == [1]`; G5-style escalation → survives; `confirmation_required` → nothing; no write at all → nothing; unparseable body → ignored; last write wins; thin result → shorter sentence; success with no id → nothing; the step's name is not a G-number |
| `tests/e2e/test_demo_tasks.py` | `DemoExpectation.answer_states_the_write_id` (demo-2 only) → `check()` asserts the `mock_writes` id appears in `response["answer"]`; the demo-2 test now asserts the answer opens `"Done: HR ticket "`, carries no `escalation` block and no "cannot open PTO requests" |
| `tests/unit/test_narration.py` (+3) | the gated shape's label and `pending` tone; only the gate is special-cased (a real failure stays `error`); the pre-gate label is unchanged |
| `tests/integration/test_sse.py` (+1 assertion) | the real gated turn's `span` frame: `status: "error"`, `tone: "pending"`, `label: "Needs your confirmation"` |
| `scripts/demo_task_2.sh` | pulls `MOCK-HR-\d+` out of the confirmed `create_mock_hr_ticket` span's `result_preview` in the **confirm response**, fails with a message if the answer does not name it, and prints `-- the confirmed write is reported as done: <id> is named in the answer` |

One existing test had to move: `test_an_escalation_block_renders_its_own_badge` asserted the
`escalation` badge on demo 2's confirmed turn — which is exactly the block this phase replaces. It
now drives `sensitive.json` with the harassment prompt, where G5 escalates deterministically and an
escalation is the right answer permanently.

### Item 5 — docs

* Spec **§7.4**, immediately after "Confirmation for irreversible actions is **not** a guardrail":
  a paragraph naming the step `outcome_consistency`, what it does, why the escalation check is
  narrow, and the measured failure. Spec **§18.2**: the expected-outcome paragraph now says the
  resumed turn's answer opens with the ticket id and names the two tests that hold it there.
* `docs/demo-script.md`: ⑤ of the task-2 DEMO.6 checklist says the answer opens with the id and why
  that first line is deterministic; the safety beat adds what the rail line reads ("Needs your
  confirmation", amber, recorded status still `error`).
* `CHANGELOG.md`: one dated P22 entry covering all three commits.

### Item 6 — the CI health-test race

`tests/conftest.py::health_after_the_boot_import(client, *, eval_runs)` polls `GET /health` until
`trace_store.eval_runs_imported` equals the expected number, bounded at 30 s in 0.2 s steps, and
returns the last response. `test_health_reports_every_block_of_the_payload` uses it and keeps the
equality assertion unchanged, with a comment naming the race (`assert 1 == 12` on 753596e, the
lifespan's `_maintenance()` import of the twelve committed `evaluation/results/r_*.json` files,
~2× slower under the coverage tracer).

Other contract tests were checked for the same assumption:

```
$ grep -rn "eval_runs_imported\|trace_store\[" tests/ src/hrmosaic/web/api.py
tests/contract/test_health.py:44:    assert body["trace_store"]["eval_runs_imported"] == _committed_run_count()
src/hrmosaic/web/api.py:1251:            "eval_runs_imported": runs,
```

That is the only test asserting a `/health` store count, so no other test needed the wait. The
helper is in `tests/conftest.py` as the brief asks, ready for the next one.

---

## 2. TDD evidence

**Outcome step** — test first, watched it fail on the missing module, then implemented:

```
$ .venv/bin/pytest -q tests/unit/test_outcome_consistency.py
ImportError while importing test module '.../tests/unit/test_outcome_consistency.py'.
E   ImportError: cannot import name 'outcome' from 'hrmosaic.agent'
1 error in 0.97s

$ .venv/bin/pytest -q tests/unit/test_outcome_consistency.py      # after outcome.py
..........                                                               [100%]
10 passed in 0.85s
```

**Rail label** — the three narration cases were appended before `tone_for` existed:

```
$ .venv/bin/pytest -q tests/unit/test_narration.py
E       AttributeError: module 'hrmosaic.web.narration' has no attribute 'tone_for'
FAILED tests/unit/test_narration.py::test_the_gated_write_attempt_reads_as_pending_not_as_a_failure
FAILED tests/unit/test_narration.py::test_the_recorded_status_is_not_what_the_rail_paints_but_everything_else_still_is
2 failed, 17 passed in 0.63s

$ .venv/bin/pytest -q tests/unit/test_narration.py                # after narration.py
...................                                                      [100%]
19 passed in 0.53s
```

**The end-to-end behaviour was red before the fix and green after** — the demo-2 e2e test failed on
the old assertion the moment the step landed, which is the same failure the live run showed:

```
$ .venv/bin/pytest -q tests/e2e/test_demo_tasks.py
>       assert "escalation" in {block["type"] for block in body["answer_blocks"]}
E       AssertionError: assert 'escalation' in {'policy_fact', 'recommendation'}
1 failed, 4 passed in 4.29s        # the escalation was replaced, as designed

$ .venv/bin/pytest -q tests/e2e/test_demo_tasks.py                # after the new assertions
.....                                                                    [100%]
5 passed in 4.34s
```

---

## 3. Definition of done — real output

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
246 files already formatted
```

```
$ .venv/bin/pytest -q
........................................................................ [ 96%]
............................................................             [100%]
1932 passed in 167.37s (0:02:47)
```

(that run predates the last two tests added during self-review; the `make coverage` run below is the
final one, at 1,933.)

```
$ make coverage
.venv/bin/coverage run --branch --source=src/hrmosaic -m pytest -q
1933 passed in 196.05s (0:03:16)
.venv/bin/coverage xml
.venv/bin/coverage report --fail-under=90
Name                                                        Stmts   Miss Branch BrPart  Cover
---------------------------------------------------------------------------------------------
src/hrmosaic/agent/outcome.py                                  79      0     22      0   100%
src/hrmosaic/web/narration.py                                  48      2     18      0    97%
src/hrmosaic/web/sse.py                                       117      0     28      0   100%
-------------------------------------------------------------------------------------------
TOTAL                                                        7229    315   1458    166    94%
```

No `Coverage failure:` line, and the report step re-run alone confirms the gate:
`.venv/bin/coverage report --fail-under=90` → `TOTAL … 94%`, exit `0`. `narration.py`'s two
uncovered lines are the pre-existing `corpusread.get_document` exception branch (135–136), not new
code.

Item 6 under the CI conditions:

```
$ .venv/bin/coverage run --branch --source=src/hrmosaic -m pytest -q tests/contract/test_health.py
.......                                                                  [100%]
7 passed in 5.58s
```

```
$ .venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
CHECK_FACTS_EXIT=0

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
PII_EXIT=0

$ .venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  totals      14     204    30840
  index    data/index/hr_index.sqlite
OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
VERIFY_EXIT=0
```

```
$ make demo1   → DEMO1_EXIT=0   (7 tool calls, 5 retrievals, answer cited across 3 documents)
$ make demo2   → DEMO2_EXIT=0
```

`make demo2`, the part this phase is about (the answer as the script printed it):

```
-- outcome: answered

-- answer
Recommendation — not company policy: Done: HR ticket MOCK-HR-000019 was opened in queue hr-timeoff (priority normal) — this is a mock ticket, nothing was sent outside this app.

PTO requests must be submitted at least 5 business days in advance.
…
Recommendation — not company policy: The ticket already exists: MOCK-HR-000019 was opened in queue hr-timeoff on this turn after you confirmed it. There is nothing further for you to file.

Next steps:
- Log into MosaicOne and submit your PTO request for 15–17 September 2026.
…
-- the confirmed write is reported as done: MOCK-HR-000019 is named in the answer
```

The ESCALATION block the live run ended on ("I cannot open PTO requests in MosaicOne on your
behalf…") is gone, replaced by the pointer at the ticket; the answer opens with the id.

---

## 4. Files changed

New:

* `src/hrmosaic/agent/outcome.py`
* `tests/unit/test_outcome_consistency.py`

Changed:

* `src/hrmosaic/agent/orchestrator.py` (step 5b + the import)
* `src/hrmosaic/agent/prompts/synthesize.j2`, `tests/fixtures/prompts/synthesize.system.txt`
* `src/hrmosaic/web/narration.py`, `src/hrmosaic/web/sse.py`,
  `src/hrmosaic/web/static/app.css`, `src/hrmosaic/web/templates/chat.html`
* `tests/e2e/test_demo_tasks.py`, `tests/unit/test_narration.py`,
  `tests/integration/test_sse.py`, `tests/contract/test_chat_page_renders.py`,
  `tests/contract/test_health.py`, `tests/conftest.py`
* `scripts/demo_task_2.sh`
* `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` (§7.4, §18.2),
  `docs/demo-script.md`, `CHANGELOG.md`

`docs/optimization-log.md` was not touched. `git status` is clean at HEAD; nothing outside this list
was staged.

---

## 5. Self-review findings (and what I did about them)

1. **`Outcome.write` was dead weight.** The dataclass carried the `PerformedWrite` it had found and
   nothing read it. Removed; `apply()` keeps it as a local. `stated` and `replaced` stay because
   they are the unit tests' assertion surface, exactly as `g3.Outcome.relabelled` is.
2. **A defensive branch was uncovered.** `performed_write` skipped a success body with no id, and
   no test exercised it (`outcome.py` 98%). Added
   `test_a_success_status_with_no_id_is_not_a_write_to_report`; the module is now 100%.
3. **A stale constant.** Moving the escalation-badge test off demo 2 left `PTO_QUESTION` unused in
   `test_chat_page_renders.py`. Deleted.
4. **Golden byte convention.** My first regeneration added a trailing newline the file never had
   (the test `rstrip`s, so it would have passed silently). Rewritten without it; the diff is +3
   lines and nothing else.
5. **Formatting.** `ruff format --check` flagged one wrapped string in the new test file; ran
   `ruff format` on it.
6. **Import name collision.** `_answer` already binds a local `outcome: TurnOutcome`, so the module
   is imported as `outcome_consistency` rather than shadowing it.

---

## 6. Ambiguities resolved

1. **"listed in the spec beside the guardrails (§10)"** — §10 of this spec is the trace/audit data
   model; the guardrails are §7.4. I put the paragraph in **§7.4**, directly after the existing
   "Confirmation for irreversible actions is **not** a guardrail" paragraph, which is literally
   beside the guardrails and beside its closest sibling idea. Nothing was added to §10: the step
   writes no span, so it has nothing to declare in §10.2's payload union.
2. **Which escalations get replaced.** The brief's sentence qualifies it ("whose text claims
   inability to perform the very action the result shows was performed") and its parenthetical is
   blunter ("an escalation block in a turn with a performed write is replaced"). I implemented the
   qualified reading — denial phrase **plus** an action word for the performed tool — because the
   blunt one would rewrite G5's sensitive escalation and lose its People Operations contact on a
   turn that also opened a case ticket, which §7.4 row G5 requires to be there.
   `test_an_escalation_about_something_else_survives_the_write` pins that.
3. **Which write, when there are several.** The last success envelope of the turn. A turn can only
   resume through one confirmation today, so this is a tie-break that never fires in practice;
   "the most recent thing that happened" is the honest one to report.
4. **Email wording.** The brief gives the ticket sentence verbatim and nothing for `draft_hr_email`.
   I mirrored it: *"Done: HR email draft MOCK-EMAIL-000001 was prepared for <to_name> — this is a
   mock draft, nothing was sent outside this app."*
5. **"the final answer MUST begin with"** — the outcome block goes before *the model's* blocks. On a
   budget-stopped turn §9.4's "this answer is incomplete" note still precedes it, which is the
   existing contract for that note and the right order for a reader.
6. **The pointer text names no contact.** The escalation being replaced was wrong precisely because
   it sent the reader elsewhere, so the replacement talks only about the thing that exists. I did
   not import `g5.PEOPLE_OPS` into the new module.
7. **Commit scopes.** The brief names `P22(agent)` and `P22(web)`; item 6 is neither, so it is
   `P22(tests)`. `docs/demo-script.md` carries one sentence for each of the first two commits and is
   staged with the `web` one.

---

## 7. Concerns

1. **`next_steps` still contradicts the ticket.** demo 2's recorded answer ends with *"Log into
   MosaicOne and submit your PTO request for 15–17 September 2026"*, and `next_steps` is not a
   block — the brief scoped this step to blocks, so I left it alone rather than widening the
   deterministic rewrite. It is visible in the `make demo2` output above. Rule 10 aims the model at
   it, but nothing enforces it; if the main session wants it deterministic, the same
   `performed_write` result is already at hand in `_answer`.
2. **The denial word lists are heuristics.** They are deliberately small and documented, and the
   second half (an action word for the performed tool) is what keeps them from firing on unrelated
   escalations. A model that writes "I am not in a position to file this for you" would not be
   caught — the answer would then still open with the correct outcome block, so the failure mode is
   a redundant paragraph, not a false statement.
3. **The streamed provisional answer still shows the model's own blocks**, including a denial, for
   the second or so before `turn_completed` hard-replaces it. That is the existing W2-E contract
   (the step runs after synthesis, and the streamed blocks are pre-guardrail by design), but a
   viewer watching closely can see the escalation flash past on the resumed half of demo 2.
4. **`ingest --verify-manifest` aborted once at interpreter teardown** with
   `libc++abi: … recursive_mutex lock failed` (exit 134) **after** printing its `OK — byte-identical
   (204 chunks)` line, immediately following a full coverage run and two demo servers on this
   machine. Two subsequent runs exited 0. Nothing in this diff touches `rag/` or `embed.py`; I am
   recording it as an observed macOS teardown flake rather than a result.
5. **`make demo1` and `make demo2` share port 8000.** Running them back to back in one shell, the
   second saw the first server's socket still closing, `wait_for_health` reported "up after 0.0s"
   and the run failed with `curl: (7)`. Run separately (as the brief says) both are green. Not
   introduced here, but worth knowing before someone chains them in CI.
6. **The live re-test is still owed.** Everything above is the stub path; the main session re-runs
   demo 2 against the deployed instance after this ships, which is where the real model's rule-10
   behaviour (as opposed to the deterministic step's) will first be visible.

---

# P22 fix report — round 1: `next_steps` is covered by the outcome step

Review finding (Important): the phase's goal — a confirmed write is reported as done, never denied
— was enforced over `blocks` only. `next_steps` still came verbatim from `raw`, so the demo-2
answer stated *"The ticket already exists: MOCK-HR-000020 … There is nothing further for you to
file."* and then, one line further down, *"Log into MosaicOne and submit your PTO request for 15–17
September 2026."* That is the same contradiction the escalation rewrite exists to remove, on screen
for the DEMO.6 take. Disclosed as §7.1 above; now fixed.

One commit on top of `8a88b8d`:

| sha | subject |
|---|---|
| `572aece` | fix: P22(agent): a next step that asks for the write again is dropped |

## 1. What changed

### `src/hrmosaic/agent/outcome.py` — a third move, on the same evidence

`apply()` now takes the model's `next_steps` (keyword-only, defaulting to `()`) and returns the
survivors on `Outcome.next_steps`, with `Outcome.dropped` carrying the indexes it removed — the
assertion surface `stated` and `replaced` already give the other two moves. `changed` includes it.

The new predicate is `directs(text, tool_name)`, the **imperative twin of `denies`** and just as
narrow. A next step is a directive at the reader when, in one clause:

* the clause **opens** with an imperative verb for the performed tool — `IMPERATIVES`:
  `submit / file / open / raise / create / log` for `create_mock_hr_ticket`,
  `send / write / compose / draft / email` for `draft_hr_email` — after stripping politeness and
  modality (`please`, `make sure to`, `you need to`, …) one layer at a time; **and**
* that same clause names one of that tool's **own objects** — `ACTION_OBJECTS`: `ticket / request /
  case`, `email / draft / message / note`.

Clauses are split on `[,;:.!?]` and on `and / then / or / but / so`, which is what makes "Log into
MosaicOne **and** submit your PTO request …" resolve: the first clause has the verb and no object,
the second has both. A step that names the write id is kept whatever it says — it is talking about
the thing that exists, not asking for a second one.

Both halves are load-bearing, and one calibration came out of a red test rather than a guess:
`"pto"` was in `ACTION_OBJECTS` in the first draft, and
`test_an_imperative_about_something_else_survives_the_write` caught it dropping *"Open the PTO &
Holidays Policy and read section 4"* — a real instruction to the reader, about the topic rather
than the ticket. `"pto"` is now deliberately **not** an object, and the constant says why.

Everything else is untouched: nothing rewrites a step, the survivors keep their order and wording,
a turn with no performed write returns the model's list unchanged, and the step still emits no
`guardrail` span and carries no G-number.

### `src/hrmosaic/agent/orchestrator.py` — step 5b passes the steps through

`_answer` hands `raw["next_steps"]` to `outcome_consistency.apply(...)` instead of straight to
`AnswerSchema`, and the schema is built from `consistent.next_steps`. `performed_write` is computed
once inside the step, as before; the change is four lines and one comment saying why `next_steps`
belongs here — `render_answer` prints the blocks and the steps into the same answer, for the same
reader.

`synthesize.j2` was **not** touched: rule 10 is pinned verbatim by the brief and by
`tests/contract/test_prompt_golden.py`, and the deterministic step is what the finding asked for.
The goldens are byte-identical (`test_prompt_golden.py` green below).

### Tests

| Test | What it pins |
|---|---|
| `tests/unit/test_outcome_consistency.py::test_a_next_step_telling_the_reader_to_file_the_request_is_dropped` | the mirror of `…escalation_denying_the_performed_write_is_replaced…`, driven by demo 2's three recorded steps: step 0 goes, steps 1–2 stay, `dropped == [0]` |
| `…::test_a_next_step_that_is_not_aimed_at_the_reader_survives` | "Watch for your manager's approval", "Dana Whitfield approves request MOCK-HR-000123", "Your manager will receive the request" — object, no imperative |
| `…::test_a_next_step_that_names_the_ticket_survives_even_in_the_imperative` | "Open MOCK-HR-000002 in the mock-action log" — the id guard |
| `…::test_an_imperative_about_something_else_survives_the_write` | "Open the PTO & Holidays Policy and read section 4", "Please submit your expense report separately" — imperative, no object of this tool |
| `…::test_politeness_in_front_of_the_verb_does_not_hide_the_directive` | "Please submit …", "You need to file a ticket …", "Make sure to open a request …" → all three dropped |
| `…::test_a_next_step_telling_the_reader_to_write_the_email_is_dropped` | the `draft_hr_email` side |
| `…::test_next_steps_are_untouched_when_nothing_was_performed` | the gated `CONFIRMATION_REQUIRED` attempt and a read-only turn both leave the advice alone |
| `…::test_next_steps_default_to_nothing_when_the_caller_passes_none` | the blocks-only call the other 13 tests use stays legal |
| `…::test_directs_needs_both_halves_for_the_tool_that_performed_the_write` | the matrix, including a tool that performs no write |
| `tests/e2e/test_demo_tasks.py::test_demo_task_2_pto_request_through_confirm_to_write` | the demo-2 e2e assertion the finding asked for: no rendered next step says "submit your PTO request", "Log into MosaicOne" is nowhere in the answer, and the two steps about what happens to the ticket are still there |
| `scripts/demo_task_2.sh` | the same check in the demo the finding was raised against — it prints `-- and no next step asks for it again (2 step(s) kept)` and exits 1 with the offending steps otherwise |

The e2e file gained one helper, `_rendered_next_steps(answer)`, which reads the `- ` lines out of
`render_answer`'s "Next steps:" paragraph, i.e. the reader's view rather than an internal field.

### Docs

Spec **§7.4** (the outcome-consistency paragraph) gains a paragraph on the `next_steps` half and
why the check is narrow; spec **§18.2**'s expected-outcome sentence now names both assertions.
`docs/demo-script.md` ⑤ says the same step clears the next steps. `CHANGELOG.md`'s P22 entry gains
the fix-round sentence.

## 2. TDD evidence

Red first — the two new behaviours, before the code existed:

```
$ .venv/bin/pytest -q tests/unit/test_outcome_consistency.py
E   TypeError: apply() got an unexpected keyword argument 'next_steps'
```

…then the calibration failure that changed the word list (`"pto"` as an object):

```
$ .venv/bin/pytest -q tests/unit/test_outcome_consistency.py
>       assert result.next_steps == steps
E       AssertionError: assert ['Please subm...ance portal.'] == ['Open the PT...ance portal.']
E         At index 0 diff: 'Please submit your expense report separately in the finance portal.'
E           != 'Open the PTO & Holidays Policy and read section 4 before your manager replies.'
FAILED tests/unit/test_outcome_consistency.py::test_an_imperative_about_something_else_survives_the_write
1 failed, 21 passed in 0.98s

$ .venv/bin/pytest -q tests/unit/test_outcome_consistency.py      # "pto" removed from ACTION_OBJECTS
......................                                                   [100%]
22 passed in 0.94s
```

Tests covering the amended code:

```
$ .venv/bin/pytest -q tests/unit/test_outcome_consistency.py tests/e2e/test_demo_tasks.py \
    tests/unit/test_narration.py tests/integration/test_sse.py tests/unit/test_g5_sensitive.py \
    tests/unit/test_g1_evidence_gate.py
........................................................................ [ 77%]
.....................                                                    [100%]
93 passed in 13.10s
```

## 3. Definition of done — real output, after the fix

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
246 files already formatted

$ .venv/bin/pytest -q
1942 passed in 167.13s (0:02:47)
```

```
$ make coverage
.venv/bin/coverage run --branch --source=src/hrmosaic -m pytest -q
1942 passed in 192.23s (0:03:12)
.venv/bin/coverage xml
.venv/bin/coverage report --fail-under=90
Name                                                        Stmts   Miss Branch BrPart  Cover
---------------------------------------------------------------------------------------------
src/hrmosaic/agent/outcome.py                                 106      0     34      0   100%
-------------------------------------------------------------------------------------------
TOTAL                                                        7256    315   1470    166    94%
COVERAGE_EXIT=0
```

No `Coverage failure:` line; `outcome.py` is back at 100% (the one uncovered branch the new code
introduced — `directs` asked about a tool that performs no write — is now asserted rather than
left).

Item 6's command, unchanged by this fix:

```
$ .venv/bin/coverage run --branch --source=src/hrmosaic -m pytest -q tests/contract/test_health.py
.......                                                                  [100%]
7 passed in 5.58s
HEALTH_EXIT=0
```

```
$ .venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
CHECK_FACTS_EXIT=0

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
PII_EXIT=0

$ .venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  totals      14     204    30840
  index    data/index/hr_index.sqlite
OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
VERIFY_EXIT=0
```

`make demo1` and `make demo2`, run separately:

```
$ make demo1   → DEMO1_EXIT=0
-- usage: 5 model call(s), 7 tool call(s), 5 retrieval(s), 31985→1797 tokens in 420 ms

$ make demo2   → DEMO2_EXIT=0
```

**The answer the finding was about, as `make demo2` printed it after the fix:**

```
-- outcome: answered

-- answer
Recommendation — not company policy: Done: HR ticket MOCK-HR-000021 was opened in queue hr-timeoff (priority normal) — this is a mock ticket, nothing was sent outside this app.

PTO requests must be submitted at least 5 business days in advance.

Every PTO request requires written approval from the employee's direct manager in MosaicOne. Verbal agreement, a message in chat and an email thread are all insufficient on their own.

PTO requests of any length are approved by the employee's direct manager.

Recommendation — not company policy: You have 13.5 PTO days remaining as of 2026-09-01, so a 3-day request is covered by your balance. Your request for 15–17 September meets the 5-business-day notice requirement (8 business days from submission on 2026-09-10).

Recommendation — not company policy: The ticket already exists: MOCK-HR-000021 was opened in queue hr-timeoff on this turn after you confirmed it. There is nothing further for you to file.

Next steps:
- Your manager will receive the request and must approve it in writing within MosaicOne.
- Once approved, the three days will be deducted from your PTO balance.

-- the confirmed write is reported as done: MOCK-HR-000021 is named in the answer
-- and no next step asks for it again (2 step(s) kept)
```

"Log into MosaicOne and submit your PTO request for 15–17 September 2026" is gone; what remains
under "Next steps:" is what happens to the ticket that exists. The answer no longer tells the
reader both that the request was filed and that they must go file it.

## 4. Files changed in this round

* `src/hrmosaic/agent/outcome.py` (the third move, `directs`, `IMPERATIVES`, `ACTION_OBJECTS`,
  `_CLAUSE`, `_LEAD_IN`, `Outcome.next_steps` / `Outcome.dropped`)
* `src/hrmosaic/agent/orchestrator.py` (step 5b passes and takes back `next_steps`)
* `tests/unit/test_outcome_consistency.py` (+9 tests), `tests/e2e/test_demo_tasks.py`
* `scripts/demo_task_2.sh`
* `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` (§7.4, §18.2),
  `docs/demo-script.md`, `CHANGELOG.md`

`.env` was never read, printed or touched; nothing was pushed; only the files above were staged; no
live LLM and no live URL was called; no subagent was dispatched.

## 5. Concerns after this round

1. **The word lists are still heuristics**, as §7.2 above says of the denial lists. "Head over to
   MosaicOne and put the three days in yourself" has no verb from `IMPERATIVES` and would survive.
   The failure mode is unchanged and bounded: the answer still opens with the deterministic outcome
   block naming the ticket, so the reader is never told the write did not happen — at worst they
   are told something redundant afterwards. The alternative (a broader verb list) trades that for
   dropping real advice, which
   `test_an_imperative_about_something_else_survives_the_write` exists to prevent.
2. **`scripts/demo_task_2.sh` repeats the rule as a regex** rather than importing
   `agent/outcome.py`, because the script runs under `$PYTHON` (default `python3`) against an
   arbitrary `BASE_URL` and must not depend on the package being importable. The regex mirrors the
   clause-head shape; a comment in the script says so. If the two ever drift, the e2e test is the
   authority.
3. **Rule 10 of `synthesize.j2` says nothing about `next_steps`.** It is pinned verbatim by the
   brief and by the golden, so the model is still free to write a directive there and the
   deterministic step is the only thing removing it. That is the same division of labour as the
   blocks half, and it is now enforced on both.
4. **The live re-test is still owed** (§7.6 above is unchanged): everything here is the stub path.
