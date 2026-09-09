"""The read-only reader over the built index (spec §4.2, §6.5).

Three callers share it, and none of them may import `hrmosaic.rag`: guardrail **G2** resolves a cited
`chunk_id` against the real index rather than against the retrieved set, `mcpserver/rules.py` resolves
a `(doc_id, heading_path)` pair from `corpus/rules.yml` to a real chunk, and the dashboard's corpus
browser renders `documents.full_text`. It lives in `core/` because `agent/**` is allowed to import
`core.corpusread` and nothing else from the retrieval side.

It opens the index file **read-only** (`file:…?mode=ro`) and touches only the plain tables — `chunks`,
`documents`, `index_meta`. The `vec0` virtual table needs the sqlite-vec extension, which
`rag/index.py` loads; a connection made here can read every citation field without it.

`IndexMeta` also owns the two derived version strings of §6.5, computed on read and stored nowhere:
`corpus_version` is the documents' common `version` stamp, and `index_version` appends the first four
characters of `manifest_sha256`, so a corpus edit that moves the manifest moves the reported index
version with no hand-maintained number.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from hrmosaic.settings import settings


class IndexModelMismatch(RuntimeError):
    """The stored index was built by a different embedder, dimension, metric or query convention.

    Raised lazily by `rag.index.open_index()` and caught at exactly two boundaries (§6.5): `/health`
    reports it as a degradation and `/chat` answers `configuration_required`. Nothing raises it at
    boot, because a restart loop on a stale image is worse than a degraded instance.
    """


@dataclass(frozen=True)
class IndexMeta:
    """The single `index_meta` row (spec §6.5)."""

    embed_model: str
    dim: int
    chunker_version: str
    distance_metric: str
    query_convention: str
    format_counts: dict[str, dict[str, int]]
    corpus_sha256: str
    manifest_sha256: str
    built_at: str
    chunk_count: int
    doc_count: int
    corpus_version: str = ""

    @property
    def index_version(self) -> str:
        """`<corpus_version>+<first four characters of manifest_sha256>` (§6.5)."""
        return f"{self.corpus_version}+{self.manifest_sha256[:4]}"


@dataclass(frozen=True)
class ChunkRow:
    """One stored chunk, carrying exactly the fields a citation needs (R2.5)."""

    chunk_id: str
    doc_id: str
    doc_title: str
    source_format: str
    heading_path: str
    section: str
    text: str
    snippet: str
    char_start: int
    char_end: int
    n_chars: int
    text_sha256: str
    topics: tuple[str, ...]


@dataclass(frozen=True)
class DocumentRow:
    """One stored document; `full_text` is what the corpus browser renders."""

    doc_id: str
    doc_title: str
    source_format: str
    topics: tuple[str, ...]
    section_count: int
    chunk_count: int
    word_count: int
    estimated_pages: float
    effective_date: str
    version: str
    full_text: str


_CHUNK_COLUMNS = (
    "chunk_id, doc_id, doc_title, source_format, heading_path, section, text, snippet, "
    "char_start, char_end, n_chars, text_sha256, topics"
)
_DOCUMENT_COLUMNS = (
    "doc_id, doc_title, source_format, topics, section_count, chunk_count, word_count, "
    "estimated_pages, effective_date, version, full_text"
)

_connections: dict[str, sqlite3.Connection] = {}


def connect(path: Path | None = None) -> sqlite3.Connection:
    """A read-only connection to the index file, cached per resolved path."""
    resolved = str(Path(path or settings.index_path).resolve())
    connection = _connections.get(resolved)
    if connection is None:
        connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        _connections[resolved] = connection
    return connection


def close_all() -> None:
    """Drop every cached connection — used by tests and by the shutdown handler."""
    while _connections:
        _, connection = _connections.popitem()
        connection.close()


def _conn(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    return connection if connection is not None else connect()


def _chunk(row: sqlite3.Row) -> ChunkRow:
    return ChunkRow(**{**dict(row), "topics": tuple(json.loads(row["topics"]))})


def _document(row: sqlite3.Row) -> DocumentRow:
    return DocumentRow(**{**dict(row), "topics": tuple(json.loads(row["topics"]))})


def read_index_meta(connection: sqlite3.Connection | None = None) -> IndexMeta:
    """The `index_meta` row, with `corpus_version` read from the documents' common stamp."""
    connection = _conn(connection)
    row = connection.execute("SELECT * FROM index_meta").fetchone()
    if row is None:
        raise IndexModelMismatch("index_meta is empty: the index was not built by rag/index.py")
    versions = {value for (value,) in connection.execute("SELECT DISTINCT version FROM documents")}
    return IndexMeta(
        embed_model=row["embed_model"],
        dim=row["dim"],
        chunker_version=row["chunker_version"],
        distance_metric=row["distance_metric"],
        query_convention=row["query_convention"],
        format_counts=json.loads(row["format_counts_json"]),
        corpus_sha256=row["corpus_sha256"],
        manifest_sha256=row["manifest_sha256"],
        built_at=row["built_at"],
        chunk_count=row["chunk_count"],
        doc_count=row["doc_count"],
        corpus_version=versions.pop() if len(versions) == 1 else "",
    )


def get_chunk(chunk_id: str, connection: sqlite3.Connection | None = None) -> ChunkRow | None:
    """One chunk by id, or `None` — G2's resolvability check, so an unknown id is not an error."""
    row = _conn(connection).execute(f"SELECT {_CHUNK_COLUMNS} FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
    return _chunk(row) if row else None


def list_chunks(doc_id: str, connection: sqlite3.Connection | None = None) -> list[ChunkRow]:
    """Every chunk of one document, in document order — how `rules.py` resolves a heading path."""
    rows = (
        _conn(connection)
        .execute(f"SELECT {_CHUNK_COLUMNS} FROM chunks WHERE doc_id = ? ORDER BY char_start", (doc_id,))
        .fetchall()
    )
    return [_chunk(row) for row in rows]


def list_documents(connection: sqlite3.Connection | None = None) -> list[DocumentRow]:
    """Every document, by id — what G1's refusal reads to name what the corpus does cover."""
    rows = _conn(connection).execute(f"SELECT {_DOCUMENT_COLUMNS} FROM documents ORDER BY doc_id").fetchall()
    return [_document(row) for row in rows]


def get_document(doc_id: str, connection: sqlite3.Connection | None = None) -> DocumentRow | None:
    """One document by id, or `None`."""
    row = _conn(connection).execute(f"SELECT {_DOCUMENT_COLUMNS} FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    return _document(row) if row else None
