"""The router (spec §9.2, R4.1) — "is RAG alone enough?" as a discrete, logged decision.

One constrained-JSON `llm_call(purpose="route")` produces a `RouteDecision`, which becomes the
turn's first `plan` span. Everything downstream branches on it: the sensitive escalation, the
out-of-scope refusal, the clarification, the workflow, and — the part that is a **gate** rather than
a hint — which tools the model is offered at all.

**The gate.** For `intent == "policy_qa"` the catalog handed to the model is hard-restricted to
tools 1–4, the RAG tools; the people-data and write tools are not offered. That is chosen over a
soft bias because it is deterministic and testable:
`tests/e2e/test_rag_only_makes_no_people_calls.py` asserts **zero** non-RAG tool calls on a pure
policy question, and the orchestrator refuses a call to a tool that was not offered rather than
relying on the model to respect an omission it can still guess around.

**The recovery path.** A gate that is wrong costs the turn, so there is exactly one way back:
if the accumulated evidence fails G1 while `intent == "policy_qa"`, the orchestrator reopens the
**full** catalog for **one** additional step and records a `plan` span with `catalog_reopened: true`
(§9.2). Any tool reachable only after a reopen is listed in the dataset as `allowed_extra_tools`,
never `expected_tools`, so a reopen never inflates `ToolRecall`.

`RouteDecision` carries **no defaults**: it is emitted as constrained JSON, and a Pydantic field
with a default produces a schema strict mode rejects (§7.3). Optionality is a nullable union with
the field still required.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from hrmosaic.agent.client import RAG_TOOLS, DiscoveredCatalog
from hrmosaic.core.llm.base import ToolSchema

#: The four intents. They answer one question — *what does this turn need?* — and the out-of-scope,
#: sensitive and clarification cases are **flags** rather than intents, because a turn can be
#: out of scope *and* have been a policy question, and the confusion matrix of §13.4 scores the
#: outcome, not the intent.
Intent = Literal["policy_qa", "employee_data", "workflow", "action"]

#: The two declarative workflows of §9.3, plus "no workflow".
WorkflowName = Literal["remote_work_eligibility", "pto_request"]

#: §11's persona format, and the only shape an employee id may take.
EMPLOYEE_ID = re.compile(r"^E1[0-9]{3}$")

#: A `rationale_summary` is an operational line, never reasoning — `test_no_chain_of_thought.py`
#: asserts the ceiling, so the loop truncates rather than letting a chatty model fail the contract.
MAX_RATIONALE_CHARS = 200


class RouteDecision(BaseModel):
    """The router's constrained-JSON output (§9.1 step 1). Strict at every level: no defaults."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    workflow: WorkflowName | None
    needs_employee_data: bool
    needs_clarification: bool
    out_of_scope: bool
    sensitive: bool
    target_employee_id: str | None
    selected_tools: list[str]
    rationale_summary: str

    @property
    def rag_only(self) -> bool:
        """Whether the gate applies — the discrete, logged "RAG alone is sufficient" decision."""
        return self.intent == "policy_qa"

    def summary(self) -> str:
        """The one-line `plan` span summary §11.1's `trace[]` shows (R4.1's element)."""
        return (
            f"intent={self.intent} workflow={self.workflow or 'none'} "
            f"needs_employee_data={str(self.needs_employee_data).lower()}"
        )


def clamp_rationale(text: str) -> str:
    """One operational line, capped. Never a place for reasoning to hide (§9.7)."""
    single = " ".join(text.split())
    return single[:MAX_RATIONALE_CHARS]


def valid_employee_id(value: str | None) -> str | None:
    """`E1042`, or `None`. A malformed id is a clarification, never a lookup (§7.4 *Identity*)."""
    return value if value and EMPLOYEE_ID.match(value) else None


def find_employee_id(message: str) -> str | None:
    """The zero-LLM pre-check of §9.1 step 0: the employee id the user typed, if they typed one."""
    found = re.search(r"\bE1[0-9]{3}\b", message)
    return found.group(0) if found else None


def allowed_tools(
    decision: RouteDecision,
    catalog: DiscoveredCatalog,
    *,
    disabled: Iterable[str] = (),
    reopened: bool = False,
) -> list[str]:
    """The names this step may call — the gate, plus the per-turn `tools_disabled` ablation filter.

    `reopened` is the one-step recovery of §9.2: the full catalog, for one more act step.
    """
    names = list(catalog.names)
    if decision.rag_only and not reopened:
        names = [name for name in names if name in RAG_TOOLS]
    blocked = set(disabled)
    return [name for name in names if name not in blocked]


def offered(
    decision: RouteDecision,
    catalog: DiscoveredCatalog,
    *,
    disabled: Iterable[str] = (),
    reopened: bool = False,
) -> list[ToolSchema]:
    """The array handed to the model: the discovered catalog, gated and filtered (§8.2 step 4)."""
    return catalog.tool_schemas(allowed_tools(decision, catalog, disabled=disabled, reopened=reopened))


def fallback_decision(message: str, *, reason: str, out_of_scope: bool = False) -> RouteDecision:
    """The decision used when the router itself could not answer — a deterministic, safe default.

    Everything is offered and nothing is claimed: a router failure must degrade the turn, never
    silently narrow the catalog or invent an intent the confusion matrix would then score.
    """
    return RouteDecision(
        intent="policy_qa" if out_of_scope else "workflow",
        workflow=None,
        needs_employee_data=False,
        needs_clarification=False,
        out_of_scope=out_of_scope,
        sensitive=False,
        target_employee_id=find_employee_id(message),
        selected_tools=[],
        rationale_summary=clamp_rationale(reason),
    )


def normalise(decision: RouteDecision, *, catalog_names: Sequence[str], message: str) -> RouteDecision:
    """Clean a model-supplied decision: cap the rationale, drop invented ids and unknown tools."""
    return decision.model_copy(
        update={
            "rationale_summary": clamp_rationale(decision.rationale_summary),
            "target_employee_id": valid_employee_id(decision.target_employee_id) or find_employee_id(message),
            "selected_tools": [name for name in decision.selected_tools if name in set(catalog_names)],
        }
    )


__all__ = [
    "EMPLOYEE_ID",
    "MAX_RATIONALE_CHARS",
    "Intent",
    "RouteDecision",
    "WorkflowName",
    "allowed_tools",
    "clamp_rationale",
    "fallback_decision",
    "find_employee_id",
    "normalise",
    "offered",
    "valid_employee_id",
]
