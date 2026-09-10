"""The `pto_request` workflow (spec §9.3, demo task 2 of §18.2).

**Required slots** — employee profile · PTO balance · requested days · policy evidence on notice
and approval · a compliance verdict · (optional, gated) a created ticket.

**`is_complete`** — a `check_pto_balance` result **in state**, **and** a compliance verdict, **and**
either evidence for at least two citations **or** a confirmed `mock_writes` row.

The balance is required as a **tool result** for the same reason the profile is in
`remote_work_eligibility`: an answer that says "you have enough days" without having read the
balance is not a completed PTO workflow, whatever it says (§9.3, §13.9).

The ticket is the *optional* slot and it is deliberately last: §8.6 gates it behind a human
confirmation, so the turn is complete with a cited answer alone. The `or` in the final clause is
what lets the same predicate close both the answer-only turn and the resumed, confirmed one.
"""

from __future__ import annotations

from hrmosaic.agent.workflows import LoopState, WorkflowSpec

NAME = "pto_request"

POLICY_DOCS = ("pto-and-holidays", "manager-approval-matrix")

MIN_CITATIONS = 2


def is_complete(state: LoopState) -> bool:
    """The predicate of §9.3, clause by clause."""
    return (
        state.has("check_pto_balance")
        and state.decided()
        and (len(state.evidence_chunk_ids) >= MIN_CITATIONS or bool(state.mock_write_ids))
    )


SPEC = WorkflowSpec(
    name=NAME,
    required_slots=(
        "employee profile",
        "PTO balance",
        "requested days",
        "policy evidence on notice and approval",
        "a compliance verdict",
        "(optional, gated) a created ticket",
    ),
    policy_docs=POLICY_DOCS,
    is_complete=is_complete,
    requires_tool_results=("check_pto_balance", "check_policy_compliance"),
)

__all__ = ["MIN_CITATIONS", "NAME", "POLICY_DOCS", "SPEC", "is_complete"]
