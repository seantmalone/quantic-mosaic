# Demo script: Mosaic HR Copilot

**Presenter:** Sean Malone. **Length:** 8:30 planned (course limit 7:00–10:00). Everything runs live
on the deployed app. Read the **Say** text out loud; the **Do** lines are for your hands.
Tick [`pre-submission-checklist.md`](pre-submission-checklist.md) after the take.

---

## Before you record

- [ ] **Tabs, left to right:**
  1. Architecture: `file:///Users/sean/Projects/quantic-mosaic/docs/architecture.html`
  2. Chat: open the tokenized link in the README. It settles on `https://mosaic-hr-copilot.onrender.com/`.
  3. `https://github.com/seantmalone/quantic-mosaic/blob/main/render.yaml`
  4. `https://mosaic-hr-copilot.onrender.com/health`
  5. `https://github.com/seantmalone/quantic-mosaic/actions?query=branch%3Amain`
  6. `https://github.com/seantmalone/quantic-mosaic/blob/main/docs/evidence/ci-deploy-skipped.png`
  7. `https://mosaic-hr-copilot.onrender.com/dashboard/evals/r_1790130220_baseline`
- [ ] **Warm up:** reload tab 4 until `"status":"ok"`, then send one throwaway question in the chat tab.
- [ ] **Record before 17:00 PT.** The server dates prompts in UTC.
- [ ] **Record by about 12 October**, so the Berlin button still says 3 November – 14 December (the policy's own example).
- [ ] **Never reload the chat tab.** Cmd-click every link that leaves it. To get back from the dashboard, use "Continue this conversation in chat".
- [ ] The Task 2 dashboard link lands on `#turn-2`. Scroll **up** for turn 1.
- [ ] Guardrails: type `/dashboard/safety#MOCK-HR-<n>` to jump to the new ticket.
- [ ] Webcam overlay on for the whole take. Keep it clear of "Sources (n)" and the row chevrons.
- [ ] 20-second audio test clip.

---

## Segments

| Time | Beat |
|---|---|
| 0:00–0:30 | 1. Intro and ID |
| 0:30–1:15 | 2. Design |
| 1:15–3:35 | 3. Task 1 live: working from Berlin |
| 3:35–5:55 | 4. Task 2 live: PTO request through the confirmation gate |
| 5:55–6:35 | 5. Deployment |
| 6:35–7:15 | 6. CI/CD |
| 7:15–8:10 | 7. Evaluation |
| 8:10–8:30 | 8. Close |

Total **8:30**.

---

### 1. Intro and ID

**Time:** 0:00–0:30
**Open:** Webcam full frame.
**Do:**
1. Hold the government ID still next to your face for 3 seconds at about 0:15.
2. Shrink the webcam to the overlay. Switch to tab 1.

**Say:**
> Hi, I'm Sean Malone. Here's my government ID.
>
> This is Mosaic HR Copilot. It's an HR assistant for a made-up 420-person robotics company. It
> answers questions from 14 policy documents, and it can call nine tools to look things up or
> file requests. It records every step it takes. Everything you'll see today runs live on the
> deployed app.

### 2. Design

**Time:** 0:30–1:15
**Open:** Tab 1, `docs/architecture.html`.
**Do:**
1. Point at each box as you name it.

**Say:**
> Here's the design. The whole app is one Docker container. A question comes into the web app,
> and the agent orchestrator decides what to do next. When it needs a tool, it goes through an MCP
> client to the MCP server. That server lives in the same container, but the agent talks to it
> over real JSON-RPC, so these are genuine tool calls. Search runs over a hybrid keyword and vector
> index of the policies. The HR tools read mock employee data. The model is Claude Haiku. Each step
> writes to one trace store, and the chat, the dashboard and the evals all read from it.

### 3. Task 1 live: working from Berlin

**Time:** 1:15–3:35
**Open:** Tab 2, chat (`https://mosaic-hr-copilot.onrender.com/`).
**Do:**
1. In the demo panel, click "Working from Berlin for six weeks".
2. Read the dates in the composer. Click **Send**.

**Say:**
> First task. I'm signed in as Priya, a hybrid employee based in Boston. This button fills in her
> question. She wants to work from Berlin from [read the dates in the composer]. I'll send it.

**Do (wait, about 40 s):**
3. Point at the progress line under the question.

**Say (while it runs):**
> This one takes about forty seconds. The line under the question is the progress line. It's
> written for the employee, so it just says things like "Searching the policy library." Behind
> it, the agent pulls up her HR record, runs a compliance check and searches the policies. I'll
> show you those calls on the dashboard in a minute.

**Do:**
4. Scroll through the answer to "What I suggest you do".
5. Click "Sources (n)". Expand one entry.
6. Cmd-click its "Open …" link. Show the highlighted section in the policy reader. Close that tab.

**Say:**
> Here's the answer. Germany is on the approved list. Forty-two days is over the thirty-day limit,
> so she needs a Tax and Legal review and director approval before she travels. It fits under the
> ninety-day yearly cap, and she has to use a company laptop on the VPN. That's the final answer.
> Each fact has its citation under it, and my advice is marked as guidance.
>
> Here are the sources, [read the number on screen] passages. This one opens the policy reader on
> the exact section it quoted.

**Do:**
7. In the demo panel under "This conversation", Cmd-click "Open this conversation in the dashboard".
8. In the new tab, scroll to the step rows. Click the chevron on the "check_policy_compliance" Tool call row.
9. Click the chevron on one "search_policy_documents" Tool call row, then on the Retrieval row under it.

**Say:**
> This is the session record, one row per step. The tool names are
> lookup_employee_profile, then check_policy_compliance, then [read the number on screen] calls to
> search_policy_documents. The agent gets that tool list from the MCP server at runtime.
>
> In the compliance call, the arguments are the scenario, international remote, her
> employee ID, Germany, and the two dates. The output is the verdict, "conditional", with each
> requirement listed. The duration rule is marked not met. A rules engine wrote that verdict. No
> model touched it.
>
> This search shows the model's query, and the row under it shows each passage it got back with
> its score.

#### Task 1: DEMO.6 sub-checklist

- [ ] Tool names: read off the step rows.
- [ ] Arguments: `check_policy_compliance` payload, `arguments`.
- [ ] Outputs: same payload, `structured_content` with `"verdict": "conditional"`.
- [ ] Citations: "Sources (n)", then one opened in the policy reader.
- [ ] Final answer: read from the chat page.

### 4. Task 2 live: PTO request through the confirmation gate

**Time:** 3:35–5:55
**Open:** Tab 2, chat.
**Do:**
1. Click "Three days of PTO, opened for me". Click **Send**.

**Say:**
> Second task. This one writes something. Priya asks for three days off, [read the dates in the
> composer], and asks the assistant to open the request for her.

**Do (wait, about 20 s, until the card shows):**
2. Point at the progress line.

**Say (while it runs):**
> This one's quicker, about twenty seconds. It checks her PTO balance and the notice rule, then
> searches the PTO policy. After that it tries to create the ticket. It can't do that by itself.

**Do:**
3. Point at "Confirm before anything is written" and "Nothing is written until you choose."

**Say:**
> And here it stops. The ticket doesn't exist yet. The MCP server refuses the write without a
> one-time token tied to these exact details, and the app only makes that token when I click.
> Replay it or change a detail and the server refuses. First I'll say no.

**Do:**
4. Click "Don't open it". Point at "You cancelled this — nothing was created."
5. Click "Three days of PTO, opened for me" again. Click **Send**. Wait about 10 s for the card.

**Say:**
> Nothing was created, and she still gets her balance and the notice rule. Now I'll ask again and
> approve it.

**Do:**
6. Click "Open the request".

**Say:**
> Done. The request went to the HR Time Off team, reference [read the MOCK-HR number on screen].
> That line comes straight from the tool's result, so the model can't invent a ticket number. The
> citations under it are the notice rule and the approval chain.

**Do:**
7. Cmd-click "Open this conversation in the dashboard". It opens on Turn 2. Scroll up to Turn 1.
8. Click the chevron on "check_pto_balance".
9. Click the chevron on "create_mock_hr_ticket", the row marked "paused for confirmation".
10. Scroll down to Turn 2. Click the chevron on the last "create_mock_hr_ticket" row.

**Say:**
> I'll scroll up to turn one. The tool names are
> check_pto_balance, check_policy_compliance, search_policy_documents, lookup_employee_profile and
> create_mock_hr_ticket.
>
> The balance call takes her employee ID and returns thirteen and a half days left, as of the
> September first snapshot. Here's the paused ticket call. Its arguments are the queue and a
> summary, and its output says confirmation required, with no token. In turn two the same call
> goes through, token redacted, and the output says created, with the ticket ID.

**Do:**
11. In the address bar, go to `https://mosaic-hr-copilot.onrender.com/dashboard/safety#MOCK-HR-<n>`.
12. Point at "Confirmations", then the row under "Simulated writes".

**Say:**
> Guardrails keeps the audit trail: my decline and approval under Confirmations, and the ticket
> under Simulated writes.

#### Task 2: DEMO.6 sub-checklist

- [ ] Tool names: read off Turn 1 and Turn 2.
- [ ] Arguments: `check_pto_balance` and the paused `create_mock_hr_ticket`.
- [ ] Outputs: 13.5 days remaining; "confirmation required"; then "created".
- [ ] Citations: the policy lines under the confirmed answer.
- [ ] Final answer and action: "Done — your request is with the HR Time Off team. Reference MOCK-HR-<n>."

### 5. Deployment

**Time:** 5:55–6:35
**Open:** Tab 3 (`render.yaml`), then tab 4 (`/health`).
**Do:**
1. On `render.yaml`, point at `runtime: docker` and `autoDeploy: false`.
2. Switch to tab 4 and reload. Point at `status`, `tool_count`, `chunk_count`, `rss_mb`.

**Say:**
> For deployment, it's one free web service on Render, built from the Dockerfile. Auto-deploy is
> off, so CI is the only way code reaches production. This is the live health check. Status is
> ok, the MCP server's connected with nine tools, and the index has 205 chunks. Memory is at
> [read rss_mb on screen] megabytes, against a 512 megabyte limit. The free tier sleeps after
> fifteen minutes. I measured cold starts at about seventy seconds, then added a keep-alive ping.

### 6. CI/CD

**Time:** 6:35–7:15
**Open:** Tab 5 (Actions), then tab 6 (red-run screenshot).
**Do:**
1. Click the newest green "ci" run on main. Point at the five jobs.
2. Switch to tab 6.

**Say:**
> CI/CD runs in GitHub Actions on each push and pull request. There are five jobs. Lint runs ruff
> and a gitleaks secret scan over the whole history. Test runs the suite offline with a ninety
> percent coverage floor. UX runs the browser tests, and Docker builds the image. Deploy waits for
> test, docker and ux to pass, then triggers Render and smoke-tests the live app. Here's a run where
> I broke a test on purpose. Test went red, and deploy was skipped.

### 7. Evaluation

**Time:** 7:15–8:10
**Open:** Tab 7, `https://mosaic-hr-copilot.onrender.com/dashboard/evals/r_1790130220_baseline`.
**Do:**
1. On the Metrics tab, point at each tile as you read it.
2. Click "Evaluations" in the nav, then "Compare".
3. Point at the "Workflow completion" and "Documents recalled" bars for baseline, then at "Workflow completion — the pre-registered check".

**Say:**
> This is the published eval run: thirty test questions against the deployed app, graded by a
> judge model from another vendor. Strict pass rate is 90 percent, 27 of 30, against my 85
> percent target. Groundedness is 98.4 percent and citation accuracy is 87.3. Tool selection is
> 99.3 percent. Action safety is 100 percent on its two items.
>
> On Compare, the baseline's workflow completion is [read the number on screen] percent, and
> documents recalled is [read the number on screen] percent. The ablation takes the structured
> tools away, and workflow completion falls to 73.3 percent. I'd pre-registered a drop of more
> than 25 points. It dropped 20, so the page says "Claim supported: no", and I'm reporting that.

### 8. Close

**Time:** 8:10–8:30
**Open:** Tab 2, chat. Webcam can go back to full frame.
**Do:**
1. Look at the camera.

**Say:**
> So that's Mosaic. You saw both tasks run live, with every tool call traced back to a cited
> answer, and a write that can't happen without my click. Three eval items still fail, and the
> run page names the rule each one broke. The code and all the eval runs are in the repo. Thanks
> for watching.

---

## Appendix: reference values and fallbacks

- Task 1 wait 36–47 s; Task 2 about 20 s to the card, about 10 s on the re-ask, about 7 s after "Open the request".
- Task 1 typical: 8 sources, 6 tool calls, verdict `conditional`, duration rule `met: false`.
- Task 2 typical: 4 sources, 13.5 days remaining, 6 business days' notice (varies with the date).
- `/health`: `tool_count` 9, `chunk_count` 205, `rss_mb` around 300 (cap 512). Cold start median 71 s.
- Eval: strict pass 90.0% (27/30), groundedness 98.4%, citation accuracy 87.3%, tool selection 99.3%, action safety 100.0% (2/2).
- Compare: workflow completion 93.3% → 73.3% (−20.0% vs a 25.0% bar, "Claim supported: no"); documents recalled 97.4% baseline.
- First request hangs: it's a cold start. Say "the free tier is waking up" and keep talking.
- `/health` shows `degraded`: read `degradations[]` aloud. If it's `llm_api_key_missing`, stop and fix it.
- The agent takes a different path: fine. Read the tool names that are actually on screen.
- Fewer sources than usual: name what's there. Breadth varies run to run.
- You reloaded the chat tab: open `/dashboard/sessions`, pick the session, click "Continue this conversation in chat".
- A button says `ADMIN_REQUIRED`: nothing in this script needs admin. Skip it.
- Running long: cut the policy-reader click (step 6 of beat 3) and the Guardrails stop (beat 4, steps 11–12).
