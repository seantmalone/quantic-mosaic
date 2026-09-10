"""G4 `injection_shield` — quarantine untrusted text that gives the assistant orders (spec §7.4).

A quarantined chunk is shown with a warning banner and **cannot be cited**: G2 strips the citation,
the block is dropped, and G1 may then refuse — on camera. So a false positive here is as dangerous
as a false negative, and the patterns below are scoped to **imperative-to-assistant** forms rather
than to the bare verbs. Our own corpus legitimately says *"send your case details to
people-ops@mosaicrobotics.example"*, and demo task 1 has to cite the People Ops mobility contact.

`tests/unit/test_g4_no_false_positives.py` runs `scan()` over **every chunk in the committed
manifest** and asserts that the only quarantined document is `security-acceptable-use`, which
carries the deliberate canary inside a labelled *example of a phishing lure* section.

Fencing is the second half of the defence and lives in the prompts: every untrusted string is
rendered inside a `<document trust="data">` or `<tool_result trust="data">` envelope under a
standing system rule that envelope content is data and never an instruction (§7.2).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from hrmosaic.agent.guardrails import emit

if TYPE_CHECKING:
    from hrmosaic.core.trace import TurnBuffer


class Scannable(Protocol):
    """Anything with an id and text: a manifest row, a `ChunkRow`, a retrieved chunk."""

    chunk_id: str
    text: str


#: The §7.4 table, verbatim in shape. Each entry is `(name, pattern)`; the name is what the
#: `guardrail` span records as `matched_pattern`, so the dashboard names the rule that fired
#: rather than echoing a regex.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_previous_instructions",
        re.compile(
            r"(?i)\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all)\b"
            r"[^.\n]{0,40}\b(instruction|prompt|rule|direction)s?\b"
        ),
    ),
    ("role_header", re.compile(r"(?im)^\s*(system|assistant)\s*:")),
    ("persona_override", re.compile(r"(?i)\byou are now\b")),
    ("act_as_assistant", re.compile(r"(?i)\bact as (an?|the)\b[^.\n]{0,30}\b(assistant|ai|model)\b")),
    (
        "exfiltration",
        re.compile(r"(?i)\b(exfiltrat|leak)\w*\b[^.\n]{0,40}\b(roster|database|credential|secret|key)s?\b"),
    ),
    (
        "bulk_data_imperative",
        re.compile(
            r"(?i)\b(email|send|forward|post)\b[^.\n]{0,30}\b(the )?"
            r"(roster|employee list|database|all (records|employees))\b"
        ),
    ),
    ("tool_call_frame", re.compile(r"(?i)<tool_call")),
    ("chat_template_frame", re.compile(r"<\|im_start\|>")),
    ("long_base64_run", re.compile(r"[A-Za-z0-9+/]{201,}={0,2}")),
)


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


def scan(text: str) -> tuple[str, str] | None:
    """The pure rule: `(pattern_name, excerpt)` for the first pattern that matches, else `None`.

    First match wins and the scan stops: the verdict is binary — the chunk is quarantined or it is
    not — and naming one pattern keeps the span readable. The excerpt is capped so a span payload
    never carries a document.
    """
    for name, pattern in PATTERNS:
        found = pattern.search(text)
        if found is not None:
            return name, found.group(0)[:200]
    return None


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
