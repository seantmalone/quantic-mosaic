# P17 report — GitHub Actions keep-alive, n=3 cold-start table, gitleaks, deploy-doc fixes

Base: `dbe7945` on `main`. Commit: **`3d38ae5`** — `P17(deploy): GitHub Actions keep-alive, and the
deploy docs stop naming the hook`. Nothing pushed.

---

## 1. What landed

### `.github/workflows/keepalive.yml` (new)

Every property the brief names, in the file:

| Brief | In the workflow |
|---|---|
| `schedule: cron: "*/10 * * * *"` + `workflow_dispatch` | both, under `on:` |
| one job, `ubuntu-latest` | `jobs.ping`, `runs-on: ubuntu-latest`, no checkout step |
| `permissions: {}` | on the job, as the brief lists it among the job's attributes |
| curl `GET $DEPLOY_URL/health`, URL from repository variable `DEPLOY_URL`, falling back to the committed live URL | `env.DEPLOY_URL: ${{ vars.DEPLOY_URL \|\| 'https://mosaic-hr-copilot.onrender.com' }}`, then `"${DEPLOY_URL%/}/health"` |
| `--retry 3`, 60 s max time | `--retry 3 --retry-delay 5 --retry-all-errors --retry-max-time 60 --max-time 60` |
| print `status`, `app.cold_start`, `app.uptime_ms` | one `jq` interpolation over the payload |
| never fails the repo's status on a transient error (exit 0 + warning) | any failure → `::warning::` + `exit 0`; the run block contains no `exit 1` and no command that can end it non-zero |
| a job-summary line so a suspended instance is visible in the Actions tab | both branches append to `$GITHUB_STEP_SUMMARY` |
| no secrets | the file contains no `secrets.` reference at all (asserted by a test) |

**Proved against the live service, not just asserted.** The step's `run:` block was extracted from
the YAML with PyYAML and executed verbatim under `bash -e`:

```
$ DEPLOY_URL="https://mosaic-hr-copilot.onrender.com" GITHUB_STEP_SUMMARY=…/summary.md bash -e keepalive_step.sh
awake — status=ok  app.cold_start=true  app.uptime_ms=27582
exit=0
--- job summary ---
**Awake.** `https://mosaic-hr-copilot.onrender.com/health` — status=ok  app.cold_start=true  app.uptime_ms=27582
```

And the failure path, with an unresolvable host (this is the only other live-ish call made; no LLM
was contacted at any point):

```
$ DEPLOY_URL="https://mosaic-hr-copilot.onrender.invalid" GITHUB_STEP_SUMMARY=…/summary2.md bash -e keepalive_step.sh
curl: (6) Could not resolve host: mosaic-hr-copilot.onrender.invalid      ← ×4 (1 + --retry 3)
::warning::no usable /health payload from https://mosaic-hr-copilot.onrender.invalid/health inside the 60 s budget — …
exit=0
--- job summary ---
**No answer.** `https://mosaic-hr-copilot.onrender.invalid/health` returned no usable `/health` payload within 60 s — …
```

### `tests/contract/test_keepalive_workflow.py` (new, 11 tests)

Valid YAML; exactly one `ubuntu-latest` job; the cron's minute field parses to `*/N` with `N ≤ 10`;
`workflow_dispatch` present; `permissions == {}`; `0 < timeout-minutes ≤ 2`; the fallback URL is the
**origin parsed out of `README.md`'s own `Deployed:` line** (so the workflow cannot drift onto some
other host) and `/health` is pinged; `--retry 3` and `--max-time 60`; all three of `.status`,
`.app.cold_start`, `.app.uptime_ms` are read; no `exit 1` anywhere in the run block, with `exit 0`
and `::warning::` present; `$GITHUB_STEP_SUMMARY` written; no `secrets.` in the file.

### Documentation

* **`deployed.md` § Cold start** is now three `###` subsections: **Measured without keep-alive**
  (the n=3 table, verbatim as it was), **Keep-alive** (directly under it), **The part the image
  controls**. The Keep-alive subsection covers what it does, the 24 × 31 = **744 of 750** hours,
  suspension-not-billing, and how to turn it off (Actions → keepalive → Disable workflow). One
  sentence in the table's lead was retensed — it claimed a grader "will actually see" the cold
  start, which stopped being true the moment the pinger landed; it now says this is the instance
  with nothing touching it, and what a visitor sees again when the keep-alive is disabled.
  § Cost gains one paragraph: the month's instance-hours now trend to ~744 **by design**.
* **`README.md`** — one sentence, replacing the "queued decision" sentence.
* **Spec §14.4** — "No keep-alive cron" replaced by the dated decision, the ordering argument and
  the cost. Three follow-ons so the spec does not contradict itself: the §1 non-goal bullet, the
  R-10 mitigation cell, and the repo-layout tree (which said `ONE workflow`).
* **`scripts/check_render_hours.py`** — docstring records that ~744 is now the expected shape of a
  full month, and that the 600-of-750 warning firing around the 25th means the budget is being
  spent as designed. `INSTANCE_HOURS_WARN = 600` / `INSTANCE_HOURS_BUDGET = 750` are untouched.
* **`design-and-evaluation.md`** — the deployment paragraph no longer says the workflow is queued
  and that `.github/workflows/` holds only `ci.yml`.
* **`CHANGELOG.md`** — one dated entry (repo convention: every phase commit carries one).

### gitleaks (brief item 4)

gitleaks **8.30.1** (`darwin_arm64`, downloaded into the scratchpad only) over the full history,
**before** any change:

```
$ gitleaks detect --source . --config .gitleaks.toml --redact -v
Finding:     ...pilot.onrender.com/?access=REDACTED
Secret:      REDACTED
RuleID:      generic-api-key
Entropy:     4.943593
File:        README.md
Line:        10
Commit:      a6b1f02ae7198a9df330a7b792a8879cd3a05c1d
Fingerprint: a6b1f02ae7198a9df330a7b792a8879cd3a05c1d:README.md:generic-api-key:10
8:16PM INF 116 commits scanned.
8:16PM WRN leaks found: 1
```

So the README line **is** flagged, exactly as the brief anticipated. The narrowest possible
carve-out was added (a new `[[allowlists]]` block; no existing allowlist was touched or widened):
`targetRules = ["generic-api-key"]`, `condition = "AND"`, `paths = ['''^README\.md$''']`,
`regexTarget = "line"`, `regexes = ['''\?access=[A-Za-z0-9_-]{43}(?:\b|$)''']`, with a comment
stating that the token is public by design (§11) and where it is rotated (`deployed.md` § Access).

After:

```
$ gitleaks detect --source . --config .gitleaks.toml --redact
8:35PM INF 116 commits scanned.
8:35PM INF scanned ~6681185 bytes (6.68 MB) in 733ms
8:35PM INF no leaks found
```

**The carve-out is narrow, proved rather than claimed.** A scratch tree containing `.gitleaks.toml`
and the first 12 lines of `README.md` plus one planted `api_key = "<fresh token_urlsafe(32)>"`:

```
--- with the planted key, paths relative so the allowlist applies ---
RuleID:      generic-api-key
File:        README.md
Line:        13                ← the planted key, still reported
8:23PM WRN leaks found: 1      ← line 10, the ?access= link, is the only thing exempted
--- planted key removed ---
8:23PM INF no leaks found
```

`--no-git` (working tree) reports findings only in **git-ignored** paths — `.env`, `.superpowers/`
and `data/runtime/` — none of which is tracked or can ever be committed; no tracked file is flagged.
`.env` was never opened, printed or staged.

### `render.yaml` and `docs/architecture.html` (brief items 5 and 6)

`render.yaml`'s header no longer calls the deploy hook "the ONLY path"; it now names
`POST /v1/services/{id}/deploys` with the hook as the optional alternative, and the inline comment
on `autoDeploy: false` follows. Values untouched, so `test_deploy_manifests.py` is green unchanged.

`docs/architecture.html` figure 6: the node title and `aria-label` (`Render deploy hook` →
`Render deploy (API)`), the figure claim, the SVG's `aria-label`, the deploy-job node's visible step
line (`curl -fsS -X POST $HOOK` → `POST /v1/services/$ID/deploys`), the edge label (`POST hook` →
`POST deploy`) and the `D["f6-*"]` payloads including every `c:` cross-reference. The `f6-cold`
payload no longer says "No keep-alive cron runs today". Text only — no `viewBox`, geometry, class,
`data-id` or style was changed, and the replaced strings are the same length or shorter than the
tiles they sit in.

## 2. Definition-of-done output (final, at `3d38ae5`)

```
$ LLM_PROVIDER=stub .venv/bin/pytest -q
........................................................................ [ 98%]
..........................                                               [100%]
1826 passed in 157.42s (0:02:37)

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
236 files already formatted

$ .venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
```

1,826 = the 1,815 baseline + the 11 new contract tests. Output pristine — no warnings, no skips.
`check_facts.py` and `pii_check.py` are unchanged files and still green.

## 3. TDD evidence

The contract test was written first and watched fail:

```
$ LLM_PROVIDER=stub .venv/bin/pytest -q tests/contract/test_keepalive_workflow.py
E   FileNotFoundError: [Errno 2] No such file or directory:
    '/Users/sean/Projects/quantic-mosaic/.github/workflows/keepalive.yml'
ERROR tests/contract/test_keepalive_workflow.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.09s
```

then the workflow was written and it went green:

```
$ LLM_PROVIDER=stub .venv/bin/pytest -q tests/contract/test_keepalive_workflow.py
...........                                                              [100%]
11 passed in 0.79s
```

The `.gitleaks.toml` change followed the same shape — the finding was reproduced first (output
above), the carve-out was written against that exact finding, and the rescan plus the planted-key
control proved both directions.

## 4. Cold-start table verification (the main session's note)

Checked the numbers already written by the `dbe7945` fix round against the brief's table:
`deployed.md` (44.8 / 43.5 / 52.4 → 44.8; 2.8 / 0.1 / 0.1 → 0.1; 23.3 / 23.9 / 25.2 → 23.9;
71.0 / 67.5 / 77.6 → 71.0; 22.5 / 22.5 / 23.9 → 22.5), `README.md`, `docs/demo-script.md`,
`docs/architecture.html` (`f6-cold`) and the RUBRIC5.6 traceability row. **All match the brief
exactly — nothing was changed.** The only edit inside the table's block was adding the
`### Measured without keep-alive` heading above it and retensing one sentence of its lead.

## 5. Files changed

| File | Why |
|---|---|
| `.github/workflows/keepalive.yml` | **new** — the keep-alive |
| `tests/contract/test_keepalive_workflow.py` | **new** — 11 contract tests |
| `deployed.md` | § Cold start subsections + the Keep-alive subsection; § Cost instance-hour paragraph |
| `README.md` | one sentence |
| `docs/superpowers/specs/…design.md` | §14.4 decision; §1 non-goal; R-10; repo-layout tree |
| `scripts/check_render_hours.py` | docstring note (thresholds unchanged) |
| `tests/unit/test_check_render_hours.py` | one docstring line that asserted "no keep-alive cron" |
| `design-and-evaluation.md` | the workflow is no longer "queued" |
| `.gitleaks.toml` | the README `?access=` carve-out |
| `render.yaml` | header + `autoDeploy` comments (values untouched) |
| `docs/architecture.html` | figures 1 and 6 name the deploy API |
| `CHANGELOG.md` | one dated entry |

## 6. Self-review — what I found and fixed

* **First pass left three stale strings in figure 6** that the brief's wording ("node and edge
  payloads") did not literally cover but that a reader sees: the node's sub-line "the hook is the
  only path", the deploy-job node's `curl -fsS -X POST $HOOK`, and the edge label `POST hook`.
  Fixed — leaving them would have made the figure disagree with its own tooltip.
* **`f1-e-deploy`'s key row still said `["Secret","RENDER_DEPLOY_HOOK_URL"]`** — a secret that is
  not set. Fixed to name `RENDER_API_KEY` + `RENDER_SERVICE_ID` with the hook optional.
* **`deployed.md` claimed a grader "will actually see" the cold start.** False once the pinger
  runs. Retensed.
* **§ Cost said nothing about the hours the keep-alive spends.** A cost section that omits "744 of
  750" is incomplete. One paragraph added.
* **The spec would have contradicted itself** — §14.4 amended while the §1 non-goal, R-10 and the
  layout tree still said "no keep-alive cron" / "ONE workflow". All three follow §14.4 now.
* **YAGNI check:** no concurrency group, no matrix, no checkout, no jq install step, no second job,
  no extra endpoint pinged, no `paths-ignore`. The test asserts behaviour (schedule interval, the
  documented URL, permissions, the never-fail property), not string equality with the file.

## 7. Ambiguities resolved

1. **"one job, `ubuntu-latest`, ≤ 1 minute".** Implemented as `timeout-minutes: 2`, not 1. A cold
   instance answers `/health` in ~45 s and the curl budget the same brief specifies is 60 s, so a
   1-minute job timeout would cancel a legitimate probe — and a cancelled job is a **red** job,
   which directly contradicts the brief's "NEVER fails the repo's status". Two minutes is the
   smallest value that cannot race the probe; the reason is a comment in the file, the expected
   runtime is still well under a minute, and the test pins `0 < timeout-minutes ≤ 2`.
2. **Where the Keep-alive subsection goes.** The brief says "directly under the cold-start table".
   Taken as: directly under the table *and the two paragraphs that interpret it*, which are part of
   the measured-table material — with a `### Measured without keep-alive` heading over that block
   so the pairing the brief wants ("a reader sees both") is structural rather than incidental. The
   local-floor block that used to sit between them moved below the new subsection and got its own
   `###`; its lead sentence was reworded to read as prose under a heading.
3. **`permissions: {}` placement.** On the job, matching the brief's list of the job's attributes.
   For a one-job workflow it is equivalent to the top-level form.
4. **`vars.DEPLOY_URL` is empty today.** `DEPLOY_URL` exists as a repository *secret* (set by
   `provision_render.py` via `gh secret set`), not as a variable, so the committed fallback is what
   actually resolves. That is what the brief specified, it works today, and it is what the live run
   above exercised. Recorded in the workflow's header comment and the CHANGELOG rather than
   silently "fixed" by reaching for the secret.
5. **`docs/architecture.html` figure 1.** The brief scopes item 6 to figure 6, but figure 1 carries
   the same visible label ("deploy hook · autoDeploy: false") and the same tooltip title for the
   same mechanism. Corrected too — same class of defect, text only, same string lengths. Flagged
   here because it is outside the brief's literal scope.
6. **`CHANGELOG.md`.** Not named in the brief; added one entry because every phase commit in this
   repository carries one and the hours arithmetic is exactly the kind of fact the file exists to
   stop a later phase rediscovering.

## 8. Concerns

1. **`docs/optimization-log.md` is now stale and I was told not to edit it.** Its Status paragraph
   says `.github/workflows/` holds `ci.yml` only, and it records the keep-alive as queued. The
   main session owns that file; it needs the same one-line correction the other documents got.
2. **The schedule has never executed.** GitHub cron cannot run until the commit is pushed, so the
   evidence above is the step script run locally against the live `/health` — which exercises the
   real curl, the real payload and both branches, but not GitHub's scheduler. Two known scheduler
   behaviours to expect and neither is a defect: `schedule` triggers can be delayed by minutes
   under load (an occasional missed ping means one cold start), and GitHub disables scheduled
   workflows in a repository with 60 days of no activity.
3. **The keep-alive spends ~744 of 750 free instance-hours a month.** That is the approved
   decision, and it is documented in four places — but it means a second free service in this
   workspace, or a long month of debugging, can hit the suspension wall. `check_render_hours.py`
   will warn around the 25th of a 31-day month, and the workflow's warning line is the signal if
   the wall is ever reached.
4. **The grader-link allowlist must be retired after rotation.** The carve-out is anchored on
   `?access=<43 chars>` in `README.md` only, so it stays narrow, but once the token is rotated and
   the link is no longer published the block should be deleted rather than left behind.

---

# Fix round 1 — the optimization-log Status paragraph

One finding, one file, no code and no measured number changed.

## Finding: `docs/optimization-log.md:336-341` still said the workflow was not in the repo

The paragraph closing `## 2026-09-11 — Cold start, measured three times without keep-alive` read
"**Status: the keep-alive workflow is not in the repository yet.** `.github/workflows/` holds
`ci.yml` and nothing else; the pinger is queued as its own step after the publish wave, …". False at
`3d38ae5` — `.github/workflows/` holds `ci.yml` **and** `keepalive.yml` — and load-bearing, because
`deployed.md` § Cold start points a grader at this file for "the keep-alive ruling". This was
concern 1 of the implementer's report ("main session owns that file"); the reviewer has assigned it
here, so it is fixed. It sits below the n=1/n=3 figures the brief told me to leave alone, and none
of them moved.

### The change

```diff
-**Status: the keep-alive workflow is not in the repository yet.** `.github/workflows/` holds
-`ci.yml` and nothing else; the pinger is queued as its own step after the publish wave, and every
-figure published anywhere in this repository — here, in `deployed.md`, `README.md`,
-`docs/architecture.html` and the traceability matrix — is the no-keep-alive behaviour measured
-above. When the workflow lands, this section and those documents gain a line saying so; they do not
-change the measured table.
+**Status: `.github/workflows/keepalive.yml` landed 2026-09-11, after these probes; every figure
+above is still the no-keep-alive behaviour and disabling the workflow restores it.**
```

The `2026-09-11` date is the one every other document uses for the workflow (`README.md:86` "added
2026-09-11 *after* these figures", `architecture.html`'s `f6-cold` "the ten-minute /health pinger
added on 2026-09-11") — the commit's local timestamp is `Thu Sep 10 20:35:46 2026 -0700`, i.e.
`2026-09-11T03:35Z`, which is why the repo's UTC-dated prose says the 11th. The rest of the section
— the decision paragraph above it, the n=3 table, the medians, the probe provenance — is byte-for-byte
unchanged.

Verified the claim rather than assuming it:

```
$ ls .github/workflows/
ci.yml
keepalive.yml

$ grep -rn "not in the repository yet" --include='*.md' --include='*.html' --include='*.json' --include='*.py' .   # excluding .superpowers
(no matches)
```

## Covering tests

`docs/optimization-log.md` has no test that reads it (`grep -rln "optimization" tests/` → no hits),
so the covering set is the contract tests that read the documentation tree around it:

```
$ LLM_PROVIDER=stub .venv/bin/pytest -q tests/contract/test_docs_completeness.py \
    tests/contract/test_keepalive_workflow.py tests/contract/test_published_run_commands.py
.........................................................                [100%]
57 passed in 1.13s
```

## Definition of done, re-run after the edit

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
236 files already formatted

$ LLM_PROVIDER=stub .venv/bin/pytest -q
........................................................................ [ 86%]
........................................................................ [ 90%]
........................................................................ [ 94%]
........................................................................ [ 98%]
..........................                                               [100%]
1826 passed in 162.53s (0:02:42)

$ .venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
```

Same 1,826 tests, still pristine — no warnings, no skips. `check_facts.py` and `pii_check.py` are
unchanged files.

## Concerns after the fix

Concern 1 of the original report is **closed** — it was this finding. Concerns 2–4 (the schedule has
never executed because nothing is pushed; the ~744-of-750 hour spend; the gitleaks allowlist should
be deleted when the grader token is rotated) all stand unchanged; nothing in this round touched
them. No new concerns.
