"""The one trace writer (spec §10.3). Nothing else in the application inserts a session, a turn
or a span — `tests/architecture/test_conventions.py` greps for exactly that, because a second
logging path is the failure USER.4 forbids.

**Two writes per turn, not per span.**

1. *Turn start* — one small batch: upsert the `sessions` row, insert the `turns` row with
   `started_at` and `process_uptime_ms`, read back the 1-based `seq`. Synchronous, so
   `/chat/stream` and the dashboard can see a turn in flight.
2. *Everything in between* is buffered in memory. Each closed span is published to the span
   listeners immediately — that is the live SSE rail — **and** appended to the buffer.
3. *Turn end* — one batched flush: every span, every `llm_messages` row, and the closing UPDATE
   on `turns` (rollups, `outcome`, `stop_reason`, `duration_ms`, `rss_mb_at_end`). On Turso that
   is one `/v2/pipeline` round trip.
4. *Reopen on confirm* — `reopen_turn(turn_id, awaiting_ms)` clears `ended_at` / `outcome`,
   increments `resumed_count`, adds the parked time to `awaiting_ms` and continues `seq` from
   `MAX(seq)`. The second flush closes the turn again.

Durability: `install_shutdown_handlers()` registers SIGTERM / SIGINT / `atexit` handlers that
flush the buffer and close any open turn with `outcome='error'`, and `sweep_stale_turns()` at boot
closes anything a hard kill left open for more than five minutes.

Every store call here is **synchronous**; an async caller wraps it in `asyncio.to_thread(...)`.
"""

from __future__ import annotations

import atexit
import json
import logging
import signal
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from hrmosaic.core import procstat
from hrmosaic.core.db import Statement, Store, get_store, now_micros
from hrmosaic.core.ids import new_session_id, new_span_id, new_turn_id
from hrmosaic.core.models import ErrorPayload, SpanKind, SpanStatus, TurnOutcome
from hrmosaic.core.redact import redact, redact_text
from hrmosaic.settings import settings as default_settings

logger = logging.getLogger(__name__)

# --- size control (§10.5) --------------------------------------------------------------
MAX_PAYLOAD_BYTES = 32 * 1024
MAX_LLM_PAYLOAD_BYTES = 128 * 1024
MAX_STRING_BYTES = 8 * 1024
#: The floor the per-string cap halves down to before the payload is replaced with a stub.
MIN_STRING_BYTES = 64
TRUNCATION_MARKER = "…[truncated]"

#: A turn open for longer than this when the process boots was left behind by a hard kill (§10.3).
STALE_TURN_SECONDS = 300

# --- SQL — the only place these three tables are written --------------------------------

SESSION_UPSERT = """
INSERT INTO sessions (id, created_at, last_activity_at, employee_id, auth_mode, actor_role,
                      client_label, eval_run_id, user_agent_hash, app_version, deploy_mode,
                      mcp_transport, cold_start)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(id) DO UPDATE SET last_activity_at = excluded.last_activity_at,
                              employee_id = excluded.employee_id,
                              eval_run_id = COALESCE(excluded.eval_run_id, sessions.eval_run_id)
"""

# One statement, so `seq` is allocated inside the same transaction that inserts the turn.
TURN_INSERT = """
INSERT INTO turns (id, session_id, seq, started_at, user_message, process_uptime_ms)
SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ? FROM turns WHERE session_id = ?
"""

TURN_SEQ_SELECT = "SELECT seq FROM turns WHERE id = ?"

SPAN_INSERT = """
INSERT INTO spans (id, turn_id, session_id, parent_span_id, seq, kind, name, started_at, ended_at,
                   duration_ms, status, error_message, payload_json, payload_bytes, truncated)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""

LLM_MESSAGE_INSERT = "INSERT INTO llm_messages (span_id, seq, role, content) VALUES (?,?,?,?)"

TURN_CLOSE = """
UPDATE turns SET ended_at = ?, duration_ms = ?, final_answer = ?, answer_blocks_json = ?,
                 citations_json = ?, outcome = ?, stop_reason = ?, intent = ?, workflow = ?,
                 error_kind = ?, total_tokens_in = ?, total_tokens_out = ?, llm_calls = ?,
                 tool_calls = ?, retrievals = ?, guardrail_hits = ?, llm_ms = ?, retrieval_ms = ?,
                 tool_ms = ?, store_ms = ?, provider = ?, model = ?, provider_failover = ?,
                 rss_mb_at_end = ?
WHERE id = ?
"""

TURN_REOPEN = """
UPDATE turns SET ended_at = NULL, outcome = NULL, resumed_count = resumed_count + 1,
                 awaiting_ms = awaiting_ms + ?
WHERE id = ?
"""

# §11.2: a **declined** proposal reopens the buffer only so the second `confirmation` span can be
# written through this module — the turn is closed again without ever being resumed. Counting that
# as a resume would report `resumed_count = 1` on a turn nobody resumed, which is what the
# dashboard's resumed-turn figures read.
TURN_REOPEN_UNCOUNTED = """
UPDATE turns SET ended_at = NULL, outcome = NULL, awaiting_ms = awaiting_ms + ?
WHERE id = ?
"""

TURN_ROLLUP_SELECT = """
SELECT session_id, seq, started_at, awaiting_ms, total_tokens_in, total_tokens_out, llm_calls,
       tool_calls, retrievals, guardrail_hits, llm_ms, retrieval_ms, tool_ms, store_ms,
       provider, model, provider_failover
FROM turns WHERE id = ?
"""

SPAN_MAX_SEQ_SELECT = "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM spans WHERE turn_id = ?"

SWEEP_STALE = """
UPDATE turns SET ended_at = ?,
                 duration_ms = MAX(0, (? - started_at) / 1000 - awaiting_ms),
                 outcome = 'error', stop_reason = 'error'
WHERE ended_at IS NULL AND started_at < ?
"""


# --------------------------------------------------------------------------------------
# Span listeners — the SSE hook
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SpanEvent:
    """A closed span, published the moment it closes — long before the end-of-turn flush."""

    session_id: str
    turn_id: str
    span_id: str
    parent_span_id: str | None
    seq: int
    kind: SpanKind
    name: str
    status: SpanStatus
    started_at: int
    ended_at: int
    duration_ms: int
    payload: dict[str, Any]
    error_message: str | None = None


SpanListener = Callable[[SpanEvent], None]

_listeners: list[SpanListener] = []
_listener_lock = threading.RLock()


def register_span_listener(listener: SpanListener) -> Callable[[], None]:
    """Register a listener for every closed span. Returns the callable that unregisters it."""
    with _listener_lock:
        _listeners.append(listener)

    def unregister() -> None:
        with _listener_lock:
            if listener in _listeners:
                _listeners.remove(listener)

    return unregister


def clear_span_listeners() -> None:
    """Drop every listener — used by tests and by a process that is shutting down."""
    with _listener_lock:
        _listeners.clear()


def _publish(event: SpanEvent) -> None:
    with _listener_lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(event)
        except Exception:  # a dead SSE client must not cost us the record
            logger.warning("span listener %r raised; the span is still persisted", listener, exc_info=True)


# --------------------------------------------------------------------------------------
# Payload preparation (§10.4 redaction, §10.5 size control)
# --------------------------------------------------------------------------------------


def _as_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    if isinstance(payload, dict):
        return dict(payload)
    raise TypeError(f"a span payload must be a model or a dict, not {type(payload).__name__}")


def _cap_strings(node: Any, limit: int) -> Any:
    if isinstance(node, dict):
        return {key: _cap_strings(value, limit) for key, value in node.items()}
    if isinstance(node, list):
        return [_cap_strings(item, limit) for item in node]
    if isinstance(node, str) and len(node.encode("utf-8")) > limit:
        return node.encode("utf-8")[:limit].decode("utf-8", "ignore") + TRUNCATION_MARKER
    return node


def _serialise(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _every_list(node: Any) -> Iterator[list[Any]]:
    """Every list anywhere in the payload — a nested one counts as much as a top-level one."""
    if isinstance(node, dict):
        for value in node.values():
            yield from _every_list(value)
    elif isinstance(node, list):
        yield node
        for item in node:
            yield from _every_list(item)


def _shed_longest_list(body: dict[str, Any]) -> bool:
    """Drop elements off the longest collection in `body`. False when there is nothing left to shed.

    `body` is always a fresh structure built by `_cap_strings`, so mutating a list found inside it
    never touches the caller's payload. Long lists shed a slice at a time rather than one element,
    so a payload holding thousands of items still converges in a bounded number of passes.
    """
    candidates = [item for item in _every_list(body) if item]
    if not candidates:
        return False
    longest = max(candidates, key=len)
    del longest[-max(1, len(longest) // 16) :]
    return True


def prepare_payload(kind: str, payload: Any) -> tuple[str, int, bool]:
    """Redact, then size-control. Returns `(payload_json, payload_bytes, truncated)`.

    `payload_bytes` is the **pre-truncation** size, so the dashboard can badge a truncated
    payload honestly (§10.5), and `truncated` is true whenever the stored JSON differs from the
    redacted original — never a `break` that leaves an over-cap payload recorded as intact.

    The loop only ever exits under the cap: shed the longest collection (nested ones included),
    then halve the per-string cap down to `MIN_STRING_BYTES`, and if even that will not fit,
    store the `payload_oversize` stub. §17 counts these caps as a denial-of-service control.
    """
    body = _as_dict(payload)
    body.setdefault("kind", kind)
    body = redact(body)
    original = _serialise(body)
    payload_bytes = len(original.encode("utf-8"))

    cap = MAX_LLM_PAYLOAD_BYTES if kind == "llm_call" else MAX_PAYLOAD_BYTES
    limit = MAX_STRING_BYTES
    body = _cap_strings(body, limit)
    serialised = _serialise(body)
    while len(serialised.encode("utf-8")) > cap:
        if not _shed_longest_list(body):
            if limit <= MIN_STRING_BYTES:
                logger.warning("payload of %d bytes will not fit the %d byte cap; stored a stub", payload_bytes, cap)
                stub = {"kind": kind, "error_kind": "payload_oversize", "payload_bytes": payload_bytes}
                return _serialise(stub), payload_bytes, True
            # Capping an already-capped string at a smaller limit slices the marker off first,
            # so the result carries exactly one `…[truncated]`.
            limit = max(MIN_STRING_BYTES, limit // 2)
            body = _cap_strings(body, limit)
        serialised = _serialise(body)
    return serialised, payload_bytes, serialised != original


# --------------------------------------------------------------------------------------
# Session and span records
# --------------------------------------------------------------------------------------


@dataclass
class SessionSpec:
    """The `sessions` row a turn belongs to (§10.1). Defaults come from `settings`."""

    id: str = field(default_factory=new_session_id)
    employee_id: str | None = None
    auth_mode: str = "open"
    actor_role: str = "employee"
    client_label: str = "web"
    eval_run_id: str | None = None
    user_agent_hash: str | None = None
    app_version: str = field(default_factory=lambda: default_settings.git_sha)
    deploy_mode: str = field(default_factory=lambda: default_settings.app_env)
    mcp_transport: str = field(default_factory=lambda: default_settings.mcp_transport_effective)
    cold_start: bool = False

    def row(self, *, at: int) -> tuple[Any, ...]:
        return (
            self.id,
            at,
            at,
            self.employee_id,
            self.auth_mode,
            self.actor_role,
            self.client_label,
            self.eval_run_id,
            self.user_agent_hash,
            self.app_version,
            self.deploy_mode,
            self.mcp_transport,
            int(self.cold_start),
        )


@dataclass
class _SpanRecord:
    id: str
    parent_span_id: str | None
    seq: int
    kind: str
    name: str
    started_at: int
    ended_at: int
    duration_ms: int
    status: str
    error_message: str | None
    payload_json: str
    payload_bytes: int
    truncated: bool
    payload: dict[str, Any]


class SpanContext:
    """The handle a `with turn.span(...)` body fills in."""

    def __init__(self, kind: str, name: str, *, span_id: str | None = None, parent_span_id: str | None = None) -> None:
        self.id = span_id or new_span_id()
        self.kind = kind
        self.name = name
        self.parent_span_id = parent_span_id
        self.started_at = now_micros()
        self.status: str = "ok"
        self.error_message: str | None = None
        self.payload: Any = None
        self.messages: list[tuple[str, str]] = []

    def set_payload(self, payload: Any) -> None:
        """The §10.2 payload model (or an equivalent dict) for this span."""
        self.payload = payload

    def add_message(self, role: str, content: str) -> None:
        """One verbatim `llm_messages` row — never truncated, redacted like everything else."""
        self.messages.append((role, content))

    def set_error(self, message: str) -> None:
        self.status = "error"
        self.error_message = message


# --------------------------------------------------------------------------------------
# The buffered turn
# --------------------------------------------------------------------------------------


class TurnBuffer:
    """One turn in flight: spans and `llm_messages` accumulate here until `close()`."""

    def __init__(
        self,
        writer: TraceWriter,
        *,
        session_id: str,
        turn_id: str,
        seq: int,
        started_at: int,
        next_span_seq: int = 1,
        rollups: dict[str, Any] | None = None,
        awaiting_ms: int = 0,
        store_us: int = 0,
    ) -> None:
        self._writer = writer
        self.session_id = session_id
        self.turn_id = turn_id
        self.seq = seq
        self.started_at = started_at
        self.awaiting_ms = awaiting_ms
        self.closed = False
        self._next_span_seq = next_span_seq
        #: What `close()` wrote into `turns`, published so the response does not have to read it
        #: back (W1-C(c)). It is the mapping the `TURN_CLOSE` statement is built from, not a copy
        #: of it, so §11.1's "provably the same rows" is an identity rather than a promise. `None`
        #: until the turn is closed.
        self.close_totals: dict[str, int] | None = None
        self._spans: list[_SpanRecord] = []
        self._messages: list[tuple[str, int, str, str]] = []
        self._lock = threading.RLock()
        self._rollups: dict[str, Any] = {
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "llm_calls": 0,
            "tool_calls": 0,
            "retrievals": 0,
            "guardrail_hits": 0,
            "llm_ms": 0,
            "retrieval_ms": 0,
            "tool_ms": 0,
            "store_us": store_us,
            "provider": None,
            "model": None,
            "provider_failover": 0,
        }
        for key, value in (rollups or {}).items():
            if key in self._rollups and value is not None:
                self._rollups[key] = value

    # -- spans -------------------------------------------------------------------------
    @contextmanager
    def span(
        self,
        kind: SpanKind,
        name: str,
        *,
        span_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> Iterator[SpanContext]:
        """Open a span; it closes — and publishes — when the block leaves, however it leaves."""
        context = SpanContext(kind, name, span_id=span_id, parent_span_id=parent_span_id)
        try:
            yield context
        except Exception as exc:
            self._finish(context, exc)
            raise
        self._finish(context, None)

    def _finish(self, context: SpanContext, exc: BaseException | None) -> None:
        kind, payload = context.kind, context.payload
        if exc is not None:
            context.set_error(f"{type(exc).__name__}: {exc}")
            if payload is None:
                # Nothing was recorded before the failure: the honest record is an `error` span
                # naming the component that broke.
                kind = "error"
                payload = ErrorPayload(
                    error_kind=type(exc).__name__,
                    message=str(exc),
                    component=context.kind,
                )
        self.add_span(
            kind,
            context.name,
            payload,
            span_id=context.id,
            parent_span_id=context.parent_span_id,
            started_at=context.started_at,
            status=context.status,
            error_message=context.error_message,
            messages=context.messages,
        )

    def add_span(
        self,
        kind: SpanKind,
        name: str,
        payload: Any,
        *,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        started_at: int | None = None,
        ended_at: int | None = None,
        status: SpanStatus = "ok",
        error_message: str | None = None,
        messages: Sequence[tuple[str, str]] = (),
    ) -> str:
        """Buffer an already-timed span. Returns its id."""
        if self.closed:
            raise RuntimeError(f"turn {self.turn_id} is closed; reopen it before writing spans")
        if payload is None:
            # The row is still written — losing a record is worse than writing a thin one — but a
            # payload that cannot be parsed back into the §10.2 union is a bug in the caller.
            logger.warning("span %s/%s was recorded with no payload", kind, name)
        span_id = span_id or new_span_id()
        started_at = started_at if started_at is not None else now_micros()
        ended_at = ended_at if ended_at is not None else now_micros()
        payload_json, payload_bytes, truncated = prepare_payload(kind, payload)
        record = _SpanRecord(
            id=span_id,
            parent_span_id=parent_span_id,
            seq=self._take_seq(),
            kind=kind,
            name=name,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=max(0, (ended_at - started_at) // 1000),
            status=status,
            error_message=error_message,
            payload_json=payload_json,
            payload_bytes=payload_bytes,
            truncated=truncated,
            payload=json.loads(payload_json),
        )
        with self._lock:
            self._spans.append(record)
            for index, (role, content) in enumerate(messages, start=1):
                self._messages.append((span_id, index, role, redact_text(content)))
            self._accumulate(record)
        _publish(
            SpanEvent(
                session_id=self.session_id,
                turn_id=self.turn_id,
                span_id=record.id,
                parent_span_id=record.parent_span_id,
                seq=record.seq,
                kind=record.kind,
                name=record.name,
                status=record.status,
                started_at=record.started_at,
                ended_at=record.ended_at,
                duration_ms=record.duration_ms,
                payload=record.payload,
                error_message=record.error_message,
            )
        )
        return span_id

    def rearm(self) -> None:
        """Accept spans again after a process-exit checkpoint (§10.3).

        Only `flush_open_turns()` calls this, and only on a turn it has just written out. The
        span sequence continues from where the checkpoint left it and the rollups keep
        accumulating, so a turn that survives the checkpoint reads exactly as it would have
        without one; a turn that does not survive keeps the `error` row the checkpoint wrote.

        This is deliberately **not** `TraceWriter.reopen_turn()`: that is §10.3 step 4's
        human-confirmation resume, which re-reads the turn from the store, bumps `resumed_count`
        and adds to `awaiting_ms`. Nothing was awaiting anybody here.
        """
        with self._lock:
            self.closed = False

    def _take_seq(self) -> int:
        with self._lock:
            seq = self._next_span_seq
            self._next_span_seq += 1
            return seq

    def _accumulate(self, record: _SpanRecord) -> None:
        rollups, payload = self._rollups, record.payload
        if record.kind == "llm_call":
            rollups["llm_calls"] += 1
            rollups["llm_ms"] += record.duration_ms
            rollups["total_tokens_in"] += int(payload.get("prompt_tokens") or 0)
            rollups["total_tokens_out"] += int(payload.get("completion_tokens") or 0)
            rollups["provider"] = payload.get("provider") or rollups["provider"]
            rollups["model"] = payload.get("model") or rollups["model"]
            if payload.get("provider_failover"):
                rollups["provider_failover"] = 1
        elif record.kind == "tool_call":
            rollups["tool_calls"] += 1
            rollups["tool_ms"] += record.duration_ms
        elif record.kind == "retrieval":
            rollups["retrievals"] += 1
            rollups["retrieval_ms"] += record.duration_ms
        elif record.kind == "guardrail" and payload.get("verdict") not in (None, "allow"):
            rollups["guardrail_hits"] += 1

    # -- close -------------------------------------------------------------------------
    def close(
        self,
        *,
        outcome: TurnOutcome,
        stop_reason: str | None = None,
        final_answer: str | None = None,
        answer_blocks: Any = None,
        citations: Any = None,
        intent: str | None = None,
        workflow: str | None = None,
        error_kind: str | None = None,
    ) -> None:
        """The end-of-turn flush: every span, every message and the closing UPDATE, in one batch."""
        with self._lock:
            if self.closed:
                return
            spans, messages = list(self._spans), list(self._messages)
            self._spans.clear()
            self._messages.clear()
            self.closed = True

        ended_at = now_micros()
        rollups = self._rollups
        # The ten published numbers, computed once. `TURN_CLOSE` below is built from this mapping
        # and the response reads the same one, so a turn's `usage`/`timings` cannot drift from its
        # audit row. `store_ms` is the store time spent *before* this flush, which is exactly what
        # the column has always held: the closing batch cannot bill itself.
        totals = {
            "ended_at": ended_at,
            "duration_ms": max(0, (ended_at - self.started_at) // 1000 - self.awaiting_ms),
            "total_tokens_in": rollups["total_tokens_in"],
            "total_tokens_out": rollups["total_tokens_out"],
            "llm_calls": rollups["llm_calls"],
            "tool_calls": rollups["tool_calls"],
            "retrievals": rollups["retrievals"],
            "guardrail_hits": rollups["guardrail_hits"],
            "llm_ms": rollups["llm_ms"],
            "retrieval_ms": rollups["retrieval_ms"],
            "tool_ms": rollups["tool_ms"],
            "store_ms": round(rollups["store_us"] / 1000),
        }
        self.close_totals = totals
        statements = [
            Statement(
                SPAN_INSERT,
                (
                    span.id,
                    self.turn_id,
                    self.session_id,
                    span.parent_span_id,
                    span.seq,
                    span.kind,
                    span.name,
                    span.started_at,
                    span.ended_at,
                    span.duration_ms,
                    span.status,
                    span.error_message,
                    span.payload_json,
                    span.payload_bytes,
                    int(span.truncated),
                ),
            )
            for span in spans
        ]
        statements += [Statement(LLM_MESSAGE_INSERT, message) for message in messages]
        statements.append(
            Statement(
                TURN_CLOSE,
                (
                    totals["ended_at"],
                    totals["duration_ms"],
                    redact_text(final_answer) if final_answer else final_answer,
                    _dump_redacted_json(answer_blocks),
                    _dump_redacted_json(citations),
                    outcome,
                    stop_reason,
                    intent,
                    workflow,
                    error_kind,
                    totals["total_tokens_in"],
                    totals["total_tokens_out"],
                    totals["llm_calls"],
                    totals["tool_calls"],
                    totals["retrievals"],
                    totals["guardrail_hits"],
                    totals["llm_ms"],
                    totals["retrieval_ms"],
                    totals["tool_ms"],
                    totals["store_ms"],
                    rollups["provider"],
                    rollups["model"],
                    rollups["provider_failover"],
                    procstat.rss_mb(),
                    self.turn_id,
                ),
            )
        )
        self._writer._flush(self.turn_id, statements)


def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    if isinstance(value, list) and value and isinstance(value[0], BaseModel):
        return json.dumps([item.model_dump(mode="json") for item in value], ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _dump_redacted_json(value: Any) -> str | None:
    """Serialise, then redact — `answer_blocks_json` and `citations_json` hold the same
    model-generated prose as `final_answer`, and §10.4 runs `redact()` over all of it. Scrubbing
    one column and persisting the leak verbatim in the next is the failure §17 forbids."""
    dumped = _dump_json(value)
    if dumped is None:
        return None
    try:
        structure = json.loads(dumped)
    except json.JSONDecodeError:  # a caller handed us prose, not JSON
        return redact_text(dumped)
    return json.dumps(redact(structure), ensure_ascii=False)


# --------------------------------------------------------------------------------------
# The writer
# --------------------------------------------------------------------------------------


class TraceWriter:
    """Owns the store and the open turns. One per process, installed with `set_writer()`."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._open: dict[str, TurnBuffer] = {}
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------------------
    def start_turn(
        self,
        session: SessionSpec,
        *,
        user_message: str,
        turn_id: str | None = None,
    ) -> TurnBuffer:
        turn_id = turn_id or new_turn_id()
        started_at = now_micros()
        began = time.perf_counter()
        results = self.store.batch(
            [
                Statement(SESSION_UPSERT, session.row(at=started_at)),
                Statement(
                    TURN_INSERT,
                    (
                        turn_id,
                        session.id,
                        started_at,
                        redact_text(user_message),
                        procstat.uptime_ms(),
                        session.id,
                    ),
                ),
                Statement(TURN_SEQ_SELECT, (turn_id,)),
            ]
        )
        store_us = int((time.perf_counter() - began) * 1_000_000)
        buffer = TurnBuffer(
            self,
            session_id=session.id,
            turn_id=turn_id,
            seq=int(results[2].scalar()),
            started_at=started_at,
            store_us=store_us,
        )
        with self._lock:
            self._open[turn_id] = buffer
        return buffer

    def reopen_turn(self, turn_id: str, awaiting_ms: int, *, resumed: bool = True) -> TurnBuffer:
        """§10.3 step 4 — `/chat/confirm` resumes a parked turn.

        `resumed=False` reopens the buffer **without** bumping `resumed_count`: the decline path of
        §11.2 reopens only so its second `confirmation` span goes through this module, and then
        closes the turn again without ever resuming it.
        """
        began = time.perf_counter()
        results = self.store.batch(
            [
                Statement(TURN_REOPEN if resumed else TURN_REOPEN_UNCOUNTED, (awaiting_ms, turn_id)),
                Statement(TURN_ROLLUP_SELECT, (turn_id,)),
                Statement(SPAN_MAX_SEQ_SELECT, (turn_id,)),
            ]
        )
        store_us = int((time.perf_counter() - began) * 1_000_000)
        row = results[1].one()
        if row is None:
            raise KeyError(f"no such turn: {turn_id}")
        buffer = TurnBuffer(
            self,
            session_id=row["session_id"],
            turn_id=turn_id,
            seq=row["seq"],
            started_at=row["started_at"],
            next_span_seq=int(results[2].scalar()) + 1,
            rollups=row,
            awaiting_ms=row["awaiting_ms"],
            store_us=(row["store_ms"] or 0) * 1000 + store_us,
        )
        with self._lock:
            self._open[turn_id] = buffer
        return buffer

    def open_turns(self) -> list[TurnBuffer]:
        with self._lock:
            return [buffer for buffer in self._open.values() if not buffer.closed]

    def flush_open_turns(self) -> int:
        """Close every open turn as an error — the SIGTERM / `atexit` path (§10.3).

        **A checkpoint, not a guillotine.** A SIGTERM does not end the process under uvicorn: the
        server finishes every in-flight request and only then runs the lifespan's shutdown. So a
        turn flushed here is very often one that is still being served, and closing it outright
        closed it *under its own request* — the next span that request wrote raised `turn … is
        closed`, the answer degraded to §12.3's catch-all escalation, and the turn was recorded as
        a process exit although it had completed. On Render, where every redeploy and every
        spin-down sends SIGTERM, that was one broken answer per shutdown.

        Each buffer is therefore **re-armed** after its rows are written. If the process really is
        about to vanish, nothing more arrives and the row stays `error` / `error` — the durability
        guarantee §10.3 asks for, unchanged. If the request does finish, its own `close()`
        overwrites that row with the truth, exactly as §10.3 step 4's reopen does for a
        confirmation (minus the `resumed_count` bump: nothing was awaiting a human).
        """
        closed = 0
        for buffer in self.open_turns():
            try:
                buffer.close(outcome="error", stop_reason="error", error_kind="process_exit")
                buffer.rearm()
                closed += 1
            except Exception:  # shutdown must never raise
                logger.warning("could not flush turn %s", buffer.turn_id, exc_info=True)
        return closed

    def sweep_stale_turns(self, older_than_s: int = STALE_TURN_SECONDS) -> int:
        """Close anything a hard kill left open. Runs at boot (§10.3)."""
        now = now_micros()
        cutoff = now - older_than_s * 1_000_000
        return self.store.execute(SWEEP_STALE, (now, now, cutoff)).rows_affected

    # -- internal ----------------------------------------------------------------------
    def _flush(self, turn_id: str, statements: Sequence[Statement]) -> None:
        try:
            self.store.batch(statements)
        finally:
            with self._lock:
                # The pop happens *before* `flush_open_turns()` re-arms the buffer, so the buffer a
                # SIGTERM checkpointed is no longer open: the `atexit` hook that follows finds
                # nothing, and spans a re-armed turn writes before the process really does vanish
                # are lost. The `error`/`process_exit` row is already written and survives, which is
                # the durability §10.3 guarantees — the later spans are not part of it.
                self._open.pop(turn_id, None)


# --------------------------------------------------------------------------------------
# Process-wide writer and the shutdown handlers
# --------------------------------------------------------------------------------------

_writer: TraceWriter | None = None
_writer_lock = threading.RLock()
_handlers_installed = False


def get_writer() -> TraceWriter:
    """The process-wide writer, built over the process-wide store on first use."""
    global _writer
    with _writer_lock:
        if _writer is None:
            _writer = TraceWriter(get_store())
        return _writer


def set_writer(writer: TraceWriter | None) -> None:
    """Install (or clear, with `None`) the process-wide writer."""
    global _writer
    with _writer_lock:
        _writer = writer


def start_turn(session: SessionSpec, *, user_message: str, turn_id: str | None = None) -> TurnBuffer:
    return get_writer().start_turn(session, user_message=user_message, turn_id=turn_id)


def reopen_turn(turn_id: str, awaiting_ms: int, *, resumed: bool = True) -> TurnBuffer:
    return get_writer().reopen_turn(turn_id, awaiting_ms, resumed=resumed)


def open_turns() -> list[TurnBuffer]:
    """Every turn still buffered, or `[]` when no writer is installed.

    The read-only seam `web/` uses to close a turn an unmodelled failure left open (§12.3): the
    close still happens through this module, so there is still exactly one trace writer.
    """
    with _writer_lock:
        writer = _writer
    return writer.open_turns() if writer is not None else []


def flush_open_turns() -> int:
    with _writer_lock:
        writer = _writer
    return writer.flush_open_turns() if writer is not None else 0


def sweep_stale_turns(*, store: Store | None = None, older_than_s: int = STALE_TURN_SECONDS) -> int:
    """Boot-time repair. Takes a store directly, because it runs before any turn exists."""
    writer = TraceWriter(store) if store is not None else get_writer()
    return writer.sweep_stale_turns(older_than_s=older_than_s)


def install_shutdown_handlers() -> None:
    """Register SIGTERM / SIGINT / `atexit` flushes. Idempotent; safe off the main thread."""
    global _handlers_installed
    with _writer_lock:
        if _handlers_installed:
            return
        _handlers_installed = True
    atexit.register(flush_open_turns)
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            previous = signal.getsignal(signum)
            signal.signal(signum, _make_handler(signum, previous))
        except ValueError:  # not the main thread — the atexit hook still covers us
            logger.warning("could not install a handler for signal %s off the main thread", signum)


def _make_handler(signum: int, previous: Any) -> Callable[[int, Any], None]:
    def handler(received: int, frame: Any) -> None:
        flush_open_turns()
        if callable(previous):
            previous(received, frame)
        elif previous == signal.SIG_DFL:
            signal.signal(received, signal.SIG_DFL)
            signal.raise_signal(received)

    return handler


def reset_shutdown_handlers() -> None:
    """Forget that handlers were installed — the seam the shutdown tests use."""
    global _handlers_installed
    with _writer_lock:
        _handlers_installed = False
    atexit.unregister(flush_open_turns)
