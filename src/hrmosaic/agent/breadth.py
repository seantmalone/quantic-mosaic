"""Citation breadth — the answer covers the documents its evidence spans (spec §7.4, P24).

**Not a guardrail.** Like `agent/outcome.py` it emits no `guardrail` span and carries no G-number:
it is one deterministic step that runs after synthesis, on the blocks G2 and G3 have already
repaired, and its whole job is to notice that the answer is narrower than the evidence it was
written from and to ask for the gap once.

**The failure it exists for**, in the published run `r_1789086979_baseline`: `expenses-002` asked
four things about one trip, its synthesis prompt listed five citable documents under CITATION
COVERAGE, and the answer cited two — losing `manager-approval-matrix`, the document that carries
the approval authority the question asked for, against an end state of `min_distinct_docs: 3`.
`onboarding-001` cited two of the four documents its gold answer names. Neither is a retrieval
defect: DocRecall is scored over the retrieval spans and read 1.000 on both.

Three things keep the cost bounded and the answer honest:

1. **It runs only on multi-document turns.** `RouteDecision.multi_doc` — or a workflow, which is
   multi-document by construction (§9.3) — is the only item-independent signal for the
   `min_distinct_docs` end state; the serving path never reads `evaluation/dataset.yaml`. A
   single-document turn never pays for a second call.
2. **One call, never two.** The repair is a single `purpose="repair"` round trip that names the
   uncited documents and their passages and asks for them to be cited *or* declared unused. If the
   second answer is still narrow, the first one stands.
3. **The repair has to earn the swap.** It replaces the answer only when it is strictly broader,
   G2 dropped nothing from it, G2 did not refuse it, and it kept every block the reader already
   had. Nothing here ever writes a citation the model did not: a fabricated citation is exactly
   what G2 exists to strip.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

#: What the step is called where it is named — reports, the spec paragraph beside §7.4's table.
#: Deliberately not a `G<n>`: the six guardrails are a closed set.
STEP_NAME = "citation_breadth"

#: The one message the repair round trip appends. It names the documents and the passage ids the
#: model may cite, and the two ways out — cite it, or say it was not used. It never says "cite
#: everything": a document the question does not touch must stay uncited, and rule 8's
#: `not used: <doc>` line in `rationale_summary` is how the model says so where a reader can see it.
INSTRUCTION = (
    "BREADTH CHECK — rule 8. Your answer cites none of the following citable document(s), each of "
    "which was retrieved for this question:\n{documents}\n"
    "For each one: if it supports any statement in your answer, add or extend a `policy_fact` that "
    "cites one of its passage ids above; if it genuinely says nothing about this question, leave it "
    "uncited and write `not used: <doc_id>` in `rationale_summary`. Keep every block you already "
    "wrote and its wording, cite no id that is not listed in CITATION COVERAGE, and invent nothing. "
    "Reply with the COMPLETE answer JSON, not a fragment."
)


class Decision(Protocol):
    """The two `RouteDecision` fields the gate reads (§9.2)."""

    multi_doc: bool
    workflow: str | None


class Chunk(Protocol):
    """One citable evidence chunk, as `orchestrator.EvidenceChunk` carries it (§7.1)."""

    chunk_id: str
    doc_id: str
    doc_title: str
    quarantined: bool


def applies(decision: Decision) -> bool:
    """Whether this turn is one a breadth check is allowed to spend a second synthesis call on."""
    return bool(decision.multi_doc) or decision.workflow is not None


def citable(chunks: Sequence[Chunk]) -> list[Chunk]:
    """The chunks an answer could actually cite — quarantined ones are never a coverage target."""
    return [chunk for chunk in chunks if not chunk.quarantined]


def cited_documents(blocks: Sequence[Mapping[str, Any]], chunks: Sequence[Chunk]) -> set[str]:
    """The citable documents the blocks reach, resolved through the turn's own evidence."""
    documents = {chunk.chunk_id: chunk.doc_id for chunk in citable(chunks)}
    return {
        documents[chunk_id] for block in blocks for chunk_id in block.get("citations") or [] if chunk_id in documents
    }


def uncited_documents(blocks: Sequence[Mapping[str, Any]], chunks: Sequence[Chunk]) -> list[str]:
    """The citable documents no block cites, in the order the evidence first offered them."""
    cited = cited_documents(blocks, chunks)
    missing: list[str] = []
    for chunk in citable(chunks):
        if chunk.doc_id not in cited and chunk.doc_id not in missing:
            missing.append(chunk.doc_id)
    return missing


def instruction(missing: Sequence[str], chunks: Sequence[Chunk]) -> str:
    """The repair message: the uncited documents, their passage ids, and the two ways out."""
    lines: list[str] = []
    for doc_id in missing:
        passages = [chunk for chunk in citable(chunks) if chunk.doc_id == doc_id]
        ids = ", ".join(chunk.chunk_id for chunk in passages)
        title = passages[0].doc_title if passages else doc_id
        lines.append(f"- {doc_id} — {title} — passage(s): {ids}")
    return INSTRUCTION.format(documents="\n".join(lines))


def accepted(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    chunks: Sequence[Chunk],
    *,
    dropped_blocks: int,
    refused: bool,
) -> bool:
    """Whether the repaired answer — already through G2 and G3 — replaces the first one."""
    if refused or dropped_blocks or len(after) < len(before):
        return False
    return len(cited_documents(after, chunks)) > len(cited_documents(before, chunks))


__all__ = [
    "INSTRUCTION",
    "STEP_NAME",
    "Chunk",
    "Decision",
    "accepted",
    "applies",
    "citable",
    "cited_documents",
    "instruction",
    "uncited_documents",
]
