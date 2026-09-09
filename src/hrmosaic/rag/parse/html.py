"""HTML parsing — a converter, not a second implementation (spec §6.2).

`beautifulsoup4` isolates the `<body>`, `markdownify` renders it as Markdown with ATX headings, and
the Markdown path does the heading extraction. `<h1>`/`<h2>`/`<h3>` therefore land on exactly the
levels `md.py` already defines, and a `<table>` survives as the pipe-delimited text §6.2 requires —
the approval thresholds live in tables and must reach a chunk intact.
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify

from . import ParsedDocument, assemble
from .md import lines


def to_markdown(raw: str) -> str:
    """The `<body>` of an HTML page as Markdown."""
    soup = BeautifulSoup(raw, "html.parser")
    body = soup.body or soup
    return markdownify(str(body), heading_style="ATX")


def parse(path: Path) -> ParsedDocument:
    return assemble(path.stem, "html", lines(to_markdown(path.read_text(encoding="utf-8"))))
