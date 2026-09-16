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

Four things keep the cost bounded and the answer honest:

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
4. **A turn that has already spent its budget never reaches the step at all.** That gate lives at
   the call site, where the §9.4 budgets live (`orchestrator._answer` step 5b): a `max_steps` /
   `max_tool_calls` / `timeout` `stop_reason`, or a wall clock already past
   `AGENT_WALL_CLOCK_S`, means the answer below is a graceful partial, and widening it would spend
   a second synthesis-sized call on the one turn the budget exists to bound.
"""

from __future__ import annotations

import re
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


#: Words that carry no claim, dropped before two `policy_fact` blocks are compared (W8, C26).
#: A restatement differs in its articles and its connectives, not in what it asserts.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "may",
        "must",
        "not",
        "of",
        "on",
        "or",
        "own",
        "s",
        "than",
        "that",
        "the",
        "their",
        "they",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
        "you",
        "your",
    }
)

#: The minimum distinct documents a multi-document answer is expected to cite. Read off the
#: workflow where there is one; this is the floor for a `multi_doc` turn with none.
MIN_DISTINCT_DOCS = 2

#: The key a block carries its position in the model's own answer under — `agent/outcome.py`'s
#: `BLOCK_ID`, repeated here so this module imports nothing. `carry_citations` matches on it.
BLOCK_ID = "_block_id"


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
    """Whether the *routing* of this turn is one a breadth check may spend a second call on.

    This is the shape half of the gate and not the whole of it: the caller also refuses a turn
    that has already spent a §9.4 budget (item 4 above), which is a fact about the turn's clock
    rather than about its route decision and therefore lives where the budgets do.
    """
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


def claim_key(text: str) -> str:
    """The claim a `policy_fact` makes, with the wording taken out (W8, C26).

    Two blocks that assert the same rule in different words — which is how the model answered the
    breadth instruction: a second block rather than a second citation — normalise to one key, and
    their citations are merged onto one block instead of telling the reader the same thing twice
    from two sources.
    """
    words = re.findall(r"[a-z0-9.]+", text.lower())
    return " ".join(sorted({word.strip(".") for word in words if word.strip(".") and word not in STOPWORDS}))


def merge(blocks: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    """`(the blocks with duplicate claims merged, the indexes that were merged away)`.

    Only `policy_fact` blocks merge, and only into the first block that made the claim: its
    wording is the one the reader sees, and the later block's citations join it in order.
    """
    seen: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    merged: list[int] = []
    for index, block in enumerate(blocks):
        item = dict(block)
        if item.get("type") != "policy_fact":
            kept.append(item)
            continue
        key = claim_key(str(item.get("text") or ""))
        if key in seen:
            target = kept[seen[key]]
            citations = list(target.get("citations") or [])
            for citation in item.get("citations") or []:
                if citation not in citations:
                    citations.append(citation)
            target["citations"] = citations
            merged.append(index)
            continue
        seen[key] = len(kept)
        kept.append(item)
    return kept, merged


def distinct_docs_shortfall(blocks: Sequence[Mapping[str, Any]], chunks: Sequence[Chunk], *, minimum: int) -> int:
    """How many distinct documents short of `minimum` the served answer is (W8, C26).

    Zero when the answer meets the floor **or** when the turn never retrieved that many documents
    to begin with: a shortfall is an answer narrower than its own evidence, not a corpus that did
    not have more to say.
    """
    available = len({chunk.doc_id for chunk in citable(chunks)})
    target = min(minimum, available)
    return max(0, target - len(cited_documents(blocks, chunks)))


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


def carry_citations(
    reference: Sequence[Mapping[str, Any]], blocks: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """`(blocks with every citation of `reference` still on its own block, the chunk ids carried)`.

    **No post-synthesis step may drop a citation from a surviving policy fact** (W9 addendum,
    ruling 2): `remote-002` reached the breadth repair with three documents and was served with
    two, because a later step — the record backstop, the restatement, the sentence surgery — took
    a *sentence* out of a block and its citations went with the whole block.

    **A citation goes back on its own block and nowhere else** (W10 addendum). The first version
    put it on the *nearest surviving policy fact*, matched by scaled position, which attaches one
    claim's evidence to another claim's sentence as soon as a step removes a block — a citation
    that no longer supports what it sits under is worse than a missing one. Blocks are matched by
    the `BLOCK_ID` marker the orchestrator sets before the first step and every step copies, so
    "its own block" is exact; a citation whose whole block is gone vanishes with it.
    """
    kept: list[dict[str, Any]] = [dict(block) for block in blocks]
    surviving: dict[Any, int] = {
        block[BLOCK_ID]: index for index, block in enumerate(kept) if block.get(BLOCK_ID) is not None
    }
    carried: list[str] = []
    for block in reference:
        identity = block.get(BLOCK_ID)
        target = surviving.get(identity) if identity is not None else None
        if target is None:
            continue
        present = set(kept[target].get("citations") or [])
        lost = [citation for citation in block.get("citations") or [] if citation not in present]
        if not lost:
            continue
        kept[target]["citations"] = [*kept[target].get("citations", []), *lost]
        carried.extend(lost)
    return kept, carried


__all__ = [
    "BLOCK_ID",
    "INSTRUCTION",
    "MIN_DISTINCT_DOCS",
    "STEP_NAME",
    "carry_citations",
    "STOPWORDS",
    "Chunk",
    "Decision",
    "accepted",
    "applies",
    "citable",
    "cited_documents",
    "claim_key",
    "distinct_docs_shortfall",
    "instruction",
    "merge",
    "uncited_documents",
]
