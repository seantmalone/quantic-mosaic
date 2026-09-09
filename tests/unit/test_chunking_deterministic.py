"""R1.4's real assertion: the committed manifest is what the chunker produces (spec §6.3).

The chunker is a pure function of the corpus bytes plus four constants, so a re-run must reproduce
`data/index/chunks.manifest.jsonl` **byte for byte**. This is the test behind the CI step
`python -m hrmosaic.rag.ingest --verify-manifest`, and it needs no index and no embedder.

It also pins the two properties P5 depends on: the manifest's key order, and that every
`corpus/facts.yml` `section` and every `corpus/rules.yml` `heading_path` resolves to at least one
chunk — otherwise `mcpserver/rules.py` would resolve a `(doc_id, heading_path)` pair to nothing and
G2 would silently strip the evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from hrmosaic.rag.chunk import MANIFEST_KEYS, chunk_corpus, manifest_bytes
from hrmosaic.rag.ingest import MANIFEST_PATH
from hrmosaic.rag.parse import parse_corpus

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "corpus"
COMMITTED_MANIFEST = REPO_ROOT / MANIFEST_PATH


@pytest.fixture(scope="module")
def rebuilt() -> bytes:
    return manifest_bytes(chunk_corpus(parse_corpus(CORPUS)))


def test_two_runs_of_the_chunker_are_byte_identical(rebuilt):
    assert manifest_bytes(chunk_corpus(parse_corpus(CORPUS))) == rebuilt


def test_the_committed_manifest_is_byte_identical_to_a_rebuild(rebuilt):
    assert COMMITTED_MANIFEST.read_bytes() == rebuilt, (
        "the corpus moved without the manifest: run `python -m hrmosaic.rag.ingest`"
    )


def test_every_manifest_row_carries_exactly_the_specified_keys_in_order():
    rows = [json.loads(line) for line in COMMITTED_MANIFEST.read_text(encoding="utf-8").splitlines()]
    assert rows
    for row in rows:
        assert tuple(row) == MANIFEST_KEYS


def test_the_manifest_carries_no_vectors():
    text = COMMITTED_MANIFEST.read_text(encoding="utf-8")
    assert "embedding" not in text
    assert "vector" not in text


def test_every_facts_and_rules_heading_path_resolves_to_a_chunk():
    """P2's heading-path convention and P4's chunker have to agree, or P5's rules engine resolves
    nothing. `scripts/check_facts.py` proves the paths are real headings; this proves they are real
    *chunks*."""
    chunks = chunk_corpus(parse_corpus(CORPUS))
    paths = {(chunk.doc_id, chunk.heading_path) for chunk in chunks}

    facts = yaml.safe_load((CORPUS / "facts.yml").read_text(encoding="utf-8"))["facts"]
    unresolved = [f"facts.yml:{key}" for key, fact in facts.items() if (fact["doc_id"], fact["section"]) not in paths]

    scenarios = yaml.safe_load((CORPUS / "rules.yml").read_text(encoding="utf-8"))["scenarios"]
    unresolved += [
        f"rules.yml:{name}.{requirement['id']}"
        for name, scenario in scenarios.items()
        for requirement in scenario["requirements"]
        if (requirement["doc_id"], requirement["heading_path"]) not in paths
    ]

    assert unresolved == []
    assert len(facts) >= 40


def test_every_fact_quote_survives_chunking():
    """A citation is only useful if the quoted sentence is in the chunk the citation names."""
    chunks = chunk_corpus(parse_corpus(CORPUS))
    by_section: dict[tuple[str, str], list[str]] = {}
    for chunk in chunks:
        by_section.setdefault((chunk.doc_id, chunk.heading_path), []).append(" ".join(chunk.text.split()))
    facts = yaml.safe_load((CORPUS / "facts.yml").read_text(encoding="utf-8"))["facts"]
    missing = [
        key
        for key, fact in facts.items()
        if not any(
            " ".join(fact["quote"].split()) in text for text in by_section.get((fact["doc_id"], fact["section"]), [])
        )
    ]
    assert missing == []
