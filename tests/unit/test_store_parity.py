"""Both store backends answer identically for the same statement sequence (spec §12.1).

`TursoHTTPStore` is exercised against an httpx `MockTransport` that speaks the real Hrana
`/v2/pipeline` wire shape and executes the SQL it receives against an in-memory SQLite
database — so the test compares two genuine executions, never a recorded fixture, and never
touches a live Turso database.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from typing import Any

import httpx
import pytest

from hrmosaic.core.db import (
    SqliteStore,
    Statement,
    StoreError,
    TursoHTTPStore,
    build_store,
    migrate,
)

# --------------------------------------------------------------------------------------
# A minimal Turso/Hrana server over httpx.MockTransport, backed by real SQLite.
# --------------------------------------------------------------------------------------


def _encode(value: Any) -> dict[str, Any]:
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


def _decode(value: dict[str, Any]) -> Any:
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


class FakeTursoServer:
    """Executes Hrana pipeline requests against one in-memory SQLite connection."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.isolation_level = None  # explicit BEGIN/COMMIT, like the real thing
        self.requests_seen: list[str] = []
        self.auth_headers: list[str | None] = []

    # -- wire -------------------------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/pipeline", request.url.path
        self.auth_headers.append(request.headers.get("authorization"))
        body = json.loads(request.content)
        results = []
        for item in body["requests"]:
            self.requests_seen.append(item["type"])
            if item["type"] == "close":
                results.append({"type": "ok", "response": {"type": "close"}})
            elif item["type"] == "execute":
                results.append(self._execute_response(item["stmt"]))
            elif item["type"] == "batch":
                results.append(self._batch_response(item["batch"]))
            else:  # pragma: no cover - the store sends nothing else
                raise AssertionError(f"unexpected request type {item['type']}")
        return httpx.Response(200, json={"baton": None, "base_url": None, "results": results})

    # -- steps ------------------------------------------------------------------------
    def _run(self, stmt: dict[str, Any]) -> dict[str, Any]:
        cursor = self.connection.execute(stmt["sql"], [_decode(arg) for arg in stmt.get("args", [])])
        cols = [{"name": d[0], "decltype": None} for d in (cursor.description or [])]
        rows = [[_encode(cell) for cell in row] for row in cursor.fetchall()] if cursor.description else []
        return {
            "cols": cols,
            "rows": rows,
            "affected_row_count": max(cursor.rowcount, 0),
            "last_insert_rowid": None,
            "rows_read": len(rows),
            "rows_written": 0,
        }

    def _execute_response(self, stmt: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"type": "ok", "response": {"type": "execute", "result": self._run(stmt)}}
        except sqlite3.Error as exc:
            return {"type": "error", "error": {"message": str(exc), "code": "SQLITE_ERROR"}}

    def _batch_response(self, batch: dict[str, Any]) -> dict[str, Any]:
        step_results: list[dict[str, Any] | None] = []
        step_errors: list[dict[str, Any] | None] = []
        for step in batch["steps"]:
            if not self._condition_met(step.get("condition"), step_results, step_errors):
                step_results.append(None)
                step_errors.append(None)
                continue
            try:
                step_results.append(self._run(step["stmt"]))
                step_errors.append(None)
            except sqlite3.Error as exc:
                step_results.append(None)
                step_errors.append({"message": str(exc), "code": "SQLITE_ERROR"})
        return {
            "type": "ok",
            "response": {
                "type": "batch",
                "result": {"step_results": step_results, "step_errors": step_errors},
            },
        }

    def _condition_met(
        self,
        condition: dict[str, Any] | None,
        results: list[dict[str, Any] | None],
        errors: list[dict[str, Any] | None],
    ) -> bool:
        if condition is None:
            return True
        if condition["type"] == "ok":
            return results[condition["step"]] is not None
        if condition["type"] == "not":
            return not self._condition_met(condition["cond"], results, errors)
        raise AssertionError(f"unexpected condition {condition['type']}")  # pragma: no cover


@pytest.fixture
def turso_server() -> FakeTursoServer:
    server = FakeTursoServer()
    yield server
    server.connection.close()


@pytest.fixture
def stores(tmp_path, turso_server: FakeTursoServer) -> list[Any]:
    sqlite_store = SqliteStore(tmp_path / "traces.sqlite")
    turso_store = TursoHTTPStore(
        "libsql://parity-test.turso.io",
        "test-token",
        transport=httpx.MockTransport(turso_server.handler),
    )
    yield [sqlite_store, turso_store]
    sqlite_store.close()
    turso_store.close()


# --------------------------------------------------------------------------------------
# The parity sequence
# --------------------------------------------------------------------------------------

SESSION_SQL = (
    "INSERT INTO sessions (id, created_at, last_activity_at, employee_id, auth_mode, actor_role, "
    "client_label, eval_run_id, user_agent_hash, app_version, deploy_mode, mcp_transport, cold_start) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
)
SESSION_PARAMS = ("s1", 100, 100, "E1042", "cookie", "employee", "web", None, None, "abc123", "local", "http", 0)
TURN_SQL = "INSERT INTO turns (id, session_id, seq, started_at, user_message, process_uptime_ms) VALUES (?,?,?,?,?,?)"
SPAN_SQL = (
    "INSERT INTO spans (id, turn_id, session_id, seq, kind, name, started_at, ended_at, duration_ms, "
    "status, payload_json, payload_bytes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _run_sequence(store) -> list[Any]:
    """The same statements every backend must answer identically."""
    applied = migrate(store)
    re_applied = migrate(store)  # idempotent: a second call applies nothing
    store.execute(SESSION_SQL, SESSION_PARAMS)
    store.execute(TURN_SQL, ("t1", "s1", 1, 200, "How much PTO do I have?", 1500))
    batched = store.batch(
        [
            Statement(SPAN_SQL, (f"sp{i}", "t1", "s1", i, "retrieval", "hybrid_rrf", 300, 310, 10, "ok", "{}", 2))
            for i in (1, 2, 3)
        ]
        + [
            Statement(
                "UPDATE turns SET ended_at = ?, duration_ms = ?, outcome = ? WHERE id = ?",
                (400, 200, "answered", "t1"),
            )
        ]
    )
    selected = store.execute("SELECT id, seq, kind, duration_ms FROM spans WHERE turn_id = ? ORDER BY seq", ("t1",))
    aggregate = store.execute(
        "SELECT COUNT(*) AS n, SUM(duration_ms) AS total FROM spans WHERE session_id = ?", ("s1",)
    )
    joined = store.execute(
        "SELECT t.outcome, s.actor_role, t.duration_ms FROM turns t JOIN sessions s ON s.id = t.session_id"
    )
    typed = store.execute(
        "SELECT eval_run_id, cold_start, CAST(duration_ms AS REAL) / 2 AS half FROM sessions "
        "JOIN turns ON turns.session_id = sessions.id"
    )
    deleted = store.execute("DELETE FROM spans WHERE seq >= ?", (3,))
    remaining = store.execute("SELECT COUNT(*) AS n FROM spans")
    return [
        applied,
        re_applied,
        [row.dicts() for row in batched],
        selected,
        aggregate,
        joined,
        typed,
        deleted.rows_affected,
        remaining,
    ]


def test_both_backends_agree_on_the_same_sequence(stores):
    sqlite_result, turso_result = (_run_sequence(store) for store in stores)
    assert sqlite_result == turso_result


def test_the_sequence_actually_produced_data(stores):
    results = _run_sequence(stores[0])
    applied, re_applied, batched, selected, aggregate, *_ = results
    assert applied == ["001_initial"]
    assert re_applied == []
    assert [row["seq"] for row in selected.dicts()] == [1, 2, 3]
    assert aggregate.dicts() == [{"n": 3, "total": 30}]
    assert batched[-1] == []  # the UPDATE returns no rows
    assert results[-1].dicts() == [{"n": 2}]


def test_turso_store_speaks_the_pipeline_wire_shape(stores, turso_server):
    _run_sequence(stores[1])
    assert turso_server.auth_headers and set(turso_server.auth_headers) == {"Bearer test-token"}
    assert "batch" in turso_server.requests_seen
    assert turso_server.requests_seen[-1] == "close"


def test_a_failing_batch_leaves_nothing_behind(stores):
    for store in stores:
        migrate(store)
        store.execute(SESSION_SQL, SESSION_PARAMS)
        with pytest.raises(StoreError):
            store.batch(
                [
                    Statement(TURN_SQL, ("t1", "s1", 1, 200, "first", 10)),
                    Statement(TURN_SQL, ("t1", "s1", 2, 200, "duplicate id", 10)),
                ]
            )
        assert store.execute("SELECT COUNT(*) AS n FROM turns").dicts() == [{"n": 0}]


def test_a_failing_statement_raises_store_error(stores):
    for store in stores:
        migrate(store)
        with pytest.raises(StoreError):
            store.execute("SELECT * FROM no_such_table")


def test_backend_selection_follows_the_spec_table(tmp_path):
    from hrmosaic.settings import Settings

    def settings(**overrides):
        # `_env_file=None`: the selection rule is read from these values alone, never from a
        # developer's real `.env`.
        return Settings(_env_file=None, **{"turso_database_url": None, "turso_auth_token": None, **overrides})

    cases = [
        (settings(trace_db_path=tmp_path / "a.sqlite"), SqliteStore),
        (
            settings(
                trace_db_path=tmp_path / "b.sqlite",
                turso_database_url="libsql://db.turso.io",
                turso_auth_token="token",
            ),
            TursoHTTPStore,
        ),
        (
            settings(
                trace_db_path=tmp_path / "c.sqlite",
                turso_database_url="libsql://db.turso.io",
                turso_auth_token="token",
                persist_backend="sqlite",
            ),
            SqliteStore,
        ),
    ]
    for configured, expected in cases:
        store = build_store(configured)
        try:
            assert isinstance(store, expected)
        finally:
            store.close()


def test_a_libsql_url_becomes_an_https_pipeline_url():
    from hrmosaic.core.db import pipeline_url

    assert pipeline_url("libsql://mosaic-hr.turso.io") == "https://mosaic-hr.turso.io/v2/pipeline"
    assert pipeline_url("https://mosaic-hr.turso.io/") == "https://mosaic-hr.turso.io/v2/pipeline"
