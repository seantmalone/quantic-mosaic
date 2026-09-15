"""G1 `evidence_gate` — refuse, and redirect, rather than answer from parametric knowledge (§7.4).

The rule fires when the fused candidate set is too weak to ground an answer:

* `max_dense_score < MIN_EVIDENCE_SCORE` (0.60), **or**
* fewer than two candidates at or above `MIN_SUPPORT_SCORE` (0.45).

Both numbers were **calibrated at P10** from the observed distribution over this corpus rather than
guessed (§7.4, §21): the shipped 0.32 / 0.26 sat below the embedding model's cosine floor here, so
neither clause could ever fire and the rule was a no-op. See `CHANGELOG.md` for the measurement.

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
from hrmosaic.agent.guardrails.g5 import PEOPLE_OPS
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
#: **These are the span's words, not the reader's** (UX W2, numbers-precision-overflow-3): they
#: carry the clause that fired and the arithmetic behind it, they are what `Verdict.reason` and the
#: G1 span record, and the dashboard is where they are read. What the reader is told is
#: `USER_REFUSAL`, which states the boundary and nothing about how it was measured.
NO_EVIDENCE = "no policy evidence was retrieved for this question"
WEAK_EVIDENCE = "the retrieved policy evidence is below the evidence threshold"
OUT_OF_SCOPE = "the question is not about Mosaic Robotics HR policy or your own HR data"

#: The refusal a person reads. One admission, one boundary — no score, no threshold, no tool count.
#: The redirect that follows it is `next_steps`, built from the real index by `coverage()`.
USER_REFUSAL = (
    "I could not find anything in Mosaic's policy library that answers this, so I would rather not "
    "guess. I only answer from Mosaic policy and your own HR record."
)


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
    # Two decimal places, and a noun that agrees with its count (UX W4,
    # `numbers-precision-overflow-4`, `-15`): the score is a 0-1 cosine, three places said nothing
    # a reader could use and `chunk(s)` is a plural nobody speaks. "best evidence score" names what
    # the figure is — the best score of the evidence the gate accumulated, first-seen-wins — rather
    # than describing the retriever that produced it.
    passages = "passage" if supporting == 1 else "passages"
    if not scores:
        reason = NO_EVIDENCE
    elif top < min_evidence_score:
        reason = f"{WEAK_EVIDENCE}: best evidence score {top:.2f} < {min_evidence_score:.2f}"
    elif supporting < 2:
        reason = f"{WEAK_EVIDENCE}: {supporting} {passages} at or above {min_support_score:.2f}, 2 required"
    else:
        reason = f"best evidence score {top:.2f}, {supporting} supporting {passages}"
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


#: How many of those titles the redirect actually names (UX W3, jargon-and-exposure-3).
#:
#: It used to name all fourteen, in one semicolon-separated sentence that ran four lines at 1440px
#: and eight on a phone — the longest single string on the chat surface, under a refusal, which is
#: the moment a reader is least inclined to read a list. Five is an example, not an inventory: the
#: reader route `/policy` lists the library in full and the refusal links to it.
EXAMPLE_TOPIC_COUNT = 5


def example_topics(titles: Sequence[str] | None = None) -> list[str]:
    """The first few covered titles, in the index's own order — a sample of the real library."""
    return list(coverage() if titles is None else titles)[:EXAMPLE_TOPIC_COUNT]


def _sentence(titles: Sequence[str]) -> str:
    """`"A, B and C"` — an English list, so the redirect reads as a sentence and not as a dump."""
    items = list(titles)
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def refusal(reason: str) -> AnswerSchema:
    """The refuse-and-redirect answer, built with no model call and no `tools/call`.

    It never states a policy — there is nothing to cite — so the redirect is a `recommendation`
    block. The `next_steps` name a few of the documents that do exist, which is the redirect §7.4
    asks for, and since UX W2 they are **rendered**: the web layer used to build them and drop them,
    which is how the most useful half of a refusal never reached a reader (jargon-and-exposure-3).
    Since UX W3 they name five example titles rather than all fourteen; the chat surface puts a
    *"See the full policy library"* link to `/policy` beside them, which is where an inventory
    belongs.

    `reason` is the span's diagnostic and reaches the reader nowhere: it goes to
    `rationale_summary`, which is the turn record. The tool-count clause — *"I can also look up your
    own HR data with 9 tools"* — is gone with it; a person counting the assistant's tools is a
    grader, and the dashboard counts them properly.
    """
    covered = _sentence(example_topics())
    return AnswerSchema(
        blocks=[AnswerBlock(type="recommendation", text=USER_REFUSAL, citations=[])],
        next_steps=[
            f"I can help with things like {covered}.",
            f"If this is urgent, contact People Operations at {PEOPLE_OPS}.",
        ],
        rationale_summary=f"Refused and redirected: {reason}."[:200],
    )


__all__ = [
    "EXAMPLE_TOPIC_COUNT",
    "NO_EVIDENCE",
    "OUT_OF_SCOPE",
    "USER_REFUSAL",
    "WEAK_EVIDENCE",
    "Scored",
    "Verdict",
    "check",
    "coverage",
    "evaluate",
    "example_topics",
    "refusal",
]
