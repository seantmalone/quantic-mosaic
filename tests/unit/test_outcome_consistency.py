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
