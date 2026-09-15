"""G3 `fact_vs_recommendation` — the distinction the answer schema already enforces, checked twice.

§7.3 makes it **structural**: `AnswerBlock` carries a validator that rejects a `policy_fact` with an
empty `citations` list, so a model that emits one cannot produce a valid `AnswerSchema` at all. G3
is the post-check behind that, and it exists because the structural guard fires at the wrong moment:
a `ValidationError` would lose the whole answer, when the honest repair is to relabel one block.

So the loop parses the model's JSON into **raw blocks**, runs G2 (which can strip a citation) and
then G3 (which relabels what is left uncited), and only then validates the repaired result into
`AnswerSchema`. An uncited claim becomes a `recommendation`, which the UI badges *"Recommendation —
not company policy"* (§7.3), rather than a policy statement nobody can check.

`record` (UX W7, JX2-05) is treated exactly as `performed` is: a statement of what is so — the
reader's own balance, tenure or notice arithmetic, read off a tool result — that is never a policy
claim and needs no citation, so this rule never touches it. `agent/outcome.py` is what types one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hrmosaic.agent.guardrails import emit

if TYPE_CHECKING:
    from hrmosaic.core.trace import TurnBuffer


@dataclass
class Outcome:
    """The relabelled blocks and which ones moved."""

    blocks: list[dict[str, Any]]
    relabelled: list[int] = field(default_factory=list)

    @property
    def repaired(self) -> bool:
        return bool(self.relabelled)


def apply(blocks: Sequence[Mapping[str, Any]]) -> Outcome:
    """The pure rule: an uncited `policy_fact` becomes a `recommendation`. Mutates nothing.

    Every other type — `recommendation`, `escalation`, `performed`, `record` — passes through as
    it came: none of them is a policy claim, so none of them owes a citation.
    """
    relabelled: list[int] = []
    repaired: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        body = dict(block)
        if body.get("type") == "policy_fact" and not (body.get("citations") or []):
            body["type"] = "recommendation"
            relabelled.append(index)
        repaired.append(body)
    return Outcome(blocks=repaired, relabelled=relabelled)


def check(blocks: Sequence[Mapping[str, Any]], *, turn: TurnBuffer | None = None) -> Outcome:
    """Relabel and emit the one `guardrail` span."""
    outcome = apply(blocks)
    # The noun agrees with the count: this reason is read on the session waterfall, where
    # `7 block(s)` was the same lazy plural page 3 printed everywhere else (UX W4, **P9**).
    relabelled = "block" if len(outcome.relabelled) == 1 else "blocks"
    counted = "block" if len(outcome.blocks) == 1 else "blocks"
    emit(
        turn,
        "G3",
        verdict="repair" if outcome.repaired else "allow",
        reason=(
            f"{len(outcome.relabelled)} uncited policy_fact {relabelled} relabelled as recommendation"
            if outcome.repaired
            else f"{len(outcome.blocks)} {counted}, every policy_fact cited"
        ),
        details={"blocks": len(outcome.blocks), "relabelled_indexes": outcome.relabelled},
    )
    return outcome


__all__ = ["Outcome", "apply", "check"]
