"""`search_policy_documents.topic` is a SOFT filter (spec §8.4, R3.1).

The defect this closes is a retrieval one with a synthesis symptom. `topic` used to restrict the
candidate pool outright, which made the model's own topic guess the ceiling on what the answer
could cite: a `pto` search cannot see `manager-approval-matrix`, which the corpus tags `approvals`,
however directly the passage answers "who approves this?". The P10 baseline lost citation breadth
to exactly that — demo task 1 fell to two documents, and demo task 2 could never reach the approval
matrix from a `pto` search.

So the topic-filtered search still runs first and still leads the ranking, and then:

* **fewer than `k` hits** — every filtered hit is kept and the gap is filled from an unfiltered
  search of the same query;
* **`k` hits that all sit in ONE document** — the top `ceil(k/2)` filtered hits keep the majority
  of the slots and the rest go to the unfiltered ranking, because nothing can be added to a list
  that is already `k` long;
* **anything else** — the topic search is returned untouched.

Backfill hits from documents not yet represented come first: breadth is the whole point. Both the
tool result and the `retrieval` span carry `topic_backfilled` and `backfill_reason`, so an audit
can always tell a widened search from a plain one.

These run against the **real committed index**, because the widening is a claim about the real
corpus's topic tagging — `corpus_mini` gives every topic exactly one document, so the interesting
case could not exist there.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from hrmosaic.mcpserver.server import ServerDeps
from hrmosaic.mcpserver.tools.search_policy_documents import (
    _search,
    backfill_reason_for,
    merge_backfill,
)
from hrmosaic.rag.retrieve import retrieve

#: §7.1's own default (`MIN_SUPPORT_SCORE`), so these searches see what the agent sees.
THRESHOLD = 0.45

DEPS = ServerDeps()


def search(query: str, *, topic: str | None, k: int = 5, min_dense_score: float = THRESHOLD):
    return _search(
        DEPS,
        query=query,
        k=k,
        k_source="model",
        doc_ids=None,
        topic=topic,
        min_dense_score=min_dense_score,
        strategy="hybrid_rrf",
    )


def documents(body: dict) -> list[str]:
    return [hit["doc_id"] for hit in body["hits"]]


# --------------------------------------------------------------------------------------------
# The merge itself, as a pure function: every branch, without an embedder.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeHit:
    chunk_id: str
    doc_id: str


def hits(*pairs: str) -> list[FakeHit]:
    """`"a:1"` → one hit with `chunk_id="1"` in document `"a"`."""
    return [FakeHit(chunk_id=pair.split(":")[1], doc_id=pair.split(":")[0]) for pair in pairs]


def test_a_topic_search_that_fills_k_across_two_documents_needs_no_backfill():
    assert backfill_reason_for(hits("a:1", "a:2", "b:3"), 3) is None


def test_too_few_hits_is_the_first_trigger():
    assert backfill_reason_for(hits("a:1", "b:2"), 5) == "fewer_than_k"
    # Both triggers at once still reports the one that is true first and more specific.
    assert backfill_reason_for(hits("a:1"), 5) == "fewer_than_k"
    assert backfill_reason_for([], 5) == "fewer_than_k"


def test_one_document_is_the_second_trigger():
    assert backfill_reason_for(hits("a:1", "a:2", "a:3"), 3) == "single_document"


def test_a_short_result_keeps_every_filtered_hit_and_fills_the_gap():
    merged = merge_backfill(
        hits("a:1", "a:2"),
        hits("a:1", "b:3", "c:4", "a:9"),
        k=4,
        reason="fewer_than_k",
    )
    # `a:1` is deduped by chunk_id, and the two unseen documents lead the backfill.
    assert [hit.chunk_id for hit in merged] == ["1", "2", "3", "4"]


def test_a_one_document_result_gives_half_its_slots_away():
    merged = merge_backfill(
        hits("a:1", "a:2", "a:3", "a:4", "a:5"),
        hits("a:1", "b:6", "a:7", "c:8"),
        k=5,
        reason="single_document",
    )
    assert [hit.chunk_id for hit in merged] == ["1", "2", "3", "6", "8"]
    assert len(merged) == 5, "the widening never returns fewer hits than the hard filter would have"
    assert [hit.chunk_id for hit in merged[: math.ceil(5 / 2)]] == ["1", "2", "3"]


def test_documents_already_represented_come_after_the_new_ones():
    merged = merge_backfill(
        hits("a:1", "a:2", "a:3", "a:4"),
        hits("a:9", "b:8"),
        k=4,
        reason="single_document",
    )
    # `b:8` is second in the unfiltered ranking and first into the result: breadth is the point.
    assert [hit.chunk_id for hit in merged] == ["1", "2", "8", "9"]


def test_a_corpus_that_cannot_widen_gives_the_dropped_hits_back():
    """No other document has anything to say — the result must not shrink below `k`."""
    merged = merge_backfill(
        hits("a:1", "a:2", "a:3", "a:4", "a:5"),
        hits("a:1", "a:2"),
        k=5,
        reason="single_document",
    )
    assert [hit.chunk_id for hit in merged] == ["1", "2", "3", "4", "5"]


# --------------------------------------------------------------------------------------------
# The tool boundary, against the real corpus.
# --------------------------------------------------------------------------------------------


def test_a_topic_that_already_spans_two_documents_is_returned_untouched():
    """`conduct` is tagged on two documents, and this query reaches both: nothing to widen."""
    body, payload = search("harassment complaint investigation and escalation", topic="conduct")

    assert len(body["hits"]) == 5
    assert len(set(documents(body))) >= 2
    assert body["topic_backfilled"] is False
    assert body["backfill_reason"] is None
    assert payload.topic_backfilled is False and payload.backfill_reason is None
    assert set(documents(body)) == {"hr-escalation-and-case-handling", "workplace-conduct"}


def test_a_topic_search_that_comes_back_short_is_filled_from_the_whole_corpus():
    """`equipment` has almost nothing to say about parental leave; the corpus has plenty."""
    query = "parental leave pay continuation"
    # A threshold above §7.1's default, so the topic under-fills without needing a nonsense query:
    # the point is a real search whose topic is simply too narrow for what was asked.
    strict = 0.55
    hard = retrieve(
        query, k=5, topic="equipment", min_dense_score=strict, strategy="hybrid_rrf", connection=DEPS.index()
    )
    assert 0 < len(hard.hits) < 5, "the topic must under-fill, but not be empty, for this test to mean anything"

    body, payload = search(query, topic="equipment", min_dense_score=strict)

    assert body["backfill_reason"] == "fewer_than_k"
    assert body["topic_backfilled"] is True
    assert len(body["hits"]) == 5, "the gap the hard filter left is filled"
    assert {hit.chunk_id for hit in hard.hits} <= {hit["chunk_id"] for hit in body["hits"]}, (
        "a soft filter keeps every hit the hard one found"
    )
    assert payload.backfill_reason == "fewer_than_k"


def test_a_single_document_topic_reaches_the_document_the_tag_hid():
    """The measured case: `pto` is tagged on one document, and approvals live in another."""
    body, payload = search("PTO request notice period and manager approval", topic="pto")

    assert body["backfill_reason"] == "single_document"
    assert body["topic_backfilled"] is True
    assert len(body["hits"]) == 5
    assert documents(body)[: math.ceil(5 / 2)] == ["pto-and-holidays"] * 3, "the topic still leads"
    assert "manager-approval-matrix" in documents(body), "the approvals document was unreachable before"
    assert len(set(documents(body))) >= 2
    assert payload.backfill_reason == "single_document" and payload.topic_backfilled is True


def test_the_merged_hits_are_renumbered_over_what_the_model_is_shown():
    """Two retrievals each number their own hits from 1; a citation's rank means its position here."""
    body, payload = search("PTO request notice period and manager approval", topic="pto")

    assert [hit["rank"] for hit in body["hits"]] == [1, 2, 3, 4, 5]
    assert [chunk.rank for chunk in payload.chunks] == [1, 2, 3, 4, 5]
    assert len({hit["chunk_id"] for hit in body["hits"]}) == 5, "the merge deduped by chunk_id"


def test_a_search_with_no_topic_runs_exactly_what_it_always_did():
    """The unfiltered path is untouched: same hits, same order, and no widening claimed."""
    query = "annual leave carry-over and expiry"
    body, payload = search(query, topic=None)
    plain = retrieve(query, k=5, min_dense_score=THRESHOLD, strategy="hybrid_rrf", connection=DEPS.index())

    assert [hit["chunk_id"] for hit in body["hits"]] == [hit.chunk_id for hit in plain.hits]
    assert [hit["rank"] for hit in body["hits"]] == [hit.rank for hit in plain.hits]
    assert body["topic_backfilled"] is False
    assert body["backfill_reason"] is None
    assert payload.filters == {}, "no topic, no filter recorded"


def test_a_retrieval_row_written_before_the_widening_still_parses():
    """Both fields are defaulted (§10.2), so the rows the P10 baseline wrote read back unchanged."""
    from hrmosaic.core.models import RetrievalPayload

    old = RetrievalPayload.model_validate(
        {"kind": "retrieval", "query": "q", "k": 5, "k_source": "default", "strategy": "hybrid_rrf"}
    )
    assert old.topic_backfilled is False
    assert old.backfill_reason is None


@pytest.mark.parametrize("topic", ["pto", "onboarding", "conduct"])
def test_the_span_payload_always_carries_both_fields(topic):
    """§10.2's retrieval payload: an audit can tell a widened search from a plain one."""
    _, payload = search("manager approval for time away from work", topic=topic)
    dumped = payload.model_dump(mode="json")
    assert dumped["topic_backfilled"] in (True, False)
    assert dumped["backfill_reason"] in (None, "fewer_than_k", "single_document")
    assert (dumped["backfill_reason"] is not None) or (dumped["topic_backfilled"] is False)
