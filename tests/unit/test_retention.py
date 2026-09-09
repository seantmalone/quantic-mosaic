"""`core/retention.py` — the cascading sweep of §10.5.

Keeps the newest `TRACE_RETENTION_SESSIONS` sessions and never prunes a session that is
eval-linked, `eval_judge`, `maintenance`, **or owns a `mock_writes` row** — so a ticket created
live on camera is still resolvable days later — and never deletes a `confirmations` row a
`mock_writes` row references.
"""

from __future__ import annotations

from hrmosaic.core import retention
from hrmosaic.core.db import Statement, now_micros
from hrmosaic.core.models import LlmCallPayload, MessagesRef
from hrmosaic.core.trace import SessionSpec

CONFIRMATION_INSERT = (
    "INSERT INTO confirmations (token, session_id, turn_id, span_id, tool_name, arguments_json, "
    "human_summary, created_at, expires_at, user_response) VALUES (?,?,?,?,?,?,?,?,?,?)"
)
MOCK_WRITE_INSERT = (
    "INSERT INTO mock_writes (id, kind, created_at, session_id, turn_id, span_id, employee_id, "
    "payload_json, confirmation_token) VALUES (?,?,?,?,?,?,?,?,?)"
)


def _one_turn_session(writer, store, *, label="web", eval_run_id=None, age_s=0):
    """A session with one turn, one `llm_call` span and one `llm_messages` row."""
    session = SessionSpec(employee_id="E1042", client_label=label, eval_run_id=eval_run_id)
    turn = writer.start_turn(session, user_message="How much PTO do I have?")
    with turn.span("llm_call", "anthropic:claude-haiku-4-5") as span:
        span.set_payload(
            LlmCallPayload(
                provider="anthropic",
                model="claude-haiku-4-5",
                purpose="synthesize",
                messages_ref=MessagesRef(span_id=span.id, n_messages=1, total_chars=20),
            )
        )
        span.add_message("user", "How much PTO do I have?")
        span_id = span.id
    turn.close(outcome="answered")
    if age_s:
        store.execute("UPDATE sessions SET created_at = ? WHERE id = ?", (now_micros() - age_s * 1_000_000, session.id))
    return session.id, turn.turn_id, span_id


def _confirmed_write(store, session_id, turn_id, span_id):
    """The `confirmations` + `mock_writes` pair a confirmed write leaves behind (§8.6)."""
    store.batch(
        [
            Statement(
                CONFIRMATION_INSERT,
                (
                    "tok_abc",
                    session_id,
                    turn_id,
                    span_id,
                    "create_hr_case",
                    "{}",
                    "Open an HR case",
                    now_micros(),
                    now_micros() + 600_000_000,
                    "confirmed",
                ),
            ),
            Statement(
                MOCK_WRITE_INSERT,
                ("MOCK-HR-000123", "hr_ticket", now_micros(), session_id, turn_id, span_id, "E1042", "{}", "tok_abc"),
            ),
        ]
    )


def test_the_newest_sessions_are_kept_and_the_rest_are_pruned(writer, store):
    ids = [_one_turn_session(writer, store, age_s=100 - index)[0] for index in range(5)]

    report = retention.sweep(store=store, keep=2)

    assert report.sessions_deleted == 3
    surviving = {row["id"] for row in store.execute("SELECT id FROM sessions")}
    assert surviving == set(ids[-2:])


def test_no_orphaned_llm_messages_survive_a_sweep(writer, store):
    for index in range(4):
        _one_turn_session(writer, store, age_s=100 - index)

    retention.sweep(store=store, keep=1)

    orphans = store.execute(
        "SELECT COUNT(*) AS n FROM llm_messages WHERE span_id NOT IN (SELECT id FROM spans)"
    ).scalar()
    assert orphans == 0
    assert store.execute("SELECT COUNT(*) AS n FROM llm_messages").scalar() == 1
    assert store.execute("SELECT COUNT(*) AS n FROM spans").scalar() == 1
    assert store.execute("SELECT COUNT(*) AS n FROM turns").scalar() == 1


def test_eval_linked_and_server_label_sessions_are_never_pruned(writer, store):
    evaluated, *_ = _one_turn_session(writer, store, eval_run_id="r_9f2c1b7e", age_s=900)
    judged, *_ = _one_turn_session(writer, store, label="eval_judge", age_s=800)
    maintenance, *_ = _one_turn_session(writer, store, label="maintenance", age_s=700)
    ordinary, *_ = _one_turn_session(writer, store, age_s=600)
    newest, *_ = _one_turn_session(writer, store, age_s=0)

    report = retention.sweep(store=store, keep=1)

    assert report.sessions_deleted == 1
    surviving = {row["id"] for row in store.execute("SELECT id FROM sessions")}
    assert surviving == {evaluated, judged, maintenance, newest}
    assert ordinary not in surviving


def test_a_session_owning_a_mock_write_survives_with_its_confirmation(writer, store):
    session_id, turn_id, span_id = _one_turn_session(writer, store, age_s=900)
    _confirmed_write(store, session_id, turn_id, span_id)
    _one_turn_session(writer, store, age_s=0)

    report = retention.sweep(store=store, keep=1)

    assert report.sessions_deleted == 0
    assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 1
    assert store.execute("SELECT COUNT(*) AS n FROM confirmations").scalar() == 1
    assert store.execute("SELECT COUNT(*) AS n FROM spans WHERE session_id = ?", (session_id,)).scalar() == 1


def test_a_pruned_session_takes_its_confirmations_with_it(writer, store):
    doomed_session, doomed_turn, doomed_span = _one_turn_session(writer, store, age_s=900)
    store.execute(
        CONFIRMATION_INSERT,
        (
            "tok_declined",
            doomed_session,
            doomed_turn,
            doomed_span,
            "create_hr_case",
            "{}",
            "Open an HR case",
            now_micros(),
            now_micros() + 600_000_000,
            "declined",
        ),
    )
    _one_turn_session(writer, store, age_s=0)

    report = retention.sweep(store=store, keep=1)

    assert (report.sessions_deleted, report.confirmations_deleted) == (1, 1)
    assert store.execute("SELECT COUNT(*) AS n FROM confirmations").scalar() == 0


def test_a_sweep_with_nothing_to_do_is_a_no_op(writer, store):
    _one_turn_session(writer, store)

    report = retention.sweep(store=store, keep=300)

    assert report == retention.RetentionReport()
    assert store.execute("SELECT COUNT(*) AS n FROM sessions").scalar() == 1


def test_the_default_keep_comes_from_settings(writer, store):
    from hrmosaic.settings import settings

    assert settings.trace_retention_sessions == 300
    _one_turn_session(writer, store)
    assert retention.sweep(store=store).sessions_deleted == 0
