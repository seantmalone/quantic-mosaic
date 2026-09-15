"""`agent/approvers.py` — the answer names the person, not the role (W8, C06).

Exhibits, both from the 2026-09-15 fresh run:

* `fresh:7523dd69…:1` — E1007 **Dana Whitfield, Director, Engineering** told her trip "requires
  approval from your director";
* `fresh:2fb97298…:1` — "your manager" written on a turn whose own profile envelope carried the
  manager's name.
"""

from __future__ import annotations

import json

from hrmosaic.agent import approvers
from hrmosaic.agent.orchestrator import _ToolEnvelope

#: E1042 Priya's chain: her manager IS the director of her department, so both roles are Dana.
PRIYA_CHAIN = {
    "approvers": [
        {"role": "Direct manager", "employee_id": "E1007", "name": "Dana"},
        {"role": "Director", "employee_id": "E1007", "name": "Dana"},
    ]
}

#: E1007 Dana's chain: she holds the director role herself, so the matrix routes one level up.
DANA_CHAIN = {
    "approvers": [
        {"role": "Direct manager", "employee_id": "E1002", "name": "Miguel"},
        {
            "role": "Director",
            "employee_id": "E1002",
            "name": "Miguel",
            "self_approval_routed": True,
            "reason": "Nobody approves their own request…",
        },
        {"role": "Tax & Legal"},
    ]
}


def envelope(body: dict, name: str = "check_policy_compliance") -> _ToolEnvelope:
    return _ToolEnvelope(name=name, result_json=json.dumps(body, ensure_ascii=False))


def block(text: str) -> dict:
    return {"type": "recommendation", "text": text, "citations": []}


# -- reading the envelope ---------------------------------------------------------------


def test_only_the_two_tools_that_resolve_a_chain_are_read():
    assert approvers.approvers([envelope(PRIYA_CHAIN, name="check_pto_balance")]) == []
    assert [entry.role for entry in approvers.approvers([envelope(PRIYA_CHAIN)])] == ["direct manager", "director"]


def test_a_role_with_no_person_behind_it_is_not_an_approver_this_step_can_name():
    assert [entry.name for entry in approvers.approvers([envelope(DANA_CHAIN)])] == ["Miguel", "Miguel"]


def test_a_body_that_will_not_parse_is_not_a_reason_to_lose_the_answer():
    assert approvers.approvers([_ToolEnvelope(name="check_policy_compliance", result_json="{oops")]) == []


# -- the rewrite ------------------------------------------------------------------------


def test_a_bare_role_is_given_the_name_the_envelope_resolved():
    result = approvers.apply(
        [block("Every PTO request needs written approval from your manager.")], [envelope(PRIYA_CHAIN)]
    )

    assert result.blocks[0]["text"] == "Every PTO request needs written approval from your manager Dana."
    assert result.named == [(0, "manager")]


def test_a_director_is_never_sent_to_herself():
    """The exhibit, verbatim: E1007 is the Director of Engineering."""
    result = approvers.apply([block("Your trip requires approval from your director.")], [envelope(DANA_CHAIN)])

    assert result.blocks[0]["text"] == (
        "Your trip requires approval from Miguel (one level up, since nobody approves their own request)."
    )
    assert result.named == [(0, "director")]


def test_naming_the_reader_as_their_own_approver_is_rewritten_to_the_person_above_them():
    profile = envelope({"preferred_name": "Dana"}, name="lookup_employee_profile")
    result = approvers.apply(
        [block("This needs approval from Dana before you travel.")], [envelope(DANA_CHAIN), profile]
    )

    assert result.blocks[0]["text"].startswith("This needs approval from Miguel (one level up")


def test_a_name_already_written_is_not_written_twice():
    result = approvers.apply([block("Ask your manager Dana to record the approval.")], [envelope(PRIYA_CHAIN)])

    assert result.blocks[0]["text"] == "Ask your manager Dana to record the approval."
    assert not result.changed


def test_a_turn_that_resolved_nothing_changes_nothing():
    result = approvers.apply([block("Ask your manager to record the approval.")], [])

    assert result.blocks[0]["text"] == "Ask your manager to record the approval."
    assert not result.changed


def test_next_steps_are_repaired_the_way_the_blocks_are():
    """`render_answer` puts both in front of the same reader."""
    result = approvers.apply(
        [block("Nothing to see here.")],
        [envelope(PRIYA_CHAIN)],
        next_steps=["Ask your director to countersign the request."],
    )

    assert result.next_steps == ["Ask your director Dana to countersign the request."]
    assert result.named_steps == [(0, "director")]


def test_the_step_is_idempotent():
    once = approvers.apply([block("Approval from your manager is required.")], [envelope(PRIYA_CHAIN)])
    twice = approvers.apply(once.blocks, [envelope(PRIYA_CHAIN)])

    assert twice.blocks == once.blocks
    assert not twice.changed
