"""Tool 9 ⚠ — a gated mock write with the same token-free rejection shape as tool 8 (spec §8.4).

The draft is composed deterministically from `purpose`, `key_points` and `tone` — no model call —
so the same arguments always produce the same bytes and the confirmation card the user approved is
exactly what gets "sent". `sent` is always `false` and `mock` always `true`: nothing leaves the
process.
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
from hrmosaic.mcpserver.tools.lookup_employee_profile import EMPLOYEE_ID, org_row

TOOL_NAME = "draft_hr_email"
ID_PREFIX = "MOCK-EMAIL-"

RecipientRole = Literal["manager", "skip_level", "people_ops", "it_security", "payroll"]
Tone = Literal["neutral", "formal", "warm"]

#: The three roles that are a team rather than a person in the synthetic org.
TEAM_NAMES = {
    "people_ops": "People Operations",
    "it_security": "IT Security",
    "payroll": "Payroll",
}

OPENING = {
    "neutral": "Hello {name},",
    "formal": "Dear {name},",
    "warm": "Hi {name},",
}
CLOSING = {
    "neutral": "Thanks,\n{sender}",
    "formal": "Kind regards,\n{sender}",
    "warm": "Thanks so much,\n{sender}",
}


class EmailOutput(BaseModel):
    """The §8.4 tool-9 result, or the five-key `CONFIRMATION_REQUIRED` rejection on `isError`."""

    status: str
    draft_id: str | None = None
    to_role: str | None = None
    to_name: str | None = None
    subject: str | None = None
    body: str | None = None
    created_at: str | None = None
    sent: bool | None = None
    mock: bool | None = None
    code: str | None = None
    action: str | None = None
    human_summary: str | None = None
    arguments_preview: dict[str, Any] | None = None


def register(server: MCPServer, deps: ServerDeps) -> None:
    @server.tool(
        name=TOOL_NAME,
        description=(
            "Draft an HR email to the employee's manager, skip level or an HR team. Requires human "
            "confirmation: called without a valid one-time confirmation_token it returns "
            "status='confirmation_required' and writes nothing. Never invent a token."
        ),
        annotations=ToolAnnotations(**WRITE),
    )
    async def draft_hr_email(
        ctx: Context,
        employee_id: Annotated[str, EMPLOYEE_ID],
        recipient_role: Annotated[RecipientRole, Field(description="Who the draft is addressed to.")],
        purpose: Annotated[str, Field(min_length=5, max_length=500, description="What the email is for.")],
        key_points: Annotated[
            list[str], Field(min_length=1, max_length=8, description="The points to make, one per bullet.")
        ],
        tone: Annotated[Tone, Field(description="How the draft should read.")] = "neutral",
        confirmation_token: Annotated[
            str | None, Field(description="Supplied by the application after the user clicks Confirm. Never by you.")
        ] = None,
    ) -> EmailOutput:
        call = read_meta(ctx)
        started = now_micros()
        body = await asyncio.to_thread(
            _draft,
            deps,
            call=call,
            employee_id=employee_id,
            recipient_role=recipient_role,
            purpose=purpose,
            key_points=list(key_points),
            tone=tone,
        )
        ended = now_micros()
        body["_trace"] = envelope(call, server_timing_ms=max(0, (ended - started) // 1000), transport=deps.transport)
        return result(body, is_error=body["status"] == "confirmation_required")


def recipient_name(deps: ServerDeps, employee_id: str, recipient_role: str) -> str:
    """The person or team the draft is addressed to, resolved from the synthetic org map."""
    if recipient_role in TEAM_NAMES:
        return TEAM_NAMES[recipient_role]
    org = org_row(deps, employee_id)
    key = "manager_id" if recipient_role == "manager" else "skip_level_id"
    target = deps.employee(org.get(key)) if org.get(key) else None
    return str(target["legal_name"]) if target else TEAM_NAMES["people_ops"]


def compose(*, name: str, sender: str, purpose: str, key_points: list[str], tone: str) -> tuple[str, str]:
    """Subject and body, deterministically. Same arguments in, same bytes out — no model call."""
    subject = purpose if len(purpose) <= 78 else f"{purpose[:75]}..."
    bullets = "\n".join(f"- {point}" for point in key_points)
    body = "\n\n".join(
        [
            OPENING[tone].format(name=name),
            purpose,
            bullets,
            CLOSING[tone].format(sender=sender),
        ]
    )
    return subject, body


def human_summary(recipient_role: str, to_name: str, purpose: str) -> str:
    return f'Draft an email to {to_name} ({recipient_role}) about: "{purpose}".'


def _draft(
    deps: ServerDeps,
    *,
    call: CallMeta,
    employee_id: str,
    recipient_role: str,
    purpose: str,
    key_points: list[str],
    tone: str,
) -> dict[str, Any]:
    """The blocking half: the gate and, if it opens, the one `mock_writes` row."""
    to_name = recipient_name(deps, employee_id, recipient_role)
    preview = {
        "employee_id": employee_id,
        "recipient_role": recipient_role,
        "to_name": to_name,
        "purpose": purpose,
    }
    sender = deps.employee(employee_id)
    subject, body = compose(
        name=to_name,
        sender=str(sender["preferred_name"]) if sender else employee_id,
        purpose=purpose,
        key_points=key_points,
        tone=tone,
    )
    try:
        confirmation = confirm.validate(deps.store(), tool_name=TOOL_NAME, arguments=call.arguments)
        created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        draft_id = confirm.consume(
            deps.store(),
            confirmation,
            kind="hr_email",
            prefix=ID_PREFIX,
            employee_id=employee_id,
            payload={
                **preview,
                "subject": subject,
                "body": body,
                "tone": tone,
                "created_at": created_at,
                "sent": False,
                "mock": True,
            },
        )
    except confirm.ConfirmationRejected:
        return confirm.rejection(TOOL_NAME, human_summary(recipient_role, to_name, purpose), preview)
    return EmailOutput(
        status="drafted",
        draft_id=draft_id,
        to_role=recipient_role,
        to_name=to_name,
        subject=subject,
        body=body,
        created_at=created_at,
        sent=False,
        mock=True,
    ).model_dump(mode="json", exclude_none=True)


__all__ = ["ID_PREFIX", "TOOL_NAME", "EmailOutput", "RecipientRole", "Tone", "compose", "register"]
