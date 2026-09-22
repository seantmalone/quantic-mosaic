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

**And the two other ways this ask can end** (fix round 1). A no-retrieval turn that is *cancelled*,
or whose authorised write *fails*, still reaches the same gate — it performed no write, so it is not
exempt and must not be — and the refusal it produced threw away the receipt: the ledes that say
*"Cancelled — nothing was created"* and *"the action itself did not complete"* are built at step 5l,
which a refusal never reaches. A grader who clicked Cancel on this very ask read that the policy
library had nothing for them and was never told nothing had been created.
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


async def test_the_ask_reaches_a_draft_hr_email_card_with_no_token(drafted, store):
    """The premise: the write is gated behind a card, and the card carries no token.

    That nothing is written *while* the card is on the screen is
    `test_confirm_resume_lifecycle.py::test_nothing_is_written_while_a_turn_is_awaiting_confirmation`
    for the ticket, and the cancelled turn below for this one — by the time this test runs its
    fixture has already confirmed.
    """
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


# --------------------------------------------------------------------------------------
# The other two endings of the same ask (fix round 1)
# --------------------------------------------------------------------------------------


async def test_a_cancelled_draft_is_answered_by_its_receipt_and_not_by_an_evidence_refusal(web, store):
    """Cancel is not a failed policy search, and the reader has to be told nothing was created."""
    from hrmosaic.agent import orchestrator

    async with web("draft_email_confirm.json") as client:
        parked = (await client.post("/chat", json={"message": QUESTION, "client_label": "demo"})).json()
        assert parked["outcome"] == "awaiting_confirmation"
        assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 0, "nothing yet"
        response = await client.post(
            "/chat/confirm",
            json={"session_id": parked["session_id"], "turn_id": parked["turn_id"], "decision": "declined"},
        )

    assert response.status_code == 200, response.text
    answer = response.json()["answer"]
    assert orchestrator.CANCELLED_NOTICE in answer, "the receipt is the answer"
    assert g1.USER_REFUSAL not in answer, "and not a report of a search that never ran"
    assert g1.OUT_OF_SCOPE_REFUSAL not in answer
    assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 0, "and nothing was created"
    # The redirect survives — it is the only other thing this turn has to offer.
    assert all(topic in answer for topic in g1.example_topics())


async def test_a_write_that_fails_after_the_confirmation_says_so_rather_than_refusing(web, store, monkeypatch):
    """The same defect on §9.4's other partial: the token validated and the draft still did not exist.

    Fault injection at the shipped gate's last step, as `test_resume_rehydrates_from_the_store.py`
    does it: `confirm.consume` is what touches `mock_writes`, so making it raise produces a genuine
    `isError` from the real server over the real transport.
    """
    import sqlite3

    from hrmosaic.agent import orchestrator
    from hrmosaic.mcpserver import confirm as confirm_gate

    def explode(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    async with web("draft_email_confirm.json") as client:
        parked = (await client.post("/chat", json={"message": QUESTION, "client_label": "demo"})).json()
        assert parked["outcome"] == "awaiting_confirmation"
        monkeypatch.setattr(confirm_gate, "consume", explode)
        response = await client.post(
            "/chat/confirm",
            json={"session_id": parked["session_id"], "turn_id": parked["turn_id"], "decision": "confirmed"},
        )

    assert response.status_code == 200, response.text
    answer = response.json()["answer"]
    assert orchestrator.WRITE_FAILED_RECEIPT in answer, "the reader is told the action did not complete"
    assert g1.USER_REFUSAL not in answer
    assert "MOCK-EMAIL-" not in answer, "no reference was allocated, so none is named"
    assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 0


async def test_a_failed_write_is_never_rendered_as_having_gone_ahead(web, store, monkeypatch):
    """The same turn on the **rendered** surface (fix round 2).

    `chat_confirm` renders the decision line from what the reader clicked, and `resolved_decision`
    suppressed it for the confirmation refusal only — so this turn put *"You approved this — it went
    ahead."* directly above *"…the action itself did not complete, so nothing was created."* Asserted
    on the htmx fragment, because that is the surface the contradiction is on.
    """
    import sqlite3

    from hrmosaic.agent import orchestrator
    from hrmosaic.mcpserver import confirm as confirm_gate
    from hrmosaic.web import api

    def explode(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    async with web("draft_email_confirm.json") as client:
        parked = (await client.post("/chat", json={"message": QUESTION, "client_label": "demo"})).json()
        assert parked["outcome"] == "awaiting_confirmation"
        monkeypatch.setattr(confirm_gate, "consume", explode)
        rendered = await client.post(
            "/chat/confirm",
            json={"session_id": parked["session_id"], "turn_id": parked["turn_id"], "decision": "confirmed"},
            headers={"HX-Request": "true"},
        )

    assert rendered.status_code == 200, rendered.text
    html = rendered.text
    assert api.DECISION_LINES["confirmed"] not in html, "nothing went ahead, so the page may not say so"
    assert orchestrator.WRITE_FAILED_RECEIPT in html, "and the reader is told what did happen"
    assert g1.USER_REFUSAL not in html
    assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 0
