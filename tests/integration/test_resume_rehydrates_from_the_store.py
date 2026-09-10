"""`resume_turn` picks a parked turn back up from the store (spec §9.1, §8.6 steps 4-5).

The act loop's state was in-process and is gone once `/chat` returned, so a resumed turn rebuilds it
from its **own spans**: the message array from the last `act` call's `llm_messages` rows, the chunk
set from its `retrieval` spans, prior tool results from its `tool_call` spans, and the step counter
from the count of `act`-purpose `llm_call` spans. The property that makes that worth asserting is
the negative one — **it never re-retrieves** — because a `resume_turn` that silently re-ran the
search would look identical from the outside while quietly answering from different evidence.

This is P7's own coverage of the entry point it ships. P8 owns the HTTP lifecycle
(`tests/integration/test_confirm_resume_lifecycle.py`: decline → re-ask → confirm over
`POST /chat/confirm`); here the token is minted directly, standing in for the `web/` layer that does
not exist yet.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent.client import McpClient
from hrmosaic.agent.orchestrator import ChatRequest, Orchestrator
from hrmosaic.core.llm.stub import StubAdapter
from hrmosaic.mcpserver import confirm
from tests.conftest import LLM_SCRIPTS

pytestmark = pytest.mark.anyio

QUESTION = (
    "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 — "
    "and can you open the request for me?"
)


@pytest.fixture
async def gated_then_confirmed(writer, store, mounted_mcp_url):
    """One gated turn, a human Confirm, and the resumed turn — on one orchestrator, as in the app.

    Over the **mounted HTTP** transport, not stdio: the confirmation gate reads `confirmations` from
    the trace store, and a stdio subprocess has a store of its own. In the deployed topology the MCP
    server shares this process, which is exactly why the gate can be a wire-level check (§8.1, §8.6).
    """
    orchestrator = Orchestrator(
        client=McpClient(transport="http", url=mounted_mcp_url),
        model=StubAdapter(script_path=LLM_SCRIPTS / "confirm_resume.json"),
    )
    try:
        parked = await orchestrator.run_turn(ChatRequest(message=QUESTION, employee_id="E1042"))
        assert parked.outcome == "awaiting_confirmation"

        # What `POST /chat/confirm` does (§8.6 step 3): mint from the **exact** arguments recorded
        # on the gated attempt's `tool_call` span, never from `arguments_preview`.
        gated = json.loads(
            store.execute(
                "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'tool_call' ORDER BY seq DESC LIMIT 1",
                (parked.turn_id,),
            ).scalar()
        )
        token = confirm.mint(
            store,
            session_id=parked.session_id,
            turn_id=parked.turn_id,
            span_id="0" * 16,
            tool_name=gated["tool_name"],
            arguments=gated["arguments"],
            human_summary="Open an HR ticket.",
        )
        writer.reopen_turn(parked.turn_id, awaiting_ms=0)
        resumed = await orchestrator.resume_turn(parked.session_id, parked.turn_id, token)
        return parked, resumed
    finally:
        await orchestrator.aclose()


async def test_the_confirmed_write_happens_exactly_once(gated_then_confirmed, store):
    parked, resumed = gated_then_confirmed

    assert resumed.outcome == "answered"
    rows = store.execute("SELECT id, turn_id, confirmation_token FROM mock_writes").dicts()
    assert len(rows) == 1
    assert rows[0]["id"].startswith("MOCK-HR-")
    assert rows[0]["turn_id"] == parked.turn_id, "the write lives in the turn that proposed it (§9.6)"
    assert store.execute("SELECT count(*) FROM turns").scalar() == 1


async def test_the_confirmation_span_precedes_the_write_it_authorised(gated_then_confirmed, store):
    """§13.4 action-safety clause 1 keys on an **earlier** `confirmation` span in the same turn."""
    parked, _ = gated_then_confirmed
    rows = store.execute(
        "SELECT seq, kind, name, status, payload_json FROM spans WHERE turn_id = ? ORDER BY seq",
        (parked.turn_id,),
    ).dicts()

    def confirmations(response: str) -> list[dict]:
        return [
            row
            for row in rows
            if row["kind"] == "confirmation" and json.loads(row["payload_json"])["user_response"] == response
        ]

    confirmed = confirmations("confirmed")
    written = [
        row
        for row in rows
        if row["kind"] == "tool_call"
        and row["status"] == "ok"
        and json.loads(row["payload_json"])["tool_name"] == "create_mock_hr_ticket"
    ]
    assert len(confirmed) == 1 and len(written) == 1
    assert confirmed[0]["seq"] < written[0]["seq"]

    pending = confirmations("pending")
    assert len(pending) == 1, "the pending span is never updated in place (§11.2)"
    assert pending[0]["seq"] < confirmed[0]["seq"]


async def test_the_resumed_turn_answers_from_the_pre_confirmation_evidence(gated_then_confirmed, store):
    """A `resume_turn` that silently re-retrieved would fail here (§9.1)."""
    parked, resumed = gated_then_confirmed
    rows = store.execute(
        "SELECT seq, kind, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (parked.turn_id,)
    ).dicts()

    retrievals = [row for row in rows if row["kind"] == "retrieval"]
    assert len(retrievals) == 1, "the resumed turn retrieved nothing new"
    before = {chunk["chunk_id"] for chunk in json.loads(retrievals[0]["payload_json"])["chunks"]}

    synthesize = [
        row for row in rows if row["kind"] == "llm_call" and json.loads(row["payload_json"])["purpose"] == "synthesize"
    ]
    assert len(synthesize) == 1
    span_id = json.loads(synthesize[0]["payload_json"])["messages_ref"]["span_id"]
    prompt = "\n".join(
        row["content"]
        for row in store.execute("SELECT content FROM llm_messages WHERE span_id = ? ORDER BY seq", (span_id,)).dicts()
    )
    assert before, "the first attempt did retrieve something"
    assert all(chunk_id in prompt for chunk_id in before)
    assert {citation.chunk_id for citation in resumed.citations} <= before


async def test_the_token_is_spent_and_never_leaves_the_process(gated_then_confirmed, store):
    parked, resumed = gated_then_confirmed
    row = store.execute("SELECT token, used_at, user_response FROM confirmations").one()

    assert row["used_at"] is not None and row["user_response"] == "confirmed"
    assert row["token"] not in resumed.model_dump_json()
    payloads = store.execute("SELECT payload_json FROM spans WHERE turn_id = ?", (parked.turn_id,)).dicts()
    assert all(row["token"] not in payload["payload_json"] for payload in payloads)


async def test_the_resumed_response_carries_the_whole_turn(gated_then_confirmed, store):
    """§11.1: the first response's `trace[]` is a strict prefix, and equality holds again on resume."""
    parked, resumed = gated_then_confirmed
    persisted = [
        row["seq"]
        for row in store.execute("SELECT seq FROM spans WHERE turn_id = ? ORDER BY seq", (parked.turn_id,)).dicts()
    ]

    assert {entry.seq for entry in resumed.trace} == set(persisted)
    assert {entry.seq for entry in parked.trace} < {entry.seq for entry in resumed.trace}
    assert [entry.seq for entry in parked.trace] == sorted(entry.seq for entry in parked.trace)
