"""R3.1's named unit test (spec §7.1), clause by clause.

(a) `len(hits) == k` whenever ≥ k fused candidates clear `min_dense_score`, and never more;
(b) `doc_ids` and `topic` filters are applied to **both** arms before fusion, verified against the
    pre-fusion candidate sets;
(c) a BM25-only candidate emerges with a non-null `dense_score` while **exactly one** query embed
    occurs for the whole retrieval.

Everything runs against the `corpus_mini` index built with the fake embedder, so the suite stays
offline and the scores are deterministic without being calibrated.
"""

from __future__ import annotations

import pytest

from hrmosaic.rag import embed, retrieve

QUERY = "imaginary time off accrual and encryption"
#: Below the tool's declared `[0, 1]` range on purpose: these tests are about ranking and filtering,
#: not about a calibrated threshold, and the fake embedder's scores hover around zero.
KEEP_EVERYTHING = -1.0


@pytest.fixture
def search(mini_index, fake_embedder):
    def run(**kwargs):
        kwargs.setdefault("min_dense_score", KEEP_EVERYTHING)
        return retrieve.retrieve(QUERY, connection=mini_index, **kwargs)

    return run


def test_a_retrieval_returns_exactly_k_hits_when_enough_candidates_clear(search):
    for k in (1, 3, 5):
        result = search(k=k)
        assert len(result.hits) == k
        assert [hit.rank for hit in result.hits] == list(range(1, k + 1))


def test_hits_are_ordered_by_rrf_score(search):
    result = search(k=10)
    assert [hit.rrf_score for hit in result.hits] == sorted((hit.rrf_score for hit in result.hits), reverse=True)
    assert all(hit.rrf_score <= 2 / (retrieve.RRF_K0 + 1) for hit in result.hits)


def test_a_doc_ids_filter_applies_to_both_arms_before_fusion(mini_index, search):
    unfiltered = search(k=10)
    assert len({hit.doc_id for hit in unfiltered.hits}) > 1

    result = search(k=10, doc_ids=["mini-md"])
    assert {hit.doc_id for hit in result.hits} == {"mini-md"}
    assert result.dense_candidates and result.bm25_candidates

    allowed = {row[0] for row in mini_index.execute("SELECT chunk_id FROM chunks WHERE doc_id = 'mini-md'")}
    assert set(result.dense_candidates) <= allowed
    assert set(result.bm25_candidates) <= allowed
    # Pre-fusion, not post-filtering: the unfiltered arms saw chunks the filter excludes.
    assert not set(unfiltered.dense_candidates) <= allowed


def test_a_topic_filter_applies_to_both_arms_before_fusion(mini_index, search):
    result = search(k=10, topic="data_security")
    assert {hit.doc_id for hit in result.hits} == {"mini-txt"}
    assert all("data_security" in hit.topics for hit in result.hits)

    allowed = {row[0] for row in mini_index.execute("SELECT chunk_id FROM chunks WHERE topics LIKE '%data_security%'")}
    assert set(result.dense_candidates) <= allowed
    assert set(result.bm25_candidates) <= allowed
    assert result.bm25_candidates, "the lexical arm must still return something inside the filter"


def test_a_filter_that_matches_nothing_returns_no_hits(search):
    result = search(k=5, doc_ids=["no-such-document"])
    assert result.hits == []
    assert result.dense_candidates == []
    assert result.bm25_candidates == []


def test_a_bm25_only_candidate_gets_a_dense_score_from_one_query_embed(mini_index, fake_embedder, monkeypatch):
    """The fill step reads stored vectors; it never re-embeds chunk text (§7.1, §4.2)."""
    calls: list[str] = []
    original = embed.embed_query
    monkeypatch.setattr(embed, "embed_query", lambda text: calls.append(text) or original(text))
    # The mini corpus is smaller than one arm's k, so the dense arm would otherwise return every
    # chunk and no candidate could be BM25-only.
    monkeypatch.setattr(retrieve, "ARM_K", 3)

    result = retrieve.retrieve(QUERY, k=10, connection=mini_index, min_dense_score=KEEP_EVERYTHING)

    assert len(calls) == 1
    bm25_only = [
        hit for hit in result.hits if hit.bm25_rank is not None and hit.chunk_id not in result.dense_candidates
    ]
    assert bm25_only, "the arms must disagree for this test to mean anything"
    for hit in bm25_only:
        assert isinstance(hit.dense_score, float)
        assert -1.0 <= hit.dense_score <= 1.0
        assert hit.rrf_score == pytest.approx(1 / (retrieve.RRF_K0 + hit.bm25_rank))


def test_dense_only_makes_no_lexical_arm(mini_index, fake_embedder):
    result = retrieve.retrieve(
        QUERY, k=5, connection=mini_index, min_dense_score=KEEP_EVERYTHING, strategy="dense_only"
    )
    assert result.strategy == "dense_only"
    assert result.bm25_candidates == []
    assert all(hit.bm25_rank is None for hit in result.hits)
    assert result.hits


def test_every_hit_carries_the_span_and_citation_fields(search):
    for hit in search(k=5).hits:
        assert hit.chunk_id and hit.doc_id and hit.doc_title and hit.heading_path and hit.section
        assert hit.snippet in " ".join(hit.text.split())
        assert hit.char_end > hit.char_start >= 0
        assert isinstance(hit.dense_score, float)
        assert isinstance(hit.rrf_score, float)


def test_timings_are_recorded_for_the_retrieval_span(search):
    result = search(k=3)
    assert result.embed_ms >= 0.0
    assert result.search_ms >= 0.0
    assert result.k == 3
    assert result.strategy == "hybrid_rrf"
