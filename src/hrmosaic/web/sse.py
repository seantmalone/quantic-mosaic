"""`GET /chat/stream?turn_id=…` — the live rail, and the answer as it is written (spec §11.3).

The rail is the point and always was: it makes the *agentic layer* visible on camera, which is what
DEMO.6 asks for. W2-E added the other half — the answer arrives under it while the model is still
writing, block by block — after the measured baseline showed a p50 turn taking 13.7 s and showing
nothing at all until the end of it (§1.4's reversed non-goal).

**Exactly one span listener.** `web/main.py`'s lifespan registers `broker.publish_span` with
`core.trace.register_span_listener()` once, and this module fans each event out to whichever
subscribers asked for that `turn_id`. A raising subscriber affects neither persistence nor its
peers: `core/trace.py` already swallows a listener exception, and the fan-out below never blocks —
a subscriber whose queue is full loses the event rather than stalling the turn that produced it.
Streamed answer blocks come through a **second registry** (`register_delta_listener`) because a
delta is not a span and is never persisted; it is still one listener per event family.

**Five event types.** `turn_started` and `turn_completed` are published by the `POST /chat` and
`POST /chat/confirm` handlers, which are the only code that knows a turn is about to begin or has
just ended. `step_started` and `span` are the two phases of one span event — the first narrates a
step in plain language while it runs (`web/narration.py`), the second replaces that line with the
record's own once it closes, and the pair is joined by `span_id`. `answer_delta` carries one
**complete** answer block, provisionally: the finished answer hard-replaces whatever was shown.

**The rail is an enhancement, never a dependency.** A browser that subscribes late, or whose
connection drops, renders `trace[]` from the POST response instead — every event published here is
a projection of a span that was persisted anyway.

**Shutdown.** A long-lived SSE response would otherwise hold uvicorn's graceful shutdown open, so
the lifespan calls `close()`, which pushes a sentinel into every open queue and lets each generator
return. That is the same problem `sse_starlette` solves with its process-global `AppStatus`
latch — handled here without the latch, because a process-global flag that one stopped server sets
for every other stream in the process is exactly the surprise P5 recorded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

from hrmosaic.agent.orchestrator import preview_value, summarise_span
from hrmosaic.core.trace import AnswerDeltaEvent, SpanEvent
from hrmosaic.web import narration

logger = logging.getLogger(__name__)

#: A comment line every 15 s keeps proxies from closing an idle connection (§11.3).
HEARTBEAT_S = 15.0

#: How long a stream waits for its turn to finish before giving up. The agent's own wall clock is
#: `AGENT_WALL_CLOCK_S` (90 s); this is that plus room for the confirmation card's own turn.
STREAM_MAX_S = 300.0

#: Per-subscriber buffer. Deep enough for a whole turn's spans, bounded so a browser that stopped
#: reading costs memory once rather than forever.
QUEUE_MAX = 512

#: Pushed by `close()`; a generator that receives it returns.
_SENTINEL = object()


def format_event(event: str, data: dict[str, Any]) -> str:
    """One SSE frame. `data` is always one line of JSON, so no client needs multi-line parsing."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def span_event_data(event: SpanEvent) -> dict[str, Any]:
    """The `span` frame of §11.3 — the same one-line summary `trace[]` carries, plus its label.

    `summarise_span` and `preview_value` are the projection's own helpers rather than a second
    implementation: the live rail and the concise trace describe a span identically, or the panel
    the rail collapses into would disagree with itself halfway through a demo.

    `span_id` and `label` are what let the closed line **replace** the in-progress one instead of
    appearing under it: the same friendly sentence leads, and today's technical detail follows it.
    """
    frame: dict[str, Any] = {
        "seq": event.seq,
        "span_id": event.span_id,
        "kind": event.kind,
        "name": event.name,
        "status": event.status,
        "duration_ms": event.duration_ms,
        "label": narration.label_for(event.kind, event.name, event.payload),
        "summary": summarise_span(event.kind, event.name, event.payload),
    }
    if event.kind == "tool_call":
        frame["args_preview"] = preview_value(event.payload.get("arguments") or {})
        frame["result_preview"] = preview_value(event.payload.get("result_json") or "")
    return frame


def step_started_data(event: SpanEvent) -> dict[str, Any]:
    """The `step_started` frame — what the assistant is about to do, in a sentence.

    Deliberately thin. The event's `payload` is the caller's `detail` (a purpose, a tool's
    arguments) and stays server-side: only the label `web/narration.py` derives from it goes on the
    wire, and a label carries no argument value and no employee data.
    """
    return {
        "span_id": event.span_id,
        "kind": event.kind,
        "name": event.name,
        "label": narration.label_for(event.kind, event.name, event.payload),
        "started_at": event.started_at,
    }


def answer_delta_data(event: AnswerDeltaEvent) -> dict[str, Any]:
    """One complete answer block. `type` is what the page's mirror of `render_answer()` reads."""
    return {
        "index": event.index,
        "type": event.type,
        "text": event.text,
        "citations": list(event.citations),
    }


class SpanBroker:
    """One process-wide fan-out from the trace listener to the open `/chat/stream` responses."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Any]]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False

    # -- lifecycle ---------------------------------------------------------------------
    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the serving loop, so a span closed on a worker thread still reaches it."""
        self._loop = loop
        self._closed = False

    def close(self) -> None:
        """Release every open stream — the lifespan's shutdown step."""
        self._closed = True
        with self._lock:
            queues = [queue for group in self._subscribers.values() for queue in group]
            self._subscribers.clear()
        for queue in queues:
            self._offer(queue, _SENTINEL)

    # -- subscription ------------------------------------------------------------------
    def subscribe(self, turn_id: str) -> asyncio.Queue[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=QUEUE_MAX)
        with self._lock:
            self._subscribers.setdefault(turn_id, []).append(queue)
        return queue

    def unsubscribe(self, turn_id: str, queue: asyncio.Queue[Any]) -> None:
        with self._lock:
            group = self._subscribers.get(turn_id)
            if group is None:
                return
            if queue in group:
                group.remove(queue)
            if not group:
                self._subscribers.pop(turn_id, None)

    def subscriber_count(self, turn_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(turn_id, ()))

    # -- publication -------------------------------------------------------------------
    def publish_span(self, event: SpanEvent) -> None:
        """The **one** `core.trace` span listener (§11.3) — both phases of a span come through it."""
        if event.phase == "started":
            self.publish(event.turn_id, "step_started", step_started_data(event))
            return
        self.publish(event.turn_id, "span", span_event_data(event))

    def publish_answer_delta(self, event: AnswerDeltaEvent) -> None:
        """The one `core.trace` delta listener: one complete answer block, provisionally (W2-E)."""
        self.publish(event.turn_id, "answer_delta", answer_delta_data(event))

    def publish(self, turn_id: str, event: str, data: dict[str, Any]) -> None:
        """Queue one frame for every subscriber of `turn_id`. Never blocks, never raises."""
        if self._closed:
            return
        message = format_event(event, data)
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._deliver, turn_id, message)
        except RuntimeError:  # the loop shut down between the check and the call
            logger.debug("dropped a %s frame for turn %s: the loop is gone", event, turn_id)

    def _deliver(self, turn_id: str, message: str) -> None:
        with self._lock:
            queues = list(self._subscribers.get(turn_id, ()))
        for queue in queues:
            self._offer(queue, message)

    @staticmethod
    def _offer(queue: asyncio.Queue[Any], item: Any) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:  # a browser that stopped reading loses frames, not the turn
            logger.debug("an SSE subscriber queue is full; dropping one frame")

    # -- the response body -------------------------------------------------------------
    async def stream(self, turn_id: str) -> AsyncIterator[str]:
        """The generator `GET /chat/stream` returns. Ends on `turn_completed`, or on shutdown."""
        queue = self.subscribe(turn_id)
        deadline = asyncio.get_running_loop().time() + STREAM_MAX_S
        try:
            yield ": subscribed\n\n"
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=min(HEARTBEAT_S, remaining))
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is _SENTINEL:
                    return
                yield item
                if item.startswith("event: turn_completed"):
                    return
        finally:
            self.unsubscribe(turn_id, queue)


#: The process-wide broker. `web/main.py` binds it to the serving loop and registers it once.
broker = SpanBroker()


__all__ = [
    "HEARTBEAT_S",
    "STREAM_MAX_S",
    "SpanBroker",
    "answer_delta_data",
    "broker",
    "format_event",
    "span_event_data",
    "step_started_data",
]
