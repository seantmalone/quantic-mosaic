"""The confirmation gate, enforced **inside** the MCP server (spec §8.6, §17 *Irreversible actions*).

The whole of R4.5, and deliberately small. A one-time token lives in `confirmations`; a mock write
lives in `mock_writes` and cannot exist without one (the column is `NOT NULL REFERENCES`). Three
functions:

* `mint()` — called only from `web/` after a human clicks Confirm or Cancel. It is here, not in
  `web/`, so that the canonical argument serialisation the gate compares against has exactly one
  implementation; `tests/architecture/test_conventions.py` does not police it, the constraint list
  does, and a second serialiser would be a silent way to let a mismatched replay through.
* `validate()` — token exists · `used_at IS NULL` · not expired · `user_response == "confirmed"` ·
  `tool_name` matches · the canonical arguments minus `confirmation_token` equal `arguments_json`.
* `consume()` — sets `used_at`, then appends the `mock_writes` row carrying that token. In that
  order, so the only interruption this can survive is a spent token with no write, never a write
  with no confirmation.

`mcpserver/**` is the only writer of `mock_writes` (constraints, §10.1). The rejection returned on
every failure is byte-identical whichever check failed and **carries no token of any kind** — the
server never hands the agent the credential that would let it retry (§8.3).

There is no HMAC, no `action_digest`, no `CONFIRM_SECRET` and no second table (§22).
"""

from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hrmosaic.core.db import Store, now_micros

#: §8.6 step 3. Ten minutes is long enough to read a confirm card and short enough that a token
#: found in a log is worthless.
TOKEN_TTL_S = 600

#: The argument every write tool accepts and no schema requires; never part of what is compared.
TOKEN_ARGUMENT = "confirmation_token"

#: `mock_writes.id` is allocated from the table's own rowid (§8.5). The insert computes it inside
#: SQL so two concurrent writes cannot read the same maximum; the lock keeps the read-back that
#: follows paired with its own insert.
_write_lock = threading.Lock()


class ConfirmationRejected(Exception):
    """Raised by `validate()` when any of the six checks fails. Carries no token."""


@dataclass(frozen=True)
class Confirmation:
    """One row of `confirmations` (§10.1), as the gate reads it back."""

    token: str
    session_id: str
    turn_id: str
    span_id: str
    tool_name: str
    arguments_json: str
    human_summary: str
    created_at: int
    expires_at: int
    used_at: int | None
    user_response: str


def canonical_arguments(arguments: Mapping[str, Any]) -> str:
    """The one canonical serialisation of a proposed argument set (§8.6 step 5).

    `confirmation_token` is excluded, keys are sorted and separators are tight, so the bytes minted
    at Confirm time and the bytes computed from the resumed call are comparable without either side
    knowing how the other built its dict.
    """
    body = {key: value for key, value in arguments.items() if key != TOKEN_ARGUMENT}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def rejection(action: str, human_summary: str, arguments_preview: Mapping[str, Any]) -> dict[str, Any]:
    """The §8.4 tool-8 rejection: exactly five keys, and **no token of any kind**."""
    return {
        "status": "confirmation_required",
        "code": "CONFIRMATION_REQUIRED",
        "action": action,
        "human_summary": human_summary,
        "arguments_preview": dict(arguments_preview),
    }


def mint(
    store: Store,
    *,
    session_id: str,
    turn_id: str,
    span_id: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    human_summary: str,
    user_response: str = "confirmed",
    ttl_s: int = TOKEN_TTL_S,
) -> str:
    """Insert one `confirmations` row and return its token — **called only from `web/`** (§8.6 step 3).

    `arguments` must be the exact proposed arguments read from the gated attempt's `tool_call` span
    payload, never `arguments_preview`, which is a display subset. A Cancel mints exactly the same
    row with `user_response="declined"`: `validate()` rejects it, and it is never returned to a
    client.
    """
    token = secrets.token_urlsafe(32)
    created_at = now_micros()
    store.execute(
        "INSERT INTO confirmations (token, session_id, turn_id, span_id, tool_name, arguments_json, "
        "human_summary, created_at, expires_at, used_at, user_response) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
        (
            token,
            session_id,
            turn_id,
            span_id,
            tool_name,
            canonical_arguments(arguments),
            human_summary,
            created_at,
            created_at + ttl_s * 1_000_000,
            user_response,
        ),
    )
    return token


def load(store: Store, token: str) -> Confirmation | None:
    row = store.execute(
        "SELECT token, session_id, turn_id, span_id, tool_name, arguments_json, human_summary, "
        "created_at, expires_at, used_at, user_response FROM confirmations WHERE token = ?",
        (token,),
    ).one()
    return Confirmation(**row) if row else None


def validate(store: Store, *, tool_name: str, arguments: Mapping[str, Any]) -> Confirmation:
    """The six checks of §8.6 step 5. Raises `ConfirmationRejected` on any failure.

    The failure reason is deliberately not reported back: every caller answers with the identical
    token-free `CONFIRMATION_REQUIRED` result, so a caller cannot probe the store by watching how
    the rejection changes.
    """
    token = arguments.get(TOKEN_ARGUMENT)
    if not isinstance(token, str) or not token:
        raise ConfirmationRejected("no confirmation_token supplied")
    confirmation = load(store, token)
    if confirmation is None:
        raise ConfirmationRejected("unknown token")
    if confirmation.used_at is not None:
        raise ConfirmationRejected("token already used")
    if confirmation.expires_at <= now_micros():
        raise ConfirmationRejected("token expired")
    if confirmation.user_response != "confirmed":
        raise ConfirmationRejected("not confirmed")
    if confirmation.tool_name != tool_name:
        raise ConfirmationRejected("tool name does not match")
    if confirmation.arguments_json != canonical_arguments(arguments):
        raise ConfirmationRejected("arguments do not match")
    return confirmation


def consume(
    store: Store,
    confirmation: Confirmation,
    *,
    kind: str,
    prefix: str,
    employee_id: str,
    payload: Mapping[str, Any],
) -> str:
    """Mark the token used and append the `mock_writes` row. Returns the allocated id.

    `mock_writes.id` is `"<prefix>" + f"{rowid:06d}"` (§8.5) — human-readable and stable within one
    database, not reproducible across databases, which matters to nobody because no literal id is
    documented anywhere. It is computed *inside* the INSERT, so the read of `MAX(rowid)` and the
    write that consumes it are one statement and two callers cannot be handed the same number.

    Single use is enforced by the `UPDATE`'s own `used_at IS NULL` predicate, not by the read in
    `validate()`: a second resume of the same token affects zero rows and is rejected here. The
    token is consumed *before* the row is appended, so the only failure this ordering can produce
    is a spent token with no write — never a write without a confirmation, which is the direction
    §17 cares about and which `mock_writes.confirmation_token NOT NULL REFERENCES` also enforces.
    """
    created_at = now_micros()
    with _write_lock:
        spent = store.execute(
            "UPDATE confirmations SET used_at = ? WHERE token = ? AND used_at IS NULL",
            (created_at, confirmation.token),
        )
        if spent.rows_affected != 1:
            raise ConfirmationRejected("token already used")
        store.execute(
            "INSERT INTO mock_writes (id, kind, created_at, session_id, turn_id, span_id, "
            "employee_id, payload_json, confirmation_token) "
            "SELECT ? || printf('%06d', COALESCE(MAX(rowid), 0) + 1), ?, ?, ?, ?, ?, ?, ?, ? "
            "FROM mock_writes",
            (
                prefix,
                kind,
                created_at,
                confirmation.session_id,
                confirmation.turn_id,
                confirmation.span_id,
                employee_id,
                json.dumps(dict(payload), ensure_ascii=False),
                confirmation.token,
            ),
        )
        allocated = store.execute(
            "SELECT id FROM mock_writes WHERE confirmation_token = ?", (confirmation.token,)
        ).scalar()
    return str(allocated)
