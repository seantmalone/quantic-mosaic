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


#: The one §8.4 tool whose result carries chunk text in a list of hits (W2-C).
SEARCH_TOOL = "search_policy_documents"

#: The result keys that can carry **untrusted corpus prose**, at any depth of a tool result.
#: `text` is `get_policy_section`'s whole section and a search hit's whole chunk; `snippet` is the
#: 320-character display subset a citation shows, on a hit and on `check_policy_compliance`'s
#: per-requirement evidence. Nothing else a tool returns is document text: the mock-data tools
#: return numbers and dates, and the two write tools return prose **we** composed.
TEXT_KEYS = ("text", "snippet")

#: How deep `quarantine_tool_result` walks. Every §8.4 body is at most `body → list → dict → list`;
#: the bound is here so a malformed result from an unknown server cannot spend the request path.
MAX_DEPTH = 6


def quarantine_tool_result(name: str, body: dict[str, Any]) -> dict[str, Any]:
    """Null every untrusted string in one tool result that gives the assistant orders, in place.

    **Per message, not per tool.** W2-C's gate is "no act message contains an unbannered G4
    pattern", and every tool result is appended to the act conversation verbatim — so scanning only
    `search_policy_documents` left the claim resting on which tools a recording happened to call.
    `get_policy_section` returns a whole section of verbatim policy text, and W2-C's own rule 6
    steers the model straight at it ("for a section no search returned"), which is exactly what a
    quarantined hit is: a section whose text the search withheld while advertising
    `quarantined: true`. So the walk is over the body, not over one tool's shape.

    A dirty string becomes `None` and its containing object gains `quarantined: true` — the same
    banner `_mark` puts on the lifted `retrieval` span, on the copy the model reads. For a search
    hit that leaves the 320-character snippet and the flag, which is what a citation needs and all
    a quarantined passage may carry.

    This runs in `client.call_tool` on the way in, **before the `tool_call` span is written and long
    before the result is appended to the conversation**, so neither the `tool_call` record nor the
    **act conversation** ever holds the text. The synthesis prompt is the one place it is shown, and
    it is shown once, inside §7.4's `<document trust="data" quarantined="true">` envelope under
    system rule 4 — `_Turn.chunks()` deliberately returns quarantined chunks and `EvidenceChunk.text`
    re-reads the stored chunk, because an answer written without seeing the passage cannot say what
    the passage was. It stays **uncitable** either way: `_Turn.citable()` filters it out. The search
    tool takes the same decision server-side (W2-C's BLOCKING bullet, so the text is never on the
    wire at all); this is the client's own shield, which holds against any MCP server it is pointed
    at rather than trusting a server to police its own output.
    """
    _walk(body, depth=0)
    return body


def _walk(node: Any, *, depth: int) -> None:
    """Depth-first over the decoded body, nulling what `scan` fires on. Mutates in place."""
    if depth > MAX_DEPTH:
        return
    if isinstance(node, dict):
        for key in TEXT_KEYS:
            value = node.get(key)
            if isinstance(value, str) and value and scan(value) is not None:
                node[key] = None
                node["quarantined"] = True
        for value in node.values():
            _walk(value, depth=depth + 1)
    elif isinstance(node, list):
        for item in node:
            _walk(item, depth=depth + 1)


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


__all__ = [
    "MAX_DEPTH",
    "PATTERNS",
    "SEARCH_TOOL",
    "TEXT_KEYS",
    "Match",
    "Scannable",
    "check",
    "quarantine_tool_result",
    "scan",
    "scan_all",
]
