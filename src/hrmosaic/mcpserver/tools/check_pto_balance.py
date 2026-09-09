"""Tool 6 — the PTO balance, stated against the snapshot (spec §8.4).

Two dates, and the difference between them is the whole point:

* `as_of` is the **snapshot** the balance is true at (`2026-09-01`, from the dataset banner). Every
  number below is computed against it.
* `computed_at` is the real wall clock, for the audit trail only.

`remaining_days` is **computed**, never copied:
`accrued_ytd − used_ytd − pending_days + carryover_unexpired`, where `carryover_unexpired` is 0.0
when `carryover_expires_on` is absent or falls before the snapshot. A `requested_as_of` later than
the snapshot is echoed and answered *from* the snapshot with a note saying so — the tool never
extrapolates and never reads the wall clock for arithmetic, so the demo narration stays true
whenever it is replayed.

`accrual_rate_days_per_month` is the `facts.yml` value for the employee's tenure band, carried on
the dataset row with its `accrual_fact_key`: `E1042` is 45 months tenured at the snapshot, so 1.50,
not the under-3y 1.25.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from hrmosaic.core.db import now_micros
from hrmosaic.mcpserver.server import READ_ONLY, ServerDeps, envelope, not_found, read_meta, result
from hrmosaic.mcpserver.tools.lookup_employee_profile import EMPLOYEE_ID

POLICY_DOC_ID = "pto-and-holidays"


class BalanceOutput(BaseModel):
    """The §8.4 tool-6 result, or `{status: not_found}` — every field is optional for that reason."""

    employee_id: str | None = None
    as_of: str | None = None
    requested_as_of: str | None = None
    computed_at: str | None = None
    accrual_rate_days_per_month: float | None = None
    accrual_fact_key: str | None = None
    accrued_ytd: float | None = None
    used_ytd: float | None = None
    pending_days: float | None = None
    carryover_from_prior_year: float | None = None
    carryover_expires_on: str | None = None
    carryover_unexpired: float | None = None
    remaining_days: float | None = None
    next_accrual_date: str | None = None
    blackout_dates: list[str] | None = None
    policy_doc_id: str | None = None
    note: str | None = None
    status: str | None = None
    code: str | None = None
    hint: str | None = None


def balance_row(deps: ServerDeps, employee_id: str) -> dict[str, Any] | None:
    return next((row for row in deps.records("pto_balances") if row["employee_id"] == employee_id), None)


def unexpired_carryover(row: dict[str, Any], snapshot: date) -> float:
    """Carryover still usable at the snapshot — 0.0 when it has no expiry or expired before it."""
    expires = row.get("carryover_expires_on")
    if not expires:
        return 0.0
    return float(row.get("carryover_from_prior_year", 0.0)) if date.fromisoformat(expires) >= snapshot else 0.0


def register(server: MCPServer, deps: ServerDeps) -> None:
    @server.tool(
        name="check_pto_balance",
        description=(
            "The employee's PTO balance at the data snapshot: accrual rate, accrued and used days, "
            "pending requests, carryover and the computed remaining days, plus the blackout dates. "
            "A requested as_of later than the snapshot is echoed and answered from the snapshot."
        ),
        annotations=ToolAnnotations(**READ_ONLY),
    )
    async def check_pto_balance(
        ctx: Context,
        employee_id: Annotated[str, EMPLOYEE_ID],
        as_of: Annotated[
            str | None,
            Field(
                pattern=r"^\d{4}-\d{2}-\d{2}$",
                description="An ISO-8601 date the caller cares about; echoed as requested_as_of.",
            ),
        ] = None,
    ) -> BalanceOutput:
        call = read_meta(ctx)
        started = now_micros()
        body = await asyncio.to_thread(_balance, deps, employee_id=employee_id, requested_as_of=as_of)
        ended = now_micros()
        body["_trace"] = envelope(call, server_timing_ms=max(0, (ended - started) // 1000), transport=deps.transport)
        return result(body)


def _balance(deps: ServerDeps, *, employee_id: str, requested_as_of: str | None) -> dict[str, Any]:
    """The blocking half: one cached JSON read plus the identity. Always inside `asyncio.to_thread`."""
    row = balance_row(deps, employee_id)
    if row is None:
        return not_found(employee_id)
    snapshot_text = str(row.get("as_of") or deps.as_of("pto_balances"))
    snapshot = date.fromisoformat(snapshot_text)
    carryover_unexpired = unexpired_carryover(row, snapshot)
    remaining = float(row["accrued_ytd"]) - float(row["used_ytd"]) - float(row["pending_days"]) + carryover_unexpired
    return BalanceOutput(
        employee_id=employee_id,
        as_of=snapshot_text,
        requested_as_of=requested_as_of,
        computed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        accrual_rate_days_per_month=float(row["accrual_rate_days_per_month"]),
        accrual_fact_key=row["accrual_fact_key"],
        accrued_ytd=float(row["accrued_ytd"]),
        used_ytd=float(row["used_ytd"]),
        pending_days=float(row["pending_days"]),
        carryover_from_prior_year=float(row["carryover_from_prior_year"]),
        carryover_expires_on=row.get("carryover_expires_on"),
        carryover_unexpired=carryover_unexpired,
        remaining_days=round(remaining, 2),
        next_accrual_date=row["next_accrual_date"],
        blackout_dates=list(row["blackout_dates"]),
        policy_doc_id=POLICY_DOC_ID,
        note=f"Balances are a synthetic snapshot as of {snapshot_text}.",
    ).model_dump(mode="json", exclude_none=True)


__all__ = ["BalanceOutput", "balance_row", "register", "unexpired_carryover"]
