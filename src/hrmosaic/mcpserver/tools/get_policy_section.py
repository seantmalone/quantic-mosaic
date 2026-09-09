"""Tool 2 — the verbatim text of one policy section (spec §8.4).

`doc_id` is required and **exactly one** of `heading_path` / `chunk_id` selects the section. §8.4
requires that rule to be expressed **in the schema, not only in prose**, as the literal root
`oneOf` reproduced in `SELECTOR_ONE_OF` below — and §22's `AnthropicAdapter` row leans on that root
`oneOf` existing when it justifies not setting `strict: true`. So this tool publishes it.

The Anthropic Messages API does answer 400 when a tool `input_schema` carries `oneOf` / `anyOf` /
`allOf` at the **root** (verified live 2026-09-09; the message is quoted in
`core/llm/anthropic.py`). That is handled where it arises, on the wire: `AnthropicAdapter` drops
those three keys from the top level of a tool schema on the way out and changes nothing else, and
`core/llm/base.py::ToolSchema` records the invariant — an adapter *never rewrites what the server
publishes*. The committed schema stays the one the MCP server validates arguments against.

A published `oneOf` is a *publication*, not a second enforcement point: `@server.tool` builds the
argument model from the handler signature, so the SDK still validates only `properties` / required.
The exactly-one rule is therefore stated three times over — in the schema for a client that reads
JSON Schema, in the description a model actually reads, and enforced *here*:

* neither → `isError` with `{"code": "INVALID_ARGUMENTS", "fields": ["heading_path", "chunk_id"]}`;
* both → **not** an error. `chunk_id` wins and `resolved_by` records it, so a model that over-
  specifies gets the precise answer rather than a scolding.

`tests/unit/test_get_policy_section_selectors.py` covers all four combinations.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from hrmosaic.core import corpusread
from hrmosaic.core.db import now_micros
from hrmosaic.mcpserver.server import READ_ONLY, ServerDeps, envelope, invalid_arguments, read_meta, result

SELECTOR_RULE = (
    "Supply exactly one of heading_path or chunk_id. Neither is an error; if both are given, "
    "chunk_id wins and resolved_by says so."
)

#: §8.4's literal root combinator, byte for byte:
#: `"oneOf":[{"required":["heading_path"]},{"required":["chunk_id"]}]`.
SELECTOR_ONE_OF: list[dict[str, list[str]]] = [{"required": ["heading_path"]}, {"required": ["chunk_id"]}]


def publish_selector_one_of(server: MCPServer) -> None:
    """Add §8.4's root `oneOf` to the published `input_schema`, after registration.

    `@server.tool` in `mcp` 2.2.0 derives `Tool.parameters` from the handler signature and takes no
    schema-override argument, so the only way to publish a keyword Pydantic cannot express is to
    amend the registered tool. `MCPServer.list_tools()` hands `Tool.parameters` straight out as
    `input_schema`, so this reaches every transport and `scripts/gen_tool_schemas.py` alike.

    It touches nothing the SDK validates against (`fn_metadata.arg_model`), which is what keeps the
    handler the single enforcement point for the selector rule.
    """
    # `MCPServer` exposes `add_tool` / `remove_tool` / `list_tools` but no accessor for a registered
    # tool, so the manager is reached directly; `test_tool_schemas_committed` fails loudly if 2.x
    # ever moves it.
    tool = server._tool_manager.get_tool("get_policy_section")
    if tool is None:  # pragma: no cover — registration precedes this call
        raise RuntimeError("get_policy_section must be registered before its schema is amended")
    tool.parameters["oneOf"] = [dict(branch) for branch in SELECTOR_ONE_OF]


class SectionOutput(BaseModel):
    """The §8.4 tool-2 result, or `{status: not_found}` when the selector resolves to nothing."""

    doc_id: str | None = None
    doc_title: str | None = None
    source_format: str | None = None
    heading_path: str | None = None
    section: str | None = None
    text: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    chunk_ids: list[str] | None = None
    resolved_by: str | None = None
    prev_section: str | None = None
    next_section: str | None = None
    sibling_sections: list[str] | None = None
    status: str | None = None
    code: str | None = None
    hint: str | None = None


def register(server: MCPServer, deps: ServerDeps) -> None:
    @server.tool(
        name="get_policy_section",
        description=(
            "Return the verbatim text of one section of a policy document, with its neighbours and "
            "siblings for context. " + SELECTOR_RULE
        ),
        annotations=ToolAnnotations(**READ_ONLY),
    )
    async def get_policy_section(
        ctx: Context,
        doc_id: Annotated[str, Field(description="The document to read, e.g. 'pto-and-holidays'.")],
        heading_path: Annotated[
            str | None, Field(description="The ' > '-joined heading path, e.g. 'Accrual > Standard Accrual Rates'.")
        ] = None,
        chunk_id: Annotated[str | None, Field(description="A chunk id from search_policy_documents.")] = None,
        include_neighbors: Annotated[
            bool, Field(description="Also concatenate the previous and next sections into text.")
        ] = False,
    ) -> SectionOutput:
        call = read_meta(ctx)
        if not heading_path and not chunk_id:
            return invalid_arguments(["heading_path", "chunk_id"])
        started = now_micros()
        body = await asyncio.to_thread(
            _section,
            deps,
            doc_id=doc_id,
            heading_path=heading_path,
            chunk_id=chunk_id,
            include_neighbors=include_neighbors,
        )
        ended = now_micros()
        body["_trace"] = envelope(call, server_timing_ms=max(0, (ended - started) // 1000), transport=deps.transport)
        return result(body)


def _parent(heading_path: str) -> str:
    head, separator, _ = heading_path.rpartition(" > ")
    return head if separator else ""


def _section(
    deps: ServerDeps,
    *,
    doc_id: str,
    heading_path: str | None,
    chunk_id: str | None,
    include_neighbors: bool,
) -> dict[str, Any]:
    """The blocking half: two read-only index queries. Always inside `asyncio.to_thread`."""
    connection = deps.index()
    with deps.lock:
        document = corpusread.get_document(doc_id, connection)
        chunks = corpusread.list_chunks(doc_id, connection) if document else []
    if document is None:
        return {
            "status": "not_found",
            "code": "DOCUMENT_NOT_FOUND",
            "hint": "Call list_policy_documents for the doc_ids this corpus carries.",
        }

    # `chunk_id` wins when both selectors arrive (§8.4).
    resolved_by = "chunk_id" if chunk_id else "heading_path"
    if chunk_id:
        target = next((chunk for chunk in chunks if chunk.chunk_id == chunk_id), None)
        path = target.heading_path if target else None
    else:
        path = heading_path
    if path is None or not any(chunk.heading_path == path for chunk in chunks):
        return {
            "status": "not_found",
            "code": "SECTION_NOT_FOUND",
            "hint": "Heading paths exclude the document title, e.g. 'Accrual > Standard Accrual Rates'.",
        }

    ordered_paths: list[str] = []
    for chunk in chunks:
        if chunk.heading_path and chunk.heading_path not in ordered_paths:
            ordered_paths.append(chunk.heading_path)
    position = ordered_paths.index(path)
    prev_section = ordered_paths[position - 1] if position > 0 else None
    next_section = ordered_paths[position + 1] if position + 1 < len(ordered_paths) else None

    def text_of(target_path: str | None) -> str:
        if target_path is None:
            return ""
        return "\n\n".join(chunk.text for chunk in chunks if chunk.heading_path == target_path)

    selected = [chunk for chunk in chunks if chunk.heading_path == path]
    text = text_of(path)
    if include_neighbors:
        text = "\n\n".join(part for part in (text_of(prev_section), text, text_of(next_section)) if part)

    parent = _parent(path)
    siblings = [other for other in ordered_paths if other != path and _parent(other) == parent]
    return SectionOutput(
        doc_id=document.doc_id,
        doc_title=document.doc_title,
        source_format=document.source_format,
        heading_path=path,
        section=path.rpartition(" > ")[2] or path,
        text=text,
        char_start=min(chunk.char_start for chunk in selected),
        char_end=max(chunk.char_end for chunk in selected),
        chunk_ids=[chunk.chunk_id for chunk in selected],
        resolved_by=resolved_by,
        prev_section=prev_section,
        next_section=next_section,
        sibling_sections=siblings,
    ).model_dump(mode="json", exclude_none=True)


__all__ = ["SectionOutput", "register"]
