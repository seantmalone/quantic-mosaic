"""`MCP_TOOLS_DISABLED` withholds tools on every turn (§12.3, gap 20).

The variable was declared in `Settings` and advertised in `.env.example` as a "process default"
tool filter, and **nothing read it**: only the per-request `options.tools_disabled` path was wired,
so a grader who set it to demonstrate the tool-availability ablation saw the full catalogue anyway.

It is honoured as an **addition** to that per-request list, unioned into the filter inside
`router.allowed_tools`, and these tests are mostly about why it is not a default the request
overrides (fix round 2). `options.tools_disabled` is privileged only when it is non-empty — an empty
list asks for nothing, so `privileged_options_used` does not count it and no persona check stands in
its way. A default would therefore have been a hole: any caller could have sent
`"tools_disabled": []` and been offered the very tool the operator configured the process to
withhold. Unioned, a request can withhold more tools and never fewer, which is all §13.9's ablation
arms ever ask for.
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


def _offered(**options) -> list[str]:
    return allowed_tools(_decision(), _catalog(), **options)


def test_the_process_filter_withholds_the_tool_from_a_request_that_asks_for_nothing(monkeypatch):
    """The whole of gap 20: the variable used to be read by nothing at all."""
    monkeypatch.setattr(process_settings, "mcp_tools_disabled", "check_pto_balance")

    assert "check_pto_balance" not in _offered(disabled=ChatOptions().tools_disabled)
    assert "search_policy_documents" in _offered(disabled=ChatOptions().tools_disabled)


def test_a_stated_empty_list_cannot_switch_the_process_filter_off(monkeypatch):
    """Fix round 2. `"tools_disabled": []` is unprivileged — it asks for nothing, so no persona check
    stands in its way — and while the variable was a *default* for the field, stating it was how any
    caller got the operator's withheld tool back for their own turn."""
    monkeypatch.setattr(process_settings, "mcp_tools_disabled", "check_pto_balance")

    assert "check_pto_balance" not in _offered(disabled=ChatOptions(tools_disabled=[]).tools_disabled)


def test_a_request_adds_to_the_process_filter(monkeypatch):
    """Both lists apply, which is all §13.9's ablation arms need: they only ever add."""
    monkeypatch.setattr(process_settings, "mcp_tools_disabled", "check_pto_balance")
    options = ChatOptions(tools_disabled=["lookup_employee_profile"])

    offered = _offered(disabled=options.tools_disabled)

    assert offered == ["search_policy_documents"]


def test_an_unset_variable_withholds_nothing_of_its_own(monkeypatch):
    monkeypatch.setattr(process_settings, "mcp_tools_disabled", "")

    assert _offered() == list(TOOL_NAMES)
    assert _offered(disabled=["check_pto_balance"]) == [
        "search_policy_documents",
        "lookup_employee_profile",
    ]


def test_the_request_field_is_the_requests_own_and_carries_no_default(monkeypatch):
    """`ChatOptions.tools_disabled` is what the caller asked for, so `web/`'s privileged-options
    check keeps reading it as "what this request stated" without consulting the environment."""
    monkeypatch.setattr(process_settings, "mcp_tools_disabled", "check_pto_balance")

    assert ChatOptions().tools_disabled == []
    assert ChatRequest(message="hello").options.tools_disabled == []
    assert ChatOptions(tools_disabled=["draft_hr_email"]).tools_disabled == ["draft_hr_email"]
