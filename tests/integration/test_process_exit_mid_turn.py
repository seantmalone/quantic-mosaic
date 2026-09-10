"""A process that dies mid-turn still leaves a readable audit record (spec §10.3).

The **store-level** form, which is P1's: the SIGTERM/atexit path calls `flush_open_turns()`, and
a hard kill that ran no handler at all is repaired by the boot-time `sweep_stale_turns()`.
(The subprocess form — a real uvicorn killed mid-request — is P8's.)
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from hrmosaic.core import trace as trace_module
from hrmosaic.core.db import SqliteStore, now_micros
from hrmosaic.core.db import migrate as migrate_store
from hrmosaic.core.models import PlanPayload
from hrmosaic.core.trace import SessionSpec
from tests.conftest import LLM_SCRIPTS, free_port

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


# --------------------------------------------------------------------------------------
# The subprocess form (P8): a real uvicorn, with a real turn left open (§10.3)
# --------------------------------------------------------------------------------------
#
# The store-level tests above call the handler directly. These serve the whole app in its own OS
# process and kill it — SIGTERM for the graceful path, SIGKILL for the one no handler can run.
# Only a subprocess can show that the lifespan installed the handler **on the main thread**, where
# `signal.signal` is legal: off the main thread it would log a warning and leave nothing but the
# `atexit` hook, which a SIGKILL never reaches either.
#
# The turn is left open **deterministically**, by `uvicorn_with_open_turn.py`: it serves the real
# `hrmosaic.web.main:app` and then opens one turn on the process-wide writer the lifespan installed,
# never closing it. No endpoint is involved, so there is no timing assumption — and, importantly,
# no reliance on a request failing: `web/api.py`'s `UnhandledErrorMiddleware` now closes the turn
# and answers 200 on any unmodelled exception, exactly so that nothing is ever left open this way.

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = Path(__file__).resolve().parent / "uvicorn_with_open_turn.py"
BOOT_TIMEOUT_S = 60
OPEN_TURN_TIMEOUT_S = 30
EXIT_TIMEOUT_S = 20


def _environment(port: int, db_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "APP_ENV": "local",
        # Explicitly empty, so a developer's own `.env` cannot turn the access gate on under test.
        "APP_ACCESS_TOKEN": "",
        "PORT": str(port),
        "TRACE_DB_PATH": str(db_path),
        "LLM_PROVIDER": "stub",
        "LLM_STUB_SCRIPT": str(LLM_SCRIPTS / "rag_only.json"),
        "EMBED_WARMUP": "0",
    }


def _serve(port: int, db_path: Path) -> subprocess.Popen:
    process = subprocess.Popen(
        [sys.executable, str(SERVER), str(port)],
        cwd=str(REPO_ROOT),
        env=_environment(port, db_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0).status_code == 200:
                return process
        except httpx.HTTPError:
            time.sleep(0.1)
    process.kill()
    raise AssertionError("the subprocess never became healthy")


def _wait_for_the_open_turn(db_path: Path) -> str:
    """The helper opens its turn just after the socket is listening; wait for the row to appear."""
    deadline = time.monotonic() + OPEN_TURN_TIMEOUT_S
    while time.monotonic() < deadline:
        rows = _rows(db_path, "SELECT id FROM turns WHERE ended_at IS NULL")
        if len(rows) == 1:
            return str(rows[0]["id"])
        time.sleep(0.05)
    raise AssertionError("the subprocess never left a turn open")


def _wait_for_the_boot_sweep(db_path: Path, turn_id: str) -> dict:
    """`sweep_stale_turns()` runs on a worker thread at boot; `/health` can answer before it lands."""
    deadline = time.monotonic() + OPEN_TURN_TIMEOUT_S
    while time.monotonic() < deadline:
        row = _rows(db_path, "SELECT outcome, stop_reason, ended_at FROM turns WHERE id = ?", (turn_id,))[0]
        if row["ended_at"] is not None:
            return row
        time.sleep(0.05)
    raise AssertionError("the next boot's sweep never closed the turn")


def _rows(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    store = SqliteStore(db_path)
    try:
        return store.execute(sql, params).dicts()
    finally:
        store.close()


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "subprocess-traces.sqlite"
    store = SqliteStore(path)
    migrate_store(store)
    store.close()
    return path


@pytest.mark.anyio
async def test_a_sigterm_flushes_the_turn_a_real_uvicorn_left_open(db_path):
    port = free_port()
    process = _serve(port, db_path)
    try:
        turn_id = await asyncio.to_thread(_wait_for_the_open_turn, db_path)
        process.send_signal(signal.SIGTERM)
        await asyncio.to_thread(process.wait, EXIT_TIMEOUT_S)
    finally:
        if process.poll() is None:  # pragma: no cover - the handler exits on its own
            process.kill()
            process.wait(EXIT_TIMEOUT_S)

    row = _rows(db_path, "SELECT outcome, stop_reason, ended_at, error_kind FROM turns WHERE id = ?", (turn_id,))[0]
    assert (row["outcome"], row["stop_reason"]) == ("error", "error")
    assert row["error_kind"] == "process_exit"
    assert row["ended_at"] is not None

    spans = _rows(db_path, "SELECT kind FROM spans WHERE turn_id = ?", (turn_id,))
    assert [span["kind"] for span in spans] == ["plan"], "the buffer was flushed, not lost"


@pytest.mark.anyio
async def test_a_hard_kill_is_repaired_by_the_next_boots_sweep(db_path):
    """No handler runs at all; the startup sweep closes anything open for more than five minutes."""
    port = free_port()
    process = _serve(port, db_path)
    try:
        turn_id = await asyncio.to_thread(_wait_for_the_open_turn, db_path)
        process.kill()
        await asyncio.to_thread(process.wait, EXIT_TIMEOUT_S)
    finally:
        if process.poll() is None:  # pragma: no cover
            process.kill()

    assert _rows(db_path, "SELECT ended_at FROM turns WHERE id = ?", (turn_id,))[0]["ended_at"] is None

    store = SqliteStore(db_path)
    try:
        store.execute(
            "UPDATE turns SET started_at = ? WHERE id = ?",
            (now_micros() - (STALE_AFTER_S + 60) * 1_000_000, turn_id),
        )
    finally:
        store.close()

    reborn = _serve(free_port(), db_path)
    try:
        row = await asyncio.to_thread(_wait_for_the_boot_sweep, db_path, turn_id)
    finally:
        reborn.terminate()
        reborn.wait(EXIT_TIMEOUT_S)

    assert (row["outcome"], row["stop_reason"]) == ("error", "error")
    assert row["ended_at"] is not None
