# Phase brief: P1

## Spec sections to read first (authoritative): §4 (layout, 4.1, 4.2), §10 (all of the trace/audit data model), §12.1 store selection, §12.3 environment variables, §16 testing strategy, §17 (secrets, redaction) — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P1.

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
### P1 — `core/`: the trace store, built before anything that can log · **M** (4 h) · deps P0 · ∥ none · no key · commit `P1(core): …`

**Goal.** The Session → Turn → Span audit model, its two backends and its readers' entry points exist before any component can emit a record.

**Scope.** `src/hrmosaic/core/`: `db.py` (`SqliteStore` + `TursoHTTPStore` behind one `execute`/`batch` interface), `migrations/00N_*.sql` (the whole
§10.1 schema, `sessions.auth_mode` and `sessions.actor_role` included — both `NOT NULL` with their `CHECK` vocabularies, so P8 and P9 have the columns
they render and filter on), `trace.py`, `models.py`, `redact.py`, `ids.py`, `procstat.py`, `archive.py`, `retention.py`; `tests/fixtures/traces/`;
`tests/fixtures/eval_runs/sample_run.json`.

**Deliverables.**
- `trace.py` — the writer, the buffered turn lifecycle (one small batch at turn start, one batched flush at turn end), `register_span_listener()`,
  `reopen_turn(turn_id, awaiting_ms)`, `install_shutdown_handlers()` / `flush_open_turns()` / `sweep_stale_turns()`, and the closing `UPDATE` that
  samples `turns.rss_mb_at_end`.
- `models.py` — the `payload_json` union on `kind`, the view-models, `strict_json_schema()`, `MODEL_PRICES`; `redact.py` — key-name denylist, value
  regexes, the `os.environ` sweep, the preserved token counts; `ids.py` — `secrets` ids plus `SEED = 1729` (no env var).
- `archive.py` — the idempotent boot importer for `evaluation/results/*.json` keyed on `import_state.sha256`; `retention.py` — the cascading sweep that
  never prunes an eval-linked, `eval_judge` or `maintenance` session.
- `tests/fixtures/traces/` — ≥ 2 hand-authored golden traces, one carrying a complete confirmed-write chain (`confirmation` span + `confirmations` row
  + `mock_writes` row) with `llm_messages` for every `llm_call`. The single home for golden traces.

**Definition of done.**
```bash
pytest tests/unit/test_store_parity.py -q              # identical results from both backends (Turso via httpx MockTransport)
pytest tests/unit/test_g6_redact.py -q                 # leaked values scrubbed AND prompt/completion/total_tokens survive
pytest tests/unit/test_span_listener.py tests/unit/test_ids_unique.py -q
pytest tests/unit/test_retention.py tests/unit/test_turn_close_records_rss.py -q
pytest tests/integration/test_results_import.py -q     # idempotent; re-imports a changed file; skips an unchanged one
pytest tests/integration/test_process_exit_mid_turn.py -q      # store-level form (the subprocess form is P8's)
pytest tests/architecture/test_conventions.py -q       # the sole-span-writer grep now has a real target
python -m hrmosaic.core.procstat                       # paste the Linux/CI RSS value with its date into CHANGELOG.md
```

