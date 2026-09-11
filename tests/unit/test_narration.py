"""`web/narration.py` — the rail's plain-language labels (spec §11.3).

Two properties, and the second is a safety property:

* **completeness.** Every tool of the committed catalog has a label. A tenth tool added to
  `mcp/tools/` without one would silently narrate itself as "Working…" on camera, so the catalog is
  the test's source of truth rather than a list copied into it.
* **containment.** A label never carries an argument value or a word of employee data. The one
  thing a label may name is a document *title*, and it is read from the index by `doc_id` — so it
  can only ever be a document the corpus holds, never whatever the model asked for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hrmosaic.web import narration

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_SCHEMAS = sorted((REPO_ROOT / "mcp" / "tools").glob("*.schema.json"))


def _published_tools() -> list[str]:
    names = []
    for path in TOOL_SCHEMAS:
        body = json.loads(path.read_text(encoding="utf-8"))
        names.append(str(body.get("name") or path.name.removesuffix(".schema.json")))
    return sorted(names)


def test_a_label_exists_for_every_published_tool():
    published = _published_tools()
    assert len(published) == 9, "the committed catalog is §8.4's nine tools"
    assert sorted(narration.TOOL_LABELS) == published


@pytest.mark.parametrize("name", _published_tools())
def test_every_tool_label_is_a_forward_looking_sentence(name):
    label = narration.label_for("tool_call", name, {"arguments": {}})

    assert label != narration.WORKING
    assert label.endswith("…"), "the rail line describes something still happening"
    assert name not in label, "a label is prose for a person, never the tool's identifier"


def test_every_agent_purpose_has_a_label():
    """The span's own name is `provider:model`, so `purpose` is what distinguishes the calls."""
    for purpose in ("route", "act", "synthesize", "repair"):
        assert narration.label_for("llm_call", "anthropic:claude-haiku-4-5", {"purpose": purpose}) != narration.WORKING
    assert narration.label_for("llm_call", "anthropic:claude-haiku-4-5", {"purpose": "synthesize"}) == (
        "Writing the answer…"
    )
    assert narration.label_for("llm_call", "anthropic:claude-haiku-4-5", {"purpose": "route"}) == (
        "Understanding your question…"
    )


def test_the_guardrail_pass_and_the_confirmation_wait_each_have_one_line():
    assert narration.label_for("guardrail", "G2_citation_resolvability") == narration.GUARDRAIL_LABEL
    assert narration.label_for("confirmation", "create_mock_hr_ticket") == narration.CONFIRMATION_LABEL


def test_an_unmapped_span_is_neutral_and_never_the_span_name():
    assert narration.label_for("mcp_discovery", "hr-mcp") == narration.WORKING
    assert narration.label_for("retrieval", "hybrid_rrf") == narration.WORKING
    assert narration.label_for("tool_call", "a_tool_that_does_not_exist") == narration.WORKING


def test_a_section_label_names_the_document_title_and_never_the_doc_id():
    """The one label that shows anything from the call — and it shows the index's word, not the model's."""
    label = narration.label_for("get_policy_section", "get_policy_section", {"arguments": {"doc_id": "pto-policy"}})
    assert label == narration.WORKING, "the kind decides; a `tool_call` is what gets a tool label"

    label = narration.label_for(
        "tool_call", "get_policy_section", {"arguments": {"doc_id": "pto-and-holidays", "heading_path": "Accrual"}}
    )
    assert label.startswith("Reading the ") and label.endswith(" section…")
    assert "pto-and-holidays" not in label
    assert "Accrual" not in label, "a heading path is an argument value; only the title is shown"


def test_an_unknown_document_degrades_rather_than_echoing_the_argument():
    label = narration.label_for("tool_call", "get_policy_section", {"arguments": {"doc_id": "no-such-document"}})

    assert label == narration.SECTION_FALLBACK
    assert "no-such-document" not in label


def test_a_label_never_repeats_an_argument_value():
    """The property the SSE contract test asserts end to end, pinned here per tool."""
    arguments = {
        "employee_id": "E1042",
        "query": "berlin remote work approval",
        "doc_id": "remote-and-hybrid-work",
        "subject": "PTO request for 15-17 September",
        "confirmation_token": "cf_secret_value",
    }
    for name in narration.TOOL_LABELS:
        label = narration.label_for("tool_call", name, {"arguments": arguments})
        for value in arguments.values():
            assert value not in label, f"{name} leaked {value!r}"


def test_the_gated_write_attempt_reads_as_pending_not_as_a_failure():
    """The CONFIRMATION_REQUIRED shape is the gate doing its job, not the tool failing (§8.6).

    The rail used to paint the first `create_mock_hr_ticket` call red — a scarlet `error` line one
    beat before "Waiting for your confirmation…" — because the span's recorded status *is* `error`
    (the MCP result is `isError`, and the audit record must keep saying so). Only the presentation
    changes here: the line reads "Needs your confirmation" in the pending style.
    """
    gated = {"error_code": "CONFIRMATION_REQUIRED", "is_error": True, "arguments": {"employee_id": "E1042"}}

    assert narration.label_for("tool_call", "create_mock_hr_ticket", gated) == narration.NEEDS_CONFIRMATION_LABEL
    assert narration.tone_for("tool_call", "error", gated) == narration.PENDING
    assert narration.NEEDS_CONFIRMATION_LABEL.lower().startswith("needs your confirmation")


def test_the_recorded_status_is_not_what_the_rail_paints_but_everything_else_still_is():
    """A real tool failure stays red, and an ok span stays neutral: only the gate is special-cased."""
    failed = {"error_code": "UPSTREAM_TIMEOUT", "is_error": True, "arguments": {}}

    assert narration.tone_for("tool_call", "error", failed) == narration.ERROR
    assert narration.tone_for("tool_call", "ok", {"arguments": {}}) == narration.OK
    assert narration.tone_for("llm_call", "error", {"purpose": "synthesize"}) == narration.ERROR
    assert narration.tone_for("confirmation", "ok", {"user_response": "pending"}) == narration.OK


def test_the_write_tool_label_before_the_gate_is_still_forward_looking():
    """`step_started` has no result yet — its detail is the arguments — so the label is unchanged."""
    assert narration.label_for("tool_call", "create_mock_hr_ticket", {"arguments": {"queue": "hr-timeoff"}}) == (
        "Preparing the ticket for your confirmation…"
    )
