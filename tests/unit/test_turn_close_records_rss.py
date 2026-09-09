"""`core/procstat.py` reads live process memory, and the closing UPDATE samples it (§10.1, §10.3).

`turns.rss_mb_at_end` is the series dashboard page 11 plots, so the closing UPDATE — not a
separate writer, not a later job — is what records it.
"""

from __future__ import annotations

import json
import subprocess
import sys

from hrmosaic.core import procstat
from hrmosaic.core.models import LlmCallPayload, MessagesRef, RetrievalPayload, RetrievedChunk
from hrmosaic.core.trace import SessionSpec

CHUNK = RetrievedChunk(
    chunk_id="c_1b7e",
    doc_id="pto-and-leave-policy",
    doc_title="PTO and Leave Policy",
    heading_path="Accrual > Full-time",
    section="Full-time",
    rank=1,
    dense_score=0.71,
    snippet="Full-time employees accrue 1.5 days per month.",
)


def test_rss_reader_returns_a_live_positive_reading():
    value = procstat.rss_mb()
    assert isinstance(value, float)
    assert 1.0 < value < 100_000.0
    assert procstat.rss_peak_mb() >= value * 0.5


def test_snapshot_names_its_source_and_uptime():
    snapshot = procstat.snapshot()
    assert set(snapshot) == {"rss_mb", "rss_peak_mb", "source", "platform", "uptime_ms", "pid"}
    assert snapshot["source"] in {"/proc/self/status", "resource.getrusage"}
    assert snapshot["uptime_ms"] >= 0


def test_the_module_entrypoint_prints_json():
    """`python -m hrmosaic.core.procstat` is the P1 definition-of-done command."""
    completed = subprocess.run(
        [sys.executable, "-m", "hrmosaic.core.procstat"], capture_output=True, text=True, check=True
    )
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["rss_mb"] > 1.0


def test_turn_close_records_rss_and_the_rollups(writer, store):
    turn = writer.start_turn(SessionSpec(employee_id="E1042"), user_message="How much PTO do I have?")
    with turn.span("retrieval", "hybrid_rrf") as span:
        span.set_payload(
            RetrievalPayload(
                query="pto accrual",
                k=5,
                k_source="default",
                strategy="hybrid_rrf",
                chunks=[CHUNK],
                max_dense_score=0.71,
            )
        )
    with turn.span("llm_call", "anthropic:claude-haiku-4-5") as span:
        span.set_payload(
            LlmCallPayload(
                provider="anthropic",
                model="claude-haiku-4-5",
                purpose="synthesize",
                prompt_tokens=7412,
                completion_tokens=883,
                total_tokens=8295,
                messages_ref=MessagesRef(span_id=span.id, n_messages=2, total_chars=120),
            )
        )
        span.add_message("system", "You are Mosaic HR Copilot.")
        span.add_message("user", "How much PTO do I have?")
    turn.close(outcome="answered", stop_reason="complete", final_answer="You have 13.5 days.")

    row = store.execute("SELECT * FROM turns WHERE id = ?", (turn.turn_id,)).one()
    assert row["rss_mb_at_end"] is not None
    assert row["rss_mb_at_end"] > 1.0
    assert row["outcome"] == "answered"
    assert row["stop_reason"] == "complete"
    assert row["final_answer"] == "You have 13.5 days."
    assert row["ended_at"] is not None and row["duration_ms"] is not None
    assert (row["llm_calls"], row["tool_calls"], row["retrievals"], row["guardrail_hits"]) == (1, 0, 1, 0)
    assert (row["total_tokens_in"], row["total_tokens_out"]) == (7412, 883)
    assert (row["provider"], row["model"]) == ("anthropic", "claude-haiku-4-5")
    # store_ms is the measured store time of this turn, rounded to ms: on a local SQLite file
    # the start batch is well under a millisecond, so the honest assertion is "recorded".
    assert row["llm_ms"] >= 0 and row["retrieval_ms"] >= 0 and row["store_ms"] is not None
    assert row["process_uptime_ms"] > 0

    messages = store.execute("SELECT role, content FROM llm_messages ORDER BY seq").dicts()
    assert [message["role"] for message in messages] == ["system", "user"]
