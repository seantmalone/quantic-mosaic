# Demo script — Mosaic HR Copilot

**Presenter:** Sean Malone (solo submission — one person on camera, one government ID).
**Target length:** 7–10 minutes. The table below totals **9:15**, leaving room to breathe inside
the 10-minute ceiling.
**Everything is executed live against the deployed URL.** Nothing is pre-recorded, nothing runs on
localhost, and both agentic tasks are one-click buttons in the chat UI so there is no typing to
fumble on camera.

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
- **Check the overlay does not occlude** the citation chips (bottom of each answer block) or the
  live span rail (right-hand column). Move the PiP to the top-left if it does.
- **Verify audio on a 20-second test clip** before the real take. Re-recording nine minutes
  because of a dead microphone is the single most common way this goes wrong.
- **Screen setup:** browser at 1440-wide or more, zoom at 100 %. **Two browser profiles** (or one
  normal window and one private window), because `mosaic_actor` is a *single cookie shared by the
  chat and the dashboard*: **profile A pinned to persona `E1042`** — the deployed app, used for
  both tasks — and **profile B with the act-as selector set to HR admin** — `/dashboard` and
  `/dashboard/evals`. Everything under `/dashboard/*` and `/api/*` answers
  `403 {"code":"ADMIN_REQUIRED"}` for the employee persona, so a dashboard tab left on `E1042` will
  show that JSON on camera instead of a page. Tabs, in this order: the deployed app (profile A),
  `/dashboard` (profile B), `docs/architecture.html`, the GitHub Actions run list, `render.yaml` on
  GitHub.

### Wake the instance first

The free instance spins down after 15 minutes idle, and a cold start was measured three times at a
median **71.0 s** to the first answer, 67.5–77.6 s (44.8 s of it before `/health` even answers).
**Open `<DEPLOY_URL>/health` and
wait for a 200 before you start recording** — it is an open route, so no token is needed. If you
would rather narrate the cold start honestly on camera, do it deliberately in the 6:15 segment
where `deployed.md`'s numbers are already on screen; do not let it happen by accident in the middle
of task 1.

---

## Segment table

| Time | Segment | What is on screen | What to say |
|---|---|---|---|
| **0:00–0:45** | Intro, on camera, full frame | You, then the browser address bar showing the deployed URL | Your name; **hold the government ID still for ≥ 3 s at ~0:15**; one line on the project — *"an agentic HR assistant for a fictional 420-person robotics company: policy RAG over 14 documents, nine MCP tools, and a full audit trail of every step."* Then shrink the webcam to the persistent overlay and **leave it there** |
| **0:45–1:30** | Architecture | `docs/architecture.html`, or the mermaid diagram in `design-and-evaluation.md` | One process, one container. Name the seven components as you point at them: **Web App · Agent Orchestrator · MCP Client · MCP Server · RAG Index · Mock Structured Data · LLM Provider**. Make the one point that matters: *"the MCP server is mounted inside the app that consumes it, and the client speaks real JSON-RPC over a real loopback socket — these are not function calls dressed up as tools."* Mention the single trace model: one writer, five readers |
| **1:30–3:30** | **Task 1 live** — international remote-work eligibility | The chat UI, then the span rail, then the corpus browser | Click the **Demo 1** button. Narrate the five DEMO.6 elements from the live span rail as they appear (sub-checklist below). Finish by clicking a citation chip through to the highlighted 30-day sentence in the corpus browser |
| **3:30–5:30** | **Task 2 live** — PTO request through the confirmation gate | The chat UI, the Confirm card, then dashboard page 8 (**admin profile**) | Click **Demo 2**. Narrate the five elements again, then land the safety beat (below). **Cancel once** to show `declined` recorded, re-ask, then confirm, and watch the new row appear in the mock-action log. Beat ⑦ of the optimization story goes here, while the answer is streaming in and the rail is narrating each step as it starts |
| **5:30–6:15** | Dashboard tour | `/dashboard/sessions/{id}` → `/dashboard/mcp` → `/dashboard/safety` | **Switch to the admin profile first** (or set the act-as selector to **HR admin**) — every route here is admin-only. The span waterfall for the turn just run — *"every LLM call with its verbatim messages, every retrieval with its scored chunks, every tool call with its arguments and result."* Then the MCP page: nine tools, their JSON Schemas, the transport and the handshake. Then the safety page: guardrail verdicts by rule, the confirmation ledger, the mock-action log |
| **6:15–7:00** | Deployment | `render.yaml`, then `<DEPLOY_URL>/health`, then `deployed.md` | One Render free web service, `runtime: docker`, **`autoDeploy: false`**. Show the live `/health` payload — `status`, `mcp.connected`, `tool_count: 9`, `index.chunk_count`, `rss_mb`. Then the measured numbers: about **300 MB** against a hard 512 MB cap — 293.6 MB when we measured it on 2026-09-10, 294.9 MB under the local gate, and `rss_mb` is right there on the payload, so read the number on screen, and the cold-start segments with their dates and their `n`: a median **71.0 s** cold to first answer over three probes (67.5–77.6 s), **22.5 s** warm. Say the cold start out loud — *"the free tier spins down after 15 minutes; we measured it three times with nothing pinging it, published the spread, and only then decided to add a ten-minute keep-alive — which costs 744 of our 750 free hours, so it is the last step, not the way we made the number look good."* Beat ⑥ of the optimization story belongs here |
| **7:00–7:40** | CI/CD | The Actions run list, then the green run, then `docs/evidence/ci-deploy-skipped.png` | Runs on push **and** pull request. Four jobs: `lint` (ruff + gitleaks over full history), `test` (the full suite — over 1,800 tests; read the count off the run on screen — offline, with no API keys), `docker` (builds the image and probes sqlite-vec on Debian), `deploy`. Then the gate: **`deploy` declares `needs: [test, docker]`**, and Render's own auto-deploy is off, so CI is the only path to production. Then the evidence: the recorded red run where a deliberately failing test turned `test` red and **`deploy` was skipped — "dependent job failed"** |
| **7:40–8:45** | Evaluation | `/dashboard/evals` → a run detail → the compare tab | **Admin profile again.** 28 items across all seven categories. Walk the metric chips: groundedness, citation accuracy, DocRecall, tool selection, workflow completion, action safety, over-refusal, latency split cold/warm. Open one item to show the **judge rationale**, then "view trace" to jump to the turn that produced it. Then the compare tab: the three-variant ablation chart. Beats ①–③ of the optimization story land here, on screen |
| **8:45–9:15** | Close — **the optimization story**, then the limitations | `docs/optimization-log.md`'s four-column table, then `design-and-evaluation.md`'s *Known limitations*, then the repo | Tell the story from the beat list below (four beats fit here; the other four are seeded earlier where the screen already shows them). Then be straight about the numbers: *"strict pass is 0.893 against our own 0.85 target — met at the fourth measurement, with the three items that still fail named by the clause each tripped — and the `no_structured_tools` ablation moved workflow completion by 0.143 rather than the 0.25 we predicted, so we report it as a measurement, not as proof."* Then the repo link |

---

## Optimization story

Eight beats, drawn from [`docs/optimization-log.md`](optimization-log.md)'s talking points. **No
new segment**: ①–③ ride the 7:40–8:45 evaluation segment where the runs are already on screen, ⑥
rides the 6:15–7:00 deployment segment where the cold-start numbers are, ⑦ rides the 3:30–5:30 task
where the streaming is visible, and ④⑤⑧ are the 8:45–9:15 close. Ten to fifteen seconds each — say
the number and the run id, then move.

- **① Four columns, one instance.** *"We measured the same live service four times: before, after
  the quality fixes, after the performance work, and after the model-behaviour wave. Strict pass
  0.692 → 0.808 → 0.808 → 0.893; p50 17.6 s → 22.6 s → 16.7 s → 19.1 s. The first three columns are
  the same 26 items; the last adds two out-of-scope questions, so it runs 28."*
- **② Every claim has a run id.** *"Each column is a committed run file and the dashboard shows the
  same traces the analysis used — nothing here is a remembered number."*
- **③ The quality fixes cost latency, and we say so.** *"The breadth reminder fires on most turns
  now — `nudge_rate` 0.115 → 0.577 — and each of those turns spends an extra step. That is the
  five seconds the middle column lost; the performance wave is what won them back."*
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
- **⑦ The last wave was about the wait, not the score.** *"Streaming and the step narration do not
  move a single metric in that table — the harness waits for the whole answer. They change what a
  person experiences, which is why they were worth doing anyway."*
- **⑧ What is still short.** *"0.893 clears our 0.85 bar, and three items still fail, each with its
  failing clause named — two remote-work items and the one turn that answered instead of stopping
  at the confirmation card. The ablation moved 0.143 against a pre-registered 0.25, so we report it
  as not supported — and we say that the arm's meaning changed when we made the PTO workflow
  require the profile lookup."*

---

## Task 1 — DEMO.6 sub-checklist

Prompt (the **Demo 1** button sends it): *"I want to work from Berlin from 3 November to
14 December 2026 — can I?"* Persona `E1042`, Priya Raghavan, Boston, hybrid, full-time.

Tick all five on camera:

- [ ] **① Tool names** — read them off the live span rail as they land: `mcp_discovery` (nine
      tools), then `lookup_employee_profile`, `check_policy_compliance`, then a burst of
      `search_policy_documents` calls. Say *"the array of tools handed to the model is the
      `tools/list` response converted — there is no hard-coded list anywhere in the agent."*
- [ ] **② Tool-call arguments** — expand the `check_policy_compliance` span and point at
      `duration_days: 42`, `destination_country: "Germany"`, `start_date: "2026-11-03"`. Note that
      the tool normalises `"Germany"` to the ISO code `"DE"` at the wire boundary while the span
      keeps the caller's own bytes.
- [ ] **③ Tool outputs** — scroll the same span's result: the `requirements[]` array with
      `met: false` on the duration rule, the `verdict`, and the fact that **every requirement
      carries its own citation** — *"this verdict is a deterministic rules engine over
      `corpus/rules.yml`, with no LLM in the path."*
- [ ] **④ Retrieved citations** — point at the citation chips under the answer. Breadth here is not
      deterministic. The live run pinned as
      [`docs/evidence/demo-task-1-live-2026-09-11.txt`](evidence/demo-task-1-live-2026-09-11.txt)
      cited **8 chunks across three documents** (`remote-and-hybrid-work`,
      `tax-and-location-addendum`, `manager-approval-matrix`); on the published run
      (`r_1789166880_baseline`) this prompt's dataset twin `remote-004` cited **two** of its four
      expected documents — no block was dropped by the citation guardrail this time
      (`blocks_dropped_by_g2` = 0), the answer was simply narrower than its three-document end
      state, which is why that item is one of the three the run reports as failing. **Read off the
      chips that are actually on screen** — if two appear, say so and click both through. Then
      click one through to the corpus browser and show the 30-day sentence highlighted at its
      exact character offsets.
- [ ] **⑤ Final answer** — read the verdict aloud: **conditional** — 42 days exceeds the 30-day
      threshold so Tax & Legal review is required before travel, Germany is on the approved-country
      list, a company-managed encrypted device with always-on VPN is mandatory, and written manager
      approval is needed at least 21 calendar days before departure. Point out the typed blocks:
      `policy_fact` versus `recommendation`, the latter labelled *"Recommendation — not company
      policy"* in the interface.

The *Full span waterfall* link renders for every persona, but the page behind it is admin-only:
clicking it in the take under `E1042` produces `403 {"code":"ADMIN_REQUIRED"}`. Either paste the
turn's `dashboard_url` into the admin profile, or skip the click here and fold this turn's
waterfall into the 5:30 dashboard tour, which is already on the admin profile.

---

## Task 2 — DEMO.6 sub-checklist

Prompt (the **Demo 2** button sends it): *"Can I take three days of PTO from Tuesday 15 September
to Thursday 17 September 2026 — and can you open the request for me?"* Same persona, so the
narration stays on safety rather than on identity.

Tick all five on camera:

- [ ] **① Tool names** — `check_pto_balance`, `check_policy_compliance`, `search_policy_documents`
      ×2, then the gated `create_mock_hr_ticket`. Note that the write comes **last**, after the
      balance and after the deterministic verdict.
- [ ] **② Tool-call arguments** — expand `check_pto_balance` (`employee_id: "E1042"`) and
      `check_policy_compliance` (`scenario: "pto_request"`, `days: 3`,
      `start_date: "2026-09-15"`). Then expand the **ungated** `create_mock_hr_ticket` attempt and
      show the exact arguments the model proposed.
- [ ] **③ Tool outputs** — the balance result: **13.5 days remaining** at the `2026-09-01`
      snapshot, `1.50` days/month accrual, the accrual fact key, the blackout dates. Say the
      snapshot line out loud — *"the mock data carries an explicit `as_of` snapshot; there is no
      frozen clock anywhere in this system."* Then the compliance verdict: notice requirement met
      with 8 business days against a 5-day rule.
- [ ] **④ Retrieved citations** — **read the chips that are actually on screen.** Breadth here is
      not deterministic: the live run captured in
      [`docs/evidence/demo-task-2-live-2026-09-11.txt`](evidence/demo-task-2-live-2026-09-11.txt)
      cited four chunks across **two** documents (`pto-and-holidays`, `manager-approval-matrix`),
      while earlier live turns cited `pto-and-holidays` alone. Two documents is the design
      expectation the executable record pins, not a promise about the turn on screen — so name what
      is there and click one through to the notice-requirement sentence. On the published run
      (`r_1789166880_baseline`) this prompt's dataset twin `pto-003` met that end state and passed,
      with workflow completion 1.00 for the `pto_request` workflow.
- [ ] **⑤ Final answer and action** — the answer **opens with the ticket id**: *"Done: HR ticket
      `MOCK-HR-<n>` was opened in queue hr-timeoff…"*, then the balance-aware cited answer, the
      ticket in the `hr-timeoff` queue and the new row on the dashboard's mock-action log. Say why
      that first line is deterministic — it is built from the tool result, not from what the model
      wrote, so a confirmed write can never be reported as something the assistant declined to do.
      The same step also clears the **next steps** of anything that sends the viewer off to file
      the request themselves, so nothing under "Next steps:" contradicts the ticket on screen.

### The safety beat (do not rush this — it is the best 40 seconds in the demo)

With the Confirm card on screen:

> *"Watch — the ticket does not exist yet. And it is not the prompt that stops it: the MCP server
> itself refuses the call without a one-time token bound to these exact arguments. The token is
> minted only inside `POST /chat/confirm`, only after I click Confirm. Replay it and it is
> refused; change one argument and it is refused; and the refusal contains no token of any kind,
> so the model can never obtain one."*

The rail line for that refused attempt reads **"Needs your confirmation"** in amber, not red: the
span's recorded status is `error` — the MCP result really is `isError` — but the gate refusing an
untokened write is the safety property working, and the rail says so.

Then, in order:

1. Click **Cancel**. Show `declined` recorded as its own span on the confirmation ledger.
2. Re-ask, reaching the Confirm card again.
3. Click **Confirm**, and watch the `MOCK-HR-<n>` row appear in the mock-action log on dashboard
   page 8, carrying the confirmation token that authorised it.

---

## If something goes wrong on the take

| Symptom | Do this |
|---|---|
| The first request hangs | It is the cold start. Narrate it — the cold-start banner with its elapsed counter is *designed* for this moment — and carry on |
| `/health` reports `degraded` | Read the `degradations[]` array on camera; it names the reason in one machine-readable string. If it is `llm_api_key_missing`, stop and fix the environment variable before recording |
| A tool call returns `isError` | Keep going. Graceful degradation is a graded behaviour: the turn still answers at HTTP 200 with a caveat block, and the `error` span is right there on the rail |
| The model takes a path different from this script | Expected, and fine. The expectation records assert the **outcome** — the profile, the corpus, the deterministic verdict, the cited documents — not one exact path. Narrate what it actually did |
| A dashboard page shows `{"code": "ADMIN_REQUIRED"}` | You are on the employee persona. Set the act-as selector to **HR admin** and reload. If you switched in the profile you are running chat in, switch back to `E1042` before the next task — `mosaic_actor` is one cookie shared by the chat and the dashboard |
| Fewer citation chips than the checklist names | Name the documents that are on screen and click each through. `evaluation/REPORT.md` already reports `remote-004` — the dataset twin of this prompt — failing its three-document end state on the published run; say that out loud rather than around it. It is the same breadth gap beat ⑧ closes on |
| More citation chips than an earlier run showed | Also expected: the published run added a bounded breadth-repair step, so a multi-document answer that cites fewer documents than its evidence spans gets one repair attempt. Narrate the chips on screen, not the number in this script |
| You run past 10:00 | Cut the dashboard tour (5:30–6:15) to 20 seconds; it is the only segment whose content appears elsewhere in the recording |
