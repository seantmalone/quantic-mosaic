## Task 1 — Agent code: clarification names every missing slot; profile debt keyed on arguments; refusal copy; router catalog

Closes gaps **4 (part a, the repair)**, **11**, **18**, **19**, **17**.

1. Gap 4a — `_clarification_text` (in `src/hrmosaic/agent/`) must join every unfilled slot, not
   the first, and `CLARIFY_QUESTIONS` gains an `employee_data` key so a balance/identity ambiguity
   gets its own question that names what is missing. Add a unit test asserting amb-002's and
   amb-003's questions name the missing information (use the dataset questions from
   `evaluation/dataset.yaml`). The judge's `named_missing_information` verdict must be able to
   pass on the served text.
2. Gap 11 — `_profile_outstanding` in `src/hrmosaic/agent/orchestrator.py` must key on the
   recorded call **arguments** of `PROFILE_FIRST_TOOLS` rather than an `employee_id` in the result
   body, so `check_policy_compliance` counts. Add a unit test whose scripted turn calls only
   `check_policy_compliance` for the actor and asserts the profile debt fires.
3. Gap 18 — covered by item 2; add no extra reopen trigger.
4. Gap 19 — `_resume` must not report a refused confirmation token as a failed policy search. Add a
   `CONFIRMATION_REFUSAL` reason with its own user copy (two entries: token invalid, token
   already used or expired), and a test that the user sees confirmation copy, not USER_REFUSAL copy.
5. Gap 17 — render the discovered catalog names (`turn.catalog.names`) into `route.j2`'s user
   block so `selected_tools` is chosen from something the router can see. Keep the cacheable
   system prefix stable. Update `tests/contract/test_prompt_golden.py` fixtures if they pin the
   prompt. If the prompt golden makes this disproportionate, drop `selected_tools` from
   `RouteDecision` instead and say so in the report.

Run `make lint` and the unit + contract suites before committing. Commit as `G5(agent): ...`.

