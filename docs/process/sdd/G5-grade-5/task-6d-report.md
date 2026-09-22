# Task 6d — ai-tooling.md

**Status:** complete. **Commit:** `e348655` on `main`. **File touched:** `ai-tooling.md` only.
**Tests:** `.venv/bin/pytest -q -p no:cacheprovider tests/contract` → 554 passed.

## What the brief asked for, and what landed

| Brief item | Where it landed |
|---|---|
| Period header runs to the final build date | Line 3: `2026-09-08 → 2026-09-21` |
| New section covering 2026-09-14 → 16 | Section **7**, two paragraphs |
| UX audit/fix loop, UX-W1 → W7 | Section 7, first paragraph (W0–W7) |
| Demo-path logic waves W8 → W10 | Section 7, second paragraph |
| The independent-auditor pattern | Section 7 ("a fresh read-only session re-captured every screen and re-scored the plan itself … never with the implementing session's account of what it had fixed") and a new *What worked well* item |
| UX principles 6/15 → 9/15 | Section 7 (48-agent and 45-agent re-audits, fourth reached 9 of 15) and the new *What did not work* item, which prints the full 6 → 8 → 7 → 9 trajectory including the dip |
| Persona scenarios 5/16 → 13/16 | Section 7, second paragraph |
| This grade-and-fix pass | Section **8** |
| Existing honesty kept | Three new *What did not work* items, two new *What worked well* items |
| Suite-size as-of date | `3,392 tests as of 2026-09-21` — the day `pytest --collect-only -q` was run; the number is unchanged and the contract test recounts it live |

Also fixed, both inside the file's own scope and named in gap 12's evidence:

* **Section 3's "thirteen phases".** A new sentence says P0–P12 built the system and the same loop
  ran on to P29, that P13 onward were quality/review-fix/performance/deployment waves rather than new
  subsystems, and that `docs/process/sdd/` carries a brief and report for each through P27.
* **The commit census.** Gap 12 offered two routes (move the anchor or label it a snapshot). Moving
  the anchor would mean editing `tests/contract/test_docs_completeness.py`, which this task does not
  own, so the snapshot route was taken: the paragraph now says the census is a snapshot at `5b1bd51`,
  that the anchor is fixed so the figures can be recounted rather than trusted, and that every commit
  since carries a trailer under the same rule. Verified: across the 96 commits after `5b1bd51` the
  trailer census is 58 Opus / 38 Fable / 0 untrailered, so "every commit since" is true.
* **"Where the process is auditable".** Gap 12 notes the file offers `CHANGELOG.md` as the
  phase record while the CHANGELOG ends at 2026-09-10 (verified: last `##` section is P10 fix round 4).
  The paragraph now adds that the audit waves were not phases and says where their record is —
  `docs/optimization-log.md` for method/measures/follow-ups, `docs/superpowers/plans/` for both plans,
  `docs/evidence/` for the audit and re-audit reports and the before/after screens. Written so it
  stays true whatever Task 6a adds to `CHANGELOG.md`.

## Every figure and its source

| Figure | Source (verified this session) |
|---|---|
| 85 commits, 15/61/9 on 09-14/15/16 | `git log --format='%ad' --date=short \| sort \| uniq -c` |
| 53 screens, seven lenses, 155 verified findings, 15 principles with detection rules | `docs/optimization-log.md` § 2026-09-14 → 15; `docs/superpowers/plans/2026-09-14-ux-remediation-plan.md` |
| Re-audit 1: 48 agents, 138/155, gate fail on 4 Criticals (3 of them wave regressions) | `docs/optimization-log.md` § 2026-09-15 |
| Re-audit 2: 45 agents, 150/155, 8 of 15 principles | same |
| Principles 6 → 8 → 7 → 9 of 15 | same (table row `6 / 15` → `9 / 15 (re-audit #4)`; the 6 → 8 → 7 → 9 sequence is in the same file's demo-talking-points) |
| 512 captured turns, 16 persona scenarios, 22 defect classes / 11 Critical, 11 of 16 wrong | `docs/evidence/demo-path-review-2026-09-15.md` § 1 |
| 5 → 8 → 13 of 16 | `docs/evidence/scenario-recheck-final-2026-09-16.md` (13 of 16, was 5); the interim 8 is in `docs/optimization-log.md` |
| 2,002 → 3,040 + 299 browser; 3 → 18 browser routes | `docs/optimization-log.md` § 2026-09-15 tables |
| Cap 8 → 12, nine tool calls, `MOCK-HR-000007` as a recommendation, tenure wording non-deterministic | `docs/optimization-log.md` § 2026-09-15; `docs/evidence/demo-task-1-live-2026-09-15-cap8-partial.txt`, `…-p29.txt` |
| 82 agents, band-4 verdict, 27 ranked gaps | `docs/superpowers/plans/2026-09-21-grade-5.md` (committed, states 82 and 27); the report and `gaps.json` in the git-ignored `.superpowers/` directory, which the file discloses |
| `tools_disabled: []` privilege hole, fixed in `ef917a3` | `.superpowers/sdd/2026-09-21-grade-5/progress.md` ruling; `git show ef917a3` |
| 3,392 tests as of 2026-09-21 | `.venv/bin/pytest --collect-only -q` → `3093/3392 tests collected (299 deselected)`, run 2026-09-21 |

## One test failure on the way, and why it matters

The first contract run failed
`test_every_document_that_states_the_suite_size_states_the_collected_one`: the new section said
"the suite went from **2,002 tests** to 3,040", and `TESTS_STATED` (`([\d][\d,]{3,}) tests\b`) treats
any four-digit "N tests" in `ai-tooling.md` as a claim about the *current* suite. The historical
figure is now phrased "from **2,002** collected to **3,040** plus **299** real-browser checks at the
final build", which is the same convention the file's existing "72 tests at P1 to **1,590** at P11"
sentence already uses. Anyone adding another historical suite figure to one of the four `NUMBER_DOCS`
must do the same.

## Self-review of the diff

Checked and corrected before committing:

* "numbers carried to seven significant figures" → "unrounded numbers on human surfaces". The log's
  measure is "> 3 s.f."; seven was invented.
* "`docs/evidence/ux-w1` … `ux-w9`" → "`docs/evidence/ux-w*` and `ux-final`". There is no `ux-w5`
  directory, so the range implied a file that does not exist.
* "put every flagged finding to a separate session" → "each serious finding". The audit skeptics
  covered serious findings and the logic review had one refuter per *triaged* class, not per finding.
* "only a third [run] showed tenure …" → "only a pair of consecutive live runs showed the tenure
  wording obeying the prompt's rule in one and not the other", which is what the log records.
* "One screenshot the capture had not produced" → "A screenshot of my own, not one the capture had
  taken", matching the log's "the owner's own screenshot".

Tone: every new claim is a dated, named, specific fact with a file behind it; the two new
*What worked well* items each end on the limitation rather than the win; the three new
*What did not work* items name a number, a mechanism and a commit. No superlatives about the tools, no
"leveraged", no claim that anything was solved that the optimization log lists as an open follow-up —
the section says nine of fifteen "is where it stopped" and points at the follow-ups.

Forward-compatibility: section 8 says "the wave's measurement and documentation tasks follow the same
pattern" rather than reporting their results, so it stays true as Tasks 4, 5 and 6a–6c land. No
figure in the new prose depends on a later task's output.

## Concerns

1. **`82 agents` / `band 4` / `27 gaps` have their primary source in a git-ignored file.** The
   committed plan `docs/superpowers/plans/2026-09-21-grade-5.md` states both 82 and 27, so the figures
   are in a committed artifact — but the plan states them inside this task's own brief, which is
   circular if a grader chases it. The file discloses the location and the ignore, consistent with how
   it already handles `.superpowers/`. If the controller copies the grade report and `gaps.json` into
   `docs/process/sdd/` (as the P0–P27 trail was copied), section 8 should be re-pointed at that path.
2. **The suite figure will move again.** `3,392` was collected on 2026-09-21 with Tasks 1–3 landed.
   Tasks 4 and 5 may add tests; the contract test recounts live, so it will go red in `README.md`,
   `ai-tooling.md`, `design-and-evaluation.md` and `docs/requirements-traceability.md` together. Whoever
   lands the last test-adding commit of the wave owns re-syncing all four, including this file's
   as-of date.
3. **No dates were changed in `docs/process/sdd/README.md`,** which still says coverage runs to P27 —
   accurate, but P28/P29's brief and report are not in the committed trail. Section 7 does not claim
   they are; it points at `docs/optimization-log.md` and `docs/evidence/` for that stretch. If a later
   task syncs the trail, the sentence in section 3 ("through P27") should move with it.
4. **`ux-w5` has no evidence directory.** Not this task's to fix, and no document now points at one,
   but the wave numbering has a visible hole for anyone reading `docs/evidence/`.

---

# Fix round 1 — commit `501e18d`

**Status:** all three Importants and the Minor addressed, plus one unflagged inaccuracy found while
checking the Minor. **Tests:** `.venv/bin/pytest -q -p no:cacheprovider tests/contract` → 554 passed.
**Files:** `ai-tooling.md`, and two new tracked files under `docs/evidence/`.

## IMPORTANT 1 — the trailer rule now says which period it holds for

The reviewer is right, and the numbers are worse than "false for this wave" — they are unambiguous:

| Period | Commits | Trailers |
|---|---|---|
| Through `5b1bd51` (the anchor) | 160 | 122 Opus (1M context), 35 Fable 5.1, 3 merges |
| 2026-09-14 → 16 (the waves) | 85 | 56 Opus (55 `(1M context)` + 1 `Claude Opus 5`), 29 Fable 5.1 |
| 2026-09-21 onward (this wave) | 8 | **8 Fable 5.1, 0 Opus** |

So the deleted claim ("every commit since carries a trailer under the same rule, in the same mix")
was true of the wave stretch and false of this one, while §8 says an Opus implementer wrote each
task's diff. Three changes:

1. The standing rule sentence now reads "The rule is the same in all three cases, **and it held for
   every commit through 2026-09-16**: the trailer names the model that actually wrote the commit."
2. The census paragraph keeps a recount for the wave stretch (85 commits, 56 Opus, 29 Fable) instead
   of the vague "same mix" clause.
3. A new closing paragraph states the narrowing plainly: every commit of the grade-and-fix wave
   carries `Claude Fable 5.1` including the ones an Opus implementer wrote, because the wave's plan
   fixes the trailer to the coordinating session's model
   (`docs/superpowers/plans/2026-09-21-grade-5.md`, global constraints) following the
   harness-is-authoritative clause already in `docs/process/sdd/constraints.md` line 14; so for those
   commits the trailer names the session that coordinated the commit, not the model that wrote it, and
   the per-task implementer and reviewer models are recorded in the wave's ledger and per-task reports
   instead of in the history.

The mechanism is sourced rather than asserted: `constraints.md` line 14 already contains *"Where a
session harness instruction names the trailer, that instruction is authoritative and this line follows
it"*, and the plan's global constraints contain *"do end commit messages with `Co-Authored-By: Claude
Fable 5.1`"*. Both are committed.

Placement note: the new paragraph went **after** the existing "…how this guard went inert the first
time" sentence, not in the middle of the census paragraph — an earlier draft split the census
paragraph from its own "None of those four figures is typed from memory" explanation, which read as a
non-sequitur. `COMMIT_CENSUS` in `tests/contract/test_docs_completeness.py` still matches (its pattern
ends at "**3 are branch merges**", all of which is untouched).

## IMPORTANT 2 — the two absences in `docs/process/sdd/`

Verified: `ls docs/process/sdd/ | grep -E "P19|P27"` returns `P19-report.md` and `P27-brief.md` only.
The sentence now reads "carries a brief and a report for almost all of them through P27 — two are
absent, `P19-brief.md` and `P27-report.md`, and `docs/process/sdd/README.md` says why in each case."
The README does say why (P19 ran without a written brief; the copy runs one report behind by
construction, so `P27-report.md` lands with the next sync).

## IMPORTANT 3 — the grade card is now committed evidence

* `docs/evidence/grade-card-2026-09-21.md` — the grade report verbatim (36,806 bytes) under a two-line
  header in the style of `grade-card-2026-09-11.md`: what it is and that the body is unaltered, then
  "**Graded:** 2026-09-21, read-only, at HEAD `98c893f`, by an independent 82-agent grading workflow —
  assessors over grouped rubric sections, one adversarial skeptic per flagged finding, one synthesising
  grader", with a link to the gap list. Nothing in the body was touched.
* `docs/evidence/grade-card-2026-09-21-gaps.json` — byte-identical copy of `gaps.json` (49,113 bytes).
* §8 now ends by pointing at both tracked paths "beside the earlier `grade-card-2026-09-11.md`, so the
  verdict and every gap behind this wave can be read rather than taken on trust", and the "Where the
  process is auditable" paragraph names both grade cards and the gap list.

**Secret scan before copying**, following the procedure `docs/process/sdd/README.md` describes for the
process trail: both files were grepped for `sk-ant-`, `sk-…`, `AIza…`, JWT (`eyJ…`), `-----BEGIN`,
`ghp_`, `xox[baprs]-` and `Bearer …` shapes, for `access=`/`token` shapes, and for the live access
token from `README.md:10` by exact match. **Zero matches of any shape in either file.** No `gitleaks`
binary is installed on this machine, so the scan was regex-only; CI's `lint` job will run the real
scanner over full history.

**Test impact checked, as instructed:** `test_no_broken_links.py` crawls the *web app's* rendered
hrefs, not markdown, so new doc files cannot affect it. `test_docs_completeness.py` touches
`docs/evidence/` only via `EVIDENCE_SCREENSHOTS` (three `.png` names) and
`EXTERNAL_MCP_TRANSCRIPT`; `test_published_run_commands.py` globs `*.png` there. There is **no
`README.md` or index file in `docs/evidence/`** and no test requiring one, so no index line was
needed. Neither new file is in `NUMBER_DOCS`, so the suite-size and coverage guards do not read them
(this matters: the grade card's body quotes older figures, which would have gone red if it were).

## MINOR 2 — the re-audit input list

§7 now reads "each dispatched with the plan, the wave briefs and the owner rulings, the previous
re-audit's report and a fresh capture". Sourced from the re-audit headers: #2 lists `ux-W6-brief.md`
(+ report §5–6), #3 lists `ux-W7-brief.md` Addenda 1–3 and `W8-brief.md`, #4 lists the owner decisions,
`ux-W7-brief.md` Addenda 1–3, `W8-brief.md` and `W8-fix-round-addendum.md`.

## One unflagged inaccuracy, found while checking MINOR 2 and fixed here

Adding "the wave briefs" to that sentence exposed a claim in my own first commit that the sources do
not support. The file said the re-audits were dispatched "**never** with the implementing session's
account of what it had fixed", and there was a matching clause in the *What worked well* item ("they
were not given the implementing session's report"). That is true of re-audit #1 only. Re-audit #2's
header lists `ux-W6-report.md` §5–6; #3 lists *"implementers' reports `ux-W7-report.md`,
`W8-report.md`"*; #4 lists the W8 fix-round addendum. Both places now make the weaker, true claim —
the auditors were **required to score the principles off the renders rather than off the implementer's
report** — which is what the audit documents actually establish and what the *What worked well* item
needs in order to stand.

## Verification

* Every relative markdown link and every backticked repo path in `ai-tooling.md` re-resolved by script:
  all exist (`docs/evidence/ux-w*` → 8 dirs, `docs/evidence/ux-reaudit*.md` → 4 files).
* Trailer censuses above recomputed from `git log` with the same trailer-line regex the contract test
  uses (a trailer **line**, not a substring).
* `554 passed` on `tests/contract`, three times across this round (before the re-wrap, after the
  content edits, and after the final re-wrap).
* Commit `501e18d` on `main`, one `Co-Authored-By: Claude Fable 5.1` trailer, no `Claude-Session`
  trailer, three files.

## Concerns after this round

1. **Concern 1 of the first report is closed** (the grade card and gaps are tracked; §8 no longer
   depends on a git-ignored path). Concern 2 (the suite figure will move again when a test-adding task
   lands) **still stands** — `3,392` and the `2026-09-21` as-of date in this file must be re-synced
   with `README.md`, `design-and-evaluation.md` and `docs/requirements-traceability.md` by whoever
   lands the wave's last test-adding commit. The period header is left at 2026-09-21 per instruction.
2. **The new closing paragraph will need one more touch if a later task changes the trailer rule.** It
   says the trailer names the coordinating session for commits "from 2026-09-21"; if the wave's final
   commit is dated later, the sentence stays true (it is an open-ended "from"), but the figure "85 wave
   commits … 56 Opus, 29 Fable" is anchored to 09-14 → 16 and is not under test. Only the `5b1bd51`
   census is recounted by `test_docs_completeness.py`; the two period censuses I added are hand-typed
   from `git log` and could drift if history is rewritten.
3. **`docs/evidence/grade-card-2026-09-21.md` quotes the pre-fix state of the repository** — stale run
   ids, "band 4", the gap list. That is correct for a grade card and matches how
   `grade-card-2026-09-11.md` is treated, but a grader skimming `docs/evidence/` will read the
   criticisms as current. The header dates it and names the HEAD graded; if the wave wants more, a
   one-line "every gap below is closed by the commits of 2026-09-21" note could be added to the header
   once the wave is done — deliberately not added now, since it is not yet true.
4. **`docs/evidence/` has no index.** Nothing requires one, but it now holds 11 markdown/JSON artifacts
   plus eight screen directories, and the two grade cards are the only ones a grader is likely to want
   pointed out.

---

# Fix round 2 — commit `c427b15`

**Status:** the one finding addressed, one sentence changed.
**Tests:** `.venv/bin/pytest -q -p no:cacheprovider tests/contract/test_docs_completeness.py` → 48 passed.
**File:** `ai-tooling.md` only.

The closing clause sent a reader to "that wave's ledger and per-task reports" for which model
implemented and reviewed each task. Both are git-ignored, neither was named as tracked, and neither
names a model in the document's own terms — so the sentence pointed nowhere. It now reads:

> …and the recount above stops being a check on authorship. What the history no longer carries, the
> tracked plan does: `docs/superpowers/plans/2026-09-21-grade-5.md` states the wave's shape as an Opus
> implementer per task with a reviewer per task, and `CLAUDE.md` pins `model: "opus"` on every
> delegated call. Which session took which task, and what each reviewer found, is in that wave's ledger
> and per-task reports, and those are in the git-ignored `.superpowers/sdd/` working directory until the
> wave's process trail is copied into `docs/process/sdd/` the way P0–P27's was.

Two precision notes:

* The coordinator's message said the plan states the shape "in its global constraints and in the
  ai-tooling task text". `grep -n "Opus\|opus" docs/superpowers/plans/2026-09-21-grade-5.md` returns
  line 118 ("Two fresh Opus sessions") and line 202 (the Task 6d text: "Opus implementers per task with
  a reviewer per task") — **not** the global constraints block. The sentence therefore says the plan
  "states the wave's shape" without naming a section, and picks up `CLAUDE.md`'s `model: "opus"` pin,
  which the file's own tools table already cites, as the second tracked source.
* The clause says the ledger and reports are in `.superpowers/sdd/` "until the wave's process trail is
  copied into `docs/process/sdd/`" — a statement about where they are now and what would change it, not
  a claim that the copy has happened.

## Concerns

Unchanged from fix round 1, minus nothing. The live one for the wave's final commit: this sentence
becomes stale in a good way once the trail is copied — "until the wave's process trail is copied"
should then become a pointer to the copied path, and the ledger's new line recording that every
implementer and reviewer of this wave ran on Opus becomes the tracked source the sentence currently
has to get from the plan. Worth adding to the final commit's checklist alongside the suite-size and
period-header re-sync.
