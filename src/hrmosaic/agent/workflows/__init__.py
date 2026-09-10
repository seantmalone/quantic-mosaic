"""The two declarative workflows of spec §9.3 (R4.2), and the state they are evaluated against.

**The LLM chooses tools; the workflow spec decides when the turn is complete.** That split is the
whole design: a completion predicate written in Python cannot be talked out of its requirements by
a confident answer, and it is what makes `workflow_completion` a measurable number (§13.4) rather
than a judge's opinion.

**The structured-data slot is required, not merely listed.** An eligibility verdict reached without
ever reading the employee's work country is not a complete workflow — and requiring the tool result
is what makes the `no_structured_tools` ablation move workflow completion rather than only
ToolSelection (§13.9). Both predicates below therefore start with "a result from *this* tool is in
state", never with "the answer says so".
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

#: The compliance verdict that means the engine could not decide — never a completed workflow.
INSUFFICIENT = "insufficient_evidence"


@dataclass
class LoopState:
    """What the act loop has accumulated so far — the only input a completion predicate reads."""

    #: Successful tool results, newest last, keyed by tool name.
    results: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: Every chunk id the turn has seen as evidence, in first-seen order.
    evidence_chunk_ids: list[str] = field(default_factory=list)
    #: The documents those chunks came from — what "citations spanning ≥ 3 distinct doc_ids" counts.
    evidence_doc_ids: list[str] = field(default_factory=list)
    #: `mock_writes` ids returned by a confirmed write tool.
    mock_write_ids: list[str] = field(default_factory=list)

    def record(self, tool_name: str, body: dict[str, Any]) -> None:
        self.results.setdefault(tool_name, []).append(body)

    def latest(self, tool_name: str) -> dict[str, Any] | None:
        results = self.results.get(tool_name)
        return results[-1] if results else None

    def has(self, tool_name: str) -> bool:
        """A **successful** result from that tool is in state (§9.3's "in state")."""
        return bool(self.results.get(tool_name))

    def note_evidence(self, chunk_id: str | None, doc_id: str | None) -> None:
        if chunk_id and chunk_id not in self.evidence_chunk_ids:
            self.evidence_chunk_ids.append(chunk_id)
        if doc_id and doc_id not in self.evidence_doc_ids:
            self.evidence_doc_ids.append(doc_id)

    def compliance_verdict(self) -> str | None:
        """The verdict of the most recent `check_policy_compliance`, or `None` if it never ran."""
        body = self.latest("check_policy_compliance")
        return None if body is None else body.get("verdict")

    def decided(self) -> bool:
        """A compliance verdict exists and is not `insufficient_evidence`."""
        verdict = self.compliance_verdict()
        return verdict is not None and verdict != INSUFFICIENT


@dataclass(frozen=True)
class WorkflowSpec:
    """One workflow: the slots it needs and the predicate that closes it."""

    name: str
    #: Human-readable required slots (§9.3's table), used for the clarification message and shown
    #: on the dashboard. They document the predicate; the predicate is what decides.
    required_slots: tuple[str, ...]
    #: The documents the workflow's evidence is expected to span, for the same reason.
    policy_docs: tuple[str, ...]
    is_complete: Callable[[LoopState], bool]
    #: The structured-data tools whose results the predicate requires (§9.3, §13.9).
    requires_tool_results: tuple[str, ...] = ()

    def missing_tool_results(self, state: LoopState) -> list[str]:
        """Which required structured-data tools have produced nothing yet."""
        return [name for name in self.requires_tool_results if not state.has(name)]


def get(name: str | None) -> WorkflowSpec | None:
    """The spec for a router-chosen workflow name, or `None` when the turn has no workflow."""
    from hrmosaic.agent.workflows import pto_request, remote_work

    registry: dict[str, WorkflowSpec] = {
        remote_work.SPEC.name: remote_work.SPEC,
        pto_request.SPEC.name: pto_request.SPEC,
    }
    return registry.get(name or "")


def names() -> Sequence[str]:
    from hrmosaic.agent.workflows import pto_request, remote_work

    return (remote_work.SPEC.name, pto_request.SPEC.name)


__all__ = ["INSUFFICIENT", "LoopState", "WorkflowSpec", "get", "names"]
