"""The §9.8 allocation table, read once and only in the factories.

Two properties are load-bearing rather than cosmetic:

* **the agent model is pinned** to Anthropic `claude-haiku-4-5` (§3 row 6, §21 row 46), and
* **the judge is a different vendor and family from the agent**, which is what makes judge
  independence hold by construction so §13.7 needs no re-judge machinery.

A key is never required to *build* an adapter — boot always succeeds and the missing credential
surfaces at the first call, naming the variable and its signup URL (§12.3).
"""

from __future__ import annotations

import asyncio

import pytest

from hrmosaic.core.llm import (
    AnthropicAdapter,
    MissingCredentialError,
    OpenAICompatAdapter,
    StubAdapter,
    build_agent_model,
    build_fallback_model,
    build_judge_model,
    shared_limiter,
)
from hrmosaic.core.llm.base import Message
from hrmosaic.settings import Settings


def _settings(**overrides) -> Settings:
    base = {
        "llm_provider": "anthropic",
        "llm_model": "claude-haiku-4-5",
        "anthropic_api_key": None,
        "llm_cache_ttl_s": 0,
        "_env_file": None,  # never read the developer's real .env in a unit test
    }
    return Settings(**{**base, **overrides})


def test_the_agent_is_the_pinned_haiku_model():
    agent = build_agent_model(_settings())

    assert isinstance(agent, AnthropicAdapter)
    assert (agent.provider, agent.model) == ("anthropic", "claude-haiku-4-5")


def test_the_judge_is_a_different_vendor_and_family_from_the_agent():
    settings = _settings()
    agent = build_agent_model(settings)
    judge = build_judge_model(settings)

    assert isinstance(judge, OpenAICompatAdapter)
    assert judge.model == "gemini-3.5-flash-lite"
    assert (judge.provider, judge.model) != (agent.provider, agent.model)


def test_the_failover_is_the_free_gemini_path():
    fallback = build_fallback_model(_settings())

    assert isinstance(fallback, OpenAICompatAdapter)
    assert fallback.model == "gemini-3.5-flash-lite"


def test_the_zero_cost_path_configures_the_agent_from_llm_base_url():
    agent = build_agent_model(_settings(llm_provider="openai_compat", llm_model="gemini-3.5-flash-lite"))

    assert isinstance(agent, OpenAICompatAdapter)
    assert agent.model == "gemini-3.5-flash-lite"


def test_the_stub_path_needs_no_credential():
    agent = build_agent_model(_settings(llm_provider="stub"))

    assert isinstance(agent, StubAdapter)
    assert agent.configured is True


def test_a_missing_credential_surfaces_at_the_first_call_not_at_build():
    agent = build_agent_model(_settings())  # no ANTHROPIC_API_KEY — building still succeeds
    assert agent.configured is False

    with pytest.raises(MissingCredentialError) as raised:
        asyncio.run(agent.complete([Message(role="user", content="hello")]))

    assert raised.value.variable == "ANTHROPIC_API_KEY"
    assert raised.value.signup_url.startswith("https://")
    assert raised.value.retryable is False, "a missing key must not fail over to the free path"


def test_the_agent_and_its_failover_share_one_limiter():
    settings = _settings(llm_rpm=10, llm_burst=6)

    assert shared_limiter(settings) is shared_limiter(settings)
    assert shared_limiter(settings).capacity == 6
    assert shared_limiter(_settings(llm_rpm=20, llm_burst=20)) is not shared_limiter(settings)
