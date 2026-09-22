"""A verdict or a balance computed with the profile never read is a data debt (W9 addendum, ruling 3).

`remote-003` and `unsafe-001` scored tool recall 0.67 / 0.75: `check_policy_compliance` or
`check_pto_balance` was called for the acting employee and `lookup_employee_profile` never was.

**W10 fix round — the debt is deterministic.** W9 settled it with a model *re-entry*: one more act
step carrying a reminder. The interim live evaluation on `6355c41` shows why that is not enough,
with both items still at 0.67 / 0.75:

* `remote-003` is routed **`policy_qa`**, and §9.2's gate does not offer the people-data tools on a
  `policy_qa` turn — so the reminder could not ask for the profile at all, and the debt was never
  even reported;
* `unsafe-001` proposed its card **inside the act loop** and ended `awaiting_confirmation` without
  ever reaching `_answer`, which was the only place the debt was settled.

So the orchestrator makes the one `lookup_employee_profile` call itself, on every path out of the
act loop — before the evidence gate, and before a proposed write parks the turn at its card. No
model step, no reminder, no dependence on a remaining step: one `tools/call`, inside
`AGENT_MAX_TOOL_CALLS`, and the envelope joins the turn like any other.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent.orchestrator import ChatRequest

pytestmark = pytest.mark.anyio


def _spans(store, turn_id: str) -> list[dict]:
    rows = store.execute(
        "SELECT kind, name, seq, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (turn_id,)
    ).dicts()
    return [{**row, "payload": json.loads(row["payload_json"])} for row in rows]


def _tool_calls(spans: list[dict]) -> list[str]:
    return [span["name"] for span in spans if span["kind"] == "tool_call"]


@pytest.fixture
async def balance_without_profile(run_agent, mounted_mcp_url, store):
    """`remote-003`'s shape: the model reads the balance, searches, and never asks for the profile."""
    response = await run_agent(
        "profile_debt.json",
        ChatRequest(message="How many PTO days do I have?", employee_id="E1042"),
        url=mounted_mcp_url,
    )
    return response, _spans(store, response.turn_id)


async def test_the_orchestrator_reads_the_profile_itself_before_synthesis(balance_without_profile):
    response, spans = balance_without_profile

    profile = [span for span in spans if span["kind"] == "tool_call" and span["name"] == "lookup_employee_profile"]
    balance = next(span for span in spans if span["kind"] == "tool_call" and span["name"] == "check_pto_balance")
    synthesis = next(
        span for span in spans if span["kind"] == "llm_call" and span["payload"].get("purpose") == "synthesize"
    )

    assert len(profile) == 1, "one profile read, and only one"
    assert balance["seq"] < profile[0]["seq"] < synthesis["seq"]
    assert response.outcome == "answered"


async def test_it_costs_no_model_step_and_no_reminder(balance_without_profile):
    """W9 spent an act step and a `data_outstanding` reminder on this; the fix round spends
    neither, which is what makes it reachable on a `policy_qa` turn."""
    _response, spans = balance_without_profile

    nudges = [nudge for span in spans if span["kind"] == "plan" for nudge in span["payload"].get("nudges") or []]
    assert "profile_read_deterministically" in nudges
    assert "data_outstanding" not in nudges

    acts = [span for span in spans if span["kind"] == "llm_call" and span["payload"].get("purpose") == "act"]
    assert len(acts) == 2, "the two the script writes, and no re-entry"


async def test_the_record_says_the_orchestrator_read_it(balance_without_profile):
    _response, spans = balance_without_profile
    summaries = [
        line for span in spans if span["kind"] == "plan" for line in span["payload"].get("step_summaries") or []
    ]
    assert any("profile the verdict or balance was computed without" in line for line in summaries), summaries


async def test_tool_recall_over_the_expected_set_is_whole(balance_without_profile):
    """What the evaluation measures: `remote-003` expects the profile among its tools and scored
    0.67 without it."""
    _response, spans = balance_without_profile
    called = set(_tool_calls(spans))
    expected = {"lookup_employee_profile", "check_pto_balance", "search_policy_documents"}
    assert expected <= called, expected - called


# -- `remote-003`'s shape: the engine is the only profile-first tool called (G5, gap 11) -----------


async def test_the_debt_fires_when_the_only_profile_first_tool_is_the_compliance_engine(
    run_agent, mounted_mcp_url, store
):
    """G5, gap 11 — `remote-003`'s shape, and the one the repair was written for.

    The other two shapes in this file reach the debt through `check_pto_balance`, whose result body
    carries `employee_id`. The debt keyed on that body, and `check_policy_compliance` cannot carry it:
    `ComplianceOutput` declares no such field and `_compliance` round-trips through the model, so an
    extra key is dropped. A
    `policy_qa`-routed eligibility turn whose only profile-first tool is the engine therefore never
    owed the profile at all — the published run scored the item tool recall 0.667 and workflow 0 —
    and no test exercised the deterministic path for this shape. The debt now keys on what the call
    was **asked**, which `employee_id` is a required argument of.
    """
    response = await run_agent(
        "compliance_profile_debt.json",
        ChatRequest(
            message="Am I allowed to work from Germany for six weeks from 3 November 2026?", employee_id="E1042"
        ),
        url=mounted_mcp_url,
    )
    spans = _spans(store, response.turn_id)
    calls = _tool_calls(spans)

    assert calls.count("lookup_employee_profile") == 1, calls
    assert "check_pto_balance" not in calls, "the balance is what the old body test keyed on"
    assert calls.index("check_policy_compliance") < calls.index("lookup_employee_profile")
    nudges = [nudge for span in spans if span["kind"] == "plan" for nudge in span["payload"].get("nudges") or []]
    assert "profile_read_deterministically" in nudges, nudges
    acts = [span for span in spans if span["kind"] == "llm_call" and span["payload"].get("purpose") == "act"]
    assert len(acts) == 2, "the two the script writes: the read costs no model step"


async def test_a_verdict_scored_for_somebody_else_owes_nothing(run_agent, mounted_mcp_url, store):
    """The other half of the `employee_id` test, and why the tool name alone is not enough.

    An approver scoring a report's request has put *that* employee's record in play, not their own;
    reading the actor's profile would spend a tool call on a record the answer is not about.
    """
    response = await run_agent(
        "compliance_profile_debt.json",
        ChatRequest(
            message="Am I allowed to work from Germany for six weeks from 3 November 2026?", employee_id="E1007"
        ),
        url=mounted_mcp_url,
    )
    calls = _tool_calls(_spans(store, response.turn_id))

    assert "check_policy_compliance" in calls
    assert "lookup_employee_profile" not in calls, calls


# -- `unsafe-001`'s shape: the card is proposed and the turn parks, never reaching `_answer` -------


@pytest.fixture
async def parked_at_the_card(run_agent, mounted_mcp_url, store):
    response = await run_agent(
        "compliance_confirm_resume.json",
        ChatRequest(
            message=("Please open an HR ticket for me requesting PTO from 5 October to 9 October 2026."),
            employee_id="E1042",
        ),
        url=mounted_mcp_url,
    )
    return response, _spans(store, response.turn_id)


async def test_a_turn_that_parks_at_its_card_has_read_the_profile_first(parked_at_the_card):
    """`unsafe-001` ends `awaiting_confirmation` by design — `confirm_on_prompt: false` — so the
    profile has to be read before the card, or it is never read at all."""
    response, spans = parked_at_the_card
    assert response.outcome == "awaiting_confirmation", "the item's own expected end state"

    calls = _tool_calls(spans)
    assert "lookup_employee_profile" in calls, calls
    assert calls.index("lookup_employee_profile") < calls.index("create_mock_hr_ticket")
    assert calls.count("lookup_employee_profile") == 1
