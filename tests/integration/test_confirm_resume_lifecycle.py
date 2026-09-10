"""Decline → re-ask → confirm — the whole confirmation gate, end to end (spec §8.6, §11.2).

The narration of §18.2 in test form: cancel once to show `declined` recorded, re-ask, confirm, and
watch exactly one row appear in the mock-action log. What the file pins down:

* **`POST /chat/confirm` is the only place a token is minted**, and it is minted from the **exact**
  arguments on the gated attempt's `tool_call` span — never from `arguments_preview`, a display
  subset (§8.6 step 3);
* a **Cancel** mints the same row with `user_response="declined"`, records a **second**
  `confirmation` span through `core/trace.py` — never an in-place update of the pending one — and
  closes the turn **without** reopening it; a re-ask starts a fresh proposal in a new turn;
* a **Confirm** reopens *that* `turn_id` (`resumed_count += 1`, `seq` continued) so the write span
  and its confirmation span live in one turn, which is what `test_action_safety.py` asserts;
* the resumed response's `trace[]` is again the whole turn's spans, and the first response's was a
  documented strict prefix of it (§11.1);
* and after all of it there is **exactly one** `mock_writes` row.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.anyio

QUESTION = (
    "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
    "— and can you open the request for me?"
)


async def _ask(client, session_id: str | None = None):
    body = {"message": QUESTION, "client_label": "demo"}
    if session_id is not None:
        body["session_id"] = session_id
    response = await client.post("/chat", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def _decide(client, turn, decision):
    response = await client.post(
        "/chat/confirm",
        json={"session_id": turn["session_id"], "turn_id": turn["turn_id"], "decision": decision},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _spans(store, turn_id, kind=None):
    sql = "SELECT id, parent_span_id, seq, kind, name, payload_json FROM spans WHERE turn_id = ?"
    params = [turn_id]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    rows = store.execute(sql + " ORDER BY seq", tuple(params)).dicts()
    for row in rows:
        row["payload"] = json.loads(row.pop("payload_json"))
    return rows


@pytest.fixture
async def lifecycle(web, store):
    """Cancel the first proposal, ask again, and confirm the second."""
    async with web("confirm_lifecycle.json") as client:
        declined_turn = await _ask(client)
        declined = await _decide(client, declined_turn, "declined")
        reasked = await _ask(client, declined_turn["session_id"])
        confirmed = await _decide(client, reasked, "confirmed")
        yield {
            "declined_turn": declined_turn,
            "declined": declined,
            "reasked": reasked,
            "confirmed": confirmed,
        }


async def test_the_gated_turn_ends_awaiting_confirmation_with_a_card_and_no_token(lifecycle):
    turn = lifecycle["declined_turn"]
    assert turn["outcome"] == "awaiting_confirmation"
    card = turn["confirmation"]
    assert card is not None
    assert set(card) == {"action", "human_summary", "arguments_preview", "expires_at"}
    assert card["action"] == "create_mock_hr_ticket"
    assert card["human_summary"]
    assert "confirmation_token" not in json.dumps(turn)


async def test_nothing_is_written_while_a_turn_is_awaiting_confirmation(web, store):
    async with web("confirm_lifecycle.json") as client:
        turn = await _ask(client)

    assert turn["outcome"] == "awaiting_confirmation"
    assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 0
    assert store.execute("SELECT COUNT(*) AS n FROM confirmations").scalar() == 0


async def test_a_decline_records_a_second_confirmation_span_and_closes_the_turn(lifecycle, store):
    turn_id = lifecycle["declined_turn"]["turn_id"]
    confirmations = _spans(store, turn_id, "confirmation")

    assert [span["payload"]["user_response"] for span in confirmations] == ["pending", "declined"]
    assert confirmations[0]["seq"] < confirmations[1]["seq"], "a second span, never an in-place update"
    assert confirmations[1]["payload"]["resolved_at"] is not None
    assert lifecycle["declined"]["outcome"] == "refused"
    assert "Cancelled" in lifecycle["declined"]["answer"]

    row = store.execute("SELECT outcome, stop_reason, resumed_count FROM turns WHERE id = ?", (turn_id,)).one()
    assert (row["outcome"], row["stop_reason"]) == ("refused", "declined")
    # §11.2: a decline "closes the turn without reopening". The buffer is reopened only so the
    # second `confirmation` span goes through `core/trace.py`, and that must not be counted as a
    # resume — the dashboard's resumed-turn figures read this column.
    assert row["resumed_count"] == 0, "the declined turn was never resumed"


async def test_a_decline_mints_a_declined_row_that_is_never_returned_to_a_client(lifecycle, store):
    rows = store.execute(
        "SELECT token, tool_name, user_response, used_at FROM confirmations ORDER BY created_at"
    ).dicts()
    declined = [row for row in rows if row["user_response"] == "declined"]

    assert len(declined) == 1
    assert declined[0]["tool_name"] == "create_mock_hr_ticket"
    assert declined[0]["used_at"] is None, "validation rejects it, so it can never be spent"
    assert declined[0]["token"] not in json.dumps(lifecycle["declined"])


async def test_a_re_ask_starts_a_fresh_proposal_in_a_new_turn(lifecycle, store):
    declined_turn = lifecycle["declined_turn"]
    reasked = lifecycle["reasked"]

    assert reasked["turn_id"] != declined_turn["turn_id"]
    assert reasked["outcome"] == "awaiting_confirmation"
    turns = store.execute("SELECT id, seq, resumed_count FROM turns ORDER BY seq").dicts()
    assert len(turns) == 2, "the declined turn, then the re-asked turn"
    assert [turn["seq"] for turn in turns] == [1, 2]


async def test_a_confirm_reopens_that_turn_and_the_write_lands_in_it(lifecycle, store):
    confirmed = lifecycle["confirmed"]
    turn_id = lifecycle["reasked"]["turn_id"]

    assert confirmed["turn_id"] == turn_id, "the same turn, reopened — never a new one"
    assert confirmed["outcome"] == "answered"
    row = store.execute("SELECT resumed_count, outcome, awaiting_ms FROM turns WHERE id = ?", (turn_id,)).one()
    assert row["resumed_count"] == 1
    assert row["outcome"] == "answered"
    assert row["awaiting_ms"] >= 0

    confirmations = _spans(store, turn_id, "confirmation")
    assert [span["payload"]["user_response"] for span in confirmations] == ["pending", "confirmed"]

    writes = _spans(store, turn_id, "tool_call")
    gated = [span for span in writes if span["name"] == "create_mock_hr_ticket"]
    assert len(gated) == 2, "the refused attempt, then the authorised one"
    assert gated[0]["payload"]["error_code"] == "CONFIRMATION_REQUIRED"
    assert gated[1]["payload"]["is_error"] is False
    assert confirmations[1]["seq"] < gated[1]["seq"], "§13.4 clause 1: the confirmation comes first"


async def test_the_token_was_minted_from_the_exact_gated_arguments(lifecycle, store):
    turn_id = lifecycle["reasked"]["turn_id"]
    gated = [span for span in _spans(store, turn_id, "tool_call") if span["name"] == "create_mock_hr_ticket"][0]
    row = store.execute(
        "SELECT arguments_json, span_id, used_at, user_response FROM confirmations "
        "WHERE turn_id = ? AND user_response = 'confirmed'",
        (turn_id,),
    ).one()

    from hrmosaic.mcpserver.confirm import canonical_arguments

    assert row["arguments_json"] == canonical_arguments(gated["payload"]["arguments"])
    assert row["span_id"] == gated["id"]
    assert row["used_at"] is not None, "single use, and it was spent"
    # `arguments_preview` is a display subset; minting from it would let a changed argument through.
    card = lifecycle["reasked"]["confirmation"]["arguments_preview"]
    assert set(card) <= set(gated["payload"]["arguments"])


async def test_exactly_one_mock_writes_row_exists_and_it_names_its_confirmation(lifecycle, store):
    rows = store.execute("SELECT id, kind, employee_id, turn_id, confirmation_token FROM mock_writes").dicts()

    assert len(rows) == 1, "one Confirm, one write — the decline created nothing"
    assert rows[0]["kind"] == "hr_ticket"
    assert rows[0]["id"].startswith("MOCK-HR-")
    assert rows[0]["turn_id"] == lifecycle["reasked"]["turn_id"]

    confirmation = store.execute(
        "SELECT user_response, used_at FROM confirmations WHERE token = ?", (rows[0]["confirmation_token"],)
    ).one()
    assert confirmation["user_response"] == "confirmed"
    assert confirmation["used_at"] is not None


async def test_the_resumed_response_carries_the_whole_turn_and_the_first_was_a_prefix(lifecycle, store):
    """§11.1: equality holds on the final response; the gated one is a documented strict prefix."""
    first = [entry["seq"] for entry in lifecycle["reasked"]["trace"]]
    final = [entry["seq"] for entry in lifecycle["confirmed"]["trace"]]
    persisted = [
        row["seq"]
        for row in store.execute(
            "SELECT seq FROM spans WHERE turn_id = ? ORDER BY seq", (lifecycle["reasked"]["turn_id"],)
        ).dicts()
    ]

    assert final == persisted
    assert first == final[: len(first)]
    assert len(first) < len(final)


async def test_no_response_body_of_the_whole_lifecycle_contains_a_token(lifecycle, store):
    """§17: a `confirmations.token` never appears in a payload or a response body."""
    tokens = {row["token"] for row in store.execute("SELECT token FROM confirmations").dicts()}
    assert len(tokens) == 2

    bodies = json.dumps(lifecycle)
    assert all(token not in bodies for token in tokens)

    payloads = json.dumps([row["payload_json"] for row in store.execute("SELECT payload_json FROM spans").dicts()])
    assert all(token not in payloads for token in tokens)
