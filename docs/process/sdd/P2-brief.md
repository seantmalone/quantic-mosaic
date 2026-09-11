# Phase brief: P2

## Spec sections to read first (authoritative): §5.1 company persona, §5.2 facts index, §5.3 document list, §6.2 parsing (what the four formats must satisfy), §7.4 G4 (the injection canary), §13.1 dataset (which facts the gold answers cite), §18 (facts the demo tasks rely on) — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P2.

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
### P2 — Policy corpus · **M** (4 h) · deps P0 · ∥ P3 · no key · commit `P2(corpus): …`

**Goal.** 14 hand-authored policy documents in four formats, plus the ~40-fact index every gold answer and compliance rule cites.
**Scope.** `corpus/` (11 `.md`, 1 `.html`, 1 `.pdf` + its `.src.md`, 1 `.txt`), `corpus/{facts.yml,rules.yml,README.md}`,
`scripts/{build_pdf,corpus_stats,check_facts}.py`, `tests/unit/{test_facts_quotes,test_corpus_stats,test_corpus_topics,test_corpus_canary}.py`.

**Deliverables.**
- The 14 documents of §5.3, each with the standard header and ≥ 6 concrete checkable statements — a review criterion, not a build gate. No generator.
- `facts.yml` — ~40 entries `{id, value, unit, doc_id, section, quote}` with the quote reproduced **verbatim**; `rules.yml` — the requirements behind
  tool 4's seven scenarios, each naming a `fact_key`, `doc_id` and `heading_path`; `README.md` — the topic → document map, outlines, format rationale.
- The **injection canary** inside `security-acceptable-use.txt`, in a labelled "example of a phishing lure" section short enough to be one chunk.
- `check_facts.py` — one check: every quote verbatim, every `section` a real heading path, every `rules.yml` `fact_key` resolvable. Any phase may run
  it; **P2 adds it to `ci.yml`'s `test` job.**

**Definition of done.**
```bash
python scripts/check_facts.py                          # quotes verbatim, sections real, every fact_key resolves
python scripts/corpus_stats.py                         # 14 files · ~63 pages · md/html/pdf/txt
python scripts/build_pdf.py && test -s corpus/workplace-conduct.pdf         # generated once from .src.md, then committed
pytest tests/unit/test_facts_quotes.py tests/unit/test_corpus_stats.py -q   # band: 5<=files<=20, 30<=pages<=120
pytest tests/unit/test_corpus_topics.py tests/unit/test_corpus_canary.py -q # all 10 PD.2 topics mapped; canary < CHUNK_MAX_CHARS
```

