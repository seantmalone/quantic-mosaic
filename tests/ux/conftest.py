"""One real server and one real browser for the UX principle suite (`pytest -m ux`).

This suite is deliberately not part of `pytest -q`: it needs `requirements-ux.txt` and a chromium
build, and the plan's principles P3–P7 are about the **rendered** page — what a person is shown at
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


@pytest.fixture(scope="session")
def ux_server(tmp_path_factory) -> Iterator[str]:
    """The shipped app on a real uvicorn, with the access gate on and the stub model."""
    workdir = tmp_path_factory.mktemp("ux")
    port = _free_port()
    env = {
        **os.environ,
        "LLM_PROVIDER": "stub",
        "LLM_STUB_SCRIPT": str(LLM_SCRIPTS / "demo_task_1.json"),
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


@pytest.fixture
def page(browser, ux_server):
    """A signed-in page in the **default** persona — the one W1 exists for."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    tab = context.new_page()
    tab.goto(f"{ux_server}/?access={TOKEN}", wait_until="networkidle")
    try:
        yield tab
    finally:
        context.close()
