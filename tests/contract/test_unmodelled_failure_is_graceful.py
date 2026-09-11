"""An exception the design does not model still answers 200 and still closes its turn (§12.3).

Constraint 11 is unconditional: *"Every failure path answers HTTP 200 with a useful body"*, and
§12.3 adds *"never a 5xx, never a stack trace"*. The modelled failures — a missing credential, an
unreachable MCP server, an empty retrieval, a daily cap — each have their own typed answer inside
`run_turn`. This file is about the one that is left: something nobody modelled, raised anywhere
inside a request.

Two things have to happen, and the second is the one that corrupts the audit trail when it does
not. The caller gets a typed 200 rather than a bare 500; and the turn that was in flight is
**closed**, with an `error` span recording what happened, instead of sitting `ended_at IS NULL`
until the next boot's `sweep_stale_turns()` writes it off as a process exit that never occurred.

The failure is injected by exhausting the committed stub script: `rag_only.json` has five
completions, all spent by the first turn, so the second turn asks for a sixth and `StubScriptError` —
a plain `RuntimeError`, none of the modelled failures — is raised with the turn's first spans
already buffered. That is
exactly the state an unmodelled crash leaves behind, and it takes no timing assumption at all.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.anyio

QUESTION = "How much PTO do full-time employees accrue each month?"


@pytest.fixture
async def crashed(web, store):
    """One turn that answers, then one whose model call raises something unmodelled."""
    async with web("rag_only.json") as client:
        answered = await client.post("/chat", json={"message": QUESTION})
        assert answered.status_code == 200, answered.text
        yield await client.post("/chat", json={"message": QUESTION})


async def test_it_answers_200_with_a_typed_escalation_and_no_stack_trace(crashed):
    assert crashed.status_code == 200, crashed.text
    body = crashed.json()

    assert body["outcome"] == "error"
    assert [block["type"] for block in body["answer_blocks"]] == ["recommendation", "escalation"]
    assert "people-ops@" in body["answer_blocks"][1]["text"]
    assert body["citations"] == []

    # §12.3's "never a stack trace": the answer the grader reads says what to do, not what broke.
    # The exception's one-line message is recorded on the `error` span, exactly as every modelled
    # failure records its own — so it reaches `trace[]` and the dashboard, and nowhere else.
    answer = json.dumps([body["answer"], body["answer_blocks"]])
    assert "StubScriptError" not in answer
    assert "Traceback" not in json.dumps(body)


async def test_the_turn_is_closed_with_an_error_span_rather_than_left_open(crashed, store):
    turn_id = crashed.json()["turn_id"]

    row = store.execute("SELECT ended_at, outcome, stop_reason, error_kind FROM turns WHERE id = ?", (turn_id,)).one()
    assert row["ended_at"] is not None, "the turn was closed, not left for the boot sweep"
    assert (row["outcome"], row["stop_reason"], row["error_kind"]) == ("error", "error", "internal")

    assert store.execute("SELECT COUNT(*) AS n FROM turns WHERE ended_at IS NULL").scalar() == 0


async def test_the_error_span_names_the_exception_and_goes_through_the_one_trace_writer(crashed, store):
    turn_id = crashed.json()["turn_id"]
    spans = store.execute(
        "SELECT name, status, error_message, payload_json FROM spans WHERE turn_id = ? AND kind = 'error'",
        (turn_id,),
    ).dicts()

    internal = [span for span in spans if json.loads(span["payload_json"])["error_kind"] == "internal"]
    assert len(internal) == 1
    span = internal[0]
    assert span["name"] == "web"
    assert span["status"] == "error"
    assert "StubScriptError" in span["error_message"]


async def test_the_trace_is_the_projection_of_the_spans_the_failed_turn_did_write(crashed, store):
    body = crashed.json()
    seqs = store.execute("SELECT seq FROM spans WHERE turn_id = ?", (body["turn_id"],)).dicts()

    assert {entry["seq"] for entry in body["trace"]} == {row["seq"] for row in seqs}
    assert body["trace"], "the spans the turn got as far as writing are still reported"


# --------------------------------------------------------------------------------------
# ...and when the error path itself cannot reach the store
# --------------------------------------------------------------------------------------
#
# Closing the turn above writes through `core/trace.py` to the store. An unreachable trace store is
# one of the five modelled `degradations[]`, so the two failures coincide the moment Turso is down:
# the unmodelled exception is caught, and then `TurnBuffer.close()` raises inside the handler's own
# `except` clause. Before the fix that second exception escaped the ASGI middleware and uvicorn
# answered a bare `500 Internal Server Error` with a plain-text body — exactly what constraint 11
# and §12.3 forbid, on the one path that exists to honour them.
#
# The store is broken *after* `start_turn`'s batch so a turn buffer exists to close: the branch at
# `unhandled_error_response`'s `buffer is None` was always safe, and it is the buffered branch that
# was not. The turn stays `ended_at IS NULL` here — unavoidable when the store cannot be written —
# and `sweep_stale_turns()` at boot is the existing backstop, so nothing below asserts on it.


@pytest.fixture
async def crashed_with_an_unreachable_store(web, store, monkeypatch):
    from hrmosaic.core.db import StoreError

    async with web("rag_only.json") as client:
        answered = await client.post("/chat", json={"message": QUESTION})
        assert answered.status_code == 200, answered.text

        real_batch = store.batch
        remaining = {"batches": 1}  # one for `start_turn`; the closing batch is the one that fails

        def failing_batch(statements):
            if remaining["batches"] > 0:
                remaining["batches"] -= 1
                return real_batch(statements)
            raise StoreError("turso request failed: connection refused")

        monkeypatch.setattr(store, "batch", failing_batch)
        yield await client.post("/chat", json={"message": QUESTION})


async def test_a_store_failure_inside_the_catch_all_still_answers_200(crashed_with_an_unreachable_store):
    response = crashed_with_an_unreachable_store

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["detail"].startswith("Something went wrong")


async def test_the_store_less_answer_still_carries_no_stack_trace(crashed_with_an_unreachable_store):
    body = json.dumps(crashed_with_an_unreachable_store.json())

    assert "Traceback" not in body
    assert "StubScriptError" not in body
    assert "StoreError" not in body
    assert "connection refused" not in body
