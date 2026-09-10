"""`evaluation/results/latest.json` can only ever name a **deployed baseline** run (spec §13.2).

> `latest.json` is `{"run_id", "target": "deployed", "variant": "baseline"}` and the runner writes
> it only for such a run; `tests/unit/test_latest_points_at_deployed.py` asserts that, so a `local`
> run can never be promoted into the headline figures a grader reads.

The file does not exist until P11 produces the published run, so the first test **passes vacuously**
by design and only checks the contents when the file is there. The rest of the file has teeth
today: it drives `Runner.write_artifacts()` over a temporary results directory and asserts that a
local run writes no pointer and a deployed baseline run does.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.runner import Runner, RunOptions
from evaluation.schema import RESULTS_DIR, RunConfig, RunFile, RunMetrics, load_dataset
from hrmosaic.core.ids import SEED

LATEST = RESULTS_DIR / "latest.json"


def test_latest_json_names_a_deployed_baseline_run_when_it_exists():
    """Vacuous until P11 publishes the deployed run — and exact from the moment it does."""
    if not LATEST.exists():
        pytest.skip("no published run yet; latest.json lands at P11")
    document = json.loads(LATEST.read_text(encoding="utf-8"))
    assert document["target"] == "deployed"
    assert document["variant"] == "baseline"
    assert document["run_id"]
    assert (RESULTS_DIR / f"{document['run_id']}.json").exists()


def _run(*, target: str, variant: str) -> RunFile:
    return RunFile(
        run_id=f"r_test_{target}_{variant}",
        created_at=1_788_000_000_000_000,
        git_sha="deadbeef",
        label="synthetic",
        variant=variant,
        target=target,  # type: ignore[arg-type]
        target_base_url="http://127.0.0.1:8000" if target == "local" else "https://example.invalid",
        dataset_sha="0" * 64,
        config=RunConfig(
            retrieval_k=5,
            retrieval_strategy="hybrid_rrf",
            tools_disabled=[],
            llm_model="claude-haiku-4-5",
            judge_model="gemini-3.5-flash-lite",
            min_evidence_score=0.60,
            min_support_score=0.45,
            llm_rpm=10,
            seed=SEED,
        ),
        n_items=0,
        metrics=RunMetrics(),
        items=[],
    )


@pytest.fixture
def runner(store, tmp_path):
    return Runner(
        RunOptions(
            variant="baseline",
            base_url="http://127.0.0.1:8000",
            judge=False,
            results_dir=tmp_path,
            write_report=False,
        ),
        store=store,
        dataset=load_dataset(),
        judge=None,
    )


def test_a_local_run_writes_no_pointer(runner, tmp_path):
    runner.write_artifacts(_run(target="local", variant="baseline"))
    assert (tmp_path / "r_test_local_baseline.json").exists()
    assert not (tmp_path / "latest.json").exists()


def test_a_deployed_non_baseline_run_writes_no_pointer(runner, tmp_path):
    runner.write_artifacts(_run(target="deployed", variant="dense_only_k2"))
    assert not (tmp_path / "latest.json").exists()


def test_a_deployed_baseline_run_writes_the_pointer(runner, tmp_path):
    runner.write_artifacts(_run(target="deployed", variant="baseline"))
    pointer = json.loads(Path(tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert pointer == {"run_id": "r_test_deployed_baseline", "target": "deployed", "variant": "baseline"}


def test_a_loopback_base_url_always_resolves_to_the_local_target():
    from evaluation.runner import resolve_target

    assert resolve_target("http://127.0.0.1:8000") == "local"
    assert resolve_target("http://localhost:8000") == "local"
    assert resolve_target("https://mosaic-hr.onrender.com") == "deployed"
