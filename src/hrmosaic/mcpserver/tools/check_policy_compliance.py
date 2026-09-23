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
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from hrmosaic.core.db import now_micros
from hrmosaic.mcpserver import approvers as approver_chain
from hrmosaic.mcpserver import rules
from hrmosaic.mcpserver.server import (
    READ_ONLY,
    ServerDeps,
    envelope,
    invalid_arguments,
    not_found,
    read_meta,
    result,
)
from hrmosaic.mcpserver.tools.check_pto_balance import balance_row
from hrmosaic.mcpserver.tools.lookup_employee_profile import EMPLOYEE_ID
from hrmosaic.settings import settings

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


#: `request_type` is named with its three values because a rule is **guarded** on them (G5b): the
#: equipment scenario applies its USD 500 director threshold only to `request_type: "new"`, so a model
#: that omits the parameter, or invents a fourth word for it, gets a verdict with that requirement
#: silently unevaluated. A closed set a caller cannot see is a closed set a caller cannot honour.
#:
#: **And the parameter each guarded branch then measures is named too** (G5c, gap 4). `refresh` and
#: `separation` were published as branches with no stated input: `device_age_months` appeared nowhere
#: in `mcp/tools/check_policy_compliance.schema.json`, and the sentence defining `refresh` as "a
#: device at or past its 36-month cycle" described the *conclusion* the engine reaches from it rather
#: than the value it compares — an early refresh is exactly the case the branch exists to route.
#: A caller that cannot see the deciding field gets `not_stated` for the one row its own
#: `request_type` selected, which is `insufficient_evidence` and nothing else.
PARAMETERS_DESCRIPTION = (
    "Scenario facts the engine cannot read from the record, e.g. destination_country, start_date, "
    "end_date, days, amount_usd, category, transaction_date, reason, request_type, "
    "device_age_months, days_since_final_day. The submission "
    "date is the server's own — never send one — and notice is always computed by the engine from it "
    "against start_date, so any supplied notice value is ignored; duration_days and days are derived "
    'from start_date and end_date. request_type takes exactly one of "new" (a request for additional '
    'or upgraded equipment, priced in amount_usd), "refresh" (a laptop refresh, whose device_age_months '
    "is compared against the 36-month cycle: at or past it the refresh is due and is an IT ticket at "
    'any price, below it the refresh is early and needs manager approval) or "separation" (a return, '
    "whose days_since_final_day is compared against the return window), and the equipment "
    'director-approval threshold is evaluated only for "new".'
)

#: What `submitted_on` means, in the words the **result** publishes (W8, C04; W10, ruling 1).
#: It is no longer an input: six of the sixteen recorded demo paths supplied one, three of them the
#: request's own start date and three the mock data's frozen snapshot, and each was narrated as the
#: notice the request gave. A date the model chose is not evidence of when anything was submitted,
#: so the server sets it — `Settings.today()`, pinned by `MOCK_TODAY` for the recorded stubs — and
#: echoes it beside the business-day walk it made.
SUBMITTED_ON_DESCRIPTION = (
    "The date the request was submitted — the server's own date, never the caller's. Notice is "
    "measured from it, and `computed.notice_span` shows the business-day walk."
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
    #: `met` | `unmet` | `not_stated` (W8, C05). `met: false` used to mean both "checked and it
    #: fails" and "never checked", and an answer cannot tell those apart from a boolean — so a
    #: requirement nobody had evaluated was narrated as a settled failure.
    status: Literal["met", "unmet", "not_stated"] = "not_stated"
    #: Whether this row alone can stop the request (W10, ruling 3). `agent/**` never imports the
    #: server, so a caller deciding whether a write may be proposed has to read the flag off the
    #: wire; a `manual` check publishes `false` here however `rules.yml` marks it.
    blocking: bool = False
    reason: str
    #: The requirement's reader label from `corpus/rules.yml` — what the measured thing is called
    #: in front of a person (W8 fix round, JX3-01). The chat surface's restatement is built from it.
    label: str = ""
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
    #: The day the request is treated as submitted — what notice is measured from (W8, C04), and
    #: since W10 an **output only**: the server's own date, never the caller's.
    submitted_on: Annotated[str | None, Field(description=SUBMITTED_ON_DESCRIPTION)] = None
    #: Every figure the engine derived — notice, duration, tenure, the blackout span, the benefits
    #: dates — so the answer quotes them instead of computing them again (W8, C13, C22, C30).
    computed: dict[str, Any] | None = None
    requirements: list[Requirement] | None = None
    unmet: list[str] | None = None
    approvals_required: list[Approval] | None = None
    #: The approval roles above, resolved to the reader's own people (W8, C06).
    approvers: list[approver_chain.Approver] | None = None
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
        # **`submitted_on` is not a parameter** (W10, ruling 1). It is not the model's to supply:
        # the server sets it to its own today, and the result echoes it.
        call = read_meta(ctx)
        started = now_micros()
        try:
            body = await asyncio.to_thread(
                _compliance,
                deps,
                scenario=scenario,
                employee_id=employee_id,
                parameters=dict(parameters),
            )
        except rules.RuleError as exc:
            # An argument no verdict can be built on — `end_date` before `start_date` is the one the
            # live Berlin turn sent (W8, C05). §9.1's one repair round trip gets a chance at it; an
            # answer built on rows that evaluated nothing does not.
            return invalid_arguments([str(exc)])
        ended = now_micros()
        body["_trace"] = envelope(call, server_timing_ms=max(0, (ended - started) // 1000), transport=deps.transport)
        return result(body)


def _holidays(deps: ServerDeps, employee: dict[str, Any]) -> list[str]:
    """The observed company holidays of the employee's own office calendar."""
    office = next((row for row in deps.records("offices") if row["office_id"] == employee.get("office_id")), {})
    calendar_id = office.get("holiday_calendar_id")
    calendar = next((row for row in deps.records("holidays_2026") if row["holiday_calendar_id"] == calendar_id), None)
    return [] if calendar is None else [holiday["observed"] for holiday in calendar["holidays"]]


def submission_date(supplied: str = "") -> str:
    """Today (W8, C04; W10, ruling 1). `MOCK_TODAY` pins "today" for the recorded stubs.

    `supplied` survives for the tests and the internal callers that pin a submission date
    deliberately; nothing on the wire can reach it any more.
    """
    return supplied.strip() or settings.today().isoformat()


def approvers_for(deps: ServerDeps, employee_id: str, roles: Sequence[str]) -> list[approver_chain.Approver]:
    """The verdict's approval roles, resolved to people on the reader's own chain (W8, C06)."""
    employees = {str(row["employee_id"]): row for row in deps.records("employees")}
    managers = {str(row["employee_id"]): row.get("manager_id") for row in deps.records("org_manager_map")}
    for employee_id_key, record in employees.items():
        managers.setdefault(employee_id_key, record.get("manager_id"))
    return approver_chain.resolve_all(list(roles), actor_id=employee_id, employees=employees, managers=managers)


def _compliance(
    deps: ServerDeps,
    *,
    scenario: str,
    employee_id: str,
    parameters: dict[str, Any],
    submitted_on: str = "",
) -> dict[str, Any]:
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
            submitted_on=submission_date(submitted_on),
            rule_set=rule_set,
            connection=connection,
        )
    body["approvers"] = approvers_for(deps, employee_id, [approval["role"] for approval in body["approvals_required"]])
    return ComplianceOutput(**body).model_dump(mode="json", exclude_none=True)


__all__ = [
    "APPROVED_COUNTRIES_FACT",
    "COUNTRY_ALIASES",
    "COUNTRY_PARAMETERS",
    "SUBMITTED_ON_DESCRIPTION",
    "Approval",
    "Citation",
    "ComplianceOutput",
    "Evidence",
    "Requirement",
    "Scenario",
    "approvers_for",
    "normalise_country",
    "normalise_parameters",
    "register",
    "submission_date",
]
