"""The corpus size gate (spec §5.3).

`scripts/corpus_stats.py` counts pages at 500 words per page for the three text formats plus the real
page count for the PDF. This test asserts a **band** — 5 to 20 files, 30 to 120 pages — rather than the
exact §5.3 figures, so ordinary wording edits never fail the build while a document quietly disappearing
still does.

It also asserts the properties the four-format requirement (R2.1) actually depends on: all four formats
present with at least one non-empty document each, and the per-format subtotals summing to the totals so
that the headline numbers cannot drift away from the per-document ones.
"""

from __future__ import annotations

import pytest

from scripts.check_facts import load_documents
from scripts.corpus_stats import WORDS_PER_PAGE, corpus_stats

STATS = corpus_stats()
DOCUMENTS = load_documents()

MIN_FILES, MAX_FILES = 5, 20
MIN_PAGES, MAX_PAGES = 30, 120
EXPECTED_FORMATS = {"md", "html", "pdf", "txt"}


def test_file_count_is_inside_the_band():
    assert MIN_FILES <= STATS["files"] <= MAX_FILES


def test_page_count_is_inside_the_band():
    assert MIN_PAGES <= STATS["pages"] <= MAX_PAGES


def test_all_four_formats_are_present():
    assert set(STATS["formats"]) == EXPECTED_FORMATS
    for source_format, values in STATS["formats"].items():
        assert values["documents"] >= 1, source_format
        assert values["words"] > 0, source_format


def test_per_format_subtotals_sum_to_the_totals():
    assert sum(values["documents"] for values in STATS["formats"].values()) == STATS["files"]
    assert sum(values["words"] for values in STATS["formats"].values()) == STATS["words"]
    assert round(sum(values["pages"] for values in STATS["formats"].values()), 1) == STATS["pages"]


def test_page_arithmetic_matches_the_documented_convention():
    for document in STATS["documents"]:
        if document["source_format"] == "pdf":
            assert document["pages"] == float(int(document["pages"]))  # a real, whole page count
        else:
            assert document["pages"] == round(document["words"] / WORDS_PER_PAGE, 1)


@pytest.mark.parametrize("doc_id", sorted(DOCUMENTS))
def test_every_document_has_a_title_topics_and_sections(doc_id):
    document = DOCUMENTS[doc_id]
    assert document.title
    assert document.topics
    assert len(document.heading_paths) >= 5
    assert document.word_count >= 800
