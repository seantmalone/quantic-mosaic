"""A process that dies mid-turn still leaves a readable audit record (spec §10.3).

The **store-level** form, which is P1's: the SIGTERM/atexit path calls `flush_open_turns()`, and
a hard kill that ran no handler at all is repaired by the boot-time `sweep_stale_turns()`.
(The subprocess form — a real uvicorn killed mid-request — is P8's.)
"""

from __future__ import annotations

import signal

from hrmosaic.core import trace as trace_module
from hrmosaic.core.db import now_micros
from hrmosaic.core.models import PlanPayload
from hrmosaic.core.trace import SessionSpec

STALE_AFTER_S = 300


def _open_turn_with_a_span(writer):
    turn = writer.start_turn(SessionSpec(), user_message="Can I work from Berlin?")
    with turn.span("plan", "router") as span:
        span.set_payload(PlanPayload(intent="workflow", workflow="remote_work_eligibility"))
    return turn


def test_flush_open_turns_closes_the_turn_as_an_error_and_keeps_its_spans(writer, store):
    turn = _open_turn_with_a_span(writer)
    assert store.execute("SELECT COUNT(*) AS n FROM spans").scalar() == 0

    flushed = trace_module.flush_open_turns()

    assert flushed == 1
    row = store.execute("SELECT outcome, stop_reason, ended_at, duration_ms FROM turns").one()
    assert (row["outcome"], row["stop_reason"]) == ("error", "error")
    assert row["ended_at"] is not None and row["duration_ms"] is not None
    assert store.execute("SELECT COUNT(*) AS n FROM spans WHERE turn_id = ?", (turn.turn_id,)).scalar() == 1


def test_flush_open_turns_is_idempotent_and_ignores_closed_turns(writer, store):
    turn = _open_turn_with_a_span(writer)
    turn.close(outcome="answered")

    assert trace_module.flush_open_turns() == 0
    assert store.execute("SELECT outcome FROM turns").scalar() == "answered"


def test_the_sigterm_handler_flushes_and_chains_to_the_previous_handler(writer, store):
    """A hard SIGTERM arrives; the buffer is flushed before the process leaves."""
    chained = []
    previous = signal.signal(signal.SIGTERM, lambda signum, frame: chained.append(signum))
    try:
        trace_module.install_shutdown_handlers()
        _open_turn_with_a_span(writer)
        handler = signal.getsignal(signal.SIGTERM)
        handler(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, previous)
        trace_module.reset_shutdown_handlers()

    assert chained == [signal.SIGTERM]
    assert store.execute("SELECT outcome, stop_reason FROM turns").one() == {
        "outcome": "error",
        "stop_reason": "error",
    }
    assert store.execute("SELECT COUNT(*) AS n FROM spans").scalar() == 1


def test_sweep_stale_turns_closes_what_a_hard_kill_left_open(writer, store):
    """No handler ran at all: the startup sweep closes anything open for more than five minutes."""
    stale = _open_turn_with_a_span(writer)
    fresh = _open_turn_with_a_span(writer)
    trace_module.set_writer(None)  # the process died; nothing is buffered any more

    store.execute(
        "UPDATE turns SET started_at = ? WHERE id = ?",
        (now_micros() - (STALE_AFTER_S + 60) * 1_000_000, stale.turn_id),
    )

    swept = trace_module.sweep_stale_turns(store=store)

    assert swept == 1
    stale_row = store.execute("SELECT outcome, stop_reason, ended_at FROM turns WHERE id = ?", (stale.turn_id,)).one()
    assert (stale_row["outcome"], stale_row["stop_reason"]) == ("error", "error")
    assert stale_row["ended_at"] is not None
    fresh_row = store.execute("SELECT outcome, ended_at FROM turns WHERE id = ?", (fresh.turn_id,)).one()
    assert fresh_row == {"outcome": None, "ended_at": None}


def test_a_flushed_turn_keeps_its_llm_messages(writer, store):
    turn = writer.start_turn(SessionSpec(), user_message="What is the PTO carryover cap?")
    with turn.span("llm_call", "anthropic:claude-haiku-4-5") as span:
        span.set_payload(
            {
                "kind": "llm_call",
                "provider": "anthropic",
                "model": "claude-haiku-4-5",
                "purpose": "route",
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "total_tokens": 15,
            }
        )
        span.add_message("user", "What is the PTO carryover cap?")

    trace_module.flush_open_turns()

    assert store.execute("SELECT COUNT(*) AS n FROM llm_messages").scalar() == 1
    assert store.execute("SELECT total_tokens_in, total_tokens_out FROM turns").one() == {
        "total_tokens_in": 12,
        "total_tokens_out": 3,
    }
