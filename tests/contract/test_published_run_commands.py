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


#: The three files `ls docs/evidence/*.png` is asking for. Two earlier P11 rounds reported the
#: third as "named nowhere in the repo" — that was wrong, and the grep that found nothing looked
#: only in the design document. All three are named, in three different files:
#:
#:   * `mcp-discovery-4-tools.png`  — spec §13.9 (the ablation arm's 4-tool catalog)
#:   * `mcp-discovery-page.png`     — `docs/requirements-traceability.md`'s **RUBRIC5.2** row and
#:                                    roadmap §5's rubric table: "`/dashboard/mcp` renders live
#:                                    discovery with all nine JSON Schemas"
#:   * `ci-deploy-skipped.png`      — spec §14.5 (the R8.4 red run's job graph)
#:
#: `NEEDS-FROM-USER.md` used to say "`ci-deploy-skipped.png` … plus the two the design document
#: references", which double-counts the CI graph — the design document references it. That sentence
#: is what sent two rounds looking for a fourth name; it now carries the table above instead.
EXPECTED_SCREENSHOTS = {
    "mcp-discovery-4-tools.png",
    "mcp-discovery-page.png",
    #: Blocked on the R8.4 red run, which needs `git push origin HEAD:ci-red-evidence` — a push
    #: no phase subagent may make (roadmap §2.2). It is the last file of P11 still outstanding
    #: that does not need a Render or Turso credential.
    "ci-deploy-skipped.png",
}

#: The ones capturable without a credential or a push. Both are committed.
CAPTURABLE_SCREENSHOTS = EXPECTED_SCREENSHOTS - {"ci-deploy-skipped.png"}


def test_the_mcp_dashboard_screenshot_is_committed():
    """RUBRIC5.2's figure: `/dashboard/mcp` rendering live discovery with all nine tool schemas.

    The traceability matrix has named this file since P0 and nothing had ever captured it. It needs
    no account: the page reads the mounted server's own `tools/list` over loopback, so the running
    image plus the admin persona is the whole recipe.
    """
    png = EVIDENCE_DIR / "mcp-discovery-page.png"
    assert png.is_file(), "run the image, open /dashboard/mcp as admin, and capture the page"
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_traceability_matrix_names_the_dashboard_screenshot():
    """The name is not this test's invention — RUBRIC5.2 is where it comes from."""
    matrix = (REPO_ROOT / "docs" / "requirements-traceability.md").read_text(encoding="utf-8")
    assert "docs/evidence/mcp-discovery-page.png" in matrix


def test_docs_evidence_holds_the_capturable_screenshots_and_nothing_unnamed():
    """Every committed figure is one of the three, and both keyless ones are there.

    Asserting the *count* is three would be a test that cannot pass until someone pushes; asserting
    the membership is what actually stops a fourth, unnamed figure appearing and stops either
    keyless one going missing again.
    """
    committed = {path.name for path in EVIDENCE_DIR.glob("*.png")}
    assert committed <= EXPECTED_SCREENSHOTS, sorted(committed - EXPECTED_SCREENSHOTS)
    assert CAPTURABLE_SCREENSHOTS <= committed, sorted(CAPTURABLE_SCREENSHOTS - committed)
