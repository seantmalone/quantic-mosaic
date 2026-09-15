"""`render_answer()` and `parse_next_steps()` are one format, written from two sides.

§7.3's deterministic join is what the JSON contract, the eval harness and every trace read; it is
also, since UX W2's review, the only place a **replayed** turn can get its `next_steps` back.
`turns` stores `final_answer`, `answer_blocks_json` and `citations_json` — the blocks and their
sources, but not the steps — so `GET /?session=<id>` used to replay a refusal without the redirect
that is the most useful half of it, and an answered turn without the actions under its suggestions.

These tests pin the pair as a round trip. The risk they exist for is drift on one side only: a
change to the writer's `"Next steps:\n"` section that the reader is never told about would silently
empty the steps on every reloaded transcript, exactly as their absence did before.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent.orchestrator import NEXT_STEPS_LEAD, parse_next_steps, render_answer
from hrmosaic.core.models import AnswerBlock

FACT = AnswerBlock(type="policy_fact", text="Stays over 30 days need a Tax & Legal review.", citations=["c_1a2b3c4d"])
SUGGESTION = AnswerBlock(type="recommendation", text="Raise the request in MosaicOne.", citations=[])
ESCALATION = AnswerBlock(type="escalation", text="Contact People Operations.", citations=[])

STEPS = [
    "Submit a Tax & Legal review request at least 21 days before departure",
    "Confirm device encryption with IT Security",
]


@pytest.mark.parametrize(
    "blocks",
    [
        pytest.param([FACT, SUGGESTION], id="a cited answer with a suggestion"),
        pytest.param([SUGGESTION], id="a clarification: one block, no citation"),
        pytest.param([ESCALATION], id="an escalation"),
        pytest.param([], id="steps with no blocks at all"),
    ],
)
def test_the_steps_render_and_read_back_unchanged(blocks):
    assert parse_next_steps(render_answer(blocks, STEPS)) == STEPS


def test_an_answer_that_carries_no_steps_reads_back_as_none():
    assert parse_next_steps(render_answer([FACT, SUGGESTION], [])) == []
    assert parse_next_steps("") == []


def test_prose_that_merely_mentions_next_steps_is_not_a_section():
    """The marker is a section lead at a paragraph boundary, not a phrase anywhere in the answer."""
    assert parse_next_steps("Next steps: are for you and your manager to agree.") == []
    assert parse_next_steps("I could not find anything. Next steps:\nask People Operations.") == []


def test_the_section_is_the_last_thing_in_the_rendered_answer():
    """Which is why reading it back is a `rpartition` and not a search."""
    rendered = render_answer([FACT, SUGGESTION], STEPS)
    assert rendered.endswith(f"- {STEPS[-1]}")
    assert rendered.count(NEXT_STEPS_LEAD) == 1
    # And the labelling guarantee the rubric measures is untouched by any of this.
    assert "Recommendation — not company policy: " in rendered
