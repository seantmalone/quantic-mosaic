"""A confirmed `draft_hr_email` is reported as done, never refused (G5, gap 21).

The measured defect, on the deployed build `e85305b`: session
`3de0ea69a1d09447ce36fa0398e19cab`, turn `87992de4dc8a7844370b5ed49b9a555d`. *"Can you draft an
email to my manager Dana…"* routed to `draft_hr_email` on the first try, the card appeared with no
token, `POST /chat/confirm` performed the write and the server minted **`MOCK-EMAIL-000018`** — and
then the resumed turn closed `refused`, with *"I could not find anything in Mosaic's policy library
that answers this"* as its whole answer. The G1 span records why: `candidates: 0`, reason *"no
policy evidence was retrieved for this question"*. A plain "draft me an email" ask searches nothing,
so the evidence gate — which asks whether there is enough retrieved policy to ground a policy
answer — refused a turn whose write had already happened, and the refusal is the one answer that
cannot name the reference the reader needs.

`scripts/demo_task_2.sh` pins this property for `create_mock_hr_ticket` ("the ticket was created …
and the answer still ended 'I cannot open PTO requests on your behalf'"). Nothing pinned it for
`draft_hr_email`, because every `evaluation/dataset.yaml` item lists that tool under
`forbidden_tools`. This file is that pin, in the style of `test_confirm_resume_lifecycle.py`.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent.guardrails import g1

pytestmark = pytest.mark.anyio

#: The ask exactly as the deployed turn was driven with it (task 4's report, gap 21).
QUESTION = (
    "Can you draft an email to my manager Dana asking her to approve three days of PTO "
    "from Tuesday 6 October to Thursday 8 October 2026?"
)


@pytest.fixture
async def drafted(web, store):
    """Ask, reach the card, confirm — the whole path the live turn took."""
    async with web("draft_email_confirm.json") as client:
        parked = await client.post("/chat", json={"message": QUESTION, "client_label": "demo"})
        assert parked.status_code == 200, parked.text
        card = parked.json()
        response = await client.post(
            "/chat/confirm",
            json={"session_id": card["session_id"], "turn_id": card["turn_id"], "decision": "confirmed"},
        )
        assert response.status_code == 200, response.text
        yield {"parked": card, "confirmed": response.json()}


async def test_the_ask_reaches_a_draft_hr_email_card_and_writes_nothing(drafted, store):
    """The premise: the write is gated, and nothing exists while the card is on the screen."""
    parked = drafted["parked"]

    assert parked["outcome"] == "awaiting_confirmation"
    assert parked["confirmation"]["action"] == "draft_hr_email"
    assert "confirmation_token" not in json.dumps(parked)


async def test_the_confirmed_turn_is_answered_and_opens_with_the_draft_reference(drafted):
    """What the live turn did not do: close `answered`, and say what was created."""
    confirmed = drafted["confirmed"]

    assert confirmed["outcome"] == "answered"
    assert confirmed["turn_id"] == drafted["parked"]["turn_id"], "the same turn, reopened"
    opener = confirmed["answer_blocks"][0]["text"]
    assert opener.startswith("Done — the email draft is ready"), opener
    assert "MOCK-EMAIL-" in opener, "the reference the reader needs is in the first sentence"
    assert "Dana Whitfield" in opener, "and who it is addressed to"


async def test_the_confirmed_turn_never_serves_a_refusal(drafted):
    """The regression itself: neither refusal copy, and no refuse-and-redirect next steps."""
    confirmed = drafted["confirmed"]
    answer = confirmed["answer"]

    assert g1.USER_REFUSAL not in answer, "a draft that exists is not a failed policy search"
    assert g1.OUT_OF_SCOPE_REFUSAL not in answer
    assert g1.CONFIRMATION_REFUSAL not in answer, "the confirmation was acted on"
    assert not all(topic in answer for topic in g1.example_topics()), "no refuse-and-redirect"


async def test_the_evidence_gate_never_refuses_a_turn_whose_write_has_happened(drafted, store):
    """One `draft_hr_email` row, and no G1 refusal in the turn that created it."""
    turn_id = drafted["parked"]["turn_id"]
    rows = store.execute("SELECT id, kind, turn_id FROM mock_writes").dicts()

    assert len(rows) == 1
    assert rows[0]["kind"] == "hr_email"
    assert rows[0]["id"].startswith("MOCK-EMAIL-")
    assert rows[0]["turn_id"] == turn_id

    guardrails = [
        json.loads(row["payload_json"])
        for row in store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'guardrail' ORDER BY seq", (turn_id,)
        ).dicts()
    ]
    gates = [payload for payload in guardrails if payload["rule_id"] == "G1"]
    assert [payload["verdict"] for payload in gates] == ["allow"], "one gate span, and it did not refuse"
    # …and the span still records what the retrieval was worth, behind the reason it allowed on.
    assert gates[0]["reason"].startswith(g1.PERFORMED_WRITE)
    assert g1.NO_EVIDENCE in gates[0]["reason"]
    assert gates[0]["details"]["candidates"] == 0
    assert store.execute("SELECT outcome FROM turns WHERE id = ?", (turn_id,)).scalar() == "answered"
