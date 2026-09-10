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
* **A hit carries the whole chunk** (W2-C). `snippet` is a 320-character *display* subset and 116 of
  116 deployed retrievals were longer than it (median 974), so 10 act steps across 7 turns existed
  only to call `get_policy_section` for text the search had already read. `Hit.text` comes off the
  same `retrieve()` call, clamped by `CHUNK_MAX_CHARS`, so the server does zero extra work. The
  §7.4 injection shield is what decides whether it may be *sent on*: the agent's `call_tool` scans
  every hit before the `tool_call` span is written, and a chunk whose text gives the assistant
  orders is handed to the loop as its snippet alone with `quarantined: true`.
* **`topic` is a SOFT filter** (P10 fix round; §8.4). It used to restrict the candidate pool
  outright, which made the model's own topic guess the ceiling on what the answer could cite: a
  `pto` search can never see `manager-approval-matrix`, which is tagged `approvals`, however
  relevant the passage is. The topic-filtered search still runs first and still leads the ranking —
  but when it comes back with fewer than `k` hits, or with `k` hits that all sit in ONE document,
  the remainder is backfilled from an unfiltered search of the same query, documents not yet
  represented first. `topic_backfilled` and `backfill_reason` are on the result and on the
  `retrieval` span, so an audit can always tell a soft widening from a plain topic search.
"""

from __future__ import annotations

import asyncio
import math
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

#: The published semantics of `topic` — a soft preference, not a wall. It says on the wire what the
#: result fields report, so a model reading only the catalog knows the filter can widen under it.
TOPIC_DESCRIPTION = (
    "Prioritise one corpus topic. When the topic alone yields fewer than k hits or a single "
    "document, results are backfilled from the whole corpus (see topic_backfilled)."
)

#: Why an unfiltered search was run underneath the topic-filtered one. `null` means it was not.
BackfillReason = Literal["fewer_than_k", "single_document"]

#: The most chunk text one hit may carry. 1,500 sits above the longest committed chunk (1,384), so
#: it truncates nothing today and is a bound on a future corpus rather than a live edit to policy
#: text: a hit's `text` is re-billed as input on **every** subsequent act step, so an unbounded
#: chunk would be an unbounded per-step cost. At the schema's ceiling of `k = 10` it caps one
#: search at 15,000 characters.
CHUNK_MAX_CHARS = 1500

#: How many hits the unfiltered backfill search asks for. Twice `k` because the filtered hits are
#: deduped out of it first: the same query without a topic returns many of the same chunks, and a
#: pool of exactly `k` could dedupe down to nothing to backfill with.
BACKFILL_POOL_FACTOR = 2


class SearchHit(BaseModel):
    """One ranked chunk, carrying every field a citation needs (R2.5) and the chunk itself.

    `text` is the stored chunk, clamped to `CHUNK_MAX_CHARS`; `snippet` stays the 320-character
    display subset a citation shows a reader. It is `null` — and `quarantined` is `true` — for a
    chunk the §7.4 injection shield has quarantined, because a chunk whose text gives the assistant
    orders must not be readable in the model's own context.
    """

    chunk_id: str
    doc_id: str
    doc_title: str
    heading_path: str
    section: str
    rank: int
    dense_score: float
    bm25_rank: int | None = None
    rrf_score: float
    text: str | None = None
    snippet: str
    char_start: int
    char_end: int
    quarantined: bool = False


class SearchOutput(BaseModel):
    """The §8.4 tool-1 result. `k_source` records which of the three `k` inputs won.

    `topic_backfilled` is `true` when at least one returned hit came from the unfiltered search the
    soft `topic` filter runs underneath itself, and `backfill_reason` says what triggered it. They
    move together: a widening that added nothing reports `false`/`null`, exactly as a search that
    passed no `topic` does.
    """

    hits: list[SearchHit]
    query_used: str
    k_effective: int
    k_source: Literal["model", "override", "default"]
    strategy: Strategy
    total_candidates: int
    embed_ms: int
    search_ms: int
    index_version: str
    topic_backfilled: bool = False
    backfill_reason: BackfillReason | None = None


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
            "the ids and heading paths a citation needs, each carrying the chunk's full text as "
            "well as a 320-character snippet, so a hit can be quoted without a second call; text "
            "is null on a hit marked quarantined, which carries its snippet only. Use "
            "get_policy_section for the sections AROUND a hit (include_neighbors) or for a section "
            "no search returned. topic prioritises one corpus topic; when the topic alone yields "
            "fewer than k hits or a single document, results are backfilled from the whole corpus."
        ),
        annotations=ToolAnnotations(**READ_ONLY),
    )
    async def search_policy_documents(
        ctx: Context,
        query: Annotated[str, Field(min_length=3, max_length=500, description="The question, in the user's words.")],
        k: Annotated[int, Field(ge=1, le=10, description="How many chunks to return.")] = 5,
        doc_ids: Annotated[list[str] | None, Field(description="Restrict the search to these doc_ids.")] = None,
        topic: Annotated[Topic | None, Field(description=TOPIC_DESCRIPTION)] = None,
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


def backfill_reason_for(hits: list[Any], k: int) -> BackfillReason | None:
    """Why a topic-filtered result needs widening, or `None` if it does not (§8.4).

    Two triggers, in this order: it returned fewer than the `k` hits that were asked for, or every
    hit it did return sits in one document. The second is the one the P10 baseline was losing
    breadth to — `k` hits, all from `pto-and-holidays`, and the answer could only ever cite one
    document however many rules from elsewhere applied.
    """
    if len(hits) < k:
        return "fewer_than_k"
    if len({hit.doc_id for hit in hits}) == 1:
        return "single_document"
    return None


def merge_backfill(filtered: list[Any], unfiltered: list[Any], *, k: int, reason: BackfillReason) -> list[Any]:
    """Filtered hits first, then unfiltered ones, capped at `k` (§8.4).

    * `fewer_than_k` — every filtered hit is kept; the gap is filled from the unfiltered ranking.
    * `single_document` — `k` is already full, so the top `ceil(k/2)` filtered hits keep the
      majority of the slots and the rest go to the unfiltered ranking. Halving rather than
      appending is what makes room: nothing can be added to a list that is already `k` long.

    Within the backfill, hits from documents not yet represented come first — the whole point is
    breadth — and the rest of the unfiltered ranking follows in its own order. Anything dropped by
    the halving is put back last if the corpus could not fill the slots, so a soft filter never
    returns fewer hits than the hard one would have.
    """
    keep = list(filtered) if reason == "fewer_than_k" else list(filtered[: math.ceil(k / 2)])
    chosen = {hit.chunk_id for hit in keep}
    represented = {hit.doc_id for hit in keep}
    fresh = [hit for hit in unfiltered if hit.chunk_id not in chosen]
    ordered = [hit for hit in fresh if hit.doc_id not in represented]
    ordered += [hit for hit in fresh if hit.doc_id in represented]
    ordered += [
        hit for hit in filtered if hit.chunk_id not in chosen and hit.chunk_id not in {h.chunk_id for h in fresh}
    ]
    return (keep + ordered)[:k]


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
    """The blocking half: the topic-filtered retrieval, its unfiltered backfill, the fusion.

    Always inside `asyncio.to_thread`. A search with no `topic` runs exactly one retrieval, as it
    always did; the second one happens only when `backfill_reason_for` asks for it.
    """
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
        ranked = list(retrieval.hits)
        backfill_reason = backfill_reason_for(ranked, k) if topic else None
        backfill = None
        if backfill_reason is not None:
            backfill = retrieve(
                query,
                k=k * BACKFILL_POOL_FACTOR,
                doc_ids=doc_ids,
                topic=None,
                min_dense_score=min_dense_score,
                strategy=strategy,
                connection=connection,
            )
            ranked = merge_backfill(ranked, backfill.hits, k=k, reason=backfill_reason)
        index_version = read_index_meta(connection).index_version

    topic_backfilled = bool({hit.chunk_id for hit in ranked} - {hit.chunk_id for hit in retrieval.hits})
    # `backfill_reason` records why the result *was* widened, not why a widening was attempted. The
    # unfiltered pool can have nothing to add — a corpus small enough that the topic already held
    # every hit — and the merge then returns exactly what the hard filter returned. A reason left on
    # such a row would claim a widening the model never saw, so the two fields move together.
    if not topic_backfilled:
        backfill_reason = None

    # `rank` is renumbered over the merged list, not carried from whichever retrieval produced the
    # hit: two searches each number their own hits from 1, and a citation's rank has to mean its
    # position in what the model was actually shown.
    hits = [
        SearchHit(
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            doc_title=hit.doc_title,
            heading_path=hit.heading_path,
            section=hit.section,
            rank=rank,
            dense_score=round(hit.dense_score, 4),
            bm25_rank=hit.bm25_rank,
            rrf_score=round(hit.rrf_score, 6),
            text=hit.text[:CHUNK_MAX_CHARS],
            snippet=hit.snippet,
            char_start=hit.char_start,
            char_end=hit.char_end,
        )
        for rank, hit in enumerate(ranked, start=1)
    ]
    candidates = set(retrieval.dense_candidates) | set(retrieval.bm25_candidates)
    if backfill is not None:
        candidates |= set(backfill.dense_candidates) | set(backfill.bm25_candidates)
    total_candidates = len(candidates)
    embed_ms = round(retrieval.embed_ms + (backfill.embed_ms if backfill else 0.0))
    # True when *either* pass was served from the query memo — on a backfilled search the second
    # `retrieve()` runs the identical query string, and that hit is the whole of W1-B's saving.
    # It goes on the span only: `SearchOutput` is bytes the model reads, and this is telemetry.
    embed_cache_hit = retrieval.embed_cache_hit or (backfill.embed_cache_hit if backfill else False)
    search_ms = round(retrieval.search_ms + (backfill.search_ms if backfill else 0.0))
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
        topic_backfilled=topic_backfilled,
        backfill_reason=backfill_reason,
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
        embed_cache_hit=embed_cache_hit,
        search_ms=search_ms,
        index_version=index_version,
        topic_backfilled=topic_backfilled,
        backfill_reason=backfill_reason,
    )
    return body, payload


__all__ = [
    "BACKFILL_POOL_FACTOR",
    "CHUNK_MAX_CHARS",
    "TOPIC_DESCRIPTION",
    "BackfillReason",
    "SearchHit",
    "SearchOutput",
    "Strategy",
    "Topic",
    "backfill_reason_for",
    "merge_backfill",
    "register",
]
