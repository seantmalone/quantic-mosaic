"""Tool 8 ⚠ — a gated mock write (spec §8.4, §8.5, §8.6).

Mock **by construction**: it appends a row to `mock_writes` in the trace store and returns its id.
Nothing external is contacted, nothing on disk is mutated, and `mock: true` is in the payload and
renders as a badge in the UI.

Gated **inside the server**: without a valid one-time `confirmation_token` the call returns
`isError` with the five-key `CONFIRMATION_REQUIRED` result of §8.4 — and **no token of any kind**,
because the server must never hand the agent the credential that would let it retry. The orchestrator
strips any model-supplied token before every `tools/call`, so a fabricated one never reaches here
either; a token exists only after a human clicks Confirm in `web/`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from hrmosaic.core.db import now_micros
from hrmosaic.mcpserver import confirm
from hrmosaic.mcpserver.server import WRITE, CallMeta, ServerDeps, envelope, read_meta, result
from hrmosaic.mcpserver.tools.lookup_employee_profile import EMPLOYEE_ID

TOOL_NAME = "create_mock_hr_ticket"
ID_PREFIX = "MOCK-HR-"

Queue = Literal["hr-general", "hr-timeoff", "hr-benefits", "hr-mobility", "hr-relations", "it-equipment"]
Priority = Literal["low", "normal", "high"]

#: The name each queue goes by in front of a person (UX W2, jargon-and-exposure-6). The slug is a
#: routing key: it is stored on the mock write, it is what the dashboard and `/api/*` show, and it
#: is never what the confirmation card or an answer says. `queue_label()` is the one translation.
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


class TicketOutput(BaseModel):
    """The §8.4 tool-8 result, or the five-key `CONFIRMATION_REQUIRED` rejection on `isError`."""

    status: str
    ticket_id: str | None = None
    queue: str | None = None
    priority: str | None = None
    created_at: str | None = None
    employee_id: str | None = None
    mock: bool | None = None
    url: str | None = None
    code: str | None = None
    action: str | None = None
    human_summary: str | None = None
    arguments_preview: dict[str, Any] | None = None


def register(server: MCPServer, deps: ServerDeps) -> None:
    @server.tool(
        name=TOOL_NAME,
        description=(
            "Open a mock HR ticket in one of the HR queues. Requires human confirmation: called "
            "without a valid one-time confirmation_token it returns status='confirmation_required' "
            "with a human_summary to show the user, and writes nothing. Never invent a token."
        ),
        annotations=ToolAnnotations(**WRITE),
    )
    async def create_mock_hr_ticket(
        ctx: Context,
        employee_id: Annotated[str, EMPLOYEE_ID],
        queue: Annotated[Queue, Field(description="Which HR queue the ticket belongs in.")],
        summary: Annotated[str, Field(min_length=5, max_length=200, description="One-line ticket title.")],
        details: Annotated[str, Field(min_length=10, max_length=4000, description="The full request.")],
        priority: Annotated[Priority, Field(description="Ticket priority.")] = "normal",
        confirmation_token: Annotated[
            str | None, Field(description="Supplied by the application after the user clicks Confirm. Never by you.")
        ] = None,
    ) -> TicketOutput:
        call = read_meta(ctx)
        started = now_micros()
        body = await asyncio.to_thread(
            _ticket,
            deps,
            call=call,
            employee_id=employee_id,
            queue=queue,
            summary=summary,
            details=details,
            priority=priority,
        )
        ended = now_micros()
        body["_trace"] = envelope(call, server_timing_ms=max(0, (ended - started) // 1000), transport=deps.transport)
        return result(body, is_error=body["status"] == "confirmation_required")


def human_summary(queue: str, summary: str) -> str:
    """The sentence the confirmation card leads with — the queue's human name, never its slug.

    The employee id it used to carry is gone with it (UX W2, jargon-and-exposure-6): the person
    reading the card is the person the ticket is for, and the id is on the span either way.
    """
    return f'Open an HR ticket with the {queue_label(queue)}: "{summary}".'


def _ticket(
    deps: ServerDeps,
    *,
    call: CallMeta,
    employee_id: str,
    queue: str,
    summary: str,
    details: str,
    priority: str,
) -> dict[str, Any]:
    """The blocking half: the gate and, if it opens, the one `mock_writes` row."""
    preview = {"employee_id": employee_id, "queue": queue, "summary": summary, "priority": priority}
    try:
        confirmation = confirm.validate(deps.store(), tool_name=TOOL_NAME, arguments=call.arguments)
        created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {**preview, "details": details, "created_at": created_at, "mock": True}
        ticket_id = confirm.consume(
            deps.store(),
            confirmation,
            kind="hr_ticket",
            prefix=ID_PREFIX,
            employee_id=employee_id,
            payload=payload,
        )
    except confirm.ConfirmationRejected:
        return confirm.rejection(TOOL_NAME, human_summary(queue, summary), preview)
    return TicketOutput(
        status="created",
        ticket_id=ticket_id,
        queue=queue,
        priority=priority,
        created_at=created_at,
        employee_id=employee_id,
        mock=True,
        url=f"/dashboard/safety#{ticket_id}",
    ).model_dump(mode="json", exclude_none=True)


__all__ = [
    "ID_PREFIX",
    "QUEUE_FALLBACK",
    "QUEUE_LABELS",
    "TOOL_NAME",
    "Priority",
    "Queue",
    "TicketOutput",
    "human_summary",
    "queue_label",
    "register",
]
