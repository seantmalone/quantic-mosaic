"""Approvers come from one template (W10, ruling 4).

Seven of the sixteen recorded demo paths got this wrong, in three ways, and all three have the same
cause: the answer's account of *who approves* was whatever prose the model reached for.

* **A name grafted into quoted policy** (01, 04, 05, 06, 09, 13) — *"PTO requests … require written
  approval from your direct manager Dana"*, served under a citation to a sentence
  `corpus/pto-and-holidays.md` does not contain. Quoted policy text is the one thing in an answer a
  reader can check; a step that edits it takes that away.
* **A routing dropped** (03) — E1007 Dana Whitfield is *Director, Engineering*, the matrix routes
  her own request one level up to Miguel, and the answer never said so.
* **A name lost altogether** (15) — a regression: the answer said "your manager" and the envelope
  had carried a name all along.

One `record` line, built from `approvers[]` and from nothing else.
"""

from __future__ import annotations

import json

from hrmosaic.agent import approvers as approver_resolution


class _Envelope:
    def __init__(self, name: str, body: dict) -> None:
        self.name = name
        self.result_json = json.dumps(body)


MANAGER = _Envelope(
    "check_policy_compliance",
    {"approvers": [{"role": "Direct manager", "name": "Dana Whitfield", "employee_id": "E1007"}]},
)

ROUTED = _Envelope(
    "check_policy_compliance",
    {
        "approvers": [
            {
                "role": "Director",
                "name": "Miguel Santos",
                "self_approval_routed": True,
                "reason": (
                    "Nobody approves their own request, and nobody approves a request from a "
                    "person who approves theirs. Where the matrix would produce that outcome, the "
                    "request routes one level higher automatically."
                ),
            }
        ]
    },
)

CITED_POLICY = {
    "type": "policy_fact",
    "text": "Every PTO request requires written approval from the employee's direct manager in MosaicOne.",
    "citations": ["c_abc"],
}


def test_a_cited_policy_sentence_is_never_rewritten():
    result = approver_resolution.apply([CITED_POLICY], [MANAGER])
    assert result.blocks[0]["text"] == CITED_POLICY["text"]
    assert result.named == [], "the policy says what it says"


def test_an_uncited_block_still_gets_the_name():
    block = {"type": "recommendation", "text": "Ask your manager to approve it.", "citations": []}
    result = approver_resolution.apply([block], [MANAGER])
    assert "Dana Whitfield" in result.blocks[0]["text"]


def test_the_record_line_names_the_approver_when_no_block_does():
    result = approver_resolution.apply([CITED_POLICY], [MANAGER])
    assert result.stated
    line = result.blocks[-1]
    assert line["type"] == approver_resolution.RECORD
    assert line["text"] == "Your request goes to Dana Whitfield, your direct manager."
    assert line["citations"] == []


def test_a_self_approval_routing_prints_the_matrixs_own_sentence_verbatim():
    result = approver_resolution.apply([CITED_POLICY], [ROUTED])
    line = result.blocks[-1]["text"]
    assert line.startswith("Your request goes to Miguel Santos.")
    assert json.loads(ROUTED.result_json)["approvers"][0]["reason"] in line
    assert "your director" not in line, "Miguel is not her director; he is who her request goes to"


def test_no_second_line_when_the_answer_already_names_the_person():
    block = {"type": "record", "text": "Dana Whitfield approves this in MosaicOne.", "citations": []}
    result = approver_resolution.apply([block], [MANAGER])
    assert not result.stated
    assert len(result.blocks) == 1


def test_nothing_is_stated_when_the_envelope_resolved_nobody():
    team = _Envelope("check_policy_compliance", {"approvers": [{"role": "Tax & Legal"}]})
    result = approver_resolution.apply([CITED_POLICY], [team])
    assert not result.stated and len(result.blocks) == 1


def test_two_roles_held_by_one_person_are_named_once():
    """Demo 1: E1042's direct manager and her director are both Dana, and the first version of the
    line said *"Dana, your direct manager and Dana, your director"* — two approvals where the matrix
    routes one."""
    both = _Envelope(
        "check_policy_compliance",
        {
            "approvers": [
                {"role": "Direct manager", "name": "Dana", "employee_id": "E1007"},
                {"role": "Director", "name": "Dana", "employee_id": "E1007"},
            ]
        },
    )
    result = approver_resolution.apply([CITED_POLICY], [both])
    assert result.blocks[-1]["text"] == "Your request goes to Dana, your direct manager and director."
