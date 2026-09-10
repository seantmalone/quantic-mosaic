"""G4 over **every chunk in the committed manifest** (spec §7.4).

A false positive here is as dangerous as a false negative and much harder to notice: a quarantined
chunk cannot be cited, so G2 strips the citation, the block is dropped, and G1 may then refuse — on
camera, in the middle of demo task 1, which has to cite four documents.

The three assertions §7.4 names, and deliberately **not** an exact count — the corpus is edited by
hand and the chunker is free to split the canary's section differently:

* every quarantined chunk has `doc_id == "security-acceptable-use"`;
* at least one chunk is quarantined, so the canary is reachable and the rule is not vacuous;
* no chunk from any other document is quarantined.

It reads `data/index/chunks.manifest.jsonl`, the committed artifact, rather than the gitignored
index: the manifest carries the full chunk text and is the thing a corpus edit moves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hrmosaic.agent.guardrails import g4

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "data" / "index" / "chunks.manifest.jsonl"

CANARY_DOC_ID = "security-acceptable-use"


def manifest_chunks() -> list[dict]:
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


CHUNKS = manifest_chunks()
QUARANTINED = [chunk for chunk in CHUNKS if g4.scan(chunk["text"]) is not None]


def test_the_manifest_is_the_whole_corpus():
    assert len(CHUNKS) > 100, "the scan is only meaningful over the real corpus"
    assert len({chunk["doc_id"] for chunk in CHUNKS}) == 14


def test_at_least_one_chunk_is_quarantined():
    """Without this the suite would pass with a regex that matches nothing at all."""
    assert QUARANTINED, "the canary must be reachable"


def test_every_quarantined_chunk_is_the_canary_document():
    assert {chunk["doc_id"] for chunk in QUARANTINED} == {CANARY_DOC_ID}


@pytest.mark.parametrize("doc_id", sorted({chunk["doc_id"] for chunk in CHUNKS} - {CANARY_DOC_ID}))
def test_no_other_document_has_a_quarantined_chunk(doc_id):
    offenders = [
        (chunk["chunk_id"], chunk["heading_path"], g4.scan(chunk["text"]))
        for chunk in CHUNKS
        if chunk["doc_id"] == doc_id and g4.scan(chunk["text"]) is not None
    ]
    assert offenders == []


def test_the_quarantined_chunk_sits_under_the_labelled_lure_section():
    """The canary is corpus content inside a section that says what it is (§5.3)."""
    assert all("PHISHING LURE" in chunk["heading_path"].upper() for chunk in QUARANTINED)
