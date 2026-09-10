"""The fourth, **zero-LLM** comparison of spec §13.9: chunk size 1,100 vs 700 vs 1,600.

Each variant is ingested into a **temporary directory** — never `data/index/`, so the committed
`chunks.manifest.jsonl` is untouched — and scored on `DocRecall` alone by running retrieval, and
nothing else, for every `evaluation/dataset.yaml` question that names `expected_docs`. No model is
called: this is the cheapest arm in the study and it is the one that says whether the chunk window
was worth choosing.

Output: `evaluation/results/chunk_size_comparison.json`, which page 11's compare tab renders beside
the three-variant bars. `core/archive.py` skips the file as a non-run object.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # `python scripts/<name>.py` puts this file's own directory on sys.path, not the repository
    # root, so the `evaluation` package (which is not installed) would not import.
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.deterministic import document_recall, mean  # noqa: E402
from evaluation.schema import RESULTS_DIR, load_dataset  # noqa: E402
from hrmosaic.rag import ingest as ingest_module  # noqa: E402
from hrmosaic.rag import retrieve as retrieve_module  # noqa: E402
from hrmosaic.rag.index import open_index  # noqa: E402
from hrmosaic.settings import settings  # noqa: E402

logger = logging.getLogger(__name__)

#: The three windows §13.9 names. 1,100 is the shipped `CHUNK_WINDOW_CHARS`.
CHUNK_WINDOWS: tuple[int, ...] = (700, 1100, 1600)

CORPUS_DIR = REPO_ROOT / "corpus"


def sweep(*, windows: Sequence[int] = CHUNK_WINDOWS, k: int | None = None) -> dict[str, Any]:
    """Build each variant index in a temp directory and score `DocRecall` over the dataset."""
    dataset = load_dataset()
    questions = [item for item in dataset.items if item.expected_docs]
    k = k or settings.retrieval_k
    original_window = settings.chunk_window_chars
    original_max = settings.chunk_max_chars
    variants: list[dict[str, Any]] = []

    try:
        for window in windows:
            settings.chunk_window_chars = window
            # `CHUNK_MAX_CHARS` is the hard ceiling a window must fit under (§6.3); it moves with
            # the window so a 1,600-character window is not silently truncated to the 1,400 default.
            settings.chunk_max_chars = max(original_max, window + 300)
            with tempfile.TemporaryDirectory(prefix=f"chunk-sweep-{window}-") as directory:
                started = time.perf_counter()
                result = ingest_module.ingest(
                    CORPUS_DIR,
                    index_path=Path(directory) / "sweep.sqlite",
                    manifest_path=Path(directory) / "chunks.manifest.jsonl",
                    report_path=None,
                    write_manifest=False,
                )
                connection = open_index(result.index_path, check=False)
                try:
                    recalls = []
                    for item in questions:
                        hits = retrieve_module.retrieve(item.question, k=k, connection=connection)
                        recall = document_recall({hit.doc_id for hit in hits.hits}, item.expected_docs)
                        if recall is not None:
                            recalls.append(recall)
                finally:
                    connection.close()
                variants.append(
                    {
                        "chunk_chars": window,
                        "doc_recall_mean": round(mean(recalls) or 0.0, 4),
                        "n_questions": len(recalls),
                        "n_chunks": len(result.chunks),
                        "build_s": round(time.perf_counter() - started, 1),
                    }
                )
                logger.info(
                    "window %s: doc_recall %.4f over %d chunks",
                    window,
                    variants[-1]["doc_recall_mean"],
                    len(result.chunks),
                )
    finally:
        settings.chunk_window_chars = original_window
        settings.chunk_max_chars = original_max

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": (
            "Zero-LLM sweep (§13.9): retrieval only, scored on DocRecall against every dataset item "
            f"that names expected_docs (n={len(questions)}), k={k}. Each index was built into a "
            "temporary directory; data/index/chunks.manifest.jsonl is untouched."
        ),
        "k": k,
        "dataset_sha": dataset.sha256,
        "variants": variants,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Zero-LLM chunk-size sweep (§13.9).")
    parser.add_argument("--k", type=int, default=None)
    parser.add_argument("--out", default=str(RESULTS_DIR / "chunk_size_comparison.json"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    document = sweep(k=args.k)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(document["variants"], indent=1))  # noqa: T201 — CLI
    logger.info("wrote %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
