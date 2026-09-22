# Task 7a report — live evidence for the two demo tasks and both `draft_hr_email` endings

All four turns were driven against `https://mosaic-hr-copilot.onrender.com` on **2026-09-22 between
12:38:03Z and 12:42:11Z**. Nothing in `src/`, `mcp/`, `Dockerfile`, `render.yaml` or
`requirements.txt` was touched; the commit is three new transcripts plus two documentation edits.

## The build the evidence was taken on

* `/health` `git_sha` = **878217797ea19573e57f259350e4bf54d9df23fa** (`8782177`) —
  *"G5(eval): the published run on the final build …"*, a docs-only commit.
* `git diff 8a89310..8782177 -- src mcp Dockerfile render.yaml requirements.txt` → **empty**, and so
  is `git diff 8a89310..HEAD` over the same paths. `8782177` is an ancestor of `HEAD`. So the live
  service is the **app build `8a89310`**, the build that carries task 1c's fixes.
* Warm-up: the instance was already up (uptime 34 min) but had served no turn, so `/health` reported
  `cold_start: true` before demo task 1 and `cold_start: false` after it. Demo task 1 is therefore the
  first turn of the instance's life; the other three ran warm. Both figures are stated in the headers.
* `index.doc_count 14`, `chunk_count 204`, `mcp.tool_count 9`, `degradations []`.

## `docs/evidence/demo-task-1-live-2026-09-22.txt`

`BASE_URL=… APP_ACCESS_TOKEN=<redacted> sh scripts/demo_task_1.sh`, server-dated prompt
*"I want to work from Berlin from 3 November to 14 December 2026 — can I?"*, **38.2 s**, `exit=0`.

* `outcome: answered`; `check_policy_compliance` verdict **`conditional`**.
* Tool sequence: `lookup_employee_profile` → `search_policy_documents` (×6 across the turn) →
  `get_policy_section` → `check_policy_compliance`; **39 spans**, 9 model calls, 9 tool calls,
  7 retrievals, 86,587→3,195 tokens.
* **8 citations across 4 documents**: `remote-and-hybrid-work` (×3), `tax-and-location-addendum` (×3),
  `manager-approval-matrix`, `security-acceptable-use`. The fourth document differs from the
  2026-09-15 run (`travel-policy` then), which is the documented non-determinism in breadth.
* Guardrails: G4 ×3 allow, G1 allow (score 0.79-class pass), G2 allow, G3 allow, G6 allow; one
  `repair` model call before the second G2/G3 pair.
* Dashboard: `/dashboard/sessions/6e665d2134de3e8015481e09ba86d60f#turn-1`.

## `docs/evidence/demo-task-2-live-2026-09-22.txt`

`… sh scripts/demo_task_2.sh`, server-dated prompt for **6–8 October 2026**, **34.9 s**, `exit=0`.

* `POST /chat` ends `awaiting_confirmation` with the card (`create_mock_hr_ticket`, queue
  `hr-timeoff`, no token in the body); `POST /chat/confirm` performs the write.
* **`MOCK-HR-000019`**, named in the answer's opening `performed` block. Both of the script's own
  assertions passed: *"the confirmed write is reported as done … in the lede 'performed' block"* and
  *"no next step asks for it again (2 step(s) kept)"*.
* **3 citations across 2 documents**: `pto-and-holidays` (Notice Requirements, Approval Chain) and
  `manager-approval-matrix` (Time Off). **36 spans**, 8 model calls, 8 tool calls, 3 retrievals.
* Dashboard: `/dashboard/sessions/61be2fd9e86e076b4a0a62acd324cb87#turn-1`.

**The spoken lede, exactly as served** (from `GET /api/traces/sessions/61be2fd9…`, because the script
prints it with its own "Done — " stripped):

> Done — your request is with the HR Time Off team. Reference MOCK-HR-000019. Your manager Dana's
> written approval is the next step.

`docs/demo-script.md` quoted *"Your manager's written approval …"*, which is `outcome.py`'s
`NEXT_EVENT` string **before** `agent/approvers.py` fills the bare role with the persona's own
manager name. The live text is the one now in the script. This is behaviour, not a defect — but it
means the string a reader greps for in `outcome.py` is not the string on screen.

## `docs/evidence/draft-hr-email-live-2026-09-22.txt`

No committed script covers this tool, so both turns were driven by a throwaway `urllib` driver that
prints in `demo_task_2.sh`'s format and echoes every request (method, path, body) above its output;
the transcript carries the equivalent two `curl` commands in its header. The prompt is task 4's,
unchanged; **`draft_hr_email` was proposed on the first try both times** — no rewording was needed.

**① Confirmed** — `POST /chat` 200 `awaiting_confirmation`, card `action: draft_hr_email`,
`recipient_role: manager`, `to_name: Dana Whitfield`, no token in the body. `POST /chat/confirm`
`{"decision":"confirmed"}` → 200, **`outcome: answered`**, **20 spans**, 4 model calls, 4 tool calls,
0 retrievals, **8.5 s**. Blocks, in order: `performed` then `record`. The lede:

> Done — the email draft is ready for Dana Whitfield. Reference MOCK-EMAIL-000020.

The `draft_hr_email · ok` span returns `{"status": "drafted", "draft_id": "MOCK-EMAIL-000020", …}`,
and the G1 span reads **`verdict=allow · the write this turn performed is the evidence for the
answer: no policy evidence was retrieved for this question`** — task 1c's `grounded_by_write`
exemption, live, with the measured clause preserved. **0 citations from 0 documents** (the turn
retrieves nothing), and G2 records `0 of 0 citation links resolved`.
Dashboard: `/dashboard/sessions/9e05a2148db78f783f5c2d38ae9ee058#turn-1`.

**② Cancelled** — same ask, `POST /chat/confirm` `{"decision":"declined"}` → 200, **15 spans**,
3 model calls, 3 tool calls, **5.5 s**. The `confirmation` span is `draft_hr_email · declined`, there
is **no** `draft_hr_email · ok` span, and the whole answer is one `notice` block:

> Cancelled — nothing was created. Ask again whenever you would like me to open it.

…followed by the redirect next steps. No `USER_REFUSAL` text anywhere — fix round 1's receipt,
live. Dashboard: `/dashboard/sessions/11b25c0746c6ca6074542bc2d2e6ce54#turn-1`.

**Ledger check, in the transcript.** `GET /api/traces/tools` immediately after both turns:
`{"tool_name": "draft_hr_email", "calls": 5, "confirmation_pauses": 3, "errors": 0, "p50_ms": 8.0}`.
Task 4 recorded `calls 2, confirmation_pauses 1`; the three new calls are ①'s pause + write and ②'s
pause alone, so exactly one `MOCK-EMAIL` id was allocated across the two turns.

## Documentation changed

* **`README.md`** — the *Pinned evidence* paragraph now leads with the three 2026-09-22 transcripts
  (sha `8782177` on app build `8a89310`, with the counts above quoted from the files), and keeps the
  2026-09-11 and 2026-09-12 runs as history. One knock-on: *"The fourth pinned transcript is the
  external MCP session"* became *"One more pinned transcript is …"*, because the ordinal no longer
  counts. Nothing else in README was touched.
* **`docs/demo-script.md`** — four reference updates and the lede: task 1's ④ now cites the
  2026-09-22 transcript (8 passages across four documents, `security-acceptable-use` in place of
  `travel-policy`); task 2's ④ cites the 2026-09-22 transcript (three passages across **two**
  documents) and keeps the 2026-09-15 single-document run as the contrast; ⑤'s quoted lede is the
  one served, with a clause naming `agent/approvers.py`; ⑤'s closing "one step survived" is now the
  two steps this run kept; and the optional `draft_hr_email` beat links the new transcript. The
  affected paragraphs were reflowed to the file's ~100-column wrap, so the diff is 32/29 rather than
  five single lines.

## Tests

```
.venv/bin/pytest -q -p no:cacheprovider tests/contract          -> 555 passed in 175.81s
.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_demo_prompts_are_dated.py -> 402 passed
```

No assertion in `tests/contract/test_docs_completeness.py` or `test_published_run_commands.py` names
a pinned-transcript filename: the only filename sets there are the three `*.png` figures
(`EXPECTED_SCREENSHOTS`, which globs `docs/evidence/*.png` only) and
`docs/evidence/mcp-external-session-2026-09-12.txt`. Adding three `.txt` files needed no test change.

## Things that did not behave as documented (reported, not fixed)

1. **The demo script's quoted write lede was wrong in a way that grepping `outcome.py` hides.** The
   served sentence is *"Your manager Dana's written approval is the next step."*; `NEXT_EVENT` in
   `src/hrmosaic/agent/outcome.py:111` is *"Your manager's written approval is the next step."*. The
   difference is `agent/approvers.py` filling the role with the persona's manager name after the
   statement is built. Fixed in the script's wording only.
2. **A cancelled write still closes `outcome: refused`** — task 1c's own concern 1, now with a live
   trace behind it: the answer says *"Cancelled — nothing was created"* while the record labels the
   turn `refused`, and the G1 span on that turn reads `verdict=refuse · no policy evidence was
   retrieved for this question` even though the copy served is the receipt, not the refusal. Anyone
   reading the dashboard sees a *Refused* turn whose answer is a cancellation. No code touched.
3. **The confirmed `draft_hr_email` turn cites nothing** (0 citations, `G2: 0 of 0`), which is correct
   for an ask that retrieves no policy but means the turn has no *Sources* strip on the chat page.
   Worth knowing before the optional demo beat is spoken.
4. **Task 1's citation breadth moved again** (10 passages/4 docs on 2026-09-15 → 8 passages/4 docs
   today, with `security-acceptable-use` replacing `travel-policy`). Expected non-determinism, and the
   script already says to read what is on screen; noted so nobody treats the new numbers as a pin.
5. **`create_mock_hr_ticket`'s live ticket ids are now at `MOCK-HR-000019`** and `draft_hr_email` at
   `MOCK-EMAIL-000020`, so any document quoting an older id as *"the live id"* is describing history.

## The commit

**`0c972dc`** on `main`, five files, +460/-33: the three transcripts, `README.md`, `docs/demo-script.md`.
`git add` was explicit; the seven other files dirty in the tree (`ai-tooling.md`, `deployed.md`,
`design-and-evaluation.md`, `docs/optimization-log.md`, `docs/requirements-traceability.md`,
`docs/evidence/grade-card-2026-09-21.md`, `docs/evidence/README.md`) belong to another agent and were
left alone. Nothing under `.superpowers/` is committed.

**One deviation from the brief, disclosed.** The brief asked for the trailer
`Co-Authored-By: Claude Fable 5.1`. This work was done by **Opus 5 (1M context)**, and the session's
standing attribution instruction names that model, so the commit carries
`Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. `ai-tooling.md`'s integrity
census counts commits by exactly this trailer, so a Fable line here would have been a false entry in
the disclosure. Say the word and it can be amended.
