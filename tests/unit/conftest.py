"""Wire fixtures for the provider adapters (spec §9.8, §16.1).

Both SDKs ship `httpx2` as their HTTP layer, so a `httpx2.MockTransport` is what lets CI verify
the exact bytes each adapter puts on the wire with no key and no network. Every fixture here
records the requests it served, because the shape of the request *is* what the adapter tests
assert: no `strict` on the tool definitions, the `cache_control` breakpoint on the last system
block, `temperature` in `extra_body`, the strict `response_format` on the OpenAI-compatible path.

**Streaming (W2-E).** `AnthropicAdapter.invoke` calls `client.messages.stream`, which puts
`"stream": true` on the wire and then *requires* an `text/event-stream` body — a JSON message body
makes the SDK raise before any test assertion runs. Rather than rewrite the 36 call sites, the
handler below serves the **same** `(status, payload)` a test already declares and renders it as the
event sequence the SDK's accumulator expects (`message_start` → per block `content_block_start` /
`content_block_delta` × n / `content_block_stop` → `message_delta` → `message_stop`) whenever the
request asked to stream. So one fixture describes both wire shapes, a non-streaming adapter is
untouched, and a streamed call and a non-streamed one are asserted against a single recorded
response — which is what `test_stream_completion_parity` needs in order to mean anything.

It also owns the retrieval fixtures (P4): one `corpus_mini` ingest per session, built with the fake
embedder so the unit suite stays offline, and the connection and settings shims that read it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest

#: How many characters of a text block travel in one `text_delta` frame. Small enough that every
#: fixture body is delivered as several deltas, so a test that counts them has something to count.
STREAM_CHUNK_CHARS = 8


def anthropic_stream_body(payload: dict[str, Any], *, chunk: int = STREAM_CHUNK_CHARS) -> str:
    """One `POST /v1/messages` **streamed** body, rendered from the same message the JSON path serves.

    Deliberately the whole sequence and not a shortcut: `message_start` carries the input-token and
    cache counters, `message_delta` carries the final `stop_reason` and `output_tokens`, and a
    `tool_use` block's arguments arrive as `input_json_delta` fragments — which is the one path by
    which a hand-rolled accumulator could move a `ToolSelection`, and therefore the one this fixture
    has to reproduce faithfully.
    """
    message = {key: value for key, value in payload.items() if key not in {"content", "usage"}}
    usage = dict(payload.get("usage") or {})
    frames: list[str] = []

    def frame(event: dict[str, Any]) -> None:
        frames.append(f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n")

    opening = {key: value for key, value in usage.items() if key != "output_tokens"} | {"output_tokens": 0}
    frame(
        {
            "type": "message_start",
            "message": {**message, "content": [], "stop_reason": None, "stop_sequence": None, "usage": opening},
        }
    )
    for index, block in enumerate(payload.get("content") or []):
        if block.get("type") == "tool_use":
            start = {"type": "tool_use", "id": block.get("id", ""), "name": block.get("name", ""), "input": {}}
            body = json.dumps(block.get("input") or {}, ensure_ascii=False)
            delta_key, delta_type = "partial_json", "input_json_delta"
        else:
            start = {"type": "text", "text": ""}
            body = block.get("text") or ""
            delta_key, delta_type = "text", "text_delta"
        frame({"type": "content_block_start", "index": index, "content_block": start})
        for offset in range(0, len(body), chunk):
            frame(
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": delta_type, delta_key: body[offset : offset + chunk]},
                }
            )
        frame({"type": "content_block_stop", "index": index})
    frame(
        {
            "type": "message_delta",
            "delta": {"stop_reason": payload.get("stop_reason"), "stop_sequence": payload.get("stop_sequence")},
            "usage": {"output_tokens": int(usage.get("output_tokens") or 0)},
        }
    )
    frame({"type": "message_stop"})
    return "".join(frames)


def _wants_stream(body: dict[str, Any]) -> bool:
    return bool(body.get("stream"))


def _is_anthropic_message(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("type") == "message"


def _client(responses: list[Any], recorded: list[dict[str, Any]]) -> httpx2.Client:
    queue = list(responses)

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content) if request.content else {}
        recorded.append({"url": str(request.url), "headers": dict(request.headers), "body": body})
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(item):
            return item(request)
        status, payload = item
        # A streamed request needs a streamed body; anything else — an error status, an
        # OpenAI-shaped completion — is served exactly as the test declared it.
        if status == 200 and _wants_stream(body) and _is_anthropic_message(payload):
            return httpx2.Response(
                status,
                content=anthropic_stream_body(payload).encode("utf-8"),
                headers={"content-type": "text/event-stream"},
            )
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


REPO_ROOT = Path(__file__).resolve().parents[2]
#: One tiny document per format (spec §16.5) — never the real fourteen.
CORPUS_MINI = REPO_ROOT / "tests" / "fixtures" / "corpus_mini"


@pytest.fixture(scope="session")
def mini_ingest(tmp_path_factory) -> Any:
    """One `EMBED_PROVIDER=fake` ingest of `corpus_mini`, built once for the session.

    The fake embedder keeps it offline and instant; `index_meta.embed_model` is then
    `fake-hash-384`, which is exactly what `open_index()`'s mismatch guard rejects — so every test
    that reads this index either opens it with `check=False` or declares `fake_embedder`.
    """
    from hrmosaic.rag import ingest as ingest_module
    from hrmosaic.settings import settings

    directory = tmp_path_factory.mktemp("mini_index")
    previous = settings.embed_provider
    settings.embed_provider = "fake"
    try:
        return ingest_module.ingest(
            CORPUS_MINI,
            index_path=directory / "mini.sqlite",
            manifest_path=directory / "chunks.manifest.jsonl",
            report_path=directory / "ingest_report.json",
        )
    finally:
        settings.embed_provider = previous


@pytest.fixture
def mini_index(mini_ingest):
    """A read-only connection to the mini index, guard bypassed (it is a fake-embedder index)."""
    from hrmosaic.rag.index import open_index

    connection = open_index(mini_ingest.index_path, check=False)
    yield connection
    connection.close()


@pytest.fixture
def fake_embedder(monkeypatch):
    """Run the calling test against `EMBED_PROVIDER=fake`, so no ONNX model is loaded."""
    from hrmosaic.settings import settings

    monkeypatch.setattr(settings, "embed_provider", "fake")
