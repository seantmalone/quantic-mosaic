"""Proof that the `no_structured_tools` arm's tools are genuinely absent from discovery (§13.9).

The ablation itself filters the catalog **client-side**, per turn, through `options.tools_disabled`
— which proves the model was not *offered* the five structured-data tools, not that they were
absent from `tools/list`. So this script spawns a **second, separate `MCPServer`** with
`remove_tool` applied, over **stdio**, as its own OS process — never the shared mounted instance,
which is process-wide and would break a concurrent grader session — and records the catalog it
publishes.

Run it and screenshot the printed catalog for `docs/evidence/mcp-discovery-4-tools.png`; the JSON it
writes beside that file is the machine-readable half of the same evidence.

    python scripts/gen_ablation_evidence.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # `python scripts/<name>.py` puts this file's own directory on sys.path, not the repository
    # root, so the `evaluation` package (which is not installed) would not import.
    sys.path.insert(0, str(REPO_ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from evaluation.schema import VARIANT_OPTIONS  # noqa: E402

logger = logging.getLogger(__name__)

EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"
EVIDENCE_PATH = EVIDENCE_DIR / "mcp-discovery-4-tools.json"

#: The five tools §13.9's third arm withdraws. `check_policy_compliance` stays: withdrawing
#: everything would only test "an agent with no tools".
REMOVED_TOOLS: tuple[str, ...] = tuple(VARIANT_OPTIONS["no_structured_tools"]["tools_disabled"])

#: The child process: a server built exactly like the shipped one, then stripped.
CHILD_SOURCE = """\
import sys
from hrmosaic.mcpserver.server import ServerDeps, build_hr_server
from hrmosaic.mcpserver.stdio_main import configure_logging

configure_logging()
server = build_hr_server(ServerDeps(transport="stdio"))
for name in {removed!r}:
    server.remove_tool(name)
server.run(transport="stdio")
"""


async def discover(removed: Sequence[str]) -> dict[str, Any]:
    """`tools/list` against a separate stdio server with `remove_tool` applied."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", CHILD_SOURCE.format(removed=tuple(removed))],
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        result = await session.initialize()
        catalog = await session.list_tools()
    return {
        "transport": "stdio",
        "server_info": {"name": result.server_info.name, "version": result.server_info.version},
        "protocol_version": str(result.protocol_version),
        "removed_tools": list(removed),
        "tool_count": len(catalog.tools),
        "tools": [
            {
                "name": tool.name,
                "description": (tool.description or "").split(".")[0] + ".",
                "required": list((tool.input_schema or {}).get("required") or []),
            }
            for tool in sorted(catalog.tools, key=lambda tool: tool.name)
        ],
    }


def render(evidence: dict[str, Any]) -> str:
    """The terminal view the evidence screenshot is taken of."""
    lines = [
        "MCP discovery — the `no_structured_tools` ablation arm (spec §13.9)",
        "",
        f"  server        {evidence['server_info']['name']} {evidence['server_info']['version']}",
        f"  transport     {evidence['transport']} (a separate OS process, not the mounted instance)",
        f"  protocol      {evidence['protocol_version']}",
        f"  removed       {', '.join(evidence['removed_tools'])}",
        f"  tools/list    {evidence['tool_count']} tools",
        "",
    ]
    lines += [f"    · {tool['name']:<28} {tool['description']}" for tool in evidence["tools"]]
    lines += [
        "",
        "  The five structured-data tools are absent from the catalog itself, not merely unoffered:",
        "  the per-request `options.tools_disabled` filter proves the model was not offered them,",
        "  and this second server proves they can be genuinely withdrawn from discovery.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record the 4-tool discovery evidence (§13.9).")
    parser.add_argument("--out", default=str(EVIDENCE_PATH))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    evidence = asyncio.run(discover(REMOVED_TOOLS))
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8")
    print(render(evidence))  # noqa: T201 — this is the artifact
    logger.info("wrote %s", path)
    return 0 if evidence["tool_count"] == 4 else 1


if __name__ == "__main__":
    sys.exit(main())
