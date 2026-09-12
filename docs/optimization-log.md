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

## 2026-09-10 — After the quality fixes: the P13 column (deployed, `r_1789069158_baseline`)

Same 26 items, same live instance, same judge model, one code change between the columns (the seven
mitigations) plus the rate-limiter setting on the service. 296 judge calls (≈ $0.18).

| Metric | Before | After P13 |
|---|---|---|
| Strict pass rate (target ≥ 0.85) | 0.692 | **0.808** |
| Groundedness | 0.979 | 1.000 |
| Citation accuracy | 0.847 | 0.914 |
| Partial match (gold facts) | 0.794 | 0.875 |
| Clarification accuracy (n=3) | 0.667 | 1.000 |
| Doc recall | 0.855 | 0.974 |
| Tool selection F1 | 0.926 | 0.987 |
| Workflow completion | 0.769 | 0.846 |
| Over-refusal / missed-refusal | 0.111 / 0.000 | 0.000 / 0.000 |
| Nudge rate | 0.115 | 0.577 |
| Latency p50 / p95 | 17.6 s / 47.7 s | 22.6 s / 39.2 s |
| Ablation delta (tools removed, workflow completion) | −0.154 | −0.192 (threshold 0.25; arm meaning changed by R5) |

**Reading it.** Every quality metric moved the right way and the over-refusals are gone; the
remaining strict-pass gap to 0.85 is five items. The price is visible in two rows: the breadth
reminder now fires on most single-search turns (nudge rate 0.115 → 0.577), and each of those turns
spends one more act step, so the median turn is ~5 s slower even with the limiter raised; the tail
improved because the worst turns no longer stall. The performance waves are what claw the median
back. This column carries no human-agreement figure: the blind reference labels are re-authored
once, for the final published run.

---

## 2026-09-10 — Deep performance assessment: the plan

Method: (1) anatomy of every LLM call in the deployed run from its traces (calls per role, tokens,
latency, a fitted latency model); (2) a map of the turn's serial structure from the code; (3) a
budgeted live latency probe of Haiku (input tokens, output tokens, JSON-schema output, prompt
caching); (4) three independent proposals from different angles (fewest round-trips, per-call
latency, infra and overlap); (5) two adversarial reviewers per lever (latency realism; quality and
grading risk); (6) one ordered plan in waves — zero-cost/no-spec-change, zero-cost/re-evaluated,
paid/owner-approval. Results and the plan will be appended here and filed under
`docs/superpowers/plans/`.

**Result (49 agents; plan filed at `docs/superpowers/plans/2026-09-10-performance-plan.md`).** Every
lever was proposed from one of three angles, then put through two adversarial reviewers (latency
realism; quality and grading risk); only levers both kept survive, at the reviewers' figures.

| Wave | What it contains | Predicted p50 / p95 after | Cost | Needs |
|---|---|---|---|---|
| Baseline | — | 17.6 s / 47.7 s | — | — |
| 1 · zero cost, no graded change | rate-limiter hygiene (measurement only; 0 ms interactive), query-embedding memo (−0.3 s), trace store off the request path (−0.1 s) | 13.7 s / 35.2 s | $0 | docs updates only |
| 2 · zero cost, changes graded behaviour | act loop stops writing a throw-away 224-token answer (−1.5 s), synthesis output diet (−0.5 s), full chunk text on search hits so a fetch step disappears (−0.4 s), input diet (cost only), streaming the answer (first prose 3 s sooner at p50, 17 s at p95) | 11.4 s / 33.1 s | $0 | a new sweep + judge + labels; one spec non-goal reversed for streaming |
| 3 · paid | Render Starter 0.5 CPU ≈ −0.45 s; keep-alive pinger | not credited | $7/month | owner approval; not recommended |

Wave 3's "keep-alive pinger" is the *paid* version of the idea — it is priced there beside Render
Starter and is still not recommended. The free GitHub Actions pinger decided on later that day (see
*Cold start, measured three times*, below) costs nothing but free instance-hours and is a separate
call.

The largest single interactive win is in Wave 2: nearly half of all act-loop output tokens are a
closing answer that nothing reads. Wave 1 is being implemented in the final fix wave (P14); Wave 2
awaits Sean's decision because it re-drives the evaluation and re-labels.

---

## 2026-09-10 — Wave 1 and Wave 2 implemented; streaming verified live

- **Wave 1 (P14, 1,745 tests):** query-embedding memo (the same question was embedded twice on most
  turns), trace-store reads off the request path, the limiter documented with the measured account
  limits, a contamination gate that refuses to publish a run with any failover or retry, and the
  Gemini price table corrected for the paid tier.
- **Wave 2 A–D (P15, 1,767 tests), one commit each:** the act loop's closing step is one sentence
  instead of a discarded 224-token answer; synthesis output trimmed on the two de-risked clauses;
  search hits carry the whole passage (with the quarantine shield: a poisoned chunk's text never
  reaches the model); the model-facing tool envelopes drop telemetry keys, with one shared
  definition of which envelopes count as evidence.
- **Wave 2 E (P16, 1,814 tests):** the answer streams to the browser block by block and is replaced
  by the final version when the guardrails finish; the chat page narrates each step as it starts
  ("Searching the policy library…", "Checking your PTO balance…", "Writing the answer…"); the
  per-string span cap raised to 24 KB so a search result is stored whole.
- **Live verification** of the streaming path against the real Anthropic API on a local server: the
  first answer block arrived while later blocks were still being written, eleven progress lines, a
  fully cited answer, no errors. Reviewers had flagged this as the one thing tests could not prove.

Next: one deploy carrying all three phases, the final three-arm sweep with the judge, blind labels,
and the before / after-P13 / final comparison.

---

## 2026-09-11 — The final column: after Waves 1 and 2 (deployed, `r_1789086979_baseline`)

One deploy carrying P14, P15 and P16; the same 26 items, judge and instance as the two earlier
columns. 249 judge calls (≈ $0.15). Blind reference labels re-authored for these answers before the
judge ran: agreement 1.00 on the seed subset (n=8).

| Metric | Before | After P13 (quality) | Final (quality + performance) |
|---|---|---|---|
| Strict pass rate (target ≥ 0.85) | 0.692 | 0.808 | **0.808** |
| Groundedness | 0.979 | 1.000 | 0.982 |
| Citation accuracy | 0.847 | 0.914 | 0.925 |
| Partial match (gold facts) | 0.794 | 0.875 | 0.852 |
| Doc recall | 0.855 | 0.974 | 0.974 |
| Tool selection F1 | 0.926 | 0.987 | 0.992 |
| Workflow completion | 0.769 | 0.846 | 0.846 |
| Over-refusal / missed-refusal | 0.111 / 0.000 | 0 / 0 | 0 / 0 |
| Latency p50 | 17.6 s | 22.6 s | **16.7 s** |
| Latency p95 | 47.7 s | 39.2 s | **32.4 s** |
| Ablation delta (tools removed) | −0.154 | −0.192 | −0.231 (bar 0.25) |

**Reading it.** The performance waves gave back the five seconds the quality fixes had cost at the
median and cut the tail by a third, with no quality metric moving more than noise (groundedness
1.000 → 0.982 is one item; citation accuracy and tool selection improved). Five items still fail
strict pass: two lose one answer block to the citation guardrail (a citation to an id that does not
resolve), three miss the "three distinct documents" end state on multi-document questions.
Those are the next targets if the 0.85 bar is to be cleared. The ablation gap widened again with
the tighter workflow rule and now sits just under the pre-registered bar; it is reported as
not supported, with the arm's changed meaning stated beside all three figures.

**Interactive experience.** Streaming and the progress lines do not show in these numbers (the
harness waits for the whole answer); the live check showed the first answer block arriving while
later blocks were still being written, and each step announced as it began.

---

## 2026-09-11 — Cold start, measured three times without keep-alive

Each probe left the instance untouched for 1,000 s so Render spun it down (its own health-check
lines stop after 15 idle minutes), then timed the wake with `scripts/measure_cold_start.py`. Probe 1
ran on the readiness-fix build `bf85ffd` at 18:55Z on 2026-09-10; probes 2 and 3 ran on the final
build `da0dca2` — the one that served the published evaluation run — at 02:19Z and 02:37Z on
2026-09-11.

| Segment | Probe 1 | Probe 2 | Probe 3 | Median |
|---|---|---|---|---|
| Spin-up and container start until `/health` answers | 44.8 s | 43.5 s | 52.4 s | 44.8 s |
| `/health` to `/ready` | 2.8 s | 0.1 s | 0.1 s | 0.1 s |
| First `POST /chat` | 23.3 s | 23.9 s | 25.2 s | 23.9 s |
| First request, end to end | 71.0 s | 67.5 s | 77.6 s | 71.0 s |
| Warm turn immediately after | 22.5 s | 22.5 s | 23.9 s | 22.5 s |

Medians are per segment, so they do not add up to the total median, and each total is the measured
wall clock rather than the sum of its rounded segments. Probe 1's 2.8 s to `/ready` is the
readiness-fix build reloading a cold ONNX session; probes 2 and 3 answered `/ready` in 0.1 s, which
is what the baked model cache buys once the instance is up. The script prints its table and writes
no file, so the three probes are transcribed into
[`docs/evidence/cold-start-probes.json`](evidence/cold-start-probes.json) with their timestamps,
their shas and the ledger entry each came from.

**Decision (Sean, 2026-09-10 20:40Z, taken before these probes ran).** Measure the cold start first,
then remove it: keep the table above as the documented no-ping behaviour — it is the number the
rubric asks us to explain — and add a GitHub Actions keep-alive that pings `/health` every ten
minutes. One always-on free instance uses about 744 of the 750 free instance-hours a month, and
running out suspends the service until the month resets rather than billing anything. The warm-turn
row is the same turn the evaluation runs measure; the cold-start penalty is entirely the 45-second
wake.

**Status: `.github/workflows/keepalive.yml` landed 2026-09-11, after these probes, and an
in-process self-ping joined it the same day as the primary layer — but that layer starts only when
`KEEP_ALIVE_URL` is set on the service; it **was set on the live service on 2026-09-11 at 14:26Z** and verified by uptime (60 min at 18:37Z, 124 min at 00:51Z next day, with no traffic but health reads), so every figure
above is still the behaviour a visitor gets; disabling the workflow and leaving the variable clear
keeps it that way.**

---

## 2026-09-11 — What a real browser showed, and the last fixes

A live session in Chrome through the grader link (after the final review's fixes were deployed):

- **Worked as designed.** Cookie exchange from the tokenized link; a PTO question narrated on the rail
  step by step in plain language; a cited answer with policy-fact and recommendation blocks; demo 2
  reached the "Confirm before anything is written" card with the exact payload, and Confirm resumed
  the turn with the rail still narrating. The store confirmed the mechanics: confirmation consumed,
  ticket MOCK-HR-000002 written.
- **Defect 1 — the keep-alive was not keeping anything alive.** GitHub's scheduler ran the `*/10`
  workflow twice in nine hours (09:48Z and 13:53Z), so the instance was asleep when the page was
  opened. Fix (P21): a self-ping inside the app every ten minutes through its own public hostname,
  which runs exactly when the instance is up and needs no scheduler; the Actions workflow stays as a
  second layer and the docs state the measured scheduler behaviour.
- **Defect 2 — a confirmed write was denied by the answer.** The synthesis prompt carried the created
  ticket verbatim, yet the model closed with an escalation saying it could not open PTO requests.
  Fix (P22): a deterministic "outcome consistency" step builds the first answer block from the tool
  result ("Done: HR ticket … was opened in queue …"), replaces an escalation that denies a performed
  action, drops a next step that asks for the write again, and a prompt rule points the model the
  same way; the stub demo and the live rehearsal script now assert the ticket id appears.
- **Cosmetic.** An empty "Writing the answer…" preview and the "Waking the free instance…" banner were
  visible at rest — a `[hidden]` attribute losing to `display: flex`, fixed with one CSS rule. The
  gated write's rail line now reads "Needs your confirmation" in amber instead of "error" in red.
- **CI.** The new coverage tracer halved the CI runner's speed and exposed a race in a health-check
  test (the boot-time import of twelve evaluation runs was still running); the test now waits for the
  import instead of racing it. Coverage gate: 90% enforced in CI; measured 95.5% lines / 87% branches
  before the last two waves, 94% with the branch-weighted total afterwards.

Final suite: 1,933 tests, pristine under `filterwarnings = error`.

---

## 2026-09-11 — The independent grade, and the last two waves

An independent grading pass (22 agents: inventory, one grader per rubric bullet, a skeptic on every
score, a synthesized card — committed under `docs/evidence/`) put the project at band 5 with two
bullets at 4.5. Everything checkable that it found was fixed in two waves:

- **Grade-card fixes (P23).** The deployed MCP endpoint had been rejecting external clients with
  HTTP 421 (the SDK's DNS-rebinding protection defaults to loopback hosts) while the documents
  invited a grader to attach MCP Inspector; the allowlist is now a setting, set on the service, and
  an external `initialize` answered 200 at 20:32Z. Stale test and statement counts, a 120- versus
  420-person headcount contradiction, a stale traceability row, run files that recorded the commit as
  "dev", an overstated labeller-independence claim, and an architecture page that loaded web fonts
  against a "no network" claim were all corrected; the process trail (briefs, reports, ledger) is now
  committed under `docs/process/sdd/`, and live demo transcripts are pinned under `docs/evidence/`.
- **Model-behaviour fixes (P24, approved by Sean).** Multi-document answers now cite every document
  their evidence spans, with one bounded repair call when they do not; two HR-adjacent
  out-of-corpus questions (tuition reimbursement, referral bonus) joined the dataset, which is now
  28 items; the two citation-guardrail block drops were traced to a quarantined chunk carrying a
  citable id and a one-character transcription slip, both fixed at the root.

| Metric | Before | After quality fixes | After perf waves | **Final (P24)** |
|---|---|---|---|---|
| Strict pass rate (target ≥ 0.85) | 0.692 | 0.808 | 0.808 | **0.893** |
| Groundedness | 0.979 | 1.000 | 0.982 | 0.984 |
| Citation accuracy | 0.847 | 0.914 | 0.925 | 0.905 |
| Doc recall | 0.855 | 0.974 | 0.974 | 0.961 |
| Tool selection F1 | 0.926 | 0.987 | 0.992 | 0.993 |
| Workflow completion | 0.769 | 0.846 | 0.846 | **0.893** |
| Over-refusal / missed-refusal | 0.111 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Latency p50 / p95 | 17.6 / 47.7 s | 22.6 / 39.2 s | 16.7 / 32.4 s | 19.1 / 38.7 s |
| Judge agreement, seed / hard (n=8 each) | 1.00 / 1.00 | — | 1.00 / 0.875 | 0.875 / 0.875 |

**Reading it.** The project's own strict-pass target is met for the first time; three items remain
(remote-003, remote-004, unsafe-001). The breadth repair costs about 2.4 s at the median, a trade
accepted for the pass rate. Both blind labellers independently caught the same judge miss, a next
step ("submit claims by month-end") that no evidence states, which is why agreement reads 0.875
rather than 1.0 and why "ground the next steps" is the recorded follow-up. The ablation delta
(−0.143) stays under the pre-registered 0.25 bar and is still reported as not supported.

---

## Demo talking points (to be finalised)

- Every optimization claim in this project is traceable to a run id and a span query; the
  dashboard shows the same traces the analysis used.
- The readiness defect is a good story: the instance passed every smoke and the whole evaluation
  while `/ready` was wrong, and only a measurement designed to fail honestly (refusing to publish a
  timeout as a number) exposed it.
- "Is it the CPU?" — the intuitive answer was wrong; two full runs settled it in one table.
