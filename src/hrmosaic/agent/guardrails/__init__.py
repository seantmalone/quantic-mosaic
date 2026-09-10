"""The six guardrails of spec §7.4 — one module each, every one a pure function plus a span.

| id | module | rule | verdict |
|---|---|---|---|
| G1 | `g1.py` | `evidence_gate` | `refuse` / `allow` |
| G2 | `g2.py` | `citation_resolvability` | `repair` / `allow` |
| G3 | `g3.py` | `fact_vs_recommendation` | `repair` / `allow` |
| G4 | `g4.py` | `injection_shield` | `warn` / `allow` |
| G5 | `g5.py` | `sensitive_escalation` | `escalate` / `allow` |
| G6 | `g6.py` | `pii_secret_redaction` | `strip` / `allow` |

Each module exposes a **pure** decision function that computes a verdict from its inputs and
touches nothing, and a `check(...)` wrapper that emits the `guardrail` span for it. The split is
what lets the unit tests assert the rule without a store and the loop assert the record with one.

Every span goes through `core/trace.py` — the sole writer (§16.3). Nothing here writes a row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hrmosaic.core.models import GuardrailPayload

if TYPE_CHECKING:
    from hrmosaic.core.trace import TurnBuffer

#: `rule_id` → `rule_name`, and the only place the pairing is written down. The span name is the
#: `G<n>_<rule_name>` form §11.1's `trace[]` example shows.
RULE_NAMES: dict[str, str] = {
    "G1": "evidence_gate",
    "G2": "citation_resolvability",
    "G3": "fact_vs_recommendation",
    "G4": "injection_shield",
    "G5": "sensitive_escalation",
    "G6": "pii_secret_redaction",
}


def span_name(rule_id: str) -> str:
    """`G2_citation_resolvability` — what the `trace[]` projection and the dashboard show."""
    return f"{rule_id}_{RULE_NAMES[rule_id]}"


def emit(
    turn: TurnBuffer | None,
    rule_id: str,
    *,
    verdict: str,
    reason: str = "",
    evidence_span_ids: list[str] | None = None,
    matched_pattern: str | None = None,
    details: dict | None = None,
    parent_span_id: str | None = None,
) -> str | None:
    """Write the one `guardrail` span for a rule. Returns its id, or `None` with no turn.

    With no turn — a unit test asserting the rule itself — nothing is written and the decision
    function's return value is the whole answer.
    """
    if turn is None:
        return None
    payload = GuardrailPayload(
        rule_id=rule_id,  # type: ignore[arg-type]
        rule_name=RULE_NAMES[rule_id],
        verdict=verdict,  # type: ignore[arg-type]
        reason=reason,
        evidence_span_ids=list(evidence_span_ids or []),
        matched_pattern=matched_pattern,
        details=dict(details or {}),
    )
    return turn.add_span("guardrail", span_name(rule_id), payload, parent_span_id=parent_span_id)


__all__ = ["RULE_NAMES", "emit", "span_name"]
