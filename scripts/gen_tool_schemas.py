"""Generate `mcp/tools/*.schema.json` from the live server (spec §8.4, §21 row 28).

    python scripts/gen_tool_schemas.py

One file per tool, named `<tool>.schema.json`, each carrying the tool's name, description,
`input_schema`, `output_schema` and `annotations` exactly as `tools/list` returns them. The schemas
are **generated, never hand-written** — they are derived from the handler signatures and their
Pydantic return models — and they are **committed**, because `design-and-evaluation.md` (DOCS.3)
publishes them as a deliverable and a reader must be able to see them without running the server.

This is the one generated artifact in the project with a test of its own:
`tests/contract/test_tool_schemas_committed.py` asserts the committed files equal a live
`tools/list`, so a schema change that was not regenerated fails CI instead of quietly making the
documentation a lie. The definition of done runs the generator and then `git diff --exit-code`.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from hrmosaic.mcpserver.server import build_hr_server

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "mcp" / "tools"


def schema_of(tool: Any) -> dict[str, Any]:
    """One tool's published contract, in the field names the 2.x wire uses."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "annotations": tool.annotations.model_dump(mode="json", exclude_none=True) if tool.annotations else None,
    }


async def collect() -> dict[str, dict[str, Any]]:
    """`tools/list` from a server built exactly as the deployed one is."""
    tools = await build_hr_server().list_tools()
    return {tool.name: schema_of(tool) for tool in tools}


def render(schema: dict[str, Any]) -> str:
    """Two-space JSON with a trailing newline — stable bytes, so `git diff` is meaningful."""
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main() -> int:
    schemas = asyncio.run(collect())
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, schema in sorted(schemas.items()):
        path = OUTPUT_DIR / f"{name}.schema.json"
        path.write_text(render(schema), encoding="utf-8")
        written.append(path.name)
    stale = sorted(path.name for path in OUTPUT_DIR.glob("*.schema.json") if path.name not in set(written))
    for name in stale:
        (OUTPUT_DIR / name).unlink()
    for name in written:
        print(f"  wrote mcp/tools/{name}")
    if stale:
        print(f"  removed {len(stale)} stale schema(s): {', '.join(stale)}")
    print(f"\n{len(written)} tool schemas generated from a live tools/list.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
