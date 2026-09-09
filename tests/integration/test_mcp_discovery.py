"""MCP discovery over both transports (spec §16.4, R8.3, R5.5).

`initialize` succeeds, `tools/list` returns at least five tools, every tool carries a non-empty
description and a well-formed JSON Schema `input_schema`, and the eight names the requirement
enumerates are all present.

**P5's version is discovery only**: the access gate and the in-process MCP client do not exist until
P8, which adds one assertion to the HTTP half — that with the gate on, the client sends
`Authorization: Bearer` on `tools/list` and on every `tools/call` (spec §16.4).
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
