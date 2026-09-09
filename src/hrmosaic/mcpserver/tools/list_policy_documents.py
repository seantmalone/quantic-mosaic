"""Tool 3 — what the corpus covers (spec §8.4).

Ours, deliberately extra: the requirement enumerates eight tools and this is the ninth, so the agent
can ask what exists rather than guessing a `doc_id`. **Every aggregate is computed from the
`documents` table at request time, never a literal** — a corpus edit moves the counts with no
hand-maintained number anywhere.

G1's refusal path reads the same information through `core.corpusread` directly, so an out-of-scope
turn makes zero tool calls (§9.2).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from hrmosaic.core import corpusread
from hrmosaic.core.db import now_micros
from hrmosaic.mcpserver.server import READ_ONLY, ServerDeps, envelope, read_meta, result
from hrmosaic.mcpserver.tools.search_policy_documents import Topic


class DocumentSummary(BaseModel):
    doc_id: str
    doc_title: str
    source_format: str
    topics: list[str]
    section_count: int
    chunk_count: int
    estimated_pages: float
    effective_date: str
    version: str


class CatalogOutput(BaseModel):
    documents: list[DocumentSummary]
    corpus_version: str
    total_documents: int
    total_pages: float
    total_chunks: int


def register(server: MCPServer, deps: ServerDeps) -> None:
    @server.tool(
        name="list_policy_documents",
        description=(
            "List the HR policy documents in the corpus with their topics, sizes and effective "
            "dates. Call it to find a doc_id, or to say honestly what the corpus does and does not "
            "cover."
        ),
        annotations=ToolAnnotations(**READ_ONLY),
    )
    async def list_policy_documents(
        ctx: Context,
        topic: Annotated[Topic | None, Field(description="Only documents carrying this topic.")] = None,
    ) -> CatalogOutput:
        call = read_meta(ctx)
        started = now_micros()
        body = await asyncio.to_thread(_catalog, deps, topic=topic)
        ended = now_micros()
        body["_trace"] = envelope(call, server_timing_ms=max(0, (ended - started) // 1000), transport=deps.transport)
        return result(body)


def _catalog(deps: ServerDeps, *, topic: str | None) -> dict[str, Any]:
    """The blocking half: one read-only index query. Always inside `asyncio.to_thread`."""
    connection = deps.index()
    with deps.lock:
        documents = corpusread.list_documents(connection)
        meta = corpusread.read_index_meta(connection)
    selected = [document for document in documents if topic is None or topic in document.topics]
    return CatalogOutput(
        documents=[
            DocumentSummary(
                doc_id=document.doc_id,
                doc_title=document.doc_title,
                source_format=document.source_format,
                topics=list(document.topics),
                section_count=document.section_count,
                chunk_count=document.chunk_count,
                estimated_pages=round(document.estimated_pages, 1),
                effective_date=document.effective_date,
                version=document.version,
            )
            for document in selected
        ],
        corpus_version=meta.corpus_version,
        total_documents=len(selected),
        total_pages=round(sum(document.estimated_pages for document in selected), 1),
        total_chunks=sum(document.chunk_count for document in selected),
    ).model_dump(mode="json")


__all__ = ["CatalogOutput", "DocumentSummary", "register"]
