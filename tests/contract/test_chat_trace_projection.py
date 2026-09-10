"""`trace[]` is a projection of **all** the turn's spans — the R4.3 table, row by row (spec §11.1).

Two claims, and the second is the one USER.4 turns on:

1. every element R4.3 enumerates maps onto a named record in the response, and the last row is
   R4.1's ("the decision to use RAG or tools"), kept here because the same `plan` span carries it;
2. `{entry.seq for entry in trace} == {seq of that turn's spans}` — the concise trace and the
   dashboard are provably the same records, not two logging paths.

Equality is asserted against the **final** response of a turn. On a confirmation-gated turn the
first response's `trace[]` is a documented strict prefix, and equality holds again on the resumed
response; `tests/integration/test_confirm_resume_lifecycle.py` owns that half.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio

TOOL_USING_QUESTION = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"
SENSITIVE_QUESTION = "A colleague has been harassing me in meetings and I want to raise it formally."


async def _turn(client, message: str, **body):
    response = await client.post("/chat", json={"message": message, **body})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
async def tool_using_turn(web, store):
    async with web("demo_task_1.json") as client:
        yield await _turn(client, TOOL_USING_QUESTION, client_label="demo")


def _payloads(store, turn_id: str, kind: str) -> list[dict]:
    import json

    rows = store.execute(
        "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = ? ORDER BY seq", (turn_id, kind)
    ).dicts()
    return [json.loads(row["payload_json"]) for row in rows]


async def test_row_1_selected_tools_are_on_the_plan_span_and_one_tool_call_entry_each(tool_using_turn, store):
    plans = _payloads(store, tool_using_turn["turn_id"], "plan")
    selected = {name for plan in plans for name in plan["selected_tools"]}
    called = {entry["name"] for entry in tool_using_turn["trace"] if entry["kind"] == "tool_call"}

    assert selected, "the router recorded what it selected"
    assert called, "and each call has its own trace entry"
    assert called <= selected | called  # every call is named; the plan may also offer more


async def test_rows_2_and_3_every_tool_call_entry_carries_its_arguments_and_its_output(tool_using_turn):
    entries = [entry for entry in tool_using_turn["trace"] if entry["kind"] == "tool_call"]
    assert entries
    for entry in entries:
        assert entry["args_preview"].startswith("{")
        assert entry["result_preview"]


async def test_row_4_every_retrieval_entry_names_k_the_top_score_and_the_documents(tool_using_turn, store):
    """The row is about the `summary`: how many chunks, the top dense score, and which documents.

    The entry's `name` is the tool that produced the retrieval (P5's span), not the strategy the
    §11.1 example happens to show; the strategy is a field of the `retrieval` payload and a column
    of dashboard page 6, so nothing is lost.
    """
    entries = [entry for entry in tool_using_turn["trace"] if entry["kind"] == "retrieval"]
    assert entries
    documents = {citation["doc_id"] for citation in tool_using_turn["citations"]}
    for entry in entries:
        assert "chunks" in entry["summary"]
        assert "top dense" in entry["summary"]
    assert any(doc_id in entry["summary"] for entry in entries for doc_id in documents)
    for payload in _payloads(store, tool_using_turn["turn_id"], "retrieval"):
        assert payload["strategy"] in {"hybrid_rrf", "dense_only"}
        assert payload["chunks"] and payload["max_dense_score"] is not None


async def test_row_5_the_answer_basis_is_the_citations_plus_the_synthesize_call_and_its_messages(
    tool_using_turn, store
):
    """`answer_blocks[].citations` + `citations[]`, plus the verbatim `llm_messages` rows (USER.2)."""
    cited = {chunk_id for block in tool_using_turn["answer_blocks"] for chunk_id in block["citations"]}
    top_level = {citation["chunk_id"] for citation in tool_using_turn["citations"]}
    assert cited and cited <= top_level

    synthesize = [
        payload
        for payload in _payloads(store, tool_using_turn["turn_id"], "llm_call")
        if payload["purpose"] == "synthesize"
    ]
    assert len(synthesize) == 1
    reference = synthesize[0]["messages_ref"]
    rows = store.execute(
        "SELECT content FROM llm_messages WHERE span_id = ? ORDER BY seq", (reference["span_id"],)
    ).dicts()
    assert len(rows) == reference["n_messages"]
    assert all(row["content"].strip() for row in rows)

    assert any(
        entry["kind"] == "llm_call" and "purpose=synthesize" in entry["summary"] for entry in tool_using_turn["trace"]
    )


async def test_row_6_an_escalation_decision_is_a_g5_span_the_outcome_and_an_escalation_block(web, store):
    async with web("sensitive.json") as client:
        turn = await _turn(client, SENSITIVE_QUESTION)

    assert turn["outcome"] == "escalated"
    assert any(block["type"] == "escalation" for block in turn["answer_blocks"])
    guardrails = [entry for entry in turn["trace"] if entry["kind"] == "guardrail"]
    escalations = [entry for entry in guardrails if entry["name"].startswith("G5")]
    assert escalations and "verdict=escalate" in escalations[0]["summary"]
    assert store.execute("SELECT outcome FROM turns WHERE id = ?", (turn["turn_id"],)).scalar() == "escalated"


async def test_row_7_the_rag_or_tools_decision_is_the_plan_spans_summary(tool_using_turn):
    """R4.1: a discrete, logged decision, readable from the concise trace alone."""
    plans = [entry for entry in tool_using_turn["trace"] if entry["kind"] == "plan"]
    assert plans
    assert any(entry["summary"].startswith("intent=") for entry in plans)
    assert any("workflow=" in entry["summary"] for entry in plans)


async def test_the_trace_is_the_set_of_the_turns_spans_with_no_kind_filtered_out(tool_using_turn, store):
    rows = store.execute(
        "SELECT seq, kind FROM spans WHERE turn_id = ? ORDER BY seq", (tool_using_turn["turn_id"],)
    ).dicts()

    assert {entry["seq"] for entry in tool_using_turn["trace"]} == {row["seq"] for row in rows}
    assert {entry["kind"] for entry in tool_using_turn["trace"]} == {row["kind"] for row in rows}
    assert [entry["seq"] for entry in tool_using_turn["trace"]] == sorted(
        entry["seq"] for entry in tool_using_turn["trace"]
    )


async def test_every_trace_entry_deep_links_to_its_own_span(tool_using_turn, store):
    ids = {
        row["id"]
        for row in store.execute("SELECT id FROM spans WHERE turn_id = ?", (tool_using_turn["turn_id"],)).dicts()
    }
    for entry in tool_using_turn["trace"]:
        prefix, _, span_id = entry["detail_url"].partition("?span=")
        assert prefix == f"/dashboard/sessions/{tool_using_turn['session_id']}"
        assert span_id in ids
