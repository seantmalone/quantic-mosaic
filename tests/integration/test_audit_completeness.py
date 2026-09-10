"""USER.2's own verification: one full tool-using turn, and nothing is missing (spec §16.1).

One turn goes through `POST /chat` with the stub, and then the **store** is interrogated. If this
file passes, no rubric-named field can be missing from the audit trail: every step the agent took
has a span, every model call has its verbatim messages, every tool call has its arguments and its
output, every retrieval has its ranked chunks with scores, the turn row carries its rollups, and
the concise trace the client received is the same set of records the dashboard will render.

That last clause is the one USER.4 turns on — a second logging path would show up here as a
mismatch, not as a code review comment six phases later.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.anyio

QUESTION = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"


@pytest.fixture
async def audited(web, store):
    async with web("demo_task_1.json") as client:
        response = await client.post("/chat", json={"message": QUESTION, "client_label": "demo"})
        assert response.status_code == 200, response.text
        body = response.json()
    rows = store.execute(
        "SELECT id, seq, kind, name, status, duration_ms, payload_json FROM spans WHERE turn_id = ? ORDER BY seq",
        (body["turn_id"],),
    ).dicts()
    for row in rows:
        row["payload"] = json.loads(row.pop("payload_json"))
    yield {"body": body, "spans": rows, "store": store}


def _of(audited, kind: str) -> list[dict]:
    return [span for span in audited["spans"] if span["kind"] == kind]


async def test_exactly_one_mcp_discovery_span(audited):
    """§8.2 step 3: emitted every turn, so every session carries RUBRIC5.2's primary evidence."""
    discovery = _of(audited, "mcp_discovery")
    assert len(discovery) == 1
    payload = discovery[0]["payload"]
    assert payload["tool_count"] == 9
    assert payload["catalog_sha"]
    assert {tool["name"] for tool in payload["tools"]} >= {"search_policy_documents", "check_pto_balance"}


async def test_every_span_kind_the_turn_should_have_is_present(audited):
    kinds = {span["kind"] for span in audited["spans"]}
    assert {"mcp_discovery", "plan", "llm_call", "retrieval", "tool_call", "guardrail"} <= kinds


async def test_every_llm_call_has_its_verbatim_messages(audited):
    store = audited["store"]
    calls = _of(audited, "llm_call")
    assert calls

    for span in calls:
        reference = span["payload"]["messages_ref"]
        assert reference is not None, f"{span['name']} recorded no messages_ref"
        rows = store.execute(
            "SELECT role, content FROM llm_messages WHERE span_id = ? ORDER BY seq", (reference["span_id"],)
        ).dicts()
        assert len(rows) == reference["n_messages"]
        assert all(row["content"].strip() for row in rows)
        assert sum(len(row["content"]) for row in rows) == reference["total_chars"]
        assert span["payload"]["purpose"] in {"route", "act", "synthesize", "repair"}


async def test_every_tool_call_carries_its_arguments_and_its_result(audited):
    calls = _of(audited, "tool_call")
    assert len(calls) >= 4

    for span in calls:
        payload = span["payload"]
        assert payload["tool_name"] == span["name"]
        assert isinstance(payload["arguments"], dict) and payload["arguments"]
        assert payload["result_json"], "R4.3 asks for the outputs, not only the calls"
        assert payload["duration_ms"] is not None
        assert payload["actor_employee_id"], "§8.7: who asked for this"


async def test_every_retrieval_carries_a_ranked_chunk_set_with_scores(audited):
    retrievals = _of(audited, "retrieval")
    assert retrievals

    for span in retrievals:
        payload = span["payload"]
        chunks = payload["chunks"]
        assert chunks
        assert [chunk["rank"] for chunk in chunks] == sorted(chunk["rank"] for chunk in chunks)
        assert all(chunk["dense_score"] > 0 for chunk in chunks)
        assert all(chunk["chunk_id"] and chunk["doc_id"] and chunk["snippet"] for chunk in chunks)
        assert payload["max_dense_score"] == max(chunk["dense_score"] for chunk in chunks)
        assert payload["k_source"] in {"model", "override", "default"}
        assert payload["strategy"] in {"hybrid_rrf", "dense_only"}


async def test_the_turn_row_carries_its_rollups_and_its_duration(audited):
    body = audited["body"]
    row = (
        audited["store"]
        .execute(
            "SELECT duration_ms, total_tokens_in, total_tokens_out, llm_calls, tool_calls, retrievals, "
            "guardrail_hits, outcome, stop_reason, intent, workflow, rss_mb_at_end, process_uptime_ms "
            "FROM turns WHERE id = ?",
            (body["turn_id"],),
        )
        .one()
    )

    assert row["duration_ms"] is not None and row["duration_ms"] >= 0
    assert row["llm_calls"] >= 2 and row["tool_calls"] >= 4 and row["retrievals"] >= 1
    assert row["outcome"] == "answered"
    assert row["intent"] and row["workflow"]
    assert row["rss_mb_at_end"] and row["rss_mb_at_end"] > 0
    assert row["process_uptime_ms"] >= 0

    assert body["usage"]["llm_calls"] == row["llm_calls"]
    assert body["usage"]["tool_calls"] == row["tool_calls"]
    assert body["timings"]["total_ms"] == row["duration_ms"]


async def test_the_concise_trace_is_the_set_of_the_turns_spans(audited):
    """USER.4: one record, projected twice — never two logging paths."""
    assert {entry["seq"] for entry in audited["body"]["trace"]} == {span["seq"] for span in audited["spans"]}
    assert len(audited["body"]["trace"]) == len(audited["spans"])


async def test_the_session_row_records_how_the_caller_was_identified(audited):
    row = (
        audited["store"]
        .execute(
            "SELECT employee_id, auth_mode, actor_role, client_label, mcp_transport, app_version, deploy_mode "
            "FROM sessions WHERE id = ?",
            (audited["body"]["session_id"],),
        )
        .one()
    )

    assert row["employee_id"] == "E1042"
    assert row["auth_mode"] == "open"
    assert row["actor_role"] == "employee"
    assert row["client_label"] == "demo"
    assert row["mcp_transport"] == "http"
    assert row["app_version"] and row["deploy_mode"] == "local"


async def test_the_final_answer_and_its_citations_are_persisted_on_the_turn(audited):
    row = (
        audited["store"]
        .execute(
            "SELECT final_answer, answer_blocks_json, citations_json FROM turns WHERE id = ?",
            (audited["body"]["turn_id"],),
        )
        .one()
    )

    assert row["final_answer"] == audited["body"]["answer"]
    blocks = json.loads(row["answer_blocks_json"])
    citations = json.loads(row["citations_json"])
    assert [block["type"] for block in blocks] == [block["type"] for block in audited["body"]["answer_blocks"]]
    assert {citation["chunk_id"] for citation in citations} == {
        citation["chunk_id"] for citation in audited["body"]["citations"]
    }
    assert all(citation["source_url"].startswith("/dashboard/corpus/") for citation in citations)
