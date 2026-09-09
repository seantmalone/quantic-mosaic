"""PDF parsing — the hardest path (spec §6.2).

`pypdf` extracts text page by page; the pages carry a running footer that splices into the middle of
a sentence when they are concatenated, so the footer is dropped **before** the pages are joined, and
so are bare page-number lines. That is the "strip page-number artifacts, drop the boilerplate footer"
half of §6.2's uniform cleaning.

Headings survive rendering only as short lines, so they are recovered by heuristic: **a line is a
heading iff it is ≤ 80 characters, has no terminal full stop, and appears in the heading set of the
`.src.md` beside the PDF.** The set is what makes the heuristic exact — without it every wrapped line
that happens to end mid-sentence would qualify — and the level of each heading comes from the same
source. `tests/unit/test_parsers.py` asserts the extracted heading set *equals* the source's, which is
the assertion §6.2 names.

The `.src.md` is the PDF's authoring source, never a corpus document (`corpus_paths()` excludes it):
the text of every block here is the text `pypdf` read out of the committed PDF, so a sentence that did
not survive rendering fails a corpus check rather than passing on the source's behalf.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from pypdf import PdfReader

from . import ParsedDocument, assemble
from .md import lines as md_lines

MAX_HEADING_CHARS = 80

#: The running footer `scripts/build_pdf.py` stamps on every page.
FOOTER = re.compile(r"^Mosaic Robotics, Inc\. · [a-z0-9-]+ · Page \d+$")
#: A page number left behind on a line of its own by some other renderer.
PAGE_NUMBER = re.compile(r"^(?:Page\s+)?\d+$")


def source_headings(source: Path) -> dict[str, int]:
    """`{heading text: level}` from the `.src.md`, excluding the document title."""
    return {line: level for level, line in md_lines(source.read_text(encoding="utf-8")) if level}


def extract_text(path: Path) -> tuple[str, int]:
    """The PDF's text with the footer and page-number artifacts removed, and its page count."""
    pages = [page.extract_text() or "" for page in PdfReader(str(path)).pages]
    kept: list[str] = []
    for page in pages:
        for raw in page.splitlines():
            stripped = raw.strip()
            if FOOTER.fullmatch(stripped) or PAGE_NUMBER.fullmatch(stripped):
                continue
            kept.append(raw)
    return "\n".join(kept), len(pages)


def lines(text: str, headings: dict[str, int], title: str) -> list[tuple[int | None, str]]:
    """The `(level, line)` stream `assemble()` folds, using the source's heading set."""
    stream: list[tuple[int | None, str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        is_heading = len(stripped) <= MAX_HEADING_CHARS and not stripped.endswith(".")
        if is_heading and stripped == title:
            stream.append((0, stripped))
        elif is_heading and stripped in headings:
            stream.append((headings[stripped], stripped))
        else:
            stream.append((None, raw))
    return stream


def parse(path: Path) -> ParsedDocument:
    source = path.with_suffix(".src.md")
    title = next((line for level, line in md_lines(source.read_text(encoding="utf-8")) if level == 0), "")
    text, page_count = extract_text(path)
    stream = lines(text, source_headings(source), title)
    return replace(assemble(path.stem, "pdf", stream), page_count=page_count)
