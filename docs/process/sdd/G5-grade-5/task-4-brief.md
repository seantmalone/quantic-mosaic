## Task 4 — Measurement on the shipped build (controller pushes and deploys first)

Closes gaps **21**, **2**, **8 (data half)**, **9 (data half)**, **24**, and supplies the numbers
for gaps **1**, **3**, **4b**, **10**.

Precondition (controller): `main` pushed, CI green, `GET /health` `app.git_sha` equals `HEAD`.

1. Gap 21 — run one confirmed `draft_hr_email` turn against the deployed service (the
   manager-message variant of demo task 2, through `/chat` then `/chat/confirm` with the bearer
   token) so `/dashboard/tools` lists calls for all nine tools. Record the session id in the report.
2. Drive the baseline: `EVAL_TARGET_BASE_URL=https://mosaic-hr-copilot.onrender.com
   .venv/bin/python -m evaluation.runner --variant baseline` (with the `.env` credentials), then
   judge it: `--judge <run_id>`. Confirm `evaluation/results/latest.json` names the new run.
3. Drive the two arms on the same build: `--variant dense_only_k2` and
   `--variant no_structured_tools`, then `.venv/bin/python -m evaluation.ablation`. Confirm
   `comparison.json` names three runs with one shared `target_git_sha`.
4. Build both blind label packets for the new baseline with `scripts/gen_label_packet.py`
   (`--subset seed` and `--subset judge_lowest`) into `.superpowers/sdd/2026-09-21-grade-5/`.
   Do **not** author labels; the controller dispatches two independent blind labellers.
5. Gap 24 — the live `/dashboard/evals` lists judged runs with no committed file
   (`r_1789547562_baseline`, `r_1789534779_baseline`). If the dashboard or API exposes the run
   file, download and commit both; otherwise write one sentence for the report that names them and
   their builds, for the documentation task to place.
6. Run `--report <new baseline run_id>` so `evaluation/REPORT.md` describes the published run, then
   `.venv/bin/python scripts/paste_eval_numbers.py` (no `--check`) and confirm `--check` exits 0.

Commit results as `G5(eval): ...`. The report must list: run ids, `target_git_sha`, every headline
metric with its n, the strict-pass causes (`deterministic.strict_pass_causes()`), and the
clarification-accuracy figure. Do not edit prose documents in this task.

