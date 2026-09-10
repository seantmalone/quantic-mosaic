"""G2 `citation_resolvability` (spec §7.4 row G2).

Resolution reads the **real index** through `core.corpusread.get_chunk`, never the retrieved set —
so the two cases the spec names explicitly are both here: an id that exists in the index but was
never retrieved (it resolves, because a reader can follow it), and an id that exists nowhere (it is
stripped). Between them sit the three drift triggers: displayed metadata that mismatches the chunk,
a displayed snippet that is not a whitespace-normalised substring of the chunk text, and a chunk G4
quarantined.

Then the cascade, which is the part that matters on camera: strip the citation; if a `policy_fact`
loses **all** of its citations, drop the block; if every block drops, refuse.
"""

from __future__ import annotations

from hrmosaic.agent.guardrails import g2
from hrmosaic.agent.orchestrator import EvidenceChunk
from hrmosaic.core import corpusread

UNKNOWN = "c_0000000000000000"


def a_chunk(doc_id: str = "pto-and-holidays"):
    """A real chunk of a real document, from the committed index."""
    return corpusread.list_chunks(doc_id)[0]


def displayed(chunk, **overrides) -> EvidenceChunk:
    """What a tool result claimed about that chunk — the half that can drift from the index."""
    fields = {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "doc_title": chunk.doc_title,
        "heading_path": chunk.heading_path,
        "section": chunk.section,
        "snippet": chunk.snippet,
        "dense_score": 0.71,
        "quarantined": False,
    }
    return EvidenceChunk(**{**fields, **overrides})


def fact(*citations: str) -> dict:
    return {"type": "policy_fact", "text": "Full-time employees accrue PTO monthly.", "citations": list(citations)}


def test_an_id_in_the_index_that_was_never_retrieved_still_resolves():
    """The whole reason resolution reads the index rather than the retrieved set (§7.4)."""
    chunk = a_chunk()
    resolution = g2.resolve(chunk.chunk_id, displayed=None)
    assert resolution.ok
    assert resolution.citation is not None
    assert resolution.citation.doc_id == chunk.doc_id
    assert resolution.citation.source_url == f"/dashboard/corpus/{chunk.doc_id}#{chunk.chunk_id}"


def test_an_id_that_exists_nowhere_is_stripped():
    resolution = g2.resolve(UNKNOWN)
    assert not resolution.ok
    assert resolution.reason == "unknown chunk_id"
    assert resolution.citation is None


def test_displayed_metadata_that_mismatches_the_index_is_stripped():
    chunk = a_chunk()
    resolution = g2.resolve(chunk.chunk_id, displayed=displayed(chunk, doc_id="travel-policy"))
    assert not resolution.ok
    assert resolution.reason == "displayed doc_id mismatches the index"


def test_a_displayed_snippet_that_is_not_in_the_chunk_is_stripped():
    chunk = a_chunk()
    resolution = g2.resolve(chunk.chunk_id, displayed=displayed(chunk, snippet="Employees accrue 99 days per month."))
    assert not resolution.ok
    assert resolution.reason == "displayed snippet is not in the chunk text"


def test_whitespace_differences_in_the_snippet_are_not_drift():
    chunk = a_chunk()
    reflowed = "  ".join(chunk.snippet.split())
    assert g2.resolve(chunk.chunk_id, displayed=displayed(chunk, snippet=reflowed)).ok


def test_a_quarantined_chunk_can_never_be_cited():
    chunk = a_chunk()
    by_flag = g2.resolve(chunk.chunk_id, displayed=displayed(chunk, quarantined=True))
    by_set = g2.resolve(chunk.chunk_id, quarantined=True)
    assert not by_flag.ok and not by_set.ok
    assert by_flag.reason == "quarantined chunk (G4)"


def test_a_policy_fact_that_loses_every_citation_is_dropped():
    chunk = a_chunk()
    outcome = g2.apply([fact(chunk.chunk_id), fact(UNKNOWN)])
    assert outcome.dropped_blocks == 1
    assert len(outcome.blocks) == 1
    assert outcome.blocks[0]["citations"] == [chunk.chunk_id]
    assert [item.chunk_id for item in outcome.stripped] == [UNKNOWN]
    assert not outcome.refused


def test_a_policy_fact_that_loses_one_of_two_citations_keeps_the_other():
    chunk = a_chunk()
    outcome = g2.apply([fact(chunk.chunk_id, UNKNOWN)])
    assert outcome.blocks[0]["citations"] == [chunk.chunk_id]
    assert outcome.dropped_blocks == 0
    assert [citation.chunk_id for citation in outcome.citations] == [chunk.chunk_id]


def test_when_every_block_drops_the_answer_refuses():
    outcome = g2.apply([fact(UNKNOWN), fact("c_1111111111111111")])
    assert outcome.blocks == []
    assert outcome.refused


def test_an_uncited_policy_fact_is_left_for_g3():
    """G2 strips what was lost; a block that never had a citation is G3's relabel, not G2's drop."""
    outcome = g2.apply([{"type": "policy_fact", "text": "Probably fine.", "citations": []}])
    assert outcome.blocks == [{"type": "policy_fact", "text": "Probably fine.", "citations": []}]
    assert not outcome.repaired


def test_an_escalation_block_with_no_citations_survives():
    outcome = g2.apply([{"type": "escalation", "text": "Contact People Operations.", "citations": []}])
    assert len(outcome.blocks) == 1
    assert not outcome.refused


def test_the_span_names_every_stripped_citation(writer, spans):
    from hrmosaic.core.trace import SessionSpec

    chunk = a_chunk()
    turn = writer.start_turn(SessionSpec(client_label="api"), user_message="pto accrual")
    outcome = g2.check([fact(chunk.chunk_id, UNKNOWN)], turn=turn, evidence={chunk.chunk_id: displayed(chunk)})
    turn.close(outcome="answered", stop_reason="answered")

    payload = next(payload for kind, _, payload in spans(turn.turn_id) if kind == "guardrail")
    assert (payload["rule_id"], payload["verdict"]) == ("G2", "repair")
    assert payload["reason"] == "1/2 citations resolved"
    assert payload["details"]["stripped"] == [{"chunk_id": UNKNOWN, "reason": "unknown chunk_id"}]
    assert outcome.citations[0].score == 0.71, "the displayed dense score rides on the citation (§7.3)"
