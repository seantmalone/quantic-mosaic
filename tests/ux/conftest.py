"""One real server and one real browser for the UX principle suite (`pytest -m ux`).

This suite is deliberately not part of `pytest -q`: it needs `requirements-ux.txt` and a chromium
build, and the plan's principles are about the **rendered** page — what a person is shown at
1440x900, 1280x800 and 390x844 — which is a level of evidence the contract tests cannot reach and
should not pay for.

`LLM_PROVIDER=stub`, one throwaway access token, one temporary trace store, loopback only: no live
model call and no request to the deployed URL, ever.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

#: Playwright is imported **inside** the `browser` fixture, never here. Two reasons, both
#: observed rather than theoretical. (1) The published suite size must not depend on whether a
#: browser package is installed: an `importorskip` at module scope skips this directory *at
#: collection*, so `pytest --collect-only -m ""` reports 2,029 on a CI box and 2,040 on a
#: developer's, and `test_docs_completeness` fails in whichever place the documents were not
#: written on. (2) `playwright.sync_api` pulls in greenlet, and a default `pytest -q` — which
#: deselects this suite *after* collection, so it never runs a browser — was seen to abort at
#: interpreter shutdown with `recursive_mutex lock failed` (exit 134) after a green summary. A
#: run that will not drive a browser now never loads one.

REPO_ROOT = Path(__file__).resolve().parents[2]
LLM_SCRIPTS = REPO_ROOT / "tests" / "fixtures" / "llm_scripts"

#: The throwaway token this suite's server is opened with. It lives for the length of one pytest
#: session, on a loopback port, and opens nothing else.
TOKEN = "uxsuite"

#: The three viewports the audit measured (**P7**).
VIEWPORTS = (("1440x900", 1440, 900), ("1280x800", 1280, 800), ("390x844", 390, 844))


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_health(base_url: str, *, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=5) as response:  # noqa: S310
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.3)
    raise RuntimeError(f"{base_url} never became healthy")


@contextmanager
def _serve(workdir: Path, script: str) -> Iterator[str]:
    """One uvicorn on a free loopback port, with the access gate on and the stub model."""
    port = _free_port()
    env = {
        **os.environ,
        "LLM_PROVIDER": "stub",
        "LLM_STUB_SCRIPT": str(LLM_SCRIPTS / script),
        "APP_ACCESS_TOKEN": TOKEN,
        "APP_ENV": "local",
        "PERSIST_BACKEND": "sqlite",
        "TRACE_DB_PATH": str(workdir / "traces.sqlite"),
        "EMBED_WARMUP": "0",
        "PORT": str(port),
    }
    log = (workdir / "server.log").open("wb")
    process = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "uvicorn",
            "hrmosaic.web.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(base_url)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()


@pytest.fixture(scope="session")
def ux_server(tmp_path_factory) -> Iterator[str]:
    """One server for the whole suite. Its stub script is spent by the first turn a test asks for,
    so a test that needs a *cited* answer takes `fresh_page` instead."""
    with _serve(tmp_path_factory.mktemp("ux"), "demo_task_1.json") as base_url:
        yield base_url


@pytest.fixture
def fresh_server(tmp_path_factory) -> Iterator[str]:
    """A server of its own, with an unspent script.

    `StubAdapter` consumes its entries in order for the life of the process and the orchestrator
    caches one adapter, so `demo_task_1.json`'s six entries are **one** turn per server. A test that
    asserts on a real answer — its sources, its geometry — needs a server nobody has asked a
    question of yet.
    """
    with _serve(tmp_path_factory.mktemp("ux-fresh"), "demo_task_1.json") as base_url:
        yield base_url


@pytest.fixture
def scripted_server(tmp_path_factory, request) -> Iterator[str]:
    """A server of its own running the stub script this test was parametrized with.

    `pytest.mark.parametrize(..., indirect=["scripted_server"])` is how a test asks for a turn of a
    particular *shape* — a refusal, a clarification, a confirmation card — because each shape needs
    its own recording and `StubAdapter` spends a recording once per process.
    """
    with _serve(tmp_path_factory.mktemp("ux-script"), request.param) as base_url:
        yield base_url


#: The question every surface fixture asks, so that the dashboard has a real turn to render.
DEMO_1 = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"

#: Every route the product paints, with three placeholders resolved by `surfaces` below. This is
#: the whole surface: the two chat states, both reader routes, all thirteen dashboard pages and the
#: themed 404. `tests/ux/test_accessibility.py` was parametrised over **three** of them
#: (`"/"`, `"/dashboard"`, `"/dashboard/evals"`) — routes that return almost no small controls,
#: which is why eight of the re-audit's ten regressions shipped green (UX W6).
SURFACE_ROUTES = (
    "/",
    "{conversation}",
    "/policy",
    "{document}",
    "/dashboard",
    "/dashboard/sessions",
    "{session}",
    "/dashboard/turns",
    "/dashboard/llm",
    "/dashboard/retrieval",
    "/dashboard/tools",
    "/dashboard/safety",
    "/dashboard/mcp",
    "/dashboard/corpus",
    "/dashboard/corpus/remote-and-hybrid-work",
    "/dashboard/evals",
    "{run}",
    "{refused}",
)


@pytest.fixture(scope="session")
def surface_server(tmp_path_factory) -> Iterator[str]:
    """One server for the whole-surface suite, with one real answered turn behind it."""
    with _serve(tmp_path_factory.mktemp("ux-surface"), "demo_task_1.json") as base_url:
        yield base_url


@pytest.fixture(scope="session")
def surfaces(browser, surface_server) -> Iterator[dict[str, str]]:
    """`{base_url, conversation, document, session, run, refused}` — the placeholders resolved.

    One turn is asked here, once, so that `/dashboard/sessions/{id}` has a session, `/dashboard/*`
    has rows to render and `/?session=` has a transcript. The eval-run route comes from the runs
    `web/main.py` imports from `evaluation/results/` at boot.
    """
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    tab = context.new_page()
    try:
        tab.goto(f"{surface_server}/?access={TOKEN}", wait_until="networkidle")
        tab.fill("#message", DEMO_1)
        tab.click("#send-button")
        tab.wait_for_selector("#messages .turn", timeout=180_000)
        tab.wait_for_timeout(1500)
        session_id = tab.eval_on_selector("#messages .turn", "e => e.dataset.sessionId")
        assert session_id, "the answered turn carries the session it belongs to"

        tab.goto(f"{surface_server}/dashboard/evals", wait_until="networkidle")
        run = tab.eval_on_selector("#eval-runs-table a[href^='/dashboard/evals/']", "e => e.getAttribute('href')")
        assert run, "the committed evaluation runs are imported at boot"

        yield {
            "base_url": surface_server,
            "conversation": f"/?session={session_id}",
            "document": "/policy/remote-and-hybrid-work",
            "session": f"/dashboard/sessions/{session_id}",
            "run": run,
            # The themed 404: a route shaped like a real one that names nothing (**P6**).
            "refused": "/policy/no-such-policy",
        }
    finally:
        context.close()


def resolve(route: str, surfaces: dict[str, str]) -> str:
    """`"{session}"` → `/dashboard/sessions/<id>`; a literal route is returned unchanged."""
    return surfaces[route[1:-1]] if route.startswith("{") else route


@pytest.fixture(scope="session")
def browser() -> Iterator[object]:
    sync_api = pytest.importorskip(
        "playwright.sync_api", reason="install requirements-ux.txt and `playwright install chromium`"
    )
    with sync_api.sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        try:
            yield instance
        finally:
            instance.close()


def _signed_in(browser, base_url: str):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    tab = context.new_page()
    tab.goto(f"{base_url}/?access={TOKEN}", wait_until="networkidle")
    return context, tab


@pytest.fixture
def page(browser, ux_server):
    """A signed-in page in the **default** persona — the one W1 exists for."""
    context, tab = _signed_in(browser, ux_server)
    try:
        yield tab
    finally:
        context.close()


@pytest.fixture
def fresh_page(browser, fresh_server):
    """The same, on a server whose stub script still has a whole turn in it."""
    context, tab = _signed_in(browser, fresh_server)
    try:
        yield tab
    finally:
        context.close()


@pytest.fixture
def scripted_page(browser, scripted_server):
    """A signed-in page on `scripted_server` — one unspent recording, chosen by the test."""
    context, tab = _signed_in(browser, scripted_server)
    try:
        yield tab
    finally:
        context.close()
