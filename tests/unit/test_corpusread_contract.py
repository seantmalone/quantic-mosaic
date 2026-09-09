"""`core/corpusread.py` — the read-only reader G2, the rules engine and the corpus browser share.

The contract three later phases build on (spec §4.2, §6.5):

* `get_chunk` returns the stored chunk or `None` — an unknown id is a verdict, not an exception;
* `list_chunks(doc_id)` returns that document's chunks in document order, which is how
  `mcpserver/rules.py` resolves a `(doc_id, heading_path)` pair from `rules.yml`;
* `list_documents()` carries `full_text` for the corpus browser and the topics G1's refusal names;
* `IndexMeta` derives `corpus_version` and `index_version` on read and stores neither;
* the connection is **read-only**, and `open_index()` refuses an index built by another embedder.
"""

from __future__ import annotations

import sqlite3

import pytest

from hrmosaic.core.corpusread import (
    IndexModelMismatch,
    get_chunk,
    get_document,
    list_chunks,
    list_documents,
    read_index_meta,
)
from hrmosaic.rag.embed import FAKE_MODEL_NAME, QUERY_CONVENTION
from hrmosaic.rag.index import DISTANCE_METRIC, open_index


def test_list_documents_carries_the_browser_and_refusal_fields(mini_index):
    documents = list_documents(mini_index)
    assert [document.doc_id for document in documents] == [
        "mini-html",
        "mini-md",
        "mini-pdf",
        "mini-txt",
    ]
    for document in documents:
        assert document.doc_title and document.full_text and document.topics
        assert document.chunk_count > 0
        assert document.section_count > 0
        assert document.word_count > 0
        assert document.estimated_pages > 0
        assert document.effective_date == "2026-01-01"
        assert document.version == "2026.1"


def test_get_document_returns_none_for_an_unknown_id(mini_index):
    assert get_document("no-such-document", mini_index) is None
    assert get_document("mini-md", mini_index).source_format == "md"


def test_list_chunks_is_in_document_order(mini_index):
    chunks = list_chunks("mini-md", mini_index)
    assert [chunk.char_start for chunk in chunks] == sorted(chunk.char_start for chunk in chunks)
    assert [chunk.heading_path for chunk in chunks][:2] == [
        "Purpose and Scope",
        "Accrual > Standard Accrual Rates",
    ]


def test_a_heading_path_resolves_to_a_chunk_id_the_way_the_rules_engine_will(mini_index):
    matches = [chunk for chunk in list_chunks("mini-md", mini_index) if chunk.heading_path == "Accrual > Carryover"]
    assert len(matches) == 1
    assert get_chunk(matches[0].chunk_id, mini_index) == matches[0]


def test_get_chunk_returns_none_for_an_id_that_exists_nowhere(mini_index):
    assert get_chunk("c_0000000000000000", mini_index) is None


def test_index_meta_derives_both_version_strings(mini_index):
    meta = read_index_meta(mini_index)
    assert meta.embed_model == FAKE_MODEL_NAME
    assert meta.dim == 384
    assert meta.distance_metric == DISTANCE_METRIC == "cosine"
    assert meta.query_convention == QUERY_CONVENTION
    assert meta.chunker_version == "2026.1"
    assert meta.corpus_version == "2026.1"
    assert meta.index_version == f"2026.1+{meta.manifest_sha256[:4]}"
    assert meta.doc_count == 4
    assert set(meta.format_counts) == {"md", "html", "pdf", "txt", "totals"}
    assert meta.built_at and meta.corpus_sha256


def test_the_reader_connection_is_read_only(mini_index):
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        mini_index.execute("DELETE FROM chunks")


def test_open_index_refuses_an_index_built_by_another_embedder(mini_ingest):
    """The §6.5 mismatch guard, naming both values. It is raised lazily and caught at exactly two
    boundaries, so `/health` can stay 200 on a stale image."""
    with pytest.raises(IndexModelMismatch) as raised:
        open_index(mini_ingest.index_path)
    message = str(raised.value)
    assert FAKE_MODEL_NAME in message
    assert "BAAI/bge-small-en-v1.5" in message


def test_open_index_names_the_command_that_builds_a_missing_index(tmp_path):
    with pytest.raises(FileNotFoundError, match="hrmosaic.rag.ingest"):
        open_index(tmp_path / "absent.sqlite")
