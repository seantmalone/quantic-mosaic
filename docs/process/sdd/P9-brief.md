# Phase brief: P9

## Spec sections to read first (authoritative): §11.6 the eleven dashboard pages, §11.7 bounded eval launch, §11.8 endpoint list, §10 (the tables the pages read), §9.8 cost accounting fields, §13.10 result artifacts the eval pages render — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P9.

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
### P9 — Observability dashboard, 11 pages · **L** (5 h) · deps P1 + P8 · ∥ 9b ∥ 9c · no key · commits `P9a/P9b/P9c(dashboard): …`

**Goal.** USER.2 and USER.3 in full: every session, turn, LLM call, retrieval, tool call, guardrail and confirmation browsable, eval views included.

**Scope.** `src/hrmosaic/web/dashboard.py`, `web/templates/dashboard/`, the `/api/*` layer, `tests/fixtures/eval_runs/` (one run JSON per variant).
**9a** — the `/api/*` endpoints, the shared table + filter-bar partials, and **page 3 (session detail) first**, the centrepiece the demo depends on.
**9b** — pages 1, 2, 4–8. **9c** — pages 9 (MCP), 10 (corpus), 11 (evals: list, detail, compare tab, metrics tab). 9b ∥ 9c once 9a lands.

**Deliverables.**
- All 11 pages of §11.6, each rendering from the typed Pydantic view-model produced by the same `/api/*` endpoint that serves its JSON, each with an
  Export JSON button; Chart.js on pages 1, 8 and 11.
- Page 11's metric block, with the four judged aggregates typed `Optional[float]` beside `judged: bool` and `n_scored{}` — never fabricated zeros —
  and the deterministic metrics non-null on every variant.
- **The whole dashboard is admin-only**, reads included — every page and every `/api/traces\|eval\|corpus\|mcp/*` endpoint returns **403**
  `{"code": "ADMIN_REQUIRED"}` outside the admin persona, on top of P8's access gate; pages 1 and 2 show and filter on `auth_mode` and `actor_role`.
- The three admin-only write controls on their stated pages: **Reset sandbox** (8), **Re-discover now** (9, opening a synthetic `maintenance` session
  for its span), **Run smoke eval** (11, bounded by `EVAL_SMOKE_MAX_ITEMS`). They are never dead: reaching the host page already proves the persona.
- `tests/fixtures/eval_runs/` — one committed run JSON per variant, so page 11's tabs are built and tested before P10 has run anything.

**Definition of done.**
```bash
pytest tests/contract/test_dashboard_pages.py -q       # 11 pages 200 + key selectors as admin; 403 ADMIN_REQUIRED without the admin persona;
                                                       #   the three write controls wired; auth_mode / actor_role on the session rows
pytest tests/contract/test_dashboard_viewmodels.py -q  # every /api/* payload validates; the judged/n_scored contract; deterministic metrics non-null
# the bounded smoke-eval endpoint ships here, importing evaluation.runner lazily; its test is P10's (runner.py is a P10 deliverable)
```

