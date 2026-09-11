"""`CachedAdapter` — the optional wrapper, **off by default** (spec §9.8, §22).

`LLM_CACHE_TTL_S` defaults to `0`, which disables it entirely; at `0` this class is a pure
pass-through and the wrapped adapter is called every time. Its only two jobs are warming the two
demo prompts before recording and making an eval re-run after a scoring change cheap. It is
**disabled during every eval latency measurement**, and it is never a correctness mechanism: no
test asserts a cache hit and no committed artifact depends on one.

Keyed by `sha256(provider|model|temperature|messages|tools)` against the `llm_cache` table (§10.1).
A hit still writes its own `llm_call` span with `cache_hit: true`, so "exactly one `llm_call` span
per logical call" holds on both branches and a warmed demo is visible on the dashboard as warmed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from pydantic import BaseModel

from hrmosaic.core.db import Store, get_store, now_micros
from hrmosaic.core.llm.base import (
    ChatModel,
    Completion,
    CompletionRequest,
    DeltaSink,
    Message,
    ToolSchema,
    record_llm_call,
)
from hrmosaic.core.models import LlmPurpose
from hrmosaic.core.trace import TurnBuffer

CACHE_SELECT = "SELECT created_at, response_json FROM llm_cache WHERE key = ?"
CACHE_UPSERT = """
INSERT INTO llm_cache (key, created_at, provider, model, response_json, prompt_tokens, completion_tokens)
VALUES (?,?,?,?,?,?,?)
ON CONFLICT(key) DO UPDATE SET created_at = excluded.created_at, response_json = excluded.response_json,
                               prompt_tokens = excluded.prompt_tokens,
                               completion_tokens = excluded.completion_tokens
"""


class CachedAdapter:
    """Wraps any `ChatModel`. At `ttl_s <= 0` it is transparent."""

    def __init__(self, inner: ChatModel, *, ttl_s: int, store: Store | None = None) -> None:
        self.inner = inner
        self.ttl_s = ttl_s
        self._store = store

    @property
    def provider(self) -> str:
        return self.inner.provider

    @property
    def model(self) -> str:
        return self.inner.model

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSchema] | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        purpose: LlmPurpose = "act",
        turn: TurnBuffer | None = None,
        on_delta: DeltaSink | None = None,
    ) -> Completion:
        if self.ttl_s <= 0:
            return await self.inner.complete(
                messages,
                tools=tools,
                response_schema=response_schema,
                temperature=temperature,
                purpose=purpose,
                turn=turn,
                on_delta=on_delta,
            )

        request = CompletionRequest(
            messages=list(messages),
            tools=list(tools or []),
            response_schema=response_schema,
            temperature=temperature,
            purpose=purpose,
            on_delta=on_delta,
        )
        store = self._store or get_store()
        key = cache_key(provider=self.provider, model=self.model, request=request)
        started_at = now_micros()
        row = store.execute(CACHE_SELECT, (key,)).one()
        if row is not None and now_micros() - int(row["created_at"]) <= self.ttl_s * 1_000_000:
            # A hit made no round trip, so it neither streamed nor has a time to first byte —
            # whatever the stored response said about the call that filled the entry.
            hit = Completion.model_validate_json(row["response_json"]).model_copy(
                update={
                    "cache_hit": True,
                    "cost_usd_estimate": 0.0,
                    "span_id": None,
                    "streamed": False,
                    "ttfb_ms": 0,
                }
            )
            # No `step_started` on this branch: a hit makes no round trip, so there is no step in
            # flight to narrate, and the wrapped adapter — which announces its own — is not called.
            span_id = record_llm_call(turn, request=request, completion=hit, started_at=started_at)
            return hit.model_copy(update={"span_id": span_id})

        completion = await self.inner.complete(
            messages,
            tools=tools,
            response_schema=response_schema,
            temperature=temperature,
            purpose=purpose,
            turn=turn,
            on_delta=on_delta,
        )
        store.execute(
            CACHE_UPSERT,
            (
                key,
                now_micros(),
                completion.provider,
                completion.model,
                completion.model_dump_json(),
                completion.prompt_tokens,
                completion.completion_tokens,
            ),
        )
        return completion


def cache_key(*, provider: str, model: str, request: CompletionRequest) -> str:
    """`sha256(provider|model|temperature|messages|tools)` (§10.1). The schema joins the messages,
    because two calls differing only in their response schema are two different calls."""
    material = json.dumps(
        {
            "provider": provider,
            "model": model,
            "temperature": request.temperature,
            "purpose": request.purpose,
            "messages": [message.model_dump(mode="json") for message in request.messages],
            "tools": [tool.model_dump(mode="json") for tool in request.tools],
            "response_schema": request.response_schema.__name__ if request.response_schema else None,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
