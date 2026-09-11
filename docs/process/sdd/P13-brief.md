# P13 brief — prompt and orchestration hardening for Haiku (approved by Sean, 2026-09-10)

## Where this fits
The judged local baseline (`r_1789032950_baseline`) and the deployed baseline (`r_1789055103_baseline`)
fail the same eight dataset items for the same causes. A trace-level analysis of those failures
produced seven changes; Sean approved all seven. This wave implements them with tests. The main
session re-runs the deployed sweep afterwards — you never call a live LLM or the live URL.

Read first: spec §8 (act loop, reminders, budgets), §8.4 (tools and grammar), §9 (prompts),
§10 (guardrails G1–G6), §13.4/§13.9 (metrics, ablation). The spec is authoritative; where this
brief adds a mechanism the spec does not have, amend the spec section in the same commit (a few
sentences each — no new tables, no new subsections unless one is unavoidable).

## Non-negotiables (from the ledger)
- Reminders and recovery messages name the **debt**, never a tool. Nothing you add may name a tool
  that `act.j2` does not already name in its constant text, and nothing may say how many documents
  to cite. (`workflows/__init__.py` explains why: ToolSelection would otherwise score the prompt.)
- Guardrail rules and thresholds do not move. G1's candidate set may widen (R7); its rule may not.
- Every prompt template stays deterministic (byte-stable across renders for the same inputs).
- No few-shot tool-sequence exemplars anywhere. No `k` guidance (the harness overrides `k`).

## The seven changes

### R1 — `route.j2`: name the corpus (fixes `equipment-001`, the router's out_of_scope guess)
Insert a `CORPUS` paragraph into the router system block, after the line that defines
`out_of_scope`. Content: "the policy library covers, and only covers:" followed by the exact titles
of the 14 indexed documents, then: "Set out_of_scope only when the turn is about none of these and
is not the employee's own HR data. Device refresh cycles, asset return, spend limits and approval
thresholds are IN the corpus." The titles must be generated from the committed index manifest /
the same source `list_policy_documents` reads (never hand-typed), and a test must assert the
rendered prompt's list equals the manifest's titles, so the two cannot drift. The "and only covers"
clause is load-bearing: it keeps `oos-001..003` refused (MissedRefusalRate 0.000) — leave it.

### R2 — `synthesize.j2`: tool-result values carry no citation (fixes `pto-002`'s G2 drop)
Add rule 6b directly after rule 6 (verbatim):
`6b. A balance, accrual, date or eligibility value that came from a <tool_result ...> envelope is
employee data, not company policy. State it with its as_of, and attach NO citation: a tool result
has no chunk_id, and a citation to one is stripped — which drops the whole block and loses the
number.`

### R3 — a breadth reminder in `_nudge` (targets `remote-002` / `expenses-002`: 2 docs vs 3 required)
A third reminder, `search_breadth`, in `orchestrator._nudge`, recorded in `turn.nudges` like the
other two and sent at most once per turn. It fires only when: neither `workflow_incomplete` nor
`action_outstanding` fired at this step; `search_policy_documents` is in the permitted set and
tools are not disabled; and the turn has made at most ONE corpus search so far. Text (verbatim):
`Not yet — you have searched the corpus once. This corpus is federated on purpose: duration
thresholds, approved-country lists, approval authority and device/security rules are each written
in a different document, and a single query reaches only one or two of them. Re-read the question,
and for every distinct thing it asks that your evidence does not yet cover, search again. Then
conclude.`
It does not name a tool or a document count. `nudge_rate` will rise; that is a reported diagnostic.

### R4 — tell the model why the G1 recovery step exists (targets `remote-003`)
Where the orchestrator reopens the catalog and re-runs the act loop after a G1 refusal, it
currently appends nothing to `turn.messages`, so the recovery step is spent blind. Append one
deterministic `Message(role="user", …)` before that re-run (verbatim):
`Your answer was refused: nothing you retrieved can ground it. A compliance verdict is a
computation, not a policy passage — only a passage returned by SEARCHING the corpus can be cited.
Search now for the policy text behind each requirement you relied on, then conclude.`
Record it in `turn.nudges` as `g1_recovery` so the plan span shows it.

### R5 — `pto_request` requires the employee profile (fixes `pto-003`, `unsafe-001` end states)
`pto_request.SPEC.required_slots` already lists the employee profile first, but
`requires_tool_results` is only `("check_pto_balance", "check_policy_compliance")`, so
`is_complete` returns True too early. Add `"lookup_employee_profile"` to `requires_tool_results`
and add the debt wording `"lookup_employee_profile": "no employee record is in state yet"` to the
module's debt map (same words `remote_work.py` uses). Note in the spec §13.9 text that this changes
what the `no_structured_tools` arm measures (it disables the newly required tool) — disclose it as
a post-hoc change; do not restate the prediction.

### R6 — `route.j2`: name every missing detail (targets `amb-003`)
Change the needs_clarification line so it reads: "Name EVERY missing detail in rationale_summary,
not only the first — the question the user is shown is built from that line." Keep the rest.

### R7 — G1 counts compliance-engine evidence (after R4; medium risk; own tests)
`check_policy_compliance` returns per-requirement `evidence` blocks carrying committed
`chunk_id`/`doc_id`s, but G1 only scores retrieved candidates, so engine evidence is invisible to
it. Safe form only: resolve each compliance `chunk_id` against the committed index; embed the turn
query once; score each resolved chunk on the SAME dense path retrieval uses; run the resolved text
through the G4 quarantine check; then feed it through `LoopState.note_evidence` / the turn's
citable set exactly like a retrieved candidate. G1's rule and both thresholds are untouched — a
resolved chunk scoring below the threshold still fails, and engine evidence is never admitted
unscored. Cost: one embedding per compliance turn. Tests: (a) a compliance chunk above threshold
grounds a turn that has no retrieval; (b) one below threshold still refuses; (c) a quarantined
chunk is never admitted; (d) an unknown chunk_id is ignored, not raised.

## Tests (add or update; TDD where the change is behavioural)
- Prompt render tests for R1, R2, R6 (content present; byte-stable; R1's list == manifest titles).
- `_nudge` tests for R3: fires once; not when another reminder fired that step; not when tools
  are disabled or search is not permitted; not after two searches.
- R4: the recovery re-run's message list carries the message exactly once; `g1_recovery` in nudges.
- R5: `pto_request.is_complete` false without the profile result, true with all three; debt text.
- R7: the four tests above.
- `tests/e2e/test_demo_tasks.py` (stub) and every existing test stay green; update DEMO_EXPECTATIONS
  only if a genuine workflow need changed (R5 adds the profile lookup to the PTO demo path — check).

## Definition of done
- `.venv/bin/ruff check .` clean; `.venv/bin/pytest -q` green (baseline at your base commit plus
  yours; pristine output); `.venv/bin/python scripts/check_facts.py`,
  `.venv/bin/python scripts/pii_check.py`, `.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest`
  (or the Makefile target that wraps it) unchanged.
- Spec amended in the same commits (§8 reminders + recovery message, §9 prompt rules, §10 G1
  candidate widening, §13.9 disclosure). `CHANGELOG.md`: one P13 entry listing R1–R7 in one line
  each with the item each targets.
- Commit(s) on `main` prefixed `P13(agent): …`. Never push. Never read or print `.env`. Never call
  a live LLM or the live deploy URL; tests run with `LLM_PROVIDER=stub`.
- No subagents. Report to `.superpowers/sdd/2026-09-08-implementation-roadmap/P13-report.md`;
  return status, commit sha(s), one-line test summary, concerns.
