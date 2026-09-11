# P21 report — in-process self keep-alive; resting-state chat UI fixes

Base `753596e` → head `f8690cb`, two commits on `main`, nothing pushed.

| | |
|---|---|
| Commits | `58e06d9` P21(web), `f8690cb` P21(deploy) |
| Tests | 1,911 → **1,916** (+5), all green, output pristine |
| Coverage | **94%** combined (95% statements, 87% branches over 7,135) — gate 90, exit 0 |
| Files changed | 13 (4 source, 2 test, 7 docs/config) |

---

## 1. What was built

### 1.1 The self keep-alive (brief item 1)

`src/hrmosaic/web/main.py` gains `_keep_alive(settings)` and lifespan **step 7**. While the process
is up it GETs `{KEEP_ALIVE_URL}/health` every `KEEP_ALIVE_INTERVAL_S` (default 600) through one
`httpx.AsyncClient` with `KEEP_ALIVE_TIMEOUT_S = 30.0`, logs both outcomes at DEBUG, never raises,
and is cancelled by the same teardown loop that already cancels the warm-up and the maintenance
task. The task is created only when `keep_alive_url` is set, so a laptop, CI and every test server
start no loop and open no socket.

The docstring carries the rationale the brief asked for, in two parts:

* **Why the app pings itself.** Render counts traffic at its *edge*, so a request to the service's
  own public hostname is inbound traffic like any other — it leaves the container, is routed by the
  edge and comes back, resetting the 15-minute idle timer exactly as a visitor's would. Hence the
  URL must be the public origin; a loopback ping would keep nothing awake.
* **Why it is primary and the cron secondary.** GitHub's scheduler is best-effort and
  de-prioritises low-traffic repositories: the `*/10` schedule ran **twice in nine hours** (09:48Z
  and 13:53Z on 2026-09-11, both green) instead of ~54, and the instance was found spun down at
  14:25Z. This loop needs no scheduler and runs whenever the instance is up — which is exactly when
  a ping is needed. The two layers cover each other's gap: the cron can wake an instance the loop
  cannot run in.

The wait comes **before** the first ping, and the docstring says why: the boot that started the
task was itself inbound traffic.

Two settings joined `settings.py` (a new `# --- keep-alive ---` block after `# --- misc ---`),
`.env.example` and spec §12.3's table, one sentence each:

| Variable | Default | Purpose |
|---|---|---|
| `KEEP_ALIVE_URL` | *(unset ⇒ no task is started)* | the service's own **public** origin, GETed at `/health` so Render's edge sees inbound traffic |
| `KEEP_ALIVE_INTERVAL_S` | `600` | seconds between those self-pings — inside the 15-minute idle timer, with headroom |

`tests/contract/test_env_example_covers_settings.py` (the bijection, both directions) is green
unchanged.

### 1.2 The workflow and the documents (brief item 2)

`.github/workflows/keepalive.yml` keeps every executable line — schedule, `permissions: {}`,
timeout, the curl budget, the exit-0 discipline — and every assertion in
`tests/contract/test_keepalive_workflow.py` still passes untouched. Only the header comment
changed: it now opens with "The SECOND layer of the keep-alive", states the measured scheduler
behaviour and names `web/main.py`'s `_keep_alive` as the primary mechanism, and says why the file
stays (it is the only layer that can wake an already-sleeping instance).

`deployed.md` § *Cold start* → *Keep-alive* is rewritten as two layers: the in-process task first
with its contract, then the cron with the two-runs-in-nine-hours measurement as the reason for the
order. Three related passages were brought into line rather than left contradicting it:

* the intro to the measured table ("the behaviour a visitor sees again the moment **both**
  keep-alive layers below are turned off");
* *How to turn it off* — now names both levers (clear `KEEP_ALIVE_URL` on Render, then disable the
  workflow), still no commit needed for either;
* § *Cost* → *The instance-hour arithmetic* — **explicitly unchanged**: 744 of 750 is the ceiling
  for both layers together, because an awake instance is counted once however many things ping it.

The § *Environment variables* table gains a note that `KEEP_ALIVE_URL` is the one variable that
switches a behaviour on rather than tuning one, and that setting it is a single-key PUT with no
rebuild.

Spec: §14.4's mitigation paragraph rewritten around the two layers; new §21 **row 49**
("Where the keep-alive lives"); two rows in §12.3. README's deployment section: one sentence
replacing the "a ten-minute GitHub Actions keep-alive … now keeps the instance warm" clause.

### 1.3 The resting-state UI (brief item 3)

**Root cause, and it is one cause for both symptoms.** `#cold-start-banner` and
`#provisional-answer` have carried the `hidden` attribute since they were written — but the
user-agent sheet's `[hidden] { display: none }` is beaten by *any* author `display:` declaration,
and `app.css` sets `.banner { display: flex }` (line 55) and `.turn { display: flex }` (line 76).
So both elements were painted at rest, and `element.hidden = true` could not remove either: the
"Waking the free instance…" strip stayed on screen for the whole session after `/health` answered,
and an empty preview box sat under its "Writing the answer…" caption before any question was asked.

The fix is one declaration near the top of `app.css`:

```css
[hidden] { display: none !important; }
```

With the switch working, the streaming logic that was already correct starts taking effect: the
preview is revealed by `answerDelta()` on the first `answer_delta` frame and hidden again by
`clearProvisional()` on `turn_completed` (and on `htmx:afterSwap`, the other half of the hard
replace). No JavaScript was needed for (a).

For (b), the preflight IIFE now defers the reveal by `COLD_START_BANNER_DELAY_MS = 1200` and
cancels it when `/health` settles, so the banner describes the only state it names — a request that
is actually waiting. The page was itself served by the instance, so on a warm one the preflight
answers in milliseconds and the banner is never painted at all; the counter still runs from when
the request was made, not from when the strip appeared.

The `[hidden]` rule is global and therefore also covers the dashboard's `hidden` tab panels and
`session_detail.html`'s row toggle. Neither changes behaviour (`.panel` / `.tab-panel` set no
`display`, so the UA rule already applied there) — the declaration can only ever hide *more*, which
is the intent everywhere `hidden` is used.

---

## 2. TDD evidence

### 2.1 The keep-alive — red, then green

The four tests were written first and run against the unmodified source (`git stash push --
src/hrmosaic/web/main.py src/hrmosaic/settings.py .env.example`):

```
FAILED tests/contract/test_keep_alive.py::test_no_task_is_started_when_the_url_is_unset
FAILED tests/contract/test_keep_alive.py::test_the_task_is_started_when_the_url_is_set
FAILED tests/contract/test_keep_alive.py::test_shutdown_cancels_the_task - At...
FAILED tests/contract/test_keep_alive.py::test_the_loop_pings_public_health_on_its_schedule_and_survives_a_failure
4 failed in 1.74s
```

(the last one on `AttributeError: module 'hrmosaic.web.main' has no attribute 'httpx'`, the first
three on the absent `keep_alive_url` field). After `git stash pop`:

```
....                                                                     [100%]
4 passed in 1.33s
```

### 2.2 The resting-state UI — red, then green

The new contract test was written first and run against the unmodified stylesheet:

```
>       assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}", css), (
            "`hidden` must beat every author `display:` rule, or neither area can be hidden at all"
        )
E       AssertionError: `hidden` must beat every author `display:` rule, or neither area can be hidden at all
E       assert None
tests/contract/test_chat_page_renders.py:64: AssertionError
1 failed, 9 deselected in 1.57s
```

After the `app.css` declaration and the deferred reveal:

```
..............                                                           [100%]
14 passed in 5.96s
```

(`test_chat_page_renders.py` + `test_keep_alive.py` together.)

### 2.3 What the new tests assert

`tests/contract/test_keep_alive.py` — the four the brief names:

* `test_no_task_is_started_when_the_url_is_unset` — `app.state.keep_alive is None`;
* `test_the_task_is_started_when_the_url_is_set` — a live, not-done task;
* `test_shutdown_cancels_the_task` — `task.cancelled()` after the lifespan exits;
* `test_the_loop_pings_public_health_on_its_schedule_and_survives_a_failure` — with a patched
  `asyncio.sleep` and a stand-in client: `waits == [600, 600, 600, 600]` (the wait comes first),
  `pings == ["https://mosaic-hr-copilot.onrender.com/health"] * 3` (a trailing slash on the
  configured origin is stripped, and the second ping raised `httpx.ConnectError` without stopping
  the loop), `timeouts == [KEEP_ALIVE_TIMEOUT_S]`.

The first three drive the **real** lifespan (`create_app(...)` through
`app.router.lifespan_context(app)`) with no socket bound, so nothing in them can reach the network.
The fourth replaces the HTTP client because the alternative is a test that talks to the internet;
everything it asserts — the URL built, the order of wait and ping, the timeout applied, the
survival of a refused connection — is the loop's own behaviour, not the stand-in's.

`test_chat_page_renders.py::test_at_rest_the_page_carries_neither_a_banner_nor_an_empty_answer_preview`
asserts on the served HTML and the served CSS: both elements carry `hidden` in the markup, the
`[hidden] { display: none !important }` rule is in `/static/app.css`, the preview's two toggles
exist, and inside the preflight IIFE the reveal is deferred (`COLD_START_BANNER_DELAY_MS`,
`setTimeout(`), occurs exactly once, and is cancelled (`clearTimeout(reveal)`) by the settle handler
that also hides the banner. **No existing assertion was weakened**: the two pre-existing
`id="cold-start-banner"` / `id="provisional-answer"` assertions stand as they were and the new test
tightens them to the full element markup including `hidden`.

---

## 3. Definition of done — real output

### `ruff check .` / `ruff format --check .`

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
244 files already formatted
```

### `pytest -q` — the whole suite

```
$ LLM_PROVIDER=stub ./.venv/bin/pytest -q
........................................................................ [ 93%]
........................................................................ [ 97%]
............................................                             [100%]
1916 passed in 169.32s (0:02:49)
```

Pristine: no warnings, no skips, no xfails (`filterwarnings = ["error"]` is on). 1,911 at
`753596e` → 1,916, the +5 being the four keep-alive tests and the one resting-state test.

### `make coverage` — the 90% gate

```
$ LLM_PROVIDER=stub make coverage
1916 passed in 196.67s (0:03:16)
src/hrmosaic/web/main.py                                    173     10     14      1    94%
TOTAL                                                      7135    315   1432    166    94%
exit=0
```

Read off `coverage json`: 95.59% of statements, 87.29% of branches, 94.20% combined. `web/main.py`
gained 19 statements and stayed at 94%.

### `check_facts.py`, `pii_check.py`, `--verify-manifest` — unchanged

```
$ ./.venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
check_facts exit=0

$ ./.venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
pii_check exit=0

$ ./.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  totals      14     204    30840
  index    data/index/hr_index.sqlite
OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
verify-manifest exit=0
```

### `make demo1` then `make demo2`, separately

```
$ make demo1
...
   27  guardrail      G6_pii_secret_redaction           0 ms  verdict=allow · final answer carried nothing to redact
-- usage: 5 model call(s), 7 tool call(s), 5 retrieval(s), 31985→1797 tokens in 431 ms
-- dashboard: /dashboard/sessions/338dd209a8de6149796c185e9c925020#turn-1
make demo1 exit=0

$ make demo2
...
   24  confirmation   create_mock_hr_ticket             0 ms  create_mock_hr_ticket · confirmed
   25  tool_call      create_mock_hr_ticket             7 ms  create_mock_hr_ticket · ok
        result {"status": "created", "ticket_id": "MOCK-HR-000014", "queue": "hr-timeoff", ...}
   30  guardrail      G6_pii_secret_redaction           0 ms  verdict=allow · final answer carried nothing to redact
-- usage: 7 model call(s), 6 tool call(s), 2 retrieval(s), 38858→1713 tokens in 490 ms
-- dashboard: /dashboard/sessions/0f69599872a5c0083151a1c015801aaa#turn-1
make demo2 exit=0
```

### Contract suite after the documentation edits

```
$ LLM_PROVIDER=stub ./.venv/bin/pytest -q tests/contract
304 passed in 70.99s (0:01:10)
```

(`test_docs_completeness`, `test_keepalive_workflow`, `test_readme_headings`,
`test_env_example_covers_settings` and `test_deploy_manifests` are all in there.)

---

## 4. Files changed

**`58e06d9` — P21(web)**

| File | What |
|---|---|
| `src/hrmosaic/web/main.py` | `_keep_alive()`, `KEEP_ALIVE_TIMEOUT_S`, lifespan step 7, teardown cancellation, `app.state.keep_alive`, docstring step 7, `__all__` |
| `src/hrmosaic/settings.py` | `keep_alive_url`, `keep_alive_interval_s` |
| `.env.example` | the two keys with `OPTIONAL` markers |
| `src/hrmosaic/web/static/app.css` | `[hidden] { display: none !important; }` with the reason |
| `src/hrmosaic/web/templates/chat.html` | the deferred banner reveal |
| `tests/contract/test_keep_alive.py` | new, 4 tests |
| `tests/contract/test_chat_page_renders.py` | +1 resting-state test |

**`f8690cb` — P21(deploy)**

| File | What |
|---|---|
| `deployed.md` | Keep-alive rewritten as two layers; table intro, *How to turn it off*, instance-hour arithmetic and the env-var section brought into line |
| `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` | §14.4 rewritten; §21 row 49; two §12.3 rows |
| `.github/workflows/keepalive.yml` | header comment only |
| `README.md` | one sentence in *Cold start*; the test/statement counts |
| `design-and-evaluation.md`, `docs/requirements-traceability.md` | the test/statement counts |

`docs/optimization-log.md` was not touched. `.env` was never read, printed or staged. No live LLM
call was made (`LLM_PROVIDER=stub` throughout); the live URL was not contacted at all.

---

## 5. Self-review

Read the diff against the brief line by line after it was written. What that turned up:

1. **Stale published counts.** The diff added 5 tests and 20 statements while three documents
   stated "1,911 tests" / "7,115 statements" as of 2026-09-11. P20 set the precedent of
   re-measuring; left alone, this commit would have made three published facts false. Re-measured
   off `coverage json` and updated (1,916 / 7,135). The percentages did not move (95 / 87 / 94).
2. **`deployed.md` had three passages the rewrite would have contradicted** — the table's
   "the moment the keep-alive below is disabled", *How to turn it off* (one menu is no longer
   enough), and the 744-hour paragraph, which named only the workflow. All three amended; the
   arithmetic itself is stated as unchanged and why.
3. **`deployed.md` § *Environment variables*** documents what the deployed service sets, and
   `KEEP_ALIVE_URL` is the one new variable that is not merely a tuning knob. Added as a note under
   the table rather than a row, because a row would have to claim the live service carries a value
   I have not verified (see concern 1).
4. **The `[hidden]` rule is global** — checked every other use of `hidden` in the templates
   (`dashboard/eval_detail.html`, `dashboard/evals.html`, `dashboard/session_detail.html`) and every
   author `display:` rule that could apply. `.panel` / `.tab-panel` set none, so nothing else
   changes behaviour, and the declaration can only hide more.
5. **YAGNI pass on `_keep_alive`.** No retry, no backoff, no jitter, no `/health` body parsing, no
   span, no `/health` field: one GET, one DEBUG line. The single `assert settings.keep_alive_url is
   not None` is a stated precondition in the same style as this module's existing
   `assert isinstance(exc, HTTPException)`, and the caller is three lines away.
6. **Test quality.** The three lifespan tests drive the real lifespan rather than inspecting a
   flag; the loop test's stand-in client exists only because the alternative is network access, and
   every assertion in it is about the loop. The UI test asserts on served bytes (HTML *and* CSS),
   which is what a grader actually loads.
7. **Pristine output.** Verified with `filterwarnings = ["error"]` on and no `-W` override: 1,916
   passed, nothing else on stdout.

---

## 6. Ambiguities resolved

1. **"the spec's env table (§21 / §11)".** The env table is §12.3, not §21 or §11. Took the
   reading that covers every candidate: two rows in **§12.3's table** (the table itself), a new
   decision row in **§21** (row 49, where decisions of this kind live), and the rewritten
   mitigation paragraph in **§14.4** (which §11.5's banner sentence points at). Nothing was added
   to §11.
2. **"only show it while a request is actually waiting" vs. §11.5's preflight-driven banner.** A
   literal zero-delay reveal satisfies the words — the banner would be up only while the preflight
   is in flight — but on a warm instance that is a yellow strip flashing on every page load, which
   trades one visual defect for another. Took the reading that honours all three constraints (the
   spec's "`/health` preflight with an elapsed counter", "hide it as soon as the first `/health`
   **or the page's own load** succeeds", and "only while a request is actually waiting"): the
   reveal is deferred 1.2 s and cancelled when the preflight settles, so a warm load — which the
   page's own arrival already proves — never paints it, and a genuinely slow one still gets the
   banner with a counter that runs from the request, not from the reveal.
3. **Ping first or wait first?** The brief says "every `KEEP_ALIVE_INTERVAL_S` it GETs". Waiting
   first, because the boot that starts the task is itself inbound traffic and the timer has just
   been reset; documented in the docstring and pinned by `waits == [600, 600, 600, 600]`.
4. **`render.yaml` was not touched.** See concern 1 — the brief specifies "default unset → task not
   started" and says nothing about the blueprint, and `test_deploy_manifests.py` pins the plain-value
   set by exact equality.

---

## 7. Concerns

1. **The feature is inert on the live service until `KEEP_ALIVE_URL` is set there.** This is the
   one thing standing between the code and the outcome Sean asked for, and it is an ops action this
   subagent cannot take: a single-key PUT (or a dashboard Environment entry) with
   `KEEP_ALIVE_URL=https://mosaic-hr-copilot.onrender.com`, no rebuild needed, which restarts the
   instance and starts the loop. Deliberately **not** added to `render.yaml`: the brief scoped the
   variable's default as unset, and `test_deploy_manifests.py::test_the_plain_values_pin_the_environment…`
   asserts the blueprint's plain-value set by exact equality, so putting it there is a contract
   change the brief did not authorise. Say the word and it is a two-line follow-up.
2. **The banner delay is a judgement call, not a brief-specified constant.** 1.2 s was chosen so a
   warm load (milliseconds) never flashes and a slow one still explains itself. If the reviewer
   prefers the strictly literal reading — reveal immediately, hide on settle — deleting the
   `setTimeout` wrapper and the three assertions that pin it restores it; the `[hidden]` fix, which
   is the actual defect, is independent of that choice.
3. **The UI assertions are string matches on served HTML/CSS**, as every UI assertion in this
   repository is — there is no JS runtime in the suite. They pin the markup, the stylesheet rule
   and the shape of the preflight, not a rendered layout; a future refactor that renames
   `coldStartPreflight` or reformats the IIFE will need them updated. That is the existing contract
   style of `test_chat_page_renders.py`, not something new here.
4. **The two-runs-in-nine-hours figure is quoted from the brief's finding**, not re-measured in
   this session (doing so would mean reading the Actions API). It is stated with its date, times
   and both run outcomes everywhere it appears, so it is checkable against the Actions tab.
5. **No coverage of the keep-alive on a real socket.** The loop is proven against a stand-in client
   and the lifespan wiring against the real lifespan; nothing in the suite makes an actual HTTP
   round trip to a public origin, and nothing should. The first real evidence will be a DEBUG line
   in the Render log, or simply an instance that is still warm ten minutes after the last visitor.

---

# P21 fix round 1 — the keep-alive claim is conditional, because the variable is unset

Review finding (Important, `README.md:112`): P21 replaced the cron's disproved "now keeps the
instance warm" with a second unconditional claim — that the in-process self-ping "now keeps the
instance warm (`KEEP_ALIVE_URL`)" — while `KEEP_ALIVE_URL` is set nowhere in the repository and is
not set on the live service. A grader reading the README would expect a warm instance and get the
published 71.0 s cold start.

**Option taken: qualify, not enable.** The finding offered two fixes. Setting the variable on the
live service needs the Render API key, which lives in `.env` — a file this phase's constraints
forbid reading — so it is not an action this session can take honestly. Every published passage is
therefore moved to the conditional, and the state of the switch is published as a fact with a date.
Enabling it later is one single-key PUT; the documents now name exactly which lines change when
someone does.

## 1. What changed

### 1.1 The three passages the finding names

| File | Was | Now |
|---|---|---|
| `README.md` § *Cold start* | "a two-layer keep-alive … **now keeps the instance warm**: the app pings its own public `/health` … (`KEEP_ALIVE_URL`)" | "keeps the instance warm **once `KEEP_ALIVE_URL` is set on the service**" + "That variable is **unset by default and this repository does not set it** — neither `render.yaml` nor the `Dockerfile` carries a value — so until an operator sets it … the numbers above are still exactly what a visitor gets" |
| `deployed.md` § *Cold start* → *Keep-alive* | "**The primary layer is in the application.** … Unset `KEEP_ALIVE_URL` — the default, and the case on a laptop and in CI" | same paragraph + "**and on the live service as of 2026-09-11**", a pointer in the subsection's opener, and a new **Status** paragraph: "the in-process layer is shipped but not switched on … set nowhere in this repository … not been set on the live service … Turning it on is one single-key PUT … of `KEEP_ALIVE_URL=https://mosaic-hr-copilot.onrender.com`" |
| spec §14.4 | "… never created at all when the variable is unset." then straight on to the cron | "— which, as of 2026-09-11, is its state everywhere: `KEEP_ALIVE_URL` is set in no file of this repository (not `render.yaml`, not the `Dockerfile`) and has not been set on the live service, so **this layer is shipped and tested but not switched on** … Nothing above or below claims otherwise." |

### 1.2 The passages that would have contradicted the qualification

Left alone, five more passages would have kept the same over-claim alive one level down:

* `deployed.md` table intro — "the moment **both** keep-alive layers below are turned off" → "whenever both … are off, which is the in-process layer's state until an operator sets `KEEP_ALIVE_URL`";
* `deployed.md` *The arithmetic below is unchanged* — now says the 744 ceiling "is a ceiling for the enabled case; while `KEEP_ALIVE_URL` is unset only the cron's best-effort runs touch the service";
* `deployed.md` § *Cost* → the instance-hour arithmetic — "**after** the keep-alive … keeps the instance awake round the clock **from 2026-09-11**" → "**once the keep-alive is switched on** … as soon as `KEEP_ALIVE_URL` is set on the service — which, as that subsection's status line records, has not happened yet";
* `deployed.md` § *Environment variables* note — now states outright "**It is not set on the live service as of 2026-09-11**, so it belongs in no row of the table above: the rows record values the service carries, and this one carries none";
* spec §14.4 cost sentence, spec §21 row 49, spec §3 non-goals bullet and risk **R-10** — each gains "once it is switched on" / "set nowhere in the repository and not on the live service".

### 1.3 Two documents the review did not name and that carried the same defect

`grep -rn "keeps the instance"` over the repository found the claim in a third graded artifact:

* **`docs/architecture.html`**, node `f6-cold` — still the *pre-P21* over-claim ("the ten-minute
  /health pinger added on 2026-09-11 **keeps the instance warm**", naming only the workflow). Both
  its prose and its *Mitigations* key row now describe the two layers and say the primary one is
  "shipped, tested, not switched on".
* **`design-and-evaluation.md`** and **`docs/optimization-log.md`** described the mitigation as the
  GitHub workflow alone. Both now name the in-process layer and state that it "is **not set on the
  live service**, so the table above is still what a visitor gets".

### 1.4 A test that keeps it honest

`tests/contract/test_keep_alive.py` gains
`test_the_published_keep_alive_claim_stays_conditional_while_nothing_sets_the_url`, which asserts
both halves of the fact the documents now publish:

* `render.yaml` and the `Dockerfile` contain no `KEEP_ALIVE_URL`, and `.env.example` carries the key
  with an empty value (`^KEEP_ALIVE_URL=\s*(#|$)`) — so the day the repository *does* set it, this
  test fails rather than the documents quietly going stale in the other direction;
* each of `README.md`, `deployed.md`, spec and `docs/architecture.html`, whitespace-normalised,
  matches no `\b(now|already|does)\s+keeps?\s+the\s+instance\s+(warm|awake)\b` and contains at least
  one of six precondition markers ("once `KEEP_ALIVE_URL` is set", "is set nowhere in this
  repository", "not set on the live service", "not switched on", …).

The published counts moved with it: 1,916 → **1,917** in `README.md`, `design-and-evaluation.md`
and `docs/requirements-traceability.md`.

## 2. Red, then green

The new test run against the three documents as the review found them (`git stash push -- README.md
deployed.md docs/superpowers/specs/…`):

```
E           AssertionError: README.md claims the instance is being kept warm; it is not, until an operator sets KEEP_ALIVE_URL on the service
E           assert not <re.Match object; span=(6583, 6610), match='now keeps the instance warm'>
tests/contract/test_keep_alive.py:202: AssertionError
FAILED tests/contract/test_keep_alive.py::test_the_published_keep_alive_claim_stays_conditional_while_nothing_sets_the_url
1 failed, 4 passed in 1.25s
```

After `git stash pop` and the document edits:

```
$ LLM_PROVIDER=stub ./.venv/bin/pytest -q tests/contract/test_keep_alive.py
.....                                                                    [100%]
5 passed in 1.19s
```

Tests covering the amended files (the doc-contract set — headings, README, workflow, env bijection,
deploy manifests, keep-alive):

```
$ LLM_PROVIDER=stub ./.venv/bin/pytest -q tests/contract/test_keep_alive.py \
    tests/contract/test_docs_completeness.py tests/contract/test_readme_headings.py \
    tests/contract/test_keepalive_workflow.py tests/contract/test_env_example_covers_settings.py \
    tests/contract/test_deploy_manifests.py
94 passed in 1.27s
```

## 3. Definition of done — real output, re-run in full

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
244 files already formatted
```

```
$ LLM_PROVIDER=stub ./.venv/bin/pytest -q
........................................................................ [ 97%]
.............................................                            [100%]
1917 passed in 168.01s (0:02:48)
```

Pristine — no warnings, skips or xfails, with `filterwarnings = ["error"]` on. 1,916 → 1,917, the
+1 being the documentation-contract test.

```
$ LLM_PROVIDER=stub make coverage
1917 passed in 195.03s (0:03:15)
src/hrmosaic/web/main.py                                    173     10     14      1    94%
TOTAL                                                      7135    315   1432    166    94%
exit=0
```

(No source file changed, so the 7,135 statements and the 94% are unmoved.)

```
$ ./.venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
check_facts exit=0

$ ./.venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
pii_check exit=0

$ ./.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  totals      14     204    30840
OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
verify-manifest exit=0
```

```
$ make demo1
   27  guardrail      G6_pii_secret_redaction           0 ms  verdict=allow · final answer carried nothing to redact
-- usage: 5 model call(s), 7 tool call(s), 5 retrieval(s), 31985→1797 tokens in 419 ms
-- dashboard: /dashboard/sessions/aaff754a7ab8d8380e789ac557e2a36d#turn-1
make demo1 exit=0

$ make demo2
   30  guardrail      G6_pii_secret_redaction           0 ms  verdict=allow · final answer carried nothing to redact
-- usage: 7 model call(s), 6 tool call(s), 2 retrieval(s), 38858→1713 tokens in 483 ms
-- dashboard: /dashboard/sessions/edac14254a40d585ca3128e494990d94#turn-1
make demo2 exit=0
```

`.env` was never read, printed or staged; nothing was pushed; no live LLM call was made
(`LLM_PROVIDER=stub` throughout) and the live URL was not contacted.

## 4. Files changed

| File | What |
|---|---|
| `README.md` | § *Cold start* claim made conditional; 1,916 → 1,917 |
| `deployed.md` | table intro, *Keep-alive* opener, primary-layer paragraph, arithmetic note, new **Status** paragraph, § *Environment variables* note, § *Cost* arithmetic |
| `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` | §14.4 (state + cost), §21 row 49, §3 non-goals bullet, risk R-10 |
| `docs/architecture.html` | `f6-cold` prose and its *Mitigations* key row |
| `design-and-evaluation.md`, `docs/optimization-log.md` | the mitigation described as two layers, the primary one off; test count |
| `docs/requirements-traceability.md` | test count |
| `tests/contract/test_keep_alive.py` | +1 documentation-contract test, module docstring's fifth property |

## 5. Concerns after the fix

1. **The outcome Sean asked for is still one ops action away.** The documents are now true, which
   is what the finding required, but the instance is still cold on a grader's first click. The
   single-key PUT of `KEEP_ALIVE_URL=https://mosaic-hr-copilot.onrender.com` remains open, and
   `deployed.md`'s new **Status** paragraph is written to be the one line that changes when it is
   done (plus the § *Environment variables* note and the README clause it points at).
2. **The guard test reads prose, not meaning.** It bans one regex family and requires one of six
   marker phrases per document; a new over-claim phrased differently ("the instance stays warm")
   would pass it. It is a regression guard for this specific defect, not a fact-checker — the
   repository has no such thing and this fix does not pretend to add one.
3. **`docs/architecture.html` was stale independently of P21** — it still described a one-layer
   cron mitigation. Fixed here because it carried the very claim the finding is about, but it is
   worth a separate read-through for other P20/P21-era drift.
