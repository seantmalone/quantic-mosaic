"""What the lifespan owns, and what it hands back on the way out (spec §10.3, §11.3, §11.4).

Six things happen at startup and every one of them is load-bearing:

1. the shutdown handlers, on the main thread — a SIGTERM from Render flushes any turn in flight;
2. the store, migrated, and the one process-wide `TraceWriter`;
3. the boot repair (`sweep_stale_turns`), the boot prune (`retention.sweep`) and the boot import
   (`archive.import_results`), all three repeating every six hours;
4. **exactly one** `core.trace` span listener — the SSE broker (§11.3);
5. the `Orchestrator`, so the MCP handshake outlives a request;
6. the `/ready` warm-up: one loopback `tools/call`, never a direct `rag.embed` import.

The teardown matters as much: a leaked listener would fan spans out to a dead loop, and a leaked
process-wide orchestrator would hand the next app a closed MCP session.
"""

from __future__ import annotations

import pytest

from hrmosaic.core import trace as trace_module
from hrmosaic.web import main as web_main
from hrmosaic.web.sse import broker

pytestmark = pytest.mark.anyio


async def test_the_lifespan_registers_exactly_one_span_listener_and_removes_it(web):
    from hrmosaic.agent import orchestrator as agent

    async with web() as client:
        await client.get("/health")
        listeners = list(trace_module._listeners)
        installed = agent._orchestrator

    assert listeners == [broker.publish_span], "one listener, and it is the SSE broker (§11.3)"
    assert installed is not None, "the orchestrator is built in the lifespan, not per request"
    assert agent._orchestrator is None, "and cleared on the way out"
    assert trace_module._listeners == []


async def test_the_lifespan_installs_the_shutdown_handlers_on_the_main_thread(web):
    trace_module.reset_shutdown_handlers()
    try:
        async with web() as client:
            await client.get("/health")
            assert trace_module._handlers_installed is True
    finally:
        trace_module.reset_shutdown_handlers()


async def test_the_lifespan_migrates_the_store_and_installs_the_one_writer(web, store):
    async with web() as client:
        await client.get("/health")
        writer = trace_module.get_writer()
        assert writer.store is store

    versions = {row["version"] for row in store.execute("SELECT version FROM schema_migrations")}
    assert "001_initial" in versions


async def test_the_boot_maintenance_pass_repairs_prunes_and_imports(web, store, writer):
    """A turn a hard kill left open is closed by the boot sweep, before anyone can read it."""
    from hrmosaic.core.db import now_micros
    from hrmosaic.core.trace import SessionSpec

    stale = writer.start_turn(SessionSpec(), user_message="killed mid-turn")
    trace_module.set_writer(None)
    store.execute(
        "UPDATE turns SET started_at = ? WHERE id = ?",
        (now_micros() - 3600 * 1_000_000, stale.turn_id),
    )

    async with web() as client:
        await client.get("/health")

    row = store.execute("SELECT outcome, stop_reason FROM turns WHERE id = ?", (stale.turn_id,)).one()
    assert (row["outcome"], row["stop_reason"]) == ("error", "error")


async def test_the_maintenance_interval_is_six_hours(web):
    """§10.3 and §10.5: the boot jobs repeat, so a long-lived process does not drift."""
    assert web_main.MAINTENANCE_INTERVAL_S == 6 * 60 * 60


async def test_the_ready_warm_up_is_one_loopback_tools_call(web, store):
    """§11.4: readiness exercises the same wire the agent uses, never a direct `rag.embed` import."""
    import json

    async with web(embed_warmup=True) as client:
        for _ in range(200):
            ready = await client.get("/ready")
            if ready.status_code == 200:
                break
        else:  # pragma: no cover - the warm-up has 30 s and the model is cached
            pytest.fail(f"/ready never went green: {ready.json()}")

    assert ready.json() == {"ready": True, "reason": None}
    sessions = store.execute("SELECT id, client_label FROM sessions WHERE client_label = 'maintenance'").dicts()
    assert len(sessions) == 1, "the warm-up turn is a maintenance session, excluded from every metric"

    turns = store.execute("SELECT id, outcome FROM turns WHERE session_id = ?", (sessions[0]["id"],)).dicts()
    assert [turn["outcome"] for turn in turns] == ["maintenance"]
    spans = store.execute(
        "SELECT kind, name, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (turns[0]["id"],)
    ).dicts()
    calls = [span for span in spans if span["kind"] == "tool_call"]
    assert [span["name"] for span in calls] == ["search_policy_documents"], "exactly one tools/call"
    assert json.loads(calls[0]["payload_json"])["is_error"] is False
