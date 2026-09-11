"""A run file must say which code produced it and which code answered it (spec §13.2, R1.3).

`git_sha` used to be `settings.git_sha`, which resolves `GIT_SHA` → `RENDER_GIT_COMMIT` → `"dev"`.
On a laptop none of those is set, so every locally-driven run — including the published one —
recorded `"dev"`, and the link from a published number back to a commit rested on prose beside it.

Two shas fix that, and they are genuinely two different things:

* **`git_sha`** — the harness tree, read from `git rev-parse HEAD`. It says which scoring code,
  dataset loader and thresholds produced the figures.
* **`target_git_sha`** — what the target's own `/health` reports under `app.git_sha`, recorded for
  every non-local target. It says which build answered the 26 questions, which is the sha a reader
  of a deployed run actually wants.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import evaluation.runner as runner
from evaluation.schema import RunConfig, RunFile, RunMetrics

REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIG = RunConfig(
    retrieval_k=5,
    retrieval_strategy="hybrid_rrf",
    llm_model="claude-haiku-4-5",
    judge_model="gemini-3.5-flash-lite",
    min_evidence_score=0.6,
    min_support_score=0.45,
    llm_rpm=10,
    seed=1729,
)


def _run(**overrides: object) -> RunFile:
    fields: dict[str, object] = {
        "run_id": "r_test",
        "created_at": 0,
        "git_sha": "0" * 40,
        "label": "",
        "variant": "baseline",
        "target": "deployed",
        "target_base_url": "https://mosaic-hr-copilot.onrender.com",
        "dataset_sha": "0" * 64,
        "config": CONFIG,
        "n_items": 26,
        "metrics": RunMetrics(judged=True, strict_pass_rate=0.808, n_scored={"items": 26}),
    }
    fields.update(overrides)
    return RunFile(**fields)  # type: ignore[arg-type]


def test_the_harness_sha_is_the_working_tree_s_real_head():
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert runner.harness_git_sha() == head
    assert re.fullmatch(r"[0-9a-f]{40}", runner.harness_git_sha())


def test_a_tree_that_is_not_a_checkout_falls_back_rather_than_raising(tmp_path):
    """A run driven from an unpacked tarball still produces a file; it just cannot name a commit."""
    assert runner.harness_git_sha(cwd=tmp_path) == runner.default_settings.git_sha


def test_the_run_file_carries_both_shas_and_target_sha_is_optional():
    run = _run(target_git_sha="e13a772e736a759b32f199039926d9622aa2dca7")
    assert run.git_sha == "0" * 40
    assert run.target_git_sha == "e13a772e736a759b32f199039926d9622aa2dca7"
    assert _run().target_git_sha is None, "a local run has no second sha to record"


def test_the_report_header_prints_the_harness_sha_and_the_target_sha():
    report = runner.render_report(_run(target_git_sha="e13a772e736a759b32f199039926d9622aa2dca7"))
    header = report.split("## Headline metrics")[0]
    assert "| Harness git sha | `" + "0" * 40 + "` |" in header
    assert "| Target git sha | `e13a772e736a759b32f199039926d9622aa2dca7` |" in header


def test_a_local_run_says_so_rather_than_printing_an_empty_cell():
    header = runner.render_report(_run(target="local", target_base_url="http://127.0.0.1:8000")).split(
        "## Headline metrics"
    )[0]
    assert "| Target git sha | — (local target) |" in header


def test_a_run_from_before_the_field_existed_points_at_the_deploy_ledger():
    """The committed run files are records, not documents: they are not rewritten to add a sha."""
    header = runner.render_report(_run(git_sha="dev")).split("## Headline metrics")[0]
    assert "| Target git sha | — (not recorded; `deployed.md` names the commit that served this run) |" in header
