"""The deterministic date check of UX W6 (npo2-02), beside outcome/breadth.

The defect it exists for is verbatim from the re-audit's `chat-answer` capture: the answer told the
reader to *"File the work-from-another-country request in MosaicOne by 13 September 2026 (21 days
before 3 November)"*. 3 November 2026 minus 21 days is 13 **October**; the advice was a month early
and the sentence contradicted its own arithmetic. A model computing a deadline in prose is not
something a guardrail can check, but a parenthetical that states the arithmetic is — so where the
answer shows its working, the working is redone.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent import dates


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The recorded defect, corrected at source.
        (
            "File the request in MosaicOne by 13 September 2026 (21 days before 3 November)",
            "File the request in MosaicOne by 13 October 2026 (21 days before 3 November)",
        ),
        # Already right — the same sentence one month later is left exactly as it was.
        (
            "File the request in MosaicOne by 13 October 2026 (21 days before 3 November)",
            "File the request in MosaicOne by 13 October 2026 (21 days before 3 November)",
        ),
        # `calendar days` is the same arithmetic under another name.
        (
            "Apply by 1 January 2026 (21 calendar days before 3 November 2026)",
            "Apply by 13 October 2026 (21 calendar days before 3 November 2026)",
        ),
        # Business days skip the weekend: 3 Nov 2026 is a Tuesday, so five working days before it
        # is Tuesday 27 October and not Thursday 29 October.
        (
            "Confirm with IT Security by 1 October 2026 (5 business days before 3 November 2026)",
            "Confirm with IT Security by 27 October 2026 (5 business days before 3 November 2026)",
        ),
        (
            "Confirm with IT Security by 27 October 2026 (5 business days before 3 November 2026)",
            "Confirm with IT Security by 27 October 2026 (5 business days before 3 November 2026)",
        ),
        # The anchor's year is used when the stated date carries none.
        (
            "Apply by 1 January (21 days before 3 November 2026)",
            "Apply by 13 October 2026 (21 days before 3 November 2026)",
        ),
    ],
)
def test_a_stated_deadline_is_recomputed_from_the_parenthetical_beside_it(text, expected):
    assert dates.correct(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Nothing to check against: "departure" is not a date, so the sentence is left alone rather
        # than guessed at.
        "Confirm with IT Security by 27 October 2026 (5 business days before departure)",
        # Neither date carries a year, so there is no arithmetic to redo.
        "Apply by 1 January (21 days before 3 November)",
        # No parenthetical at all — the overwhelming majority of sentences.
        "Raise your request in MosaicOne at least 21 calendar days before departure.",
        # A parenthetical that is not this shape.
        "Germany is an approved destination (see the addendum).",
    ],
)
def test_a_sentence_the_step_cannot_check_is_returned_unchanged(text):
    assert dates.correct(text) == text


def test_a_parenthetical_whose_stated_date_cannot_be_corrected_is_removed():
    """The other half of the rule: when the working is wrong and there is nothing to correct to,
    the claim goes rather than standing as an unchecked assertion."""
    text = "Apply as soon as you can (21 days before 3 November 2026) and keep the receipts."
    assert dates.correct(text) == "Apply as soon as you can and keep the receipts."


def test_the_step_rewrites_block_text_and_next_steps_together():
    """`render_answer()` puts both in front of the same reader, so both go through the step."""
    outcome = dates.apply(
        [
            {"type": "recommendation", "text": "Apply by 13 September 2026 (21 days before 3 November)."},
            {"type": "policy_fact", "text": "Germany is an approved destination.", "citations": ["c_1"]},
        ],
        next_steps=["File it by 13 September 2026 (21 days before 3 November)", "Watch for approval"],
    )

    assert outcome.blocks[0]["text"] == "Apply by 13 October 2026 (21 days before 3 November)."
    assert outcome.blocks[1]["text"] == "Germany is an approved destination."
    assert outcome.next_steps == ["File it by 13 October 2026 (21 days before 3 November)", "Watch for approval"]
    assert outcome.corrected == 2
    assert outcome.changed


def test_an_answer_with_no_arithmetic_in_it_is_untouched():
    outcome = dates.apply([{"type": "policy_fact", "text": "You have 13.5 days left.", "citations": ["c_1"]}])
    assert not outcome.changed
    assert outcome.corrected == 0
