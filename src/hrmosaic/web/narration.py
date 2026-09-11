"""Plain-language labels for the live span rail (spec §11.3).

The rail used to list a step only after it closed, in the shape the audit record wants:
`tool_call · search_policy_documents — 5 hits`. That is the right line to keep — the observability
story is half the point — but it is not what a person watching a 13-second turn needs while it is
running. `open_span()` announces each step as it begins, and this module is the **one** mapping
from a span to the forward-looking sentence the rail shows in the meantime.

**One mapping, keyed on kind plus what identifies the step within that kind** — the tool's name for
a `tool_call`, the call's `purpose` for an `llm_call` (the span's own name is `provider:model`,
which cannot tell the router from the synthesis). Anything unmapped is `WORKING`, never a raw span
name: a rail line is prose for a person, and a person is not helped by `mcp_discovery`.

**A label never carries an argument value or a word of employee data.** The single exception is a
document *title*, and it is read from the committed index by `doc_id` rather than echoed from the
call — so a label can only ever name a document the corpus actually holds. `test_narration.py`
asserts both halves: that every tool in `mcp/tools/*.schema.json` has a label, and that no label
contains a value from the arguments it was given.

**It also decides the line's tone** (`tone_for`), which is presentation and nothing else. The span's
recorded `status` stays exactly what the trace contract says: the gated `create_mock_hr_ticket`
attempt really is an `isError` result and really is stored as `error` (§10.1), but it is the
confirmation gate doing its job — so the rail paints it amber and reads "Needs your confirmation"
instead of painting the safety moment scarlet one beat before "Waiting for your confirmation…".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hrmosaic.core import corpusread

#: What an unmapped span says. Neutral, honest and short: the closed-span line that replaces it a
#: moment later carries the detail.
WORKING = "Working…"

#: `tool_call` → the sentence shown while that tool runs. Every tool of the committed catalog
#: (§8.4) is here, and `test_a_label_exists_for_every_published_tool` fails when one is added
#: without a label. `get_policy_section` is a format string: see `_section_label`.
TOOL_LABELS: dict[str, str] = {
    "search_policy_documents": "Searching the policy library…",
    "get_policy_section": "Reading the {title} section…",
    "list_policy_documents": "Listing the policy library…",
    "lookup_employee_profile": "Looking up your employee record…",
    "check_pto_balance": "Checking your PTO balance…",
    "lookup_benefits_status": "Checking your benefits status…",
    "check_policy_compliance": "Checking this request against the rules…",
    "create_mock_hr_ticket": "Preparing the ticket for your confirmation…",
    "draft_hr_email": "Preparing the email for your confirmation…",
}

#: What `get_policy_section` says when the `doc_id` names nothing the index holds — a repaired
#: argument, a hallucinated id. The label degrades; it never prints the id it was given.
SECTION_FALLBACK = "Reading the policy section…"

#: `llm_call` → the sentence, keyed on `purpose` (§10.2). The span's name is `provider:model`, so
#: the purpose is the only thing that distinguishes the router from the synthesis call.
PURPOSE_LABELS: dict[str, str] = {
    "route": "Understanding your question…",
    "act": "Deciding what to look up next…",
    "synthesize": "Writing the answer…",
    "repair": "Working out what went wrong with that tool call…",
}

#: The guardrail pass, and the confirmation card's wait. Both are one sentence for the whole kind:
#: what a reader needs to know is that their answer is being checked, not which of six rules is
#: running.
GUARDRAIL_LABEL = "Verifying every claim against the policy text…"
CONFIRMATION_LABEL = "Waiting for your confirmation…"

#: The closed line for the gated write attempt — the one whose result is §8.4 tool 8's five-key
#: `CONFIRMATION_REQUIRED` rejection. Not forward-looking, because that step is over: what it
#: produced is a card waiting for a human, and "Waiting for your confirmation…" follows it.
NEEDS_CONFIRMATION_LABEL = "Needs your confirmation"

#: The three presentation tones a rail line can carry. **Presentation only**: the span's recorded
#: `status` is the audit record and is never rewritten here (§10.1).
OK = "ok"
PENDING = "pending"
ERROR = "error"

#: The result code that means the gate did its job rather than the tool failing (§8.6). The MCP
#: result is `isError` and the span's status is `error` — correctly, because the call returned no
#: ticket — but a red line one beat before "Waiting for your confirmation…" reads as a broken demo.
CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"


def label_for(kind: str, name: str, detail: Mapping[str, Any] | None = None) -> str:
    """The rail's line for one span. Never raises, never empty, never echoes an argument."""
    values = detail or {}
    if kind == "llm_call":
        return PURPOSE_LABELS.get(str(values.get("purpose") or ""), WORKING)
    if kind == "tool_call":
        if _gated(values):
            return NEEDS_CONFIRMATION_LABEL
        if name == "get_policy_section":
            return _section_label(values.get("arguments"))
        return TOOL_LABELS.get(name, WORKING)
    if kind == "guardrail":
        return GUARDRAIL_LABEL
    if kind == "confirmation":
        return CONFIRMATION_LABEL
    return WORKING


def tone_for(kind: str, status: str, detail: Mapping[str, Any] | None = None) -> str:
    """How the rail should paint one closed span: `ok`, `pending` or `error`.

    The one special case is the gated write attempt. Everything else follows the recorded status,
    so a genuine tool failure is still red and the record itself is untouched either way.
    """
    if kind == "tool_call" and _gated(detail or {}):
        return PENDING
    return ERROR if status == "error" else OK


def _gated(detail: Mapping[str, Any]) -> bool:
    """Is this `tool_call` payload the confirmation gate's own rejection (§8.4 tool 8)?"""
    return str(detail.get("error_code") or "") == CONFIRMATION_REQUIRED


def _section_label(arguments: Any) -> str:
    """`Reading the {document title} section…` — the title from the index, or nothing at all.

    The `doc_id` is a selector, not prose: it is used to *look up* a title and is never rendered.
    A document the index does not hold therefore degrades to `SECTION_FALLBACK` rather than
    leaking whatever the model asked for.
    """
    doc_id = arguments.get("doc_id") if isinstance(arguments, Mapping) else None
    if not isinstance(doc_id, str) or not doc_id:
        return SECTION_FALLBACK
    try:
        document = corpusread.get_document(doc_id)
    except Exception:  # no index on this process; a rail label is never worth an exception
        return SECTION_FALLBACK
    if document is None or not document.doc_title:
        return SECTION_FALLBACK
    return TOOL_LABELS["get_policy_section"].format(title=document.doc_title)


__all__ = [
    "CONFIRMATION_LABEL",
    "CONFIRMATION_REQUIRED",
    "ERROR",
    "GUARDRAIL_LABEL",
    "NEEDS_CONFIRMATION_LABEL",
    "OK",
    "PENDING",
    "PURPOSE_LABELS",
    "SECTION_FALLBACK",
    "TOOL_LABELS",
    "WORKING",
    "label_for",
    "tone_for",
]
