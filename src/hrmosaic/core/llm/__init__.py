"""The provider abstraction (spec §9.8): one `ChatModel` protocol, four implementations.

| Role | Provider / model | Adapter |
|---|---|---|
| agent — route, act, synthesize, repair | Anthropic `claude-haiku-4-5` | `AnthropicAdapter` |
| judge — decompose, groundedness, … | Google `gemini-3.5-flash-lite` | `OpenAICompatAdapter` |
| agent failover on 429 / 5xx / timeout | Google `gemini-3.5-flash-lite` | `OpenAICompatAdapter` |
| CI / tests | — | `StubAdapter` |

`CachedAdapter` is an optional wrapper, **off by default** (`LLM_CACHE_TTL_S=0`); it is never a
correctness mechanism (§22).

The three factories below are the only place the allocation table is read, so a caller asks for a
role — never for a provider. Credentials are validated **lazily**, at the point of use: building an
adapter with no key succeeds and the first `complete()` raises `MissingCredentialError`, which the
web layer renders as `outcome: "configuration_required"` (§12.3).
"""

from __future__ import annotations

from hrmosaic.core.llm.anthropic import AnthropicAdapter
from hrmosaic.core.llm.base import (
    LOGICAL_CALL_BUDGET_S,
    ChatModel,
    Completion,
    CompletionRequest,
    Deadline,
    Message,
    MissingCredentialError,
    ProviderError,
    RecordingAdapter,
    ToolCall,
    ToolSchema,
)
from hrmosaic.core.llm.cache import CachedAdapter
from hrmosaic.core.llm.limiter import DailyCapExceeded, TokenBucket, count_calls_today
from hrmosaic.core.llm.openai_compat import OpenAICompatAdapter
from hrmosaic.core.llm.stub import StubAdapter, StubScriptError
from hrmosaic.settings import Settings
from hrmosaic.settings import settings as default_settings

__all__ = [
    "LOGICAL_CALL_BUDGET_S",
    "AnthropicAdapter",
    "CachedAdapter",
    "ChatModel",
    "Completion",
    "CompletionRequest",
    "DailyCapExceeded",
    "Deadline",
    "Message",
    "MissingCredentialError",
    "OpenAICompatAdapter",
    "ProviderError",
    "RecordingAdapter",
    "StubAdapter",
    "StubScriptError",
    "TokenBucket",
    "ToolCall",
    "ToolSchema",
    "build_agent_model",
    "build_fallback_model",
    "build_judge_model",
    "count_calls_today",
    "shared_limiter",
]


_limiters: dict[tuple[int, int], TokenBucket] = {}


def shared_limiter(settings: Settings | None = None) -> TokenBucket:
    """The process-wide token bucket: capacity `LLM_BURST`, refill `LLM_RPM / 60` per second.

    One bucket per `(rpm, burst)` pair, so the agent, its failover and the judge all draw on the
    same budget under one configuration, and a run at a different rate gets its own bucket rather
    than inheriting a warm one.
    """
    settings = settings or default_settings
    burst = settings.llm_burst or settings.llm_rpm
    key = (settings.llm_rpm, burst)
    if key not in _limiters:
        _limiters[key] = TokenBucket(capacity=burst, refill_per_second=settings.llm_rpm / 60.0)
    return _limiters[key]


def build_fallback_model(settings: Settings | None = None) -> ChatModel | None:
    """The `LLM_FALLBACK_*` adapter (free Gemini), or `None` when failover is switched off."""
    settings = settings or default_settings
    if settings.llm_fallback_provider == "stub":
        return StubAdapter(script_path=settings.llm_stub_script)
    if settings.llm_fallback_provider != "openai_compat":
        return None
    return OpenAICompatAdapter(
        model=settings.llm_fallback_model,
        base_url=settings.llm_fallback_base_url,
        api_key=settings.llm_fallback_api_key,
        api_key_variable="LLM_FALLBACK_API_KEY",
        limiter=shared_limiter(settings),
    )


def build_agent_model(settings: Settings | None = None) -> ChatModel:
    """The agent's adapter for `LLM_PROVIDER`, wrapped in the optional cache when it is on."""
    settings = settings or default_settings
    limiter = shared_limiter(settings)
    model: ChatModel
    if settings.llm_provider == "stub":
        model = StubAdapter(script_path=settings.llm_stub_script)
    elif settings.llm_provider == "anthropic":
        model = AnthropicAdapter(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key,
            limiter=limiter,
            fallback=build_fallback_model(settings),
            daily_call_cap=settings.llm_daily_call_cap,
        )
    else:
        model = OpenAICompatAdapter(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            api_key_variable="LLM_API_KEY",
            limiter=limiter,
            fallback=build_fallback_model(settings),
        )
    if settings.llm_cache_ttl_s > 0:
        model = CachedAdapter(model, ttl_s=settings.llm_cache_ttl_s)
    return model


def build_judge_model(settings: Settings | None = None) -> ChatModel:
    """The judge — a different vendor and family from the agent by construction (§13.7).

    `JUDGE_API_KEY` falls back to `LLM_API_KEY` (§12.3); `/health.llm.judge.separate_key` reports
    which of the two was used.
    """
    settings = settings or default_settings
    if settings.judge_provider == "stub":
        return StubAdapter(script_path=settings.llm_stub_script)
    api_key = settings.judge_api_key or settings.llm_api_key
    return OpenAICompatAdapter(
        model=settings.judge_model,
        base_url=settings.judge_base_url,
        api_key=api_key,
        api_key_variable="JUDGE_API_KEY",
        limiter=shared_limiter(settings),
    )
