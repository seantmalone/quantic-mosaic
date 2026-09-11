"""`GET /chat/stream?turn_id=…` — the live rail, the streamed answer, and the fallback (§11.3).

Three paths, and §11.3 asks for all of them:

* **live** — the browser subscribes **before** the POST, every step announces itself as a
  `step_started` frame and settles into its own `span` frame, between `turn_started` and
  `turn_completed`;
* **the answer as it is written** — `answer_delta` carries one **complete** block at a time,
  provisionally, and `turn_completed` hard-replaces whatever was shown (W2-E);
* **fallback** — the browser subscribed late or the connection dropped, and the UI renders
  `trace[]` from the POST response instead. The rail is an enhancement, never a dependency.

The rail is still the point of the page: it makes the *agentic layer* visible on camera, which is
what DEMO.6 asks for. The answer stream is what §1.4's reversed non-goal bought — a p50 turn takes
13.7 s and used to show nothing at all until the end of it.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from hrmosaic.core.trace import SpanEvent
from hrmosaic.web import sse
from tests.conftest import LLM_SCRIPTS

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
    assert events.count("step_started") >= 1

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


# --------------------------------------------------------------------------------------
# `step_started` — the plain-language narration of §11.3
# --------------------------------------------------------------------------------------


async def _drive(client, script_question: str, turn_id: str) -> list[tuple[str, dict]]:
    """Subscribe, POST, and return the whole frame sequence the browser saw."""
    collected: list[str] = []

    async def subscribe() -> None:
        async with client.stream("GET", "/chat/stream", params={"turn_id": turn_id}) as response:
            async for chunk in response.aiter_text():
                collected.append(chunk)
                if "turn_completed" in chunk:
                    break

    listening = asyncio.create_task(subscribe())
    while sse.broker.subscriber_count(turn_id) == 0:
        await asyncio.sleep(0.01)
    posted = await client.post("/chat", json={"message": script_question, "turn_id": turn_id})
    assert posted.status_code == 200, posted.text
    await asyncio.wait_for(listening, timeout=60)
    return _frames("".join(collected))


async def test_every_step_is_announced_before_its_span_closes(web):
    """`turn_started`, `step_started` … `span` … `turn_completed`, paired by `span_id`."""
    async with web("demo_task_1.json") as client:
        frames = await _drive(client, BERLIN_QUESTION, TURN_ID)

    events = [event for event, _ in frames]
    assert events[0] == "turn_started" and events[-1] == "turn_completed"

    order = {}
    for position, (event, data) in enumerate(frames):
        if event in {"step_started", "span"} and "span_id" in data:
            order.setdefault(data["span_id"], {})[event] = position
    announced = {span_id: positions for span_id, positions in order.items() if "step_started" in positions}
    assert announced, "at least the router, the tool calls and the synthesis announce themselves"
    for span_id, positions in announced.items():
        assert "span" in positions, f"{span_id} was announced and never closed"
        assert positions["step_started"] < positions["span"], "the narration comes first, or it is not narration"

    # Every announced step is one of the five §11.3 names, and each carries a sentence.
    kinds = {data["kind"] for event, data in frames if event == "step_started"}
    assert kinds <= {"llm_call", "tool_call", "guardrail", "confirmation"}
    assert {"llm_call", "tool_call"} <= kinds
    labels = [data["label"] for event, data in frames if event == "step_started"]
    assert all(label.endswith("…") for label in labels)
    assert "Understanding your question…" in labels and "Writing the answer…" in labels


async def test_no_step_started_label_carries_an_argument_from_the_script(web):
    """A rail line is prose for a person; it never repeats what the model asked a tool for."""
    async with web("demo_task_1.json") as client:
        frames = await _drive(client, BERLIN_QUESTION, TURN_ID)

    script = json.loads((LLM_SCRIPTS / "demo_task_1.json").read_text(encoding="utf-8"))
    values = {
        str(value)
        for entry in script["completions"]
        for call in entry.get("tool_calls") or []
        for value in (call.get("args") or {}).values()
        if isinstance(value, str | int | float) and len(str(value)) > 2
    }
    assert values, "the recording has to actually pass arguments, or this asserts nothing"

    labels = [data["label"] for event, data in frames if event == "step_started"]
    for label in labels:
        for value in values:
            assert value not in label, f"{label!r} leaked {value!r}"


async def test_a_closed_span_frame_carries_the_label_that_replaces_its_own_line(web):
    """The rail replaces the in-progress line rather than adding under it, so both carry the label."""
    async with web("rag_only.json") as client:
        frames = await _drive(client, QUESTION, TURN_ID)

    spans = [data for event, data in frames if event == "span"]
    assert spans and all(data["label"] and data["span_id"] for data in spans)
    synthesis = [data for data in spans if data["kind"] == "llm_call" and "purpose=synthesize" in data["summary"]]
    assert synthesis and synthesis[0]["label"] == "Writing the answer…"


# --------------------------------------------------------------------------------------
# `answer_delta` — the answer while it is being written (W2-E)
# --------------------------------------------------------------------------------------


async def test_the_answer_arrives_as_complete_blocks_before_the_turn_ends(web):
    async with web("rag_only.json") as client:
        frames = await _drive(client, QUESTION, TURN_ID)

    events = [event for event, _ in frames]
    deltas = [data for event, data in frames if event == "answer_delta"]
    assert deltas, "the stub streams its recorded synthesis"
    assert events.index("answer_delta") < events.index("turn_completed")
    assert [data["index"] for data in deltas] == list(range(len(deltas)))
    for data in deltas:
        assert set(data) == {"index", "type", "text", "citations"}
        assert data["type"] in {"policy_fact", "recommendation", "escalation"}
        assert data["text"], "a block is delivered whole or not at all"

    script = json.loads((LLM_SCRIPTS / "rag_only.json").read_text(encoding="utf-8"))
    synthesis = json.loads(next(e["response_text"] for e in script["completions"] if e["purpose"] == "synthesize"))
    assert [data["text"] for data in deltas] == [block["text"] for block in synthesis["blocks"]]
    # §9.7: the model's own reasoning is not something the page ever sees.
    assert all(synthesis["rationale_summary"] not in json.dumps(data) for data in deltas)


async def test_a_block_g2_strips_is_streamed_and_then_replaced_by_the_final_answer(web):
    """The provisional render is a preview, and `turn_completed` is the hard replace."""
    async with web("g2_strips_a_block.json") as client:
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
        body = (await client.post("/chat", json={"message": QUESTION, "turn_id": TURN_ID})).json()
        await asyncio.wait_for(listening, timeout=60)

    frames = _frames("".join(collected))
    deltas = [data for event, data in frames if event == "answer_delta"]
    dropped = "Unused PTO rolls over without limit under section 9 of the policy."

    assert len(deltas) == 2, "the raw synthesis had two blocks and both were streamed"
    assert dropped in [data["text"] for data in deltas], "the provisional answer showed the block"

    # G2 could not resolve its only citation, and §7.3 drops an uncited `policy_fact`.
    assert [block["text"] for block in body["answer_blocks"]] == [deltas[0]["text"]]
    assert dropped not in body["answer"], "the finished answer is the one the guardrails passed"
    assert [event for event, _ in frames][-1] == "turn_completed", "and it is what replaces the preview"


PTO_QUESTION = (
    "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
    "— and can you open the request for me?"
)


async def _collect(client, turn_id: str) -> tuple[asyncio.Task, list[str]]:
    """Subscribe to `turn_id` and read until `turn_completed`, as the page's EventSource does."""
    collected: list[str] = []

    async def subscribe() -> None:
        async with client.stream("GET", "/chat/stream", params={"turn_id": turn_id}) as response:
            assert response.status_code == 200
            async for chunk in response.aiter_text():
                collected.append(chunk)
                if "turn_completed" in chunk:
                    break

    listening = asyncio.create_task(subscribe())
    while sse.broker.subscriber_count(turn_id) == 0:
        await asyncio.sleep(0.01)
    return listening, collected


async def test_a_confirmation_gated_turn_streams_its_resumed_half_to_a_second_subscriber(web, store):
    """§10.3 step 4 — the half that performs the mock write has a rail of its own.

    `POST /chat` publishes `turn_completed` even when the outcome is `awaiting_confirmation`, which
    ends the generator server-side and closes the `EventSource` on the page. So the resumed turn is
    only visible if the client subscribes a **second** time, with the id already in the confirm
    card, before it posts `/chat/confirm` — which is what `chat.html`'s `htmx:configRequest`
    handler now does. This pins the frames that second subscription exists to receive: the same
    turn, its mock write, and the answer written after the human clicked.
    """
    async with web("demo_task_2.json") as client:
        listening, gated_chunks = await _collect(client, TURN_ID)
        proposal = await client.post("/chat", json={"message": PTO_QUESTION, "turn_id": TURN_ID})
        assert proposal.status_code == 200, proposal.text
        await asyncio.wait_for(listening, timeout=60)

        gated = _frames("".join(gated_chunks))
        assert gated[-1][0] == "turn_completed"
        assert gated[-1][1]["outcome"] == "awaiting_confirmation"
        assert sse.broker.subscriber_count(TURN_ID) == 0, "the first stream is over before the click"

        resumed_listening, resumed_chunks = await _collect(client, TURN_ID)
        confirmed = await client.post(
            "/chat/confirm",
            json={"session_id": proposal.json()["session_id"], "turn_id": TURN_ID, "decision": "confirmed"},
        )
        assert confirmed.status_code == 200, confirmed.text
        await asyncio.wait_for(resumed_listening, timeout=60)

    frames = _frames("".join(resumed_chunks))
    events = [event for event, _ in frames]

    assert events[0] == "turn_started"
    assert frames[0][1]["turn_id"] == TURN_ID
    assert frames[0][1]["seq"] == gated[0][1]["seq"], "the same turn, not a new one"
    assert "create_mock_hr_ticket" in {data.get("name") for _, data in frames if _ == "span"}
    assert events.count("answer_delta") >= 1, "the answer written after the click streams too"
    assert events[-1] == "turn_completed"
    assert frames[-1][1]["outcome"] == "answered"


async def test_a_declined_confirmation_also_streams_a_second_turn_started_and_completed(web, store):
    """Cancel republishes `turn_started`, its own `confirmation` span and `turn_completed` (§11.2)."""
    async with web("demo_task_2.json") as client:
        listening, _gated = await _collect(client, TURN_ID)
        proposal = await client.post("/chat", json={"message": PTO_QUESTION, "turn_id": TURN_ID})
        await asyncio.wait_for(listening, timeout=60)

        resumed_listening, resumed_chunks = await _collect(client, TURN_ID)
        declined = await client.post(
            "/chat/confirm",
            json={"session_id": proposal.json()["session_id"], "turn_id": TURN_ID, "decision": "declined"},
        )
        assert declined.status_code == 200, declined.text
        await asyncio.wait_for(resumed_listening, timeout=60)

    frames = _frames("".join(resumed_chunks))
    events = [event for event, _ in frames]

    assert events[0] == "turn_started" and events[-1] == "turn_completed"
    assert frames[-1][1]["outcome"] == "refused"
    assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 0


# --------------------------------------------------------------------------------------
# The broker's own promises: never block, never raise, always let go (§11.3)
# --------------------------------------------------------------------------------------
#
# Everything above drives the rail through a real browser-shaped subscription, which is the path
# that matters. The block below drives the three paths a healthy turn never takes — a browser that
# stopped reading, an idle connection, and uvicorn's graceful shutdown — because each of them is a
# promise this module makes to the *turn*: the turn must not stall, must not raise, and must not
# hold the process open (P20).


async def _read_stream(generator, limit: int) -> list[str]:
    """Read a stream generator to completion, or to `limit` frames, whichever comes first."""
    frames: list[str] = []
    async for frame in generator:
        frames.append(frame)
        if len(frames) >= limit:
            await generator.aclose()
            break
    return frames


async def test_shutdown_releases_every_open_stream():
    """The lifespan's `close()`: a long-lived SSE response must not hold graceful shutdown open."""
    broker = sse.SpanBroker()
    broker.bind(asyncio.get_running_loop())
    stream = broker.stream("t-shutdown")
    frames: list[str] = []

    async def read() -> None:
        async for frame in stream:
            frames.append(frame)

    reading = asyncio.create_task(read())
    while broker.subscriber_count("t-shutdown") == 0:
        await asyncio.sleep(0.01)
    broker.close()

    await asyncio.wait_for(reading, timeout=5)
    assert frames == [": subscribed\n\n"], "the sentinel ended the generator without emitting a frame"
    assert broker.subscriber_count("t-shutdown") == 0


async def test_a_frame_published_after_shutdown_reaches_nobody():
    broker = sse.SpanBroker()
    broker.bind(asyncio.get_running_loop())
    queue = broker.subscribe("t-closed")
    broker.close()
    while not queue.empty():  # drain the sentinel `close()` pushed
        queue.get_nowait()

    broker.publish("t-closed", "span", {"seq": 1})
    await asyncio.sleep(0)
    assert queue.empty()


async def test_unsubscribing_from_a_turn_nobody_is_watching_is_a_no_op():
    """A generator's `finally` runs after `close()` has already cleared the registry."""
    broker = sse.SpanBroker()
    queue: asyncio.Queue = asyncio.Queue()
    broker.unsubscribe("t-absent", queue)  # must not raise
    assert broker.subscriber_count("t-absent") == 0


async def test_one_subscriber_leaving_does_not_end_its_peer_s_stream():
    """Two browsers on one turn: the second tab closing must not unregister the first."""
    broker = sse.SpanBroker()
    broker.bind(asyncio.get_running_loop())
    first = broker.subscribe("t-two")
    second = broker.subscribe("t-two")

    broker.unsubscribe("t-two", second)
    assert broker.subscriber_count("t-two") == 1

    broker.unsubscribe("t-two", second)  # already gone: still not an error
    assert broker.subscriber_count("t-two") == 1

    broker.publish("t-two", "span", {"seq": 1})
    await asyncio.sleep(0)
    assert first.qsize() == 1
    broker.unsubscribe("t-two", first)
    assert broker.subscriber_count("t-two") == 0


async def test_a_frame_published_with_no_serving_loop_is_dropped_rather_than_raised():
    """`publish_span` runs on a worker thread; a broker that was never bound must not take the turn down."""
    unbound = sse.SpanBroker()
    queue = unbound.subscribe("t-unbound")
    unbound.publish("t-unbound", "span", {"seq": 1})
    assert queue.empty()

    spent = asyncio.new_event_loop()
    spent.close()
    bound_to_a_dead_loop = sse.SpanBroker()
    bound_to_a_dead_loop.bind(spent)
    bound_to_a_dead_loop.subscribe("t-dead")
    bound_to_a_dead_loop.publish("t-dead", "span", {"seq": 1})  # must not raise


async def test_a_loop_that_shuts_down_mid_publish_costs_the_frame_and_nothing_else():
    """The race the `except RuntimeError` exists for: the loop dies between the check and the call.

    It cannot be provoked with a real loop — `is_closed()` would already be true — so the stand-in
    below is a loop that reports itself open and then raises exactly what `asyncio` raises.
    """

    class ClosingLoop:
        def is_closed(self) -> bool:
            return False

        def call_soon_threadsafe(self, *args, **kwargs):
            raise RuntimeError("Event loop is closed")

    broker = sse.SpanBroker()
    broker.bind(ClosingLoop())  # type: ignore[arg-type]
    queue = broker.subscribe("t-racing")
    broker.publish("t-racing", "span", {"seq": 1})  # must not raise
    assert queue.empty()


async def test_a_subscriber_that_stopped_reading_loses_frames_not_the_turn():
    """A browser that stopped draining costs memory once (`QUEUE_MAX`) and never stalls the agent."""
    broker = sse.SpanBroker()
    broker.bind(asyncio.get_running_loop())
    queue = broker.subscribe("t-full")
    for seq in range(sse.QUEUE_MAX):
        broker.publish("t-full", "span", {"seq": seq})
    await asyncio.sleep(0)
    assert queue.qsize() == sse.QUEUE_MAX

    broker.publish("t-full", "span", {"seq": sse.QUEUE_MAX})  # must not raise, must not block
    await asyncio.sleep(0)
    assert queue.qsize() == sse.QUEUE_MAX


async def test_an_idle_stream_sends_a_keep_alive_rather_than_letting_a_proxy_close_it(monkeypatch):
    """§11.3's comment line every `HEARTBEAT_S`, shortened here so the test costs milliseconds."""
    monkeypatch.setattr(sse, "HEARTBEAT_S", 0.02)
    broker = sse.SpanBroker()
    broker.bind(asyncio.get_running_loop())

    frames = await asyncio.wait_for(_read_stream(broker.stream("t-idle"), limit=3), timeout=5)
    assert frames == [": subscribed\n\n", ": keep-alive\n\n", ": keep-alive\n\n"]
    assert broker.subscriber_count("t-idle") == 0, "the generator's finally still unsubscribed"


async def test_a_stream_gives_up_at_its_deadline_rather_than_living_forever(monkeypatch):
    """`STREAM_MAX_S` bounds a subscription whose turn never completes (P19's unbounded-id fix)."""
    monkeypatch.setattr(sse, "STREAM_MAX_S", 0.0)
    broker = sse.SpanBroker()
    broker.bind(asyncio.get_running_loop())

    frames = [frame async for frame in broker.stream("t-expired")]
    assert frames == [": subscribed\n\n"]
    assert broker.subscriber_count("t-expired") == 0
