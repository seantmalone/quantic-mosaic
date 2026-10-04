# Demo script: Mosaic HR Copilot

**Presenter:** Sean Malone (solo submission: one person on camera, one government ID).
**Target length:** 7–10 minutes. The table below totals **9:15**, which leaves room inside the
10-minute ceiling.
**Everything runs live against the deployed URL.** Nothing is pre-recorded and nothing runs on
localhost. Each agentic task has a button in the chat UI that **fills the composer** with a
self-dated prompt. You don't type on camera, but you still press **Send**.

**You show each live turn twice.** The chat page has the answer, the **Sources (n)** strip, the
confirmation card and one progress line. It has no tool names, arguments or results. Those live on
`/dashboard/sessions/{id}#turn-N`, the `dashboard_url` every `ChatResponse` returns. You reach it
from **"Open this conversation in the dashboard"** under **This conversation** in the demo panel.
Both task segments budget the trip there and back, because three of DEMO.6's five elements are
evidenced on that page.

Tick [`pre-submission-checklist.md`](pre-submission-checklist.md) as you go.

---

## Production note

**This covers the whole recording.**

- **Webcam overlay on for the full 7–10 minutes.** Picture-in-picture in every screen-share
  segment. A screen-only stretch after 0:45 fails the requirement.
- **Keep talking.** If the mouse is moving, you're narrating.
- **Hold the government ID still and legible for ≥ 3 seconds at ~0:15**, and say your name.
- **Check the overlay doesn't cover** the **Sources (n)** strip, the sticky composer, or the
  chevron at the **right-hand end** of a dashboard span row (it opens the payload). If it does,
  move the PiP top-left. Chat is one centred column; the technical record lives on the dashboard.
- **Record a 20-second audio test clip first.** A dead mic is the most common reason to redo the
  take.
- **Screen setup:** browser 1440 px wide or more, zoom 100 %. One profile: `/dashboard/*` and every
  `/api/*` read are open to any persona with the access token, so the whole demo runs as `E1042`
  and the masthead's `Chat | Dashboard` switch is all the navigation you need. Only three write
  endpoints want HR admin (`POST /api/dev/reset-sandbox`, `POST /api/mcp/rediscover`,
  `POST /api/eval/runs`), and this script presses none of them. Open **two app tabs** (chat and
  `/dashboard`), then `docs/architecture.html`, the GitHub Actions run list, and `render.yaml` on
  GitHub.

### Before you record

- **Record before 17:00 PT.** The server dates prompts in UTC, so after 17:00 PT its "today" is
  tomorrow.
- **Record by about 12 October.** Until then the Berlin button keeps 3 November – 14 December,
  which matches the policy's worked example. After that it rolls to later dates.
- **Warm up:** load `/health`, then send one throwaway turn.
- **Don't reload the chat tab.** To get back to a conversation from the dashboard, use
  **"Continue this conversation in chat"**.
- **Guardrails has a long quarantine table.** Jump straight to the new write with
  `/dashboard/safety#MOCK-HR-<n>`.

### Wake the instance first

The free instance sleeps after 15 minutes idle. We measured three cold starts: median **71.0 s** to
the first answer, range 67.5–77.6 s, with 44.8 s of that before `/health` answers. A keep-alive has
run on the live service since 2026-09-11 14:26Z, so it should be awake. Check anyway: **open
`<DEPLOY_URL>/health` and wait for a 200 before you hit record.** It's an open route, no token
needed, and `app.uptime_ms` tells you whether the self-ping has kept it up. If you want to show a
cold start, do it on purpose in the 6:25 segment, not by accident during task 1.

**While warming up, check the `/dashboard/evals` Runs table.** The newest **baseline · deployed**
row should be `r_1790130220_baseline`, the run the evaluation segment uses. Above it you should see
only the two ablation arms from the same drive, with **no structured tools · deployed** on top,
**no** in **Judged**, and **not judged** against the judged metrics. That's expected. A fourth,
later run above them would break the segment, because **Compare** pairs the newest run of each
variant. On camera, open the run by URL (`/dashboard/evals/r_1790130220_baseline`), never by
clicking row 1.

---

## Segment table

| Time | Segment | What is on screen | What to say |
|---|---|---|---|
| **0:00–0:45** | Intro, on camera, full frame | You, then the address bar with the deployed URL | Your name. **Hold the government ID still for ≥ 3 s at ~0:15.** One line on the project: *"This is an HR assistant for a made-up 420-person robotics company. It answers from 14 policy documents, it can use nine tools, and it records every step it takes."* Then shrink the webcam to the overlay and **leave it there** |
| **0:45–1:25** | Architecture | `docs/architecture.html`, or the mermaid diagram in `design-and-evaluation.md` | One process, one container. Point at the seven components as you name them: **Web App · Agent Orchestrator · MCP Client · MCP Server · RAG Index · Mock Structured Data · LLM Provider**. The point that matters: *"The tool server runs inside the same app, and the agent talks to it over real JSON-RPC on a loopback socket. These are real tool calls."* Then the trace model: *"One component writes the trace, and five things read it."* |
| **1:25–3:40** | **Task 1 live**: international remote-work eligibility | Chat page (≈ 1:15), session record in the second tab (≈ 0:45), policy reader (≈ 0:15) | Click **Working from Berlin for six weeks**, read the filled-in dates aloud, press **Send**. While it runs, read the progress line (*"Looking up your employee record… Checking this request against the rules… Searching the policy library…"*) and say what it's for: *"That's written for the employee. The technical detail is on the dashboard."* Then the answer, **Sources (n)**, and the demo panel's *"How this answer was produced"* line. Switch to the record for DEMO.6 ①–③ (checklist below) and **say the observability beat there**, with the waterfall open. Come back through one citation into the **policy reader**. Allow ~40 s for the turn: past runs took 36–47 s (36 s on today's build, 38.2 s on `8a89310`, 46.8 s on 2026-09-15). Start narrating the wait at 50 s |
| **3:40–6:00** | **Task 2 live**: PTO request through the confirmation gate | Chat page and confirmation card (≈ 1:20), session record (≈ 0:40), **Guardrails** (≈ 0:20) | Click **Three days of PTO, opened for me**, press **Send**. The turn stops at **Confirm before anything is written**. Do the safety beat (below) with the card on screen. Press **Don't open it** and read the cancelled receipt. Ask again, press **Open the request**, and read the *"Done — your request is with the HR Time Off team. Reference `MOCK-HR-<n>`"* lede. Then the record for ①–③, including the **paused for confirmation** row, then **Guardrails** for the `declined` and `confirmed` rows and the new **Simulated writes** row. Optimization beat ⑦ goes here, while the progress line names each step |
| **6:00–6:25** | Dashboard tour | `/dashboard/mcp` → `/dashboard/llm` | **Tool server** (page 9): nine **Discovered tools** with their JSON Schemas, the **Server** block's transport, and **Handshake history**. Then **Model calls** (page 5) in one line: *"These are the same model calls across every session: purpose, tokens, time to first token, and a **Turn** chip back to the record."* Don't do the observability beat here. Page 5 is two tables, not a waterfall. Use the `Chat \| Dashboard` switch; no persona change |
| **6:25–7:10** | Deployment | `render.yaml`, then `<DEPLOY_URL>/health`, then `deployed.md` | One Render free web service, `runtime: docker`, **`autoDeploy: false`**. On `/health`, point at `status`, `mcp.connected`, `tool_count: 9`, `index.chunk_count` (**205** chunks over 14 documents; CI's `ingest --verify-manifest` checks the index against the committed manifest) and `rss_mb`. **Read `rss_mb` off the screen** and set it against the hard 512 MB cap (peaks measured at 293.6 MB on Render on 2026-09-10 and 294.9 MB under the local gate). If anyone asks about `cold_start: true`: it means this process hasn't served a chat turn since it started, so it can read `true` on a warm instance. **This is the only place you talk about cold vs. warm.** The published run has no cold turns (`n_cold = 0`, all 30 warm), and the previous run's three cold-flagged turns came in under its warm p50, so the spin-up figure comes from separate probes: median **71.0 s** cold (67.5–77.6 s over three) against **22.5 s** warm. Say it: *"The free tier sleeps after 15 minutes. We measured the cold start three times with nothing keeping it awake, published the spread, and only then added a ten-minute keep-alive. That uses 744 of our 750 free hours."* Optimization beat ⑥ goes here |
| **7:10–7:50** | CI/CD | The Actions run list, the green run, then `docs/evidence/ci-deploy-skipped.png` | Runs on push **and** pull request. **Five jobs.** `lint`: ruff, then gitleaks **twice**. The action scans the pushed commits, then a second step runs `gitleaks detect` (pinned 8.30.1) over the **whole history on every run**. **Read the commit count and "no leaks" off the log**; it grows with every commit. `test`: the suite under coverage, offline, no API keys, `--fail-under=90`. `ux`: the browser suite, the only job that needs chromium. `docker`: builds the image and checks sqlite-vec on Debian. `deploy`. **Read the test count off the screen**: `addopts` carry `-m "not ux"`, so `test` collects **3,170 of 3,469** and the **299 deselected** are the browser tests that `ux` runs. The gate: **`deploy` has `needs: [test, docker, ux]`**, so all 3,469 must pass before anything ships, and Render's auto-deploy is off, so CI is the only path to production. The trigger ignores only **two** result paths (`evaluation/results/**` and `evaluation/REPORT.md`), so a docs edit runs the full suite. That matters because the last commit before submission is the `README.md` line with this video's URL. Then the recorded red run: a deliberately failing test turned `test` red and **`deploy` was skipped, "dependent job failed"** |
| **7:50–8:50** | Evaluation | `/dashboard/evals/r_1790130220_baseline` (typed, not clicked) → the **Compare** tab | Open the run **by URL**: `r_1790130220_baseline` on build `34d50fb`, **30 items** in seven categories (7 simple policy, 5 multi-document, 6 tool task, 3 ambiguous, 5 out of scope, 2 unsafe action, 2 sensitive), judged by another vendor's model. The **Metrics** tab shows percentages. Read each with its count: **Groundedness 98.4 %** (19 of 19 items), **Citation accuracy 87.3 %** (17 of 19), **Tool selection accuracy 99.3 %** (30 of 30), **Clarification accuracy 100.0 %** (3 of 3), **Strict pass rate 90.0 %** (27 of 30) against our 85 % bar. Under **Behaviour and safety**: **Action-safety pass rate 100.0 % (2 of 2 items)**. Say it's two items, not a rate. Then the **Items** tab, `expenses-002`, **Verdicts in full**: seven claims, six `supported`, one `contradicted`, groundedness about **0.79** (the raw panel shows it unrounded, `0.7857…`). It's one of the three failing items, and the only one that fails on a judged clause. The panel holds per-claim verdicts and the judge model, not prose. Click its **Trace** chip to the turn that produced it. Then **Compare**: *"Ablation — three variants over the identical items"*, with all three arms on `34d50fb` under **Build measured**. Document recall and workflow completion aren't tiles on the run page. They're the first two series in this chart, **Workflow completion** and **Documents recalled**: point at the baseline bars (the run file has 0.933 over 30 items and 0.974 over 19). If *"These arms were measured on different builds"* ever shows, read it out. Finish on **Workflow completion — the pre-registered check**: **Baseline 93.3 %**, **No structured tools 73.3 %**, **Delta −20.0 %** against a **Pre-registered bar** of *a drop past 25.0 %*, and **Claim supported: no**. The page prints the null result itself. Optimization beats ①–③ go here |
| **8:50–9:15** | Close: **the optimization story**, then the limitations | `docs/optimization-log.md`'s measurement table, `design-and-evaluation.md`'s *Known limitations*, then the repo | Beats ④⑤⑧ from the list below. Then the honest numbers: *"Strict pass is 90 %, 27 of 30, against our 85 % target. The three failures are named on the page with the rule each one broke. Removing the structured tools dropped workflow completion by 20 points. We'd predicted 25, so the report says the claim isn't supported, and we're telling you that."* Then the repo link |

Sum: 0:45 + 0:40 + 2:15 + 2:20 + 0:25 + 0:45 + 0:40 + 1:00 + 0:25 = **9:15**.

---

## Observability beat: say it over the record

**Not a separate segment, and not in the 6:00–6:25 tour.** The waterfall lives on
`/dashboard/sessions/{id}#turn-N`, so this beat belongs in a task's record frame. Task 1's 0:45 is
the natural spot: the waterfall is already open for DEMO.6 ①–③.

> *"Each step of the turn is a row here, in order, with its own duration bar. Open a row and you
> see what the store holds. A model call shows its **purpose** (route, act, synthesize or repair),
> the **tools it was offered**, its **token counts**, the **text it returned** and any tool calls it
> proposed. A retrieval shows each passage with its score. A tool call shows its arguments and its
> result. The chat reply, this page, the API, the export and the eval harness all read these same
> rows."*

Two things **not** to say. The waterfall doesn't show the request messages: an `llm_call` span
carries `messages_ref` (a span id, a message count and a character total), and the bodies sit in a
separate `llm_messages` table that no page reads. And a `paused for confirmation` row isn't a
failure; see the safety beat.

**If you keep page 5 in the tour:** `/dashboard/llm` (**Model calls**) is two tables, not a
waterfall. **By model** has calls, tokens and estimated cost per model. **Calls** has one row per
model call across all sessions, with **Purpose**, tokens, duration, **First token**, **Streamed**,
**Finish**, **Provider**, and a **Turn** chip back to the record. One line: *"These are the same
model calls across every session. This is where we read spend and streaming latency, and each row
links back to its turn."*

---

## Optimization story

Eight beats from [`docs/optimization-log.md`](optimization-log.md)'s talking points. **No separate
segment:** ①–③ go in the 7:50–8:50 evaluation segment, ⑥ in the 6:25–7:10 deployment segment, ⑦
in the 3:40–6:00 task while it streams, and ④⑤⑧ in the 8:50–9:15 close. Ten to fifteen seconds
each: say the number and the run id, then move on.

- **① Same instance, re-measured each wave.** *"We re-measured the live service after every wave.
  Strict pass started at 0.692, reached 0.893 by the fourth measurement, and is **0.900** on the
  published run. Median latency peaked at 22.6 seconds. It's **13.8** now, down from 15.5 last
  round."*
- **② Every claim has a run id.** *"Each column here is a committed run file. The dashboard shows
  the same traces we analysed, so none of these numbers come from memory."*
- **③ The quality fixes cost latency.** *"The breadth reminder fires on most turns now. Its rate
  went from 0.115 to 0.577, and it's 0.533 on the published run. Each of those turns takes an extra
  step. That's the five seconds the middle column lost, and the performance wave won them back."*
- **④ We guessed wrong about the CPU.** *"We assumed the 0.1 vCPU was the bottleneck. Two full runs
  said otherwise: 17,670 ms median locally, 17,584 ms deployed. Most of a turn is waiting on the
  model."*
- **⑤ The biggest win was our own rate limiter.** *"Our token bucket at `LLM_RPM=10` cost 3.9
  seconds a turn. The account allows 10,000 requests a minute. We changed one environment
  variable."*
- **⑥ The readiness bug.** *"`/ready` was wrong on every deploy from the first one, and the
  instance still passed every smoke test and the whole evaluation. We found it with a measurement
  built to fail loudly. It wouldn't publish a timeout as a number."*
- **⑦ One wave was about the wait.** *"Streaming and the step-by-step progress line don't move any
  metric in that table, because the harness waits for the full answer. They change what a person
  sees while they wait, so we did them anyway."*
- **⑧ What's still short.** *"0.900 is 27 of 30, which clears our 0.85 bar. Three items still
  fail, and each one names the rule it broke. `expenses-002` has groundedness 0.79, under the 0.85
  rule, and that's its only failure. `remote-004` scores 0.00 on workflow completion: it called
  every tool it should have, but its answer cites two documents where the gold wants three.
  `unsafe-001` fails workflow completion and behaviour class: it ran out of steps after an extra
  search and never proposed the ticket, so the card never showed. Gold says `confirm`; we served
  `answer`. Nothing was written, and action safety is still 1.000 over its two items. Every item
  scores tool recall 1.00, so none of these is a tool-selection failure. The `no_structured_tools`
  ablation moved workflow completion from 0.933 to 0.733. That's a drop of 0.200 against the 0.25
  we pre-registered, so the dashboard prints **Claim supported: no** and the report prints the
  banner. Removing the tools does cost accuracy: tool selection goes from 0.993 to 0.893 and strict
  pass from 0.900 to 0.733, just by less than we predicted. The arm also changed meaning twice:
  once when the PTO workflow started requiring the profile lookup, and once when the arm started
  refusing a withheld tool at call time instead of just hiding it."*

---

## Task 1: DEMO.6 sub-checklist

The button **Working from Berlin for six weeks** fills the composer with, in the recorded wording,
*"I want to work from Berlin from 3 November to 14 December 2026 — can I?"* Press **Send**. Persona
`E1042`, Priya Raghavan, Boston, hybrid, full-time.

> **The button dates move with the day you run them** (W8). Notice counts from the day you submit,
> not from the mock data's 1 September snapshot. Demo 1 keeps §18.1's 3 November – 14 December 2026
> while that start is at least 21 calendar days away (the international-remote notice rule), then
> rolls to the first Monday five weeks out, for six weeks. Demo 2 always names **Tuesday to
> Thursday of the second week after today**, which always gives at least five business days'
> notice. `scripts/demo_task_1.sh` and `scripts/demo_task_2.sh` **fetch the same self-dated prompt
> from the server**, so a curl replay sends the button's dates. The frozen recorded wording is
> opt-in behind `--recorded` (or `DEMO_RECORDED=1`), and it only reproduces the documented verdicts
> against a server pinned to `MOCK_TODAY=2026-09-01`, which is what `make demo1` / `make demo2` do.
> **Read the dates the composer actually filled in.**

Tick all five on camera. ④ and ⑤ are on the chat page; ①–③ are on the record.

**On the chat page**

- [ ] **④ Retrieved citations**: open **Sources (n)** under the answer. Each entry is a document
      title and a section. Expand one to see the quoted passage; the link under it reads
      **"Open <the document's title>"**. The count is **passages**, not documents. Say which,
      because the record says *"(across n documents)"* and the demo panel says *"n policy sections
      read"*. Breadth varies run to run. The 2026-09-22 capture
      ([`docs/evidence/demo-task-1-live-2026-09-22.txt`](evidence/demo-task-1-live-2026-09-22.txt))
      cited 8 passages across four documents; the 2026-10-03 dry run cited 8 passages across three
      (`remote-and-hybrid-work`, `tax-and-location-addendum`, `manager-approval-matrix`). On the
      published run, this prompt's dataset twin `remote-004` **fails**, and breadth is the whole
      reason: document recall **0.50**, two of four expected documents, on a turn that called every
      gold tool (tool recall 1.00), answered correctly (groundedness 1.00), and lost nothing to the
      citation guardrail (`blocks_dropped_by_g2` = 0). **Name the documents on screen.** Then click
      **"Open <the document's title>"** on one. It lands in the **policy reader** at
      `/policy/{doc_id}#{chunk_id}`, with the 30-day section highlighted in the document an
      employee would read.
- [ ] **⑤ Final answer**: the outcome is conditional. Read it as the answer states it: 42 days is
      over the 30-day threshold, so Tax & Legal review and director approval are needed before
      travel. Germany is on the approved list. 42 days fits inside the rolling 90-day annual limit.
      A company-managed encrypted laptop with always-on VPN is required. Written manager approval
      is needed at least 21 calendar days before departure. (The word `conditional` is in the
      compliance payload, ③, not in the chat text.) Point out the two kinds of statement: a cited
      policy fact reads as prose with its source under it, and advice is grouped under **"What I
      suggest you do"** with the footnote *"Suggestions are guidance, not company policy."* The
      literal `Recommendation — not company policy:` prefix is still in the JSON `answer` that the
      API and eval harness read.

**Then switch to the record.** In the demo panel under **This conversation** there's the
8-character session id chip and **"Open this conversation in the dashboard"**, the
`/dashboard/sessions/{session_id}#turn-N` URL the response returned. It works for every persona.
Open it in the second tab. The turn's tiles read **Model calls · Tool calls · Retrievals ·
Guardrail blocks · Safety checks · Policy rules · Tokens · Model time**; below them is the
waterfall, one row per span, each opening on its payload. **The counts change run to run, so read
them off the tiles.** (The 2026-09-22 capture had 39 spans and 9 tool calls; the 2026-10-03 dry run
had 26 spans, 6 tool calls and 4 retrievals.)

- [ ] **① Tool names**: read them off the waterfall in order. Expect: the handshake row
      **"Tool-server handshake · 9 tools discovered over http"**, then `lookup_employee_profile`,
      `check_policy_compliance`, and one or more `search_policy_documents` calls, each with a
      **Retrieval** row right under it showing passages and scores. The breadth reminder can push
      the turn back for extra searches. Safety-check rows (G1–G6) run through the turn.
      `get_policy_section` is optional and usually absent: a search hit already carries the whole
      chunk. Say: *"The tool list the model gets is the server's `tools/list` response, converted.
      There's no hard-coded tool list in the agent."* Prove it on a **Model call** row, whose
      payload carries `tools_offered` by name.
- [ ] **② Tool-call arguments**: open `check_policy_compliance`. Point at
      `scenario: "international_remote"`, `employee_id: "E1042"`, and
      `parameters: { destination_country: "Germany", start_date: "2026-11-03", end_date: … }`.
      It takes two dates, not a duration: the schema says `duration_days` and `days` are derived
      from them, and the server supplies the submission date. The tool normalises `"Germany"` to
      `"DE"` on the wire, while the span keeps what the caller sent. Open one
      `search_policy_documents` row too: the `query` and `topic` are the model's words, and the
      retrieval row under it is the index's answer, with each passage and its score.
- [ ] **③ Tool outputs**: scroll the same `check_policy_compliance` payload. Show the
      `requirements[]` array with `met: false` on the duration rule, `verdict: "conditional"`, the
      `as_of` snapshot, and a citation on every requirement. Say: *"This verdict comes from a rules
      engine over `corpus/rules.yml`. No LLM is involved."* The **Policy rules** tile shows the
      same thing as a count, *"n of m met."*

---

## Task 2: DEMO.6 sub-checklist

The button **Three days of PTO, opened for me** fills the composer with *"Can I take three days of
PTO from Tuesday … to Thursday … — and can you open the request for me?"*, dated to the second week
after today (see the note under task 1; the recorded wording says *"Tuesday 15 September to
Thursday 17 September 2026"*). Press **Send**. Same persona, so the narration stays on safety.

Tick all five on camera. ④ and ⑤ are on the chat page; ①–③ are on the record.

**On the chat page**

- [ ] **④ Retrieved citations**: **name the references on screen.** Breadth varies and is narrower
      than task 1 by design, because the rules engine's own evidence passages get cited directly.
      The 2026-09-22 run
      ([`docs/evidence/demo-task-2-live-2026-09-22.txt`](evidence/demo-task-2-live-2026-09-22.txt))
      cited three passages across `pto-and-holidays` (Notice Requirements, Approval Chain) and
      `manager-approval-matrix` (Time Off). Click one through to the notice rule in the policy
      reader. On the published run, the dataset twin `pto-003` **passed** every clause. Workflow
      completion for `pto_request` is **0.67** over three items: `pto-003` and the two
      `unsafe_action` items, which are gate checks rather than completed writes. One of those
      (`unsafe-001`) ran out of steps before reaching the card, which is the missing 0.33. Name the
      `n` and what's in it; don't read it as a rate.
- [ ] **⑤ Final answer and action**: after **Open the request**, the answer **opens with the
      write** in its own block: *"Done — your request is with the HR Time Off team. Reference
      `MOCK-HR-<n>`. Your manager Dana's written approval is the next step."* `agent/approvers.py`
      fills in the manager's name. That block is deterministic: `agent/outcome.py` builds it from
      the tool result, not from the model's text. If a model block names the ticket id, the code
      removes it and uses this one, so a created ticket can't end up under *"What I suggest you
      do"* (that happened live on 2026-09-15, before the guard was rewritten). The same step drops
      any advice that tells the employee to file the request themselves, so nothing on screen
      contradicts the ticket.

### The safety beat (take your time here: it's the best 40 seconds in the demo)

With **Confirm before anything is written** on screen. The card lists the action's fields and says
**"Nothing is written until you choose."**

> *"The ticket doesn't exist yet. The prompt isn't what stops it. The tool server refuses the call
> unless it has a one-time token tied to these exact arguments. That token only gets created in
> `POST /chat/confirm`, after I click. If you replay it, it's refused. If you change one argument,
> it's refused. And the refusal never contains a token, so the model can't get hold of one."*

For that refused attempt, the chat progress line says **"Needs your confirmation"** and the record
row says **"create_mock_hr_ticket · paused for confirmation"** with a `paused` pill. Neither is red.
The span's stored status is `error` and the MCP result is `isError`, because that's what came over
the wire. The gate refusing an untokened write is the safety feature working, so the UI says
*paused* and the payload keeps the truth (`error_code: "CONFIRMATION_REQUIRED"`).

Then:

1. Press **Don't open it**. The card changes to **"You cancelled this — nothing was created."** and
   the answer is the cancelled receipt: *"Cancelled — nothing was created. Ask again whenever you
   would like me to open it."*
2. Ask again to get the card back. Its summary wording may differ from the first card.
3. Press **Open the request**. The card changes to **"You approved this — it went ahead."**, the
   answer leads with `MOCK-HR-<n>`, and the ticket shows under **Simulated writes** on
   **Guardrails** (`/dashboard/safety#MOCK-HR-<n>`, page 8), next to its `confirmed` entry under
   **Confirmations** and the `declined` entry from step 1.

**Then switch to the record** for ①–③, as in task 1. The dashboard link lands on **turn 2** (the
confirmed write). **Scroll up to turn 1** (the declined turn) for the searches.

- [ ] **① Tool names**: read them off the waterfall. Counts vary, so read the tiles. Expect:
      **turn 1** has `check_pto_balance`, `check_policy_compliance`, the `search_policy_documents`
      calls with their retrieval rows, the first `lookup_employee_profile`, then the gated
      `create_mock_hr_ticket` (*paused for confirmation*) and its declined **Confirmation** row.
      **Turn 2** has `check_pto_balance`,
      `check_policy_compliance`, the gated ticket and its **Confirmation** row, then
      `lookup_employee_profile`, and finally `create_mock_hr_ticket` again, this time `ok`. The
      write comes **after** the balance and the deterministic verdict, and the confirmed write is
      the same tool called a second time. `tests/e2e/test_demo_tasks.py` requires
      `search_policy_documents` for demo 2, so the stub path always calls it. If the live turn
      answers without searching, say so.
- [ ] **② Tool-call arguments**: open `check_pto_balance` (`employee_id: "E1042"`) and
      `check_policy_compliance` (`scenario: "pto_request"`,
      `parameters: { start_date: …, end_date: … }`). Then open the **refused**
      `create_mock_hr_ticket` row: the model's proposed `employee_id`, `queue: "hr-timeoff"`,
      `summary` and `details`, with the result `{"status": "confirmation_required", "code":
      "CONFIRMATION_REQUIRED", …}` and no token in it. Then the **confirmed** row: the same
      arguments plus `confirmation_token: "[REDACTED]"`, and a different result.
- [ ] **③ Tool outputs**: the balance result shows **13.5 days remaining** at the `2026-09-01`
      snapshot, `1.50` days/month accrual, the accrual fact key and the blackout dates. Say the
      snapshot out loud: *"The mock data has an explicit `as_of` date. There's no frozen clock
      anywhere in the system."* Then the compliance verdict: notice met against the 5-day rule.
      The business-day count depends on today's date (6 on the 2026-10-03 dry run, 8 in the
      recorded replay), so read it off the payload. Then the confirmed write's result:
      `{"status": "created", "ticket_id": "MOCK-HR-<n>", "queue": "hr-timeoff", …}`, the same row
      you just saw on **Guardrails**.

### Optional beat, if you have 20 seconds spare

The ninth tool, `draft_hr_email`, goes through the **same** gate. One sentence if time allows:
*"Ask it to message your manager instead and you get the same card and the same one-time token."*
The card's buttons read **Open the request** and **Don't open it**. A confirmed draft says
**"Done — the email draft is ready for <name>. Reference `MOCK-EMAIL-…`"**; cancelling gives the
same cancelled receipt. Captured live on 2026-09-22 in
[`docs/evidence/draft-hr-email-live-2026-09-22.txt`](evidence/draft-hr-email-live-2026-09-22.txt)
(`MOCK-EMAIL-000020` confirmed, then a cancel with no write). Cut this beat first if you're short on
time.

---

## If something goes wrong on the take

| Symptom | Do this |
|---|---|
| The first request hangs | It's a cold start. Say so. The page shows *"Just waking up — the first answer may take a little longer."* from a `/health` preflight, built for exactly this. Keep going |
| `/health` reports `degraded` | Read the `degradations[]` array on camera; it names the reason. If it's `llm_api_key_missing`, stop and fix the environment variable before recording |
| A tool call returns `isError` | Keep going. Graceful degradation is graded: the turn still answers at HTTP 200 with a caveat block, and the span row shows the `failed` flag |
| The model takes a different path from this script | That's fine. The tests check the **outcome** (profile, corpus, deterministic verdict, cited documents), not one exact path. Narrate what it did, reading tool names off the waterfall |
| A **write control** returns `{"code": "ADMIN_REQUIRED"}` (Reset sandbox, Re-discover now, Run smoke eval) | Only those three need HR admin. Choose **HR admin** in the demo panel and reload. Nothing in this script needs them, and **reading dashboard pages needs no persona change** |
| Fewer citations than the checklist names | Name what's on screen and click each through. Breadth varies, and the published run shows this prompt's twin `remote-004` failing workflow completion at document recall 0.50. Say that plainly; beat ⑧ comes back to it |
| More citations than an earlier run | Also expected. A multi-document answer that cites fewer documents than its evidence gets one repair attempt. Narrate what's on screen |
| The session record shows no rows for a turn | You're on an imported eval run, not a live session. The run's **Items** table says so. Your live turn is under `/dashboard/sessions` |
| You run past 10:00 | Cut the dashboard tour (6:00–6:25) to 10 seconds and drop the optional email beat. Don't cut either task's dashboard frame; that's where DEMO.6 ①–③ are shown |
