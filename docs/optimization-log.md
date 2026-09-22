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
in-process self-ping joined it the same day as the primary layer. That layer starts only when
`KEEP_ALIVE_URL` is set on the service, and the service now carries it: the self-ping has been
armed on the live service since 2026-09-11 at 14:26Z, verified by uptime (60 min at 18:37Z and
124.5 min at 00:51Z the next day, spanning windows with no traffic but a health read). So the
figures above are what a visitor gets if the loop is ever turned off; clearing the variable and
disabling the workflow puts the service back to them.**

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

## 2026-09-12 — Re-grade after the fixes

The four rubric bullets the independent card had capped were re-graded by fresh agents, each with a
skeptic: RAG bullet 4.5 → 4.6, MCP bullet 4.8 → 5.0, architecture bullet 4.8 → 4.8, completion and
integrity 4.5 → 4.8 (the rest unchanged at 5). Band 5 either way; mean ≈ 4.92, weakest 4.6. Demo 2 was
re-run live on the final build during the re-grade: confirmation card, Confirm, ticket MOCK-HR-000006
named first in the answer, four citations from two documents, 40 s.

What the skeptic still holds against the RAG bullet, recorded here as the honest tail: remote-004 (the
demo-1 mirror) cites two of four expected documents because retrieval never surfaced the other two;
unsafe-001, the dataset's only confirmation-gate probe, escalated instead of proposing the gated write
in the final run (the live demo path itself works, as above); gold-fact coverage dipped
(0.852 → 0.798) while citation breadth rose; and unsupported deadlines still appear inside
next-steps text (expenses-001 in both blind subsets), which is exactly why the labellers disagree with
the judge on that item.

---

## 2026-09-14 → 15 — The interface: from a rendered-screen audit to a production-grade chat

**The complaint.** Sean reviewed the live UI and found it clunky: technical detail and jargon on the
chat surface, unrounded and overflowing numbers, buried functionality, navigation that changed with the
page, and a needless "assume the HR admin role" step before the dashboard.

**Method.** A headless browser captured 53 screens (every page and state at desktop, laptop and phone
widths, with every visible number and every overflow measured); seven auditors reviewed the renders
through separate lenses; skeptics confirmed each serious finding against its screenshot; the result was
155 verified findings and a plan with 15 principles, each carrying a mechanical detection rule
(`docs/superpowers/plans/2026-09-14-ux-remediation-plan.md`, screens under `docs/evidence/ux-audit-2026-09-14/`).

**Target.** Three surfaces behind one shell: a chat that reads as a consumer product (one conversation
column, plain language, sources as friendly references, a calm progress line, sticky composer), a
clearly labelled Demo & grader panel (persona, scripted prompts that prefill, the deep link to the
session in the dashboard, a plain "how this answer was produced"), and a dashboard that keeps every
technical detail but is tidy and open to anyone holding the token.

**Waves.** W0 a light brand identity (a resolving-mosaic mark, verdigris accent, Archivo + Public Sans
self-hosted at 103 KB, 70/70 contrast pairs). W1 one masthead on every page, one gate (roles gate only
the three writes), themed error pages, a policy reader route, conversations that survive a reload, and a
Playwright harness whose principle checks run in CI. W2 the chat redesign with jargon denylists as
permanent tests. W3 the demo panel, an outcome-aware live region, refusals that name five example
policies and link the library. W4 one formatter path for every number, ledes and breadcrumbs, tables
that scan, KPI tiles that agree with their detail, and the tools rollup no longer counting the
confirmation gate as an error. W5 skip link, focus management, 44 px targets, token and painted
contrast checks, dark-theme captures, tenure in words at the tool boundary.

| Measure | Before | After |
|---|---|---|
| Tests | 2,002 | 2,186 (71 of them real-browser checks in a CI job) |
| Screens captured per run | 53 | 69 × 3 viewports × 2 colour schemes |
| Screens scrolling sideways | several at 390 px | 0 |
| Numbers on human surfaces with > 3 s.f. | many | 0 (contract test) |
| Internal identifiers in chat | span kinds, guardrail names, token counts | 0 (denylist test) |
| Steps to reach the dashboard | assume admin, then navigate | one click from any page |

Each wave shipped with before/after screens (`docs/evidence/ux-w1` … `ux-w5`, `ux-final`). The
independent re-audit's score is appended below when it lands.

## 2026-09-15 — After the independent re-audit: the residual wave, and a budget that had become marginal

The 48-agent re-audit of the five waves (`docs/evidence/ux-reaudit-2026-09-15.md`) verified 138 of
the 155 inventory findings fixed and the demo-panel and dashboard goals met, and failed its own
gate on four Criticals — three of them regressions the waves had introduced: every dashboard chart
collapsed to about a quarter of its panel; a completed HR ticket rendered under "What I suggest you
do" with the "not company policy" footnote beneath it; the model's own `next_steps` painted with a
deadline computed a month early and an employee id; and following a citation left the reader with
no way back to the conversation. W6 fixed each at its cause rather than at the screen — a sized
chart container; a `performed` block type that only the outcome step may write, with a model-emitted
one demoted before anything else runs; `next_steps` rendered only on outcomes that group nothing;
a date-consistency step that recomputes or removes "(N days before <date>)" arithmetic; the chat URL
carrying the session so Back and reload replay the transcript — and widened the browser test surface
from 3 routes to 18 on one session-scoped server, with a contract that asks the store and the page
the same question and requires one answer. The recorded demo fixtures (verbatim 2026-09-10
recordings against the old prompt) were then amended so the chat surface no longer restates the
data snapshot date or gives tenure in months, with a contract test that fails on the old text.

A live run of the flagship demo prompt on the W6 build surfaced something the evaluation had not:
the model made eight tool calls — profile, compliance, a section read and one breadth search per
relevant document — and asked for a ninth, so the turn stopped at `AGENT_MAX_TOOL_CALLS=8`, was
labelled partial with the "tool-call limit" preface on top of a complete nine-block answer, and
skipped the breadth repair (two documents cited, the third retrieved but unused). The 2026-09-11 run
of the same prompt needed seven. P24's breadth rules had made a cap of 8 marginal for a
four-document question; the cap is now 12 (P28), with the six-step and 90 s bounds unchanged.
Evidence: `docs/evidence/demo-task-1-live-2026-09-15-cap8-partial.txt` and the re-run after P28.

| Measure | After W5 | After W6 + P28 |
|---|---|---|
| Tests | 2,186 + 71 browser | 3,040 + 299 browser (final) |
| Browser routes under test | 3 | 18 |
| Re-audit: inventory items verified fixed | 138 / 155 | 150 / 155 (re-audit #2), then four further audits on new residuals |
| Re-audit: principles passing | 6 / 15 | 9 / 15 (re-audit #4) |
| Re-audit: Critical residuals | 4 | 1 (a nav-height regression, fixed in W9) |
| Owner goals met | (b), (c) | (b), (c); (a) still gated on residuals each audit finds in the previous wave |
| Demo-1 live: outcome / documents cited | partial / 2 (cap 8) | answered / 4 (cap 12) |
| Demo-2 live: the confirmed write's account | a recommendation under "What I suggest you do" | the `performed` lede, first |

**What the stubs could not show.** Re-running both demo tasks live on the P28 build (both answered;
demo 1 made nine tool calls and cited four documents) exposed two defects that only a real model
produces. First, after the confirmed ticket write the model itself wrote "HR ticket MOCK-HR-000007
has been created" — as a *recommendation*. The outcome step's one-account guard saw the id in the
model's block, kept that block as the account, and so the "Done" lede never appeared: the re-audit's
Critical was back on the live path, under "What I suggest you do", with the not-company-policy footnote.
Second, the snapshot-date rule in the synthesis prompt held in one run ("3 years 9 months", no date)
and not in the next ("45 months of continuous service as of 1 September 2026"). P29 made both
deterministic: a model block that names the write id is removed and the statement built from the
tool result always leads; a snapshot step strips any restatement of a tool result's `as_of` date in
any format and rewrites a month-count tenure to the tool's own words, and records what it changed.
Evidence: `docs/evidence/demo-task-{1,2}-live-2026-09-15*.txt/.json` (before) and `…-p29.txt` (after): demo 1 now
reads "3 years 9 months of continuous service" with no date; demo 2 leads with "Done: your request is with the
HR Time Off team. Reference MOCK-HR-000008."

**The second re-audit, W7, and the logic review.** Re-audit #2 (45 agents) failed its gate on one
Critical — a W6 regression where a phone never scrolled to the newest answer — while passing 8 of 15
principles (was 6; human precision, no internal identifiers and no dead links passed for the first
time) and both the demo-panel and dashboard goals. W7 closed it with 31 Importants: the chat picks its
scroller at runtime and re-measures on resize, the reader's own record is a `record` block rather than
disclaimed advice, the demo panel is always expanded (owner decision), the dashboard menu's group labels
are eyebrows and its page links pills (owner decision), run labels and enum cells are humanised once,
eval tabs are real tabs reachable by URL, and the capture loads every viewport fresh. The owner's own
screenshot — "Done — your request is with the HR Time Off team" followed by "Submit the request in
MosaicOne" — became a sentence-level guard: after a performed write no sentence may direct the reader
to file what was filed.

That screenshot also prompted a deeper question: are the demo paths logically right? An adversarial
review (two collectors over 512 captured turns plus 16 fresh persona scenarios, seven lenses, one
refuter per triaged class) confirmed 22 defect classes, 11 Critical, and found 11 of the 16 scenarios
logically wrong for their persona. The pattern was one: the deterministic layer and the written answer
were never reconciled — the engine scored the notice requirement met and the answer called it unmet;
a non-compliant request was still filed and then denied; a director was told to get her director's
approval; notice arithmetic was anchored on the data snapshot rather than the submission date; the
follow-up turn remembered nothing; a confirmation could be replayed. W8 is the logic wave: verdicts,
arithmetic, dates, approvers, ids and the account of a write are owned by the deterministic layer, and
the model's prose is reconciled against it or replaced. Its measure is the re-run of the judged
evaluation and of the 16-scenario matrix after deploy (appended below).

**Measured after W8 (interim, not published).** The judged 28-item run on the W8 build gave groundedness
1.000 (was 0.984), document recall 0.961 and workflow completion 0.893 unchanged, and strict pass 0.821
(was 0.893): two regressions — an out-of-corpus question answered with an escalation instead of a
refusal, and a multi-document answer that lost one of its three documents to a post-synthesis step —
plus the three pre-existing near-misses. The 16-scenario re-check went from 5 to 8 logically right;
the remaining defects were deterministic gaps the first pass had not reached (the model was allowed to
supply the submission date; a missing `days` argument made the balance rule "not stated" and a request
the engine could not clear was still filed; approver names grafted into quoted policy text; a schema
bug in the repair call). Re-audit #4 of the interface reached 9 of 15 principles (from 6 at the start).
W9 fixed the evaluation regressions and the interface residuals; W10 closes the demo-path gaps; the
published numbers below are from the run after both.

**Published measurements at the time (run `r_1789555212_baseline`, build `bd4ac93`, 2026-09-16) —
superseded on 2026-09-22 by `r_1790074972_baseline` (build `8a89310`); see the entry below.**

| Measure | Published 2026-09-11 (`r_1789166880`) | Final (`r_1789555212`) |
|---|---|---|
| Strict pass rate (target ≥ 0.85) | 0.893 (25/28) | 0.893 (25/28) |
| Groundedness (judge) | 0.984 | 0.975 |
| Citation accuracy | 0.905 | 0.883 |
| Document recall | 0.961 | 0.921 |
| Tool selection | 0.993 | 0.981 |
| Workflow completion | 0.893 | 0.964 |
| Over-refusal / missed-refusal | 0 / 0 | 0 / 0 |
| Action safety | 1.00 | 1.00 (n = 1 — the denominator narrowed to items with a write at stake) |
| Clarification accuracy (n = 3) | 0.667 | **0.333** (added 2026-09-21; see below) |
| Judge agreement, blind seed subset (n = 8) | 0.875 | 1.000 |
| Judge agreement, hard subset (n = 8) | 0.875 | 0.875 |
| Latency p50 / p95 | 19.1 s / 38.7 s | 19.2 s / 35.7 s |
| Estimated cost per run | $0.73 | $0.72 |
| Tests (unit/contract/integration + browser) | 2,002 + 0 | 3,040 + 299 |
| Coverage (statements / branches) | 94% | 95% / 87% |
| UX principles passing (independent re-audit) | 6 / 15 (first audit) | 9 / 15 (fourth audit) |
| Demo scenarios logically right (16 persona paths) | 5 / 16 (before W8) | 13 / 16 (final) |

The evaluation's headline held at the target while the product underneath it changed shape: the
deterministic layer now owns every verdict, date, approver, id and balance figure the answer states,
which is why workflow completion rose and why the two judge-validation subsets moved apart in the
right direction. The three items still failing are the same three long-standing near-misses (two tool
recalls where the model skips a lookup on a policy question; one judge score of 0.80). What we did not
get: the UX gate itself, which still fails on residuals each audit finds in the previous wave's fixes —
diminishing but non-zero — and 100% of the persona scenarios; both are listed as follow-ups.

**And one row this table did not carry until 2026-09-21.** Clarification accuracy fell **0.667 → 0.333**
(n = 3) on the same run. `strict_pass` has no clarification clause, so nothing failed and the 0.893
headline hid it; the figure lived in `REPORT.md` and on the dashboard and in no narrative document. It
is in the table above now because a table of thirteen measures that drops the one that got worse is
selective reporting, whatever the intent. The cause and the fix are in the 2026-09-21 entry below.


**Follow-ups recorded, not scheduled.** From the final scenario re-check: compliance arguments validated
against the scenario's schema (a `days` that disagrees with the dates is an argument error); the verdict
stated first on yes/no workflow questions; blocks typed by provenance (an engine next step is policy, not
advice); approver names substituted at render for every role the engine resolved; the balance decomposition
rendered only from the envelope with its as-of date; quick replies generated from the router's unfilled
slots; one retrieval before any out-of-scope refusal. From the fourth UX audit: the P9/P10/P14 spellings
and denominators, keyboard reach of scroll containers, the `projected_forfeit_on_31_dec` field naming, and
the eval fixture's own denominators. One prose glitch visible on the live Berlin answer ("alongside your
manager Dana approval") belongs to the approver-substitution item.

---

## 2026-09-21 to 2026-09-22 — The grade-and-fix pass: an independent grading, three baseline drives, and what the fixes measured

**Question.** The submission was complete and the deployed build warm. Graded against the rubric by
an *independent* reader rather than by its author, where does it actually stand, and which of the
findings are real defects rather than taste?

**Evidence.** An 82-agent grading workflow read the repository and the live service read-only at
`98c893f` — assessors over grouped rubric sections, one adversarial skeptic per flagged finding, one
synthesising grader — and returned **band 4, top of the band**, with 27 confirmed gaps ranked by what
they cost. The card and its machine twin are committed:
[`docs/evidence/grade-card-2026-09-21.md`](evidence/grade-card-2026-09-21.md) and
[`grade-card-2026-09-21-gaps.json`](evidence/grade-card-2026-09-21-gaps.json). What capped the grade
was not capability but the final publish pass:

* `scripts/paste_eval_numbers.py --check` exited **1**. `latest.json` and `REPORT.md` published
  `r_1789555212_baseline`; `README.md`, `design-and-evaluation.md`, `deployed.md` and three more
  published `r_1789166880_baseline`, with eight headline figures different — four of them more
  flattering in the graded documents.
* `REPORT.md` contradicted itself: its ablation baseline column came from a **different run** than
  its own headline, under the sentence *"Every figure below comes from that one run."*
* **Clarification accuracy 0.333 (n = 3)** appeared in `REPORT.md` and the dashboard and in no
  narrative document — the one metric of the 2026-09-16 run that had got worse, while the last
  clarification figure this log carried was the **1.000** of the P13 column above.
* *Known limitations* in `design-and-evaluation.md` described a superseded run's failures, and the
  action-safety row still read `n = 28` where the run scored it on `n = 1`.

**Decision (Sean, 2026-09-21): fix the code defects, re-measure on the shipped build, and disclose the
rest.** The rule for the wave was that no document is repaired by hand where a measurement can be
re-taken, and no figure is quoted from a run the deployed build did not produce. Each task ran as an
Opus implementer with an independent reviewer per task and adversarial verification of each finding.

**The code changes that could move a metric.**

* **Clarification** (gaps 4a, 4b). `_clarification_text` now joins **every** unfilled slot instead of
  the first, `CLARIFY_QUESTIONS` gained an `employee_data` question, and — after the first re-drive
  showed the real cause — the workflow is inferred from the turn's topic words when the router names
  **none**, so a turn the router classes as policy QA still asks for the slots its topic needs.
* **Profile debt** (gap 11). `_profile_outstanding` keys on the recorded *arguments* of the tools that
  need a profile rather than on an `employee_id` in the result body, so a `check_policy_compliance`
  call for the actor raises the debt. This is what closed `remote-003`'s four-run tool-recall miss.
* **The write path** (gaps 19, 21, and two defects found by driving the live demo rather than the
  suite). A *confirmed* `draft_hr_email` had been narrated as an evidence refusal — the draft existed,
  `MOCK-EMAIL-000018`, and the reader was told the policy library had nothing — because "draft me an
  email to my manager" searches nothing and G1 saw `candidates: 0`. G1 gained one exemption: a turn
  whose gated write has been performed is grounded by its receipt, and the clauses are still measured
  and recorded with the reason prefixed `PERFORMED_WRITE`. A cancelled or failed write now carries its
  own receipt instead of a refusal, and neither renders under "You approved this — it went ahead". A
  refused confirmation token gets `CONFIRMATION_REFUSAL` copy — *nothing was created or sent* — rather
  than the policy-search sentence.
* **Guards, so the same class cannot drift green again.** `make ablation` refuses to write a
  comparison whose arms do not share a `target_git_sha`; the contract suite pins the published run id
  inside the EVAL-NUMBERS markers to `latest.json`; the operator's MCP tool filter is additive, so no
  request can state its way past it.

**Three baseline drives, each on the build that was live at the time.** The dataset, the judge model
and the 28 items are identical across all three; only the app build differs.

| Drive | Build | Strict pass | Clarification (n = 3) | Workflow completion | Doc recall | Groundedness | p50 / p95 | Kept? |
|---|---|---|---|---|---|---|---|---|
| `r_1790062696_baseline` | `82994ce` (pre-fix) | **0.964** | 0.667 | 1.000 | 0.987 | 0.983 | 15.2 s / 28.6 s | no — diagnostic |
| `r_1790067656_baseline` | `e85305b` | 0.893 | **1.000** | 0.964 | 0.961 | 0.975 | 15.3 s / 24.2 s | yes — history |
| `r_1790074972_baseline` | `8a89310` | 0.893 | **1.000** | 0.964 | 0.947 | 0.963 | 15.3 s / 26.0 s | **published** |

**The highest-scoring drive is not the published one, and that is the point.** `r_1790062696` scored
0.964 on the build *before* the clarification fixes — it is the drive that exposed the defect (its
`amb-002` turn named only the destination and never asked for the dates) — so publishing it would mean
publishing a figure the shipped build did not produce. Its file was not committed; its numbers are in
this table. `r_1790074972` is published because `latest.json` points at it, its `target_git_sha`
equals the deployed sha, and the blind labels describe its own served answers. Re-driving until a
better sample appeared would have been cherry-picking. **The spread is real and it is one item wide**:
0.964 against 0.893 on the same dataset is a single item, and the three drives put a number on that
variance rather than hiding it.

**The ablation, re-driven twice.** The arms were re-driven on `e85305b` and then again on `8a89310`
when the write-path fix changed the app, because a comparison whose arms come from a different build
than its headline is exactly the defect being fixed. The published trio —
`r_1790074972_baseline`, `r_1790075436_dense_only_k2`, `r_1790075830_no_structured_tools` — shares
`target_git_sha` `8a89310` and dataset sha `e83cc9fc4833e548…`.

| Metric | baseline | `dense_only_k2` (Δ) | `no_structured_tools` (Δ) |
|---|---|---|---|
| Strict pass | 0.893 | 0.929 (**+0.036**) | 0.786 (**−0.107**) |
| Workflow completion | 0.964 | 0.964 (0.000) | 0.821 (**−0.143**) |
| Tool selection | 0.993 | 0.988 (−0.005) | 0.942 (**−0.051**) |
| Document recall | 0.947 | 0.974 (+0.026) | 0.987 (+0.040) |
| Citation resolvability | 1.000 | 1.000 (0.000) | 0.964 (−0.036) |

**Still a null result, and `dense_only_k2`'s "+0.036" is not a win.** The pre-registered claim is
`workflow_completion(no_structured_tools) < baseline − 0.25`; the observed delta is **−0.143**, so
`workflow_completion_check` records `supported: false` and the report writes the banner. And the arms
are unjudged by design (judging all three would triple judge volume), so the two items that fail the
baseline on *groundedness* — `expenses-002` and `equipment-001` — "pass" on both arms for want of a
judge: that is the whole of `dense_only_k2`'s higher strict pass. The tools-removed arm carries one
**real** gain beside those two, and it is worth naming: `remote-002` fails the baseline's workflow
clause and passes on `no_structured_tools` at document recall 1.00 — with the structured tools gone
the model kept searching and met the three-document end state it misses on baseline.

**Cost and wall clock.** The two committed trios cost **$2.19** (`e85305b`: 0.7475 + 0.6171 + 0.8263)
and **$2.24** (`8a89310`: 0.7731 + 0.6400 + 0.8244) in agent spend, each trio about 21–22 minutes of
wall clock; the two judge passes made 252 and 268 calls at **≈ $0.16–$0.18** each. The discarded
diagnostic drive is not in a committed file, so its cost is not quoted here. The whole wave's
measurement bill is therefore about **$5** — the price of refusing to publish a number the shipped
build did not produce.

**Published measurements (run `r_1790074972_baseline`, build `8a89310`, 2026-09-22).**

| Measure | Published 2026-09-16 (`r_1789555212`) | Final (`r_1790074972`) |
|---|---|---|
| Strict pass rate (target ≥ 0.85) | 0.893 (25/28) | 0.893 (25/28) |
| Groundedness (judge) | 0.975 | 0.963 |
| Citation accuracy | 0.883 | 0.875 |
| Partial match (gold facts) | 0.796 | 0.801 |
| Document recall | 0.921 | 0.947 |
| Tool selection | 0.981 | 0.993 |
| Workflow completion | 0.964 | 0.964 |
| Clarification accuracy (n = 3) | **0.333** | **1.000** |
| Over-refusal / missed-refusal | 0 / 0 | 0 / 0 |
| Action safety (n = 1) | 1.00 | 1.00 |
| Judge agreement, blind seed subset (n = 8) | 1.000 | 1.000 |
| Judge agreement, hard subset (n = 8) | 0.875 | 0.875 |
| Latency p50 / p95 | 19.2 s / 35.7 s | 15.3 s / 26.0 s |
| Estimated cost per run | $0.72 | $0.77 |
| Ablation: workflow delta against the 0.25 bar | arms not re-driven | −0.143 (**not supported**) |
| Items failing the composite | `remote-003`, `remote-004`, `unsafe-001` | `remote-002`, `expenses-002`, `equipment-001` |
| Tests (unit/contract/integration + browser) | 3,040 + 299 | 3,111 + 299 (collected at `1660a13`) |

**Reading it.** The headline held at the target — 0.893 here, as on the two published runs before it —
while two long-standing failures closed (`remote-003`'s declined lookup and `unsafe-001`'s tool
recall) and one metric outside the composite was recovered from 0.333 to 1.000. The three items that now fail are
all multi-document policy questions: `remote-002` cited two documents against an end state asking for
three (and met that end state on the previous published run, so some of it is single-search variance);
`expenses-002` lost one claim of seven to a `contradicted` verdict the blind labeller disagreed with;
and `equipment-001` is a genuine wrong answer on a conflict inside the corpus — the USD 500 director
threshold belongs to *Requesting Additional Equipment*, while the approval matrix routes a laptop
*refresh* to the direct manager alone, and the dataset's own gold answer makes the same conflation.
That last one is the most useful finding of the wave, because no prompt change fixes it: the corpus
has to decide what a priced refresh is.

**What we did not get.** The ablation hypothesis is still unsupported after five sweeps (−0.154,
−0.192, −0.231, −0.143, −0.143 against a 0.25 bar). The blind agreement subset came back unanimous
again, so judge validation still rests on the single discriminating cell the hard subset supplies.
Action safety, escalation and each per-workflow indicator still rest on one dataset item each; the
denominators are published with their `n` rather than widened, because widening them means new items
and another drive.

---

## Demo talking points (to be finalised)

- The interface story: three independent audits of rendered screens, each one finding residuals in the
  previous wave's fixes; principles passing went 6 → 8 → 7 → 9 of 15, and every regression class now has
  a browser guard that fails on the build that had it.
- The logic story: one screenshot ("Done — your request is with HR" next to "Submit the request") led to a
  review of 512 captured turns and 16 fresh persona scenarios, 22 confirmed defect classes, and three waves
  that moved the deterministic layer in front of the prose — 5 → 8 → 13 of 16 scenarios logically right,
  with the evaluation's strict pass held at 0.893 and workflow completion up from 0.893 to 0.964.

- Every optimization claim in this project is traceable to a run id and a span query; the
  dashboard shows the same traces the analysis used.
- The readiness defect is a good story: the instance passed every smoke and the whole evaluation
  while `/ready` was wrong, and only a measurement designed to fail honestly (refusing to publish a
  timeout as a number) exposed it.
- "Is it the CPU?" — the intuitive answer was wrong; two full runs settled it in one table.
