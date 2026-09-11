# Phase brief: P3

## Spec sections to read first (authoritative): §5.4 mock structured data and the as_of snapshot convention, §8.4 the nine tools (what each reads from the data), §13.1 (item anchors E1002/E1007/E1042/E1108), §18 demo personas — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P3.

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
### P3 — Synthetic mock data · **S** (2 h) · deps P0 · ∥ P2 · no key · commit `P3(mockdata): …`

**Goal.** Six committed, immutable, obviously-synthetic datasets carrying the `as_of: 2026-09-01` snapshot that stabilises every date-bearing answer.

**Scope.** `scripts/{gen_mock_data,gen_mock_schemas,pii_check}.py`, `mock_data/*.json`, `mock_data/schemas/*.schema.json`, `mock_data/README.md`,
`tests/unit/{test_mock_schemas,test_pto_balance_arithmetic,test_mock_anchor_ids}.py`.

**Deliverables.**
- The six datasets of §5.4, each with the `_synthetic` / `_notice` / `_generator` / `as_of` banner, produced by a byte-idempotent `seed=1729` generator.
- 24 non-contiguous ids from `E1001`–`E1199` with the four anchors `E1002`, `E1007`, `E1042` (the demo persona, hired 2022-11-13, 45 months tenured at
  the snapshot, **13.5 days remaining** at 1.50 d/mo) and `E1108` (hired 2026-08-15, `waiting_period_ends` 2026-11-13 — still waiting at the snapshot).
- Synthetic conventions: `@mosaicrobotics.example` addresses, `+1-555-01xx` phones, **no SSN field in any schema**, no dates of birth, no addresses.
  `pii_check.py` fails the build on any hit; **P3 adds it to `ci.yml`'s `test` job.**
- `mock_data/README.md` — the SYNTHETIC DATA banner and the `as_of` convention: what it means, why every date-bearing tool reports it, and why nothing
  computes against "today".

**Definition of done.**
```bash
python scripts/gen_mock_data.py && git diff --exit-code mock_data/          # byte-idempotent regeneration
python scripts/gen_mock_schemas.py && python scripts/pii_check.py
pytest tests/unit/test_mock_schemas.py tests/unit/test_mock_anchor_ids.py -q     # schemas valid; anchors present; E1108 still waiting
pytest tests/unit/test_pto_balance_arithmetic.py -q      # the identity holds for all 24 at the snapshot; E1042 -> 13.5
```
That last file also checks each accrual rate against `corpus/facts.yml`, so the **main session runs it once P2 has landed**; nothing else in P3 touches
P2's files.

