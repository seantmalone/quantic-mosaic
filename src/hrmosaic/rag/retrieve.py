"""Hybrid retrieval: dense + BM25, fused with RRF, filtered on `dense_score` (spec §7.1, R3.1).

    query
     ├─ dense:   embed_query(q) → vec0 KNN k=20   → dense_score = 1 − cosine_distance
     ├─ lexical: chunks_fts MATCH bm25()          → top 20
     ├─ filter:  optional doc_ids[] / topic (applied to BOTH arms BEFORE fusion)
     ├─ fuse:    RRF score(c) = Σ_arms 1 / (60 + rank_arm(c))
     ├─ fill:    every candidate that entered from the BM25 arm only is scored against the query
     │           vector using its STORED embedding, so dense_score is never null
     └─ cut:     drop candidates below min_dense_score, THEN take the top k

**The threshold filters `dense_score`, never `rrf_score`.** Two arms at k₀ = 60 cap `rrf_score` at
`2/61 ≈ 0.0328`, so a 0.26 threshold applied to it would reject every candidate of every query and the
system would refuse everything at its own default configuration. The parameter is therefore named
`min_dense_score`, and `tests/unit/test_min_dense_score_is_not_rrf.py` pins the distinction.

**The fill step reads stored vectors** and dots them against the query vector the dense arm already
computed. It never re-embeds chunk text: that would cost hundreds of milliseconds per chunk on 0.1 CPU
and would put an embedder call inside this module, which §4.2 forbids. Exactly one embed call happens
per retrieval, whatever the strategy.

`k` and `strategy` arrive as arguments — no module-level global is ever mutated (§7.1). The MCP tool
that calls this resolves the precedence `_meta.k_override → the model's k → RETRIEVAL_K` and emits the
`retrieval` span from the numbers returned here.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from hrmosaic.rag import embed, index
from hrmosaic.settings import settings

#: Candidates drawn from each arm before fusion (§7.1).
ARM_K = 20
#: RRF's rank constant k₀ (§7.1).
RRF_K0 = 60


@dataclass(frozen=True)
class Hit:
    """One ranked chunk, carrying every field a citation and a `retrieval` span need."""

    chunk_id: str
    doc_id: str
    doc_title: str
    source_format: str
    heading_path: str
    section: str
    text: str
    snippet: str
    char_start: int
    char_end: int
    topics: tuple[str, ...]
    dense_score: float
    bm25_rank: int | None
    rrf_score: float
    rank: int


@dataclass(frozen=True)
class RetrievalResult:
    """What one retrieval produced, including the pre-fusion candidate sets a test can check."""

    hits: list[Hit]
    strategy: str
    k: int
    min_dense_score: float
    dense_candidates: list[str] = field(default_factory=list)
    bm25_candidates: list[str] = field(default_factory=list)
    embed_ms: float = 0.0
    search_ms: float = 0.0


def rrf_score(ranks: list[int], k0: int = RRF_K0) -> float:
    """Reciprocal rank fusion over one candidate's 1-based ranks in the arms that returned it."""
    return sum(1.0 / (k0 + rank) for rank in ranks)


def score_chunk_ids(
    chunk_ids: Sequence[str],
    *,
    query: str,
    connection: sqlite3.Connection | None = None,
) -> dict[str, float]:
    """The dense score chunks that are **already known** would have had, without searching for them.

    §7.4's G1 scores retrieved candidates. `check_policy_compliance` cites committed chunks it
    resolved from `corpus/rules.yml` rather than from a search, so those ids reach the turn with no
    score at all and were invisible to the gate — a correct, cited verdict could be refused for want
    of evidence (P13 R7). This is the one function that closes that gap, and it closes it by
    scoring, never by admitting: it is §7.1's **fill step**, applied to an explicit id list rather
    than to the BM25-only arrivals — `1 − cosine_distance` between the query vector and each chunk's
    **stored** embedding, which is exactly what `retrieve()` puts on a `Hit`.

    One embed call, and none at all when nothing resolves. An id that is not in the index is simply
    absent from the result: an unknown citation is not an error here, it is nothing (§7.4 G2 makes
    the same choice).
    """
    if not chunk_ids:
        return {}
    owned = connection is None
    connection = connection if connection is not None else index.open_index()
    try:
        placeholders = ", ".join("?" for _ in chunk_ids)
        rows = connection.execute(
            f"SELECT rowid, chunk_id FROM chunks WHERE chunk_id IN ({placeholders})", list(chunk_ids)
        ).fetchall()
        vectors = index.stored_vectors(connection, [row["rowid"] for row in rows])
    finally:
        if owned:
            connection.close()
    if not vectors:
        return {}
    vector = embed.embed_query(query)
    return {row["chunk_id"]: index.cosine(vectors[row["rowid"]], vector) for row in rows if row["rowid"] in vectors}


def retrieve(
    query: str,
    *,
    k: int | None = None,
    doc_ids: list[str] | None = None,
    topic: str | None = None,
    min_dense_score: float | None = None,
    strategy: str | None = None,
    connection: sqlite3.Connection | None = None,
) -> RetrievalResult:
    """Run the §7.1 pipeline and return the ranked hits with their pre-fusion candidate sets."""
    k = settings.retrieval_k if k is None else k
    strategy = settings.retrieval_strategy if strategy is None else strategy
    min_dense_score = settings.min_support_score if min_dense_score is None else min_dense_score
    owned = connection is None
    connection = connection if connection is not None else index.open_index()
    try:
        started = time.perf_counter()
        vector = embed.embed_query(query)
        embed_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        rowids = index.allowed_rowids(connection, doc_ids, topic)
        dense = index.dense_knn(connection, vector, ARM_K, rowids)
        lexical = index.bm25_top(connection, query, ARM_K, rowids) if strategy != "dense_only" else []

        dense_scores = dict(dense)
        bm25_ranks = {rowid: position for position, rowid in enumerate(lexical, start=1)}
        dense_ranks = {rowid: position for position, (rowid, _) in enumerate(dense, start=1)}

        candidates = list(dense_ranks) + [rowid for rowid in bm25_ranks if rowid not in dense_ranks]
        # The fill step: a BM25-only candidate is scored against the query vector using its stored
        # embedding, so `dense_score` is never null and the threshold below is total.
        missing = [rowid for rowid in candidates if rowid not in dense_scores]
        for rowid, stored in index.stored_vectors(connection, missing).items():
            dense_scores[rowid] = index.cosine(stored, vector)

        rows = index.chunk_rows(connection, candidates)
        search_ms = (time.perf_counter() - started) * 1000
    finally:
        if owned:
            connection.close()

    scored = [
        (
            rowid,
            rrf_score([rank for rank in (dense_ranks.get(rowid), bm25_ranks.get(rowid)) if rank]),
            dense_scores.get(rowid, 0.0),
        )
        for rowid in candidates
    ]
    kept = [entry for entry in scored if entry[2] >= min_dense_score]
    kept.sort(key=lambda entry: (-entry[1], -entry[2], entry[0]))

    hits: list[Hit] = []
    for rank, (rowid, fused, dense_score) in enumerate(kept[:k], start=1):
        row = rows[rowid]
        hits.append(
            Hit(
                chunk_id=row["chunk_id"],
                doc_id=row["doc_id"],
                doc_title=row["doc_title"],
                source_format=row["source_format"],
                heading_path=row["heading_path"],
                section=row["section"],
                text=row["text"],
                snippet=row["snippet"],
                char_start=row["char_start"],
                char_end=row["char_end"],
                topics=tuple(json.loads(row["topics"])),
                dense_score=dense_score,
                bm25_rank=bm25_ranks.get(rowid),
                rrf_score=fused,
                rank=rank,
            )
        )
    return RetrievalResult(
        hits=hits,
        strategy=strategy,
        k=k,
        min_dense_score=min_dense_score,
        dense_candidates=[rows[rowid]["chunk_id"] for rowid, _ in dense],
        bm25_candidates=[rows[rowid]["chunk_id"] for rowid in lexical],
        embed_ms=embed_ms,
        search_ms=search_ms,
    )
