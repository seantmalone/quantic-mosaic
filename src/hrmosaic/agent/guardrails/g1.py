"""G1 `evidence_gate` — refuse, and redirect, rather than answer from parametric knowledge (§7.4).

The rule fires when the fused candidate set is too weak to ground an answer:

* `max_dense_score < MIN_EVIDENCE_SCORE` (0.32), **or**
* fewer than two candidates at or above `MIN_SUPPORT_SCORE` (0.26).

Every fused candidate carries a dense score by construction — §7.1's fill step scores the BM25-only
arrivals against the query vector using their stored embeddings — so the rule is **total**: there is
no "score unknown" branch, and `test_g1_evidence_gate.py` has a BM25-only case that proves it.

The refusal is built **deterministically**, with no model call and, crucially, **no `tools/call`**:
§13.4 scores `ToolPrecision = 1.0` when both the called and the expected tool sets are empty, so a
refusal that issued a `list_policy_documents` call to find out what the corpus covers would score
0.0 for exemplary behaviour. The redirect reads `core.corpusread.list_documents()` — the same
read-only index the tool would have read — and the cached tool catalog the turn already discovered.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from hrmosaic.agent.guardrails import emit
from hrmosaic.core import corpusread
from hrmosaic.core.models import AnswerBlock, AnswerSchema
from hrmosaic.settings import settings as default_settings

if TYPE_CHECKING:
    from hrmosaic.core.trace import TurnBuffer


class Scored(Protocol):
    """Any candidate carrying the one score of §7.1 — `dense_score = 1 − cosine_distance`."""

    dense_score: float


@dataclass(frozen=True)
class Verdict:
    """The pure decision. `passed` is what the loop branches on; the rest is what the span records."""

    passed: bool
    reason: str
    max_dense_score: float
    supporting: int
    candidates: int
    min_evidence_score: float
    min_support_score: float


#: How the redirect is worded when nothing was retrieved at all versus when it was all too weak.
NO_EVIDENCE = "no policy evidence was retrieved for this question"
WEAK_EVIDENCE = "the retrieved policy evidence is below the evidence threshold"
OUT_OF_SCOPE = "the question is not about Mosaic Robotics HR policy or your own HR data"


def evaluate(
    candidates: Sequence[Scored],
    *,
    min_evidence_score: float | None = None,
    min_support_score: float | None = None,
) -> Verdict:
    """The pure rule of §7.4 row G1. Touches no store and emits nothing."""
    min_evidence_score = default_settings.min_evidence_score if min_evidence_score is None else min_evidence_score
    min_support_score = default_settings.min_support_score if min_support_score is None else min_support_score
    scores = [float(candidate.dense_score) for candidate in candidates]
    top = max(scores) if scores else 0.0
    supporting = sum(1 for score in scores if score >= min_support_score)
    if not scores:
        reason = NO_EVIDENCE
    elif top < min_evidence_score:
        reason = f"{WEAK_EVIDENCE}: max dense score {top:.3f} < {min_evidence_score:.2f}"
    elif supporting < 2:
        reason = f"{WEAK_EVIDENCE}: {supporting} chunk(s) at or above {min_support_score:.2f}, 2 required"
    else:
        reason = f"max dense score {top:.3f}, {supporting} supporting chunk(s)"
    return Verdict(
        passed=bool(scores) and top >= min_evidence_score and supporting >= 2,
        reason=reason,
        max_dense_score=top,
        supporting=supporting,
        candidates=len(scores),
        min_evidence_score=min_evidence_score,
        min_support_score=min_support_score,
    )


def check(
    candidates: Sequence[Scored],
    *,
    turn: TurnBuffer | None = None,
    evidence_span_ids: Sequence[str] = (),
    min_evidence_score: float | None = None,
    min_support_score: float | None = None,
) -> Verdict:
    """Evaluate and emit the one `guardrail` span. The observed scores ride on the span (§9.5)."""
    verdict = evaluate(candidates, min_evidence_score=min_evidence_score, min_support_score=min_support_score)
    emit(
        turn,
        "G1",
        verdict="allow" if verdict.passed else "refuse",
        reason=verdict.reason,
        evidence_span_ids=list(evidence_span_ids),
        details={
            "max_dense_score": round(verdict.max_dense_score, 4),
            "supporting_chunks": verdict.supporting,
            "candidates": verdict.candidates,
            "min_evidence_score": verdict.min_evidence_score,
            "min_support_score": verdict.min_support_score,
        },
    )
    return verdict


def coverage() -> list[str]:
    """What the corpus covers, as `"Title"` strings, read from the real index — never a hard-coded list."""
    return [document.doc_title for document in corpusread.list_documents()]


def refusal(reason: str, *, tool_names: Sequence[str] = ()) -> AnswerSchema:
    """The refuse-and-redirect answer, built with no model call and no `tools/call`.

    It never states a policy — there is nothing to cite — so the redirect is a `recommendation`
    block, which the UI badges *"Recommendation — not company policy"*. The `next_steps` name the
    documents that do exist, which is the redirect §7.4 asks for.
    """
    titles = coverage()
    covered = "; ".join(titles)
    capability = f" I can also look up your own HR data with {len(tool_names)} tools." if tool_names else ""
    text = (
        f"I cannot answer that: {reason}. I answer only from the Mosaic Robotics policy corpus and "
        f"your own HR data, and I do not answer from general knowledge."
        f"{capability}"
    )
    return AnswerSchema(
        blocks=[AnswerBlock(type="recommendation", text=text, citations=[])],
        next_steps=[f"The corpus covers: {covered}."]
        + ["Ask about one of those policies, or contact People Operations at people-ops@mosaicrobotics.example."],
        rationale_summary=f"Refused and redirected: {reason}."[:200],
    )


__all__ = [
    "NO_EVIDENCE",
    "OUT_OF_SCOPE",
    "WEAK_EVIDENCE",
    "Scored",
    "Verdict",
    "check",
    "coverage",
    "evaluate",
    "refusal",
]
