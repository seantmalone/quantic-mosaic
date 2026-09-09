"""The boot-time importer for committed evaluation results (spec §10.3).

Render's free instance has no persistent disk: the filesystem is wiped on every redeploy,
restart and 15-minute spin-down. The evaluation pages must still render, so every committed
`evaluation/results/<run_id>.json` is imported into `eval_runs` / `eval_results` at boot,
**idempotently**, keyed on `import_state.sha256`:

* a file whose sha256 is unchanged is skipped;
* a changed file is re-imported, replacing that run's rows — never an "only when the tables are
  empty" check, which would freeze the grader's view at the first boot;
* `latest.json`, `comparison.json` and `chunk_size_comparison.json` are aggregates, not run
  objects, and are ignored, as is any JSON whose top level lacks both `run_id` and `metrics`.

The run-file shape this module reads is the shape `evaluation/runner.py` writes at P10: the
`eval_runs` columns at the top level (`config` and `metrics` as objects, stored as
`config_json` / `metrics_json`) plus `items[]`, one per `eval_results` row.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hrmosaic.core.db import Statement, Store, get_store, now_micros

logger = logging.getLogger(__name__)

#: Aggregates over runs, not run objects (§10.3).
AGGREGATE_FILENAMES = frozenset({"latest.json", "comparison.json", "chunk_size_comparison.json"})

DEFAULT_RESULTS_DIR = Path("evaluation/results")

RUN_UPSERT = """
INSERT INTO eval_runs (id, created_at, git_sha, label, variant, target, target_base_url, dataset_sha,
                       config_json, n_items, metrics_json, judge_model, judge_calls, duration_s, status, notes)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(id) DO UPDATE SET
    created_at = excluded.created_at, git_sha = excluded.git_sha, label = excluded.label,
    variant = excluded.variant, target = excluded.target, target_base_url = excluded.target_base_url,
    dataset_sha = excluded.dataset_sha, config_json = excluded.config_json, n_items = excluded.n_items,
    metrics_json = excluded.metrics_json, judge_model = excluded.judge_model,
    judge_calls = excluded.judge_calls, duration_s = excluded.duration_s, status = excluded.status,
    notes = excluded.notes
"""

RESULT_INSERT = """
INSERT INTO eval_results (id, run_id, item_id, category, session_id, turn_id, run_phase, answer,
                          latency_ms, cold, scores_json, verdicts_json, passed)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
"""

IMPORT_STATE_UPSERT = """
INSERT INTO import_state (path, sha256, imported_at, n_records) VALUES (?,?,?,?)
ON CONFLICT(path) DO UPDATE SET sha256 = excluded.sha256, imported_at = excluded.imported_at,
                                n_records = excluded.n_records
"""


@dataclass(frozen=True)
class ImportReport:
    """What one import pass did, file by file."""

    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    records: int = 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_run_object(document: Any) -> bool:
    return isinstance(document, dict) and "run_id" in document and "metrics" in document


def _run_row(run: dict[str, Any]) -> tuple[Any, ...]:
    return (
        run["run_id"],
        int(run.get("created_at") or now_micros()),
        run.get("git_sha") or "dev",
        run.get("label") or run["run_id"],
        run.get("variant") or "baseline",
        run.get("target") or "local",
        run.get("target_base_url") or "",
        run.get("dataset_sha") or "",
        json.dumps(run.get("config") or {}, ensure_ascii=False),
        int(run.get("n_items") or len(run.get("items") or [])),
        json.dumps(run.get("metrics") or {}, ensure_ascii=False),
        run.get("judge_model"),
        run.get("judge_calls"),
        run.get("duration_s"),
        run.get("status") or "complete",
        run.get("notes"),
    )


def _result_row(run_id: str, item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("id") or f"{run_id}::{item['item_id']}",
        run_id,
        item["item_id"],
        item.get("category") or "uncategorised",
        item.get("session_id"),
        item.get("turn_id"),
        item.get("run_phase") or "scored",
        item.get("answer"),
        item.get("latency_ms"),
        int(item.get("cold") or 0),
        json.dumps(item.get("scores") or {}, ensure_ascii=False),
        json.dumps(item["verdicts"], ensure_ascii=False) if item.get("verdicts") is not None else None,
        int(item.get("passed") or 0),
    )


def import_results(*, store: Store | None = None, results_dir: Path | str = DEFAULT_RESULTS_DIR) -> ImportReport:
    """Import every committed run object under `results_dir`. Never raises: boot must succeed."""
    store = store or get_store()
    directory = Path(results_dir)
    if not directory.is_dir():
        logger.info("no committed evaluation results at %s", directory)
        return ImportReport()

    known = {row["path"]: row["sha256"] for row in store.execute("SELECT path, sha256 FROM import_state")}
    imported: list[str] = []
    skipped: list[str] = []
    ignored: list[str] = []
    failed: list[str] = []
    records = 0

    for path in sorted(directory.glob("*.json")):
        name = path.name
        if name in AGGREGATE_FILENAMES:
            ignored.append(name)
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("could not read %s; skipping it", path, exc_info=True)
            failed.append(name)
            continue
        if not _is_run_object(document):
            ignored.append(name)
            continue

        digest = _sha256(path)
        key = str(path)
        if known.get(key) == digest:
            skipped.append(name)
            continue

        try:
            records += _import_run(store, key, digest, document)
        except Exception:
            logger.warning("could not import %s; skipping it", path, exc_info=True)
            failed.append(name)
            continue
        imported.append(name)

    return ImportReport(imported=imported, skipped=skipped, ignored=ignored, failed=failed, records=records)


def _import_run(store: Store, path: str, digest: str, run: dict[str, Any]) -> int:
    """One run, replacing whatever the previous import of the same run left behind."""
    run_id = run["run_id"]
    items = run.get("items") or []
    statements = [
        Statement(RUN_UPSERT, _run_row(run)),
        Statement("DELETE FROM eval_results WHERE run_id = ?", (run_id,)),
    ]
    statements += [Statement(RESULT_INSERT, _result_row(run_id, item)) for item in items]
    statements.append(Statement(IMPORT_STATE_UPSERT, (path, digest, now_micros(), len(items))))
    store.batch(statements)
    return len(items)
