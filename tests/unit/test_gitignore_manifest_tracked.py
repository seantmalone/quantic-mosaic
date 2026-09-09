"""The one committed artifact under `data/index/` (spec §4, §6.5).

`.gitignore` carries `data/index/*` and `!data/index/chunks.manifest.jsonl` **literally**: with a
trailing-slash exclusion (`data/index/`) git never descends into the directory, the negation is dead,
and the manifest silently becomes uncommittable — which would take R1.4's determinism assertion with
it. The index file and the ingest report stay ignored.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = "data/index/chunks.manifest.jsonl"


def _check_ignore(path: str) -> int:
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True).returncode


def test_the_manifest_is_not_ignored():
    assert _check_ignore(MANIFEST) != 0


def test_the_manifest_is_tracked():
    tracked = subprocess.run(
        ["git", "ls-files", MANIFEST], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert tracked == [MANIFEST]


def test_the_index_and_the_report_are_ignored():
    assert _check_ignore("data/index/hr_index.sqlite") == 0
    assert _check_ignore("data/index/ingest_report.json") == 0


def test_the_gitignore_rule_is_the_star_form_not_the_slash_form():
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "data/index/*" in lines
    assert f"!{MANIFEST}" in lines
    assert "data/index/" not in lines
