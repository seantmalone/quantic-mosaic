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

**A slot also carries the words for its own debt.** The act loop may remind a model that stopped
early (§9.1 step 2), and what it is allowed to say is `slot_descriptions` / `evidence_description`
— "no compliance verdict is in state yet" — never the name of the tool that would fill the slot.
A reminder that listed the remaining calls would author the rest of the tool sequence on every
nudged turn, and §13.4's ToolSelection would be scoring the hint rather than the model; a reminder
that told the model one search would do would simply be false here.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: The compliance verdict that means the engine could not decide — never a completed workflow.
INSUFFICIENT = "insufficient_evidence"

#: The only tool whose result carries scored, citable evidence — the one that runs §7.1's pipeline
#: and emits a `retrieval` span. Read **only** to decide whether an unfilled evidence slot is worth
#: reminding the model about under §13.9's `tools_disabled` ablation; never to word the reminder.
EVIDENCE_TOOLS: tuple[str, ...] = ("search_policy_documents",)


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

    def note_evidence(self, chunk_id: str | None, doc_id: str | None, *, quarantined: bool = False) -> None:
        """Record one retrieved chunk as evidence — unless G4 quarantined it (§7.4).

        A quarantined chunk cannot be cited: G2 strips any citation to one, the block that carried
        it is dropped and the answer can lose its last support. Counting it towards a completion
        predicate would let `is_complete` close a turn on evidence the answer is forbidden to use —
        the same class of defect as counting a merely *cited* chunk id, and the reason the gate and
        the predicate must read the word "evidence" the same way. The `retrieval` span still lists
        the hit with its flag; it just never becomes something the turn may lean on.
        """
        if quarantined:
            return
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


def _always_met(state: LoopState) -> bool:
    return True


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
    #: What each of those results **is**, in workflow words: the debt the slot leaves while it is
    #: empty. This is what the act loop's reminder is allowed to say, and it is deliberately not
    #: the tool's name — a reminder that named the remaining calls would dictate the rest of the
    #: turn, and §13.4's ToolSelection would then be measuring the hint rather than the model.
    slot_descriptions: Mapping[str, str] = field(default_factory=dict)
    #: The same, for the predicate's *evidence* clause — and it states what that clause actually
    #: requires, which is never "one search is enough": `remote_work_eligibility` wants three
    #: distinct documents and `pto_request` two citable passages.
    evidence_description: str = ""
    #: How to see the evidence clause in state. `is_complete` remains the authority; this is the
    #: same expression, named, so a reminder can tell the two halves of the predicate apart.
    evidence_met: Callable[[LoopState], bool] = _always_met

    def missing_tool_results(self, state: LoopState) -> list[str]:
        """Which required structured-data tools have produced nothing yet."""
        return [name for name in self.requires_tool_results if not state.has(name)]

    def debts(self, state: LoopState, *, permitted: Collection[str] | None = None) -> list[str]:
        """What this turn still owes the workflow, in workflow words — never a tool name.

        `permitted` is the act step's allowed-tool list (§9.2's gate plus §13.9's per-turn
        ablation filter). A debt no permitted tool can settle is dropped: telling a model to fill
        a slot whose only tool was disabled produces a call the gate then refuses, which is a
        `tool_not_offered` error span the ablation itself manufactured.
        """
        owed = [
            self.slot_descriptions.get(name, f"the {name.replace('_', ' ')} slot is still empty")
            for name in self.missing_tool_results(state)
            if permitted is None or name in permitted
        ]
        evidence_reachable = permitted is None or any(name in permitted for name in EVIDENCE_TOOLS)
        if self.evidence_description and evidence_reachable and not self.evidence_met(state):
            owed.append(self.evidence_description)
        return owed


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


__all__ = ["EVIDENCE_TOOLS", "INSUFFICIENT", "LoopState", "WorkflowSpec", "get", "names"]
