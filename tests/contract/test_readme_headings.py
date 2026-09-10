"""README carries its five headings and its three link lines (R1.1, R1.3, DOCS.2, SUB.2).

Also guards the documented setup path: `## Setup` and `make setup` must leave `hrmosaic`
importable, so `python -m hrmosaic.rag.download_model` runs from an activated venv with no
PYTHONPATH prefix.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
MAKEFILE = REPO_ROOT / "Makefile"
PYPROJECT = REPO_ROOT / "pyproject.toml"
EDITABLE_INSTALL = "pip install -e ."

REQUIRED_HEADINGS = [
    "## Setup",
    "## Local Run",
    "## Deployment",
    "## Evaluation",
    "## Third-party components",
]
LINK_LABELS = ["Deployed", "Demo video", "Repo"]
PLACEHOLDER = "TBD-before-submission"
#: P12 retires the placeholder (`grep -c 'TBD-before-submission' README.md` must be 0) while the
#: link it stood for can still be blocked on a human gate — the Render account for `Deployed:`,
#: the recording for `Demo video:`. Such a line carries a marker naming the gate instead, which is
#: strictly more informative than the placeholder was. `test_docs_completeness.py` is what holds
#: those markers to naming a gate `NEEDS-FROM-USER.md` still tracks; this P0 test only asks that
#: the line exists and is not silently blank.
PENDING = re.compile(r"^pending: gate \d")


def _lines() -> list[str]:
    return README.read_text(encoding="utf-8").splitlines()


def _readme_section(heading: str) -> str:
    lines = _lines()
    start = lines.index(heading)
    end = next(
        (i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _make_target(name: str) -> str:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{name}:")
    end = next(
        (i for i, line in enumerate(lines[start + 1 :], start + 1) if line and not line.startswith("\t")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_five_headings_present():
    lines = _lines()
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in lines]
    assert missing == [], f"README.md is missing headings: {missing}"


def test_setup_section_names_the_venv_command():
    """R1.1 — `## Setup` names `python3.12 -m venv .venv` literally."""
    assert "python3.12 -m venv .venv" in _readme_section("## Setup")


def test_documented_setup_installs_the_package():
    """`## Setup` and `make setup` both install the package, and pyproject can build it."""
    assert EDITABLE_INSTALL in _readme_section("## Setup"), (
        "README `## Setup` must install the package, or `python -m hrmosaic...` fails for a developer"
    )
    assert EDITABLE_INSTALL in _make_target("setup"), "`make setup` must install the package"
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    assert "[build-system]" in pyproject, "pyproject.toml needs a [build-system] for `pip install -e .`"
    assert 'package-dir = {"" = "src"}' in pyproject, "the src layout must be declared to setuptools"


def test_hrmosaic_imports_without_pythonpath():
    """The behaviour the setup path buys: no PYTHONPATH, no repo cwd, still importable."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-c", "import hrmosaic; print(hrmosaic.__file__)"],
        cwd=REPO_ROOT.parent,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "`import hrmosaic` fails with no PYTHONPATH and no repo cwd — run the `## Setup` steps "
        f"(`{EDITABLE_INSTALL}`). stderr:\n{result.stderr}"
    )


def test_three_link_lines_in_the_first_twenty_lines():
    head = _lines()[:20]
    for label in LINK_LABELS:
        pattern = re.compile(rf"^(?:[-*]\s*)?(?:\*\*)?{re.escape(label)}:(?:\*\*)?\s+(.+?)\s*$")
        matches = [pattern.match(line) for line in head]
        found = [m for m in matches if m]
        assert found, f"README.md has no `{label}:` line in its first 20 lines"
        value = found[0].group(1)
        assert value == PLACEHOLDER or value.startswith("https://") or PENDING.match(value), (
            f"`{label}:` must carry an https URL, the literal {PLACEHOLDER}, or a "
            f"`pending: gate …` marker, got {value!r}"
        )
