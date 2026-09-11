# Phase brief: P4

## Spec sections to read first (authoritative): §6 (all: pipeline, parsing, chunking, embedding, vector store), §7.1 retrieval, §4.2 import boundaries, §12.3 (RAG/embedding variables), §15.1 (the ingest --verify-manifest CI step), §16 — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P4.

## Standing brief (roadmap §2.2, adapted: you DO commit locally, you never push)
### 2.2 The standing subagent brief (prepended to every phase dispatch)

```
Read docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md sections: <list>.
That spec is authoritative; do not redesign. Implement exactly what it specifies.
Write ONLY the files named in your deliverables list. Commit locally on the current branch using the commit pattern below; never push; never touch .env.
Every span write goes through core/trace.py. Real wall clock everywhere: there is no clock module and
no NOW_OVERRIDE; date-bearing data computes against the mock_data `as_of` snapshot.
Add tests to the existing suite under tests/; do NOT edit .github/workflows/ci.yml unless your
deliverables say so (job `test` already runs the whole suite with `pytest -q`).
Run the acceptance commands yourself and paste the real output; never claim green without it.
If the spec is ambiguous, take the simplest reading that satisfies the requirements and list the choice in your
report. STOP and report only when the ambiguity would change a user-facing contract (/chat or /health JSON,
an MCP tool schema, a dashboard route) or when a definition-of-done command cannot pass as written.
Scratch work goes in the scratchpad directory, never in the repo.
```

### 2.3 Standing acceptance criterion (from P4 onward)

## Standing acceptance criterion (from P4 onward)
### 2.3 Standing acceptance criterion (from P4 onward)

> *The expected spans were persisted, with the expected kinds and payload shapes.* — checked in every phase gate from P4 on; it is what stops a later
> subagent inventing a parallel logging path, the failure USER.4 forbids.


## Commit pattern (roadmap §2.4)
### 2.4 Commit message pattern

Every phase commits with:

```
P<n>(<scope>): <what landed>

- <one bullet per deliverable>
Gate: <the exact command(s) that proved it> — green
Reqs: <comma-separated requirement ids from docs/requirements-traceability.md>

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RnJs3hSPUc8kca4BtF5oAM
```

Scopes: `skeleton`, `core`, `corpus`, `mockdata`, `rag`, `mcpserver`, `llm`, `agent`, `web`, `dashboard`, `eval`, `deploy`, `docs`. Sub-phases use
`P9a(dashboard):` etc. Fix-ups inside a phase reuse the scope with a `fix:` prefix on the subject. Results commits use `P11(eval): published run`.


## How CI grows (roadmap §3 excerpt)
**How CI grows.** P0 lands `.github/workflows/ci.yml` with jobs `lint` and `test` in their final shape apart from three data steps whose scripts do not
exist yet: **P2** adds `python scripts/check_facts.py`, **P3** adds `python scripts/pii_check.py`, **P4** adds `python -m hrmosaic.rag.ingest
--verify-manifest`, and **P11** adds the `docker` and `deploy` jobs with the `Dockerfile` and `render.yaml`. That is four one-line edits by the phase
that creates the artifact — not a step-ownership table (spec §22 row 14). Every phase's tests reach CI with no workflow edit at all, because the `test`
job's test step is `pytest -q` over the whole suite.

---

## The phase (roadmap §4, verbatim)
### P4 — `rag/`: parsing, chunking, embedding, hybrid index · **M** (4 h) · deps P2 (+P1) · ∥ P6 · no key · commit `P4(rag): …`

**Goal.** A deterministic committed chunk manifest, a read-only sqlite-vec + FTS5 index built at Docker build time, and hybrid RRF retrieval.

**Scope.** `src/hrmosaic/rag/`: `parse/{md,html,pdf,txt}.py`, `chunk.py`, `embed.py`, `index.py`, `retrieve.py`, `ingest.py`;
`src/hrmosaic/core/corpusread.py`; `data/index/chunks.manifest.jsonl`; `tests/fixtures/corpus_mini/`.

**Deliverables.**
- Four parser paths with heading extraction (the PDF path's heading set equals `workplace-conduct.src.md`'s); the heading-aware chunker (1,400 max /
  1,100 window / 150 overlap / 120 min, `heading_path` joined with `" > "` **before** hashing, `chunker_version = "2026.1"`) and the committed
  `chunks.manifest.jsonl` — text and hashes, never vectors.
- `embed.py`, the only module that touches fastembed: `embed_passages()` / `embed_query()`, `batch_size=EMBED_BATCH_SIZE` (8) on every call,
  `threads=1` on construction, `parallel=` never, plus `_fake_embed()` for `EMBED_PROVIDER=fake`.
- The index (`vec_chunks` with `distance_metric=cosine`, `chunks`, `chunks_fts`, `documents`, `index_meta`), `open_index()`'s mismatch guard,
  `--selftest`, and `ingest.py --verify-manifest` (chunking only, never vectors) writing `ingest_report.json`.
- The retriever — dense k=20 + BM25 k=20 → RRF k₀=60 → score-fill from **stored** vectors → filter on `min_dense_score` → truncate to k — and
  `core/corpusread.py`, the read-only reader G2, the rules engine and the corpus browser share.
- **P4 adds `python -m hrmosaic.rag.ingest --verify-manifest` to `ci.yml`'s `test` job**, ahead of `pytest`, since index-backed tests need a real index.

**Definition of done.**
```bash
python -m hrmosaic.rag.ingest --verify-manifest        # rebuild byte-identical to the committed manifest (R1.4)
python -m hrmosaic.rag.index --selftest                # top-1 doc_id, dense >= SELFTEST_MIN_DENSE_SCORE, counts match the manifest
git check-ignore -q data/index/chunks.manifest.jsonl || echo "manifest is tracked"    # must print
pytest tests/unit/test_chunking.py tests/unit/test_chunking_deterministic.py tests/unit/test_ingest_report.py -q
pytest tests/unit/test_query_embed_is_asymmetric.py -q # record the branch taken and the fastembed version in CHANGELOG.md
pytest tests/unit/test_fake_embedder.py tests/unit/test_chunk_citation_fields.py tests/unit/test_corpusread_contract.py -q
pytest tests/unit/test_retrieval_filters.py tests/unit/test_min_dense_score_is_not_rrf.py -q
pytest tests/architecture/test_conventions.py -q       # sole embed call site; no `parallel=` under src/
```

