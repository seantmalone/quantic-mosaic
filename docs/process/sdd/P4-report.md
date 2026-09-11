# P4 report — `rag/`: parsing, chunking, embedding, hybrid index

**Branch** `main` · **commits** `432c3be`, `a7b33b3` · **HEAD** `a7b33b3` (from `3d5eaf4`)
**Suite** 577 passed in 7.87 s (504 before P4 → 73 new), pristine, no warnings. Nothing pushed.

---

## 1. What landed

### `src/hrmosaic/rag/parse/` — four heading-extraction paths onto one shape (§6.2, R2.1)

`parse/__init__.py` owns `Block`, `ParsedDocument`, the uniform cleaning and `assemble()`. Each format
module reduces its bytes to the same `(level, line)` stream — `0` for the title, `1`/`2` for a heading,
`None` for body — so the four paths differ **only** in heading extraction, which is the part R2.1 asks
to be tested four times.

| Module | Heading extraction |
|---|---|
| `md.py` | ATX regex, fenced-block aware; `#` title, `##`/`###` path |
| `html.py` | `beautifulsoup4` → `markdownify` (ATX) → the Markdown path; tables survive as pipe text |
| `pdf.py` | `pypdf` text; a line is a heading iff ≤ 80 chars, no terminal period, **and** in the `.src.md` heading set (which also supplies its level) |
| `txt.py` | `=` underline = title, `-` underline = level 1, an ALL-CAPS line = level 2 |

* **Heading paths exclude the title** — the P2 carry-forward. All 57 `facts.yml` `section` values and
  all 33 `rules.yml` `heading_path` values resolve to a real chunk (test below).
* **PDF cleaning**: the running footer is stripped **per page, before the pages are joined**, so the
  page-break splice never reaches a block; bare page-number lines go too. `char_start`/`char_end`
  index `ParsedDocument.text`, the cleaned text stored as `documents.full_text`, and
  `test_char_offsets_slice_the_assembled_text` asserts each block is exactly that slice.

### `src/hrmosaic/rag/chunk.py` — deterministic heading-aware chunking (§6.3, R2.2, R1.4)

Leaf sections split first; a leaf ≤ `CHUNK_MAX_CHARS` (1,400) is emitted whole and never merged; a
longer leaf becomes ordered 1,100-char windows overlapping by 150, cut on sentence boundaries, with 120
as the floor (a tail shorter than that is absorbed rather than emitted as a sliver).
`heading_path` is joined with `" > "` **before hashing and before storage**;
`chunk_id = "c_" + sha256(f"{doc_id}|{heading_path}|{char_start}|{text}")[:16]`;
`CHUNKER_VERSION = "2026.1"`. `manifest_bytes()` writes the ten keys in the specified order,
`ensure_ascii=False`, newline-terminated.

### `src/hrmosaic/rag/embed.py` — the sole fastembed call site (§6.4, R2.3)

`batch_size=EMBED_BATCH_SIZE` (8) on every call, `threads=1` on construction, the `parallel` keyword
nowhere (the literal does not even appear in a docstring — the conventions grep is over source text).
`_fake_embed()` for `EMBED_PROVIDER=fake`: sha256 blocks → 384 L2-normalised floats, deterministic
across interpreter runs. `model_name()` stamps `fake-hash-384` so the mismatch guard can reject it.
Model construction is lazy, so nothing loads ONNX at import.

### `src/hrmosaic/rag/index.py` — sqlite-vec + FTS5 (§6.5, R2.4, R2.5)

`SCHEMA` is the spec's, verbatim: `vec_chunks` (`float[384] distance_metric=cosine`), `chunks`,
`chunks_fts` (external content), `documents`, `index_meta`. Plus `build_index()`, `check_meta()` /
`open_index()` (lazy, raises `IndexModelMismatch` naming both values), the store-level query helpers
the retriever fuses (`allowed_rowids`, `dense_knn`, `bm25_top`, `stored_vectors`, `chunk_rows`) and
`--selftest`.

### `src/hrmosaic/rag/retrieve.py` — RRF with filter-then-truncate (§7.1, R3.1)

dense k=20 + BM25 k=20 → filters on **both** arms before fusion → RRF k₀=60 → fill from **stored**
vectors → drop below `min_dense_score` → truncate to k. Exactly one `embed_query` per retrieval,
whatever the strategy. `RetrievalResult` carries the pre-fusion candidate sets, `embed_ms` and
`search_ms` — everything the P5 `retrieval` span records.

### `src/hrmosaic/core/corpusread.py` — the shared read-only reader (§4.2, §6.5)

`IndexMeta` (+ derived `corpus_version` / `index_version`), `IndexModelMismatch`, `ChunkRow`,
`DocumentRow`, `get_chunk`, `list_chunks`, `list_documents`, `get_document`, `read_index_meta`. It opens
`file:…?mode=ro` and reads only the plain tables, so it needs no sqlite-vec extension; `rag/index.py`
loads that and imports the guard from here, which keeps `core/` free of any dependency on `rag/`.

### `src/hrmosaic/rag/ingest.py` + the committed manifest

`python -m hrmosaic.rag.ingest [--verify-manifest] [--corpus] [--index-path] [--manifest] [--report]`.
`--verify-manifest` runs the whole pipeline into `INDEX_PATH`, compares the manifest byte for byte,
prints a unified diff and exits 1 on a difference — and never rewrites the file. `ingest_report.json`
carries the §6.1 per-format map. `data/index/chunks.manifest.jsonl` is committed: 204 lines, 261,138
bytes, text and hashes, no vectors.

### Tests and CI

`tests/fixtures/corpus_mini/` (one tiny document per format + the PDF's source + a README with the
regeneration command), eleven new test files, one extended (`test_conventions.py`) and one extended
conftest. `ci.yml`'s `test` job gains `python -m hrmosaic.rag.ingest --verify-manifest` ahead of
`pytest`. `scripts/build_pdf.py` gained `--source`/`--target` so the fixture PDF is produced by the same
renderer with the same footer shape — verified the corpus PDF still renders **byte-identically**
(md5 `866ddc1a49e5865cfd68d00357e0c502` before and after).

---

## 2. Definition of done — real output

```
$ python -m hrmosaic.rag.ingest --verify-manifest
  format    docs  chunks    words
  md          11     153    23276
  html         1      17     2515
  pdf          1      15     2425
  txt          1      19     2624
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
exit=0

$ python -m hrmosaic.rag.index --selftest
  top-1        tax-and-location-addendum · Approved Countries
  dense_score  0.7640 (floor 0.25)
  chunk_count  204 (manifest lines 204)
  index        BAAI/bge-small-en-v1.5 · dim 384 · cosine · 2026.1+920c

OK — 'How many consecutive days abroad require Tax & Legal review?' resolves to tax-and-location-addendum
exit=0

$ git check-ignore -q data/index/chunks.manifest.jsonl || echo "manifest is tracked"
manifest is tracked

$ pytest tests/unit/test_chunking.py tests/unit/test_chunking_deterministic.py tests/unit/test_ingest_report.py -q
.........................                                                [100%]
25 passed in 0.36s

$ pytest tests/unit/test_query_embed_is_asymmetric.py -q
....                                                                     [100%]
4 passed in 0.35s

$ pytest tests/unit/test_fake_embedder.py tests/unit/test_chunk_citation_fields.py tests/unit/test_corpusread_contract.py -q
.................                                                        [100%]
17 passed in 0.28s

$ pytest tests/unit/test_retrieval_filters.py tests/unit/test_min_dense_score_is_not_rrf.py -q
............                                                             [100%]
12 passed in 0.18s

$ pytest tests/architecture/test_conventions.py -q
.....                                                                    [100%]
5 passed in 0.02s

$ pytest tests/unit/test_parsers.py tests/unit/test_gitignore_manifest_tracked.py -q
...............                                                          [100%]
15 passed in 0.18s
```

Beyond the brief's list, run to prove nothing regressed:

```
$ pytest -q
577 passed in 7.87s

$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
80 files already formatted

$ python scripts/check_facts.py | tail -2
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ python scripts/pii_check.py | tail -1
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers

$ git status --short | wc -l
       0
```

The Docker `python:3.12-slim` sqlite-vec probe was **not** run: it belongs to the CI `docker` job and
`scripts/probe_sqlite_vec.py`, both of which P11 creates, and no P4 definition-of-done line names it.
sqlite-vec 0.1.9 was probed locally instead (`vec_version()` → `v0.1.9`, KNN with a `chunk_rowid IN (…)`
filter, and reading a stored `embedding` blob back — all three are load-bearing here).

---

## 3. TDD and the defects the tests found

Honest accounting: the pipeline modules were written against the brief's definition-of-done commands
(which are executable specifications and were run continuously), and the named unit tests were written
straight after each module, before the next one. Two real defects came out of that loop, both with
red-before-green evidence:

**1. The windowing crawl (found by the build, pinned by a test).** The first full ingest died on
`sqlite3.IntegrityError: UNIQUE constraint failed: chunks.chunk_id`. Instrumenting the offending leaf
— `hr-escalation-and-case-handling` § "What Must Be Escalated", 1,860 chars whose only full stop is at
offset 278 — showed the window advancing **one character per iteration**: the cut search's lower bound
was `start + min_chars`, and after the overlap pulled `start` back the search found the *same*
boundary, so `end` never moved. It emitted 31 near-identical chunks, six of which collided on
`chunk_id` after leading-whitespace stripping. Fix: the cut must land past the previous window's end.
`test_a_leaf_whose_only_full_stop_is_early_still_advances` reproduces it synthetically, and I ran the
pre-fix algorithm against that exact text to confirm the test is genuinely red first:

```
pre-fix pieces: 35 unique starts: 30      # 5 colliding chunk ids
post-fix pieces: 5 [(0, 324), (175, 1092), (1118, 1094), (2063, 1094), (3008, 806)]
```

**2. The conventions greps caught my own docstrings.** Extending
`test_fastembed_is_called_in_one_place` with the non-vacuity assertion turned both fastembed
assertions red: `retrieve.py`'s docstring contained the literal `` `.embed(` `` and `embed.py`'s
contained `` `parallel=` ``. The greps are over source text, so a docstring is an offender exactly like
a call would be — correct behaviour, and the prose now names the keyword instead of writing it.

**3. A near-miss worth recording.** A failing assertion that mentioned `settings` rendered the whole
`Settings` object into pytest's output, **including the real `ANTHROPIC_API_KEY` from `.env`**. Nothing
was committed or pasted, and the four chunk constants are now bound to module-level names in
`tests/unit/test_chunking.py` with a comment saying why. See *Concerns*.

The remaining tests were written after their module and passed first time; where that is so I have not
claimed otherwise.

---

## 4. Tests added (73)

| File | What it holds |
|---|---|
| `test_parsers.py` (11) | all four formats parse; the Markdown fence case; HTML keeps its table; the txt convention; **the real PDF's heading set equals `workplace-conduct.src.md`'s**; the footer reaches no block; offsets slice the text; `.src.md` is not a document (11 md + 3 = 14); a mismatched `Document ID` is refused |
| `test_chunking.py` (13) | heading-path propagation; a short leaf is one chunk; **overlap** (`0 < shared ≤ 150`, and the shared text is identical on both sides); every real-corpus chunk within `[120, 1400]` and unique; the crawl regression; the tail-absorb floor; ids hash the joined path; the header block is not chunked; **the canary in exactly one chunk**; snippets are whitespace-normalised substrings |
| `test_chunking_deterministic.py` (6) | two runs byte-identical; **the committed manifest byte-identical to a rebuild**; the ten keys in order; no vectors; **every `facts.yml` section and `rules.yml` heading_path resolves to a chunk**; every fact quote survives chunking |
| `test_ingest_report.py` (6) | four formats non-zero; rows sum to `totals`; `totals` = `documents`/`chunks`/`vec_chunks`/`chunks_fts` row counts; the report lands beside the index; `--verify-manifest` fails on drift **without rewriting**, and passes on a correct manifest |
| `test_fake_embedder.py` (5) | 384-dim, unit norm; identical across **two interpreter runs** (a subprocess); batching changes nothing; asymmetric like the real one; stamped `fake-hash-384` |
| `test_query_embed_is_asymmetric.py` (4) | fastembed is the pinned 0.8.0; query ≠ passage for one string; **`QUERY_CONVENTION` matches the branch the installed library forces**; passages are unit norm |
| `test_chunk_citation_fields.py` (4) | R2.5 over stored rows *and* over every real-corpus chunk; a citation renders from a chunk alone |
| `test_corpusread_contract.py` (9) | `list_documents` browser/refusal fields; `None` for unknown ids; document order; a heading path → one chunk id, the way `rules.py` will; both derived version strings; the connection is read-only; **`open_index` refuses a fake-embedder index naming both values**; a missing index names the command that builds it |
| `test_retrieval_filters.py` (9) | (a) exactly `k`; ordering by `rrf_score`; (b) `doc_ids` and `topic` applied to **both** pre-fusion candidate sets (and the unfiltered arms provably saw excluded chunks); an empty filter; (c) **a BM25-only candidate gets a dense score from exactly one query embed**; `dense_only` has no lexical arm; hits carry the span fields; timings recorded |
| `test_min_dense_score_is_not_rrf.py` (3) | the spec's own case with chosen vectors: `dense 0.71` retained, `dense 0.10` dropped, both at `rrf ≈ 0.03`; both `rrf_score`s far below the threshold; the filter runs **before** the truncation to k |
| `test_gitignore_manifest_tracked.py` (4) | `git check-ignore` exits non-zero; the manifest is tracked; the index and report are ignored; `.gitignore` uses the `data/index/*` star form, not the slash form |

Index-backed tests run against a session-scoped `corpus_mini` ingest built with the **fake** embedder
(`tests/unit/conftest.py`), so the unit suite is offline, instant and independent of whether anyone has
run `ingest` locally. No pytest test requires `data/index/hr_index.sqlite`.

---

## 5. Ambiguities resolved (simplest reading that satisfies the spec)

1. **What `char_start`/`char_end` index.** The spec does not say. They index the **cleaned assembled
   text** (`ParsedDocument.text`, which is `documents.full_text`), not the raw file bytes — for the PDF
   the latter do not exist as text at all. A test asserts the slice equality, so citations can highlight.
2. **Empty parent sections.** `scripts/check_facts.py` emits a section for an `##` that is immediately
   followed by its first `###` (empty body); the chunker skips blocks with no text, so it emits no chunk
   there. Checked: no `facts.yml` section and no `rules.yml` heading path is one of those, so nothing
   is lost. Blocks with an **empty heading path** (a document's `Document ID`/`Topics` header) are also
   not chunked — the metadata is already in `documents`, and an empty `heading_path` could not satisfy
   R2.5.
3. **`IndexMeta` vs `open_index`.** Appendix A puts `IndexMeta` in `core/corpusread.py`; §6.5 puts the
   guard in `index.py::open_index()`. Both: `corpusread` owns `IndexMeta`, `IndexModelMismatch` and
   `read_index_meta`; `index.py` imports them, loads sqlite-vec and applies the guard. `core/` therefore
   never imports `rag/`.
4. **`min_dense_score`'s default** is `MIN_SUPPORT_SCORE` (0.26) — §12.3's table says that variable "is
   also `min_dense_score`'s default"; there is no separate env var, and none was added.
5. **FTS5 query syntax.** A user's words go through a tokeniser and are OR-ed as quoted terms; `bm25()`
   ranks. Untokenised text would make `"Tax & Legal review?"` an FTS5 syntax error rather than a search.
6. **`corpus_sha256`** is one digest over every corpus document's name and bytes in path order (the spec
   names the column, not the recipe).
7. **`estimated_pages`** follows `scripts/corpus_stats.py`: real pages for the PDF, words ÷ 500 elsewhere.
8. **`--verify-manifest` builds the index too.** §6.5 says it "runs the full pipeline into `INDEX_PATH`";
   the comparison alone is chunking-only. That is also why the brief puts it ahead of `pytest` in CI.
9. **Where the `retrieval` span is written.** Nowhere in P4: `rag/` writes no spans at all. §7.1's span
   is emitted by the MCP tool at P5 from the fields `RetrievalResult` returns (`strategy`, `k`, the
   ranked hits with `dense_score`/`bm25_rank`/`rrf_score`/`rank`/`snippet`, `embed_ms`, `search_ms`).
   The standing acceptance criterion is therefore vacuous for this phase by design, and
   `test_only_trace_module_writes_spans` stays green.
10. **Commit attribution.** The session's standing instruction overrides the roadmap's
    `Co-Authored-By: Claude Fable 5.1` line, so both commits carry
    `Co-Authored-By: Claude Opus 5 (1M context)` and the `Claude-Session:` line.

---

## 6. Self-review findings (all fixed before or in the commits)

* Removed a `CREATE INDEX chunks_doc_id` I had added to the schema: the spec's schema is the contract,
  204 rows do not need it, and it was the only invented line in the file.
* Removed `__import__("json")` from `retrieve.py` (a leftover) and gave `hits` a real annotation.
* Rewrote the `doc_ids` filter assertion, which was close to tautological (it compared candidates with
  the hits of a `k=50` search over the same filter); it now checks candidate ids against the index's own
  `doc_id` column and asserts the *unfiltered* arms saw excluded chunks, which is what "before fusion"
  means.
* `--report` was not exposed on the CLI, so a test invoking `main()` would have written
  `data/index/ingest_report.json` inside the repo. Added the flag; tests write to `tmp_path`.
* `_FTS_TOKEN` was `[A-Za-z0-9]+`, which shattered an accented query word into one- and two-character
  junk tokens that get OR-ed into the lexical arm. Now `[^\W_]+` (commit `a7b33b3`).
* Bound the chunk constants to module names in `test_chunking.py` so a failure cannot render the
  `Settings` object (see below).
* Checked for stray files before each commit (`git status --short`); staged by explicit path only;
  `.env` was never read, printed or staged, and the working tree is clean.

---

## 7. Concerns for the reviewer / later phases

1. **`Settings` leaks credentials into pytest failure output.** Any failing assertion whose expression
   mentions `settings` prints the full `Settings` repr, which includes `anthropic_api_key`. That happened
   once locally during this phase. CI runs with `LLM_PROVIDER=stub` and no key, so CI logs are safe
   today, but P10/P11 will run the suite on machines that have keys. The durable fix is `SecretStr` on
   the four `*_api_key` / `*_token` fields in `settings.py` (plus their adapter call sites), which is a
   `core/` change and outside P4's deliverables. Flagging it rather than doing it.
2. **204 chunks, against the spec's `~240–320` estimate (§6.3).** The four constants are exactly as
   specified and the corpus is the size §6.1 predicted (30,840 words vs 31,500). The corpus's leaf
   sections simply average ~940 characters, so most are emitted whole and only 24 chunks come from
   windowing. Nothing asserts the band, and `test_ingest_report.py` deliberately asserts no literals —
   but if a reviewer wants to land inside it, the lever is `CHUNK_MAX_CHARS`, and moving it bumps
   `CHUNKER_VERSION` and rewrites every `chunk_id`. I did not change a specified constant on my own
   judgement.
3. **No pytest test opens the real `data/index/hr_index.sqlite`.** The brief motivates the CI ingest step
   with "index-backed tests need a real index"; P4's index-backed tests use the mini fake-embedder index
   instead, so they stay hermetic and fast. The CI step still earns its place (it is R1.4's gate) and
   P5's `search_policy_documents` tests will be the first real consumers of the file it leaves behind.
4. **`retrieve()` opens and closes the index per call when no connection is passed.** Fine for a CLI and
   for tests; P5 should hold one connection (via `index.open_index()` or `corpusread.connect()`) for the
   process and thread it through, and P8's `/ready` warm-up is where the guard should first be caught.
5. **`strategy` is not validated inside `retrieve()`** — anything other than `"dense_only"` behaves as
   hybrid. The enum belongs at the MCP tool boundary (P5), where `_meta.mosaic/retrieval` and the model's
   own argument are validated together.
6. **The self-test's top-1 is `Approved Countries`, not `Duration Thresholds > Stays Exceeding 30 Days`**
   (which is rank 2 at `dense_score` 0.820). §6.5 asserts the `doc_id` only, and it holds comfortably;
   worth knowing at P10 when `MIN_EVIDENCE_SCORE` is calibrated, since the top five for that query score
   0.751–0.820, well above the 0.32 default.
7. **`scripts/download_model.py` constructs `TextEmbedding` without `threads=1`** (P0 code). It only warms
   the cache and never embeds, so the conventions greps are satisfied, but it is the one other place in
   the tree that builds the model.

---

# P4 fix round 1 — the truncation-order test could not fail

**Commit** `8f761d8` (from `a7b33b3`) · **Suite** 578 passed (577 → 578; one test added), pristine, no warnings.
Nothing pushed. One file changed: `tests/unit/test_min_dense_score_is_not_rrf.py`.

## 1. The finding

> `test_the_threshold_is_applied_before_the_truncation_to_k` cannot fail on the implementation it
> names. Its fixture has exactly 2 candidates and it calls `retrieve(k=2)`, so filter-then-truncate
> and truncate-then-filter produce identical output.

Correct, and the diagnosis is exact. With `k` equal to the candidate count the cut is a no-op in
either order: both spellings yield `[high-doc]`, `len(hits) == 1`, two `dense_candidates`. The
production cut in `retrieve.py:134-138` is right — filter, sort, slice — but nothing was guarding it,
and P5 (`_meta.k_override` → the model's `k` → `RETRIEVAL_K`) and P10 (`MIN_SUPPORT_SCORE`
calibration) both thread these two numbers through this exact path.

## 2. What changed

**The two cases are now separate fixtures**, because the two halves of the §7.1 cut need different
shapes and conflating them is what produced the vacuous test:

* `spec_case_index` — the spec's own sentence, unchanged in substance: two chunks at `dense 0.71` and
  `dense 0.10`, both at `rrf ≈ 0.03`. The two tests that assert *which score the threshold reads*
  keep running against exactly the case §7.1 words.
* `ordering_case_index` — **four** chunks, so `k = 2` actually truncates, with the lexical arm
  arranged so that **a below-threshold candidate leads the fused ranking**. That is the only shape in
  which the two cut orders disagree.

The dense arm is monkeypatched (chosen vectors, as before), so a document's *text* now only reaches
BM25 — that is the lever the arrangement uses. `ORDERING_QUERY` is `"encrypted laptop travel"`: all
three words appear in `below-floor-doc`, only `travel` appears in `lexical-doc`, and neither of the
other two documents matches, so the lexical arm returns those two in that order and nothing else.
Fused against the dense ranks the chosen scores force:

| doc | dense | dense rank | bm25 rank | rrf_score |
|---|---|---|---|---|
| `below-floor-doc` | 0.10 | 4 | 1 | 1/64 + 1/61 = **0.0320184** ← fails the threshold |
| `lexical-doc` | 0.70 | 3 | 2 | 1/63 + 1/62 = **0.0320020** ← passes |
| `high-doc` | 0.90 | 1 | — | 1/61 = 0.0163934 |
| `mid-doc` | 0.80 | 2 | — | 1/62 = 0.0161290 |

At `k = 2`: filter-then-truncate fills both slots with passing chunks (`lexical-doc`, `high-doc`);
truncate-then-filter spends a slot on `below-floor-doc` and returns one hit.

Two tests carry that:

* `test_a_below_threshold_candidate_can_outrank_a_passing_one_on_rrf` (new) states the premise and
  pins the arrangement it rests on — both arms' candidate lists are asserted by `doc_id`, so if FTS5
  ever ranked these sentences differently the test would say so instead of silently going vacuous
  again.
* `test_the_threshold_is_applied_before_the_truncation_to_k` (rewritten) asserts
  `len(hits) == 2`, the order `["lexical-doc", "high-doc"]`, that all four candidates were in the
  pool the cut ran over, and that every hit clears the threshold.

The docstring at the top of the file now says why there are two fixtures, so the next person to
extend this file does not collapse them back.

## 3. Red before green — the mutation check

Both cut orders were installed by recompiling `retrieve()`'s source with the cut lines swapped and
rebinding `rag.retrieve.retrieve`, loaded as a pytest plugin (scratchpad, never in the repo) — the
reviewer's method, extended to a second mutant.

**Mutant A — sort, truncate to `k`, then filter the survivors** (the semantic inverse of §7.1):

```
$ PYTHONPATH=$SCRATCH pytest -p mutant_sorted tests/unit/test_retrieval_filters.py tests/unit/test_min_dense_score_is_not_rrf.py -q
............F                                                            [100%]
>       assert len(result.hits) == 2, "truncate-then-filter would have returned 1"
E       AssertionError: truncate-then-filter would have returned 1
E       assert 1 == 2
1 failed, 12 passed in 0.23s
```

**Mutant B — the reviewer's literal one** (`kept = [e for e in scored[:k] if e[2] >= min_dense_score]`,
truncating in candidate order before the sort), which the old test passed:

```
$ PYTHONPATH=$SCRATCH pytest -p mutant_unsorted tests/unit/test_retrieval_filters.py tests/unit/test_min_dense_score_is_not_rrf.py -q
>       assert _doc_ids(result) == ["lexical-doc", "high-doc"]
E       AssertionError: assert ['high-doc', 'mid-doc'] == ['lexical-doc', 'high-doc']
E         At index 0 diff: 'high-doc' != 'lexical-doc'
1 failed, 12 passed in 0.22s
```

Mutant B is worth keeping in mind: it truncates *before* sorting, so it drops a BM25-boosted
candidate that the fusion had promoted. The `len(hits)` assertion alone does not see it — the
`doc_id` ordering assertion is what kills it. Both mutants now die on the same test; the real
implementation passes it.

## 4. Definition of done — real output, re-run in full

```
$ python -m hrmosaic.rag.ingest --verify-manifest
  format    docs  chunks    words
  md          11     153    23276
  html         1      17     2515
  pdf          1      15     2425
  txt          1      19     2624
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
exit=0

$ python -m hrmosaic.rag.index --selftest
  top-1        tax-and-location-addendum · Approved Countries
  dense_score  0.7640 (floor 0.25)
  chunk_count  204 (manifest lines 204)
  index        BAAI/bge-small-en-v1.5 · dim 384 · cosine · 2026.1+920c

OK — 'How many consecutive days abroad require Tax & Legal review?' resolves to tax-and-location-addendum
exit=0

$ git check-ignore -q data/index/chunks.manifest.jsonl || echo "manifest is tracked"
manifest is tracked

$ pytest tests/unit/test_chunking.py tests/unit/test_chunking_deterministic.py tests/unit/test_ingest_report.py -q
.........................                                                [100%]
25 passed in 0.44s

$ pytest tests/unit/test_query_embed_is_asymmetric.py -q
....                                                                     [100%]
4 passed in 0.44s

$ pytest tests/unit/test_fake_embedder.py tests/unit/test_chunk_citation_fields.py tests/unit/test_corpusread_contract.py -q
.................                                                        [100%]
17 passed in 0.37s

$ pytest tests/unit/test_retrieval_filters.py tests/unit/test_min_dense_score_is_not_rrf.py -q
.............                                                            [100%]
13 passed in 0.27s

$ pytest tests/architecture/test_conventions.py -q
.....                                                                    [100%]
5 passed in 0.02s
```

Beyond the brief's list:

```
$ pytest -q
578 passed in 8.77s

$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
80 files already formatted

$ git status --short
 M tests/unit/test_min_dense_score_is_not_rrf.py
```

## 5. Notes

* No production code changed. The finding says so explicitly — `retrieve.py` was already correct —
  and the fix is entirely in what the suite is able to detect.
* The §4 test table's row for this file now reads **4** tests, not 3: the spec's own retained/dropped
  case (2), the new outranking premise (1), and the rewritten ordering test (1). Suite total 578.
* Nothing else from §7 *Concerns* was touched; those remain for the phases that own them.
