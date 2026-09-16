"""A balance is the engine's, decomposition and all (W10, ruling 8).

Scenario 16, E1007 Dana Whitfield, *"How many PTO days do I have and when do they expire?"*:

    engine   remaining_days 8.0 · accrued 13.5 · used 4.0 · pending 1.5
             carryover_from_prior_year 2.5, expired 2026-03-31, carryover_unexpired 0.0
             carryover_cap_days 5.0 · projected_forfeit_on_31_dec 3.0
    answer   "You have 8.0 remaining PTO days. This comprises 5.5 days from your current year
              accrual (13.5 accrued minus 4.0 used minus 1.5 pending) and 2.5 days carried over
              from the prior year."

The sentence refutes itself — its own parenthetical comes to 8.0, not 5.5 — presents carryover that
expired in March as live, and never tells her that 3.0 of her 8.0 days are forfeited on 31 December.
W8's step repaired a *parenthetical*; it could not repair the sentence built around one.
"""

from __future__ import annotations

import json

from hrmosaic.agent import arithmetic as arithmetic_consistency


class _Envelope:
    def __init__(self, name: str, body: dict) -> None:
        self.name = name
        self.result_json = json.dumps(body)


BALANCE = {
    "employee_id": "E1007",
    "as_of": "2026-09-01",
    "accrued_ytd": 13.5,
    "used_ytd": 4.0,
    "pending_days": 1.5,
    "carryover_from_prior_year": 2.5,
    "carryover_expires_on": "2026-03-31",
    "carryover_unexpired": 0.0,
    "remaining_days": 8.0,
    "carryover_cap_days": 5.0,
    "projected_forfeit_on_31_dec": 3.0,
}

SCENARIO_16 = (
    "You have 8.0 remaining PTO days. This comprises 5.5 days from your current year accrual "
    "(13.5 accrued minus 4.0 used minus 1.5 pending) and 2.5 days carried over from the prior year."
)


def envelope() -> _Envelope:
    return _Envelope("check_pto_balance", BALANCE)


def test_a_sentence_stating_a_total_the_balance_does_not_carry_is_replaced():
    result = arithmetic_consistency.apply([{"type": "record", "text": SCENARIO_16, "citations": []}], [envelope()])
    text = result.blocks[0]["text"]
    assert "5.5" not in text and "2.5 days carried over" not in text
    assert text == "You have 8.0 days of PTO remaining: 13.5 accrued minus 4.0 used minus 1.5 pending."
    # **The total is said once** (W10 fix round, Minor). The model's own *"You have 8.0 remaining
    # PTO days."* states the same fact in a different wording, so `dedupe_sentences` cannot see it;
    # the engine's statement carries the same total and its working, and the model's goes.
    assert text.count("8.0") == 1


def test_an_expiry_date_no_field_states_is_replaced_by_the_one_that_is():
    block = {
        "type": "record",
        "text": "Your carried-over days expire on 31 March 2027.",
        "citations": [],
    }
    result = arithmetic_consistency.apply([block], [envelope()])
    text = result.blocks[0]["text"]
    assert "2027" not in text
    assert text.startswith("Your 2.5 days of carryover expired on 31 March 2026")


def test_a_quoted_policy_sentence_about_expiry_is_left_alone():
    """*"Carried-over PTO expires on 31 March of the following plan year"* is the corpus speaking,
    not a claim about this reader — and a **cited** `policy_fact` is never rewritten at all, in this
    step or in the approver step: its citation is how a reader checks it."""
    for quoted in (
        {
            "type": "policy_fact",
            "text": "Carried-over PTO expires on 31 March of the following plan year.",
            "citations": ["c_carryover"],
        },
        {
            "type": "policy_fact",
            "text": "You may carry over a maximum of 5.0 days into the following plan year.",
            "citations": ["c_carryover"],
        },
    ):
        result = arithmetic_consistency.apply([quoted], [envelope()])
        assert result.blocks[0]["text"] == quoted["text"]


def test_the_forfeit_the_fields_imply_is_stated():
    result = arithmetic_consistency.apply([{"type": "record", "text": SCENARIO_16, "citations": []}], [envelope()])
    assert result.blocks[-1]["text"] == (
        "3.0 of those 8.0 days are above the 5.0-day carryover limit and are forfeited on 31 December if unused."
    )
    assert result.blocks[-1]["type"] == arithmetic_consistency.RECORD


def test_the_forfeit_is_stated_only_where_the_answer_is_about_expiry():
    """The reader of demo 2 asked to book three days in September; a block about next New Year's
    Eve is a fact nobody asked for, and it would be on every PTO answer for ever."""
    booking = {"type": "record", "text": "You have 13.5 days remaining, which covers a 3-day request.", "citations": []}
    result = arithmetic_consistency.apply([booking], [envelope()])
    assert [block["text"] for block in result.blocks] == [booking["text"]]


def test_no_forfeit_line_when_the_balance_is_under_the_cap():
    under = {**BALANCE, "remaining_days": 0.25, "projected_forfeit_on_31_dec": 0.0}
    asked = "You have 0.25 days, and none of it expires this year."
    result = arithmetic_consistency.apply(
        [{"type": "record", "text": asked, "citations": []}],
        [_Envelope("check_pto_balance", under)],
    )
    assert [block["text"] for block in result.blocks] == [asked]


def test_an_answer_the_engine_agrees_with_is_returned_unchanged():
    agreed = {
        "type": "record",
        "text": "You have 8.0 days of PTO remaining (13.5 accrued minus 4.0 used minus 1.5 pending).",
        "citations": [],
    }
    result = arithmetic_consistency.apply([agreed], [envelope()])
    assert result.blocks[0]["text"] == agreed["text"]


def test_the_engines_own_forfeiture_sentence_is_not_read_as_invented():
    """W10 fix round. `_DATE` matched a bare day-month, so *"forfeited on 31 December"* — the
    sentence `forfeit_note` itself writes — was treated as a date no field states and deleted with
    nothing in its place, because `expired_note` returns `None` for unexpired carryover."""
    live = {**BALANCE, "carryover_from_prior_year": 0.0, "carryover_expires_on": None, "carryover_unexpired": 0.0}
    block = {
        "type": "record",
        "text": "Your 3.0 days above the 5.0-day cap are forfeited on 31 December if unused.",
        "citations": [],
    }
    result = arithmetic_consistency.apply([block], [_Envelope("check_pto_balance", live)])
    assert result.blocks[0]["text"] == block["text"]


def test_a_specific_year_the_balance_does_not_carry_is_still_invented():
    block = {"type": "record", "text": "Your carryover expires on 31 March 2027.", "citations": []}
    result = arithmetic_consistency.apply([block], [envelope()])
    assert "2027" not in result.blocks[0]["text"]
