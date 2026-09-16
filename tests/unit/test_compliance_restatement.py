"""`agent/compliance.py` — the answer may not contradict the engine (W8, C03).

The exhibits are the two demo-2 scenarios of the 2026-09-15 fresh run
(`demo-path-review-2026-09-15.md` §5, rows 4 and 6), with the engine's own requirement rows as
`check_policy_compliance` returned them on those turns.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent import compliance
from hrmosaic.agent.orchestrator import _ToolEnvelope

#: `fresh:40ad6a43…:1` — Priya, demo 2, confirmed. Verdict `conditional`; every data-backed row
#: met; the one open row is the manual manager-approval confirmation.
SCENARIO_4_VERDICT = {
    "scenario": "pto_request",
    "verdict": "conditional",
    "as_of": "2026-09-01",
    "submitted_on": "2026-09-15",
    "requirements": [
        {
            "id": "pto.request.notice",
            "text": "PTO requests must be submitted at least 5 business days in advance.",
            "met": True,
            "status": "met",
            "reason": "computed.notice_business_days is 8; the policy value is 5 (gte).",
        },
        {
            "id": "pto.request.balance",
            "text": "The requested days must be covered by the balance accrued at the snapshot.",
            "met": True,
            "status": "met",
            "reason": "pto_balance.remaining_days is 13.5; the policy value is 3 (gte).",
        },
        {
            "id": "pto.request.manager_approval",
            "text": "Every PTO request needs written manager approval in MosaicOne.",
            "met": False,
            "status": "not_stated",
            "reason": "Not verifiable from the synthetic record; confirm before proceeding.",
        },
    ],
}

#: `fresh:a771d87b…:1` — Marcus, demo 2. The balance row is genuinely unmet and the answer says so.
SCENARIO_6_VERDICT = {
    "scenario": "pto_request",
    "verdict": "non_compliant",
    "requirements": [
        {
            "id": "pto.request.balance",
            "text": "The requested days must be covered by the balance accrued at the snapshot.",
            "met": False,
            "status": "unmet",
            "reason": "pto_balance.remaining_days is 0.25; the policy value is 3 (gte).",
        }
    ],
}

#: The sentence the live build shipped beside `met: true` on the notice row.
SCENARIO_4_SENTENCE = (
    "Your request for 15–17 September does not meet the 5 business day notice requirement "
    "(only 8 calendar days from today, 15 September)."
)

#: The sentence the live build shipped beside `status: unmet` on the balance row. It agrees with
#: the engine, and must survive untouched.
SCENARIO_6_SENTENCE = (
    "You have 0.25 days remaining, and your request is for 3 days. You do not have sufficient "
    "accrual to cover this request."
)


def envelope(body: dict, name: str = compliance.COMPLIANCE_TOOL) -> _ToolEnvelope:
    return _ToolEnvelope(name=name, result_json=json.dumps(body, ensure_ascii=False))


def block(text: str, kind: str = "recommendation") -> dict:
    return {"type": kind, "text": text, "citations": []}


# -- reading the envelope ---------------------------------------------------------------


def test_only_the_compliance_envelope_is_read():
    assert compliance.rows([envelope(SCENARIO_4_VERDICT, name="check_pto_balance")]) == []
    assert [row.id for row in compliance.rows([envelope(SCENARIO_4_VERDICT)])] == [
        "pto.request.notice",
        "pto.request.balance",
        "pto.request.manager_approval",
    ]


def test_a_body_that_will_not_parse_is_not_a_reason_to_lose_the_answer():
    assert compliance.rows([_ToolEnvelope(name=compliance.COMPLIANCE_TOOL, result_json="{oops")]) == []


def test_a_row_written_before_the_status_field_still_reads():
    """`met` alone is what the older recorded envelopes carry, and it still means what it meant."""
    legacy = {"requirements": [{"id": "x", "text": "A rule about notice.", "met": True, "reason": ""}]}
    assert compliance.rows([envelope(legacy)])[0].status == "met"


def test_a_requirement_knows_what_it_is_about():
    notice, balance, approval = compliance.rows([envelope(SCENARIO_4_VERDICT)])
    assert notice.subjects == ("notice",)
    assert balance.subjects == ("balance",)
    assert "approval" in approval.subjects


# -- polarity ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Your request does not meet the notice requirement.", "denies"),
        ("Your request meets the notice requirement.", "asserts"),
        ("Your balance is sufficient for the request.", "asserts"),
        ("You have insufficient accrual for this request.", "denies"),
        ("Your request is for three days in September.", None),
        ("It meets the notice rule but does not meet the balance rule.", None),
    ],
)
def test_polarity_reads_the_sentence_or_declines_to(sentence, expected):
    assert compliance.polarity(sentence) is expected


# -- the restatement --------------------------------------------------------------------


def test_scenario_four_the_answer_stops_contradicting_a_met_requirement():
    """The headline defect: the engine scored the notice requirement met with eight business days,
    and the answer denied it using the same eight relabelled as calendar days."""
    result = compliance.apply([block(SCENARIO_4_SENTENCE)], [envelope(SCENARIO_4_VERDICT)])

    assert result.blocks[0]["text"] == ("Your notice business days is 8, and the policy asks for at least 5.")
    assert result.restated == [(0, "pto.request.notice")]
    assert result.changed


def test_scenario_six_a_sentence_that_agrees_with_the_engine_is_left_alone():
    """The step repairs a contradiction. Marcus really does lack the accrual, and the answer says
    so; nothing here is for this step to touch."""
    result = compliance.apply([block(SCENARIO_6_SENTENCE, "escalation")], [envelope(SCENARIO_6_VERDICT)])

    assert result.blocks[0]["text"] == SCENARIO_6_SENTENCE
    assert result.restated == [] and not result.changed


def test_asserting_a_requirement_the_engine_found_unmet_is_replaced():
    result = compliance.apply(
        [block("Your balance covers the three days you asked for.")], [envelope(SCENARIO_6_VERDICT)]
    )

    assert result.blocks[0]["text"] == "Your balance, in days is 0.25, and the policy asks for at least 3."
    assert result.restated == [(0, "pto.request.balance")]


def test_a_conclusion_on_a_requirement_nobody_evaluated_says_so():
    """W8, C05: `not_stated` has no verdict to state, in either direction."""
    for sentence in (
        "Written manager approval is already recorded, so this requirement is met.",
        "Your request does not have the manager approval it needs.",
    ):
        result = compliance.apply([block(sentence)], [envelope(SCENARIO_4_VERDICT)])
        assert result.blocks[0]["text"] == "I could not check the approval requirement."


def test_a_sentence_carrying_two_verdicts_is_left_alone_and_recorded():
    """A repair that is not certain is worse than the prose it replaces."""
    mixed = "Your request meets the notice requirement but does not meet the balance requirement."
    result = compliance.apply([block(mixed)], [envelope(SCENARIO_4_VERDICT)])

    assert result.blocks[0]["text"] == mixed
    assert result.restated == []
    assert sorted(requirement for _index, requirement in result.unverified) == [
        "pto.request.balance",
        "pto.request.notice",
    ]


def test_a_policy_sentence_about_the_rule_itself_is_not_a_verdict():
    """`policy_fact` blocks quote the rule. The rule is not a claim about this request."""
    fact = block("PTO requests must be submitted at least 5 business days in advance.", "policy_fact")
    result = compliance.apply([fact], [envelope(SCENARIO_4_VERDICT)])

    assert result.blocks[0]["text"] == fact["text"]
    assert not result.changed


def test_next_steps_are_repaired_the_way_the_blocks_are():
    """`render_answer` puts both in front of the same reader."""
    result = compliance.apply(
        [block("Your balance covers the request.")],
        [envelope(SCENARIO_4_VERDICT)],
        next_steps=["Ask Dana to waive the notice requirement, which your request does not meet."],
    )

    assert result.next_steps == ["Your notice business days is 8, and the policy asks for at least 5."]
    assert result.restated_steps == [(0, "pto.request.notice")]


def test_a_turn_with_no_verdict_changes_nothing():
    result = compliance.apply([block(SCENARIO_4_SENTENCE)], [])
    assert result.blocks[0]["text"] == SCENARIO_4_SENTENCE
    assert not result.changed


def test_the_step_is_idempotent():
    once = compliance.apply([block(SCENARIO_4_SENTENCE)], [envelope(SCENARIO_4_VERDICT)])
    twice = compliance.apply(once.blocks, [envelope(SCENARIO_4_VERDICT)])

    assert twice.blocks == once.blocks
    assert not twice.changed


# -- W8 C07: a threshold the request has already outgrown --------------------------------
#
# `eval:expenses-002:1` — a USD 3,000 trip whose one policy fact is the USD 2,500 manager limit,
# closed by a step routing the report to the manager. The limit is true; it is not the rule that
# applies to this claim, and a reader who acts on it sends the report to the wrong person.

EXPENSES_002 = {
    "scenario": "expense_claim",
    "verdict": "conditional",
    "requirements": [
        {
            "id": "expense.manager_limit",
            "text": "A direct manager may approve expense reports up to USD 2,500.",
            "met": False,
            "status": "unmet",
            "reason": "parameters.amount_usd is 3000; the policy value is 2500 (lte).",
        },
        {
            "id": "expense.vp_limit",
            "text": "A vice president may approve expense reports up to USD 25,000.",
            "met": True,
            "status": "met",
            "reason": "parameters.amount_usd is 3000; the policy value is 25000 (lte).",
        },
    ],
    "approvals_required": [
        {"role": "Direct manager", "reason": "Expense reports up to USD 2,500 are approved by the direct manager."},
        {
            "role": "Director",
            "reason": "Reports above USD 2,500 need director approval and a Finance business partner review.",
        },
    ],
}


def test_the_amount_the_question_carries_is_read_off_the_engines_own_reasons():
    assert compliance.stated_amount(compliance.rows([envelope(EXPENSES_002)])) == 3000.0


def test_the_covering_tier_is_the_highest_approval_the_request_triggered():
    assert compliance.covering_rule([envelope(EXPENSES_002)]) == (
        "Reports above USD 2,500 need director approval and a Finance business partner review."
    )


def test_a_ceiling_below_the_claim_is_replaced_by_the_tier_that_applies():
    quoted = block("A direct manager may approve expense reports up to USD 2,500.", "policy_fact")
    quoted["citations"] = ["c_1"]
    result = compliance.apply([quoted], [envelope(EXPENSES_002)])

    assert result.blocks[0]["text"] == (
        "Reports above USD 2,500 need director approval and a Finance business partner review."
    )
    assert result.thresholds == 1 and result.changed


def test_a_ceiling_the_claim_is_within_is_left_alone():
    quoted = block("A vice president may approve expense reports up to USD 25,000.", "policy_fact")
    result = compliance.apply([quoted], [envelope(EXPENSES_002)])

    assert result.blocks[0]["text"] == quoted["text"]
    assert result.thresholds == 0


def test_a_next_step_routing_to_the_outgrown_tier_is_rewritten_too():
    result = compliance.apply(
        [block("Nothing to see here.")],
        [envelope(EXPENSES_002)],
        next_steps=["Send the report to your manager, who may approve up to USD 2,500."],
    )

    assert result.next_steps == [
        "Reports above USD 2,500 need director approval and a Finance business partner review."
    ]


def test_a_turn_with_no_amount_in_it_never_touches_a_threshold():
    quoted = block("A direct manager may approve expense reports up to USD 2,500.", "policy_fact")
    result = compliance.apply([quoted], [envelope(SCENARIO_4_VERDICT)])

    assert result.blocks[0]["text"] == quoted["text"]
    assert result.thresholds == 0


# -- W8 fix round: a not_stated row is opposable only by a conclusion about THIS request ----------


@pytest.mark.parametrize(
    "sentence",
    [
        "Verbal approval is insufficient.",
        "Verbal agreement, a message in chat and an email thread are all insufficient on their own.",
        "A request without written approval does not meet the policy.",
    ],
)
def test_a_policy_sentence_about_the_approval_rule_is_not_a_verdict_on_the_request(sentence):
    """W7-review I4. `pto.request.manager_approval` is `manual` and therefore `not_stated` on
    every PTO turn; a true, cited policy sentence about approval was being replaced by "I could
    not check the approval requirement."."""
    result = compliance.apply([block(sentence, "policy_fact")], [envelope(SCENARIO_4_VERDICT)])

    assert result.blocks[0]["text"] == sentence
    assert result.restated == []


def test_a_conclusion_about_this_request_on_a_not_stated_row_is_still_replaced():
    for sentence in (
        "Your request already meets the manager approval requirement.",
        "This requirement is met because the approval is on file.",
    ):
        result = compliance.apply([block(sentence)], [envelope(SCENARIO_4_VERDICT)])
        assert result.blocks[0]["text"] == "I could not check the approval requirement.", sentence
