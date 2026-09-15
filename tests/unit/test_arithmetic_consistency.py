"""`agent/arithmetic.py` — the working beside a total has to come to the total (W8, C13).

The exhibit is `fresh:5f985ab3…:1`, scenario 16 of the 2026-09-15 fresh run: E1007 Dana asked
about her PTO expiry, was told the right total (8.0) and then shown a decomposition that comes to
12.0 — adding a carryover the same sentence calls expired and omitting the 1.5 pending days that
actually produce the figure.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent import arithmetic
from hrmosaic.agent.orchestrator import _ToolEnvelope

#: E1007's row as `check_pto_balance` returns it: the carryover expired on 31 March 2026, so
#: `carryover_unexpired` is 0.0 and `remaining_days` is 13.5 − 4.0 − 1.5 = 8.0.
DANA = {
    "employee_id": "E1007",
    "as_of": "2026-09-01",
    "accrued_ytd": 13.5,
    "used_ytd": 4.0,
    "pending_days": 1.5,
    "carryover_from_prior_year": 2.5,
    "carryover_expires_on": "2026-03-31",
    "carryover_unexpired": 0.0,
    "remaining_days": 8.0,
}

#: The sentence the live build shipped.
SHIPPED = "You have 8.0 days remaining (13.5 accrued minus 4.0 used, plus 2.5 carryover)."

#: What the envelope's own fields say.
REPAIRED = "You have 8.0 days remaining (13.5 accrued minus 4.0 used minus 1.5 pending)."


def envelopes(body: dict, name: str = arithmetic.BALANCE_TOOL) -> list[_ToolEnvelope]:
    return [_ToolEnvelope(name=name, result_json=json.dumps(body, ensure_ascii=False))]


def block(text: str) -> dict:
    return {"type": "record", "text": text, "citations": []}


# -- reading the envelope ---------------------------------------------------------------


def test_only_the_balance_envelope_is_read():
    assert arithmetic.balance(envelopes(DANA, name="check_policy_compliance")) is None
    assert arithmetic.balance(envelopes(DANA))["remaining_days"] == 8.0


def test_a_body_that_will_not_parse_is_not_a_reason_to_lose_the_answer():
    assert arithmetic.balance([_ToolEnvelope(name=arithmetic.BALANCE_TOOL, result_json="{oops")]) is None


def test_the_envelopes_own_decomposition_reproduces_its_own_total():
    assert arithmetic.decomposition(DANA) == "13.5 accrued minus 4.0 used minus 1.5 pending"


def test_a_zero_term_is_left_out_rather_than_written_as_minus_zero():
    clean = {**DANA, "used_ytd": 0.0, "pending_days": 0.0, "remaining_days": 13.5}
    assert arithmetic.decomposition(clean) == "13.5 accrued"


def test_carryover_joins_the_working_only_when_there_is_some():
    carrying = {**DANA, "carryover_unexpired": 2.5, "remaining_days": 10.5}
    assert arithmetic.decomposition(carrying) == "13.5 accrued minus 4.0 used minus 1.5 pending plus 2.5 carried over"


def test_an_envelope_whose_own_fields_do_not_reproduce_its_total_offers_nothing():
    """Better no working than working this step cannot vouch for."""
    inconsistent = {**DANA, "remaining_days": 99.0}
    assert arithmetic.decomposition(inconsistent) is None


# -- the parser -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("13.5 accrued minus 4.0 used, plus 2.5 carryover", [(13.5, "accrued"), (-4.0, "used"), (2.5, "carryover")]),
        ("13.5 accrued and 2.5 carryover", [(13.5, "accrued"), (2.5, "carryover")]),
        ("minus 4.0 used", [(-4.0, "used")]),
    ],
)
def test_the_terms_of_a_decomposition_are_read_with_their_signs(body, expected):
    assert arithmetic.terms(body) == expected


def test_a_term_is_matched_to_the_envelope_field_it_names():
    assert arithmetic.field_of("accrued") == "accrued_ytd"
    assert arithmetic.field_of("carried over from 2025") == "carryover_unexpired"
    assert arithmetic.field_of("days of something else") is None


# -- the step ---------------------------------------------------------------------------


def test_scenario_sixteen_the_working_is_replaced_and_the_total_is_kept():
    """8.0 is the tool's and is right; 13.5 − 4.0 + 2.5 = 12.0 is the model's and is not."""
    result = arithmetic.apply([block(SHIPPED)], envelopes(DANA))

    assert result.blocks[0]["text"] == REPAIRED
    assert result.corrected == 1 and result.changed


def test_a_decomposition_that_already_adds_up_is_left_exactly_as_written():
    result = arithmetic.apply([block(REPAIRED)], envelopes(DANA))

    assert result.blocks[0]["text"] == REPAIRED
    assert not result.changed


def test_an_addend_the_envelope_scores_at_zero_is_forbidden_even_when_it_sums():
    """The sum works only because the omission and the addition cancel. The carryover is still
    not there: `carryover_unexpired` is 0.0."""
    lucky = "You have 8.0 days remaining (13.5 accrued minus 8.0 used, plus 2.5 carryover)."
    result = arithmetic.apply([block(lucky)], envelopes(DANA))

    assert result.blocks[0]["text"] == REPAIRED


def test_a_working_with_nothing_to_replace_it_is_removed_and_the_total_stays():
    inconsistent = {**DANA, "remaining_days": 8.0, "accrued_ytd": None}
    result = arithmetic.apply([block(SHIPPED)], envelopes(inconsistent))

    assert result.blocks[0]["text"] == "You have 8.0 days remaining."


def test_a_parenthetical_that_is_not_a_decomposition_is_not_touched():
    for text in (
        "You have 8.0 days remaining (as at the snapshot).",
        "Your request is for 3 days (15–17 September).",
        "PTO accrues at 1.5 days per month (1.25 under three years).",
    ):
        assert arithmetic.apply([block(text)], envelopes(DANA)).blocks[0]["text"] == text


def test_a_turn_with_no_balance_changes_nothing():
    assert arithmetic.apply([block(SHIPPED)], []).blocks[0]["text"] == SHIPPED


def test_next_steps_are_repaired_the_way_the_blocks_are():
    """`render_answer` puts both in front of the same reader."""
    result = arithmetic.apply([block("Nothing to see here.")], envelopes(DANA), next_steps=[SHIPPED])

    assert result.next_steps == [REPAIRED]
    assert result.corrected == 1


def test_line_breaks_around_a_repair_survive_byte_for_byte():
    """The rule `dates.correct` learned at UX W6: only the span the parenthetical occupies moves."""
    text = f"First paragraph.\n\n{SHIPPED}\n\nThird paragraph."
    result = arithmetic.apply([block(text)], envelopes(DANA))

    assert result.blocks[0]["text"] == f"First paragraph.\n\n{REPAIRED}\n\nThird paragraph."


def test_the_step_is_idempotent():
    once = arithmetic.apply([block(SHIPPED)], envelopes(DANA))
    twice = arithmetic.apply(once.blocks, envelopes(DANA))

    assert twice.blocks == once.blocks
    assert not twice.changed
