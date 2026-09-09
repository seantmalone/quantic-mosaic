"""`tools/call` over both transports (spec §16.4, R8.3, R5.2).

Both halves of R5.2, on stdio **and** on the mounted HTTP loopback:

* a structured-data tool — `check_pto_balance("E1042")` returns `remaining_days == 13.5` stated
  against `as_of == "2026-09-01"`, the snapshot, not the wall clock;
* a RAG tool — `search_policy_documents` returns a non-empty `hits[]` whose `chunk_id`s all resolve
  in the committed index.

Both result paths of §8.2 step 5 are checked: `structured_content` and the
`json.loads(content[0].text)` fallback must agree, because the spec's probe found `structured_content`
absent over stdio on an earlier SDK and a client that trusted one path would break silently.

The last test is the standing acceptance criterion from P4 on: the nested `retrieval` span the tool
returned under `_trace` is persisted **through `core/trace.py`** — the only writer — and comes back
out of the store with the expected kind and payload shape.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.core import corpusread
from hrmosaic.core.models import RetrievalPayload, SpanPayloadEnvelope
from hrmosaic.core.trace import SessionSpec
from tests.integration.conftest import BASE_META

pytestmark = pytest.mark.anyio


def read_both_ways(result) -> dict:
    """`structured_content` and the text fallback must be the same object (§8.2 step 5)."""
    from_text = json.loads(result.content[0].text)
    assert result.structured_content == from_text
    return from_text


async def test_check_pto_balance_answers_from_the_snapshot(open_session):
    async with open_session() as session:
        result = await session.call_tool("check_pto_balance", {"employee_id": "E1042"}, meta=BASE_META)
    body = read_both_ways(result)
    assert result.is_error is not True
    assert body["remaining_days"] == 13.5
    assert body["as_of"] == "2026-09-01"
    assert body["accrual_rate_days_per_month"] == 1.5
    assert body["accrual_fact_key"] == "pto.accrual.ft_3y_plus"
    # The identity of §8.4 tool 6, recomputed from the fields the tool itself returned.
    assert body["remaining_days"] == pytest.approx(
        body["accrued_ytd"] - body["used_ytd"] - body["pending_days"] + body["carryover_unexpired"]
    )


async def test_an_unknown_employee_is_a_successful_not_found(open_session):
    async with open_session() as session:
        result = await session.call_tool("check_pto_balance", {"employee_id": "E1999"}, meta=BASE_META)
    body = read_both_ways(result)
    assert result.is_error is not True, "a domain 'not found' is a successful result (§8.3)"
    assert body["code"] == "EMPLOYEE_NOT_FOUND"
    assert body["hint"] == "Employee ids look like E1042."


async def test_search_hits_all_resolve_in_the_committed_index(open_session):
    async with open_session() as session:
        result = await session.call_tool(
            "search_policy_documents",
            {"query": "working from another country for more than 30 days"},
            meta=BASE_META,
        )
    body = read_both_ways(result)
    assert body["hits"], "the query must retrieve something from the real corpus"
    for hit in body["hits"]:
        assert corpusread.get_chunk(hit["chunk_id"]) is not None, hit["chunk_id"]
    assert body["k_source"] == "default"
    assert body["strategy"] == "hybrid_rrf"
    assert body["index_version"]


async def test_the_actor_is_echoed_for_the_audit_trail(open_session):
    async with open_session() as session:
        explicit = await session.call_tool("check_pto_balance", {"employee_id": "E1042"}, meta=BASE_META)
        anonymous = await session.call_tool("check_pto_balance", {"employee_id": "E1042"})
    assert read_both_ways(explicit)["_trace"]["actor"] == {"employee_id": "E1042", "source": "explicit"}
    assert read_both_ways(anonymous)["_trace"]["actor"] == {"employee_id": "E1042", "source": "default"}


async def test_k_override_beats_a_model_supplied_k(open_session):
    meta = {**BASE_META, "mosaic/retrieval": {"strategy": "hybrid_rrf", "k_override": 2}}
    async with open_session() as session:
        overridden = await session.call_tool(
            "search_policy_documents", {"query": "pto accrual rate", "k": 7}, meta=meta
        )
        model_chosen = await session.call_tool(
            "search_policy_documents", {"query": "pto accrual rate", "k": 7}, meta=BASE_META
        )
    override_body = read_both_ways(overridden)
    model_body = read_both_ways(model_chosen)
    assert (override_body["k_effective"], override_body["k_source"]) == (2, "override")
    assert len(override_body["hits"]) <= 2
    assert (model_body["k_effective"], model_body["k_source"]) == (7, "model")


async def test_an_unrecognised_strategy_is_rejected_at_the_tool_boundary(open_session):
    meta = {**BASE_META, "mosaic/retrieval": {"strategy": "hybrid", "k_override": None}}
    async with open_session() as session:
        result = await session.call_tool("search_policy_documents", {"query": "pto accrual"}, meta=meta)
    body = read_both_ways(result)
    assert result.is_error is True
    assert body["code"] == "INVALID_ARGUMENTS"
    assert body["fields"] == ["_meta.mosaic/retrieval.strategy"]


async def test_a_schema_violation_is_an_is_error_result(open_session):
    async with open_session() as session:
        result = await session.call_tool("search_policy_documents", {"query": "no"}, meta=BASE_META)
    assert result.is_error is True
    assert "search_policy_documents" in result.content[0].text


async def test_the_returned_retrieval_span_persists_through_the_one_trace_writer(open_session, writer):
    """The standing acceptance criterion: the expected span, kind and payload shape, persisted."""
    async with open_session() as session:
        result = await session.call_tool(
            "search_policy_documents", {"query": "remote work eligibility"}, meta=BASE_META
        )
    envelope = read_both_ways(result)["_trace"]
    assert len(envelope["spans"]) == 1
    nested = envelope["spans"][0]
    assert nested["kind"] == "retrieval"
    # The payload parses back into the §10.2 discriminated union — no parallel shape.
    parsed = SpanPayloadEnvelope(payload=nested["payload"]).payload
    assert isinstance(parsed, RetrievalPayload)

    turn = writer.start_turn(SessionSpec(client_label="api"), user_message="remote work eligibility")
    turn.add_span(
        nested["kind"],
        nested["name"],
        parsed,
        span_id=nested["span_id"],
        parent_span_id="a" * 16,
        started_at=nested["started_at"],
        ended_at=nested["ended_at"],
    )
    turn.close(outcome="answered", final_answer="ok")

    row = writer.store.execute(
        "SELECT kind, name, parent_span_id, payload_json FROM spans WHERE id = ?", (nested["span_id"],)
    ).one()
    assert row is not None, "the lifted span must be persisted by core/trace.py, not by mcpserver/"
    assert (row["kind"], row["name"]) == ("retrieval", "search_policy_documents")
    assert row["parent_span_id"] == "a" * 16
    persisted = json.loads(row["payload_json"])
    assert persisted["k_source"] == "default"
    assert persisted["chunks"] and persisted["index_version"]
    assert writer.store.execute("SELECT retrievals FROM turns WHERE id = ?", (turn.turn_id,)).scalar() == 1
