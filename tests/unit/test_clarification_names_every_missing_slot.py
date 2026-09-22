"""A clarification names **every** detail it is missing, not the first one (G5, gap 4).

The published run scored `clarification_accuracy` **1 of 3** over the three `ambiguous` items, and
the two failures are both in this file, driven by the routing the run recorded:

* `amb-002` — *"Am I allowed to work from there for a while?"* — was asked *"where would you be
  working from?"* and never for how long or from when. `_clarification_text` returned the **first**
  unfilled slot and stopped, so the second and third were never mentioned.
* `amb-003` — *"Can you check the balance for me?"* — is routed `employee_data` with no workflow, so
  there was no slot order to walk at all and the turn served `CLARIFY_FALLBACK`, *"could you tell me
  a little more about what you are after?"*, which names nothing. That is the exact defect
  `CLARIFY_QUESTIONS` was keyed on the slot to remove.

The deployed run `r_1790062696_baseline` then showed that amb-002 is routed with `workflow: null` as
well, so the slot order the first fix walks was never reached and only the rationale words were: the
question named the destination and stopped again (G5, gap 4b). The workflow is now inferred from the
topic words of the rationale and the question when the router names none.

The missing information each item expects is read from `evaluation/dataset.yaml`'s own
`clarification_expects`, because that string is what the judge is handed as MISSING INFORMATION
(`evaluation/judges.py::CLARIFICATION_USER`). The assertions below are the deterministic half of that
verdict: the words the judge would have to read to answer `entailed: true`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hrmosaic.agent.client import McpClient
from hrmosaic.agent.orchestrator import (
    CLARIFY_ALSO,
    CLARIFY_FALLBACK,
    CLARIFY_QUESTIONS,
    CLARIFY_SLOT_ORDER,
    CLARIFY_TOPIC_WORDS,
    ChatRequest,
    Orchestrator,
    clarification_question,
    clarify_slot_of,
    clarify_topic_workflow,
    unfilled_slots,
)
from hrmosaic.core.llm.stub import StubAdapter

pytestmark = pytest.mark.anyio

DATASET = Path(__file__).resolve().parents[2] / "evaluation" / "dataset.yaml"


def item(item_id: str) -> dict:
    """One dataset item, so the question asked here is the question the run scored."""
    items = yaml.safe_load(DATASET.read_text(encoding="utf-8"))["items"]
    found = next((row for row in items if row["id"] == item_id), None)
    assert found is not None, f"{item_id} is no longer in the dataset"
    assert found["clarification_expects"], f"{item_id} carries no clarification_expects for the judge to read"
    return found


async def served(run_agent, script: str, item_id: str) -> str:
    """The text the reader — and the judge — is given for that dataset item."""
    row = item(item_id)
    response = await run_agent(script, ChatRequest(message=row["question"], employee_id=row["persona"]))
    assert response.outcome == "clarify", response.outcome
    return response.answer


async def test_amb_002_names_the_destination_and_the_dates(run_agent):
    """MISSING INFORMATION: *"the destination country and the start and end dates"*."""
    answer = await served(run_agent, "clarify_remote_missing_details.json", "amb-002")

    assert "where would you be working from" in answer, answer
    assert "how long you would be there" in answer, answer
    assert "from when" in answer, answer
    assert CLARIFY_FALLBACK not in answer
    assert answer.count("?") == 1, "every slot is named, and still only one question is asked"


async def test_amb_002_names_both_slots_when_the_router_names_no_workflow(run_agent):
    """The deployed run's own routing for amb-002: `policy_qa`, `workflow: null` (G5, gap 4b).

    `CLARIFY_SLOT_ORDER` is keyed on the workflow and `CLARIFY_INTENT_ORDER` has no `policy_qa`
    entry, so this turn had no slot order at all and fell through to the rationale words — which name
    the destination and nothing else. The topic words of the rationale ("Remote work eligibility…")
    and of the question ("work from there") both point at `remote_work_eligibility`, so the whole
    order is walked and the answer names what MISSING INFORMATION says it must: *"the destination
    country and the start and end dates"*.
    """
    answer = await served(run_agent, "clarify_remote_no_workflow.json", "amb-002")

    assert "where would you be working from" in answer, answer
    assert "how long you would be there" in answer, answer
    assert "from when" in answer, answer
    assert CLARIFY_FALLBACK not in answer
    assert answer.count("?") == 1, "every slot is named, and still only one question is asked"


async def test_an_expense_rationale_that_names_only_the_amount_still_names_the_amount(run_agent):
    """The inference must not lose what the rationale-word path already got right (G5, gap 4b).

    An expense question with no workflow and a rationale naming only the amount: the inferred
    `expense_claim` order is `identity, amount_usd`, and this persona has a record, so the one slot
    left is the amount — the same slot the rationale words found. Either path has to ask for it.
    """
    response = await run_agent(
        "clarify_expense_no_workflow.json",
        ChatRequest(message="Can I get reimbursed for this expense?", employee_id="E1042"),
    )

    assert response.outcome == "clarify", response.outcome
    assert CLARIFY_QUESTIONS["amount_usd"] in response.answer, response.answer
    assert CLARIFY_FALLBACK not in response.answer
    assert "whose record" not in response.answer, "the reader's own id is never asked for (W10, ruling 9)"


async def test_a_time_off_question_with_no_workflow_names_the_dates_and_the_day_count(run_agent):
    """A rationale that names no slot at all used to serve the fallback (G5, gap 4b).

    *"A time off request cannot be scored without more detail"* matches nothing in
    `RATIONALE_SLOT_WORDS`, so before the inference this turn asked *"could you tell me a little more
    about what you are after?"* — the exact defect gap 4 exists to remove. The topic is `pto_request`,
    whose order asks for the dates and then names the day count.
    """
    response = await run_agent(
        "clarify_pto_no_workflow.json",
        ChatRequest(message="Am I allowed to take some time off later this year?", employee_id="E1042"),
    )

    assert response.outcome == "clarify", response.outcome
    assert "which dates are you thinking of" in response.answer, response.answer
    assert CLARIFY_ALSO["days"] in response.answer, response.answer
    assert CLARIFY_FALLBACK not in response.answer
    assert response.answer.count("?") == 1


SETTLED = "Can I take three days of PTO from Tuesday 22 September to Thursday 24 September 2026?"
MENTIONS_AN_EXPENSE = "Would the hotel for those days count as an expense?"
MORE_TIME_OFF = "Could I take more time off in December as well?"


@pytest.fixture
async def clarifications_after_a_settled_session(writer, mounted_mcp_url):
    """One session: a PTO turn that settles the slots, then the two clarifications after it.

    Turn 1 is `followup_extend.json`'s first turn, so `start_date` and `days` are what the session
    carries — the only way to reach a clarification whose workflow **is** named and whose slot order
    is nonetheless empty, which is the branch fix round 1 is about.
    """
    from tests.conftest import LLM_SCRIPTS

    orchestrator = Orchestrator(
        client=McpClient(transport="http", url=mounted_mcp_url),
        model=StubAdapter(script_path=LLM_SCRIPTS / "clarify_after_the_session_settled_the_slots.json"),
    )
    try:
        first = await orchestrator.run_turn(ChatRequest(message=SETTLED, employee_id="E1042"))
        assert first.outcome == "answered", first.outcome
        named = await orchestrator.run_turn(
            ChatRequest(message=MENTIONS_AN_EXPENSE, session_id=first.session_id, employee_id="E1042")
        )
        unnamed = await orchestrator.run_turn(
            ChatRequest(message=MORE_TIME_OFF, session_id=first.session_id, employee_id="E1042")
        )
    finally:
        await orchestrator.aclose()
    return named, unnamed


async def test_a_named_workflow_is_never_re_keyed_by_a_word_in_the_message(clarifications_after_a_settled_session):
    """The inference fires only when the router named no workflow (G5, gap 4b, fix round 1).

    The gate it was added behind — *"no slot order came back"* — is also true of a turn whose workflow
    the router **did** name and whose every slot the session has settled. On that turn the topic words
    would read the reader's own message and walk a different workflow's order: a `pto_request`
    follow-up that says "expense" would be asked *"how much is the claim for?"*, a question about a
    claim nobody made. A named workflow is the router's decision and is not second-guessed here.
    """
    named, _unnamed = clarifications_after_a_settled_session

    assert named.outcome == "clarify", named.outcome
    assert CLARIFY_QUESTIONS["amount_usd"] not in named.answer, named.answer
    assert "how much" not in named.answer, named.answer
    assert CLARIFY_FALLBACK in named.answer, named.answer


async def test_the_rationale_still_asks_for_a_slot_outside_the_inferred_order(
    clarifications_after_a_settled_session,
):
    """The rationale words are the fallback on an empty result, not only on no match (fix round 1).

    This turn's topic is `pto_request` — whose two slots the session settled on turn 1 — and its
    rationale names the destination country, which is in no PTO order at all. Were the inference an
    `else`, the turn would serve the fallback that names nothing while the router had already said
    what was missing.
    """
    _named, unnamed = clarifications_after_a_settled_session

    assert unnamed.outcome == "clarify", unnamed.outcome
    assert CLARIFY_QUESTIONS["destination_country"] in unnamed.answer, unnamed.answer
    assert CLARIFY_FALLBACK not in unnamed.answer, unnamed.answer


async def test_amb_003_names_which_balance_and_whose_record(run_agent):
    """MISSING INFORMATION: *"which balance is meant and the employee id it belongs to"*.

    The reader's own id is never *asked* for — the app knows who is asking (W10, ruling 9) — so the
    question names the record it would be read against and offers the other branch.
    """
    answer = await served(run_agent, "clarify_which_balance.json", "amb-003")

    assert "which balance do you mean" in answer, answer
    assert "your own record" in answer, answer
    assert CLARIFY_FALLBACK not in answer, "the fallback names nothing, which is what scored 0"


async def test_amb_001_still_asks_one_question_and_names_both_its_slots(run_agent):
    """The item that already passed must not regress: both PTO slots, one question."""
    answer = await served(run_agent, "fault_ambiguous.json", "amb-001")

    assert "which dates are you thinking of" in answer, answer
    assert "how many days that would be" in answer, answer
    assert answer.count("?") == 1


async def test_amb_001_asks_about_time_off_even_when_the_rationale_says_remote_work(run_agent):
    """The published run's own routing for amb-001, which the covering fixture never exercised (G5b, gap 2).

    `r_1790074972_baseline` routed *"Can I take some time off?"* `policy_qa` with `workflow: null` —
    the inference path — and its rationale mentioned remote work in passing. The topic words used to
    be matched against the rationale and the message **joined**, so "remote work" decided ahead of
    "time off": amb-001 was served amb-002's question verbatim, asking for a destination country the
    item never needed, and the judge passed it for naming *some* missing detail. MISSING INFORMATION
    for this item is *"the requested dates and the number of days"*, so those are the words the
    question has to carry, and `fault_ambiguous.json`'s rationale ("No dates were given…") cannot
    catch the flip because it names no other topic.
    """
    answer = await served(run_agent, "clarify_pto_rationale_names_remote_work.json", "amb-001")

    assert "which dates are you thinking of" in answer, answer
    assert "how many days that would be" in answer, answer
    assert "where would you be working from" not in answer, "amb-002's question, on amb-001's turn"
    assert "how long you would be there" not in answer, answer
    assert CLARIFY_FALLBACK not in answer
    assert answer.count("?") == 1


def test_every_unfilled_slot_is_named_and_the_first_one_asks_the_question():
    """Three empty slots, one question, and the other two named after it."""
    slots = unfilled_slots("pto_request", known=set(), has_record=False)
    assert slots == ("identity", "start_date", "days")

    question = clarification_question(slots)
    assert question.startswith(CLARIFY_QUESTIONS["identity"])
    assert CLARIFY_ALSO["start_date"] in question
    assert CLARIFY_ALSO["days"] in question
    assert question.count("?") == 1


def test_a_slot_the_session_already_settled_is_not_named_again():
    """W8, C12's half of this: a follow-up is never asked for a detail the session carries."""
    slots = unfilled_slots("pto_request", known={"start_date"}, has_record=True)
    assert slots == ("days",)
    assert clarification_question(slots) == CLARIFY_QUESTIONS["days"]


def test_a_turn_with_no_workflow_and_no_intent_order_still_falls_back():
    assert clarification_question(unfilled_slots(None, known=set(), has_record=True)) == CLARIFY_FALLBACK


def test_every_question_has_a_fragment_for_when_it_is_not_asked_first():
    """`CLARIFY_ALSO` is keyed on the same closed set, or a named slot would go unnamed."""
    assert set(CLARIFY_ALSO) == set(CLARIFY_QUESTIONS)
    assert all(not fragment.endswith((".", "?")) for fragment in CLARIFY_ALSO.values()), "fragments, not sentences"


def test_no_question_is_a_prefix_of_another():
    """What `clarify_slot_of`'s `startswith` rests on (G5, gap 4, fix round 1).

    The served text can now carry a fragment after the opening question, so the reverse lookup the
    replay path uses (`web/api.py::_replayed_clarify_slot`) matches on the opening question rather
    than on the whole string. That is exact only while no question is a prefix of another: were one
    added that is, a stored question would resolve to the wrong slot and the replayed turn would
    offer the wrong two quick replies — silently, because both are valid chip sets.
    """
    for slot, question in CLARIFY_QUESTIONS.items():
        others = [text for other, text in CLARIFY_QUESTIONS.items() if other != slot]
        assert not [text for text in others if question.startswith(text)], slot
        assert clarify_slot_of(f"{question} I will also need to know the dates.") == slot


def test_the_topic_table_only_ever_names_a_workflow_with_a_slot_order():
    """What the inference is allowed to return: one of the three keys `CLARIFY_SLOT_ORDER` has.

    A topic mapped to a workflow with no slot order would walk an empty order and serve the fallback
    that names nothing — the failure it was added to fix, reintroduced silently.
    """
    assert [workflow for workflow, _ in CLARIFY_TOPIC_WORDS if workflow not in CLARIFY_SLOT_ORDER] == []
    assert clarify_topic_workflow("Am I allowed to work from there for a while?") == "remote_work_eligibility"
    assert clarify_topic_workflow("How much time off do I have?") == "pto_request"
    assert clarify_topic_workflow("Can I reimburse this?") == "expense_claim"
    assert clarify_topic_workflow("Who is my manager?") is None
    assert clarify_topic_workflow("") is None
