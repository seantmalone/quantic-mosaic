"""`GET /chat/stream?turn_id=…` — the live span rail, and its fallback (spec §11.3).

Two paths, and §11.3 asks for both:

* **live** — the browser subscribes **before** the POST, and every closed span arrives as its own
  `span` frame between `turn_started` and `turn_completed`;
* **fallback** — the browser subscribed late or the connection dropped, and the UI renders
  `trace[]` from the POST response instead. The rail is an enhancement, never a dependency.

Spans rather than tokens: on 0.1 CPU token streaming buys cosmetics, while a span rail makes the
agentic layer visible on camera, which is what DEMO.6 asks for.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from hrmosaic.core.trace import SpanEvent
from hrmosaic.web import sse

pytestmark = pytest.mark.anyio

QUESTION = "How much PTO do full-time employees accrue each month?"
BERLIN_QUESTION = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"
TURN_ID = "4a71c0de" * 4


def _frames(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into `(event, data)` pairs, ignoring comments and heartbeats."""
    parsed = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if not lines:
            continue
        event = next((line.removeprefix("event: ") for line in lines if line.startswith("event: ")), "message")
        data = next((line.removeprefix("data: ") for line in lines if line.startswith("data: ")), "{}")
        parsed.append((event, json.loads(data)))
    return parsed


async def test_the_live_path_delivers_turn_started_every_span_and_turn_completed(web, store):
    async with web("rag_only.json") as client:
        collected: list[str] = []

        async def subscribe() -> None:
            async with client.stream("GET", "/chat/stream", params={"turn_id": TURN_ID}) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                async for chunk in response.aiter_text():
                    collected.append(chunk)
                    if "turn_completed" in chunk:
                        break

        listening = asyncio.create_task(subscribe())
        # Give the subscription a moment to register before the POST that fills it.
        while sse.broker.subscriber_count(TURN_ID) == 0:
            await asyncio.sleep(0.01)

        response = await client.post("/chat", json={"message": QUESTION, "turn_id": TURN_ID})
        assert response.status_code == 200, response.text
        await asyncio.wait_for(listening, timeout=30)

    frames = _frames("".join(collected))
    events = [event for event, _ in frames]
    assert events[0] == "turn_started"
    assert events[-1] == "turn_completed"
    assert events.count("span") >= 1

    started = frames[0][1]
    assert started["turn_id"] == TURN_ID and started["seq"] == 1

    seqs = [data["seq"] for event, data in frames if event == "span"]
    assert seqs == sorted(seqs), "spans arrive in `seq` order"
    persisted = [
        row["seq"] for row in store.execute("SELECT seq FROM spans WHERE turn_id = ? ORDER BY seq", (TURN_ID,)).dicts()
    ]
    assert seqs == persisted, "every closed span was published, and every published span persisted"

    completed = frames[-1][1]
    assert completed["outcome"] == "answered"
    assert completed["dashboard_url"] == response.json()["dashboard_url"]


async def test_a_span_frame_carries_the_same_summary_the_trace_does(web):
    """The rail collapses into the trace panel under the finished answer; they must agree (§11.3)."""
    async with web("demo_task_1.json") as client:
        collected: list[str] = []

        async def subscribe() -> None:
            async with client.stream("GET", "/chat/stream", params={"turn_id": TURN_ID}) as response:
                async for chunk in response.aiter_text():
                    collected.append(chunk)
                    if "turn_completed" in chunk:
                        break

        listening = asyncio.create_task(subscribe())
        while sse.broker.subscriber_count(TURN_ID) == 0:
            await asyncio.sleep(0.01)
        body = (
            await client.post(
                "/chat",
                json={"message": BERLIN_QUESTION, "turn_id": TURN_ID},
            )
        ).json()
        await asyncio.wait_for(listening, timeout=60)

    streamed = {data["seq"]: data for event, data in _frames("".join(collected)) if event == "span"}
    for entry in body["trace"]:
        frame = streamed.get(entry["seq"])
        assert frame is not None, f"span {entry['seq']} never reached the rail"
        assert (frame["kind"], frame["name"], frame["summary"]) == (entry["kind"], entry["name"], entry["summary"])
        if entry["kind"] == "tool_call":
            assert frame["args_preview"] == entry["args_preview"]


async def test_the_fallback_path_is_the_trace_in_the_post_response(web):
    """No subscriber at all: the turn is unaffected and the UI has everything it needs."""
    async with web("rag_only.json") as client:
        response = await client.post("/chat", json={"message": QUESTION})

    assert sse.broker.subscriber_count(response.json()["turn_id"]) == 0
    assert response.status_code == 200
    assert response.json()["trace"], "the rail is an enhancement, never a dependency"


async def test_a_late_subscriber_misses_the_earlier_spans_and_nothing_else(web):
    """Subscribing after the turn closed yields a heartbeat and no history — by design."""
    async with web("rag_only.json") as client:
        body = (await client.post("/chat", json={"message": QUESTION})).json()

        collected: list[str] = []
        async with client.stream("GET", "/chat/stream", params={"turn_id": body["turn_id"]}) as response:
            assert response.status_code == 200
            async for chunk in response.aiter_text():
                collected.append(chunk)
                break

    assert _frames("".join(collected)) == [], "no replay; the POST response carries the whole trace"
    assert body["trace"]


async def test_a_raising_subscriber_affects_neither_persistence_nor_its_peers(store, writer):
    """§11.3, and the same promise `core/trace.py` makes to any listener."""
    from hrmosaic.core.models import PlanPayload
    from hrmosaic.core.trace import SessionSpec

    broker = sse.SpanBroker()
    broker.bind(asyncio.get_running_loop())
    queue = broker.subscribe("t-1")

    def explode(event: SpanEvent) -> None:
        raise RuntimeError("a dead SSE client")

    from hrmosaic.core import trace as trace_module

    unregister_bad = trace_module.register_span_listener(explode)
    unregister_broker = trace_module.register_span_listener(broker.publish_span)
    try:
        turn = writer.start_turn(SessionSpec(), user_message="hello", turn_id="t-1")
        turn.add_span("plan", "router", PlanPayload(intent="policy_qa"))
        turn.close(outcome="answered")
        await asyncio.sleep(0)
    finally:
        unregister_bad()
        unregister_broker()

    assert queue.qsize() == 1, "the peer still got its frame"
    assert store.execute("SELECT COUNT(*) AS n FROM spans WHERE turn_id = 't-1'").scalar() == 1
