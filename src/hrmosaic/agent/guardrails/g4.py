"""G4 `injection_shield` — quarantine untrusted text that gives the assistant orders (spec §7.4).

A quarantined chunk is shown with a warning banner and **cannot be cited**: G2 strips the citation,
the block is dropped, and G1 may then refuse — on camera. So a false positive here is as dangerous
as a false negative, and the patterns are scoped to **imperative-to-assistant** forms rather than to
the bare verbs. Our own corpus legitimately says *"send your case details to
people-ops@mosaicrobotics.example"*, and demo task 1 has to cite the People Ops mobility contact.

`tests/unit/test_g4_no_false_positives.py` runs `scan()` over **every chunk in the committed
manifest** and asserts that the only quarantined document is `security-acceptable-use`, which
carries the deliberate canary inside a labelled *example of a phishing lure* section.

**The table and the scan live in `core/injection.py`; this module is still their only public name.**
`mcpserver/tools/search_policy_documents.py` has to take the same decision the agent takes — a hit
carries the whole chunk now, and the MCP endpoint is publicly reachable (§15, R-12) — and §4.2
forbids `mcpserver/` importing `hrmosaic.agent`. So the regex table moved down to `core/`, which
both packages may import, and everything with a *policy* in it stayed here. Nothing outside this
module imports `core.injection`, except the one tool that must.

Fencing is the second half of the defence and lives in the prompts: every untrusted string is
rendered inside a `<document trust="data">` or `<tool_result trust="data">` envelope under a
standing system rule that envelope content is data and never an instruction (§7.2).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from hrmosaic.agent.guardrails import emit
from hrmosaic.core.injection import PATTERNS, scan

if TYPE_CHECKING:
    from hrmosaic.core.trace import TurnBuffer


class Scannable(Protocol):
    """Anything with an id and text: a manifest row, a `ChunkRow`, a retrieved chunk."""

    chunk_id: str
    text: str


#: The one §8.4 tool whose result carries chunk text (W2-C).
SEARCH_TOOL = "search_policy_documents"


def quarantine_search_hits(body: dict[str, Any]) -> dict[str, Any]:
    """Strip the chunk text of any search hit that gives the assistant orders, in place (W2-C).

    A `search_policy_documents` hit carries the whole stored chunk so the loop need not spend an act
    step re-reading it. The corpus's one quarantinable chunk is 630 characters and its imperative
    begins at character 355 — past `SNIPPET_CHARS` — so before W2-C `scan()` over the snippet never
    saw it and it never reached the act conversation. It would now, one `json.dumps` later.

    The shield runs **here**, in the agent, rather than in the tool: §4.2's dependencies run
    downward and `mcpserver/` may not import a guardrail, and a client that trusted the server to
    scan its own output would have no shield at all against any other MCP server it is pointed at.
    `agent/client.py` calls it on the way in, before the `tool_call` span is written and long before
    the result is appended to the conversation, so neither the record nor the model ever holds the
    text. What survives is the 320-character snippet and `quarantined: true` — the same flag `_mark`
    puts on the lifted `retrieval` span, on the copy the model reads.
    """
    for hit in body.get("hits") or []:
        text = hit.get("text")
        if text and scan(text) is not None:
            hit["text"] = None
            hit["quarantined"] = True
    return body


@dataclass(frozen=True)
class Match:
    """One quarantine decision: which chunk, which pattern, and the text that tripped it."""

    chunk_id: str
    pattern: str
    excerpt: str


def scan_all(chunks: Iterable[Scannable]) -> list[Match]:
    """Every quarantine decision over a set of chunks, in input order. Pure."""
    matches = []
    for chunk in chunks:
        hit = scan(chunk.text)
        if hit is not None:
            matches.append(Match(chunk_id=chunk.chunk_id, pattern=hit[0], excerpt=hit[1]))
    return matches


def check(
    chunks: Sequence[Scannable],
    *,
    turn: TurnBuffer | None = None,
    source: str = "retrieval",
    parent_span_id: str | None = None,
) -> list[Match]:
    """Scan new evidence and emit the one `guardrail` span. Returns the quarantine decisions.

    A clean scan still emits a span with `verdict="allow"`: the audit answers *was the evidence
    checked?*, and an absent span cannot distinguish "nothing matched" from "nobody looked".
    """
    matches = scan_all(chunks)
    emit(
        turn,
        "G4",
        verdict="warn" if matches else "allow",
        reason=(
            f"{len(matches)} of {len(chunks)} {source} chunks quarantined"
            if matches
            else f"{len(chunks)} {source} chunks clean"
        ),
        matched_pattern=matches[0].pattern if matches else None,
        details={
            "chunks_scanned": len(chunks),
            "quarantined": len(matches),
            "chunk_ids": [match.chunk_id for match in matches],
            "patterns": sorted({match.pattern for match in matches}),
            "source": source,
        },
        parent_span_id=parent_span_id,
    )
    return matches


__all__ = ["PATTERNS", "SEARCH_TOOL", "Match", "Scannable", "check", "quarantine_search_hits", "scan", "scan_all"]
