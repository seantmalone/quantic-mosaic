"""The threshold filters `dense_score`, never `rrf_score` (spec §7.1).

Two arms at k₀ = 60 cap `rrf_score` at `2/61 ≈ 0.0328`, so the default 0.26 applied to it would reject
every candidate of every query and the system would refuse everything at its own default
configuration. Naming the parameter `min_dense_score` is what makes that unrepresentable; this test is
what keeps it that way.

The spec's own case, built exactly: a candidate with `rrf_score ≈ 0.03, dense_score = 0.71` is
retained while `rrf_score ≈ 0.03, dense_score = 0.10` is dropped. The vectors are chosen, not
embedded, so the two dense scores are the literals in that sentence.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from hrmosaic.rag import embed, index, retrieve
from hrmosaic.rag.chunk import chunk_corpus
from hrmosaic.rag.parse import parse_corpus

QUERY = "encrypted laptop policy for travel"
HIGH_DENSE = 0.71
LOW_DENSE = 0.10
THRESHOLD = 0.26

DOCUMENTS = {
    "high-doc": "An encrypted laptop policy for travel that is close to the question.",
    "low-doc": "An encrypted laptop policy for travel that is far from the question.",
}


def _unit(first: float) -> list[float]:
    """A 384-dimension unit vector whose cosine with `[1, 0, …]` is exactly `first`."""
    return [first, math.sqrt(1.0 - first * first)] + [0.0] * 382


@pytest.fixture
def two_chunk_index(tmp_path: Path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for doc_id, sentence in DOCUMENTS.items():
        (corpus / f"{doc_id}.md").write_text(
            f"# {doc_id}\n\nDocument ID: {doc_id} · Owner: People Operations · "
            f"Effective 2026-01-01 · Version 2026.1\nTopics: data_security\n\n## Body\n\n{sentence}\n",
            encoding="utf-8",
        )
    documents = parse_corpus(corpus)
    chunks = chunk_corpus(documents)
    assert [chunk.doc_id for chunk in chunks] == ["high-doc", "low-doc"]

    monkeypatch.setattr(embed, "embed_passages", lambda texts: [_unit(HIGH_DENSE), _unit(LOW_DENSE)])
    monkeypatch.setattr(embed, "embed_query", lambda text: _unit(1.0))
    index_path = index.build_index(
        chunks,
        documents,
        index_path=tmp_path / "two.sqlite",
        corpus_sha256="0" * 64,
        manifest_sha256="1" * 64,
        format_counts={},
    )
    connection = index.open_index(index_path, check=False)
    yield connection
    connection.close()


def test_both_candidates_score_far_below_the_threshold_on_rrf(two_chunk_index):
    result = retrieve.retrieve(QUERY, k=5, connection=two_chunk_index, min_dense_score=-1.0)
    assert len(result.hits) == 2
    assert all(hit.rrf_score < THRESHOLD for hit in result.hits)
    assert max(hit.rrf_score for hit in result.hits) <= 2 / (retrieve.RRF_K0 + 1)
    assert {round(hit.dense_score, 2) for hit in result.hits} == {HIGH_DENSE, LOW_DENSE}


def test_the_high_dense_candidate_is_retained_and_the_low_one_is_dropped(two_chunk_index):
    result = retrieve.retrieve(QUERY, k=5, connection=two_chunk_index, min_dense_score=THRESHOLD)
    assert [hit.doc_id for hit in result.hits] == ["high-doc"]
    kept = result.hits[0]
    assert kept.dense_score == pytest.approx(HIGH_DENSE, abs=1e-6)
    assert kept.rrf_score < THRESHOLD, "retention cannot have been decided by rrf_score"


def test_the_threshold_is_applied_before_the_truncation_to_k(two_chunk_index):
    """Filter, *then* take the top k — never truncate first and filter the survivors."""
    result = retrieve.retrieve(QUERY, k=2, connection=two_chunk_index, min_dense_score=THRESHOLD)
    assert len(result.hits) == 1
    assert len(result.dense_candidates) == 2
