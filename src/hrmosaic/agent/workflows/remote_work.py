"""The `remote_work_eligibility` workflow (spec §9.3, demo task 1 of §18.1).

**Required slots** — employee profile · `duration_days` · `destination_country` · policy evidence
from ≥ 3 of the four documents below · a compliance verdict.

**`is_complete`** — a `lookup_employee_profile` result **in state**, **and** a
`check_policy_compliance` result whose `verdict != insufficient_evidence`, **and** evidence
spanning ≥ 3 distinct `doc_id`s.

The employee profile is required as a **tool result**, not as a claim in the answer: an eligibility
verdict reached without ever reading the employee's work country and entity is not a complete
workflow, and requiring the result is what makes the `no_structured_tools` ablation move workflow
completion rather than only ToolSelection (§13.9).

Three distinct documents is the R3.5 multi-document floor, and it is also what demo task 1 shows on
camera: the duration threshold, the approved-country list and the device requirement do not all live
in one policy.
"""

from __future__ import annotations

from hrmosaic.agent.workflows import LoopState, WorkflowSpec

NAME = "remote_work_eligibility"

#: The four documents §9.3 names. Evidence must span at least three of them — never these three.
POLICY_DOCS = (
    "remote-and-hybrid-work",
    "tax-and-location-addendum",
    "security-acceptable-use",
    "manager-approval-matrix",
)

MIN_DISTINCT_DOCS = 3


def is_complete(state: LoopState) -> bool:
    """The predicate of §9.3, clause by clause."""
    return state.has("lookup_employee_profile") and state.decided() and len(state.evidence_doc_ids) >= MIN_DISTINCT_DOCS


SPEC = WorkflowSpec(
    name=NAME,
    required_slots=(
        "employee profile",
        "duration_days",
        "destination_country",
        f"policy evidence from at least {MIN_DISTINCT_DOCS} of {', '.join(POLICY_DOCS)}",
        "a compliance verdict",
    ),
    policy_docs=POLICY_DOCS,
    is_complete=is_complete,
    requires_tool_results=("lookup_employee_profile", "check_policy_compliance"),
)

__all__ = ["MIN_DISTINCT_DOCS", "NAME", "POLICY_DOCS", "SPEC", "is_complete"]
