"""The four `mcp` 2.x API differences this project is written against (spec §3, constraints).

The SDK's 1.x and 2.x surfaces differ in ways that fail loudly at import or silently at runtime, and
every one of them is pinned here so an accidental downgrade is a red test rather than a mystery:

1. the server class is `mcp.server.mcpserver.MCPServer`, not 1.x's `mcp.server.fastmcp.FastMCP`;
2. the Streamable HTTP client is `streamable_http_client`, not 1.x's `streamablehttp_client`;
3. that client yields a **2-tuple** `(read, write)`, where 1.x yielded a 3-tuple whose third member
   was a `get_session_id` callable — unpacking the wrong arity is a `ValueError` at connect time;
4. result fields are snake_case: `server_info`, `input_schema`, `structured_content`.

This module also carries the live proof for the `mcp/` shadowing hazard of §4.1: pytest puts the
repository root on `sys.path`, the repository has a top-level `mcp/` directory, and the import below
still resolves to the installed SDK because that directory has no `__init__.py` and a namespace
portion never wins over a regular package found later on the path.
"""

from __future__ import annotations

import typing
from importlib.metadata import version
from pathlib import Path

import mcp
import mcp_types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import TransportStreams, streamable_http_client
from mcp.server.mcpserver import MCPServer

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_the_installed_sdk_is_the_pinned_two_x():
    assert version("mcp") == "2.2.0"


def test_the_real_sdk_wins_over_the_repo_root_mcp_directory():
    # §4.1: `mcp/` is a deliverable directory, and importing the SDK from the repository root is
    # what proves it is not shadowing it.
    assert (REPO_ROOT / "mcp").is_dir()
    assert not (REPO_ROOT / "mcp" / "__init__.py").exists()
    assert Path(mcp.__file__).parent != REPO_ROOT / "mcp"
    assert "site-packages" in Path(mcp.__file__).as_posix()


def test_difference_one_the_server_class_is_mcpserver():
    assert MCPServer.__module__.startswith("mcp.server.mcpserver")
    assert callable(MCPServer(name="shape", version="0.0.0").tool)


def test_difference_two_the_streamable_http_client_is_snake_cased():
    assert callable(streamable_http_client)
    assert not hasattr(mcp.client.streamable_http, "streamablehttp_client")


def test_difference_three_the_client_yields_a_two_tuple():
    # 1.x yielded `(read, write, get_session_id)`; unpacking three names from this would raise.
    # `tests/integration/test_mcp_discovery.py` unpacks exactly two, live, on both transports.
    assert len(typing.get_args(TransportStreams)) == 2
    for client in (streamable_http_client, stdio_client):
        yielded, _ = typing.get_args(typing.get_type_hints(client)["return"])
        assert len(typing.get_args(yielded)) == 2, client


def test_difference_four_result_fields_are_snake_case():
    assert "server_info" in mcp_types.InitializeResult.model_fields
    assert "input_schema" in mcp_types.Tool.model_fields
    assert "structured_content" in mcp_types.CallToolResult.model_fields
    assert "outputSchema" not in mcp_types.Tool.model_fields
