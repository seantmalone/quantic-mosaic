"""Exactly one `llm_call` span, with its `llm_messages` rows, per logical call (spec §9.8, §10.2).

The standing acceptance criterion from P4 on is *the expected spans were persisted, with the
expected kinds and payload shapes*, and USER.4 forbids a second logging path. So the span is
emitted **inside** the adapter: a caller cannot make a provider call that leaves no record, and a
call that fails over to `LLM_FALLBACK_*` still produces one span — flagged `provider_failover`, not
two spans that would double-count the turn's rollups.

The audit invariant `len(llm_messages rows) == payload.messages_ref.n_messages`
(`tests/integration/test_audit_completeness.py`, §16.1) is asserted here at the source.

The last section asserts the *other* invariant the one recording call path owns: a logical call —
however many round trips, backoffs and degradation steps it took — is over inside its 52 s budget,
which is what keeps it inside `AGENT_WALL_CLOCK_S` (§9.4).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx2
import pytest

from hrmosaic.core.llm.anthropic import AnthropicAdapter
from hrmosaic.core.llm.base import (
    LOGICAL_CALL_BUDGET_S,
    CompletionRequest,
    Deadline,
    Message,
    ProviderError,
    ToolCall,
    ToolSchema,
)
from hrmosaic.core.llm.limiter import DailyCapExceeded, count_calls_today
from hrmosaic.core.llm.openai_compat import OpenAICompatAdapter
from hrmosaic.core.llm.stub import StubAdapter, StubScriptError, load_script
from hrmosaic.core.models import Citation, parse_payload
from hrmosaic.core.trace import SessionSpec
from hrmosaic.settings import settings

SCRIPT = "tests/fixtures/llm_scripts/adapter_smoke.json"

MESSAGES = [
    Message(role="system", content="You are the Mosaic HR Copilot."),
    Message(role="user", content="How much PTO do I accrue?"),
]

SEARCH_TOOL = ToolSchema(
    name="search_policy_documents",
    description="Search the policy corpus.",
    input_schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
)


def _spans(store, turn_id, kind="llm_call"):
    return store.execute("SELECT * FROM spans WHERE turn_id = ? AND kind = ? ORDER BY seq", (turn_id, kind)).dicts()


def _messages(store, span_id):
    return store.execute("SELECT * FROM llm_messages WHERE span_id = ? ORDER BY seq", (span_id,)).dicts()


def test_one_span_and_its_messages_per_call(writer, store):
    turn = writer.start_turn(SessionSpec(client_label="api"), user_message="How much PTO do I accrue?")
    adapter = StubAdapter(script_path=SCRIPT)

    completion = asyncio.run(
        adapter.complete(MESSAGES, tools=[SEARCH_TOOL], purpose="route", turn=turn, temperature=0.0)
    )
    turn.close(outcome="answered", stop_reason="answered")

    rows = _spans(store, turn.turn_id)
    assert len(rows) == 1
    span = rows[0]
    assert span["name"] == "stub:stub"
    assert span["status"] == "ok"

    payload = parse_payload(json.loads(span["payload_json"]))
    assert payload.kind == "llm_call"
    assert payload.purpose == "route"
    assert payload.provider == "stub"
    assert payload.tools_offered == ["search_policy_documents"]
    assert payload.finish_reason == "stop"
    assert payload.prompt_tokens == 812 and payload.completion_tokens == 74
    assert payload.total_tokens == 886
    assert payload.provider_failover is False
    assert payload.limiter_wait_ms == 0
    assert payload.temperature == 0.0
    assert payload.messages_ref is not None and payload.messages_ref.span_id == span["id"]
    assert completion.span_id == span["id"]

    rows = _messages(store, span["id"])
    assert len(rows) == payload.messages_ref.n_messages == len(MESSAGES)
    assert [row["role"] for row in rows] == ["system", "user"]
    assert [row["content"] for row in rows] == [message.content for message in MESSAGES]
    assert payload.messages_ref.total_chars == sum(len(message.content) for message in MESSAGES)


def test_the_turn_rollups_count_the_call(writer, store):
    turn = writer.start_turn(SessionSpec(), user_message="How much PTO do I accrue?")
    adapter = StubAdapter(script_path=SCRIPT)

    asyncio.run(adapter.complete(MESSAGES, purpose="route", turn=turn))
    turn.close(outcome="answered", stop_reason="answered")

    row = store.execute("SELECT * FROM turns WHERE id = ?", (turn.turn_id,)).one()
    assert row["llm_calls"] == 1
    assert row["total_tokens_in"] == 812
    assert row["total_tokens_out"] == 74
    assert row["provider"] == "stub"
    assert row["provider_failover"] == 0


def test_a_tool_calling_completion_records_its_proposed_arguments(writer, store):
    turn = writer.start_turn(SessionSpec(), user_message="How much PTO do I accrue?")
    adapter = StubAdapter(script_path=SCRIPT)

    asyncio.run(adapter.complete(MESSAGES, purpose="route", turn=turn))
    completion = asyncio.run(adapter.complete(MESSAGES, tools=[SEARCH_TOOL], purpose="act", turn=turn))
    turn.close(outcome="answered", stop_reason="answered")

    assert completion.tool_calls == [
        ToolCall(
            id="toolu_smoke_1",
            name="search_policy_documents",
            args={"query": "paid time off accrual rate full time", "k": 5},
        )
    ]
    payloads = [parse_payload(json.loads(row["payload_json"])) for row in _spans(store, turn.turn_id)]
    assert [payload.purpose for payload in payloads] == ["route", "act"]
    assert payloads[1].tool_calls[0].args == {"query": "paid time off accrual rate full time", "k": 5}


def test_the_anthropic_cache_counters_and_cost_reach_the_span(writer, store, wire, anthropic_response):
    client, _ = wire(
        [
            anthropic_response(
                input_tokens=120,
                output_tokens=40,
                cache_creation_input_tokens=4200,
                cache_read_input_tokens=0,
            )
        ]
    )
    turn = writer.start_turn(SessionSpec(), user_message="hello")
    adapter = AnthropicAdapter(api_key="k", http_client=client)

    asyncio.run(adapter.complete(MESSAGES, purpose="synthesize", turn=turn))
    turn.close(outcome="answered", stop_reason="answered")

    payload = parse_payload(json.loads(_spans(store, turn.turn_id)[0]["payload_json"]))
    assert payload.cache_creation_input_tokens == 4200
    assert payload.cache_read_input_tokens == 0
    # MODEL_PRICES: 120 in @ $1/MTok + 40 out @ $5/MTok + 4200 cache-write @ $1.25/MTok.
    assert payload.cost_usd_estimate == pytest.approx((120 * 1.00 + 40 * 5.00 + 4200 * 1.25) / 1_000_000)
    assert payload.ttfb_ms is not None


def test_failover_is_one_span_carrying_the_flag(writer, store, wire, anthropic_response, openai_response):
    overloaded = (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
    primary_client, primary_recorded = wire([overloaded])
    fallback_client, fallback_recorded = wire([openai_response(content="the fallback answered")])

    fallback = OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=fallback_client)
    adapter = AnthropicAdapter(api_key="k", http_client=primary_client, fallback=fallback)
    turn = writer.start_turn(SessionSpec(), user_message="hello")

    completion = asyncio.run(adapter.complete(MESSAGES, purpose="act", turn=turn))
    turn.close(outcome="answered", stop_reason="answered")

    assert completion.text == "the fallback answered"
    assert completion.provider_failover is True
    # One bounded backoff, then the failover: **two** round trips, never three. Running the primary
    # twice and then the fallback would be 25 + 2 + 25 + 25 = 77 s, past the 52 s the brief allows.
    assert len(primary_recorded) == 1, "the primary is tried once, then the backoff, then the fallback"
    assert len(fallback_recorded) == 1

    rows = _spans(store, turn.turn_id)
    assert len(rows) == 1, "a failover is one logical call, so it is one span"
    payload = parse_payload(json.loads(rows[0]["payload_json"]))
    assert payload.provider_failover is True
    assert payload.retry_count == 1
    assert payload.provider == "openai_compat" and payload.model == "gemini-3.5-flash-lite"
    assert rows[0]["name"] == "openai_compat:gemini-3.5-flash-lite"
    # `ttfb_ms` times the round trip that answered; the backoff sleep in front of it belongs to the
    # span's own `duration_ms`, so a paced or retried call never looks like a slow provider.
    assert payload.ttfb_ms is not None and payload.ttfb_ms < 500
    assert rows[0]["duration_ms"] >= 1000
    assert store.execute("SELECT provider_failover FROM turns WHERE id = ?", (turn.turn_id,)).scalar() == 1


def test_a_long_retry_after_fails_over_without_parking(wire, openai_response):
    def rate_limited(request):
        import httpx2

        return httpx2.Response(
            429,
            headers={"retry-after": "45"},
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
        )

    primary_client, primary_recorded = wire([rate_limited])
    fallback_client, _ = wire([openai_response(content="fallback")])
    adapter = AnthropicAdapter(
        api_key="k",
        http_client=primary_client,
        fallback=OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=fallback_client),
    )

    completion = asyncio.run(adapter.complete(MESSAGES, purpose="act"))

    assert completion.provider_failover is True
    assert completion.retry_count == 0, "a 45 s Retry-After is longer than we will ever wait"
    assert len(primary_recorded) == 1


def test_a_total_failure_still_records_the_attempt(writer, store, wire):
    overloaded = (503, {"type": "error", "error": {"type": "api_error", "message": "upstream down"}})
    client, recorded = wire([overloaded])
    adapter = AnthropicAdapter(api_key="k", http_client=client)
    turn = writer.start_turn(SessionSpec(), user_message="hello")

    with pytest.raises(ProviderError):
        asyncio.run(adapter.complete(MESSAGES, purpose="act", turn=turn))
    turn.close(outcome="error", stop_reason="error", error_kind="provider_error")

    # No fallback configured, so the second of the two round trips is the primary again.
    assert len(recorded) == 2
    rows = _spans(store, turn.turn_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert "503" in rows[0]["error_message"]


def test_a_non_retryable_status_never_fails_over(wire, openai_response):
    forbidden = (403, {"type": "error", "error": {"type": "permission_error", "message": "no access"}})
    primary_client, primary_recorded = wire([forbidden])
    fallback_client, fallback_recorded = wire([openai_response(content="never reached")])
    adapter = AnthropicAdapter(
        api_key="k",
        http_client=primary_client,
        fallback=OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=fallback_client),
    )

    with pytest.raises(ProviderError, match="403"):
        asyncio.run(adapter.complete(MESSAGES, purpose="act"))

    assert len(primary_recorded) == 1
    assert fallback_recorded == []


def test_the_daily_cap_is_counted_from_the_spans(writer, store, wire, anthropic_response):
    client, _ = wire([anthropic_response()])
    adapter = AnthropicAdapter(api_key="k", http_client=client, daily_call_cap=1, store=store)

    first = writer.start_turn(SessionSpec(), user_message="one")
    asyncio.run(adapter.complete(MESSAGES, purpose="act", turn=first))
    first.close(outcome="answered", stop_reason="answered")
    assert count_calls_today(store, "anthropic") == 1

    second = writer.start_turn(SessionSpec(), user_message="two")
    with pytest.raises(DailyCapExceeded) as raised:
        asyncio.run(adapter.complete(MESSAGES, purpose="act", turn=second))
    second.close(outcome="error", stop_reason="error", error_kind=raised.value.error_kind)

    assert raised.value.error_kind == "daily_cap_reached"
    assert "LLM_DAILY_CALL_CAP" in str(raised.value)
    assert _spans(store, second.turn_id) == [], "the capped call never reached the provider"


def test_a_script_out_of_step_fails_loudly():
    adapter = StubAdapter(script_path=SCRIPT)

    with pytest.raises(StubScriptError, match="purpose"):
        asyncio.run(adapter.complete(MESSAGES, purpose="synthesize"))


def test_an_exhausted_script_fails_loudly():
    adapter = StubAdapter(script_path=SCRIPT)
    for purpose in ("route", "act", "synthesize"):
        asyncio.run(adapter.complete(MESSAGES, purpose=purpose))

    assert adapter.remaining == 0
    with pytest.raises(StubScriptError, match="3 entries"):
        asyncio.run(adapter.complete(MESSAGES, purpose="route"))


def test_the_committed_demo_script_loads():
    path = Path("tests/fixtures/llm_scripts/demo_task_1.json")
    adapter = StubAdapter(script_path=path)

    assert adapter.remaining == 5
    assert [entry["purpose"] for entry in load_script(path)] == ["route", "act", "act", "act", "synthesize"]


def test_both_providers_down_is_still_one_span_flagged_as_a_failover(writer, store, wire):
    overloaded = (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
    unavailable = (503, {"error": {"message": "backend unavailable", "type": "server_error"}})
    primary_client, _ = wire([overloaded])
    fallback_client, fallback_recorded = wire([unavailable])
    adapter = AnthropicAdapter(
        api_key="k",
        http_client=primary_client,
        fallback=OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=fallback_client),
    )
    turn = writer.start_turn(SessionSpec(), user_message="hello")

    with pytest.raises(ProviderError, match="503"):
        asyncio.run(adapter.complete(MESSAGES, purpose="act", turn=turn))
    turn.close(outcome="error", stop_reason="error", error_kind="provider_error")

    assert len(fallback_recorded) == 1
    rows = _spans(store, turn.turn_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    payload = parse_payload(json.loads(rows[0]["payload_json"]))
    assert payload.provider_failover is True, "the record must show the failover was attempted"


# --------------------------------------------------------------------------------------
# The bound on a logical call (§9.4: ≈ 25 + 2 + 25 = 52 s inside `AGENT_WALL_CLOCK_S` = 90)
# --------------------------------------------------------------------------------------
#
# The 52 s is a real deadline, not arithmetic over the round-trip count: an adapter whose
# `invoke()` degrades in three steps, or a transport that ignores its own timeout, must still not
# outlive the slot the agent loop allotted the call. These four assert the deadline itself.

#: Small enough to keep the suite fast, and `_hangs` is always well clear of it.
BUDGET_S = 0.25
HANG_S = 0.8


def _hangs(seconds: float, response: tuple[int, dict]):
    """A wire handler that stalls past the budget — a provider that accepted and went quiet."""
    status, payload = response

    def handler(request):
        time.sleep(seconds)
        return httpx2.Response(status, json=payload)

    return handler


def test_the_call_budget_fits_inside_the_agent_wall_clock():
    assert LOGICAL_CALL_BUDGET_S == pytest.approx(25.0 + 2.0 + 25.0), "one round trip, one backoff, one more"
    assert LOGICAL_CALL_BUDGET_S < settings.agent_wall_clock_s


def test_a_logical_call_never_outlives_its_budget(writer, store, wire, anthropic_response, openai_response):
    """Primary and fallback both hang. The budget ends the call, and the span still records it."""
    primary_client, _ = wire([_hangs(HANG_S, anthropic_response())])
    fallback_client, _ = wire([_hangs(HANG_S, openai_response(content="too late"))])
    adapter = AnthropicAdapter(
        api_key="k",
        http_client=primary_client,
        fallback=OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=fallback_client),
        call_budget_s=BUDGET_S,
    )
    turn = writer.start_turn(SessionSpec(), user_message="hello")

    async def scenario() -> float:
        # Timed inside the loop: `asyncio.run` joins the stalled worker thread on the way out,
        # which is the hanging provider's time, not the caller's.
        started = time.monotonic()
        with pytest.raises(ProviderError, match="budget"):
            await adapter.complete(MESSAGES, purpose="act", turn=turn)
        return time.monotonic() - started

    elapsed = asyncio.run(scenario())
    turn.close(outcome="error", stop_reason="error", error_kind="provider_error")

    assert BUDGET_S <= elapsed < HANG_S, "the budget ended the call, not the transport"
    rows = _spans(store, turn.turn_id)
    assert len(rows) == 1, "a call cut short by its budget is still one span"
    assert rows[0]["status"] == "error"
    assert "budget" in rows[0]["error_message"]


def test_the_structured_output_ladder_is_bounded_by_the_same_budget(wire, openai_response):
    """strict → prompted → repair is three round trips; they share the call's budget, not 25 s each."""
    rejected = (
        400,
        {"error": {"message": "response_format json_schema is not supported", "type": "invalid_request_error"}},
    )
    client, recorded = wire([rejected, _hangs(HANG_S, openai_response(content="not json"))])
    adapter = OpenAICompatAdapter(
        base_url="https://example.test/v1/", api_key="k", http_client=client, call_budget_s=BUDGET_S
    )

    async def scenario() -> float:
        started = time.monotonic()
        with pytest.raises(ProviderError, match="budget"):
            await adapter.complete(MESSAGES, purpose="route", response_schema=Citation)
        return time.monotonic() - started

    elapsed = asyncio.run(scenario())

    assert BUDGET_S <= elapsed < HANG_S
    assert len(recorded) == 2, "strict, then prompted — the repair round trip had no budget left to spend"


def test_an_expired_deadline_puts_nothing_on_the_wire(wire, openai_response):
    client, recorded = wire([openai_response(content="never sent")])
    adapter = OpenAICompatAdapter(base_url="https://example.test/v1/", api_key="k", http_client=client)
    request = CompletionRequest(messages=MESSAGES, purpose="act")

    with pytest.raises(ProviderError, match="budget is spent"):
        asyncio.run(adapter.invoke(request, Deadline.after(0.0)))

    assert recorded == [], "a round trip that cannot finish inside the budget is never started"
