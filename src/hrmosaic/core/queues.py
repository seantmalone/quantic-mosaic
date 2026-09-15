"""What each HR queue is called in front of a person — one map, read by three layers.

The slug (`hr-timeoff`) is a routing key. It is stored on the mock write, it is what the dashboard
and `/api/*` show, and it is never what a human-facing sentence says (UX W2, jargon-and-exposure-6).

It lives in `core/` because three layers need the *same* translation and two of them may not import
each other: `mcpserver/tools/create_mock_hr_ticket.py` writes the confirmation card's lead sentence,
`web/api.py` builds the card's `<dl>`, and `agent/outcome.py` writes the completed write's lead
sentence — and `tests/architecture/test_conventions.py` forbids `agent/**` from importing
`hrmosaic.mcpserver` at all (UX W6, cpux-re-2: the queue's human name was lost from the answer
because the answer's own layer could not reach the lookup the card uses).
"""

from __future__ import annotations

#: The name each queue goes by in front of a person. `queue_label()` is the one translation.
QUEUE_LABELS: dict[str, str] = {
    "hr-general": "HR",
    "hr-timeoff": "HR Time Off team",
    "hr-benefits": "HR Benefits team",
    "hr-mobility": "HR Mobility team",
    "hr-relations": "Employee Relations team",
    "it-equipment": "IT Equipment team",
}

#: What an unmapped queue is called. A slug never reaches a reader, not even an unknown one.
QUEUE_FALLBACK = "HR"


def queue_label(queue: str) -> str:
    """`hr-timeoff` → `HR Time Off team`. Never returns the slug."""
    return QUEUE_LABELS.get(queue, QUEUE_FALLBACK)


__all__ = ["QUEUE_FALLBACK", "QUEUE_LABELS", "queue_label"]
