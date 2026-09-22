"""`MCP_TOOLS_DISABLED` is the process default for `options.tools_disabled` (§12.3, gap 20).

The variable was declared in `Settings` and advertised in `.env.example` as a "process default"
tool filter, and **nothing read it**: only the per-request `options.tools_disabled` path was wired,
so a grader who set it to demonstrate the tool-availability ablation saw the full catalogue anyway.
Its siblings marked the same way — `RETRIEVAL_K`, `RETRIEVAL_STRATEGY` — are honoured inside
`rag.retrieve`, which is the contract these tests pin for this one: the environment supplies the
default, a request that states the field wins, and the value reaches the filter that withholds the
tools rather than sitting in a model nobody consults.
"""

from __future__ import annotations

from hrmosaic.agent.client import DiscoveredCatalog, DiscoveredTool
from hrmosaic.agent.orchestrator import ChatOptions, ChatRequest
from hrmosaic.agent.router import RouteDecision, allowed_tools
from hrmosaic.settings import Settings
from hrmosaic.settings import settings as process_settings

TOOL_NAMES = ("search_policy_documents", "lookup_employee_profile", "check_pto_balance")


def _catalog() -> DiscoveredCatalog:
    return DiscoveredCatalog(
        server="hrmosaic-mcp",
        transport="stdio",
        url=None,
        protocol_version="2025-06-18",
        server_info=None,
        tools=tuple(
            DiscoveredTool(name=name, description=name, input_schema={"type": "object", "properties": {}})
            for name in TOOL_NAMES
        ),
        catalog_sha="sha",
        mcp_session_id=None,
        handshake_ms=1,
        discovered_at=0,
    )


def _decision() -> RouteDecision:
    return RouteDecision(
        intent="employee_data",
        workflow=None,
        multi_doc=False,
        needs_employee_data=True,
        needs_clarification=False,
        out_of_scope=False,
        sensitive=False,
        target_employee_id="E1042",
        selected_tools=list(TOOL_NAMES),
        rationale_summary="the balance question",
    )


def test_the_env_var_is_parsed_the_way_a_comma_separated_list_is():
    """Blanks dropped, spaces trimmed: an untouched `.env.example` line leaves `KEY=` behind."""
    assert Settings(mcp_tools_disabled="").mcp_tools_disabled_list == []
    assert Settings(mcp_tools_disabled="  ,  ").mcp_tools_disabled_list == []
    assert Settings(mcp_tools_disabled="check_pto_balance, draft_hr_email,").mcp_tools_disabled_list == [
        "check_pto_balance",
        "draft_hr_email",
    ]


def test_an_unstated_request_takes_the_process_default(monkeypatch):
    monkeypatch.setattr(process_settings, "mcp_tools_disabled", "check_pto_balance,lookup_employee_profile")

    assert ChatOptions().tools_disabled == ["check_pto_balance", "lookup_employee_profile"]
    assert ChatRequest(message="hello").options.tools_disabled == [
        "check_pto_balance",
        "lookup_employee_profile",
    ]


def test_the_default_is_empty_when_the_variable_is(monkeypatch):
    monkeypatch.setattr(process_settings, "mcp_tools_disabled", "")

    assert ChatOptions().tools_disabled == []


def test_a_request_that_states_the_field_wins_including_with_the_empty_list(monkeypatch):
    """The per-turn channel of §13.9 must be able to ask for the whole catalogue on a process that
    withholds tools by default — otherwise the baseline arm of the ablation could not be run there."""
    monkeypatch.setattr(process_settings, "mcp_tools_disabled", "check_pto_balance")

    assert ChatOptions(tools_disabled=[]).tools_disabled == []
    assert ChatOptions(tools_disabled=["draft_hr_email"]).tools_disabled == ["draft_hr_email"]


def test_the_process_default_reaches_the_filter_that_withholds_the_tools(monkeypatch):
    """Not just stored: `allowed_tools` is what decides the array the model is offered."""
    monkeypatch.setattr(process_settings, "mcp_tools_disabled", "check_pto_balance")
    options = ChatOptions()

    offered = allowed_tools(_decision(), _catalog(), disabled=options.tools_disabled)

    assert "check_pto_balance" not in offered
    assert "search_policy_documents" in offered
