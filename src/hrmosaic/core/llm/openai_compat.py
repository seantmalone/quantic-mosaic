"""The OpenAI-compatible adapter — the judge, the failover path and the free agent path (§9.8).

One adapter covers Gemini, OpenRouter, Cerebras and OpenAI, because they all speak
`POST /chat/completions`. Two details are the whole reason it exists as its own file:

* **tool-call arguments arrive as a JSON string.** They are always `json.loads`-ed here, never
  string-matched, so `ToolCall.args` is the same dict the Anthropic adapter produces (§3 row 5);
* **structured output degrades in three steps.** `response_format: {type: "json_schema", strict:
  true}` first; if the endpoint rejects strict mode — Gemini's compatibility layer is entitled to —
  the same schema is *prompted* instead, and if that answer will not parse, **one** repair round
  trip asks for the JSON alone. `structured_output_mode` records which of the three produced the
  answer, so the dashboard never has to guess. **All three steps share one deadline** — the
  logical call's, passed down from `RecordingAdapter` — because three unbounded 25 s round trips
  would be 75 s on their own, more than the 52 s the whole call is allowed. Each request is capped
  at what is left, and a step with nothing left is not sent at all.

The sync client is called through `asyncio.to_thread` for the same reason the Anthropic adapter is
(§2.1), and with `max_retries=0` so `RecordingAdapter` remains the single retry layer.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import openai

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
    strip_json_fences,
)
from hrmosaic.core.llm.limiter import TokenBucket
from hrmosaic.core.models import strict_json_schema

if TYPE_CHECKING:  # httpx2 is the HTTP layer the openai SDK ships; tests inject a MockTransport
    import httpx2

GOOGLE_AI_STUDIO_SIGNUP_URL = "https://aistudio.google.com/apikey"

STRICT = "json_schema_strict"
PROMPTED = "prompted_json"
PROMPTED_REPAIR = "prompted_json_repair"

PROMPTED_JSON_INSTRUCTION = (
    "Reply with a single JSON object and nothing else — no prose, no code fence. "
    "It must validate against this JSON Schema:\n{schema}"
)
REPAIR_INSTRUCTION = (
    "That reply was not valid JSON ({error}). Reply again with the JSON object alone, no prose and no code fence."
)


class OpenAICompatAdapter(RecordingAdapter):
    """Any `/chat/completions` endpoint. Defaults to the free Gemini model of §9.8."""

    provider = "openai_compat"

    def __init__(
        self,
        *,
        model: str = "gemini-3.5-flash-lite",
        base_url: str,
        api_key: str | None = None,
        api_key_variable: str = "LLM_API_KEY",
        signup_url: str = GOOGLE_AI_STUDIO_SIGNUP_URL,
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
        self._base_url = base_url
        self._api_key = api_key
        self._api_key_variable = api_key_variable
        self._signup_url = signup_url
        self._http_client = http_client
        self._client: openai.OpenAI | None = None

    @property
    def configured(self) -> bool:
        """`/health.llm.*.configured` — whether a credential is present (§11.4)."""
        return bool(self._api_key)

    def client(self) -> openai.OpenAI:
        """Built on first use, never at import: a missing key must not stop the app booting."""
        if self._client is None:
            if not self._api_key:
                raise MissingCredentialError(self._api_key_variable, self._signup_url)
            self._client = openai.OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_S,
                max_retries=0,
                http_client=self._http_client,
            )
        return self._client

    # -- the round trip -----------------------------------------------------------------
    async def invoke(self, request: CompletionRequest, deadline: Deadline | None = None) -> Completion:
        """The one-to-three round trips of the degradation ladder, all inside `deadline`."""
        if request.response_schema is None:
            return await self._chat(request.messages, request, deadline)

        schema = strict_json_schema(request.response_schema)
        try:
            return await self._chat(
                request.messages, request, deadline, response_format=_strict_format(request, schema)
            )
        except ProviderError as exc:
            if not _rejects_strict_mode(exc):
                raise

        prompted = list(request.messages) + [
            Message(role="user", content=PROMPTED_JSON_INSTRUCTION.format(schema=json.dumps(schema)))
        ]
        completion = await self._chat(prompted, request, deadline, mode=PROMPTED)
        try:
            json.loads(strip_json_fences(completion.text))
        except json.JSONDecodeError as exc:
            repaired = prompted + [
                Message(role="assistant", content=completion.text),
                Message(role="user", content=REPAIR_INSTRUCTION.format(error=exc)),
            ]
            completion = await self._chat(repaired, request, deadline, mode=PROMPTED_REPAIR)
        return completion

    async def _chat(
        self,
        messages: Sequence[Message],
        request: CompletionRequest,
        deadline: Deadline | None = None,
        *,
        response_format: dict[str, Any] | None = None,
        mode: str | None = None,
    ) -> Completion:
        client = self.client()
        resolved_mode = STRICT if response_format is not None else mode
        kwargs = self.request_kwargs(messages, tools=request.tools, temperature=request.temperature)
        if response_format is not None:
            kwargs["response_format"] = response_format
        # Raises before anything reaches the wire once the budget is spent, so the ladder degrades
        # in however many steps it has time for and never one step more.
        kwargs["timeout"] = round_trip_timeout(deadline, what=f"{self.model} {resolved_mode or 'chat'}")
        try:
            # The SDK client is synchronous; §2.1 forbids blocking the single worker's loop.
            response = await asyncio.to_thread(lambda: client.chat.completions.create(**kwargs))
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise ProviderError(f"{self.model} transport failure: {exc}", retryable=True) from exc
        except openai.APIStatusError as exc:
            raise status_error(exc.status_code, f"{self.model} {exc.status_code}: {exc}", exc.response.headers) from exc
        return self._to_completion(response, mode=resolved_mode)

    def request_kwargs(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSchema] = (),
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """The exact `chat.completions.create` keyword arguments — what the shape tests read."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [_wire_message(message) for message in messages],
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in tools
            ]
        return kwargs

    def _to_completion(self, response: Any, *, mode: str | None) -> Completion:
        choice = response.choices[0]
        message = choice.message
        tool_calls = []
        for call in message.tool_calls or []:
            # The OpenAI shape delivers arguments as a JSON **string** — always parse, never match.
            tool_calls.append(
                ToolCall(id=call.id or "", name=call.function.name, args=_parse_arguments(call.function.arguments))
            )
        usage = getattr(response, "usage", None)
        return Completion(
            text=message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            provider=self.provider,
            # The configured id, for the same reason the Anthropic adapter uses it: `MODEL_PRICES`
            # and the §10.1 span name key on what was configured, not on what the endpoint echoes.
            model=self.model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            structured_output_mode=mode,
        )


def _strict_format(request: CompletionRequest, schema: dict[str, Any]) -> dict[str, Any]:
    name = request.response_schema.__name__ if request.response_schema is not None else "response"
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


def _rejects_strict_mode(exc: ProviderError) -> bool:
    """A 400 naming the response format is the endpoint declining strict mode, not a bad prompt."""
    if exc.status != 400:
        return False
    text = str(exc).lower()
    return any(marker in text for marker in ("response_format", "json_schema", "strict", "schema"))


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"tool-call arguments were not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProviderError(f"tool-call arguments were {type(parsed).__name__}, not an object")
    return parsed


def _wire_message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id or "", "content": message.content}
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.args, ensure_ascii=False)},
                }
                for call in message.tool_calls
            ],
        }
    return {"role": message.role, "content": message.content}
