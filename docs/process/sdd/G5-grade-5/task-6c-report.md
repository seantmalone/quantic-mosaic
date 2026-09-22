# Task 6c — docs/demo-script.md

**Commit `d4f8ed9`** on `main`: `G5(demo-script): each live turn twice-framed — chat page for the
answer, the session record for the tools`. One path, explicitly added: `docs/demo-script.md`.
Trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`, no `Claude-Session` trailer.
222 insertions, 143 deletions. Working tree still carries the other agents' files (README,
deployed.md, design-and-evaluation.md, requirements-traceability.md, pre-submission-checklist.md,
NEEDS-FROM-USER.md, corpus/README.md, CHANGELOG.md) — none of them touched here.

Line references below are against the committed file.

## Gap 5 — the deleted span rail, and the twice-framed turn

`grep -ni '\brail\b' docs/demo-script.md` → **no hits** (the six matches on "Guardrails" are the
dashboard page's real name). What replaced it:

- **Lines 10–15, new paragraph in the header.** States the split as a premise: the chat page carries
  the answer, the `Sources (n)` strip, the confirmation card and one progress line "and nothing
  else"; tool names, arguments and results are on `/dashboard/sessions/{id}#turn-N`, the
  `dashboard_url` every `ChatResponse` returns, reached from **"Open this conversation in the
  dashboard"** under **This conversation** in the demo panel.
  - *Label verified* at `src/hrmosaic/web/templates/_demo_controls.html:85-93` (`demo-link`, the
    `<h3>This conversation</h3>` group, the 8-char `id_chip`). The dispatch's phrasing "Open this
    conversation's record" is **not** the shipped string; the template's exact wording is used.
  - *URL shape verified* at `src/hrmosaic/web/api.py:1552,1725,1956` —
    `f"/dashboard/sessions/{session_id}#turn-{seq}"`.
- **Line 32 (production note).** The overlay-occlusion bullet now names the third thing the PiP can
  cover — the chevron at the left of a span row, which is the control that opens the payload
  (`templates/dashboard/session_detail.html:155-159`) — and states plainly that chat has been one
  centred column since UX W2 with no side panel.
- **Lines 44–45 (production note, screen setup).** Two browser tabs on the app, so the switch to the
  record is a tab and not a back-and-forward.
- **Lines 67–68 (segment table).** Each task row's "What is on screen" column now carries the
  per-frame split: Task 1 = chat ≈ 1:15, record ≈ 0:45, policy reader ≈ 0:15; Task 2 = chat and card
  ≈ 1:20, record ≈ 0:40, Guardrails ≈ 0:20.
- **Lines 140–218 (Task 1 sub-checklist)** and **lines 220–306 (Task 2)** are split into an **"On the
  chat page"** half (④ citations, ⑤ final answer/action) and a **"Then switch to the record"** half
  (① tool names, ② arguments, ③ outputs), with the transition paragraph at lines 189–196 naming the
  turn tiles as they render: **Model calls · Tool calls · Retrievals · Guardrail blocks · Safety
  checks · Policy rules · Tokens · Model time** (`session_detail.html:111-122`).
- **Line 326 (troubleshooting).** The "path different from this script" row now says to read the tool
  names off the waterfall rather than off the page.
- **Line 331 (troubleshooting).** The final row's cut instruction explicitly forbids cutting either
  task's dashboard frame, "that is where DEMO.6 ①–③ are evidenced".

## The new segment table, and its sum

| Time | Segment | Length |
|---|---|---|
| 0:00–0:45 | Intro, on camera, full frame | 0:45 |
| 0:45–1:25 | Architecture | 0:40 |
| 1:25–3:40 | **Task 1 live** — chat, record, policy reader | 2:15 |
| 3:40–6:00 | **Task 2 live** — chat and card, record, Guardrails | 2:20 |
| 6:00–6:25 | Dashboard tour — Tool server, Model calls | 0:25 |
| 6:25–7:10 | Deployment | 0:45 |
| 7:10–7:50 | CI/CD | 0:40 |
| 7:50–8:50 | Evaluation | 1:00 |
| 8:50–9:15 | Close | 0:25 |

45 + 40 + 135 + 140 + 25 + 45 + 40 + 60 + 25 = **555 s = 9:15**, stated as a visible sum on line 75.
Verified by script: the nine ranges are contiguous (each start equals the previous end) and total
555 s. 9:15 is also what `tests/contract/test_docs_completeness.py:774` requires
(`\b9:15\b|\b9:1\d\b`), so the figure is guarded.

Two documented cuts remain, both outside the graded frames: the dashboard tour to 0:10 and the
optional `draft_hr_email` beat.

Turn-duration budget is stated honestly rather than assumed: Task 1's turn alone is budgeted at
~45 s, sourced to `docs/evidence/demo-task-1-live-2026-09-15-p29.txt` (46,750 ms over 35 spans).

## Gap 13 — CI/CD and the counts

**Line 71 (CI/CD row).** Five jobs named — `lint`, `test`, `ux`, `docker`, `deploy` — read off
`.github/workflows/ci.yml` (jobs at lines 24, 47, 94, 118, 145). The `ux` rationale is quoted from
the workflow's own comment: *"a browser suite must never be able to block a deploy, so it is its own
job with no `needs:` and nothing needing it; it reports, it does not gate."* `deploy` still declares
`needs: [test, docker]`; Render auto-deploy off.

**Test counts, both stated:**

```
$ .venv/bin/pytest --collect-only -q -m ""      -> 3410 tests collected
$ .venv/bin/pytest --collect-only -q            -> 3111/3410 tests collected (299 deselected)
```

The script says the `test` job collects **3,111 of 3,410** because `addopts` carries `-m "not ux"`
(`pyproject.toml:108`), and that the **299 deselected** are the browser tests `ux` runs. Not guarded
by `NUMBER_DOCS` (which excludes `docs/demo-script.md`), so both figures are hand-checked against
the two collections above.

**Cold/warm latency moved.** It is narrated only in the 6:25–7:10 deployment row (line 70), which
says so in as many words — *"This is the only place the cold/warm split is narrated, because the
published evaluation run has `n_cold = 0`"*. Figures from `deployed.md:180-189`: median **71.0 s**
cold to first answer over n = 3 (67.5–77.6 s), 44.8 s of it before `/health` answers, **22.5 s**
warm. RSS from `deployed.md:460,479` (**293.6 MB** on Render, 2026-09-10) and `:442,447`
(**294.9 MB** under the local gate).

## Gap 14 — observability

**Lines 79–96, new section "Observability beat (6:00–6:25)".** The spoken paragraph describes what
the waterfall renders: every step as a row with its duration bar, each opening on the stored payload;
a model call showing its **purpose** (route / act / synthesize / repair), the **tools it was
offered** by name, its **token counts**, the **text it returned** and the tool calls it proposed; a
retrieval showing each passage with its score; a tool call showing arguments and result. Verified
field-by-field against `LlmCallPayload` in `src/hrmosaic/core/llm/base.py:368-385`
(`purpose`, `tools_offered`, `response_text`, `tool_calls`, `prompt_tokens`, `completion_tokens`) and
against `_summary` in `src/hrmosaic/agent/orchestrator.py:847-854`
(`purpose=… · 1,439→133 tok`).

**Lines 92–96, the two things not to say.** `messages_ref` is named as a span id, a message count and
a character total, with the bodies in a separate `llm_messages` table "with no route and no
drill-down reading it" (`core/llm/base.py:369-373`; `grep -rn llm_messages src/hrmosaic/web/` → no
hits). The second is the `paused for confirmation` row not being a failure.

## Evaluation beat, republished

**Line 72 (segment row) and lines 106–138 (beats ①③⑧).** Everything from
`evaluation/REPORT.md` and `.superpowers/…/task-5-report.md` for
**`r_1790074972_baseline`, build `8a89310`**, 28 items, 7 categories
(`load_dataset()` → 28 items, 7 categories):

| Stated in the script | Value | n |
|---|---|---|
| Groundedness | 0.963 | 18 |
| Citation accuracy | 0.875 | 18 |
| Document recall | 0.947 | 19 |
| Tool selection | 0.993 | 28 |
| Workflow completion | 0.964 | 28 |
| Clarification accuracy | 1.000 | 3 |
| Action safety | 1.000 | **1** — called out as "one item, not a rate" |
| Strict pass | 0.893 | 28 (target ≥ 0.85) |

The three failing items are named by clause: `remote-002` (workflow completion 0.00 < 1.00),
`expenses-002` (groundedness 0.79 < 0.85), `equipment-001` (0.69 < 0.85) — `REPORT.md` strict-pass
causes table, recomputed by `deterministic.strict_pass_causes()`.

**Ablation, narrated as a null (lines 129–138, beat ⑧).** Workflow completion 0.964 → 0.821, delta
**0.143** against a pre-registered 0.25 — *"so the bar was **not** met and the report says so in the
banner it generates"*. The two secondary deltas are given as the honest positive finding: tool
selection 0.993 → 0.942 (−0.051) and strict pass 0.893 → 0.786 (−0.107). No word anywhere claiming
the delta is "supported". Source: `REPORT.md` ABLATION block and `task-5-report.md`'s
`workflow_completion_check` (`supported: false`).

**Judge-rationale overclaim fixed.** The old file's line 62 said *"Open one item to show the judge
rationale"*. The `Items` table's disclosures are `Scores` and `Verdicts`
(`templates/dashboard/eval_detail.html:210-215`), and the run file's `verdicts` payload carries
per-claim labels plus `judge_model`, no prose. The script now opens `equipment-001`'s **Verdicts**
disclosure — eight claims, `c4 contradicted`, `c5 unsupported`, groundedness 0.69 — and says in as
many words that it is per-claim verdicts, not a paragraph.

**Compare tab.** Named as it ships: *"Ablation — three variants over the identical items"* with the
**Build measured** column showing all three arms on `8a89310`, plus the instruction to read the
*"These arms were measured on different builds"* notice aloud if it ever appears, because the tab
pairs the newest run per variant in the deployment's store
(`templates/dashboard/evals.html:121-139`).

**Beat ① re-worded to avoid a column count** that Task 6b is concurrently changing: "strict pass
0.692 at the start, 0.893 from the fourth measurement on, and 0.893 again on the published run; p50
was 22.6 s at its worst and is 15.3 s now" (`docs/optimization-log.md:398-407`, `REPORT.md` latency).
Beat ③ gives nudge_rate 0.115 → 0.577 → 0.571 on the published run.

## Demo scripts, line ~117's old claim

**Lines 146–160.** The old text said the scripts "still send the recorded wording". Replaced with
what they do: both scripts **fetch the self-dated prompt from the server** before asking anything,
the frozen wording is **opt-in** behind `--recorded` (or `DEMO_RECORDED=1`), and it only reproduces
the documented verdicts against a server pinned to `MOCK_TODAY=2026-09-01` — `make demo1` /
`make demo2`. Verified against `scripts/demo_task_1.sh:26-50` and `scripts/demo_task_2.sh` (the
`elif ! PROMPT="$(… demo_prompt.py … --key demo_N)"` branch with `exit 1` and no silent fallback),
and against `tests/unit/test_demo_prompts_are_dated.py::test_each_script_asks_the_server_for_its_own_prompt`
and `::test_the_recorded_wording_is_opt_in_and_never_a_silent_downgrade`.

## Admin profile

`ADMIN_ROUTES` (`src/hrmosaic/web/api.py:134-140`) is exactly three write endpoints:
`POST /api/dev/reset-sandbox`, `POST /api/mcp/rediscover`, `POST /api/eval/runs`. The module
docstring at `:20-23` says every `/dashboard/*` page and every `/api/*` read answers any persona
holding the token.

- **The old line 62 is gone:** that evaluation row opened *"**Admin profile again.**"* — `/dashboard/evals`
  is a read. The new row (line 72) opens *"No persona change — the dashboard is open to any persona
  holding the token."*
- **Lines 40–45:** the production note now names the three endpoints and states that nothing in the
  script presses one.
- **Line 327 (troubleshooting):** the `ADMIN_REQUIRED` row keeps the fix and adds *"reading any
  dashboard page needs no persona change"*.

## Other UI claims corrected against the shipped templates

| Was | Is, and where verified |
|---|---|
| "both agentic tasks are one-click buttons … no typing" | The buttons **prefill the composer**; you press **Send** (`chat.html:610-620` `prefill()`; `:106` `<button id="send-button">Send`). Lines 6–8, 67, 68, 142, 222. |
| "Click **Cancel**" / "Click **Confirm**" | **"Don't open it"** and **"Open the request"** (`_turn.html:202-203`), with the card's heading *"Confirm before anything is written"* and note *"Nothing is written until you choose."* (`:192,198`). Lines 68, 257–262, 274–284. |
| *"Done: HR ticket `MOCK-HR-<n>` was opened in queue hr-timeoff…"* | *"Done — your request is with the HR Time Off team. Reference `MOCK-HR-<n>`. Your manager's written approval is the next step."* (`agent/outcome.py:402-408`, `NEXT_EVENT` at `:110-112`, `core/queues.py:19`). Lines 68, 244–254. |
| "`outcome.py` inserts the opener only when the model has not already stated the id" | No longer true: the `performed` statement is now **always** prepended and a model block of any type naming the id is **removed** (`outcome.py:22-31`, `:999-1003`). Lines 244–254, with the 2026-09-15 live regression named as the reason the guard was rewritten. |
| Cancel "shows `declined` recorded" | The card resolves to **"You cancelled this — nothing was created."** (`web/api.py:1090`) and the answer is the cancelled receipt *"Cancelled — nothing was created. Ask again whenever you would like me to open it."* (`orchestrator.py:493`). Lines 276–279. |
| "the cold-start banner with its **elapsed counter**" | There is no counter: the banner reads *"Just waking up — the first answer may take a little longer."*, raised by a `/health` preflight (`chat.html:23`, `:646-658`). Line 323. |
| "every LLM call with its verbatim messages, every retrieval …, every tool call …" | The observability section above. |
| "the `error` span is right there on the rail" | "the `failed` flag is right there on the span row" (`session_detail.html:168-170`). Line 325. |
| Dashboard pages unnamed / mis-numbered | Named as the nav names them: **Tool server** `/dashboard/mcp` page 9 (`Server` / `Discovered tools` / `Handshake history`), **Model calls** page 5, **Guardrails** `/dashboard/safety` page 8 (`Verdicts by rule`, `Confirmations`, `Simulated writes`), **Evaluations** page 11 (`dashboard.py:95-110`; `safety.html:31-84`; `mcp.html:13-60`). |
| "mock-action log" | **Simulated writes** (`safety.html:84`). |

## Task 1 / Task 2 evidence, refreshed

The pinned live captures were upgraded from the 2026-09-11 pair to the newest ones:

- **Task 1** now cites `docs/evidence/demo-task-1-live-2026-09-15-p29.txt` (build `d8a2ca3`):
  **10 passages across four documents** — `remote-and-hybrid-work`, `tax-and-location-addendum`,
  `manager-approval-matrix`, `travel-policy` — 35 spans, 46.8 s. The chain in ① is that run's real
  `seq` order: `mcp_discovery` ("9 tools discovered over http") → `lookup_employee_profile` →
  `search_policy_documents` → `get_policy_section` → `check_policy_compliance` → a burst of further
  `search_policy_documents`. ② quotes the real argument shape, including the **nested `parameters`
  object** the old script flattened: `scenario: "international_remote"`, `employee_id: "E1042"`,
  `parameters: { destination_country: "Germany", start_date: "2026-11-03", duration_days: 42 }`. The
  ISO-`DE` normalisation claim is confirmed at
  `src/hrmosaic/mcpserver/tools/check_policy_compliance.py:11,73,86`.
  `remote-004` (the dataset twin) **passes** on the published run with document recall 0.75 — the old
  script's "cited two of its four expected documents … one of the three the run reports as failing"
  is gone.
- **Task 2** now cites `docs/evidence/demo-task-2-live-2026-09-15-p29.txt`: **three passages from one
  document** (`pto-and-holidays` — Notice Requirements, Approval Chain, Blackout Periods) with **no
  `search_policy_documents` call at all**, beside the 2026-09-11 run's four passages across two
  documents. ① says so explicitly, so the presenter is not hunting for a tool that may not fire.
  `pto-003` passes; `pto_request` workflow completion 1.00 is labelled an indicator over n = 1.
- The `Sources (n)` unit ambiguity is called out once: the heading counts **passages**, the record's
  citation line says *"(across n documents)"*, the demo panel says *"n policy sections read"*
  (`_turn.html:213`; `dashboard.py:713-728`; `web/api.py:1285-1289`).

## Optional beat

**Lines 308–315.** `draft_hr_email` through the same gate, narrating *"Done — the email draft is
ready for <name>. Reference `MOCK-EMAIL-…`"* (`outcome.py:393-396`) and the same cancelled receipt,
deployed in `8a89310`. Explicitly labelled *"a bonus, not a requirement … the first thing to cut"*,
and named again in the troubleshooting table's over-run row. The two required tasks remain the spine.

## Tests

```
.venv/bin/pytest -q -p no:cacheprovider tests/contract tests/unit/test_demo_prompts_are_dated.py
956 passed in 176.74s (0:02:56)
```

Plus the two collections quoted above for the test counts, and the dataset probe (28 items, 7
categories). No GET or POST was made against the deployed service; every label was read from the
templates and route tables. `.env` and `data/runtime/provision_turso.json` were not read.

## Concerns

1. **Two live claims in the script are not pinned by a committed capture on the final build.** The
   write lede (*"Done — your request is with the HR Time Off team. Reference … Your manager's written
   approval is the next step."*) is quoted from `agent/outcome.py` on `8a89310`; the newest committed
   transcript (`demo-task-2-live-2026-09-15-p29.txt`, build `d8a2ca3`) shows the **earlier** wording
   *"Done: your request is with the HR Time Off team. Reference MOCK-HR-000008."* — a colon rather
   than an em dash, and without the `NEXT_EVENT` sentence UX W7 added. Same for `draft_hr_email`,
   which grade-report gap 21 already flags as having **no live-call evidence at all**. The script
   quotes the code, which is what will be on screen, but a grader comparing script to transcript
   will see the older string. One confirmed live `demo_task_2.sh` run plus one `draft_hr_email` turn
   against `8a89310`, pinned under `docs/evidence/`, would close both.
2. **The evaluation segment points the camera at the deployment's own eval store, which is not
   guaranteed to front the committed published run.** The script names `r_1790074972_baseline` and
   the figures come from the committed run file; `/dashboard/evals` shows whatever this deployment
   imported. If `eval_runs_imported` fronts a newer dashboard-only drive (task 5's report lists three
   such runs), the tiles on screen will not be the numbers spoken. Worth a `GET /dashboard/evals`
   check during the warm-up, before the take.
3. **`docs/architecture.html:1569` is on screen during the 0:45–1:25 segment and still says "four
   jobs"** (per gap 13's evidence). That file is outside my ownership and outside every Task 6
   sub-brief I can see; nothing in this wave appears to own it. Same for the span-rail leakage gap 5
   records at `architecture.html:1107,1507`. If nobody picks those up, the architecture segment
   shows a contradicted claim while the presenter says "five".
4. **9:15 leaves 45 s of headroom, and Task 1's turn is 45 s of measured latency on its own.** The
   budget is honest but not generous: a cold instance (median 71.0 s) blows it. The warm-up
   instruction is therefore load-bearing, not advisory, and the over-run row's cut list is the only
   slack.
5. **Two segment rows are long paragraphs.** The CI/CD and evaluation cells now carry a lot of spoken
   detail for 40 s and 60 s respectively. They are readable as a script but will need a rehearsal
   pass to fit; the figures are the part that must not be paraphrased.

---

# Fix round 1

**Commit `b7cf1f1`** on `main`: `G5(demo-script): fix round 1 — the observability beat is narrated
over the record that shows it`. One path, explicitly added: `docs/demo-script.md`. Trailer
`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`, no `Claude-Session` trailer. 23
insertions, 6 deletions.

## IMPORTANT — the observability beat was staged over a page with no waterfall

**Confirmed, and the reviewer is right.** `templates/dashboard/llm.html` is two `t.table(...)` calls
and nothing else: **By model** (`Model`, `Calls`, `Tokens in`, `Tokens out`, `Estimated cost`) at
`:27-38`, and **Calls** (`Model`, `Purpose` badge, `Tokens in`, `Tokens out`, `Duration`, `First
token`, `Streamed`, `Finish`, `Provider`, `Turn` with `link_key: dashboard_url`, `Span`) at `:46-59`.
No `detail_key` on any column, no `<details>`, no waterfall, no payload. The beat's paragraph —
duration bars, per-row payload disclosures, `tools_offered`, `response_text`, retrieval passages with
scores, tool arguments — describes `session_detail.html:139-192`, which is a different page.

Fixed by re-anchoring the beat, not by rewriting the paragraph (the paragraph was already verified
true of the record):

- **Section heading and new lead-in (`docs/demo-script.md:84-90`).** Retitled *"Observability beat —
  say it over the record, because the record is what shows it"*, and the first paragraph now says
  **"No new segment, and not the 6:00–6:25 tour"**: the beat rides **task 1's record frame**, where
  the waterfall is already open for DEMO.6 ①–③ and this paragraph is the sentence that frames those
  three ticks. Costs no time, because that frame was already budgeted at ≈ 0:45.
- **Task 1 segment row (`:72`).** Now reads *"Then switch to the record for DEMO.6 ①–③ … — **the
  observability beat is said here**, with the waterfall open, because this is the page that shows
  it — and come back through one citation into the **policy reader**."*
- **Page 5 given its own true description, twice.** In the tour row (`:74`) as the one line to say —
  *"the same model calls, aggregated across every session: purpose, token counts, first-token and
  streamed, and a **Turn** chip back into the record"* — followed by **"The observability beat is not
  narrated here"** and the reason (two tables, not a waterfall). And in the observability section
  itself, a closing paragraph **"What page 5 is, if you keep it in the tour"** (`:105-112`) naming
  both tables and every column above, with the explicit *"is **not** a waterfall and has no payload
  disclosures"*.
- The stale cross-reference *"for the observability beat below"* is gone
  (`grep -c 'observability beat below'` → 0).

## MINOR 1 — the disclosure is on the right, not the left

**Confirmed.** `.span-row`'s `grid-template-columns` is seven tracks
(`src/hrmosaic/web/static/app.css:1081`) and `.span-payload > summary` is placed in track **7**;
below 70rem the row is five tracks and the summary is placed in track **5** (`:1146`). Last track at
both widths, i.e. the right-hand end.

`docs/demo-script.md:31-34` now reads *"the chevron at the **right-hand end** of a span row, which is
the control that opens the payload (it is the last grid track at every width)"*.

## MINOR 4 — warm-up check on the published run

`docs/demo-script.md:59-63`, appended to *"Wake the instance first"*: **"In the same warm-up, open
`/dashboard/evals` and confirm the Runs table fronts `r_1790074972_baseline`"** — with the reason (the
store can hold later dashboard-only drives whose tiles would not match the script) and the
instruction to check it before the take, not on camera. This is concern 2 of the first round turned
into a scripted action.

Minor 2 (the pinned transcripts predate the spoken write lede) and Minor 3 (leakage in
`architecture.html`, the design doc and traceability) left alone as directed; the lede is still quoted
from `agent/outcome.py`.

## Runtime, re-summed

Unchanged — no time was moved, because the beat went into a frame that was already budgeted.
Re-verified by script after the edits: **nine segments, contiguous (each start equals the previous
end), total 555 s = 9:15**, inside 7:00–10:00 and still matching the `\b9:15\b|\b9:1\d\b` guard at
`tests/contract/test_docs_completeness.py:774`.

## Tests

```
.venv/bin/pytest -q -p no:cacheprovider tests/contract/test_docs_completeness.py
48 passed in 8.96s
```

All four relative links in the file still resolve.
