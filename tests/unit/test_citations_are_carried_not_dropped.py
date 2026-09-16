"""No post-synthesis step drops a citation from a surviving policy fact (W9 addendum, ruling 2).

`remote-002` (multi_doc, `answer_with_citations`, three distinct documents required) reached the
breadth repair citing three documents and was served citing two: a later step took a block, and
the block's citations went with it. `breadth.carry_citations` puts a lost citation back on the
nearest surviving policy fact, so the served set is a superset of the repair's.
"""

from __future__ import annotations

from hrmosaic.agent import breadth


def _fact(text: str, *citations: str) -> dict:
    return {"type": "policy_fact", "text": text, "citations": list(citations)}


def test_a_citation_lost_with_its_block_moves_to_the_nearest_surviving_fact():
    reference = [_fact("Rule one.", "c_one"), _fact("Rule two.", "c_two"), _fact("Rule three.", "c_three")]
    served = [_fact("Rule one.", "c_one"), _fact("Rule three.", "c_three")]  # a step dropped the middle block

    blocks, carried = breadth.carry_citations(reference, served)

    assert carried == ["c_two"]
    assert {citation for block in blocks for citation in block["citations"]} >= {"c_one", "c_two", "c_three"}
    assert blocks[0]["citations"] == ["c_one", "c_two"], "the earlier neighbour takes the tie"


def test_an_answer_that_kept_every_citation_is_returned_byte_for_byte():
    reference = [_fact("Rule one.", "c_one"), {"type": "record", "text": "You have 13.5 days.", "citations": []}]
    blocks, carried = breadth.carry_citations(reference, reference)
    assert (blocks, carried) == (reference, [])


def test_nothing_is_carried_when_no_policy_fact_survives():
    reference = [_fact("Rule one.", "c_one")]
    served = [{"type": "escalation", "text": "Contact People Operations.", "citations": []}]
    blocks, carried = breadth.carry_citations(reference, served)
    assert blocks == served and carried == []
