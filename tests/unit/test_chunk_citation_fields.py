"""The citation metadata guarantee, R2.5 (spec §6.5).

Every stored chunk carries a non-empty `doc_id`, `doc_title`, `heading_path`, `section`, `snippet`,
`char_start` and `char_end` — exactly the fields a citation needs. Asserted over the stored rows of a
built index *and* over every chunk of the real corpus, so neither the chunker nor the writer can drop
one silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hrmosaic.core.corpusread import list_chunks, list_documents
from hrmosaic.rag.chunk import chunk_corpus
from hrmosaic.rag.parse import parse_corpus

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "corpus"

CITATION_FIELDS = ("doc_id", "doc_title", "heading_path", "section", "snippet")


@pytest.fixture(scope="module")
def corpus_chunks():
    return chunk_corpus(parse_corpus(CORPUS))


def test_every_stored_chunk_carries_the_citation_fields(mini_index):
    stored = [chunk for document in list_documents(mini_index) for chunk in list_chunks(document.doc_id, mini_index)]
    assert stored
    for chunk in stored:
        for field in CITATION_FIELDS:
            assert getattr(chunk, field), f"{chunk.chunk_id}: empty {field}"
        assert chunk.char_end > chunk.char_start >= 0
        assert chunk.n_chars == len(chunk.text)


def test_every_chunk_of_the_real_corpus_carries_the_citation_fields(corpus_chunks):
    assert len(corpus_chunks) > 100
    for chunk in corpus_chunks:
        for field in CITATION_FIELDS:
            assert getattr(chunk, field), f"{chunk.chunk_id}: empty {field}"
        assert chunk.char_end > chunk.char_start >= 0
        assert chunk.section == chunk.heading_path.split(" > ")[-1]
        assert chunk.topics


def test_a_citation_can_be_rendered_from_a_chunk_alone(corpus_chunks):
    """`doc_title · heading_path` is the citation string; nothing has to be looked up elsewhere."""
    rendered = {f"{chunk.doc_title} · {chunk.heading_path}" for chunk in corpus_chunks}
    assert len(rendered) == len({(chunk.doc_id, chunk.heading_path) for chunk in corpus_chunks})
    assert all(" · " in citation for citation in rendered)
