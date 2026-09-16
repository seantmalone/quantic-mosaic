"""`agent/capability.py` — the answer may not deny what the turn could do (W8, C09 and C10).

Two exhibits, both from the 2026-09-15 captures:

* `eval:unsafe-001:1` — *"I cannot submit PTO requests in MosaicOne on your behalf"*, written on a
  turn where `create_mock_hr_ticket` was offered and gated. **Nine of twelve** recorded runs.
* `live:c2f99759…:1` — *"for a fully remote employee"*, written for E1042, whose own profile
  envelope on that turn says `work_arrangement: "hybrid"`.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent import capability
from hrmosaic.agent.orchestrator import _ToolEnvelope

PERMITTED = ("search_policy_documents", "check_pto_balance", "create_mock_hr_ticket")

PROFILE = _ToolEnvelope(
    name="lookup_employee_profile",
    result_json=json.dumps(
        {"employee_id": "E1042", "preferred_name": "Priya", "work_arrangement": "hybrid", "office": {"city": "Boston"}}
    ),
)


def block(text: str, kind: str = "escalation") -> dict:
    return {"type": kind, "text": text, "citations": []}


# -- C09: a denial of what a permitted tool does ----------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "I cannot submit PTO requests in MosaicOne on your behalf.",
        "I am not able to open a ticket for you.",
        "I do not have the ability to file the request for you.",
    ],
)
def test_a_first_person_denial_of_a_permitted_tool_is_one(sentence):
    assert capability.denies_a_permitted_tool(sentence, PERMITTED)


@pytest.mark.parametrize(
    "sentence",
    [
        # Policy, not capability: a rule about who may approve what.
        "Nobody can approve their own request.",
        # A denial about something no permitted tool does.
        "I cannot give you legal advice about your visa.",
        # G5's escalation, which names a contact and must survive intact.
        "I will not handle a discrimination concern here — contact People Operations.",
        # A statement about the reader, not about the assistant.
        "You cannot carry more than five days into the next plan year.",
        # Third person with a "for you" in it: a policy sentence, not this assistant (W7-review Minor).
        "A manager cannot open a ticket for you without a written request.",
        "Nobody is able to submit the request on your behalf without your written consent.",
    ],
)
def test_a_denial_that_is_not_about_a_permitted_tool_survives(sentence):
    assert not capability.denies_a_permitted_tool(sentence, PERMITTED)


def test_a_tool_the_turn_was_not_offered_is_not_a_capability_it_denies():
    """§9.2's gate and §13.9's ablation both narrow the list; the check follows it."""
    sentence = "I cannot open a ticket for you."
    assert capability.denies_a_permitted_tool(sentence, PERMITTED)
    assert not capability.denies_a_permitted_tool(sentence, ("search_policy_documents",))


def test_the_denial_is_dropped_and_what_it_said_beside_it_is_kept():
    text = (
        "I cannot submit PTO requests in MosaicOne on your behalf. "
        "Contact People Operations at people-ops@mosaicrobotics.example if you need help."
    )
    result = capability.apply([block(text)], [], permitted=PERMITTED)

    assert (
        result.blocks[0]["text"] == "Contact People Operations at people-ops@mosaicrobotics.example if you need help."
    )
    assert len(result.dropped) == 1 and result.emptied == []
    assert result.changed


def test_a_block_that_was_nothing_but_the_denial_goes_whole():
    result = capability.apply([block("I cannot open PTO requests on your behalf.")], [], permitted=PERMITTED)

    assert result.blocks == []
    assert result.emptied == [0]


# -- C10: a profile attribute the reader's own record contradicts ------------------------


def test_an_attribute_the_envelope_contradicts_is_dropped():
    sentence = "As a fully remote employee you have no onsite requirement."
    assert capability.contradicts_the_record(sentence, [PROFILE])

    result = capability.apply([block(sentence, "recommendation")], [PROFILE], permitted=PERMITTED)
    assert result.blocks == []


def test_the_attribute_the_envelope_actually_carries_is_kept():
    sentence = "As a hybrid employee you work on site at least three days each week."
    assert not capability.contradicts_the_record(sentence, [PROFILE])
    assert capability.apply([block(sentence, "recommendation")], [PROFILE], permitted=PERMITTED).blocks[0]["text"] == (
        sentence
    )


#: A live-shaped demo-1 answer for a **hybrid** employee. Every sentence names remote work, and
#: every one of them is company policy or the reader's own request — none is a claim about the
#: reader's work arrangement. Until W8's fix round, all seven were dropped (Critical 1).
DEMO_1_SHAPED = [
    (
        "Work performed outside your home country under the remote work policy requires a Tax & Legal "
        "review for stays over 30 days."
    ),
    "International remote work of more than 30 days requires approval from your director and from Tax & Legal.",
    "Germany is on the approved-destination list in the remote-and-hybrid-work policy.",
    "Your remote work request for Berlin needs 21 calendar days' notice to your manager.",
    "You may work remotely from an approved country for up to 90 days in a rolling twelve months.",
    "Remote work abroad on a company-managed device requires the always-on VPN.",
    (
        "You have completed 3 years 9 months of continuous service, exceeding the 12-month minimum for "
        "remote work abroad."
    ),
]


@pytest.mark.parametrize("sentence", DEMO_1_SHAPED)
def test_a_policy_sentence_about_remote_work_is_not_a_claim_about_the_reader(sentence):
    """W8 fix round, Critical 1. All three demo personas are `hybrid` and demo 1 is *about*
    international remote work: a check that read the word "remote" as a claim about the reader
    emptied the headline demo's answer of everything it had to say."""
    assert not capability.contradicts_the_record(sentence, [PROFILE]), sentence


def test_the_whole_demo_1_shaped_answer_survives_for_a_hybrid_employee():
    blocks = [block(sentence, "policy_fact") for sentence in DEMO_1_SHAPED]
    result = capability.apply(blocks, [PROFILE], permitted=PERMITTED)

    assert [item["text"] for item in result.blocks] == DEMO_1_SHAPED
    assert not result.changed


@pytest.mark.parametrize(
    "sentence",
    [
        "As a fully remote employee you have no onsite requirement.",
        "You are a fully remote employee, so no onsite days apply to you.",
        "Your work arrangement is fully remote.",
    ],
)
def test_a_claim_about_the_readers_own_arrangement_is_still_caught(sentence):
    """The C10 exhibit, in the three frames it takes: the reader is the subject."""
    assert capability.contradicts_the_record(sentence, [PROFILE]), sentence


def test_a_turn_that_never_read_the_profile_has_nothing_to_contradict():
    """The step corrects an answer against the record; with no record it corrects nothing."""
    sentence = "As a fully remote employee you have no onsite requirement."
    assert not capability.contradicts_the_record(sentence, [])


def test_the_step_is_idempotent():
    text = "I cannot open a ticket for you. Your manager will approve it in MosaicOne."
    once = capability.apply([block(text)], [PROFILE], permitted=PERMITTED)
    twice = capability.apply(once.blocks, [PROFILE], permitted=PERMITTED)

    assert twice.blocks == once.blocks
    assert not twice.changed
