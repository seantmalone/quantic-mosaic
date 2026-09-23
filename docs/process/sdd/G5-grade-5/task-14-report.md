# Task 14 (G5c, round-3 code) — report

Commit **6a4821a** — `G5c(code): the disabled filter, the rules engine's not_stated, and five smaller gaps`
(on `main`, parent `7919e94` = Task 15's packet commit; trailer `Co-Authored-By: Claude Fable 5.1`, no
`Claude-Session`).

Ranks closed: **3, 4, 14, 16, 29, 30, 35, 36**. Rank **21** left alone as ruled (recorded traces are
history); nothing in this commit touches `tests/fixtures/traces/**`. `scripts/gen_label_packet.py`,
`tests/unit/test_gen_label_packet_store.py` and `tests/contract/test_docs_completeness.py` were not
edited by me (Task 15 committed them as `7919e94` while this task was in flight); I own only the
suite-size figures inside `test_docs_completeness.py`'s `NUMBER_DOCS` documents.

---

## Gap 3 — `tools_disabled` enforced at the MCP call boundary

The effective set is a new one-line reader, and the guard sits at the single chokepoint every
`tools/call` in the process passes through (`_act`'s calls and its one repair, the three deterministic
calls, and `_resume`'s re-issue of the gated write):

* `src/hrmosaic/agent/orchestrator.py:2411` — `_disabled(turn)`: `options.tools_disabled ∪
  settings.mcp_tools_disabled_list`, the same union `router.allowed_tools` applies to the offered array.
* `src/hrmosaic/agent/orchestrator.py:2417` — `_refuse_disabled()`: records a `tool_call` span with
  `is_error: true`, `error_code: "TOOL_DISABLED"`, the arguments as they would have been sent, no
  `server_timing_ms`, plus an `error` span (`error_kind: "tool_disabled"`, component `mcp`) and a step
  summary. Returns an `is_error` `ToolResult`; **never raises**, so the turn degrades the way an
  unavailable tool does (`_read_profile_deterministically` / `_score_deterministically` already test
  `result.is_error`, `_propose_deterministically` tests `confirmation_required`, and `_resume` takes its
  `tool_failed` branch → `partial`).
* `src/hrmosaic/agent/orchestrator.py:2478` — the guard itself, first statement of `_call`.
* `src/hrmosaic/agent/orchestrator.py:2092` — `_profile_outstanding` gains
  `PROFILE_TOOL not in self._disabled(turn)`. Reason: `_settle_profile_debt` is called on every path out
  of the act loop, so with only the chokepoint guard the arm made **two** refused attempts per turn and
  still recorded a `profile_read_deterministically` reminder for a read that never happened. §9.2's
  router gate is still deliberately not consulted there (W10's ruling); only §13.9's filter is.

`evaluation/schema.py:79-89`'s `VARIANT_OPTIONS["no_structured_tools"]` withholds
`lookup_employee_profile`, `check_pto_balance`, `lookup_benefits_status`, `create_mock_hr_ticket`,
`draft_hr_email` — all five are now unreachable on that arm, from any caller, which is the arm's stated
semantics. `check_policy_compliance` and `search_policy_documents` are not in the list and are unaffected.

**Tests**

* `tests/unit/test_mcp_tools_disabled_default.py:171,194,206` — an orchestrator-issued `_call` for a
  request-disabled tool is refused with nothing reaching the client, the operator's own
  `MCP_TOOLS_DISABLED` refuses the same call, and an undisabled tool still reaches the client (the guard
  is the union and nothing wider). The refusal span's fields are asserted.
* `tests/integration/test_tools_disabled_boundary.py:55,80,93` — the profile-debt turn over the
  **mounted MCP server on loopback HTTP** with `tools_disabled: [lookup_employee_profile]`: no span for
  that tool carries `server_timing_ms` (the control, `check_pto_balance`, does), the turn still closes
  `answered`, the same script **does** read the profile when nothing is disabled (so the suppression is
  not vacuous), and the `plan` span carries no `profile_read_deterministically`.

**Not done (out of this task's list, and deliberate):** `evaluation/runner.py:1050` still records
`VARIANT_OPTIONS[...]["tools_disabled"]` — the arm's *request*. Unioning the harness's local
`MCP_TOOLS_DISABLED` there would be wrong for a **deployed** target, whose operator filter is the
service's and not the harness's; the honest widening would be a `/health`-reported field. Left as is,
flagged for the re-drive owner: the run config is what the arm asked for, and gap 3's enforcement is
now what the server does with it.

---

## Gaps 4 and 29 — the rules engine reads `not_stated` as `not_stated`

* `src/hrmosaic/mcpserver/rules.py:514,543` — `guard_holds(..., decided: Mapping[str, str], ...)`;
  `unmet:`/`met:` now hold iff `decided.get(id) == kind`. A requirement that did not apply is absent from
  `decided` and satisfies neither form, exactly as before.
* `src/hrmosaic/mcpserver/rules.py:789,795` — `decided` holds `decision.status`, not `decision.met`.
* Verdict semantics untouched (`_verdict` is unchanged): `insufficient_evidence` for a scenario with
  nothing evaluable, `non_compliant` for an evaluable blocking failure, `conditional`, `compliant`.
* `src/hrmosaic/mcpserver/tools/check_policy_compliance.py:116` — the parameters description names
  `device_age_months` and `days_since_final_day`, and rewrites the `refresh` clause so it describes the
  **input** (compared against the 36-month cycle; below it the refresh is early and needs manager
  approval) instead of the conclusion, which was the sentence that contradicted the returned approval.
  Every `parameter_`/`employee_eq` guard in `corpus/rules.yml` was grepped: `request_type`, `category`,
  `reason`, `days`, `amount_usd`, `work_arrangement` — all already named or record-side.
  `mcp/tools/check_policy_compliance.schema.json` regenerated with `scripts/gen_tool_schemas.py`
  (one-line diff; the other eight schemas are byte-identical).

Measured in process at this commit:

| call | before | after |
|---|---|---|
| `equipment_request {request_type: refresh}` | `insufficient_evidence` + Direct-manager approval + early-refresh step | `insufficient_evidence`, `approvals []`, `next_steps []` |
| `… + device_age_months: 24` | conditional + Direct manager | unchanged (conditional + Direct manager + early-refresh step) |
| `… + device_age_months: 36` | compliant + IT-ticket step | unchanged |
| `equipment_request {request_type: new}` | `insufficient_evidence` + Director | `insufficient_evidence`, Direct manager only |
| `… + amount_usd: 1200` | conditional + manager + Director | unchanged |
| `international_remote {destination_country: PT}` | **conditional**, Director + Tax & Legal, 21-day step | Direct manager only, no tax-review row |

**Tests** — `tests/unit/test_rules_engine.py:745,759,772,783,795,806,829`: the five equipment cases the
brief names, the `international_remote`/`PT` case (rank 29's instance), and `guard_holds` itself over
`unmet`/`met`/`not_stated`/undecided — the function had exactly one test before this (its unknown-prefix
refusal), which is why the class was unfrozen.

---

## Gap 14 — the action-safety population is keyed on conduct

* `evaluation/deterministic.py:661` — `performed_write(turn)`: a `mock_writes` row, or an `ok` write-tool
  span that is not `CONFIRMATION_REQUIRED` (a `draft_hr_email` performed envelope leaves no row).
* `evaluation/deterministic.py:681` — `safety_at_stake(item, usage, *, wrote)`: `wrote or usage.gated or
  category == "unsafe_action" or expected_behavior == "confirm"`. The three expectation clauses are kept,
  so the published `n = 2` does not move; the pass rule (`action_safety_violations() == []`) is untouched.
* `evaluation/runner.py:564` — the per-item score calls both. `n_scored['safety']` is still
  `len(safety)` over the same population it divides by (`runner.py:832-836, :997`), so the report line
  stays honest by construction.

**Tests** — `tests/unit/test_action_safety.py:175,191,205,215`: both directions over the committed golden
traces (the confirmed-write fixture is in the population against an item that expects a plain answer; the
no-write fixture is out), the three expectation clauses still standing alone, and an `ok` write span with
its `mock_writes` row deleted still counting as a write.

---

## Gap 16 — a smoke run cannot replace an ablation arm

* `src/hrmosaic/web/dashboard.py:3087` — `SMOKE_LABEL = "dashboard smoke run"`, now the default of
  `SmokeEvalBody.label` (`:3184`) and the same string `evaluation/runner.py::smoke_run` defaults to.
* `src/hrmosaic/web/dashboard.py:3090` — `_compare_rank()`: `0` a run whose `n_items ≥ len(dataset.yaml)`,
  `1` a shorter non-smoke run, `2` a smoke run.
* `src/hrmosaic/web/dashboard.py:3115` — newest-per-variant becomes best-rank-then-newest. A
  **preference, not a filter**: a variant whose only run is short is still charted (the committed
  `tests/fixtures/eval_runs/*` runs are 6–10 items and every existing compare-tab test still passes).
  No new view-model field, so `EvalCompareView`'s field set and the templates are unchanged.

**Tests** — `tests/contract/test_dashboard_viewmodels.py:434,469`: a newer 3-item smoke row for
`baseline` does not change the charted run ids (and the endpoint/harness smoke labels are pinned equal);
a short non-smoke arm yields to a full one, all three arms stay on the page, and `_compare_rank`'s three
ranks are asserted directly.

---

## Gap 30 — the expense approver justified from the rule that decided it

* `src/hrmosaic/agent/compliance.py:173` — `LOWER_AUTHORITY`: "your manager … can/may/is able to/has the
  authority to approve|authorise|sign", up to four words of name between role and verb, plus the passive
  "approved by your manager". `\bcan\b` does not match inside "cannot", so a sentence that *denies* the
  authority is left alone.
* `src/hrmosaic/agent/compliance.py:630` — `correct_authority(text, rows, covering)`: while a row whose
  reason subject is `parameters.amount_usd` is **`unmet`**, such a sentence is replaced by the engine's own
  routing sentence — `covering_rule()`'s highest attached tier, else the failing row's `reader_sentence` —
  once per block, with a second occurrence dropped rather than repeated.
* Wired at `src/hrmosaic/agent/compliance.py:705` over the **blocks only**; the engine's own `next_steps`
  are `rules.yml` speaking and are not rewritten. Counted as `Outcome.authority` (`:316`, `:753`), which
  joins `changed`; `thresholds` keeps meaning ceilings only.
* This is the code side. **No corpus/rules change was needed** — the corpus already routes a USD 3,000
  claim to the Director, and the defect was entirely in the served prose — so there is no rules-side
  sentence owed to the corpus owner for this gap.

**Tests** — `tests/unit/test_compliance_restatement.py:493,509,516,526,540,552,562,570`: the live lead
sentence ("below the USD 5,000 director threshold, your manager Dana can approve it") becomes "Reports
above USD 2,500 need director approval and a Finance business partner review."; four voices of the same
conclusion; "cannot approve" untouched; a claim **within** the manager's limit keeps its manager; a
`not_stated` row is not grounds for rerouting; the engine's own next steps are never rerouted;
idempotent; and with a single attached tier the failing row's own reader sentence is said instead.

---

## Gap 35 — `make test` builds the index it needs

* `Makefile:28,30` — `INDEX ?= data/index/hr_index.sqlite` and a rule that runs
  `python -m hrmosaic.rag.ingest` when the file is missing. `Makefile:63,72,88` — `test`, `coverage` and
  `ux` depend on the **file**, so an existing index is never rebuilt (`make -n test` prints only
  `pytest -q`). `ingest` stays a phony always-rebuild target.
* `README.md:63-65` (Local Run, one sentence) — says the three targets build the index themselves when
  it is missing and that an existing index is never rebuilt.
* `corpusread.connect()`'s missing-existence check (the gap's optional third suggestion) was **not**
  added: it is a src change with no gap of its own and the Makefile prerequisite removes the failure mode.

---

## Gap 36 — `docs/**` out of `paths-ignore`

* `.github/workflows/ci.yml:20` — `paths-ignore: ['evaluation/results/**', 'evaluation/REPORT.md']`, with
  the comment above it (`:6-19`) extended to name the three documents the contract tests bind and the
  three round-2 commits that touched nothing else.
* `tests/contract/test_deploy_manifests.py:214` — the pinned list is the two paths, plus a new assertion
  that **no** entry starts with `docs/`, naming the documents the suite would stop reading.

---

## Suite size (owned by this task)

`pytest --collect-only -q` at this commit: **3,469** total, **299** `-m ux`, **3,170** non-ux
(`3,469 = 3,170 + 299`). Bumped from 3,439 / 3,140 in: `README.md:67`, `ai-tooling.md:301`,
`design-and-evaluation.md:992`, `docs/requirements-traceability.md:149`, `docs/demo-script.md:84`
("3,170 of 3,469" and "all 3,469"). Delta +30 collected tests, all from this commit.

---

## Sentences the docs wave must update

1. **`deployed.md:89-90`** — "`ci.yml`'s `paths-ignore` — which since 2026-09-22 keeps only published
   *results* off the build budget (`evaluation/results/**`, `evaluation/REPORT.md`, `docs/**`)": drop
   `docs/**` from the parenthesis. The claim before it becomes true as written.
2. **`design-and-evaluation.md:1008-1009`** — "`paths-ignore` keeps `evaluation/results/**`,
   `evaluation/REPORT.md` and `docs/**` off the pipeline": drop `docs/**`, and the paragraph can now say
   the docs tree is gated rather than exempted (G5c, gap 36).
3. **`docs/demo-script.md:84`** (CI/CD row) — "it ignores only the **three** paths a published *result*
   lands in (`evaluation/results/**`, `evaluation/REPORT.md`, `docs/**`)": two paths, and drop `docs/**`.
4. **`design-and-evaluation.md:445-480` and limitation 13 at `:1844-1864`** — the `not_stated`-read-as-
   `unmet` disclosure is now a **fixed defect**, not a deferred one, and its scope was 18 guards rather
   than the four equipment ones. Rewrite as a closed item (with the `international_remote` instance and
   the two verdict examples) or delete it; the six characterisation tests at
   `tests/unit/test_rules_engine.py:745-853` are the citation.
5. **`design-and-evaluation.md:1391-1399` and `:1795`** — the `expenses-002` loss is framed mainly as a
   judge-versus-labeller disagreement. It now has a named code cause and a fix (the lead sentence cited
   the wrong threshold; `compliance.correct_authority`), and the sentence should say so.
6. **The `no_structured_tools` arm's published comparison** — any document that reads the
   round-2 `no_structured_tools` numbers as "the arm with the structured tools withheld" is describing a
   run in which 8 of 30 items called a withheld tool. Either the re-drive supersedes it or the
   annotation must name the 8 items (expenses-002, pto-002, pto-003, remote-003, remote-004,
   benefits-002, unsafe-001, unsafe-002).
7. **`evaluation/REPORT.md`'s action-safety line** — should state its population the way
   `design-and-evaluation.md:1216-1222` already does, now that the population includes any turn that
   performed a write (gap 14's second half).
8. **`.env.example`'s `MCP_TOOLS_DISABLED` comment and §12.3 wherever it is quoted** — the knob now
   refuses a withheld tool at the call boundary with `TOOL_DISABLED`, not merely withholding it from the
   offered array. Worth one clause, since that was the operator-facing half of gap 3.
9. **Corpus owner (`corpus/rules.yml`'s own header, off-limits this task):** two stale lines.
   `:78` should say `unmet:<id>` holds only for a row whose **`status` is `unmet`** (checked and failed)
   and that a `not_stated` row satisfies neither form; and `:98-99`'s "a requirement whose subject is
   **absent** … lands in `unmet[]`" has been false since W8's fix round — `unmet[]` is filtered on
   `status == "unmet"`.

---

## Commands run (all at this commit unless noted)

* `.venv/bin/ruff check .` → All checks passed; `.venv/bin/ruff format --check .` → 322 files formatted.
* Touched files one at a time: `tests/unit/test_mcp_tools_disabled_default.py` (9 passed),
  `tests/integration/test_tools_disabled_boundary.py` (3), `tests/unit/test_rules_engine.py` (216),
  `tests/unit/test_action_safety.py` (10), `tests/unit/test_compliance_restatement.py` (46),
  `tests/contract/test_dashboard_viewmodels.py` (28), `tests/unit/test_profile_debt_is_settled.py` +
  `tests/unit/test_agent_nudge.py` (55), `tests/contract/test_docs_completeness.py` (49).
* `MOCK_TODAY=2026-09-01 .venv/bin/pytest -q -p no:cacheprovider tests/unit tests/integration
  tests/contract tests/architecture` → **1 failed, 3161 passed in 292.78s**, the single failure being
  `test_every_document_that_states_the_suite_size_states_the_collected_one` (README still said 3,439).
  After the five-document bump, `tests/contract` alone: **561 passed in 156.35s, exit 0**, and
  `test_docs_completeness.py` 49 passed. One pytest process at a time throughout.
* `MOCK_TODAY=2026-09-01 .venv/bin/python -m hrmosaic.rag.ingest --verify-manifest` → "OK —
  `data/index/chunks.manifest.jsonl` is byte-identical to the rebuild (205 chunks)", 14 files / 205
  chunks / 30,938 words.
* `scripts/gen_tool_schemas.py` (9 schemas from a live `tools/list`; one file changed).

---

## Concerns

1. **The round-2 published arms are now stale in two ways.** `no_structured_tools` no longer calls the
   withheld tools (its workflow-completion delta, and therefore the pre-registered check the demo reads
   out, will move), and every `check_policy_compliance` call whose scenario has an `unmet:` guard on a
   `not_stated` row returns fewer approvals and next steps. A re-drive of the trio is required before any
   published figure is quoted again; `evaluation/results/**` and `evaluation/REPORT.md` are untouched here.
2. **The re-drive may change `strict_pass` on `expenses-002` and on any `equipment`/`international_remote`
   item.** Direction unknown: gap 30's reroute should raise groundedness on `expenses-002`, and gap 4's fix
   removes sentences the judge previously had to weigh. Nobody's gold answer was edited.
3. **A rerouted or ceiling-replaced sentence keeps its block type.** `retype()` is not told about
   `correct_authority` (nor about `correct_ceilings`, which has shipped this way since W8), so a
   `recommendation` block carrying the engine's own routing sentence still renders under "What I suggest
   you do" with the "not company policy" footnote. Pre-existing class, not widened; a candidate for the
   next wave.
4. **`_refuse_disabled` writes `server: catalog.server`** when a catalogue exists, so a refusal span names
   the server it did not reach. `server_timing_ms: null` and `error_code: TOOL_DISABLED` are what
   distinguish it; the integration test asserts both. If a reader finds that confusing, the field could
   become `"(not called)"` — it is a `str`, so no schema change.
5. **The compare tab still shows no notice when the paired arms disagree on `n_items`.** The gap offered
   that as well; I implemented the exclusion only, to avoid adding a field to `EvalCompareView` and its
   templates mid-wave. The page's existing "these are the newest per variant, not always the published
   comparison's runs" warning still stands.
6. **`LOWER_AUTHORITY` is a regex over English prose.** It is deliberately narrow (one role noun, a closed
   verb set, and only while an amount row is `unmet`), so the likely failure is a miss rather than a false
   rewrite — the seven negative tests cover the false-rewrite directions I could think of.
7. **Suite figure timing.** The count was measured at this commit with Task 15's `7919e94` already in the
   tree. Any later commit in this wave that adds a collected test must re-bump the same five documents.

---

# Fix round 1 — commit `43da563`

`G5c(eval): fix round 1 — a violating turn is in the safety population even without a write`
(on `main`, parent `6a4821a`; Fable trailer, no `Claude-Session`; **not pushed**). Four files,
+70/−10. Reviewer approved all eight fixes on substance; this lands the one code residual.

**Gap 14 residual — `safety == 0.0` is a membership clause.**

* `evaluation/deterministic.py:681` — `safety_at_stake(item, usage, *, wrote, safety=1.0)`; the
  predicate now reads `safety == 0.0 or wrote or usage.gated or category == "unsafe_action" or
  expected_behavior == "confirm"`. The first pass keyed membership on conduct, which covers clauses 1–3
  of §13.4; **clause 4 needs neither a write nor a gate** — a `confirmations.token` value in a served
  answer or a persisted payload — so a turn that leaked a token with no write at all scored 0.0 and was
  then dropped from the rate that exists to report it. The three expectation clauses are kept
  deliberately: they are what makes a *passing* denominator honest, since the population has to hold
  the items where an action was at stake and nothing happened.
* `evaluation/runner.py:566` — the call passes the item's own `safety` (computed two lines earlier from
  `det.action_safety_violations`), with the reason in the comment above it. `safety=1.0` is the default,
  so no other caller changes behaviour.

**Test (no new collected test — the suite stays 3,469 / 3,170 + 299).**
`tests/unit/test_action_safety.py:191` —
`test_a_turn_that_neither_wrote_nor_reached_the_gate_stays_out_of_the_population` grows the case
instead of gaining a sibling: the no-write golden trace is made to violate **clause 4** (a minted
`confirmations` row on that turn's own span, and that token in `turns.final_answer`) while
`mock_writes` stays empty, no write span exists and `ToolUsage.gated` is empty. `violations()` then
reports clause 4 **and nothing else**, `performed_write()` is still `False`, and the item is in the
population on the violation alone. The clean half of the same test still asserts it is out at
`safety=1.0`.

**Docstring.** `src/hrmosaic/agent/orchestrator.py:2427` — "Every **turn's** `tools/call` goes through
`_call`", with the one exception named: `web/main.py:232`'s `/ready` warm-up calls `client.call_tool`
directly under a `maintenance` session and no turn, so it is a process readiness probe rather than work
done for a reader and §13.9's per-request filter has nothing to say about it.

**Ruling honoured:** the three false `paths-ignore` sentences (`deployed.md:89`,
`design-and-evaluation.md:1008-1009`, `docs/demo-script.md:84`) were **not** edited — they belong to the
docs wave after the re-drive. They remain items 1–3 of the list above.

**Commands:** `ruff check .` → All checks passed; `ruff format --check .` → 322 files formatted;
`tests/unit/test_action_safety.py` → **10 passed in 1.45s**; `tests/unit/test_strict_pass_causes.py` →
**15 passed in 1.00s** (run one at a time); `pytest --collect-only -q` → **3,469** total / **3,170**
non-ux / **299** ux, unchanged, so no document figure moves.
