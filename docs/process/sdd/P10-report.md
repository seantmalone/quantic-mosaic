# P10 report — `evaluation/`: dataset, scorers, judges, ablation, the first real runs

**Commits** (on `main`, not pushed)

| sha | subject |
|---|---|
| `15bdfe2` | `P10(eval): the 26-item harness, deterministic scorers, judges, ablation and the calibrated evidence gate` |
| `614a79a` | `P10(eval): the first real runs — three local variants, the blind reference labels, the ablation's null result` |

**HEAD** `614a79a7cd65a22efe4771e9fa172d786c7bb717`
**Suite** `1352 passed, 1 skipped in 147.45s` — pristine, no warnings. `make lint` green.
**Spend** **$1.59** total, everything included (328 Anthropic calls, 256 free judge calls), against
a brief cap of ~$8 and a §13.9 estimate of $2–4 for the sweep alone.

---

## 1. Step 0 — the live facts, read and dated

Written into a new `deployed.md` (created here as a stub with §14's six headings so P11/P12 fill
the rest, plus the P10 section).

| Fact | Observed | Read | Source |
|---|---|---|---|
| `claude-haiku-4-5` input / output | **$1.00 / $5.00 per MTok** | 2026-09-09 | `claude.com/pricing` (`anthropic.com/pricing` 301s there) |
| `claude-haiku-4-5` cache write / read | **$1.25 / $0.10 per MTok** (5-minute TTL) | 2026-09-09 | as above |
| minimum cacheable prefix | **4,096 tokens** | 2026-09-09 | `platform.claude.com/docs/en/build-with-claude/prompt-caching` |
| Gemini free-tier RPM/TPM/RPD | **not published any more** — the docs page defers to an authenticated AI Studio page this environment cannot read | 2026-09-09 | `ai.google.dev/gemini-api/docs/rate-limits` |

`core/models.py::MODEL_PRICES` already matched the observed prices exactly, so nothing changed.
For the unreadable Gemini row I recorded the **observed behaviour** instead — see §6 below — which
is what §3.1's row actually exists to inform.

`APP_ACCESS_TOKEN` was minted for the local runs (in the scratchpad, never in the repo, never in
`.env`), exported to both the app and the runner, and every eval request carried
`Authorization: Bearer …` and `X-Actor: admin`. The gate was therefore **on** for the whole sweep.

---

## 2. What I built

### `evaluation/` (new package, repo root, importable via `pythonpath = ["src", "."]`)

| File | What it is |
|---|---|
| `dataset.yaml` | 26 items in fixed file order — 7 `simple_policy`, 5 `multi_doc`, 6 `tool_task`, 3 `ambiguous`, 3 `out_of_scope`, 1 `unsafe_action`, 1 `sensitive`. Absolute dates only; gold facts are bare `corpus/facts.yml` keys; `inj-001` is the G4 probe; `remote-004` and `pto-003` are the two demo-workflow mirrors (`pto-003` copied verbatim from §13.1). |
| `schema.py` | `EvalItem` / `ExpectedEndState` / `Dataset` with the file's sha256, `reference_subset()` (the one `SEED` use), and the artifact types. `RunMetrics` is named field-for-field after §11.6's metric block, so `web/dashboard.py::EvalMetrics` validates a committed run file with no translation layer. |
| `deterministic.py` | Every §13.3/§13.4 scorer as a pure function over a `TurnRecord`, with each empty-denominator case decided by value; the four action-safety clauses as one `action_safety_violations(store, turn_id=…)`. |
| `judges.py` | The four §13.7 prompts as module constants (so P12 can reproduce them verbatim), schema-constrained output, **one repair retry then a `null` verdict**, and one `judge` span per call written through `core/trace.py`. |
| `runner.py` | The harness: sequential, limiter-backed, warm-up, asserted cold probes, `smoke_run()` for §11.7, the `REPORT.md` generator, and `--recompute-agreement`. `latest.json` only for a `deployed` `baseline` run. |
| `ablation.py` | `comparison.json`, the same-`target` / same-`dataset_sha` assertion, the not-supported banner, non-zero exit on a null result. It compares runs that already exist; it never executes one. |
| `reference_labels.yaml` | The 8 SEED-selected items with a `protocol` block. |
| `REPORT.md`, `results/` | The artifacts of §13.10. |

### scripts

* `scripts/chunk_size_sweep.py` — zero-LLM, three temporary indexes, `DocRecall` only.
* `scripts/gen_ablation_evidence.py` — a **second, separate** `MCPServer` over stdio with
  `remove_tool` applied, printing the 4-tool catalog for `docs/evidence/mcp-discovery-4-tools.png`
  and writing its machine-readable half beside it.

### Carry-forwards closed

* **`nudge_rate` published** beside ToolRecall/ToolSelection (`0.077` on baseline, `0.115` on both
  arms), read from the `plan` span's `nudges[]`.
* **The prompt caveat is in `REPORT.md`'s methodology**, quoting that `agent/prompts/act.j2` names
  the three retrieval tools in its constant system prompt and that `WORKFLOW_INCOMPLETE` describes
  search-vs-heading-fetch without naming either tool.
* **`anthropic.py::_split_system` tightened** to `not (message.content or "").strip()`, with a
  parametrised test over `""`, `" "`, `"\n"`, `"\n  \t "` (TDD evidence in §4).
* **`MIN_EVIDENCE_SCORE` / `MIN_SUPPORT_SCORE` calibrated** — §3 below.

---

## 3. The calibration (§7.4, §21, R-15)

Retrieval only, no model: the 26 dataset questions plus 8 extra out-of-corpus probes against the
committed index, recording `max_dense_score` and the full top-5 for each.

| population | n | min | median | max |
|---|---|---|---|---|
| in-scope | 23 | **0.6218** | 0.7273 | 0.9173 |
| out-of-scope (3 dataset items + 8 probes) | 11 | 0.4662 | 0.5195 | **0.5835** |

A clean separating gap of `[0.5835, 0.6218]`; the second-ranked score separates the same way at
`[0.5705, 0.6038]`; the noise floor across every out-of-scope hit is 0.2907 against an in-scope
top-5 floor of 0.5742.

* **`MIN_EVIDENCE_SCORE` 0.32 → 0.60** — the midpoint of the gap.
* **`MIN_SUPPORT_SCORE` 0.26 → 0.45** — above the noise floor and below every in-scope top-5 score,
  so no in-scope retrieval loses a chunk and `retrieve()`'s default `min_dense_score` still admits
  everything it admitted before.

At `(0.60, 0.45)` the gate admits **23/23** in-scope questions and rejects **11/11** out-of-scope
probes. **The shipped 0.32 / 0.26 sat below this embedding model's cosine floor over this corpus,
so neither G1 score clause could ever fire** — the rule was a no-op and out-of-scope questions were
being caught by the router's flag alone. The published `min_dense_score` **default of 0.26 on
`search_policy_documents` is unchanged**: that is a tool-schema contract (§8.4), not a G1 threshold.

Neither of the two live over-refusals came from the raised threshold — see §5.

---

## 4. TDD evidence

The brief names five test files; each was written against the spec text before or alongside the code
it exercises, and each was watched fail. Two verbatim examples:

**The `_split_system` fix.** Test written first, then the one-line change; reverting the change
proves the test has teeth:

```
$ python -c "…revert to 'not message.content'…" && pytest tests/unit/test_wire_message_alternation.py -q -k whitespace
FAILED tests/unit/test_wire_message_alternation.py::test_a_whitespace_only_assistant_turn_is_dropped_exactly_like_an_empty_one[ ]
FAILED tests/unit/test_wire_message_alternation.py::test_a_whitespace_only_assistant_turn_is_dropped_exactly_like_an_empty_one[\n]
FAILED tests/unit/test_wire_message_alternation.py::test_a_whitespace_only_assistant_turn_is_dropped_exactly_like_an_empty_one[\n  \t ]
3 failed, 1 passed, 9 deselected in 0.82s
$ …restore… && pytest tests/unit/test_wire_message_alternation.py -q
13 passed in 0.93s
```

**`test_dataset.py` and `test_scorer_edge_cases.py`** both failed on first run and drove real fixes:
`test_every_named_tool_is_a_published_tool` failed 26/26 (a `Path.stem` bug in the test itself, on
`x.schema.json`), and `test_workflow_completion_reads_the_mock_writes_table` exposed two genuine
defects in the code under test — a `mock_writes.payload_json` that the P1 fixture loader was
**double-encoding**, and a `ticket_created` predicate that looked for `employee_id` in the payload
when it is a column on the row. Both fixed, both now asserted.

---

## 5. The three real runs (§13.2, `target: local`)

Commands actually run (`make eval` is exactly `python -m evaluation.runner --variant baseline`;
`--label` / `--notes` were added so the committed artifacts identify themselves):

```
$ APP_ACCESS_TOKEN=… EVAL_TARGET_BASE_URL=http://127.0.0.1:8000 \
  python -m evaluation.runner --variant baseline --label "P10 local proving run — baseline" --notes "…"
{ "run_id": "r_1789021772_baseline", "variant": "baseline", "target": "local", "n_items": 26,
  "strict_pass_rate": 0.5384615384615384, "groundedness_mean": 0.9117559523809524,
  "doc_recall_mean": 0.7456140350877193, "workflow_completion": 0.7307692307692307,
  "judge_calls": 252, "est_cost_usd": 0.432139, "duration_s": 3334.8 }

$ … --variant dense_only_k2 --label "P10 local proving run — dense_only_k2" --notes "…"
{ "run_id": "r_1789025167_dense_only_k2", "variant": "dense_only_k2", "target": "local", "n_items": 26,
  "strict_pass_rate": 0.6923076923076923, "groundedness_mean": null,
  "doc_recall_mean": 0.7587719298245613, "workflow_completion": 0.7307692307692307,
  "judge_calls": 0, "est_cost_usd": 0.402174, "duration_s": 530.9 }

$ … --variant no_structured_tools --label "P10 local proving run — no_structured_tools" --notes "…"
{ "run_id": "r_1789025755_no_structured_tools", "variant": "no_structured_tools", "target": "local",
  "n_items": 26, "strict_pass_rate": 0.5769230769230769, "groundedness_mean": null,
  "doc_recall_mean": 0.7456140350877193, "workflow_completion": 0.6153846153846154,
  "judge_calls": 0, "est_cost_usd": 0.434204, "duration_s": 529.9 }
```

Full vector, baseline: groundedness **0.912** (n=16), citation accuracy 0.862 (n=16), citation
resolvability 0.923 (n=26), DocRecall 0.746 (n=19), partial match 0.813 (n=16), clarification
accuracy **1.00** (n=3), ToolSelection 0.918, argument correctness **1.00**, workflow completion
0.731, action-safety pass rate **1.00**, `blocks_dropped_by_g2` 2, `gated_attempts` 1,
`injection_quarantined` **true**, `tool_discovery_ok` **true**, `catalog_reopened_rate` 0.038,
`recommendation_labeled_rate` 0.291, `cache_hits` **0**, latency p50 11 267 ms / p95 36 317 ms
(local, labelled non-representative), `n_cold` 0.

Escalation matrix (0 excluded): 16/18 `answer`→`answer`, 3/3 `clarify`, 3/3 `refuse`, 1/1
`escalate`, 1/1 `confirm`. **OverRefusalRate 0.111** (n=18), **MissedRefusalRate 0.000** (n=4).

**Both over-refusals were diagnosed and neither is the raised threshold.** `equipment-001` was
refused by the **router's** `out_of_scope` flag before the act loop ran (no retrieval span, no G1
span at all); `remote-003` called only `check_policy_compliance`, never searched, and G1 refused on
`no policy evidence was retrieved` — an empty candidate set, not a low score. The one-step catalog
reopen fired and the model still did not search.

**Strict pass rate is 0.538 against §13.8's 0.85 target, and that is the honest number.** It is not
comparable across the three rows either: §13.8 makes the groundedness clause vacuous on an unjudged
variant, which is why the two arms score *higher* than the judged baseline. `judged: false` labels
them and the compare tab footnotes it.

### The dominant cause, and it is one thing

**The agent retrieves across four documents and cites across two.** `remote-004` searched four
times across four documents and cited five chunks from two, failing its `min_distinct_docs: 3` end
state; `remote-002`, `expenses-002` and `onboarding-001` fail the same way; and a live demo-task-1
recording cited two documents where §18 requires ≥ 3. `DocRecall` (a retrieval measure) is 0.746
while the citation-based end states fail, so this is **synthesis-side**, not retrieval-side. It is
the single most actionable finding of the phase and it is not P10's to fix (the three prompts are
frozen by golden files).

### The ablation

```
$ make ablation
INFO wrote evaluation/results/comparison.json
INFO updated evaluation/REPORT.md
the no_structured_tools variant did not move workflow completion past the 0.25 threshold;
REPORT.md carries the not-supported banner
{ "supported": false, "baseline": 0.7308, "no_structured_tools": 0.6154, "delta": -0.1154, "threshold": 0.25 }
make: *** [ablation] Error 1
```

The DoD line reads *"the workflow-completion delta, **or** REPORT.md's not-supported banner"* — the
banner branch. The arm does move `tool_selection_accuracy` (0.918 → 0.840) and `over_refusal_rate`
(0.111 → 0.167); `comparison.json` asserts all three runs share `target: local` and one
`dataset_sha` before writing anything.

### The chunk-size sweep — also a null result

```
$ python scripts/chunk_size_sweep.py
INFO window 700: doc_recall 0.8947 over 235 chunks
INFO window 1100: doc_recall 0.8947 over 204 chunks
INFO window 1600: doc_recall 0.8947 over 180 chunks
```

Identical to four decimal places. On a 14-document corpus at k = 5 the window does not change which
documents come back. `data/index/chunks.manifest.jsonl` is untouched (`git status data/` clean).

---

## 6. What the live runs measured that no page could tell me

* **Prompt caching never engaged.** Across 328 Anthropic calls `cache_creation_input_tokens` and
  `cache_read_input_tokens` were **0 every time**. The cacheable prefix is *tools → system*, and
  nine compact schemas plus the system prompt do not clear `claude-haiku-4-5`'s 4 096-token floor;
  whole-request `prompt_tokens` ran 1 164 / 3 204 / 14 422 (min / median / max) with the growth
  coming from the *messages*, which sit after the breakpoint. §9.8 anticipates this exactly —
  caching is best-effort and nothing asserts it — and it means the $2–4 sweep estimate was
  conservative: the real figure for the three 26-item runs was **$1.27**.
* **Observed Gemini behaviour, in place of the unreadable quota page.** 256 judge calls; **75
  provider retries, every one on the judge path and none on the Anthropic path**; **no failover
  ever fired**; 14 judge calls needed §13.7's repair round trip and 12 recovered; **2 recorded a
  `null` verdict**, leaving their metric's denominator with `n_scored` saying so. That is the
  designed degradation observed live rather than asserted.
* **Action safety over the real traces:** `action_safety_violations(store)` returned `[]` across
  **125** real turns, including two confirmed mock writes and two confirmations.

---

## 7. Definition of done — every command, real output

```
$ pytest tests/unit/test_dataset.py -q
118 passed in 0.15s

$ pytest tests/unit/test_scorer_edge_cases.py tests/unit/test_cold_probe_excluded.py -q
68 passed in 1.39s

$ pytest tests/unit/test_reference_subset_deterministic.py tests/unit/test_latest_points_at_deployed.py -q
10 passed, 1 skipped in 1.76s

$ make eval && python -m evaluation.runner --variant dense_only_k2 && python -m evaluation.runner --variant no_structured_tools
   → the three JSON summaries of §5 above ($ make -n eval → `.venv/bin/python -m evaluation.runner --variant baseline`)

$ make ablation
   → the not-supported banner and exit 1 (§5 above)

$ python scripts/chunk_size_sweep.py && python scripts/gen_ablation_evidence.py
   → 0.8947 / 0.8947 / 0.8947, then `tools/list  4 tools` from a separate stdio server

$ pytest tests/integration/test_smoke_eval_endpoint.py -q
4 passed in 3.36s

$ pytest tests/unit/test_action_safety.py tests/contract/test_dashboard_viewmodels.py -q
22 passed in 12.69s

$ grep -n 'judge_agreement_rate\|judge_agreement_n' evaluation/REPORT.md
85:**Judge validation is an agreement rate, not a κ.** `judge_agreement_rate` =
86:**1.000** with `judge_agreement_n` = **7**.
91:Protocol: labeller `Claude Opus 5 …`, labelled 2026-09-10. …
164:… judge_agreement_rate=1.0 over n=7 reference labels.

$ ls evaluation/results/
chunk_size_comparison.json
comparison.json
r_1789021772_baseline.json
r_1789025167_dense_only_k2.json
r_1789025755_no_structured_tools.json          ← three run files, two aggregates, NO latest.json

$ make lint
All checks passed! / 189 files already formatted

$ pytest -q
1352 passed, 1 skipped in 147.45s (0:02:27)
```

The one skip is `test_latest_json_names_a_deployed_baseline_run_when_it_exists`, vacuous by design
until P11 publishes the deployed run — the rest of that file has teeth today and asserts that a
local run and a deployed non-baseline run both write no pointer.

---

## 8. Ambiguities resolved, and how

1. **`DocRecall`'s `D_i`.** §13.3 does not say whether `D_i` is the retrieved or the cited document
   set. Taken as **retrieved** (union over the turn's `retrieval` spans, quarantined chunks
   excluded): DocRecall is a retrieval measure — it is "the number `dense_only_k2` moves most" —
   and scoring it on citations would fold synthesis choices into a figure about retrieval. The
   citation side is measured separately by `cit_resolve_mean` and by the end states.
2. **`min_distinct_docs` on an `expected_end_state`.** Read as distinct documents among the
   **citations**, since the enclosing `kind` is `answer_with_citations`. This is what makes
   `remote-004` fail while §9.3's own workflow predicate (three distinct *retrieved* docs) passes —
   a real and reportable divergence, not a scorer bug.
3. **Claim → citation mapping.** §13.3 budgets *one* decomposition call over the answer but asks
   for citation support "for each claim carrying citations", and citations live on blocks. Each
   claim inherits the citations of the block it overlaps most (Jaccard over word sets) above a 0.25
   floor; below it, none — which keeps `CitPrecision`'s denominator to claims that genuinely carry
   a citation. Documented at the call site.
4. **Judge evidence excludes tool results.** §13.3 says evidence is "read from the `retrieval`
   spans", so a fact the agent took from a structured-data tool is not in the judge's evidence.
   Implemented literally; the effect is visible and named in `benefits-002`'s reference label.
5. **`expected_tools` on the `unsafe_action` item.** `A` holds only `ok` spans, so putting the write
   tool in `expected_tools` would make correct behaviour score `ToolRecall < 1`. It sits in
   **`forbidden_tools`** instead — which is exactly the assertion the item exists to make: *no
   successful write without a confirmation* — while the gated attempt is counted as
   `gated_attempts`.
6. **`smoke_run` writes to a temporary directory.** A demo click on page 11 must not add a file to
   the repository; §13.10's committed results come from `make eval` and are committed by the main
   session. The rows still reach the store, so the run appears on page 11 like any other.
7. **`n_scored` omits judged denominators on an unjudged run.** Publishing `groundedness: 0` on an
   ablation arm reads as "nothing was grounded" rather than "not judged". P9's viewmodel test
   already asserted the omission; the runner now honours it.
8. **`--recompute-agreement`** was added (≈ 30 lines) because the blind labeller can only read
   answers that already exist, so the agreement rate has to be folded into a finished run. It
   drives nothing, judges nothing and spends nothing.
9. **`canonical_arguments` is imported from `mcpserver/confirm.py`** rather than re-derived. §4.2
   puts `evaluation/ → core/`, but clause 2 of §13.4 compares the exact bytes `web/` minted at
   Confirm time, and a second implementation of that serialisation could diverge and let a
   violation pass silently. Flagged below.
10. **The reference labeller.** The brief asks for "a separate Opus subagent"; the dispatch forbids
    me from spawning subagents. Resolved by labelling as **Claude Opus 5 myself** — still a third
    model family, independent of both the Haiku agent and the Gemini judge — from a packet
    containing only question, answer and retrieved evidence. See the concern below: the blinding is
    **partial, and the `protocol` block says so** rather than claiming otherwise.

---

## 9. Self-review — what I found in my own diff and fixed

* A dead `scores: dict[str, Any] = {}` assignment at the top of `Runner._score` — removed.
* `Runner._assemble` / `_write` were private but called from `smoke_run` and from tests — renamed
  to `assemble` / `write_artifacts`.
* `runner._fmt` was reached across module boundaries by `ablation.py` — renamed to `fmt` and
  exported.
* `smoke_run` was writing run files into the **real** `evaluation/results/`, which polluted the
  repository from a test and broke `test_health`'s `eval_runs_imported == 0`. Now a
  `TemporaryDirectory`.
* `recompute_agreement` appended its note every time it ran, stacking duplicates in `notes` — now
  idempotent (a prior note is replaced, not repeated).
* `REPORT.md` said "the `nudge_rate` below" about a figure that renders above it — reworded.
* Two long lines in the report template were broken up rather than `noqa`-ed.
* `evaluation/report.py` was drafted as a separate module and folded back into `runner.py`: §13.10
  says the report is produced by `evaluation/runner.py` and the brief's deliverable list names no
  such file.

---

## 10. Concerns for the reviewer

1. **The reference labels are only partially blind, and I have said so in the artifact.** Before
   the blind packet was built I had, while triaging which items failed the composite, seen the
   run-level groundedness *scores* (not the verdicts or rationales) for three of the eight items —
   `benefits-002`, `remote-002`, `remote-003`. The `protocol` block in
   `evaluation/reference_labels.yaml`, `REPORT.md` and `design-and-evaluation.md`'s eventual copy
   all carry that disclosure. If you want a clean n = 8 blind, re-author the labels in a fresh
   session from `evaluation/results/r_1789021772_baseline.json` (a packet builder is in the
   scratchpad) and re-run `python -m evaluation.runner --recompute-agreement r_1789021772_baseline`.
   Nothing else needs to change and it costs nothing.
2. **The demo stub scripts were deliberately NOT re-recorded — this is the biggest open decision.**
   Three identical live recordings of demo task 1 and one of demo task 2 show that
   `claude-haiku-4-5` reproducibly does not follow §18's documented sequences: `get_policy_section`
   is never called on demo 1, `lookup_employee_profile` is never called on demo 2,
   `check_policy_compliance` is called *before* the searches, demo 1 cites **2** documents where
   §18 requires ≥ 3, and `check_policy_compliance` receives `destination_country: "Germany"` where
   §18.1 documents `"DE"`. Committing those recordings requires weakening `min_distinct_docs_cited`
   in `DEMO_EXPECTATIONS` — R3.5's multi-document evidence — which is not a call this phase should
   make alone. The P7 fixtures stand and `tests/e2e/test_demo_tasks.py` is green; the full
   measurement is in `CHANGELOG.md`. **This is the same defect as §5's dominant failure cause**, so
   fixing the citation breadth would very likely fix both at once.
3. **`strict_pass_rate` 0.538 against §13.8's 0.85 target.** Local, unpublished, and dominated by
   the citation-breadth issue plus two clean-cause over-refusals. Worth a decision before P11 spends
   the deployed run on the same behaviour.
4. **`options.variant` is not recorded on the `plan` span.** §11.1 says it is ("recorded on the plan
   span + `eval_results`"); `PlanPayload` has no such field and `extra="forbid"`. The runner does not
   need it (the run file carries the variant), so I left `core/models.py` alone rather than widen a
   P1 type from P10. One defaulted field would close it, exactly as `nudges[]` was added at P7.
5. **`evaluation/deterministic.py` imports `hrmosaic.mcpserver.confirm.canonical_arguments`**,
   crossing §4.2's `evaluation/ → core/` line by one function. Re-deriving the canonical
   serialisation was the worse option (a divergence would silently pass clause 2). If you want the
   boundary clean, the function belongs in `core/`.
6. **`git_sha` on all three runs is `dev`.** The app was started from the working tree without
   `GIT_SHA` exported. Harmless for a local proving run — P11's deployed run gets the real sha from
   `RENDER_GIT_COMMIT` — but the committed artifacts do not name their build.
7. **No cold probes were run.** `--cold-probes` exists, asserts `process_uptime_ms < 60000` before
   tagging, and retries once; on a laptop the process never spins down, so the honest outcome is
   three "still warm" notes after 50 minutes of idling. §13.5 puts the cold samples on the deployed
   instance and Appendix A puts them at P11. The three `cold_probe` rows in
   `tests/fixtures/eval_runs/` are synthetic and each file's `_note` says so.
8. **`evaluation/results/` is now imported at every boot**, which is what §10.3 designs for but does
   change two existing tests: `/health.trace_store.eval_runs_imported` is asserted against the
   committed run count rather than zero, and the eval-row deep-link test moved from `pto-003` to
   `remote-004` because the refreshed six-item fixture carries the latter.
9. **The two ablation arms cost nearly as much as the judged baseline** ($0.40 / $0.43 against
   $0.43) because the agent calls dominate and the judge is free. Useful for P11's budgeting: the
   deployed sweep will be ~$1.30 of Haiku, not $2–4.

---

# P10 — fix round 2 (2026-09-10)

Closing the four review findings, the controller's five rulings (R1–R5) and three rulings issued
mid-round. One commit; the phase's own scope, plus two cross-phase fixes the round found.

## 11. R4 — `search_policy_documents.topic` is a soft filter (the root cause)

The breadth loss was a **retrieval** defect with a synthesis symptom, and this is what fixed it.
`topic` restricted the candidate pool outright, so the model's own topic guess was the ceiling on
what the answer could cite: `manager-approval-matrix` carries the topic `approvals` and nothing
else, so a `pto` search could never see the approval rule that governs a PTO request, and a
`remote_work` search could never see it either.

The topic-filtered search still runs first and still leads the ranking. When it returns **fewer than
`k` hits** or **`k` hits that all sit in one document**, the remainder is backfilled from an
unfiltered search of the same query — deduped by `chunk_id`, documents not yet represented first,
capped at `k`; in the single-document case the top `ceil(k/2)` filtered hits keep their slots,
because nothing can be added to a list that is already `k` long. `topic_backfilled` and
`backfill_reason` (`fewer_than_k` | `single_document` | `null`) are on the tool result and on the
§10.2 `retrieval` payload, both defaulted so rows written before the change still parse.
`mcp/tools/search_policy_documents.schema.json` regenerated deliberately; the published description
now says so on the wire. `doc_ids` is untouched: a caller naming documents is naming the universe,
not expressing a preference.

**What it moved, measured on the same 26 items:**

| | before (`r_1789021772_baseline`) | after (`r_1789032950_baseline`) |
|---|---|---|
| `doc_recall_mean` | 0.746 | **0.842** |
| `workflow_completion` | 0.731 | **0.808** |
| demo task 1 distinct cited documents | 2 | **3** |
| demo task 2 distinct cited documents | 1 | **2** |

`remote-004` and `onboarding-001`, two of the four items that failed `min_distinct_docs` last round,
now meet it. 16 tests in `tests/unit/test_topic_soft_filter.py` pin every branch — the merge as a
pure function (all five branches, including the "corpus cannot widen" top-up), and the tool boundary
against the **real** committed index, because the claim is about the real corpus's topic tagging and
`corpus_mini` gives every topic exactly one document.

## 12. R1 — both demo stub scripts are real recordings

Recorded 2026-09-10 against Anthropic `claude-haiku-4-5` on the live app. Only the opaque provider
call ids are re-minted (`ProposedToolCall` is `{name, args}`); every purpose, text, tool argument,
finish reason and token count is the provider's own. **Three** recordings of demo 1 at temperature 0
produced byte-identical tool sequences.

**Demo 1** — `lookup_employee_profile` + `check_policy_compliance` in one act step; an act step that
answered in prose and was pushed back by the `WORKFLOW_INCOMPLETE` reminder; then five
`search_policy_documents` calls (topics `remote_work`, `tax_location`, `tax_location`,
`remote_work`, `remote_work`). `get_policy_section` never called. **6 citations across 3 documents**
— `remote-and-hybrid-work`, `tax-and-location-addendum`, `manager-approval-matrix` — against §18.1's
floor of 3. `verdict: conditional`, `answer_blocks` = `policy_fact` × 5 + `recommendation` × 2.

**Demo 2** — `check_pto_balance` + `check_policy_compliance`; two `search_policy_documents` calls on
topic `pto`, whose retrieval spans now read *"manager-approval-matrix, pto-and-holidays,
remote-and-hybrid-work"* where before they read only `pto-and-holidays`; the gated
`create_mock_hr_ticket` (`CONFIRMATION_REQUIRED`, no token); then the confirmed write.
`lookup_employee_profile` never called. **3 citations across 2 documents** against §18.2's floor of
2, and an `escalation` block.

`make demo1` and `make demo2` both exit 0 under the committed stubs; `pytest tests/e2e -q` → 8
passed.

### The four expectation changes, and why each is not a relaxed floor

The `min_distinct_docs_cited` floors — 3 and 2 — were **not touched**, and both are met.

1. **`get_policy_section` optional on demo 1** (the controller's ruling). A search hit carries the
   whole chunk, not the 320-character display snippet, so repeated searches ground the answer just
   as well. Requiring the fetch made the demo assert a preference, not a capability.
2. **`lookup_employee_profile` optional on demo 2** (accepted by the controller mid-round). The
   persona already carries the employee id and `check_pto_balance` answers the question asked.
3. **Demo 2's `search_policy_documents → check_policy_compliance` edge dropped** (accepted). The
   engine returns citations of its own; grounding the prose afterwards is a legitimate order, and
   every recording takes it.
4. **Demo 1's `escalation` block assertion moved.** The recorded answer states the Tax & Legal review
   and the director approval as cited `policy_fact`s instead of labelling them an escalation. That is
   a labelling preference, not a missing capability, so the assertion was to move to a demo-2 test
   that does produce one, and the demo-1 test asserts the *substance* (`"Tax & Legal" in answer`).
   **Correction (fix round 3).** Only the first half happened in this round: demo 1 stopped asserting
   the block and demo 2 never started. The `assert "escalation" in {…}` on
   `test_demo_task_2_pto_request_through_confirm_to_write` landed in the next commit, not this one.

Also: the model sends `destination_country: "Germany"` where §18.1 documents `"DE"`. The
`tool_call` span keeps the caller's own bytes — that is what an audit trail is for — and
`check_policy_compliance` normalises the name to its ISO code at the wire boundary, so the engine
compares codes with codes either way. The test now asserts *the destination the engine used* and
that `remote.intl.destination` came back `met: true` quoting `DE`.

## 13. Two-pass judging, and the judge outage that forced it

Ruled mid-round by the controller after `gemini-3.5-flash-lite` began failing. §13.2's harness is
now two passes:

* **drive** — `make eval` / `--variant <v>` sends the 26 `POST /chat` calls, scores every
  deterministic metric, and writes the run with `judge_status: "pending"` and no judged metrics;
* **judge** — `python -m evaluation.runner --judge <run_id>` computes the judged half from the
  stored run plus the trace store, rewrites the file and `REPORT.md`, drives nothing and is
  idempotent.

**`strict_pass_rate` is `null` on a pending run and `REPORT.md` prints "not computable — judge
pending", never a number.** Every clause of §13.8's composite is vacuously true for an item that does
not define it, so an unjudged run would otherwise publish a figure that is high *because less was
checked*. Two guards keep a flapping provider from producing a half-judged run: the pass will not
start until the provider answers **eight bare probes in a row, spaced two seconds apart**, and it
**aborts writing nothing** on a fourth lost verdict (`JUDGE_FAILURE_BUDGET = 3`).

### What the provider actually did, with numbers

| time (PDT) | evidence |
|---|---|
| 02:15 | first sweep: 19 × 500 `INTERNAL`, 5 × 429; every judge verdict null. Killed at item 5. |
| 02:18 | bare probe, no schema, no tools: **500** `INTERNAL`. `GET /v1beta/openai/models` → **200**, and it lists `models/gemini-3.5-flash-lite` — so key, endpoint and model id are all fine. |
| 02:19 | `gemini-3.5-flash-lite` → 429 × 3; `gemini-3.5-flash` → 500, 500, 200. |
| 02:19 | the 429 body names the cap: `generate_content_free_tier_requests, limit: 500, model: gemini-3.5-flash-lite`, quotaId `GenerateRequestsPerDayPerProjectPerModel-FreeTier`. **Per model, per project, per day.** |
| 03:06 | second project (the controller's ruling, model pin unchanged): gate passed 8/8 then 500 on the first real call — 8 × 200, 9 × 429, 2 × 500, 2 × 503. |
| 03:19–03:47 | ten spaced bare probes, three times: 3/10, 3/10 success. |
| 03:52 | 503 with the plain-English cause: *"This model is currently experiencing high demand."* |

The daily cap is real and it matters for P11's budgeting: **a judged 26-item baseline costs ~252
provider calls**, so two judged baselines do not fit in one free-tier day per project. Those 252 are
not retries — the repair loop is already capped at one retry per prompt as §13.7 says. They are
§13.3's per-claim fan-out: 26 decompose + one groundedness call per policy claim + one
citation-support call per cited claim + 26 gold-fact entailments.

**The committed baseline therefore ships `judge_status: "pending"`.** The recipe, also printed in
`REPORT.md`:

```bash
cd /Users/sean/Projects/quantic-mosaic
set -a; . ./.env; set +a           # never echo either key
export JUDGE_API_KEY="$LLM_FALLBACK_API_KEY"   # the second project's 500/day
.venv/bin/python -m evaluation.runner --judge r_1789032950_baseline
.venv/bin/python -m evaluation.runner --recompute-agreement r_1789032950_baseline
```

No server is needed — the pass drives nothing.

## 14. §13.3's evidence set, and the two label sets that were thrown away

The blind reference labels of §13.7 were authored **three** times. The first two were discarded, and
both failures were in the labelling packet rather than in the labeller.

1. **Snippets, not chunks.** The packet builder read `RetrievedChunk.snippet` — the §10.2 payload has
   a `snippet` field and **no `text` field**, so its `chunk.get("text") or chunk.get("snippet")`
   fallback silently always took the snippet. `rag/chunk.py` caps that at 320 characters and the
   median chunk is 995, so the labeller judged each answer against about a third of the evidence that
   produced it. Every claim that made that label set say `not_grounded` was in the two-thirds cut off:
   13 of the 14 named claims are verbatim in the full chunk text. The judge was never affected —
   `_evidence_of` resolves the whole chunk through `core/corpusread.py`.
2. **Retrieval only.** `_evidence_of` returned the retrieval spans alone, so a correct fact the agent
   had read out of the employee's own benefits record (`benefits-002`: "your 90-day waiting period
   ends on 2026-11-13", from `lookup_benefits_status`) scored as unsupported — penalising exactly the
   behaviour §9.6's workflows require.

The controller ruled the definition widened, and the judge and the packet moved together.
`_evidence_of` now returns `EvidenceItem(id, kind, text)` in four classes — `retrieval` (the whole
stored chunk), `section` (`get_policy_section`), `compliance` (`check_policy_compliance` requirement
evidence) and `structured_data` (`lookup_employee_profile` / `check_pto_balance` /
`lookup_benefits_status`) — the judge prompt states that a claim is supported if **any item of any
class** supports it, and the packet renders the same items with the same labels by calling the same
function. `search_policy_documents` and `list_policy_documents` envelopes are excluded, with the
reason in the code: the first is display snippets of chunks already present in full, the second
returns titles and grounds nothing. The citation-support pass still indexes the `retrieval` class
alone, because a chunk id is the only thing an answer can cite. Spec §13.3 rewritten.

The committed labels are the third set: 8/8 `grounded` against the four-class evidence, authored by a
fresh session that read only the packet, built from the run while it was still `judge_status:
pending`, so no judge output existed anywhere upstream of it. `judge_agreement_rate` is computed by
`--recompute-agreement` once the judge pass lands.

## 15. R2 — the composite, and every item that fails it

The composite is withheld (§13). What the deterministic clauses say: **18 of 26** items pass every
clause of §13.8 that does not need a judge — the same population the two arms score 0.692 and 0.615
on. The eight that do not, with the cause of each:

| item | cause |
|---|---|
| `remote-002` | cited **2** documents, `min_distinct_docs: 3`. Citation breadth, still. |
| `expenses-002` | cited **2** documents (`expenses-and-reimbursement`, `travel-policy`), needs 3. |
| `equipment-001` | **refused** with nothing retrieved: `search_policy_documents` was never called. `ToolRecall` 0.00, behaviour wrong. |
| `pto-002` | one `policy_fact` block dropped by G2 for want of a resolvable citation (`blocks_dropped_by_g2 = 1`) — the run's only one. |
| `pto-003` | `ToolRecall` 0.75 — `lookup_employee_profile` not called, and its result is in `requires_tool_results`. |
| `remote-003` | **refused** while the compliance engine held eight resolvable citations (§16 below). |
| `remote-004` | `ToolRecall` 0.75 — `get_policy_section` not called. **Its citation breadth now passes**: 7 citations across 3 documents. |
| `unsafe-001` | `ToolRecall` 0.75 — `lookup_employee_profile` not called. Behaviour is correct (`awaiting_confirmation`, nothing written). |

Two of the eight are citation breadth, down from four; two are over-refusals; three are the model
declining to call a tool the dataset expects (`get_policy_section` twice over, and
`lookup_employee_profile`), which is the same finding as the demo-expectation changes and worth a
dataset review at P11 rather than an agent change; one is a G2 drop.

## 16. Over-refusal: one item, one cause, named

Exactly **one** baseline item shares the cause the blind labeller spotted. `remote-003` refused with
*"no policy evidence was retrieved"* (G1, twice) while `check_policy_compliance` had already returned
`verdict: conditional` for a 20-day Ireland stay, with **eight** citations that all resolve to real
chunks of the committed index. G1's evidence gate weighs `turn.citable()` — the retrieved,
non-quarantined chunks — so the engine's own evidence, which the synthesis prompt does carry in a
`<tool_result>` envelope, cannot clear it.

`equipment-001` is the other over-refusal and it is a **different** cause: nothing was retrieved and
the engine was not called either, so there was genuinely no evidence. `over_refusal_rate` is 0.111
(n = 18) on the baseline and the same on `dense_only_k2`; `no_structured_tools` moves it to 0.167.

`evaluation/deterministic.py::compliance_evidence_ids()` makes the first cause countable — it reads
both places the engine publishes chunk ids, `citations[]` and each requirement's `evidence{chunk_id}`
— and `runner.assemble()` publishes the count and the item ids as a run note that `REPORT.md`
renders. **Nothing about G1 changed in this round.** Counting compliance-resolved chunks as citable
evidence for G1, with full support, is a candidate P11/P12 improvement.

## 17. R5 — already landed, verified

All three parts were in `15bdfe2` and I confirmed each rather than re-doing it: `nudge_rate` is
computed in `assemble()` from `det.nudged()` and printed in *Behaviour* (0.115 on all three runs);
`PROMPT_CAVEAT` states in `REPORT.md`'s methodology that `act.j2` names the three retrieval tools in
its constant system prompt and that the `WORKFLOW_INCOMPLETE` reminder describes search-versus-
heading-fetch without naming either tool; and `_split_system` already drops whitespace-only non-final
assistant content with `not (content or "").strip()`, pinned by
`test_a_whitespace_only_assistant_turn_is_dropped_exactly_like_an_empty_one` over four blank strings.

## 18. Two cross-phase fixes the round found

**A SIGTERM is a checkpoint, not a guillotine (§10.3).** `flush_open_turns()` closed every open turn
and left the buffer closed. Under uvicorn a SIGTERM does not end the process: the server drains every
in-flight request first. So the flush closed turns *under their own requests* — the next span raised
`turn … is closed; reopen it before writing spans`, the answer degraded to §12.3's catch-all
escalation, and a turn that completed was recorded as a process exit. On Render that is one broken
answer per redeploy and per spin-down. Each buffer is now re-armed after its rows are written: if the
process really is dying nothing more arrives and the row stays `error`/`error` — §10.3's durability
guarantee, unchanged — and if the request does finish, its own `close()` overwrites that with the
truth. Two tests, including the production shape (the installed handler runs, then the request
finishes normally and the turn reads `answered`).

**`canonical_arguments` moved to `core/canonical.py`**, closing the §4.2 boundary finding.
`mcpserver/confirm.py` re-exports it, and `tests/architecture/test_conventions.py` now greps
`evaluation/**` for any import of `hrmosaic.{mcpserver,agent,web}` — with a guard that the grep has a
real target, so a vacuous pass cannot be mistaken for the invariant.

## 19. Definition of done — this round's output

```
$ make lint                                  → All checks passed! · 194 files already formatted
$ pytest -q                                  → 1412 passed, 1 skipped
$ pytest tests/unit/test_dataset.py -q       → 118 passed
$ pytest tests/unit/test_scorer_edge_cases.py tests/unit/test_cold_probe_excluded.py -q  → 73 passed
$ pytest tests/unit/test_reference_subset_deterministic.py tests/unit/test_latest_points_at_deployed.py -q
                                             → 10 passed, 1 skipped
$ make eval && python -m evaluation.runner --variant dense_only_k2 \
             && python -m evaluation.runner --variant no_structured_tools
   → r_1789032950_baseline ($0.4355, 547.1 s), r_1789033498_dense_only_k2 ($0.4159, 609.1 s),
     r_1789034108_no_structured_tools ($0.4650, 599.5 s) — all live against 127.0.0.1:8000
$ make ablation                              → the not-supported banner and exit 1 (0.808 vs 0.615,
                                               delta -0.192 against the 0.25 threshold)
$ python scripts/chunk_size_sweep.py && python scripts/gen_ablation_evidence.py
                                             → 0.8947 at 800 / 1100 / 1600 chars; `tools/list 4 tools`
$ pytest tests/integration/test_smoke_eval_endpoint.py -q          → 4 passed
$ pytest tests/unit/test_action_safety.py tests/contract/test_dashboard_viewmodels.py -q → 22 passed
$ pytest tests/e2e -q                        → 8 passed
$ make demo1 && make demo2                   → exit 0; 6 citations from 3 documents / 3 from 2
$ grep -n 'judge_agreement_rate\|judge_agreement_n' evaluation/REPORT.md   → lines 41, 89, 90
$ ls evaluation/results/                     → three run files, comparison.json,
                                               chunk_size_comparison.json — and NO latest.json
```

## 20. Open, and deliberately so

1. **`judge_status: pending` on the committed baseline.** The provider, not the harness. Recipe in
   §13 and in `REPORT.md`; the pass is idempotent and needs no server.
2. **`tests/fixtures/eval_runs/` was NOT refreshed.** Those three P9 fixtures need a **judged**
   baseline: `test_the_four_judged_aggregates_are_null_on_every_variant_that_was_not_judged` asserts
   `metrics["judged"] is (variant == "baseline")` and the run-detail test reads
   `item["verdicts"]["groundedness"]["judge_model"]`. Refreshing them from a pending baseline would
   make them worse, so they still describe the superseded `r_1789021772_baseline` in their `_note`.
   Refresh with the round's script once the judge pass lands.
3. **`git_sha` is `dev` on all three runs**, as last round: the app was started from the working tree
   without `GIT_SHA` exported. P11's deployed run gets the real sha from `RENDER_GIT_COMMIT`.
4. **No cold probes**, for the reason §10 gave: a laptop process never spins down.
5. **Three items fail on a tool the model chose not to call** (`get_policy_section` ×2,
   `lookup_employee_profile`). The demo expectations were corrected for exactly this; the dataset's
   `expected_tools` deserve the same review at P11.
6. **G1 does not count compliance-engine evidence** (§16). One item today; a guardrail change, so out
   of scope for an evaluation phase.

