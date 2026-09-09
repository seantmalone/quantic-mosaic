"""The `ChatModel` protocol, the shared wire types, and the one recording call path (spec §9.8).

Everything a provider-specific adapter must not reinvent lives here:

* **the types** — `Message`, `ToolSchema`, `ToolCall`, `Completion`. Tool-call arguments are
  normalised at this boundary: OpenAI-shaped endpoints deliver a JSON **string**, Anthropic a
  parsed **object**, and both arrive in `ToolCall.args` as the same dict (§3 row 5);
* **the limiter, the spend guard, the one backoff and the failover** — an adapter implements
  `invoke()` for one round trip and inherits the rest, so `retry_count` and `provider_failover`
  can never mean different things in two adapters;
* **the record** — exactly one `llm_call` span per logical call plus its `llm_messages` rows,
  written through `core/trace.py` (the sole span writer, §16.3) from inside the adapter, so no
  caller can make a provider call that leaves no trace.

Credentials are resolved lazily: constructing an adapter without a key is fine and the first
`complete()` raises `MissingCredentialError`, naming the variable and its signup URL (§12.3).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from hrmosaic.core.db import Store, get_store, now_micros
from hrmosaic.core.ids import new_span_id
from hrmosaic.core.llm.limiter import DailyCapExceeded, TokenBucket, count_calls_today
from hrmosaic.core.models import (
    LlmCallPayload,
    LlmPurpose,
    MessagesRef,
    ProposedToolCall,
    estimate_cost_usd,
)

if TYPE_CHECKING:  # a type-only edge, so `core.llm` stays importable without the trace writer
    from hrmosaic.core.trace import TurnBuffer

Role = Literal["system", "user", "assistant", "tool"]

#: The single backoff before failover when the provider names no `Retry-After` (§9.8).
DEFAULT_BACKOFF_S = 1.0

#: `Retry-After` is honoured **up to** this cap; a longer one fails over immediately, which is
#: what bounds a logical call at ≈ 25 + 2 + 25 = 52 s inside `AGENT_WALL_CLOCK_S` (§9.4).
MAX_BACKOFF_S = 2.0

#: One request may not outlive this, and the SDKs' own retry layers are off (`max_retries=0`), so
#: the backoff-then-failover below is the single retry layer in the system.
REQUEST_TIMEOUT_S = 25.0

#: §9.8's failover triggers: 429, every 5xx, and timeouts. 408 is the server reporting a read
#: timeout, so it belongs with the transport timeouts rather than with the client's own mistakes.
RETRYABLE_STATUSES = frozenset({408, 429})


# --------------------------------------------------------------------------------------
# Wire types
# --------------------------------------------------------------------------------------


class ToolCall(BaseModel):
    """A tool the model asked for. `args` is always a parsed dict, on every wire shape."""

    model_config = ConfigDict(extra="forbid")
    id: str = ""
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """One entry of the messages array, in the provider-neutral shape the adapters translate."""

    model_config = ConfigDict(extra="forbid")
    role: Role
    content: str = ""
    #: assistant only — the tool calls this turn of the conversation asked for
    tool_calls: list[ToolCall] = Field(default_factory=list)
    #: `tool` role only — which call this message answers
    tool_call_id: str | None = None
    #: `tool` role only — the tool that produced the result, for the audit record
    name: str | None = None


class ToolSchema(BaseModel):
    """A tool exactly as `tools/list` published it.

    An adapter translates it into its provider's tool shape and may drop a keyword that provider
    rejects (`AnthropicAdapter` and top-level `oneOf`), but never rewrites what it publishes: the
    committed schema stays the one the MCP server validates arguments against (§8.4).
    """

    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class Completion(BaseModel):
    """One provider response, plus the accounting the `llm_call` span records."""

    model_config = ConfigDict(extra="forbid")
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd_estimate: float = 0.0
    structured_output_mode: str | None = None
    ttfb_ms: int | None = None
    retry_count: int = 0
    provider_failover: bool = False
    limiter_wait_ms: int = 0
    cache_hit: bool = False
    span_id: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def parsed_json(self) -> Any:
        """The constrained-JSON body. Raises `json.JSONDecodeError` on prose, deliberately."""
        return json.loads(strip_json_fences(self.text))


class CompletionRequest(BaseModel):
    """What an adapter is asked for — the unit the cache keys on and the failover replays."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    messages: list[Message]
    tools: list[ToolSchema] = Field(default_factory=list)
    response_schema: type[BaseModel] | None = None
    temperature: float = 0.0
    purpose: LlmPurpose = "act"


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------


class ProviderError(RuntimeError):
    """A provider round trip failed. `retryable` decides backoff-then-failover (§9.8)."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


class MissingCredentialError(ProviderError):
    """No key for the configured provider — the deferred validation of §12.3, never a boot failure."""

    def __init__(self, variable: str, signup_url: str) -> None:
        super().__init__(f"{variable} is not set. Get a key at {signup_url} and set {variable}.")
        self.variable = variable
        self.signup_url = signup_url


def status_error(status: int, message: str, headers: Mapping[str, str] | None = None) -> ProviderError:
    """Translate an SDK status error into the one shape the retry logic understands."""
    return ProviderError(
        message,
        status=status,
        retryable=status in RETRYABLE_STATUSES or status >= 500,
        retry_after=_retry_after_seconds(headers),
    )


def _retry_after_seconds(headers: Mapping[str, str] | None) -> float | None:
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):  # the HTTP-date form; treat it as "longer than we will wait"
        return MAX_BACKOFF_S + 1.0


def strip_json_fences(text: str) -> str:
    """Drop a ```json … ``` wrapper — some OpenAI-compatible endpoints add one under prompted JSON."""
    body = text.strip()
    if not body.startswith("```"):
        return body
    body = body.split("\n", 1)[-1] if "\n" in body else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body.strip()


# --------------------------------------------------------------------------------------
# The protocol
# --------------------------------------------------------------------------------------


class ChatModel(Protocol):
    """Spec §9.8's protocol. `purpose` and `turn` are the recording seam: the payload of §10.2
    names a purpose, and the span is written into the turn the call belongs to."""

    provider: str
    model: str

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSchema] | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        purpose: LlmPurpose = "act",
        turn: TurnBuffer | None = None,
    ) -> Completion: ...


# --------------------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------------------


def message_rows(messages: Sequence[Message]) -> list[tuple[str, str]]:
    """The `llm_messages` rows for a call: the exact prompt, one row per message (§10.1)."""
    rows: list[tuple[str, str]] = []
    for message in messages:
        content = message.content
        if message.tool_calls:
            requested = json.dumps(
                [{"name": call.name, "args": call.args} for call in message.tool_calls],
                ensure_ascii=False,
            )
            content = f"{content}\n{requested}" if content else requested
        rows.append((message.role, content))
    return rows


def record_llm_call(
    turn: TurnBuffer | None,
    *,
    request: CompletionRequest,
    completion: Completion,
    started_at: int,
    status: str = "ok",
    error_message: str | None = None,
) -> str | None:
    """Write the one `llm_call` span and its `llm_messages` rows. Returns the span id.

    Called from inside the adapter — including on the cache-hit and total-failure paths — so
    "exactly one span per logical call" holds however the call ended. With no turn (the live
    probe, a bare unit test) nothing is written and the completion is returned as it is.
    """
    if turn is None:
        return None
    span_id = new_span_id()
    rows = message_rows(request.messages)
    payload = LlmCallPayload(
        provider=completion.provider,
        model=completion.model,
        purpose=request.purpose,
        messages_ref=MessagesRef(
            span_id=span_id,
            n_messages=len(rows),
            total_chars=sum(len(content) for _, content in rows),
        ),
        tools_offered=[tool.name for tool in request.tools],
        response_text=completion.text or None,
        tool_calls=[ProposedToolCall(name=call.name, args=call.args) for call in completion.tool_calls],
        finish_reason=completion.finish_reason,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        total_tokens=completion.total_tokens,
        cache_creation_input_tokens=completion.cache_creation_input_tokens,
        cache_read_input_tokens=completion.cache_read_input_tokens,
        cost_usd_estimate=completion.cost_usd_estimate,
        temperature=request.temperature,
        retry_count=completion.retry_count,
        cache_hit=completion.cache_hit,
        limiter_wait_ms=completion.limiter_wait_ms,
        provider_failover=completion.provider_failover,
        structured_output_mode=completion.structured_output_mode,
        ttfb_ms=completion.ttfb_ms,
    )
    turn.add_span(
        "llm_call",
        f"{completion.provider}:{completion.model}",
        payload,
        span_id=span_id,
        started_at=started_at,
        status=status,
        error_message=error_message,
        messages=rows,
    )
    return span_id


# --------------------------------------------------------------------------------------
# The recording call path
# --------------------------------------------------------------------------------------


@dataclass
class _Attempts:
    """What one logical call cost, across however many round trips it took."""

    completion: Completion | None = None
    retry_count: int = 0
    failed_over: bool = False
    round_trip_ms: int = 0
    failure: ProviderError | None = None


class RecordingAdapter:
    """The shared half of every adapter: cap, limiter, one backoff, failover, one span.

    A subclass implements `invoke(request)` — a single round trip returning a `Completion` with
    `text`, `tool_calls`, the token counts and `structured_output_mode` filled in — and raises
    `ProviderError` for anything the transport or the endpoint reported.
    """

    provider: str = ""

    def __init__(
        self,
        *,
        model: str,
        limiter: TokenBucket | None = None,
        fallback: ChatModel | None = None,
        daily_call_cap: int | None = None,
        store: Store | None = None,
    ) -> None:
        self.model = model
        self._limiter = limiter
        self._fallback = fallback
        self._daily_call_cap = daily_call_cap
        self._store = store

    # -- the subclass seam -------------------------------------------------------------
    async def invoke(self, request: CompletionRequest) -> Completion:
        """One round trip. Raises `ProviderError`; never retries, never records."""
        raise NotImplementedError

    # -- the public call ---------------------------------------------------------------
    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSchema] | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        purpose: LlmPurpose = "act",
        turn: TurnBuffer | None = None,
    ) -> Completion:
        request = CompletionRequest(
            messages=list(messages),
            tools=list(tools or []),
            response_schema=response_schema,
            temperature=temperature,
            purpose=purpose,
        )
        self._check_daily_cap(turn)
        limiter_wait_ms = await self._limiter.acquire() if self._limiter is not None else 0

        started_at = now_micros()
        result = await self._call_with_failover(request)

        # Both providers failed: the span still records the attempt, with no tokens and no cost.
        completion = result.completion or Completion(provider=self.provider, model=self.model)
        completion = completion.model_copy(
            update={
                "retry_count": result.retry_count,
                "provider_failover": result.failed_over,
                "limiter_wait_ms": limiter_wait_ms,
                "ttfb_ms": result.round_trip_ms,
                "cost_usd_estimate": estimate_cost_usd(
                    completion.model,
                    prompt_tokens=completion.prompt_tokens,
                    completion_tokens=completion.completion_tokens,
                    cache_creation_input_tokens=completion.cache_creation_input_tokens,
                    cache_read_input_tokens=completion.cache_read_input_tokens,
                ),
            }
        )
        span_id = record_llm_call(
            turn,
            request=request,
            completion=completion,
            started_at=started_at,
            status="error" if result.failure is not None else "ok",
            error_message=str(result.failure) if result.failure is not None else None,
        )
        if result.failure is not None:
            raise result.failure
        return completion.model_copy(update={"span_id": span_id})

    # -- internals ---------------------------------------------------------------------
    def _check_daily_cap(self, turn: TurnBuffer | None) -> None:
        """Counted from `llm_call` spans, so there is no second counter to drift (§9.8).

        The guard needs the trace store, which a turn implies; the live probe and the unit tests
        run without one and are not metered.
        """
        if turn is None or not self._daily_call_cap:
            return
        store = self._store or get_store()
        used = count_calls_today(store, self.provider)
        if used >= self._daily_call_cap:
            raise DailyCapExceeded(provider=self.provider, calls_today=used, cap=self._daily_call_cap)

    async def _call_with_failover(self, request: CompletionRequest) -> _Attempts:
        """At most one backoff retry on the primary, then `LLM_FALLBACK_*` (§9.8).

        `round_trip_ms` times the attempt that produced the answer, never the backoff sleep in
        front of it — the span's own `duration_ms` already covers the whole logical call, so
        `ttfb_ms` stays a provider-latency number the dashboard can compare across turns.
        """
        result = _Attempts()
        failure: ProviderError | None = None
        for attempt in (0, 1):
            try:
                result.completion = await self._timed(self.invoke(request), result)
                return result
            except ProviderError as exc:
                failure = exc
                if attempt == 1 or not exc.retryable:
                    break
                delay = exc.retry_after if exc.retry_after is not None else DEFAULT_BACKOFF_S
                if delay > MAX_BACKOFF_S:  # a long Retry-After: fail over now rather than park
                    break
                await asyncio.sleep(delay)
                result.retry_count += 1

        if failure is not None and failure.retryable and self._fallback is not None:
            result.failed_over = True
            try:
                result.completion = await self._timed(_invoke_fallback(self._fallback, request), result)
                return result
            except ProviderError as exc:
                # Both providers are down. The span still says a failover was attempted, so the
                # dashboard narrates a real outage rather than one provider having a bad day.
                failure = exc
        result.failure = failure
        return result

    @staticmethod
    async def _timed(awaitable: Awaitable[Completion], result: _Attempts) -> Completion:
        clock = time.monotonic()
        try:
            return await awaitable
        finally:
            result.round_trip_ms = max(0, round((time.monotonic() - clock) * 1000))


async def _invoke_fallback(fallback: ChatModel, request: CompletionRequest) -> Completion:
    """Run the fallback for one round trip.

    Through `invoke()`, so it records no second span and takes no second limiter token: one logical
    call is one span and one token, however many providers it took to answer.
    """
    if isinstance(fallback, RecordingAdapter):
        return await fallback.invoke(request)
    return await fallback.complete(
        request.messages,
        tools=request.tools,
        response_schema=request.response_schema,
        temperature=request.temperature,
        purpose=request.purpose,
    )
