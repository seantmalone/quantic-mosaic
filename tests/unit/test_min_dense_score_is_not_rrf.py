"""The threshold filters `dense_score`, never `rrf_score`, and it runs *before* the cut to k (§7.1).

Two arms at k₀ = 60 cap `rrf_score` at `2/61 ≈ 0.0328`, so the default 0.26 applied to it would reject
every candidate of every query and the system would refuse everything at its own default
configuration. Naming the parameter `min_dense_score` is what makes that unrepresentable; this test is
what keeps it that way.

Two fixtures, because the two halves of the §7.1 cut need different shapes:

* `spec_case_index` is the spec's own sentence built exactly — a candidate with
  `rrf_score ≈ 0.03, dense_score = 0.71` is retained while `rrf_score ≈ 0.03, dense_score = 0.10` is
  dropped. The vectors are chosen, not embedded, so the two dense scores are the literals in that
  sentence.
* `ordering_case_index` holds **more than k** candidates and arranges the lexical arm so that the
  below-threshold candidate *outranks a passing one on `rrf_score`*. That is the only shape in which
  "filter, then truncate" and "truncate, then filter" disagree: the first returns k hits, the second
  returns fewer. Without it the ordering test cannot fail, whatever the implementation does.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from pathlib import Path

import pytest

from hrmosaic.rag import embed, index, retrieve
from hrmosaic.rag.chunk import chunk_corpus
from hrmosaic.rag.parse import parse_corpus

QUERY = "encrypted laptop policy for travel"
HIGH_DENSE = 0.71
LOW_DENSE = 0.10
THRESHOLD = 0.26

#: `doc_id -> (body sentence, chosen dense_score)`. The dense arm is monkeypatched, so the sentence
#: only ever reaches BM25 — which is exactly the lever the ordering case needs.
SPEC_CASE = {
    "high-doc": ("An encrypted laptop policy for travel that is close to the question.", HIGH_DENSE),
    "low-doc": ("An encrypted laptop policy for travel that is far from the question.", LOW_DENSE),
}

#: The ordering case. `ORDERING_QUERY`'s three words all appear in `below-floor-doc` and only
#: `travel` appears in `lexical-doc`, so the lexical arm returns those two, in that order, and
#: nothing else. Fused against the dense ranks that the chosen scores force (0.9 → 1, 0.8 → 2,
#: 0.7 → 3, 0.10 → 4) that puts the below-threshold chunk at the top of the fused ranking:
#:
#:   below-floor-doc  1/64 + 1/61 = 0.0320184   ← fails the threshold
#:   lexical-doc      1/63 + 1/62 = 0.0320020   ← passes
#:   high-doc         1/61        = 0.0163934   ← passes
#:   mid-doc          1/62        = 0.0161290   ← passes
#:
#: At k = 2: filtering first yields two hits (`lexical-doc`, `high-doc`); truncating first yields
#: one, because `below-floor-doc` would have eaten a slot it is not entitled to.
ORDERING_QUERY = "encrypted laptop travel"
ORDERING_CASE = {
    "high-doc": ("A confidential briefing about badge access in the main office lobby.", 0.9),
    "mid-doc": ("A confidential briefing about badge access in the secondary office lobby.", 0.8),
    "lexical-doc": ("Travel expenses are reimbursed within thirty days of the trip.", 0.7),
    "below-floor-doc": ("Every encrypted laptop taken on travel must be registered first.", 0.10),
}


def _unit(first: float) -> list[float]:
    """A 384-dimension unit vector whose cosine with `[1, 0, …]` is exactly `first`."""
    return [first, math.sqrt(1.0 - first * first)] + [0.0] * 382


def _build(case: dict[str, tuple[str, float]], tmp_path: Path, monkeypatch) -> Iterator[object]:
    """One chunk per document, each carrying the dense score the case chose for it."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for doc_id, (sentence, _) in case.items():
        (corpus / f"{doc_id}.md").write_text(
            f"# {doc_id}\n\nDocument ID: {doc_id} · Owner: People Operations · "
            f"Effective 2026-01-01 · Version 2026.1\nTopics: data_security\n\n## Body\n\n{sentence}\n",
            encoding="utf-8",
        )
    documents = parse_corpus(corpus)
    chunks = chunk_corpus(documents)
    assert [chunk.doc_id for chunk in chunks] == sorted(case), "one chunk per document, in file order"

    scores = {sentence: score for sentence, score in case.values()}
    monkeypatch.setattr(
        embed,
        "embed_passages",
        lambda texts: [_unit(next(score for body, score in scores.items() if body in text)) for text in texts],
    )
    monkeypatch.setattr(embed, "embed_query", lambda text: _unit(1.0))
    index_path = index.build_index(
        chunks,
        documents,
        index_path=tmp_path / "case.sqlite",
        corpus_sha256="0" * 64,
        manifest_sha256="1" * 64,
        format_counts={},
    )
    connection = index.open_index(index_path, check=False)
    yield connection
    connection.close()


@pytest.fixture
def spec_case_index(tmp_path: Path, monkeypatch):
    yield from _build(SPEC_CASE, tmp_path, monkeypatch)


@pytest.fixture
def ordering_case_index(tmp_path: Path, monkeypatch):
    yield from _build(ORDERING_CASE, tmp_path, monkeypatch)


def _doc_ids(result: retrieve.RetrievalResult) -> list[str]:
    return [hit.doc_id for hit in result.hits]


def _docs_of(connection, chunk_ids: list[str]) -> list[str]:
    """The documents behind a candidate list, in candidate order."""
    rows = dict(connection.execute("SELECT chunk_id, doc_id FROM chunks").fetchall())
    return [rows[chunk_id] for chunk_id in chunk_ids]


def test_both_candidates_score_far_below_the_threshold_on_rrf(spec_case_index):
    result = retrieve.retrieve(QUERY, k=5, connection=spec_case_index, min_dense_score=-1.0)
    assert len(result.hits) == 2
    assert all(hit.rrf_score < THRESHOLD for hit in result.hits)
    assert max(hit.rrf_score for hit in result.hits) <= 2 / (retrieve.RRF_K0 + 1)
    assert {round(hit.dense_score, 2) for hit in result.hits} == {HIGH_DENSE, LOW_DENSE}


def test_the_high_dense_candidate_is_retained_and_the_low_one_is_dropped(spec_case_index):
    result = retrieve.retrieve(QUERY, k=5, connection=spec_case_index, min_dense_score=THRESHOLD)
    assert _doc_ids(result) == ["high-doc"]
    kept = result.hits[0]
    assert kept.dense_score == pytest.approx(HIGH_DENSE, abs=1e-6)
    assert kept.rrf_score < THRESHOLD, "retention cannot have been decided by rrf_score"


def test_a_below_threshold_candidate_can_outrank_a_passing_one_on_rrf(ordering_case_index):
    """The premise of the ordering test: without it, the two cut orders cannot disagree."""
    result = retrieve.retrieve(ORDERING_QUERY, k=4, connection=ordering_case_index, min_dense_score=-1.0)
    assert _docs_of(ordering_case_index, result.dense_candidates) == [
        "high-doc",
        "mid-doc",
        "lexical-doc",
        "below-floor-doc",
    ], "the chosen vectors order the dense arm"
    assert _docs_of(ordering_case_index, result.bm25_candidates) == [
        "below-floor-doc",
        "lexical-doc",
    ], "and the sentences order the lexical arm"
    assert _doc_ids(result) == ["below-floor-doc", "lexical-doc", "high-doc", "mid-doc"]
    top = result.hits[0]
    assert top.dense_score == pytest.approx(0.10, abs=1e-6), "the top of the fused ranking fails the threshold"
    assert top.rrf_score > result.hits[1].rrf_score
    assert result.hits[1].dense_score == pytest.approx(0.7, abs=1e-6), "and the runner-up passes it"


def test_the_threshold_is_applied_before_the_truncation_to_k(ordering_case_index):
    """Filter, *then* take the top k — never truncate first and filter the survivors.

    Four candidates, k = 2, and the fused ranking led by a chunk that fails the threshold. Filtering
    first fills both slots with passing chunks; truncating first would spend one slot on the failing
    chunk and return a single hit.
    """
    result = retrieve.retrieve(ORDERING_QUERY, k=2, connection=ordering_case_index, min_dense_score=THRESHOLD)
    assert len(result.dense_candidates) == 4, "the failing chunk was in the pool the cut ran over"
    assert len(result.hits) == 2, "truncate-then-filter would have returned 1"
    assert _doc_ids(result) == ["lexical-doc", "high-doc"]
    assert all(hit.dense_score >= THRESHOLD for hit in result.hits)
    assert [hit.rank for hit in result.hits] == [1, 2]
