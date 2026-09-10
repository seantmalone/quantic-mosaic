"""The agent's adapter — Anthropic `claude-haiku-4-5`, a genuinely non-OpenAI wire shape (§9.8).

Every choice here is the spec's, and several are corrections to what a 1.x-era paste would write:

* the official `anthropic` SDK **1.x sync** client, called as
  `await asyncio.to_thread(client.messages.create, …)`, because §2.1 forbids blocking the single
  worker's event loop and the SDK's sync client is what the type stubs actually describe;
* `timeout=25` s with **`max_retries=0`**: the SDK's own retry layer is off, so `RecordingAdapter`'s
  one backoff plus one failover is the single retry layer (§9.4's arithmetic depends on it). Each
  request is sent with `timeout=round_trip_timeout(deadline)`, so a second attempt gets what is
  left of the logical call's 52 s budget rather than a fresh 25 s;
* **`extra_body={"temperature": 0}`** — SDK 1.x removed the `temperature` keyword (passing it
  raises `TypeError`) while the API still honours the field on `claude-haiku-4-5`;
* **no `strict` on the tool definitions.** The nine published `input_schema` blocks keep `default`
  values, an open `additionalProperties` sub-schema and a root `oneOf`, none of which strict tool
  use admits; arguments are validated server-side against the same committed schemas (§8.4);
* `output_config.format` for constrained JSON on route / synthesize / repair, so there is **no**
  prompted-JSON fallback on this path — that lives only in `OpenAICompatAdapter`;
* one `cache_control {"type": "ephemeral"}` breakpoint on the **last system block**. A breakpoint
  marks the *end* of the cached prefix and Anthropic renders a request as *tools → system →
  messages*, so this caches the whole stable head. On the last tool definition it would cache the
  tools alone and re-bill the system prompt every call. Caching is **best effort**: Haiku 4.5's
  minimum cacheable prefix is 4096 tokens and a shorter prefix silently writes no entry, which is
  why the span *records* the two cache counters rather than anything asserting them;
* no extended thinking and no assistant prefill; `max_tokens` 1024 / 2048 / 512 by purpose.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import anthropic

from hrmosaic.core.db import Store
from hrmosaic.core.llm.base import (
    LOGICAL_CALL_BUDGET_S,
    REQUEST_TIMEOUT_S,
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
    round_trip_timeout,
    status_error,
    without_root_combinators,
)
from hrmosaic.core.llm.limiter import TokenBucket
from hrmosaic.core.models import LlmPurpose, strict_json_schema

if TYPE_CHECKING:  # httpx2 is the HTTP layer the anthropic SDK ships; tests inject a MockTransport
    import httpx2

ANTHROPIC_SIGNUP_URL = "https://console.anthropic.com/settings/keys"

#: Spec §9.8. Anything unnamed there (`act`, and the judge purposes if ever pointed here) takes the
#: route budget: a tool-use turn emits a handful of small `tool_use` blocks, not prose.
MAX_TOKENS: dict[str, int] = {"route": 1024, "synthesize": 2048, "repair": 512}
DEFAULT_MAX_TOKENS = 1024

#: Haiku 4.5's minimum cacheable prefix — the highest of any current model. Below it a request
#: writes no cache entry and reports zeros, with no error (§9.8; re-read at P6 and P10 step 0).
MIN_CACHEABLE_PREFIX_TOKENS = 4096

CACHE_CONTROL: dict[str, str] = {"type": "ephemeral"}


class AnthropicAdapter(RecordingAdapter):
    """`claude-haiku-4-5` — the pinned agent model (§3 row 6, §21 row 46)."""

    provider = "anthropic"

    def __init__(
        self,
        *,
        model: str = "claude-haiku-4-5",
        api_key: str | None = None,
        limiter: TokenBucket | None = None,
        fallback: ChatModel | None = None,
        daily_call_cap: int | None = None,
        store: Store | None = None,
        call_budget_s: float = LOGICAL_CALL_BUDGET_S,
        http_client: httpx2.Client | None = None,
    ) -> None:
        super().__init__(
            model=model,
            limiter=limiter,
            fallback=fallback,
            daily_call_cap=daily_call_cap,
            store=store,
            call_budget_s=call_budget_s,
        )
        self._api_key = api_key
        self._http_client = http_client
        self._client: anthropic.Anthropic | None = None

    # -- the client ---------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        """`/health.llm.agent.configured` — whether a credential is present (§11.4)."""
        return bool(self._api_key)

    def client(self) -> anthropic.Anthropic:
        """Built on first use, never at import: a missing key must not stop the app booting."""
        if self._client is None:
            if not self._api_key:
                raise MissingCredentialError("ANTHROPIC_API_KEY", ANTHROPIC_SIGNUP_URL)
            self._client = anthropic.Anthropic(
                api_key=self._api_key,
                timeout=REQUEST_TIMEOUT_S,
                max_retries=0,
                http_client=self._http_client,
            )
        return self._client

    # -- the round trip -----------------------------------------------------------------
    async def invoke(self, request: CompletionRequest, deadline: Deadline | None = None) -> Completion:
        client = self.client()
        kwargs = self.request_kwargs(
            request.messages,
            tools=request.tools,
            response_schema=request.response_schema,
            purpose=request.purpose,
            temperature=request.temperature,
        )
        # One round trip, never longer than what is left of the logical call: the client's own
        # `timeout=25` is the ceiling, the deadline lowers it when this is the second attempt.
        kwargs["timeout"] = round_trip_timeout(deadline, what="anthropic")
        try:
            # The SDK client is synchronous; §2.1 forbids blocking the single worker's loop.
            response = await asyncio.to_thread(lambda: client.messages.create(**kwargs))
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise ProviderError(f"anthropic transport failure: {exc}", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise status_error(exc.status_code, f"anthropic {exc.status_code}: {exc}", exc.response.headers) from exc
        return self._to_completion(response, structured="output_config" in kwargs)

    def request_kwargs(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSchema] = (),
        response_schema: type | None = None,
        purpose: LlmPurpose = "act",
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """The exact `messages.create` keyword arguments — the shape the MockTransport tests read."""
        system_blocks, conversation = _split_system(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS.get(purpose, DEFAULT_MAX_TOKENS),
            "messages": conversation,
            # SDK 1.x removed the `temperature` keyword; the API still honours the field.
            "extra_body": {"temperature": temperature},
        }
        if system_blocks:
            kwargs["system"] = system_blocks
        if tools:
            kwargs["tools"] = [_tool_payload(tool) for tool in tools]
        if response_schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": strict_json_schema(response_schema)}}
        return kwargs

    def count_prefix_tokens(self, *, system: Sequence[Message] | str, tools: Sequence[ToolSchema] = ()) -> int:
        """Tokens in the cacheable *tools → system* prefix — what decides the 4096-token floor.

        Used by `scripts/probe_provider.py`, which arms its cache assertion only above the floor.
        """
        messages = [Message(role="system", content=system)] if isinstance(system, str) else list(system)
        system_blocks, _ = _split_system(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            # count_tokens needs a non-empty conversation; one token of user text is the floor.
            "messages": [{"role": "user", "content": "."}],
        }
        if system_blocks:
            kwargs["system"] = system_blocks
        if tools:
            kwargs["tools"] = [_tool_payload(tool) for tool in tools]
        return int(self.client().messages.count_tokens(**kwargs).input_tokens)

    # -- response translation ------------------------------------------------------------
    def _to_completion(self, response: Any, *, structured: bool) -> Completion:
        text_parts: list[str] = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                # Anthropic delivers tool input as a parsed object; the OpenAI shape delivers a
                # JSON string. Both land in `args` as the same dict (§3 row 5).
                tool_calls.append(ToolCall(id=block.id, name=block.name, args=dict(block.input or {})))
        usage = response.usage
        return Completion(
            text="".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=response.stop_reason,
            provider=self.provider,
            # The **configured** id, not the dated snapshot the API echoes back
            # (`claude-haiku-4-5` → `claude-haiku-4-5-20251001`, observed 2026-09-09): that is what
            # §10.1's span name shows, what `LLM_MODEL` pins and what `MODEL_PRICES` keys on, so a
            # snapshot roll can never silently zero out the cost estimate.
            model=self.model,
            prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cache_creation_input_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            cache_read_input_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            structured_output_mode="output_config_json_schema" if structured else None,
        )


def _tool_payload(tool: ToolSchema) -> dict[str, Any]:
    """One tool as Anthropic accepts it: as published, minus the top-level combinators it rejects.

    No `strict` — the nine published schemas keep their defaults and their open sub-schema, none of
    which strict tool use admits, and arguments are validated server-side instead (§8.4, §9.8).
    """
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": without_root_combinators(tool.input_schema),
    }


def _flatten(blocks: list[dict[str, Any]]) -> Any:
    """One text block travels as a plain string; anything else stays a block list."""
    if not blocks:
        return ""
    if len(blocks) == 1 and blocks[0].get("type") == "text" and set(blocks[0]) == {"type", "text"}:
        return blocks[0]["text"]
    return blocks


def _split_system(messages: Sequence[Message]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Anthropic carries the system prompt outside `messages`; the last block gets the breakpoint.

    Roles must **alternate** on the Messages API, and every `tool_use` block must be answered by a
    `tool_result` block in the *immediately following* message. The provider-neutral `Message`
    carries one tool result each (`tool_call_id` is singular), so an act step that asked for two
    tools produces two neutral `tool` messages — and one user message per result would break both
    rules at once. Consecutive same-role messages are therefore **coalesced** into a single message
    whose content is the concatenation of their blocks, which puts every `tool_result` of a step in
    the one user turn that answers the assistant's `tool_use` blocks, in order, results first.
    """
    system_blocks: list[dict[str, Any]] = []
    conversation: list[tuple[str, list[dict[str, Any]]]] = []

    def emit(role: str, blocks: list[dict[str, Any]]) -> None:
        if conversation and conversation[-1][0] == role:
            conversation[-1][1].extend(blocks)
        else:
            conversation.append((role, list(blocks)))

    for message in messages:
        if message.role == "system":
            system_blocks.append({"type": "text", "text": message.content})
        elif message.role == "tool":
            emit(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id or "",
                        "content": message.content,
                    }
                ],
            )
        elif message.role == "assistant" and message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks += [
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.args}
                for call in message.tool_calls
            ]
            emit("assistant", blocks)
        else:
            emit(message.role, [{"type": "text", "text": message.content}] if message.content else [])
    if system_blocks:
        # One breakpoint, on the LAST system block: the cached prefix is then tools → system.
        system_blocks[-1] = {**system_blocks[-1], "cache_control": CACHE_CONTROL}
    return system_blocks, [{"role": role, "content": _flatten(blocks)} for role, blocks in conversation]
