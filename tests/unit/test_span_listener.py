"""`register_span_listener()` — the SSE hook of §10.3 step 2, and its two phases (§11.3).

Every closed span reaches every listener immediately, in `seq` order, and a listener that raises
affects neither persistence nor its peers: the live rail is a convenience, the store is the record.

Since P16 the **same** seam also carries a `started` event, published the moment a step opens, so
`/chat/stream` can narrate the step while it runs and then replace that line with the closed span's
own. One listener, two phases, joined by `span_id` — a second publication path is what §11.3
forbids. Every assertion about the record below therefore reads `closed(...)`, and the phase itself
is asserted on its own.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.core.models import GuardrailPayload, PlanPayload, ToolCallPayload
from hrmosaic.core.trace import SessionSpec, register_span_listener


@pytest.fixture
def turn(writer):
    return writer.start_turn(SessionSpec(), user_message="How much PTO do I have?")


def closed(events):
    """The events that describe the record: a `started` one is timed and sequenced by nothing yet."""
    return [event for event in events if event.phase == "closed"]


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

    events = closed(seen)
    assert [event.seq for event in events] == [1, 2, 3]
    assert [event.kind for event in events] == ["plan", "tool_call", "guardrail"]
    assert [event.turn_id for event in events] == [turn.turn_id] * 3
    assert all(event.status == "ok" for event in events)
    assert events[1].payload["arguments"] == {"employee_id": "E1042"}


def test_a_step_is_announced_before_it_closes_and_the_two_share_a_span_id(turn):
    """§11.3's `step_started` / `span` pair: same seam, same id, opened strictly first."""
    seen = []
    register_span_listener(seen.append)
    _emit_three_spans(turn)

    assert [event.phase for event in seen] == ["started", "closed"] * 3
    assert [event.span_id for event in seen[0:2]] == [seen[0].span_id] * 2
    opened = seen[0]
    assert (opened.kind, opened.name) == ("plan", "router")
    # Nothing is timed or sequenced when a step opens; the record's fields arrive with the close.
    assert (opened.seq, opened.duration_ms, opened.payload) == (0, 0, {})
    assert closed(seen)[0].seq == 1


def test_open_span_returns_the_id_the_close_must_carry(turn):
    """A caller that does not pass it on leaves a rail line nothing ever replaces."""
    seen = []
    register_span_listener(seen.append)
    span_id = turn.open_span("tool_call", "check_pto_balance", detail={"arguments": {"employee_id": "E1042"}})
    turn.add_span(
        "tool_call",
        "check_pto_balance",
        ToolCallPayload(server="hr-mcp", transport="http", tool_name="check_pto_balance"),
        span_id=span_id,
    )

    assert [event.span_id for event in seen] == [span_id, span_id]
    # `detail` is the narration's input, not the payload: it is never written and never persisted.
    assert seen[0].payload == {"arguments": {"employee_id": "E1042"}}
    assert closed(seen)[0].payload["tool_name"] == "check_pto_balance"


def test_spans_are_published_before_the_end_of_turn_flush(turn, store):
    seen = []
    register_span_listener(seen.append)
    _emit_three_spans(turn)

    assert len(closed(seen)) == 3
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

    assert [event.seq for event in closed(before)] == [1, 2, 3]
    assert [event.seq for event in closed(after)] == [1, 2, 3]
    assert store.execute("SELECT COUNT(*) AS n FROM spans").scalar() == 3


def test_unregistering_stops_delivery(turn):
    seen = []
    unregister = register_span_listener(seen.append)
    with turn.span("plan", "router") as span:
        span.set_payload(PlanPayload(intent="rag_only"))
    unregister()
    with turn.span("plan", "router") as span:
        span.set_payload(PlanPayload(intent="rag_only"))

    assert [event.seq for event in closed(seen)] == [1]


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
    recorded = closed(seen)[0]
    assert recorded.payload["arguments"]["authorization"] == "[REDACTED]"
    assert recorded.payload["arguments"]["to"] == "people-ops@mosaicrobotics.example"


def test_an_announced_step_is_redacted_too(turn):
    """What a listener is handed is what a listener could publish (§10.4)."""
    seen = []
    register_span_listener(seen.append)
    turn.open_span(
        "tool_call",
        "create_mock_hr_ticket",
        detail={"arguments": {"employee_id": "E1042", "confirmation_token": "cf_secret_value"}},
    )

    assert seen[0].phase == "started"
    assert seen[0].payload["arguments"]["confirmation_token"] == "[REDACTED]"
    assert seen[0].payload["arguments"]["employee_id"] == "E1042"


def test_a_raising_span_body_is_recorded_as_an_error_span(turn, store):
    """An exception inside a span body becomes an `error` span naming the component it broke."""
    seen = []
    register_span_listener(seen.append)
    with pytest.raises(ZeroDivisionError):
        with turn.span("retrieval", "hybrid_rrf"):
            raise ZeroDivisionError("boom")
    turn.close(outcome="error", stop_reason="error")

    recorded = closed(seen)[0]
    assert recorded.status == "error"
    assert recorded.kind == "error"
    assert recorded.payload["component"] == "retrieval"
    row = store.execute("SELECT kind, name, status, error_message, payload_json FROM spans").one()
    assert (row["kind"], row["name"], row["status"]) == ("error", "hybrid_rrf", "error")
    assert "boom" in row["error_message"]
    assert json.loads(row["payload_json"])["error_kind"] == "ZeroDivisionError"


def test_reopening_a_turn_continues_the_span_sequence_and_the_live_rail(writer, store):
    """§10.3 step 4 — `/chat/confirm` resumes a parked turn; the rail and `seq` carry on."""
    turn = writer.start_turn(SessionSpec(), user_message="Open the PTO request for me.")
    _emit_three_spans(turn)
    turn.close(outcome="awaiting_confirmation", stop_reason="awaiting_confirmation")

    seen = []
    register_span_listener(seen.append)
    resumed = writer.reopen_turn(turn.turn_id, awaiting_ms=25_000)

    assert resumed.turn_id == turn.turn_id
    assert store.execute("SELECT outcome, ended_at FROM turns").one() == {"outcome": None, "ended_at": None}

    with resumed.span("tool_call", "create_mock_hr_ticket") as span:
        span.set_payload(
            ToolCallPayload(
                server="hr-mcp",
                transport="http",
                tool_name="create_mock_hr_ticket",
                arguments={"employee_id": "E1042", "confirmation_token": "cf_secret"},
                result_json=json.dumps({"ticket_id": "MOCK-HR-000123"}),
            )
        )
    resumed.close(outcome="answered", stop_reason="complete")

    assert [event.seq for event in closed(seen)] == [4]
    assert closed(seen)[0].payload["arguments"]["confirmation_token"] == "[REDACTED]"

    spans = store.execute("SELECT seq, kind FROM spans ORDER BY seq").dicts()
    assert [row["seq"] for row in spans] == [1, 2, 3, 4]
    row = store.execute("SELECT * FROM turns").one()
    assert (row["resumed_count"], row["awaiting_ms"]) == (1, 25_000)
    assert row["outcome"] == "answered"
    assert row["tool_calls"] == 2  # one from each half of the turn
    assert row["duration_ms"] >= 0  # the parked time is excluded from every latency statistic
