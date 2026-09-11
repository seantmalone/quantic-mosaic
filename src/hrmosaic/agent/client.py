"""The agent's MCP client: discovery, the `_meta` conventions, and the `tool_call` span (§8.2, §8.7).

`agent/**` never imports `hrmosaic.mcpserver` — `tests/architecture/test_conventions.py` greps for
exactly that. The tools are reached over the MCP wire on all three transports, which is what makes
R5.4 ("the array handed to the model *is* the discovered catalog") structurally true rather than
asserted: `DiscoveredCatalog.tool_schemas()` is the only source of the model's tool array, and it is
built from a live `tools/list`.

**Three things this module owns.**

*The cached handshake and the per-turn span.* `initialize` + `tools/list` run once per process (and
again after a failure); the `mcp_discovery` span is emitted **every turn** (§8.2 step 3), carrying
the cached catalog with `cached=false` and a real `handshake_ms` on the turn that handshook and
`cached=true, handshake_ms=0` afterwards. Without that, only the first turn after a boot would carry
the primary RUBRIC5.2 evidence and every later session would fail the audit-completeness census.

*The `_meta` envelope.* Every `tools/call` carries `mosaic/trace`, `mosaic/actor` and
`mosaic/retrieval` (§8.7). `mosaic/retrieval` is the only path from `POST /chat`'s options to the
retriever, because retrieval lives inside the MCP server and `agent/**` may not import it.

*Stripping `confirmation_token`.* A token is a credential. The model must never be able to supply
one — not even a fabricated one — so the argument is removed from **every** call and re-attached
only by `resume_turn`, from a token `web/` minted after a human clicked Confirm (§8.6).

**Why the session lives in its own task.** `streamable_http_client` and `stdio_client` are anyio
context managers holding cancel scopes, and anyio refuses to let a scope be exited by a task other
than the one that entered it. A session cached across turns is entered on turn 1 and closed at
shutdown, which are different tasks. So one background task owns the whole context-manager stack for
the life of the connection and every caller talks to the `ClientSession` it publishes — memory
object streams are safe across tasks in one loop, cancel scopes are not.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from hrmosaic.agent.guardrails import g4
from hrmosaic.core.db import now_micros
from hrmosaic.core.llm.base import ToolSchema
from hrmosaic.core.models import (
    DiscoveredTool,
    McpDiscoveryPayload,
    RetrievalPayload,
    ServerInfo,
    ToolCallPayload,
)
from hrmosaic.settings import Settings
from hrmosaic.settings import settings as default_settings

if TYPE_CHECKING:
    from hrmosaic.core.trace import TurnBuffer

REPO_ROOT = Path(__file__).resolve().parents[3]
STDIO_ENTRYPOINT = REPO_ROOT / "mcp" / "server_entrypoint.py"

#: The argument the model may never supply (§8.6). Stripped from every call, unconditionally.
TOKEN_ARGUMENT = "confirmation_token"

#: Where a tool returns the spans it produced, and the actor and timing the `tool_call` payload
#: declares (§8.7). Lifted out of the body before the result reaches the model.
TRACE_KEY = "_trace"

#: How long `close()` waits for the owning task to unwind before cancelling it.
CLOSE_TIMEOUT_S = 10.0

#: The loopback transport's timeouts, mirroring the SDK's own `create_mcp_http_client`: 30 s to
#: connect, write and take a pool slot, and **300 s to read**. httpx2's default is `Timeout(5.0)`
#: on all four phases, which is wrong for a StreamableHTTP `tools/call` (see `_http_client`).
LOOPBACK_TIMEOUT = httpx2.Timeout(30.0, read=300.0)

#: Tools 1–4 of §8.4 — the RAG tools, and the whole catalog for `intent == "policy_qa"` (§9.2).
RAG_TOOLS: tuple[str, ...] = (
    "search_policy_documents",
    "get_policy_section",
    "list_policy_documents",
    "check_policy_compliance",
)


class McpUnavailable(RuntimeError):
    """The handshake or a call could not reach the server — §9.5 row 1's `tool_unavailable`."""


# --------------------------------------------------------------------------------------
# The discovered catalog
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveredCatalog:
    """One `tools/list`, sorted and hashed — the prompt prefix's stable half (§8.2 step 2)."""

    server: str
    transport: str
    url: str | None
    protocol_version: str | None
    server_info: ServerInfo | None
    tools: tuple[DiscoveredTool, ...]
    catalog_sha: str
    mcp_session_id: str | None
    handshake_ms: int
    discovered_at: int

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)

    def tool_schemas(self, allowed: Iterable[str] | None = None) -> list[ToolSchema]:
        """The model's tool array: the catalog itself, converted, never a hard-coded list.

        `ToolSchema` is the provider-neutral form each adapter translates — `OpenAICompatAdapter`
        into OpenAI-shaped `{"type": "function", "function": {...}}` entries, `AnthropicAdapter`
        into its own shape minus the top-level combinators it rejects (§9.8). Filtering happens
        here, so what the model is offered and what the client will call are one list.
        """
        permitted = None if allowed is None else set(allowed)
        return [
            ToolSchema(name=tool.name, description=tool.description, input_schema=tool.input_schema)
            for tool in self.tools
            if permitted is None or tool.name in permitted
        ]

    def payload(self, *, cached: bool) -> McpDiscoveryPayload:
        """The §10.2 `mcp_discovery` payload for one turn."""
        return McpDiscoveryPayload(
            server=self.server,
            transport=self.transport,
            url=self.url,
            protocol_version=self.protocol_version,
            server_info=self.server_info,
            tools=list(self.tools),
            tool_count=len(self.tools),
            catalog_sha=self.catalog_sha,
            mcp_session_id=self.mcp_session_id,
            cached=cached,
            handshake_ms=0 if cached else self.handshake_ms,
            discovered_at=self.discovered_at,
        )


def catalog_sha(tools: Sequence[DiscoveredTool]) -> str:
    """A stable digest of the sorted catalog — the dashboard's "did the tool surface change?"."""
    body = json.dumps(
        [tool.model_dump(mode="json") for tool in tools], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _validated(tool: Any) -> DiscoveredTool:
    """One `tools/list` entry, with the well-formedness check of §8.2 step 2."""
    schema = dict(tool.input_schema or {})
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise McpUnavailable(f"tool {tool.name!r} published a malformed input_schema")
    return DiscoveredTool(
        name=tool.name,
        description=tool.description or "",
        input_schema=schema,
        output_schema=dict(tool.output_schema) if tool.output_schema else None,
        annotations=tool.annotations.model_dump(mode="json") if tool.annotations is not None else None,
    )


# --------------------------------------------------------------------------------------
# One tool result
# --------------------------------------------------------------------------------------


#: Top-level `search_policy_documents` result keys the model is not shown (W2-D). Ten of them, and
#: every one is retrieval telemetry the `retrieval` span already records in full (§10.2): the model
#: acts on the hits, not on how they were found, and these bytes are re-billed as input on every
#: later act step of the turn.
SEARCH_TELEMETRY_KEYS = frozenset(
    {
        "query_used",
        "k_effective",
        "k_source",
        "strategy",
        "total_candidates",
        "embed_ms",
        "search_ms",
        "index_version",
        "topic_backfilled",
        "backfill_reason",
    }
)

#: Per-hit keys on the same basis: `rank` is a position in a list the model reads in order, the
#: three scores are the fusion's own arithmetic, and the two offsets locate the chunk inside a file
#: nobody reads. `quarantined` belongs with them and is dropped **only when it is false** — a true
#: one is the §7.4 banner telling the model this passage may not be cited, and dropping that would
#: trade a guardrail for bytes.
HIT_TELEMETRY_KEYS = frozenset({"rank", "dense_score", "bm25_rank", "rrf_score", "char_start", "char_end"})


def prompt_body(name: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """The tool result as the **model** is shown it (§7.2), which is not the one the record keeps.

    Only `search_policy_documents` differs, and only by subtraction: ten telemetry keys off the
    result and six off each hit, ~9 % of the input tokens of a turn that searches twice. What is
    left is what a citation needs — the ids, the heading path, the chunk and its snippet — plus the
    quarantine flag on any hit that carries one. **Subtraction only**: an error body carries no
    `hits` and does not grow one here.

    `ToolResult.text` stays whole, because three readers need the whole thing: the §11.1 `tool_call`
    span (and the dashboard drill-down over it), G4, and the eval's scorers.
    """
    if name != g4.SEARCH_TOOL:
        return dict(body)
    reduced = {key: value for key, value in body.items() if key not in SEARCH_TELEMETRY_KEYS}
    hits = []
    for hit in body.get("hits") or []:
        kept = {key: value for key, value in hit.items() if key not in HIT_TELEMETRY_KEYS}
        if not kept.get("quarantined"):
            kept.pop("quarantined", None)
        hits.append(kept)
    if "hits" in body:
        # Set only when the tool returned one. An `isError` body is `{code, message, fields}` and
        # nothing else, and it is exactly what `_repair` shows the model as `failed.prompt_text` on
        # the one repair round trip — the path where the model has to work out what went wrong. A
        # fabricated `"hits": []` would tell it, falsely, that the search also returned nothing.
        reduced["hits"] = hits
    return reduced


@dataclass
class ToolResult:
    """What one `tools/call` produced, as the act loop needs it."""

    tool_name: str
    arguments: dict[str, Any]
    body: dict[str, Any]
    is_error: bool
    error_code: str | None
    span_id: str | None
    duration_ms: int
    text: str
    retrievals: list[RetrievalPayload] = field(default_factory=list)

    @property
    def prompt_text(self) -> str:
        """The bytes appended to the act conversation — `text` minus the telemetry (W2-D)."""
        return json.dumps(prompt_body(self.tool_name, self.body), ensure_ascii=False)

    @property
    def confirmation_required(self) -> bool:
        return self.error_code == "CONFIRMATION_REQUIRED"

    @property
    def not_found(self) -> bool:
        """A domain "not found" is a **successful** result (§8.3), and a clarification for us."""
        return self.body.get("code") == "EMPLOYEE_NOT_FOUND"


def read_body(result: Any) -> dict[str, Any]:
    """`structured_content` when present, else `json.loads(content[0].text)` (§8.2 step 5).

    Both paths are real on both transports and `tests/integration/test_mcp_tool_call.py` asserts
    they agree; a client that trusted only one would break silently on an SDK change.
    """
    if getattr(result, "structured_content", None):
        return dict(result.structured_content)
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {"status": "error", "message": text}
            return parsed if isinstance(parsed, dict) else {"result": parsed}
    return {}


# --------------------------------------------------------------------------------------
# The connection
# --------------------------------------------------------------------------------------


class _Connection:
    """One MCP session, opened and closed by a single background task (see the module docstring)."""

    def __init__(self, opener: Callable[[], Any], *, http_client: Any = None) -> None:
        self._opener = opener
        self._http_client = http_client
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._stopping = asyncio.Event()
        self._session: ClientSession | None = None
        self._initialized: Any = None
        self._failure: BaseException | None = None

    @property
    def session(self) -> ClientSession | None:
        """The live session, or `None` once the owning task has stopped."""
        return self._session

    async def open(self) -> tuple[ClientSession, Any]:
        self._task = asyncio.create_task(self._run(), name="mcp-session")
        await self._ready.wait()
        if self._failure is not None or self._session is None:
            await self.close()
            raise McpUnavailable(f"the MCP handshake failed: {self._failure}")
        return self._session, self._initialized

    async def _run(self) -> None:
        try:
            async with self._opener() as (read, write), ClientSession(read, write) as session:
                self._initialized = await session.initialize()
                self._session = session
                self._ready.set()
                await self._stopping.wait()
        except BaseException as exc:  # noqa: BLE001 - reported to the opener, never swallowed
            self._failure = exc
        finally:
            self._session = None
            if self._http_client is not None:
                # Ours to close: `streamable_http_client` closes only a client it made itself.
                await self._http_client.aclose()
            self._ready.set()

    async def close(self) -> None:
        self._stopping.set()
        task, self._task = self._task, None
        self._session = None
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=CLOSE_TIMEOUT_S)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()


# --------------------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------------------


class McpClient:
    """The one MCP client the orchestrator uses, over whichever transport is configured (§8.1)."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        headers: dict[str, str] | None = None,
        transport: str | None = None,
        url: str | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._headers = dict(headers or {})
        self._transport = transport or self._settings.mcp_transport_effective
        self._url = url if url is not None else self._settings.mcp_server_url
        self._connection: _Connection | None = None
        self._catalog: DiscoveredCatalog | None = None
        self._lock = asyncio.Lock()

    # -- transports --------------------------------------------------------------------
    def _open_connection(self) -> _Connection:
        """A connection over the configured transport, with the access-gate header when there is one."""
        if self._transport == "stdio":
            parameters = StdioServerParameters(
                command=sys.executable, args=[str(STDIO_ENTRYPOINT), "--stdio"], cwd=str(REPO_ROOT)
            )
            return _Connection(lambda: stdio_client(parameters))
        http_client = self._http_client()
        return _Connection(
            lambda: streamable_http_client(str(self._url), http_client=http_client),
            http_client=http_client,
        )

    def _http_client(self) -> httpx2.AsyncClient | None:
        """A client carrying the access-gate header, or `None` to let the SDK build its own.

        The gate is P8's; this is the seam it plugs into, because `streamable_http_client` takes an
        `httpx2.AsyncClient` rather than a headers mapping (§11, the in-process MCP client sends
        `Authorization: Bearer` on `tools/list` and on every `tools/call`).

        `LOOPBACK_TIMEOUT` is not optional here: on a 0.1-CPU free instance the first
        `search_policy_documents` call loads the ONNX session before it embeds anything, so the
        response stream stays silent for far longer than httpx2's 5 s default read timeout. A
        StreamableHTTP response stream that is silent between bytes is not a dead stream — it is a
        result still being computed — which is why the SDK's own factory reads for 300 s.
        """
        if not self._headers:
            return None
        return httpx2.AsyncClient(headers=self._headers, timeout=LOOPBACK_TIMEOUT)

    # -- discovery ---------------------------------------------------------------------
    async def discover(self, turn: TurnBuffer | None = None) -> DiscoveredCatalog:
        """The cached handshake, and **one `mcp_discovery` span per turn** (§8.2 step 3)."""
        async with self._lock:
            cached = self._catalog is not None
            if not cached:
                self._catalog = await self._handshake()
            catalog = self._catalog
        assert catalog is not None
        if turn is not None:
            # The span spans the handshake on the turn that performed it, and is instantaneous
            # afterwards — which is exactly what `cached` / `handshake_ms` report (§8.2 step 3).
            ended_at = now_micros()
            started_at = ended_at if cached else ended_at - catalog.handshake_ms * 1000
            turn.add_span(
                "mcp_discovery",
                catalog.server,
                catalog.payload(cached=cached),
                started_at=started_at,
                ended_at=ended_at,
            )
        return catalog

    async def _handshake(self) -> DiscoveredCatalog:
        began = time.perf_counter()
        connection = self._open_connection()
        try:
            session, initialized = await connection.open()
            listed = await session.list_tools()
        except McpUnavailable:
            raise
        except Exception as exc:  # a transport failure is `tool_unavailable`, never a 5xx (§9.5)
            await connection.close()
            raise McpUnavailable(f"could not reach the MCP server: {exc}") from exc
        self._connection = connection
        tools = tuple(sorted((_validated(tool) for tool in listed.tools), key=lambda tool: tool.name))
        info = getattr(initialized, "server_info", None)
        return DiscoveredCatalog(
            server=getattr(info, "name", None) or "mcp",
            transport=self._transport,
            url=None if self._transport == "stdio" else str(self._url),
            protocol_version=getattr(initialized, "protocol_version", None),
            server_info=ServerInfo(name=info.name, version=info.version or "") if info is not None else None,
            tools=tools,
            catalog_sha=catalog_sha(tools),
            mcp_session_id=getattr(session, "session_id", None),
            handshake_ms=max(0, round((time.perf_counter() - began) * 1000)),
            discovered_at=now_micros(),
        )

    async def reset(self) -> None:
        """Drop the cached handshake so the next turn re-discovers — §9.5 row 1's "re-discover once"."""
        connection, self._connection = self._connection, None
        self._catalog = None
        if connection is not None:
            await connection.close()

    async def aclose(self) -> None:
        await self.reset()

    # -- calls -------------------------------------------------------------------------
    def meta(
        self,
        *,
        turn: TurnBuffer,
        parent_span_id: str | None,
        employee_id: str,
        actor_source: str,
        strategy: str | None,
        k_override: int | None,
    ) -> dict[str, Any]:
        """The three `_meta` keys of §8.7, with `null`s when the request supplied no options."""
        return {
            "mosaic/trace": {
                "trace_id": turn.session_id,
                "turn_id": turn.turn_id,
                "parent_span_id": parent_span_id,
            },
            "mosaic/actor": {"employee_id": employee_id, "source": actor_source},
            "mosaic/retrieval": {"strategy": strategy, "k_override": k_override},
        }

    async def call_tool(
        self,
        turn: TurnBuffer,
        *,
        name: str,
        arguments: dict[str, Any],
        employee_id: str,
        actor_source: str = "default",
        strategy: str | None = None,
        k_override: int | None = None,
        confirmation_token: str | None = None,
        parent_span_id: str | None = None,
        on_retrieval: Callable[[RetrievalPayload], None] | None = None,
    ) -> ToolResult:
        """One `tools/call`, its `tool_call` span, and the nested spans re-parented under it.

        `confirmation_token` is **never** taken from `arguments`: any the model supplied is dropped
        here and the one `resume_turn` passes is attached afterwards, so a fabricated token can
        never reach the server (§8.6).

        `on_retrieval` is G4's seam. The nested `retrieval` spans the server returned are handed to
        it *before* they are persisted, so a quarantine decision is on the record the eval and the
        demo read, rather than applied to a copy after the span was written.
        """
        if self._catalog is None or self._connection is None or self._connection.session is None:
            await self.reset()
            await self.discover(None)
        catalog, connection = self._catalog, self._connection
        session = connection.session if connection is not None else None
        if catalog is None or session is None:
            raise McpUnavailable("no MCP session")

        sent = {key: value for key, value in arguments.items() if key != TOKEN_ARGUMENT}
        if confirmation_token:
            sent[TOKEN_ARGUMENT] = confirmation_token
        meta = self.meta(
            turn=turn,
            parent_span_id=parent_span_id,
            employee_id=employee_id,
            actor_source=actor_source,
            strategy=strategy,
            k_override=k_override,
        )

        # §11.3's narration, before the wire: the rail says what this tool is for while it runs,
        # under the id the `tool_call` span will carry, and `web/narration.py` is the only reader of
        # the arguments handed to it.
        step_span_id = turn.open_span("tool_call", name, parent_span_id=parent_span_id, detail={"arguments": sent})
        started_at = now_micros()
        try:
            result = await session.call_tool(name, sent, meta=meta)
        except Exception as exc:  # the transport, not the tool: §9.5 row 1
            raise McpUnavailable(f"{name} could not be called: {exc}") from exc
        ended_at = now_micros()

        body = read_body(result)
        envelope = body.pop(TRACE_KEY, None) or {}
        # §7.4's injection shield, before the span and before the conversation, over **every** tool
        # result rather than over the search one: every result is appended to the act conversation
        # verbatim, `get_policy_section` returns a whole section of policy text, and W2-C's rule 6
        # steers the model at it for "a section no search returned" — which is what a quarantined
        # hit is. A string that gives the assistant orders must not be readable anywhere downstream
        # of here (W2-C). `search_policy_documents` takes the same decision server-side; this is the
        # client's own shield, which holds against any MCP server it is pointed at.
        g4.quarantine_tool_result(name, body)
        actor = envelope.get("actor") or {}
        is_error = bool(getattr(result, "is_error", False))
        text = json.dumps(body, ensure_ascii=False)
        span_id = turn.add_span(
            "tool_call",
            name,
            span_id=step_span_id,
            payload=ToolCallPayload(
                server=envelope.get("server") or catalog.server,
                transport=envelope.get("transport") or catalog.transport,
                tool_name=name,
                # The arguments **as sent**, which is what §8.6 step 3 mints a token from.
                arguments=sent,
                result_json=text,
                structured_content=body,
                is_error=is_error,
                error_code=body.get("code"),
                duration_ms=max(0, (ended_at - started_at) // 1000),
                server_timing_ms=envelope.get("server_timing_ms"),
                actor_employee_id=actor.get("employee_id") or employee_id,
                actor_source=actor.get("source") or actor_source,
            ),
            parent_span_id=parent_span_id,
            started_at=started_at,
            ended_at=ended_at,
            status="error" if is_error else "ok",
            error_message=body.get("code") if is_error else None,
        )

        retrievals = self._lift(turn, envelope, parent_span_id=span_id, on_retrieval=on_retrieval)
        return ToolResult(
            tool_name=name,
            arguments=sent,
            body=body,
            is_error=is_error,
            error_code=body.get("code"),
            span_id=span_id,
            duration_ms=max(0, (ended_at - started_at) // 1000),
            text=text,
            retrievals=retrievals,
        )

    def _lift(
        self,
        turn: TurnBuffer,
        envelope: dict[str, Any],
        *,
        parent_span_id: str,
        on_retrieval: Callable[[RetrievalPayload], None] | None,
    ) -> list[RetrievalPayload]:
        """Re-parent the server's nested spans under our `tool_call` span (§8.7).

        The server never writes a span — `core/trace.py` is the only writer, and over stdio there is
        no turn to write into — so the spans cross as JSON and are persisted here, which keeps the
        audit trail complete if the MCP server is ever split into its own service.
        """
        retrievals: list[RetrievalPayload] = []
        for nested in envelope.get("spans") or []:
            payload: Any = nested.get("payload") or {}
            if nested.get("kind") == "retrieval":
                payload = RetrievalPayload.model_validate(payload)
                if on_retrieval is not None:
                    on_retrieval(payload)
                retrievals.append(payload)
            turn.add_span(
                nested.get("kind", "retrieval"),
                nested.get("name", "tool"),
                payload,
                span_id=nested.get("span_id"),
                parent_span_id=parent_span_id,
                started_at=nested.get("started_at"),
                ended_at=nested.get("ended_at"),
                status=nested.get("status", "ok"),
            )
        return retrievals


__all__ = [
    "HIT_TELEMETRY_KEYS",
    "LOOPBACK_TIMEOUT",
    "RAG_TOOLS",
    "SEARCH_TELEMETRY_KEYS",
    "STDIO_ENTRYPOINT",
    "TOKEN_ARGUMENT",
    "TRACE_KEY",
    "DiscoveredCatalog",
    "McpClient",
    "McpUnavailable",
    "ToolResult",
    "catalog_sha",
    "prompt_body",
    "read_body",
]
