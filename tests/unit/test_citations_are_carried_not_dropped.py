"""No post-synthesis step drops a citation from a surviving policy fact (W9 addendum, ruling 2).

`remote-002` (multi_doc, `answer_with_citations`, three distinct documents required) reached the
breadth repair citing three documents and was served citing two: a later step took a *sentence* out
of a block, and the block's citations went with the whole block.

**A citation goes back on its own block and nowhere else** (W10 addendum). The first version put it
on the nearest surviving `policy_fact`, matched by scaled position, which attaches one claim's
evidence to a different claim's sentence the moment a step removes a block — and a citation that
does not support the sentence it sits under is worse than a missing one, because a reader who
follows it finds a passage about something else. Blocks are matched by the `BLOCK_ID` marker the
orchestrator sets before the first step and every step's `dict(block)` copy carries; a citation
whose whole block is gone vanishes with it, and the answer's narrowness is then the breadth
shortfall's to record.
"""

from __future__ import annotations

from hrmosaic.agent import breadth


def _fact(identity: int, text: str, *citations: str) -> dict:
    return {
        "type": "policy_fact",
        "text": text,
        "citations": list(citations),
        breadth.BLOCK_ID: identity,
    }


def test_a_citation_a_step_took_off_its_own_block_goes_back_on_it():
    """The measured shape: the sentence surgery strips a block's citations but keeps the block."""
    reference = [_fact(0, "Rule one.", "c_one"), _fact(1, "Rule two.", "c_two")]
    served = [_fact(0, "Rule one.", "c_one"), _fact(1, "Rule two.")]  # a step took the citation

    blocks, carried = breadth.carry_citations(reference, served)

    assert carried == ["c_two"]
    assert blocks[1]["citations"] == ["c_two"], "back on its own block"


def test_a_citation_whose_whole_block_is_gone_vanishes_rather_than_moving():
    reference = [_fact(0, "Rule one.", "c_one"), _fact(1, "Rule two.", "c_two"), _fact(2, "Rule three.", "c_three")]
    served = [_fact(0, "Rule one.", "c_one"), _fact(2, "Rule three.", "c_three")]  # a step dropped the middle

    blocks, carried = breadth.carry_citations(reference, served)

    assert carried == []
    assert [block["citations"] for block in blocks] == [["c_one"], ["c_three"]]


def test_an_answer_that_kept_every_citation_is_returned_byte_for_byte():
    reference = [
        _fact(0, "Rule one.", "c_one"),
        {"type": "record", "text": "You have 13.5 days.", "citations": [], breadth.BLOCK_ID: 1},
    ]
    blocks, carried = breadth.carry_citations(reference, reference)
    assert (blocks, carried) == (reference, [])


def test_a_block_a_step_invented_is_never_a_target():
    """The record backstop, the approver line and the forfeit note carry no identity, so nothing
    is ever carried onto a block the model did not write."""
    reference = [_fact(0, "Rule one.", "c_one")]
    served = [{"type": "record", "text": "Your request goes to Dana Whitfield.", "citations": []}]
    blocks, carried = breadth.carry_citations(reference, served)
    assert blocks == served and carried == []
