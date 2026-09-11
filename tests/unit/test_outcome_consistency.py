"""`agent/outcome.py` — the post-synthesis outcome-consistency step (spec §7.4, P22).

The live demo-2 failure this exists for: the confirmation was consumed, `create_mock_hr_ticket`
returned `{"status": "created", "ticket_id": "MOCK-HR-000002", …}`, the synthesis prompt carried
that result verbatim — and the answer still ended *"I cannot open PTO requests on your behalf. You
must submit the request directly in MosaicOne…"* and never named the ticket.

So the outcome of a performed write is no longer left to the model. It is read out of the tool
result and stated first, deterministically, and an escalation that denies the very action the
result shows was performed is replaced by a line pointing at what was created.

This is **not** a guardrail: it emits no `guardrail` span and carries no G-number (§7.4).
"""

from __future__ import annotations

import json

from hrmosaic.agent import outcome
from hrmosaic.agent.orchestrator import _ToolEnvelope

TICKET = {
    "status": "created",
    "ticket_id": "MOCK-HR-000002",
    "queue": "hr-timeoff",
    "priority": "normal",
    "created_at": "2026-09-11T14:33:07Z",
    "employee_id": "E1042",
    "mock": True,
}
DRAFT = {
    "status": "drafted",
    "draft_id": "MOCK-EMAIL-000001",
    "to_role": "manager",
    "to_name": "Priya Raman",
    "subject": "PTO request for 15-17 September",
    "sent": False,
    "mock": True,
}
REJECTED = {
    "status": "confirmation_required",
    "code": "CONFIRMATION_REQUIRED",
    "action": "create_mock_hr_ticket",
    "human_summary": 'Open an HR ticket in hr-timeoff for E1042: "PTO 15–17 Sep".',
    "arguments_preview": {"employee_id": "E1042", "queue": "hr-timeoff"},
}

POLICY_BLOCK = {
    "type": "policy_fact",
    "text": "PTO requests must be submitted at least 5 business days in advance.",
    "citations": ["c_16186f87d12c1302"],
}
DENIAL_BLOCK = {
    "type": "escalation",
    "text": (
        "I cannot open PTO requests in MosaicOne on your behalf. You must submit the request "
        "yourself in MosaicOne so your manager can record written approval."
    ),
    "citations": [],
}


def envelopes(*results) -> list[_ToolEnvelope]:
    names = {"created": "create_mock_hr_ticket", "drafted": "draft_hr_email"}
    return [
        _ToolEnvelope(
            name=names.get(str(body.get("status")), "create_mock_hr_ticket"),
            result_json=json.dumps(body, ensure_ascii=False),
        )
        for body in results
    ]


def test_a_created_ticket_is_stated_first_with_its_id_and_queue():
    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET))

    assert result.changed
    first = result.blocks[0]
    assert first["type"] == "recommendation", "tool data, not company policy (§7.3)"
    assert first["citations"] == [], "a tool result has no chunk_id to cite"
    assert first["text"] == (
        "Done: HR ticket MOCK-HR-000002 was opened in queue hr-timeoff (priority normal) — this is "
        "a mock ticket, nothing was sent outside this app."
    )
    assert result.blocks[1:] == [POLICY_BLOCK], "the model's own blocks follow, untouched"


def test_a_drafted_email_is_stated_first_with_its_id():
    result = outcome.apply([POLICY_BLOCK], envelopes(DRAFT))

    assert result.blocks[0]["text"] == (
        "Done: HR email draft MOCK-EMAIL-000001 was prepared for Priya Raman — this is a mock "
        "draft, nothing was sent outside this app."
    )


def test_an_id_the_answer_already_states_is_not_repeated():
    stated = {
        "type": "recommendation",
        "text": "Your request is filed as MOCK-HR-000002 in the hr-timeoff queue.",
        "citations": [],
    }

    result = outcome.apply([stated], envelopes(TICKET))

    assert result.blocks == [stated], "the id is already in a block; a second statement is noise"
    assert not result.changed


def test_an_escalation_denying_the_performed_write_is_replaced_by_a_pointer_to_it():
    result = outcome.apply([POLICY_BLOCK, DENIAL_BLOCK], envelopes(TICKET))

    assert [block["type"] for block in result.blocks] == ["recommendation", "policy_fact", "recommendation"]
    replaced = result.blocks[2]
    assert "MOCK-HR-000002" in replaced["text"]
    assert "cannot" not in replaced["text"].lower()
    assert result.replaced == [1], "the model's block index, before the outcome block is inserted"


def test_an_escalation_about_something_else_survives_the_write():
    """G5's contact is not collateral: only a denial of the performed action is replaced."""
    sensitive = {
        "type": "escalation",
        "text": (
            "This raises a potential discrimination concern, which I will not handle here. "
            "Contact People Operations at people-ops@mosaicrobotics.example."
        ),
        "citations": [],
    }

    result = outcome.apply([sensitive], envelopes(TICKET))

    assert result.blocks[1] == sensitive
    assert result.replaced == []


def test_a_write_that_was_only_proposed_states_nothing():
    """The gated attempt returns `CONFIRMATION_REQUIRED` and writes nothing (§8.6)."""
    result = outcome.apply([POLICY_BLOCK, DENIAL_BLOCK], envelopes(REJECTED))

    assert result.blocks == [POLICY_BLOCK, DENIAL_BLOCK]
    assert not result.changed
    assert outcome.performed_write(envelopes(REJECTED)) is None


def test_a_turn_with_no_write_at_all_is_untouched():
    balance = _ToolEnvelope(name="check_pto_balance", result_json='{"remaining_days": 13.5}')

    result = outcome.apply([POLICY_BLOCK, DENIAL_BLOCK], [balance])

    assert result.blocks == [POLICY_BLOCK, DENIAL_BLOCK]
    assert not result.changed


def test_an_unreadable_write_envelope_is_ignored_rather_than_raising():
    broken = _ToolEnvelope(name="create_mock_hr_ticket", result_json="not json at all")

    assert outcome.performed_write([broken]) is None
    assert outcome.apply([POLICY_BLOCK], [broken]).blocks == [POLICY_BLOCK]


def test_the_last_performed_write_of_the_turn_is_the_one_reported():
    second = {**TICKET, "ticket_id": "MOCK-HR-000003", "queue": "hr-general"}

    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET, second))

    assert "MOCK-HR-000003" in result.blocks[0]["text"]


def test_the_step_has_a_name_and_it_is_not_a_guardrail_number():
    assert outcome.STEP_NAME == "outcome_consistency"
    assert not outcome.STEP_NAME.startswith("G")


def test_an_escalation_denying_a_performed_draft_points_at_the_draft():
    denial = {
        "type": "escalation",
        "text": "I cannot send email on your behalf. Write to your manager yourself.",
        "citations": [],
    }

    result = outcome.apply([denial], envelopes(DRAFT))

    assert result.blocks[1]["type"] == "recommendation"
    assert "MOCK-EMAIL-000001" in result.blocks[1]["text"]


def test_a_result_missing_its_queue_states_what_it_has_and_no_more():
    """The sentence is assembled from the result, so a thinner result makes a shorter sentence."""
    thin = {"status": "created", "ticket_id": "MOCK-HR-000009"}

    result = outcome.apply([POLICY_BLOCK], envelopes(thin))

    assert result.blocks[0]["text"] == (
        "Done: HR ticket MOCK-HR-000009 was opened — this is a mock ticket, nothing was sent outside this app."
    )


def test_a_success_status_with_no_id_is_not_a_write_to_report():
    """The sentence is the id; a body without one is nothing to state."""
    idless = _ToolEnvelope(name="create_mock_hr_ticket", result_json='{"status": "created"}')

    assert outcome.performed_write([idless]) is None


# --------------------------------------------------------------------------------------
# `next_steps` — the same contradiction, one line further down the same answer
# --------------------------------------------------------------------------------------

#: Exactly what the recorded demo-2 synthesis emits (`tests/fixtures/llm_scripts/demo_task_2.json`).
DEMO_2_STEPS = [
    "Log into MosaicOne and submit your PTO request for 15–17 September 2026.",
    "Your manager will receive the request and must approve it in writing within MosaicOne.",
    "Once approved, the three days will be deducted from your PTO balance.",
]


def test_a_next_step_telling_the_reader_to_file_the_request_is_dropped():
    """The twin of the escalation case: `render_answer` puts next steps in the same answer."""
    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET), next_steps=DEMO_2_STEPS)

    assert result.next_steps == DEMO_2_STEPS[1:], "only the directive to go and file it goes"
    assert result.dropped == [0], "the model's own next_steps index"
    assert result.changed


def test_a_next_step_that_is_not_aimed_at_the_reader_survives():
    """A statement about someone else carries the object and no imperative at the reader."""
    steps = [
        "Watch for your manager's approval in MosaicOne.",
        "Dana Whitfield approves request MOCK-HR-000123 in hr-timeoff.",
        "Your manager will receive the request and must approve it in writing.",
    ]

    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET), next_steps=steps)

    assert result.next_steps == steps
    assert result.dropped == []


def test_a_next_step_that_names_the_ticket_survives_even_in_the_imperative():
    """It is talking about the ticket that exists, not asking for a second one."""
    steps = ["Open MOCK-HR-000002 in the mock-action log if you want to see the request."]

    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET), next_steps=steps)

    assert result.next_steps == steps
    assert result.dropped == []


def test_an_imperative_about_something_else_survives_the_write():
    """An imperative verb is not enough: the object has to be the thing the tool made."""
    steps = [
        "Open the PTO & Holidays Policy and read section 4 before your manager replies.",
        "Please submit your expense report separately in the finance portal.",
    ]

    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET), next_steps=steps)

    assert result.next_steps == steps
    assert result.dropped == []


def test_politeness_in_front_of_the_verb_does_not_hide_the_directive():
    steps = [
        "Please submit the PTO request in MosaicOne yourself.",
        "You need to file a ticket for the three days.",
        "Make sure to open a request with HR.",
    ]

    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET), next_steps=steps)

    assert result.next_steps == []
    assert result.dropped == [0, 1, 2]


def test_a_next_step_telling_the_reader_to_write_the_email_is_dropped():
    steps = [
        "Send the email to your manager yourself once you have checked the dates.",
        "Your manager usually replies within two business days.",
    ]

    result = outcome.apply([POLICY_BLOCK], envelopes(DRAFT), next_steps=steps)

    assert result.next_steps == steps[1:]
    assert result.dropped == [0]


def test_next_steps_are_untouched_when_nothing_was_performed():
    """No write, no contradiction: the gated attempt leaves the model's advice alone."""
    for turn_envelopes in (envelopes(REJECTED), [_ToolEnvelope(name="check_pto_balance", result_json="{}")]):
        result = outcome.apply([POLICY_BLOCK], turn_envelopes, next_steps=DEMO_2_STEPS)

        assert result.next_steps == DEMO_2_STEPS
        assert result.dropped == []
        assert not result.changed


def test_next_steps_default_to_nothing_when_the_caller_passes_none():
    """`apply` is called for the blocks alone in the unit tests above; that stays legal."""
    assert outcome.apply([POLICY_BLOCK], envelopes(TICKET)).next_steps == []


def test_directs_needs_both_halves_for_the_tool_that_performed_the_write():
    """The matrix the two word lists encode, stated once."""
    assert outcome.directs("Submit your PTO request in MosaicOne.", "create_mock_hr_ticket")
    assert not outcome.directs("Submit your PTO request in MosaicOne.", "draft_hr_email")
    assert not outcome.directs("The request was submitted for you.", "create_mock_hr_ticket")
    assert not outcome.directs("Open the policy document.", "create_mock_hr_ticket")
    assert not outcome.directs("Submit your PTO request.", "check_pto_balance"), (
        "a read-only tool performs nothing, so no advice can contradict it"
    )
