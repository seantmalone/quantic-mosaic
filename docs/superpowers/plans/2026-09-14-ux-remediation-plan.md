# Mosaic HR Copilot — UX remediation plan

**Scope.** Everything the owner called "clunky and messy", generalised into classes of defect,
turned into a target information architecture, a page-by-page target design, a complete issue
inventory (155 findings: 124 verified serious + 31 minor), and five ordered fix waves with files,
tests, effort and risk.

**Source of truth.** `/private/tmp/claude-501/-Users-sean-Projects-quantic-mosaic/44fed378-5d63-4daa-b66b-91107d8f0a3a/scratchpad/uxaudit/index.json`
— 53 screen ids x 3 viewports (1440x900, 1280x800, 390x844), captured LOCAL with
`LLM_PROVIDER=stub` (no live model call), each with `.full.png`, `.fold.png`, `.txt` DOM dump,
`.overflow.json` and `.numbers.json`.

**Stack.** FastAPI + Jinja2 + htmx (vendored) + vendored Alpine, one hand-written `app.css`, no
build step. **Nothing in this plan requires changing that.** Every fix is a template edit, a CSS
rule, a Jinja filter, an inline `<script>` in the page that already has one, or a small change to a
Python view-model/route. The one place a dependency is added is *tests only*: the Playwright venv
at `/private/tmp/claude-501/-Users-sean-Projects-quantic-mosaic/44fed378-5d63-4daa-b66b-91107d8f0a3a/scratchpad/pwvenv/bin/python`
already exists and is used for the screenshot/geometry regression suite; if that suite is to live
in the repo it needs a `dev` extra (`playwright`) in `pyproject.toml`. The pytest-only checks
(number precision, jargon denylist, nav parity, link resolution) need no new dependency at all.

---

## 1. Principles — the classes of issue, each with a detection rule

Each principle is written so it can be mechanically checked. The check is the acceptance criterion
for the wave that fixes it.

| # | Principle | Detection rule (mechanical) |
|---|---|---|
| **P1** | **Human precision.** No number on a human surface carries more significant digits than its purpose supports: rates/scores ≤ 3 s.f. (or 1 dp as a percentage), money 2 dp, durations in the largest sensible unit, counts with thousands separators. | Over every rendered `.txt` DOM dump: `\d+\.\d{4,}` → 0 matches on chat, 0 on dashboard; `\$\d+\.\d{3,}` → 0 matches anywhere; every `*_rate`/`*_accuracy`/`*_mean` cell matches one single format across all pages. |
| **P2** | **No internal identifier in chat.** No span kind, guardrail id, provider:model, token arithmetic, similarity score, snake_case field name, chunk id, epoch, git sha, raw JSON, or ms timing appears in any chat-surface template or in any user-facing agent string. | Denylist regex over the rendered chat HTML for every turn state: `\bG[1-6]_`, `stub:stub`, `→\s*\d+\s*tok`, `top dense`, `max dense score`, `verdict=`, `purpose=`, `intent=`, `catalog_reopened`, `chunk_id`, `c_[0-9a-f]{8}`, `\bspan\b`, `\btrace\b`, `_[a-z]+_[a-z]+` (snake_case), `\{"` → 0 matches. |
| **P3** | **One global nav on every page.** Identical markup, identical position, on every authenticated route, independent of persona and of page. | The shared masthead partial renders byte-identical (modulo `aria-current`) on `/` and on all 13 `/dashboard/*` routes; `id="dashboard-link"` present as the default actor; `Sign out` present on both surfaces when the gate is on. |
| **P4** | **One gate, not two.** Anything the shared access token opens is reachable in one click. Roles gate *writes* only, never reads, never navigation. | GET every `/dashboard/*` and every read-only `/api/traces\|corpus\|mcp\|eval/*` with `mosaic_actor=E1042` → 200. POST `/api/dev/reset-sandbox`, `/api/mcp/rediscover`, `/api/eval/runs` → still 403 for a non-admin. |
| **P5** | **No link is offered to a persona that cannot follow it.** | Crawl every `href` rendered on `/` as the default actor; all resolve 2xx. |
| **P6** | **No dead-end error.** Every HTML navigation that fails returns a themed page carrying the global nav and a route back. A bare JSON body is never rendered to a browser. | Request `/dashboard`, `/dashboard/sessions/<id>`, `/api/traces/overview`, a rate-limited path with `Accept: text/html` → `content-type: text/html` and body contains `href="/"`. |
| **P7** | **Nothing overflows.** Content fits, wraps, or scrolls inside its own container *with a visible affordance*. The document itself never scrolls sideways. | `.overflow.json` at all three viewports: `body_horizontal_scroll` false on every screen; every element with `scrollWidth > clientWidth` is a `.table-scroll` (or `pre`) whose computed style shows a persistent scrollbar or edge shadow. |
| **P8** | **Demo controls are quarantined and labelled.** Persona switch, demo prompts and grader deep links live in one visually distinct section with a heading that says so. | No `#actor-select`, no `.demo-button`, no `/dashboard/...#turn-` link exists outside `section.demo-panel`; `section.demo-panel > h2` contains "Demo". |
| **P9** | **Summaries agree with their detail.** A count and the list it counts are computed from one source; the label names the unit it actually measures; plurals follow the count. | Contract test: `guardrail_hits` tile labelled "blocks" equals the count of non-allow verdicts, and a sibling "checks" figure equals the guardrail span count; no rendered `\(s\)` plural form anywhere. |
| **P10** | **One convention per concept.** One date format per audience, one rate unit, one duration helper, one name per field, one formatter path. | No bare `{{ value }}` for a numeric or temporal expression in any template — every one goes through a registered Jinja filter (`num`/`pct`/`rate`/`score`/`usd`/`ms`/`secs`/`ts`). Grep the templates for unfiltered numeric interpolations → 0. |
| **P11** | **The primary surface owns the page.** Chat uses the full width at a readable measure, the composer stays reachable, the newest message is visible, and no permanent column of technical output competes with it. | Computed: `.conversation` max-width 37–40rem and centred; `#chat-form` `position: sticky`; after 3 turns `document.documentElement.scrollHeight == window.innerHeight` and the send control is in the viewport; no `aside.rail` in the chat layout grid. |
| **P12** | **Keyboard and screen-reader parity.** Enter sends, focus is returned after every turn, the finished answer is announced once in plain language, every control has a distinct accessible name, text scales with the browser default. | Playwright: Enter submits; `document.activeElement` is `#message` after the swap; exactly one live-region text addition per turn and it contains no denylist token; no two disclosure controls share an accessible name on a page; `body` font-size declared in `rem`. |
| **P13** | **Plain language on every human surface.** No infrastructure, protocol or deployment vocabulary in chat copy, access copy, or agent-authored user text. | Denylist over `access.html`, `chat.html`, `_turn.html` and the user-facing strings in `g1.py`/`orchestrator.py`: `MCP`, `Bearer`, `cookie`, `tokenized`, `/health`, `/ready`, `audit trail`, `deployment`, `eval runner`, `span`, `trace`, `copilot` (third person) → 0. |
| **P14** | **Honest statistics.** A rate computed over fewer than 20 samples shows its denominator; a percentile over fewer than 5 samples shows `n=` instead of a number. | Contract test on `ToolRollup`/`OverviewKpis`: `sample_n` present, and the rendered cell for `calls < 20` contains " of ". |
| **P15** | **The technical record is never destroyed, only relocated.** Every value removed from chat must still exist, unrounded, in the dashboard and in `Export JSON`/`/api/*`. | The `/api/*` payload for each page is byte-identical before and after each wave (snapshot test on the JSON view-models). |

---

## 2. Target information architecture

Three surfaces, one shell.

### Shell (every authenticated page)
`templates/_masthead.html` — a single partial, included by `chat.html` and `dashboard/_base.html`:

```
[ Mosaic HR Copilot ]                         [ Chat | Dashboard ]  [ Priya Raghavan ]  [ Sign out ]
                                               ^ segmented, current marked aria-current="page"
```

No persona `<select>`. No "HR ADMIN" chip. No tagline in the pinned row. Identical markup on both
surfaces; the only difference is which half of the switch carries `is-current`.

### A. Chat — production UX
The whole page belongs to the conversation. Plain language only. Sources are friendly references,
not chunk ids. Progress is one calm human sentence. There is no rail, no trace panel, no token
counts, no scores, no badges on non-answer turns. Answers read as prose. The composer is sticky.
Enter sends. The newest message is always in view. Everything technical has moved to C, reachable
from B.

### B. Demo & grader panel — clearly labelled, visually separate
One `section.demo-panel` below the conversation (below the composer on mobile), dashed border,
muted ground, heading **"Demo & grader controls"** and the line *"These controls exist for
evaluation. A real user of this assistant never sees them."* It holds:
1. **Act as** — the 24-employee persona picker (moved out of the masthead), full-width, name only.
2. **Try a demo prompt** — the two scripted prompts, relabelled to the question with no "Demo N —"
   prefix, prefilling the composer rather than auto-submitting.
3. **Open this conversation in the dashboard** — the deep link, enabled once a turn exists,
   pointing at `/dashboard/sessions/{session_id}#turn-{seq}`.
4. **How this answer was produced** — a short human summary of the last turn (steps, sources
   checked, safety checks run, time taken), with the same deep link for the full record.
5. **Demo environment** — provider (`recorded script — no live model call`), employee data
   snapshot date, and the "writes are simulated" disclaimer, stated once here instead of inside
   answers.

### C. Dashboard — all technical detail, tidy and self-explaining
Reachable by **anyone holding the access token**; the admin role gates only the three write
endpoints. Every page: shared masthead (sticky), a secondary page nav (no ordinals, grouped, one
scrollable row on mobile), a page title with a one-line plain-English lede, a breadcrumb on detail
pages, `Export JSON` demoted to a footer link. Tables lead with the human column, ids are 8-char
chips, numbers are right-aligned and rounded, wide tables scroll with a visible affordance and
stack on mobile.

### Access (pre-auth, outside the shell)
Product name, one sentence, one autofocused field, one button. No Bearer/MCP/health copy.

---

## 3. Page-by-page target design (wireframe level)

Layout tokens: page max-width `none` (the shell uses the window), `.conversation` `max-width: 40rem;
margin-inline: auto` (≈ 606px measure ≈ 80 characters — today it is 802px ≈ 107 characters).
`.layout` becomes a single column: `grid-template-columns: minmax(0, 1fr)`.

### 3.1 Chat at rest — `chat-rest`, `chat-rest-admin`, `zoom-header-rest`, `zoom-composer-rest`

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Mosaic HR Copilot            [ Chat |Dashboard]  Priya Raghavan  Sign out │  ← shared masthead
├───────────────────────────────────────────────────────────────────────────┤
│                    ┌──────────────── 40rem ───────────────┐               │
│                    │  Hi Priya — ask me anything about HR │  ← h2         │
│                    │  I answer from Mosaic's policy       │               │
│                    │  documents and your own HR record,   │               │
│                    │  and I always show the policy I used.│               │
│                    │                                       │              │
│                    │ ( How much PTO do I have left? )      │  ← starter   │
│                    │ ( Can I work from another country? )  │    chips,    │
│                    │ ( How much notice for time off? )     │    not demo  │
│                    │ ( What does my benefits status cover?)│    buttons   │
│                    │                                       │              │
│                    │ ┌───────────────────────────────────┐ │              │
│                    │ │ Ask about policy, your PTO…       │ │ ← 1-row      │
│                    │ │                            [Send] │ │   autogrow,  │
│                    │ └───────────────────────────────────┘ │   sticky     │
│                    │  Enter to send · Shift+Enter new line │              │
│                    └───────────────────────────────────────┘              │
│                    ┌ ─ ─ ─ Demo & grader controls ─ ─ ─ ─ ┐ (see 3.7)     │
└───────────────────────────────────────────────────────────────────────────┘
```
Gone: "Act as" select from the masthead, "tools over MCP, and a full audit trail" tagline, the
22rem "Live agent activity" rail, "Demo 1 — …"/"Demo 2 — …" in the composer, the rail's
"…settles into the span it recorded" explainer, "Employee data snapshot: 2026-09-01" footer.

### 3.2 Chat during a turn — `chat-inflight`, `chat-confirm-inflight`

The question appears immediately as a right-aligned user bubble (optimistic echo). Below it, one
assistant bubble in a pending state showing **one** line, replaced as the step changes, taken
verbatim from `narration.label_for()` and nothing else:

```
                    │  You                      ▸ right    │
                    │    Can I work from Berlin…           │
                    │                                       │
                    │  ● Searching the policy library…      │  ← single status line,
                    │                                       │    role=status, throttled 2 s,
                    │ [textarea disabled]   [Stop]          │    no kind/name/summary
```
`Stop` is client-side: abort the htmx request, close the EventSource, clear the pending bubble,
and say "Stopped. The full record is still in the dashboard." The composer is locked (textarea
disabled, demo buttons and persona select disabled) so a second turn cannot be queued silently.
No spans, no `0 ms`, no `13512→648 tok`, no `stub:stub`, no elapsed counter in a live region.

### 3.3 Chat with an answer — `chat-answer`, `zoom-turn-answer`, `chat-answer-expanded`

```
│  You                                                       ▸ right, 75% max │
│    I want to work from Berlin from 3 Nov to 14 Dec 2026 — can I?            │
│                                                                             │
│  M  Mosaic                                        23:49   ◂ left, 92% max   │
│     You have 3 years 9 months of continuous service, past the 12-month      │
│     minimum for working outside your home country.                          │
│     (Remote & Hybrid Work Policy · Eligibility)                             │  ← inline ref,
│                                                                             │    button not link
│     Stays over 30 days need a Tax & Legal review before departure.          │
│     (Tax & Location Addendum · Duration Thresholds)                         │
│                                                                             │
│     ▸ What I suggest you do                                                 │  ← recommendations
│       • Raise the request in MosaicOne at least 30 days ahead               │    grouped once
│       • Confirm device encryption with IT Security                          │
│       Suggestions are guidance, not company policy.                         │  ← one footnote
│                                                                             │
│     Sources  (6)                                                            │  ← always visible
│       Remote & Hybrid Work Policy · Eligibility                             │    strip, expands
│       Tax & Location Addendum · Approved Countries                          │    to snippets
│       …                                                                     │
│     Based on employee data from 1 September 2026                            │  ← once per turn
```
Gone: the five uppercase `POLICY FACT` chips, `Recommendation — not company policy` repeated per
block, the `▸ Agent activity — 28 steps · 7 tool calls · 6 model calls` disclosure and its 28 rows,
`Full span waterfall`, `data-chunk-id`, the `>` heading-path operator, the second ISO date.
A source reference opens the snippet in place; "Open the full policy" goes to a **reader** route
(`/policy/{doc_id}#{chunk_id}`), never `/dashboard/corpus/...`.

### 3.4 Confirmation — `chat-confirm-card`, `zoom-confirm-card`, `chat-after-confirm`

```
│  M  Mosaic                                                                  │
│     Nothing has been created yet. Review this, then confirm or cancel.      │
│     ┌───────────────────────────────────────────────────────────────────┐   │
│     │  Confirm before anything is written                               │   │
│     │  Request    PTO Request: 3 days, 15–17 September 2026             │   │  ← <dl>, not <pre>
│     │  Goes to    HR Time Off team                                      │   │  ← label, not slug
│     │  Priority   Normal        (omitted when normal)                   │   │
│     │  Nothing is written until you choose.                             │   │
│     │                       [ Open the request ]  [ Don't open it ]     │   │
│     └───────────────────────────────────────────────────────────────────┘   │
```
After confirming, the **user's question stays in the transcript** (the resumed fragment re-renders
it), the card is replaced by a resolved line — "You approved this — HR ticket opened" — and the
answer reads: *"Done — your time-off request is with the HR Time Off team. Reference
MOCK-HR-000001."* One statement, no queue slug, no priority enum, no "this is a mock ticket"
inline (that lives in the demo panel), no contradicting "The ticket already exists…" block, no
amber "Recommendation — not company policy" badge over a completed write.

### 3.5 Refusal, clarification, error — `chat-refusal`, `chat-clarify`, `chat-error-degraded`

No badge on any of these outcomes. One quiet state lead, then prose, then an action.

* **Refusal:** *"I could not find anything in Mosaic's policy library that answers this, so I would
  rather not guess. I only answer from Mosaic policy and your own HR record. Try asking about PTO,
  remote work, travel or benefits — or contact People Operations at people-ops@mosaicrobotics.example."*
  The threshold arithmetic (`max dense score 0.583 < 0.60`) and the tool count (`with 9 tools`)
  are gone from the answer and survive only on the G1 span in the dashboard. `next_steps` is
  **rendered** (today it is generated and silently dropped by the web layer).
* **Clarification:** one question, not a requirement list. *"Happy to check — which dates are you
  thinking of?"* plus two quick-reply chips that prefill the composer. Gone: "I need: employee
  profile, PTO balance, requested days, policy evidence on notice and approval, a compliance
  verdict, (optional, gated) a created ticket" and "Employee ids look like E1042".
* **Error:** *"Something went wrong and I could not finish that. Nothing was created or changed.
  Please try again, or contact People Operations at people-ops@mosaicrobotics.example."* Plus a
  **Try again** button that re-posts the same question. No `ESCALATION` pill, no
  `Recommendation — not company policy` over a crash, no `Agent activity — 3 steps` disclosure
  (which today leaks `StubScriptError: tests/fixtures/llm_scripts/... has 1 entries`).

### 3.6 Chat on mobile (390x844) — `chat-rest@390x844`, `chat-answer@390x844`

Single column, no horizontal document scroll (today 494px / 590px against a 390px viewport). The
masthead is one wrapping row: name, then `Chat | Dashboard`, then Sign out — all three on screen.
Composer pinned to the bottom edge, full-bleed. Demo panel collapses to a `<details>` below it.
Confirmation card values wrap; nothing scrolls sideways inside it.

### 3.7 Demo & grader panel — new `templates/_demo_controls.html`

```
┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
│  [DEMO]  Demo & grader controls                                       │
│  These controls exist for evaluation. A real user never sees them.    │
│                                                                        │
│  Act as   [ Priya Raghavan — Senior Robotics Engineer        ▾ ]      │  ← moved from masthead
│                                                                        │
│  Try a demo prompt                                                     │
│   [ Work from Berlin for six weeks ]                                   │  ← prefills composer
│   [ Book three days of PTO ]                                           │
│                                                                        │
│  This conversation                                                     │
│   Session 6fe8834d…  ·  [ Open this conversation in the dashboard → ]  │  ← the deep link
│   How this answer was produced: 7 tools used, 6 policy sections        │  ← plain-language
│   checked, 6 safety checks passed, 4.1 s.  See the full record →       │    trace summary
│                                                                        │
│  Demo environment                                                      │
│   Model provider: recorded script (no live model call)                 │
│   Employee data snapshot: 1 September 2026                             │
│   Writes are simulated — nothing leaves this app.                      │
│                                                                        │
│   [ Sign out of the demo ]                                             │
└ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
```

### 3.8 Access — `access-key-page`, `access-key-wrong`, `gate-401-root`, `gate-401-api`

Title `Sign in · Mosaic HR Copilot`. Card: **Mosaic HR Copilot** / *"Policy answers you can check,
drawn from Mosaic's HR handbook. Enter the access key you were given."* / autofocused field /
Enter. On a rejected key: the same card with the error `aria-describedby`-linked to the field,
`aria-invalid="true"` on the field, the failure echoed in the document title, and *"Check the link
you were sent, or ask whoever shared it for a new key."* Deleted: the Bearer / eval runner / MCP
Inspector / `/health` `/ready` paragraph (already documented in README and deployed.md) and the
cookie-exchange sentence. `APP_ACCESS_TOKEN is not set on this deployment.` becomes an
operator-only JSON detail, never rendered to a visitor.

### 3.9 Dashboard shell — `zoom-dash-masthead`, `zoom-dash-nav`

```
┌ Mosaic HR Copilot           [ Chat | Dashboard ]  Priya Raghavan  Sign out ┐  ← sticky, shared
│ Activity: Overview · Sessions · Turns   Under the hood: Model calls ·      │  ← sticky row 2,
│ Retrieval · Tools · Tool server   Quality: Guardrails · Evaluations        │    no "1."…"11.",
│ Reference: Policy library                                                  │    no greyed item
├────────────────────────────────────────────────────────────────────────────┤
│ Sessions / Conversation · Priya Raghavan · 14 Sep 2026 23:49               │  ← breadcrumb on
│ Turns  ────────────────────────────────────────────────────────────────    │    detail pages
│ Every question asked, and how each one was answered.                        │  ← per-page lede
│ …content…                                                    Export JSON ↓ │  ← demoted to footer
```
Both rows are inside one `.app-chrome` sticky container, so scrolling never hides the way back to
chat (today the nav is sticky and the masthead is not — exactly the wrong half). `scroll-margin-top`
on every anchor target equals the measured chrome height, so `#turn-N` deep links land with the
turn header visible. `H1` is "Mosaic HR Copilot" at the same size as on chat; "Observability" and
the seven-noun enumeration move to a tagline/lede.

### 3.10 Dashboard pages — shared table rules

Applied once in `_table.html` + `app.css`, inherited by all ~20 tables:
* Lead with the human column (Question / Query / Tool / Model / Started). Ids move to the end as
  `kind: 'id'` → 8-char `<code>` chip with the full value in `title=`, still linking to the full id.
* `white-space: nowrap` only on numeric/time/badge cells; prose cells wrap at `max-width: 24rem`
  with `text-overflow: ellipsis` and a `title`.
* Numeric kinds right-aligned with `tabular-nums` — fix the specificity bug (`.data-table td.cell-num`
  beats `.data-table td`), and add the missing `score` kind (fixed 2 dp) for `max_dense_score`.
* Headers carry the same `cell-{kind}` class so labels align with values, plus an optional
  `help` tooltip rendered with a dotted underline.
* Sortable numeric/time headers via the existing query-string `Filters` mechanism (server-side —
  Turns/Sessions are `LIMIT/OFFSET` paginated, so client-side sorting would lie).
* Wide tables: persistent thin scrollbar + self-cancelling edge shadow; first column sticky;
  stacked card layout under 640px using the `data-col`/`data-label` attributes the macro already emits.
* Pills in list cells get a separator so copied/announced text is not `clarifyerror`.

Per page, the header + lede + notable table changes:

| # | Page | Header / lede | Table changes |
|---|---|---|---|
| 1 | **Overview** | "Overview — the last 24 hours at a glance." | 17 flat KPI tiles → 12 in three labelled groups (Traffic / Quality & safety / Speed & cost); drop the duplicate `SESSIONS TOTAL`; collapse three `$0.0000` spend tiles into one with today/7-day sub-line; error rate shows "11% (1 of 9 turns)"; percentiles show `n`; 2-up grid under 30rem; `Turns per hour` chart gets axis titles + "(UTC)" + a flat-data fallback sentence. |
| 2 | **Sessions** | "Every conversation the assistant has had." | Lead Started / Persona / Outcomes; `auth_mode`→**Sign-in**, `actor_role`→**Role**; Session id last as a chip. |
| — | **Session detail** | Breadcrumb `Sessions / "<first question>" · <id chip>`; title is the question, not `Session fd7a7cb56895…`. | Add **"Continue this conversation in chat"** (requires `/?session=<id>` rehydration); `Guardrail hits`→**Guardrail blocks** plus a new **Guardrail checks** count; answer rendered from `answer_blocks` (typed sections) instead of one flattened paragraph; payload disclosure named per span; drop `result_json` (duplicate of `structured_content`) and wrap the rest; waterfall gains an axis + total marker, zero-duration spans render as ticks not min-width bars, and the duration column survives below 1120px. |
| 4 | **Turns** | "Every question asked, and how each one was answered." | Lead `Started / Question / Outcome / Duration`; ids last as chips; Question wraps; sortable Duration. This alone brings 8 hidden columns back on screen at 1440. |
| 5 | **Model calls** (was "LLM calls") | "Each call to the language model — model, purpose, tokens, latency." | `TTFB`→**First token**, `Cache hit`→**Cached**, `Limiter wait`→**Rate-limit wait**; drop or dash-fill all-zero columns; `<1 ms` instead of `0 ms`; `$0.00`. |
| 6 | **Retrieval** | "Which policy passages each question pulled up, and how well they matched." | `k`→**Chunks requested**, `k source`→**Chosen by**, `Max dense`→**Best match** with `kind:'score'` (2 dp, right-aligned); scale hint in the panel heading. |
| 7 | **Tools** | "Every tool the assistant called, and what came back." | Arguments/Result become one-line human summaries (`"paid time off accrual" · k=1` → `1 hit · pto-and-holidays`) with the raw JSON in a per-row disclosure; a designed confirmation pause stops counting as an error (50.0% → `0.0%` + `1 paused`); `Paused for confirmation` column; `pct_of` denominators. |
| 8 | **Guardrails** (was "Safety") | "The six safety checks, what they allowed, and every human confirmation." | Rule chart labelled `G1 Evidence gate` etc. with a zero bar for unfired rules; `Reset sandbox` moved **below** the table it destroys, demoted from solid-red, `hx-confirm`, disabled when empty, copy rewritten with no table name and no admin sentence. |
| 9 | **Tool server** (was "MCP") | "The tool server the assistant is connected to, and the tools it offers." | Handshake history: `cached` instead of `0 ms`; drop the always-`[REDACTED]` catalog-sha column; schema blocks wrap. |
| 10 | **Policy library** (was "Corpus") | "The policy documents the assistant is allowed to answer from." | `PAGES 3.8` → **Words** (or `~4 pages` whole-number); document page leads each chunk with its heading path, chunk id as a chip, offsets labelled, bodies collapsed with an in-page contents list. |
| 11 | **Evaluations** | "Scored test runs — how accurate and well-cited the answers are." | Headline metrics: human labels (`Groundedness`, `Citation accuracy`, `Blocks dropped by citation check`) instead of `GROUNDEDNESS_MEAN`; all values through `pct`/`num`; Run column shows `label · created` so 15 rows are distinguishable; `Build` sha truncated to 12; `Duration (s)` → `Duration` via a `secs` adapter onto the existing `ms` filter. |
| — | **Eval run** | Breadcrumb + verdict line: **"25 of 28 items passed (89%)"**, and a delta vs the previous run of the same variant. | Metric tiles rounded (kills the 1280px overflow) and human-labelled; `Escalation matrix (0 excluded)` explained; workflow completion shows `1 of 1` not `1.0`; router matrix gets a `<thead>` and one cell of pills; `n_scored` → "Items scored per metric"; filter checkboxes get help text. |

---

## 4. Complete issue inventory

155 findings: **124 verified serious** (severities as corrected during verification) + **31 minor**.
Grouped by surface. `W` = the wave that owns the fix (§5). Severities: C = Critical, I = Important,
M = Minor. Evidence column names the screen ids that carry the proof (all three viewports exist for
each unless noted).

### 4.A Global — navigation, authorization, shell, access (28)

| ID | Sev | Issue | Evidence | Fix | W |
|---|---|---|---|---|---|
| navigation-and-ia-1 | C | Dashboard link rendered only when persona == admin (`chat.html:31 {% if is_admin %}`); 24 of 25 personas, incl. the default E1042, have no route to the dashboard at all. | zoom-header-rest, zoom-header-admin, chat-rest, all chat-* | Extract `_masthead.html`; render `Chat | Dashboard` unconditionally on both surfaces with `aria-current`. | W1 |
| navigation-and-ia-2 | C | Second "assume HR admin" gate: `ADMIN_PREFIXES=("/dashboard","/api")` → 403 `{"code":"ADMIN_REQUIRED"}`. The gate protects nothing — `POST /session/actor` sets the cookie with no check. | dashboard-403-employee, deeplink-403-employee | Replace with `ADMIN_ROUTES = {("POST","/api/dev/reset-sandbox"),("POST","/api/mcp/rediscover"),("POST","/api/eval/runs")}`; make `needs_admin(method, path)` exact-match. Keep `authorise_options()` untouched. | W1 |
| navigation-and-ia-3 | I | Every HTML navigation refusal returns a bare JSON body — no page, no nav, no way back. Same for `RATE_LIMITED` and `ACCESS_TOKEN_MISSING`. | dashboard-403-employee, deeplink-403-employee, gate-401-api | Add `_refusal_page()` beside `_key_page()`, negotiate on `_wants_html()` (already exists at `api.py:192`); new `templates/refused.html` reusing `.access-card`. | W1 |
| navigation-and-ia-6 | I | Sign out exists on chat, on none of the 13 dashboard routes; dashboard nav is `Chat` + a static `HR ADMIN` chip. `_page()` never passes `gate_on`. | zoom-dash-masthead, all dashboard-* | Shared masthead + add `gate_on`/`actor` to `_page()`'s context dict. | W1 |
| navigation-and-ia-7 | I | `.dash-nav` is `position:sticky`, `.masthead` is not — the row of internal page names stays pinned, the only Chat link scrolls away. Pages are 1.9–5.1 viewports tall. | deeplink-session-turn1, dashboard-corpus-doc, dashboard-session-demo1/2 | Wrap both rows in one sticky `.app-chrome`; drop sticky from `.dash-nav`; shrink the pinned row. | W1 |
| navigation-and-ia-8 | I | Nav items carry spec-section ordinals `1.`–`11.`, and item 3 "Session detail" is a greyed non-link that exists only to avoid a numbering gap; on session detail it is highlighted *and* navigates away. | zoom-dash-nav, all dashboard-* | Drop ordinals from labels (keep `data-nav`), remove the pseudo-entry and `DETAIL_ONLY_PAGES`, group items, highlight the real parent. | W1 |
| navigation-and-ia-11 | C | Every citation chip links to `/dashboard/corpus/{doc}#{chunk}` (`g2.py:46`) — 403 raw JSON for 24 of 25 personas; even for admin the target is a chunk inspector, not a reader. | chat-answer, zoom-citation-drawer, dashboard-403-employee | Chips become in-place disclosures; add an ungated reader route `/policy/{doc_id}#{chunk_id}`; `SOURCE_URL` repointed. | W1 |
| navigation-and-ia-12 | I | At 390px the chat masthead is 494px (employee) / 590px (admin); Dashboard and Sign out sit entirely outside the viewport. Cause: 391px `<select>` with no `min-width:0`. | chat-rest@390, chat-rest-admin@390, zoom-header-admin@390 | Move the select to the demo panel; add `min-width:0` / `flex-wrap:wrap` to `.masthead-nav`. | W1 |
| navigation-and-ia-15 | M | Three surfaces, two product names (`Mosaic HR Copilot` vs `… — observability`), three titles, two H1 sizes; session page titled `Session fd7a7cb56895…`. | zoom-dash-masthead, dashboard-session-demo1, access-key-page | One H1, one size (delete `body.dashboard .masthead h1`); session title = first question + id chip. | W1 |
| navigation-and-ia-16 | I | No route from a session record back to the conversation; the masthead `Chat` link lands on an empty composer and the transcript is lost (Back loses it too — chat has no rehydration). | dashboard-session-demo1/2, dashboard-sessions, deeplink-session-turn1 | Add `GET /?session=<id>` rehydration (replay stored turns into `#messages`, seed `#session-id`, own-persona/admin only) + a "Continue this conversation in chat" action on session detail. | W1 |
| navigation-and-ia-17 | M | `#turn-{seq}` deep link lands under the sticky nav; the offset hack targets `#turn-{turn_id}` instead. Nav is 51px desktop / 163px mobile, so a fixed offset is wrong at one end. | deeplink-session-turn1, dashboard-session-demo1 | Measure nav height into `--dash-nav-h`; `scroll-margin-top` on `.turn-card`/`.chunk`/`.anchor`; keep `.anchor` (eval link + contract tests depend on it). | W1 |
| navigation-and-ia-20 | M | Static `HR ADMIN` pill occupies the slot chat uses for its interactive persona control, and asserts a rule that is being removed. | zoom-dash-masthead, all dashboard-* | Delete; replace with the shared identity chip. | W1 |
| navigation-and-ia-14 | M | Access card leads with cookie-exchange and tokenized-link copy and closes with Bearer / eval runner / MCP Inspector / `/health` `/ready`. | access-key-page, access-key-wrong, gate-401-root, gate-401-api | Reduce to name + one sentence + field + button; delete `.access-note` (facts already in README/deployed.md). | W1 |
| jargon-and-exposure-17 | I | Same as above, plus `api.py:412` "This deployment needs an access key." and `MISSING_TOKEN_MESSAGE` leaking the env-var name to a visitor. | access-key-page, gate-401-root, gate-401-api | Rewrite both strings; keep "not recognised" verbatim (asserted by `test_access_gate.py:91`). | W1 |
| jargon-and-exposure-8 | I | `{"code":"ADMIN_REQUIRED"}` reachable in one click from the turn's own "Full span waterfall" link. | dashboard-403-employee, deeplink-403-employee, gate-401-api | Covered by nav-2 + nav-3. | W1 |
| jargon-and-exposure-7 | I | The only chat→session deep link is labelled "Full span waterfall", unstyled default-blue, last line of a collapsed technical panel, and 403s for the default persona. | zoom-trace-panel, chat-*-expanded, deeplink-403-employee | Delete from `_turn.html`; re-render in the demo panel as "Open this conversation in the dashboard". | W1/W3 |
| navigation-and-ia-5 | C | Same defect stated as IA: the hinge of the owner's target IA takes 4 discovery steps and then dead-ends. | zoom-trace-panel, chat-*-expanded | As above. | W1/W3 |
| demo-and-grader-controls-4 | C | Same, with the 403 verified for the default persona. | zoom-trace-panel, deeplink-403-employee, deeplink-session-turn1 | As above. | W1/W3 |
| chat-production-ux-23 | I | Same link: jargon label, unstyled, buried, broken. | zoom-trace-panel, chat-error-degraded, deeplink-403-employee | As above; carry `data-dashboard-url` on `article.turn` for the panel to read. | W1/W3 |
| chat-production-ux-13 | C | Nav shape depends on page *and* persona; dashboard has no persona control and no sign out. | zoom-header-rest/admin, zoom-dash-masthead, dashboard-403-employee | Shared masthead + gate narrowing. Note: opening `/dashboard` without opening the read-only `/api/traces/*` leaves every Export-JSON button and every `hx-get` drawer 403ing. | W1 |
| chat-production-ux-24 | C | Followed from chat, the dashboard is not a landable destination: 403 for the default persona; as admin, no breadcrumb, and the only way back destroys the conversation. | dashboard-* , zoom-dash-nav, zoom-dash-masthead | nav-2 + nav-8 + nav-16 together. | W1 |
| chat-production-ux-12 | C | Citation chips (6–8 per answer, the most inviting elements on the page) all dead-end in raw JSON for the default persona. | chat-answer, zoom-citation-drawer, dashboard-403-employee, dashboard-corpus-doc | nav-11. | W1 |
| accessibility-and-responsive-5 | C | Same, from the a11y angle: the destination has no `<html lang>`, no heading, no landmark, nothing focusable. | chat-answer, zoom-citation-drawer, deeplink-403-employee, gate-401-api | nav-11 + nav-3. | W1 |
| dashboard-readability-1 | C | The dashboard is not readable because for the default persona it is not reachable. | dashboard-403-employee, deeplink-403-employee, chat-rest, zoom-header-rest | nav-1 + nav-2. | W1 |
| dashboard-readability-2 | C | Three mastheads, two product names, three control sets; no persistent switch. | zoom-header-rest/admin, zoom-dash-masthead, dashboard-overview | Shared `_masthead.html`; `_page()` gains `surface`/`gate_on`. | W1 |
| demo-and-grader-controls-2 | C | Navigation asymmetry, verified in both directions. | zoom-header-rest/admin, zoom-dash-masthead, dashboard-403-employee | W1 bundle. | W1 |
| demo-and-grader-controls-6 | I | 403 dead end; also reachable from the un-guarded in-turn link. | dashboard-403-employee, deeplink-403-employee | nav-2 + nav-3. | W1 |
| accessibility-and-responsive-7 | M | Inert nav item at 2.455:1 contrast whose only explanation is a hover `title`; reads as a broken tab, invisible to touch/AT. | zoom-dash-nav, all dashboard-* | Removed by nav-8. | W1 |

### 4.B Chat surface (47)

| ID | Sev | Issue | Evidence | Fix | W |
|---|---|---|---|---|---|
| jargon-and-exposure-1 | C | Permanent 22rem "Live agent activity" rail prints the raw closed-span record under every friendly label (`span.kind · span.name — span.summary`), incl. `stub:stub`, `13512→648 tok`, `G2_citation_resolvability`. | zoom-rail-*, chat-answer, chat-refusal | Delete `aside.rail`; one `<p class="turn-status">` fed by `narration.label_for()` only. | W2 |
| jargon-and-exposure-2 | C | Every finished turn carries `▸ Agent activity — 28 steps · 7 tool calls · 6 model calls` whose body is span kinds, guardrail ids, token deltas, raw tool JSON and `0 ms` rows. | zoom-trace-panel, all chat-*-expanded | Delete `_turn.html:69-85` and the `.trace-*` CSS. | W2 |
| navigation-and-ia-18 | C | Same defect as IA: the technical surface is co-resident with the product, squeezing the conversation to 836 of 1440px. | chat-answer, zoom-rail-*, zoom-trace-panel, zoom-confirm-card | `.layout` single column; `.conversation { max-width: 40rem }`. | W2 |
| demo-and-grader-controls-3 | C | Same, verified as owner-goal-(c) violation on 100% of turns in every outcome state. | zoom-trace-panel, all chat-*-expanded | As above. | W2 |
| demo-and-grader-controls-5 | C | Same for the rail, incl. `stub:stub` announcing that no real model ran, plus a 100-word grader explainer. | chat-*, zoom-rail-* | As above. | W2 |
| dashboard-readability-31 | C | The dashboard is not the single home for technical detail — chat duplicates it verbatim with the same unrounded numbers. | zoom-trace-panel, zoom-rail-answer, chat-*-expanded | W2 bundle. | W2 |
| chat-production-ux-4 | C | Same trace panel, from the chat-conventions angle. | zoom-trace-panel, chat-*-expanded | As above. | W2 |
| chat-production-ux-5 | C | The rail is a developer log presented as the progress indicator; one label repeats 6x per turn; `Working…` for unmapped kinds; `turn completed · awaiting_confirmation`. | chat-inflight, zoom-rail-* | One throttled status line; map `retrieval`/`plan`/`mcp_discovery` in `narration.py`; drop `turn started`/`turn completed`. | W2 |
| chat-production-ux-21 | I | The rail reserves 352px permanently and is boilerplate-only at rest and on any turn that finishes before the SSE stream delivers. | zoom-rail-rest, chat-rest, chat-clarify, chat-error-degraded | Deleted with the rail. | W2 |
| jargon-and-exposure-12 | M | Rail explainer uses "span", "the stream drops", "trace" on the default screen. | zoom-rail-rest, all zoom-rail-* | Deleted with the rail. | W2 |
| jargon-and-exposure-13 | I | `Working…` (6x/turn) and `turn completed · awaiting_confirmation` — raw enum — shown to the user. | zoom-rail-answer, chat-inflight, zoom-rail-confirm | `narration.label_for()` gains `retrieval`/`plan`; outcome→prose map. | W2 |
| numbers-precision-overflow-3 | C | Retrieval scores, a cosine threshold, token counts and span counts inside the answer body and the always-visible rail; `max dense score 0.583 < 0.60` is inside the refusal sentence. | chat-refusal, chat-answer, zoom-rail-*, zoom-trace-panel | Split `Verdict.reason` (span) from a plain `user_reason` (answer); strip the rail detail line. | W2 |
| jargon-and-exposure-3 | I | Refusal = the guardrail's diagnostic string + a tool count; the helpful `next_steps` it builds are never rendered. | chat-refusal, zoom-rail-chat-refusal | Rewrite `g1.refusal()`; render `next_steps` (add to `ChatResponse` + `_turn.html`). | W2 |
| chat-production-ux-6 | I | Same, plus the amber "Recommendation — not company policy" badge over a refusal. | chat-refusal, chat-refusal-expanded | As above + outcome-gated badges. | W2 |
| demo-and-grader-controls-9 | I | Same refusal, with the unrounded `0.583`. | chat-refusal, chat-refusal-expanded | As above. | W2 |
| jargon-and-exposure-4 | I | Clarification reads the internal `required_slots` tuple aloud, including `(optional, gated) a created ticket`, and asks for an employee id the app already knows. | chat-clarify, chat-clarify-expanded | Rewrite `_clarification_text()`; per-workflow single question; drop the id hint. | W2 |
| chat-production-ux-7 | I | Same, plus no quick way to answer. | chat-clarify, zoom-rail-chat-clarify | As above + quick-reply chips that prefill (not auto-submit). | W2 |
| jargon-and-exposure-5 | I | `Recommendation — not company policy` stamped on refusals, clarifications, confirmations, errors and completed writes. | chat-refusal, chat-clarify, chat-confirm-card, chat-error-degraded | Gate badges on `turn.outcome in (answered, escalated, partial)`. | W2 |
| chat-production-ux-8 | C | Every sentence wears an uppercase `POLICY FACT` chip (5 per answer) and the badge vocabulary is wrong on 4 of 5 outcomes. | chat-answer, zoom-turn-answer, chat-after-confirm, chat-error-degraded | Prose for facts (citation carries authority); one grouped suggestions block + one footnote; state lead for non-answer outcomes. | W2 |
| jargon-and-exposure-14 | I | 5x `POLICY FACT` per answer; chat's own streaming preview and `render_answer()` already do the right thing, so the finished turn is *more* tagged than the stream. | chat-answer, zoom-turn-answer, chat-after-confirm | As above; repoint `test_chat_page_renders.py:162`. | W2 |
| jargon-and-exposure-6 | I | Confirmation card shows the raw tool-arguments JSON (`employee_id`, `queue: hr-timeoff`, `priority`); at 390px it is clipped mid-value behind a horizontal scroll. | chat-confirm-card, zoom-confirm-card | `<dl class="confirm-details">` from a label/value helper; `QUEUE_LABELS`; drop `overflow-x`. | W2 |
| chat-production-ux-9 | C | Same, plus a triply-repeated summary and no statement of what Cancel does on the card itself. | chat-confirm-card, zoom-confirm-card | As above + "Nothing is written until you choose." + relabelled buttons. | W2 |
| demo-and-grader-controls-8 | I | Same, verified clipped at 390px (447/278). | chat-confirm-card, zoom-confirm-card | As above. | W2 |
| chat-production-ux-10 | I | Confirming erases the user's own question from the transcript (`hx-swap=outerHTML`, `question` not passed on the resume path). Same on Cancel. | chat-confirm-card → chat-after-confirm | Pass `question=turn["user_message"]` at `api.py:969`; add a resolved-decision line. | W2 |
| chat-production-ux-11 | I | Post-confirm answer exposes the queue slug + priority enum, says "this is a mock ticket", then argues with itself ("The ticket already exists… nothing further for you to file"). | chat-after-confirm, zoom-turn-after-confirm | Fix the `outcome.apply()` de-dup guard; rewrite `PerformedWrite.statement`; move the mock disclosure to the demo panel. | W2 |
| jargon-and-exposure-16 | I | Server failure badged "Recommendation", shouty `ESCALATION` pill, third-person "the copilot", and an expander that leaks `StubScriptError: tests/fixtures/...` / `unhandled errors in a TaskGroup`. | chat-error-degraded | Suppress badges+panel on failing outcomes; first-person copy; `text-transform:none` on `.badge-escalation`. | W2 |
| chat-production-ux-20 | I | A failed turn has no Retry, carries no copy of the question that failed, and is badged as advice. | chat-error-degraded, zoom-rail-error | Echo the question (`api.py:792`), add a Try-again form posting the same message, drop the badges. | W2 |
| chat-production-ux-1 | C | No empty state: an unlabelled textarea + two demo buttons, then ~⅔ of the viewport blank. | chat-rest, chat-rest-admin, zoom-composer-rest | Greeting + one-line capability statement + 4 starter chips. | W2 |
| chat-production-ux-2 | C | The page is a growing document: composer not sticky, no auto-scroll, composer off-screen after one answer (1406px doc / 900px viewport). | chat-answer, chat-after-confirm, chat-error-degraded | `.transcript` scroll container + sticky composer + stick-to-bottom + "Jump to latest". | W2 |
| chat-production-ux-16 | I | Measure is 99–107 characters (802px); the shell is capped at 1248px so 1920/2560 windows show large empty gutters. | chat-answer, zoom-turn-answer, chat-refusal, chat-clarify | `.layout { max-width:none }`, `.conversation { max-width:40rem; margin-inline:auto }`, `line-height:1.6`. | W2 |
| chat-production-ux-17 | I | User and assistant messages are the same full-width shape, distinguished only by tint; no avatar, label, timestamp or asymmetry. | chat-answer, zoom-turn-answer, chat-error-degraded | Asymmetric bubbles, speaker row with hover timestamp, `Copy answer`. | W2 |
| chat-production-ux-3 | I | Enter inserts a newline; no Shift+Enter convention, no Cmd/Ctrl+Enter, no hint. | zoom-composer-rest, chat-rest | `keydown` handler + `Enter to send · Shift+Enter for a new line` hint + autogrow. | W2 |
| chat-production-ux-19 | I | No Stop; a second turn can be queued; a demo click silently overwrites the draft, is dropped by htmx queueing, then blanks the finished rail. | chat-inflight, zoom-composer-rest, chat-confirm-inflight | `setBusy()` gating textarea + demo buttons + persona select; `htmx:abort` Stop; optimistic echo. | W2 |
| jargon-and-exposure-9 | M | Tagline sells the implementation ("tools over MCP, and a full audit trail") on the product's landing surface. | chat-*, zoom-header-rest/admin | Replace with employee-facing copy. | W2 |
| chat-production-ux-25 | M | Same, plus it is repeated on every screen. | chat-rest, zoom-header-* | As above. | W2 |
| numbers-precision-overflow-12 | M | Three date conventions on one chat screen (`2026-09-01` in prose, `1 September 2026` in the footer, `2026-09-01` in the rail). | chat-answer, chat-refusal, chat-confirm-card | Delete the rail footer; `human_date()` everywhere in chat; amend `synthesize.j2` to stop repeating the in-body as-of. | W2 |
| jargon-and-exposure-25 | M | Same fact printed twice per page in two vocabularies and formats. | chat-answer, zoom-rail-answer | As above. | W2 |
| demo-and-grader-controls-12 | M | Same duplication; the per-answer note is already conditional and correct. | chat-rest, chat-answer, zoom-turn-answer | Delete the rail footer only. | W2 |
| numbers-precision-overflow-13 | M | Tenure quoted as "45 months" (3 y 9 m) — LLM prose, not a rendered field. | chat-answer, zoom-turn-answer, dashboard-session-demo1 | Add a display field to `lookup_employee_profile` + a phrasing rule in `synthesize.j2`; re-record the stub scripts. | W2 |
| chat-production-ux-22 | I | Mixed and machine precision across chat and dashboard (`0.7612`/`0.774`, `1176→121 tok`, `0 ms` on 16 of 28 rows). | chat-answer-expanded, zoom-trace-panel, chat-refusal | Chat: delete. Dashboard: one `{top:.2f}` in `_summary`, `_f_num`/`_f_orna`/`_f_ms` fixes. | W2/W4 |
| demo-and-grader-controls-7 | I | Sources drawer built as grader evidence: `data-chunk-id`, raw `A > B` heading path, lowercase "6 sources", dead-end links, and a dead `Quarantined by G4` branch. | zoom-citation-drawer, chat-answer-expanded, chat-after-confirm-expanded | Use `citation.section` (already populated), drop `data-chunk-id`, title-case "Sources", delete the quarantine branch. | W2 |
| chat-production-ux-26 | M | Sources collapsed by default and styled identically to the trace disclosure directly below it. | chat-answer, zoom-citation-drawer | Always-visible sources strip; split the shared CSS rule. | W2 |
| chat-production-ux-27 | M | `Quarantined by G4 — not citable` is unconditional in the template (unexercised — G2 filters quarantined chunks out first). | zoom-citation-drawer, chat-*-expanded | Delete the branch (dead code). | W2 |
| chat-production-ux-28 | M | The only banner fires on a `/health` preflight that always resolves, and talks about free-tier spin-down; the multi-second turn has no banner. | chat-rest, chat-answer, chat-inflight | Repurpose for a long-running turn or delete. | W2 |
| demo-and-grader-controls-14 | M | Streaming preview explains the app's own architecture: "this preview is replaced by the checked answer when the turn finishes." | chat-inflight, chat-confirm-inflight | Replace with a neutral pending state. | W2 |
| demo-and-grader-controls-15 | M | `stub:stub` in chat, and the mock-write disclaimer buried mid-sentence in an answer beside a raw queue slug. | chat-answer, zoom-rail-answer, chat-after-confirm | Move both to the demo panel; use the human queue name in the answer. | W2/W3 |
| accessibility-and-responsive-3 | I | The rail is an `aria-live=polite` firehose: 46 text additions per turn, each step announced twice, a 100 ms ticker mutating inside the region, and the answer itself never announced. | chat-inflight, zoom-rail-* | `aria-hidden` the rail (then delete it) + one throttled `role=status` line + announce the finished answer. | W2/W5 |

### 4.C Demo & grader panel (11)

| ID | Sev | Issue | Evidence | Fix | W |
|---|---|---|---|---|---|
| demo-and-grader-controls-1 | C | No demo section exists. Persona select, Sign out, demo prompts, the live rail and the snapshot date are scattered through production chrome, none labelled as demo. | chat-rest, zoom-header-*, zoom-composer-rest | Create `templates/_demo_controls.html`; move all five in. | W3 |
| jargon-and-exposure-10 | C | "Act as" is the most prominent masthead control, lists 24 employees with job titles plus "HR admin", and is what makes the Dashboard link appear or vanish. | chat-*, zoom-header-rest/admin | Move to the demo panel; masthead shows a read-only name chip. | W1/W3 |
| navigation-and-ia-4 | C | Same, measured: the select is 391px (27% of the masthead) and is the widest control on mobile. | zoom-header-*, chat-rest-admin | As above. | W3 |
| chat-production-ux-14 | C | Same, plus `Demo 1 — …` / `Demo 2 — …` in the composer action row. | chat-rest, zoom-composer-rest, chat-answer | Both moved into the labelled panel. | W3 |
| jargon-and-exposure-11 | I | Two buttons literally named "Demo" share the composer's action row with the primary Send; on mobile Demo 2 takes a full row under Ask. | zoom-composer-rest, all chat-* | Move + relabel to the question text; keep `class="button demo-button"` + `data-prompt` (contract test counts 2). | W3 |
| navigation-and-ia-19 | I | Same, plus: a demo click *immediately submits* someone else's question into the user's conversation. | zoom-composer-rest, chat-rest | Prefill + focus instead of `requestSubmit()`. | W3 |
| demo-and-grader-controls-13 | I | The demo persona select is the single element that makes the page scroll sideways on a phone. | chat-rest@390, zoom-header-rest@390 | Relocation fixes it at the source; CSS guard as backstop. | W1/W3 |
| demo-and-grader-controls-11 | M | "Sign out" (which clears the shared access cookie for the whole browser) sits in the account-menu slot and is absent from the dashboard entirely. | chat-rest, zoom-header-*, zoom-dash-masthead | Shared masthead keeps it in one place; a "Sign out of the demo" row with an explanation lives in the panel. | W3 |
| demo-and-grader-controls-17 | M | Dashboard chrome is itself a rubric checklist: `1.`–`11.` ordinals plus an `HR ADMIN` chip. | zoom-dash-nav, zoom-dash-masthead, all dashboard-* | Covered by nav-8 + nav-20; the rubric→page mapping moves to the panel/README. | W1 |
| demo-and-grader-controls-16 | M | Both straplines are written for a grader: "tools over MCP, and a full audit trail" / a seven-noun enumeration of span kinds. | zoom-header-*, zoom-dash-masthead | User-facing chat line; plain dashboard line; the capability claim moves into the panel. | W2/W4 |
| demo-and-grader-controls-10 | M | Access card carries grader/API instructions before anyone reaches the product. | access-key-page, access-key-wrong, gate-401-* | Covered by nav-14 / jargon-17. | W1 |

### 4.D Dashboard (52)

| ID | Sev | Issue | Evidence | Fix | W |
|---|---|---|---|---|---|
| numbers-precision-overflow-1 | I | Eval metrics printed at full float repr (`0.9839181286549706`) as the headline of a stat tile; at 1280px 12 elements overflow (231 vs 205px) and numbers cross their card borders. | dashboard-eval-run, dashboard-evals | `|num`/`|rate` in `eval_detail.html:42,56,81-88,104` and `evals.html:52`; `.metric{min-width:0}`; keep raw in `title=` and in Export JSON. | W4 |
| dashboard-readability-3 | I | Same, with 67 such tokens on `/dashboard/evals`. | dashboard-eval-run, dashboard-evals | As above. | W4 |
| jargon-and-exposure-18 | I | Same values *and* raw snake_case identifiers as column headers/tile captions (`GROUNDEDNESS_MEAN`, `BLOCKS_DROPPED_BY_G2`), pushing 2 of 8 metric columns off a desktop viewport. | dashboard-evals, dashboard-eval-run | `METRIC_LABELS` map + `metric_label` filter; drop `font-family:var(--mono)` from `.metric-label`. | W4 |
| dashboard-readability-6 | I | Same, plus `n_scored` as a visible `<h4>` and six raw behaviour-metric `<dt>`s. | dashboard-evals, dashboard-eval-run | As above. | W4 |
| accessibility-and-responsive-17 | I | Same, framed as overflow + `$0.0000` on four KPI tiles. | dashboard-eval-run, dashboard-evals, dashboard-overview | As above + `_f_usd`. | W4 |
| numbers-precision-overflow-2 | I | A rate renders three ways across three pages (`1.0`, `0.0%`, `11.1%`); `_RATE` columns show `1.0` one click from `50.0%`; `n=` on 3 of 6 behaviour rates. | dashboard-overview, dashboard-tools, dashboard-evals, dashboard-eval-run | `RATE_METRICS` set; `|pct` for rates, `|num` for counts; uniform denominators. | W4 |
| numbers-precision-overflow-4 | I | Same score at 3 dp and 4 dp on one screen; a "max" (0.773) lower than the maxima above it (0.8583) — a labelling defect, not a maths bug. | chat-refusal-expanded, dashboard-session-*, dashboard-retrieval | `{top:.2f}` once in `orchestrator._summary`; `score` filter+kind for `max_dense_score`; relabel G1's reason "best evidence score …". **Do not** recompute the gate. | W4 |
| numbers-precision-overflow-9 | I | Numeric columns left-aligned because `.cell-num` (0,1,0) loses to `.data-table td` (0,1,1); `Max dense` is the one genuinely proportional/ragged column (no `kind`). | dashboard-retrieval/tools/llm/turns/sessions/overview/corpus/evals | Table-scoped selector; `cell-{kind}` on `<th>`; add `score` kind. | W4 |
| numbers-precision-overflow-10 | I | Wide tables overflow with no visible scrollbar, no fade, no hint: Turns 2474/1398, Retrieval 2172/1359, Tools 1939/1359, Evals 1776/1359 — Duration and Estimated cost entirely off-screen on the page that exists to show them. | dashboard-turns/retrieval/tools/llm/safety/evals (+sessions/overview @1280) | `kind:'id'` 8-char chips, prose columns wrap with ellipsis, persistent scrollbar + edge shadow, sticky first column, mobile stacking via `data-col`. | W4 |
| dashboard-readability-4 | I | Same, measured per column, incl. `TOKENS` clipped to `1,17`. | dashboard-turns/retrieval/tools/llm/safety/evals/overview/sessions | As above; drop the blanket `white-space:nowrap`. | W4 |
| dashboard-readability-11 | I | 32-hex ids are the first and widest columns (575px of 1238 on Turns), hiding the one human column. | dashboard-turns/sessions/llm/retrieval/tools/overview/session-* | As above + reorder. | W4 |
| jargon-and-exposure-19 | I | Same, plus the session page titled with a truncated hex. | dashboard-overview/sessions/turns/llm/retrieval/tools/session-* | As above + nav-15. | W4 |
| numbers-precision-overflow-6 | I | Money at 4 dp; three adjacent `$0.0000` tiles on the landing page; "(estimate)" twice in one row. | dashboard-overview, dashboard-llm, dashboard-evals, dashboard-eval-run | Banded `_f_usd` with an exact-zero branch; collapse the three tiles; drop the duplicate suffix. | W4 |
| dashboard-readability-14 | I | Same, plus nothing on the page says the provider is a stub, so the zeros read as a bug. | dashboard-overview, dashboard-llm | As above + a provider banner from `OverviewHealth`. | W4 |
| jargon-and-exposure-22 | M | Same, plus every model-call duration reads `0 ms`; `RSS` as a label. | dashboard-overview, dashboard-llm | As above + `<1 ms` + rename to "Memory". | W4 |
| numbers-precision-overflow-5 | M | Sub-ms durations truncate to `0 ms` on 16 of 28 waterfall rows, all 20 LLM rows, and all 6 MCP rows; `LLM MS 0 ms` beside `LLM CALLS 6`. | dashboard-session-*, dashboard-llm, dashboard-mcp, chat-*-expanded | `<1 ms` branch in `_f_ms`; `cached` for MCP; `LLM ms`→`LLM time`; drop dead TTFB/limiter columns. | W4 |
| numbers-precision-overflow-19 | M | One discovery event reported as both `29 ms` (card) and `0 ms` (history, all six rows). | dashboard-mcp | Label the card "Last live handshake"; render `cached` in the history. | W4 |
| dashboard-readability-26 | M | MCP handshake history has two information-free columns (`CATALOG SHA [REDACTED]`, `0 ms`); schema blocks overflow. | dashboard-mcp | Drop the sha column; wrap schemas. | W4 |
| numbers-precision-overflow-7 | M | `DURATION (S) 569.4` — the reader divides by 60; unit in the header on one page, inline on the other. | dashboard-evals, dashboard-eval-run | `_f_secs` adapter delegating to the existing `_f_ms`. | W4 |
| numbers-precision-overflow-8 | M | Thousands separators on the tile (`45,497 → 2,445`) and not on the span row (`13512→648 tok`) on the same page. | dashboard-session-*, chat-* | `:,` in `orchestrator._summary` (note: also changes the `/chat` `trace[]` wire value) or format in `_f_span_summary`. | W4 |
| numbers-precision-overflow-14 | M | 50.0% from 1 of 2 calls; a p95 from a single sample; overview rates with no `n`. | dashboard-tools, dashboard-overview | `pct_of` + `ms_n` kinds; `sample_n` on `ToolRollup`; `error_turns` on `OverviewKpis`. | W4 |
| dashboard-readability-13 | I | `create_mock_hr_ticket` shows a **50.0% error rate** — the counted error is the designed confirmation pause. Misreports the flagship safety guardrail as a failure. | dashboard-tools | Exclude `CONFIRMATION_REQUIRED` from the error numerator and the "Errors only" filter; add a `Paused for confirmation` column. | W4 |
| numbers-precision-overflow-15 | I | `GUARDRAIL HITS 0` above seven guardrail spans; `6 sources` vs `8/8 citations resolved`; `1 user_message chunks clean`. | dashboard-session-*, deeplink-session-turn1, chat-answer-expanded | Relabel to "Guardrail blocks" + add "Guardrail checks"; name G2's unit "citation links"; pluralise from the count. | W4 |
| numbers-precision-overflow-16 | M | `PAGES 3.8` for a markdown file; raw character offsets as chunk headers. | dashboard-corpus, dashboard-corpus-doc | Words (or whole `~pages`); label the offsets or move them to Export JSON. | W4 |
| dashboard-readability-25 | M | Same fractional page count with no stated basis. | dashboard-corpus | As above. | W4 |
| numbers-precision-overflow-17 | M | A unix epoch inside the clickable run id, and a 40-char git sha as the widest column (~300px) while the detail page already abbreviates to 12. | dashboard-evals, dashboard-eval-run | Human label as link text; truncate `Build` to 12. | W4 |
| dashboard-readability-7 | I | "Headline metrics" cannot be joined to "Runs": its only id column repeats 3 variant names 5 times with no run id or date. | dashboard-evals | Render `run.label` + `created_at|ts` (both already on the row model). | W4 |
| dashboard-readability-21 | I | The eval run page has no methodology and no verdict: no pass line, no comparison to the previous run of the same variant, no description of the 28 items, unexplained filters and `(0 excluded)`. | dashboard-eval-run | Verdict block ("25 of 28 items passed (89%)"), previous-run delta (one extra query), dataset legend, legends via `.note`, router-matrix `<thead>`. | W4 |
| numbers-precision-overflow-18 | M | Waterfall bars overflow their track by 2–7px; zero-duration spans render as min-width slivers at positions readers take for timing. | dashboard-session-demo1/2, deeplink-session-turn1 | Clamp to the track; distinct tick glyph for instants. | W4 |
| dashboard-readability-9 | I | Waterfall has no axis, no scale, no total marker, and 31 duplicate full-width `▸ payload` rows double the page height. | dashboard-session-demo2, dashboard-session-demo1, deeplink-session-turn1 | Axis row + quarter ticks; move the disclosure summary into a 7th column chevron; dashboard-local prose summary filter. | W4 |
| dashboard-readability-8 | M | One `result_json` line (8k chars, a double-encoded duplicate of `structured_content`) blows a payload block to 59,780px wide. | dashboard-session-*, deeplink-session-turn1, dashboard-mcp | `payload_pretty` filter dropping `result_json` when `structured_content` exists; `white-space:pre-wrap; overflow-wrap:anywhere`. | W4 |
| dashboard-readability-18 | M | The session page (the chat deep-link target) flattens the answer into one wall of text with `Recommendation — not company policy:` and `- ` list markers inline. | dashboard-session-demo1/2, deeplink-session-turn1 | Render `turn.answer_blocks` (already on the view model) + `white-space:pre-line` as the one-line mitigation. | W4 |
| dashboard-readability-19 | I | Tools `ARGUMENTS`/`RESULT` show JSON truncated mid-token (12 rows read the same `{"hits": [{"chunk_`), 906px of 1946 spent on unreadable text while Error/Duration/Actor are off-screen. | dashboard-tools | One-line human summaries + raw JSON in a per-row disclosure. | W4 |
| dashboard-readability-16 | I | Overview opens with 17 equal-weight tiles mixing measurements with config (`DAILY CALL CAP`), no reading order, no status colour; 1,663px of stacked tiles on mobile before any content. | dashboard-overview | Three labelled groups, 12 tiles, status colours on at-risk values, 2-up mobile grid. | W4 |
| dashboard-readability-23 | I | An irreversible `Reset sandbox` is the first control in its card, above the evidence it destroys, with no confirmation and developer copy naming a DB table and justifying the permission check. | dashboard-safety | Reorder below the table, `hx-confirm`, disable when empty, demote the styling, rewrite the copy. | W4 |
| jargon-and-exposure-20 | I | `AUTH_MODE`, `ACTOR_ROLE`, `K SOURCE`, `MAX DENSE`, `TTFB`, `CACHE HIT`, `LIMITER WAIT`, and a `Span kinds` chip row of raw kinds. | dashboard-overview/sessions/turns/session-*/llm/retrieval | Label-only renames (never `key`/`name`/`data-col`); `kind_label` filter for the span pills. | W4 |
| dashboard-readability-12 | M | Same `auth_mode`/`actor_role` in filter bars and `<dt>`s — three casing styles in one row. | dashboard-overview/sessions/turns/session-* | As above. | W4 |
| dashboard-readability-20 | M | `K`, `K SOURCE`, `MAX DENSE` unexplained; the score raw, left-aligned, ragged. | dashboard-retrieval, dashboard-session-* | Rename + `score` kind + scale hint in the panel heading. | W4 |
| jargon-and-exposure-23 | M | Table names, env-var names, a localhost URL, chunk ids with byte offsets, JSON clipped mid-token in body copy. | dashboard-safety/evals/mcp/corpus-doc/tools | Rewrite the copy for a reader; keep genuinely operational facts. | W4 |
| dashboard-readability-5 | M | No glossary, no legend, 3 `title=` attributes across 16 templates; `span`, `G1`–`G6`, `strict pass`, `k source`, `TTFB`, `cold`, `catalog reopened` all undefined. | dashboard-eval-run/evals/safety/retrieval/llm/session-*/mcp/overview | `GLOSSARY` + a Glossary page + a `help` slot in `_table.html`/`_filters.html`. | W4 |
| dashboard-readability-15 | M | No page states its own purpose; the same 7-noun tagline on all eleven. | all dashboard-* | Required `lede` kwarg on `_page()` (fails loudly for new pages) + `.dash-lede`. | W4 |
| navigation-and-ia-9 | M | Page names and strapline written for the implementer (`MCP catalog`, `initialize + tools/list`, `mcp_discovery span`). | zoom-dash-nav, zoom-dash-masthead, dashboard-mcp/llm/retrieval/turns/corpus/evals | Keep the technical noun primary, add a plain lede; rename entry 9 to "Tool server". | W4 |
| navigation-and-ia-10 | M | Detail pages have no breadcrumb; corpus/eval detail paint the *parent* nav item as current. | dashboard-session-*, dashboard-corpus-doc, dashboard-eval-run, deeplink-session-turn1 | `breadcrumbs` + `nav_state` kwargs on `_page()`; `.crumbs` CSS. | W4 |
| dashboard-readability-22 | M | Session page titled with a truncated hex, with the full id repeated directly below. | dashboard-session-*, deeplink-session-turn1 | Title = first question; id as a copyable chip; drop the duplicate fact row. | W4 |
| dashboard-readability-10 | M | No table on the dashboard is sortable; 9–13 columns scanned by eye. | dashboard-sessions/turns/llm/retrieval/tools/safety/corpus/evals/overview | Server-side sort threaded through the existing `Filters` query-string (JS would only sort one page of a `LIMIT/OFFSET` table). | W4 |
| dashboard-readability-17 | M | Charts have no axis titles, no units, no timezone; the guardrail chart's categories are bare `G1`–`G6` and `G5` is silently absent while the filter offers it. | dashboard-overview, dashboard-safety | Axis titles, `(UTC)`, rule names from `RULE_NAMES`, zero bars, flat-data fallback sentence. | W4 |
| dashboard-readability-24 | M | Corpus document is a 4,887px dump with the chunk id as each section's heading. | dashboard-corpus-doc | Heading path first, id as a chip, labelled offsets, collapsed bodies, in-page contents. | W4 |
| dashboard-readability-28 | M | Filter placeholders (`E1042`, `workflow`, `pto_request`, `PTO`) are indistinguishable from applied filters. | dashboard-turns/tools/retrieval/sessions | `e.g. ` prefix + an "Active filters" chip row. | W4 |
| dashboard-readability-29 | M | The chat deep link lands with the turn's identity row behind the sticky nav and no highlight on the target. | deeplink-session-turn1 | `scroll-margin-top` + `:target` highlight + "Opened from chat" breadcrumb (with nav-17). | W4 |
| dashboard-readability-30 | M | Multi-value cells emit pills with no separator, so copied/announced text reads `clarifyerror`, `ptoholidays`. | dashboard-overview/sessions/corpus/retrieval | Visually-hidden `, ` between pills (or an `aria-label` on the cell). | W4 |
| navigation-and-ia-21 | M | `Export JSON` is a bordered button level with the H1 on all 13 pages — a raw-API escape hatch as the dominant action. | all dashboard-* | Demote to a footer text link; consider CSV primary. | W4 |
| jargon-and-exposure-24 | M | "observability", "the one trace store", ordinals, and `3. Session detail` in the nav. | zoom-dash-masthead, zoom-dash-nav, all dashboard-* | Covered by nav-8/nav-9/nav-15. | W1/W4 |

### 4.E Cross-surface — responsive & accessibility (17)

| ID | Sev | Issue | Evidence | Fix | W |
|---|---|---|---|---|---|
| numbers-precision-overflow-11 | I | Every chat screen scrolls the document sideways at 390px (494px employee / 590px admin); Sign out and Dashboard fully off-viewport. | all chat-*@390, zoom-header-admin@390 | Structural (move the select) + `min-width:0` CSS guard. | W1 |
| accessibility-and-responsive-1 | I | Same, with the a11y consequence: the chat↔dashboard switch and Sign out are unreachable without discovering a horizontal scroll. | all chat-*@390 | As above. | W1 |
| chat-production-ux-15 | I | Same, measured; dashboard routes at 390 are clean, so this is chat-only. | all chat-*@390 | As above. | W1 |
| accessibility-and-responsive-2 | I | The finished answer is never announced. The only conversation live region is `#provisional-answer`, which is emptied and hidden the instant the real answer arrives; `#messages` has no live region. | chat-answer, chat-confirm-card, chat-refusal, chat-error-degraded | Two visually-hidden announcers (`role=status` + `role=alert`) composed from `data-outcome`; move focus to the confirm heading. | W5 |
| accessibility-and-responsive-4 | M | Submitting destroys focus (`hx-disabled-elt` blurs the pressed button → `<body>`); focus is never returned; Confirm/Cancel are removed from the DOM with no id so htmx restores nothing. | chat-inflight, chat-answer, chat-after-confirm | Return focus to `#message` in `htmx:afterSwap`; add `:focus-visible` styles (none exist in `app.css`). | W5 |
| accessibility-and-responsive-9 | I | Below 1120px the waterfall **deletes** the duration bar and the ms value, and the summary reflows into a 32px column (row height 65→326px, page 12,473px). | dashboard-session-demo1/2, deeplink-session-turn1 | Explicit 4-column restack keeping `.span-duration`; hide only the decorative track; `aria-hidden` on it. | W5 |
| accessibility-and-responsive-10 | I | Deep links land under the sticky nav and move no focus; same for citation `#chunk_id` anchors. | deeplink-session-turn1, dashboard-session-*, dashboard-corpus-doc | `--dash-nav-h` measured + `scroll-margin-top` + `el.focus({preventScroll:true})`. | W5 |
| accessibility-and-responsive-12 | M | The wrong-key error is not announced (`role=alert` on a server render fires nothing) and is not linked to the field. | access-key-wrong, gate-401-root, gate-401-api | `invalid` flag; title prefix; `aria-describedby` + `aria-invalid` + `autofocus` **only** on a genuine rejection. | W5 |
| accessibility-and-responsive-13 | M | At 390px the rail reflows below the composer and its auto-scrolled newest line is 129px below the fold, so the only visible lines are stale. | chat-rest, chat-answer, chat-clarify | Dies with the rail; the status line lives in the composer. | W2/W5 |
| accessibility-and-responsive-16 | M | No heading structure in the conversation, no skip link, unnamed conversation region; `dashboard-corpus-doc` renders its title twice. | chat-*, dashboard-corpus-doc, dashboard-session-demo1 | Visually-hidden per-turn `<h2>` + `aria-labelledby`; `aria-label` on `.conversation`; skip link to `#main-content`; delete the duplicate `<h3>`. | W5 |
| accessibility-and-responsive-18 | M | 28 disclosure controls named `payload` on one page; the chat trace disclosure named by step count. | dashboard-session-*, deeplink-session-turn1, chat-*-expanded | Name each per span; chat's disappears with the panel. | W5 |
| accessibility-and-responsive-19 | M | Six Chart.js canvases expose no data, animate with no `prefers-reduced-motion` opt-out, and encode series by hue alone. | dashboard-overview, dashboard-safety, dashboard-evals, dashboard-eval-run | `figure role=img` + a visually-hidden table from the JSON already embedded; reduced-motion guard; dash patterns. | W5 |
| accessibility-and-responsive-20 | M | `body { font: 16px }` and `body.dashboard { font-size: 17px }` pin body copy to px; the densest technical panels are 11.5–12px monospace. | chat-answer, zoom-trace-panel, zoom-rail-answer, dashboard-* | `rem` on both; raise every sub-0.8rem token. | W5 |
| navigation-and-ia-13 | M | The 11-item nav wraps to four rows at 390px and stays pinned, consuming ~160px (a fifth of the viewport) of internal page names. | dashboard-safety@390, all dashboard-*@390 | One scrollable row or a select below 700px (with nav-8's de-numbering). | W5 |
| numbers-precision-overflow-20 | M | Overview degrades to 17 full-width single-number cards on a phone. | dashboard-overview@390 | 2-up grid + grouping (with dashboard-readability-16). | W5 |
| dashboard-readability-27 | M | Numbered nav implies a sequence, contains a never-clickable item, and pushes all content below the fold on mobile. | zoom-dash-nav, dashboard-overview@390, dashboard-eval-run@390, dashboard-turns@390 | nav-8 + the mobile nav collapse. | W1/W5 |
| chat-production-ux-29 | M | Access card is engineering documentation; the field is not autofocused; a bad key offers no recovery path. | access-key-page, access-key-wrong, gate-401-* | Covered by nav-14 + a11y-12. | W1/W5 |

---

## 5. Fix waves

Each wave is independently shippable and independently verifiable. The order is load-bearing:
W1 unblocks the links W2 and W3 rely on; W2 empties the chat surface that W3's panel then adopts;
W4 and W5 are cleanup and can run in parallel with each other once W1–W3 have landed.

---

### W1 — IA, navigation, persona removal, the deep link
**Goal.** One global nav on every page, one gate, no dead ends, and a working chat→session deep
link, for every persona.

**Findings.** navigation-and-ia-1, -2, -3, -5, -6, -7, -8, -11, -12, -14, -15, -16, -17, -20;
jargon-and-exposure-7, -8, -10, -17, -24; chat-production-ux-12, -13, -14, -15, -24, -29;
demo-and-grader-controls-2, -4, -6, -10, -13, -17; dashboard-readability-1, -2;
accessibility-and-responsive-1, -5, -7; numbers-precision-overflow-11.

**Files.**
`src/hrmosaic/web/templates/_masthead.html` (new), `templates/refused.html` (new),
`templates/chat.html` (masthead block, actor form removal), `templates/dashboard/_base.html`
(masthead + nav loop + sticky chrome), `templates/access.html`,
`src/hrmosaic/web/api.py` (`ADMIN_PREFIXES`→`ADMIN_ROUTES`, `needs_admin(method, path)`,
`_refusal_page()`, `chat_page()` context: `surface`, `actor_name`, `?session=` rehydration),
`src/hrmosaic/web/dashboard.py` (`NAV` de-numbered/grouped, drop `DETAIL_ONLY_PAGES`, `_page()`
gains `surface`/`gate_on`/`breadcrumbs`/`nav_state`, session-detail title, `/policy/{doc_id}` route),
`src/hrmosaic/web/templates/dashboard/session_detail.html` (breadcrumb + "Continue in chat"),
`src/hrmosaic/agent/guardrails/g2.py:46` (`SOURCE_URL` → `/policy/...`),
`src/hrmosaic/web/static/app.css` (`.app-chrome`, `.nav-switch`, `.crumbs`, `--dash-nav-h`,
`scroll-margin-top`, `.masthead-nav{min-width:0;flex-wrap:wrap}`, delete `.persona-chip`,
`body.dashboard .masthead h1`, `.dash-nav-link.is-detail`),
`templates/dashboard/_table.html` (no change yet).

**Tests to add / update.**
* `tests/contract/test_nav_parity.py` (new) — the masthead block is byte-identical (modulo
  `aria-current`) on `/` and on all 13 dashboard routes; `id="dashboard-link"` present for
  `mosaic_actor=E1042`; `action="/access/logout"` present on every dashboard route when the gate is on.
* `tests/contract/test_no_broken_links.py` (new) — render `/` as the default actor, collect every
  `href`, assert all resolve 2xx (this is the regression guard for the citation-chip class).
* `tests/contract/test_html_error_pages.py` (new) — `Accept: text/html` on the admin-write 403,
  the missing-token 403 and the rate-limit 429 returns `text/html` containing `href="/"`; the
  `Accept: */*` JSON bodies are unchanged.
* **Update** (they encode the old gate): `tests/contract/test_dashboard_pages.py:139,146`,
  `tests/contract/test_personas.py:42,44,56`, `tests/contract/test_access_gate.py:173`.
  **Keep green untouched:** `tests/contract/test_chat_privileged_options.py`,
  `tests/integration/test_smoke_eval_endpoint.py:58`.
* Docs to move with the behaviour: `docs/requirements-traceability.md:236` (USER.2),
  `docs/architecture.html` §11/§11.8, `docs/demo-script.md:33,145,229`, `README.md` Deployed line,
  and the stale docstrings at `api.py:12,20` and `dashboard.py:19`.

**Effort.** ~2 days. The gate narrowing and the shared masthead are each an hour; the two costs are
(a) the `/policy/{doc_id}` reader route + template, and (b) `GET /?session=<id>` rehydration, which
needs a turn-replay path in `chat_page()` and an ownership check (`/` is not admin-gated, so a raw
session id would otherwise expose another persona's conversation).

**Risks.**
* **Opening `/dashboard` without opening the read-only `/api/traces/*` breaks the dashboard** —
  `Export JSON` on all 13 pages and ~10 `hx-get` drawers point at `/api/*`. Narrow by
  method+exact path, not by prefix; `GET /api/eval/runs` and `POST /api/eval/runs` share a path.
* Rehydration is the one place a genuinely new capability is added; if it slips, ship the
  "Continue this conversation in chat" affordance in W3 instead of W1 and keep the honest label
  "Back to chat (starts a new conversation)".
* `.anchor` must survive (eval trace links + `test_dashboard_pages.py:332` depend on it) — only its
  `top:-4rem` hack goes.

---

### W2 — Chat redesign
**Goal.** Chat reads as a production assistant: full page, plain language, no trace, no badges on
non-answer turns, sticky composer, Enter to send, humane progress, friendly sources.

**Findings.** jargon-and-exposure-1, -2, -3, -4, -5, -6, -9, -12, -13, -14, -16, -25;
chat-production-ux-1, -2, -3, -4, -5, -6, -7, -8, -9, -10, -11, -16, -17, -19, -20, -21, -22, -25,
-26, -27, -28; navigation-and-ia-18; numbers-precision-overflow-3, -12, -13;
demo-and-grader-controls-3, -5, -7, -8, -9, -12, -14, -15; dashboard-readability-31;
accessibility-and-responsive-3 (partial), -13.

**Files.**
`templates/chat.html` (delete `aside.rail` + its JS detail line; status line; empty state; sticky
composer + transcript container; keyboard handler; busy switch + Stop; optimistic echo; tagline),
`templates/_turn.html` (delete the trace panel; outcome-gated badges; prose facts; grouped
suggestions; sources strip; confirm `<dl>`; per-turn heading; retry form),
`src/hrmosaic/web/api.py` (`_confirm_fields()` + `QUEUE_LABELS`; `question=` on the confirm and
error render paths; `next_steps` on `ChatResponse` + context; `INTERNAL_ERROR_TEXT` copy;
`data_as_of` through `human_date`),
`src/hrmosaic/web/narration.py` (labels for `retrieval`/`plan`/`mcp_discovery`),
`src/hrmosaic/agent/guardrails/g1.py` (`user_reason` split; drop the tool-count clause),
`src/hrmosaic/agent/orchestrator.py` (`_clarification_text()`; `outcome.apply()` de-dup guard),
`src/hrmosaic/agent/outcome.py` (`PerformedWrite.statement`/`pointer`),
`src/hrmosaic/mcpserver/tools/create_mock_hr_ticket.py` (`QUEUE_LABELS`, `human_summary`),
`src/hrmosaic/agent/prompts/synthesize.j2` (date + duration phrasing rules),
`src/hrmosaic/web/static/app.css` (single-column `.layout`, `.conversation` measure, sticky
composer, message asymmetry, `.turn-status`, `.confirm-details`, delete `.rail*`/`.span-*`
rail rules/`.trace-*`/`.arguments-preview`).

**Tests to add / update.**
* `tests/contract/test_chat_has_no_jargon.py` (new) — render every turn state through the stub
  scripts (`demo_task_1`, `demo_task_2`, `out_of_corpus_tuition`, `fault_ambiguous`) and assert the
  **P2 denylist** matches nothing in the HTML. This is the permanent guard for the whole class.
* `tests/contract/test_number_precision.py` (new) — over the same rendered pages *and* every
  dashboard route: no `\d+\.\d{4,}`, no `\$\d+\.\d{3,}`. (Dashboard half turns on in W4.)
* New assertions: badge absent on `refused`/`clarify`/`awaiting_confirmation`/`error`; the user
  question present on the post-confirm and post-error fragments; `next_steps` rendered on a refusal.
* **Update:** `test_chat_page_renders.py:39,89` (`#span-rail` → `#turn-status`), `:162`
  (`badge-policy_fact` → `answer-block-policy_fact`), `tests/unit/test_narration.py:67-68`,
  `tests/unit/test_outcome_consistency.py:83,93,195`.
* Re-record `tests/fixtures/llm_scripts/*.json` only if the tenure/date phrasing rules land
  (`numbers-precision-overflow-13`, `-12`); three `tests/fixtures/eval_runs/r_p9fixture_*.json`
  carry the old refusal/clarify strings as stored artifacts — check nothing asserts equality.

**Effort.** ~3 days — the largest wave. The template work is mechanical; the copy rewrites in
`g1.py`, `orchestrator.py` and `outcome.py` need care because their strings are shared with the
trace and the eval harness (split, never move).

**Risks.**
* **Deleting the rail leaves the chat surface with no progress signal and no live region at all**
  unless the status line and the answer announcement (W5's a11y-2) ship in the same change. Land
  them together.
* `summarise_span`/`_summary` is shared by the rail, the chat trace and the dashboard waterfall —
  edit rendering, not the helper, except for the one `{top:.2f}` change.
* The streamed preview (`chat.html renderBlock`) mirrors `BADGE_TEXT`; changing one and not the
  other makes the answer visibly change chrome at `turn_completed`.
* `tests/contract/test_chat_page_renders.py:100` asserts the literal `"Recommendation — not company
  policy: "` prefix exists in the page JS — keep the constant, branch on outcome.

---

### W3 — Demo & grader panel
**Goal.** Every demo/grader affordance in one clearly labelled section; nothing demo-shaped left in
production chrome.

**Findings.** demo-and-grader-controls-1, -11, -13, -15 (part), -16 (part);
jargon-and-exposure-10, -11; navigation-and-ia-4, -19; chat-production-ux-14, -23;
navigation-and-ia-5 / demo-and-grader-controls-4 / jargon-and-exposure-7 (the deep link's new home).

**Files.** `templates/_demo_controls.html` (new), `templates/chat.html` (include it; remove the
actor form and the two demo buttons; `data-dashboard-url` on `article.turn`; enable the link in the
existing `htmx:afterSwap` handler), `src/hrmosaic/web/api.py` (`actor_employee`/`actor_name` in the
chat context; a plain-language per-turn "how this answer was produced" summary derived from
`turn.usage` + citation count), `src/hrmosaic/web/static/app.css` (`.demo-panel`, `.demo-chip`,
`.demo-note`, `.identity-chip`).

**Tests.**
* `tests/contract/test_demo_controls_are_quarantined.py` (new) — **P8**: `#actor-select`,
  `.demo-button` and any `/dashboard/sessions/` link appear only inside `section.demo-panel`, and
  never inside `nav.masthead-nav` or `form#chat-form`; the panel has a heading containing "Demo".
* **Keep green:** `test_chat_page_renders.py:35` (`<select id="actor-select" name="actor"` — keep
  the id and name), `:38` (`html.count('class="button demo-button"') == 2` — keep the class).

**Effort.** ~0.5 day. Pure relocation: the demo-button click handler is delegated by class and the
actor form posts by URL, so neither depends on DOM position.

**Risks.** Low. The one behaviour change is making a demo prompt *prefill* rather than submit —
confirm with the owner whether the grader flow should stay one-click.

---

### W4 — Numbers, jargon and dashboard cleanup
**Goal.** Every number at human precision in one convention; every label in English; every table
scannable; the dashboard self-explaining.

**Findings.** numbers-precision-overflow-1, -2, -4, -5, -6, -7, -8, -9, -10, -14, -15, -16, -17,
-18, -19; jargon-and-exposure-18, -19, -20, -22, -23, -24; navigation-and-ia-9, -10, -21;
dashboard-readability-3 to -23 (all), -24, -25, -26, -28, -29, -30; accessibility-and-responsive-17;
chat-production-ux-22 (dashboard half).

**Files.**
`src/hrmosaic/web/dashboard.py` — the filter table (`_f_num` fixed decimals, `_f_pct`, new `_f_rate`,
`_f_score`, `_f_secs`, `_f_usd` banded, `_f_ms` `<1 ms`, `_f_orna` delegating floats,
`_f_payload_pretty`, `_f_kind_label`, `_f_label`), `METRIC_LABELS`/`RATE_METRICS`/`GLOSSARY`/
`RULE_NAMES` wiring, `ToolRollup.sample_n`+`errors`+`confirmation_pauses`,
`OverviewKpis.error_turns`, the tools-rollup SQL, `build_turns` `dashboard_url`,
`build_eval_run_detail` (verdict + previous-run delta + dataset legend), `_page(lede=…)`,
sort support in `Filters`;
`templates/dashboard/_table.html` (kinds `id`/`score`/`secs`/`pct_of`/`ms_n`, `cell-{kind}` on
`<th>`, `data-label`, `help`, detail row, sortable headers, pill separators);
`templates/dashboard/{overview,sessions,turns,llm,retrieval,tools,safety,mcp,corpus,corpus_document,evals,eval_detail,session_detail}.html`;
`templates/dashboard/glossary.html` (new);
`src/hrmosaic/agent/orchestrator.py:398-404` (`{top:.2f}`, thousands separators — note this string
is also the `/chat` `trace[]` `summary` field);
`src/hrmosaic/agent/guardrails/{g1,g3,g4}.py` + `_table.html:53` (pluralise from the count);
`src/hrmosaic/core/trace.py:694` is the *definition* of `guardrail_hits` — relabel the display, do
not change the column;
`src/hrmosaic/web/static/app.css` (numeric alignment specificity, `.table-scroll` affordance,
sticky first column, mobile stacking, `.metric{min-width:0}`, `.kpi-sub`, `.dash-lede`, `.crumbs`,
`.id-chip`, `.pill-paused`, `.span-payload pre{white-space:pre-wrap}`).

**Tests.**
* `tests/contract/test_number_precision.py` — extend to every dashboard route (**P1**).
* `tests/contract/test_formatter_coverage.py` (new) — **P10**: grep the dashboard templates for a
  numeric/temporal expression not piped through a registered filter → 0.
* `tests/unit/test_dashboard_tools_rollup.py:90-110` — **update**: a `CONFIRMATION_REQUIRED` span
  lands in `confirmation_pauses`, not `error_rate`, and is skipped by `errors_only`.
* `tests/contract/test_dashboard_viewmodels.py` — snapshot the `/api/*` payloads before/after
  (**P15**): additive fields only, no formatting in the JSON.
* **Keep green:** `test_dashboard_pages.py` asserts on `data-page`, `data-col`, `data-metric`,
  `id="dash-nav"`, `id="eval-runs-table"` and the literal "not judged on this variant" — preserve
  every one of those hooks while changing labels.

**Effort.** ~3 days, highly parallelisable (one page per sitting). ~60% of it lands from ~15 lines
in the filter table plus `_table.html`.

**Risks.**
* Formatting must stay in Jinja. `tests/unit/test_dashboard_tools_rollup.py:94` and
  `tests/contract/test_dashboard_viewmodels.py` assert raw floats on the view models.
* Do **not** turn 0–1 eval metrics into percentages in the JSON or the Chart.js series — page,
  export and chart must agree (the charts plot 0–1 today).
* Do **not** recompute G1's `max_dense_score` to "the true maximum": the gate deliberately scores
  the accumulated citable evidence, first-seen-wins. Relabel only.
* `_f_num`'s `rstrip("0").rstrip(".")` is itself a ragged-column generator — fix it while adding
  `score`, or the alignment fix is undone by the next float column.

---

### W5 — Responsive & accessibility
**Goal.** Nothing lost or unreachable at 390px or at 200% zoom; keyboard and screen-reader parity
on both surfaces.

**Findings.** accessibility-and-responsive-2, -3, -4, -9, -10, -12, -13, -16, -18, -19, -20;
navigation-and-ia-13; numbers-precision-overflow-20; dashboard-readability-27;
chat-production-ux-29 (a11y half).

**Files.** `templates/chat.html` (announcers, focus return, skip link, `#main-content`),
`templates/_turn.html` (per-turn `<h2>` + `aria-labelledby`, confirm heading focus target),
`templates/access.html` (`invalid` flag, `aria-invalid`, `aria-describedby`, autofocus, title),
`src/hrmosaic/web/api.py` (`_key_page(invalid=…)`),
`templates/dashboard/_base.html` (skip link, `--dash-nav-h` measurement script, chart figure
wrappers), `templates/dashboard/session_detail.html` (restack + named payload summaries),
`templates/dashboard/corpus_document.html` (delete the duplicate `<h3>`),
`src/hrmosaic/web/static/app.css` (`rem` body sizes, `:focus-visible`, `.skip-link`,
`@media (max-width:70rem)` waterfall restack, mobile nav row, 2-up KPI grid, `.cell-*` minimum
sizes, reduced-motion guard).

**Tests.**
* `tests/e2e/test_screens_playwright.py` (new, behind a `playwright` dev extra) — drives the stub
  app at 1440x900 / 1280x800 / 390x844 and asserts: `body_horizontal_scroll` false on every screen
  (**P7**); the composer is sticky and in-viewport after 3 turns (**P11**); Enter submits and focus
  returns to `#message` (**P12**); exactly one live-region addition per turn, denylist-clean
  (**P12**); `.span-duration` count > 0 at 390px (**a11y-9**); no two disclosures on a page share an
  accessible name (**a11y-18**).
* Non-browser fallback if the dev extra is rejected: assert the CSS rules exist and the markup
  hooks are present (weaker, but keeps the class from silently regressing).

**Effort.** ~1.5 days plus ~0.5 day to stand the Playwright suite up in-repo.

**Risks.** The only wave that adds a dependency, and it is test-only. Keep it optional
(`pytest -m browser`) so CI without browsers still passes.

---

## 6. Verification protocol

The audit is reproducible; re-run it, do not eyeball it.

1. **Start the stub app** exactly as the capture did — four servers sharing one trace DB:
   ```
   LLM_PROVIDER=stub LLM_STUB_SCRIPT=tests/fixtures/llm_scripts/<name>.json \
   APP_ACCESS_TOKEN=uxaudit APP_ENV=local PERSIST_BACKEND=sqlite \
   TRACE_DB_PATH=<scratchpad>/uxaudit/traces.sqlite \
   .venv/bin/uvicorn hrmosaic.web.main:app --host 127.0.0.1 --port <free>
   ```
   scripts: `demo_task_1` (rest / cited answer / 403s), `demo_task_2` (confirm + resume),
   `out_of_corpus_tuition` (refusal), `fault_ambiguous` (clarify, error, all dashboard routes).
   **Never call a live LLM.**
2. **Re-capture the same 53 screen ids at the same 3 viewports** with the existing harness
   (`<scratchpad>/uxaudit/cap.py`, `run_prompt.py`, `run_dash.py`) into a new directory
   `uxaudit-w<N>/`, using the Playwright venv
   `<scratchpad>/pwvenv/bin/python`. Keep `index.json`'s screen ids stable so before/after pairs
   line up; add ids only for genuinely new surfaces (`demo-panel`, `policy-reader`, `refused-page`,
   `chat-empty-state`, `dashboard-glossary`).
3. **Run the mechanical gates** (§1) over the new `.txt` / `.overflow.json` / `.numbers.json`:
   P1 precision, P2 chat denylist, P7 overflow, P10 formatter coverage, P8 demo quarantine.
   Each must be 0 matches / false.
4. **Run the pytest suite**, including the five new contract tests, plus the browser suite if the
   dev extra landed.
5. **Diff the numbers.** The audit's own counters are the scoreboard:
   | Metric | Today | Target |
   |---|---|---|
   | chat screens with a denylist token | 26 of 26 | 0 |
   | tokens with ≥4 decimals, `/dashboard/evals` | 67 | 0 |
   | ditto, `/dashboard/evals/{run}` | 9 | 0 |
   | `$0.0000` occurrences | 4+ | 0 |
   | chat screens with `body_horizontal_scroll` at 390px | 26 | 0 |
   | `.table-scroll` elements overflowing with no affordance | 8 pages | 0 |
   | metric tiles overflowing at 1280px | 12 | 0 |
   | dashboard routes reachable as E1042 | 0 of 13 | 13 of 13 |
   | hrefs on `/` that 403 for the default persona | 7–9 per answer | 0 |
   | live-region additions per turn | 46 | ≤2 |
6. **Re-run the seven lenses** (numbers/precision, jargon, navigation/IA, chat production UX,
   demo controls, dashboard readability, accessibility/responsive) against the new captures and
   record any finding that survives, plus any *new* finding the redesign introduced — a redesign
   this large will produce some.
7. **Owner review** of the three surfaces at 1440x900 and 390x844, against the three stated goals
   (a) production chat UX, (b) demo controls in a labelled card, (c) technical detail in the
   dashboard with a deep link from clean chat.

---

## 7. Open questions — owner decisions this plan cannot make

1. **Should a real user ever see sources?** The plan keeps them as friendly references because they
   are the product's trust affordance. The alternative — hiding them behind "How was this checked?"
   — makes chat cleaner but weakens the claim. Which?
2. **Where does a citation link go?** Options: (a) expand the quoted passage in place only,
   (b) a new ungated reader route `/policy/{doc_id}#{chunk_id}` (this plan's default — new template,
   ~half a day), (c) leave them pointing at the dashboard corpus page once the gate is gone, which
   is a chunk inspector, not a reader. (c) is free but re-introduces goal-(c) leakage.
3. **Does the persona selector stay visible to a "real" user at all?** The plan keeps it inside the
   demo panel, always visible. Alternatives: collapse the panel by default; hide it behind a
   `?demo=1` query param; keep it only for `admin`. The last one re-creates the role step the owner
   wants removed.
4. **Should a demo prompt still submit on one click**, or prefill the composer for review? Prefill
   is safer (today a misclick irreversibly posts a foreign turn) but costs the grader a keystroke.
5. **Does `HR admin` remain a selectable persona** once the dashboard is open to everyone? It is
   still needed for the three write endpoints and for privileged `/chat` options — but the eval
   runner reaches admin via the `X-Actor` header, not the picker, so the option could be dropped
   from the UI entirely.
6. **Restoring a conversation.** Chat currently loses the transcript on any reload. Is
   `GET /?session=<id>` rehydration in scope (it is what makes "Continue this conversation in chat"
   honest), or should the dashboard's action be labelled "Back to chat (starts a new conversation)"?
7. **Brand and colour.** The plan reuses the existing tokens (`--accent #1f6f6b`, `--warn`,
   `--danger`) and introduces no new palette. Is there a Mosaic Robotics brand to apply — mark,
   type, accent — or does the neutral system stay?
8. **Should the app still identify itself as a demo?** The plan puts the "recorded script /
   simulated writes" disclosure in the demo panel only. A persistent `DEMO` pill in the masthead is
   more honest but permanently marks the product as not-real.
9. **Dashboard audience.** The page ledes are written for an HR admin. If the audience is really
   the technical grader, keep the technical nouns primary and skip the glossary page (saves ~half a
   day of W4).
10. **Is a browser-based test dependency acceptable?** The screenshot/geometry regression suite
    needs `playwright` as a `dev` extra in `pyproject.toml`. Without it, P7/P11/P12 can only be
    checked by hand at each release.
11. **Tenure and other unit phrasing come from model prose**, not a rendered field. Changing
    "45 months" to "3 years 9 months" means a tool change plus re-recording the stub scripts. Worth
    it, or leave the model's own phrasing alone?
12. **Deleting vs. relocating the eval/tools JSON detail.** W4 replaces truncated JSON cells with
    human summaries and a per-row disclosure. Confirm no grader workflow depends on reading that
    JSON directly out of the table rather than from `Export JSON`.
