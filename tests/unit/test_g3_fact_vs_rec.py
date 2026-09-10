"""G3 `fact_vs_recommendation` (spec §7.4 row G3, §7.3).

The distinction is structural first: `AnswerBlock` rejects a `policy_fact` with no citations, so a
model cannot emit one inside a valid `AnswerSchema`. G3 is the post-check behind that, and it exists
because the structural guard fires at the wrong moment — a `ValidationError` loses the whole answer
when the honest repair is to relabel one block.

So the loop runs G2 and G3 over **raw** blocks and validates afterwards, which is what these tests
pin: an uncited claim becomes a `recommendation` the UI badges *"Recommendation — not company
policy"*, and everything else is left exactly as it was.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hrmosaic.agent.guardrails import g3
from hrmosaic.core.models import AnswerBlock
from hrmosaic.core.trace import SessionSpec

CITED = {"type": "policy_fact", "text": "Notice is five business days.", "citations": ["c_abc"]}
UNCITED = {"type": "policy_fact", "text": "You will probably be fine.", "citations": []}
ADVICE = {"type": "recommendation", "text": "Ask your manager early.", "citations": []}


def test_an_uncited_policy_fact_becomes_a_recommendation():
    outcome = g3.apply([UNCITED])
    assert outcome.blocks[0]["type"] == "recommendation"
    assert outcome.blocks[0]["text"] == UNCITED["text"], "only the label moves; the claim is unchanged"
    assert outcome.relabelled == [0]


def test_a_cited_policy_fact_is_untouched():
    outcome = g3.apply([CITED])
    assert outcome.blocks == [CITED]
    assert not outcome.repaired


def test_the_other_two_block_types_are_untouched():
    outcome = g3.apply([ADVICE, {"type": "escalation", "text": "People Ops.", "citations": []}])
    assert [block["type"] for block in outcome.blocks] == ["recommendation", "escalation"]
    assert not outcome.repaired


def test_only_the_uncited_block_moves():
    outcome = g3.apply([CITED, UNCITED, ADVICE])
    assert [block["type"] for block in outcome.blocks] == ["policy_fact", "recommendation", "recommendation"]
    assert outcome.relabelled == [1]


def test_the_input_blocks_are_not_mutated():
    blocks = [dict(UNCITED)]
    g3.apply(blocks)
    assert blocks[0]["type"] == "policy_fact", "the rule is pure; the loop keeps the model's own reply"


def test_the_relabelled_block_is_what_makes_the_answer_valid():
    """Without G3 the repaired answer would not validate at all (§7.3's validator)."""
    with pytest.raises(ValidationError):
        AnswerBlock.model_validate(UNCITED)
    assert AnswerBlock.model_validate(g3.apply([UNCITED]).blocks[0]).type == "recommendation"


def test_the_span_records_which_blocks_moved(writer, spans):
    turn = writer.start_turn(SessionSpec(client_label="api"), user_message="pto notice")
    g3.check([CITED, UNCITED], turn=turn)
    turn.close(outcome="answered", stop_reason="answered")

    payload = next(payload for kind, _, payload in spans(turn.turn_id) if kind == "guardrail")
    assert (payload["rule_id"], payload["rule_name"], payload["verdict"]) == (
        "G3",
        "fact_vs_recommendation",
        "repair",
    )
    assert payload["details"]["relabelled_indexes"] == [1]


def test_a_clean_answer_still_leaves_a_span(writer, spans):
    turn = writer.start_turn(SessionSpec(client_label="api"), user_message="pto notice")
    g3.check([CITED], turn=turn)
    turn.close(outcome="answered", stop_reason="answered")

    payload = next(payload for kind, _, payload in spans(turn.turn_id) if kind == "guardrail")
    assert payload["verdict"] == "allow", "an absent span cannot say 'nothing matched' (§7.4)"
