"""Every graded document exists and carries the headings the requirements name (P12).

This is the phase where every asserted document exists, so the whole file is authored here
(spec §22 row 15: no test file is built up across five phases).

**Headings are asserted, prose is not diffed** (§21 row 28, §22 row 13). There is no docs
generator and no CI diff-check of documentation: `scripts/paste_eval_numbers.py` writes the
figures of one results table and nothing else. What this file proves is that a grader following
`docs/project-requirements.md` finds each named section where the requirement says it will be —
plus the handful of literal strings a requirement asks for by name (`?access=`, the bearer
header, the ISO date beside the cold-start number).

Every heading match is on a **whole line**, never a substring: `### Tool schemas` must not be
allowed to satisfy an assertion for `## Tool schemas`, and both legitimately exist — the `##`
section is the DOCS.3 subject, the `###` is one of requirement 10's ten justifications.

**Three link lines are gate-aware.** `Deployed:` must carry the tokenized `?access=` link and
`Demo video:` the recording URL, and neither may still read `TBD-before-submission` (SUB.1,
SUB.2, DEMO.1). Neither artifact can exist before a human satisfies a gate — the Render account
(gate 2 + 4) and the recording (gate 7) — so until then the line must carry a marker that names
the gate and `NEEDS-FROM-USER.md` must carry that gate. The assertion is therefore a branch, not
a skip: an `https://` value is held to the full requirement, a `pending: gate …` value is held
to naming a gate that is genuinely open. The placeholder itself is banned outright.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

README = REPO_ROOT / "README.md"
DESIGN = REPO_ROOT / "design-and-evaluation.md"
AI_TOOLING = REPO_ROOT / "ai-tooling.md"
DEPLOYED = REPO_ROOT / "deployed.md"
NEEDS = REPO_ROOT / "NEEDS-FROM-USER.md"
DEMO_SCRIPT = REPO_ROOT / "docs" / "demo-script.md"
CHECKLIST = REPO_ROOT / "docs" / "pre-submission-checklist.md"
EVIDENCE = REPO_ROOT / "docs" / "evidence"

PLACEHOLDER = "TBD-before-submission"
PENDING = re.compile(r"^pending: gate \d(?: \+ \d| ?/ ?\d)*\b")

#: DOCS.3 — the eight subjects the submission bullet names, as `##` sections.
DOCS3_SECTIONS = [
    "## Architecture",
    "## RAG design",
    "## MCP server design",
    "## Agent orchestration",
    "## Tool schemas",
    "## Safety guardrails",
    "## Deployment choices",
    "## Evaluation questions, expected answers and results",
]

#: R10.1 — the ten choices requirement 10's first bullet asks to be justified, as `###` subsections.
R10_1_JUSTIFICATIONS = [
    "### Orchestration approach",
    "### MCP server design",
    "### Transport choice",
    "### Tool schemas",
    "### Embedding model",
    "### Chunking strategy",
    "### Retrieval k",
    "### Vector store",
    "### Deployment architecture",
    "### Safety guardrails",
]

#: R10.2 — the seven components the architecture diagram must label.
SEVEN_COMPONENTS = [
    "Web App",
    "Agent Orchestrator",
    "MCP Client",
    "MCP Server",
    "RAG Index",
    "Mock Structured Data",
    "LLM Provider",
]

#: DOCS.5 / §14.1 — `deployed.md`'s six headings.
DEPLOYED_SECTIONS = [
    "## Deployed URLs",
    "## Access",
    "## Cold start",
    "## Environment variables",
    "## MCP transport",
    "## Cost",
]

#: DOCS.4 / DOCS.9 — `ai-tooling.md`'s three sections.
AI_TOOLING_SECTIONS = [
    "## What worked well",
    "## What did not work",
    "## AI use and ownership",
]

#: R1.3 / DOCS.2 — README's five headings.
README_SECTIONS = [
    "## Setup",
    "## Local Run",
    "## Deployment",
    "## Evaluation",
    "## Third-party components",
]

LINK_LABELS = ["Deployed", "Demo video", "Repo"]

#: The three committed screenshots (§13.9, §14.5, RUBRIC5.2).
EVIDENCE_SCREENSHOTS = [
    "mcp-discovery-4-tools.png",
    "mcp-discovery-page.png",
    "ci-deploy-skipped.png",
]

DEMO_IDS = [f"DEMO.{n}" for n in range(1, 8)]
SUB_IDS = [f"SUB.{n}" for n in range(1, 4)]


def _text(path: Path) -> str:
    assert path.exists(), f"{path.relative_to(REPO_ROOT)} does not exist"
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> list[str]:
    return _text(path).splitlines()


def _missing(path: Path, headings: list[str]) -> list[str]:
    """Headings absent as whole lines — never as a substring of a deeper heading."""
    present = {line.rstrip() for line in _lines(path)}
    return [heading for heading in headings if heading not in present]


def _section(path: Path, heading: str) -> str:
    """The text under `heading`, up to the next heading of the same or a shallower level."""
    lines = _lines(path)
    depth = len(heading) - len(heading.lstrip("#"))
    start = lines.index(heading)
    stop = len(lines)
    for index, line in enumerate(lines[start + 1 :], start + 1):
        if line.startswith("#") and (len(line) - len(line.lstrip("#"))) <= depth:
            stop = index
            break
    return "\n".join(lines[start:stop])


def _link_value(label: str) -> str:
    pattern = re.compile(rf"^(?:[-*]\s*)?(?:\*\*)?{re.escape(label)}:(?:\*\*)?\s+(.+?)\s*$")
    for line in _lines(README)[:20]:
        match = pattern.match(line)
        if match:
            return match.group(1)
    raise AssertionError(f"README.md has no `{label}:` line in its first 20 lines")


def _demo_expectations() -> list:
    """The live `DEMO_EXPECTATIONS` records, loaded from the e2e test that enforces them.

    `tests/` is not a package, so the module is loaded by path. Documenting a sequence that the
    executable records do not require is exactly the rot R10.3 is worried about.
    """
    path = REPO_ROOT / "tests" / "e2e" / "test_demo_tasks.py"
    spec = importlib.util.spec_from_file_location("_demo_tasks_for_docs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` resolves its own module through `sys.modules`, so registering it is not
    # optional here — without it the decorator raises on `DemoExpectation`.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module.DEMO_EXPECTATIONS
    finally:
        sys.modules.pop(spec.name, None)


# --------------------------------------------------------------------------- README (R1.3, DOCS.2)


def test_readme_has_its_five_headings():
    assert _missing(README, README_SECTIONS) == []


def test_readme_setup_still_names_the_venv_command():
    """R1.1 — the P0 assertion, re-asserted here now that the document is final."""
    assert "python3.12 -m venv .venv" in _section(README, "## Setup")


def test_readme_carries_no_submission_placeholder():
    """SUB.1 / SUB.2 / DEMO.1 — `grep -c 'TBD-before-submission' README.md` is 0."""
    assert PLACEHOLDER not in _text(README)


def test_readme_has_its_three_link_lines():
    for label in LINK_LABELS:
        value = _link_value(label)
        assert value.startswith("https://") or PENDING.match(value), (
            f"`{label}:` must carry an https URL or a `pending: gate …` marker, got {value!r}"
        )


def _open_gates() -> set[str]:
    """Gate numbers NEEDS-FROM-USER.md still lists as unticked."""
    return {match.group(1) for match in (re.match(r"- \[ \] \*\*(\d+) —", line) for line in _lines(NEEDS)) if match}


def _assert_pending_names_only_open_gates(label: str, value: str) -> None:
    named = set(re.findall(r"gate (\d)(?:\s*[+/]\s*(\d))?", value))
    numbers = {number for pair in named for number in pair if number}
    assert numbers, f"a pending `{label}:` must name at least one gate, got {value!r}"
    still_open = _open_gates()
    assert numbers <= still_open, (
        f"`{label}:` names gate(s) {sorted(numbers - still_open)}, which NEEDS-FROM-USER.md "
        f"no longer lists as open (open: {sorted(still_open)}) — the link is overdue"
    )


def test_deployed_link_is_tokenized_or_names_an_open_gate():
    """SUB.2 — the `Deployed:` line carries the full `?access=` link once its gates land."""
    value = _link_value("Deployed")
    if value.startswith("https://"):
        assert "?access=" in value, "the `Deployed:` link must carry the grader's `?access=` token"
    else:
        _assert_pending_names_only_open_gates("Deployed", value)


def test_demo_video_link_is_recorded_or_names_an_open_gate():
    """DEMO.1 — the `Demo video:` line carries the recording once it exists."""
    value = _link_value("Demo video")
    if not value.startswith("https://"):
        _assert_pending_names_only_open_gates("Demo video", value)


def test_readme_names_the_third_party_components():
    section = _section(README, "## Third-party components")
    for component in ["FastAPI", "mcp", "fastembed", "sqlite-vec", "htmx", "Chart.js"]:
        assert component in section, f"`## Third-party components` does not name {component}"


# ------------------------------------------------------- design-and-evaluation.md (DOCS.3, R10.*)


def test_design_document_has_the_eight_docs3_sections():
    assert _missing(DESIGN, DOCS3_SECTIONS) == []


def test_design_document_has_the_ten_r10_1_justifications():
    assert _missing(DESIGN, R10_1_JUSTIFICATIONS) == []


def test_every_justification_carries_its_rejected_alternative():
    """R10.1 — a justification without the alternative it beat is not a justification."""
    for heading in R10_1_JUSTIFICATIONS:
        body = _section(DESIGN, heading)
        assert "Rejected" in body, f"{heading} does not state what was rejected"


def test_architecture_diagram_labels_all_seven_components():
    """R10.2 — the mermaid source names every component the requirement enumerates."""
    text = _text(DESIGN)
    fences = re.findall(r"```mermaid\n(.*?)```", text, flags=re.DOTALL)
    assert fences, "design-and-evaluation.md carries no ```mermaid diagram"
    diagram = "\n".join(fences)
    missing = [name for name in SEVEN_COMPONENTS if name not in diagram]
    assert missing == [], f"the architecture diagram does not label: {missing}"


def test_architecture_section_links_the_interactive_page():
    assert "docs/architecture.html" in _section(DESIGN, "## Architecture")


def test_security_posture_subsection_is_complete():
    """DOCS.3 — the subsection and the six things it must say."""
    assert _missing(DESIGN, ["### Security posture"]) == []
    body = _section(DESIGN, "### Security posture").lower()
    for phrase in [
        "no user accounts",
        "app_access_token",
        "persona",
        "confirmation",
        "sso",
        "employee-scoped",
        "retention",
    ]:
        assert phrase in body, f"`### Security posture` does not cover {phrase!r}"


def test_judge_methodology_names_the_labeller_and_the_blinding():
    """RUBRIC5.8 / §13.7 — the agreement rate is never described as human."""
    body = _section(DESIGN, "### Judge methodology")
    assert "gemini-3.5-flash-lite" in body and "claude-haiku-4-5" in body
    assert "Opus" in body, "the labeller must be named, not implied"
    assert "blind" in body.lower(), "the blinding must be stated"
    assert "judge_agreement_rate" in body


def test_design_document_references_all_three_evidence_screenshots():
    text = _text(DESIGN)
    missing = [name for name in EVIDENCE_SCREENSHOTS if name not in text]
    assert missing == [], f"design-and-evaluation.md does not reference: {missing}"


def test_the_two_committed_screenshots_exist():
    """The third is committed by the main session with the red CI run (R8.4)."""
    for name in ["mcp-discovery-4-tools.png", "mcp-discovery-page.png"]:
        assert (EVIDENCE / name).exists(), f"docs/evidence/{name} is missing"


def test_documented_demo_sequences_match_the_executable_records():
    """R10.3 — every tool `DEMO_EXPECTATIONS` requires is named in the documented sequence."""
    section = _section(DESIGN, "## Evaluation questions, expected answers and results")
    demo = _section(DESIGN, "### The two demo tasks")
    haystack = section + demo
    for expectation in _demo_expectations():
        assert expectation.id in haystack, f"{expectation.id} is not documented"
        for tool in expectation.required_tools:
            assert tool in haystack, f"{expectation.id}: the documented sequence omits {tool}"


def test_results_table_carries_the_metric_families():
    """RUBRIC5.8 — all six families are reported in one table (filled by paste_eval_numbers.py)."""
    body = _section(DESIGN, "## Evaluation questions, expected answers and results")
    for metric in [
        "groundedness",
        "citation",
        "tool_selection_accuracy",
        "workflow_completion",
        "action_safety_pass_rate",
        "latency",
    ]:
        assert metric in body.lower() or metric in body, f"the results section omits {metric}"


def test_paste_eval_numbers_markers_are_intact():
    """`scripts/paste_eval_numbers.py` writes between these two markers and nowhere else."""
    text = _text(DESIGN)
    assert text.count("<!-- EVAL-NUMBERS:BEGIN -->") == 1
    assert text.count("<!-- EVAL-NUMBERS:END -->") == 1


# ----------------------------------------------------------------------------- deployed.md (DOCS.5)


def test_deployed_has_its_six_headings():
    assert _missing(DEPLOYED, DEPLOYED_SECTIONS) == []


def test_deployed_urls_section_names_the_health_endpoint():
    assert "/health" in _section(DEPLOYED, "## Deployed URLs")


def test_access_section_explains_every_way_in():
    body = _section(DEPLOYED, "## Access")
    for phrase in ["?access=", "mosaic_access", "Authorization: Bearer", "MCP Inspector", "admin", "Rotat"]:
        assert phrase in body, f"`## Access` does not cover {phrase!r}"


def test_cold_start_section_carries_a_measured_number_and_its_iso_date():
    """R7.5 — a number and the date it was measured, never an inference."""
    body = _section(DEPLOYED, "## Cold start")
    assert re.search(r"\b\d+(?:\.\d+)?\s*s\b", body), "`## Cold start` carries no measured number"
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", body), "`## Cold start` carries no ISO date"


def test_mcp_transport_section_states_the_single_service_decision():
    body = _section(DEPLOYED, "## MCP transport")
    assert "not deployed as a second service" in body or "not deployed as a separate service" in body
    assert "MCP_SERVER_URL" in body


def test_cost_section_states_zero_infrastructure():
    body = _section(DEPLOYED, "## Cost")
    assert "$0" in body


def test_deployed_references_the_ci_evidence_screenshot():
    assert "ci-deploy-skipped.png" in _text(DEPLOYED)


# ---------------------------------------------------------------------------- ai-tooling.md (DOCS.4)


def test_ai_tooling_has_its_three_sections():
    assert _missing(AI_TOOLING, AI_TOOLING_SECTIONS) == []


def test_ai_tooling_names_the_tools_and_the_workflow():
    text = _text(AI_TOOLING)
    for phrase in ["Claude Code", "Opus"]:
        assert phrase in text, f"ai-tooling.md does not name {phrase!r}"


def test_ai_tooling_carries_the_ownership_disclosure():
    """DOCS.9 — the student remains responsible for correctness, security and integrity."""
    body = _section(AI_TOOLING, "## AI use and ownership")
    for phrase in ["correctness", "security", "integrity"]:
        assert phrase in body, f"the ownership disclosure does not mention {phrase!r}"


# ------------------------------------------------------------ demo script and checklist (DEMO.*, SUB.*)


def test_demo_script_carries_the_segment_table_and_the_production_note():
    text = _text(DEMO_SCRIPT)
    assert "## Segment table" in text.splitlines() or "## Segments" in text.splitlines()
    assert "## Production note" in text.splitlines(), "DEMO.3's standing production note is a required section"
    assert "government ID" in text, "DEMO.4 — the ID beat must be scripted"
    assert re.search(r"\b0:00\b", text) and re.search(r"\b9:15\b|\b9:1\d\b", text), (
        "the segment table must be time-boxed across the full 7–10 minutes"
    )


def test_demo_script_carries_a_five_element_sub_checklist_per_task():
    """DEMO.6 — tool names, arguments, outputs, citations, final answer, ticked per task."""
    text = _text(DEMO_SCRIPT)
    headings = [line for line in text.splitlines() if line.startswith("#") and "DEMO.6 sub-checklist" in line]
    for task in ["Task 1", "Task 2"]:
        assert any(task in heading for heading in headings), f"{task} has no DEMO.6 sub-checklist heading"
    for element in ["tool names", "arguments", "outputs", "citations", "final answer"]:
        assert text.lower().count(element) >= 2, f"the DEMO.6 element {element!r} is not ticked for both tasks"


def test_pre_submission_checklist_has_a_line_per_demo_and_sub_id():
    lines = _lines(CHECKLIST)
    for identifier in DEMO_IDS + SUB_IDS:
        matches = [line for line in lines if line.startswith("- [ ] ") and identifier in line]
        assert len(matches) == 1, f"docs/pre-submission-checklist.md needs exactly one `- [ ] {identifier}` line"
