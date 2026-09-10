"""The act loop's budgets produce a graceful partial answer, never a hang (spec §9.4).

Every turn records a `stop_reason`, and exceeding a budget is one of them: the loop stops, an
`error` span carries the reason, the turn closes `partial` — which §13.4's confusion matrix
classifies as `answer`, "a budget-limited but genuine answer, not a refusal" — and the reader is
told, in the first block, that the answer is incomplete before they read it.

`AGENT_WALL_CLOCK_S` is the third budget and is checked the same way, at the top of every step; it
is not exercised here because a test that has to burn 90 s of wall clock to prove it would be the
slowest thing in the suite by two orders of magnitude. The three checks share one code path and one
`stop_reason` vocabulary.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent.orchestrator import BUDGET_NOTE, ChatRequest
from hrmosaic.settings import settings

pytestmark = pytest.mark.anyio

QUESTION = "Tell me everything about PTO accrual, carryover and caps."


def act_calls(records) -> list[dict]:
    return [payload for kind, _, payload in records if kind == "llm_call" and payload["purpose"] == "act"]


async def test_the_step_budget_stops_the_loop_and_says_so(run_agent, spans, monkeypatch):
    monkeypatch.setattr(settings, "agent_max_steps", 2)

    response = await run_agent("budget_probe.json", ChatRequest(message=QUESTION, employee_id="E1042"))
    records = spans(response.turn_id)

    assert response.outcome == "partial"
    assert len(act_calls(records)) == 2, "the third step was never started"
    errors = [payload for kind, _, payload in records if kind == "error"]
    assert [payload["error_kind"] for payload in errors] == ["max_steps"]
    assert errors[0]["component"] == "agent_loop"

    assert response.answer_blocks[0].type == "recommendation"
    assert response.answer_blocks[0].text == BUDGET_NOTE["max_steps"]
    assert response.answer.startswith("Recommendation — not company policy: I reached my step limit")


async def test_the_tool_call_budget_stops_the_loop_and_says_so(run_agent, spans, monkeypatch):
    monkeypatch.setattr(settings, "agent_max_tool_calls", 1)

    response = await run_agent("budget_probe.json", ChatRequest(message=QUESTION, employee_id="E1042"))
    records = spans(response.turn_id)

    assert response.outcome == "partial"
    assert response.usage.tool_calls == 1
    errors = [payload for kind, _, payload in records if kind == "error"]
    assert [payload["error_kind"] for payload in errors] == ["max_tool_calls"]
    assert response.answer_blocks[0].text == BUDGET_NOTE["max_tool_calls"]


async def test_a_turn_inside_its_budgets_answers_and_records_no_error(run_agent, spans):
    """The control, on a script that stops by itself: nothing degraded and no note prepended.

    A different script on purpose. `budget_probe.json` never stops asking for tools — that is what
    makes it a budget probe — so under the shipped budgets it would run until the script ran out,
    which proves nothing about a turn that finishes.
    """
    assert settings.agent_max_steps == 6 and settings.agent_max_tool_calls == 8
    response = await run_agent(
        "injection_probe.json",
        ChatRequest(message="What should I do about a suspicious phishing email?", employee_id="E1042"),
    )

    assert response.outcome == "answered"
    assert [kind for kind, _, _ in spans(response.turn_id) if kind == "error"] == []
    assert response.answer_blocks[0].type == "policy_fact"
