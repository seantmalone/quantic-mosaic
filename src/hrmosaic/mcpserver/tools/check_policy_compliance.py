"""Tool 4 — the deterministic compliance engine (spec §8.4).

Zero LLM calls: `mcpserver/rules.py` is a pure function of `corpus/rules.yml`, `corpus/facts.yml`,
the employee's snapshot record and the caller's `parameters`. This module is the wire boundary — it
assembles the engine's inputs from the committed datasets and hands back its output verbatim.

`policy_topics` is accepted because §8.4 publishes it, and it is **advisory**: which requirements
apply is decided by the scenario's own `applies_when` guards, never by a topic list a model chose,
so a mistaken hint cannot change a verdict.

**`destination_country` is normalised to an ISO 3166-1 alpha-2 code here, at the wire boundary.**
`corpus/rules.yml`'s `remote.intl.destination` compares it with `in` against the code list in
`tax.approved_countries`, so a caller writing `"Germany"` was reported as travelling somewhere
unapproved — a wrong verdict produced by a spelling, and one live recordings of demo task 1 showed
`claude-haiku-4-5` producing reproducibly. Normalising here keeps `rules.py`'s closed grammar a
pure function of its inputs: the engine still only ever compares codes. An unrecognised name is
passed through untouched rather than guessed at, because a name the table does not know is not on
the approved list under any spelling and must keep failing the check.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from hrmosaic.core.db import now_micros
from hrmosaic.mcpserver import rules
from hrmosaic.mcpserver.server import READ_ONLY, ServerDeps, envelope, not_found, read_meta, result
from hrmosaic.mcpserver.tools.check_pto_balance import balance_row
from hrmosaic.mcpserver.tools.lookup_employee_profile import EMPLOYEE_ID

Scenario = Literal[
    "international_remote",
    "domestic_remote",
    "pto_request",
    "expense_claim",
    "equipment_request",
    "benefits_change",
    "conduct_escalation",
]

#: The fact whose value the `remote.intl.destination` requirement compares against — a
#: comma-separated ISO 3166-1 alpha-2 list. `tests/unit/test_country_normalisation.py` asserts every
#: code in it is reachable from `COUNTRY_ALIASES`, so adding an approved country without teaching
#: this table its name fails there rather than silently in a verdict.
APPROVED_COUNTRIES_FACT = "tax.approved_countries"

#: The parameter keys that carry a country. Only these are rewritten; `category: "Germany"` is not
#: a country and is left exactly as the caller sent it.
COUNTRY_PARAMETERS: tuple[str, ...] = ("destination_country",)

#: Names → ISO 3166-1 alpha-2, in the spellings `corpus/facts.yml`'s own quote uses ("Germany,
#: Ireland, the Netherlands, Portugal, Spain, Canada and Mexico"), plus the two everyday variants a
#: writer of English reaches for. Deliberately not a world country table: the only names whose
#: spelling can change a verdict are the approved destinations, and every other name has to fail the
#: `in` check whether it is normalised or not.
COUNTRY_ALIASES: dict[str, str] = {
    "germany": "DE",
    "ireland": "IE",
    "netherlands": "NL",
    "the netherlands": "NL",
    "holland": "NL",
    "portugal": "PT",
    "spain": "ES",
    "canada": "CA",
    "mexico": "MX",
}


def normalise_country(value: Any) -> Any:
    """`"Germany"` → `"DE"`, `"de"` → `"DE"`, anything else back unchanged.

    Non-strings are returned identically — `parameters` is `dict[str, str | float | bool]` and only
    the string half can carry a name.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if len(stripped) == 2 and stripped.isalpha():
        return stripped.upper()
    return COUNTRY_ALIASES.get(stripped.casefold(), value)


def normalise_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """A new mapping with every `COUNTRY_PARAMETERS` entry normalised; the caller's is untouched."""
    return {key: normalise_country(value) if key in COUNTRY_PARAMETERS else value for key, value in parameters.items()}


PARAMETERS_DESCRIPTION = (
    "Scenario facts the engine cannot read from the record, e.g. destination_country, "
    "duration_days, start_date, days, amount_usd, category, transaction_date. Notice days are "
    "always computed by the engine from start_date against the data snapshot and any supplied "
    "notice value is ignored."
)


class Evidence(BaseModel):
    chunk_id: str
    doc_id: str
    heading_path: str
    snippet: str


class Requirement(BaseModel):
    id: str
    text: str
    met: bool
    reason: str
    fact_key: str
    evidence: Evidence | None = None


class Approval(BaseModel):
    role: str
    reason: str
    doc_id: str
    heading_path: str


class Citation(BaseModel):
    chunk_id: str
    doc_id: str
    heading_path: str


class ComplianceOutput(BaseModel):
    """The §8.4 tool-4 result, or `{status: not_found}` for an unknown employee id."""

    scenario: str | None = None
    verdict: Literal["compliant", "conditional", "non_compliant", "insufficient_evidence"] | None = None
    as_of: str | None = None
    requirements: list[Requirement] | None = None
    unmet: list[str] | None = None
    approvals_required: list[Approval] | None = None
    next_steps: list[str] | None = None
    escalate_to: str | None = None
    citations: list[Citation] | None = None
    rules_version: str | None = None
    status: str | None = None
    code: str | None = None
    hint: str | None = None


def register(server: MCPServer, deps: ServerDeps) -> None:
    @server.tool(
        name="check_policy_compliance",
        description=(
            "Evaluate one HR scenario against the policy rules deterministically: which "
            "requirements apply, which are met, which approvals the request needs and what to do "
            "next, every requirement citing the policy section that backs it. No model judgement "
            "is involved."
        ),
        annotations=ToolAnnotations(**READ_ONLY),
    )
    async def check_policy_compliance(
        ctx: Context,
        scenario: Annotated[Scenario, Field(description="Which of the seven scenarios to evaluate.")],
        employee_id: Annotated[str, EMPLOYEE_ID],
        policy_topics: Annotated[
            list[str], Field(description="Advisory: topics the caller wants covered. Never changes a verdict.")
        ] = [],  # noqa: B006 - the schema publishes an empty-array default (§8.4); pydantic copies it per call
        parameters: Annotated[dict[str, str | float | bool], Field(description=PARAMETERS_DESCRIPTION)] = {},  # noqa: B006
    ) -> ComplianceOutput:
        call = read_meta(ctx)
        started = now_micros()
        body = await asyncio.to_thread(
            _compliance, deps, scenario=scenario, employee_id=employee_id, parameters=dict(parameters)
        )
        ended = now_micros()
        body["_trace"] = envelope(call, server_timing_ms=max(0, (ended - started) // 1000), transport=deps.transport)
        return result(body)


def _holidays(deps: ServerDeps, employee: dict[str, Any]) -> list[str]:
    """The observed company holidays of the employee's own office calendar."""
    office = next((row for row in deps.records("offices") if row["office_id"] == employee.get("office_id")), {})
    calendar_id = office.get("holiday_calendar_id")
    calendar = next((row for row in deps.records("holidays_2026") if row["holiday_calendar_id"] == calendar_id), None)
    return [] if calendar is None else [holiday["observed"] for holiday in calendar["holidays"]]


def _compliance(deps: ServerDeps, *, scenario: str, employee_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """The blocking half: the YAML load, the index lookups behind the evidence, the pure evaluation."""
    employee = deps.employee(employee_id)
    if employee is None:
        return not_found(employee_id)
    parameters = normalise_parameters(parameters)
    rule_set = rules.load_rules(deps.rules_path, deps.facts_path)
    connection = deps.index()
    with deps.lock:
        body = rules.evaluate(
            scenario,
            employee=employee,
            balance=balance_row(deps, employee_id) or {},
            parameters=parameters,
            holidays=_holidays(deps, employee),
            as_of=deps.as_of(),
            rule_set=rule_set,
            connection=connection,
        )
    return ComplianceOutput(**body).model_dump(mode="json", exclude_none=True)


__all__ = [
    "APPROVED_COUNTRIES_FACT",
    "COUNTRY_ALIASES",
    "COUNTRY_PARAMETERS",
    "Approval",
    "Citation",
    "ComplianceOutput",
    "Evidence",
    "Requirement",
    "Scenario",
    "normalise_country",
    "normalise_parameters",
    "register",
]
