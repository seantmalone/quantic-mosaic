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

The missing information each item expects is read from `evaluation/dataset.yaml`'s own
`clarification_expects`, because that string is what the judge is handed as MISSING INFORMATION
(`evaluation/judges.py::CLARIFICATION_USER`). The assertions below are the deterministic half of that
verdict: the words the judge would have to read to answer `entailed: true`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hrmosaic.agent.orchestrator import (
    CLARIFY_ALSO,
    CLARIFY_FALLBACK,
    CLARIFY_QUESTIONS,
    ChatRequest,
    clarification_question,
    unfilled_slots,
)

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
