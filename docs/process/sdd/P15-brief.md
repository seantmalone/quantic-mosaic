# P15 brief — performance Wave 2, levers W2-A … W2-D (approved by Sean 2026-09-10: "Do Wave 1 and 2")

## Where this fits
P14 landed Wave 1. This wave changes bytes the model reads or writes, so it is followed by a full
deployed sweep (all three §13.9 arms), a judge pass and fresh blind labels — the main session drives
those; you never call a live LLM or the live URL.

## Requirements
`docs/superpowers/plans/2026-09-10-performance-plan.md` §3 is your requirements text: read W2-A,
W2-B, W2-C, W2-D in full, including every "Required changes applied" bullet — those bullets are
binding corrections from two adversarial reviewers and are NOT optional refinements. Where the plan
says something is DROPPED or must not be done, do not do it. The spec
(`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`) is authoritative; amend it in the same
commit where a lever changes a contract (§7.2 prompt-golden re-review; §13.3 and the `ENVELOPE_KINDS`
docstring restated for W2-C; the committed `mcp/tools/search_policy_documents.schema.json` and its
description for W2-C; §9 prompt rules for W2-A/W2-B).

## Sequencing and commits (binding)
- Implement in the order W2-A → W2-B → W2-C → W2-D, **one commit per lever**, each independently
  green, subjects `P15(agent): W2-A …`, `P15(agent): W2-B …`, `P15(mcp): W2-C …`, `P15(agent): W2-D …`.
- The act *system* half must stay byte-stable relative to the cache breakpoint (W2-A touches rule 7's
  content, which is inside the cached prefix — regenerate the golden deliberately and say in the
  report what changed, byte counts before/after).
- Regenerate all six prompt golden fixtures as a deliberate re-review (diff each, explain each).

## Tests (from the plan's "Tests to add"; all mandatory)
- `test_act_closing_step_is_short`: median `completion_tokens` of TERMINAL zero-tool-call act spans
  ≤ 40, measured separately from consumed (re-sent) ones — use recorded fixtures / stub scripts.
- `test_search_hit_omits_text_for_quarantined_chunk`: the corpus canary chunk returns snippet-only
  with `quarantined: true` (highest-severity gate of the wave).
- `test_no_act_message_contains_unbannered_g4_pattern`, asserted over `llm_messages`.
- `test_envelope_partition_is_one_definition`: the set rendered into synth EMPLOYEE CONTEXT equals
  `evaluation.runner.ENVELOPE_KINDS`, both imported from ONE module.
- Prompt-golden fixture extended with `get_policy_section` and `check_policy_compliance` envelopes.
- Existing suites stay green (baseline: P14's count in its report).

## Definition of done
- `.venv/bin/ruff check .` and `ruff format --check` clean; `.venv/bin/pytest -q` green, pristine;
  `scripts/check_facts.py`, `scripts/pii_check.py`, `-m hrmosaic.rag.ingest --verify-manifest`
  unchanged; `tests/contract/test_tool_schemas_committed.py` green after regenerating the committed
  schema with the repo's generator (`scripts/gen_tool_schemas.py`).
- Never push. Never read or print `.env`. Never touch `evaluation/results/**` or `evaluation/REPORT.md`
  (a sweep may be writing them). Do not edit `docs/optimization-log.md`.
- No subagents. Report to `.superpowers/sdd/2026-09-08-implementation-roadmap/P15-report.md`
  (per-lever: what changed, golden diffs explained, tests, DoD output, concerns).

## Item 0 (carry-forward from P14 review, do first, own commit `P15(rag): …`)
`src/hrmosaic/rag/retrieve.py` derives `embed_cache_hit` by diffing the process-global LRU hit counter
before/after `embed_query`; `retrieve()` runs under `asyncio.to_thread`, so a concurrent retrieval's
hit can be stamped on a span whose embed was real work. Make the embed report its own hit (e.g.
`embed_query_with_meta(text) -> tuple[list[float], bool]` deciding inside the same call), and keep the
existing tests plus one that two interleaved lookups attribute hits correctly.
