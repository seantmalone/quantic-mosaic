"""The heading-aware chunker: heading-path propagation and bounded overlap (spec §6.3, R2.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hrmosaic.rag.chunk import CHUNKER_VERSION, chunk_corpus, chunk_document, snippet_of, windows
from hrmosaic.rag.parse import corpus_paths, parse_corpus, parse_path
from hrmosaic.settings import settings

# Bound to module constants deliberately: an assertion that mentions `settings` renders the whole
# Settings object — including credentials — into pytest's failure output.
MAX_CHARS = settings.chunk_max_chars
WINDOW_CHARS = settings.chunk_window_chars
OVERLAP_CHARS = settings.chunk_overlap_chars
MIN_CHARS = settings.chunk_min_chars

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "corpus"
CORPUS_MINI = REPO_ROOT / "tests" / "fixtures" / "corpus_mini"


@pytest.fixture(scope="module")
def mini_chunks():
    return chunk_corpus(parse_corpus(CORPUS_MINI))


@pytest.fixture(scope="module")
def corpus_chunks():
    return chunk_corpus(parse_corpus(CORPUS))


def test_every_chunk_carries_its_leaf_heading_path(mini_chunks):
    document = parse_path(CORPUS_MINI / "mini-md.md")
    windowed = [chunk for chunk in mini_chunks if chunk.heading_path == "Accrual > Standard Accrual Rates"]
    assert len(windowed) > 1, "the fixture's long leaf must reach the windowing branch"
    assert {chunk.section for chunk in windowed} == {"Standard Accrual Rates"}
    assert {chunk.doc_title for chunk in windowed} == {document.doc_title}
    assert all(chunk.chunker_version == CHUNKER_VERSION for chunk in mini_chunks)


def test_a_short_leaf_is_one_chunk_and_is_never_merged(mini_chunks):
    carryover = [chunk for chunk in mini_chunks if chunk.heading_path == "Accrual > Carryover"]
    assert len(carryover) == 1
    assert carryover[0].n_chars < MIN_CHARS * 2
    assert "Employees may carry over two imaginary days." in carryover[0].text


def test_windows_of_one_leaf_overlap_and_stay_within_the_limits(mini_chunks):
    windowed = [chunk for chunk in mini_chunks if chunk.heading_path == "Accrual > Standard Accrual Rates"]
    for earlier, later in zip(windowed, windowed[1:], strict=False):
        shared = earlier.char_end - later.char_start
        assert 0 < shared <= OVERLAP_CHARS
        assert later.text[:shared] == earlier.text[-shared:]
    for chunk in windowed:
        assert MIN_CHARS <= chunk.n_chars <= MAX_CHARS


def test_no_chunk_of_the_real_corpus_breaks_a_bound(corpus_chunks):
    for chunk in corpus_chunks:
        assert chunk.n_chars <= MAX_CHARS
        assert chunk.n_chars >= MIN_CHARS
        assert chunk.text == chunk.text.strip()
    assert len({chunk.chunk_id for chunk in corpus_chunks}) == len(corpus_chunks)


def test_a_leaf_whose_only_full_stop_is_early_still_advances():
    """Regression: the overlap used to carry the cut search back to the same sentence boundary, so
    the window crawled forward one character at a time and emitted colliding chunk ids."""
    text = (
        ("policy " * 40)
        + "and that is the only full stop in this leaf. "
        + " ".join(f"item-{number}" for number in range(400))
    )
    pieces = windows(text)
    starts = [offset for offset, _ in pieces]
    assert starts == sorted(set(starts)), "windows must advance, and never repeat an offset"
    assert len(pieces) <= len(text) // WINDOW_CHARS + 2
    assert pieces[-1][0] + len(pieces[-1][1]) == len(text)


def test_a_leaf_within_the_maximum_is_returned_whole():
    text = "Short enough. " * 10
    assert windows(text) == [(0, text)]


def test_the_windowing_floor_absorbs_a_tail_instead_of_emitting_a_sliver():
    sentence = "This sentence is exactly the kind of filler a windowing test needs. "
    text = sentence * 25
    pieces = windows(text)
    assert all(len(piece) >= MIN_CHARS for _, piece in pieces)
    assert all(len(piece) <= MAX_CHARS for _, piece in pieces)


def test_chunk_ids_hash_the_joined_heading_path_not_a_list():
    document = parse_path(CORPUS_MINI / "mini-md.md")
    chunks = chunk_document(document)
    heading_paths = {chunk.heading_path for chunk in chunks}
    assert "Accrual > Standard Accrual Rates" in heading_paths
    assert not any(path.startswith("[") for path in heading_paths)
    assert all(chunk.chunk_id.startswith("c_") and len(chunk.chunk_id) == 18 for chunk in chunks)


def test_the_header_block_before_the_first_heading_is_not_chunked(mini_chunks):
    assert all(chunk.heading_path for chunk in mini_chunks)
    assert not any("Document ID: mini-md" in chunk.text for chunk in mini_chunks)


def test_the_injection_canary_lands_in_exactly_one_chunk(corpus_chunks):
    """The lure is deliberately shorter than `CHUNK_MAX_CHARS` so it cannot be split away from the
    label that explains it (`corpus/README.md`); G4 quarantines that one chunk."""
    canary = [chunk for chunk in corpus_chunks if "EXAMPLE OF A PHISHING LURE" in chunk.heading_path]
    assert len(canary) == 1
    assert canary[0].doc_id == "security-acceptable-use"
    assert canary[0].n_chars <= MAX_CHARS


def test_snippet_is_a_whitespace_normalised_substring_of_its_chunk(corpus_chunks):
    for chunk in corpus_chunks:
        assert chunk.snippet
        assert len(chunk.snippet) <= 320
        assert chunk.snippet in " ".join(chunk.text.split())


def test_snippet_trims_to_a_sentence_boundary():
    text = "First sentence here. " + "x" * 400
    assert snippet_of(text) == "First sentence here."


def test_every_corpus_document_contributes_chunks(corpus_chunks):
    doc_ids = {chunk.doc_id for chunk in corpus_chunks}
    assert doc_ids == {path.stem for path in corpus_paths(CORPUS)}
