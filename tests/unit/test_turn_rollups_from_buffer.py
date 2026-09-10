"""`/chat`'s `usage` and `timings` come from the closed buffer, not from a re-SELECT (W1-C(c)).

`TurnBuffer.close()` computes `ended_at`, `duration_ms` and the ten rollup columns, writes them in
one batch and then had them read straight back out of `turns` — a second round trip, on the request
path, for numbers the process had just produced. It now publishes them: `close_totals` is the very
mapping the `TURN_CLOSE` statement is built from, so the response and the row **cannot** disagree.

That identity is the whole safety argument (§11.1's "provably the same rows"), so it is what the
first test asserts — column by column, against the row the store actually holds.
"""

from __future__ import annotations

import time

from hrmosaic.agent.orchestrator import Orchestrator, _Turn
from hrmosaic.core.models import LlmCallPayload, RetrievalPayload, ToolCallPayload
from hrmosaic.core.trace import SessionSpec
from hrmosaic.web.api import ChatRequest

PUBLISHED = (
    "total_tokens_in",
    "total_tokens_out",
    "llm_calls",
    "tool_calls",
    "retrievals",
    "duration_ms",
    "llm_ms",
    "retrieval_ms",
    "tool_ms",
    "store_ms",
)


def _busy_turn(writer):
    turn = writer.start_turn(SessionSpec(), user_message="how much PTO do I have?")
    turn.add_span(
        "llm_call",
        "anthropic:claude-haiku-4-5",
        LlmCallPayload(
            provider="anthropic", model="claude-haiku-4-5", purpose="act", prompt_tokens=120, completion_tokens=40
        ),
    )
    turn.add_span("retrieval", "search", RetrievalPayload(query="pto", k=5, k_source="default", strategy="hybrid_rrf"))
    turn.add_span(
        "tool_call",
        "check_pto_balance",
        ToolCallPayload(tool_name="check_pto_balance", server="hr-mosaic", transport="http"),
    )
    turn.close(outcome="answered", stop_reason="answered")
    return turn


def test_the_published_totals_are_the_row_the_close_wrote(writer, store):
    turn = _busy_turn(writer)
    row = store.execute(f"SELECT {', '.join(PUBLISHED)}, ended_at FROM turns WHERE id = ?", (turn.turn_id,)).one()

    assert turn.close_totals is not None
    for column in PUBLISHED:
        assert turn.close_totals[column] == row[column], column
    assert turn.close_totals["ended_at"] == row["ended_at"]
    assert turn.close_totals["llm_calls"] == 1
    assert turn.close_totals["total_tokens_in"] == 120


def test_the_response_is_built_without_going_back_to_the_store(writer, store):
    """Corrupt the row and the answer is unchanged: nothing on this path reads it any more."""
    buffer = _busy_turn(writer)
    turn = _Turn(
        request=ChatRequest(message="how much PTO do I have?", employee_id="E1042"),
        buffer=buffer,
        catalog=None,
        began=time.perf_counter(),
    )
    expected_usage, expected_timings = Orchestrator()._rollups(turn)

    store.execute(
        "UPDATE turns SET llm_calls = 99, tool_calls = 99, retrievals = 99, total_tokens_in = 99, "
        "total_tokens_out = 99, duration_ms = 99999 WHERE id = ?",
        (buffer.turn_id,),
    )
    usage, timings = Orchestrator()._rollups(turn)

    assert usage == expected_usage and timings == expected_timings
    assert usage.llm_calls == 1 and usage.tool_calls == 1 and usage.retrievals == 1
    assert usage.prompt_tokens == 120 and usage.completion_tokens == 40
    assert timings.total_ms >= 0
