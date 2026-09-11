# P14 brief — final fix wave (carry-forwards + performance Wave 1)

## Where this fits
Every phase has landed (P0–P13, P11b/P11c). This wave clears the parked minors and the zero-cost,
no-spec-change performance levers before the publish step. Read the spec sections each item names;
the spec is authoritative and must be amended in the same commit where an item changes it.

## Items (all mandatory; each with tests)
1. **Gemini price table.** `src/hrmosaic/core/models.py MODEL_PRICES["gemini-3.5-flash-lite"]` →
   paid standard rates $0.30 input / $2.50 output per 1M tokens (context-cache rates: $0.03 write
   per 1M, cache read $0.03 — if the adapter never uses Gemini caching, set cache fields to 0.0 and say
   so in a comment). Sean enabled paid billing on the judge project on 2026-09-10; the free-tier $0
   entry now under-reports real spend. Cost is priced at write time (`core/llm/base.py`), so add a
   note in `evaluation/REPORT.md`'s judge section that judge spans recorded before this commit carry
   $0 and the pass cost (≈ $0.16 = 369k × $0.30/1M + 20k × $2.50/1M) is stated from token counts.
   Test: the price entry is non-zero and the estimator prices a 1,000/100-token Gemini call correctly.
2. **LLM rate limiter — document the service override, keep the code default.** The Render service
   now runs `LLM_RPM=60` / `LLM_BURST=30` (set 2026-09-10 via the API); the code default stays 10 (the
   harness process shares one bucket across agent, failover and judge, so a raised default would
   pace the Gemini judge differently). Update the six committed statements of "10" the performance
   plan lists (spec §9.4 token-bucket paragraph and the §11/§21 env table rows, `design-and-evaluation.md`,
   `deployed.md`, `docs/architecture.html` ×2, and the regenerated REPORT — the last one is the publish
   step's, leave it) to say: default 10; the deployed service is configured at 60/30 because the
   Anthropic account's limits, read from response headers on 2026-09-10, are 10,000 RPM and 10M input
   tokens/min, and the deployed sweep recorded 3.9 s/turn mean of bucket waiting at 10 (p90 12.2 s);
   spend stays bounded by `LLM_DAILY_CALL_CAP`. Add the provenance fix from plan W1-A: the run file
   records the harness's `llm_rpm`, so `--variant` runs against a remote target must record the
   target's effective rate (or "unknown; service env") in `eval_runs.notes` / the run file's config
   notes. Add the publish gate from W1-A: a check (script or runner flag) that fails a run whose spans
   carry any `provider_failover` or `retry_count > 0`, or any `model` other than the pinned one;
   wire it into the `--report` path so a contaminated run cannot be published silently. Tests.

3. **P11c minors.** (m1) a `main()`-level test in `tests/unit/test_deploy_health_scripts.py` proving
   `scripts/smoke_deployed.py` fails (exit 1, reason text on stderr) when `/ready` never greens with
   `--ready-timeout 0`; (m2) `ready_timeout_default()` prints a one-line stderr warning when
   `SMOKE_READY_TIMEOUT_S` is not a number before falling back; (m3) declare `httpx2` as a direct
   dependency in `pyproject.toml` (and `requirements.txt` if it is hand-maintained) at the pinned
   version already installed (2.12.0), since `agent/client.py` imports it at module level.
4. **P13 carry-forwards.** (p1) `orchestrator._nudge`'s breadth reminder opens with a count-aware
   clause: at zero searches "Not yet — you have not searched the corpus yet." and at one search the
   existing "Not yet — you have searched the corpus once."; the rest of the text is unchanged; tests
   for both wordings. (p2) G1's compliance-evidence scoring (`score_chunk_ids` call inside the
   synchronous `_absorb`) must not run the embedding on the event loop: move the scoring to a thread
   (`asyncio.to_thread`) at the nearest async boundary without rewriting the unit call sites, or
   document precisely why it cannot; on the 0.1-CPU instance an embed is ≈0.6 s of blocked loop.
5. **§14.4 expectations table.** Replace the stub-era "1.5–5 s warm turn" expectation with the
   measured figures and their provenance: warm turn 22.5 s on the free instance (cold-start probe
   2026-09-10), turn p50 17.6 s on both local and deployed 26-item runs, and the note that the earlier
   figure came from stub-model turns (mean 292 ms). `deployed.md`'s cold-start section is the
   publish step's, not yours — touch only the spec table.
6. **Performance Wave 1** from `docs/superpowers/plans/2026-09-10-performance-plan.md` §2 — read the
   whole section, then implement exactly:
   - **W1-B** query-vector memo in `src/hrmosaic/rag/embed.py` only: `functools.lru_cache(maxsize=16)`
     on a private `_embed_query_cached(model, convention, embed_dim, text)`; `embed_query` returns a
     list copy; expose `clear_query_cache()` and add an autouse test fixture that clears it; tests
     that (i) an identical query embeds once, (ii) a different model/convention/dim key misses,
     (iii) the returned list is a copy. The measurement hook: the retrieval span's `embed_ms` (already
     recorded) — add `embed_cache_hit: bool` to the retrieval payload.
   - **W1-C parts (a) and (c) only** — (a) the daily cap as a fast negative: an in-process counter
     incremented in `record_llm_call` keyed on the completion's provider, consulted first; the
     authoritative SQL count still runs before any refusal and still backs `/health`, so §9.8's "no
     second counter to drift" stays literally true — document the reasoning in the docstring; (c) turn
     rollups computed from the `TurnBuffer` instead of a re-SELECT at turn close. **Part (b) (turn-open
     batch via `asyncio.to_thread`) is deferred** — it is a TurnBuffer constructor/resume-path refactor,
     out of scope here; **part (d) (backgrounded flush) is rejected** — it races the runner's
     `read_turn`. Tests for (a) and (c); the existing store tests stay green.
   - Do NOT implement anything from Wave 2 or Wave 3.

## Definition of done
- `.venv/bin/ruff check .` and `ruff format --check` clean; `.venv/bin/pytest -q` green (baseline
  1,703 at b24ad32 plus yours; pristine output); `scripts/check_facts.py`, `scripts/pii_check.py`,
  `-m hrmosaic.rag.ingest --verify-manifest` unchanged.
- Commits on `main` prefixed `P14(<scope>): …`. Never push. Never read or print `.env`. Never call a
  live LLM or the live deploy URL (an evaluation sweep is running against it).
- No subagents. Report to `.superpowers/sdd/2026-09-08-implementation-roadmap/P14-report.md`.
