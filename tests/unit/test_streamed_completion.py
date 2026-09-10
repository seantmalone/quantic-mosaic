"""W2-E — the answer streams, and streaming changes nothing about the answer.

`AnthropicAdapter.invoke` calls `client.messages.stream` rather than `messages.create`, so every
call is now a streamed round trip. Two things have to be true for that to be free:

* **parity.** The `Completion` a streamed round trip produces is the one the JSON round trip
  produced from the same response — text, tool-call arguments, `stop_reason`, every token counter,
  the cost estimate and `structured_output_mode`. The plan names the single way this could go
  wrong: a hand-rolled `input_json_delta` accumulator that mis-assembles a `tool_use` block and
  therefore moves a `ToolSelection`. The adapter uses `stream.get_final_message()` instead, and the
  control below is the **same recorded body** decoded through `messages.create`.
* **the measurement.** `ttfb_ms` was equal to `duration_ms` on all 185 recorded spans, because a
  non-streaming call has nothing else to report. Streamed, it is the first delta; not streamed —
  the failover adapter, a call that answered with tool calls and no prose — it is the round trip,
  and `streamed` is the flag §11.6 page 5 needs in order not to mix the two definitions in one
  column.

The wire fixture serves both shapes from one declared response (`tests/unit/conftest.py`), which is
what makes "identical on one recorded response" a claim about the adapter rather than about two
fixtures that happen to agree.
"""

from __future__ import annotations

import asyncio
import json

from hrmosaic.core.llm.anthropic import AnthropicAdapter
from hrmosaic.core.llm.base import (
    Completion,
    CompletionRequest,
    Deadline,
    Message,
    round_trip_timeout,
)
from hrmosaic.core.llm.openai_compat import OpenAICompatAdapter
from hrmosaic.core.llm.stub import DELTA_CHARS, StubAdapter
from hrmosaic.core.models import AnswerSchema, parse_payload
from hrmosaic.core.trace import SessionSpec

SCRIPT = "tests/fixtures/llm_scripts/adapter_smoke.json"

MESSAGES = [
    Message(role="system", content="You are the Mosaic HR Copilot."),
    Message(role="user", content="How much PTO do I accrue?"),
]

#: One recorded response that exercises every field parity is claimed over: prose, and a `tool_use`
#: block whose arguments only survive if the `input_json_delta` fragments are reassembled correctly.
RECORDED_CONTENT = [
    {"type": "text", "text": "Let me look that up in the PTO policy before I answer."},
    {
        "type": "tool_use",
        "id": "toolu_01parity",
        "name": "search_policy_documents",
        "input": {"query": "paid time off accrual full-time", "k": 5, "strategy": "hybrid_rrf"},
    },
]


class NonStreamingAnthropic(AnthropicAdapter):
    """The `messages.create` round trip this adapter made before W2-E — the parity control."""

    async def invoke(self, request: CompletionRequest, deadline: Deadline | None = None) -> Completion:
        kwargs = self.request_kwargs(
            request.messages,
            tools=request.tools,
            response_schema=request.response_schema,
            purpose=request.purpose,
            temperature=request.temperature,
        )
        kwargs["timeout"] = round_trip_timeout(deadline, what="anthropic")
        response = await asyncio.to_thread(lambda: self.client().messages.create(**kwargs))
        return self._to_completion(response, structured="output_config" in kwargs)


#: What a streamed call is *allowed* to report differently: the two fields W2-E adds, plus the span
#: id, which is minted per call and says nothing about the response.
STREAMING_ONLY_FIELDS = {"ttfb_ms", "streamed", "span_id"}


def test_stream_completion_parity(wire, anthropic_response, writer):
    """The golden parity test the plan asks for, over one recorded response."""
    recorded = anthropic_response(
        content=RECORDED_CONTENT, stop_reason="tool_use", input_tokens=1_204, output_tokens=88
    )

    streamed_client, _ = wire([recorded])
    created_client, _ = wire([recorded])
    turn = writer.start_turn(SessionSpec(), user_message="How much PTO do I accrue?")

    streamed = asyncio.run(
        AnthropicAdapter(api_key="k", http_client=streamed_client).complete(
            MESSAGES, response_schema=AnswerSchema, purpose="synthesize", turn=turn
        )
    )
    created = asyncio.run(
        NonStreamingAnthropic(api_key="k", http_client=created_client).complete(
            MESSAGES, response_schema=AnswerSchema, purpose="synthesize", turn=turn
        )
    )
    turn.close(outcome="answered", stop_reason="answered")

    assert streamed.text == created.text == "Let me look that up in the PTO policy before I answer."
    assert [(call.id, call.name, call.args) for call in streamed.tool_calls] == [
        ("toolu_01parity", "search_policy_documents", RECORDED_CONTENT[1]["input"])
    ]
    assert streamed.model_dump(exclude=STREAMING_ONLY_FIELDS) == created.model_dump(exclude=STREAMING_ONLY_FIELDS)
    # Named one by one as well, so a future field added to `Completion` cannot quietly widen or
    # narrow what this test is asserting.
    for field in (
        "finish_reason",
        "prompt_tokens",
        "completion_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "cost_usd_estimate",
        "structured_output_mode",
    ):
        assert getattr(streamed, field) == getattr(created, field), field
    assert streamed.finish_reason == "tool_use"
    assert streamed.cost_usd_estimate > 0.0
    assert streamed.structured_output_mode == "output_config_json_schema"


def test_the_streamed_call_delivers_every_delta_in_order(wire, anthropic_response):
    """`on_delta` sees the text, in order, and never a fragment of a `tool_use` argument."""
    recorded = anthropic_response(content=RECORDED_CONTENT, stop_reason="tool_use")
    client, _ = wire([recorded])
    deltas: list[str] = []

    completion = asyncio.run(
        AnthropicAdapter(api_key="k", http_client=client).complete(MESSAGES, on_delta=deltas.append)
    )

    assert len(deltas) > 1, "the fixture delivers the block in several deltas, not one"
    assert "".join(deltas) == completion.text
    assert not any("hybrid_rrf" in delta for delta in deltas), "tool arguments are not answer text"


def test_a_delta_sink_that_raises_costs_the_turn_nothing(wire, anthropic_response):
    """A browser that went away must not take the answer with it."""
    recorded = anthropic_response(content=[{"type": "text", "text": "PTO accrues monthly."}])
    client, _ = wire([recorded])

    def explode(_: str) -> None:
        raise RuntimeError("the subscriber is gone")

    completion = asyncio.run(AnthropicAdapter(api_key="k", http_client=client).complete(MESSAGES, on_delta=explode))

    assert completion.text == "PTO accrues monthly."
    assert completion.streamed is True


def test_the_span_of_a_streamed_call_reports_a_first_delta_ttfb(wire, anthropic_response, writer, store):
    recorded = anthropic_response(content=[{"type": "text", "text": "PTO accrues monthly on a service scale."}])
    client, _ = wire([recorded])
    turn = writer.start_turn(SessionSpec(), user_message="How much PTO do I accrue?")

    completion = asyncio.run(AnthropicAdapter(api_key="k", http_client=client).complete(MESSAGES, turn=turn))
    turn.close(outcome="answered", stop_reason="answered")

    payload = parse_payload(json.loads(_llm_span(store, turn.turn_id)["payload_json"]))
    assert payload.streamed is True
    assert payload.ttfb_ms is not None
    assert payload.ttfb_ms == completion.ttfb_ms


def test_a_response_with_no_prose_falls_back_to_the_round_trip(wire, anthropic_response, writer, store):
    """`ttfb_ms = first_delta_ms or round_trip_ms` — a tool-use-only step has no first token."""
    recorded = anthropic_response(content=[RECORDED_CONTENT[1]], stop_reason="tool_use")
    client, _ = wire([recorded])
    turn = writer.start_turn(SessionSpec(), user_message="Do I have PTO left?")

    asyncio.run(AnthropicAdapter(api_key="k", http_client=client).complete(MESSAGES, turn=turn))
    turn.close(outcome="answered", stop_reason="answered")

    payload = parse_payload(json.loads(_llm_span(store, turn.turn_id)["payload_json"]))
    assert payload.ttfb_ms is not None, "`test_llm_span_emission` asserts non-null on every span"
    assert payload.streamed is True, "the round trip streamed; the response simply carried no prose"


def test_the_failover_adapter_is_not_streamed_and_still_reports_a_ttfb(wire, openai_response, writer, store):
    """`OpenAICompatAdapter` may stay non-streaming; its spans say so (§11.6 page 5)."""
    client, _ = wire([openai_response(content="The fallback answered.")])
    turn = writer.start_turn(SessionSpec(), user_message="How much PTO do I accrue?")

    asyncio.run(
        OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=client).complete(
            MESSAGES, turn=turn
        )
    )
    turn.close(outcome="answered", stop_reason="answered")

    payload = parse_payload(json.loads(_llm_span(store, turn.turn_id)["payload_json"]))
    assert payload.streamed is False
    assert payload.ttfb_ms is not None


def test_the_stub_replays_its_recording_as_deltas(writer):
    """§16.2's keystone streams too, so the key-free path exercises the same seam a live one does."""
    adapter = StubAdapter(script_path=SCRIPT)
    deltas: list[str] = []
    turn = writer.start_turn(SessionSpec(), user_message="How much PTO do I accrue?")

    completion = asyncio.run(adapter.complete(MESSAGES, purpose="route", turn=turn, on_delta=deltas.append))
    turn.close(outcome="answered", stop_reason="answered")

    assert completion.text
    assert "".join(deltas) == completion.text
    assert max(len(delta) for delta in deltas) <= DELTA_CHARS
    assert completion.streamed is True and completion.ttfb_ms == 0


def test_the_stub_is_not_streamed_when_nobody_is_listening(writer):
    adapter = StubAdapter(script_path=SCRIPT)
    turn = writer.start_turn(SessionSpec(), user_message="How much PTO do I accrue?")

    completion = asyncio.run(adapter.complete(MESSAGES, purpose="route", turn=turn))
    turn.close(outcome="answered", stop_reason="answered")

    assert completion.streamed is False


def _llm_span(store, turn_id: str) -> dict:
    return store.execute(
        "SELECT * FROM spans WHERE turn_id = ? AND kind = 'llm_call' ORDER BY seq", (turn_id,)
    ).dicts()[0]
