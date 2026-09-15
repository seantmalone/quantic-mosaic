# UX re-audit — Mosaic HR Copilot redesign

**Date** 2026-09-15 · **Plan verified** `docs/superpowers/plans/2026-09-14-ux-remediation-plan.md`
(principles §1, target IA §2, wireframes §3, inventory §4)
**Owner decisions** `.superpowers/sdd/2026-09-08-implementation-roadmap/ux-decisions.md`
**Before** `docs/evidence/ux-audit-2026-09-14/` (mirrored at `scratchpad/uxaudit/`)
**After** `scratchpad/uxreaudit/` — 69 screen ids × 3 viewports, 207 DOM dumps, 207 `.overflow.json`,
996 files. Captured LOCAL with `LLM_PROVIDER=stub`. **No live LLM call was made.** Repo read-only;
nothing was edited or committed.

---

## Verdict

**FAIL the gate — ship-blocked, but a large net improvement.**

138 of the 155 inventory findings are verified fixed. 22 inventory items remain open. The redesign
passes **6 of the 15 principles** and meets **2 of the owner's 3 goals**. It is blocked by **6
confirmed Critical residuals (4 unique defects)**, of which **3 are regressions introduced by the
remediation itself** — they did not exist in the before-capture.

The two structural wins are real and permanent: the rail is gone, the shell is one partial on every
surface, and the dashboard is now readable by any token-holder (the before-capture's employee
dashboard was a bare `{"code":"ADMIN_REQUIRED"}` body; the after-capture is the full Overview with
chrome). What blocks the gate is that the remediation broke three things it was not aiming at —
every chart on the dashboard, the truthfulness of a completed write in chat, and the survival of the
transcript when a reader follows the citation the plan itself made the most inviting link on the page.

---

## 1. Per-principle scorecard

Each principle is scored twice: against its own mechanical detection rule from plan §1 (run here),
and against the confirmed residuals that land on it. A principle passes only if both hold.

| # | Principle | Rule run here | Verdict |
|---|---|---|---|
| P1 | Human precision | `[0-9]+\.[0-9]{4,}` → **0** of 207 dumps; `\$[0-9]+\.[0-9]{3,}` → **0** | **FAIL** |
| P2 | No internal identifier in chat | 12 of 13 denylist patterns → **0 files**; `\bE1[0-9]{3}\b` → **15 chat dumps** | **FAIL** |
| P3 | One global nav on every page | `_masthead.html` included by chat, dashboard/_base, policy, policy_index, refused; `test_nav_parity.py` present | **PASS** |
| P4 | One gate, not two | before: `{"code":"ADMIN_REQUIRED"}`; after: full Overview for E1042. `test_dashboard_pages.py:133/152` | **PASS** |
| P5 | No link offered to a persona that cannot follow it | 52 dead trace links per eval-run page | **FAIL** |
| P6 | No dead-end error | 404s return the themed refused page with the nav to a browser Accept header | **PASS** |
| P7 | Nothing overflows | `body_horizontal_scroll` false on **207/207**; but 4 unaffordanced inner scrolls + the chart collapse | **FAIL** |
| P8 | Demo controls quarantined and labelled | `#actor-select`/`.demo-button` exist only in `_demo_controls.html` + its handler; `<h2>Demo &amp; grader controls</h2>` | **PASS** |
| P9 | Summaries agree with their detail | `\b[a-z]+\(s\)` → **0**; but 4 count/label disagreements | **FAIL** |
| P10 | One convention per concept | 8 confirmed convention collisions across chat/reader/dashboard | **FAIL** |
| P11 | The primary surface owns the page | `--measure: 40rem` (brand.css:112) on `.conversation`; `#chat-form position: sticky` (app.css:350); **no `aside`** in chat.html | **PASS** |
| P12 | Keyboard and screen-reader parity | 4 confirmed failures; the suite is parametrised over **3 routes** | **FAIL** |
| P13 | Plain language on every human surface | denylist clean in rendered chat/access copy; fails on meaning in chat and on vocabulary on the dashboard | **FAIL** |
| P14 | Honest statistics | 3 rates render bare where `n < 20`; 4 notations for one idea | **FAIL** |
| P15 | The record is relocated, never destroyed | `Export this page as JSON` on **29** dashboard screens, "Every figure above, unrounded, from the same endpoint" | **PASS** |

**6 pass / 9 fail.**

### P1 — Human precision · FAIL
The mechanical rule is green: zero 4-decimal numbers and zero 3-decimal money strings across all
207 dumps (before: the finding set that produced `numbers-precision-overflow` had 13 of 20 items on
exactly this). What fails is the principle's own clauses.
- **Critical, npo2-02.** `chat-answer__1440x900.txt` line 39: *"File the work-from-another-country
  request in MosaicOne by 13 September 2026 (21 days before 3 November)"*. 3 Nov 2026 − 21 days =
  **13 October**, not 13 September. The same block computes *"27 October 2026 (5 business days
  before departure)"* correctly, so the answer contradicts its own arithmetic and the advice is a
  month early. This is new: the before-capture had no `next_steps` in chat at all.
- **Minor, npo2-09.** *"45 months of continuous service"* — durations are still not in the largest
  sensible unit. The tool-side half shipped (`tenure` = "3 years 9 months", commit d8f180a); the
  stub script was never re-recorded, so the user-visible string is byte-identical to before.
- Open inventory: `numbers-precision-overflow-4, -13, -15`.

### P2 — No internal identifier in chat · FAIL
Twelve of the thirteen enumerated patterns return zero files across every chat state at every
viewport — `\bG[1-6]_`, `stub:stub`, `→ N tok`, `top dense`, `max dense`, `verdict=`, `purpose=`,
`intent=`, `catalog_reopened`, `chunk_id`, `c_[0-9a-f]{8}`, `{"`. That is a genuine, complete win
against the before-capture. The principle nevertheless fails on a token the regex never listed:
- **Important, cpux-re-4.** `grep -hoE '\bE1[0-9]{3}\b' chat-*.txt` → **15 hits of `E1007`**.
  *"Obtain written approval from your director (Dana, E1007)"* now reaches the reader, because
  `_turn.html:83` renders `turn.next_steps` for the first time. The plan deleted the "Employee ids
  look like E1042" hint from the clarification for precisely this reason.

### P3 — One global nav · PASS
One partial, five includes, parity test in the suite. **Minor, nav-reaudit-5:** `/policy/{doc}` and
the refused page call `shell_context(surface="chat")`, so the masthead paints `Chat` with
`aria-current="page"` while the reader is not in chat. Markup parity (the stated rule) holds; the
`aria-current` value is wrong on two routes.

### P4 — One gate, not two · PASS (clean)
The strongest single fix in the wave. Before: `docs/evidence/.../dashboard-403-employee__1440x900.txt`
is the literal 24-byte body `{"code":"ADMIN_REQUIRED"}`. After: the same screen id renders the full
Overview with masthead, grouped nav and KPI strip for persona E1042. Writes are still gated
(`ADMIN_ROUTES` = reset-sandbox, rediscover, eval runs; `test_dashboard_pages.py:152`). No residual.

### P5 — No link offered to a persona that cannot follow it · FAIL
- **Important, nav-reaudit-3.** `/dashboard/evals/{run}` renders 26 `href="/api/traces/turns/<32-hex>"`
  chips and 26 `a.trace-link` session pills — **52 links, all 404**, because eval runs are imported
  from committed fixtures whose turns were never in this deployment's store
  (`eval_detail.html:170,172-174`). `test_no_broken_links.py` crawls `/`, an answered turn,
  `/dashboard`, `/dashboard/sessions` and one session page — never an eval-run detail, which is why
  it shipped green.
- **Minor, nav-reaudit-4.** `Continue this conversation in chat` is unconditional on every session
  record (`session_detail.html:24`) but `/?session=` only rehydrates for the owner or an admin. It
  resolves 2xx, so the mechanical crawl passes while the promise breaks.

### P6 — No dead-end error · PASS
Verified as a side effect of nav-reaudit-3: the same 404 that yields `{"code":"UNKNOWN_TURN"}` to an
`Accept: */*` client returns the themed refused page carrying the global nav and `href="/"` to a
browser Accept header. `refused.html` includes `_masthead.html`.

### P7 — Nothing overflows · FAIL
`body_horizontal_scroll` is **false on all 207 screens** — the document-level half of the principle
is genuinely fixed, and `.table-scroll` now carries a thin persistent scrollbar plus self-cancelling
edge shadows (app.css:552–563), which is the affordance the rule demands. Four things still fail:
- **Critical, npo2-01 = dr-new-1 (regression).** Verified by pixel inspection of
  `shots/dashboard-safety__1440x900.full.png`: the "Verdicts by rule" plot box spans **x≈68→348**
  inside a panel spanning **x=20→1420**, one x-tick is drawn (`G1 Evidence gate`), rotated, clipped
  and overlapping the `Verdicts recorded` y-axis title; five of six bars are unlabelled. The
  before-capture of the identical chart is full panel width with legible gridlines and a legend at
  x≈640–800. Cause confirmed in the repo: all six canvases declare only `height=` and no width
  (`overview.html:109`, `safety.html:35`, `evals.html:103`, `eval_detail.html:202/207/212`), no chart
  sets `responsive`/`maintainAspectRatio`, and the only CSS is `canvas { max-width: 100% }`
  (app.css:880) + `.chart-figure { margin: 0 }` (app.css:884). The `<figure class="chart-figure">`
  wrapper arrived in c152ad4 (UX-W5 a11y). Light and dark captures agree, so it is not a race.
  **This inverts the W4 fix**: `dashboard-readability-17` added the axis titles and named all six
  rules, and none of it reaches the reader.
- **Important, cpux-re-6 (regression).** `#transcript` is now the page's scroll container
  (`scrollHeight 1417 / clientHeight 544`) with `overflow-y: auto` and **no affordance at all** —
  no scrollbar, no edge shade, no fade (app.css:215). The answer is clipped mid-glyph at the top
  edge. The dashboard got exactly this affordance in the same wave; the primary surface was skipped.
- **Important, cpux-re-7 (regression).** At 390×844 the composer's placeholder wraps to two lines in
  a one-line box (`textarea#message` 74/49) because `autogrow()` is bound to `input` and called in
  `htmx:afterSwap` but never on load (chat.html:186-189, 392).
- **Important, dgc-re-1.** `.demo-panel { max-height: 45vh; overflow-y: auto }` (app.css:144) with
  the two-column relief applied only at `min-width: 48rem`, so at 390px the panel is exactly 380px
  and hides the deep link, the environment disclosure and the demo sign-out behind an unaffordanced
  inner scroll. The CSS comment at app.css:160-164 states the rule the block breaks.
- Open inventory: `numbers-precision-overflow-10` (`/dashboard/evals` still 1603/1359 at 1440, with
  `Partial match` and `Strict pass rate` off-screen), `-18` (span bars still paint 2–3px past their
  track, 48 instances).

### P8 — Demo controls quarantined and labelled · PASS
`#actor-select` and `.demo-button` exist only inside `_demo_controls.html` and the chat page's own
event handler; the deep link exists only there; `section.demo-panel` carries
`<h2>Demo &amp; grader controls</h2>` and *"For evaluation only — a real user never sees this
panel."* Two caveats that do not overturn the principle but do violate the owner's file:
- **Important, dgc-re-2.** The panel ships as a closed `<details>` at **every** viewport
  (`_demo_controls.html:35`, no `open`), so the persona picker is not visible on arrival. The owner
  decided *"the persona picker stays always visible inside the demo panel"*; §3.6 scoped the collapse
  to 390px only.
- **Minor, dgc-re-11.** The admin persona puts *"HR admin"* in the masthead identity chip and
  degrades the greeting to *"Hi there"* — a demo-only construct back in production chrome, in the
  slot `navigation-and-ia-20` emptied.
- Open inventory: `demo-and-grader-controls-1` (partial).

### P9 — Summaries agree with their detail · FAIL
No `(s)` plural form anywhere in 207 dumps — that half is clean. Four disagreements confirmed:
- **Important, npo2-03 = dr-new-2 (regression).** Overview Traffic tile reads **"5 / QUESTIONS
  ANSWERED"**. `/dashboard/turns` lists the five turns as `answered, clarify, refused, ..., error` —
  **two** were answered. The tile three places right reads **"20.0% / ERROR RATE / 1 of 5 turns"**,
  i.e. 5 is the denominator of *turns*. The before-capture labelled the same figure honestly as
  "9 / TURNS"; the rename created the defect (`overview.html:28-31`, `data-kpi="turns"`).
- **Important, JX-R7.** Demo panel: *"7 safety checks passed"* (api.py:921 counts guardrail **spans**
  with `verdict == allow`). Guardrails page one click away: *"The six safety checks…"*
  (dashboard.py:2708, hard-coded, counts **rules**). Two surfaces the plan built to agree, contradicting.
- **Important, dr-new-3.** The designed confirmation pause reads *"paused for confirmation / paused /
  CONFIRMATION_REQUIRED"* on `/dashboard/tools` and **"create_mock_hr_ticket failed"** with a red
  `flag-error` chip on the session waterfall (`session_detail.html:112-114`) — and the waterfall is
  the page the chat deep link lands on.
- **Minor, npo2-13.** The new note says *"All six checks are plotted… The same counts are in the
  table below"*; the table has **five** rules (G5 has no row).

### P10 — One convention per concept · FAIL
Eight confirmed collisions. The worst are on the two surfaces a citation crosses in one click:
- **Important, npo2-08 = JX-R6.** Chat carries the as-of date twice in two formats on one screen:
  *"…as of 2026-09-01…"* in the answer body and *"Based on employee data from 1 September 2026"* six
  lines below. The plan's fix was explicit — amend `synthesize.j2` to stop restating the in-body
  as-of — and `synthesize.j2:47` still says *"When a tool result carries an `as_of` date, state it in
  the answer."* Open inventory: `numbers-precision-overflow-12`, `jargon-and-exposure-25`.
- **Important, npo2-04 / dr-new-4 / JX-R13.** The 8-char id chip was applied to identifiers that are
  not opaque. Eval run ids are `r_<unix-epoch>…`, so all 15 rows collapse to six indistinguishable
  chips (`r_178916…` ×3, `r_178908…` ×3, `r_178905…` ×3, `r_178903…` ×3, `r_178906…` ×2). Document
  slugs become `benefits…`, `equipmen…`, `pto-and-…` — except `travel-policy`, which Jinja's
  `truncate` leeway spares, so the column looks broken rather than abbreviated
  (`_table.html:38`, `truncate(9, true, '…')`). Open inventory: `numbers-precision-overflow-17`.
- **Important, JX-R4.** `jargon-and-exposure-20` is half done: every **header** is renamed
  (`AUTH_MODE`→`SIGN-IN`, `TTFB`→`FIRST TOKEN`, `MAX DENSE`→`BEST MATCH`) and span-kind pills are
  humanised, but the **values** are raw enums — `Sign-in: cookie / bearer / open`,
  `awaiting_confirmation`, `hybrid_rrf`, `multi_doc`, and on the eval run page the Category filter
  offers `simple_policy, multi_doc, unsafe_action` three inches above a legend reading
  *"5 multi doc, 7 simple policy, 1 unsafe action"*.
- **Important, cpux-re-9 = JX-R12 = a11y-reaudit-5 = dr-new-9.** The new `/policy/{doc}` reader —
  the destination of every citation — reverts both conventions the same wave established: the raw
  `A > B` heading path (*"Work Arrangements > Onsite"*) where the chip above it reads
  *"Remote & Hybrid Work Policy · Eligibility"*, and a bare ISO date (*"effective 2026-01-01"*).
  Its contents list also repeats an entry.
- **Important, npo2-06.** The same quantity has two names one page apart: `BEST MATCH` in the
  Retrieval table, `top dense` in the span summary; `PASSAGES` in the table, `5 chunks` in the span.
  24× `5 chunks`, 24× `top dense`, 22× `passages` across the screen set. Open inventory:
  `numbers-precision-overflow-4`.
- Minors: `npo2-12` (Build sha 8 chars on the list, 12 on the detail), `JX-R10` (guardrail rules named
  four ways), `dr-new-10` (five hard-coded hex palettes, against app.css's own "a literal hex in this
  file is a bug").

### P11 — The primary surface owns the page · PASS
`--measure: 40rem` (brand.css:112, *"about 80 characters of Public Sans"*) applied to
`.conversation` (app.css:212) and centred; `#chat-form` is `position: sticky; bottom: 0`
(app.css:350); **no `aside` element anywhere in `chat.html`** — the 22rem "Live agent activity" rail
is gone. This is the plan's headline layout change and it landed intact.
**Minor, nav-reaudit-7:** the sticky chrome leaves `#transcript` 392px of an 844px phone viewport (46%).

### P12 — Keyboard and screen-reader parity · FAIL
Announcements are correct — measured on a real turn, exactly two live-region writes
(`"Looking up your employee record…"`, `"Answer ready."`), once per turn, no denylist token. Four
failures, all of them things the remediation added:
- **Important, a11y-reaudit-1.** The 44px rule is a hand-written selector allow-list in one
  `@media (max-width: 40rem)` block (app.css:384-411) and omits every control the redesign added.
  At 390×844 with an answer on screen, **14 of 24** hittable controls are under 44px (six source
  `<summary>` at 302×21, six `Open the full policy` at 127×16, `Copy answer` 96×21, the demo deep
  link 260×16). `/policy`: 14 of 17. `/dashboard/sessions/{id}`: 32 of 56.
- **Important, a11y-reaudit-2 (regression).** `_table.html:71` —
  `<div class="table-scroll" tabindex="0" role="region" aria-label="{{ id }}">`. **19 of 21** tables
  announce themselves to a screen reader as a kebab-case DOM slug: `latest-sessions`,
  `by-model-table`, `zero-evidence`, `mock-writes-table`. The pre-W4 macro was a bare
  `<div class="table-scroll">` with no role and no label, so this defect is new. 14 of the 21 are
  also a landmark and a tab stop over a box with nothing to scroll.
- **Important, a11y-reaudit-3.** `accessibility-and-responsive-18` was fixed on session detail and
  reintroduced by the shared macro (`_table.html:85`, `{{ column.get('detail_label', column.label) }}
  in full` — named after the *column*, not the row): **"Scores in full" ×28 + "Verdicts in full" ×28
  on one eval-run page**, "Arguments in full" ×14 on Tools. The pile is bigger than the one the plan
  recorded. Open inventory: `accessibility-and-responsive-18`.
- **Important, a11y-reaudit-4.** `navigation-and-ia-13`'s own fix landed (eleven page names in one
  59px scrollable row), but nav-7 moved the masthead *inside* the sticky container and it wraps to
  three rows at 390px, so total pinned chrome is **224px = 27%** of the viewport — larger than the
  163px the plan measured as the defect. Open inventory: `navigation-and-ia-13`.
- **Root cause, and the reason all of the above shipped green:** `tests/ux/test_accessibility.py:33`
  — `CHAT_AND_DASHBOARD = ("/", "/dashboard", "/dashboard/evals")`. Every 44px, contrast, type-floor,
  control-name and focus-indicator test is parametrised over those three routes, which return zero
  small controls. P12's own detection rule *"no two disclosure controls share an accessible name on
  a page"* **has no test at all** (`grep` for a duplicate-name assertion → none).
- Minors: `nav-reaudit-9` (six links per answer whose entire accessible name is "Open the full
  policy"), `a11y-reaudit-6` (nav groups are sibling `<span>`s, invisible to AT),
  `a11y-reaudit-7` (one polite `role=status` carries crashes and refusals; the plan asked for a
  second assertive announcer), `a11y-reaudit-9` (the skip link is 37px and is explicitly excluded
  from the guard by the guard itself, `test_accessibility.py:87`), `dr-new-6` (21 header definitions
  delivered as bare `title=` on a non-focusable span — the exact anti-pattern
  `accessibility-and-responsive-7` condemned, reinstated 21 times).

### P13 — Plain language on every human surface · FAIL
The denylist over rendered chat and access copy is clean; the only hits in `access.html`,
`chat.html` and `_turn.html` are inside Jinja comments and JS (`{#…#}`, `<span>` markup,
a `/health` preflight comment) — none reach the reader. The failures are of meaning in chat and of
vocabulary on the dashboard:
- **Critical, JX-R1 = cpux-re-1 (regression).** A completed, irreversible write is rendered as
  non-binding advice. `chat-after-confirm__1440x900.txt` lines 29-36, verified verbatim:
  ```
  What I suggest you do
  Done — your request is with HR. Reference MOCK-HR-000001.
  …
  That is already taken care of — there is nothing further for you to file.
  …
  Suggestions are guidance, not company policy.
  ```
  The amber *"Recommendation — not company policy"* badge W2 deleted has been replaced by a heading
  plus a footnote saying the same wrong thing, and the self-contradiction §3.4 set out to kill is
  two bullets below the completion. Cause: `outcome.py:263/304` injects the write as
  `{"type": "recommendation"}`; `_turn.html:74-89` hoists every `recommendation` out of document
  order into one `<ul>` under `block_headings.recommendation` with `suggestion_footnote`.
  `outcome.py:119` still documents `statement` as *"The block that opens the answer"* — it no longer
  does. Plan §3.4 requires *"One statement"* and *"no contradicting 'The ticket already exists…'
  block"*. Open inventory: `chat-production-ux-11`.
- **Important, cpux-re-8 = JX-R8.** The refusal's recovery path names the wrong topics:
  *"I can help with things like Benefits and Open Enrollment Guide, Equipment & Asset Policy,
  Expenses & Reimbursement Policy, HR Escalation & Case Handling Policy and Leave of Absence
  Policy."* `g1.py:153-156` takes `list(coverage())[:5]` over a query ordered `BY doc_id`, so the
  slice is alphabetical and **structurally excludes PTO, Remote Work, Travel and Tax** — every topic
  the product is demonstrated on and the four §3.5 names. A reader who has just been refused is
  redirected to equipment and expenses.
- **Important, JX-R2 (regression).** The provider banner added for `dashboard-readability-14` prints
  the raw enum and an internal spec ordinal on the dashboard's first screen: *"Answers come from
  **stub**. Every cost figure is an estimate from the per-call token counts and the committed price
  table **(§9.8)**…"* (`overview.html:96,99`; same ordinal at `llm.html:31`). `stub` is the token W2
  spent a wave removing from chat, and chat names the same fact correctly as *"recorded script — no
  live model call"*.
- **Important, JX-R5.** Three of the five things `jargon-and-exposure-23` names survive: the Tool
  server page publishes `http://127.0.0.1:59074/mcp-server/mcp` as a labelled field; Guardrails ›
  Simulated writes prints the raw body clipped mid-token
  (`{"employee_id": "E1042", "queue": "hr-timeoff", "summary": …`); Tools renders
  `parameters={"start_date": …` and `verdict=conditional`.
- **Important, JX-R3.** The policy reader publishes the corpus markdown verbatim inside one `<p>`
  (`policy.html:41`) — `*people*`, and the database field name `work_arrangement` in backticks —
  to employees.
- Minors: `JX-R11` (Health tile `TRACE STORE` / `sqlite` — the one surviving instance of a word
  `jargon-and-exposure-24` removed from all 207 dumps), `JX-R14` (`CONFIRMATION_REQUIRED` under a
  column headed ERROR CODE on a row whose OUTCOME says `paused`), `dgc-re-7` (`(§9.8)`),
  `JX-R9` (persona options lead with the employee id, against §2/§3.7's "name only").
- Open inventory: `jargon-and-exposure-13, -20, -23, -24, -25`.

### P14 — Honest statistics · FAIL
- **Important, npo2-05.** Four notations for one idea now coexist, and three rates carry no
  denominator while their row-mates do. On one row of `/dashboard/evals/{run}`:
  `OVER-REFUSAL RATE 0.0% (0 of 18 items)` and `MISSED-REFUSAL RATE 0.0% (0 of 6 items)` beside
  `ACTION-SAFETY PASS RATE 100.0%` (computed over a single `unsafe_action` item) and
  `TOOL CATALOG REOPENED 0.0%` — both bare. P14 requires " of " in the cell whenever the count is
  under 20. Elsewhere the same idea is `0.0% (0 of 8 calls)`, `n=2`, and `1 of 5 turns`.
- **Minor, dr-new-8.** `Workflow completion` renders `pto request 0.0%` / `remote work eligibility
  0.0%` with no `n` at all (`eval_detail.html:126`, `{{ value|pct }}`).

### P15 — The record is relocated, never destroyed · PASS
`Export this page as JSON` on **29** dashboard screens, each with the line *"Every figure above,
unrounded, from the same endpoint the page is rendered from."* Every value removed from chat (scores,
token counts, span kinds, chunk ids, ms timings, guardrail codes) is present on the dashboard and in
`/api/*`. Two caveats: the plan's stated detection rule — a byte-identical `/api/*` snapshot test per
wave — does not exist in `tests/`; and three values moved in the **wrong** direction (`next_steps`,
`E1007`, model-computed deadlines now render in chat), which is the inverse of the principle rather
than a violation of it.

---

## 2. Owner goals

### (a) Production-grade chat — **NOT MET**
Everything structural landed. The rail is gone (no `aside` in `chat.html`), the measure is 40rem,
the composer is sticky, Enter sends, focus returns, the newest message is in view, the badges are
gone from non-answer turns, progress is one calm human sentence measured at exactly two live-region
writes per turn, and the P2 denylist is clean on twelve of thirteen patterns. Against that, chat
carries **four of the six Critical residuals**, and each is a thing a real user would notice before
a grader would:

1. A completed HR ticket is filed under *"What I suggest you do"* and disclaimed as *"guidance, not
   company policy"*, with a contradiction two bullets below it (JX-R1 / cpux-re-1).
2. The answer tells the reader to file a request by **13 September** that its own parenthetical
   computes as 21 days before 3 November — a month early (npo2-02).
3. Following the citation the plan made the most inviting link in an answer destroys the
   conversation: chat never writes `?session=` into its own URL (`url_after_turn = "/"`, no
   `replaceState` anywhere in `templates/`), the reader's only outbound links are `Chat` and
   `Dashboard`, and Back lands on an un-rehydrated `/` with 0 turns (nav-reaudit-1).
4. The transcript scrolls with no affordance and the answer is clipped mid-glyph (cpux-re-6); on a
   phone the composer placeholder is clipped on first load (cpux-re-7).

Plus: an internal employee id in the answer body, `Copy answer` offered over a crash, a refusal that
redirects to equipment and expenses, two date formats for one fact, and seven suggestion bullets
where §3.3 wireframes two. **Not production-grade. It is, however, a different order of product
than the before-capture** — the failures are now about truthfulness and polish rather than about
exposure.

### (b) Demo controls quarantined and labelled — **MET**
`section.demo-panel` is the sole home of `#actor-select`, `.demo-button` and the grader deep link;
its `<summary>` carries both the `<h2>Demo &amp; grader controls</h2>` and the disclaimer *"For
evaluation only — a real user never sees this panel."* P8 holds. Three caveats, none of which
un-quarantine anything:
- It ships **collapsed at every viewport**, against the owner's explicit decision that the persona
  picker stays always visible (dgc-re-2, Important).
- At 390px a 45vh cap hides the deep link, the environment disclosure and the demo sign-out behind
  an invisible inner scroll (dgc-re-1, Important); the two buttons print the full verbatim prompt
  sentence instead of the short labels §3.7 specifies, which is what fills the panel (dgc-re-3).
- `HR admin` still reaches the production masthead chip when that persona is selected (dgc-re-11).

### (c) All technical detail in the dashboard, with a deep link — **MET**
The relocation is real and the round trip now exists in both directions:
`_demo_controls.html:84` → `/dashboard/sessions/{id}#turn-{seq}`, and `session_detail.html:24` →
`/?session={id}`, with rehydration verified (`GET /?session=<id>` replays 1 turn;
`test_conversation_reload.py` passes). Every removed value is recoverable — 29 `Export JSON` links,
the span waterfall, `/api/*`. Caveats:
- The dashboard's own legibility **regressed**: every chart is ~300px in a ~1380px panel, so the
  detail that was relocated there is now less readable than it was (npo2-01 / dr-new-1, Critical).
- Some technical detail travelled back the wrong way into chat (`next_steps`, `E1007`, ISO as-of).
- The deep link's sibling path — citation → reader → back — is broken (nav-reaudit-1), and the
  reader's own deep link lands behind the sticky masthead on a phone (nav-reaudit-2).

---

## 3. Still-open plan items (22)

| Lens | Fixed | Still open |
|---|---|---|
| numbers-precision-overflow | 13 | **-4** (G1 "best evidence score" lower than the maxima above it; two names per field), **-10** (`/dashboard/evals` 1603/1359, Strict pass rate off-screen), **-12** (two date formats in chat), **-13** ("45 months"; stub script not re-recorded), **-15** (G2 "8/8 citations" vs "Sources (6)"), **-17** (run-id chips collapse; Build sha 8 vs 12), **-18** (span bars 2–3px past their track, 48 instances) |
| jargon-and-exposure | 18 | **-13** (fixed in `narration.py`, unverified on screen — both in-flight captures raced; `WORKING = "Working…"` survives as the unmapped-kind fallback), **-20** (labels renamed, values still raw enums), **-23** (localhost URL, raw JSON body, `verdict=`), **-24** (residual: `TRACE STORE` / `sqlite`), **-25** (`synthesize.j2:47` still instructs the model to state the as-of) |
| navigation-and-ia | 20 | **-16** (the dashboard→chat half is done and tested; the chat-surface half is not — chat never writes the session into its URL), **-13** (the nav row is fixed; total pinned chrome grew to 224px) |
| chat-production-ux | 26 | **-11** (answer still argues with itself; queue's human name lost), **-29** (the §3.8 autofocus half; the a11y-12 half is fully fixed) |
| demo-and-grader-controls | 16 | **-1** (partial: the panel exists and holds all five controls, but ships collapsed and clips on mobile) |
| dashboard-readability | 27 | **-5** (`session_detail.html` declares zero `help` and is both the densest jargon surface and the deep-link target; `_filters.html` has no help slot), **-9** (the axis landed; the 7th-column chevron did not — 31 spans still emit 62 rows and the page grew 2,922→3,220px), **-10** (not started: no dashboard table is sortable; `Filters` has no sort field; zero `sort` occurrences in any dashboard template), **-17** (written but not delivered — illegible at the shipped chart size) |
| accessibility-and-responsive | 18 | **-18** (fixed on session detail, reintroduced by the shared table macro) |
| — | — | **P12's own detection rule has no test**, and the a11y suite is parametrised over 3 routes |

**138 verified fixed, 22 open** (of 155 inventory findings; per-lens "fixed" counts overlap slightly).

---

## 4. Confirmed residuals

**39 confirmed serious findings (6 Critical, 33 Important) = 34 unique defects after de-duplicating
cross-lens rediscoveries; 49 Minor.** Ten of the 34 are **regressions** — defects that do not exist
in the before-capture and were introduced by the remediation.

### Critical (4 unique / 6 reported)

| id(s) | Defect | Regression? | Fix |
|---|---|---|---|
| **npo2-01 = dr-new-1** | Every dashboard canvas renders ~300px in a ~1380px panel; on Guardrails only 1 of 6 rule labels is drawn, rotated and overlapping the axis title — the exact inverse of the W4 fix | **Yes** (c152ad4) | `.chart-figure { position: relative; width: 100%; height: 16rem }` + `.chart-figure canvas { width:100%!important; height:100%!important }` + `maintainAspectRatio: false` per chart; on Guardrails `ticks.autoSkip:false, maxRotation:0` with wrapped two-line labels. Re-capture overview + safety at all three viewports and confirm six rule names print horizontally |
| **JX-R1 = cpux-re-1** | The completed, irreversible write is filed under "What I suggest you do" and disclaimed "guidance, not company policy", with a contradicting pointer two bullets below | **Yes** (the badge W2 deleted, restored as a heading + footnote) | Give the performed write its own block type (`performed`/`performed_write`) at `outcome.py:263/304` and render it in `_turn.html` as the turn's lead statement above the fact blocks, outside the suggestions `<ul>` and outside the footnote. Type or drop `pointer` when `statement` already ran on the same turn |
| **npo2-02** | `next_steps` is now rendered and carries an arithmetic error the reader is told to act on: "by 13 September 2026 (21 days before 3 November)" — 3 Nov − 21 d = 13 Oct | **Yes** (`next_steps` was previously generated and dropped by the web layer) | Fix the date at source (`tests/fixtures/llm_scripts/demo_task_1.json`) or stop rendering model-computed deadlines in chat; route any surviving date through `human_date()`. A wrong date in an HR answer is worse than no date |
| **nav-reaudit-1** | Following a citation destroys the conversation: chat never writes `?session=` into its URL, the reader offers no route back, Back lands on `/` with 0 turns. 6 citations per answer — the most-travelled path in the product | Partly (the reader route is new) | `history.replaceState` to `/?session=<id>` after the first turn; add a `Back to the conversation` action on the reader (or `target="_blank" rel="noopener"` on citations). Extend `test_no_broken_links.py` with answer → citation → back → transcript-still-rendered |

### Important — the 30 unique defects

**Regressions (7):** npo2-03/dr-new-2 (tile counts turns, labelled "questions answered"),
JX-R2 (raw `stub` + `(§9.8)` on the dashboard's first screen), cpux-re-5 (`Copy answer` on every
outcome, `_turn.html:44`, no gate), cpux-re-6 (transcript scrolls with no affordance),
cpux-re-7 (composer clipped on load), a11y-reaudit-2 (19 tables announce a DOM slug), cpux-re-3/JX-R15
(`recommendation` + `next_steps` merged into one 7-bullet list where §3.3 wireframes two).

**Partially-fixed plan items (8):** npo2-04/dr-new-4/JX-R13 (id chip over-applied),
npo2-06 (best-evidence label + two names per field), npo2-07 (evals table still overflows),
npo2-08/JX-R6 (two date formats), JX-R4 (enum values unmapped), JX-R5 (localhost URL, raw JSON),
cpux-re-2 (answer argues with itself; queue name lost), a11y-reaudit-3 (56 duplicate disclosure names).

**New surfaces, old defects (5):** JX-R3 (reader publishes raw markdown + `work_arrangement` + ISO
date), cpux-re-9/JX-R12/a11y-reaudit-5/dr-new-9 (reader reverts the `>` and ISO conventions;
duplicate contents entries), nav-reaudit-2 (reader deep link lands behind a 165px sticky masthead at
390px; hard-coded `scroll-margin-top: 5.5rem` where the dashboard correctly measures `--dash-nav-h`),
nav-reaudit-3 (52 dead trace links per eval-run page), a11y-reaudit-1 (44px allow-list misses every
new control; 14 of 24 on chat with an answer, 14 of 17 on `/policy`).

**Cross-surface disagreements (4):** JX-R7 (7 spans vs six rules), dr-new-3 (`CONFIRMATION_REQUIRED`
= "failed" on the waterfall, "paused" on Tools), npo2-05 (four denominator notations; three bare
rates), npo2-03 (tile vs its own neighbour).

**Mobile / density (4):** dgc-re-1 (demo panel clipped at 45vh), dgc-re-2 (panel collapsed, against
the owner's decision), dr-new-5 (card stacking makes phone pages 3–5×  longer: Model calls
1,871→9,766px, Evaluations 2,339→10,707px), a11y-reaudit-4 (224px = 27% pinned chrome).

**Process (2):** cpux-re-10 (both in-flight captures raced to the finished turn — `chat-inflight.txt`
is byte-identical to `chat-answer.txt`, `chat-confirm-inflight.txt` to `chat-confirm-card.txt`, at
all three viewports, verified here with `cmp`; `scripts/ux_capture.py:407` calls `time.sleep()` in a
**sync** Playwright route handler, blocking the dispatcher, so §3.2 has no screen evidence and no
regression guard — a re-capture driven directly confirms the in-flight state is actually correct),
cpux-re-8/JX-R8 (refusal redirects to alphabetically-first documents).

### Minor (49)
Full list retained in the finding set. The recurring shapes: the `·` vs `>` heading-path split across
four surfaces; `stub` / `recorded script` / `recorded-script run` for one fact; ids leading persona
options and chunk headers; the demo panel's produced-line missing the duration and session id §3.7
draws; five hard-coded chart palettes against app.css's own no-literal-hex rule; `(§9.8)` on two
pages; the inert wordmark; `Mosaic HR Copilot — access key` as the one title that kept the old shape.

---

## 5. What to fix before the next gate

Ordered by reader harm per unit of work.

1. **`.chart-figure` sizing + `maintainAspectRatio: false`** — one CSS rule and six one-line config
   changes. Restores every chart and, with it, the whole of `dashboard-readability-17`.
2. **Give the performed write its own block type** — `outcome.py` + `_turn.html`. Removes the
   Critical, closes `chat-production-ux-11`, and kills the contradiction and the wrong disclaimer in
   one edit.
3. **`history.replaceState('/?session=<id>')` after the first turn** — three lines in `chat.html`.
   Makes Back, reload and the masthead `Chat` link all rehydrate, closes the second half of
   `navigation-and-ia-16`, and fixes the demo panel's persona-reload data loss (dgc-re-10) for free.
4. **Stop merging `next_steps` into the `labelled` branch**, and fix the 13 September date at source.
   Removes a Critical, the seven-bullet list, and `E1007` from chat together.
5. **Relabel the Overview tile** (or count `outcome == 'answered'`), with a denominator sub-line.
6. **Widen the test surface** — this is what let eight of the ten regressions ship green:
   `CHAT_AND_DASHBOARD` must include a chat page **with a turn in it**, `/policy`, `/policy/{doc}`,
   `/dashboard/tools`, `/dashboard/sessions/{id}` and `/dashboard/evals/{run}`; add P12's
   duplicate-accessible-name assertion; widen `test_no_broken_links.py` to every `/dashboard/*`
   including an eval-run detail; assert `#stop-button` is visible before the in-flight screenshot so
   a mis-capture fails the run instead of producing a duplicate.

---

## 6. Method and evidence

- After-set captured with the repo's own harness (`make ux-capture` → `scripts/ux_capture.py`),
  LOCAL, `LLM_PROVIDER=stub`, four scripted servers sharing one `TRACE_DB_PATH`.
  **No live LLM call was made and `.env` was never read.**
- Mechanical rules re-run here over all 207 DOM dumps and 207 `.overflow.json`: P1 (two regexes),
  P2 (thirteen patterns + `E\d{4}`), P7 (`body_horizontal_scroll`), P9 (`(s)` plurals).
- Chart regression verified by pixel inspection of the after and before `.full.png` at 1440×900, not
  from the DOM dump — the defect is invisible in text.
- P4 and P6 verified by diffing the `dashboard-403-employee` screen before (a 24-byte JSON body)
  against after (the full Overview with chrome).
- In-flight duplication verified with `cmp` on the `.txt` dumps at all three viewports.
- Source claims verified against the working tree at `/Users/sean/Projects/quantic-mosaic`
  (read-only): `app.css`, `_table.html`, `_turn.html`, `_demo_controls.html`, `session_detail.html`,
  `eval_detail.html`, `overview.html`, `safety.html`, `access.html`, `policy.html`,
  `tests/ux/test_accessibility.py`, `tests/contract/`.
