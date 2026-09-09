"""The two store backends behind one narrow interface (spec §12.1).

`execute(sql, params) -> Rows` and `batch(stmts) -> list[Rows]` are the whole contract.
Both backends speak the **identical** SQLite dialect (SQLite ⊃ libSQL) and apply the identical
numbered migrations from `core/migrations/00N_*.sql`, so dev, CI, production, the dashboard and
the evaluation harness all read and write the same statements.

| Environment            | Backend          | Selected by                                     |
|------------------------|------------------|-------------------------------------------------|
| local dev, CI, tests   | `SqliteStore`    | `TURSO_DATABASE_URL` absent                     |
| production (Render)    | `TursoHTTPStore` | `TURSO_DATABASE_URL` **and** `TURSO_AUTH_TOKEN` |
| forced fallback        | `SqliteStore`    | `PERSIST_BACKEND=sqlite`                        |

Both backends are **synchronous**. An async caller wraps a call in `asyncio.to_thread(...)`,
exactly as §2.1 mandates for every other blocking call, so the single worker's event loop is
never blocked. `SqliteStore` is therefore guarded by a lock and opened with
`check_same_thread=False`.
"""

from __future__ import annotations

import base64
import logging
import sqlite3
import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from hrmosaic.settings import Settings
from hrmosaic.settings import settings as default_settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

SCHEMA_MIGRATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)"
)


def now_micros() -> int:
    """Epoch microseconds — the unit every timestamp column in §10.1 stores."""
    return time.time_ns() // 1000


class StoreError(RuntimeError):
    """Any failure from either backend, so callers never see a backend-specific exception."""


@dataclass(frozen=True)
class Statement:
    """One SQL statement plus its positional parameters."""

    sql: str
    params: Sequence[Any] = ()


@dataclass(frozen=True)
class Rows:
    """A result set, identical in shape whichever backend produced it."""

    columns: tuple[str, ...] = ()
    rows: tuple[tuple[Any, ...], ...] = ()
    rows_affected: int = 0

    def dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]

    def one(self) -> dict[str, Any] | None:
        """The first row as a dict, or `None` when the result set is empty."""
        return self.dicts()[0] if self.rows else None

    def scalar(self) -> Any:
        """The first column of the first row — the `SELECT COUNT(*)` shape."""
        return self.rows[0][0] if self.rows else None

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.dicts())

    def __len__(self) -> int:
        return len(self.rows)


class Store(Protocol):
    """The narrow interface every caller (trace, archive, retention, the dashboard) uses."""

    backend: str

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Rows: ...

    def batch(self, stmts: Sequence[Statement]) -> list[Rows]: ...

    def close(self) -> None: ...


# --------------------------------------------------------------------------------------
# SqliteStore
# --------------------------------------------------------------------------------------


class SqliteStore:
    """The local store: one SQLite file, WAL, foreign keys on."""

    backend = "sqlite"

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Rows:
        with self._lock:
            try:
                return _rows_from_cursor(self._connection.execute(sql, tuple(params)))
            except sqlite3.Error as exc:
                raise StoreError(f"{exc} [{sql.strip().splitlines()[0]}]") from exc

    def batch(self, stmts: Sequence[Statement]) -> list[Rows]:
        with self._lock:
            results: list[Rows] = []
            self._connection.execute("BEGIN")
            try:
                for stmt in stmts:
                    results.append(_rows_from_cursor(self._connection.execute(stmt.sql, tuple(stmt.params))))
            except sqlite3.Error as exc:
                self._connection.execute("ROLLBACK")
                raise StoreError(f"{exc} [{stmt.sql.strip().splitlines()[0]}]") from exc
            self._connection.execute("COMMIT")
            return results

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _rows_from_cursor(cursor: sqlite3.Cursor) -> Rows:
    if cursor.description is None:
        return Rows(rows_affected=max(cursor.rowcount, 0))
    columns = tuple(column[0] for column in cursor.description)
    rows = tuple(tuple(row) for row in cursor.fetchall())
    return Rows(columns=columns, rows=rows, rows_affected=max(cursor.rowcount, 0))


# --------------------------------------------------------------------------------------
# TursoHTTPStore — Hrana over HTTP, `POST <db>/v2/pipeline`
# --------------------------------------------------------------------------------------


def pipeline_url(database_url: str) -> str:
    """`libsql://db-org.turso.io` → `https://db-org.turso.io/v2/pipeline`."""
    url = database_url.strip().rstrip("/")
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://") :]
    elif url.startswith("ws://"):
        url = "http://" + url[len("ws://") :]
    elif url.startswith("wss://"):
        url = "https://" + url[len("wss://") :]
    return f"{url}/v2/pipeline"


def _encode_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _decode_value(value: dict[str, Any]) -> Any:
    kind = value["type"]
    if kind == "null":
        return None
    if kind == "integer":
        return int(value["value"])
    if kind == "float":
        return float(value["value"])
    if kind == "blob":
        return base64.b64decode(value["base64"])
    return value["value"]


def _encode_stmt(stmt: Statement) -> dict[str, Any]:
    return {"sql": stmt.sql, "args": [_encode_value(param) for param in stmt.params]}


def _rows_from_hrana(result: dict[str, Any]) -> Rows:
    columns = tuple(column["name"] for column in result.get("cols", []))
    rows = tuple(tuple(_decode_value(cell) for cell in row) for row in result.get("rows", []))
    return Rows(columns=columns, rows=rows, rows_affected=int(result.get("affected_row_count") or 0))


class TursoHTTPStore:
    """The production store: one `POST /v2/pipeline` round trip per `execute` / `batch`.

    A `batch` is sent as a single Hrana *batch* request whose steps are `BEGIN`, the caller's
    statements each conditioned on its predecessor, a `COMMIT` conditioned on the last one, and a
    `ROLLBACK` that runs only when the commit did not — so a turn's end-of-turn flush is one
    atomic round trip, as §10.3 requires.
    """

    backend = "turso"

    def __init__(
        self,
        database_url: str,
        auth_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.url = pipeline_url(database_url)
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"},
        )

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Rows:
        response = self._pipeline([{"type": "execute", "stmt": _encode_stmt(Statement(sql, params))}])
        return _rows_from_hrana(response[0]["response"]["result"])

    def batch(self, stmts: Sequence[Statement]) -> list[Rows]:
        steps: list[dict[str, Any]] = [{"stmt": {"sql": "BEGIN", "args": []}}]
        for index, stmt in enumerate(stmts):
            steps.append({"condition": {"type": "ok", "step": index}, "stmt": _encode_stmt(stmt)})
        commit_step = len(stmts) + 1
        steps.append({"condition": {"type": "ok", "step": len(stmts)}, "stmt": {"sql": "COMMIT", "args": []}})
        steps.append(
            {
                "condition": {"type": "not", "cond": {"type": "ok", "step": commit_step}},
                "stmt": {"sql": "ROLLBACK", "args": []},
            }
        )
        response = self._pipeline([{"type": "batch", "batch": {"steps": steps}}])
        result = response[0]["response"]["result"]
        errors = [error for error in result["step_errors"] if error]
        if errors:
            raise StoreError(errors[0].get("message", "batch step failed"))
        if result["step_results"][commit_step] is None:
            raise StoreError("batch did not commit")
        return [_rows_from_hrana(step) for step in result["step_results"][1 : len(stmts) + 1]]

    def close(self) -> None:
        self._client.close()

    # -- wire ---------------------------------------------------------------------------
    def _pipeline(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payload = {"requests": [*requests, {"type": "close"}]}
        try:
            response = self._client.post(self.url, json=payload)
        except httpx.HTTPError as exc:
            raise StoreError(f"turso request failed: {exc}") from exc
        if response.status_code != 200:
            raise StoreError(f"turso responded {response.status_code}: {response.text[:200]}")
        results = response.json()["results"]
        for result in results:
            if result.get("type") == "error":
                raise StoreError(result["error"].get("message", "turso error"))
        return results


# --------------------------------------------------------------------------------------
# Migrations
# --------------------------------------------------------------------------------------


def split_statements(sql_text: str) -> list[str]:
    """Split a migration file into statements, dropping `--` comments and blank lines."""
    stripped = "\n".join(line.split("--", 1)[0] for line in sql_text.splitlines())
    return [statement.strip() for statement in stripped.split(";") if statement.strip()]


def migrate(store: Store) -> list[str]:
    """Apply every pending `core/migrations/00N_*.sql`, idempotently. Returns what it applied."""
    store.execute(SCHEMA_MIGRATIONS_DDL)
    applied_already = {row["version"] for row in store.execute("SELECT version FROM schema_migrations")}
    newly_applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        if version in applied_already:
            continue
        statements = [Statement(sql) for sql in split_statements(path.read_text(encoding="utf-8"))]
        statements.append(
            Statement("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (version, now_micros()))
        )
        store.batch(statements)
        newly_applied.append(version)
    return newly_applied


# --------------------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------------------


def build_store(settings: Settings | None = None) -> Store:
    """The §12.1 selection table, in code. Never raises: boot always succeeds."""
    settings = settings or default_settings
    turso_configured = bool(settings.turso_database_url and settings.turso_auth_token)
    wants_turso = settings.persist_backend == "turso" or (settings.persist_backend == "auto" and turso_configured)
    if wants_turso and turso_configured:
        return TursoHTTPStore(str(settings.turso_database_url), str(settings.turso_auth_token))
    if wants_turso:
        logger.warning("PERSIST_BACKEND=turso but TURSO_DATABASE_URL/TURSO_AUTH_TOKEN are unset; using SQLite")
    return SqliteStore(settings.trace_db_path)


@dataclass
class _StoreHolder:
    store: Store | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_holder = _StoreHolder()


def get_store(settings: Settings | None = None) -> Store:
    """The process-wide store, migrated on first use."""
    with _holder.lock:
        if _holder.store is None:
            store = build_store(settings)
            migrate(store)
            _holder.store = store
        return _holder.store


def set_store(store: Store | None) -> None:
    """Install (or clear, with `None`) the process-wide store — the seam tests and `web/` use."""
    with _holder.lock:
        _holder.store = store
