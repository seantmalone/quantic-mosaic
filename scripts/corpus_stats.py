"""Print the size of the policy corpus: files, pages, words and per-format counts (spec §5.3).

    python scripts/corpus_stats.py

**The numbers come from the production parser.** `hrmosaic.rag.parse.parse_corpus` is the reader
`python -m hrmosaic.rag.ingest` builds the index with, so every figure here is the figure the
committed `data/index/hr_index.sqlite`, the live `/api/corpus` response and `/dashboard/corpus`
show — the same words, the same sections, the same pages. It used to import `check_facts.py`'s
script-local reader instead, which counts a Markdown `##` marker and a TXT underline as words and
keeps heading-only sections, and the two readings disagreed on screen: 31,007 words and 176-vs-190
sections published against the index's 30,840 (2026-09-21 grade card, rank 6). `check_facts.py`
keeps its own reader for what it alone needs — matching a `facts.yml` quote verbatim against the
rendered bytes of the file on disk.

Pages are counted at **500 words per page** for the three text formats plus the **real page count**
for the PDF, which is the convention the §5.3 document table is stated in;
`ParsedDocument.estimated_pages` is that arithmetic and this script does not repeat it.
`tests/unit/test_corpus_stats.py` asserts a band — 5 to 20 files and 30 to 120 pages — rather than an
exact figure, so ordinary wording edits never fail the build while a document silently disappearing
still does.

`--json` prints the same numbers as a single JSON object, for a later phase that wants to assert on
them without re-deriving the arithmetic.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from hrmosaic.rag.parse import ParsedDocument, parse_corpus

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "corpus"

#: Stated here because the §5.3 table is stated in it and `test_corpus_stats.py` re-derives the
#: per-document arithmetic from it. The division itself lives on `ParsedDocument.estimated_pages`.
WORDS_PER_PAGE = 500


@dataclass(frozen=True)
class DocumentStats:
    doc_id: str
    source_format: str
    topics: tuple[str, ...]
    sections: int
    words: int
    pages: float


def document_stats(document: ParsedDocument) -> DocumentStats:
    """One row of the §5.3 table, straight off the parsed document the index was built from.

    `sections` is `len(heading_paths)` — the count the `documents` table stores — so a heading with
    no body of its own is not counted: it carries no text, so nothing in it can be retrieved or cited.
    """
    return DocumentStats(
        doc_id=document.doc_id,
        source_format=document.source_format,
        topics=document.topics,
        sections=len(document.heading_paths),
        words=document.word_count,
        pages=round(document.estimated_pages, 1),
    )


def corpus_stats(corpus_dir: Path = CORPUS_DIR) -> dict:
    documents = [document_stats(document) for document in parse_corpus(corpus_dir)]
    by_format: dict[str, dict] = {}
    for source_format in sorted({stats.source_format for stats in documents}):
        subset = [stats for stats in documents if stats.source_format == source_format]
        by_format[source_format] = {
            "documents": len(subset),
            "words": sum(stats.words for stats in subset),
            "pages": round(sum(stats.pages for stats in subset), 1),
        }
    topics = Counter(topic for stats in documents for topic in stats.topics)
    return {
        "files": len(documents),
        "words": sum(stats.words for stats in documents),
        "pages": round(sum(stats.pages for stats in documents), 1),
        "sections": sum(stats.sections for stats in documents),
        "formats": by_format,
        "topics": dict(sorted(topics.items())),
        "documents": [vars(stats) | {"topics": list(stats.topics)} for stats in documents],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the statistics as JSON")
    args = parser.parse_args(argv)

    stats = corpus_stats()
    if args.json:
        print(json.dumps(stats, indent=2))
        return 0

    print(f"Mosaic HR Copilot — policy corpus ({CORPUS_DIR.relative_to(REPO_ROOT)})\n")
    print(f"  {'document':<34}{'fmt':<6}{'sections':>9}{'words':>8}{'pages':>7}  topics")
    for document in stats["documents"]:
        print(
            f"  {document['doc_id']:<34}{document['source_format']:<6}{document['sections']:>9}"
            f"{document['words']:>8}{document['pages']:>7}  {', '.join(document['topics'])}"
        )
    print(f"\n  {'total':<34}{'':<6}{stats['sections']:>9}{stats['words']:>8}{stats['pages']:>7}")

    formats = " · ".join(
        f"{name} {values['documents']} ({values['pages']} pp)" for name, values in stats["formats"].items()
    )
    print(
        f"\n{stats['files']} files · {stats['pages']} pages · {stats['words']:,} words · "
        f"{stats['sections']} sections · {formats}"
    )
    print(f"{len(stats['topics'])} topics: {', '.join(stats['topics'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
