"""The in-process self keep-alive (spec §14.4).

`.github/workflows/keepalive.yml` asks GitHub for a ping every ten minutes. GitHub's cron is
best-effort: on 2026-09-11 it ran that schedule **twice in nine hours** (09:48Z and 13:53Z, both
green) and the live instance was found spun down at 14:25Z. So the workflow cannot be the primary
mechanism, and `web/main.py` grows one that needs no scheduler — a background task that GETs the
service's **own public** `/health` on a fixed interval, which is inbound traffic at Render's edge
and therefore resets the fifteen-minute idle timer.

Four properties carry the argument, and each is asserted below:

* it does not exist unless `KEEP_ALIVE_URL` is set, so a developer's laptop and every test server
  start no loop and open no socket;
* it does exist when the variable is set;
* it pings `{KEEP_ALIVE_URL}/health` once per `KEEP_ALIVE_INTERVAL_S`, waiting *before* the first
  one (the boot that started it was itself inbound traffic), and a failed ping neither raises nor
  stops the loop — a missed ping costs only the cold start `deployed.md` publishes;
* shutdown cancels it, like every other lifespan-owned task.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest import mock

import httpx
import pytest

from hrmosaic.core import trace as trace_module
from hrmosaic.settings import Settings
from hrmosaic.settings import settings as live_settings
from hrmosaic.web import main as web_main
from tests.conftest import free_port

pytestmark = pytest.mark.anyio

PUBLIC_ORIGIN = "https://mosaic-hr-copilot.onrender.com"


def _settings(**overrides: object) -> Settings:
    """The live settings with the test defaults of `conftest.web` and nothing from the network."""
    port = free_port()
    return live_settings.model_copy(
        update={
            "port": port,
            "mcp_server_url": f"http://127.0.0.1:{port}/mcp-server/mcp",
            "llm_provider": "stub",
            "embed_warmup": False,
            "app_access_token": None,
            "keep_alive_url": None,
            **overrides,
        }
    )


@asynccontextmanager
async def _lifespan(**overrides: object) -> AsyncIterator[object]:
    """`create_app()` through its real lifespan, without a uvicorn — the tasks are what is asserted.

    No socket is bound, so nothing here can ping anything: `embed_warmup` is off (the `/ready`
    warm-up returns at once) and `keep_alive_url` defaults to `None` unless a test sets it.
    """
    app = web_main.create_app(_settings(**overrides))
    try:
        async with app.router.lifespan_context(app):
            yield app
    finally:
        trace_module.clear_span_listeners()
        trace_module.clear_delta_listeners()
        trace_module.set_writer(None)
        trace_module.reset_shutdown_handlers()


async def test_no_task_is_started_when_the_url_is_unset(store):
    """The default: a laptop, CI and every test server run no loop and open no socket."""
    async with _lifespan() as app:
        assert app.state.keep_alive is None


async def test_the_task_is_started_when_the_url_is_set(store):
    async with _lifespan(keep_alive_url=PUBLIC_ORIGIN) as app:
        task = app.state.keep_alive
        assert task is not None
        assert not task.done(), "the loop is running for the life of the process"


async def test_shutdown_cancels_the_task(store):
    """A leaked loop would outlive its app and keep pinging with a closed event loop under it."""
    async with _lifespan(keep_alive_url=PUBLIC_ORIGIN) as app:
        task = app.state.keep_alive

    assert task.cancelled(), "the teardown cancels it and awaits the cancellation"


async def test_the_loop_pings_public_health_on_its_schedule_and_survives_a_failure():
    """One `GET {KEEP_ALIVE_URL}/health` per interval, the wait first, and an error changes nothing.

    The HTTP client is a stand-in because the alternative is a test that talks to the internet;
    everything asserted — the URL it builds, the order of wait and ping, the timeout it applies and
    the fact that the loop outlives a refused connection — is the loop's own behaviour.
    """
    waits: list[float] = []
    pings: list[str] = []
    timeouts: list[float] = []

    class _FakeClient:
        def __init__(self, *, timeout: float) -> None:
            timeouts.append(timeout)

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *exc_info: object) -> bool:
            return False

        async def get(self, url: str) -> httpx.Response:
            pings.append(url)
            if len(pings) == 2:
                raise httpx.ConnectError("the edge refused the connection")
            return httpx.Response(200)

    async def _fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) > 3:  # three pings is enough to show a schedule and an error inside it
            raise asyncio.CancelledError

    settings = _settings(keep_alive_url=PUBLIC_ORIGIN + "/", keep_alive_interval_s=600)
    with (
        mock.patch.object(web_main.httpx, "AsyncClient", _FakeClient),
        mock.patch.object(asyncio, "sleep", _fake_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await web_main._keep_alive(settings)

    assert waits == [600, 600, 600, 600], "it waits its interval before every ping"
    assert pings == [f"{PUBLIC_ORIGIN}/health"] * 3, "the public origin, one trailing slash or none"
    assert timeouts == [web_main.KEEP_ALIVE_TIMEOUT_S]
