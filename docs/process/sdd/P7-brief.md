# Phase brief: P7

## Spec sections to read first (authoritative): §7 (all: retrieval use, prompt construction, answer schema, guardrails G1–G6), §9 (all: the loop, routing, workflows, budgets, failure handling, clarification/confirmation, no hidden CoT), §10.2 span payloads, §18 the two demo tasks and DEMO_EXPECTATIONS, §16 — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P7.

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
### P7 — `agent/`: orchestrator, guardrails, workflows · **L** (5 h) · deps P5 + P6 · ∥ none · no key · commit `P7(agent): …`

**Goal.** Route → act → synthesize, with six guardrails and two declarative workflows; the demo sequences are asserted at P8.
**Scope.** `src/hrmosaic/agent/`: `client.py`, `router.py`, `orchestrator.py`, `guardrails/{g1..g6}.py`, `workflows/{remote_work,pto_request}.py`,
`prompts/{route,act,synthesize}.j2`; `tests/e2e/test_rag_only_makes_no_people_calls.py`.

**Deliverables.**
- `orchestrator.run_turn(req)` and `resume_turn(session_id, turn_id, confirmation_token)` — the two entry points `web/api.py` calls at P8, with
  `resume_turn` rehydrating from that turn's persisted `llm_messages`, `retrieval` and `tool_call` spans rather than re-retrieving.
- The MCP client: cached handshake but **one `mcp_discovery` span per turn**; the catalog → OpenAI-function conversion that *is* the model's tool
  array; `_meta` attachment; and the stripping of any model-supplied `confirmation_token`.
- The router gate (`intent == "policy_qa"` ⇒ tools 1–4 only) with the one-step `catalog_reopened` recovery path; guardrails G1–G6 as pure functions,
  each emitting a span, with G4's scoped patterns and G1's refusal reading `core.corpusread` so an out-of-scope turn makes **zero** tool calls.
- Both workflow specs, whose completion predicates require a structured-data tool result; the three Jinja prompts with the frozen prefix ordering; and
  the prompts' frozen prefix ordering. `DEMO_EXPECTATIONS` and its e2e test are P8's, the phase whose `/chat/confirm` can make demo 2 pass.

**Definition of done.**
```bash
pytest tests/unit/test_g1_evidence_gate.py tests/unit/test_g2_citation_resolvability.py tests/unit/test_g3_fact_vs_rec.py -q
pytest tests/unit/test_g4_injection.py tests/unit/test_g4_no_false_positives.py tests/unit/test_g5_sensitive.py -q   # the middle one runs over the whole manifest
pytest tests/unit/test_confirmation_token_stripped.py tests/contract/test_prompt_golden.py tests/contract/test_no_chain_of_thought.py -q
pytest tests/e2e/test_rag_only_makes_no_people_calls.py -q            # zero non-RAG tool calls on a pure policy question
pytest tests/architecture/test_conventions.py -q                      # agent/ imports no hrmosaic.mcpserver
```

