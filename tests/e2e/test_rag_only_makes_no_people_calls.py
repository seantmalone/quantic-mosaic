"""P7's e2e gate: a pure policy question makes **zero** non-RAG tool calls (spec §9.2, R4.1).

"Decide whether RAG alone is sufficient" is a discrete, logged decision, and for
`intent == "policy_qa"` it is a **gate** rather than a hint: the catalog handed to the model is
hard-restricted to tools 1-4, and the orchestrator refuses a call to anything else at the call
boundary. That second half is what this file exists to prove. Omitting a tool from the array is a
suggestion; a model that guesses `lookup_employee_profile` anyway would still reach a real server if
the omission were the only control — so the script here scripts exactly that guess.

Nothing is mocked. `StubAdapter` replays a committed script (§16.2); the tools, the retrieval and
the catalog are the shipped MCP server in a separate OS process, reached over stdio.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent.client import RAG_TOOLS
from hrmosaic.agent.orchestrator import ChatRequest

pytestmark = pytest.mark.anyio

QUESTION = "How much PTO do full-time employees accrue each month?"

PEOPLE_AND_WRITE_TOOLS = {
    "lookup_employee_profile",
    "check_pto_balance",
    "lookup_benefits_status",
    "create_mock_hr_ticket",
    "draft_hr_email",
}


async def test_zero_non_rag_tool_calls(run_agent, spans):
    """The gate, in one line: nothing outside tools 1-4 was ever called."""
    answered = await run_agent("rag_only.json", ChatRequest(message=QUESTION, employee_id="E1042"))

    called = [payload["tool_name"] for kind, _, payload in spans(answered.turn_id) if kind == "tool_call"]
    assert called, "the turn did use the RAG tools"
    assert set(called) <= set(RAG_TOOLS)
    assert set(called).isdisjoint(PEOPLE_AND_WRITE_TOOLS)
    assert answered.outcome == "answered"


async def test_the_gate_holds_at_the_array_and_at_the_call_boundary(run_agent, spans):
    """Omitting a tool is a suggestion; refusing the call is the control.

    The script asks for `lookup_employee_profile` anyway, so both halves are exercised: every act
    call was offered exactly the four RAG tools, and the guess was refused and recorded rather than
    quietly reaching a real server.
    """
    answered = await run_agent("rag_only.json", ChatRequest(message=QUESTION, employee_id="E1042"))
    records = spans(answered.turn_id)

    offered = [
        payload["tools_offered"] for kind, _, payload in records if kind == "llm_call" and payload["purpose"] == "act"
    ]
    assert offered, "the act loop ran"
    assert all(set(array) == set(RAG_TOOLS) for array in offered), offered

    errors = [payload for kind, _, payload in records if kind == "error"]
    assert [payload["error_kind"] for payload in errors] == ["tool_not_offered"]
    assert "lookup_employee_profile" in errors[0]["message"]
    assert errors[0]["component"] == "router_gate"

    plans = [payload for kind, name, payload in records if kind == "plan" and name == "router"]
    assert [(plan["intent"], plan["catalog_reopened"]) for plan in plans] == [("policy_qa", False)]


async def test_the_filtered_catalog_was_the_discovered_one_and_the_answer_is_cited(run_agent, spans):
    """R5.4: the model's array is the conversion of a live `tools/list`, never a hard-coded list."""
    answered = await run_agent("rag_only.json", ChatRequest(message=QUESTION, employee_id="E1042"))

    discovery = next(payload for kind, _, payload in spans(answered.turn_id) if kind == "mcp_discovery")
    assert discovery["tool_count"] == 9
    assert set(RAG_TOOLS) < {tool["name"] for tool in discovery["tools"]}
    assert discovery["cached"] is False and discovery["catalog_sha"]

    assert [block.type for block in answered.answer_blocks] == ["policy_fact"]
    assert [citation.doc_id for citation in answered.citations] == ["pto-and-holidays"]
    assert answered.citations[0].source_url.startswith("/dashboard/corpus/pto-and-holidays#")
