"""`tools_disabled` is enforced at the call boundary, over a real MCP session (G5c, gap 3).

The filter is the union of the operator's `MCP_TOOLS_DISABLED` and the request's own
`options.tools_disabled` (§13.9), and until now it governed only the `tools` array handed to the
model. §9.2's gate re-checked it before every **model-issued** call, so a model could not reach a
withheld tool — but the orchestrator's own calls never asked. The deterministic profile read is the
one that mattered: `evaluation/results/r_1790111270_no_structured_tools.json` lists
`lookup_employee_profile` in `config.tools_disabled` and 8 of its 30 items record it in
`scores.tools_called`, two of them scoring workflow completion 1.0 on the result — an ablation arm
whose stated intervention did not happen.

`Orchestrator._call` now refuses a withheld tool for **every** path (the act loop, its one repair,
the three deterministic calls and `_resume`'s re-issue of a gated write);
`tests/unit/test_mcp_tools_disabled_default.py` pins that refusal and its span. This file drives the
whole profile-debt turn against the **mounted server over loopback HTTP** — the same wire the
deployed agent uses — so "no call reached the server" is a claim about a real MCP session and not
about a stand-in that could not have made one. `check_pto_balance` on the same turn is the control:
it is not disabled, it reaches the server, and its span carries the server's own timing.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent.orchestrator import ChatOptions, ChatRequest

pytestmark = pytest.mark.anyio

PROFILE = "lookup_employee_profile"
QUESTION = "How many PTO days do I have?"


def _tool_spans(store, turn_id: str) -> list[dict]:
    rows = store.execute(
        "SELECT name, status, payload_json FROM spans WHERE turn_id = ? AND kind = 'tool_call' ORDER BY seq",
        (turn_id,),
    ).dicts()
    return [{"name": row["name"], "status": row["status"], "payload": json.loads(row["payload_json"])} for row in rows]


async def _debt_turn(run_agent, url: str, *, disabled: list[str]):
    return await run_agent(
        "profile_debt.json",
        ChatRequest(
            message=QUESTION,
            employee_id="E1042",
            options=ChatOptions(tools_disabled=disabled),
        ),
        url=url,
    )


async def test_the_profile_debt_never_reaches_the_server_when_the_request_disables_the_tool(
    run_agent, mounted_mcp_url, store
):
    """`remote-003`'s shape under the `no_structured_tools` arm: the debt is owed and not settled."""
    response = await _debt_turn(run_agent, mounted_mcp_url, disabled=[PROFILE])
    spans = _tool_spans(store, response.turn_id)

    served = [span for span in spans if span["name"] == PROFILE and span["payload"]["server_timing_ms"] is not None]
    assert served == [], "no `tools/call` for a disabled tool may be answered by the server"
    for span in (span for span in spans if span["name"] == PROFILE):
        # If the boundary is ever reached at all, it is reached as a refusal and nothing else.
        assert span["status"] == "error" and span["payload"]["error_code"] == "TOOL_DISABLED"

    # The control, on the same turn and the same session: an undisabled tool *is* answered by the
    # server, so the assertion above is about the filter and not about a broken transport.
    balance = next(span for span in spans if span["name"] == "check_pto_balance")
    assert balance["status"] == "ok"
    assert balance["payload"]["server_timing_ms"] is not None

    # The turn still answers. A disabled tool degrades the turn exactly as an unavailable one does,
    # which is the behaviour the arm is supposed to be measuring.
    assert response.outcome == "answered"
    assert response.answer.strip()


async def test_the_same_turn_reads_the_profile_when_nothing_is_disabled(run_agent, mounted_mcp_url, store):
    """The other direction, against the same script: the debt is real, and it is normally settled by
    a `tools/call` the server answers. Without this the test above would pass on a turn that had no
    profile debt to suppress."""
    response = await _debt_turn(run_agent, mounted_mcp_url, disabled=[])
    spans = _tool_spans(store, response.turn_id)

    profile = [span for span in spans if span["name"] == PROFILE]
    assert len(profile) == 1, "the deterministic read, once"
    assert profile[0]["status"] == "ok"
    assert profile[0]["payload"]["server_timing_ms"] is not None, "answered by the server"


async def test_the_record_does_not_claim_a_read_that_was_withheld(run_agent, mounted_mcp_url, store):
    """The `plan` span is what §13.4 reads. A withheld tool must not leave a
    `profile_read_deterministically` reminder behind it, and must not appear among the tools called."""
    response = await _debt_turn(run_agent, mounted_mcp_url, disabled=[PROFILE])

    called = [span["name"] for span in _tool_spans(store, response.turn_id) if span["status"] == "ok"]
    assert PROFILE not in called
    assert "check_pto_balance" in called

    nudges = [
        nudge
        for row in store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'plan'", (response.turn_id,)
        ).dicts()
        for nudge in json.loads(row["payload_json"]).get("nudges") or []
    ]
    assert "profile_read_deterministically" not in nudges, nudges
