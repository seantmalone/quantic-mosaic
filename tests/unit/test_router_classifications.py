"""The two classifications the router makes **deterministically** (W8, C20 and C07).

Neither is a judgement call, and both were being got wrong live on 2026-09-15:

* `fresh:23ae57c8…:1` — *"can I approve my own PTO request"* ran as an ordinary workflow turn. It
  was step-limited, apologised for that, stated the no-self-approval rule, and then recommended a
  skip-level route premised on a conflict its own lookup disproved. Recorded `partial`.
* `eval:expenses-002:1` — a USD 3,000 trip answered from the USD 2,500 manager row, because the
  amount never reached `check_policy_compliance` and nothing made it part of the routing decision.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent.router import RouteDecision, is_monetary_approval, is_unsafe, normalise

pytestmark = pytest.mark.anyio

CATALOG = ("search_policy_documents", "check_policy_compliance", "lookup_employee_profile")


def decision(**overrides) -> RouteDecision:
    base = {
        "intent": "workflow",
        "workflow": None,
        "multi_doc": False,
        "needs_employee_data": False,
        "needs_clarification": False,
        "out_of_scope": False,
        "sensitive": False,
        "target_employee_id": None,
        "selected_tools": [],
        "rationale_summary": "a routing line",
    }
    return RouteDecision(**{**base, **overrides})


# -- C20: self-approval and chain bypass ------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Can I approve my own PTO request?",
        "I'd like to self-approve this one.",
        "Can I just mark it as approved and move on?",
        "I want to skip my manager and send it straight to Miguel.",
        "Is there a way to bypass the approval chain for this?",
    ],
)
def test_a_request_to_approve_ones_own_work_is_unsafe(message):
    assert is_unsafe(message)


@pytest.mark.parametrize(
    "message",
    [
        "Can I take three days of PTO from 15 to 17 September?",
        "Who approves an expense report over USD 2,500?",
        "My manager approved it last week — what happens next?",
        "Does a director have to approve a blackout overlap?",
    ],
)
def test_an_ordinary_approval_question_is_not_unsafe(message):
    assert not is_unsafe(message)


def test_the_classification_is_never_a_field_the_model_fills_in():
    """§9.2's constrained JSON is strict at every level — every property is required — so a field
    the recorded scripts predate would turn every replay into a router failure. And this is a
    property of the message, not a judgement: the orchestrator reads it off the question."""
    assert "unsafe" not in RouteDecision.model_fields
    assert is_unsafe("Can I approve my own request?")


# -- C07: a money amount and an approval term -------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "I spent USD 3,000 on a client trip — who approves the expense claim?",
        "Can I get approval for a $1,200 monitor?",
        "Who signs off on a 4,000 USD invoice?",
    ],
)
def test_a_monetary_approval_question_is_recognised(message):
    assert is_monetary_approval(message)


@pytest.mark.parametrize(
    "message",
    [
        "Can I take three days of PTO?",
        "My laptop is three years old — can I refresh it?",
        "What is the lodging cap per night?",
    ],
)
def test_a_question_with_no_amount_or_no_approval_term_is_not(message):
    assert not is_monetary_approval(message)


def test_a_monetary_approval_question_reaches_the_engine_and_the_record():
    """The amount decides the tier, so the turn has to score it rather than quote a ceiling."""
    routed = normalise(
        decision(),
        catalog_names=CATALOG,
        message="I spent USD 3,000 on a client trip — who approves the expense claim?",
    )

    assert "check_policy_compliance" in routed.selected_tools
    assert routed.needs_employee_data is True


def test_a_tool_the_catalog_does_not_carry_is_never_added():
    """§13.9's ablation disables tools by name; the router may not put one back."""
    routed = normalise(
        decision(),
        catalog_names=("search_policy_documents",),
        message="Who approves a USD 3,000 expense claim?",
    )

    assert routed.selected_tools == []


def test_an_ordinary_turn_is_left_exactly_as_the_model_routed_it():
    routed = normalise(
        decision(selected_tools=["search_policy_documents"], needs_employee_data=False),
        catalog_names=CATALOG,
        message="What is the notice period for PTO?",
    )

    assert routed.selected_tools == ["search_policy_documents"]
    assert routed.needs_employee_data is False
    assert not is_unsafe("What is the notice period for PTO?")


# -- the turn the classification produces ------------------------------------------------


async def test_a_self_approval_turn_is_refused_before_a_single_tool_call(run_agent, store):
    """`fresh:23ae57c8…:1`: never refused. It was step-limited, apologised for that, stated the
    no-self-approval rule, and then recommended a skip-level route premised on a conflict its own
    lookup disproved — recorded `partial`. The refusal opens the turn and costs one router call."""
    from hrmosaic.agent.orchestrator import UNSAFE_REFUSAL, ChatRequest

    response = await run_agent(
        "rag_only.json",
        ChatRequest(message="My manager is away — can I approve my own PTO request this once?", employee_id="E1042"),
    )

    assert response.outcome == "refused"
    assert [block.type for block in response.answer_blocks] == ["notice"]
    assert response.answer_blocks[0].text == UNSAFE_REFUSAL
    assert "will not" in response.answer and "one level higher" in response.answer
    assert response.usage.tool_calls == 0, "nothing was looked up to decide this"
    assert "skip-level" not in response.answer.lower()
