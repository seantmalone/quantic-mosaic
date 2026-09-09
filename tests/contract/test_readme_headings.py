"""README carries its five headings and its three link lines (R1.1, R1.3, DOCS.2, SUB.2)."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"

REQUIRED_HEADINGS = [
    "## Setup",
    "## Local Run",
    "## Deployment",
    "## Evaluation",
    "## Third-party components",
]
LINK_LABELS = ["Deployed", "Demo video", "Repo"]
PLACEHOLDER = "TBD-before-submission"


def _lines() -> list[str]:
    return README.read_text(encoding="utf-8").splitlines()


def test_five_headings_present():
    lines = _lines()
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in lines]
    assert missing == [], f"README.md is missing headings: {missing}"


def test_setup_section_names_the_venv_command():
    """R1.1 — `## Setup` names `python3.12 -m venv .venv` literally."""
    lines = _lines()
    start = lines.index("## Setup")
    end = next(
        (i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## ")),
        len(lines),
    )
    section = "\n".join(lines[start:end])
    assert "python3.12 -m venv .venv" in section


def test_three_link_lines_in_the_first_twenty_lines():
    head = _lines()[:20]
    for label in LINK_LABELS:
        pattern = re.compile(rf"^(?:[-*]\s*)?(?:\*\*)?{re.escape(label)}:(?:\*\*)?\s+(\S+)\s*$")
        matches = [pattern.match(line) for line in head]
        found = [m for m in matches if m]
        assert found, f"README.md has no `{label}:` line in its first 20 lines"
        value = found[0].group(1)
        assert value == PLACEHOLDER or value.startswith("https://"), (
            f"`{label}:` must carry an https URL or the literal {PLACEHOLDER}, got {value!r}"
        )
