"""`LLM_DAILY_CALL_CAP` short-circuits on an in-process counter (performance plan W1-C(a)).

Every logical provider call used to run `CALLS_TODAY_SQL` before it reached the provider — a fully
indexed query (`ix_spans_kind`), so the cost is round-trip rather than scan, but ~1.8 ms of it on
every one of a turn's five or six calls, on the request path, on a 0.1-CPU instance.

**The counter is a fast negative and nothing else.** It only ever answers "this process is nowhere
near the cap, do not ask the database"; the moment it is not sure — it has never been seeded this
UTC day, its seed is stale, or its own count has reached the cap — the authoritative SQL runs and
**every refusal is raised from that number**. So §9.8's "counted from the `llm_call` spans, so there
is no second counter to drift" stays literally true: no refusal, and no `/health.calls_today`, is
ever computed from the in-process number.
"""

from __future__ import annotations

import asyncio

import pytest

from hrmosaic.core.llm.anthropic import AnthropicAdapter
from hrmosaic.core.llm.base import Message
from hrmosaic.core.llm.limiter import DailyCallCounter, DailyCapExceeded, count_calls_today, daily_calls
from hrmosaic.core.trace import SessionSpec

MESSAGES = [Message(role="user", content="How much PTO do I accrue?")]


# --------------------------------------------------------------------------------------
# The counter on its own
# --------------------------------------------------------------------------------------


def test_an_unseeded_provider_is_never_taken_on_trust():
    """A fresh process knows nothing about the day's spans; it must go and look."""
    counter = DailyCallCounter()
    assert counter.below("anthropic", cap=1500) is False


def test_a_seeded_provider_short_circuits_until_it_reaches_the_cap():
    counter = DailyCallCounter()
    counter.seed("anthropic", 1498)
    assert counter.below("anthropic", cap=1500) is True

    counter.record("anthropic")
    assert counter.below("anthropic", cap=1500) is True
    counter.record("anthropic")
    assert counter.below("anthropic", cap=1500) is False, "at the cap it stops answering and asks"


def test_the_seed_goes_stale_so_a_second_process_cannot_be_ignored_forever():
    """The counter sees only this process's calls; the re-seed bounds how far it can drift."""
    counter = DailyCallCounter(reseed_every=3)
    counter.seed("anthropic", 0)
    for _ in range(3):
        assert counter.below("anthropic", cap=1500) is True
        counter.record("anthropic")
    assert counter.below("anthropic", cap=1500) is False


def test_the_day_rolls_over(monkeypatch):
    from datetime import UTC, datetime

    counter = DailyCallCounter()
    monday = datetime(2026, 9, 10, 23, 59, tzinfo=UTC)
    tuesday = datetime(2026, 9, 11, 0, 1, tzinfo=UTC)
    counter.seed("anthropic", 1500, now=monday)
    assert counter.below("anthropic", cap=1500, now=monday) is False
    assert counter.below("anthropic", cap=1500, now=tuesday) is False, "a new day is unseeded, not zero"


def test_a_call_recorded_before_any_seed_does_not_open_a_window_of_trust():
    """`record_llm_call` writes spans for capless adapters too; those must not vouch for a cap."""
    counter = DailyCallCounter()
    counter.record("anthropic")
    assert counter.below("anthropic", cap=1500) is False


def test_the_counter_is_keyed_per_provider():
    counter = DailyCallCounter()
    counter.seed("anthropic", 0)
    counter.record("anthropic")
    assert counter.below("anthropic", cap=1500) is True
    assert counter.below("google", cap=1500) is False


# --------------------------------------------------------------------------------------
# Wired into the adapter
# --------------------------------------------------------------------------------------


def test_the_cap_is_still_enforced_and_still_raised_from_the_spans(writer, store, wire, anthropic_response):
    client, _ = wire([anthropic_response()])
    adapter = AnthropicAdapter(api_key="k", http_client=client, daily_call_cap=1, store=store)

    first = writer.start_turn(SessionSpec(), user_message="one")
    asyncio.run(adapter.complete(MESSAGES, purpose="act", turn=first))
    first.close(outcome="answered", stop_reason="answered")

    second = writer.start_turn(SessionSpec(), user_message="two")
    with pytest.raises(DailyCapExceeded) as raised:
        asyncio.run(adapter.complete(MESSAGES, purpose="act", turn=second))
    second.close(outcome="error", stop_reason="error", error_kind=raised.value.error_kind)

    assert raised.value.calls_today == count_calls_today(store, "anthropic") == 1


def test_a_call_under_the_cap_asks_the_database_once_and_then_stops_asking(
    writer, store, wire, anthropic_response, monkeypatch
):
    """The whole point of the lever: the SQL is seed-and-reseed, not per call."""
    import hrmosaic.core.llm.base as base

    asked: list[str] = []
    real = base.count_calls_today
    monkeypatch.setattr(base, "count_calls_today", lambda s, p: asked.append(p) or real(s, p))

    client, _ = wire([anthropic_response()])
    adapter = AnthropicAdapter(api_key="k", http_client=client, daily_call_cap=1500, store=store)
    for index in range(4):
        turn = writer.start_turn(SessionSpec(), user_message=str(index))
        asyncio.run(adapter.complete(MESSAGES, purpose="act", turn=turn))
        turn.close(outcome="answered", stop_reason="answered")

    assert asked == ["anthropic"], "one seeding query, then four calls served from the counter"


def test_the_counter_follows_the_completion_not_the_adapter(writer, store):
    """A failover bills the **fallback** provider, so that is the counter the call belongs in."""
    from hrmosaic.core.llm.base import Completion, CompletionRequest, record_llm_call

    counter = daily_calls()
    counter.seed("google", 0)
    counter.seed("anthropic", 0)

    turn = writer.start_turn(SessionSpec(), user_message="one")
    record_llm_call(
        turn,
        request=CompletionRequest(messages=list(MESSAGES), purpose="act"),
        completion=Completion(provider="google", model="gemini-3.5-flash-lite", provider_failover=True),
        started_at=0,
    )
    turn.close(outcome="answered", stop_reason="answered")

    assert counter.count("google") == 1
    assert counter.count("anthropic") == 0
