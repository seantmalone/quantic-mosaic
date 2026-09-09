"""All four selector combinations of `get_policy_section` (spec §8.4 tool 2).

| `heading_path` | `chunk_id` | Result |
|---|---|---|
| absent | absent | `isError` with `{"code": "INVALID_ARGUMENTS", "fields": ["heading_path", "chunk_id"]}` |
| present | absent | resolved by heading path, `resolved_by == "heading_path"` |
| absent | present | resolved by chunk id, `resolved_by == "chunk_id"` |
| present | present | **not** an error: `chunk_id` wins and `resolved_by` records it |

The last row is the one worth stating twice. §8.4 makes over-specification succeed rather than fail,
because the useful thing to do with a model that names both is answer the precise one, not spend a
repair round-trip teaching it a rule the schema cannot express anyway (the root `oneOf` is dropped by
the Anthropic Messages API, so it never reaches the model).
"""

from __future__ import annotations

import json

import pytest
from mcp import Client

from hrmosaic.core import corpusread
from hrmosaic.mcpserver.server import build_hr_server

pytestmark = pytest.mark.anyio

DOC_ID = "pto-and-holidays"
HEADING_PATH = "Accrual > Standard Accrual Rates"


@pytest.fixture(scope="module")
def anchor():
    """A real chunk from the committed index, so no id in this file is invented."""
    chunks = [chunk for chunk in corpusread.list_chunks(DOC_ID) if chunk.heading_path == HEADING_PATH]
    assert chunks, f"{DOC_ID} must carry {HEADING_PATH!r} for this test to mean anything"
    return min(chunks, key=lambda chunk: chunk.char_start)


async def section(**arguments):
    async with Client(build_hr_server()) as client:
        result = await client.call_tool("get_policy_section", {"doc_id": DOC_ID, **arguments})
    body = json.loads(result.content[0].text)
    assert result.structured_content == body
    return result, body


async def test_neither_selector_is_an_invalid_arguments_error():
    result, body = await section()
    assert result.is_error is True
    assert body["code"] == "INVALID_ARGUMENTS"
    assert body["fields"] == ["heading_path", "chunk_id"]


async def test_heading_path_alone_resolves_by_heading_path(anchor):
    result, body = await section(heading_path=HEADING_PATH)
    assert result.is_error is not True
    assert body["resolved_by"] == "heading_path"
    assert body["heading_path"] == HEADING_PATH
    assert body["section"] == "Standard Accrual Rates"
    assert anchor.chunk_id in body["chunk_ids"]
    assert body["text"].strip()


async def test_chunk_id_alone_resolves_by_chunk_id(anchor):
    result, body = await section(chunk_id=anchor.chunk_id)
    assert result.is_error is not True
    assert body["resolved_by"] == "chunk_id"
    assert body["heading_path"] == HEADING_PATH
    assert anchor.chunk_id in body["chunk_ids"]


async def test_both_selectors_are_not_an_error_and_chunk_id_wins(anchor):
    other = next(
        chunk for chunk in corpusread.list_chunks(DOC_ID) if chunk.heading_path and chunk.heading_path != HEADING_PATH
    )
    result, body = await section(heading_path=HEADING_PATH, chunk_id=other.chunk_id)
    assert result.is_error is not True
    assert body["resolved_by"] == "chunk_id"
    assert body["heading_path"] == other.heading_path, "the chunk id, not the heading path, chose the section"


async def test_the_section_carries_its_neighbours_and_siblings():
    _, body = await section(heading_path=HEADING_PATH)
    assert body["prev_section"] and body["next_section"]
    assert HEADING_PATH not in body["sibling_sections"]
    assert all(sibling.startswith("Accrual > ") for sibling in body["sibling_sections"])


async def test_include_neighbors_lengthens_the_text():
    _, plain = await section(heading_path=HEADING_PATH)
    _, widened = await section(heading_path=HEADING_PATH, include_neighbors=True)
    assert plain["text"] in widened["text"]
    assert len(widened["text"]) > len(plain["text"])


async def test_an_unknown_section_is_a_successful_not_found():
    result, body = await section(heading_path="Accrual > No Such Heading")
    assert result.is_error is not True
    assert body["code"] == "SECTION_NOT_FOUND"


async def test_an_unknown_document_is_a_successful_not_found():
    async with Client(build_hr_server()) as client:
        result = await client.call_tool(
            "get_policy_section", {"doc_id": "no-such-document", "heading_path": HEADING_PATH}
        )
    body = json.loads(result.content[0].text)
    assert result.is_error is not True
    assert body["code"] == "DOCUMENT_NOT_FOUND"
