"""Four parsing paths onto one document shape (spec §6.1, §6.2).

Each format module turns its bytes into the same `(level, line)` stream — `0` for the document
title, `1` or `2` for a heading, `None` for body text — and `assemble()` folds that stream into a
`ParsedDocument`. So the four paths differ only in *heading extraction*, which is the part R2.1
actually asks to be tested four times; everything downstream sees one shape.

**Heading paths exclude the document title** (`corpus/README.md`, and `scripts/check_facts.py`
enforces it for `facts.yml` and `rules.yml`): a `##`/`###` pair produces the two-component
`"Accrual > Standard Accrual Rates"`, joined with `" > "`. The title travels separately as
`doc_title` in every citation. The chunker hashes that joined string, so a change here moves every
`chunk_id`.

**Character offsets index `ParsedDocument.text`**, the cleaned text this module assembles — not the
raw bytes on disk, which for the PDF do not exist as text at all. That text is what `documents.full_text`
stores and what the corpus browser renders, so a chunk's `char_start`/`char_end` slice it exactly.

Cleaning is uniform (§6.2): trailing whitespace goes, runs of blank lines collapse to one, the PDF's
running footer and page-number artifacts are dropped, and pipe-delimited tables are preserved
verbatim because approval thresholds live in them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HEADING_SEPARATOR = " > "

#: `Document ID: pto-and-holidays · Owner: People Operations · Effective 2026-01-01 · Version 2026.1`
_HEADER_LINE = re.compile(
    r"^Document ID:\s*(?P<doc_id>[a-z0-9-]+)\s*·\s*Owner:\s*(?P<owner>[^·]+?)\s*·\s*"
    r"Effective\s*(?P<effective_date>\d{4}-\d{2}-\d{2})\s*·\s*Version\s*(?P<version>\S+)\s*$",
    re.MULTILINE,
)
_TOPICS_LINE = re.compile(r"^Topics:\s*(?P<topics>.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Block:
    """One leaf section: its `" > "`-joined heading path and its own body text."""

    heading_path: str
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ParsedDocument:
    """One policy document, parsed into blocks (spec §6.1)."""

    doc_id: str
    doc_title: str
    source_format: str
    topics: tuple[str, ...]
    effective_date: str
    version: str
    text: str
    blocks: tuple[Block, ...]
    #: Real pages, for the PDF alone; every other format is counted at 500 words to a page, which
    #: is the convention `scripts/corpus_stats.py` states the §5.3 document table in.
    page_count: int = 0

    @property
    def estimated_pages(self) -> float:
        return float(self.page_count) if self.page_count else round(self.word_count / 500, 1)

    @property
    def heading_paths(self) -> tuple[str, ...]:
        return tuple(block.heading_path for block in self.blocks if block.heading_path)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def clean_line(line: str) -> str:
    """Uniform cleaning of one body line: tabs become spaces, trailing whitespace goes."""
    return line.replace("\t", "    ").rstrip()


def _clean_body(lines: list[str]) -> str:
    """Collapse runs of blank lines to one and trim the block, preserving table pipes as authored."""
    cleaned: list[str] = []
    for line in lines:
        line = clean_line(line)
        if not line and (not cleaned or not cleaned[-1]):
            continue
        cleaned.append(line)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned)


def assemble(doc_id: str, source_format: str, lines: list[tuple[int | None, str]]) -> ParsedDocument:
    """Fold a `(level, line)` stream into a `ParsedDocument`.

    `level` is `0` for the title, `1`/`2` for a heading and `None` for body text. Sections are
    emitted in document order; a section whose body is empty (an `##` immediately followed by its
    first `###`) contributes its heading to the assembled text but no block, because a block with no
    text cannot be cited.
    """
    title = ""
    open_levels: list[tuple[int, str]] = []
    pending: list[str] = []
    sections: list[tuple[str, str, str]] = []  # (heading line, heading path, body)

    def close(heading_line: str) -> None:
        path = HEADING_SEPARATOR.join(name for _, name in open_levels)
        sections.append((heading_line, path, _clean_body(pending)))

    heading_line = ""
    for level, line in lines:
        if level is None:
            pending.append(line)
            continue
        close(heading_line)
        pending = []
        if level == 0:
            title = line
            heading_line = ""
            open_levels = []
        else:
            heading_line = line
            open_levels = [entry for entry in open_levels if entry[0] < level]
            open_levels.append((level, line))
    close(heading_line)

    segments: list[str] = []
    blocks: list[Block] = []
    offset = 0

    def append(segment: str) -> int:
        """Append one `"\\n\\n"`-joined segment and return the offset it starts at."""
        nonlocal offset
        if segments:
            offset += 2
        start = offset
        segments.append(segment)
        offset += len(segment)
        return start

    if title:
        append(title)
    for heading, path, body in sections:
        if heading:
            append(heading)
        if not body:
            continue
        start = append(body)
        blocks.append(Block(heading_path=path, text=body, char_start=start, char_end=start + len(body)))

    text = "\n\n".join(segments)
    header = _HEADER_LINE.search(text)
    topics_line = _TOPICS_LINE.search(text)
    if header and header.group("doc_id") != doc_id:
        raise ValueError(f"{doc_id}: header names Document ID {header.group('doc_id')!r}")
    topics = ()
    if topics_line:
        topics = tuple(topic.strip() for topic in topics_line.group("topics").split(",") if topic.strip())
    return ParsedDocument(
        doc_id=doc_id,
        doc_title=title,
        source_format=source_format,
        topics=topics,
        effective_date=header.group("effective_date") if header else "",
        version=header.group("version") if header else "",
        text=text,
        blocks=tuple(blocks),
    )


def parse_path(path: Path) -> ParsedDocument:
    """Parse one corpus file, dispatching on its extension."""
    from . import html, md, pdf, txt

    parsers = {".md": md.parse, ".html": html.parse, ".pdf": pdf.parse, ".txt": txt.parse}
    parser = parsers.get(path.suffix)
    if parser is None:
        raise ValueError(f"unsupported corpus format: {path.name}")
    return parser(path)


#: Files under a corpus directory that are index or documentation rather than policy documents.
NON_DOCUMENT_STEMS = frozenset({"facts", "rules", "README"})


def corpus_paths(corpus_dir: Path) -> list[Path]:
    """Every policy document under `corpus_dir`, in a stable order.

    `<stem>.src.md` is the PDF's authoring source, not a document in its own right (spec §6.1), so
    exactly eleven Markdown documents are ingested from the real corpus.
    """
    return sorted(
        path
        for path in corpus_dir.iterdir()
        if path.suffix in (".md", ".html", ".pdf", ".txt")
        and path.stem not in NON_DOCUMENT_STEMS
        and not path.name.endswith(".src.md")
    )


def parse_corpus(corpus_dir: Path) -> list[ParsedDocument]:
    """Parse every policy document under `corpus_dir`, ordered by file name."""
    return [parse_path(path) for path in corpus_paths(corpus_dir)]
