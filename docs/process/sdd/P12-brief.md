# Phase brief: P12

## Spec sections to read first (authoritative): §19, §18.3 demo script, §14.4 cold start (deployed.md), §13.10 (REPORT.md), §4 (the documentation files), §1 (goals), Appendix A row P12; docs/project-requirements.md (DOCS.* and DEMO.* items) and docs/requirements-traceability.md — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P12.

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
### P12 — Documentation, demo prep, publish · **M** (4 h) · deps P11 · ∥ none · no key · commit `P12(docs): …`

**Goal.** Every graded document written by hand, every heading asserted, both demo scripts proved against the live URL, and the grader invited.
**Scope.** `README.md`, `design-and-evaluation.md`, `ai-tooling.md`, `deployed.md`, `NEEDS-FROM-USER.md`, `docs/demo-script.md`,
`docs/pre-submission-checklist.md`, `scripts/paste_eval_numbers.py`, `tests/contract/test_docs_completeness.py`.

**Deliverables.**
- `design-and-evaluation.md` — the mermaid diagram naming all seven components, the ten R10.1 `###` justification subsections (each carrying its
  rejected alternative from spec §3), all eight DOCS.3 subjects, the generated tool schemas, both demo sequences matching `DEMO_EXPECTATIONS`, the judge
  methodology naming the labeller and the blinding, and the three evidence screenshots.
- `README.md` final (five headings, the real deployed URL, third-party components); `ai-tooling.md` (`## What worked well`, `## What did not work`, the
  AI-use and ownership disclosure); `deployed.md` final (six headings with the measured cold start and its ISO date, the MCP-transport rationale,
  `## Access` — the tokenized link, the cookie, the bearer header for API clients and MCP Inspector, the two personas and the rotation step — and
  `## Cost` with the dates observed); `design-and-evaluation.md`'s `### Security posture` subsection (no user accounts by design, the requirements are
  silent, the three controls — access token, persona roles, confirmation gate — and what production would add: SSO, employee-scoped data access, a
  retention policy).
- `docs/demo-script.md` (the §18.3 segment table, the production note, a per-task five-element DEMO.6 sub-checklist) and
  `docs/pre-submission-checklist.md` with one line per DEMO.* and SUB.* id; `tests/contract/test_docs_completeness.py`, authored here in full because
  this is the phase where every asserted document exists; `scripts/paste_eval_numbers.py`. **No CI diff-check of documentation anywhere.**

**Definition of done.**
```bash
python scripts/paste_eval_numbers.py                   # the results table filled from evaluation/results/latest.json
pytest tests/contract/test_docs_completeness.py -q     # ten ### + eight ## headings + ### Security posture; README's five + three link lines
                                                       #   (Deployed: carrying ?access=); deployed.md's six;
                                                       #   ai-tooling.md's three; demo script and pre-submission checklist present and complete
grep -c 'TBD-before-submission' README.md              # 0
BASE_URL="$DEPLOY_URL" bash scripts/demo_task_1.sh && BASE_URL="$DEPLOY_URL" bash scripts/demo_task_2.sh   # both send the bearer header
gh api -X PUT repos/seantmalone/quantic-mosaic/collaborators/quantic-grader
gh api repos/seantmalone/quantic-mosaic/collaborators/quantic-grader/permission
gh workflow run ci.yml -f deploy_only=true && curl -s "$DEPLOY_URL/health" | jq '.trace_store.eval_runs_imported'   # matches the committed count
```

