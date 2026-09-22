# Task 11b — unsafe-002's expectations, and a bare balance ask always clarifies

**Commit** `2bfb9b73a7c36a949e8ee284b459360fb51adbe2` — `G5b(agent-dataset): a bare balance ask always
clarifies, and a draft-me-an-email item expects no retrieval` · 8 files, +126 / −9 · branch `main`.

Files touched (all explicitly `git add`-ed, nothing else staged): `src/hrmosaic/agent/orchestrator.py`,
`evaluation/dataset.yaml`, `tests/unit/test_clarification_names_every_missing_slot.py`, `README.md`,
`ai-tooling.md`, `design-and-evaluation.md`, `docs/requirements-traceability.md`,
`docs/demo-script.md`.

---

## 1. `unsafe-002` — the expectations now describe the turn the item is for

`evaluation/dataset.yaml:604-612` (was `:597-601`; the item now spans `:583-615`). Three lines changed and a seven-line comment
added above them; **nothing else in the item moved**.

| field | before | after |
|---|---|---|
| `expected_docs` | `[pto-and-holidays]` | `[]` |
| `expected_tools` | `[lookup_employee_profile, search_policy_documents]` | `[lookup_employee_profile, check_pto_balance]` |
| `allowed_extra_tools` | `[check_pto_balance, check_policy_compliance, get_policy_section, list_policy_documents]` | `[search_policy_documents, check_policy_compliance, get_policy_section, list_policy_documents]` |

`check_pto_balance` moved from *allowed* to *expected* and `search_policy_documents` the other way, so
retrieval stays **permitted** (the gold still states the manager-approval and 5-business-day notice
rules, and the turn may well cite them) and is simply not **required**. `question`,
`gold_answer_short`, `workflow`, `gold_facts`, `forbidden_tools`, `expected_end_state`
(`awaiting_confirmation` / `draft_hr_email` / `requires_tool_results: [lookup_employee_profile]`),
`expected_behavior`, `requires_confirmation` and `confirm_on_prompt` are byte-identical.

Why: on the discarded round-2 drive (`r_1790106448`) the turn did the right thing — read the balance
and the profile, proposed the `draft_hr_email` card, wrote nothing — and scored **tool recall 0.5,
doc recall 0** for it. `expected_docs: []` takes the item out of the DocRecall mean rather than
scoring it 0 (`evaluation/deterministic.py:280` — an empty `expected_docs` is *omitted*, never 0 or 1),
which is the same treatment the five `out_of_scope` items and both `sensitive` items already get.

**No test needed editing for this.** `tests/unit/test_dataset.py`'s per-category assertions read
`expected_docs` / `expected_tools` only for `out_of_scope` (`:120-121`) and `sensitive` (`:137-138`),
and `test_every_answering_item_names_the_documents_it_expects` (`:183-186`) is scoped to
`expected_behavior == "answer"` — `unsafe-002` is `confirm`. The `unsafe_action` assertion
(`:141-153`) reads the end state, the behaviour, the confirmation flags and `forbidden_tools`, all
unchanged. `test_dataset.py` is green untouched (134 passed).

Dataset sha256 moves `642c578e0a52…` → **`2c8973147744a3513899f55107ab0f0db489d7d5f7463bcfde06c19ade2d5577`**.
Item count stays 30 and `reference_subset(load_dataset())` still returns the same eight ids
(`benefits-001, benefits-002, conduct-001, expenses-001, pto-001, remote-001, remote-002, remote-003`)
— checked before committing, because a re-sample would silently repoint `reference_labels.yaml`.

---

## 2. The bare-balance clarify rule

`src/hrmosaic/agent/orchestrator.py:413-459` — the tables and the predicate, placed with the other
message-reading tables, immediately after `clarify_topic_workflow` and before `clarify_slot_of`; the
wiring is `:1227`; the import of `find_employee_id` is `:76`; `__all__` gains `is_bare_balance_ask` at
`:3563`.

### The rule, in full

```python
if intent != "employee_data":
    return False
lowered = " ".join((message or "").lower().split())
asks = any(word in lowered for word in BALANCE_ASK_WORDS) or BALANCE_QUANTITY.search(lowered) is not None
if not asks or any(word in lowered for word in NAMED_BALANCE_WORDS):
    return False
return find_employee_id(message) is None
```

**The exact word lists** (`orchestrator.py:418-434`):

* `NAMED_BALANCE_WORDS` — 10 entries, in file order: `"pto"`, `"time off"`, `"time-off"`,
  `"vacation"`, `"leave"`, `"sick"`, `"benefit"`, `"401k"`, `"401(k)"`, `"expense"`.
  The brief's list verbatim, plus two spelling variants of entries it names (`time-off` for
  *time off*, `401(k)` for *401k*); `"benefit"` and `"expense"` are substrings, so *benefits* and
  *expenses* match without a second entry.
* `BALANCE_ASK_WORDS` — one entry: `"balance"` (it is a substring of *balances*, so no plural entry).
* `BALANCE_QUANTITY` — `re.compile(r"\bhow m(?:uch|any)\b[^?]*\b(?:left|remaining|remain)\b")`.
  The `[^?]*` keeps the quantity phrase inside one sentence.

Matching is substring-on-lowercased-and-whitespace-collapsed text, exactly as `RATIONALE_SLOT_WORDS`
and `CLARIFY_TOPIC_WORDS` already do it — the message is **data**, and the only things taken from it
are three booleans. The employee-id clause reuses `router.find_employee_id` (`\bE1[0-9]{3}\b`), so
there is one definition of "the reader typed an id" and not a second.

### The wiring (`orchestrator.py:1227`)

```python
if decision.needs_clarification or is_bare_balance_ask(req.message, intent=decision.intent):
```

A disjunct on the existing branch, not a mutation of `RouteDecision`, so a router that *does* say
`needs_clarification` behaves exactly as before and the path taken is the existing
`employee_data` one: `CLARIFY_INTENT_ORDER["employee_data"] = ("identity", "employee_data")`, whose
`identity` slot is dropped for a persona with a record, leaving `CLARIFY_QUESTIONS["employee_data"]`
— *"Happy to check — which balance do you mean: your time off, or something else on your record? If
it is not your own record, tell me whose."* No new question, chip set, next step or slot name was
added. It sits after the `sensitive`, `is_unsafe` and `out_of_scope` branches, so a sensitive or
unsafe turn is still escalated or refused first.

**It cannot override a turn that names its balance**: the named-balance clause is checked before the
function can return `True`, and the two balance questions already in the suite —
`"How many PTO days do I have?"` (`tests/unit/test_profile_debt_is_settled.py:49`) and
`"How much PTO do I have left, and how does it accrue?"` (`tests/integration/test_repair_round_trip.py:27`)
— both name `pto` and both still answer. The one bare balance ask elsewhere in the suite,
`"Can you look up the balance?"` (`tests/contract/test_record_blocks.py:121`), is driven by
`fault_ambiguous.json`, whose intent is `workflow`, so the rule does not fire there and the contract
test's behaviour is unchanged.

### Tests (3 added, in `tests/unit/test_clarification_names_every_missing_slot.py`)

* `test_a_bare_balance_ask_clarifies_even_when_the_router_did_not_say_so` (`:220`) — `amb-003`'s
  **exact** question and persona, read from `evaluation/dataset.yaml` by the file's existing
  `item()` helper, driven through `profile_debt.json`. That script is the deployed shape: intent
  `employee_data`, `workflow: null`, **`needs_clarification: false`** — and it carries the act and
  synthesize entries that answer, so a rule that failed to fire would end the turn `answered` and
  fail on the assertion rather than on an exhausted stub. Asserts `outcome == "clarify"`, *"which
  balance do you mean"* and *"your own record"* in the answer, and no `CLARIFY_FALLBACK`.
* `test_a_question_that_names_its_balance_is_never_forced_to_clarify` (`:238`) — the negative case
  the brief names, *"What is my PTO balance?"*, same script and same intent, asserts
  `outcome == "answered"`.
* `test_the_bare_balance_rule_reads_the_three_things_it_says_it_reads` (`:250`) — the predicate
  directly: fires on the bare ask and on both quantity phrasings; does not fire for
  `intent="policy_qa"` or `intent=None`, for a non-balance `employee_data` question, for
  *"How many days of notice do I need?"*, or for *"Can you check the balance for E1042?"*; and a
  loop asserts every one of the ten `NAMED_BALANCE_WORDS` disarms it (one collected test, not ten).

No existing test was edited. `NAMED_BALANCE_WORDS` and `is_bare_balance_ask` were added to the file's
existing import block.

---

## 3. The suite figure

`pytest --collect-only -q` now reports **3139/3438 tests collected (299 deselected)** — was
**3,136 / 3,435**, delta **+3**, exactly the three tests above and nothing parametrised. The pair was
bumped in all five documents the brief names, one occurrence each: `README.md:62`, `ai-tooling.md:279`,
`design-and-evaluation.md:838`, `docs/requirements-traceability.md:149`, `docs/demo-script.md:76`.
The "as of 2026-09-22" dates are today's and stayed. `tests/contract/test_docs_completeness.py`'s
`test_every_document_that_states_the_suite_size_states_the_collected_one` is green, as is
`…_the_browser_suite_size_…` (299 unchanged) and
`…_the_dataset_size_states_the_one_in_dataset_yaml` (30 unchanged).

---

## 4. Commands run, and their summary lines

One pytest process at a time throughout; nothing in parallel, no subagents.

| command | result |
|---|---|
| `make lint` | `All checks passed!` · `321 files already formatted` |
| `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_clarification_names_every_missing_slot.py tests/unit/test_dataset.py tests/unit/test_profile_debt_is_settled.py` | **159 passed in 11.75 s** |
| `.venv/bin/pytest --collect-only -q -p no:cacheprovider` | **3139/3438 tests collected (299 deselected) in 2.74 s** |
| `.venv/bin/pytest -q -p no:cacheprovider tests/unit tests/contract` | **2956 passed in 198.59 s** — no failures, no skips reported |

The broad run was green, which also closes the two failures task 11 left open: the docs dataset-size
guard (fixed by the interim docs commit `7ada32e`) and
`test_loopback_client_timeouts.py::test_the_ungated_client_is_none_so_the_sdk_builds_its_own` (the
gap-17 `client.py` is committed now, at `6e71e0f`).

`.venv/bin/ruff check --fix` and `.venv/bin/ruff format` were run on the one test file (import order
and one long line); `make lint` is the authority above.

---

## 5. Concerns

1. **The rule is a patch over router variance, and it is one-directional.** It can only *add* a
   clarification, never remove one, and it fires on one intent and one question shape — but it does
   mean an `employee_data` turn whose reader genuinely wanted "the balance" and would have accepted
   the PTO one now costs a round trip. That is the gold's own ruling for `amb-003`; if a later wave
   decides a bare balance ask should answer the PTO balance and say which one it picked, this rule is
   the thing to delete, and `amb-003`'s gold with it.
2. ~~**`"leave"` is the widest word in `NAMED_BALANCE_WORDS`**, and disarms the rule on *"Can you
   check the balance I have left?"*~~ — **withdrawn, the concern was inverted** (reviewer, fix round
   1): `"left"` does not contain `"leave"`, so that message names no balance and the predicate
   already returns `True` for it. There is now an assertion saying so
   (`tests/unit/test_clarification_names_every_missing_slot.py:263`). `"leave"` is still the widest
   entry — it would disarm the rule on a message that says *"leave"* incidentally — but no phrasing
   that does so has been found, and the brief specifies the bare word.
3. **`evaluation/results/chunk_size_comparison.json` is stale again**: it records
   `dataset_sha 642c578e…`, and the dataset is now `2c897314…`. Nothing asserts the two match (no
   test reads that field), and the sweep's conclusion — DocRecall flat at 0.9000 across 700 / 1,100 /
   1,600 chars — is unaffected by this edit in substance. But `unsafe-002` no longer has
   `expected_docs`, so a re-run's `n_questions` will drop from 20 to 19. Re-running
   `scripts/chunk_size_sweep.py` is ~2 min and zero LLM cost; it was outside this brief.
4. **The published run's `dataset_sha` moves again**, so `python -m evaluation.runner --judge <run_id>`
   still refuses to re-judge anything published (`evaluation/runner.py:2050`). Expected, and the
   round-2 drive was already discarded.
5. **Gold-side until the re-drive.** `unsafe-002`'s tool and doc recall will read 1.0 / omitted on the
   *next* sweep, not on any committed one, and `amb-003`'s clarification is deterministic now but
   unmeasured. Prose must not claim either as a measured result before the re-drive.
6. **Attribution.** The session's system instruction specifies
   `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`; the brief and the ledger's
   own task-7a ruling specify the wave's `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`
   (the trailer names the coordinating session). I committed the Opus trailer, then amended to the
   Fable one so the wave's documented rule stays true — which is exactly what the controller did for
   task 7a — and record here that **the implementing model was Claude Opus 5 (1M context)**. No
   `Claude-Session` trailer. Amended sha is the one at the top; the pre-amend sha
   `8003b1775c8ceb80c8c5bd3bb8b0916c059d002e` is unreferenced.


---

## 6. Fix round 1

**Commit** `80a5a71c02f27ae696137c2afdc27bfe39d1625b` — `G5b(agent): fix round 1 — a named FSA/HSA
balance is not bare, and the rule waits for the router to name no workflow` · 2 files,
`src/hrmosaic/agent/orchestrator.py` and `tests/unit/test_clarification_names_every_missing_slot.py`,
both explicitly `git add`-ed. Review verdict: approved, two one-liners, plus the withdrawn concern 2
above.

1. **`NAMED_BALANCE_WORDS` gains `"fsa"` and `"hsa"`** (`orchestrator.py:427-430`, with a
   three-line comment). The list is now **12** entries: `"pto"`, `"time off"`, `"time-off"`,
   `"vacation"`, `"leave"`, `"sick"`, `"benefit"`, `"401k"`, `"401(k)"`, `"expense"`,
   `"fsa"`, `"hsa"`. Those two balances are asked about by acronym and never by the word
   *benefit*, and E1042 holds an FSA, so *"How much is left in my FSA?"* was being sent back a
   clarification about a balance the reader had named.
2. **The rule fires only when the router named no workflow.** `is_bare_balance_ask` takes a required
   keyword `workflow: str | None` and returns `False` when it is not `None`
   (`orchestrator.py:443,460`); the call site passes `workflow=decision.workflow`
   (`orchestrator.py:1239-1241`). This is the rule `_clarification_text`'s topic inference already
   keeps (gap 4b, fix round 1) — a named workflow is the router's decision — and it also has to hold
   for the question to make sense: a bare ask attached to `pto_request` walks that workflow's slot
   order and is asked *"which dates are you thinking of?"*, while only an unattached turn reaches
   `CLARIFY_INTENT_ORDER["employee_data"]` and the *"which balance do you mean"* question. The
   end-to-end tests are unaffected — `profile_debt.json` routes `workflow: null`, which is the
   deployed shape.

**No collected test was added.** `test_the_bare_balance_rule_reads_the_three_things_it_says_it_reads`
became `…_the_four_things_…` and was extended in place (`:250-284`): every call passes `workflow`
explicitly; a loop over `CLARIFY_SLOT_ORDER` asserts all three named workflows disarm the rule; the
word loop now asserts **both** phrasings of every word (`"my <word> balance"` and `"How much is
left in my <word>?"`); `{"fsa", "hsa"} <= set(NAMED_BALANCE_WORDS)` is asserted by name; and
*"Can you check the balance I have left?"* is asserted **bare**, which is the withdrawn concern
turned into a guard.

| command | result |
|---|---|
| `make lint` | `All checks passed!` · `321 files already formatted` |
| `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_clarification_names_every_missing_slot.py` | **18 passed in 7.76 s** |
| `.venv/bin/pytest --collect-only -q -p no:cacheprovider` | **3139/3438 tests collected (299 deselected)** — unchanged, so the five documents need no further edit |

`grep -rn is_bare_balance_ask src tests` confirms the one production call site, so the required
keyword cannot silently default anywhere. The broad `tests/unit tests/contract` run was not repeated
for this round (the coordinator asked for the single file); the signature change reaches exactly one
call site and one test file, and both are green.

**One thing in the working tree that is not mine.** After the fix-round commit,
`evaluation/results/chunk_size_comparison.json` is **modified and unstaged**: someone re-ran
`scripts/chunk_size_sweep.py` at `2026-09-22T20:12:02Z`, which is concern 3 above being acted on. The
new artifact reads `dataset_sha 2c897314…` (matching `dataset.yaml`), `n_questions` 20 → **19** and
DocRecall 0.9000 → **0.8947** in all three windows, with `n_chunks` unchanged at 237 / 205 / 180 — so
the conclusion still holds (DocRecall flat across the three windows; 1,100 is chosen on chunk count
and build time). `unsafe-002` leaving the DocRecall population is exactly the predicted cause of the
n and mean change. I left it unstaged and uncommitted: it is not in my remit and my two commits used
explicit `git add`. Concern 3 is therefore addressed, pending whoever owns that file committing it.
