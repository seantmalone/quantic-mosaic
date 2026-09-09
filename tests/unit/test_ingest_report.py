"""`ingest_report.json` — R2.1's per-format evidence (spec §6.1).

Those numbers are a **measurement, not a fixture**: nothing here asserts a literal count. It asserts
that four formats are present with non-zero counts, that the per-format rows sum to `totals`, and that
`totals` equals the `documents` and `chunks` row counts of the index that was built alongside it.
"""

from __future__ import annotations

import json
from pathlib import Path

from hrmosaic.rag import ingest as ingest_module
from hrmosaic.rag.ingest import FORMATS

CORPUS_MINI = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "corpus_mini"


def test_the_report_covers_four_formats_with_non_zero_counts(mini_ingest):
    assert set(FORMATS) == {"md", "html", "pdf", "txt"}
    for source_format in FORMATS:
        row = mini_ingest.report[source_format]
        assert row["doc_count"] > 0, source_format
        assert row["chunk_count"] > 0, source_format
        assert row["word_count"] > 0, source_format


def test_the_rows_sum_to_totals(mini_ingest):
    totals = mini_ingest.report["totals"]
    for field in ("doc_count", "chunk_count", "word_count"):
        assert totals[field] == sum(mini_ingest.report[name][field] for name in FORMATS)


def test_totals_match_the_table_row_counts(mini_index, mini_ingest):
    totals = mini_ingest.report["totals"]
    documents = mini_index.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    chunks = mini_index.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    vectors = mini_index.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0]
    fts = mini_index.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    assert totals["doc_count"] == documents
    assert totals["chunk_count"] == chunks == vectors == fts


def test_the_report_is_written_next_to_the_index(mini_ingest):
    report_path = mini_ingest.index_path.parent / "ingest_report.json"
    assert json.loads(report_path.read_text(encoding="utf-8")) == mini_ingest.report


def _verify(tmp_path: Path, manifest: Path) -> int:
    return ingest_module.main(
        [
            "--verify-manifest",
            "--corpus",
            str(CORPUS_MINI),
            "--manifest",
            str(manifest),
            "--index-path",
            str(tmp_path / "mini.sqlite"),
            "--report",
            str(tmp_path / "ingest_report.json"),
        ]
    )


def test_verify_manifest_fails_on_drift_and_never_rewrites_the_manifest(tmp_path, fake_embedder):
    """`--verify-manifest` compares; it must not silently repair a manifest that has drifted."""
    manifest = tmp_path / "chunks.manifest.jsonl"
    manifest.write_bytes(b"stale\n")
    assert _verify(tmp_path, manifest) == 1
    assert manifest.read_bytes() == b"stale\n"


def test_verify_manifest_passes_on_the_manifest_the_chunker_produces(tmp_path, mini_ingest, fake_embedder):
    manifest = tmp_path / "chunks.manifest.jsonl"
    manifest.write_bytes(mini_ingest.manifest)
    assert _verify(tmp_path, manifest) == 0
