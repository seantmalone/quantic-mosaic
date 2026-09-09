"""Heading-aware chunking with bounded overlap windows (spec §6.3, R2.2, R1.4).

Policy documents are authored as semantically complete sections and **the section path is the
citation**, so the primary split is the leaf section. A leaf at or below `CHUNK_MAX_CHARS` is emitted
whole and never merged with a neighbour; a longer leaf resolves to an ordered list of windows that
share one heading path and overlap by `CHUNK_OVERLAP_CHARS`, cut on sentence boundaries so a chunk
never begins mid-sentence.

**Determinism (R1.4).** The chunker is a pure function of the corpus bytes plus four constants — no
randomness, so no seed. `tests/unit/test_chunking_deterministic.py` re-runs it and asserts byte
identity with the committed `data/index/chunks.manifest.jsonl`.

The heading path is joined to a **string before hashing and before storage**, never a list repr, so
the manifest, `chunks.heading_path` and every citation carry one form:

    chunk_id = "c_" + sha256(f"{doc_id}|{heading_path}|{char_start}|{text}").hexdigest()[:16]

`CHUNKER_VERSION` is bumped whenever a chunk constant or the hash input changes; it is written into
`index_meta` and into every manifest row.

A block with no heading path — the header lines between a document's title and its first heading — is
**not** chunked: it carries the `Document ID` / `Topics` metadata, which `documents` already stores,
and a chunk with an empty heading path could not satisfy the R2.5 citation guarantee.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from hrmosaic.rag.parse import HEADING_SEPARATOR, ParsedDocument
from hrmosaic.settings import settings

#: Bumped whenever a chunk constant or the `chunk_id` hash input changes (spec §6.3).
CHUNKER_VERSION = "2026.1"

SNIPPET_CHARS = 320

#: The keys of one `chunks.manifest.jsonl` row, in the order §6.3 fixes them.
MANIFEST_KEYS = (
    "chunk_id",
    "doc_id",
    "doc_title",
    "heading_path",
    "char_start",
    "char_end",
    "n_chars",
    "text",
    "text_sha256",
    "chunker_version",
)

_SENTENCE_END = re.compile(r"[.!?][\"')\]]?(?=\s|$)")


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit, carrying every field a citation needs (R2.5)."""

    chunk_id: str
    doc_id: str
    doc_title: str
    source_format: str
    heading_path: str
    section: str
    text: str
    snippet: str
    char_start: int
    char_end: int
    n_chars: int
    text_sha256: str
    chunker_version: str
    topics: tuple[str, ...]

    def manifest_row(self) -> dict[str, Any]:
        """The committed manifest's view of this chunk: text and hashes, never vectors."""
        return {key: getattr(self, key) for key in MANIFEST_KEYS}


def normalise(text: str) -> str:
    """Collapse every run of whitespace to a single space."""
    return " ".join(text.split())


def snippet_of(text: str, limit: int = SNIPPET_CHARS) -> str:
    """The first `limit` characters, whitespace-normalised and trimmed to a sentence boundary.

    G2 checks that a displayed snippet is a whitespace-normalised substring of its chunk's text, so
    nothing is ever appended — no ellipsis, no padding.
    """
    flat = normalise(text)
    if len(flat) <= limit:
        return flat
    head = flat[:limit]
    ends = [match.end() for match in _SENTENCE_END.finditer(head)]
    if ends:
        return head[: ends[-1]]
    space = head.rfind(" ")
    return head[:space] if space > 0 else head


def _cut(text: str, low: int, high: int) -> int:
    """The last sentence boundary in `(low, high]`, else the last space, else `high`."""
    ends = [match.end() for match in _SENTENCE_END.finditer(text, low, high)]
    if ends:
        return ends[-1]
    space = text.rfind(" ", low, high)
    return space + 1 if space > low else high


def windows(
    text: str,
    *,
    max_chars: int | None = None,
    window_chars: int | None = None,
    overlap_chars: int | None = None,
    min_chars: int | None = None,
) -> list[tuple[int, str]]:
    """Split one leaf into `(offset, text)` pieces; a leaf within `max_chars` is returned whole."""
    max_chars = settings.chunk_max_chars if max_chars is None else max_chars
    window_chars = settings.chunk_window_chars if window_chars is None else window_chars
    overlap_chars = settings.chunk_overlap_chars if overlap_chars is None else overlap_chars
    min_chars = settings.chunk_min_chars if min_chars is None else min_chars

    if len(text) <= max_chars:
        return [(0, text)]

    pieces: list[tuple[int, str]] = []
    start = 0
    previous_end = 0
    length = len(text)
    while start < length:
        end = min(start + window_chars, length)
        # A tail shorter than the windowing floor is absorbed rather than emitted as a sliver.
        if length - end < min_chars:
            end = length
        if end < length:
            # The cut must land past the previous window's end, or the overlap would carry the
            # search back to the same sentence boundary and the window would crawl forward one
            # character at a time. A section whose only full stop is early — a long bulleted list —
            # is what makes that reachable.
            low = max(start + min_chars, previous_end + 1)
            end = _cut(text, low, end) if low < end else end
        previous_end = end
        piece = text[start:end]
        lead = len(piece) - len(piece.lstrip())
        stripped = piece.strip()
        if stripped:
            pieces.append((start + lead, stripped))
        if end >= length:
            break
        start = max(end - overlap_chars, start + 1)
    return pieces


def chunk_document(document: ParsedDocument, **limits: int | None) -> list[Chunk]:
    """Every chunk of one document, in document order."""
    chunks: list[Chunk] = []
    for block in document.blocks:
        if not block.heading_path:
            continue
        for offset, text in windows(block.text, **limits):
            char_start = block.char_start + offset
            digest = hashlib.sha256(f"{document.doc_id}|{block.heading_path}|{char_start}|{text}".encode()).hexdigest()
            chunks.append(
                Chunk(
                    chunk_id=f"c_{digest[:16]}",
                    doc_id=document.doc_id,
                    doc_title=document.doc_title,
                    source_format=document.source_format,
                    heading_path=block.heading_path,
                    section=block.heading_path.split(HEADING_SEPARATOR)[-1],
                    text=text,
                    snippet=snippet_of(text),
                    char_start=char_start,
                    char_end=char_start + len(text),
                    n_chars=len(text),
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    chunker_version=CHUNKER_VERSION,
                    topics=document.topics,
                )
            )
    return chunks


def chunk_corpus(documents: list[ParsedDocument], **limits: int | None) -> list[Chunk]:
    """Every chunk of every document, in the order the documents were parsed."""
    return [chunk for document in documents for chunk in chunk_document(document, **limits)]


def manifest_bytes(chunks: list[Chunk]) -> bytes:
    """The committed manifest: one JSON object per chunk, newline-terminated, UTF-8.

    `ensure_ascii=False` keeps the corpus's own punctuation readable in a diff, which is the whole
    point of committing text rather than vectors.
    """
    lines = [json.dumps(chunk.manifest_row(), ensure_ascii=False) for chunk in chunks]
    return ("\n".join(lines) + "\n").encode("utf-8")
