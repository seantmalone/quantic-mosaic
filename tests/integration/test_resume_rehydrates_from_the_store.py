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

import contextlib
import json
import sqlite3
import threading
from unittest import mock

import pytest

from hrmosaic.agent.client import McpClient
from hrmosaic.agent.guardrails import g1
from hrmosaic.agent.orchestrator import ChatRequest, Orchestrator
from hrmosaic.core.llm.stub import StubAdapter
from hrmosaic.mcpserver import confirm
from hrmosaic.rag import retrieve
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

    # **One span, resolved in place** (W8, C11). It is the proposal's own: the card that was shown
    # and the answer the human gave it are one fact, and the span that carried the card is where
    # the answer belongs. Leaving it `pending` for ever and writing a second span beside it is what
    # let the same card be confirmed twice — `POST /chat/confirm` mints from a pending span.
    assert confirmations("pending") == [], "the proposal's own span carries the answer"
    assert confirmed[0]["payload_json"] and json.loads(confirmed[0]["payload_json"])["resolved_at"]


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


@pytest.fixture
async def write_failed_after_confirmation(writer, store, mounted_mcp_url, monkeypatch):
    """The same flow, with the ticket write failing **after** its token validated.

    Fault injection, not a mock of the thing under test: `confirm.consume` is the last step of tool
    8 and the one that touches `mock_writes`, so making it raise produces a genuine `isError` result
    from the shipped server over the real transport — the class of failure `_resume` has to branch
    on and could not otherwise be reached, because bad arguments never park in the first place.
    """
    orchestrator = Orchestrator(
        client=McpClient(transport="http", url=mounted_mcp_url),
        model=StubAdapter(script_path=LLM_SCRIPTS / "confirm_resume.json"),
    )
    try:
        parked = await orchestrator.run_turn(ChatRequest(message=QUESTION, employee_id="E1042"))
        assert parked.outcome == "awaiting_confirmation"
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

        def explode(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(confirm, "consume", explode)
        resumed = await orchestrator.resume_turn(parked.session_id, parked.turn_id, token)
        return parked, resumed
    finally:
        await orchestrator.aclose()


async def test_a_write_that_fails_after_confirmation_does_not_close_the_turn_answered(
    write_failed_after_confirmation, store
):
    """The token validated and the ticket still did not exist; §9.4's partial, never "answered"."""
    parked, resumed = write_failed_after_confirmation

    assert store.execute("SELECT count(*) FROM mock_writes").scalar() == 0, "nothing was created"
    assert resumed.outcome == "partial"
    closed = store.execute("SELECT outcome, stop_reason FROM turns WHERE id = ?", (parked.turn_id,)).one()
    assert (closed["outcome"], closed["stop_reason"]) == ("partial", "tool_failed")
    assert resumed.answer_blocks[0].text.startswith("The confirmation was accepted but the action")

    errors = [
        json.loads(row["payload_json"])
        for row in store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'error' ORDER BY seq", (parked.turn_id,)
        ).dicts()
    ]
    # `distinct_docs_shortfall` rides along on this turn because the repair round was bought and
    # the recorded answer still cites fewer documents than the workflow expects (W8, C26). It is a
    # record of the served answer's breadth, not of the write. Exact, so a future extra error span
    # on this turn is noticed rather than tolerated (W7-review Minor).
    assert [error["error_kind"] for error in errors] == ["tool_failed", "distinct_docs_shortfall"]
    assert errors[0]["component"] == "mcp" and "create_mock_hr_ticket" in errors[0]["message"]


async def test_the_failure_reaches_the_model_and_no_ticket_id_is_invented(write_failed_after_confirmation, store):
    """`_act`'s rule on the resume path: the body goes to the envelopes, not into `LoopState`.

    The half that is observable from outside is asserted here — the model is shown what went wrong,
    so it can say so, and no `MOCK-HR-…` id appears anywhere, because none was ever allocated. The
    other half, that the result never satisfies `pto_request`'s gated slot, is what
    `outcome == "partial"` above records.
    """
    parked, resumed = write_failed_after_confirmation
    span_id = json.loads(
        store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'llm_call' "
            "AND json_extract(payload_json, '$.purpose') = 'synthesize' ORDER BY seq DESC LIMIT 1",
            (parked.turn_id,),
        ).scalar()
    )["messages_ref"]["span_id"]
    prompt = "\n".join(
        row["content"]
        for row in store.execute("SELECT content FROM llm_messages WHERE span_id = ? ORDER BY seq", (span_id,)).dicts()
    )

    assert "MOCK-HR-" not in prompt, "no ticket id was ever allocated"
    assert "create_mock_hr_ticket" in prompt, "the failure itself is still shown to the model"
    assert not any(block.text.startswith("MOCK-HR-") for block in resumed.answer_blocks)


# --------------------------------------------------------------------------------------
# The confirmation boundary, for a turn grounded on the compliance engine (P13 R7 / review)
# --------------------------------------------------------------------------------------

#: The same request, asked of a turn that never searches: `pto_request` reaches its verdict from the
#: engine, whose per-requirement evidence R7 scores and admits.
ENGINE_QUESTION = QUESTION


@contextlib.asynccontextmanager
async def an_engine_grounded_park(store, writer, mounted_mcp_url):
    """Park an engine-grounded turn at §8.6's gate; yield the orchestrator, the turn and the token.

    Split out of the fixture below so a test can wrap the **resume** itself — the P14 review's
    finding needs the resume to happen under a patched `score_chunk_ids`, not before the test runs.
    """
    orchestrator = Orchestrator(
        client=McpClient(transport="http", url=mounted_mcp_url),
        model=StubAdapter(script_path=LLM_SCRIPTS / "compliance_confirm_resume.json"),
    )
    try:
        parked = await orchestrator.run_turn(ChatRequest(message=ENGINE_QUESTION, employee_id="E1042"))
        assert parked.outcome == "awaiting_confirmation"
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
        yield orchestrator, parked, token
    finally:
        await orchestrator.aclose()


@pytest.fixture
async def engine_grounded_then_confirmed(writer, store, mounted_mcp_url):
    """A turn whose only evidence is the compliance engine's, parked at the gate and resumed.

    Since R7 that evidence counts towards `is_complete` and towards G1 — but it is *scored*, not
    retrieved, so it never reaches a `retrieval` span and `_rehydrate_retrieval` cannot bring it
    back. `_rehydrate` therefore has to re-run the same scoring over the `tool_call` span, or the
    evidence gate means two different things on the two sides of the park.
    """
    async with an_engine_grounded_park(store, writer, mounted_mcp_url) as (orchestrator, parked, token):
        return parked, await orchestrator.resume_turn(parked.session_id, parked.turn_id, token)


def engine_chunk_ids(store, turn_id: str) -> set[str]:
    """The chunk ids the compliance engine put in its own per-requirement evidence blocks."""
    payloads = [
        json.loads(row["payload_json"])
        for row in store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'tool_call' ORDER BY seq", (turn_id,)
        ).dicts()
    ]
    body = next(
        payload["structured_content"] for payload in payloads if payload["tool_name"] == "check_policy_compliance"
    )
    return {
        requirement["evidence"]["chunk_id"]
        for requirement in body["requirements"]
        if (requirement.get("evidence") or {}).get("chunk_id")
    }


async def test_the_parked_turn_never_retrieved_and_still_holds_evidence(engine_grounded_then_confirmed, store):
    """The premise: no `retrieval` span exists, so only R7's scoring can have grounded this turn."""
    parked, _ = engine_grounded_then_confirmed
    kinds = [
        row["kind"]
        for row in store.execute("SELECT kind FROM spans WHERE turn_id = ? ORDER BY seq", (parked.turn_id,)).dicts()
    ]

    assert "retrieval" not in kinds, "nothing was searched — the engine is the only source of evidence"
    assert engine_chunk_ids(store, parked.turn_id), "and the engine did name committed chunks"


async def test_a_confirmed_engine_grounded_turn_is_not_refused_for_want_of_evidence(
    engine_grounded_then_confirmed, store
):
    """The review's finding 1: the gate has to mean the same thing on both sides of the park.

    Before the fix the resumed turn rebuilt `citable()` from `retrieval` spans alone — empty here —
    and G1 refused with `no policy evidence was retrieved`, on a write that had already happened.
    """
    parked, resumed = engine_grounded_then_confirmed

    assert resumed.outcome == "answered"
    assert store.execute("SELECT count(*) FROM mock_writes").scalar() == 1
    gates = [
        json.loads(row["payload_json"])
        for row in store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'guardrail' ORDER BY seq", (parked.turn_id,)
        ).dicts()
    ]
    verdicts = [payload["verdict"] for payload in gates if payload["rule_id"] == "G1"]
    assert verdicts and set(verdicts) == {"allow"}, "G1 allowed on both sides of the confirmation"
    assert {citation.chunk_id for citation in resumed.citations} <= engine_chunk_ids(store, parked.turn_id)


async def test_the_resumed_synthesize_prompt_still_carries_the_engine_chunks(engine_grounded_then_confirmed, store):
    """§9.1's property, for engine evidence: the resumed prompt carries the pre-confirmation set."""
    parked, _ = engine_grounded_then_confirmed
    before = engine_chunk_ids(store, parked.turn_id)
    synthesize = store.execute(
        "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'llm_call' "
        "AND json_extract(payload_json, '$.purpose') = 'synthesize' ORDER BY seq DESC LIMIT 1",
        (parked.turn_id,),
    ).scalar()
    assert synthesize is not None, "the resumed turn reached synthesis rather than a refusal"
    span_id = json.loads(synthesize)["messages_ref"]["span_id"]
    prompt = "\n".join(
        row["content"]
        for row in store.execute("SELECT content FROM llm_messages WHERE span_id = ? ORDER BY seq", (span_id,)).dicts()
    )

    assert before
    assert all(chunk_id in prompt for chunk_id in before), "every engine chunk survived the park"


async def test_the_resumed_engine_scoring_does_not_run_on_the_event_loop(store, writer, mounted_mcp_url):
    """P14 review: the resume path embeds too, and `POST /chat/confirm` awaits it (P13 carry-forward p2).

    `_rehydrate` re-runs `_engine_evidence` over the parked `tool_call` span, and that scoring
    embeds the turn's question — ≈ 0.6 s of ONNX on the 0.1-CPU instance. `_rehydrate` is
    synchronous, but `resume_turn` is a coroutine that `web/api.py` awaits, so the embed was on the
    loop thread: for those 0.6 s the confirm path served nothing, exactly as the act loop used to
    before `_absorb_async`. `_rehydrate_scores` is that path's async boundary.
    """
    scored_on: list[int] = []
    real = retrieve.score_chunk_ids

    def recording(chunk_ids, *, query):
        scored_on.append(threading.get_ident())
        return real(chunk_ids, query=query)

    async with an_engine_grounded_park(store, writer, mounted_mcp_url) as (orchestrator, parked, token):
        with mock.patch.object(retrieve, "score_chunk_ids", recording):
            resumed = await orchestrator.resume_turn(parked.session_id, parked.turn_id, token)
        loop_thread = threading.get_ident()

    assert resumed.outcome == "answered", "the resumed turn still reaches an answer"
    assert {citation.chunk_id for citation in resumed.citations} <= engine_chunk_ids(store, parked.turn_id)
    assert scored_on, "the parked turn's engine evidence still has to be scored"
    assert all(thread != loop_thread for thread in scored_on), "and never on the thread running the loop"
    assert len(scored_on) == 1, "scored once, ahead of the walk — the walk is handed the result"


# --------------------------------------------------------------------------------------
# A confirmation that cannot be acted on says so (G5, gap 19)
# --------------------------------------------------------------------------------------
#
# `_resume` passes two non-evidence reasons into `g1.refusal()`, and until G5 neither had any copy:
# `refusal_text` fell through to `USER_REFUSAL`, so a reader who had just clicked **Confirm** was told
# *"I could not find anything in Mosaic's policy library that answers this"* — about a search that
# never ran, on a turn whose whole subject was a write. Neither branch had a test.


async def test_a_refused_confirmation_is_not_reported_as_a_failed_policy_search(writer, store, mounted_mcp_url):
    """Branch one: the token does not validate, so `create_mock_hr_ticket` gates the call again."""
    orchestrator = Orchestrator(
        client=McpClient(transport="http", url=mounted_mcp_url),
        model=StubAdapter(script_path=LLM_SCRIPTS / "confirm_resume.json"),
    )
    try:
        parked = await orchestrator.run_turn(ChatRequest(message=QUESTION, employee_id="E1042"))
        assert parked.outcome == "awaiting_confirmation"
        writer.reopen_turn(parked.turn_id, awaiting_ms=0)
        resumed = await orchestrator.resume_turn(parked.session_id, parked.turn_id, "not-a-minted-token")
    finally:
        await orchestrator.aclose()

    assert resumed.outcome == "refused"
    assert resumed.answer_blocks[0].text == g1.CONFIRMATION_REFUSAL
    assert g1.USER_REFUSAL not in resumed.answer, "nothing was searched, so nothing may say a search failed"
    assert "policy library" not in resumed.answer
    assert store.execute("SELECT count(*) FROM mock_writes").scalar() == 0, "and nothing was created"


async def test_a_turn_with_nothing_to_confirm_says_that_instead_of_refusing_a_search(writer, mounted_mcp_url):
    """Branch two: the card is spent or expired, so the resumed turn has no gated call to re-issue."""
    orchestrator = Orchestrator(
        client=McpClient(transport="http", url=mounted_mcp_url),
        model=StubAdapter(script_path=LLM_SCRIPTS / "rag_only.json"),
    )
    try:
        answered = await orchestrator.run_turn(
            ChatRequest(message="How much PTO do full-time employees accrue each month?", employee_id="E1042")
        )
        assert answered.outcome == "answered", "a turn that never proposed a write"
        writer.reopen_turn(answered.turn_id, awaiting_ms=0)
        resumed = await orchestrator.resume_turn(answered.session_id, answered.turn_id, "a-token-for-nothing")
    finally:
        await orchestrator.aclose()

    assert resumed.outcome == "refused"
    assert resumed.answer_blocks[0].text == g1.CONFIRMATION_REFUSAL
    assert g1.USER_REFUSAL not in resumed.answer
