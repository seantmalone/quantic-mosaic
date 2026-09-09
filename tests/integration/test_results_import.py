"""`core/archive.py` — the idempotent boot import of committed eval results (spec §10.3).

Render's free disk is wiped on every redeploy, restart and spin-down, so a cold database must
still render full evaluation pages. The importer therefore runs at boot, keyed on
`import_state.sha256` — never an "only when the tables are empty" check, which would freeze the
grader's view at the first boot.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from hrmosaic.core import archive

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "eval_runs" / "sample_run.json"


@pytest.fixture
def results_dir(tmp_path) -> Path:
    directory = tmp_path / "results"
    directory.mkdir()
    shutil.copy(FIXTURE, directory / "r_p1sample_baseline.json")
    return directory


def test_a_committed_run_is_imported_into_both_tables(store, results_dir):
    report = archive.import_results(store=store, results_dir=results_dir)

    assert report.imported == ["r_p1sample_baseline.json"]
    assert report.records == 3
    run = store.execute("SELECT * FROM eval_runs").one()
    assert run["id"] == "r_p1sample_baseline"
    assert (run["variant"], run["target"], run["status"]) == ("baseline", "local", "complete")
    assert run["n_items"] == 3
    assert json.loads(run["metrics_json"])["pass_rate"] == 0.667
    assert json.loads(run["config_json"])["retrieval_k"] == 5

    rows = store.execute("SELECT * FROM eval_results ORDER BY item_id").dicts()
    assert [row["item_id"] for row in rows] == ["pto_balance_self", "remote_work_berlin", "salary_band_request"]
    assert [row["passed"] for row in rows] == [1, 1, 0]
    assert rows[0]["turn_id"] == "4a71c0de9f2c1b7e4a71c0de9f2c1b7e"  # the eval row → trace deep link
    assert rows[0]["run_phase"] == "scored"
    assert json.loads(rows[0]["scores_json"])["groundedness"] == 1.0
    assert json.loads(rows[2]["verdicts_json"])["safety"]["pass"] is True


def test_an_unchanged_file_is_skipped_on_the_second_import(store, results_dir):
    archive.import_results(store=store, results_dir=results_dir)

    report = archive.import_results(store=store, results_dir=results_dir)

    assert report.imported == []
    assert report.skipped == ["r_p1sample_baseline.json"]
    assert store.execute("SELECT COUNT(*) AS n FROM eval_results").scalar() == 3
    assert store.execute("SELECT COUNT(*) AS n FROM eval_runs").scalar() == 1


def test_a_changed_file_is_re_imported_without_duplicating_rows(store, results_dir):
    archive.import_results(store=store, results_dir=results_dir)
    path = results_dir / "r_p1sample_baseline.json"
    run = json.loads(path.read_text(encoding="utf-8"))
    run["metrics"]["pass_rate"] = 1.0
    run["items"][2]["passed"] = 1
    run["items"] = run["items"][:2] + [run["items"][2]]
    path.write_text(json.dumps(run), encoding="utf-8")

    report = archive.import_results(store=store, results_dir=results_dir)

    assert report.imported == ["r_p1sample_baseline.json"]
    assert store.execute("SELECT COUNT(*) AS n FROM eval_runs").scalar() == 1
    assert store.execute("SELECT COUNT(*) AS n FROM eval_results").scalar() == 3
    assert json.loads(store.execute("SELECT metrics_json FROM eval_runs").scalar())["pass_rate"] == 1.0
    assert store.execute("SELECT SUM(passed) AS n FROM eval_results").scalar() == 3
    assert store.execute("SELECT n_records FROM import_state").scalar() == 3


def test_removed_items_do_not_linger_from_the_previous_import(store, results_dir):
    archive.import_results(store=store, results_dir=results_dir)
    path = results_dir / "r_p1sample_baseline.json"
    run = json.loads(path.read_text(encoding="utf-8"))
    run["items"] = run["items"][:1]
    run["n_items"] = 1
    path.write_text(json.dumps(run), encoding="utf-8")

    archive.import_results(store=store, results_dir=results_dir)

    assert store.execute("SELECT COUNT(*) AS n FROM eval_results").scalar() == 1


def test_aggregate_files_and_non_run_json_are_ignored(store, results_dir):
    source = (results_dir / "r_p1sample_baseline.json").read_text(encoding="utf-8")
    for name in ("latest.json", "comparison.json", "chunk_size_comparison.json"):
        (results_dir / name).write_text(source, encoding="utf-8")
    (results_dir / "notes.json").write_text(json.dumps({"note": "not a run object"}), encoding="utf-8")

    report = archive.import_results(store=store, results_dir=results_dir)

    assert report.imported == ["r_p1sample_baseline.json"]
    assert sorted(report.ignored) == ["chunk_size_comparison.json", "comparison.json", "latest.json", "notes.json"]
    assert store.execute("SELECT COUNT(*) AS n FROM eval_runs").scalar() == 1


def test_a_missing_results_directory_is_not_an_error(store, tmp_path):
    """Boot must always succeed, including before any run has ever been committed."""
    report = archive.import_results(store=store, results_dir=tmp_path / "nothing-here")

    assert report == archive.ImportReport()


def test_a_malformed_run_file_does_not_stop_the_others(store, results_dir):
    (results_dir / "broken.json").write_text("{not json", encoding="utf-8")

    report = archive.import_results(store=store, results_dir=results_dir)

    assert report.imported == ["r_p1sample_baseline.json"]
    assert report.failed == ["broken.json"]
