"""The submission date is the server's, and `days` is derived (W10, rulings 1 and 2).

Two causes between them account for eleven of the sixteen recorded demo paths
(`scenario-recheck-2026-09-16.md`), and both are the same mistake: a figure the verdict turns on
was left to the model.

* **`submitted_on`.** Six paths supplied one — three the request's own `start_date` (04, 05, 07),
  three the mock data's frozen `as_of` (01, 03, 15) — and each was narrated back as the notice the
  request gave: *"you are submitting on 29 September for time off starting the same day"*, on a
  request made eight business days ahead. Notice is *how much warning a request gives*, so it is
  measured from the day the server received it and from nothing a caller can send.
* **`days`.** Five paths (04–07, 09) left it out, so `pto.request.balance` — the one *blocking* PTO
  requirement — came back `not_stated` on all five, and two of them filed a ticket for a request
  nobody had checked the reader could afford. A span written as two dates states its own day count.

The engine echoes both walks, so the answer quotes them instead of deriving a second opinion.
"""

from __future__ import annotations

import json

import pytest
from mcp import Client

from hrmosaic.mcpserver import rules
from hrmosaic.mcpserver.server import DEFAULT_ACTOR, ServerDeps, build_hr_server
from hrmosaic.mcpserver.tools.check_policy_compliance import submission_date
from hrmosaic.settings import settings

pytestmark = pytest.mark.anyio

DEPS = ServerDeps()
RULE_SET = rules.load_rules(DEPS.rules_path, DEPS.facts_path)

#: Tuesday 29 September to Friday 2 October 2026 — the span scenario 04's turn actually requested,
#: and four business days however many calendar days it spans.
SPAN = {"start_date": "2026-09-29", "end_date": "2026-10-02"}


async def call(tool: str, arguments: dict) -> dict:
    async with Client(build_hr_server(DEPS)) as client:
        result = await client.call_tool(tool, arguments)
    return json.loads(result.content[0].text)


# -- ruling 1: `submitted_on` is not the model's to supply ------------------------------


async def test_the_model_facing_schema_publishes_no_submitted_on():
    async with Client(build_hr_server(DEPS)) as client:
        listed = await client.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    published = tools["check_policy_compliance"].input_schema["properties"]
    assert "submitted_on" not in published, "a date the model chose is not evidence of a submission"
    assert set(published) == {"scenario", "employee_id", "policy_topics", "parameters"}


async def test_the_result_echoes_the_servers_own_date_and_the_walk_it_made():
    body = await call(
        "check_policy_compliance",
        {"scenario": "pto_request", "employee_id": DEFAULT_ACTOR, "parameters": SPAN},
    )
    today = settings.today().isoformat()
    assert body["submitted_on"] == today == submission_date()
    assert body["computed"]["submitted_on"] == today
    # The span the engine walked, in the words an answer may quote — not a number it must re-derive.
    # 18, not 19: Boston observes Labor Day on Monday 7 September, and the walk knows it.
    assert body["computed"]["notice_business_days"] == 18
    assert body["computed"]["notice_span"] == ("Tuesday 1 September to Tuesday 29 September: 18 business days' notice")


# -- ruling 2: `days` is derived from the span -----------------------------------------


def test_two_dates_state_their_own_business_day_count():
    derived = rules.derive_parameters(SPAN)
    assert derived["days"] == 4, "29, 30 September, 1, 2 October"
    assert derived["duration_days"] == 4


def test_a_holiday_inside_the_span_is_not_a_business_day():
    from datetime import date

    holidays = frozenset({date(2026, 9, 30)})
    assert rules.derive_parameters(SPAN, holidays)["days"] == 3


def test_a_supplied_days_is_never_overwritten():
    assert rules.derive_parameters({**SPAN, "days": 2})["days"] == 2


async def test_the_blocking_balance_rule_is_evaluable_whenever_the_dates_are_there():
    """Scenario 06: `days` absent → `not_stated` → verdict `conditional` → a ticket filed for a
    request against a balance of 0.25 days."""
    body = await call(
        "check_policy_compliance",
        {"scenario": "pto_request", "employee_id": "E1108", "parameters": SPAN},
    )
    balance = next(row for row in body["requirements"] if row["id"] == "pto.request.balance")
    assert balance["blocking"] is True
    assert balance["status"] == "unmet", "0.25 days does not cover four"
    assert body["verdict"] == "non_compliant"


async def test_the_result_echoes_the_span_it_walked():
    body = await call(
        "check_policy_compliance",
        {"scenario": "pto_request", "employee_id": DEFAULT_ACTOR, "parameters": SPAN},
    )
    assert body["computed"]["business_days"] == 4
    assert body["computed"]["business_day_span"] == "Tuesday 29 September to Friday 2 October: 4 business days"


async def test_a_manual_row_publishes_blocking_false_however_the_file_marks_it():
    """Ruling 3 reads this flag, and a `manual` row is never blocking: `pto.request.manager_approval`
    is `not_stated` on every PTO turn, and counting it would file no ticket ever again."""
    body = await call(
        "check_policy_compliance",
        {"scenario": "pto_request", "employee_id": DEFAULT_ACTOR, "parameters": SPAN},
    )
    manual = next(row for row in body["requirements"] if row["id"] == "pto.request.manager_approval")
    assert (manual["status"], manual["blocking"]) == ("not_stated", False)
