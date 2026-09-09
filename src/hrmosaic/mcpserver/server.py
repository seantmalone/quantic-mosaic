"""`build_hr_server()` — the one factory behind all three transports (spec §8.1).

The same `MCPServer` instance is served over the in-process Streamable HTTP mount, over a stdio
subprocess and, unchanged, from a remote deployment. Nothing in a tool knows which transport carried
the call; the transport name reaches the tools only as a label on the `_trace` envelope.

**Every handler is `async def` and every CPU-bound call is inside `await asyncio.to_thread(...)`.**
That is not decoration: in the graded topology the server is mounted in the *same* event loop as
FastAPI, so a synchronous SQLite read or an ONNX embed on the loop would stall `/chat`, `/health` and
the SSE rail at once.

**One index connection per process.** `ServerDeps` opens `data/index/hr_index.sqlite` once, read-only
with sqlite-vec loaded, and threads it into `rag.retrieve.retrieve()` and every `core.corpusread`
call. `retrieve()` opens and closes its own connection when none is passed, which on 0.1 CPU is a
per-call cost paid for nothing. The connection is guarded by a lock because `asyncio.to_thread` hands
it to a pool thread.

**Spans.** This package never writes a span: `core/trace.py` is the only writer (§16.3), and over
stdio there is no turn to write into. Instead a tool returns the spans it produced under `_trace` on
its result and the client lifts them and re-parents them under its own `tool_call` span (§8.7). The
envelope also echoes the acting persona, which the client records on that `tool_call` span as
`actor_employee_id` / `actor_source` — audit only, gating nothing (§17 *Identity*).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel

from hrmosaic.core.db import Store, get_store
from hrmosaic.core.ids import new_span_id
from hrmosaic.settings import settings

#: `server_info.name` / `server_info.version` of §8.2 step 1.
SERVER_NAME = "mosaic-hr"
SERVER_VERSION = "0.1.0"

#: The persona recorded when a call carries no `_meta["mosaic/actor"]` (§8.7).
DEFAULT_ACTOR = "E1042"

#: The two annotation sets of §8.4. `destructive_hint=False` on the write tools is honest: both are
#: mock by construction (§8.5) and append a row rather than mutating anything.
READ_ONLY = {"read_only_hint": True, "open_world_hint": False}
WRITE = {"read_only_hint": False, "destructive_hint": False, "idempotent_hint": False}

#: Read from the working directory, like `corpus/` and `data/index/` everywhere else in the project.
MOCK_DATA_DIR = Path("mock_data")
RULES_PATH = Path("corpus/rules.yml")
FACTS_PATH = Path("corpus/facts.yml")

#: The six committed datasets of §5.4, each a `{as_of, records[]}` envelope.
DATASETS = (
    "employees",
    "pto_balances",
    "benefits_elections",
    "org_manager_map",
    "offices",
    "holidays_2026",
)


# --------------------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------------------


@dataclass
class ServerDeps:
    """Everything the nine tools read, resolved once per process.

    Constructed by the caller that builds the server (`asgi.build_mounted_app`, `stdio_main`, a
    test), so a test can point it at a fixture index or a temporary store without monkeypatching.
    The trace store is *not* held here: `get_store()` is consulted per write, so a test that swaps
    the process store between calls is honoured.
    """

    index_path: Path = field(default_factory=lambda: Path(settings.index_path))
    mock_data_dir: Path = MOCK_DATA_DIR
    rules_path: Path = RULES_PATH
    facts_path: Path = FACTS_PATH
    transport: str = "http"
    _index: sqlite3.Connection | None = field(default=None, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _datasets: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def index(self) -> sqlite3.Connection:
        """The one process-wide read-only index connection, opened on first use, never at boot."""
        with self._lock:
            if self._index is None:
                from hrmosaic.rag.index import open_index

                self._index = open_index(self.index_path)
            return self._index

    @property
    def lock(self) -> threading.RLock:
        """Held around every use of the shared connection — `asyncio.to_thread` uses a pool."""
        return self._lock

    def dataset(self, name: str) -> dict[str, Any]:
        """One committed mock dataset, parsed once and cached (§5.4)."""
        with self._lock:
            if name not in self._datasets:
                path = self.mock_data_dir / f"{name}.json"
                self._datasets[name] = json.loads(path.read_text(encoding="utf-8"))
            return self._datasets[name]

    def records(self, name: str) -> list[dict[str, Any]]:
        return list(self.dataset(name)["records"])

    def as_of(self, name: str = "employees") -> str:
        """The snapshot date every date-bearing answer is stated against (§5.4)."""
        return str(self.dataset(name)["as_of"])

    def employee(self, employee_id: str) -> dict[str, Any] | None:
        return next((row for row in self.records("employees") if row["employee_id"] == employee_id), None)

    def store(self) -> Store:
        return get_store()

    def close(self) -> None:
        with self._lock:
            if self._index is not None:
                self._index.close()
                self._index = None


# --------------------------------------------------------------------------------------
# The `_meta` conventions of §8.7
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ActorMeta:
    """`_meta["mosaic/actor"]` — recorded for *who asked*, gating nothing (§17 *Identity*)."""

    employee_id: str = DEFAULT_ACTOR
    source: Literal["explicit", "default"] = "default"

    def as_dict(self) -> dict[str, str]:
        return {"employee_id": self.employee_id, "source": self.source}


@dataclass(frozen=True)
class CallMeta:
    """What one `tools/call` carried besides its arguments."""

    trace: dict[str, Any]
    actor: ActorMeta
    retrieval: dict[str, Any]
    arguments: dict[str, Any]

    def supplied(self, name: str) -> bool:
        """True when the caller wrote the argument itself, rather than inheriting a schema default.

        The tool body sees defaults already applied, so `k_source` and the confirmation gate's
        argument comparison both have to read the raw wire arguments to stay honest.
        """
        return name in self.arguments


def read_meta(ctx: Context) -> CallMeta:
    """Parse the three `_meta` keys and the raw wire arguments off one request (§8.7).

    A direct `server.call_tool(...)` — the SDK's in-process shortcut, which `gen_tool_schemas.py`
    and a unit test may use — carries no request at all. That is the "no `_meta` supplied" case, and
    it answers with the documented defaults rather than raising.
    """
    try:
        request = ctx.request_context
    except ValueError:
        request = None
    meta = dict(getattr(request, "meta", None) or {})
    params = dict(getattr(request, "params", None) or {})
    actor_meta = meta.get("mosaic/actor") or {}
    employee_id = actor_meta.get("employee_id") if isinstance(actor_meta, dict) else None
    actor = (
        ActorMeta(employee_id=str(employee_id), source="explicit")
        if employee_id
        else ActorMeta(employee_id=DEFAULT_ACTOR, source="default")
    )
    return CallMeta(
        trace=dict(meta.get("mosaic/trace") or {}),
        actor=actor,
        retrieval=dict(meta.get("mosaic/retrieval") or {}),
        arguments=dict(params.get("arguments") or {}),
    )


# --------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------


def envelope(
    call: CallMeta,
    *,
    spans: Sequence[dict[str, Any]] = (),
    server_timing_ms: int = 0,
    transport: str = "http",
) -> dict[str, Any]:
    """The `_trace` key of §8.7: nested spans plus what the client's `tool_call` span needs.

    A list would have been the literal reading of "returns nested spans under a `_trace` key", but
    the same span also has to carry the actor and the server-side timing the `tool_call` payload
    declares (§10.2), and a second sibling key would be one more thing for a client to know about.
    """
    return {
        "spans": list(spans),
        "server_timing_ms": server_timing_ms,
        "actor": call.actor.as_dict(),
        "server": SERVER_NAME,
        "transport": transport,
    }


def span_record(kind: str, name: str, payload: Any, *, started_at: int, ended_at: int) -> dict[str, Any]:
    """One nested span, in the shape the client re-parents under its `tool_call` span (§8.7).

    A dict rather than a `SpanContext`, because over stdio the span crosses a process boundary as
    JSON. `payload` is a §10.2 payload model; the client hands it straight to `core/trace.py`, which
    stays the only writer.
    """
    return {
        "span_id": new_span_id(),
        "kind": kind,
        "name": name,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": max(0, (ended_at - started_at) // 1000),
        "status": "ok",
        "payload": payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload,
    }


def result(body: dict[str, Any], *, is_error: bool = False) -> CallToolResult:
    """One tool result, carried **both** as `structured_content` and as JSON text.

    §8.2 step 5 has the client read `structured_content` when present and fall back to
    `json.loads(content[0].text)`. Both are populated here, so both paths are real on both
    transports and neither is a fiction a test would have to fake.

    Every handler is annotated `-> <its output model>` but returns this instead. The annotation is
    what the SDK derives `output_schema` from; returning a `CallToolResult` is what lets a tool set
    `is_error` **with** structured content, and the SDK validates a successful one against that same
    model — extra keys such as `_trace` are ignored, an omitted required field is not.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(body, ensure_ascii=False))],
        structured_content=body,
        is_error=is_error,
    )


def invalid_arguments(fields: Sequence[str]) -> CallToolResult:
    """The §8.4 tool-2 rejection: `isError` with `INVALID_ARGUMENTS` and the offending field names."""
    return result({"status": "invalid_arguments", "code": "INVALID_ARGUMENTS", "fields": list(fields)}, is_error=True)


def not_found(employee_id: str) -> dict[str, Any]:
    """The §8.3 domain "not found": a **successful** result the orchestrator turns into a clarification."""
    return {
        "status": "not_found",
        "code": "EMPLOYEE_NOT_FOUND",
        "hint": "Employee ids look like E1042.",
        "employee_id": employee_id,
    }


# --------------------------------------------------------------------------------------
# The factory
# --------------------------------------------------------------------------------------


def build_hr_server(deps: ServerDeps | None = None) -> MCPServer:
    """The nine tools of §8.4 on one `MCPServer`, ready for any of the three transports.

    The tool modules are imported here rather than at module scope: each of them imports the result
    helpers above, so a top-level import would close a cycle for no gain.
    """
    from hrmosaic.mcpserver.tools import REGISTRARS

    deps = deps if deps is not None else ServerDeps()
    server: MCPServer = MCPServer(name=SERVER_NAME, version=SERVER_VERSION)
    for register in REGISTRARS:
        register(server, deps)
    return server
