"""`register_span_listener()` — the SSE hook of §10.3 step 2.

Every closed span reaches every listener immediately, in `seq` order, and a listener that raises
affects neither persistence nor its peers: the live rail is a convenience, the store is the record.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.core.models import GuardrailPayload, PlanPayload, ToolCallPayload
from hrmosaic.core.trace import SessionSpec, register_span_listener


@pytest.fixture
def turn(writer):
    return writer.start_turn(SessionSpec(), user_message="How much PTO do I have?")


def _emit_three_spans(turn) -> None:
    with turn.span("plan", "router") as span:
        span.set_payload(PlanPayload(intent="workflow", workflow="pto_request", selected_tools=["check_pto_balance"]))
    with turn.span("tool_call", "check_pto_balance") as span:
        span.set_payload(
            ToolCallPayload(
                server="hr-mcp",
                transport="http",
                tool_name="check_pto_balance",
                arguments={"employee_id": "E1042"},
                result_json=json.dumps({"balance_days": 13.5}),
            )
        )
    with turn.span("guardrail", "G2_citation_resolvability") as span:
        span.set_payload(GuardrailPayload(rule_id="G2", rule_name="citation_resolvability", verdict="allow"))


def test_every_closed_span_is_published_in_seq_order(turn):
    seen = []
    register_span_listener(seen.append)
    _emit_three_spans(turn)

    assert [event.seq for event in seen] == [1, 2, 3]
    assert [event.kind for event in seen] == ["plan", "tool_call", "guardrail"]
    assert [event.turn_id for event in seen] == [turn.turn_id] * 3
    assert all(event.status == "ok" for event in seen)
    assert seen[1].payload["arguments"] == {"employee_id": "E1042"}


def test_spans_are_published_before_the_end_of_turn_flush(turn, store):
    seen = []
    register_span_listener(seen.append)
    _emit_three_spans(turn)

    assert len(seen) == 3
    assert store.execute("SELECT COUNT(*) AS n FROM spans").scalar() == 0  # still buffered (§10.3)
    turn.close(outcome="answered")
    assert store.execute("SELECT COUNT(*) AS n FROM spans").scalar() == 3


def test_a_raising_listener_affects_neither_persistence_nor_its_peers(turn, store):
    before, after = [], []

    def exploding(event):
        raise RuntimeError("the SSE client went away")

    register_span_listener(before.append)
    register_span_listener(exploding)
    register_span_listener(after.append)

    _emit_three_spans(turn)
    turn.close(outcome="answered")

    assert [event.seq for event in before] == [1, 2, 3]
    assert [event.seq for event in after] == [1, 2, 3]
    assert store.execute("SELECT COUNT(*) AS n FROM spans").scalar() == 3


def test_unregistering_stops_delivery(turn):
    seen = []
    unregister = register_span_listener(seen.append)
    with turn.span("plan", "router") as span:
        span.set_payload(PlanPayload(intent="rag_only"))
    unregister()
    with turn.span("plan", "router") as span:
        span.set_payload(PlanPayload(intent="rag_only"))

    assert [event.seq for event in seen] == [1]


def test_published_payloads_are_already_redacted(turn):
    seen = []
    register_span_listener(seen.append)
    with turn.span("tool_call", "send_hr_email") as span:
        span.set_payload(
            ToolCallPayload(
                server="hr-mcp",
                transport="http",
                tool_name="send_hr_email",
                arguments={"authorization": "Bearer abc123", "to": "people-ops@mosaicrobotics.example"},
            )
        )
    assert seen[0].payload["arguments"]["authorization"] == "[REDACTED]"
    assert seen[0].payload["arguments"]["to"] == "people-ops@mosaicrobotics.example"


def test_a_raising_span_body_is_recorded_as_an_error_span(turn, store):
    """An exception inside a span body becomes an `error` span naming the component it broke."""
    seen = []
    register_span_listener(seen.append)
    with pytest.raises(ZeroDivisionError):
        with turn.span("retrieval", "hybrid_rrf"):
            raise ZeroDivisionError("boom")
    turn.close(outcome="error", stop_reason="error")

    assert seen[0].status == "error"
    assert seen[0].kind == "error"
    assert seen[0].payload["component"] == "retrieval"
    row = store.execute("SELECT kind, name, status, error_message, payload_json FROM spans").one()
    assert (row["kind"], row["name"], row["status"]) == ("error", "hybrid_rrf", "error")
    assert "boom" in row["error_message"]
    assert json.loads(row["payload_json"])["error_kind"] == "ZeroDivisionError"
