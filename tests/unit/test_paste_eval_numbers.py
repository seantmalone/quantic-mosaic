"""`scripts/paste_eval_numbers.py` picks its fallback run from the file, not from the filesystem.

Until gates 2 and 4 land there is no `evaluation/results/latest.json`, so the script pastes the
newest committed `*_baseline.json` into `design-and-evaluation.md` and labels the block
`BLOCKED-BY-GATE`. "Newest" used to mean `path.stat().st_mtime`, which is not a property of the
run at all: **git stores no mtime**, so every file in a fresh clone carries the moment the
checkout wrote it, in whatever order it happened to write them. CI and a developer's laptop could
therefore paste different figures from the identical commit — and the figures are the ones the
rubric reads.

The ordering key is now the run's own `created_at`, with the epoch embedded in the
`r_<seconds>_<variant>` run id as the fallback for a file written before that field existed. The
two are recorded in different units — `created_at` in microseconds, the run id in seconds — so
these tests pin the normalisation as much as the ordering.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import paste_eval_numbers as paste

#: Two runs a minute apart, in the unit each source actually uses.
EARLIER_SECONDS = 1_789_032_950
LATER_SECONDS = 1_789_033_010


def _write(directory: Path, name: str, payload: dict) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run(run_id: str, **extra) -> dict:
    return {"run_id": run_id, "variant": "baseline", "target": "local", **extra}


def test_created_at_orders_the_runs_even_when_mtime_disagrees(tmp_path):
    """The mutation the old key could not survive: a fresh clone's arbitrary mtimes."""
    older = _write(
        tmp_path,
        f"r_{EARLIER_SECONDS}_baseline.json",
        _run(f"r_{EARLIER_SECONDS}_baseline", created_at=EARLIER_SECONDS * 1_000_000),
    )
    newer = _write(
        tmp_path,
        f"r_{LATER_SECONDS}_baseline.json",
        _run(f"r_{LATER_SECONDS}_baseline", created_at=LATER_SECONDS * 1_000_000),
    )
    # A checkout that wrote the newer run first: mtime says the opposite of `created_at`.
    newer.touch()
    older.touch()
    assert older.stat().st_mtime >= newer.stat().st_mtime

    assert sorted([older, newer], key=paste.run_sort_key)[-1] == newer
    assert sorted([newer, older], key=paste.run_sort_key)[-1] == newer


def test_the_run_id_epoch_is_the_fallback_when_created_at_is_absent(tmp_path):
    older = _write(tmp_path, f"r_{EARLIER_SECONDS}_baseline.json", _run(f"r_{EARLIER_SECONDS}_baseline"))
    newer = _write(tmp_path, f"r_{LATER_SECONDS}_baseline.json", _run(f"r_{LATER_SECONDS}_baseline"))
    assert sorted([newer, older], key=paste.run_sort_key)[-1] == newer


def test_microsecond_and_second_stamps_are_compared_in_the_same_unit(tmp_path):
    """Raw comparison would rank every microsecond stamp above every second stamp."""
    seconds_stamped = _write(
        tmp_path,
        "r_0001_baseline.json",
        _run("r_0001_baseline", created_at=LATER_SECONDS),
    )
    micros_stamped = _write(
        tmp_path,
        "r_0002_baseline.json",
        _run("r_0002_baseline", created_at=EARLIER_SECONDS * 1_000_000),
    )
    assert sorted([seconds_stamped, micros_stamped], key=paste.run_sort_key)[-1] == seconds_stamped


def test_an_unreadable_run_sorts_first_rather_than_raising(tmp_path):
    """A truncated or half-written file must not stop the paste, and must never win."""
    broken = _write(tmp_path, "r_9999999999_baseline.json", {})
    broken.write_text("{ not json", encoding="utf-8")
    good = _write(
        tmp_path,
        f"r_{EARLIER_SECONDS}_baseline.json",
        _run(f"r_{EARLIER_SECONDS}_baseline", created_at=EARLIER_SECONDS * 1_000_000),
    )
    assert sorted([good, broken], key=paste.run_sort_key)[-1] == good


def test_the_committed_baseline_run_is_selectable_by_its_own_timestamp():
    """The real artifact carries the field the ordering now depends on."""
    committed = sorted(paste.RESULTS_DIR.glob("*_baseline.json"))
    assert committed, "no committed baseline run to order"
    for path in committed:
        stamp, _ = paste.run_sort_key(path)
        assert stamp > 0, f"{path.name} carries neither a usable `created_at` nor an `r_<epoch>_` id"


def test_epoch_seconds_rejects_non_timestamps():
    for value in (None, "1789032950", -1, 0, True):
        assert paste._epoch_seconds(value) is None
