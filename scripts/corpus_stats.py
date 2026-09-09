"""Print the size of the policy corpus: files, pages, words and per-format counts (spec §5.3).

    python scripts/corpus_stats.py

Pages are counted at **500 words per page** for the three text formats plus the **real page count** for
the PDF, which is the convention the §5.3 document table is stated in. `tests/unit/test_corpus_stats.py`
asserts a band — 5 to 20 files and 30 to 120 pages — rather than an exact figure, so ordinary wording
edits never fail the build while a document silently disappearing still does.

`--json` prints the same numbers as a single JSON object, for a later phase that wants to assert on them
without re-deriving the arithmetic.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

if __package__:
    from .check_facts import CORPUS_DIR, REPO_ROOT, Document, load_documents
else:  # `python scripts/corpus_stats.py` puts this file's own directory on sys.path
    from check_facts import CORPUS_DIR, REPO_ROOT, Document, load_documents

WORDS_PER_PAGE = 500


@dataclass(frozen=True)
class DocumentStats:
    doc_id: str
    source_format: str
    topics: tuple[str, ...]
    sections: int
    words: int
    pages: float


def _pdf_pages(document: Document) -> int:
    return len(PdfReader(str(document.path)).pages)


def document_stats(document: Document) -> DocumentStats:
    words = document.word_count
    pages = float(_pdf_pages(document)) if document.source_format == "pdf" else words / WORDS_PER_PAGE
    return DocumentStats(
        doc_id=document.doc_id,
        source_format=document.source_format,
        topics=document.topics,
        sections=len(document.heading_paths),
        words=words,
        pages=round(pages, 1),
    )


def corpus_stats(corpus_dir: Path = CORPUS_DIR) -> dict:
    documents = [document_stats(document) for document in load_documents(corpus_dir).values()]
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
    print(f"\n  {'total':<34}{'':<6}{'':>9}{stats['words']:>8}{stats['pages']:>7}")

    formats = " · ".join(
        f"{name} {values['documents']} ({values['pages']} pp)" for name, values in stats["formats"].items()
    )
    print(f"\n{stats['files']} files · {stats['pages']} pages · {stats['words']:,} words · {formats}")
    print(f"{len(stats['topics'])} topics: {', '.join(stats['topics'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
