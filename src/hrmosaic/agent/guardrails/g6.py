"""G6 `pii_secret_redaction` — the one that is already everywhere, given a name and a record (§7.4).

`core/redact.py` runs over **every** span payload inside `core/trace.py` before persistence, and
`tests/unit/test_g6_redact.py` (P1) is its test in both directions: leaked values are scrubbed and
the three integer token counts survive the denylist's `token` pattern. Nothing here re-implements
any of that.

What this module adds is the **audit record**. The other five guardrails leave a `guardrail` span
per turn saying they looked; G6 without one would be the only rule whose operation is invisible on
the dashboard's safety page, and "the redaction ran" would be an inference from the absence of a
leak rather than a record. So the loop calls `check()` once, over the answer it is about to persist,
and the span says whether anything was scrubbed.

Redaction is idempotent — `redact()` over already-redacted text is a no-op — so the second pass
`core/trace.py` performs on the closing UPDATE changes nothing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from hrmosaic.agent.guardrails import emit
from hrmosaic.core.redact import redact

if TYPE_CHECKING:
    from hrmosaic.core.trace import TurnBuffer


def scrub(value: Any) -> tuple[Any, bool]:
    """The pure call: `(redacted, changed)`. `changed` is what the span reports."""
    scrubbed = redact(value)
    return scrubbed, json.dumps(scrubbed, sort_keys=True, default=str) != json.dumps(value, sort_keys=True, default=str)


def check(value: Any, *, turn: TurnBuffer | None = None, subject: str = "answer") -> Any:
    """Redact `value`, emit the one `guardrail` span, and return the redacted value."""
    scrubbed, changed = scrub(value)
    emit(
        turn,
        "G6",
        verdict="strip" if changed else "allow",
        reason=f"{subject} scrubbed" if changed else f"{subject} carried nothing to redact",
        details={"subject": subject, "changed": changed},
    )
    return scrubbed


__all__ = ["check", "scrub"]
