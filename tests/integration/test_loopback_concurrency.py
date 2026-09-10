"""Two simultaneous loopback `tools/call`s, and the page that is waiting on them (spec §2.1).

The deployed topology is **one process**: uvicorn serves `/chat` and, at `/mcp-server/mcp`, the very
tools the agent calls over loopback HTTP. That means a request handler awaits a request the same
event loop has to serve — so **every tool handler is `async def` and every CPU-bound call inside one
goes through `asyncio.to_thread`**. A single synchronous `.embed()` on the loop would self-deadlock
the loopback call (§2.1's second rule), and a single-flight lock would serialise every visitor.

P5 built the mount and P5's own tests drove it one call at a time; the concurrent case is P8's,
because P8 is the phase whose `/health` has to keep answering while a turn is in flight.
"""

from __future__ import annotations

import asyncio

import pytest

from hrmosaic.agent.client import McpClient
from hrmosaic.core import trace as trace_module
from hrmosaic.core.trace import SessionSpec

pytestmark = pytest.mark.anyio

QUERIES = (
    "paid time off accrual and carryover",
    "international remote work approval and tax review",
)


async def _one_call(url: str, query: str) -> tuple[str, bool]:
    """One client, one turn, one `tools/call` — the shape a real turn makes, minus the model."""
    client = McpClient(transport="http", url=url)
    buffer = trace_module.start_turn(SessionSpec(client_label="api"), user_message=query)
    try:
        result = await client.call_tool(
            buffer, name="search_policy_documents", arguments={"query": query, "k": 3}, employee_id="E1042"
        )
        return result.tool_name, result.is_error
    finally:
        buffer.close(outcome="answered")
        await client.aclose()


async def test_two_simultaneous_tools_calls_both_complete(web, store):
    async with web() as client:
        url = str(client.base_url) + "/mcp-server/mcp"
        results = await asyncio.gather(*(_one_call(url, query) for query in QUERIES))

    assert results == [("search_policy_documents", False)] * len(QUERIES)
    retrievals = store.execute("SELECT COUNT(*) AS n FROM spans WHERE kind = 'retrieval'").scalar()
    assert retrievals >= len(QUERIES), "both calls really searched; neither was served a cached stub"


async def test_the_app_still_answers_while_two_loopback_calls_are_in_flight(web):
    """The embedding runs in a worker thread, so the loop that serves `/health` is never blocked."""
    async with web() as client:
        url = str(client.base_url) + "/mcp-server/mcp"
        calls = asyncio.gather(*(_one_call(url, query) for query in QUERIES))
        health = await asyncio.wait_for(client.get("/health"), timeout=30)
        results = await asyncio.wait_for(calls, timeout=60)

    assert health.status_code == 200
    assert all(not is_error for _, is_error in results)


async def test_two_concurrent_chat_turns_are_isolated(web, store):
    """Two visitors, two turns, two sets of spans — and no cross-talk in the shared trace store."""
    async with web("rag_only.json") as client:
        # Out-of-corpus questions are refused by the deterministic pre-check, so the two turns
        # cannot race for entries in the one shared stub script; what is under test here is the
        # store and the span buffers, which are shared whatever the model does.
        first, second = await asyncio.gather(
            client.post("/chat", json={"message": "What is the weather in Berlin?"}),
            client.post("/chat", json={"message": "What is the stock price today?"}),
        )

    assert (first.status_code, second.status_code) == (200, 200)
    turns = {first.json()["turn_id"], second.json()["turn_id"]}
    assert len(turns) == 2
    for turn_id in turns:
        rows = store.execute("SELECT COUNT(*) AS n FROM spans WHERE turn_id = ?", (turn_id,)).scalar()
        assert rows >= 1
    assert first.json()["session_id"] != second.json()["session_id"]
