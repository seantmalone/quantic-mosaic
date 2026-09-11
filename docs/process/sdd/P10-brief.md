# Phase brief: P10

## Spec sections to read first (authoritative): §13 (all: dataset, harness, metrics, judge, composite, ablation, artifacts), §11.1 privileged options, §11.7, §9.8 (judge adapter, cost per run), §18 — all in docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md. Also read the Appendix A row for P10.

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
### P10 — `evaluation/`: dataset, scorers, judges, ablation · **L** (5 h) · deps P8 (+P9 for the views) · ∥ none · **key #1** (supplied) · commit `P10(eval): …`

**Goal.** A 26-item harness whose deterministic scorers run offline, whose judged metrics state their `n`, and whose three variants are proved locally
before anything is published.

**Scope.** `evaluation/`: `dataset.yaml`, `schema.py`, `deterministic.py`, `judges.py`, `runner.py`, `ablation.py`, `reference_labels.yaml`, `results/`,
`REPORT.md`; `scripts/{chunk_size_sweep,gen_ablation_evidence}.py`. **Step 0:** read the live Gemini judge RPM/RPD/TPM **and the Anthropic
`claude-haiku-4-5` prices** (§3.1) and paste them with the date into `deployed.md`, and export `APP_ACCESS_TOKEN` — the runner sends
`Authorization: Bearer $APP_ACCESS_TOKEN` and `X-Actor: admin`, and every eval item's privileged `/chat` options fail closed outside the admin persona.

**Deliverables.**
- `dataset.yaml` — 26 items in fixed file order (7 `simple_policy`, 5 `multi_doc`, 6 `tool_task`, 3 `ambiguous`, 3 `out_of_scope`, 1 `unsafe_action`,
  1 `sensitive`), **absolute dates only**, gold facts citing `corpus/facts.yml` keys, and the two workflow mirrors `remote-004` and `pto-003`.
- The deterministic scorers with every §13.3/§13.4 edge case; the four judge prompts; the runner (sequential, limiter-backed, warming the target before
  item 1, three `cold_probe` re-runs that assert `process_uptime_ms < 60000` before tagging cold); `ablation.py`; the zero-LLM chunk-size sweep.
- `reference_labels.yaml` — 8 items selected with `SEED`, groundedness labels authored by a **separate Opus subagent blind to the judge's output**,
  with a `protocol` block naming the labeller, the date and the blinding. `judge_agreement_rate` is published with its n. No κ.
- `MIN_EVIDENCE_SCORE` calibrated from the observed score distribution; one **real** exchange per demo task recorded as a stub script; the first real
  runs at `target: local`, all three variants — plumbing and determinism evidence, never promoted to `latest.json`.

**Definition of done.**
```bash
pytest tests/unit/test_dataset.py -q                   # every §13.1 clause: counts, five expected_behavior classes, inj-001, no relative dates, probe ids
pytest tests/unit/test_scorer_edge_cases.py tests/unit/test_cold_probe_excluded.py -q          # green offline against tests/fixtures/traces/
pytest tests/unit/test_reference_subset_deterministic.py tests/unit/test_latest_points_at_deployed.py -q
make eval && python -m evaluation.runner --variant dense_only_k2 && python -m evaluation.runner --variant no_structured_tools
make ablation                                          # same target + dataset_sha; the workflow-completion delta, or REPORT.md's not-supported banner
python scripts/chunk_size_sweep.py && python scripts/gen_ablation_evidence.py
pytest tests/integration/test_smoke_eval_endpoint.py -q # 403 ADMIN_REQUIRED in the employee persona; a 1-item bounded run as admin
pytest tests/unit/test_action_safety.py tests/contract/test_dashboard_viewmodels.py -q         # over the real traces; refreshed fixtures still validate
grep -n 'judge_agreement_rate\|judge_agreement_n' evaluation/REPORT.md
ls evaluation/results/                                 # three <run_id>.json, comparison.json, chunk_size_comparison.json — and NO latest.json yet
```

