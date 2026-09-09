"""Tool 1 — semantic + lexical search over the policy corpus (spec §8.4, §7.1).

The one tool that runs the RAG pipeline, and therefore the one that emits a nested `retrieval` span
under `_trace`. Three things about it are load-bearing:

* **`min_dense_score` filters `dense_score`, never `rrf_score`.** Two arms at k₀ = 60 cap `rrf_score`
  at 2/61 ≈ 0.0328, so a 0.26 threshold applied to it would reject every candidate of every query.
  The parameter is named for what it filters and the description says so on the wire.
* **`k` precedence is `_meta.mosaic/retrieval.k_override` → the model's `k` → `RETRIEVAL_K`** (§7.1),
  and the span records which of the three won as `k_source`. The override is clamped to 1..10 before
  use, so an anonymous caller of the public URL cannot ask for `k=10000` on a 0.1-CPU instance.
* **`strategy` is validated here**, because `retrieve()` treats anything that is not `dense_only` as
  hybrid: a typo would silently retrieve hybrid and record the typo in the audit trail.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from hrmosaic.core.db import now_micros
from hrmosaic.core.models import RetrievalPayload, RetrievedChunk
from hrmosaic.mcpserver.server import (
    READ_ONLY,
    ServerDeps,
    envelope,
    invalid_arguments,
    read_meta,
    result,
    span_record,
)
from hrmosaic.settings import settings

#: The corpus topic vocabulary of §8.4 tool 1, shared with `list_policy_documents`.
Topic = Literal[
    "pto",
    "holidays",
    "remote_work",
    "tax_location",
    "expenses",
    "travel",
    "data_security",
    "benefits",
    "onboarding",
    "equipment",
    "leave",
    "conduct",
    "performance",
    "compensation",
    "approvals",
    "escalation",
]

Strategy = Literal["hybrid_rrf", "dense_only"]

MIN_DENSE_SCORE_DESCRIPTION = (
    "Minimum DENSE score (dense_score = 1 - cosine_distance). Applied to the full fused candidate "
    "list, then the top-k is taken from the survivors. Never applied to rrf_score, whose maximum "
    "is ~0.033."
)


class SearchHit(BaseModel):
    """One ranked chunk, carrying every field a citation needs (R2.5)."""

    chunk_id: str
    doc_id: str
    doc_title: str
    heading_path: str
    section: str
    rank: int
    dense_score: float
    bm25_rank: int | None = None
    rrf_score: float
    snippet: str
    char_start: int
    char_end: int
    quarantined: bool = False


class SearchOutput(BaseModel):
    """The §8.4 tool-1 result. `k_source` records which of the three `k` inputs won."""

    hits: list[SearchHit]
    query_used: str
    k_effective: int
    k_source: Literal["model", "override", "default"]
    strategy: Strategy
    total_candidates: int
    embed_ms: int
    search_ms: int
    index_version: str


def _resolve_k(supplied: bool, model_k: int, override: Any) -> tuple[int, str]:
    """`k_override` → the model's `k` → `RETRIEVAL_K`, with the override clamped to the schema range."""
    if isinstance(override, int) and not isinstance(override, bool):
        return max(1, min(10, override)), "override"
    if supplied:
        return model_k, "model"
    return settings.retrieval_k, "default"


def register(server: MCPServer, deps: ServerDeps) -> None:
    @server.tool(
        name="search_policy_documents",
        description=(
            "Semantic + lexical search over the 14 HR policy documents. Returns ranked chunks with "
            "the ids and heading paths a citation needs. Use it to find the passage that answers a "
            "policy question; use get_policy_section to read one in full."
        ),
        annotations=ToolAnnotations(**READ_ONLY),
    )
    async def search_policy_documents(
        ctx: Context,
        query: Annotated[str, Field(min_length=3, max_length=500, description="The question, in the user's words.")],
        k: Annotated[int, Field(ge=1, le=10, description="How many chunks to return.")] = 5,
        doc_ids: Annotated[list[str] | None, Field(description="Restrict the search to these doc_ids.")] = None,
        topic: Annotated[Topic | None, Field(description="Restrict the search to one corpus topic.")] = None,
        min_dense_score: Annotated[float, Field(ge=0, le=1, description=MIN_DENSE_SCORE_DESCRIPTION)] = 0.26,
    ) -> SearchOutput:
        call = read_meta(ctx)
        strategy = call.retrieval.get("strategy") or settings.retrieval_strategy
        if strategy not in ("hybrid_rrf", "dense_only"):
            return invalid_arguments(["_meta.mosaic/retrieval.strategy"])
        effective_k, k_source = _resolve_k(call.supplied("k"), k, call.retrieval.get("k_override"))
        threshold = min_dense_score if call.supplied("min_dense_score") else settings.min_support_score

        started = now_micros()
        body, payload = await asyncio.to_thread(
            _search,
            deps,
            query=query,
            k=effective_k,
            k_source=k_source,
            doc_ids=doc_ids,
            topic=topic,
            min_dense_score=threshold,
            strategy=strategy,
        )
        ended = now_micros()
        spans = [span_record("retrieval", "search_policy_documents", payload, started_at=started, ended_at=ended)]
        body["_trace"] = envelope(
            call, spans=spans, server_timing_ms=max(0, (ended - started) // 1000), transport=deps.transport
        )
        return result(body)


def _search(
    deps: ServerDeps,
    *,
    query: str,
    k: int,
    k_source: str,
    doc_ids: list[str] | None,
    topic: str | None,
    min_dense_score: float,
    strategy: str,
) -> tuple[dict[str, Any], RetrievalPayload]:
    """The blocking half: one embed, two index arms, the fusion. Always inside `asyncio.to_thread`."""
    from hrmosaic.core.corpusread import read_index_meta
    from hrmosaic.rag.retrieve import retrieve

    connection = deps.index()
    with deps.lock:
        retrieval = retrieve(
            query,
            k=k,
            doc_ids=doc_ids,
            topic=topic,
            min_dense_score=min_dense_score,
            strategy=strategy,
            connection=connection,
        )
        index_version = read_index_meta(connection).index_version

    hits = [
        SearchHit(
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            doc_title=hit.doc_title,
            heading_path=hit.heading_path,
            section=hit.section,
            rank=hit.rank,
            dense_score=round(hit.dense_score, 4),
            bm25_rank=hit.bm25_rank,
            rrf_score=round(hit.rrf_score, 6),
            snippet=hit.snippet,
            char_start=hit.char_start,
            char_end=hit.char_end,
        )
        for hit in retrieval.hits
    ]
    total_candidates = len(set(retrieval.dense_candidates) | set(retrieval.bm25_candidates))
    embed_ms = round(retrieval.embed_ms)
    search_ms = round(retrieval.search_ms)
    body = SearchOutput(
        hits=hits,
        query_used=query,
        k_effective=k,
        k_source=k_source,  # type: ignore[arg-type]
        strategy=strategy,  # type: ignore[arg-type]
        total_candidates=total_candidates,
        embed_ms=embed_ms,
        search_ms=search_ms,
        index_version=index_version,
    ).model_dump(mode="json")

    filters: dict[str, Any] = {}
    if doc_ids:
        filters["doc_ids"] = list(doc_ids)
    if topic:
        filters["topic"] = topic
    payload = RetrievalPayload(
        query=query,
        k=k,
        k_source=k_source,  # type: ignore[arg-type]
        filters=filters,
        strategy=strategy,  # type: ignore[arg-type]
        min_dense_score=min_dense_score,
        chunks=[
            RetrievedChunk(
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                doc_title=hit.doc_title,
                heading_path=hit.heading_path,
                section=hit.section,
                rank=hit.rank,
                dense_score=hit.dense_score,
                bm25_rank=hit.bm25_rank,
                rrf_score=hit.rrf_score,
                snippet=hit.snippet,
                quarantined=hit.quarantined,
            )
            for hit in hits
        ],
        max_dense_score=max((hit.dense_score for hit in hits), default=None),
        embed_ms=embed_ms,
        search_ms=search_ms,
        index_version=index_version,
    )
    return body, payload


__all__ = ["SearchHit", "SearchOutput", "Strategy", "Topic", "register"]
