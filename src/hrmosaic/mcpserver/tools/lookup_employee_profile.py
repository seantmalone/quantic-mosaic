"""Tool 5 — one employee's profile from the committed mock data (spec §8.4).

Everything here is synthetic (§17 *PII*): no SSN, no date of birth, no street address, `.example`
emails, 555-block phones. An unknown id is a **successful** result carrying
`{"status": "not_found", "code": "EMPLOYEE_NOT_FOUND", "hint": …}` (§8.3), not an error, because the
orchestrator turns it into a clarification turn rather than a repair round-trip.

`tenure_months_at_as_of` is the dataset's own field, computed against the `as_of: 2026-09-01`
snapshot by the P3 generator — never against the wall clock, which is why a verdict computed months
from now still matches the demo narration.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from hrmosaic.core.db import now_micros
from hrmosaic.mcpserver.server import READ_ONLY, ServerDeps, envelope, not_found, read_meta, result

EMPLOYEE_ID = Field(pattern=r"^E1[0-9]{3}$", description="An employee id, e.g. E1042.")


class Office(BaseModel):
    office_id: str
    city: str
    country: str
    timezone: str
    entity: str


class Person(BaseModel):
    employee_id: str
    preferred_name: str
    title: str


class ProfileOutput(BaseModel):
    """The §8.4 tool-5 record, or `{status: not_found}` — every field is optional for that reason."""

    employee_id: str | None = None
    as_of: str | None = None
    preferred_name: str | None = None
    legal_name: str | None = None
    title: str | None = None
    department: str | None = None
    employment_type: str | None = None
    fte: float | None = None
    level: str | None = None
    hire_date: str | None = None
    tenure_months_at_as_of: int | None = None
    work_arrangement: str | None = None
    work_country: str | None = None
    office: Office | None = None
    manager: Person | None = None
    skip_level: Person | None = None
    status: str | None = None
    code: str | None = None
    hint: str | None = None


def person(deps: ServerDeps, employee_id: str | None) -> Person | None:
    """The short form of one employee — how a manager or skip level appears on someone else's row."""
    record = deps.employee(employee_id) if employee_id else None
    if record is None:
        return None
    return Person(employee_id=record["employee_id"], preferred_name=record["preferred_name"], title=record["title"])


def org_row(deps: ServerDeps, employee_id: str) -> dict[str, Any]:
    return next((row for row in deps.records("org_manager_map") if row["employee_id"] == employee_id), {})


def register(server: MCPServer, deps: ServerDeps) -> None:
    @server.tool(
        name="lookup_employee_profile",
        description=(
            "Look up one employee's synthetic HR profile: role, office, work arrangement, tenure at "
            "the data snapshot, manager and skip level. An unknown id returns status='not_found'."
        ),
        annotations=ToolAnnotations(**READ_ONLY),
    )
    async def lookup_employee_profile(
        ctx: Context,
        employee_id: Annotated[str, EMPLOYEE_ID],
    ) -> ProfileOutput:
        call = read_meta(ctx)
        started = now_micros()
        body = await asyncio.to_thread(_profile, deps, employee_id=employee_id)
        ended = now_micros()
        body["_trace"] = envelope(call, server_timing_ms=max(0, (ended - started) // 1000), transport=deps.transport)
        return result(body)


def _profile(deps: ServerDeps, *, employee_id: str) -> dict[str, Any]:
    """The blocking half: six cached JSON reads. Always inside `asyncio.to_thread`."""
    record = deps.employee(employee_id)
    if record is None:
        return not_found(employee_id)
    office_row = next((row for row in deps.records("offices") if row["office_id"] == record["office_id"]), None)
    org = org_row(deps, employee_id)
    return ProfileOutput(
        employee_id=record["employee_id"],
        as_of=deps.as_of(),
        preferred_name=record["preferred_name"],
        legal_name=record["legal_name"],
        title=record["title"],
        department=record["department"],
        employment_type=record["employment_type"],
        fte=record["fte"],
        level=record["level"],
        hire_date=record["hire_date"],
        tenure_months_at_as_of=record["tenure_months_at_as_of"],
        work_arrangement=record["work_arrangement"],
        work_country=record["work_country"],
        office=Office(**{key: office_row[key] for key in Office.model_fields}) if office_row else None,
        manager=person(deps, org.get("manager_id") or record.get("manager_id")),
        skip_level=person(deps, org.get("skip_level_id")),
    ).model_dump(mode="json", exclude_none=True)


__all__ = ["EMPLOYEE_ID", "Office", "Person", "ProfileOutput", "org_row", "person", "register"]
