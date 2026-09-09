"""Wire fixtures for the provider adapters (spec §9.8, §16.1).

Both SDKs ship `httpx2` as their HTTP layer, so a `httpx2.MockTransport` is what lets CI verify
the exact bytes each adapter puts on the wire with no key and no network. Every fixture here
records the requests it served, because the shape of the request *is* what the adapter tests
assert: no `strict` on the tool definitions, the `cache_control` breakpoint on the last system
block, `temperature` in `extra_body`, the strict `response_format` on the OpenAI-compatible path.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest


def _client(responses: list[Any], recorded: list[dict[str, Any]]) -> httpx2.Client:
    queue = list(responses)

    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": json.loads(request.content) if request.content else {},
            }
        )
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(item):
            return item(request)
        status, payload = item
        return httpx2.Response(status, json=payload)

    return httpx2.Client(transport=httpx2.MockTransport(handler))


@pytest.fixture
def wire() -> Callable[[list[Any]], tuple[httpx2.Client, list[dict[str, Any]]]]:
    """`client, recorded = wire([...])` — the last response repeats, so identical calls are easy."""

    def build(responses: list[Any]) -> tuple[httpx2.Client, list[dict[str, Any]]]:
        recorded: list[dict[str, Any]] = []
        return _client(responses, recorded), recorded

    return build


@pytest.fixture
def anthropic_response() -> Callable[..., tuple[int, dict[str, Any]]]:
    """A `POST /v1/messages` body in the shape the SDK parses."""

    def build(
        *,
        content: list[dict[str, Any]] | None = None,
        stop_reason: str = "end_turn",
        input_tokens: int = 11,
        output_tokens: int = 7,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        model: str = "claude-haiku-4-5",
    ) -> tuple[int, dict[str, Any]]:
        return 200, {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content if content is not None else [{"type": "text", "text": "ok"}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "cache_read_input_tokens": cache_read_input_tokens,
            },
        }

    return build


@pytest.fixture
def openai_response() -> Callable[..., tuple[int, dict[str, Any]]]:
    """A `POST /chat/completions` body in the shape the SDK parses."""

    def build(
        *,
        content: str | None = "ok",
        tool_calls: list[dict[str, Any]] | None = None,
        finish_reason: str = "stop",
        prompt_tokens: int = 11,
        completion_tokens: int = 7,
        model: str = "gemini-3.5-flash-lite",
    ) -> tuple[int, dict[str, Any]]:
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
        return 200, {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1_760_000_000,
            "model": model,
            "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    return build
