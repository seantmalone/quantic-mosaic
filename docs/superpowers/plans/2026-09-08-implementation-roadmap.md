# Mosaic HR Copilot — Implementation Roadmap

**Project:** `quantic-mosaic` · Quantic "AI Engineering Techniques and Architectures"
**Date:** 2026-09-08 · **Status:** ready for autonomous execution
**Source of design truth:** [`docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`](../specs/2026-09-08-hr-agentic-rag-design.md)
**Traceability:** [`docs/requirements-traceability.md`](../../requirements-traceability.md)

> This document is the **execution plan**, not the design. Every "what" and "why" lives in the spec;
> this file answers **in what order**, **proved by which command**, **by whom (main session vs Opus
> subagent)**, and **what the human must do and when**. Where this roadmap and the spec appear to
> disagree, **the spec wins** and this file is corrected.

---

## 1. Executive summary

1. Build **Mosaic HR Copilot**: a deployed, free-tier, agentic HR assistant for the fictional
   *Mosaic Robotics, Inc.* — policy RAG over a 14-document / 63-page corpus in four formats, plus an
   agent that plans, calls **9 real MCP tools** over real JSON-RPC, and answers with resolvable citations.
2. One Python 3.12 process, one container, one Render free web service: FastAPI + Jinja/htmx UI,
   agent orchestrator, MCP client, an **in-process-mounted Streamable-HTTP MCP server**, a read-only
   sqlite-vec + FTS5 index, committed synthetic mock data, and a durable Turso trace store.
3. The **trace/audit model is built first (P1), before anything that can log**, with an AST test
   proving `core/trace.py` is the sole writer — one writer, five readers (`/chat` trace, SSE, the
   13-page dashboard, the eval scorers, the demo narration).
4. Safety is **architectural, not prompted**: mock writes require an HMAC `confirm_token` minted only
   after a human click, verified *inside* the MCP server; action safety is a build-blocking CI gate at 1.0.
5. Seven guardrails (evidence gate, citation resolvability, fact-vs-recommendation, injection shield,
   sensitive escalation, identity scope, redaction) each emit a span and each has a unit test.
6. A **single fact ledger** (`corpus/_facts.yml`) generates the corpus prose insertions, the
   deterministic compliance rules and the eval gold answers, so gold-vs-corpus contradiction is impossible.
7. A 26-item evaluation with 9 metrics across all six rubric families, a 3-variant ablation plus a
   zero-LLM chunk-size comparison, judge validation by Cohen's κ, and byte-reproducible committed results.
8. **Phases P0–P9 build and pass CI with zero API keys** (`StubAdapter` + frozen clock); credentials
   are needed only from P10 (one Gemini key) and P11 (Render + Turso).
9. CI runs on push **and** PR, is offline and deterministic after the first cache fill, and `deploy`
   is gated `needs: [test, docker]` with recorded red-run evidence.
10. Thirteen phases, ≈51 agent-hours, each ending green, committed, and independently demoable.

---

## 2. How execution is organised

### 2.1 Roles

| Actor | Does |
|---|---|
| **Main session** (this session) | Reads the spec §, writes the phase brief, dispatches subagents, reviews diffs, runs the acceptance gate, **commits**, updates `CHANGELOG.md` and `NEEDS-FROM-USER.md`. |
| **Opus subagent** (`model: "opus"` on every Agent/Workflow call, per `CLAUDE.md`) | Implements one phase or one sub-phase. Reads the spec sections named in its brief plus `mcp/README.md` where relevant. **Never commits.** |
| **Human (Sean)** | Only the seven gates in §5. Everything else is scripted. |

### 2.2 The standing subagent brief (prepended to every phase dispatch)

```
Read docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md sections: <list>.
That spec is authoritative; do not redesign. Implement exactly what it specifies.
Write ONLY the files named in your deliverables list. Never commit; never touch .git.
Every wall-clock read goes through core.clock.now(). Every span write goes through core/trace.py.
Run the acceptance commands yourself and paste the real output; do not claim green without it.
Extend .github/workflows/ci.yml job `test` with the spec §15.1 steps this phase's tests occupy
(see the step -> phase table in roadmap §6.1), then paste the green run URL. A test that a phase
gate ran locally but CI does not run cannot gate the deploy, and the two suites must not diverge.
If the spec is ambiguous or wrong, STOP and report — do not resolve it yourself.
Scratch work goes in the scratchpad directory, never in the repo.
```

### 2.3 Standing acceptance criterion (from P4 onward)

> *The expected spans were persisted, with the expected kinds and payload shapes.*

This is checked in every phase gate from P4 on, and is the mechanism that prevents a later subagent
inventing a parallel logging path (the failure USER.4 forbids).

### 2.4 Commit message pattern

Every phase commits with:

```
P<n>(<scope>): <what landed>

- <bullet per deliverable>
Gate: <the exact command(s) that proved it> — green
Reqs: <comma-separated requirement ids from docs/requirements-traceability.md>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RnJs3hSPUc8kca4BtF5oAM
```

Scopes: `skeleton`, `core`, `corpus`, `mockdata`, `rag`, `mcpserver`, `llm`, `agent`, `web`,
`dashboard`, `eval`, `deploy`, `docs`. Sub-phases use `P9a(dashboard):` etc.
Fix-up commits inside a phase use the same scope with a `fix:` prefix on the subject.

**The trailer names Opus deliberately**, matching §2.1's `model: "opus"` rule, `CLAUDE.md`, the user
auto-memory and spec §13.7's `labeller: "Claude Opus 5 subagent (claude-opus-5)"`. P12 checks the
three agree: `git log --format=%b | grep Co-Authored-By | sort -u` must return exactly one value, and
`ai-tooling.md`'s DOCS.9 ownership disclosure must name that same model. An inaccurate co-author line
on every phase commit would contradict a graded artifact.

### 2.5 Size key

| Size | Agent-hours | Phases |
|---|---|---|
| **S** | ≤ 3 h | P0, P3, P11 |
| **M** | 3–4 h | P1, P2, P4, P6, P8, P12 |
| **L** | 5–6 h | P5, P7, P9, P10 |

Total ≈ **51 agent-hours** (2+4+4+2+4+5+3+6+4+5+5+3+4), matching Appendix A of the spec.

⚠ **"Agent-hours" means attention, not elapsed time — the two diverge sharply in one place.** The
sizes above exclude wall-clock the agent spends *waiting* on an unattended workflow. **P11 is the
only phase where that matters, and it is stated separately: ≈ 2.5 h unattended** — the single
published `eval.yml` dispatch is ~700 sequential provider calls behind a 10 RPM token bucket (~70 min
of pacing floor alone) plus three `cold_probe` re-runs each preceded by `EVAL_COLD_IDLE_S = 1000 s`
of deliberate idling (~50 min), on top of Render/Turso provisioning, two Docker gate runs, the R8.4
red-run evidence pair and three browser screenshots. Its **S (3 h)** size is honest about attention
and would be dishonest about the clock, so both numbers are given. No other phase carries a material
unattended figure, and the ≈ 51 h total is an agent-hours total throughout.

---

## 3. Phase dependency graph

```
P0 skeleton
 └─ P1 core/ (trace FIRST)  ──────────────────────────────────┐
     ├─ P2 corpus ────┐                                       │
     ├─ P3 mock data ─┤ (P2 ∥ P3)                             │
     │                └─ P4 rag/ ──┐                          │
     ├─ P6 core/llm/ ──────────────┤ (P4 ∥ P6)                │
     │                 P3+P4 ──── P5 mcpserver/ ──┐           │
     │                                            └─ P7 agent/ (needs P5+P6)
     │                                                └─ P8 web/
     └────────────────────────────────────────────────── P9 dashboard (needs P1+P8)
                                                            └─ P10 evaluation (needs P7, +P9 for views)
                                                                └─ P11 deployment (needs P9+P10)
                                                                    └─ P12 docs + demo prep
```

**Parallelisable pairs:** `P2 ∥ P3` (two subagents, no shared files) and `P4 ∥ P6` (two subagents;
`rag/` and `core/llm/` share nothing). P9 splits into `9a → 9b ∥ 9c` internally. Everything else is
strictly sequential because each phase's acceptance gate consumes the previous phase's artifacts.

**Join gate after `P2 ∥ P3`: `python scripts/check_facts.py --accrual-bands`.** The accrual
cross-check reads `corpus/_facts.yml`'s two tenure bands (**P2**) *and* `mock_data/pto_balances.json`
(**P3**), so it cannot be a gate of either phase while the two genuinely run in parallel. The **main
session** runs it once, after both have landed and before P4/P5 are dispatched. It is not optional:
P5's `check_pto_balance` gate asserts `remaining_days == 13.5`, so a ledger/mock contradiction that
slipped past here would surface three phases later as a failing MCP test with no obvious cause
(spec §5.2's mode table).

---

## 4. Build phases

> Each phase ends with: acceptance gate green → **`.github/workflows/ci.yml` job `test` extended with
> the §15.1 steps this phase's tests occupy (§6.1's step → phase table), with the green run URL
> pasted** → main session reviews the diff → `CHANGELOG.md` line added → **commit** →
> `NEEDS-FROM-USER.md` refreshed. `git status` must be clean at every phase boundary (USER.5).
>
> **CI grows with the build; it is not retrofitted.** P0 lands the skeleton (steps 1, 1b, 2, 3) and
> P11 adds the `docker`, `fresh-clone` and `deploy` jobs, but **steps 4–19 of job `test` belong to
> the phase that introduces the tests they run** — otherwise the deploy-gating suite silently lags
> the suite a phase gate ran locally, which is exactly the R8.2 / USER.5 failure. The mapping is
> normative and lives in §6.1.

---

### P0 — Skeleton, CI, repo policy · **S** (2 h) · deps: none · no key

**Goal.** A repository that lints, tests (on an empty suite), runs CI on push *and* PR, and enforces
its own documentation and dependency invariants from commit one — so every later phase inherits a
green baseline rather than building one.

**Scope.** `pyproject.toml`, `requirements.txt` (`uv pip compile`, committed), `requirements-dev.txt`,
`.python-version` (3.12.14), `Makefile`, `src/hrmosaic/settings.py`, `.env.example`, `.gitignore`,
`.dockerignore`, `.github/workflows/ci.yml` (skeleton), `README.md` stub, `NEEDS-FROM-USER.md`,
`CHANGELOG.md`, `scripts/vendor_assets.py`, `src/hrmosaic/web/static/vendor/`,
`src/hrmosaic/web/static/app.css`, **`src/hrmosaic/rag/download_model.py`**.

**Deliverables.**
- `settings.py` — pydantic-settings, every §12.3 variable, **structural validation at import,
  credential validation deferred**; the `sys.version_info[:2] != (3, 12)` warning (never a crash);
  the `MCP_SERVER_URL` / `GIT_SHA` / `LLM_FALLBACK_API_KEY` / `JUDGE_FALLBACK_API_KEY` /
  `mcp_transport_effective` `model_validator`s.
- `.env.example` — every settings field, `# REQUIRED` / `# OPTIONAL`, default, signup URL,
  **including `EMBED_PROVIDER` and `GROQ_API_KEY`**.
- `Makefile` targets: `setup run run-stdio test test-smoke lint ingest eval ablation demo1 demo2
  docker docker-run` (every `make` target named anywhere in the spec must exist here).
  **`test-smoke` is written LITERALLY as `pytest tests/contract -q -m smoke; s=$$?; [ $$s -eq 0 ] ||
  [ $$s -eq 5 ]`** with `LLM_PROVIDER=stub` and the `smoke` marker declared in `pyproject.toml` —
  *not* a list of file paths. `test_app_starts.py` and `test_chat_page_renders.py` are **P8**
  deliverables, so naming them makes pytest exit 4 on a missing path and fails P0's own first command.
  ⚠ **The exit-code clause is mandatory and is not decoration:** when every collected test is
  deselected by `-m`, pytest exits **5** (`EXIT_NOTESTSCOLLECTED`), *not* 0 — so a bare
  `pytest ... -m smoke` fails the `make lint && make test && make test-smoke` chain in P0's own
  definition of done. The marker is still the right choice over file paths; the target must simply
  tolerate exit 5 explicitly rather than assume an empty selection passes (spec §4).
- **`src/hrmosaic/rag/download_model.py`** — a ~15-line
  `TextEmbedding(model_name=settings.embed_model, cache_dir=settings.fastembed_cache)` warm-fetch
  with no chunking or index dependency. ⚠ **It is a P0 deliverable, moved out of P4's scope**: CI
  step 1b (which P0 lands) runs `python -m hrmosaic.rag.download_model` on a cache miss, and the
  first CI run at P0 is *always* a cache miss — so leaving the module at P4 fails P0's own required
  status check with `ModuleNotFoundError`, and P1's R-1 container (which runs the same module inside
  `docker run -m 512m`) could not produce its `grep -E 'RSS|vec_version' CHANGELOG.md` gate either.
  P4 still owns `embed.py`, `ingest.py` and everything else under `rag/`.
- **`.gitignore` carries these lines literally** (order and shape matter): `data/index/*`,
  `!data/index/chunks.manifest.jsonl`, `data/runtime/`, `.cache/`, `.env`. Writing `data/index/`
  with a trailing slash excludes the directory, git never descends into it, and P4 silently cannot
  commit the manifest three phases later (spec §4).
- `README.md` stub whose **first 20 lines** carry `Deployed:`, `Demo video:` and `Repo:` lines with
  the literal placeholder `TBD-before-submission` — **all three regexes accept that placeholder**
  (spec §15.1; an `https://`-only `Deployed:` regex would fail P0's own `pytest
  tests/contract/test_docs_completeness.py -q` on its first run and keep the deploy-gating push path
  red from P0 through P11).
  **The stub is not link-lines-only: it carries all five required headings from commit one**, because
  P0 also authors `test_readme_required_headings`, which asserts them — `## Setup` containing the
  literal `python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`,
  `## Local Run` containing the literal `make ingest && make run`, plus `## Deployment`,
  `## Evaluation` and `## Third-party components`. The command text is load-bearing beyond P0: the
  P11 `fresh-clone` job executes those bytes **verbatim from README**. Later phases enrich the prose
  but never rename the headings.
- `scripts/vendor_assets.py` downloads htmx 2.0.9, Alpine 3.15.2, Chart.js 4.5.1 at exact tags and
  writes `{file, version, upstream_url, sha256}` into a **delimited generated block**
  ⚠ **All three pins are `[medium]` (spec §3 row 4) — only six versions in the whole document were
  probe-verified — so the script must survive a wrong tag rather than assume it.** On a 404 it
  resolves the latest matching release from the CDN's version listing, prints
  `PINNED <name> <resolved-version>`, **writes the resolved version back into its own pin table**, and
  records the sha256 **from the bytes actually fetched** (never an authored hash, which would make
  `test_vendor_asset_hashes` a tautology). P0's definition of done then reads the resolved versions
  out of `static/vendor/LICENSES.md` and records them with the date in `CHANGELOG.md`, upgrading those
  three §3 rows to `[verified]`. Without this, a single non-existent tag turns P0's own gate red with
  no stated fallback.
  (`<!-- BEGIN GENERATED: vendored assets -->` … `<!-- END GENERATED -->`) in
  `static/vendor/LICENSES.md`. **P0 hand-authors the full MIT/BSD licence texts above that block**
  (they are known at vendoring time), and the script never rewrites them — the same generated-block
  convention `corpus_stats.py` uses. **`static/vendor/` holds third-party files only:** our own
  stylesheet is `static/app.css`, because both `test_vendor_asset_hashes` and docs-check demand a
  version, sha256, upstream URL and licence text for everything in `vendor/` and P0's gate would go
  red on a file we wrote (spec §4, §15.1).
- **Repo visibility: already public** (verified with `gh api repos/seantmalone/quantic-mosaic --jq
  .private` → `false` on 2026-09-08), so no visibility change is made. P0 only re-asserts it in the
  definition of done. The grader invite (`gh api -X PUT
  repos/seantmalone/quantic-mosaic/collaborators/quantic-grader`) is sent by script at **P12**, once
  the deliverables exist, so the grader never lands on an empty repo. The user's only remaining action
  is **confirming the invite went out at G7** (§19.1 item 5).
- **Branch protection applied** to `main` with this literal configuration:
  `required_status_checks: {strict: false, contexts: ["test"]}`, **`enforce_admins: false`**,
  `allow_force_pushes: false`, `required_pull_request_reviews: null`.
  ⚠ **`enforce_admins: false` is the load-bearing part.** A required status check on `main` makes
  GitHub reject any direct push whose head commit has no passing `test` run — which is *every* phase
  commit in this plan (§4: "every phase commits directly to `main`"), and P0's own first push, since
  the workflow does not exist upstream yet and no check can have run. With `enforce_admins: true` the
  entire 13-phase build deadlocks on its first commit; with it unstated, an implementer picks one at
  random and the protection is either fatal or decorative. **The check is enforced where it matters —
  on pull requests** (P0's evidence PR, `eval.yml`'s results PR, and P11's deliberately-red R8.4 PR,
  which must be genuinely unmergeable) — **while the owner's direct phase commits are admin-exempt by
  design.**
- `.github/workflows/ci.yml` **skeleton = §15.1 steps 1, 1b, 2, 3 plus the empty `tests/unit` and
  `tests/contract` steps (6, 13)** — **six** steps, matching §6.1's table; steps 4–19 are added by
  the phases that own them (§6.1).
- `tests/contract/test_docs_completeness.py` containing **only P0's three test functions** —
  `test_readme_link_lines`, `test_readme_required_headings`, `test_vendor_licenses_complete`. Every
  later phase that creates a graded document adds its own functions to the **same file** (P11:
  `deployed.md`'s five headings; P12: the ten R10.1 + eight DOCS.3 headings, `ai-tooling.md`, the
  demo-payload containment check, `docs/demo-script.md` + `docs/pre-submission-checklist.md`). Spec
  §15.1 carries the normative ownership table. Authoring the whole file at P0 would keep the
  deploy-gating push path red from P0 through P12.
- **A recorded green `pull_request` run.** Every phase commits directly to `main`, so nothing else in
  the plan opens a PR (`eval.yml`'s comes late, P11's R8.4 PR is deliberately red) and RUBRIC5.7's
  "green on both events" artifact would have no producer. P0 therefore creates a throwaway branch
  with a no-op commit, opens a PR against `main`, waits for `test` to go green, records the run URL
  in `CHANGELOG.md`, then closes the PR and deletes the branch.

**Definition of done.**
```bash
make lint && make test && make test-smoke        # test-smoke tolerates pytest's exit 5 explicitly
                                                 #   (`; s=$?; [ $s -eq 0 ] || [ $s -eq 5 ]`);
                                                 #   an empty -m selection exits 5, not 0
python -m hrmosaic.rag.download_model && test -d "$FASTEMBED_CACHE_PATH"   # the module CI step 1b runs
pytest tests/contract/test_env_example_covers_settings.py -q     # both directions, minus DERIVED_FIELDS
pytest tests/unit/test_vendor_asset_hashes.py -q
pytest tests/contract/test_docs_completeness.py -q               # the WHOLE file: at P0 it holds only P0's
                                                                 # three functions (spec §15.1 ownership table)
gh api repos/seantmalone/quantic-mosaic --jq .private              # false (already public; no change made)
gh api repos/seantmalone/quantic-mosaic/branches/main/protection | jq '.required_status_checks.contexts'  # ["test"]
gh api repos/seantmalone/quantic-mosaic/branches/main/protection --jq .enforce_admins.enabled              # false
                                                                 # ^ read back explicitly: `true` would reject
                                                                 #   every direct phase commit to main, starting
                                                                 #   with P0's own first push

# The pull_request evidence — nothing else in the plan opens a PR, so this step produces it:
git switch -c ci-evidence-pr && git commit --allow-empty -m "ci: pull_request evidence" && git push -u origin ci-evidence-pr
gh pr create --base main --head ci-evidence-pr --title "CI evidence (pull_request)" --body "Throwaway PR to record a green pull_request run."
gh pr checks --watch                                              # `test` green
gh pr view --json url -q .url >> CHANGELOG.md                     # record the run URL, then:
gh pr close ci-evidence-pr --delete-branch
gh run list --limit 5                                             # push AND pull_request runs green
```

**Parallelism.** None (single small subagent). **Commit:** `P0(skeleton): …`

---

### P1 — `core/`: the trace store, built before anything that can log · **M** (4 h) · deps: P0 · no key

**Goal.** Make the audit model the foundation, not an afterthought — plus retire the highest-severity
risk (R-1) by measuring Linux memory *and* 0.1-CPU wall-clock before ~40 more agent-hours are spent.

**Scope.** `core/db.py`, `core/migrations/00N_*.sql`, `core/trace.py`, `core/models.py`,
`core/redact.py`, `core/ids.py`, `core/clock.py`, `core/procstat.py`, `core/archive.py`,
`core/retention.py`, `tests/architecture/`, `tests/unit/`, `tests/integration/`.
⚠ **`core/corpusread.py` and its `IndexMeta` model MOVED TO P4.** They read
`data/index/hr_index.sqlite`, whose schema — including the twelve-column `index_meta` that P4's
`test_index_meta_columns` asserts against — is not defined until **P4**, so a P1 subagent would be
authoring a reader and a typed model for a database that will not exist for two phases, with nothing
to run it against and no deliverable bullet, acceptance command or test in P1's own definition of
done. Nothing before P4 imports it: G2 is P7, `/health` is P8, the dashboard is P9 (spec §4.2, §6.5).

**Deliverables.**
- `db.py` — `execute()` / `batch()` over `SqliteStore` and `TursoHTTPStore` (hand-written httpx
  client against `POST <db>/v2/pipeline`, ~130 lines).
- Migrations for all 12 tables incl. `llm_messages`, `import_state`, `mock_writes.action_digest`,
  `turns.resumed_count`, `turns.awaiting_ms`, **`turns.rss_mb_at_end`** (page 13's chartable series),
  **`turns.outcome`'s ninth value `maintenance`**, **`sessions.client_label`'s SEVEN values** —
  `web | api | eval | demo` client-suppliable, `archive | eval_judge | maintenance` server-only (a
  five-value CHECK/Literal rejects every judge-span write and the re-discover control),
  `eval_results.run_phase`, **`used_confirm_tokens.session_id` + `.turn_id` (both NOT NULL)** —
  without them §10.6's cascade has no join column and §11.8's per-table count is unimplementable —
  and `pending_actions`' composite `(session_id, turn_id, action_digest)` primary key.
- `trace.py` — sole writer; **`register_span_listener(fn) -> Unsubscribe`**, the SSE publish hook
  (an *inversion*: `core/**` may not import `hrmosaic.web`, so `web/sse.py` registers **one**
  listener at P8 and owns the `dict[turn_id, list[asyncio.Queue]]` — spec §11.3);
  **`install_shutdown_handlers() -> None` (idempotent), `flush_open_turns(timeout_s: float) -> int`
  and `sweep_stale_turns(older_than_s: int = 300) -> int`** — the SIGTERM/SIGINT/`atexit` machinery,
  bounded at 3 s, **homed here rather than in `web/main.py`** because §8.1's lifespan calls them by
  name, P1's `test_process_exit_mid_turn` must drive them store-level with no HTTP (it cannot import
  `hrmosaic.web`, which does not exist at P1), and §4.2 makes `core/trace.py` the sole writer of
  `turns` in any case (spec §10.3); **`reopen_turn(turn_id, awaiting_ms) -> int`**, the
  only legal way to reopen a turn (spec §10.3 step 4 — `web/api.py` may not issue that `UPDATE`);
  **and the end-of-turn close path that calls `procstat.rss_mb()` itself and writes
  `turns.rss_mb_at_end` in the closing `UPDATE`** — assigning that write here is what stops P9
  arriving to build page 13's chart and finding the column null for every turn (spec §10.1, §11.4);
  and the explicit **eight-entry** replay API `import_session / import_turn / import_span /
  import_llm_messages / import_mock_write / import_pending_action / **import_eval_run** /
  **import_eval_result**` — the last two carry §10.4 tier 3, without which `archive.py` would need
  SQL of its own and fail its own architecture test.
- `models.py` — the span-payload discriminated union + `strict_json_schema(model)` emitter.
- `clock.py` — the only module that reads a real clock, with **TWO functions**: `now()` (overridable
  by `EVAL_FIXED_NOW` → `NOW_OVERRIDE` → real, used for every business/date value that can reach
  `messages`, a tool result or a gold fact) **and the NON-overridable `wall_ms()` / `monotonic_ms()`**,
  used exclusively for `turns.started_at` / `duration_ms` / `awaiting_ms` / `process_uptime_ms` and
  `/health.app.uptime_ms`. The AST sole-caller rule exempts only that second pair inside `clock.py`.
  Without the split a frozen clock makes `process_uptime_ms` constant, so §13.5's warm-up poll never
  terminates, every turn classifies COLD and the published p50/p95 is degenerate (spec §4, §13.6).
- `ids.py` — `SEED = 1729` as a **module constant consumed only by `evaluation/**`**; it is
  deliberately **not** a `Settings` field and has **no `.env.example` entry** (spec §12.3), since a
  live env var that nothing reads would break the determinism claim in the one direction a user can
  exercise. Ids from `secrets.token_hex`, never a seeded RNG (spec §4, §13.6).
- `procstat.py` — `rss_mb() -> (current_mb, peak_mb, source)`, `/proc/self/statm` on Linux with the
  unit-converted `getrusage` peak fallback elsewhere (spec §11.4). P1 owns the module and its test;
  P8 merely calls it from `/health`.
- `tests/fixtures/traces/` — **created here**, with at least two hand-authored golden traces, one
  carrying a complete confirmed-write chain (`confirmation` span + `pending_actions` row with
  `user_response='confirmed'` + `mock_writes` row with matching `confirmation_span_id` /
  `action_digest`) plus `llm_messages` for every `llm_call` span. **P1's three archive tests point
  here, not at `data/archive/`**, which is a P10/P11 artifact. P10 *adds* real recorded traces to the
  same directory (spec §16.4).
- **`tests/fixtures/eval_runs/eval_results_sample.{deterministic.json,env.json,items.jsonl}`** — a
  hand-authored **tier-3 triple**, written from spec §13.6's pinned column mapping. P1's definition of
  done requires `test_archive_roundtrip` to import one committed eval-results artifact through
  `import_eval_run()` / `import_eval_result()`, but `evaluation/results/` is a **P10** deliverable and
  `tests/fixtures/traces/` holds *trace* fixtures, not eval-result files — so without this bullet P1
  either invents a file shape ahead of P10 (which P10 then contradicts) or ships an assertion its own
  gate names as red. **P10's definition of done regenerates this triple from its first real run and
  re-runs P1's round-trip test**, which is what keeps the two phases from diverging (spec §13.6,
  §16.4).
- `archive.py` — idempotent upsert **containing no SQL of its own** (it calls the replay API).
- `retention.py` — **cascading** sweep: spans → `llm_messages` → turns → `pending_actions` /
  `used_confirm_tokens` → sessions, in one batch.
- **The P1 half of the R-1 measurements**, recorded with dates in `CHANGELOG.md`: (a) `docker run
  -m 512m --memory-swap 512m` on `python:3.12-slim` + `pip install -r requirements.txt` +
  `python -m hrmosaic.rag.download_model`, importing FastAPI + `mcp` + fastembed + sqlite-vec and
  **holding the ONNX session open**, reading RSS from `/proc/self/statm`; (b) the `python:3.12-slim`
  sqlite-vec loadable-extension probe (`enable_load_extension` → `sqlite_vec.load()` →
  `vec_version()`).
  **The model-resident and `--cpus 0.1` six-tool-call measurements are P8's**, not P1's: they need
  `/ready`, `/health.app.rss_mb` (P8), a six-tool-call turn (P5 + P6 + P7) and a bootable app. P1
  records what a bare container can show; P8 records the rest and re-confirms `AGENT_WALL_CLOCK_S`
  against it (spec §20 R-1, §9.4).

**Definition of done.**
```bash
pytest tests/architecture -q          # sole-writer over src/** AND evaluation/**, WITHOUT an archive.py
                                      # carve-out. Roots are [Path("src"), Path("evaluation")]; a missing
                                      # root is SKIPPED with a pytest.warns message, never an error —
                                      # evaluation/ does not exist until P10, which then asserts
                                      # scanned_roots == {"src","evaluation"} (spec §4.2).
pytest tests/unit/test_store_parity.py tests/unit/test_redact_preserves_token_counts.py \
       tests/unit/test_rss_reader.py tests/unit/test_pending_action_collision.py \
       tests/unit/test_span_listener.py tests/unit/test_ids_unique.py \
       tests/unit/test_clock_split.py tests/unit/test_turn_close_records_rss.py -q
# test_clock_split: under NOW_OVERRIDE, two now() reads 50 ms apart are EQUAL while two wall_ms()
#   reads are NOT — the split that keeps the latency model unfrozen (spec §4, §13.6).
# test_turn_close_records_rss: a normally-closed turn has a non-null turns.rss_mb_at_end.
pytest tests/integration/test_archive_roundtrip.py tests/integration/test_archive_idempotent.py \
       tests/integration/test_archive_updates.py tests/integration/test_retention.py \
       tests/integration/test_process_exit_mid_turn.py -q
grep -E 'RSS|vec_version' CHANGELOG.md            # the two P1 R-1 numbers, dated
```
`test_retention.py` must assert **zero orphaned `llm_messages`**; `test_archive_roundtrip.py` must
assert `messages_ref.n_messages == count(llm_messages for that span_id)` with non-empty content,
**and** that the committed `tests/fixtures/eval_runs/eval_results_sample.{deterministic.json,env.json,items.jsonl}`
**triple** imports to exactly one `eval_runs` row and N `eval_results` rows with `run_phase` preserved
**and at least one row carrying non-null `session_id`, `turn_id` and `latency_ms`** — the assertion
that proves `.items.jsonl` was merged, without which the dashboard's one-click eval-row → trace link
is dead on every cold database (spec §10.4 tier 3, §13.6).
`test_process_exit_mid_turn.py` is the **store-level** form at P1 — the SIGTERM/`atexit` flush and the
5-minute startup sweep driven against an in-process trace writer, **no HTTP** — because `web/main.py`
and a tool-calling turn are P7/P8 deliverables; P8 extends the same file with the subprocess form.
**`test_lifespan_order.py` is not a P1 test at all**: it asserts `web/main.py`'s lifespan ordering
against a booted app and belongs to **P8** (spec §8.1, §10.3).
`test_rss_reader.py`'s decreasing-value assertion is `skipif`-ed off darwin, so **P1 pastes the CI
(Linux) run output**, not only the local run — weakening it to pass on macOS would silently turn
CI step 19's < 420 MB gate into a peak measurement (spec §11.4).

**Parallelism.** One subagent (the sole-writer invariant is easier to hold with one author).
**Commit:** `P1(core): …`

---

### P2 — Policy corpus and the fact ledger · **M** (4 h) · deps: P0 · no key · ∥ P3

**Goal.** A corpus whose every number is authored exactly once, so gold answers, compliance rules and
prose can never contradict each other (mitigation for R-7).

**Scope.** `corpus/_facts.yml`, `corpus/_spec/*.yaml`, `corpus/_numeric_allowlist.yml`, the 14
documents, `corpus/README.md`, `scripts/gen_corpus.py`, `scripts/build_pdf.py`,
`scripts/gen_rules.py`, `scripts/corpus_stats.py`, `scripts/check_facts.py`.

**Deliverables.**
- `_facts.yml` incl. **both** accrual bands (`pto.accrual.ft_under_3y`, `pto.accrual.ft_3y_plus`)
  each with its `tenure_band`, plus `approved_countries` and `cross_references`.
- **The 14 documents' prose authored ONCE and committed** (no LLM runs inside the generator);
  `gen_corpus.py` is a deterministic renderer that only injects ledger statements, stamps headers and
  emits the PDF/HTML derivatives.
- `_rules.yml` generated from the ledger, carrying **≥ 1 requirement for every one of tool 4's SEVEN
  `scenario` enum values** — `international_remote`, `domestic_remote`, `pto_request`,
  `expense_claim`, `equipment_request`, `benefits_change`, `conduct_escalation` — since the demos
  exercise only two and the tool could otherwise ship returning `insufficient_evidence` for five
  advertised scenarios with every cited test green (spec §5.2, §8.4 tool 4); `gen_rules.py` **fails
  at P2 on an empty scenario, and fails if any rule's `heading_path` is
  absent from the rendered corpus** — `mcpserver/rules.py` resolves that pair to a real `chunk_id` at
  call time and G2 strips anything that does not resolve, spec §8.4 tool 4);
  `_numeric_allowlist.yml` with a `reason` per entry.
- `check_facts.py` with its **three explicitly-scoped modes** — `--ledger` (P2's gate),
  `--accrual-bands` (P3's gate and the P2 ∥ P3 join gate) and `--manifest` (P4's gate). The bare
  command runs all three and is used only by P12 and full local checks (spec §5.2).
- The **injection canary** pinned into its own leaf section sized between `CHUNK_MIN_CHARS` (120) and
  `CHUNK_MAX_CHARS` (1400).
- Topic → document map in `corpus/README.md` covering all ten PD.2 topics.

**Definition of done.**
```bash
python scripts/gen_corpus.py && git diff --exit-code corpus/     # idempotency gate
python scripts/corpus_stats.py                                    # 5<=files<=20, round(pages)==stated, 30..120
python scripts/check_facts.py --ledger                            # every SCOPED numeric ledgered; xrefs resolve
pytest tests/unit/test_corpus_stats.py tests/unit/test_corpus_topics.py \
       tests/unit/test_numeric_allowlist.py -q
```
⚠ **P2's gate runs `--ledger`, never the bare `check_facts.py`.** The bare form also runs
`--accrual-bands` (needs `mock_data/`, a **P3** deliverable running in parallel) and `--manifest`
(needs `data/index/chunks.manifest.jsonl`, a **P4** deliverable), so it cannot close green here — and
CI step 17, which P2 creates, would be red from P2 until P4. The canary-in-exactly-one-chunk
assertion is **P4's** for the same reason. P2 still *ships* all three modes (spec §5.2).

**Parallelism.** Runs **in parallel with P3** (disjoint file trees). Within P2, one subagent authors
prose for documents 1–7 and a second for 8–14 against the same `_spec` files, then the main session
runs `check_facts.py --ledger` over the union. **Commit:** `P2(corpus): …`

---

### P3 — Synthetic mock data · **S** (2 h) · deps: P0 · no key · ∥ P2 (the accrual cross-check is a JOIN gate, not a P3 gate)

**Goal.** Six committed, immutable, obviously-synthetic JSON datasets that are arithmetically
consistent with the fact ledger at the frozen clock.

**Scope.** `scripts/gen_mock_data.py`, `mock_data/*.json`, `mock_data/schemas/*.schema.json`,
`mock_data/README.md`, `scripts/gen_mock_schemas.py`, `scripts/pii_check.py`.

**Deliverables.** `employees.json` (24), `pto_balances.json`, `benefits_elections.json` (**`E1108`
is hired `2026-08-15` with `waiting_period_ends: 2026-11-13` — a date AFTER the frozen now, so the
90-day waiting period is still open and the fixture demonstrates something; the old `2026-04-01`
ended five months before `NOW_OVERRIDE` and was arithmetically self-contradictory in exactly the way
spec §5.4 spends a page preventing for `E1042`. `lookup_benefits_status` **computes** `eligible` at
`clock.now()` against `waiting_period_ends`, never echoing the stored flag**),
`org_manager_map.json`, `offices.json`, `holidays_2026.json` — **no `tickets.seed.json`**; each with
the `_synthetic` / `_notice` / `_generator` banner; Pydantic models → generated JSON Schemas;
`pii_check.py`. **Employee ids: 24 non-contiguous ids from the `E1001`–`E1199` space, every one
matching `^E1[0-9]{3}$` (the same pattern in `mock_data/schemas/*.schema.json` and in every §8.4 tool
schema), with the four fixed anchors `E1002`, `E1007`, `E1042` (the demo/eval persona) and `E1108`
(the benefits waiting-period fixture) emitted first — §5.4.** Do **not** emit `E1001`–`E1024`
sequentially: `E1042` and `E1108` are load-bearing in both demo tasks, eval item `pto-003`,
`test_mcp_tool_call`, `test_demo_tasks` and the archived traces.

**Definition of done.**
```bash
python scripts/gen_mock_data.py && git diff --exit-code mock_data/    # byte-idempotent
pytest tests/unit/test_mock_schemas.py tests/unit/test_pto_balance_arithmetic.py \
       tests/unit/test_mock_anchor_ids.py -q          # ★ {E1002,E1007,E1042,E1108} present; all 24 ids
                                                      #   unique and ^E1[0-9]{3}$; E1042 -> 13.5 at frozen now;
                                                      #   E1108 -> eligible == false with
                                                      #   waiting_period_ends == "2026-11-13", strictly
                                                      #   AFTER clock.now() (spec §5.4)
python scripts/pii_check.py                                           # no SSN/real-email/non-555 phone
```
**The accrual cross-check is the `P2 ∥ P3` JOIN gate, not a P3 gate.**
`python scripts/check_facts.py --accrual-bands` reads `corpus/_facts.yml`'s two tenure bands (P2)
*and* `mock_data/pto_balances.json` (P3); run truly in parallel, P3 cannot execute it. The **main
session** runs it once after both phases land, before P4/P5 are dispatched (§3). Skipping it
propagates a ledger/mock contradiction into P5's `check_pto_balance` gate, which asserts
`remaining_days == 13.5`.

**`E1042` is hired `2022-11-13`** (45 completed months at the frozen `2026-09-08`), **not**
2023-02-13: the later date crosses the `ft_under_3y` → `ft_3y_plus` band on 2026-02-13, so January
and February 2026 would accrue at 1.25 and `accrued_ytd` would be **13.00**, contradicting the 13.50
/ `remaining_days == 13.5` every other artifact documents (spec §5.4).

**Parallelism.** One subagent, in parallel with P2. **Commit:** `P3(mockdata): …`

---

### P4 — `rag/`: parsing, chunking, embedding, hybrid index · **M** (4 h) · deps: P2 (+P1) · no key · ∥ P6

**Goal.** A deterministic, byte-reproducible index with hybrid retrieval whose score scale and
threshold semantics are unambiguous.

**Scope.** `rag/parse/{md,html,pdf,txt}.py`, `rag/chunk.py`, `rag/embed.py`, `rag/index.py`,
`rag/vecbackend.py`, `rag/retrieve.py`, `rag/ingest.py`, **`core/corpusread.py` (moved here from P1)**,
`data/index/chunks.manifest.jsonl`. (**`rag/download_model.py` is a P0 deliverable** — CI step 1b runs
it from P0 onward and P1's R-1 container calls it.)

**Deliverables.**
- Four parser paths with heading extraction; the PDF path validated against
  `workplace-conduct.src.md`'s heading set.
- Heading-aware chunker (1400/1100/150/120) with
  `chunk_id = "c_" + sha256(f"{doc_id}|{' > '.join(heading_path)}|{char_start}|{text}")[:16]` —
  **`heading_path` is joined with the literal `" > "` before hashing AND before storage**; hashing a
  Python list `repr` instead changes every chunk id and every artifact keyed on one.
  `chunker_version = "2026.1"` is a module constant, bumped whenever the four chunk constants or the
  hash input change (spec §6.3).
- `embed.py` — the **only** module permitted `.embed(` / `.query_embed(` / `.passage_embed(`;
  `batch_size=8`, `threads=1`, `cache_dir=`, **never** `parallel=`. **Plus the `fake` embedder, which
  had no home anywhere: `_fake_embed(texts)` (sha256 of the text expanded to 384 float32s,
  L2-normalised, seeded only by the text), selected inside `embed_passages` / `embed_query` when
  `settings.embed_provider == "fake"`, with the module constant
  `EMBED_MODEL_EFFECTIVE = "fake-hash-384"` written to `index_meta.embed_model`; and the module
  constant `QUERY_CONVENTION` set by the `query_embed` gate below** (spec §6.4, §12.3).
- **`core/corpusread.py` + the `IndexMeta` Pydantic model** — `get_chunk` / `get_document` /
  `list_documents` / `list_chunks` / `get_index_meta`, opening `INDEX_PATH` with `mode=ro`. Moved
  from P1 because the schema it reads (the twelve-column `index_meta`) is defined *here*, and nothing
  before P4 imports it (spec §4.2, §6.5).
- **`rag/vecbackend.py::knn(query_vec, k) -> list[(rowid, dense_score)]` with BOTH implementations,
  unconditionally** — the `vec0` KNN and the NumPy brute-force scan — selected at call time by
  `rag/index.py::available_vector_backend()`, and `ingest.py` **always** writing
  `data/index/vectors.f32` (gitignored, ~0.4 MB) alongside the vec0 table. It is *not* wired only on
  probe failure: `test_vector_backend_parity.py` runs the same query through both backends and cannot
  exist unless both do, and a fallback first exercised in production is untested where it matters
  (spec §6.5, R-17).
- sqlite-vec `vec0` (`distance_metric=cosine`) + FTS5 + `chunks` + `documents` + `index_meta`
  — **all twelve columns, incl. `vector_backend` AND `format_counts_json` unconditionally**
  (spec §6.5; `/health.index` and `corpus_stats.py` both require them).
- **The three non-settings comparison values `open_index()`'s mismatch guard needs, as module
  constants and a probe — because §12.3 forbids a `Settings` field no code reads and the bijection
  test enforces it in both directions:** `rag/index.py::EXPECTED_DISTANCE_METRIC = "cosine"`,
  `rag/embed.py::QUERY_CONVENTION` (set by the P4 `query_embed` gate) and
  `rag/index.py::available_vector_backend()`. Only `embed_model` and `dim` come from settings.
  `test_index_meta_columns` asserts all three exist (spec §6.5).
- `open_index()` is **lazy** and its `IndexModelMismatch` is caught at the `/health` and retrieval
  boundaries — it never fails boot (spec §6.5, §11.4, §12.3).
- `--selftest` with the **fixed** pair of spec §6.5: the query *"How many consecutive days abroad
  require Tax & Legal review?"* asserting top-1 `doc_id == "tax-and-location-addendum"`,
  **`dense_score >= SELFTEST_MIN_DENSE_SCORE`** — a module constant in `rag/index.py` initialised to
  **0.25**, deliberately *not* `MIN_EVIDENCE_SCORE`, which is a **P10** calibration output while
  `--selftest` is both a P4 gate and a build-blocking Dockerfile step; coupling them would let a
  legitimate 0.29 corpus block P4 and every Docker build six phases before the remedy, and would let
  a P10 recalibration start failing the build on an unchanged index — and
  `index_meta.chunk_count == wc -l chunks.manifest.jsonl`. **P4 records the observed selftest score in
  `CHANGELOG.md` so P10's calibration starts from a measurement** (spec §6.5).
- **`ingest.py --verify-manifest` implemented as spec §6.5 defines it**: run the full pipeline into
  `INDEX_PATH`, write the manifest to a temp path, exit non-zero with a unified diff if it is not
  byte-identical to the committed `data/index/chunks.manifest.jsonl`, and **refuse
  `EMBED_PROVIDER=fake` with exit code 2 and a named message**.
- **The committed manifest now carries a `text` field**, last-but-one:
  `{chunk_id, doc_id, doc_title, heading_path, char_start, char_end, n_chars, text, text_sha256,
  chunker_version}` — `check_facts.py --manifest` and `test_g4_no_false_positives` both read chunk
  text from it, and neither is implementable without it (spec §6.1, §6.3).
- RRF retriever with **filter-then-truncate** `min_dense_score` semantics and the score-fill step.
- `ingest.py` emitting `data/index/ingest_report.json` + `index_meta.format_counts_json`.

**Definition of done.**
```bash
make ingest && pytest tests/unit/test_chunking_deterministic.py -q     # manifest byte-identical
pytest tests/unit/test_query_embed_is_asymmetric.py -q                 # ★ P4 ACCEPTANCE GATE
pytest tests/unit/test_dense_score_scale.py tests/unit/test_min_dense_score_is_not_rrf.py \
       tests/unit/test_retrieval_filters.py tests/unit/test_ingest_report.py \
       tests/unit/test_chunking.py tests/unit/test_chunk_citation_fields.py -q
# test_chunking.py = heading-path propagation + overlap behaviour on fixtures (R2.2's named artifact,
#   distinct from test_chunking_deterministic's byte-identity check)
pytest tests/unit/test_vector_backend_parity.py -q                     # UNCONDITIONAL — both backends
                                                                       # always ship (spec §6.5)
pytest tests/unit/test_fake_embedder.py -q                             # determinism across two interpreter
                                                                       # runs, unit norm, and --verify-manifest
                                                                       # exiting 2 under EMBED_PROVIDER=fake
pytest tests/unit/test_index_meta_columns.py tests/unit/test_gitignore_manifest_tracked.py \
       tests/unit/test_corpusread_contract.py -q
python scripts/check_facts.py --manifest        # canary in exactly one manifest chunk (P4 owns it, not P2)
python -m hrmosaic.rag.index --selftest         # the FIXED query/expected pair of spec §6.5,
                                                #   gated on SELFTEST_MIN_DENSE_SCORE (0.25), never on
                                                #   the P10-calibrated MIN_EVIDENCE_SCORE
```
**Gate discipline:** P4 does **not** complete until `test_query_embed_is_asymmetric` has run and the
branch taken (`fastembed.query_embed` vs `prefix:…`), the fastembed version and the date are written
into `CHANGELOG.md` and §3 row 8's confidence tag is updated.

**Parallelism.** Runs **in parallel with P6**. **Commit:** `P4(rag): …`

---

### P5 — `mcpserver/`: nine tools, HMAC confirmation, identity binding · **L** (5 h) · deps: P3+P4 · no key

**Goal.** A real MCP 2.2.0 server whose safety properties are enforced at the tool boundary, so a
fully prompt-injected agent still cannot write state or read another employee's record.

**Pre-step (before any code is written).** Grep the installed `mcp==2.2.0` for
`TransportSecuritySettings` / `allowed_hosts` / `allowed_origins`; record the exact API found **or its
absence** with the date and confidence in `mcp/README.md`. If absent, the §17 claim is *replaced* by a
FastAPI `Host`/`Origin` allowlist + per-IP rate limit on the `/mcp-server` mount.

**Scope.** `mcpserver/server.py`, `mcpserver/tools/*.py` (9), `mcpserver/rules.py`,
`mcpserver/confirm.py`, `mcpserver/identity.py`, **`mcpserver/asgi.py`**, `mcpserver/stdio_main.py`,
`mcp/server_entrypoint.py`, `mcp/run_{stdio,http}.sh`, `mcp/tools/*.schema.json`, `mcp/README.md`,
`mcp/inspector.md`, `scripts/gen_tool_schemas.py`.

**Deliverables.** The nine tools with in/out schemas and annotations; the deterministic rules engine
over `_rules.yml`, **resolving each rule's `(doc_id, heading_path)` to a real `chunk_id` at call time
via `core.corpusread` — never inventing one, since G2 strips anything that does not resolve**
(spec §8.4 tool 4); **`mcpserver/asgi.py::mount_mcp()` / `build_mounted_app()`** — the single mount
helper, so P5's mounted-HTTP gate exercises byte-for-byte the mounting P8's `web/main.py` ships
(spec §8.1), since `web/main.py` itself is a P8 deliverable and an invented throwaway app would
diverge; **`confirm.action_digest(tool, args)`** — the one implementation of the 16-hex join key that
both the tool handlers and (at P8) `web/api.py` import, `sha256(canonical_json({"tool", "args"
omitting confirm_token}))[:16]` (spec §8.6), without which P5 and P8 produce two formulas and the
1.0 action-safety gate never closes; HMAC `mint`/`verify` (mint referenced from **zero** modules in this phase — it is
called only from `web/api.py` at P8; **P5 therefore must NOT write
`tests/architecture/test_mint_sole_caller.py`** — the §15.1 step-5 assertion "`confirm.mint`
referenced from exactly one module (`web/api.py`)" is unsatisfiable until `web/api.py` exists, so
authoring it here turns `pytest tests/architecture` red on every push from P5 through P7. It is a
**P8** deliverable); identity binding on **tools 4–9**, with the **absent-actor rule stated by the spec rather than
guessed: a missing `_meta["mosaic/actor"]` means `actor == the requested employee_id`
(self-service), the result carries `"actor_source": "implicit_self"`, and cross-employee access still
requires an explicit actor and is still `FORBIDDEN_IDENTITY`** — the reading that keeps CI step 11's
bare `check_pto_balance("E1042")` satisfiable *and* §17's "reads are identity-bound server-side" true
(spec §8.6); all four `_meta` keys
(`mosaic/trace`, `mosaic/actor`, `mosaic/retrieval`, `mosaic/confirm`) and the `_trace` span envelope;
**`agent/client.py`'s `STDIO_INHERITED_ENV = ("CONFIRM_SECRET", "TRACE_DB_PATH", "PERSIST_BACKEND",
"TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "NOW_OVERRIDE", "EVAL_FIXED_NOW")` and the launcher that
exports every one into the stdio child, plus `SqliteStore` opening with `journal_mode=WAL` and
`busy_timeout=5000`** — under stdio the child writes `mock_writes` rows and marks
`used_confirm_tokens` single-use, so without a shared store `test_confirm_across_stdio` is
unimplementable and dashboard page 8's mock-action log is empty for every stdio write (spec §8.6);
**`get_policy_section`'s `oneOf` selector rule** (neither ⇒ `isError` `INVALID_ARGUMENTS` naming both
fields; both ⇒ `chunk_id` wins and the result records `resolved_by`); **`gen_tool_schemas.py`
file-tolerant** — always writes `mcp/tools/*.schema.json`, rewrites `design-and-evaluation.md`'s
generated block only if that file exists and otherwise prints
`skipped: design-and-evaluation.md not present` (the document is a P12 deliverable, so without the
skip this phase's own gate either crashes or creates a graded document seven phases early — spec
§8.8);
`mcp/README.md` with the full 1.x→2.x mapping table, the `_meta` conventions **and the
`STDIO_INHERITED_ENV` / WAL rules above**.

**Definition of done.**
```bash
pytest tests/contract/test_mcp_api_shape.py tests/contract/test_tools_match_spec.py -q
pytest tests/integration/test_mcp_discovery.py -q          # >=5 tools over stdio AND mounted HTTP —
                                                           # the HTTP half runs against build_mounted_app()
pytest tests/integration/test_mcp_tool_call.py -q          # BOTH halves of R5.2 on BOTH transports:
                                                           #   check_pto_balance("E1042") -> remaining_days == 13.5
                                                           #   search_policy_documents -> non-empty hits[] whose
                                                           #     chunk_ids all resolve via core.corpusread
                                                           #   (spec §16.3 — the RAG half had no named live-call
                                                           #    assertion anywhere before P5 otherwise)
pytest tests/unit/test_confirm_hmac.py tests/unit/test_action_digest_stable.py \
       tests/unit/test_g6_identity_server.py tests/unit/test_rules_engine.py \
       tests/unit/test_stdio_inherited_env.py tests/unit/test_confirm_secret_unwritable.py \
       tests/unit/test_get_policy_section_selectors.py -q
# test_g6_identity_server also covers the absent-actor default: a bare check_pto_balance("E1042") with
#   NO _meta succeeds with actor_source == "implicit_self", while an explicit actor E1042 against
#   E1108 is FORBIDDEN_IDENTITY (spec §8.6).
# test_rules_engine also asserts set(_rules.yml scenarios) == set(tool 4's enum) with a
#   non-insufficient_evidence verdict reachable for each of the seven (spec §5.2, §8.4 tool 4).
# test_g6_identity_server.py = the MCP-LAYER half of G6 (tools 4-9, incl. tool 4). The orchestrator
# half, tests/unit/test_g6_identity.py, is P7's: one file named as a gate in two phases means either
# P5 ships a partial file P7 rewrites, or P5's gate fails on an agent/ module that does not exist.
# test_rules_engine.py additionally asserts every emitted evidence.chunk_id resolves in the index.
pytest tests/architecture/test_tool_handlers_async.py tests/architecture/test_no_mcp_init.py -q
python scripts/gen_tool_schemas.py && git diff --exit-code mcp/tools/
#   ^ prints `skipped: design-and-evaluation.md not present` and exits 0 — the document is P12's
```
Plus: write-without-token returns `CONFIRMATION_REQUIRED` **carrying no token field**; a
cross-employee read returns `FORBIDDEN_IDENTITY` **including through `check_policy_compliance`**;
`_meta.mosaic/retrieval.k_override` beats a model-supplied `k`.

**Parallelism.** Sub-split by tool group across two subagents (tools 1–4 corpus, tools 5–9 people +
writes) after `server.py` / `confirm.py` / `identity.py` land from one author.
**Commit:** `P5(mcpserver): …`

---

### P6 — `core/llm/`: the provider abstraction · **M** (3 h) · deps: P1 · key #1 for the gate only · ∥ P4

**Goal.** Four adapters behind one protocol, with the `StubAdapter` that makes P0–P9 credential-free
and the `CachedAdapter` that makes the eval replayable offline.

**Scope.** `core/llm/{base,openai_compat,anthropic,stub,cache,limiter}.py`,
`scripts/probe_provider.py`, `tests/fixtures/llm_scripts/`.

**Deliverables.** `ChatModel` protocol; `OpenAICompatAdapter`; `AnthropicAdapter` (httpx
`MockTransport`-tested, no key); `StubAdapter`; `CachedAdapter` with three sources and
`EVAL_CACHE_ONLY`; token-bucket limiter (capacity `LLM_BURST`, refill `LLM_RPM`/60, **keyed on the
resolved API key**); failover to `LLM_FALLBACK_*`; exactly one `llm_call` span emitted **from inside
the adapter**, plus its `llm_messages` rows and `structured_output_mode`.

**Definition of done.**
```bash
pytest tests/unit/test_adapters.py tests/unit/test_limiter_burst.py \
       tests/unit/test_strict_schema_emission.py tests/unit/test_cache_key_stable_across_days.py -q
pytest tests/contract/test_no_cot.py -q
```
**Live gate (needs key #1):** `python scripts/probe_provider.py` must (a) `GET /models` and confirm
`LLM_MODEL` exists, (b) issue **one** request carrying both `tools` and a strict `response_format`,
(c) write the outcome + endpoint + date into `CHANGELOG.md`. **If key #1 is not yet pasted, P6 ships
the prompted-JSON fallback path and this gate defers to the start of P10** — it never blocks the phase.

**Parallelism.** Runs **in parallel with P4**. **Commit:** `P6(llm): …`

---

### P7 — `agent/`: orchestrator, guardrails, workflows · **L** (6 h) · deps: P5+P6 · no key

**Goal.** The plan → act → synthesize loop that reaches tools **only** through the MCP client, with
seven guardrails and four tested failure paths, all at HTTP 200.

**Scope.** `agent/client.py`, `agent/router.py`, `agent/orchestrator.py`,
`agent/guardrails/g1..g7.py`, `agent/workflows/{remote_work,pto_request}.py`, `agent/prompts/*.j2`.

**Deliverables.** MCP client with per-turn `mcp_discovery` span (cached handshake, per-turn span);
router that **gates** the catalog to tools 1–4 on `policy_qa` with the one-step reopen recovery;
**`agent/orchestrator.py`'s two named entry points — `async def run_turn(req: ChatRequest) ->
ChatResponse` and `async def resume_turn(session_id, turn_id, action_digest, confirm_token) ->
ChatResponse`** — the interface `web/api.py` calls at P8. Every other cross-phase symbol in this build
is named explicitly (`trace.reopen_turn`, `confirm.mint`, `confirm.action_digest`, `mount_mcp`,
`register_span_listener`) precisely because unnamed interfaces get invented twice; the orchestrator
was the one gap, and `/chat/confirm` was additionally unimplementable without a stated rehydration
rule. **`resume_turn` rebuilds the buffered turn state from that turn's persisted spans** — the
message array from its `llm_messages` rows, the chunk set from its `retrieval` spans, prior results
from its `tool_call` spans, the step counter from its `purpose == "act"` `llm_call` spans — via
`core.trace` read helpers (spec §9.1);
act loop with budgets (6 steps / 8 tool calls / 90 s); G1–G7 each emitting a `guardrail` span;
confirmation flow; two declarative workflow specs whose `is_complete` predicates **require a
structured-data tool result**; three Jinja prompts with a golden snapshot **and the standing rule
that no run-varying value is rendered into a prompt — in particular the `mock_writes` id, which is a
hash over the client-minted `turn_id` and would change the `llm_cache` key on every run** (spec
§7.2, §8.5) — **and `synthesize.j2`'s evidence envelope renders the fusion weight as
`rrf="{{ '%.4f'|format(c.rrf_score) }}"`, never `score=`, so the model is not shown a ~0.032 value
under the name every other surface gives a ~0.7 `dense_score` (spec §7.1, §7.2)**;
**`tests/fixtures/demo/task2_expected.json`**, the committed **JSON payload fixture** that
`test_demo_tasks.py` and docs-check step 18 both assert against (spec §8.4 tool 8, §16.4); **and
`DEMO_EXPECTATIONS` in `tests/e2e/test_demo_tasks.py` carrying `required_tools: list[str]` and
`precedence_edges: list[tuple[str,str]]` populated from spec §18.1/§18.2's tables** — without them the
expectation record holds only counts and flags, and both documented sequences could change completely
while R10.3's only verification artifact stayed green (spec §18). *(These are two different artifacts:
the expectation records live in code, `tests/fixtures/demo/` holds the JSON payload fixture.)*

**Definition of done.**
```bash
pytest tests/unit/test_g1_evidence_gate.py tests/unit/test_g2_citation_resolvability.py \
       tests/unit/test_g3_fact_vs_rec.py tests/unit/test_g4_injection.py \
       tests/unit/test_g4_no_false_positives.py tests/unit/test_g5_sensitive.py \
       tests/unit/test_g6_identity.py tests/unit/test_g7_redact.py -q
# test_g6_identity.py here is the ORCHESTRATOR half of G6; the MCP-layer half is P5's
# tests/unit/test_g6_identity_server.py (spec §7.4).
pytest tests/e2e/test_demo_tasks.py tests/e2e/test_rag_only_makes_no_people_calls.py -q   # LLM_PROVIDER=stub
# ⚠ P7 owns the ORCHESTRATOR-LEVEL half of test_demo_tasks.py only: both tasks driven through
#   run_turn(), asserted against DEMO_EXPECTATIONS' required_tools + precedence_edges +
#   forbidden_tools, with task 2 STOPPING at outcome == "awaiting_confirmation" and NO mock_writes
#   row. The confirm -> write half is P8's: the resumed call needs a confirm_token, and confirm.mint
#   is legal only from web/api.py (spec §8.6, §9.5, §16.1).
pytest tests/integration/test_fault_mcp_down.py tests/integration/test_fault_unknown_employee.py \
       tests/integration/test_fault_empty_retrieval.py tests/integration/test_fault_ambiguous.py -q
# ⚠ P7 owns the ORCHESTRATOR-LEVEL half of these four files: drive run_turn() directly, assert the
#   returned ChatResponse and the named span (error `tool_unavailable` with exactly one re-discover
#   attempt against a DEAD PORT; the not_found -> clarify conversion; G1's guardrail span; the
#   router's needs_clarification with zero tool_call spans). NO HTTP. The HTTP-200 assertions are
#   P8's, because POST /chat is a P8 deliverable — a P7 that owned them could never close green
#   (spec §9.5). test_health_mcp_down.py is a SEPARATE P8 file with the two-uvicorn mechanism.
pytest tests/architecture -q          # agent/** imports no hrmosaic.rag.*, no hrmosaic.mcpserver
pytest tests/contract/test_prompt_golden.py tests/contract/test_no_cot.py -q
```
`test_g4_no_false_positives` runs over the **whole committed manifest** and asserts every quarantine
is a canary chunk in `security-acceptable-use` and nothing else is quarantined.

**Parallelism.** After `client.py` + `orchestrator.py` land from one author, G1–G7 split cleanly
across two subagents (G1–G3 answer-shape, G4–G7 safety), and the two workflow specs across a third.
**Commit:** `P7(agent): …`

---

### P8 — `web/`: `/chat`, `/chat/confirm`, SSE, `/health`, `/ready`, chat UI · **M** (4 h) · deps: P7 · no key

**Goal.** The four rubric-named response fields, the live span rail that makes the demo watchable, and
a `/health` that never 5xxs.

**Scope.** `web/main.py` (the written-out lifespan), `web/api.py`, `web/sse.py`,
`web/templates/{base,chat}.html`, `web/templates/partials/`, `scripts/demo_task_1.sh`,
`scripts/demo_task_2.sh`.

**Deliverables.** `POST /chat` with client-supplied ids, the **four-row privileged-options matrix**
(fail-closed on an empty token), and the `trace[]` = all-spans projection **plus the seven-row R4.3
mapping** (six literal R4.3 elements incl. *final answer basis* and *any escalation decision*, and
one clearly-labelled R4.1 row — spec §11.1); `POST /chat/confirm` as the
**only** `confirm.mint` call site, calling **`trace.reopen_turn(turn_id, awaiting_ms)`** rather than
issuing the reopen `UPDATE` itself (§4.2 sole-writer); **`tests/architecture/test_mint_sole_caller.py`**
— the §15.1 step-5 / §16.1 assertion that `confirm.mint` is referenced from exactly one module —
**authored here, not at P5**, because `web/api.py` is its only legal caller and it cannot pass before
this phase; `GET /chat/stream` SSE with grace window,
late-subscriber replay, bounded queues and `turn_resumed` — **`web/sse.py` owns the
`dict[turn_id, list[asyncio.Queue]]` and registers exactly ONE `trace.register_span_listener` during
the lifespan** (spec §11.3); `/health` (always 200, incl. the `index_model_mismatch` degradation) and
`/ready` (503 until warm; the warm-up is **one loopback `tools/call` to `search_policy_documents`**,
never a `hrmosaic.rag.embed` import, which §4.2 forbids `web/**` — spec §11.4);
the **minimal `GET /api/traces/turns/{turn_id}`** the §9.4 202 fallback and the demo scripts poll
(P9 extends it to the full page-3 view-model); the chat UI with persona picker, typed answer blocks,
citation chips deep-linking to the corpus browser, confirm card, cold-start banner and two demo buttons.
**Plus the P8 halves of two test files P7 started:** the **HTTP-200 assertions of the four
`tests/integration/test_fault_*.py` files** (P7 shipped their orchestrator-level halves; `POST /chat`
does not exist before this phase — spec §9.5), and **`tests/e2e/test_demo_tasks.py` extended through
the `POST /chat/confirm` → resumed-write path**, which is what makes "the confirmation gate blocks
task 2's write **until confirmed**" assertable at all. **Plus `tests/contract/test_app_starts.py`** —
it must live under `tests/contract/` for `make test-smoke`'s marker selection to reach it (spec §4),
and P8 marks it and `test_chat_page_renders.py` `@pytest.mark.smoke`.
**Plus `tests/fixtures/traces/archive_slow/`**, the fixture archive `test_lifespan_order` runs against
(below).
**Plus the P8 half of R-1** (spec §20): `docker run -m 512m` with the model **resident** (poll
`/ready` → serve one turn → read live `rss_mb`) and `docker run -m 512m --cpus 0.1` serving **one
stubbed six-tool-call turn**, both on `python:3.12-slim` with the repo bind-mounted so neither waits
on P11's Dockerfile, dated in `CHANGELOG.md`; **`AGENT_WALL_CLOCK_S` is re-confirmed against that
number** (P7 sets the budgets from the documented worst case; P8 measures).

**Definition of done.**
```bash
pytest tests/contract/test_chat_contract.py tests/contract/test_chat_privileged_options.py \
       tests/contract/test_chat_trace_projection.py tests/contract/test_retrieval_options_reach_the_tool.py \
       tests/contract/test_chat_page_renders.py tests/contract/test_app_starts.py \
       tests/contract/test_health.py tests/contract/test_missing_key_is_graceful.py -q
# test_app_starts.py lives under tests/contract/ (not tests/integration/) so `make test-smoke`'s
#   `-m smoke` selection can reach it (spec §4, §11.4, traceability R6.1).
# test_health.py additionally asserts the FOUR-string degradations[] vocabulary — llm_api_key_missing,
#   index_model_mismatch, mcp_disconnected, trace_store_unreachable (spec §11.4).
# test_missing_key_is_graceful covers ONLY surfaces 1-3 at P8: import succeeds; /health 200+degraded
# with llm_api_key_missing; an arbitrary prompt returns 200 with outcome=="configuration_required"
# naming LLM_API_KEY. The cache-HIT branch needs evaluation/cache/ (P10) and the dashboard-listing
# branch needs the dashboard + data/archive (P9/P10) — spec §12.3's five-surface table. P8 also marks
# test_app_starts and test_chat_page_renders @pytest.mark.smoke so `make test-smoke` picks them up.
pytest tests/integration/test_sse_spans_arrive_before_post_returns.py \
       tests/integration/test_sse_fallback.py tests/integration/test_loopback_concurrency.py \
       tests/integration/test_ready_warms_up.py tests/integration/test_confirm_resume_lifecycle.py \
       tests/integration/test_health_mcp_down.py tests/integration/test_mcp_remote_url.py \
       tests/integration/test_lifespan_order.py tests/integration/test_confirm_across_stdio.py \
       tests/integration/test_process_exit_mid_turn.py -q
# test_lifespan_order MOVES HERE from P1: it asserts web/main.py's ordering against a booted app.
#   ⚠ It runs against a FIXTURE archive, not the real one: TRACE_ARCHIVE_DIR points at
#   tests/fixtures/traces/archive_slow/ (enough records for the import to be observable) and the
#   ordering is asserted deterministically — /health 200 on the FIRST poll with
#   archive_import_progress.files_total > 0 and files_done < files_total, and /ready still 503 —
#   never by racing wall-clock. At P8 the real archive is EMPTY (demo_traces.jsonl is P11,
#   eval_traces.jsonl P10), so the import would finish in microseconds and the assertion would be
#   flaky or permanently false while gating CI step 14 for four phases (spec §8.1).
# test_confirm_across_stdio: a token minted in the parent verifies inside the stdio child, and an
#   unset CONFIRM_SECRET under MCP_TRANSPORT=stdio fails with the named message (spec §8.6, §12.3).
# test_process_exit_mid_turn is EXTENDED here to its subprocess/SIGTERM form (P1 ships the
#   store-level form).
pytest tests/unit/test_confirm_token_never_leaked.py -q
pytest tests/architecture/test_mint_sole_caller.py -q     # ★ first phase in which this can pass
pytest tests/e2e/test_demo_tasks.py tests/integration/test_fault_mcp_down.py \
       tests/integration/test_fault_unknown_employee.py \
       tests/integration/test_fault_empty_retrieval.py \
       tests/integration/test_fault_ambiguous.py -q   # the HTTP-200 halves added here (spec §9.5),
                                                      # and demo task 2 driven through confirm -> write
bash scripts/demo_task_1.sh && bash scripts/demo_task_2.sh   # against a local uvicorn, LLM_PROVIDER=stub
```

**Parallelism.** One subagent for the API + SSE, a second for the Jinja/htmx chat page against the
frozen response schema. **Commit:** `P8(web): …`

---

### P9 — Observability dashboard, 13 pages · **L** (5 h) · deps: P1+P8 · no key

**Goal.** USER.2 and USER.3 in full: every session, turn, LLM call, retrieval, tool call, guardrail
decision and final answer browsable — and the entire evaluation browsable in the same UI.

**Sub-phases (independently committable, and this is R-14's schedule mitigation):**

| Sub | Scope | Pages |
|---|---|---|
| **9a** | `/api/*` endpoints, typed Pydantic view-models, shared table + filter partials, **page 3 first** (the centrepiece the demo depends on) | 3 |
| **9b** | Overview + explorers | 1, 2, 4, 5, 6, 7, 8 |
| **9c** | MCP page (incl. the synthetic maintenance turn), corpus browser, eval pages, compare, metrics; retention job; bounded smoke-eval endpoint | 9, 10, 11, 12, 13 |

**Deliverables.** All 13 routes and their `/api/*` siblings (incl. the **full**
`GET /api/traces/turns/{turn_id}` view-model, extending P8's minimal form); Chart.js on 1, 11, 12, 13;
the page-11 metric panel with the headline aggregate strip and the `Optional[float]` +
`judged: bool` + `n_scored{}` contract **over the FOUR judged aggregates** —
`groundedness_mean`, `citation_accuracy_mean`, `partial_match_mean` and **`clarification_accuracy`**
(the ambiguous-item sub-check of spec §13.4, whose judge prompt, denominator entry and `n_scored` key
all already existed while it had no persisted field, aggregate name, threshold or dashboard surface) —
with **`cit_resolve_pre` and `cit_resolve_post` typed non-null `float` on every run**, since §13.3
defines resolvability as deterministic and zero-judge-call (spec §10.1, §11.6, §13.9); `POST /api/eval/runs` capped at
`EVAL_SMOKE_MAX_ITEMS`;
`POST /api/mcp/rediscover` (opening the synthetic **`outcome='maintenance'`** turn in a
`client_label='maintenance'` session — its own outcome value so §16.1's span census stays an honest
invariant and §13.4's escalation matrix excludes it); `POST /api/dev/reset-sandbox` (the
archive-preserving two-statement form, whose `WHERE` clause now exempts
`archive`, `eval_judge` **and** `maintenance` labels);
`POST /api/dev/retention` (token-gated, invoking `core/retention.py`'s cascading sweep and returning
rows deleted **per table**) — **all four** §11.6 write controls therefore have an endpoint, so none
ships as the dead control §11.6 forbids. Plus **page 13's `rss_mb` chart over the persisted
`turns.rss_mb_at_end` series** (an instantaneous `/health` value cannot be charted, §10.1) and
**pages 1 and 7's "estimated cost (static price table)" reading `core/models.py::MODEL_PRICES`** —
a committed constant, not a billing feed and not an env var, so §12.3's bijection is untouched.
**Plus `tests/fixtures/eval_runs/` — the committed eval-run fixture pages 11–13 are built against:
one `<run_id>.{deterministic.json,env.json,items.jsonl}` triple per variant (`baseline` judged; the
two arms with null judged fields and `judged: false`).** P9 is explicitly scheduled so pages 11–13 do
not wait on P10 and `test_dashboard_viewmodels` asserts the page-11 contract *on all three variants* —
but that fixture had no declared home: spec §16.4 enumerated four fixture directories, none holding
eval-run JSON, while `evaluation/` deliberately has no `fixtures/` and `evaluation/results/*` is a P10
deliverable. It is **superseded, never deleted**, by the real committed runs at P10/P11 (spec §16.4).

**Definition of done.**
```bash
pytest tests/contract/test_dashboard_viewmodels.py tests/contract/test_dashboard_pages.py -q
pytest tests/integration/test_reset_sandbox_preserves_archive.py \
       tests/integration/test_smoke_eval_endpoint.py tests/integration/test_retention_endpoint.py -q
pytest tests/integration/test_audit_completeness.py -q     # ★ USER.2's own verification note
```
`test_dashboard_pages.py`'s selector assertions cover **all four** write controls **on their stated
host pages** (spec §11.6): *Reset sandbox* → **page 8**, *Re-discover now* → **page 9**, *Run smoke
eval* and *Run retention* → **page 11** — asserting each is present, wired to its
endpoint, and rendered disabled-with-tooltip when `DASHBOARD_TOKEN` is unset.
`test_smoke_eval_endpoint.py` runs the container as
`docker run -e DASHBOARD_TOKEN=ci-smoke -e EVAL_TOKEN=ci-smoke -e LLM_PROVIDER=stub …` and sends both
headers — without them the endpoint answers 401 and then 403 fail-closed, so asserting 200 would be
unsatisfiable (spec §11.7, §14.2).
P9 also adds `test_missing_key_is_graceful`'s **dashboard-listing surface** (`GET
/dashboard/sessions` 200 with the archived sessions listed — spec §12.3).
`test_retention_endpoint.py` asserts `POST /api/dev/retention` is 401 without the token, returns the
per-table `deleted` counts with it, and leaves every archived and eval-linked session untouched.
`test_audit_completeness` posts a real stubbed turn and asserts the **per-turn, outcome-conditional
span census**, payload completeness for all five named span kinds, the turn record's
`final_answer`/`answer_blocks_json`/`citations_json`, and that `/chat`'s `trace[]` span ids equal the
dashboard payload's (USER.4). Pages 11–13 are built against **committed fixture JSON under
`tests/fixtures/eval_runs/`** (one triple per variant, authored here) so P9 does not wait on P10.

**Parallelism.** 9b ∥ 9c after 9a lands — two subagents, disjoint templates, one shared partial.
**Commits:** `P9a(dashboard): …`, `P9b(dashboard): …`, `P9c(dashboard): …`

---

### P10 — `evaluation/`: dataset, scorers, judges, runs, ablation · **L** (5 h) · deps: P7 (+P9 for views) · **key #1** (+#8, #9)

**Goal.** All six rubric metric families, a falsifiable ablation, validated judging, and results that
a grader can reproduce offline with no key. **P10 proves the harness end to end in `target: local`
mode; the run that is *published* (and the `comparison.json` beside it) is produced at P11 in
`target: deployed` mode — §13.2 forbids a `local` run reaching `latest.json`, and §13.9 forbids
`comparison.json` mixing targets.**

**Step 0 (before anything else).** Read the live Gemini quotas from
`https://aistudio.google.com/rate-limit` and paste the observed numbers **with the date** into
`deployed.md`.

**Scope.** `evaluation/{dataset.yaml,schema.py,judges.py,deterministic.py,runner.py,ablation.py,
kappa.py,reference_labels.yaml}`, `evaluation/cache/`, `evaluation/results/`,
`scripts/{chunk_size_sweep,gen_ablation_evidence,export_archive,gen_eval_docs}.py`,
`tests/fixtures/traces/`, `tests/fixtures/eval_runs/`, **`.github/workflows/eval.yml`** (§15.2 — the
harness's own dispatch surface; it lands here, not at P11, because P10's ablation gate is what
exercises it). ⚠ **`eval.yml` runs `python scripts/gen_eval_docs.py`, which is FILE- and
POINTER-TOLERANT** (spec §15.2): it rewrites `design-and-evaluation.md`'s generated blocks only if
that file exists (it is a **P12** deliverable) and is a no-op-with-warning when
`evaluation/results/latest.json` is absent (written first at **P11**), so this phase's dispatch does
not fail on artifacts two phases away. **The hard `target == "deployed"` / `variant == "baseline"`
assertion is unchanged and stays where it already lives — `docs-check` step 18, wired at P12** — and
the workflow's branch carries `design-and-evaluation.md` **only once that file exists**, so there is
no deadlock at P10 or P11 (step 18 does not exist yet).

**Deliverables.** The 26-item dataset — **seven categories, 7/5/6/3/3/1/1**: `simple_policy` 7,
`multi_doc` 5, `tool_task` 6, `ambiguous` 3, `out_of_scope` 3, `unsafe_action` 1, **`sensitive` 1** —
with **absolute dates only**, gold facts resolving
to ledger keys, the two mirrored workflow items `remote-004` and `pto-003` (**`pto-003` carries
`check_policy_compliance` in `expected_tools`, matching the mirror table, and a non-empty
`requires_tool_results` — as every `tool_task` item must**), **`inj-001` as a `simple_policy` item
that genuinely retrieves from `security-acceptable-use`** (as an `out_of_scope` item it made zero
tool calls by design, so nothing was ever quarantined and G4 had no eval evidence at all), **one
`sensitive` HR-case-triage item with `expected_behavior: escalate`** (without it no item carries that
gold label, the 5×5 matrix's `escalate` row and column are structurally empty, `MissedRefusalRate`'s
denominator collapses to the refuse items, and guardrail G5 is never exercised by the evaluation),
**≥ 3 `multi_doc` items
each carrying ≥ 3 distinct `expected_docs`** (the §13.1 coverage claim, now asserted) and the three
§13.5 cold-probe items **`pto-001`, `remote-001`, `benefits-001`, all `category: simple_policy`**
(without the assertion a rename silently leaves `n_cold = 0`); every deterministic
scorer including all §13.3/§13.4 edge cases; the four judge prompts through `CachedAdapter`;
the runner with `EVAL_TARGET_BASE_URL`, the three `cold_probe` re-runs and the coldness assertion;
`ablation.py` with the same-target/same-dataset assertion **and** the workflow-moved assertion;
`eval.yml` (`workflow_dispatch` only, the `schedule` block committed disabled) with its `target` /
`variants` / `judge` inputs, the two post-run gates (`cit_resolve_post == 1.00`, the workflow-moved
assertion) and the results-by-PR flow;
`reference_labels.yaml` authored by an **independent Opus subagent** with its `protocol` block;
`kappa.py`; the zero-LLM chunk-size sweep; `export_archive.py` producing `data/archive/eval_traces.jsonl`;
the golden trace fixtures (≥ 1 carrying `mock_writes` + `llm_messages` + `pending_actions`);
`MIN_EVIDENCE_SCORE` calibrated from the observed distribution **starting from the selftest score P4
recorded in `CHANGELOG.md`**; one **real** provider exchange per
demo task recorded as a stub fixture (R-13); **regeneration of
`tests/fixtures/eval_runs/eval_results_sample.*` from the first real run, followed by re-running P1's
`test_archive_roundtrip` against it, and a refresh of P9's three per-variant view-model fixtures**
(spec §13.6, §16.4); and **`evaluation/results/replay_target.json`** naming
P10's own `target: local` `baseline` run. **P10 does NOT write `latest.json`** — spec §13.2 reserves
that published pointer for the P11 `deployed` run, and the push-path replay test reads
`replay_target.json` precisely so step 14 can be green at P10 without a `deployed` run existing.

**Definition of done.**
```bash
pytest tests/unit/test_dataset.py tests/unit/test_scorer_edge_cases.py \
       tests/unit/test_cold_probe_excluded.py tests/unit/test_run_id.py \
       tests/unit/test_eval_ordering_deterministic.py -q
# test_dataset asserts: n == 26; all SEVEN category labels present with the 7/5/6/3/3/1/1 counts;
#   EVERY ONE of the five expected_behavior classes (answer|clarify|confirm|refuse|escalate) has >= 1
#   item — the clause that keeps the escalation matrix's gold rows non-empty; inj-001 present as
#   simple_policy with security-acceptable-use in expected_docs; every tool_task item's
#   expected_end_state carrying a non-empty requires_tool_results; no relative dates (spec §13.1).
pytest tests/unit/test_action_safety_gate.py -q                  # must be 1.0
pytest tests/integration/test_eval_replay_from_cache.py -q       # offline, keyless, byte-identical .deterministic.json;
                                                                 # reads the run_id from replay_target.json (NOT latest.json);
                                                                 # reconstructs target/target_base_url/fixed_now from the
                                                                 # committed .env.json and ASSERTS config_sha rather than
                                                                 # recomputing it (a re-derived config would carry
                                                                 # target="local" and never match — spec §13.6);
                                                                 # >=1 judge-purpose cache hit, back-dated entry still served
pytest tests/architecture -q                                     # now asserts scanned_roots == {"src","evaluation"}
                                                                 # (P1's skipped root is live from here — spec §4.2)
pytest tests/contract/test_missing_key_is_graceful.py -q         # P10 adds the cache-HIT surface (needs evaluation/cache/)
EVAL_TARGET_BASE_URL=http://127.0.0.1:8000 python evaluation/ablation.py   # ★ target: local — all three
                                                                 # variants local; committed as DETERMINISM evidence
                                                                 # only, never promoted to latest.json (§13.2).
                                                                 # Asserts same target + dataset_sha; workflow-moved
python scripts/chunk_size_sweep.py
python evaluation/kappa.py                                       # reference-vs-judge Cohen's kappa reported
pytest tests/integration/test_archive_roundtrip.py -q            # re-run after regenerating
                                                                 # tests/fixtures/eval_runs/eval_results_sample.*
                                                                 # from this phase's first real run (spec §13.6)
```
⚠ **A CALENDAR-DAY BOUNDARY IS REQUIRED between this dispatch and P11's.** Each sweep is ~700
provider calls (~150 agent × 3 variants + ~247 judge on `baseline`), so P10 + P11 back to back is
~1,400+ calls against a `[medium]` ~1,000 RPD — the exact mid-sweep exhaustion R-5 claims to have
mitigated, landing on the day the published results must be produced. The boundary is the normative
mitigation (spec §13.9); P11 step 0 re-checks it. `JUDGE_API_KEY` (a second Cloud project, §5 G6
item #9) remains **strongly recommended** on top of it, because it removes judge/agent contention
*within* each sweep.
Plus the post-run gate `cit_resolve_post == 1.00` over items with ≥ 1 citation, with
`blocks_dropped_by_g2` reported separately.

**Parallelism.** Dataset authoring ∥ scorer implementation ∥ reference-label authoring (the labeller
**must** be a separate session, blind to judge output, for the κ claim to be honest).
**Commit:** `P10(eval): …`

---

### P11 — Deployment · **S** (3 h of agent attention; **≈ 2.5 h additional unattended wall-clock**) · deps: P9+P10 · **keys #2, #3, #4**

**Goal.** A live, shareable, $0 URL whose CI-gated deploy is provable, plus the single `deployed`-mode
`eval.yml` dispatch that supplies every published figure — headline metrics *and* the ablation.

⚠ **Sizing note.** The **S (3 h)** figure is **agent-hours**, per §2.5 — it does *not* cover the
workflow's own wall clock. The published `eval.yml` dispatch is ~700 sequential provider calls behind
a 10 RPM token bucket (~70 min of pacing floor alone) plus three `cold_probe` re-runs each preceded
by `EVAL_COLD_IDLE_S = 1000 s` of deliberate idling (~50 min), so budget **≈ 2.5 h of unattended
elapsed time** on top, during which the agent is free. The ≈ 51 h project total is unchanged because
it likewise counts agent-hours.

**Step 0.** **First, confirm a CALENDAR-DAY BOUNDARY has passed since P10's `eval.yml` dispatch**
(spec §13.9, R-5: two ~700-call sweeps must not share one RPD window). Then re-verify in the live
dashboards and paste the observed values **with dates** into
`deployed.md`: Render (Docker on Hobby, bandwidth, build RAM, **the 500 build-pipeline minutes per
month Hobby allowance — every push to `main` from here fires a build that bakes a 64 MB model and
rebuilds the index, and exhausting it blocks the `deploy_only: true` republish the plan depends on**,
**and the documented HTTP request/idle
timeout**) and the Turso free-tier figures. **Cap `AGENT_WALL_CLOCK_S` below the observed Render
timeout**; if that timeout is < 90 s, ship the documented `202 Accepted` + SSE fallback.

**Scope.** `Dockerfile`, `render.yaml`, `.github/workflows/ci.yml` (`docker`, `fresh-clone`, `deploy`
jobs), `scripts/{provision_render,provision_turso,wait_for_deploy,
smoke_deployed,check_render_hours,measure_cold_start}.py`, `docs/evidence/`.
(`.github/workflows/eval.yml` itself lands at **P10**; P11 *dispatches* it.)

**Deliverables.** The single-stage Dockerfile (`sh -c` CMD for `${PORT}`, `PYTHONPATH=/app/src:/app`,
`ARG GIT_SHA`, model baked, index built with `--verify-manifest`, index self-test); `render.yaml`
**carrying `- { key: NOW_OVERRIDE, value: "2026-09-08T12:00:00Z" }` in `envVars` — the graded instance
runs on the frozen `clock.now()` like every other surface. Without it the server computes
`check_pto_balance.remaining_days`, `check_policy_compliance`'s dates and
`create_mock_hr_ticket.created_at` at the live wall clock, so `pto-003`'s documented 13.5 is wrong
from 2026-10-01, and the published `deployed` run's recorded `messages` can never match the committed
`evaluation/cache/*.llm_cache.jsonl` that the push-path replay test reproduces once
`replay_target.json` is repointed here (spec §13.6, §14.1). It does NOT freeze
`clock.wall_ms()`/`monotonic_ms()`, so uptime, cold/warm classification and latency stay real**;
**`scripts/check_render_hours.py` warning on BOTH projections — instance-hours above 600 of 750 and
build minutes above 400 of 500 (spec §14.1, R-10)**;
unattended provisioning of Render + Turso + all `gh secret set` calls; **one `eval.yml` dispatch with
`target: deployed` covering all three variants** (`baseline` judged; `dense_only_k2` and
`no_structured_tools` deterministic-only, per §13.9's quota scoping) incl. the three `cold_probe`
re-runs — this single dispatch is what produces `latest.json` **and** `comparison.json`, so §13.9's
same-target assertion holds by construction; `export_archive.py` against the two recorded
demo sessions → `data/archive/demo_traces.jsonl`; measured cold-start numbers; the **three evidence
screenshots** captured by Claude Code with the browser tool and committed under `docs/evidence/`.
**This dispatch writes `evaluation/results/latest.json` for the first time** (spec §13.2's published
pointer) **and repoints `evaluation/results/replay_target.json` at that deployed `baseline` run**, so
the push-path replay test from here on reproduces the published artifact.

**Definition of done.**
```bash
docker build -t mosaic . && docker run -m 512m -p 8000:8000 mosaic   # /ready 200 -> one turn -> rss_mb < 420
docker run -m 512m -e PORT=10000 -p 10000:10000 mosaic               # /health mcp.connected == true
python scripts/smoke_deployed.py "$DEPLOYED_URL"                     # 200, mcp.connected, git_sha != "dev",
                                                                     # app.clock_frozen == true and
                                                                     # app.clock_now == "2026-09-08T12:00:00Z",
                                                                     # archive_manifest_sha matches local
python scripts/measure_cold_start.py "$DEPLOYED_URL"
gh api repos/seantmalone/quantic-mosaic/branches/main/protection | jq '.required_status_checks.contexts'
ls docs/evidence/ci-deploy-skipped.png docs/evidence/mcp-discovery-page.png docs/evidence/mcp-discovery-4-tools.png
```
Plus, on the eval dispatch itself:
```bash
python evaluation/ablation.py                                        # green: same config_json.target + dataset_sha
                                                                     # across all three runs; workflow-moved assertion
jq -r '.runs[].config_json.target' evaluation/results/comparison.json  # "deployed" x3, no other value
```
Plus: `latest.json` names a `target: deployed`, `variant: baseline` run; that run produced rows with
**non-null `sessions.eval_run_id`** (proving the eval token was configured); **that run's
`eval_runs.config_json.fixed_now` equals the deployed instance's `/health.app.clock_now`** — i.e. the
instant the served tool results were actually computed at, which is the assertion that ties the
published figures, the committed cache keys and the frozen deployment together (spec §13.6); and the R8.4 evidence
pair exists — a failing PR to `main` (genuinely unmergeable under branch protection) **and** a
`workflow_dispatch` run on `main` with `FORCE_TEST_FAILURE=1` whose deploy-job skip reason reads
**"dependent job failed"**, not "if condition not met".

**Parallelism.** None (a single deploy identity; concurrent provisioning would race).
**Commit:** `P11(deploy): …`

---

### P12 — Documentation, demo prep, publish · **M** (4 h) · deps: P11 · no key

**Goal.** Every graded document present, generated where possible, and asserted by a test — plus a
time-boxed demo script that ticks every DEMO.* item.

**Scope.** `README.md`, `design-and-evaluation.md`, `ai-tooling.md`, `deployed.md`,
`NEEDS-FROM-USER.md`, `static/vendor/LICENSES.md`, **`docs/demo-script.md`**,
**`docs/pre-submission-checklist.md`**.

**Deliverables.** README's four headings + `## Third-party components` + the three link lines with the
placeholders **retired**; `design-and-evaluation.md` with the mermaid diagram (all seven components),
the **ten `###` R10.1 justification subsections**, **all eight `##` DOCS.3 subjects** (8a and 8b
generated by `gen_eval_docs.py`), the facts/sources/confidence table, the judge-validation methodology
naming the labeller, both κ values, the rejected alternatives and both demo sequences;
`ai-tooling.md` with `## What worked well`, `## What did not work` and the DOCS.9 ownership
disclosure **naming the same model as the commit trailers** (§2.4); `deployed.md` with all five
required headings; **`docs/demo-script.md`** — the §18.3 timed `## Segment table`, the standing
webcam-overlay production note, and a **per-task five-element DEMO.6 sub-checklist**; and
**`docs/pre-submission-checklist.md`** — one checkbox line per `DEMO.1`–`DEMO.7` and
`SUB.1`–`SUB.3`, plus `- [ ] no TBD-before-submission remains in README.md` and
`- [ ] the quantic-grader invite was sent and accepted`. Those two files are the **only**
verification artifact eight traceability rows have (DEMO.2–DEMO.7, SUB.1, SUB.3), so
`test_docs_completeness.py` asserts both exist and that the checklist carries a line for every id
(spec §15.1).

**Definition of done.**
```bash
python scripts/gen_tool_schemas.py && python scripts/gen_eval_docs.py && python scripts/corpus_stats.py
git diff --exit-code                                        # docs-check: zero drift
pytest tests/contract/test_docs_completeness.py -q          # 10 R10.1 + 8 DOCS.3 + README + deployed.md x5 +
                                                            # LICENSES + demo-script.md + pre-submission-checklist.md
grep -c 'TBD-before-submission' README.md                   # must be 0
git log --format=%b | grep Co-Authored-By | sort -u         # exactly one value, matching ai-tooling.md's disclosure
bash scripts/demo_task_1.sh "$DEPLOYED_URL" && bash scripts/demo_task_2.sh "$DEPLOYED_URL"
```
**Final step of the whole build:** after the eval-results PR is merged, dispatch `ci.yml` with
`deploy_only: true` and verify the live `/health.trace_store.archive_manifest_sha` equals the locally
computed manifest sha — `paths-ignore` means the merge itself triggers nothing.

**Parallelism.** Three subagents, one document each (`design-and-evaluation.md` is the long pole).
**Commit:** `P12(docs): …`

---

## 5. Gates requiring the user

Seven tracked gates. **G1 is fully scripted and needs nothing from the user** (§19.1 item 5), so six
actually reach a human: **five are a single paste or click taking under 10 minutes, and G7 (record +
submit) is the one substantial human task, budgeted at 60–90 minutes including retakes** — the only
irreducible human bottleneck in the plan, to be scheduled rather than squeezed in. (G6 is under
10 minutes for items #8–#10; its *optional* item #11 adds ~20 minutes of label adjudication, §19.2.)
**Nothing in P0–P9 blocks on any of them** — the build never idles.

| Gate | When requested | When actually needed | What Sean does (time) | What Claude Code does while waiting |
|---|---|---|---|---|
| **G1 — Repo public + `quantic-grader`** (§19.1 item 5) | **P0** | pre-submission (invite) | **Nothing.** The repo is already public (verified 2026-09-08), so there is no visibility change. The grader invite is scripted: `gh api -X PUT repos/seantmalone/quantic-mosaic/collaborators/quantic-grader`, run by Claude Code on the already-authenticated gh 2.96 session at **P12**. The grader's side (**accepting the invite**) is a person's action and is folded into **G7**. | Re-asserts `gh api repos/seantmalone/quantic-mosaic \| jq .private` → `false` at P0; sends the invite at P12 and reads back `gh api repos/seantmalone/quantic-mosaic/collaborators/quantic-grader/permission`. |
| **G2 — Render account + install the Render GitHub App** (item 2) | **P0** | **P11** | Open `https://github.com/apps/render/installations/new`, sign in / sign up (no card), grant access to `seantmalone/quantic-mosaic`. Browser-only: **no API can install a GitHub App**. | P0–P10 in full. `make docker-run` proves the exact image locally under `-m 512m` with no host at all. |
| **G3 — Turso account + Platform API token** (item 3) | **P0** | any time after **P1**; hard-needed at **P11** | `https://turso.tech` → GitHub SSO (no card) → create a **Platform API token** → paste to Claude Code. | `scripts/provision_turso.py` then does database creation, scoped-token minting, `gh secret set` and Render env-var population unattended. Until then `SqliteStore` + the committed archive are the fallback. |
| **G4 — Google AI Studio key → `LLM_API_KEY`** (item 1) | **P0** (so P6's gate can run early) | **P6 gate** (deferrable) / hard at **P10** | `https://aistudio.google.com/apikey` → sign in → *Create API key* → paste to Claude Code. Free, no card. | P0–P9 build and pass CI entirely on `LLM_PROVIDER=stub`. If it arrives late, P6 ships the prompted-JSON fallback and the live gate runs at P10 step 0. ⚠ **This key carries BOTH `eval.yml` sweeps, so P10's and P11's dispatches must fall on DIFFERENT CALENDAR DAYS** (~700 calls each against a `[medium]` ~1,000 RPD — spec §13.9, R-5). |
| **G5 — Render API key** (item 4) | **P10** | **P11** | Render dashboard → Account Settings → API Keys → *Create* → paste. | `provision_render.py` then creates the service, populates env vars, reads back the deploy hook and sets every GH secret. Fallback: ~15 min of manual Blueprint clicking per iteration. |
| **G6 — Optional upgrades** (items 8–11) | **P10** | before **P10**'s judged run (8, 9, 10); before **P12** (11) | *(~6 min for #8–#10; **+~20 min** for #11)* #8 Groq key (`https://console.groq.com/keys`, ~2 min) · #9 second Gemini key from a *different* Cloud project (~2 min — **strongly recommended: it removes judge/agent quota contention *within* each sweep, on top of the mandatory calendar-day boundary between the P10 and P11 dispatches, spec §13.9**) · #10 Anthropic key (~$5) · #11 ~20 min adjudicating 8 groundedness labels. | Each has a documented degradation: judge stays in-family (κ still published, named *reference-vs-judge*); judged metrics stay scoped to `baseline`; `AnthropicAdapter` stays MockTransport-tested; labels stay model-authored **and are named as such**. |
| **G7 — Record the demo + submit** (items 6, 7) | **P12** | after **P12** | **★ Budget 60–90 min** (7–10 min of footage, plus setup, retakes, upload and submission — the one gate that is not a single paste). Accept the `quantic-grader` collaborator invite (G1's scripted half already sent it). Follow `docs/demo-script.md` (7–10 min, webcam overlay throughout, ID held ≥ 3 s at ~0:15, both tasks one-click). Then paste the video link into `README.md`'s `Demo video:` line and submit the two links via the Quantic dashboard. | Pre-stages both link lines at the top of `README.md`; warms both demo prompts through the cache; verifies the live URL, the dashboard and the eval pages; runs the pre-submission checklist. |

**`NEEDS-FROM-USER.md`** is created at P0 with the **minimum viable set stated at the top — one
Google AI Studio key, a Render account, a Turso token, all free and card-free** — and is updated at
every phase boundary. **It carries a time estimate per gate**, so the user can schedule the only
substantial one: G2–G5 at ~2–5 minutes each, G6 at ~6 minutes (+~20 for optional item #11), and
**G7 at 60–90 minutes** (recording, retakes, upload, submission). G1 is listed as *scripted — no
user action*, with the grader-invite acceptance folded into G7. This file is USER.1's mechanical
artifact, and "stays minimal" is measured against it.

---

## 6. Verification strategy

### 6.1 Per phase

| Phase | Primary verification instrument |
|---|---|
| P0 | Lint + empty-suite CI green on push **and** PR; `.env.example` ↔ `Settings` bijection; vendored-asset sha256; branch-protection API read-back |
| P1 | Store parity across both backends; **AST sole-writer** over `[src, evaluation]` with a *skipped* missing root; archive round-trip / idempotency / update **incl. eval-results tier 3**; cascading-retention orphan check; **store-level** process-exit recovery; span-listener and id-uniqueness tests; the **two** dated P1 R-1 measurements in `CHANGELOG.md` (bare-container RSS + `vec_version()`; the model-resident and 0.1-CPU numbers are P8's) |
| P2 | `git diff --exit-code corpus/` after regeneration; ledger resolution over scoped numerics; `round(measured) == stated` pages; canary-in-exactly-one-chunk |
| P3 | JSON-Schema validation; PII grep; generator byte-idempotency; **anchor ids `E1002`/`E1007`/`E1042`/`E1108` present and all 24 matching `^E1[0-9]{3}$`**; PTO arithmetic at the frozen clock (`E1042` hired **2022-11-13**, 45 months, `13.5`). The accrual-band cross-check is the **P2 ∥ P3 join gate** run by the main session, not a P3 gate (§3) |
| P4 | Byte-identical chunk manifest (`heading_path` joined with `" > "` before hashing; the row now carries `text`); **the `query_embed` asymmetry gate**; `test_chunking` (heading-path propagation + overlap); dense-score scale; `min_dense_score` ≠ `rrf_score`; exact-`k` filter-then-truncate; per-format ingest report; the **twelve-column `index_meta`** plus the three non-settings comparison values (`EXPECTED_DISTANCE_METRIC`, `QUERY_CONVENTION`, `available_vector_backend()`); **unconditional `test_vector_backend_parity`** over both `vecbackend.py` implementations; `test_fake_embedder`; `test_corpusread_contract` (moved here with `core/corpusread.py`); `check_facts.py --manifest`; `--selftest`'s fixed query/expected pair gated on `SELFTEST_MIN_DENSE_SCORE`; the manifest is genuinely git-tracked |
| P5 | MCP 2.x API shape; `REQUIRED_TOOL_NAMES ⊆ tools/list`; discovery + call on **both** transports; token-free `CONFIRMATION_REQUIRED`; `FORBIDDEN_IDENTITY` incl. tool 4; generated schemas diff-clean; async-handler AST |
| P6 | Both wire shapes normalised; exactly one span per call; limiter burst + shared bucket; strict-schema emission; cache-key stability across days; **live provider probe** |
| P7 | Seven guardrail suites; the four fault injections at the **orchestrator level** (no HTTP — their HTTP-200 halves are P8's); both demo sequences under the stub against `required_tools` + `precedence_edges`, task 2 stopping at `awaiting_confirmation`; RAG-only makes zero people-tool calls; no-CoT; import boundaries |
| P8 | `confirm.mint` sole-caller AST test (first phase where it can pass); the four fault injections' **HTTP-200 halves** and `test_demo_tasks`' confirm→write half; `test_lifespan_order` against the `archive_slow/` fixture; `/chat` contract for RAG-only **and** tool-using; four-row privileged-options matrix; `trace[]` = spans-of-turn + the **seven-row R4.3/R4.1 mapping**; SSE-before-POST-returns; loopback concurrency; confirm resume lifecycle (`reopen_turn`); lifespan order; confirm-token across a stdio spawn; keyless graceful degradation **surfaces 1–3**; the **model-resident RSS and 0.1-CPU** R-1 measurements |
| P9 | View-model schema contracts (page 11's `judged: bool` / `n_scored{}` over the **four** judged aggregates — incl. `clarification_accuracy` — with `cit_resolve_pre`/`_post` non-null on every run), against the committed `tests/fixtures/eval_runs/` triples; page renders; all **four** §11.6 write controls present, wired and disabled-with-tooltip on their stated host pages (8, 9, 11, 11); **`test_audit_completeness`** round trip; reset-sandbox preserves the archive; retention endpoint token-gated and archive-safe; smoke-eval endpoint against the built image |
| P10 | Dataset shape (seven categories, 7/5/6/3/3/1/1; all five `expected_behavior` classes populated; `requires_tool_results` on every `tool_task` item) + no relative dates; every scorer edge case; **action-safety gate = 1.0**; offline keyless replay byte-identity incl. a judge-purpose hit; ablation same-target + workflow-moved assertions; κ |
| P11 | `docker run -m 512m` RSS < 420 with the model resident; injected-`PORT` health; live smoke incl. `git_sha != "dev"`, `app.clock_frozen`/`app.clock_now` and `archive_manifest_sha`; the published run's `config_json.fixed_now` equal to the deployed `/health.app.clock_now`; non-null `sessions.eval_run_id`; the R8.4 evidence pair; three committed screenshots |
| P12 | `docs-check` zero-diff across three generators; ten `###` + eight `##` headings; README link lines with no placeholder; `deployed.md`'s five headings; `LICENSES.md` completeness; both demo scripts against the live URL |

**Which phase wires which §15.1 `test` step.** Job `test` has **21 ordered steps** (`1, 1b, 1c, 2–19`
— §15.1; the ids are deliberately non-contiguous, so the count is
`1 + 1b + 1c + eighteen of 2–19 = 21`, which is also the number of rows in the spec's step table).
**Step `1c` was formerly `7c`**: full-corpus index provisioning moved *ahead of* `pytest tests/unit`
(step 6), because several `tests/unit` tests require the real index — `test_rules_engine`,
`test_g2_citation_resolvability`, `test_chunk_citation_fields`, `test_retrieval_filters`,
`test_min_dense_score_is_not_rrf` — and with the build after step 6 the push path is red from P4/P5
onward (spec §6.5, §15.1). **P0 lands steps 1, 1b, 2 and 3 plus the two empty suite steps 6 and 13 —
six in all**; every other step is added by the phase that introduces its tests, in that phase's own
commit:

| §15.1 step(s) | What it runs | Added by |
|---|---|---|
| 1, 1b, 2, 3 | install; fastembed model cache + conditional download; `ruff`; `gitleaks` | **P0** (skeleton) |
| 6 | `pytest tests/unit` | **P0** creates the step (`test_vendor_asset_hashes`); **every later phase extends the suite in place** |
| 13 | `pytest tests/contract` | **P0** creates the step (`test_env_example_covers_settings`, plus `test_docs_completeness` carrying **only P0's three functions** — see the sub-table below); extended in place by **P5, P8, P9, P10, P11, P12** |
| 5 | `pytest tests/architecture` | **P1** creates the step (sole span writer over `[src, evaluation]` with a **skipped** missing root, clock sole-caller); extended in place by **P4** (embed call site, `batch_size=EMBED_BATCH_SIZE == 8`, no `parallel=`), **P5** (async handlers, no `mcp/__init__.py`, mock-writes ownership), **P7** (import boundaries), **P8** (`test_mint_sole_caller.py` — see P5/P8 below), **P10** (`scanned_roots == {"src","evaluation"}` once `evaluation/` exists) |
| 14 | `pytest tests/integration` | **P1** creates the step (archive round-trip incl. the eval-results tier-3 **triple**, retention, **trace-level** process-exit); extended in place by **P5**, **P7** (the four `test_fault_*.py` files at the **orchestrator level**, no HTTP), **P8** (the **HTTP-200 halves** of those same four files, plus `test_health_mcp_down.py` — a *distinct* file with the two-uvicorn mechanism — `test_lifespan_order` against the `archive_slow/` fixture, `test_confirm_across_stdio` and the subprocess form of `test_process_exit_mid_turn`), **P9, P10** |
| 17 | corpus + data checks | **P2** creates the step with `check_facts.py --ledger` + `corpus_stats` + topic map; **P3** adds `pii_check.py` and `--accrual-bands`; **P4** adds `--manifest` (the canary-in-exactly-one-chunk assertion, which needs the P4 manifest); **P7** adds `test_g4_no_false_positives` over the committed manifest |
| 1c, 7, 8 | **full-corpus index provisioning (`ingest --verify-manifest`, placed immediately after 1b and BEFORE step 6 — spec §6.5, §15.1)**; chunk-manifest determinism; mini-corpus ingest smoke. Step 1c has **no** `EMBED_PROVIDER=fake` fallback (`--verify-manifest` refuses it, exit 2): cache restore + two retries, then a loud failure. The fake-embedder fallback belongs to step 8 alone, which does not pass the flag | **P4** |
| 4 | `test_mcp_api_shape` | **P5** |
| 10, 11 | MCP discovery (stdio) and tool call (stdio + mounted HTTP) | **P5** |
| 16 | `pytest tests/e2e` under `LLM_PROVIDER=stub` | **P7** creates the step (both demo tasks through the orchestrator against `DEMO_EXPECTATIONS`' `required_tools` + `precedence_edges` + `forbidden_tools`, task 2 stopping at `awaiting_confirmation`); **P8** extends it through the `POST /chat/confirm` → resumed-write path, which is what makes the *"until confirmed"* clause assertable (spec §9.5, §16.1) |
| 9, 12, 19 | `test_app_starts`; `test_mcp_remote_url`; the RSS-with-model-resident gate (all three need a bootable `web/` app) | **P8** — P1 owns the `rss_mb` reader itself (`test_rss_reader`, step 6) |
| 15 | action-safety gate + `test_confirm_token_never_leaked` | **P8** authors `test_confirm_token_never_leaked`; **P10** wires the step, because the gate scores over `tests/fixtures/traces/` **and `data/archive/*.jsonl`**, the latter of which does not exist before P10. ⚠ `evaluation/results/*.deterministic.json` is **not** an input: its four clauses assert over `tool_call` / `confirmation` spans and `mock_writes` rows, and that file carries only metric values and per-item scores — no trace records at all (spec §13.6, §15.1 step 15) |
| 18 | `docs-check` | **P12** |
| jobs `docker`, `fresh-clone`, `deploy` | — | **P11** |

**Sub-table: who authors which assertion group inside the two files that are built up in place.**
Both are created at P0 and wired into step 13 at P0, so authoring them whole at P0 would keep the
deploy-gating push path red for a dozen phases.

| File | Assertion group | Authored by |
|---|---|---|
| `test_docs_completeness.py` | `test_readme_link_lines`, `test_readme_required_headings`, `test_vendor_licenses_complete` | **P0** |
| | `test_deployed_md_headings` (the five headings + their content) | **P11** |
| | `test_design_doc_headings`, `test_ai_tooling_sections`, `test_demo_payload_containment`, `test_demo_script_and_checklist` | **P12** |
| `test_missing_key_is_graceful.py` | surfaces 1–3: import succeeds; `/health` 200+degraded; an arbitrary prompt → 200 `configuration_required` | **P8** |
| | surface 4: a committed demo prompt answers `cache_hit=true, keyless=true` (needs `evaluation/cache/`) | **P10** |
| | surface 5: `GET /dashboard/sessions` 200 with archived sessions (needs the dashboard + `data/archive/`) | **P9** |

A phase whose row is empty for a step must not add that step early: a step whose test does not yet
exist turns the push path red for every phase in between (see P5 ↔ P8 on `test_mint_sole_caller.py`).

### 6.2 Continuous — from the phase that introduces it (§6.1)

There is no gate that runs "every phase, every push" from P0: §6.1 is normative and it warns that
adding a step before its tests exist turns the push path red for every phase in between. So:

| From | Runs on every push thereafter |
|---|---|
| **P0** | `ruff check` + `ruff format --check`; `gitleaks` over full history; the growing `tests/unit` and `tests/contract` suites |
| **P1** | `tests/architecture`; the growing `tests/integration` suite |
| **P2 → P4** | the corpus/data checks, mode by mode (`--ledger` at P2, `pii_check` + `--accrual-bands` at P3, `--manifest` at P4); from **P4**, step **1c**'s full-corpus index provisioning, which runs before `pytest tests/unit` and is what every index-backed unit test depends on |
| **P7** | `tests/e2e` under `LLM_PROVIDER=stub` |
| **P8** | the **RSS < 420 MB with the model resident** gate (step 19) |
| **P10** | the **action-safety 1.0 gate** (step 15) — it scores over `tests/fixtures/traces/` and `data/archive/*.jsonl`, and only the first exists before P10 |
| **P12** | `docs-check` (step 18) |

Everything on the push path is **key-free, deterministic, and offline after the first cache fill**.

---

## 7. End-to-end acceptance checklist (mirrors the rubric level-5 bullets)

Signed off in P12 before submission. Each row names the artifact a grader can open.

| # | Rubric level-5 bullet | Passes when | Artifact |
|---|---|---|---|
| 1 | Outstanding deployed agentic HR system with cited, grounded responses | Groundedness ≥ 0.92 mean; `cit_resolve_post` = 1.00 over items with ≥ 1 citation; run-level `cit_resolve_pre` ≥ 0.95; ≥ 0.90 strict-pass — **all from the single `deployed` baseline run** | `evaluation/results/<run_id>.deterministic.json` + `latest.json` + dashboard pages 11–12 |
| 2 | MCP fully functional, clear traces, graceful errors | 9 tools discovered via real `tools/list`; every turn's `tools/call` on the wire; 4 fault-injection tests green | `mcp_discovery` + `tool_call` spans; `/dashboard/mcp`; `docs/evidence/mcp-discovery-page.png` |
| 3 | Two end-to-end agentic tasks, multi-step, RAG + mock data | Each ≥ 4 tool calls, ≥ 1 retrieval, ≥ 1 structured-data tool; task 2 writes behind a confirmation gate | `tests/e2e/test_demo_tasks.py` (two per-task expectation records) + `data/archive/demo_traces.jsonl` + the video |
| 4 | Excellent RAG ingestion, indexing, retrieval, citations, guardrails | Byte-identical rebuild; hybrid retrieval; 7 guardrails green; tuned `k` demonstrated | `test_chunking_deterministic`, guardrail suites, `dense_only_k2` + `chunk_size_comparison.json` |
| 5 | Excellent architecture, clear separation | Six components in six packages, **zero cross-layer imports** | `tests/architecture/test_import_boundaries.py` + the mermaid diagram |
| 6 | Free-tier deployment fully functional, env vars + cold start documented | Live URL 200; `/health` + `/ready`; every env var in `.env.example` **and** `deployed.md`; measured cold/warm numbers | `deployed.md`, `render.yaml`, `scripts/measure_cold_start.py` |
| 7 | CI/CD on push/PR with build/start + MCP tests, deploy gated | Green on both events — the `pull_request` half is the **recorded P0 evidence run** (throwaway branch → PR → green `test` → URL in `CHANGELOG.md` → PR closed), since every phase otherwise commits straight to `main`; `test_app_starts`; `test_mcp_tool_discovery`; `deploy` declares `needs: [test, docker]`; a recorded red run with deploy skipped for **"dependent job failed"** | `gh run list`; the P0 `pull_request` run URL in `CHANGELOG.md`; `docs/evidence/ci-deploy-skipped.png` |
| 8 | Excellent evaluation across all six metric families | 26 items; groundedness, citation accuracy, tool selection, workflow completion, escalation/safety, latency p50/p95 cold vs warm; ablation; κ | `evaluation/results/`, `evaluation/REPORT.md`, dashboard pages 11–13 |
| 9 | Excellent docs + demo meeting every DEMO.* item | `docs-check` green; video 7–10 min, on camera throughout, ID shown, both tasks live, design/deploy/CI/eval walkthroughs | `design-and-evaluation.md`, `README.md`, `ai-tooling.md`, `deployed.md`, the video link |
| 10 | **USER.2/3/4** — full audit logs + eval in the dashboard, one trace model | Every record type present for a freshly executed chat; all six metric families + cold/warm p50/p95 + ablation browsable; `/chat` trace, dashboard and eval report derive from one `trace_id` | `test_audit_completeness`, `test_dashboard_viewmodels`, `/dashboard/sessions/{id}` |
| 11 | **USER.1** — autonomous buildability | `NEEDS-FROM-USER.md` lists only the seven human gates; every other step is a scripted command; CI reproduces build → index → test → eval with no manual step | `NEEDS-FROM-USER.md`, `.github/workflows/*.yml` |

---

## 8. Risk register (triggers and fallbacks)

Severity and mitigation follow §20 of the spec. **"Trigger"** is the observable signal that the
fallback must be taken; **"Fallback"** is decided now, not at the moment of failure.

| # | Risk | Sev | Trigger (observable) | Fallback (pre-decided) | Owner phase |
|---|---|---|---|---|---|
| R-1 | Memory/CPU figures are macOS inferences, not Linux cgroup measurements | **High** | **P1**'s bare-container `docker run -m 512m --memory-swap 512m` (ONNX session held open) already near 420 MB, **or** **P8**'s model-resident RSS ≥ 420 MB, **or** P8's `--cpus 0.1` six-tool-call turn exceeding ~30 s | Memory: drop `EMBED_WARMUP` default to 0 and lazy-load; if still over, move embeddings to the Gemini embedding API (one extra key, documented). CPU: raise `AGENT_WALL_CLOCK_S` toward the Render timeout and adopt the `202 Accepted` + SSE pattern; reduce `AGENT_MAX_STEPS` to 4. **The measurement is split because P1 has no bootable app, no `/ready`, no `/health.app.rss_mb` and no six-tool-call turn** (spec §20 R-1) | P1 (bare container + `vec_version()`) / P8 (model-resident RSS + 0.1-CPU turn) |
| R-2 | `mcp` 2.2.0 is a breaking rewrite; model priors target 1.x | **High** | `test_mcp_api_shape` red, or `ImportError: FastMCP` | Pin `mcp==2.2.0`; the P5 subagent reads `mcp/README.md`'s 1.x→2.x mapping **before** writing code; the shape test fails in seconds rather than at integration | P5 |
| R-3 | fastembed footguns (default batch → 1477 MB; `parallel=1` hangs) | **High** | RSS spike during ingest, or an ingest run exceeding 600 s | Hard-coded `batch_size=8`, `threads=1`, **never** `parallel=`; two AST tests enforce it permanently; ingestion runs on the 8 GB builder so a regression cannot OOM runtime | P4 |
| R-4 | Ephemeral disk vs "full audit logs for EVERY session" | **High** | Turso credentials absent at P11, or `/health.trace_store.backend == "sqlite"` in production | `SqliteStore` + the boot-imported committed archive (~80 drillable sessions incl. both demo tasks and all three eval variants); UI labels live sessions *"session-scoped on the free tier"*; `deployed.md` states exactly which part of USER.2 is then unmet | P1 / P11 |
| R-5 | Free-tier quota exhaustion mid-eval or live on camera — **the plan runs TWO full sweeps, P10 `local` and P11 `deployed`, ~700 calls each** | **High** | HTTP 429 with `Retry-After`, or `eval_runs.notes` accumulating 429s | Judged metrics scoped to `baseline` (~700 calls per sweep); **a CALENDAR-DAY BOUNDARY is required between the P10 and P11 dispatches** so the two sweeps never share one RPD window (spec §13.9; P11 step 0 confirms it, G4 records it); `JUDGE_API_KEY` on a second Cloud project strongly recommended on top; content-addressed cache + committed replay JSONL make re-runs free; sequential execution behind the limiter; failover to Groq recorded as `provider_failover`; **both demo prompts cache-warmed and narrated honestly via the `cache_hit` badge** | P10 / P11 |
| R-6 | Judge credibility (agent and judge share the Gemini family) | Medium | — (standing) | **Five of the nine metric families are judge-free** — citation resolvability, DocRecall, tool selection + argument correctness, workflow completion, action safety — **and four are judge-derived** (groundedness, citation support, partial match, the ambiguous-item clarification check), so the honest claim is *"the majority of metrics, and every safety and behaviour metric, need no judge at all"* (spec §13.9; the earlier "7 of 9" form was contradicted by §13.3, §13.4 and §13.7's four judge prompts); 8 reference labels authored by an independent Opus subagent in a **different family**, blind to judge output, reported as *reference-vs-judge* κ; `GROQ_API_KEY` adds a cross-family re-judge; optional item #11 upgrades to human adjudication | P10 |
| R-7 | AI-authored corpus drifts into vagueness or contradiction | **High** | `check_facts.py` red, or an eval item's gold contradicting a cited chunk | The fact ledger is the single authoring point for every number; corpus, rules and gold all derive from it; ≥ 6 checkable `required_facts` per document | P2 |
| R-8 | Untyped Jinja/htmx boundary across 13 pages | Medium | A dashboard page rendering with a missing field, green tests notwithstanding | Every page renders from a typed Pydantic view-model produced by the same `/api/*` endpoint; pages 2/4/5/6/7/8 are thin configurations of one shared partial; **page 3 is built first** | P9 |
| R-9 | Platform/provider facts partly unverified (Render, Gemini limits, Turso) | Medium | A `[medium]` claim contradicted by the live dashboard at P10/P11 step 0 | Every such claim is tagged and reproduced in the facts/sources/confidence table; **P10 step 0 and P11 step 0 read the live values and paste them with dates**; documented host fallbacks: native Python service on Render, then Google Cloud Run (same image) | P10 / P11 |
| R-10 | **Two Render budgets: 750 instance-hours/workspace/month AND 500 build-pipeline minutes/month** `[verified]`. Exhausting the first suspends *all* free services; exhausting the second blocks every rebuild — including the `deploy_only: true` republish that gets committed results into the live image | Medium | `check_render_hours.py` projecting > 600 h **or > 400 build minutes** month-to-date | One service only; **no keep-alive cron**; `autoDeploy: false` + `ci.yml`'s `paths-ignore` so a results merge spends no build; CI warns (never fails) above 600 h and above 400 build minutes; both figures re-read and dated at P11 step 0, with the measured per-build wall-clock recorded in `deployed.md`'s `## Cost` | P11 |
| R-11 | Autonomous-build drift across 13 phases and many subagents | **High** | A second logging path appearing; `docs-check` diffing; a demo sequence silently changing | Trace built in P1 with a sole-writer AST test; the standing per-phase span criterion; docs turned into tests (`gen_tool_schemas`, `gen_eval_docs`, `corpus_stats` all diff-checked); `test_demo_tasks` compares actual against documented sequences | all |
| R-12 | Public `/mcp-server/mcp` endpoint | Low | An unexpected `tools/call` in the trace store from an unknown actor | Read tools expose only synthetic data; identity binding; the HMAC gate (unforgeable without `CONFIRM_SECRET`, never leaked in a rejection); `Host`/`Origin` allowlist + per-IP rate limit as middleware — **with the SDK capability verified before P5, not assumed** | P5 |
| R-13 | Stub-vs-real divergence hiding a prompt regression | Medium | A real `eval.yml` run failing on tool-call shape while `tests/e2e` is green | One **real** provider exchange per demo task recorded as a fixture at P10 (the stub becomes a recording); the golden prompt snapshot forces deliberate re-review on any prompt change | P10 |
| R-14 | Schedule risk in the late phases (dashboard, eval, docs) | Medium | P9 or P10 running materially over its estimate | Smallest-scope approach (~51 h); every phase ends green and committed so partial progress ships; **P9 splits into 9a/9b/9c**; pages 11–13 render committed fixture JSON so they precede P10; P0–P9 need no credentials so no phase blocks on a human | P9 / P10 |
| R-15 | Over-refusal from a mis-tuned evidence threshold | Medium | `OverRefusalRate` > 0.10 on the baseline run | `MIN_EVIDENCE_SCORE` **calibrated at P10** from the observed score distribution rather than guessed; over/missed-refusal are first-class metrics beside a 5-class confusion matrix; the threshold is env-configurable so the ablation can move it | P10 |
| R-16 | **Python 3.14.6 on the dev machine vs the 3.12 pin** | Low | A package failing to resolve, or `settings.py`'s version warning firing locally | The pin is enforced in three places (README's `python3.12 -m venv`, CI's `python-version-file`, the runtime warning); `uv` manages 3.12.14 locally; the `fresh-clone` CI job runs the README commands verbatim on a clean runner | P0 |
| R-17 | **sqlite-vec loadable extensions unavailable on `python:3.12-slim`** | Medium | P1's probe failing `enable_load_extension` / `vec_version()` | The **NumPy brute-force vector backend in `rag/vecbackend.py`, BUILT UNCONDITIONALLY at P4** (~40 lines, same `knn()` interface behind `retrieve.py`, `ingest.py` always writing `data/index/vectors.f32`, `index_meta.vector_backend` recording which loaded, and `test_vector_backend_parity` as an unconditional P4 gate) — a config branch, never an architecture re-decision, and never a fallback first exercised in production | P1 / P4 |

---

## 9. Cross-references

- **Design truth:** `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`
- **Requirement → phase → verification:** `docs/requirements-traceability.md`
- **Human gates, live checklist:** `NEEDS-FROM-USER.md` (created at P0)
- **Per-phase landing log + dated measurements:** `CHANGELOG.md`
