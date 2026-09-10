"""Size control for the trace store — the cascading sweep of spec §10.5.

Runs at boot and every six hours (the schedule belongs to `web/`; this module is the sweep).
It keeps the newest `TRACE_RETENTION_SESSIONS` sessions and **never prunes**:

* a session with a non-null `eval_run_id`;
* a session whose `client_label` is `eval_judge` or `maintenance`;
* a session that owns a `mock_writes` row — a ticket created live on camera stays resolvable;

and it never deletes a `confirmations` row that a `mock_writes` row references, because
`mock_writes.confirmation_token` is `NOT NULL REFERENCES confirmations(token)`: no mock write
may ever be left without the human decision that authorised it.

The cascade runs children-first — `llm_messages` → `spans` → `confirmations` → `turns` →
`sessions` — so no delete can strand a foreign key.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from hrmosaic.core.db import Statement, Store, get_store
from hrmosaic.settings import settings as default_settings

logger = logging.getLogger(__name__)

PRUNABLE_SESSIONS = """
SELECT id FROM sessions
WHERE eval_run_id IS NULL
  AND client_label NOT IN ('eval_judge', 'maintenance')
  AND id NOT IN (SELECT session_id FROM mock_writes WHERE session_id IS NOT NULL)
  AND id NOT IN (SELECT id FROM sessions ORDER BY created_at DESC LIMIT ?)
ORDER BY created_at
"""


@dataclass(frozen=True)
class RetentionReport:
    """What one sweep removed."""

    sessions_deleted: int = 0
    turns_deleted: int = 0
    spans_deleted: int = 0
    llm_messages_deleted: int = 0
    confirmations_deleted: int = 0


def sweep(*, store: Store | None = None, keep: int | None = None) -> RetentionReport:
    """Prune everything outside the retention window that is not protected."""
    store = store or get_store()
    keep = keep if keep is not None else default_settings.trace_retention_sessions

    doomed = [row["id"] for row in store.execute(PRUNABLE_SESSIONS, (keep,))]
    if not doomed:
        return RetentionReport()

    placeholders = ",".join("?" for _ in doomed)
    session_filter = f"session_id IN ({placeholders})"
    results = store.batch(
        [
            Statement(
                f"DELETE FROM llm_messages WHERE span_id IN (SELECT id FROM spans WHERE {session_filter})",
                doomed,
            ),
            Statement(f"DELETE FROM spans WHERE {session_filter}", doomed),
            Statement(
                f"DELETE FROM confirmations WHERE {session_filter} "
                "AND token NOT IN (SELECT confirmation_token FROM mock_writes)",
                doomed,
            ),
            Statement(f"DELETE FROM turns WHERE {session_filter}", doomed),
            Statement(f"DELETE FROM sessions WHERE id IN ({placeholders})", doomed),
        ]
    )
    report = RetentionReport(
        llm_messages_deleted=results[0].rows_affected,
        spans_deleted=results[1].rows_affected,
        confirmations_deleted=results[2].rows_affected,
        turns_deleted=results[3].rows_affected,
        sessions_deleted=results[4].rows_affected,
    )
    logger.info("retention sweep kept the newest %d sessions and removed %s", keep, report)
    return report
