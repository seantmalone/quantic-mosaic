# P26 report — the keep-alive is armed on the live service; the documents say so, coherently

**Commit:** `3c6a234` — `P26(docs): the keep-alive is armed on the live service, and every document says so`
**Base:** `54d5756` · branch `main` · nothing pushed · 2,001 tests, unchanged from the 0b6de0a baseline.

---

## What I built

### 1. The fact, and the evidence I re-read

`KEEP_ALIVE_URL=https://mosaic-hr-copilot.onrender.com` and `KEEP_ALIVE_INTERVAL_S=600` were set on
the live Render service on 2026-09-11 at 14:26Z by a single-key PUT. The brief's uptime evidence is
first-hand and I added one fresh reading of my own, with `GET /health` only (the one call the brief
permits against the live URL, no LLM involved):

```
$ curl -sS --max-time 60 https://mosaic-hr-copilot.onrender.com/health
{"status":"ok","app":{"version":"2026.1","git_sha":"34717b52…","uptime_ms":7555036,
 "cold_start":false,"rss_mb":276.9,…,"now":"2026-09-12T00:52:53Z"},…,"degradations":[]}
```

`uptime_ms` 7,555,036 ms = **125.9 minutes at 00:52:53Z**, which matches the brief's 124.5 min at
00:51Z and is more than eight times Render's 15-minute idle timer. That is the argument the
documents now make: an instance with nothing pinging it cannot show an uptime that crosses its own
idle timer.

### 2. The prose, rewritten (brief item 1)

| File | What changed |
|---|---|
| `README.md` § *Cold start* | The conditional clause ("keeps the instance warm **once `KEEP_ALIVE_URL` is set**… still not set on the live service") becomes: the layer *holds the instance awake*, **armed on the live service since 2026-09-11 14:26Z**, with the PUT, the two uptime readings and the spin-down comparison; `render.yaml` carries the value, the `Dockerfile` deliberately does not; the measured numbers are what a visitor gets **if the loop is ever turned off**, and the two ways to turn it off are named. |
| `deployed.md` § *Cold start* table intro | "the behaviour a visitor sees whenever both layers are off … until an operator sets `KEEP_ALIVE_URL`" → "…whenever **both** layers are off. That is not the live service's state today: the in-process layer has been armed on it since 2026-09-11 14:26Z, and this table is what comes back the moment the variable is cleared again." |
| `deployed.md` § *Keep-alive* opener | "conditional on one environment variable that the live service does not carry" → "runs on one environment variable, which **the live service has carried since 2026-09-11 14:26Z**". |
| `deployed.md` primary-layer paragraph | Dropped the stale "**and on the live service as of 2026-09-11**" from the list of places the variable is unset (laptop and CI remain). |
| `deployed.md` arithmetic paragraph | "It is a ceiling for the enabled case; while `KEEP_ALIVE_URL` is unset only the cron's runs touch the service" → "It is the ceiling for the enabled case, and since 2026-09-11 14:26Z that is the case this service is in." The 744-of-750-hour arithmetic and the "suspends … rather than billing anything" sentence are untouched. |
| `deployed.md` **Status** paragraph | Rewritten end to end: "**Status, 2026-09-11 14:26Z: the in-process layer is armed on the live service**", the PUT, the three uptime readings (60 min at 18:37Z; 69 → 86 min across 23:56Z–00:13Z with only two health reads in between; 124.5 min at 00:51Z), the "an instance with nothing pinging it cannot show an uptime that crosses its own idle timer" argument, `render.yaml` and the `Dockerfile`, and the pointer to *How to turn it off*. |
| `deployed.md` § *Environment variables* | The note now says the variable **is set on the live service**, by a single-key PUT at 14:26Z, alongside `KEEP_ALIVE_INTERVAL_S=600`; the section intro records that two further single-key PUTs followed the 2026-09-10 read-back (`MCP_ALLOWED_HOSTS` and the keep-alive pair). |
| `deployed.md` § *Cost* | "once the keep-alive is switched on … has not happened yet" → "now that the keep-alive is armed … which it has been since 2026-09-11 14:26Z". |
| `deployed.md` § *How to turn it off* | **Unchanged** — it already documents both layers (delete the variable → no task on the next boot; GitHub → Actions → *keepalive* → Disable workflow). |
| `docs/architecture.html` `f6-cold` tile | Prose rewritten to the armed state with the PUT time and two uptime readings; the *Mitigations* key row's "(shipped, tested, not switched on)" becomes "while `KEEP_ALIVE_URL` is set, which is set on the live service since 2026-09-11 14:26Z", with the Actions workflow named as the best-effort second layer. No other tile or tooltip mentions the keep-alive (grepped). |
| `docs/demo-script.md` | *Wake the instance first* now says the keep-alive has been armed since 14:26Z so the instance should already be awake — "check it rather than trust it" — and points at `app.uptime_ms` on the `/health` payload; the 6:15 narration line says the ten-minute keep-alive was *turned on* and "has been running on the service since the eleventh". |
| `design-and-evaluation.md` § cold start | Not named in the brief, but it carried the same now-false clause ("which is **not set on the live service**, so the table above is still what a visitor gets"). Corrected to "set there at **14:26Z on 2026-09-11**, after every figure above had been measured and published, so the table is what a visitor gets if the loop is turned off again." |
| design spec §14.4, the keep-alive non-goal note, risk **R-10**, decision **49** | Same flip, with the date and the uptime evidence. The spec is one of the four `PUBLISHED_DOCS` the contract test checks, so leaving it conditional would have failed the new test (see *Ambiguities*). |

### 3. The contract test (brief item 2) — `tests/contract/test_keep_alive.py`

* `CONDITIONAL_MARKERS` → **`ARMED_MARKERS`** (`"armed on the live service since 2026-09-11"`,
  `"is set on the live service"`): every published document must carry one.
* New **`STALE_MARKERS`** (`"not set on the live service"`, `"not been set on the live service"`,
  `"not switched on"`, `"until an operator sets"`, `"once KEEP_ALIVE_URL is set"`): a published
  document carrying any of them fails, and the failure message names which. This replaces the old
  `UNCONDITIONAL_CLAIM` regex, whose prohibition ("the instance is now kept warm") is exactly the
  claim that became **true** at 14:26Z.
* The prose is now normalised with backticks stripped as well as whitespace collapsed, so one marker
  matches a Markdown document and the HTML page alike.
* The test is renamed `test_the_published_keep_alive_claim_names_the_armed_live_service_and_its_date`
  and its docstring says why the wording flipped; the module docstring gains a paragraph —
  "**The document property flipped on 2026-09-11 at 14:26Z**" — carrying the PUT and the uptime
  readings; `test_the_blueprint_carries_the_url_and_the_image_never_does` keeps both invariants
  (`render.yaml` carries the public origin, the `Dockerfile` never bakes it, `.env.example` carries
  the key with no value) and its docstring now explains that the blueprint line is what keeps a
  later apply from *clearing* the operator's value.

### 4. `docs/optimization-log.md` (brief item 3)

Read, not edited — it already carries the corrected status line ("**was set on the live service on
2026-09-11 at 14:26Z** and verified by uptime"). `git status` confirms it is untouched.

### 5. P25 minors (brief item 4)

* **(a)** `design-and-evaluation.md`'s four-column table: the column-2 judge-agreement cell reads
  **"not published (labels are authored per published run)"** instead of "not labelled", and the
  second disclosure gains a clause: the run file `r_1789069158_baseline.json` *does* carry a
  mechanically computed `judge_agreement_rate` of 1.00 (n=8) — I verified that in the file — because
  the harness scores whatever labels it finds and those labels were authored for another run's
  answers, "which is precisely why that number is not published as column 2's agreement figure."
* **(b)** `docs/pre-submission-checklist.md` **SUB.2** keeps its box open but now names the split:
  the `Deployed:`-line half is already `verified` in `docs/requirements-traceability.md` (and held by
  `test_docs_completeness.py`), so the box waits on the second half only — "on the day, open that
  exact link in a private window, signed into nothing, and confirm the app loads". The checklist,
  the traceability row and the traceability header summary now agree.

### 6. `NEEDS-FROM-USER.md` and `CHANGELOG.md` (brief item 5)

* `NEEDS-FROM-USER.md`: the header paragraph and the gate-**2b** block both record that the variable
  **was set on the live service on 2026-09-11 at 14:26Z**, that the self-ping has been holding the
  instance awake since, and that `deployed.md` carries the state, the evidence and both off-switches.
* `CHANGELOG.md`: one dated P26 entry with the PUT, the uptime evidence, the documents touched, the
  test flip and the two P25 minors.

---

## TDD evidence

The document assertion is the only behavioural change, and it was written first.

**Red** (new markers, docs untouched):

```
$ .venv/bin/pytest -q tests/contract/test_keep_alive.py
.....F                                                                   [100%]
E           AssertionError: README.md still says the keep-alive is off (['not set on the live service',
            'once KEEP_ALIVE_URL is set']); it has been armed on the live service since 2026-09-11 14:26Z
1 failed, 5 passed in 1.34s
```

**Still red, one document at a time** — the test walked me through the set, which is what it is for:

```
E  AssertionError: docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md still says the keep-alive is off
   (['not set on the live service', 'not been set on the live service', 'not switched on', 'until an operator sets'])
…
E  AssertionError: docs/architecture.html still says the keep-alive is off
   (['not set on the live service', 'not switched on', 'once KEEP_ALIVE_URL is set'])
```

**Green:**

```
$ .venv/bin/pytest -q tests/contract/test_keep_alive.py
......                                                                   [100%]
6 passed in 1.09s
```

---

## Definition of done — real output, run at the committed tree (`3c6a234`)

```
$ .venv/bin/ruff check . && .venv/bin/pytest -q | tail -4 \
    && .venv/bin/python scripts/check_facts.py | tail -2 \
    && .venv/bin/python scripts/pii_check.py | tail -1
All checks passed!
........................................................................ [ 93%]
........................................................................ [ 97%]
.........................................................                [100%]
2001 passed in 177.11s (0:02:57)
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
```

2,001 tests — the 0b6de0a baseline exactly, no test added or removed — and pristine: no warnings, no
skips reported, `filterwarnings=error` in force. (The same four commands also ran green before the
commit; the run pasted above is the post-commit re-run, so it describes the committed tree.)

---

## Files changed

```
 CHANGELOG.md                                       |  2 +
 NEEDS-FROM-USER.md                                 | 12 ++--
 README.md                                          | 21 +++---
 deployed.md                                        | 77 ++++++++++++----------
 design-and-evaluation.md                           | 13 ++--
 docs/architecture.html                             |  4 +-
 docs/demo-script.md                                |  8 ++-
 docs/pre-submission-checklist.md                   |  6 +-
 .../specs/2026-09-08-hr-agentic-rag-design.md      | 18 ++---
 tests/contract/test_keep_alive.py                  | 68 +++++++++++--------
 10 files changed, 137 insertions(+), 92 deletions(-)
```

No source file under `src/` changed: the loop's behaviour is unaffected by where the variable is set,
and `settings.py` / `web/main.py` / `.env.example` describe the mechanism rather than the live
service's state, so there was nothing to correct there. `docs/optimization-log.md`, `render.yaml`,
the `Dockerfile` and the workflow are untouched. Nothing was staged with `git add -A`; `git status`
is clean apart from the pre-existing untracked `CLAUDE.md`, which I did not touch. `.env` was never
read, printed or staged.

---

## Self-review findings (and what I did about them)

1. **README said "The table above"** — the README has prose figures, not a table. Fixed to "The
   numbers above are what a visitor gets if the loop is ever turned off".
2. **Two paragraphs I edited in `deployed.md` had lines running past the file's ~100-column wrap.**
   Re-wrapped the *Keep-alive* opener and the *Cost* arithmetic paragraph so the diff does not leave
   ragged lines behind.
3. **The `Environment variables` table now had a hole.** The old note explained that `KEEP_ALIVE_URL`
   "belongs in no row of the table above … this one carries none", which stopped being true. I did
   **not** add a table row: `MCP_ALLOWED_HOSTS`, set on the service the same way on the same day, is
   also documented in prose rather than in that table, and adding one row but not the other would
   have been the incoherence this phase exists to remove. Instead the section intro now says two
   further single-key PUTs followed the 2026-09-10 read-back and points at both prose notes.
4. **`design-and-evaluation.md` would have been left contradicting everything else** — it is not in
   the brief's item-1 list and not in the test's `PUBLISHED_DOCS`, but it carried "which is **not set
   on the live service**, so the table above is still what a visitor gets". Corrected; recorded below
   as an ambiguity I resolved.
5. **Stale-wording sweep.** After the edits, `grep` across every tracked `.md`/`.html` outside the
   frozen history (`docs/process/sdd/`, `docs/evidence/`, `CHANGELOG.md`, the plans) finds **no**
   remaining "not set on the live service" / "not switched on" / "until an operator sets" / "once
   `KEEP_ALIVE_URL` is set". `docs/requirements-traceability.md`'s RUBRIC5.6 row keeps "n=3 …, no
   keep-alive" because that is a correct label on a historical measurement, not a claim about today.
6. **The test could have been satisfied cheaply.** `"is set on the live service"` as an armed marker
   is not a substring of `"not set on the live service"`, so a document cannot pass the armed check
   with the old negative sentence; and the stale ban means a document cannot carry both. I checked
   that deliberately rather than assuming it.
7. **YAGNI.** No new test file, no new helper, no source change, no touch to `render.yaml`, the
   `Dockerfile` or the workflow. The one deletion (`UNCONDITIONAL_CLAIM`) removes a rule that now
   forbids a true statement; `re` is still used by the `.env.example` assertion, so no import went
   stale (`ruff` confirms).

---

## Ambiguities, and how I resolved them

1. **The spec is one of the four documents the test pins, but the brief's item 1 does not list it.**
   The brief's item 2 requires markers that pin the new truth across `PUBLISHED_DOCS`, which includes
   `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`. Simplest reading that satisfies both:
   the spec is authoritative for *architecture*, and what changed here is a **fact about the live
   service's state**, which the spec reports in four places (§14.4, the keep-alive non-goal note,
   R-10, decision 49). I updated those four reports of state and changed no design decision, no
   variable name, no contract.
2. **`design-and-evaluation.md` is not listed in item 1.** It carried the same false clause and is a
   graded document; the phase is titled "say so everywhere, coherently". I corrected the one clause
   and nothing else in that paragraph.
3. **"so the three documents agree" (item 4b)** does not name the three. I read them as
   `docs/pre-submission-checklist.md` (the open box), `docs/requirements-traceability.md`'s SUB.2 row
   (`verified` 2026-09-11) and that file's header summary ("4 are now `verified` … **SUB.2** (the
   tokenized `Deployed:` link)"). Both traceability statements cover only the README half, so I took
   the brief's second option — leave the box open and name the half still to be checked on the day —
   rather than ticking a box whose second half genuinely needs a signed-out browser on the day.
4. **Whether to keep banning the "now keeps the instance warm" phrasing.** I dropped that ban: the
   claim it guarded against is now true and the guard would have forced contorted prose. The
   protection a grader actually needs is that the claim travels with its date and evidence, which is
   what `ARMED_MARKERS` requires, and that no document still says the opposite, which is what
   `STALE_MARKERS` newly forbids — a strictly stronger check than the one it replaces.
5. **`docs/demo-script.md` "if it mentions it".** It mentions the keep-alive twice (the *Wake the
   instance first* preamble and the 6:15 narration). I updated both, keeping the narration's point —
   measure first, mitigate second — intact.

---

## Concerns

1. **The stale-marker ban is a substring check, and substrings are blunt.** A future document that
   legitimately needs the phrase "until an operator sets …" about some *other* variable, inside one of
   the four published documents, would fail this test for an innocent reason. The failure message
   names the offending marker, so the fix is obvious, but it is a maintenance cost worth knowing about.
2. **The uptime argument is evidential, not conclusive.** `app.uptime_ms` past 15 minutes proves
   *something* kept the instance awake; the in-process loop is the overwhelmingly likely cause given
   the variable was set at 14:26Z, but the GitHub Actions workflow could in principle have supplied a
   ping in some of those windows. The 23:56Z → 00:13Z window in the documents is the strongest single
   reading (two health reads seventeen minutes apart, both inside one uptime run). The documents say
   "verified by uptime", which is what was observed, and do not claim a per-ping log.
3. **The 744-of-750-hour ceiling is now being spent for real.** With the loop armed, the workspace
   trends to ~744 of 750 free instance-hours a month, and exhausting the budget *suspends* the
   service. `scripts/check_render_hours.py` warns above 600 but never fails; nothing in this phase
   changes that, and the deadline for the graded submission is well inside the current month, but it
   is worth a glance at the Render dashboard before the recording.
4. **One live `GET /health`** is the only network call this phase made; no LLM was called and `.env`
   was never opened.

---

# Fix round 1 — 2026-09-11

## The finding

`docs/optimization-log.md:336-340` — the brief's item 3 declared this file already corrected by the
main session and off-limits, so the implementer read it and left it alone. It was only half
corrected. The *Status* block read:

> **Status: `.github/workflows/keepalive.yml` landed 2026-09-11, after these probes, and an
> in-process self-ping joined it the same day as the primary layer — but that layer starts only when
> `KEEP_ALIVE_URL` is set on the service; it \*\*was set on the live service on 2026-09-11 at
> 14:26Z\*\* and verified by uptime (60 min at 18:37Z, 124 min at 00:51Z next day, with no traffic
> but health reads), so every figure above is still the behaviour a visitor gets; disabling the
> workflow and leaving the variable clear keeps it that way.**

Three defects in one sentence:

1. **A non sequitur.** "it was set … *so* every figure above is still the behaviour a visitor gets"
   — the armed loop is precisely why those figures are *not* what a visitor gets today. The old
   consequent belonged to the old (unset) antecedent and was never rewritten.
2. **A direct contradiction.** "leaving the variable clear keeps it that way" asserts the variable is
   clear, one clause after saying it was set — and contradicts `README.md`, `deployed.md`,
   `design-and-evaluation.md`, `docs/architecture.html` and the spec as they now stand. The file is
   linked from README/deployed.md and is on screen in the demo script's 8:45 segment, so both
   versions of the fact are one click apart for a grader.
3. **Broken emphasis.** The inner `**…**` sits inside an already-bold paragraph, so it renders as
   *un*-bolding, not double emphasis.

Nothing in the suite caught it: `scripts/check_facts.py` does not read this file's prose, and
`tests/contract/test_keep_alive.py`'s `PUBLISHED_DOCS` did not include it.

## What changed

**`docs/optimization-log.md`** — the *Status* block now uses the same framing as every other
document (the table is the no-keep-alive behaviour a visitor gets *if the loop is ever turned off*;
clearing the variable and disabling the workflow is how you get back to it), and the nested bold is
gone (the paragraph now opens and closes with exactly one `**` pair — verified: two occurrences of
`**` across the block). The wording also now carries the armed marker verbatim:

```
**Status: `.github/workflows/keepalive.yml` landed 2026-09-11, after these probes, and an
in-process self-ping joined it the same day as the primary layer. That layer starts only when
`KEEP_ALIVE_URL` is set on the service, and the service now carries it: the self-ping has been
armed on the live service since 2026-09-11 at 14:26Z, verified by uptime (60 min at 18:37Z and
124.5 min at 00:51Z the next day, spanning windows with no traffic but a health read). So the
figures above are what a visitor gets if the loop is ever turned off; clearing the variable and
disabling the workflow puts the service back to them.**
```

The uptime figure is now `124.5 min`, matching the brief's evidence and the other documents, and the
lines re-wrap inside the file's ~100-column limit (longest new line: 95).

**`tests/contract/test_keep_alive.py`** — `docs/optimization-log.md` added to `PUBLISHED_DOCS`, so
the stale/armed marker pair guards it too and this exact regression cannot come back silently. The
`#:` comment above the tuple says why a dated record is in a list of published documents (its
*Status* block is a present-tense claim, it is linked from README/deployed.md, and it is on screen in
the demo script). The test's docstring drops the now-wrong word "four". No assertion logic changed;
no new test file, no helper, no source change.

Checked before adding it: the whole file carries none of `STALE_MARKERS` — the historical entries
describe the 2026-09-11 browser session's defect ("the keep-alive was not keeping anything alive"),
which is not one of the banned phrases and is a correct label on a past observation.

## Verification

```
$ .venv/bin/pytest -q tests/contract/test_keep_alive.py
......                                                                   [100%]
6 passed in 1.18s
```

Marker check on the amended file (the same normalisation the test does — whitespace collapsed,
backticks stripped):

```
$ .venv/bin/python -c "..."
armed: True
stale: []
max line len: 95
```

Every definition-of-done command from the brief:

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
252 files already formatted

$ .venv/bin/pytest -q
........................................................................ [ 97%]
.........................................................                [100%]
2001 passed in 176.68s (0:02:56)

$ .venv/bin/python scripts/check_facts.py
  travel-policy                      md     12 sections
  workplace-conduct                  pdf    13 sections

14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
```

2,001 tests — the `0b6de0a` baseline exactly, no test added or removed — and pristine: no warnings,
no skips. `PUBLISHED_DOCS` grew by one document, not by a test.

Only the two files above were staged. `.env` was never read, printed or staged; no network call and
no LLM call was made in this round; the untracked `CLAUDE.md` was left alone.

## Concerns

1. **`docs/optimization-log.md` is now half history, half live claim, and the test treats the whole
   file as live.** A future dated entry that legitimately quotes the old conditional wording — "until
   an operator sets `KEEP_ALIVE_URL`", as a record of what the docs said before 14:26Z — would fail
   `test_the_published_keep_alive_claim_names_the_armed_live_service_and_its_date` for an innocent
   reason. The failure message names the offending marker, so the diagnosis is immediate; the
   remedies are to scope the check to the *Status* block or to drop the file again. I took the
   coarse, loud version deliberately: this phase exists because a stale sentence survived in exactly
   this file.
2. **The same non sequitur pattern could exist in prose the markers do not reach.** The markers catch
   documents that still say the layer is *off*; they cannot catch a sentence that says "armed" and
   then draws the old conclusion, which is what this finding actually was. I re-read the keep-alive
   paragraph in each of the five `PUBLISHED_DOCS` for that shape and found none, but it is a
   judgement, not an assertion.
