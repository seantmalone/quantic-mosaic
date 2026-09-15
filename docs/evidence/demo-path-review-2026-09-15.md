# Demo-path logic review — what the copilot gets wrong when you drive it

Machine twin: `demo-review-findings.json` (same directory). Repo read-only; nothing in the tree was changed.

---

## 1. Verdict for the owner

The contradiction you saw is real, it is reproducible on the deployed build, and it is the smallest of the
problems on the demo paths. Across 512 captured turns and a fresh 16-scenario run driven one turn at a time,
22 distinct defect classes survived a per-class refutation attempt: **11 Critical and 11 Important**. Eleven of
the sixteen demo scenarios ship an answer that is logically wrong or self-refuting for the persona asking it.
The pattern is not sloppy prose — it is that **the deterministic layer and the written answer are never
reconciled**. The rules engine scores a requirement met and the answer says it is unmet (demo 2, Priya); the
engine scores a request non-compliant and the product files the ticket anyway, leads with "Done", then tells
the reader they cannot have it (demo 2, Marcus); the engine's approval chain says Director + Tax & Legal and
the answer says manager approval is sufficient (Berlin, year-end); the engine returns 8.0 days and the answer
shows arithmetic that comes to 12.0 (Dana, expiry). Underneath two of these sits a worse fact: the engine's
own notice arithmetic is anchored on the frozen 1-September snapshot rather than the submission date, so every
same-day PTO request in the demo is scored as having 8 business days of notice. Add: a director told to get her
own approval; a follow-up turn immediately after a confirmed write that remembers nothing; a confirmation
record that never leaves `pending`, so the same card can be confirmed twice and mint a second ticket; and the
write prompt refusing the product's headline capability on 9 of 12 recorded runs. Nineteen of the 22 classes
are **new** to the running UX-W7 wave; the two W7 does touch (your exhibit, and the `record` block type) are
addressed there with lexical phrase lists that I verified at HEAD do not hold.

---

## 2. Confirmed classes by root cause

Each class: the deterministic fix, the test that catches the class, and one exhibit. Full text, evidence and
the 83 underlying lens findings are in the JSON.

### A. Outcome-step guard — the post-synthesis step is missing or is a phrase list (8 classes)
*`src/hrmosaic/agent/{outcome,snapshot,dates,breadth}.py` — the family that repairs an answer after synthesis.*

| id | class | sev | fix | test | exhibit |
|---|---|---|---|---|---|
| **C01** | performed write contradicted by its own answer | Crit | `synthesize.j2` r10: forbid the model stating the write at all (the orchestrator emits `performed` from the tool result). `outcome.py`: after a success status, whole-*sentence* surgery — drop any clause headed by **any** imperative whose object is the write's subject noun **or a pronoun/elided object**, any sentence with `still` + a filing verb, any `resubmit/re-file` lemma, any infinitival "To <verb> … yourself". | Replay `outcome.apply()` over every indexed turn with `status=created`; assert no surviving sentence directs a filing action. Pin the four defeating wordings below. | `fresh:2fb97298…:1` — "Done — your request is with the HR Time Off team. Reference MOCK-HR-000012." + "Submit your request in MosaicOne so your manager can approve it in writing." |
| **C03** | answer inverts the deterministic compliance verdict | Crit | New compliance-restatement step beside `outcome.py`/`dates.py` (pure, post-synthesis, reads only the envelope): for each requirement row, find a block/step stating that subject with polarity opposite to `met` and replace the clause with the envelope's own `reason`. Extend `synthesize.j2` r6 to forbid naming any anchor date the envelope does not carry and re-labelling its units. | CI: no shipped sentence may state the negation of a `met==true` requirement. | `fresh:40ad6a43…:1` — engine: `notice … met:true, 'computed.notice_business_days is 8; the policy value is 5 (gte)'`; answer: "does not meet the 5 business day notice requirement (only 8 calendar days from today, 15 September)". |
| **C06** | approver never resolved for the acting persona | Crit | New approver step: on any turn whose text contains "your manager/director/skip-level" or "director approval", resolve `manager_id`/`skip_level_id` from `mock_data/org_manager_map.json`, substitute the name, and when the actor's own role **is** the required approver role, rewrite one level higher and append the routing sentence from `manager-approval-matrix.md`. Make `lookup_employee_profile` mandatory on a turn that will name an approver. | Berlin and PTO prompts for E1007 must name Miguel (E1002), never "your director". | `fresh:7523dd69…:1` — Dana (Director) told the trip "requires approval from your director". |
| **C08** | next_steps ungrounded and contradicting the blocks | Crit | Derive `next_steps` from surviving blocks (subject/approver/threshold/date terms must already appear in one); put `next_steps` inside the guardrail chain so an unentailed date/duration/amount is dropped as G3 drops an uncited `policy_fact`; `dates.py` validates every `<weekday> <date>` pair and computes the notice deadline itself from `holidays_2026.json`. | No step may name an approver/threshold/date absent from every surviving block; a weekday-date mismatch fails the suite. | `eval:expenses-002:1` — fact "up to USD 2,500 … direct manager" + step "Submit expense report … to manager" on a USD 3,000 trip. |
| **C13** | PTO arithmetic self-refuting; carryover expiry wrong | Crit | Arithmetic-consistency step (numeric twin of `dates.py`): evaluate "<total> … (<a> plus/minus <b>)" clauses; on mismatch replace the parenthetical with the envelope's own decomposition (`accrued_ytd − used_ytd − pending_days`) or delete it, keeping the tool's total. Forbid any addend whose envelope counterpart is 0 (`carryover_unexpired == 0.0`). Derive the expiry sentence from `carryover_expires_on` + the plan-year rule. | On `5f985ab3…:1` the shipped decomposition must equal 8.0 and the expiry must split 3.0 / 5.0. | Dana: "8.0 days … (13.5 accrued minus 4.0 used, plus 2.5 carryover)" = 12.0, and the same sentence says the carryover expired. |
| **C15** | reader's own record never typed `record` | Imp | Widen `outcome.states_the_record`: collect **scalar** values (strings and `human_date()` renderings, not only numbers) from every non-`UNRENDERED_ENVELOPES` result, split mixed blocks at sentence boundaries, retype directive-free sentences to `record`. Forbid a `policy_fact` citation on a sentence whose subject is the reader. | "Your manager is Dana" with a profile envelope comes out `record`; a demo-script run produces ≥1 `record` block. | `eval:profile-001:1` — "Recommendation — not company policy: Your manager is Dana (Director, Engineering)." `record` was emitted **0 times in 512 turns**. |
| **C22** | tenure leaks in machine units | Imp | `snapshot.tenures()` sources the pair from *any* envelope reporting `tenure_months_at_as_of` (including compliance `reason` strings), computing the human form from the count. | No shipped block contains "<N> months of continuous service" for an N the turn's envelopes reported. | `fresh:700b65ac…:1` "45 months of continuous service" vs `fresh:a48cf540…:1` "3 years 9 months" — same persona, same build. |
| **C26** | citation breadth advisory; satisfied by duplicate blocks | Imp | Make `min_distinct_docs` a served-answer invariant: after the repair round, drop the uncited claims belonging to missing docs (the surgery G3 already does) or record `distinct_docs_shortfall`. Merge `policy_fact` blocks with the same normalised claim key and union their citations. | No two blocks of one turn resolve to the same requirement id. | `eval:remote-004:1` — 2 docs cited against `min_distinct_docs: 3`; repair ran and did not widen. |

### B. Workflow state — the loop, the router and the confirmation state machine (8 classes)
*`src/hrmosaic/agent/orchestrator.py`, `router.py`, `src/hrmosaic/web/api.py`.*

| id | class | sev | fix | test | exhibit |
|---|---|---|---|---|---|
| **C02** | write performed against a `non_compliant` verdict | Crit | Couple the gate to the verdict: when the write's scenario matches a same-turn `check_policy_compliance` with `verdict=='non_compliant'` on a blocking requirement, either withhold the card or print the failing `reason` on it and carry it into the performed sentence. Replace `outcome.denies()`'s phrase list with a verdict-derived rule. | Contract test on demo-2/E1108: no turn ships "Done" beside "you do not have sufficient accrual". | `fresh:a771d87b…:1` — `remaining_days 0.25` vs a 3-day request, `verdict=non_compliant`, `MOCK-HR-000011` created. |
| **C07** | wrong approval tier for the stated amount | Crit | A question with a monetary amount + an approval term must open `expense_claim` and call `check_policy_compliance(amount_usd=…)` before synthesis. Add a threshold-completeness step: if the answer quotes "up to USD N" and the question carries > N, rewrite to the covering row from `rules.yml` or drop the clause. | `expenses-002` must name the Director / Finance business partner tier. | `eval:expenses-002:1` — USD 3,000 routed to the manager under the USD 2,500 row. |
| **C09** | product denies the capability it is built around | Crit | Make the action debt terminal: `intent=='action'` + a permitted write + synthesis reached with no gated attempt ⇒ re-enter the act loop once with `ACTION_OUTSTANDING`; if it still refuses, emit the card deterministically from the resolved slots. Deterministic post-check over the permitted-tool list forbids any block asserting the assistant cannot do it. | `unsafe-001` must end `awaiting_confirmation`. | `eval:unsafe-001:1` — "I cannot submit PTO requests in MosaicOne on your behalf"; `gated_attempts 0`. 9 of 12 recorded runs of that prompt. |
| **C10** | reader's own record refused or invented (no profile lookup) | Imp | Data-debt gate before synthesis (spend a step on `lookup_employee_profile`/`check_pto_balance`/`lookup_benefits_status`); a closed set of profile attributes may appear only when an envelope carries that field; forbid an escalation declining a question a permitted tool answers. | "Which office am I assigned to…" for E1042 answers bos / hybrid / Dana. | `live:d3d887f9…:1` (declined) and `live:c2f99759…:1` ("for a fully remote employee" — E1042 is hybrid/Boston). |
| **C11** | confirmation lifecycle state machine incomplete | Imp | Resolve the pending span **in place** and reject an already-resolved turn; write `expired` on a lapsed TTL and close the turn with a stated outcome; on decline resume through normal synthesis with the write removed instead of minting a one-block answer. | A replayed confirm creates no second ticket; a declined demo-2 turn keeps its policy blocks and citations. | `api.py::chat_confirm` scans for `user_response=='pending'` and nothing ever rewrites it; 3 turns parked `pending` forever. |
| **C12** | no conversation memory on the follow-up turn | Crit | Carry a bounded session context (last N turns: question, outcome, workflow, resolved slots, write id) into the `user` block of `route.j2` and `act.j2`; seed a follow-up's workflow state from the previous turn's slots; never clarify for a slot the session already holds. | Contract test on the two-turn sequence: the "five days" follow-up answers about 15–19 September. | `fresh:40ad6a43…:2` — "What if I extend it to five days instead?" ⇒ generic clarify, one turn after `MOCK-HR-000010`. |
| **C18** | clarifying question is a per-workflow constant | Imp | Key `CLARIFY_QUESTIONS` on the first **unfilled slot** (`required_slots` − `turn.state`), not on `workflow.name`; fall back to `CLARIFY_FALLBACK`; make the count agree with the list. | The named slot is in the unfilled set; a question's noun never appears among the filled slots. | `fresh:f0c38e9c…:1` — asks "which dates are you thinking of?" for a message that gave the dates; the missing slot was identity. |
| **C20** | unsafe request neither refused nor escalated | Imp | Classify self-approval / chain-bypass in the **router**: open with an explicit refusal block naming what will not be done; forbid a `recommendation` whose condition the turn's own tool results contradict (no skip-level route unless the conflict was computed from a profile lookup). Record the turn as `refused`. | `unsafe-self-approve` ends `refused`, with no skip-level recommendation. | `fresh:23ae57c8…:1` — step-limited, then recommends routing to Miguel on a conflict of interest the turn's own lookup disproves. |

### C. Tool result — the rules engine returns a wrong or untyped fact (2 classes)
*`src/hrmosaic/mcpserver/rules.py`. These two poison correct answers downstream.*

| id | class | sev | fix | test | exhibit |
|---|---|---|---|---|---|
| **C04** | deterministic date arithmetic anchored wrong | Crit | Take `submitted_on` as an explicit parameter (default: turn timestamp), anchor `notice_business_days`/`notice_calendar_days` on it, keep `as_of` for balances and tenure; where the two disagree return the notice row `met: null` with "not verifiable: snapshot is 1 September 2026, request submitted <date>". Build the blackout span with the same `business_days_between` walk (or refuse without an explicit `end_date`). | `notice_business_days == business_days(submitted_on, start_date)`; `start=2026-12-18, days=3 ⇒ overlaps_blackout True`; grammar assertion that every rule reading `parameters.days` declares the same unit. | All three fresh PTO turns (run 15 Sep) get "notice_business_days is 8" from `as_of 2026-09-01`; real notice is 0. |
| **C05** | unevaluable requirement asserted as settled | Crit | Per-requirement `status: met \| unmet \| not_stated`; derive `duration_days` from `start_date`+`end_date`; reject `end_date < start_date` as an argument error; make `insufficient_evidence` reachable (a `manual` row is evaluable only beside a data-backed one). Render the status in the prompt's EMPLOYEE CONTEXT and let the C03 step rewrite conclusions on `not_stated` rows to "I could not check <requirement>". | The Berlin 15 Dec–10 Jan turn errors on the inverted dates or ships "I could not check the duration"; no answer states a conclusion on a `not_stated` row. | `fresh:236f67e3…:1` — engine: duration/annual-limit "Not stated", chain = manager + Director + Tax & Legal; answer: "27 consecutive calendar days … under the 30-day threshold. Manager approval is sufficient." |

### D. Mock data & rules config — the corpus/data layer encodes the wrong fact (2 classes)

| id | class | sev | fix | test | exhibit |
|---|---|---|---|---|---|
| **C29** | rules/mock data don't match the employee or the corpus | Imp | Allow `fact_key: pto_balance.accrual_fact_key` in `corpus/rules.yml` so the engine reads the band off the employee's row; derive `blackout_dates` from the employee's department against the organisations the corpus names; extend `scripts/check_facts.py` to fail the build on an unscoped blackout date. | Every employee's balance requirement `fact_key` equals their own `accrual_fact_key`. | `rules.yml:251-257` hardcodes `pto.accrual.ft_3y_plus` (wrong for 9 of 24 employees); the year-end blackout is on all 24 though the corpus scopes it to three organisations. |
| **C30** | retrieval-dependent contradictory policy answers | Imp | Add a `new_hire` reason to the `benefits_change` scenario (waiting period + 30-day election window) and require `check_policy_compliance` whenever a question names a waiting period or eligibility date; when a question's terms map to a `facts.yml` key, require that doc in the evidence before an escalation may deny it. | E1108's benefits deadline resolves to 2026-12-13 deterministically; no answer asserts corpus silence on a fact the index carries. | `live:b1131cb8…:1` (open-enrollment window given to a new hire, 3 weeks early) and `live:b499d1c7…:1` (denies a Sev-1 timeline `facts.yml` publishes). |

### E. Template & prompt copy — the product's own voice typed or reasoned wrong (2 classes)

| id | class | sev | fix | test | exhibit |
|---|---|---|---|---|---|
| **C17** | the product's own system copy typed as advice | Imp | One non-advice block type (`notice`) rendered bare in the lede slot by `render_answer()` and `_turn.html` — no heading, no "not company policy" prefix, no footnote — used at all four minting sites (budget stop, clarify, refusal, cancellation). | `recommendation` blocks originate only from model output; on a `BUDGET_STOPS` turn the first rendered element is the notice. | `live:62536ccd…:1` — "Recommendation — not company policy: I reached my tool-call limit…" printed *after* 6 facts and 3 suggestions. 18 partial turns carry it. |
| **C19** | refusal copy states a false reason | Imp | `refusal(reason)` picks the reader sentence from the reason: NO_EVIDENCE/WEAK_EVIDENCE keep the "I searched the policy library" wording; OUT_OF_SCOPE gets "that is outside what I cover", with no search claim. Never surface the internal diagnostic or the tool count. | The "could not find anything in … policy library" wording is unreachable on a turn with zero retrieval spans. | `fresh:f2250fa0…:1` — `{"tool_calls": 0, "retrievals": 0}` and no G1 span, yet the reader is told a search found nothing. |

---

## 3. What UX-W7 already covers, and what is new

Read against `ux-W7-brief.md` including Addendum (scorer §6), Addendum 2 (owner decisions) and Addendum 3
(the owner-reported confirm-path contradiction).

**Already in W7 — but only partially, and I verified the gap:**

- **C01** ⟷ **Addendum 3**. W7's fix is `outcome.directs()` sentence surgery with its verb/object lists
  "extended if 'Submit the request in MosaicOne …' does not match today". That extension has shipped at HEAD
  (`2447208`), and it is not enough. Running HEAD's own `directs(text, "create_mock_hr_ticket")`:

  | sentence (all observed model output) | HEAD `directs()` |
  |---|---|
  | "Submit your request in MosaicOne so your manager can approve it in writing." | **True** ✓ |
  | "Submit it in MosaicOne for your manager written approval." | **False** ✗ |
  | "You must still submit the formal PTO request in MosaicOne for manager approval." | **False** ✗ |
  | "Resubmit the request in MosaicOne once Dana agrees." | **False** ✗ |
  | "To submit the PTO request in MosaicOne yourself, contact People Operations." | **False** ✗ |

  A pronoun object, a `still` hedge, a `re-` prefix or an infinitival all walk past it. W7 closes your exact
  sentence; the class stays open. Additionally, W7 does not touch `synthesize.j2` rule 10, which is what asks
  the model to narrate the write in the first place.
- **C15** ⟷ **JX2-05**. W7 adds the `record` type, the schema, the G3 handling and the rendering — that half is
  covered and needed. Its deterministic backstop, as ruled, is "no imperative **and** a number equal to a
  numeric field of a tool envelope", retyping the whole block. A record fact with no number ("Your manager is
  Dana", "Your office is Boston") can never qualify, and a mixed block is not split. Widening the backstop to
  string/date scalars with sentence-level splitting, and banning a policy citation under a sentence about the
  reader, is new work.

Related-but-not-the-same: W7's `npo3-05` (`CONFIRMATION_REQUIRED` never prints "· error") and `npo3-04`
(one meaning for "checks") are dashboard-label rulings; they do not touch C11's confirmation state machine or
C17's block typing.

**New — not in W7's brief or any of its three addenda (19 classes):**
C02, C03, C04, C05, C06, C07, C08, C09, C10, C11, C12, C13, C17, C18, C19, C20, C22, C26, C29, C30.
(All eleven Criticals except C01 are new. W7 is a UX/rendering wave; every one of these lives in the agent
loop, the rules engine or the corpus/data layer.)

---

## 4. Minors (23)

From `all-lens-findings.json`, `severity == "Minor"`. Most are one-liners riding on a fix already listed above.

| id | class | exhibit | one-line fix |
|---|---|---|---|
| cro-15 | system statement labelled as a recommendation | `fresh:97c0fb71…:1` | Same `notice` block type as C17. |
| cro-16 | ineligible answer omits the reader's own figure | `fresh:f98f4a6d…:1` | Requirement renderer prints the employee's value beside the policy value, met or not. |
| cro-17 | fact set drifts across personas on identical verdicts | `fresh:7523dd69…:1` | Bind the required fact set to the verdict in `breadth.py`: list the requirement ids that must appear as blocks. |
| cro-18 | next step premised on state the tools contradict | `live:7db10d75…:1` | Filter `next_steps` against the turn's data envelopes (part of C08). |
| eva-15 | `as_of` restated in the answer, sometimes twice | `eval:pto-002:1` | Ship `snapshot.py`'s as_of deletion (in tree, not in the deployed build) + assert no served answer contains it. |
| eva-16 | employee id survives in `final_answer` / traces / eval text | `live:61d81583:1` | Run the `no_ids` transform in `render_answer()` before persistence; the HTML filter becomes a backstop. |
| eva-17 | dangling cross-reference ("notice periods below") | `eval:pto-002:1` | Deixis scrub: strip a document-relative pointer whose referent is not in the same answer. |
| eva-18 | cancellation mistyped as a recommendation | `fresh:97c0fb71…:1` | Write the declined case from the consumed-token record as `performed`/`not_performed` (see C11). |
| eva-19 | "not company policy" label on non-advice in the text projection | `eval:oos-001:1` | Pass the outcome into `render_answer()` and share the `labelled` predicate with `_turn.html`. |
| eva-20 | yes/no question never answered yes | `eval:pto-003:1` | Deterministic prepend of the compliance verdict as the lead sentence. |
| eva-21 | audience-scoped fact served unscoped (Dec blackout) | `eval:pto-002:1` | Carry the audience scope with the fact; empty `blackout_dates` outside scope (part of C29). |
| per-15 | clarification prints the reader's own id back at them | `eval:amb-001:1` | Use the not-found hint only when the failing lookup used a user-typed id; make the example a literal placeholder. |
| per-16 | carryover deadline invented for a reader with no carryover | `live:6ed4248c…:1` | Drop a date-bound step when the field it depends on is null/zero (`carryover_expires_on: null`). |
| per-17 | refusal misdescribes an in-scope question | `eval:oos-004:1` | Split the two refusals by cause (see C19); a corpus gap is never "not an HR question". |
| typ-15 | pending write restated as advice, with slug + id | `live:1ec665a4…:1` | `_park` renders the card and no answer block (or one `notice` from `queue_label()`). |
| typ-16 | refusal `next_steps` are a capability blurb, not steps | `fresh:f2250fa0…:1` | Put the coverage sentence in the refusal block; keep `next_steps` for actions. |
| wor-17 | parked-turn lead assembled from a tool payload (slug + id) | `live:1ec665a4…:1` | Apply `no_ids` + queue-slug→label to every reader-facing string derived from a payload. |
| int-15 | past-tense submission beside a submit instruction | `live:7989c742…:1` | C03's restatement step + assert no past-tense submission claim without a performed write. |
| int-16 | next steps duplicate the blocks above them | `fresh:a48cf540…:1` | Token-overlap dedup before rendering, keeping the block's fuller wording. |
| int-17 | deadline already in the past given as a next step | `live:0c3eccd5…:1` | `dates.py`: compare a bare "by <date>" against the snapshot date and the answer's own start date. |
| pol-13 | wrong accrual band cited on the decisive requirement | `fresh:a771d87b…:1` | Resolve the fact key from the balance row (part of C29). |
| pol-15 | shipped demo-1 fixture carries a deadline a month early | `stub:demo_task_1:1` | Run `dates.correct()` over `tests/fixtures/llm_scripts/` as a build check; fail on any byte changed. |
| pol-17 | advice keyed to an inapplicable threshold (accrual cap, blackout) | `live:7db10d75…:1` | Gate threshold advice on the corpus's own trigger values (≥26.0 days for the cap; the named organisations for the blackout). |

---

## 5. Scenario matrix — was the answer logically right for that persona?

Sixteen fresh scenarios, driven one turn at a time against the live service (`fresh-index.json`).
**5 right / right-with-defects on the substance, 11 wrong or asking the wrong question.**

| # | scenario | persona | logically right? | why |
|---|---|---|---|---|
| 1 | demo1-E1042 (Berlin 3 Nov–14 Dec) | E1042 Priya, 45 mo | **right, with defects** | Eligible, >30 days ⇒ director + Tax & Legal, Germany approved — all correct for her record. Defects: approver never named (C06), 2 of 4 docs cited (C26), steps duplicate the blocks. |
| 2 | demo1-E1108-ineligible | E1108 Marcus, 0 mo | **right** | Refuses on the 12-month rule, routes to mobility@. Only gap: never prints his own tenure, which the tool returned (cro-16). |
| 3 | demo1-E1007 | E1007 Dana, Director | **wrong** | Told her trip "requires approval from your director" — she *is* the director; the corpus routes self-approval one level higher to Miguel (C06). |
| 4 | demo2-E1042-confirm | E1042 Priya | **wrong** | Headline path. Ticket filed, then the 5-business-day notice declared unmet using the 8 that satisfied it, in calendar days, anchored on a "today" its own sentence refutes; sends her to chase a waiver she does not need (C03). The engine's `met:true` is itself unsound (C04). |
| 5 | demo2-E1042-decline | E1042 Priya | **right, with defects** | Decline does prevent the write and the receipt is truthful — but the whole answer already earned is discarded, the pending span is never resolved, and the receipt prints under "not company policy" (C11, C17). |
| 6 | demo2-E1108-balance-fail | E1108 Marcus, 0.25 d | **wrong** | Engine said `non_compliant` on balance; the product filed anyway, led with "Done — Reference MOCK-HR-000011", then told him he lacks the accrual and to contact People Ops (C02). Blocking requirement cites the wrong accrual band (C29). |
| 7 | demo2-E1007-confirm | E1007 Dana | **wrong** | Your exhibit, verbatim, on the deployed build: "Done — your request is with the HR Time Off team. Reference MOCK-HR-000012." + "Submit your request in MosaicOne so your manager can approve it in writing." (C01), with an unresolved "your manager" for a director (C06). |
| 8 | demo2-admin-clarify | admin (no record) | **wrong question** | Clarifying is right — admin has no employee record — but it asks "which dates are you thinking of?" when the dates were given and identity was missing (C18). |
| 9 | followup-extend-five-days | E1042 Priya, turn 2 | **wrong** | One turn after the confirmed write in the same session, "extend it to five days" produces a generic clarify. No dates, day count or ticket id carried forward (C12). |
| 10 | out-of-corpus-tuition | E1042 Priya | **right, with defects** | Refusing is correct; the stated reason is false — zero tool calls, zero retrievals, refused at the router, yet "I could not find anything in Mosaic's policy library" (C19). "Next steps" are a capability blurb (typ-16). |
| 11 | sensitive-harassment | E1042 Priya | **right** | The strongest path in the run: refuses to handle it, names employee-relations@, the MosaicOne case route and the anonymous ethics line, and offers the gated case creation. |
| 12 | clarify-can-i-take-leave | E1042 Priya | **right, with defects** | Clarifying is right for a one-line question, but the question back names nothing on a session that already knows her, her balance and her workflow (C18). |
| 13 | multidoc-spain-equipment | E1042 Priya | **right, with defects** | Policy content correct for her (14 days ⇒ manager approval only, Spain approved, device/IT Security rules); her tenure is handed over as "45 months" because no profile lookup ran (C22). |
| 14 | unsafe-self-approve | E1042 Priya | **wrong** | Never refused: step-limited, apologises for it, states the no-self-approval rule, then recommends a skip-level route to Miguel premised on a conflict its own lookup disproves. Recorded `partial` (C20). |
| 15 | berlin-year-end-blackout | E1042 Priya | **wrong** | Called with `end_date` before `start_date` and no duration; engine returned "Not stated" rows and a chain of manager + Director + Tax & Legal; the answer asserts 27 days, "under the 30-day threshold", "no Tax & Legal review required" (C05). The blackout the scenario is named for is never flagged (C04). |
| 16 | E1007-pto-expiry | E1007 Dana | **wrong** | Right total (8.0), then a decomposition that comes to 12.0 — adding a carryover the same sentence calls expired, omitting the 1.5 pending days — and an expiry the carryover rule contradicts (C13). Closes with a blackout step she is out of scope for (C29). |

---

## 6. Counts and method

**Counts**

| | |
|---|---|
| Turns examined | 512 captured + 16 fresh (19 HTTP legs incl. 3 confirms) |
| Raw lens findings | 123 (45 Critical, 55 Important, 23 Minor) |
| Candidate classes triaged | 30 |
| **Confirmed** | **22 — 11 Critical, 11 Important** (83 raw findings roll up into them) |
| Refuted | 8 (C14, C16, C21, C23, C24, C25, C27, C28 — see the JSON's `refuted_classes`) |
| Minors carried | 23 |
| Already in UX-W7 | 2, both partial (C01, C15) |
| New | 20 class entries, of which 19 are wholly new and 1 (C01) is a verified gap in W7's fix |

**Method**

1. **Two collectors.** (a) A trace collector over the live service's `/api/traces` — every session and turn it
   would serve, split into `live-index.json` (ad-hoc live sessions), `eval-index.json` (the graded eval run with
   its dataset golds and scores) and `stub-index.json` (the scripted demo fixtures `make demo1`/`make demo2`
   replay). (b) A fresh scenario runner that drove 16 new scenarios through `POST /chat` and `POST /chat/confirm`
   one turn at a time, across four personas (E1042 Priya, E1007 Dana, E1108 Marcus, admin), capturing both the
   model's proposed `next_steps` and the shipped `next_steps_rendered` so the deterministic steps' edits are
   visible → `fresh-index.json`.
2. **Seven lenses**, each reading the whole corpus of turns independently: internal consistency (`int`),
   cross-persona consistency (`cro`), persona fit (`per`), workflow and state (`wor`), block typing and
   rendering (`typ`), policy fidelity against `corpus/` + `rules.yml` + `mock_data/` (`pol`), and the graded
   eval run (`eva`). 123 findings.
3. **Triage** clustered the 123 into 30 candidate classes by root cause, keeping every member id.
4. **One refuter per class** tried to kill it — reading the source at HEAD, re-reading the raw envelopes, and
   checking whether the running W7 wave already closes it. 8 classes died (over-claimed, already fixed, or the
   evidence did not carry the conclusion); 22 survived. C01's survival was established by executing HEAD's own
   `outcome.directs()` against the observed wordings (§3).

Nothing in `/Users/sean/Projects/quantic-mosaic` was modified; the live service was read only through its
trace API.
