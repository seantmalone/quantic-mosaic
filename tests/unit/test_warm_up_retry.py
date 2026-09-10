"""The `/ready` warm-up retries its one loopback `tools/call` inside the deadline (spec §11.4).

The handshake half of `_warm_up` has always been retried until `READY_WARMUP_TIMEOUT_S`, because a
socket uvicorn has not finished binding refuses the first connection. The `tools/call` half had
exactly one attempt — so a single slow or dropped first call latched `app.state.ready = False` for
the life of the process, which is precisely what happened on the deployed instance: `/health` was
`ok` and `POST /chat` answered, while `/ready` stayed 503 with
`warm-up call failed: … SSE stream ended without a response` until the next deploy.

Both halves now share one deadline. It is checked **between** attempts only: a call already on the
wire is bounded by the transport's own read timeout and is never cancelled mid-flight, because the
first call is the one loading the ONNX session and cancelling it would throw away the very work
readiness is waiting for.

Time here is virtual. `_warm_up` reads the clock through the running loop, so the tests swap in a
loop stand-in whose `time()` moves only when the patched `asyncio.sleep` says so — the deadline
arithmetic is then exact and no test spends a real second.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from hrmosaic.settings import settings as default_settings
from hrmosaic.web import main as web_main

pytestmark = pytest.mark.anyio

SSE_FAILURE = "search_policy_documents could not be called: SSE stream ended without a response"


@dataclass
class _FakeResult:
    """The two attributes `_warm_up` reads off a `ToolResult`."""

    is_error: bool
    text: str = "{}"


class _FakeClient:
    """Answers `discover()` at once and plays `outcomes` back, repeating the last one forever."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = outcomes
        self.attempts = 0

    async def discover(self, turn: Any = None) -> None:
        return None

    async def call_tool(self, buffer: Any, **kwargs: Any) -> _FakeResult:
        self.attempts += 1
        outcome = self._outcomes[min(self.attempts, len(self._outcomes)) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _VirtualClock:
    """A loop stand-in: everything delegates, except a `time()` only the fake sleep advances."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def __getattr__(self, name: str) -> Any:
        return getattr(self._loop, name)


def _virtual_time(monkeypatch: pytest.MonkeyPatch) -> _VirtualClock:
    clock = _VirtualClock(asyncio.get_running_loop())

    async def sleep(delay: float, *_: Any, **__: Any) -> None:
        clock.now += delay

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: clock)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    return clock


def _app(client: _FakeClient, *, timeout_s: int = 3) -> Any:
    settings = default_settings.model_copy(update={"embed_warmup": True, "ready_warmup_timeout_s": timeout_s})
    state = SimpleNamespace(
        settings=settings,
        orchestrator=SimpleNamespace(client=client),
        ready=False,
        ready_reason=None,
    )
    return SimpleNamespace(state=state)


async def test_a_call_that_fails_once_and_then_succeeds_still_goes_green(writer, monkeypatch):
    """The deployed failure exactly: one dropped stream used to cost the process its readiness."""
    _virtual_time(monkeypatch)
    client = _FakeClient([RuntimeError(SSE_FAILURE), _FakeResult(is_error=False)])
    app = _app(client)

    await web_main._warm_up(app)

    assert (app.state.ready, app.state.ready_reason) == (True, None)
    assert client.attempts == 2


async def test_an_is_error_result_is_retried_like_a_raised_failure(writer, monkeypatch):
    """A tool that answered `is_error` is a failed warm-up, not a verdict on the deployment."""
    _virtual_time(monkeypatch)
    client = _FakeClient([_FakeResult(is_error=True, text='{"code": "TOOL_ERROR"}'), _FakeResult(is_error=False)])
    app = _app(client)

    await web_main._warm_up(app)

    assert (app.state.ready, app.state.ready_reason) == (True, None)
    assert client.attempts == 2


async def test_the_retries_stop_at_the_deadline_and_keep_the_last_reason(writer, monkeypatch):
    """Bounded, not endless: `READY_WARMUP_TIMEOUT_S` is the whole warm-up's budget."""
    monkeypatch.setattr(web_main, "WARMUP_RETRY_S", 1.0)
    clock = _virtual_time(monkeypatch)
    client = _FakeClient([RuntimeError(SSE_FAILURE)])
    app = _app(client, timeout_s=3)

    await web_main._warm_up(app)

    assert app.state.ready is False
    assert app.state.ready_reason == f"warm-up call failed: {SSE_FAILURE}"
    # 3 s of budget spent one second at a time: attempts at t=0, 1, 2 and 3, then the deadline.
    assert (client.attempts, clock.now) == (4, 3.0)
