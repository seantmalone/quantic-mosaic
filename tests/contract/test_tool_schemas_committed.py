"""The committed `mcp/tools/*.schema.json` equal a live `tools/list` (spec §8.4, §21 row 28).

The generated schemas are a published deliverable — `design-and-evaluation.md` shows them under
DOCS.3 — so a reader must be able to trust the committed bytes without running the server. This is
the one generated artifact in the project with a test, and it exists because the failure it catches
is silent: a handler signature changes, nobody re-runs `scripts/gen_tool_schemas.py`, and the
documentation quietly describes a tool that no longer exists in that shape.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.mcpserver.tools import TOOL_NAMES
from scripts.gen_tool_schemas import OUTPUT_DIR, collect, render

pytestmark = pytest.mark.anyio

COMMITTED = sorted(OUTPUT_DIR.glob("*.schema.json"))


def test_one_schema_file_per_tool_is_committed():
    assert {path.name for path in COMMITTED} == {f"{name}.schema.json" for name in TOOL_NAMES}


async def test_the_committed_schemas_match_a_live_tools_list():
    live = await collect()
    committed = {
        path.name.removesuffix(".schema.json"): json.loads(path.read_text(encoding="utf-8")) for path in COMMITTED
    }
    assert committed == live


async def test_the_committed_bytes_are_exactly_what_the_generator_writes():
    # Content equality is not enough: `git diff --exit-code mcp/tools/` in the definition of done
    # compares bytes, so the formatting has to round-trip too.
    live = await collect()
    stale = [
        path.name
        for path in COMMITTED
        if path.read_text(encoding="utf-8") != render(live[path.name.removesuffix(".schema.json")])
    ]
    assert stale == [], "run `python scripts/gen_tool_schemas.py` and commit the result"


async def test_the_published_schemas_carry_the_contract_a_reader_needs():
    live = await collect()
    for name, schema in live.items():
        assert schema["description"], name
        assert schema["input_schema"]["type"] == "object", name
        assert schema["output_schema"]["type"] == "object", name
        assert schema["annotations"], name
