"""Render `corpus/workplace-conduct.src.md` to the committed `corpus/workplace-conduct.pdf`.

The corpus needs a fourth format so that R2.1's four parsing paths are real (spec §6.2). The PDF is
generated **once** by this script from a hand-authored Markdown source and then committed; the source
stays in the repository so that the PDF's heading set has an authoritative reference — spec §6.2 asks
`tests` to assert that the headings extracted from the PDF *equal* `workplace-conduct.src.md`'s.

    python scripts/build_pdf.py && test -s corpus/workplace-conduct.pdf

Deliberate properties of the output:

* **Core fonts only.** fpdf2's built-in Helvetica is Latin-1, so the source is written in Latin-1-safe
  characters and no font file has to be vendored into the repository or the Docker image.
* **Headings are extractable.** Every heading is emitted on its own line, under 80 characters and
  without a terminal full stop, which is exactly the heuristic the P4 PDF parser applies.
* **A running footer.** Every page carries `Mosaic Robotics, Inc. · workplace-conduct · Page N`, which
  gives the uniform cleaning step in §6.2 ("drop the boilerplate footer") something real to drop.
* **Deterministic bytes.** The creation date is pinned, so re-running the script on an unchanged source
  produces an unchanged file and the committed PDF does not churn in git.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "corpus" / "workplace-conduct.src.md"
TARGET = REPO_ROOT / "corpus" / "workplace-conduct.pdf"

DOC_ID = "workplace-conduct"
CREATION_DATE = datetime(2026, 1, 1, tzinfo=UTC)

BODY_FONT_SIZE = 10.5
LINE_HEIGHT = 5.0
ATX = re.compile(r"^(#{1,3})\s+(.*?)\s*#*$")
BOLD = re.compile(r"\*\*(.+?)\*\*")

#: Heading levels mapped to (font size, style, space before, space after).
HEADING_STYLE = {
    1: (17.0, "B", 0.0, 4.0),
    2: (13.0, "B", 6.0, 2.5),
    3: (11.0, "BI", 4.0, 1.5),
}


class ConductPDF(FPDF):
    """A4 with a running footer that names the document and the page."""

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("helvetica", size=8)
        self.set_text_color(110)
        self.cell(0, 5, f"Mosaic Robotics, Inc. · {DOC_ID} · Page {self.page_no()}", align="C")
        self.set_text_color(0)


def _plain(text: str) -> str:
    """Strip the little inline Markdown the source uses; the PDF carries no inline styling."""
    return BOLD.sub(r"\1", text).replace("*", "")


def build(source: Path = SOURCE, target: Path = TARGET) -> Path:
    pdf = ConductPDF(format="A4", unit="mm")
    pdf.set_margins(left=22, top=20, right=22)
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_title("Workplace Conduct Policy")
    pdf.set_author("Mosaic Robotics, Inc. — People Operations")
    pdf.set_subject("Policy corpus document: workplace-conduct")
    pdf.set_creation_date(CREATION_DATE)
    pdf.add_page()

    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line:
            continue
        heading = ATX.match(line)
        if heading:
            size, style, before, after = HEADING_STYLE[len(heading.group(1))]
            pdf.ln(before)
            pdf.set_font("helvetica", style=style, size=size)
            pdf.multi_cell(0, size * 0.42, _plain(heading.group(2)), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(after)
            continue
        pdf.set_font("helvetica", size=BODY_FONT_SIZE)
        pdf.multi_cell(0, LINE_HEIGHT, _plain(line), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2.0)

    pdf.output(str(target))
    return target


def main() -> int:
    target = build()
    print(f"wrote {target.relative_to(REPO_ROOT)} ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
