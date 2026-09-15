"""`agent/snapshot.py` — the post-synthesis snapshot-consistency step (spec §7.4, P29).

The two live sentences this exists for, both from the 2026-09-15 turns on `ebd665a`
(`docs/evidence/demo-task-1-live-2026-09-15-session.json` and `…-2-…`):

* *"You have completed 45 months of continuous service as of 1 September 2026, which exceeds the
  12-month minimum…"* — the snapshot date restated above the page's own footer, and a tenure the
  reader has to divide by twelve, when `lookup_employee_profile` returned *"3 years 9 months"*.
* *"Your PTO balance as of 1 September 2026 is 13.5 days remaining, …"* — the same date, again,
  over the same footer.

`synthesize.j2` rules 6 and 6b ask the model for both; this step is what makes them true. It is
**not** a guardrail: it emits no `guardrail` span and carries no G-number (§7.4).
"""

from __future__ import annotations

import json

from hrmosaic.agent import snapshot
from hrmosaic.agent.orchestrator import _ToolEnvelope

#: `lookup_employee_profile` for E1042 on the live turn, trimmed to the fields this step reads.
PROFILE = {
    "employee_id": "E1042",
    "as_of": "2026-09-01",
    "tenure": "3 years 9 months",
    "tenure_months_at_as_of": 45,
}
#: `check_pto_balance` from the same turn.
BALANCE = {"employee_id": "E1042", "as_of": "2026-09-01", "remaining_days": 13.5}

#: The two sentences, verbatim from the stored `answer_blocks` of the two live turns.
LIVE_TENURE_FACT = (
    "You have completed 45 months of continuous service as of 1 September 2026, which exceeds the "
    "12-month minimum required to work outside your home country."
)
LIVE_BALANCE_RECOMMENDATION = (
    "Your PTO balance as of 1 September 2026 is 13.5 days remaining, which covers your three-day "
    "request. You have 8 business days of notice, which exceeds the 5-day requirement."
)


def envelopes(*results, tool: str = snapshot.PROFILE_TOOL) -> list[_ToolEnvelope]:
    return [_ToolEnvelope(name=tool, result_json=json.dumps(body, ensure_ascii=False)) for body in results]


def block(text: str, kind: str = "policy_fact") -> dict[str, object]:
    return {"type": kind, "text": text, "citations": []}


# --------------------------------------------------------------------------------------
# The two live sentences
# --------------------------------------------------------------------------------------


def test_the_live_tenure_fact_loses_the_snapshot_date_and_states_the_tenure_in_words():
    result = snapshot.apply([block(LIVE_TENURE_FACT)], envelopes(PROFILE))

    assert result.blocks[0]["text"] == (
        "You have completed 3 years 9 months of continuous service, which exceeds the "
        "12-month minimum required to work outside your home country."
    )
    assert result.corrected == 1 and result.changed


def test_the_live_balance_recommendation_loses_the_snapshot_date_and_keeps_everything_else():
    result = snapshot.apply(
        [block(LIVE_BALANCE_RECOMMENDATION, "recommendation")],
        envelopes(BALANCE, tool="check_pto_balance"),
    )

    assert result.blocks[0]["text"] == (
        "Your PTO balance is 13.5 days remaining, which covers your three-day request. "
        "You have 8 business days of notice, which exceeds the 5-day requirement."
    )
    assert result.blocks[0]["type"] == "recommendation", "the step rewrites text and nothing else"


# --------------------------------------------------------------------------------------
# The date, in every shape it has been written in
# --------------------------------------------------------------------------------------


def test_every_variant_of_the_snapshot_date_is_removed_with_the_punctuation_that_introduced_it():
    cases = {
        "Your balance (as of 2026-09-01) is 13.5 days.": "Your balance is 13.5 days.",
        "Your balance as at 1 September 2026 is 13.5 days.": "Your balance is 13.5 days.",
        "Your balance as of September 1, 2026 is 13.5 days.": "Your balance is 13.5 days.",
        "Your balance as of September 1 2026 is 13.5 days.": "Your balance is 13.5 days.",
        "Your balance as of 1 Sept 2026 is 13.5 days.": "Your balance is 13.5 days.",
        "Your balance as of 1 Sep 2026 is 13.5 days.": "Your balance is 13.5 days.",
        "Your balance as of Sept 1, 2026 is 13.5 days.": "Your balance is 13.5 days.",
        "Your balance as of Sep 1, 2026 is 13.5 days.": "Your balance is 13.5 days.",
        "Your balance as of 01 September 2026 is 13.5 days.": "Your balance is 13.5 days.",
        "You have 13.5 days, as of 1 September 2026.": "You have 13.5 days.",
        "**PTO Balance** (as of 2026-09-01):": "**PTO Balance**:",
        "As of 1 September 2026, your balance is 13.5 days.": "Your balance is 13.5 days.",
        "Your balance, as of 1 September 2026, is 13.5 days.": "Your balance is 13.5 days.",
        "You have 13.5 days remaining, as of 1 September 2026, which covers the request.": (
            "You have 13.5 days remaining, which covers the request."
        ),
    }

    for written, expected in cases.items():
        assert snapshot.correct(written, dates=["2026-09-01"]) == expected, written
        assert "  " not in snapshot.correct(written, dates=["2026-09-01"]), written


def test_a_date_that_is_not_the_snapshot_survives_untouched():
    """A deadline is the reader's whole reason for reading the sentence (UX W6, npo2-02)."""
    deadline = "File the request by 13 October 2026, which is 21 days before departure."

    assert snapshot.correct(deadline, dates=["2026-09-01"]) == deadline
    assert snapshot.apply([block(deadline)], envelopes(PROFILE)).blocks[0]["text"] == deadline


def test_an_as_of_with_no_date_after_it_is_left_alone():
    """*"as of today"* is the model's prose, not a restatement of an envelope's `as_of`."""
    prose = "Your balance as of today is 13.5 days, and as of the last snapshot it was the same."

    assert snapshot.correct(prose, dates=["2026-09-01"]) == prose


def test_an_envelope_without_an_as_of_contributes_nothing():
    search = [_ToolEnvelope(name="search_policy_documents", result_json='{"results": []}')]
    broken = [_ToolEnvelope(name="check_pto_balance", result_json="not json at all")]

    assert snapshot.snapshot_dates(search) == []
    assert snapshot.snapshot_dates(broken) == []
    text = "Your balance as of 1 September 2026 is 13.5 days."
    assert snapshot.apply([block(text)], search + broken).blocks[0]["text"] == text


# --------------------------------------------------------------------------------------
# The tenure
# --------------------------------------------------------------------------------------


def test_a_policy_threshold_in_months_is_never_rewritten():
    """*"at least 12 months"* is the rule's own wording, and 12 is under the floor as well."""
    twelve = {**PROFILE, "tenure": "1 year", "tenure_months_at_as_of": 12}
    rule = "Working abroad requires at least 12 months of continuous service."

    assert snapshot.apply([block(rule)], envelopes(twelve)).blocks[0]["text"] == rule
    assert not snapshot.apply([block(rule)], envelopes(twelve)).changed


def test_the_employees_own_tenure_is_not_rewritten_where_the_sentence_states_a_threshold():
    """Same number, same turn: *"requires 45 months"* is a claim about the policy, not the record."""
    threshold = "The exception requires 45 months of continuous service, which you meet."

    assert snapshot.apply([block(threshold)], envelopes(PROFILE)).blocks[0]["text"] == threshold
    for lead in ("at least", "a minimum of", "you need", "it needs", "is required after"):
        sentence = f"The policy asks for {lead} 45 months of service."
        assert snapshot.correct(sentence, pairs=[(45, "3 years 9 months")]) == sentence, lead


def test_a_tenure_under_the_floor_is_already_how_a_person_says_it():
    twelve = {**PROFILE, "tenure": "1 year", "tenure_months_at_as_of": 12}
    text = "You have completed 12 months of continuous service."

    assert snapshot.apply([block(text)], envelopes(twelve)).blocks[0]["text"] == text


def test_a_tenure_that_is_not_a_number_is_ignored_rather_than_raising():
    for broken in ({**PROFILE, "tenure_months_at_as_of": "45"}, {"as_of": "2026-09-01"}):
        assert snapshot.tenures(envelopes(broken)) == []


def test_the_words_are_computed_when_an_envelope_reports_the_count_alone():
    """W8, C22: the count is the record; the words are how a person says it, from one place."""
    assert snapshot.tenures(envelopes({**PROFILE, "tenure": ""})) == [(45, "3 years 9 months")]


def test_any_envelope_that_reports_a_tenure_reports_it():
    """W8, C22: *"45 months of continuous service"* shipped whenever the model happened not to
    call the profile tool — the same persona, the same build, a different unit."""
    assert snapshot.tenures(envelopes(PROFILE)) == [(45, "3 years 9 months")]
    # The compliance engine reports the same count inside `computed`, and the rewrite follows it.
    verdict = {"scenario": "pto_request", "computed": {"tenure_months_at_as_of": 45}}
    assert snapshot.tenures(envelopes(verdict, tool="check_policy_compliance")) == [(45, "3 years 9 months")]
    text = "You have 45 months of continuous service."
    repaired = snapshot.apply([block(text)], envelopes(verdict, tool="check_policy_compliance"))
    assert repaired.blocks[0]["text"] == "You have 3 years 9 months of continuous service."


# --------------------------------------------------------------------------------------
# The step
# --------------------------------------------------------------------------------------


def test_next_steps_are_repaired_the_way_the_blocks_are():
    """`render_answer` puts both in front of the same reader — the rule the outcome step follows."""
    result = snapshot.apply(
        [block("Germany is an approved destination.")],
        envelopes(PROFILE),
        next_steps=["Confirm your 45 months of service as of 1 September 2026 with HR."],
    )

    assert result.next_steps == ["Confirm your 3 years 9 months of service with HR."]
    assert result.corrected == 1, "the block was already right; only the step changed"


def test_applying_the_step_twice_changes_nothing_the_second_time():
    once = snapshot.apply([block(LIVE_TENURE_FACT)], envelopes(PROFILE), next_steps=[LIVE_BALANCE_RECOMMENDATION])
    twice = snapshot.apply(once.blocks, envelopes(PROFILE), next_steps=once.next_steps)

    assert twice.blocks == once.blocks and twice.next_steps == once.next_steps
    assert not twice.changed


def test_a_turn_with_no_snapshot_and_no_tenure_is_returned_as_it_came():
    blocks = [block(LIVE_TENURE_FACT)]

    result = snapshot.apply(blocks, [], next_steps=["Watch for your manager's approval."])

    assert result.blocks == blocks and not result.changed
    assert result.next_steps == ["Watch for your manager's approval."]


def test_the_step_never_flattens_the_paragraphs_of_a_block():
    """`dates.correct` once ran `\\s{2,}` over whole strings and turned every line break into a
    space (UX W6). What `turns.final_answer` stores is what the reader was shown."""
    text = "Your balance as of 2026-09-01:\n\n- 13.5 days remaining\n- 3 days requested"

    assert snapshot.correct(text, dates=["2026-09-01"]) == (
        "Your balance:\n\n- 13.5 days remaining\n- 3 days requested"
    )


def test_the_step_has_a_name_and_it_is_not_a_guardrail_number():
    assert snapshot.STEP_NAME == "snapshot_consistency"
    assert not snapshot.STEP_NAME.startswith("G")
