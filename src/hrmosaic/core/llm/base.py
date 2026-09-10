"""The `ChatModel` protocol, the shared wire types, and the one recording call path (spec §9.8).

Everything a provider-specific adapter must not reinvent lives here:

* **the types** — `Message`, `ToolSchema`, `ToolCall`, `Completion`. Tool-call arguments are
  normalised at this boundary: OpenAI-shaped endpoints deliver a JSON **string**, Anthropic a
  parsed **object**, and both arrive in `ToolCall.args` as the same dict (§3 row 5);
* **the limiter, the spend guard, the one backoff, the failover and the call budget** — an adapter
  implements `invoke()` for one attempt and inherits the rest, so `retry_count`,
  `provider_failover` and the 52 s bound on a logical call can never mean different things in two
  adapters;
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

#: `Retry-After` is honoured **up to** this cap; a longer one goes straight to the second round
#: trip rather than parking the turn.
MAX_BACKOFF_S = 2.0

#: One request may not outlive this, and the SDKs' own retry layers are off (`max_retries=0`), so
#: the backoff-then-failover below is the single retry layer in the system.
REQUEST_TIMEOUT_S = 25.0

#: **The bound on one logical call**: 25 + 2 + 25 = 52 s, inside `AGENT_WALL_CLOCK_S` (= 90, §9.4).
#:
#: That arithmetic only holds if a logical call is **two** round trips with one bounded backoff
#: between them — so the second attempt is the failover *or* a second try at the primary, never
#: both — and if a multi-round-trip `invoke()` (the OpenAI-compatible adapter's strict → prompted →
#: repair ladder, itself up to three round trips) cannot outlive its slot. Neither is left to
#: arithmetic: every call carries a `Deadline`, each round trip is capped at what is left of it,
#: and `complete()` wraps the whole thing in `asyncio.timeout`. The bound therefore survives an
#: adapter that grows a fourth degradation step, or a transport that ignores its own timeout.
LOGICAL_CALL_BUDGET_S = REQUEST_TIMEOUT_S + MAX_BACKOFF_S + REQUEST_TIMEOUT_S

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


#: JSON Schema's top-level combinators. **Neither** provider accepts one at the root of a tool's
#: parameter schema: the Anthropic Messages API answers 400 `input_schema does not support oneOf,
#: allOf, or anyOf at the top level` (verified live 2026-09-09), and Gemini's OpenAI-compatible
#: layer rejects a root combinator on `tools[].function.parameters` the same way. `get_policy_section`
#: publishes a root `oneOf` because §8.4 requires its exactly-one-selector rule *in the schema*, so
#: every adapter drops these three keys on the way out — and none of them rewrites what the server
#: publishes: the committed schema stays the one the MCP server validates arguments against.
ROOT_COMBINATOR_KEYS = ("oneOf", "allOf", "anyOf")


def without_root_combinators(input_schema: dict[str, Any]) -> dict[str, Any]:
    """A tool's parameter schema minus the top-level combinators no provider accepts.

    Nothing else is touched: `default` values and open sub-schemas travel as published, nested
    combinators are untouched, and the selector rule is still enforced where §8.4 says it is —
    server-side, where neither selector returns `isError {"code": "INVALID_ARGUMENTS"}`.
    """
    if not any(key in input_schema for key in ROOT_COMBINATOR_KEYS):
        return input_schema
    return {key: value for key, value in input_schema.items() if key not in ROOT_COMBINATOR_KEYS}


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
# The budget
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Deadline:
    """When this logical call must be over, on the monotonic clock.

    One deadline is minted per `complete()` and handed down to every round trip, so an adapter with
    a multi-step `invoke()` spends the *same* budget the retry layer is spending rather than a
    fresh 25 s per step. `remaining_s` is what a round trip may take; at zero the adapter refuses
    to put another request on the wire instead of starting one it cannot finish.
    """

    expires_at: float

    @classmethod
    def after(cls, budget_s: float) -> Deadline:
        return cls(time.monotonic() + budget_s)

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining_s <= 0.0


def round_trip_timeout(deadline: Deadline | None, *, what: str) -> float:
    """The timeout for the next round trip: `min(25 s, what is left of the logical call)`.

    Raises rather than returning a useless sliver, and non-retryably: with the budget gone there is
    no time for a failover either, so the honest answer is to stop now and record the attempt.
    With no deadline (the live probe, a bare unit test) it is the plain per-request timeout.
    """
    if deadline is None:
        return REQUEST_TIMEOUT_S
    remaining = deadline.remaining_s
    if remaining <= 0.0:
        raise ProviderError(f"{what}: the logical call's budget is spent", retryable=False)
    return min(REQUEST_TIMEOUT_S, remaining)


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
    """The shared half of every adapter: cap, limiter, one backoff, one failover, one span.

    A subclass implements `invoke(request, deadline)` — the round trip(s) for one attempt,
    returning a `Completion` with `text`, `tool_calls`, the token counts and
    `structured_output_mode` filled in — and raises `ProviderError` for anything the transport or
    the endpoint reported. It must cap each request it sends at `round_trip_timeout(deadline)`.
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
        call_budget_s: float = LOGICAL_CALL_BUDGET_S,
    ) -> None:
        self.model = model
        self._limiter = limiter
        self._fallback = fallback
        self._daily_call_cap = daily_call_cap
        self._store = store
        self.call_budget_s = call_budget_s

    # -- the subclass seam -------------------------------------------------------------
    async def invoke(self, request: CompletionRequest, deadline: Deadline | None = None) -> Completion:
        """One attempt, inside `deadline`. Raises `ProviderError`; never retries, never records."""
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
        result = _Attempts()
        try:
            # The hard bound. `_call_with_failover` already spends the same budget round trip by
            # round trip; this is the outer belt, so a transport that ignores its own timeout — or
            # an adapter that grows another degradation step — still cannot outlive the slot the
            # agent loop allotted it (§9.4: 52 s inside `AGENT_WALL_CLOCK_S` = 90).
            async with asyncio.timeout(self.call_budget_s):
                await self._call_with_failover(request, Deadline.after(self.call_budget_s), result)
        except TimeoutError:
            result.failure = ProviderError(
                f"the logical call exceeded its {self.call_budget_s:g} s budget", retryable=False
            )

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

    async def _call_with_failover(self, request: CompletionRequest, deadline: Deadline, result: _Attempts) -> None:
        """One backoff, then failover: **two** round trips at most, which is what makes 52 s real.

        The primary is tried once. A retryable failure buys one bounded backoff and then exactly
        one more attempt — the `LLM_FALLBACK_*` model when one is configured (§9.8), the primary
        again when none is. Running the primary twice *and then* the fallback would be three round
        trips, and 25 + 2 + 25 + 25 = 77 s is not the bound the brief specifies.

        `result` is filled in place so the span still records a call the outer `asyncio.timeout`
        cut short. `round_trip_ms` times the attempt that produced the answer, never the backoff
        sleep in front of it — the span's own `duration_ms` already covers the whole logical call,
        so `ttfb_ms` stays a provider-latency number the dashboard can compare across turns.
        """
        try:
            result.completion = await self._timed(self.invoke(request, deadline), result)
            return
        except ProviderError as exc:
            failure = exc

        if not failure.retryable:
            result.failure = failure
            return

        delay = failure.retry_after if failure.retry_after is not None else DEFAULT_BACKOFF_S
        # A long `Retry-After` is not worth parking the turn for, and neither is a backoff that
        # would eat the budget the second attempt needs.
        if delay <= MAX_BACKOFF_S and delay < deadline.remaining_s:
            await asyncio.sleep(delay)
            result.retry_count += 1

        if self._fallback is not None:
            result.failed_over = True
            second = _invoke_fallback(self._fallback, request, deadline)
        else:
            second = self.invoke(request, deadline)
        try:
            result.completion = await self._timed(second, result)
        except ProviderError as exc:
            # Both attempts failed. When a fallback was tried the span still says so, so the
            # dashboard narrates a real outage rather than one provider having a bad day.
            result.failure = exc

    @staticmethod
    async def _timed(awaitable: Awaitable[Completion], result: _Attempts) -> Completion:
        clock = time.monotonic()
        try:
            return await awaitable
        finally:
            result.round_trip_ms = max(0, round((time.monotonic() - clock) * 1000))


async def _invoke_fallback(fallback: ChatModel, request: CompletionRequest, deadline: Deadline) -> Completion:
    """Run the fallback for one attempt, inside what is left of the same deadline.

    Through `invoke()`, so it records no second span, takes no second limiter token and — the point
    of passing the deadline down — spends the remainder of the logical call's budget rather than
    starting a fresh 25 s (or, with its degradation ladder, a fresh 75 s) of its own.
    """
    if isinstance(fallback, RecordingAdapter):
        return await fallback.invoke(request, deadline)
    return await fallback.complete(
        request.messages,
        tools=request.tools,
        response_schema=request.response_schema,
        temperature=request.temperature,
        purpose=request.purpose,
    )
