"""`tools/list` versus the requirement's own tool names (spec §8.4, R5.3).

`REQUIRED_TOOL_NAMES` is the requirement's enumerated list, copied here as a constant so the check is
a literal string comparison rather than a restatement of whatever the code happens to expose.
`list_policy_documents` is ours and deliberately extra, which is why the assertion is `⊆` and not
equality.

The catalog is read from a **live** session — a real `initialize` + `tools/list` round trip over the
SDK's in-process transport — so the conventions asserted below (`employee_id` pattern, `outputSchema`
on every tool, the read/write annotation split) are asserted against the bytes a client receives, not
against the Python objects that produced them.
"""

from __future__ import annotations

import pytest
from mcp import Client

from hrmosaic.mcpserver.server import build_hr_server

pytestmark = pytest.mark.anyio

#: The requirement's own enumerated names (R5.3), verbatim.
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

#: Ours, and the only name in `tools/list` that is not in the requirement's list.
EXTRA_TOOL_NAMES = {"list_policy_documents"}

WRITE_TOOLS = {"create_mock_hr_ticket", "draft_hr_email"}

EMPLOYEE_ID_PATTERN = "^E1[0-9]{3}$"


@pytest.fixture
async def catalog():
    async with Client(build_hr_server()) as client:
        listed = await client.list_tools()
    return {tool.name: tool for tool in listed.tools}


async def test_every_required_tool_name_is_served(catalog):
    assert REQUIRED_TOOL_NAMES <= set(catalog)
    assert set(catalog) - REQUIRED_TOOL_NAMES == EXTRA_TOOL_NAMES


async def test_every_tool_has_a_description_and_a_well_formed_input_schema(catalog):
    for name, tool in catalog.items():
        assert tool.description and tool.description.strip(), name
        assert tool.input_schema.get("type") == "object", name
        assert isinstance(tool.input_schema.get("properties"), dict), name


async def test_every_tool_declares_an_output_schema(catalog):
    for name, tool in catalog.items():
        assert tool.output_schema, name
        assert tool.output_schema.get("type") == "object", name


async def test_read_and_write_tools_carry_the_conventional_annotations(catalog):
    for name, tool in catalog.items():
        annotations = tool.annotations
        assert annotations is not None, name
        if name in WRITE_TOOLS:
            assert annotations.read_only_hint is False, name
            assert annotations.destructive_hint is False, name
            assert annotations.idempotent_hint is False, name
        else:
            assert annotations.read_only_hint is True, name
            assert annotations.open_world_hint is False, name


async def test_employee_id_uses_the_one_documented_pattern(catalog):
    carriers = [tool for tool in catalog.values() if "employee_id" in tool.input_schema["properties"]]
    assert {tool.name for tool in carriers} == set(catalog) - {
        "search_policy_documents",
        "get_policy_section",
        "list_policy_documents",
    }, "every tool but the three corpus tools keys on an employee id"
    for tool in carriers:
        assert tool.input_schema["properties"]["employee_id"]["pattern"] == EMPLOYEE_ID_PATTERN, tool.name


async def test_no_input_schema_carries_a_root_combinator(catalog):
    # The Anthropic Messages API answers 400 when a tool input_schema has oneOf/anyOf/allOf at the
    # ROOT (P6's live probe), so `get_policy_section` states its exactly-one rule in prose and
    # enforces it in the handler instead of publishing the `oneOf` of §8.4.
    for name, tool in catalog.items():
        assert not {"oneOf", "anyOf", "allOf"} & set(tool.input_schema), name


async def test_the_write_tools_accept_a_confirmation_token_and_never_require_it(catalog):
    for name in WRITE_TOOLS:
        schema = catalog[name].input_schema
        assert "confirmation_token" in schema["properties"], name
        assert "confirmation_token" not in schema.get("required", []), name
