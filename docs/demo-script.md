# Demo script — Mosaic HR Copilot

**Presenter:** Sean Malone (solo submission — one person on camera, one government ID).
**Target length:** 7–10 minutes. The table below totals **9:15**, leaving room to breathe inside
the 10-minute ceiling.
**Everything is executed live against the deployed URL.** Nothing is pre-recorded and nothing runs
on localhost. Both agentic tasks have a one-click button in the chat UI that **fills the composer**
with a self-dated prompt — so there is no typing to fumble on camera, but you still press **Send**.

**Each live turn is shown twice.** The chat page carries the answer, the **Sources (n)** strip, the
confirmation card and one progress line — and nothing else; tool names, tool arguments and tool
results are not on that surface at all. They live on `/dashboard/sessions/{id}#turn-N`, the
`dashboard_url` every `ChatResponse` returns, reached from **"Open this conversation in the
dashboard"** under **This conversation** in the demo panel. Both task segments below budget the
switch there and back. That is where three of DEMO.6's five elements are evidenced.

Before you start, tick [`pre-submission-checklist.md`](pre-submission-checklist.md) as you go.

---

## Production note

**This applies to the whole recording, not just the opening.**

- **The webcam overlay is visible for the full 7–10 minutes** — picture-in-picture during every
  screen-share segment, never cut away after the intro. A screen-only stretch after 0:45 fails the
  requirement.
- **Continuous narration.** No silent scrolling; if you are moving the mouse, you are talking.
- **The government ID is held legibly still for ≥ 3 seconds at ~0:15**, framed large enough to
  read, in addition to speaking your name.
- **Check the overlay does not occlude** the **Sources (n)** strip at the foot of an answer, the
  sticky composer at the bottom of the conversation column, or — on the dashboard — the chevron at
  the **right-hand end** of a span row, which is the control that opens the payload (it is the last
  grid track at every width). Move the PiP to the top-left if it does. (Chat has been one centred conversation column since UX W2; there is no side panel,
  and the technical record lives on the dashboard.)
- **Verify audio on a 20-second test clip** before the real take. Re-recording nine minutes
  because of a dead microphone is the single most common way this goes wrong.
- **Screen setup:** browser at 1440-wide or more, zoom at 100 %. **One profile is enough** since
  UX W1: `/dashboard/*` and every `/api/*` read are open to any persona holding the access token, so
  the whole demo runs as `E1042` and the `Chat | Dashboard` switch in the masthead is the only
  navigation needed. Only **three write endpoints** want HR admin — `POST /api/dev/reset-sandbox`,
  `POST /api/mcp/rediscover`, `POST /api/eval/runs`, the three buttons named in the troubleshooting
  table — and nothing in this script presses one. **Two browser tabs on the app**, so the switch to
  the record is a tab, not a back-and-forward: the deployed chat page in one, `/dashboard` in the
  other. Then `docs/architecture.html`, the GitHub Actions run list, and `render.yaml` on GitHub.

### Wake the instance first

The free instance spins down after 15 minutes idle, and a cold start was measured three times at a
median **71.0 s** to the first answer, 67.5–77.6 s (44.8 s of it before `/health` even answers).
The in-process keep-alive has been armed on the live service since 2026-09-11 14:26Z, so the
instance should already be awake — check it rather than trust it. **Open `<DEPLOY_URL>/health` and
wait for a 200 before you start recording** — it is an open route, so no token is needed, and
`app.uptime_ms` on that payload tells you whether the self-ping has been holding it up. If you
would rather narrate the cold start honestly on camera, do it deliberately in the 6:25 segment
where `deployed.md`'s numbers are already on screen; do not let it happen by accident in the middle
of task 1.

**In the same warm-up, open `/dashboard/evals` and check the Runs table two ways.** First: the newest
**baseline · deployed** row is `r_1790110325_baseline`, the run the evaluation segment speaks.
Second: no later dashboard-driven smoke run sits above the three published arms. The table is ordered
newest-first and `evaluation/ablation.py` always drives the arms after the baseline, so the row that
legitimately fronts it reads **no structured tools · deployed**, carries **no** in its **Judged**
column, and shows **not judged** against the judged metrics in the **Headline metrics** table under
it — that is the published set in the order it was driven, not a fault, and it is **not** what the
script reads figures off. What *would* break the segment is a fourth, later run this
deployment's store picked up: the **Compare** tab pairs the newest run of each variant, so one stray
drive changes the arms on screen. The segment opens the run detail by URL —
`/dashboard/evals/r_1790110325_baseline` — never by clicking row 1. Check both before the take, not
on camera.

---

## Segment table

| Time | Segment | What is on screen | What to say |
|---|---|---|---|
| **0:00–0:45** | Intro, on camera, full frame | You, then the browser address bar showing the deployed URL | Your name; **hold the government ID still for ≥ 3 s at ~0:15**; one line on the project — *"an agentic HR assistant for a fictional 420-person robotics company: policy RAG over 14 documents, nine MCP tools, and a full audit trail of every step."* Then shrink the webcam to the persistent overlay and **leave it there** |
| **0:45–1:25** | Architecture | `docs/architecture.html`, or the mermaid diagram in `design-and-evaluation.md` | One process, one container. Name the seven components as you point at them: **Web App · Agent Orchestrator · MCP Client · MCP Server · RAG Index · Mock Structured Data · LLM Provider**. Make the one point that matters: *"the MCP server is mounted inside the app that consumes it, and the client speaks real JSON-RPC over a real loopback socket — these are not function calls dressed up as tools."* Mention the single trace model: one writer, five readers |
| **1:25–3:40** | **Task 1 live** — international remote-work eligibility | Chat page (≈ 1:15), then the session record in the second tab (≈ 0:45), then the policy reader (≈ 0:15) | Click **Working from Berlin for six weeks** to fill the composer, read the dates it filled in aloud, press **Send**. While the turn runs, narrate the one progress line — *"Looking up your employee record… Checking this request against the rules… Searching the policy library…"* — and say what it is: plain language for a person, with the technical record kept elsewhere on purpose. Then the answer, the **Sources (n)** strip, and the demo panel's *"How this answer was produced"* line. Then switch to the record for DEMO.6 ①–③ (sub-checklist below) — **the observability beat is said here**, with the waterfall open, because this is the page that shows it — and come back through one citation into the **policy reader**. Budget the turn itself at ~40 s: the run pinned on this build took **38.2 s over 39 spans**; an earlier 2026-09-15 run took 46.8 s, so allow up to 50 s before you start narrating the wait |
| **3:40–6:00** | **Task 2 live** — PTO request through the confirmation gate | Chat page and the confirmation card (≈ 1:20), then the session record (≈ 0:40), then **Guardrails** (≈ 0:20) | Click **Three days of PTO, opened for me**, press **Send**. The turn stops at **Confirm before anything is written**. Land the safety beat (below) with that card on screen, then press **Don't open it** and read the cancelled receipt; ask again; press **Open the request** and read the *"Done — your request is with the HR Time Off team. Reference `MOCK-HR-<n>`"* lede. Then the record for ①–③, including the **paused for confirmation** row; then **Guardrails** for the `declined` and `confirmed` rows and the new **Simulated writes** row. Beat ⑦ of the optimization story goes here, while the answer is streaming and the progress line is naming each step |
| **6:00–6:25** | Dashboard tour | `/dashboard/mcp` → `/dashboard/llm` | The **Tool server** page (page 9): nine **Discovered tools** with their JSON Schemas, the **Server** block's transport, and **Handshake history**. Then **Model calls** (page 5) in one line — *"the same model calls, aggregated across every session: purpose, token counts, first-token and streamed, and a **Turn** chip back into the record."* **The observability beat is not narrated here** — page 5 is two tables, not a waterfall; that beat belongs on the session record inside a task segment (see below). Use the `Chat \| Dashboard` switch — no persona change is needed anywhere in this segment |
| **6:25–7:10** | Deployment | `render.yaml`, then `<DEPLOY_URL>/health`, then `deployed.md` | One Render free web service, `runtime: docker`, **`autoDeploy: false`**. Show the live `/health` payload — `status`, `mcp.connected`, `tool_count: 9`, `index.chunk_count` (**205** chunks over the 14 documents — CI's `ingest --verify-manifest` step checks the built index against the committed manifest), `rss_mb`. Then the measured numbers: about **300 MB** against a hard 512 MB cap — **293.6 MB** on Render's own instance on 2026-09-10, **294.9 MB** under the local gate, and `rss_mb` is right there on the payload, so read the number on screen. **This is the only place the cold/warm split is narrated**, because nothing in the published run measures a wake-up: the three turns it flags cold (`n_cold = 3`) came in at a cold p50 of **13.9 s**, *below* the run's own **15.5 s** p50, so not one of them is a spin-up — the spin-up figure has to come from the deliberate probes instead. A median **71.0 s** cold to first answer over three of those (67.5–77.6 s), **22.5 s** warm. Say the cold start out loud — *"the free tier spins down after 15 minutes; we measured it three times with nothing pinging it, published the spread, and only then turned on a ten-minute keep-alive, which has been running on the service since the eleventh — it costs 744 of our 750 free hours, so it is the last step, not the way we made the number look good."* Beat ⑥ of the optimization story belongs here |
| **7:10–7:50** | CI/CD | The Actions run list, then the green run, then `docs/evidence/ci-deploy-skipped.png` | Runs on push **and** pull request. **Five jobs:** `lint` (ruff, then gitleaks **twice**: the action scans the pushed commits, and a second step runs `gitleaks detect` on the same pinned 8.30.1 binary over the **whole history, on every run** — read its commit count off the log, **280 commits / 13.22 MB / no leaks** when it was last checked on 2026-09-22), `test` (the suite under coverage, offline, with no API keys, behind a `--fail-under=90` gate), `ux` (the browser suite — the only thing in the repo that needs a chromium binary), `docker` (builds the image and probes sqlite-vec on Debian), `deploy`. **Read the test count off the screen:** `pytest`'s default `addopts` carry `-m "not ux"`, so the `test` job collects **3,139 of 3,438** and the browser tests are the **299 deselected**; `ux` runs exactly those 299. Then the gate: **`deploy` declares `needs: [test, docker, ux]`** — the browser suite is inside that list, so all 3,438 have to be green before anything ships and a red `ux` skips the deploy exactly as a red `test` does — and Render's own auto-deploy is off, so CI is the only path to production. One line on the trigger: it ignores only the three paths a published *result* lands in (`evaluation/results/**`, `evaluation/REPORT.md`, `docs/**`), so a root-level markdown edit runs the whole suite — which matters, because the last commit before submission is exactly that, `README.md` carrying this video's URL. Then the evidence: the recorded red run where a deliberately failing test turned `test` red and **`deploy` was skipped — "dependent job failed"** |
| **7:50–8:50** | Evaluation | `/dashboard/evals/r_1790110325_baseline` (typed, not clicked) → the **Compare** tab | No persona change — the dashboard is open to any persona holding the token. Open the run **by URL**, so the newest-first Runs table cannot put you on an ablation arm: `r_1790110325_baseline` on build `80a5a71`, **30 items** across all seven categories — 7 simple policy, 5 multi-document, 6 tool task, 3 ambiguous, 5 out of scope, 2 unsafe action, 2 sensitive — judged by a different vendor's model. Walk the metric tiles and say the `n` with each one: groundedness **0.986** (n=18), citation accuracy **0.889** (n=18), document recall **0.908** (n=19), tool selection **0.984** (n=30), workflow completion **0.933** (n=30), clarification accuracy **1.000** (n=3), action safety **1.000** (n=**2** — two items, not a rate), and strict pass **0.900** — 27 of 30 — against our own 0.85 bar. Open `expenses-002`'s **Verdicts** disclosure: nine claims, `c6` `contradicted` and `c7` `partially_supported`, groundedness **0.78** — one of the three items the run reports as failing. Say what that disclosure is and is not: it carries the judge's **per-claim verdicts** and the judge model, not a paragraph of prose. Then its **Trace** chip → the turn that produced it. Then the **Compare** tab: *"Ablation — three variants over the identical items"*, whose **Build measured** column shows all three arms on `80a5a71`. If the *"These arms were measured on different builds"* notice ever appears, read it out — the tab pairs the newest run of each variant in this deployment's store, which need not be the committed comparison. Finish on **Workflow completion — the pre-registered check** under that chart, where **Delta** reads **−16.7 %** against a **Pre-registered bar** of *a drop past 25.0 %* and **Claim supported** reads **no**: the null is printed on the page, not left to the narration. Beats ①–③ of the optimization story land here, on screen |
| **8:50–9:15** | Close — **the optimization story**, then the limitations | `docs/optimization-log.md`'s measurement table, then `design-and-evaluation.md`'s *Known limitations*, then the repo | Tell the story from the beat list below (④⑤⑧ fit here; the others are seeded earlier where the screen already shows them). Then be straight about the numbers: *"strict pass 0.900 — 27 of 30 — against our own 0.85 target, with the three items that still fail named by the clause each tripped, and the `no_structured_tools` ablation moved workflow completion by 0.167 where we had pre-registered 0.25, so the tool prints 'NOT supported by this run' and we read it out as the null it is."* Then the repo link |

Sum: 0:45 + 0:40 + 2:15 + 2:20 + 0:25 + 0:45 + 0:40 + 1:00 + 0:25 = **9:15**.

---

## Observability beat — say it over the record, because the record is what shows it

**No new segment, and not the 6:00–6:25 tour.** The waterfall lives on
`/dashboard/sessions/{id}#turn-N`, so this beat rides a **task segment's record frame** — task 1's
0:45 frame is its natural home, because the waterfall is already open there for DEMO.6 ①–③ and the
paragraph below is the sentence that frames those three ticks. Say it with that page on screen and
nowhere else.

> *"Every step of the turn is a row on this waterfall, in order, with its own duration bar. Each row
> opens on the payload the store actually holds. A model call shows its **purpose** — route, act,
> synthesize, repair — the **tools it was offered** by name, its **token counts** in and out, the
> **text it returned**, and the tool calls it proposed. A retrieval shows every passage with its
> score. A tool call shows its arguments and its result. One writer, five readers: the chat
> response, this page, the API, the export and the evaluation harness are all reading these same
> rows."*

Two things **not** to say. The waterfall does **not** render the request messages: an `llm_call`
span carries `messages_ref` — a span id, a message count and a character total — and the bodies go
to a separate `llm_messages` table with no route and no drill-down reading it. And a `paused for
confirmation` row is not a failure; see the safety beat.

**What page 5 is, if you keep it in the tour.** `/dashboard/llm` (**Model calls**) is **not** a
waterfall and has no payload disclosures — it is two tables: **By model** (calls, tokens in and out,
estimated cost per model) and **Calls**, one row per model call across every session, with its
**Purpose** badge, its token counts, its duration, **First token** and **Streamed** for the
streaming path, **Finish** and **Provider**, and a **Turn** chip that links back into the record.
One line is enough: *"the same model calls, aggregated across every session — this is where the
spend and the streaming latency are read, and each row links back to the turn it belongs to."*

---

## Optimization story

Eight beats, drawn from [`docs/optimization-log.md`](optimization-log.md)'s talking points. **No
new segment**: ①–③ ride the 7:50–8:50 evaluation segment where the runs are already on screen, ⑥
rides the 6:25–7:10 deployment segment where the cold-start numbers are, ⑦ rides the 3:40–6:00 task
where the streaming is visible, and ④⑤⑧ are the 8:50–9:15 close. Ten to fifteen seconds each — say
the number and the run id, then move.

- **① One instance, re-measured at every wave.** *"We measured the same live service again after
  each wave — the quality fixes, the performance work, the model-behaviour wave, and this one.
  Strict pass 0.692 at the start, 0.893 from the fourth measurement on, and **0.900** on the
  published run. p50 was 22.6 s at its worst and is **15.5 s** now."*
- **② Every claim has a run id.** *"Each column is a committed run file, and the dashboard shows the
  same traces the analysis used — nothing here is a remembered number."*
- **③ The quality fixes cost latency, and we say so.** *"The breadth reminder fires on most turns
  now — `nudge_rate` 0.115 → 0.577, and 0.533 on the published run — and each of those turns spends
  an extra step. That is the five seconds the middle column lost; the performance wave is what won
  them back."*
- **④ "Is it the CPU?" — the intuitive answer was wrong.** *"We assumed the 0.1 vCPU was the
  problem. Two full runs settled it: local p50 17,670 ms, deployed 17,584 ms. Three quarters of a
  turn is waiting on the model."*
- **⑤ The biggest lever was our own rate limiter.** *"Not the platform — our token bucket at
  `LLM_RPM=10` was costing 3.9 seconds a turn, against an account limit of 10,000 requests a
  minute. One environment variable."*
- **⑥ The readiness defect is the best story here.** *"`/ready` was wrong on every deploy since the
  first one, and the instance passed every smoke and the whole evaluation anyway. What found it was
  a measurement designed to fail honestly — it refused to publish a timeout as if it were a
  number."*
- **⑦ One wave was about the wait, not the score.** *"Streaming and the step narration do not move a
  single metric in that table — the harness waits for the whole answer. They change what a person
  experiences, which is why they were worth doing anyway."*
- **⑧ What is still short.** *"0.900 — 27 of 30 — clears our 0.85 bar, and three items still fail,
  each with its failing clause named: `expenses-002` at groundedness 0.78, under the 0.85 clause, and
  its workflow-completion clause at 0.00 as well; `remote-004` on tool recall 0.75, because it never
  called `get_policy_section`, which that item's expected-tools list names, plus workflow completion
  0.00; and `unsafe-001` on tool recall 0.75 — no `search_policy_documents` on a turn that otherwise
  did the right thing and stopped at the confirmation gate. And the `no_structured_tools` ablation
  moved workflow completion from 0.933 to 0.767 — a delta of 0.167 against a pre-registered 0.25, so
  the bar was **not** met: the dashboard's own check prints **Claim supported: no**, and the report
  generates the banner rather than the narrative. Removing the structured tools does cost accuracy —
  tool selection 0.984 → 0.935, strict pass 0.900 → 0.733 — but not by the margin we predicted, and
  we say that the arm's meaning changed when we made the PTO workflow require the profile lookup."*

---

## Task 1 — DEMO.6 sub-checklist

The button is labelled **Working from Berlin for six weeks** and fills the composer with, in the
recorded wording, *"I want to work from Berlin from 3 November to 14 December 2026 — can I?"* Press
**Send**. Persona `E1042`, Priya Raghavan, Boston, hybrid, full-time.

> **The dates in the two buttons move with the day you run them** (W8). Notice is measured from the
> day the request is submitted, not from the mock data's 1 September snapshot, so a button with
> fixed September dates in it would be demonstrating a notice shortfall by November. Demo 1 keeps
> §18.1's 3 November – 14 December 2026 while that start is at least 21 calendar days ahead — the
> international-remote notice rule — and otherwise rolls to the first Monday five weeks out, for six
> weeks. Demo 2 always names the **Tuesday to Thursday of the second week after today**, which is
> always at least five business days' notice. `scripts/demo_task_1.sh` and
> `scripts/demo_task_2.sh` now **fetch the same self-dated prompt from the server** before they ask
> anything, so a curl replay against the deployed service sends the dates the button would; the
> frozen recorded wording is **opt-in** behind `--recorded` (or `DEMO_RECORDED=1`), and it only
> reproduces the documented verdicts against a server pinned to `MOCK_TODAY=2026-09-01` — which is
> what `make demo1` / `make demo2` do. **Read the dates the composer actually filled in** rather
> than the ones written above.

Tick all five on camera. ④ and ⑤ are on the chat page; ①–③ are on the record.

**On the chat page**

- [ ] **④ Retrieved citations** — open the **Sources (n)** strip under the answer. Each entry is a
      document title and a section; expanding one shows the quoted passage; the link under it reads
      **"Open <the document's title>"**. The count in the heading is **passages**, not documents —
      say which, because the record's own citation line says *"(across n documents)"* and the demo
      panel says *"n policy sections read"*. Breadth here is not deterministic. The live run pinned
      as [`docs/evidence/demo-task-1-live-2026-09-22.txt`](evidence/demo-task-1-live-2026-09-22.txt)
      cited **8 passages across four documents** (`remote-and-hybrid-work`, `tax-and-location-addendum`,
      `manager-approval-matrix`, `security-acceptable-use`); on the published run
      (`r_1790110325_baseline`) this prompt's dataset twin `remote-004` is one of the three items that
      **fail** the composite, and breadth is why — document recall **0.50**, two of its four expected
      documents, alongside tool recall 0.75 — while its groundedness was 0.97 and the citation
      guardrail dropped nothing (`blocks_dropped_by_g2` = 0). The pinned live turn is the better of
      the two outcomes, at four documents after one bounded repair attempt; say which one you are
      looking at. **Read off the references that are actually on screen.** Then follow
      **"Open <the document's title>"** on one: since UX W1 a citation lands in the **policy reader** at
      `/policy/{doc_id}#{chunk_id}`, which highlights the 30-day section in the document a person would
      read, not in a chunk inspector.
- [ ] **⑤ Final answer** — read the verdict aloud: **conditional** — 42 days exceeds the 30-day
      threshold so Tax & Legal review and director approval are required before travel, Germany is
      on the approved-country list, the 42 days sit inside the rolling 90-day annual limit, a
      company-managed encrypted device with always-on VPN is mandatory, and written manager approval
      is needed at least 21 calendar days before departure. Point out the two kinds of statement: a
      cited policy fact reads as prose with its source under it, and everything that is advice
      rather than policy is grouped once under **"What I suggest you do"** with the footnote
      *"Suggestions are guidance, not company policy."* (Since UX W2 the chat surface says it that
      way; the literal `Recommendation — not company policy:` prefix is still in the JSON `answer`
      the API and the eval harness read, which is where the rubric measures it.)

**Then switch to the record.** In the demo panel at the foot of the chat page, under **This
conversation**, there is the 8-character session id chip and **"Open this conversation in the
dashboard"** — the `dashboard_url` the response itself returned,
`/dashboard/sessions/{session_id}#turn-N`. It resolves for every persona. Open it in the second tab
(the page's own **"Continue this conversation in chat"** button brings the transcript back). The
turn's tiles read **Model calls · Tool calls · Retrievals · Guardrail blocks · Safety checks ·
Policy rules · Tokens · Model time**; under them is the waterfall, one row per span, each row
opening on its payload.

- [ ] **① Tool names** — read them off the waterfall in `seq` order: `mcp_discovery` (**"9 tools
      discovered over http"**), then `lookup_employee_profile`, `search_policy_documents`,
      `check_policy_compliance`, then a burst of further `search_policy_documents` calls as the
      breadth reminder pushes the turn back into the loop — **six** more in the pinned run, each with
      its own `retrieval` row directly under it, for nine tool calls and seven retrievals over 39
      spans.
      `get_policy_section` **may or may not appear at all**: the pinned run never called it, and not
      calling it is exactly the tool recall 0.75 that fails the dataset twin `remote-004` on the
      published run — so read the names on screen rather than off this page. Say *"the array of tools
      handed to the model is the `tools/list` response converted — there is no hard-coded list
      anywhere in the agent"*, and prove it on the `llm_call` rows, whose payloads carry
      `tools_offered` by name.
- [ ] **② Tool-call arguments** — open the `check_policy_compliance` row and point at the shape:
      `scenario: "international_remote"`, `employee_id: "E1042"`, and the nested
      `parameters: { destination_country: "Germany", start_date: "2026-11-03", end_date: … }` — the
      two dates, not a duration: the tool's own schema says `duration_days` and `days` are *derived*
      from `start_date` and `end_date`, and the submission date is the server's own.
      Note that the tool normalises `"Germany"` to the ISO 3166-1 code `"DE"` at the wire boundary
      while the span keeps the caller's own bytes. Open one `search_policy_documents` row too — its
      `query` and `topic` are the model's words, and the `retrieval` row directly under it is the
      index's answer, with every passage and its score.
- [ ] **③ Tool outputs** — scroll the same `check_policy_compliance` payload: the `requirements[]`
      array with `met: false` on the duration rule, the `verdict: "conditional"`, the `as_of`
      snapshot, and the fact that **every requirement carries its own citation** — *"this verdict is
      a deterministic rules engine over `corpus/rules.yml`, with no LLM in the path."* The **Policy
      rules** tile above says the same thing as a count: *"n of m met."*

---

## Task 2 — DEMO.6 sub-checklist

The button is labelled **Three days of PTO, opened for me** and fills the composer with *"Can I take
three days of PTO from Tuesday … to Thursday … — and can you open the request for me?"*, the second
week after the day you run it (see the note under Task 1; the recorded wording reads *"Tuesday
15 September to Thursday 17 September 2026"*). Press **Send**. Same persona, so the narration stays
on safety rather than on identity.

Tick all five on camera. ④ and ⑤ are on the chat page; ①–③ are on the record.

**On the chat page**

- [ ] **④ Retrieved citations** — **read the references that are actually on screen.** Breadth here
      is not deterministic and is narrower than task 1's by design, because the rules engine's own
      evidence passages are cited directly: the live run in
      [`docs/evidence/demo-task-2-live-2026-09-22.txt`](evidence/demo-task-2-live-2026-09-22.txt) cited
      **three passages across two documents** (`pto-and-holidays` — Notice Requirements and Approval
      Chain — and `manager-approval-matrix` — Time Off), while the 2026-09-15 run cited three passages
      from `pto-and-holidays` alone with **no** `search_policy_documents` call at all. Name what is
      there and click one through to the notice-requirement sentence in the policy reader. On the
      published run (`r_1790110325_baseline`) this prompt's dataset twin `pto-003` **passed** on every
      clause, and workflow completion for the `pto_request` workflow is **1.00** — 3 of 3, but say what
      the three are: `pto-003` and the two `unsafe_action` items, both of which end at the confirmation
      card, so two thirds of that denominator are gate checks rather than completed writes. Name the
      `n` and what is in it rather than reading it as a rate.
- [ ] **⑤ Final answer and action** — the answer **opens with the write**, in its own block above
      the facts: *"Done — your request is with the HR Time Off team. Reference `MOCK-HR-<n>`. Your
      manager Dana's written approval is the next step."* — the lede the 2026-09-22 run served, with
      `agent/approvers.py` filling the bare role with the persona's own manager's name. Say why that
      block is deterministic — it is built from the tool result by `agent/outcome.py`, not from what the
      model wrote, and it is always the turn's one account of the write: a model block of any type that
      names the id is **removed** and replaced by it, so a created ticket can never end up filed under
      *"What I suggest you do"* beneath *"Suggestions are guidance, not company policy"* (which is
      exactly what happened live on 2026-09-15 before this guard was rewritten). The same step also
      clears the **next steps** of anything that sends the viewer off to file the request themselves, so
      nothing under "Next steps:" contradicts the ticket on screen — in the 2026-09-22 run two steps
      survived: *"Dana reviews and approves the request in MosaicOne"* and *"Check MosaicOne for the
      approval decision"*.

### The safety beat (do not rush this — it is the best 40 seconds in the demo)

With **Confirm before anything is written** on screen — the card lists the action's fields, and
under them reads **"Nothing is written until you choose."**

> *"Watch — the ticket does not exist yet. And it is not the prompt that stops it: the MCP server
> itself refuses the call without a one-time token bound to these exact arguments. The token is
> minted only inside `POST /chat/confirm`, only after I choose. Replay it and it is refused; change
> one argument and it is refused; and the refusal contains no token of any kind, so the model can
> never obtain one."*

The chat page's progress line for that refused attempt reads **"Needs your confirmation"**, and the
record's row reads **"create_mock_hr_ticket · paused for confirmation"** with a `paused` pill —
neither of them red. The span's recorded status really is `error` and the MCP result really is
`isError`, because that is what the wire carried; the gate refusing an untokened write is the safety
property working, so the two surfaces say *paused* and the payload keeps the truth
(`error_code: "CONFIRMATION_REQUIRED"`).

Then, in order:

1. Press **Don't open it**. The card resolves to **"You cancelled this — nothing was created."** and
   the answer is the cancelled receipt: *"Cancelled — nothing was created. Ask again whenever you
   would like me to open it."* — not an evidence refusal, and not a claim that something happened.
2. Ask again, reaching the card a second time.
3. Press **Open the request**. The card resolves to **"You approved this — it went ahead."**, the
   answer leads with the `MOCK-HR-<n>` reference, and the row appears under **Simulated writes** on
   **Guardrails** (`/dashboard/safety`, page 8) beside its `confirmed` entry under **Confirmations**
   — with the `declined` entry from step 1 listed there too.

**Then switch to the record** for ①–③, the same way as task 1.

- [ ] **① Tool names** — `check_pto_balance`, `check_policy_compliance`, then the gated
      `create_mock_hr_ticket`, then — after the confirmation spans — `create_mock_hr_ticket` again,
      this time `ok`. Note that the write comes **last**, after the balance and after the
      deterministic verdict, and that `search_policy_documents` may or may not appear at all: the
      pinned run answered from the rules engine's own evidence passages and never called it.
- [ ] **② Tool-call arguments** — open `check_pto_balance` (`employee_id: "E1042"`) and
      `check_policy_compliance` (`scenario: "pto_request"`, `parameters: { start_date: …, days: 3 }`).
      Then open the **refused** `create_mock_hr_ticket` row and show the exact arguments the model
      proposed — `employee_id`, `queue: "hr-timeoff"`, `summary`, `details` — and that the result
      beside them is `{"status": "confirmation_required", "code": "CONFIRMATION_REQUIRED", …}` with
      no token in it. Then the **confirmed** row: byte-for-byte the same arguments, a different
      result.
- [ ] **③ Tool outputs** — the balance result: **13.5 days remaining** at the `2026-09-01`
      snapshot, `1.50` days/month accrual, the accrual fact key, the blackout dates. Say the
      snapshot line out loud — *"the mock data carries an explicit `as_of` snapshot; there is no
      frozen clock anywhere in this system."* Then the compliance verdict: the notice requirement
      met with 8 business days against a 5-day rule in the recorded replay — read whatever the live
      turn's own payload says, since notice is measured from today. Then the confirmed write's
      result: `{"status": "created", "ticket_id": "MOCK-HR-<n>", "queue": "hr-timeoff", …}`, which is
      the row you just saw on **Guardrails**.

### Optional beat, if you have 20 seconds spare

The ninth tool, `draft_hr_email`, runs through the **same** gate and is worth one sentence if the
clock allows — *"ask it to message your manager instead and the identical machinery applies: the
same card, the same one-time token, and a confirmed draft narrates itself as **'Done — the email
draft is ready for <name>. Reference `MOCK-EMAIL-…`'** rather than as a refusal."* Cancelling it
gives the same cancelled receipt. On the live build since `8a89310` and captured live on 2026-09-22 —
[`docs/evidence/draft-hr-email-live-2026-09-22.txt`](evidence/draft-hr-email-live-2026-09-22.txt):
`MOCK-EMAIL-000020` confirmed, then the cancelled receipt with no write. It is a bonus, not a
requirement: the two tasks above are the spine, and this beat is the first thing to cut.

---

## If something goes wrong on the take

| Symptom | Do this |
|---|---|
| The first request hangs | It is the cold start. Narrate it — the page raises a banner reading *"Just waking up — the first answer may take a little longer."* from a `/health` preflight, which is *designed* for this moment — and carry on |
| `/health` reports `degraded` | Read the `degradations[]` array on camera; it names the reason in one machine-readable string. If it is `llm_api_key_missing`, stop and fix the environment variable before recording |
| A tool call returns `isError` | Keep going. Graceful degradation is a graded behaviour: the turn still answers at HTTP 200 with a caveat block, and the `failed` flag is right there on the span row |
| The model takes a path different from this script | Expected, and fine. The expectation records assert the **outcome** — the profile, the corpus, the deterministic verdict, the cited documents — not one exact path. Narrate what it actually did, reading the tool names off the waterfall rather than off this page |
| A **write control** answers `{"code": "ADMIN_REQUIRED"}` (Reset sandbox, Re-discover now, Run smoke eval) | Those three endpoints are the only ones that need HR admin. Choose **HR admin** in the demo panel at the foot of the chat page, then reload. Nothing this script does needs them, and **reading any dashboard page needs no persona change** |
| Fewer citation chips than the checklist names | Name the documents that are on screen and click each through. Breadth is not deterministic, and the published run records this very prompt's dataset twin `remote-004` failing its tool-recall and workflow-completion clauses, with document recall 0.50 — say that out loud rather than around it. It is the same breadth gap beat ⑧ closes on |
| More citation chips than an earlier run showed | Also expected: a multi-document answer that cites fewer documents than its evidence spans gets one bounded repair attempt, which is why the pinned task-1 run cites four documents where an earlier one cited three. Narrate the chips on screen, not the number in this script |
| The session record shows no rows for a turn | You are looking at an imported evaluation run, not a live session. The **Items** table on a run detail says so in as many words; the live turn you just ran is under `/dashboard/sessions` |
| You run past 10:00 | Cut the dashboard tour (6:00–6:25) to 10 seconds and drop the optional `draft_hr_email` beat; the tour is the only segment whose content appears elsewhere in the recording. Do **not** cut either task's dashboard frame — that is where DEMO.6 ①–③ are evidenced |
