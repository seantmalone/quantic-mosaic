"""MCP discovery over both transports (spec §16.4, R8.3, R5.5).

`initialize` succeeds, `tools/list` returns at least five tools, every tool carries a non-empty
description and a well-formed JSON Schema `input_schema`, and the eight names the requirement
enumerates are all present.

**P5's version was discovery only**: the access gate and the in-process MCP client did not exist
until P8, which added the last three tests — with the gate on, the client sends
`Authorization: Bearer` on `tools/list` and on every `tools/call`, and the mount refuses anyone who
does not (spec §16.4).
"""

from __future__ import annotations

import pytest

from hrmosaic.mcpserver.tools import TOOL_NAMES

pytestmark = pytest.mark.anyio

#: The requirement's own enumerated names (R5.3). `list_policy_documents` is ours and extra.
REQUIRED_TOOL_NAMES = {
    "search_policy_documents",
    "get_policy_section",
    "check_policy_compliance",
    "lookup_employee_profile",
    "check_pto_balance",
    "lookup_benefits_status",
    "create_mock_hr_ticket",
    "draft_hr_email",
}


async def test_initialize_reports_the_server_identity(open_session):
    async with open_session() as session:
        initialized = await session.initialize()
    assert initialized.server_info.name == "mosaic-hr"
    assert initialized.server_info.version
    assert initialized.protocol_version


async def test_tools_list_returns_at_least_five_well_formed_tools(open_session):
    async with open_session() as session:
        listed = await session.list_tools()
    assert len(listed.tools) >= 5
    for tool in listed.tools:
        assert tool.description and tool.description.strip(), tool.name
        assert tool.input_schema["type"] == "object", tool.name
        assert isinstance(tool.input_schema["properties"], dict), tool.name
        assert tool.output_schema, tool.name
        assert tool.annotations is not None, tool.name


async def test_every_required_tool_name_is_discoverable(open_session):
    async with open_session() as session:
        listed = await session.list_tools()
    names = {tool.name for tool in listed.tools}
    assert REQUIRED_TOOL_NAMES <= names
    assert names == set(TOOL_NAMES)


# --------------------------------------------------------------------------------------
# P8's addition to the HTTP half: the access gate on the loopback mount (§11, §16.4)
# --------------------------------------------------------------------------------------

TOKEN = "test-access-token-9f2c1b7e"


async def test_the_mounted_endpoint_is_gated_like_every_other_non_open_route(web):
    """The mount stays reachable so a grader can attach MCP Inspector — with the bearer (§17)."""
    from pydantic import SecretStr

    async with web(app_access_token=SecretStr(TOKEN)) as client:
        anonymous = await client.post(
            "/mcp-server/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "ACCESS_REQUIRED"


async def test_with_the_gate_on_the_in_process_client_sends_the_bearer(web, store):
    """`tools/list` **and** every `tools/call` carry `Authorization: Bearer` (§11, §16.4).

    Behavioural, not introspective: with the gate on, a client that sent no header would be 401 on
    the mount, discovery would report zero tools and every call would fail. That the handshake
    returns nine tools and the turn's `tool_call` spans are all `ok` is the proof the header rode
    along — and the header itself is asserted on the client the lifespan built.
    """
    from pydantic import SecretStr

    from hrmosaic.agent import orchestrator as agent

    async with web("demo_task_1.json", app_access_token=SecretStr(TOKEN)) as client:
        headers = dict(agent.get_orchestrator().client._headers)
        health = await client.get("/health", headers={"Authorization": f"Bearer {TOKEN}"})
        response = await client.post(
            "/chat",
            json={"message": "I want to work from Berlin from 3 November to 14 December 2026 — can I?"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert headers == {"Authorization": f"Bearer {TOKEN}"}
    assert health.json()["mcp"]["connected"] is True
    assert health.json()["mcp"]["tool_count"] == 9, "tools/list passed the gate"

    assert response.status_code == 200, response.text
    calls = store.execute(
        "SELECT name, status FROM spans WHERE turn_id = ? AND kind = 'tool_call' ORDER BY seq",
        (response.json()["turn_id"],),
    ).dicts()
    assert calls, "the turn really called tools"
    assert all(call["status"] == "ok" for call in calls), "every tools/call passed the gate too"


async def test_with_the_gate_off_the_client_sends_no_authorization_header(web):
    """Local development stays frictionless: no token set, no header, no gate (§11)."""
    from hrmosaic.agent import orchestrator as agent

    async with web() as client:
        headers = dict(agent.get_orchestrator().client._headers)
        health = await client.get("/health")

    assert headers == {}
    assert health.json()["mcp"]["tool_count"] == 9
