"""The sqlite-vec + FTS5 index: schema, build, read-only open, and the self-test (spec §6.5).

One file, `data/index/hr_index.sqlite`, built at Docker build time and on the CI runner — never at
boot, where indexing would dominate a free-tier cold start. Boot only opens it.

`distance_metric=cosine` is declared explicitly on the `vec0` table: sqlite-vec defaults to L2, and a
silent switch would move every score and therefore every calibrated threshold. **One score definition
holds everywhere in this project:** `dense_score = 1 − cosine_distance ∈ [−1, 1]`.

`open_index()` reads `index_meta` and raises `IndexModelMismatch` if the embedder, dimension, metric or
query convention differs from the running configuration. It is called **lazily** and the exception is
caught at exactly two boundaries (§6.5), because `/health` must always answer 200 and raising at boot
would make Render restart-loop the instance on a stale image.

    python -m hrmosaic.rag.index --selftest

runs the fixed query of §6.5 and asserts the top-1 document, a real dense score, and that the stored
chunk count equals the committed manifest's line count. It is a Dockerfile step and a P4 acceptance
command.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import struct
import sys
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec

from hrmosaic.core.corpusread import IndexMeta, IndexModelMismatch, read_index_meta
from hrmosaic.rag import embed
from hrmosaic.rag.chunk import Chunk
from hrmosaic.rag.parse import ParsedDocument
from hrmosaic.settings import settings

DISTANCE_METRIC = "cosine"

#: The §6.5 self-test: a question whose answer lives in exactly one document.
SELFTEST_QUERY = "How many consecutive days abroad require Tax & Legal review?"
SELFTEST_DOC_ID = "tax-and-location-addendum"
#: Deliberately below the guardrail thresholds: it proves the dense arm returned a real match, not
#: that a threshold is calibrated (that is P10's job).
SELFTEST_MIN_DENSE_SCORE = 0.25

#: FTS5 treats most punctuation as syntax, so a question mark or an `&` in a user's words would be a
#: query error rather than a search. Words are extracted and OR-ed; bm25() does the ranking. The class
#: is unicode-aware so an accented word stays one token rather than breaking into junk fragments.
_FTS_TOKEN = re.compile(r"[^\W_]+")

SCHEMA = """
CREATE VIRTUAL TABLE vec_chunks USING vec0(
  chunk_rowid INTEGER PRIMARY KEY, embedding float[{dim}] distance_metric={metric});

CREATE TABLE chunks (
  rowid INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE NOT NULL,
  doc_id TEXT NOT NULL, doc_title TEXT NOT NULL, source_format TEXT NOT NULL,
  heading_path TEXT NOT NULL,
  section TEXT NOT NULL,
  text TEXT NOT NULL, snippet TEXT NOT NULL,
  char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
  n_chars INTEGER NOT NULL, text_sha256 TEXT NOT NULL, topics TEXT NOT NULL);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  text, doc_title, heading_path, content='chunks', content_rowid='rowid');

CREATE TABLE documents (
  doc_id TEXT PRIMARY KEY, doc_title TEXT, source_format TEXT, topics TEXT,
  section_count INTEGER, chunk_count INTEGER, word_count INTEGER, estimated_pages REAL,
  effective_date TEXT, version TEXT, full_text TEXT);

CREATE TABLE index_meta (
  embed_model TEXT NOT NULL, dim INTEGER NOT NULL, chunker_version TEXT NOT NULL,
  distance_metric TEXT NOT NULL,
  query_convention TEXT NOT NULL,
  format_counts_json TEXT NOT NULL,
  corpus_sha256 TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, built_at TEXT NOT NULL,
  chunk_count INTEGER NOT NULL, doc_count INTEGER NOT NULL);
"""


def serialize(vector: list[float]) -> bytes:
    """A float32 blob in the layout `vec0` stores."""
    return struct.pack(f"{len(vector)}f", *vector)


def deserialize(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def cosine(left: list[float], right: list[float]) -> float:
    """The one score definition: cosine similarity, which is `1 − cosine_distance`."""
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def load_extension(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Load sqlite-vec into a connection; the `vec0` table is unreadable without it."""
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    return connection


def build_index(
    chunks: list[Chunk],
    documents: list[ParsedDocument],
    *,
    index_path: Path,
    corpus_sha256: str,
    manifest_sha256: str,
    format_counts: dict[str, dict[str, int]],
) -> Path:
    """Write a complete index to `index_path`, replacing any previous file.

    The embedder runs here and only here in the pipeline: `embed_passages` batches at
    `EMBED_BATCH_SIZE`, and nothing else in the project embeds anything.
    """
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.unlink(missing_ok=True)
    connection = load_extension(sqlite3.connect(index_path))
    try:
        connection.executescript(SCHEMA.format(dim=settings.embed_dim, metric=DISTANCE_METRIC))
        for rowid, chunk in enumerate(chunks, start=1):
            connection.execute(
                "INSERT INTO chunks (rowid, chunk_id, doc_id, doc_title, source_format, heading_path, "
                "section, text, snippet, char_start, char_end, n_chars, text_sha256, topics) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rowid,
                    chunk.chunk_id,
                    chunk.doc_id,
                    chunk.doc_title,
                    chunk.source_format,
                    chunk.heading_path,
                    chunk.section,
                    chunk.text,
                    chunk.snippet,
                    chunk.char_start,
                    chunk.char_end,
                    chunk.n_chars,
                    chunk.text_sha256,
                    json.dumps(list(chunk.topics)),
                ),
            )
        connection.execute(
            "INSERT INTO chunks_fts (rowid, text, doc_title, heading_path) "
            "SELECT rowid, text, doc_title, heading_path FROM chunks"
        )
        vectors = embed.embed_passages([chunk.text for chunk in chunks])
        for rowid, vector in enumerate(vectors, start=1):
            connection.execute(
                "INSERT INTO vec_chunks (chunk_rowid, embedding) VALUES (?, ?)", (rowid, serialize(vector))
            )
        counts = {document.doc_id: 0 for document in documents}
        for chunk in chunks:
            counts[chunk.doc_id] += 1
        for document in documents:
            connection.execute(
                "INSERT INTO documents (doc_id, doc_title, source_format, topics, section_count, "
                "chunk_count, word_count, estimated_pages, effective_date, version, full_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document.doc_id,
                    document.doc_title,
                    document.source_format,
                    json.dumps(list(document.topics)),
                    len(document.heading_paths),
                    counts[document.doc_id],
                    document.word_count,
                    document.estimated_pages,
                    document.effective_date,
                    document.version,
                    document.text,
                ),
            )
        connection.execute(
            "INSERT INTO index_meta (embed_model, dim, chunker_version, distance_metric, "
            "query_convention, format_counts_json, corpus_sha256, manifest_sha256, built_at, "
            "chunk_count, doc_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                embed.model_name(),
                settings.embed_dim,
                chunks[0].chunker_version if chunks else "",
                DISTANCE_METRIC,
                embed.QUERY_CONVENTION,
                json.dumps(format_counts),
                corpus_sha256,
                manifest_sha256,
                datetime.now(UTC).isoformat(timespec="seconds"),
                len(chunks),
                len(documents),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return index_path


def check_meta(meta: IndexMeta) -> None:
    """Raise `IndexModelMismatch` naming both values if the index and the process disagree (§6.5)."""
    expected = {
        "embed_model": embed.model_name(),
        "dim": settings.embed_dim,
        "distance_metric": DISTANCE_METRIC,
        "query_convention": embed.QUERY_CONVENTION,
    }
    differences = [
        f"{field}: index has {getattr(meta, field)!r}, this process expects {value!r}"
        for field, value in expected.items()
        if getattr(meta, field) != value
    ]
    if differences:
        raise IndexModelMismatch("; ".join(differences))


def open_index(path: Path | None = None, *, check: bool = True) -> sqlite3.Connection:
    """A read-only connection with sqlite-vec loaded, guarded against a stale index.

    Called lazily — never at import and never at boot.
    """
    resolved = Path(path or settings.index_path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"no index at {resolved}: run `python -m hrmosaic.rag.ingest`")
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    load_extension(connection)
    if check:
        try:
            check_meta(read_index_meta(connection))
        except Exception:
            connection.close()
            raise
    return connection


def allowed_rowids(
    connection: sqlite3.Connection, doc_ids: list[str] | None = None, topic: str | None = None
) -> list[int] | None:
    """The rowids a `doc_ids` / `topic` filter admits, or `None` when nothing is filtered.

    Applied to **both** retrieval arms before fusion (§7.1), which is why it is computed once here
    rather than inside either arm.
    """
    if not doc_ids and not topic:
        return None
    clauses: list[str] = []
    params: list[object] = []
    if doc_ids:
        clauses.append(f"doc_id IN ({', '.join('?' for _ in doc_ids)})")
        params.extend(doc_ids)
    if topic:
        clauses.append("EXISTS (SELECT 1 FROM json_each(chunks.topics) WHERE json_each.value = ?)")
        params.append(topic)
    sql = f"SELECT rowid FROM chunks WHERE {' AND '.join(clauses)} ORDER BY rowid"
    return [row[0] for row in connection.execute(sql, params)]


def dense_knn(
    connection: sqlite3.Connection, vector: list[float], k: int, rowids: list[int] | None = None
) -> list[tuple[int, float]]:
    """`(rowid, dense_score)` for the k nearest chunks, filtered before the search."""
    if rowids is not None and not rowids:
        return []
    sql = "SELECT chunk_rowid, distance FROM vec_chunks WHERE embedding MATCH ? AND k = ?"
    params: list[object] = [serialize(vector), k]
    if rowids is not None:
        sql += f" AND chunk_rowid IN ({', '.join('?' for _ in rowids)})"
        params.extend(rowids)
    rows = connection.execute(f"{sql} ORDER BY distance", params).fetchall()
    return [(row[0], 1.0 - row[1]) for row in rows]


def bm25_top(connection: sqlite3.Connection, query: str, k: int, rowids: list[int] | None = None) -> list[int]:
    """The rowids of the top-k BM25 matches, best first, filtered before the search."""
    tokens = _FTS_TOKEN.findall(query)
    if not tokens or (rowids is not None and not rowids):
        return []
    match = " OR ".join(f'"{token}"' for token in tokens)
    sql = "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ?"
    params: list[object] = [match]
    if rowids is not None:
        sql += f" AND rowid IN ({', '.join('?' for _ in rowids)})"
        params.extend(rowids)
    sql += " ORDER BY bm25(chunks_fts) LIMIT ?"
    params.append(k)
    return [row[0] for row in connection.execute(sql, params)]


def stored_vectors(connection: sqlite3.Connection, rowids: list[int]) -> dict[int, list[float]]:
    """The **stored** embeddings of the given rowids — the §7.1 fill step never re-embeds text."""
    if not rowids:
        return {}
    placeholders = ", ".join("?" for _ in rowids)
    rows = connection.execute(
        f"SELECT chunk_rowid, embedding FROM vec_chunks WHERE chunk_rowid IN ({placeholders})", rowids
    ).fetchall()
    return {row[0]: deserialize(row[1]) for row in rows}


def chunk_rows(connection: sqlite3.Connection, rowids: list[int]) -> dict[int, sqlite3.Row]:
    """The `chunks` rows behind a candidate set, keyed by rowid."""
    if not rowids:
        return {}
    placeholders = ", ".join("?" for _ in rowids)
    rows = connection.execute(f"SELECT * FROM chunks WHERE rowid IN ({placeholders})", rowids).fetchall()
    return {row["rowid"]: row for row in rows}


def selftest(index_path: Path | None = None, manifest_path: Path | None = None) -> int:
    """The §6.5 self-test. Returns a process exit code and prints what it asserted."""
    from hrmosaic.rag import ingest, retrieve

    manifest_path = manifest_path or ingest.MANIFEST_PATH
    connection = open_index(index_path)
    try:
        meta = read_index_meta(connection)
        result = retrieve.retrieve(SELFTEST_QUERY, k=5, connection=connection)
    finally:
        connection.close()

    problems: list[str] = []
    if not result.hits:
        problems.append("no hits")
    else:
        top = result.hits[0]
        print(f"  top-1        {top.doc_id} · {top.heading_path}")
        print(f"  dense_score  {top.dense_score:.4f} (floor {SELFTEST_MIN_DENSE_SCORE})")
        if top.doc_id != SELFTEST_DOC_ID:
            problems.append(f"top-1 doc_id is {top.doc_id!r}, expected {SELFTEST_DOC_ID!r}")
        if top.dense_score < SELFTEST_MIN_DENSE_SCORE:
            problems.append(f"top-1 dense_score {top.dense_score:.4f} < {SELFTEST_MIN_DENSE_SCORE}")

    manifest_lines = sum(1 for line in manifest_path.read_bytes().splitlines() if line.strip())
    print(f"  chunk_count  {meta.chunk_count} (manifest lines {manifest_lines})")
    print(f"  index        {meta.embed_model} · dim {meta.dim} · {meta.distance_metric} · {meta.index_version}")
    if meta.chunk_count != manifest_lines:
        problems.append(f"index_meta.chunk_count {meta.chunk_count} != manifest lines {manifest_lines}")

    if problems:
        print("\nFAIL — " + "; ".join(problems))
        return 1
    print(f"\nOK — {SELFTEST_QUERY!r} resolves to {SELFTEST_DOC_ID}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or self-test the built index.")
    parser.add_argument("--selftest", action="store_true", help="run the spec §6.5 self-test")
    parser.add_argument("--index-path", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.selftest:
        parser.error("nothing to do: pass --selftest")
    return selftest(args.index_path)


if __name__ == "__main__":
    sys.exit(main())
