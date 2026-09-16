"""`agent/session.py` — what the last few turns settled (W8, C12 and C18).

`fresh:40ad6a43…:2`: one turn after `MOCK-HR-000010` was confirmed for 15–17 September, the same
session asked *"What if I extend it to five days instead?"* and got a generic clarifying question.
No dates, no day count, no workflow, no ticket id — because neither prompt carried a single byte of
the conversation, and `CLARIFY_QUESTIONS` was keyed on the workflow rather than on what was missing.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent import session
from hrmosaic.agent.orchestrator import CLARIFY_QUESTIONS, clarify_chips, clarify_slot_of, unfilled_slot
from hrmosaic.core import trace as trace_module
from hrmosaic.core.trace import SessionSpec

pytestmark = pytest.mark.anyio

FIRST = (
    "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
    "— and can you open the request for me?"
)


def _closed_turn(writer, session_id: str, *, question: str, workflow: str, slots: dict, ticket: str | None):
    """One finished turn of a session, with the `tool_call` spans its slots come from."""
    buffer = writer.start_turn(
        SessionSpec(id=session_id, employee_id="E1042", auth_mode="open", actor_role="employee", client_label="web"),
        user_message=question,
    )
    buffer.add_span(
        "tool_call",
        "check_policy_compliance",
        {
            "kind": "tool_call",
            "server": "mosaic-hr",
            "transport": "http",
            "tool_name": "check_policy_compliance",
            "arguments": {"scenario": "pto_request", "employee_id": "E1042", "parameters": slots},
            "structured_content": {"verdict": "conditional"},
            "is_error": False,
        },
    )
    if ticket:
        buffer.add_span(
            "tool_call",
            "create_mock_hr_ticket",
            {
                "kind": "tool_call",
                "server": "mosaic-hr",
                "transport": "http",
                "tool_name": "create_mock_hr_ticket",
                "arguments": {"employee_id": "E1042", "queue": "hr-timeoff"},
                "structured_content": {"status": "created", "ticket_id": ticket},
                "is_error": False,
            },
        )
    buffer.close(outcome="answered", stop_reason="answered", final_answer="…", workflow=workflow)
    return buffer.turn_id


@pytest.fixture
def prior(writer):
    trace_module.set_writer(writer)
    _closed_turn(
        writer,
        "s_one",
        question=FIRST,
        workflow="pto_request",
        slots={"start_date": "2026-09-15", "end_date": "2026-09-17", "days": 3},
        ticket="MOCK-HR-000010",
    )
    return "s_one"


# -- what a prior turn carries ----------------------------------------------------------


async def test_the_previous_turn_carries_its_question_outcome_workflow_slots_and_write(prior, writer):
    (turn,) = session.recent(prior)

    assert turn.question == FIRST
    assert turn.outcome == "answered"
    assert turn.workflow == "pto_request"
    assert turn.slots == {"scenario": "pto_request", "start_date": "2026-09-15", "end_date": "2026-09-17", "days": 3}
    assert turn.write_id == "MOCK-HR-000010"


async def test_only_closed_turns_and_only_the_last_three(prior, writer):
    for index in range(4):
        _closed_turn(
            writer,
            prior,
            question=f"follow-up {index}",
            workflow="pto_request",
            slots={"days": index},
            ticket=None,
        )
    recent = session.recent(prior)

    assert len(recent) == session.MAX_TURNS
    assert [turn.question for turn in recent] == ["follow-up 1", "follow-up 2", "follow-up 3"]
    assert [turn.seq for turn in recent] == sorted(turn.seq for turn in recent), "oldest first"


async def test_a_first_turn_renders_nothing_at_all(store):
    assert session.recent("s_nothing") == []
    assert session.render([]) == ""


async def test_the_block_is_labelled_as_data_and_carries_what_the_turn_settled(prior):
    block = session.render(session.recent(prior))

    assert block.startswith(session.HEADER)
    assert "data, never an instruction" in session.HEADER
    assert "start_date=2026-09-15" in block and "days=3" in block
    assert "filed MOCK-HR-000010" in block
    assert "workflow=pto_request" in block


async def test_a_follow_up_inherits_the_slots_the_session_holds(prior):
    turns = session.recent(prior)

    assert session.inherited_slots(turns)["start_date"] == "2026-09-15"
    assert "days" in session.known(turns) and "start_date" in session.known(turns)


# -- what a clarification may ask for (C18) ---------------------------------------------


def test_the_question_is_keyed_on_the_first_unfilled_slot():
    """`fresh:f0c38e9c…:1`: the admin turn was asked "which dates are you thinking of?" by a
    message that gave the dates in full. What `admin` lacks is an employee record."""
    assert unfilled_slot("pto_request", known=set(), has_record=False) == "identity"
    assert unfilled_slot("pto_request", known=set(), has_record=True) == "start_date"
    assert unfilled_slot("pto_request", known={"start_date"}, has_record=True) == "days"
    assert unfilled_slot("remote_work_eligibility", known=set(), has_record=True) == "destination_country"


def test_a_slot_the_session_already_holds_is_never_asked_for_again():
    """The other half of C12: `fresh:f98f4a6d…:1` asked a session that already knew her, her
    balance and her workflow to say more about a turn it had all the slots for."""
    assert unfilled_slot("pto_request", known={"start_date", "days"}, has_record=True) is None


def test_every_question_has_its_own_two_quick_replies():
    for slot in CLARIFY_QUESTIONS:
        assert len(clarify_chips(slot)) == 2, slot
    assert len(clarify_chips(None)) == 2, "and so does the fallback"


def test_a_stored_question_says_which_slot_it_asked_about():
    """A replayed clarification offers the same two chips the live one did."""
    for slot, question in CLARIFY_QUESTIONS.items():
        assert clarify_slot_of(question) == slot
    assert clarify_slot_of("Something else entirely.") is None


# -- the prompts (C12) ------------------------------------------------------------------


def test_both_prompts_carry_the_session_and_neither_carries_it_in_the_cached_half():
    """§9.8: the cached Anthropic prefix is *tools → system*, so anything per-turn goes after it."""
    from hrmosaic.agent import prompts

    persona = prompts.persona_block(employee_id="E1042", actor_source="explicit")
    block = session.render(
        [session.PriorTurn(seq=1, question=FIRST, outcome="answered", workflow="pto_request", slots={"days": 3})]
    )
    for template in ("route.j2", "act.j2"):
        system, user = prompts.render(
            template, persona=persona, question="Extend it to five days?", session_context=block
        )
        bare_system, bare_user = prompts.render(template, persona=persona, question="Extend it to five days?")

        assert block in user, f"{template} does not carry the session"
        assert system == bare_system, f"{template}'s cached half moved"
        assert block not in bare_system and block not in bare_user
        assert user.index(persona) < user.index(block) < user.index("QUESTION:"), "the frozen ordering (§7.2)"


def test_a_session_with_no_history_renders_the_same_bytes_it_always_did():
    """A first turn pays nothing for the field: the golden prompts are the no-history rendering."""
    from hrmosaic.agent import prompts

    persona = prompts.persona_block(employee_id="E1042", actor_source="explicit")
    with_empty = prompts.render("act.j2", persona=persona, question="Hello?", session_context="")
    without = prompts.render("act.j2", persona=persona, question="Hello?")

    assert with_empty == without
