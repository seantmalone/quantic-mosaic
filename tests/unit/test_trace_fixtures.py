"""The golden traces under `tests/fixtures/traces/` are real records, not decoration.

`tests/fixtures/traces/` is the single home for golden traces (§16.5): the dashboard render
tests (P9), `test_action_safety.py` (P8) and the deterministic eval scorers (P10) all read from
here. This test is the contract those phases rely on — each fixture loads into the real §10.1
schema, and every span payload parses as its member of the §10.2 union.

Fixture shape: `{session, turn, spans[], llm_messages[], confirmations[], mock_writes[]}`, one
JSON object per table row, with `payload_json` / `answer_blocks_json` / `citations_json` written
as objects for readability and serialised on load.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hrmosaic.core.db import Statement
from hrmosaic.core.models import parse_payload

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "traces"
FIXTURES = sorted(FIXTURE_DIR.glob("*.json"))

JSON_COLUMNS = {"payload_json", "answer_blocks_json", "citations_json"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _columns(store, table: str) -> set[str]:
    return {row["name"] for row in store.execute(f"PRAGMA table_info({table})")}


def _statement(table: str, row: dict) -> Statement:
    columns = list(row)
    values = [
        json.dumps(row[column], ensure_ascii=False) if column in JSON_COLUMNS else row[column] for column in columns
    ]
    placeholders = ",".join("?" for _ in columns)
    return Statement(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", values)


def _insert_fixture(store, fixture: dict) -> None:
    """Load one golden trace into a migrated store, foreign keys and CHECKs enforced."""
    statements = [_statement("sessions", fixture["session"]), _statement("turns", fixture["turn"])]
    for span in fixture["spans"]:
        row = {**span, "turn_id": fixture["turn"]["id"], "session_id": fixture["session"]["id"]}
        statements.append(_statement("spans", row))
    statements += [_statement("llm_messages", message) for message in fixture["llm_messages"]]
    statements += [_statement("confirmations", row) for row in fixture["confirmations"]]
    statements += [_statement("mock_writes", row) for row in fixture["mock_writes"]]
    store.batch(statements)


def test_there_are_at_least_two_golden_traces():
    assert len(FIXTURES) >= 2


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_a_golden_trace_loads_into_the_real_schema(store, path):
    fixture = _load(path)
    for table, rows in (
        ("sessions", [fixture["session"]]),
        ("turns", [fixture["turn"]]),
        ("spans", fixture["spans"]),
        ("llm_messages", fixture["llm_messages"]),
        ("confirmations", fixture["confirmations"]),
        ("mock_writes", fixture["mock_writes"]),
    ):
        available = _columns(store, table)
        for row in rows:
            unknown = set(row) - available
            assert not unknown, f"{path.name}: {table} has unknown columns {sorted(unknown)}"

    _insert_fixture(store, fixture)

    assert store.execute("SELECT COUNT(*) AS n FROM spans").scalar() == len(fixture["spans"])
    assert store.execute("SELECT COUNT(*) AS n FROM turns").scalar() == 1


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_every_span_payload_parses_as_its_member_of_the_union(path):
    fixture = _load(path)
    seqs = [span["seq"] for span in fixture["spans"]]
    assert seqs == list(range(1, len(seqs) + 1))

    for span in fixture["spans"]:
        payload = parse_payload(span["payload_json"])
        assert payload.kind == span["kind"], f"{path.name}: span {span['seq']} kind mismatch"
        assert span["status"] in {"ok", "error"}
        assert span["duration_ms"] == (span["ended_at"] - span["started_at"]) // 1000


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_every_llm_call_has_its_verbatim_messages(path):
    fixture = _load(path)
    messages = fixture["llm_messages"]
    for span in fixture["spans"]:
        if span["kind"] != "llm_call":
            continue
        rows = [message for message in messages if message["span_id"] == span["id"]]
        assert rows, f"{path.name}: llm_call span {span['id']} has no llm_messages rows"
        assert [row["seq"] for row in rows] == list(range(1, len(rows) + 1))
        assert all(row["content"].strip() for row in rows)
        assert len(rows) == span["payload_json"]["messages_ref"]["n_messages"]
    assert {message["span_id"] for message in messages} <= {
        span["id"] for span in fixture["spans"] if span["kind"] == "llm_call"
    }


def test_one_fixture_carries_a_complete_confirmed_write_chain(store):
    """`confirmation` span + `confirmations` row + `mock_writes` row, all three joined up (§16.5)."""
    chains = [_load(path) for path in FIXTURES if _load(path)["mock_writes"]]
    assert len(chains) >= 1
    fixture = chains[0]
    _insert_fixture(store, fixture)

    confirmation_span = next(span for span in fixture["spans"] if span["kind"] == "confirmation")
    row = store.execute(
        "SELECT w.id AS write_id, c.user_response, c.tool_name "
        "FROM mock_writes w JOIN confirmations c ON c.token = w.confirmation_token"
    ).one()
    assert row["user_response"] == "confirmed"
    assert row["tool_name"] == confirmation_span["payload_json"]["action"]
    assert confirmation_span["payload_json"]["user_response"] == "confirmed"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_no_confirmation_token_ever_appears_in_a_payload(path):
    """§10.2: the `confirmation` payload is never the token, and a persisted token is redacted."""
    fixture = _load(path)
    tokens = {row["token"] for row in fixture["confirmations"]}
    serialised = json.dumps(fixture["spans"], ensure_ascii=False)
    for token in tokens:
        assert token not in serialised
    for span in fixture["spans"]:
        if span["kind"] == "tool_call":
            supplied = span["payload_json"]["arguments"].get("confirmation_token")
            assert supplied in (None, "[REDACTED]")
