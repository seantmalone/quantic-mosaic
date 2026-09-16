"""The `expense_claim` workflow (spec §9.3; W8 fix round, W7-review I2).

**Required slots** — employee profile · the claim amount · policy evidence on expense limits and
approval authority · a compliance verdict on that amount.

**`is_complete`** — a `lookup_employee_profile` result **in state**, **and** a compliance verdict,
**and** evidence for at least two citations.

It exists because a monetary approval question is decided by a **threshold**, and the threshold is
the engine's to apply: `eval:expenses-002:1` asked who approves a USD 3,000 trip and was answered
from the USD 2,500 manager row, because the amount never reached `check_policy_compliance` and
nothing made it part of the routing decision. `agent/router.py::normalise` routes a question that
carries a money amount and an approval or expense term here; the amount it extracts is seeded as a
resolved slot the compliance call inherits; and a turn that reaches synthesis without a verdict has
one scored for it (`orchestrator._score_deterministically`). The model still chooses the tools and
writes the answer — the workflow only guarantees the amount was scored before anything was said
about who approves it.
"""

from __future__ import annotations

from hrmosaic.agent.workflows import LoopState, WorkflowSpec

NAME = "expense_claim"

POLICY_DOCS = ("expenses-and-reimbursement", "manager-approval-matrix")

MIN_CITATIONS = 2

#: The compliance scenario this workflow scores — `corpus/rules.yml`'s `expense_claim`.
SCENARIO = "expense_claim"

#: What each required slot is **in workflow words**, for the act loop's reminder. Never a tool
#: name: the reminder reports the debt and lets the model choose how to settle it (§9.1 step 2).
SLOT_DESCRIPTIONS = {
    "lookup_employee_profile": "no employee record is in state yet",
    "check_policy_compliance": "no compliance verdict on the claim amount is in state yet",
}

EVIDENCE_DESCRIPTION = (
    f"the turn holds fewer than {MIN_CITATIONS} citable policy passages on expense limits and approval "
    "authority, and an answer may state policy only from passages it can cite"
)


def evidence_met(state: LoopState) -> bool:
    """The predicate's evidence clause, named."""
    return len(state.evidence_chunk_ids) >= MIN_CITATIONS


def is_complete(state: LoopState) -> bool:
    """The predicate of §9.3, clause by clause."""
    return state.has("lookup_employee_profile") and state.decided() and evidence_met(state)


SPEC = WorkflowSpec(
    name=NAME,
    required_slots=(
        "employee profile",
        "the claim amount",
        "policy evidence on expense limits and approval authority",
        "a compliance verdict on the amount",
    ),
    policy_docs=POLICY_DOCS,
    is_complete=is_complete,
    requires_tool_results=("lookup_employee_profile", "check_policy_compliance"),
    slot_descriptions=SLOT_DESCRIPTIONS,
    evidence_description=EVIDENCE_DESCRIPTION,
    evidence_met=evidence_met,
)

__all__ = [
    "EVIDENCE_DESCRIPTION",
    "MIN_CITATIONS",
    "NAME",
    "POLICY_DOCS",
    "SCENARIO",
    "SLOT_DESCRIPTIONS",
    "SPEC",
    "evidence_met",
    "is_complete",
]
