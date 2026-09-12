# P24 brief — model-behaviour fixes from the grade card (approved by Sean 2026-09-11: "Fix the model behavior items as well")

## Where this fits
After P23. Everything here changes what the model reads, what the dataset asks, or what a guardrail
does — so the main session re-drives the full deployed sweep (three arms), the judge and fresh blind
labels afterwards. You never call a live LLM or the live URL. The spec is authoritative; amend the
sections you change in the same commit. Grade card: `grade-card-2026-09-11.md` beside this brief.

## A. Multi-document citation breadth (grade card R3.5; RB1's principal cap)
Live multi-document answers under-cite: expenses-002 cited {travel-policy, expenses-and-reimbursement}
against `min_distinct_docs: 3` (manager-approval-matrix missing) and onboarding-001 cited two of the
four expected documents, in run `r_1789086979_baseline` (turn ids via `eval_results`). The evidence
set the synthesis prompt carried spanned more documents than the answer cited (check the synthesis
`llm_messages` for those turns in the Turso store — env from data/runtime/provision_turso.json — and
count the documents under CITATION COVERAGE).
Fix, in this order and only as far as needed:
1. `synthesize.j2` rules 8/9: make the coverage rule checkable by the model — every document listed
   under CITATION COVERAGE that supports any statement in the answer MUST be cited at least once; the
   model must walk the list and, for any listed document it does not cite, name it in
   `rationale_summary` as "not used: <doc>" (≤ 120 chars total still applies — if the list is long,
   "not used: 2 docs" is acceptable). Keep byte-stability of the act system half; regenerate goldens.
2. A deterministic post-synthesis breadth check (beside the P22 outcome-consistency step, same
   pattern, own name, no G-number): when the turn's item-independent end state can be inferred from
   the router's `multi_doc`/workflow signal (do NOT read the dataset), and the cited distinct-document
   count is below the number of distinct documents in the citable evidence set, ONE bounded repair
   call to the synthesis model with the list of uncited supporting documents ("cite these or say why
   not") — at most one extra LLM call per turn, only on multi-document turns, recorded as a
   `repair` purpose span so the dashboard shows it. If the second attempt still under-cites, keep the
   answer (never fabricate citations). Tests with the stub adapter for: repair triggered, repair not
   triggered on single-document turns, repair result replaces the answer only when it passes G2/G3.
3. Document the trade in the spec (§9 synthesis, §7.4 beside the outcome step) and the expected
   latency cost (one extra synthesis call on a minority of turns).

## B. HR-adjacent out-of-corpus items (grade card R3.4)
The three `out_of_scope` dataset items are non-HR trivia. Add TWO items whose topic is HR but absent
from the corpus — e.g. `oos-004` tuition reimbursement / education assistance, `oos-005` sabbatical
leave (check `corpus/` and `corpus/facts.yml` to be sure neither exists; pick different topics if they
do). Gold behaviour: refuse-or-redirect with the People Operations contact, no policy claims, no
citation. Category `out_of_scope`, `expected_tools: []`, expected_docs empty, and the behaviour
scorer's existing refusal checks apply. Then update every place that states the item count (26 →
28): README.md, design-and-evaluation.md (dataset table and counts), docs/requirements-traceability.md,
evaluation/REPORT.md's generated text (template only), the spec §13, ai-tooling.md if it quotes the
number, and the docs-completeness contract test so the count is asserted from `dataset.yaml`. Keep
`evaluation.schema.reference_subset()` (seed 1729 over answer items) and `judge_lowest_subset()`
unchanged; add a unit test that the two new items are excluded from both subsets (they are refusals).
Also make sure the router's corpus list (route.j2, R1) plus G1 actually refuse such a question on the
stub path: add an e2e/integration stub test where retrieval returns weakly related chunks for
"tuition reimbursement" and the served outcome is a refusal, not an answer.

## C. The two G2 block drops (grade card RB1: "G2 destroyed 2 grounded policy facts")
In `r_1789086979_baseline`, inj-001 and remote-004 each lost one block to G2 (`verdict: repair`).
Diagnose from the Turso store: which citation id was stripped and why (unknown chunk id? a compliance
evidence id not in the citable set? a formatting variant?). Fix the ROOT CAUSE deterministically where
possible: e.g. if the model cites an id that exists in the index but was not in the turn's citable set
because it came from a compliance envelope scored below threshold, decide with evidence whether the
right fix is (i) rendering such ids without a citable marker so the model does not cite them, (ii) a
synthesis rule that only ids under CITATION COVERAGE are citable, or (iii) resolving the citation when
the id is a genuine index chunk that supports the statement (only if G1's evidence rule still holds —
never admit unscored evidence). Write the diagnosis in the report with the two ids; add a test that
reproduces each drop and passes after the fix.

## D. Definition of done
`ruff check .` / `ruff format --check` clean; `pytest -q` pristine; `make coverage` ≥ 90%;
`scripts/check_facts.py`, `scripts/pii_check.py`, `--verify-manifest` unchanged; `make demo1` then
`make demo2` (separately) green; the dataset validates (`python -m evaluation.schema` or the existing
dataset test). Commits `P24(agent|eval): …` on `main`; never push; never read or print `.env`; never
call a live LLM or the live URL. No subagents. Report to
`.superpowers/sdd/2026-09-08-implementation-roadmap/P24-report.md`.
