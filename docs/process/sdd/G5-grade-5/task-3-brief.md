## Task 3 — Configuration and scripts: the dead knob, self-dating demo scripts

Closes gaps **20** and **7**.

1. Gap 20 — `MCP_TOOLS_DISABLED` must be read: use it as the process default for
   `options.tools_disabled` where `ChatOptions` is built, with a unit test. Keep the
   `.env.example` line and correct its comment if needed.
2. Gap 7 — `scripts/demo_task_1.sh` and `scripts/demo_task_2.sh` must produce the documented
   verdicts against **any** server, including the deployed one, without `MOCK_TODAY`. The chat UI
   already self-dates through `demo_prompts()` in `src/hrmosaic/web/api.py`; give the scripts the
   same behaviour (fetch the prompt from the endpoint that serves the UI buttons if one exists, or
   compute the dates in POSIX `sh` the same way). The stub replays under `make demo1`/`make demo2`
   must still pass (`tests/e2e/test_demo_tasks.py` and `tests/contract/test_deploy_scripts_are_runnable.py`).

Run `make lint`, `make demo1`, `make demo2` and the affected suites. Commit as `G5(config-scripts): ...`.

