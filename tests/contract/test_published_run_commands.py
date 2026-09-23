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
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------------------
# `git diff 80a5a71..HEAD -- <the application tree>` — the provenance command five documents print
# --------------------------------------------------------------------------------------

#: The pathspec of the published provenance command, as **one** definition. Five documents print it
#: (README, `deployed.md`, `docs/pre-submission-checklist.md`, `docs/requirements-traceability.md`
#: and the `CHANGELOG.md` entry for the wave), the test below runs it, and neither can drift from the
#: other because both read this tuple.
#:
#: What is in it is *what the image serves*. `src`, the MCP server's code and schemas, the two launch
#: scripts, the image, the service manifest and the pinned dependencies are the obvious half.
#: `corpus` and `data/index/chunks.manifest.jsonl` are the half that is easy to forget and matters
#: just as much: `Dockerfile` copies the corpus into the image and builds the sqlite-vec + FTS5 index
#: from it at **build** time behind `ingest --verify-manifest`, so a policy edit or a re-chunk changes
#: the answers the deployed service gives exactly as a code change does — this wave's own
#: equipment-policy repair moved the live index from 204 chunks to 205.
#:
#: What is **out** of it is documentation, by name and by nothing broader: `mcp/README.md` and
#: `corpus/README.md`. Naming either directory whole would make the published command print a path on
#: the first prose edit — which is exactly how the round-1 version of this command falsified itself,
#: and `corpus/README.md` had already moved by the time round 2 widened the pathspec. `corpus/README.md`
#: is the directory's map, not one of the fourteen documents the index is built from:
#: `NON_DOCUMENT_STEMS` in `src/hrmosaic/rag/parse/__init__.py` skips it by stem.
APPLICATION_PATHSPEC = (
    "src",
    "mcp/tools",
    "mcp/server_entrypoint.py",
    "mcp/run_stdio.sh",
    "mcp/run_http.sh",
    "corpus",
    ":!corpus/README.md",
    "data/index/chunks.manifest.jsonl",
    "Dockerfile",
    "render.yaml",
    "requirements.txt",
)

#: The arguments as a reader copies them. Quoted where a shell needs it — `:!…` is a git pathspec, not
#: a glob, and an unquoted `!` is history expansion in an interactive shell.
PATHSPEC_ARGUMENTS = " ".join(f"'{entry}'" if entry.startswith(":") else entry for entry in APPLICATION_PATHSPEC)


def published_command(base: str) -> str:
    """The single-line form a reader copies, against `base`."""
    return f"git diff --stat {base}..HEAD -- {PATHSPEC_ARGUMENTS}"


#: The published command with its base sha captured. The sha is **read out of the document**, not
#: typed here, because the claim under test is the one the document makes.
PUBLISHED_COMMAND = re.compile(r"git diff --stat (?P<base>[0-9a-f]{7,40})\.\.HEAD -- " + re.escape(PATHSPEC_ARGUMENTS))

#: The marker of the interim notice README carries *instead* of the command while the claim is
#: withdrawn — a run has been published, the application tree has moved past the build it measured,
#: and the re-drive that would make the command true again has not landed. A notice is not a claim,
#: so the guard below stands down rather than blocking the very commit that has to be deployed
#: before a new run can measure it.
RE_MEASURE_NOTICE = re.compile(r"the application tree has changed since", re.IGNORECASE)

README = REPO_ROOT / "README.md"

#: Every document that prints that command. A document may wrap it over several lines, with or
#: without a trailing `\\`, so the comparison is against whitespace-normalised text.
PROVENANCE_DOCUMENTS = (
    README,
    REPO_ROOT / "deployed.md",
    REPO_ROOT / "docs" / "pre-submission-checklist.md",
    REPO_ROOT / "docs" / "requirements-traceability.md",
    REPO_ROOT / "CHANGELOG.md",
)

LATEST = REPO_ROOT / "evaluation" / "results" / "latest.json"


def _normalised(path: Path) -> str:
    """The document as one line, with any shell continuation folded away."""
    return " ".join(path.read_text(encoding="utf-8").replace("\\\n", " ").split())


def test_the_application_tree_has_not_moved_since_the_measured_build():
    """The claim is enforced exactly while README.md makes it (G5c).

    The guarantee is a documentary one, and it is narrower than it looks. It is **not** that the
    application tree may never move after a run is published — it has to move, because a code change
    can only be measured by a run driven against a build that was deployed first, and a guard that
    failed on every application commit would make that deploy impossible to get through CI. It is
    that the graded documents must not *claim* the tree is unchanged while it is.

    So the claim, not the tree, is what this test reads. README.md is where it is published: either
    it prints the provenance command inside a sentence offering it as evidence that nothing changed —
    and then the command is run here, against the base sha parsed out of the very line a reader
    copies, and must print nothing — or it prints the interim notice instead (`RE_MEASURE_NOTICE`),
    withdrawing the claim until a re-drive lands, and there is nothing to enforce. A README that
    prints no command at all makes no claim either. Both of those skip.

    When the claim *is* made, two things are checked beyond the diff: that README's base is the build
    the published run actually measured (`target_git_sha` in the run file `latest.json` points at, the
    sha the service's own `/health` reported while the run was driven), and that the other four
    documents print the same command — so the line a reader copies is the line the suite executes.

    The skip for an unresolvable base is earned rather than assumed, the same way
    `test_docs_completeness.py`'s commit census earns its own: a checkout that cannot resolve the base
    has to *prove* it could not hold it (no git at all, or a shallow clone) or this fails. CI is not
    that checkout — both the `lint` and the `test` job in `ci.yml` check out at `fetch-depth: 0`.
    """
    run_id = json.loads(LATEST.read_text(encoding="utf-8"))["run_id"]
    readme = _normalised(README)
    published = PUBLISHED_COMMAND.search(readme)
    if published is None or RE_MEASURE_NOTICE.search(readme):
        pytest.skip(
            f"README.md does not claim the application tree is unchanged since the build {run_id} "
            "measured — the claim is withdrawn pending a re-drive on the current build — so there is "
            "nothing to enforce. This test starts running again the moment README publishes the "
            "provenance command as evidence that the command prints nothing."
        )

    base = published.group("base")
    run_file = REPO_ROOT / "evaluation" / "results" / f"{run_id}.json"
    measured = json.loads(run_file.read_text(encoding="utf-8"))["target_git_sha"]
    assert measured.startswith(base) or base.startswith(measured), (
        f"README.md publishes the provenance command against {base}, but the published run {run_id} "
        f"records `target_git_sha` {measured}. A command based on any other build proves nothing "
        "about what that run measured."
    )

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)

    try:
        resolved = git("cat-file", "-e", f"{base}^{{commit}}").returncode == 0
    except OSError:  # pragma: no cover - no git binary on this machine
        resolved = False
        shallow = "true"
    else:
        shallow = git("rev-parse", "--is-shallow-repository").stdout.strip()
    if not resolved:
        assert shallow == "true", (
            f"the published run {run_id} records `target_git_sha` {base}, and this full clone has no "
            "such commit. Either the run file names a build this history does not have or the history "
            "was rewritten; a skip would hide both."
        )
        pytest.skip(f"git cannot resolve {base}; the application tree cannot be compared in this checkout")

    changed = git("diff", "--name-only", base, "HEAD", "--", *APPLICATION_PATHSPEC)
    assert changed.returncode == 0, changed.stderr
    moved = changed.stdout.split()
    assert git("diff", "--quiet", base, "HEAD", "--", *APPLICATION_PATHSPEC).returncode == 0, (
        f"the application tree has moved since the measured build {base[:7]}, so the published run "
        f"{run_id} no longer measures what this repository would deploy. Changed: {moved}. Either "
        "re-drive the run against the new build and repoint `latest.json`, or stop printing "
        f"`{published_command(base)}` as evidence that nothing changed."
    )

    stale = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in PROVENANCE_DOCUMENTS
        if published_command(base) not in _normalised(path)
    ]
    assert stale == [], (
        f"these documents no longer print the pathspec this test runs (`{published_command(base)}`), "
        f"so the command a reader copies is not the command the suite executes: {stale}"
    )
