"""G2 `citation_resolvability` — a citation the reader cannot follow is not a citation (§7.4).

A cited `chunk_id` is stripped when any of four things is true:

1. the id is **unknown** to the index;
2. the **displayed metadata** (doc, title, heading path, section) mismatches the real chunk;
3. the **displayed snippet** is not a whitespace-normalised substring of the real chunk text;
4. the cited chunk is **quarantined** by G4.

Resolution reads the **real index** through `core.corpusread.get_chunk` rather than the retrieved
set — otherwise a plausible id carried over from a prior turn would "resolve" against evidence that
was never in this answer's prompt. `agent/**` may import `core.corpusread` and nothing else from the
retrieval side; that exemption exists for exactly this rule (§4.2).

The cascade is the point: strip the citation; if a `policy_fact` block loses **all** of its
citations, drop the block; if every block drops, refuse. Verdict `repair`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from hrmosaic.agent.guardrails import emit
from hrmosaic.core import corpusread
from hrmosaic.core.models import Citation

if TYPE_CHECKING:
    from hrmosaic.core.trace import TurnBuffer

_WHITESPACE = re.compile(r"\s+")

#: The corpus browser route §7.3 gives every citation.
SOURCE_URL = "/dashboard/corpus/{doc_id}#{chunk_id}"


class Displayed(Protocol):
    """What the evidence claimed about a chunk — the half that can drift from the index."""

    chunk_id: str
    doc_id: str
    doc_title: str
    heading_path: str
    section: str
    snippet: str
    dense_score: float
    quarantined: bool


def normalise(text: str) -> str:
    """Whitespace-normalised, for the substring test of trigger 3."""
    return _WHITESPACE.sub(" ", text).strip()


@dataclass(frozen=True)
class Resolution:
    """One citation's verdict, plus the `Citation` built from the **real** chunk when it stands."""

    chunk_id: str
    ok: bool
    reason: str | None = None
    citation: Citation | None = None


@dataclass
class Outcome:
    """What G2 did to an answer: the surviving blocks, the resolved citations, and the casualties."""

    blocks: list[dict[str, Any]]
    citations: list[Citation]
    stripped: list[Resolution] = field(default_factory=list)
    dropped_blocks: int = 0
    refused: bool = False

    @property
    def repaired(self) -> bool:
        return bool(self.stripped) or self.dropped_blocks > 0


def resolve(chunk_id: str, *, displayed: Displayed | None = None, quarantined: bool = False) -> Resolution:
    """The pure rule for one cited id. Reads the index; writes nothing."""
    chunk = corpusread.get_chunk(chunk_id)
    if chunk is None:
        return Resolution(chunk_id, ok=False, reason="unknown chunk_id")
    if quarantined or (displayed is not None and displayed.quarantined):
        return Resolution(chunk_id, ok=False, reason="quarantined chunk (G4)")
    if displayed is not None:
        for label, shown, real in (
            ("doc_id", displayed.doc_id, chunk.doc_id),
            ("doc_title", displayed.doc_title, chunk.doc_title),
            ("heading_path", displayed.heading_path, chunk.heading_path),
            ("section", displayed.section, chunk.section),
        ):
            if shown != real:
                return Resolution(chunk_id, ok=False, reason=f"displayed {label} mismatches the index")
        if normalise(displayed.snippet) not in normalise(chunk.text):
            return Resolution(chunk_id, ok=False, reason="displayed snippet is not in the chunk text")
    return Resolution(
        chunk_id,
        ok=True,
        citation=Citation(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            doc_title=chunk.doc_title,
            heading_path=chunk.heading_path,
            section=chunk.section,
            snippet=chunk.snippet,
            score=float(displayed.dense_score) if displayed is not None else 0.0,
            quarantined=False,
            source_url=SOURCE_URL.format(doc_id=chunk.doc_id, chunk_id=chunk.chunk_id),
        ),
    )


def apply(
    blocks: Sequence[Mapping[str, Any]],
    *,
    evidence: Mapping[str, Displayed] | None = None,
    quarantined: Sequence[str] = (),
) -> Outcome:
    """The pure cascade over one answer's raw blocks. Returns new blocks; mutates nothing."""
    evidence = evidence or {}
    quarantined_ids = set(quarantined)
    resolutions: dict[str, Resolution] = {}
    kept: list[dict[str, Any]] = []
    stripped: list[Resolution] = []
    dropped = 0

    for block in blocks:
        surviving: list[str] = []
        for chunk_id in block.get("citations") or []:
            if chunk_id not in resolutions:
                resolutions[chunk_id] = resolve(
                    chunk_id,
                    displayed=evidence.get(chunk_id),
                    quarantined=chunk_id in quarantined_ids,
                )
            resolution = resolutions[chunk_id]
            if resolution.ok:
                if chunk_id not in surviving:
                    surviving.append(chunk_id)
            elif resolution not in stripped:
                stripped.append(resolution)
        if block.get("type") == "policy_fact" and not surviving and (block.get("citations") or []):
            # It had citations and lost every one of them: the claim is now unsupported.
            dropped += 1
            continue
        kept.append({**dict(block), "citations": surviving})

    ordered: list[Citation] = []
    seen: set[str] = set()
    for block in kept:
        for chunk_id in block["citations"]:
            if chunk_id not in seen:
                seen.add(chunk_id)
                citation = resolutions[chunk_id].citation
                if citation is not None:
                    ordered.append(citation)
    return Outcome(
        blocks=kept,
        citations=ordered,
        stripped=stripped,
        dropped_blocks=dropped,
        refused=bool(blocks) and not kept,
    )


def check(
    blocks: Sequence[Mapping[str, Any]],
    *,
    turn: TurnBuffer | None = None,
    evidence: Mapping[str, Displayed] | None = None,
    quarantined: Sequence[str] = (),
    evidence_span_ids: Sequence[str] = (),
) -> Outcome:
    """Run the cascade and emit the one `guardrail` span."""
    outcome = apply(blocks, evidence=evidence, quarantined=quarantined)
    total = sum(len(block.get("citations") or []) for block in blocks)
    resolved = sum(len(block["citations"]) for block in outcome.blocks)
    emit(
        turn,
        "G2",
        verdict="repair" if outcome.repaired else "allow",
        reason=f"{resolved}/{total} citations resolved",
        evidence_span_ids=list(evidence_span_ids),
        details={
            "citations_seen": total,
            "citations_resolved": resolved,
            "stripped": [{"chunk_id": item.chunk_id, "reason": item.reason} for item in outcome.stripped],
            "blocks_dropped": outcome.dropped_blocks,
            "refused": outcome.refused,
        },
    )
    return outcome


__all__ = ["SOURCE_URL", "Displayed", "Outcome", "Resolution", "apply", "check", "normalise", "resolve"]
