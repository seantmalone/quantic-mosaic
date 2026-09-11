"""The application object and its lifespan (spec §11, §10.3, §14).

One process serves everything: the chat UI, the JSON contract endpoints, the SSE span rail, the
observability dashboard (P9) and — mounted in-process at `/mcp-server/mcp` — the MCP server the
agent reaches over loopback Streamable HTTP. That single-service topology is the architectural bet
of §2.1: one cold start, one memory budget, one trace store.

**What the lifespan owns, in order:**

1. `install_shutdown_handlers()` — on the **main thread**, where `signal.signal` is legal, so a
   SIGTERM from Render flushes any turn in flight (§10.3).
2. the store: `get_store()` + `migrate()`, then the one process-wide `TraceWriter`.
3. boot repair and boot import: `sweep_stale_turns()` closes what a hard kill left open,
   `retention.sweep()` prunes, and `archive.import_results()` loads the committed evaluation runs
   from a **stable absolute path** (`import_state.path` is stored as given, so a relative path
   would re-import under a different working directory). All three repeat every six hours.
4. `web/sse.py`'s broker: bound to the serving loop and registered as the **one**
   `core.trace.register_span_listener()` listener — and, for the streamed answer, the one
   `register_delta_listener()` listener (§11.3).
5. the `Orchestrator`, built here rather than per request so the MCP handshake is cached for the
   life of the process (§9.1). With the gate on, its client carries `Authorization: Bearer` on
   every loopback `tools/list` and `tools/call` (§11, §16.4).
6. the `/ready` warm-up: **one loopback `tools/call`**, never a direct `rag.embed` import, so
   readiness exercises the same wire the agent uses (§11.4). It runs as a background task because
   uvicorn does not accept connections until lifespan startup has returned — a loopback call made
   inside the lifespan would be refused by a socket that is not listening yet.
7. the **self keep-alive** (§14.4), started only when `KEEP_ALIVE_URL` is set: a `GET` of the
   service's own *public* `/health` every `KEEP_ALIVE_INTERVAL_S`, so Render's fifteen-minute idle
   timer never fires.

`/health` never depends on any of it: it answers 200 while the process is up, whatever failed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from hrmosaic.agent.client import McpClient
from hrmosaic.agent.orchestrator import Orchestrator, set_orchestrator
from hrmosaic.core import archive, retention
from hrmosaic.core import trace as trace_module
from hrmosaic.core.db import get_store, migrate
from hrmosaic.core.trace import SessionSpec, TraceWriter
from hrmosaic.mcpserver.asgi import mcp_lifespan, mount_mcp
from hrmosaic.mcpserver.server import ServerDeps, build_hr_server
from hrmosaic.settings import Settings, secret_value
from hrmosaic.settings import settings as default_settings
from hrmosaic.web import api, dashboard
from hrmosaic.web.sse import broker

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = Path(__file__).resolve().parent
MOCK_DATA_DIR = REPO_ROOT / "mock_data"

#: §10.3 and §10.5: the boot jobs repeat every six hours for a process that stays up for days.
MAINTENANCE_INTERVAL_S = 6 * 60 * 60

#: How long the warm-up waits between attempts while uvicorn finishes binding its socket.
WARMUP_POLL_S = 0.2

#: How long the warm-up waits between `tools/call` attempts. Longer than `WARMUP_POLL_S`, which
#: paces a handshake against a socket that is not listening yet: a retried call has already reached
#: the server, and on a 0.1-CPU instance an immediate second attempt would only pile another cold
#: embed onto the CPU the first one is still using.
WARMUP_RETRY_S = 1.0

#: How long a self keep-alive ping may take before it is abandoned. A cold instance answers
#: `/health` in ~45 s, but a ping that finds one cold has already lost the race it exists to win:
#: 30 s bounds a ping made by an instance that is, by construction, already awake.
KEEP_ALIVE_TIMEOUT_S = 30.0

#: The one warm-up call. `search_policy_documents` is the only tool that touches both halves of
#: what `/ready` promises: the ONNX model (the query embedding) and the index (the search).
WARMUP_TOOL = "search_policy_documents"
WARMUP_ARGUMENTS = {"query": "paid time off accrual", "k": 1}


def _employees() -> list[dict[str, Any]]:
    """The 24 mock employees the act-as selector lists (§11.5)."""
    document = json.loads((MOCK_DATA_DIR / "employees.json").read_text(encoding="utf-8"))
    return [
        {
            "employee_id": row["employee_id"],
            "name": row["legal_name"],
            "title": row["title"],
            "office_id": row["office_id"],
        }
        for row in document["records"]
    ]


def _data_as_of() -> str:
    return str(json.loads((MOCK_DATA_DIR / "employees.json").read_text(encoding="utf-8"))["as_of"])


def _build_client(settings: Settings) -> McpClient:
    """The in-process client: the bearer whenever the gate is on (§16.4), and always the nonce.

    `api.LOOPBACK_NONCE` is what tells the gate that a request on the MCP mount is the app talking
    to itself, so the agent's own `initialize` / `tools/list` / `tools/call` — and the
    `client.discover()` behind every `GET /health` — do not spend the visitor-facing per-IP budget
    that is keyed on the one loopback address they all share (§17).
    """
    headers = {api.LOOPBACK_HEADER: api.LOOPBACK_NONCE}
    token = secret_value(settings.app_access_token)
    if token and api.gate_enabled(settings):
        headers["Authorization"] = f"Bearer {token}"
    return McpClient(settings=settings, headers=headers)


async def _maintenance(settings: Settings) -> None:
    """Boot repair and boot import, then the same three jobs every six hours (§10.3, §10.5)."""
    while True:
        try:
            await asyncio.to_thread(_maintenance_pass, settings)
        except asyncio.CancelledError:
            raise
        except Exception:  # a maintenance failure must never take the process down
            logger.warning("a maintenance pass failed", exc_info=True)
        await asyncio.sleep(MAINTENANCE_INTERVAL_S)


def _maintenance_pass(settings: Settings) -> None:
    store = get_store(settings)
    swept = trace_module.sweep_stale_turns(store=store)
    pruned = retention.sweep(store=store)
    # An absolute path: `import_state.path` is the primary key and is stored exactly as given, so
    # a relative one would re-import every file the first time the process ran from elsewhere.
    imported = archive.import_results(store=store, results_dir=(REPO_ROOT / "evaluation" / "results").resolve())
    logger.info(
        "maintenance: %d stale turn(s) closed, %d session(s) pruned, %d eval run(s) imported",
        swept,
        pruned.sessions_deleted,
        len(imported.imported),
    )


async def _keep_alive(settings: Settings) -> None:
    """`GET {KEEP_ALIVE_URL}/health` every `KEEP_ALIVE_INTERVAL_S`, from inside the process (§14.4).

    **Why the app pings itself.** Render counts traffic at its *edge*, and a request to the
    service's own public hostname is inbound traffic like any other: it leaves the container, is
    routed by the edge and comes back, resetting the fifteen-minute idle timer exactly as a
    visitor's request would. Which is why the URL must be the public one — a loopback call to
    `127.0.0.1` never reaches the edge and would keep nothing awake.

    **Why it is the primary mechanism, and the GitHub Actions schedule the second layer.**
    `.github/workflows/keepalive.yml` asks for a ping every ten minutes, but GitHub's scheduler is
    best-effort and de-prioritises low-traffic repositories: on 2026-09-11 it ran the `*/10`
    schedule **twice in nine hours** (09:48Z and 13:53Z — both green), and the instance was found
    spun down at 14:25Z. This loop depends on no scheduler at all, and it runs whenever the
    instance is up, which is precisely when a ping is needed. The two layers cover each other's
    gap: the cron can wake an instance this loop cannot run in.

    It never raises — a missed ping costs only the cold start `deployed.md` publishes — and it
    logs at DEBUG, because a line every ten minutes at INFO would bury the traffic it protects.
    The wait comes first: the boot that started this task was itself inbound traffic.
    """
    assert settings.keep_alive_url is not None  # the caller starts the task only when it is set
    url = f"{settings.keep_alive_url.rstrip('/')}/health"
    async with httpx.AsyncClient(timeout=KEEP_ALIVE_TIMEOUT_S) as client:
        while True:
            await asyncio.sleep(settings.keep_alive_interval_s)
            try:
                response = await client.get(url)
            except Exception as exc:  # a dropped ping is never worth a restart or a warning
                logger.debug("keep-alive: GET %s failed: %s", url, exc)
            else:
                logger.debug("keep-alive: GET %s -> %s", url, response.status_code)


async def _warm_up(app: FastAPI) -> None:
    """`/ready` goes green after **one** loopback `tools/call` (§11.4).

    One successful call, but not one attempt: the handshake and the call share the single
    `READY_WARMUP_TIMEOUT_S` deadline and both retry inside it. Without that, one dropped stream on
    the first (and slowest) call latched `ready = False` for the life of the process while
    `/health` stayed `ok` and `/chat` answered — the defect P11c fixes. The deadline is checked
    **between** attempts only: a call already on the wire is bounded by the transport's read
    timeout and is never cancelled, because it is the one loading the ONNX session.
    """
    settings: Settings = app.state.settings
    if not settings.embed_warmup:
        app.state.ready = True
        app.state.ready_reason = None
        return

    client: McpClient = app.state.orchestrator.client
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.ready_warmup_timeout_s
    last_error = "the MCP server has not answered yet"
    while loop.time() < deadline:
        try:
            await client.discover()
            break
        except Exception as exc:  # the socket is not listening yet, or the handshake failed
            last_error = f"mcp handshake: {exc}"
            app.state.ready_reason = last_error
            await asyncio.sleep(WARMUP_POLL_S)
    else:
        app.state.ready_reason = last_error
        return

    session = SessionSpec(client_label="maintenance", employee_id=None)
    buffer = trace_module.start_turn(session, user_message="startup warm-up")
    try:
        while True:
            try:
                result = await client.call_tool(
                    buffer, name=WARMUP_TOOL, arguments=dict(WARMUP_ARGUMENTS), employee_id=api.DEFAULT_ACTOR
                )
                if not result.is_error:
                    app.state.ready = True
                    app.state.ready_reason = None
                    return
                app.state.ready_reason = f"warm-up call failed: {result.text[:200]}"
            except Exception as exc:
                app.state.ready_reason = f"warm-up call failed: {exc}"
            if loop.time() >= deadline:
                return
            await asyncio.sleep(WARMUP_RETRY_S)
    finally:
        buffer.close(outcome="maintenance", stop_reason="maintenance")


def _install_error_handlers(app: FastAPI) -> None:
    """A dict `detail` is the body (§11.1's `{"code": …}`), not a value nested under `detail`.

    Three handlers, and the third is the one constraint 11 turns on: `HTTPException` and
    `RequestValidationError` are the modelled refusals, and `api.UnhandledErrorMiddleware` catches
    everything else — so an exception the design does not model still answers **200** with a typed
    escalation block and still closes the turn it was raised in, instead of escaping as a bare 500
    and leaving the turn row open until the next boot sweep (§12.3).
    """

    async def http_exception(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, HTTPException)
        body = exc.detail if isinstance(exc.detail, dict) else {"code": "ERROR", "detail": exc.detail}
        return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    async def validation_error(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        return JSONResponse(
            {"code": "INVALID_REQUEST", "errors": json.loads(json.dumps(exc.errors(), default=str))},
            status_code=422,
        )

    app.add_exception_handler(HTTPException, http_exception)
    app.add_exception_handler(RequestValidationError, validation_error)
    # Added first, so the access gate (added last, and therefore outermost) still refuses before
    # any work happens, and this sits directly outside Starlette's own `ExceptionMiddleware`.
    app.add_middleware(api.UnhandledErrorMiddleware)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. `main:app` is the module-level instance uvicorn serves."""
    resolved = settings or default_settings
    server = build_hr_server(ServerDeps(index_path=Path(resolved.index_path), transport="http"))

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 1. the shutdown handlers, on the main thread (§10.3).
        trace_module.install_shutdown_handlers()

        # 2. the store and the one writer.
        store = get_store(resolved)
        migrate(store)
        trace_module.set_writer(TraceWriter(store))

        # 3. boot repair and boot import, repeating every six hours.
        maintenance = asyncio.create_task(_maintenance(resolved))

        # 4. the one span listener, and the one answer-delta listener (§11.3).
        broker.bind(asyncio.get_running_loop())
        unregister = trace_module.register_span_listener(broker.publish_span)
        unregister_deltas = trace_module.register_delta_listener(broker.publish_answer_delta)

        # 5. the orchestrator, so the MCP handshake outlives a request (§9.1).
        orchestrator = Orchestrator(client=_build_client(resolved), settings=resolved)
        set_orchestrator(orchestrator)
        app.state.orchestrator = orchestrator

        # 6. the `/ready` warm-up, after uvicorn starts accepting (§11.4).
        warmup = asyncio.create_task(_warm_up(app))

        # 7. the self keep-alive (§14.4) — only when the public origin is configured.
        keep_alive = asyncio.create_task(_keep_alive(resolved)) if resolved.keep_alive_url else None
        app.state.keep_alive = keep_alive

        async with mcp_lifespan(server):
            try:
                yield
            finally:
                broker.close()
                unregister()
                unregister_deltas()
                for task in (warmup, maintenance, keep_alive):
                    if task is None:
                        continue
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
                await orchestrator.aclose()
                trace_module.flush_open_turns()
                set_orchestrator(None)

    # `docs_url=None` and friends: §11.8's endpoint list is exact, and FastAPI's three default
    # documentation routes are not on it.
    app = FastAPI(
        title="Mosaic HR Copilot",
        version=api.APP_VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = resolved
    app.state.keep_alive = None
    app.state.employees = _employees()
    app.state.data_as_of = _data_as_of()
    app.state.served_a_turn = False
    app.state.ready = False
    app.state.ready_reason = "the embedding model and the index are still loading"
    app.state.mcp_server = server

    _install_error_handlers(app)
    app.include_router(api.router)
    # P9's eleven pages and the whole `/api/*` layer (§11.6–§11.8), behind the same gate.
    app.include_router(dashboard.router)
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
    mount_mcp(app, server)
    app.add_middleware(api.AccessGateMiddleware, settings=resolved)
    return app


app = create_app()


__all__ = ["KEEP_ALIVE_TIMEOUT_S", "MAINTENANCE_INTERVAL_S", "app", "create_app"]
