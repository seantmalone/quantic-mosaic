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

A fifth property is about the **documents**, and it is here because it is a property of this
feature and of nothing else: the loop only runs when an operator sets `KEEP_ALIVE_URL` on the
service, and nothing in this repository sets it. So every graded document that publishes the
keep-alive has to publish it in the conditional, and the day someone does set it — in
`render.yaml`, in the `Dockerfile`, or on the live service — those documents have to be revisited.
`test_the_published_keep_alive_claim_stays_conditional_while_nothing_sets_the_url` fails on both
halves of that: an unconditional claim, or a repository that quietly starts setting the variable.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
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

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The graded documents that publish the keep-alive to a reader.
PUBLISHED_DOCS = (
    "README.md",
    "deployed.md",
    "docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md",
    "docs/architecture.html",
)

#: A claim that the instance *is* being kept warm, with no precondition attached.
UNCONDITIONAL_CLAIM = re.compile(r"\b(now|already|does)\s+keeps?\s+the\s+instance\s+(warm|awake)\b", re.I)

#: Any one of these, in a document, states the precondition the reader needs.
CONDITIONAL_MARKERS = (
    "once `KEEP_ALIVE_URL` is set",
    "is set nowhere in this repository",
    "is set in no file of this repository",
    "not set on the live service",
    "has not been set on the live service",
    "not switched on",
)

#: Files that could set the variable for the deployed service without an operator lifting a finger.
DEPLOY_FILES = ("render.yaml", "Dockerfile")


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


def test_the_published_keep_alive_claim_stays_conditional_while_nothing_sets_the_url():
    """The documents may promise a warm instance only where they name the switch that arms it.

    P21 replaced one over-claim (the GitHub cron "now keeps the instance warm", which its own
    finding disproved) and must not install another: the in-process loop is real, tested and
    **off**, because `KEEP_ALIVE_URL` is unset by default and this repository sets it nowhere. A
    grader reads `README.md` and gets the 71.0 s cold start `deployed.md` measures, so the claim
    has to carry its precondition. Both halves are asserted — the repository's silence about the
    variable, and each document's conditional — so that setting it in `render.yaml` tomorrow fails
    here instead of quietly making three documents true by accident and one of them stale.
    """
    for name in DEPLOY_FILES:
        body = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert "KEEP_ALIVE_URL" not in body, (
            f"{name} now sets the keep-alive URL — the documents say the repository does not; "
            "update them (and this test) in the same commit"
        )

    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^KEEP_ALIVE_URL=\s*(#|$)", example, re.M), (
        ".env.example must carry the key with no value: unset is the documented default"
    )

    for rel in PUBLISHED_DOCS:
        prose = " ".join((REPO_ROOT / rel).read_text(encoding="utf-8").split())
        assert not UNCONDITIONAL_CLAIM.search(prose), (
            f"{rel} claims the instance is being kept warm; it is not, until an operator sets "
            "KEEP_ALIVE_URL on the service"
        )
        assert any(marker in prose for marker in CONDITIONAL_MARKERS), (
            f"{rel} publishes the keep-alive without naming the variable that arms it"
        )
