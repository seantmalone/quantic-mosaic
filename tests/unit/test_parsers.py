"""The four parsing paths of R2.1 (spec §6.2).

One test per format over `tests/fixtures/corpus_mini/`, plus the two assertions §6.2 names against the
real corpus: the PDF's extracted heading set **equals** `workplace-conduct.src.md`'s, and the running
footer never reaches a block.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hrmosaic.rag.parse import corpus_paths, parse_path
from hrmosaic.rag.parse import md as md_parser
from hrmosaic.rag.parse import pdf as pdf_parser

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "corpus"
CORPUS_MINI = REPO_ROOT / "tests" / "fixtures" / "corpus_mini"


@pytest.fixture(scope="module")
def mini() -> dict[str, object]:
    return {path.suffix.lstrip("."): parse_path(path) for path in corpus_paths(CORPUS_MINI)}


def test_all_four_formats_parse(mini):
    assert sorted(mini) == ["html", "md", "pdf", "txt"]
    for source_format, document in mini.items():
        assert document.source_format == source_format
        assert document.doc_title
        assert document.blocks
        assert document.effective_date == "2026-01-01"
        assert document.version == "2026.1"
        assert document.topics


def test_markdown_heading_path_excludes_the_title(mini):
    document = mini["md"]
    assert document.doc_title == "Mini Markdown Policy"
    assert "Accrual > Standard Accrual Rates" in document.heading_paths
    assert "Mini Markdown Policy" not in " ".join(document.heading_paths)


def test_markdown_ignores_headings_inside_a_fence():
    stream = md_parser.lines("# Title\n\n```\n## Not a heading\n```\n\n## Real\n")
    assert [line for level, line in stream if level is not None] == ["Title", "Real"]


def test_html_becomes_markdown_and_keeps_its_table(mini):
    document = mini["html"]
    assert document.doc_title == "Mini HTML Guide"
    assert "Eligibility > Waiting Period" in document.heading_paths
    table = next(block for block in document.blocks if block.heading_path == "Contribution Table")
    assert "| Employee plus one | USD 90 |" in table.text


def test_text_heading_convention_is_underlines_and_capitals(mini):
    document = mini["txt"]
    assert document.doc_title == "Mini Text Policy"
    assert "Device Security" in document.heading_paths
    assert "Device Security > FULL-DISK ENCRYPTION" in document.heading_paths
    assert "Device Security > SCREEN LOCK" in document.heading_paths


def test_pdf_heading_set_equals_the_source(mini):
    document = mini["pdf"]
    source = CORPUS_MINI / "mini-pdf.src.md"
    expected = set(pdf_parser.source_headings(source))
    extracted = {name for path in document.heading_paths for name in path.split(" > ")}
    assert extracted == expected


def test_real_pdf_heading_set_equals_workplace_conduct_src_md():
    """The §6.2 assertion, on the document it is written about."""
    document = parse_path(CORPUS / "workplace-conduct.pdf")
    expected = set(pdf_parser.source_headings(CORPUS / "workplace-conduct.src.md"))
    extracted = {name for path in document.heading_paths for name in path.split(" > ")}
    assert extracted == expected
    assert document.doc_title == "Workplace Conduct Policy"


def test_pdf_footer_and_page_artifacts_are_dropped():
    """The footer splices into a sentence across a page break, so it is stripped before joining."""
    document = parse_path(CORPUS / "workplace-conduct.pdf")
    assert document.page_count > 1
    assert "Mosaic Robotics, Inc. · workplace-conduct · Page" not in document.text
    for block in document.blocks:
        assert "· Page " not in block.text


def test_char_offsets_slice_the_assembled_text(mini):
    for document in mini.values():
        for block in document.blocks:
            assert document.text[block.char_start : block.char_end] == block.text


def test_src_md_is_not_a_corpus_document():
    names = [path.name for path in corpus_paths(CORPUS)]
    assert "workplace-conduct.src.md" not in names
    assert sum(1 for name in names if name.endswith(".md")) == 11
    assert len(names) == 14


def test_a_header_naming_another_document_is_refused(tmp_path: Path):
    document = tmp_path / "wrong-id.md"
    document.write_text(
        "# Wrong\n\nDocument ID: other-doc · Owner: People Operations · "
        "Effective 2026-01-01 · Version 2026.1\n\n## Body\n\nText.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="other-doc"):
        parse_path(document)
