"""The `jq` lines the published-run instructions print must run against the artifacts we write.

A definition-of-done command that can never pass is worse than a missing one: it reads as
evidence, and the first person to run it after the gates land loses an hour to
`jq: error (…): Cannot iterate over null`. That is exactly what
`jq -r '.runs[].config_json.target' evaluation/results/comparison.json` did — `ablation.py` has
never written a `runs` key or a `config_json` field. It was corrected at source on 2026-09-10 in
the P11 brief, roadmap §4, `docs/requirements-traceability.md` and `NEEDS-FROM-USER.md`; this test
is what stops it, or anything like it, coming back.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPARISON = REPO_ROOT / "evaluation" / "results" / "comparison.json"

#: Every *committed* document that prints the published-run block. Each is authoritative for
#: someone. The dispatch brief under `.superpowers/` carries the same line and was corrected with
#: them, but that directory is git-ignored, so a fresh checkout has no copy for this test to read.
DOCUMENTS = (
    REPO_ROOT / "NEEDS-FROM-USER.md",
    REPO_ROOT / "docs" / "requirements-traceability.md",
    REPO_ROOT / "docs" / "superpowers" / "plans" / "2026-09-08-implementation-roadmap.md",
)

COMPARISON_JQ = ".target, (.variants[].variant)"
IMPOSSIBLE_JQ = ".runs[].config_json.target"


def _jq(filter_: str, path: Path) -> list[str]:
    """Run the real `jq` when it is installed; otherwise evaluate the one filter we document."""
    if shutil.which("jq"):
        completed = subprocess.run(["jq", "-r", filter_, str(path)], capture_output=True, text=True, check=False)
        assert completed.returncode == 0, completed.stderr
        return completed.stdout.split()
    document = json.loads(path.read_text(encoding="utf-8"))
    assert filter_ == COMPARISON_JQ, filter_
    return [document["target"], *[entry["variant"] for entry in document["variants"]]]


def test_the_comparison_jq_prints_the_target_then_the_three_variants():
    assert _jq(COMPARISON_JQ, COMPARISON) == [
        json.loads(COMPARISON.read_text(encoding="utf-8"))["target"],
        "baseline",
        "dense_only_k2",
        "no_structured_tools",
    ]


def test_the_comparison_artifact_carries_no_runs_key_to_iterate():
    """The shape the corrected command depends on — and the reason the old one could not work."""
    document = json.loads(COMPARISON.read_text(encoding="utf-8"))
    assert "runs" not in document
    assert "config_json" not in document
    assert isinstance(document["target"], str)
    assert [entry["variant"] for entry in document["variants"]] == [
        "baseline",
        "dense_only_k2",
        "no_structured_tools",
    ]


def _command_lines(path: Path) -> list[str]:
    """The lines inside fenced code blocks — the ones a reader copies and runs."""
    lines, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            inside = not inside
            continue
        if inside:
            lines.append(line)
    return lines


def test_no_document_offers_the_impossible_comparison_jq_as_a_command():
    """Prose may quote the old form while explaining the correction; a runnable block may not."""
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()}: {line.strip()}"
        for path in DOCUMENTS
        for line in _command_lines(path)
        if IMPOSSIBLE_JQ in line
    ]
    assert offenders == [], offenders


def test_every_document_prints_the_corrected_comparison_jq():
    missing = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in DOCUMENTS
        if COMPARISON_JQ not in path.read_text(encoding="utf-8")
    ]
    assert missing == [], missing


# --------------------------------------------------------------------------------------
# `ls docs/evidence/*.png` — the committed screenshots
# --------------------------------------------------------------------------------------

EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"


def test_the_mcp_discovery_screenshot_is_committed_beside_its_json():
    """Spec §13.9 names this pair: the 4-tool catalog as a figure and as machine-readable JSON.

    The figure is the half a grader reads. It is not gate-blocked — `gen_ablation_evidence.py`
    spawns its own stdio server locally — so its absence was a gap, not a missing credential.
    """
    png = EVIDENCE_DIR / "mcp-discovery-4-tools.png"
    payload = json.loads((EVIDENCE_DIR / "mcp-discovery-4-tools.json").read_text(encoding="utf-8"))
    assert png.is_file(), "run `python scripts/gen_ablation_evidence.py` and capture its output"
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert payload["tool_count"] == 4
    assert len(payload["removed_tools"]) == 5
    assert [tool["name"] for tool in payload["tools"]] == sorted(tool["name"] for tool in payload["tools"])
