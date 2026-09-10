# Optimization log — output quality and performance

A dated engineering log of every optimization question asked about the Mosaic HR Copilot, the
evidence gathered, the decision taken, and what it changed. It exists so the work can be reported
on and spoken to in the demo. Newest entries are at the bottom; each entry names its evidence
(a run id, a trace query, a Render log line, a script) so a reader can check it.

Conventions: times are UTC; run ids are the `evaluation/results/r_*.json` files; "local" is the
developer laptop, "deployed" is the Render free instance at 0.1 vCPU / 512 MB.

---

## 2026-09-10 — Output quality: where Haiku falls short, and the seven mitigations

**Question.** The judged local baseline (`r_1789032950_baseline`) scored strict pass 0.654 against
the 0.85 target. Which failures are the model's, which are the orchestration's, and what should
change?

**Evidence.** Per-item spans and `llm_messages` for the eight strict failures; the deployed
baseline (`r_1789055103_baseline`) fails the same eight items for the same causes, so the local
traces stand as evidence for the deployed numbers.

| Item | Failing clause | Cause found in the trace |
|---|---|---|
| equipment-001 | tool-recall, doc-recall, workflow, behaviour | Router guessed `out_of_scope` — the route prompt never says what the corpus contains |
| pto-002 | one G2 block dropped | The model cited a tool result (`check_pto_balance`) because the synthesis rules demand a citation on every fact and never exempt employee data |
| remote-002, expenses-002 | `min_distinct_docs: 3` | One search reached two documents; the only breadth mechanism fires on routed workflows, and these routed as policy QA |
| remote-003 | tool-recall, workflow, behaviour | G1 refused; the recovery step re-ran with no message explaining why, and was spent without a search |
| pto-003, unsafe-001 | workflow end state | `pto_request` lists the employee profile as a slot but its completion predicate never required the lookup |
| amb-003 | clarification | Router named one missing detail; the dataset expects both |

**Decision (Sean, 2026-09-10): implement all seven.** R1 corpus list in the route prompt; R2 "tool
results carry no citation" synthesis rule; R3 a once-per-turn breadth reminder; R4 a message on the
G1 recovery step; R5 `pto_request` requires the profile lookup; R6 name every missing detail; R7 G1
scores compliance-engine evidence on the same dense path as retrieval (thresholds unchanged).
Rejected: few-shot tool sequences in the act prompt (the exemplar would score the ToolSelection
metric), `k` guidance (the harness overrides `k`), and editing dataset expectations to fit answers.

**Comparability protocol.** Judge the pre-change deployed baseline first (quota permitting) so the
report has a judged "before" column; re-drive all three deployed arms after the change; disclose
that R5 changes what the `no_structured_tools` arm disables; report the higher `nudge_rate` as a
diagnostic, not a regression.

**Implemented (P13, six commits ending b24ad32; 1,703 tests, 21 new).** Every mandated wording is
verbatim. Two facts a reader should know: the route prompt now lists the corpus titles read from
the committed index manifest, with a test that fails if the two ever drift; and G1 scores
compliance-engine evidence on the identical dense path retrieval uses, so a chunk that scores
below threshold still refuses (the tests pin that to 1e-5 against retrieval's own score). Disclosed
costs: the breadth reminder adds one act step to most single-search turns, so `nudge_rate` and
latency rise by design, and the `no_structured_tools` ablation arm now disables a tool the PTO
workflow genuinely requires, so post-change ablation figures are reported beside, not instead of,
the pre-change ones. Deployed with `LLM_RPM=60` / `LLM_BURST=30`; the "after" sweep of all three
arms and its judge pass are running.

---

## 2026-09-10 — Readiness defect found while measuring cold start

**What the measurement showed.** Render did spin the free instance down: its own health-check log
lines stop at 17:20:59Z, ~15 min after the last inbound request, and a fresh container logs
"Started server process" at 17:29:05Z; the probe's first `/health` answered at 17:29:11Z, ≈49 s
after the idle ended. But `/ready` stayed 503 for the life of the process with
`warm-up call failed: … SSE stream ended without a response`, while `/chat` answered normally.

**Cause.** The in-process MCP client built its HTTP client with httpx2's default 5-second timeout;
the SDK's own factory uses 30 s connect and 300 s read because a Streamable HTTP response stream is
held open until the result arrives. On 0.1 vCPU the first embedding call (ONNX session load) takes
longer than 5 s, the loopback stream timed out, and the one-shot warm-up latched readiness false.
Locally the model loads in 2.6 s, so no local gate ever saw it. Nothing in the deploy path checked
`/ready`, so the whole published sweep ran against an instance reporting `ready: false`.

**Fix (P11c, commit 395036d).** Loopback timeouts set to the SDK's 30 s / 300 s-read values; the
warm-up call retries inside `READY_WARMUP_TIMEOUT_S`; `scripts/smoke_deployed.py` now fails a
deploy whose `/ready` never greens. Verification: the next deploy's `/ready`, then the re-measured
three cold probes (pending).

---

## 2026-09-10 — Performance: "is it the CPU?"

**Question.** A warm `POST /chat` on the free instance took 26.3 s for a two-tool question; the
spec's §14.4 table expected 1.5–5 s. Is the 0.1 vCPU the cause, and what would it cost to fix?

**Evidence.** The two 26-item baseline runs, one local and one deployed, summed by span kind.

| Per turn (26 items) | Local | Deployed |
|---|---|---|
| Latency p50 | 17.7 s | 17.6 s |
| Latency p95 | 42.4 s | 47.7 s |
| LLM calls (Haiku) | 13.4 s | 13.6 s |
| Retrieval (embed + search) | 0.05 s | 0.80 s |
| Tool bodies | 0.08 s | 0.89 s |
| Trace-store writes | ~0 | 0.06 s |

**Conclusion.** The free instance is ~15× slower on CPU-bound work, but that work is under two
seconds of an ~18-second turn; roughly three quarters of every turn is waiting on the model
(router → act steps → synthesis, each a few seconds, none cached because the static prefix sits
below Haiku's 4,096-token caching floor). The 26.3 s probe sits inside the same band both runs
show. The §14.4 expectation was written for a stub-model turn and is to be corrected. A paid CPU
tier would buy back ≈1.5 s per turn plus the removal of cold starts; it would not touch the model
time. Adversarial verification of this attribution and a priced options table: in progress.

---

## 2026-09-10 — Performance: the CPU question, adversarially verified

**Method.** Three independent analyses (span-level decomposition of both 26-item runs; live
microbenchmarks of the deployed instance against the same app running locally; a priced survey of
Render tiers and free alternatives), then a skeptic instructed to refute the CPU hypothesis with
eight alternative explanations, recomputing every figure from the raw trace stores.

**Verdict.** The premise "a deployed turn is slow because of the 0.1 vCPU" is refuted on magnitude
and confirmed only on composition. Like for like (same items, same model, same config, server-side
turn duration), local p50 is 17,670 ms and deployed p50 is 17,584 ms; the mean service-time gap of
about 1.6 s per turn is not statistically significant at n=26 (bootstrap 95% CI −0.2 s to +3.5 s).
Of that small gap, about 72% is CPU-bound work (query embedding ≈41%, Python-side work ≈24%,
search and the MCP hop ≈7%), 15% is the deployed run simply taking more act steps on three items,
and 9% is Turso round-trips on the request path. Memory pressure, region latency to Anthropic,
and the loopback MCP hop were each tested and rejected. The "local turn of a few seconds" the spec
quoted came from stub-model turns (mean 292 ms) and was never a real-model figure.

**What a bigger CPU would buy.** A 0.5 vCPU Starter instance ($7/month, no spin-down) or a 1 vCPU
Standard instance ($25/month) projects to a 3–5% faster turn (p50 ≈ 16.8–17.2 s) because the
CPU-bound share is ~1.0–1.4 s per turn. The two tiers are indistinguishable for this workload. The
larger user-visible penalty of the free tier is the spin-down itself: ~41–49 s to the first
response after 15 idle minutes.

**The finding that matters.** The largest controllable cost on the deployed box is the project's
own LLM rate limiter: `LLM_RPM=10` / `LLM_BURST=10` (a Settings default applied in production, not
only in the harness) recorded 3.9 s of token-bucket waiting per turn on average (20% of run wall
clock, p90 12.2 s, max 14.0 s) inside the turn latency. Raising it is an environment change with
no rebuild, bounded independently by `LLM_DAILY_CALL_CAP`. Second: the same query is embedded
twice when the soft topic filter backfills (~270 ms per affected turn on 0.1 vCPU) — an LRU cache on
the query embedding removes it. Third: nothing streams today (time-to-first-byte equals duration on
all 330 LLM spans), and prompt caching is inactive (zero cache reads), so the user waits for whole
completions of uncached prompts.

**Costed options table (all paid tiers need Sean's explicit approval).**

| Option | USD / month | CPU / RAM | Spins down | Expected effect |
|---|---|---|---|---|
| Render Free (current) | 0 | 0.1 vCPU / 512 MB | yes, 15 min | baseline |
| Render Starter | 7 | 0.5 vCPU / 512 MB | no | −1.0 to −1.4 s per turn; no cold starts |
| Render Standard | 25 | 1 vCPU / 2 GB | no | same as Starter for this workload |
| Google Cloud Run (free allowance, card required) | 0 within allowance | up to 1 vCPU while serving | yes, scale-to-zero | ~10× CPU; a migration, not a knob |
| Koyeb free | 0 | 0.1 vCPU / 512 MB | yes | no gain |
| Fly.io / Railway / HF Spaces | trial or paid only | — | — | not a free fit |

**Decision.** Do not buy CPU for speed. The zero-cost levers above go into the performance plan
(deep assessment in progress); the rate-limiter change is applied with the next deploy.

---

## 2026-09-10 — The judged "before optimization" baseline (deployed, `r_1789055103_baseline`)

Sean enabled paid billing on the judge project (≈ $0.16 per pass) so the pre-change deployed run
could be judged before any prompt changed. 264 Gemini calls; judge agreement with the blind human
labels 1.00 on the seed subset (n=7) and 1.00 on the hard subset (n=8).

| Metric | Before (deployed, judged) |
|---|---|
| Strict pass rate (target ≥ 0.85) | 0.692 |
| Groundedness | 0.979 |
| Citation accuracy | 0.847 |
| Partial match (gold facts) | 0.794 |
| Clarification accuracy (n=3) | 0.667 |
| Doc recall | 0.855 |
| Tool selection F1 | 0.926 |
| Argument correctness | 1.000 |
| Workflow completion | 0.769 |
| Over-refusal / missed-refusal | 0.111 / 0.000 |
| Action safety | 1.000 |
| Nudge rate | 0.115 |
| Latency p50 / p95 | 17.6 s / 47.7 s |

Ablation unchanged: `no_structured_tools` moves workflow completion by −0.154 against the
pre-registered 0.25 threshold, so the hypothesis stays "not supported". This table is the column
every P13 and performance change is measured against.

---

## 2026-09-10 — Deep performance assessment (in progress)

Method: (1) anatomy of every LLM call in the deployed run from its traces (calls per role, tokens,
latency, a fitted latency model); (2) a map of the turn's serial structure from the code; (3) a
budgeted live latency probe of Haiku (input tokens, output tokens, JSON-schema output, prompt
caching); (4) three independent proposals from different angles (fewest round-trips, per-call
latency, infra and overlap); (5) two adversarial reviewers per lever (latency realism; quality and
grading risk); (6) one ordered plan in waves — zero-cost/no-spec-change, zero-cost/re-evaluated,
paid/owner-approval. Results and the plan will be appended here and filed under
`docs/superpowers/plans/`.

---

## Demo talking points (to be finalised)

- Every optimization claim in this project is traceable to a run id and a span query; the
  dashboard shows the same traces the analysis used.
- The readiness defect is a good story: the instance passed every smoke and the whole evaluation
  while `/ready` was wrong, and only a measurement designed to fail honestly (refusing to publish a
  timeout as a number) exposed it.
- "Is it the CPU?" — the intuitive answer was wrong; two full runs settled it in one table.
