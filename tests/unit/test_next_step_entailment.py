"""`agent/entailment.py` — a next step may not name what the answer does not (W8, C08).

`next_steps` is written in parallel with the blocks and was read by no rule: G2 and G3 both run
over blocks only. The exhibit is `eval:expenses-002:1` — a USD 3,000 trip whose one policy fact is
the USD 2,500 manager limit, closed by a step routing the report to the manager.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent import entailment
from hrmosaic.agent.orchestrator import _ToolEnvelope

BLOCKS = [
    {
        "type": "policy_fact",
        "text": "Expense reports up to USD 2,500 are approved by the direct manager.",
        "citations": ["c_1"],
    },
    {
        "type": "record",
        "text": "Your claim is USD 3,000, so it is above the direct-manager limit.",
        "citations": [],
    },
]

ENVELOPES = [
    _ToolEnvelope(
        name="check_policy_compliance",
        result_json=json.dumps({"scenario": "expense_claim", "computed": {"amount_usd": 3000}}),
    )
]


# -- what a step commits to -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Submit the claim by 15 September 2026.", ["15 September 2026"]),
        ("Allow 15 business days for the review.", ["15 business days"]),
        ("Ask a director to approve the USD 3,000 report.", ["USD 3,000"]),
        ("Ask Miguel to countersign it.", ["Miguel"]),
        ("Record the working location in MosaicOne.", []),
        ("Contact People Operations if this is urgent.", []),
    ],
)
def test_a_step_commits_to_its_dates_durations_amounts_and_names(text, expected):
    assert entailment.claims(text) == expected


def test_a_claim_is_entailed_by_a_block_or_by_an_envelope():
    ground = entailment.grounds(BLOCKS, ENVELOPES)

    assert entailment.entailed("USD 3,000", ground)
    assert entailment.entailed("USD 2,500", ground)
    assert not entailment.entailed("USD 25,000", ground)


# -- the step ---------------------------------------------------------------------------


def test_a_step_naming_a_threshold_the_answer_excludes_is_dropped():
    result = entailment.apply(
        BLOCKS,
        ENVELOPES,
        next_steps=[
            "Submit the expense report in MosaicOne Expenses with the business purpose written out.",
            "Ask a director to approve the USD 25,000 report.",
        ],
    )

    assert result.next_steps == [
        "Submit the expense report in MosaicOne Expenses with the business purpose written out."
    ]
    assert result.dropped == [(1, "Ask a director to approve the USD 25,000 report.", "USD 25,000")]
    assert result.changed


def test_a_step_naming_a_date_no_block_or_envelope_carries_is_dropped():
    result = entailment.apply(BLOCKS, ENVELOPES, next_steps=["File the claim by 30 November 2026."])

    assert result.next_steps == []
    assert result.dropped[0][2] == "30 November 2026"


def test_a_step_naming_a_person_the_turn_never_established_is_dropped():
    result = entailment.apply(BLOCKS, ENVELOPES, next_steps=["Ask Miguel to countersign the report."])

    assert result.next_steps == []
    assert result.dropped[0][2] == "Miguel"


def test_a_person_the_envelope_names_is_entailed():
    profile = _ToolEnvelope(
        name="lookup_employee_profile",
        result_json=json.dumps({"manager": {"preferred_name": "Dana"}}),
    )
    result = entailment.apply(BLOCKS, [*ENVELOPES, profile], next_steps=["Ask Dana to countersign the report."])

    assert result.next_steps == ["Ask Dana to countersign the report."]
    assert not result.changed


def test_a_step_with_no_specifics_in_it_is_never_dropped():
    """This step removes ungrounded specifics; it does not edit advice."""
    steps = [
        "Record the working location in MosaicOne so the payroll position stays accurate.",
        "Contact People Operations if this is urgent.",
    ]
    assert entailment.apply(BLOCKS, ENVELOPES, next_steps=steps).next_steps == steps


def test_a_turn_with_no_steps_is_a_no_op():
    assert entailment.apply(BLOCKS, ENVELOPES).next_steps == []


def test_the_step_is_idempotent():
    steps = ["Ask a director to approve the USD 25,000 report.", "Contact People Operations if this is urgent."]
    once = entailment.apply(BLOCKS, ENVELOPES, next_steps=steps)
    twice = entailment.apply(BLOCKS, ENVELOPES, next_steps=once.next_steps)

    assert twice.next_steps == once.next_steps
    assert not twice.changed


def test_a_duration_is_entailed_by_a_number_token_and_not_by_a_digit_substring():
    """W7-review Minor: "3 days" reduced to "3", which is inside every turn's ground somewhere."""
    ground = entailment.grounds(
        [], [_ToolEnvelope(name="check_pto_balance", result_json='{"remaining_days": 13.5, "days": 3}')]
    )

    assert entailment.entailed("3 days", ground), "the envelope carries days: 3"
    assert not entailment.entailed("6 days", ground), "6 is not a token, whatever digits the ground holds"
    assert not entailment.entailed("35 days", ground), "and 35 is not entailed by 13.5"
    assert entailment.entailed(
        "USD 2,500", entailment.grounds([], [_ToolEnvelope(name="x", result_json='{"limit": 2500}')])
    )
