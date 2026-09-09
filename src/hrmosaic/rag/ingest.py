"""The build-time ingestion pipeline (spec §6.1, R1.4, R2.1).

    corpus/*.{md,html,pdf,txt}
      → parse/{md,html,pdf,txt}.py  → Document{doc_id, doc_title, source_format, blocks[…]}
      → chunk.py                    → Chunk[]            (deterministic, §6.3)
      → data/index/chunks.manifest.jsonl                 ★ COMMITTED (text + hashes, NO vectors)
      → embed.py (fastembed, batch_size=8)               → 384-dim float32
      → index.py                    → data/index/hr_index.sqlite

    python -m hrmosaic.rag.ingest                    # build the index and rewrite the manifest
    python -m hrmosaic.rag.ingest --verify-manifest  # build the index and PROVE the manifest is unchanged

This runs at Docker build time and on the CI runner, **never at boot**: indexing takes seconds that
would dominate a free-tier cold start, where booting only opens the finished file.

`--verify-manifest` compares the manifest it just produced with the committed one **byte for byte** and
prints a unified diff before exiting non-zero. The comparison is on **chunking only, never vectors**, so
an embedder change cannot fail it and `EMBED_PROVIDER=fake` still produces a valid manifest. That is
R1.4's real assertion, and it is a CI step ahead of `pytest` so index-backed tests find a real index.

Both runs write `data/index/ingest_report.json` — the per-format breakdown R2.1 asks for. Those numbers
are a **measurement**: `tests/unit/test_ingest_report.py` asserts four formats with non-zero counts, that
the rows sum to `totals` and that `totals` matches the table row counts, never the literals.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from hrmosaic.rag import index
from hrmosaic.rag.chunk import Chunk, chunk_corpus, manifest_bytes
from hrmosaic.rag.parse import ParsedDocument, corpus_paths, parse_corpus
from hrmosaic.settings import settings

#: Paths are relative to the repository root, which is the working directory of every documented
#: command (`make ingest`, the CI step, the Dockerfile's `WORKDIR /app`) — the same convention
#: `settings.index_path` follows.
CORPUS_DIR = Path("corpus")
MANIFEST_PATH = Path("data/index/chunks.manifest.jsonl")
REPORT_PATH = Path("data/index/ingest_report.json")

FORMATS = ("md", "html", "pdf", "txt")


@dataclass(frozen=True)
class IngestResult:
    """What one ingest produced."""

    documents: list[ParsedDocument]
    chunks: list[Chunk]
    manifest: bytes
    report: dict[str, dict[str, int]]
    index_path: Path | None


def corpus_sha256(corpus_dir: Path = CORPUS_DIR) -> str:
    """One digest over every corpus document's bytes, in path order."""
    digest = hashlib.sha256()
    for path in corpus_paths(corpus_dir):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def format_counts(documents: list[ParsedDocument], chunks: list[Chunk]) -> dict[str, dict[str, int]]:
    """The §6.1 per-format map, plus `totals` — a measurement, never a fixture."""
    report: dict[str, dict[str, int]] = {}
    for source_format in FORMATS:
        subset = [document for document in documents if document.source_format == source_format]
        report[source_format] = {
            "doc_count": len(subset),
            "chunk_count": sum(1 for chunk in chunks if chunk.source_format == source_format),
            "word_count": sum(document.word_count for document in subset),
        }
    report["totals"] = {
        "doc_count": len(documents),
        "chunk_count": len(chunks),
        "word_count": sum(document.word_count for document in documents),
    }
    return report


def ingest(
    corpus_dir: Path = CORPUS_DIR,
    *,
    index_path: Path | None = None,
    manifest_path: Path = MANIFEST_PATH,
    report_path: Path | None = REPORT_PATH,
    write_manifest: bool = True,
    build: bool = True,
) -> IngestResult:
    """Run the pipeline. With `write_manifest=False` the committed manifest is left untouched."""
    index_path = Path(index_path or settings.index_path)
    documents = parse_corpus(corpus_dir)
    chunks = chunk_corpus(documents)
    manifest = manifest_bytes(chunks)
    report = format_counts(documents, chunks)

    if write_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(manifest)
    if build:
        index.build_index(
            chunks,
            documents,
            index_path=index_path,
            corpus_sha256=corpus_sha256(corpus_dir),
            manifest_sha256=hashlib.sha256(manifest).hexdigest(),
            format_counts=report,
        )
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return IngestResult(
        documents=documents,
        chunks=chunks,
        manifest=manifest,
        report=report,
        index_path=index_path if build else None,
    )


def manifest_diff(committed: bytes, rebuilt: bytes, manifest_path: Path) -> str:
    """A unified diff between the committed manifest and the one just produced."""
    return "".join(
        difflib.unified_diff(
            committed.decode("utf-8").splitlines(keepends=True),
            rebuilt.decode("utf-8").splitlines(keepends=True),
            fromfile=f"{manifest_path} (committed)",
            tofile=f"{manifest_path} (rebuilt)",
            n=1,
        )
    )


def _print_report(report: dict[str, dict[str, int]]) -> None:
    print(f"  {'format':<8}{'docs':>6}{'chunks':>8}{'words':>9}")
    for key in (*FORMATS, "totals"):
        row = report[key]
        print(f"  {key:<8}{row['doc_count']:>6}{row['chunk_count']:>8}{row['word_count']:>9}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the chunk manifest and the retrieval index.")
    parser.add_argument(
        "--verify-manifest",
        action="store_true",
        help="rebuild and compare with the committed manifest byte for byte; never rewrite it",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_DIR)
    parser.add_argument("--index-path", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    result = ingest(
        args.corpus,
        index_path=args.index_path,
        manifest_path=args.manifest,
        report_path=args.report,
        write_manifest=not args.verify_manifest,
    )
    _print_report(result.report)
    print(f"  index    {result.index_path}")

    if args.verify_manifest:
        committed = args.manifest.read_bytes() if args.manifest.exists() else b""
        if committed != result.manifest:
            print(f"\nFAIL — {args.manifest} is not what the chunker produces:\n")
            print(manifest_diff(committed, result.manifest, args.manifest) or "  (only trailing bytes differ)")
            return 1
        print(f"\nOK — {args.manifest} is byte-identical to the rebuild ({len(result.chunks)} chunks)")
    else:
        print(f"\nOK — wrote {args.manifest} ({len(result.chunks)} chunks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
