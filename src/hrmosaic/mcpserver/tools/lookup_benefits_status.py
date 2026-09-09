"""Tool 7 — benefits eligibility and elections (spec §8.4).

`eligible` is computed against the snapshot `as_of`, never the wall clock, for the same reason as
tool 6: the 90-day waiting period of a September-2026 hire must read the same in the demo video as
it does a year later. `E1108`'s waiting period ends `2026-11-13`, after the `2026-09-01` snapshot,
so that employee is the corpus's worked "not yet eligible" case.

`qualifying_life_event_window_open` is read from the dataset row rather than hard-coded false, so a
future dataset that gives an employee a life event needs no code change here.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from hrmosaic.core.db import now_micros
from hrmosaic.mcpserver.server import READ_ONLY, ServerDeps, envelope, not_found, read_meta, result
from hrmosaic.mcpserver.tools.lookup_employee_profile import EMPLOYEE_ID

POLICY_DOC_ID = "benefits-and-open-enrollment"

PlanType = Literal["medical", "dental", "vision", "retirement_401k", "hsa", "fsa", "life", "all"]


class Election(BaseModel):
    plan_type: str
    plan_id: str
    plan_name: str
    tier: str
    effective_date: str
    employee_cost_monthly: float


class EnrollmentWindow(BaseModel):
    open: str
    close: str


class BenefitsOutput(BaseModel):
    """The §8.4 tool-7 result, or `{status: not_found}` — every field is optional for that reason."""

    employee_id: str | None = None
    plan_year: int | None = None
    as_of: str | None = None
    eligible: bool | None = None
    eligibility_reason: str | None = None
    waiting_period_ends: str | None = None
    elections: list[Election] | None = None
    dependents: int | None = None
    open_enrollment_window: EnrollmentWindow | None = None
    qualifying_life_event_window_open: bool | None = None
    policy_doc_id: str | None = None
    status: str | None = None
    code: str | None = None
    hint: str | None = None


def register(server: MCPServer, deps: ServerDeps) -> None:
    @server.tool(
        name="lookup_benefits_status",
        description=(
            "Benefits eligibility and current elections at the data snapshot, with the open-"
            "enrollment window. Eligibility is computed against the snapshot, not today's date."
        ),
        annotations=ToolAnnotations(**READ_ONLY),
    )
    async def lookup_benefits_status(
        ctx: Context,
        employee_id: Annotated[str, EMPLOYEE_ID],
        plan_type: Annotated[PlanType, Field(description="Filter the elections; 'all' returns them all.")] = "all",
    ) -> BenefitsOutput:
        call = read_meta(ctx)
        started = now_micros()
        body = await asyncio.to_thread(_benefits, deps, employee_id=employee_id, plan_type=plan_type)
        ended = now_micros()
        body["_trace"] = envelope(call, server_timing_ms=max(0, (ended - started) // 1000), transport=deps.transport)
        return result(body)


def _benefits(deps: ServerDeps, *, employee_id: str, plan_type: str) -> dict[str, Any]:
    """The blocking half: one cached JSON read. Always inside `asyncio.to_thread`."""
    row = next((item for item in deps.records("benefits_elections") if item["employee_id"] == employee_id), None)
    if row is None:
        return not_found(employee_id)
    snapshot_text = str(row.get("as_of") or deps.as_of("benefits_elections"))
    waiting_period_ends = row["waiting_period_ends"]
    eligible = date.fromisoformat(waiting_period_ends) <= date.fromisoformat(snapshot_text)
    elections = [
        Election(**election)
        for election in row["elections"]
        if plan_type == "all" or election["plan_type"] == plan_type
    ]
    return BenefitsOutput(
        employee_id=employee_id,
        plan_year=int(row["plan_year"]),
        as_of=snapshot_text,
        eligible=eligible,
        eligibility_reason=row["eligibility_reason"],
        waiting_period_ends=waiting_period_ends,
        elections=elections,
        dependents=int(row["dependents"]),
        open_enrollment_window=EnrollmentWindow(**row["open_enrollment_window"]),
        qualifying_life_event_window_open=bool(row.get("qualifying_life_event_window_open", False)),
        policy_doc_id=POLICY_DOC_ID,
    ).model_dump(mode="json", exclude_none=True)


__all__ = ["BenefitsOutput", "Election", "EnrollmentWindow", "PlanType", "register"]
