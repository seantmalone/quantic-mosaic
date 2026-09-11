# P22 brief — a confirmed write is reported as done; the gated write is not painted as an error

## Finding (live, 2026-09-11 14:33Z, Mac Chrome, deployed 753596e)
Demo 2 ("book three days of PTO"): the confirmation card appeared with the exact payload, the user
clicked Confirm, the confirmation was consumed (`user_response: confirmed`), `create_mock_hr_ticket`
ran with status ok and `mock_writes` holds `MOCK-HR-000002` — and the synthesis prompt carried the
result verbatim (`{"status": "created", "ticket_id": "MOCK-HR-000002", …}` inside a
`<tool_result tool="create_mock_hr_ticket">` envelope). The final answer nevertheless ended with an
ESCALATION block: "I cannot open PTO requests on your behalf. You must submit the request directly in
MosaicOne…" and never mentioned the ticket. `synthesize.j2` has no rule about completed writes, and
rule 3 plus the policy text ("submit in MosaicOne") pulled the model into an escalation. The earlier
live demo 2 (P11b) produced `MOCK-HR-000001`; whether its answer text named it is not recorded.

## Required
1. **Deterministic outcome block.** In the orchestrator's synthesis path: when the turn holds a
   write-tool envelope (`create_mock_hr_ticket` → `status: created`, `draft_hr_email` → its success
   status) that was performed after a human confirmation, the final answer MUST begin with a
   `recommendation` block (it is tool data, not company policy) stating the outcome and the id
   verbatim, e.g. "Done: HR ticket MOCK-HR-000002 was opened in queue hr-timeoff (priority normal) —
   this is a mock ticket, nothing was sent outside this app." Build it from the tool result, not from
   model output; insert it before the model's blocks; if the model's answer already states the id in a
   block, do not duplicate. Additionally, drop any `escalation` block whose text claims inability to
   perform the very action the result shows was performed (a small deterministic check: an escalation
   block in a turn with a performed write is replaced by a recommendation pointing at the ticket) —
   G3 stays untouched; this is a new, narrowly scoped post-synthesis step with its own name, listed in
   the spec beside the guardrails (§10) as "outcome consistency", never as a guardrail number.
2. **Prompt rule.** `synthesize.j2` rule 10 (verbatim): "10. A <tool_result> from a write tool with a
   success status is an action the user confirmed and that has been performed. State it first, with
   its id, as a recommendation block. Never write that you cannot perform, or did not perform, an
   action such a result shows was performed." Regenerate the golden; the act system half stays
   byte-stable.
3. **Rail label for a gated write.** The rail paints the first `create_mock_hr_ticket` call as a red
   "error" line before "Waiting for your confirmation…". When a tool result is the CONFIRMATION_REQUIRED
   shape, the closed-span line must read "needs your confirmation" in the pending (amber) style, not
   the error style; the span's own status stays whatever the trace contract says (do not change the
   recorded status — only the presentation mapping in `web/narration.py` / the rail CSS).
4. **Tests.** Unit tests for the outcome block (created → block first with the id; already-stated →
   no duplicate; escalation-with-performed-write → replaced); DEMO_EXPECTATIONS for demo-2 asserts
   the ticket id appears in the final answer text; `scripts/demo_task_2.sh` asserts the id from the
   confirm response appears in the answer text and prints it; narration test for the gated shape.
5. **Docs.** Spec §10 paragraph + §18.2 demo-2 expectation sentence; `docs/demo-script.md` demo-2
   beat says the answer opens with the ticket id; CHANGELOG entry.

## Definition of done
`ruff check .` / `ruff format --check` clean; `pytest -q` pristine; `make coverage` ≥ 90%;
`check_facts.py`, `pii_check.py`, `--verify-manifest` unchanged; `make demo1` then `make demo2`
(separately) green with the new assertion. Commits `P22(agent): …` / `P22(web): …` on `main`; never
push; never read or print `.env`; never call a live LLM or the live URL (the main session re-tests
live after deploy). No subagents. Report to `.superpowers/sdd/2026-09-08-implementation-roadmap/P22-report.md`.

## Item 6 — CI test-job failure on 753596e (must be fixed in this wave; blocks the deploy)
`tests/contract/test_health.py::test_health_reports_every_block_of_the_payload` failed in CI with
`assert 1 == 12` (`eval_runs_imported` vs `_committed_run_count()`); locally it passes. The boot-time
import of `evaluation/results/r_*.json` runs in the maintenance background task, and under the new
coverage tracer the CI runner is ~2× slower (suite 300 s), so `/health` was read while the import was
still running — one run in, eleven to go. Fix the TEST, not the timing: poll `/health` until
`eval_runs_imported` equals the committed count (or the maintenance task is done) with a bounded wait
(≤ 30 s, 0.2 s steps) before asserting; keep the equality assertion; add a comment naming the race.
Check the other contract tests that read `/health`'s store counts for the same assumption and give
them the same wait (a shared helper in tests/conftest.py). Verify with
`coverage run --branch --source=src/hrmosaic -m pytest -q tests/contract/test_health.py` locally.
