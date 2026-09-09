"""`CachedAdapter` is off by default and never a correctness mechanism (spec §9.8, §22).

`LLM_CACHE_TTL_S` defaults to `0`, and what this file protects is that the default really is
transparent — a wrapper that quietly served a stale answer during an eval latency run would
invalidate the numbers. **No test here asserts a cache hit**, deliberately: the spec forbids any
test or committed artifact from depending on one. What is asserted is that the wrapper is a
pass-through when it is off, that its key separates calls that differ, and that a warmed call still
leaves exactly one `llm_call` span so the record never lies about where an answer came from.
"""

from __future__ import annotations

import asyncio

from hrmosaic.core.llm.base import CompletionRequest, Message
from hrmosaic.core.llm.cache import CachedAdapter, cache_key
from hrmosaic.core.llm.stub import StubAdapter
from hrmosaic.core.models import AnswerSchema
from hrmosaic.core.trace import SessionSpec

SCRIPT = "tests/fixtures/llm_scripts/adapter_smoke.json"
MESSAGES = [Message(role="user", content="How much PTO do I accrue?")]


def test_the_default_ttl_is_a_pass_through(writer, store):
    inner = StubAdapter(script_path=SCRIPT)
    adapter = CachedAdapter(inner, ttl_s=0, store=store)
    turn = writer.start_turn(SessionSpec(), user_message="How much PTO do I accrue?")

    asyncio.run(adapter.complete(MESSAGES, purpose="route", turn=turn))
    asyncio.run(adapter.complete(MESSAGES, purpose="act", turn=turn))
    turn.close(outcome="answered", stop_reason="answered")

    # Both calls reached the script — nothing was served from the table, and nothing was written.
    assert inner.remaining == 1
    assert store.execute("SELECT COUNT(*) FROM llm_cache").scalar() == 0
    assert store.execute("SELECT COUNT(*) FROM spans WHERE kind = 'llm_call'").scalar() == 2


def test_an_enabled_cache_still_writes_one_span_per_call(writer, store):
    inner = StubAdapter(script_path=SCRIPT)
    adapter = CachedAdapter(inner, ttl_s=600, store=store)
    turn = writer.start_turn(SessionSpec(), user_message="How much PTO do I accrue?")

    asyncio.run(adapter.complete(MESSAGES, purpose="route", turn=turn))
    adapter_second = CachedAdapter(StubAdapter(script_path=SCRIPT), ttl_s=600, store=store)
    asyncio.run(adapter_second.complete(MESSAGES, purpose="route", turn=turn))
    turn.close(outcome="answered", stop_reason="answered")

    assert store.execute("SELECT COUNT(*) FROM spans WHERE kind = 'llm_call'").scalar() == 2


def test_the_key_separates_calls_that_differ():
    def key_for(**overrides) -> str:
        request = CompletionRequest(**{"messages": MESSAGES, "purpose": "route", **overrides})
        return cache_key(provider="stub", model="stub", request=request)

    baseline = key_for()
    assert baseline == key_for(), "the key is a pure function of the call"
    assert baseline != key_for(temperature=0.7)
    assert baseline != key_for(purpose="synthesize")
    assert baseline != key_for(response_schema=AnswerSchema)
    assert baseline != key_for(messages=[Message(role="user", content="a different question")])
    assert baseline != cache_key(
        provider="anthropic", model="claude-haiku-4-5", request=CompletionRequest(messages=MESSAGES, purpose="route")
    )
