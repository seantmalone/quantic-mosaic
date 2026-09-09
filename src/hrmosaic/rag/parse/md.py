"""Markdown parsing — the reference heading path (spec §6.2).

A regex over ATX headings, fenced-block aware so a `#` comment inside a code fence is body text and
not a heading. `#` is the document title (level 0), `##` and `###` are the two components of a
heading path; deeper headings are not used by the corpus and are read as body text.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import ParsedDocument, assemble

_ATX = re.compile(r"^(#{1,3})\s+(.*?)\s*#*$")
_FENCE = re.compile(r"^\s*(?:```|~~~)")


def lines(text: str) -> list[tuple[int | None, str]]:
    """The `(level, line)` stream `assemble()` folds; level 0 is the title."""
    stream: list[tuple[int | None, str]] = []
    in_fence = False
    for raw in text.splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
            stream.append((None, raw))
            continue
        heading = None if in_fence else _ATX.match(raw)
        if heading:
            stream.append((len(heading.group(1)) - 1, heading.group(2)))
        else:
            stream.append((None, raw))
    return stream


def parse(path: Path) -> ParsedDocument:
    return assemble(path.stem, "md", lines(path.read_text(encoding="utf-8")))
