"""Plain-text parsing — a heading convention that owes nothing to Markdown (spec §6.2).

The convention is stated in the document itself and in `corpus/README.md`:

* a line underlined with `=` is the document title;
* a line underlined with `-` is a level-1 heading;
* a line in capitals, alone and unindented, is a level-2 heading.

`tests/unit/test_parsers.py` asserts it, because a convention nothing checks is a comment.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import ParsedDocument, assemble

_TITLE_RULE = re.compile(r"^=+$")
_SECTION_RULE = re.compile(r"^-{3,}$")
_SUBSECTION = re.compile(r"^[A-Z][A-Z0-9 ,'&()./-]*[A-Z0-9)]$")


def lines(text: str) -> list[tuple[int | None, str]]:
    """The `(level, line)` stream `assemble()` folds; an underline is consumed with its heading."""
    raw_lines = text.splitlines()
    stream: list[tuple[int | None, str]] = []
    skip_next = False
    for index, raw in enumerate(raw_lines):
        if skip_next:
            skip_next = False
            continue
        stripped = raw.strip()
        following = raw_lines[index + 1].strip() if index + 1 < len(raw_lines) else ""
        if stripped and _TITLE_RULE.fullmatch(following):
            stream.append((0, stripped))
            skip_next = True
        elif stripped and _SECTION_RULE.fullmatch(following):
            stream.append((1, stripped))
            skip_next = True
        elif raw == stripped and _SUBSECTION.fullmatch(stripped):
            stream.append((2, stripped))
        else:
            stream.append((None, raw))
    return stream


def parse(path: Path) -> ParsedDocument:
    return assemble(path.stem, "txt", lines(path.read_text(encoding="utf-8")))
