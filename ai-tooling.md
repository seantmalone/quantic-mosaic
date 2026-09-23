# AI tooling — how Mosaic HR Copilot was actually built

**Project:** `quantic-mosaic` · **Author:** Sean Malone · **Period:** 2026-09-08 → 2026-09-22

This is a dated, specific account of the AI tooling used to build this project, including the
parts that went badly. It is not a summary of what the tools can do; it is what happened.

## The tools

| Tool | Role |
|---|---|
| **Claude Code** (CLI), coordinating session on **Claude Fable 5.1** | Held the plan, wrote each phase brief, dispatched subagents, reviewed diffs, ran the acceptance gate, committed and pushed, watched CI, and adjudicated every ruling |
| **Claude Opus 5** subagents, in the same CLI | One subagent implemented one phase; a second, independently dispatched subagent reviewed it against that phase's definition of done. `CLAUDE.md` pins `model: "opus"` on every delegated call |
| **Anthropic `claude-haiku-4-5`** | The *product's* agent model — not a development tool, but the model every prompt in `agent/prompts/` was iterated against |
| **Google `gemini-3.5-flash-lite`** | The product's LLM judge and failover path, on two Google AI Studio keys from two Cloud projects — the judge's project on paid billing since 2026-09-10 (≈ $0.16 a judge pass), the failover's still free |
| `gh`, `ruff`, `pytest`, `gitleaks`, Docker | Ordinary tooling, driven by the sessions above rather than by hand |

Everything in this repository — the corpus, the mock data, the code, the tests, the dashboard, the
evaluation harness and these documents — was produced by Claude Code sessions under my direction.
No code was copied from another project or from a tutorial.

## How the work was organised

**1 — Design before code (2026-09-08 → 09).** A brainstorming pass produced the requirement
inventory; a set of **probes** answered questions no model should answer from memory by running
them: does `fastembed` hang at `parallel=1` (it did, twice, for 600 s), what does the default
`batch_size` cost in RSS (1,477 MB against 334 MB at 8), does `sqlite-vec`'s loadable extension
work on this interpreter, does `mcp` 2.2.0 really rename `FastMCP` to `MCPServer` and yield a
2-tuple, does `ragas` import on 3.12 (it installs and then fails to import). **Four architecture
proposals** were drafted and put to a **three-judge panel** of independently dispatched sessions;
the "Mosaic Monolith" won on the strength of one property — a single process where the MCP server
is mounted on the app that consumes it, so real JSON-RPC crosses a real socket at zero
infrastructure cost.

**2 — Critic loops, which had to be constrained (2026-09-09).** The winning design went through
adversarial critic rounds. The first rounds worked. Then they stopped converging: each round
invented a mechanism to close the previous round's objection, and the next round objected to *that*
mechanism. See *What did not work*.

**3 — Thirteen phases, each one subagent (2026-09-09 → 10).** The roadmap split the build into
P0–P12 with strictly forward dependencies. Each phase ran as: a written brief naming the spec
sections and an explicit definition of done → an **implementer** Opus subagent that wrote code and
tests and committed locally but never pushed → an independently dispatched **reviewer** Opus
subagent that ran the definition-of-done commands itself and reported findings by severity → up to
**three fix rounds** → the coordinating session pushed and watched CI. Reviewers were required to
run the commands rather than read the implementer's claims, because the build was unattended and
"green" had to mean evidence.

Phases P2 ∥ P3 ∥ P6 ran in **parallel git worktrees** on separate branches and were merged by the
coordinating session.

P0–P12 built the system; the same loop then ran to **P29**. P13 onward were quality, review-fix,
performance and deployment waves rather than new subsystems, and `docs/process/sdd/` carries a brief
and a report for almost all of them through P27 — two are absent, `P19-brief.md` and
`P27-report.md`, and `docs/process/sdd/README.md` says why in each case.

**4 — Blind labelling by separate sessions (2026-09-10).** The judge-agreement figures in
`design-and-evaluation.md` come from a fresh **Claude Opus 5** session: the **same vendor as the
agent** (Anthropic), a *different model*, in an **independent session that read only the packet** —
and a different vendor and family from the Gemini judge (Google). Its independence is of the
*session*, not of the vendor; calling it a third model family, as this document did before
2026-09-11, was wrong, and a shared vendor is a shared training lineage. The packet carried the
question, the served answer and the verbatim evidence and nothing else, with no judge output
anywhere upstream of it: no run file, no report, no changelog. `design-and-evaluation.md`'s
*Judge methodology* section states the same thing at length.

**5 — CI on every phase.** Every phase ended with a pushed commit and a watched GitHub Actions
run. The suite grew from 72 tests at P1 to **1,590** at P11, and the whole suite runs on the push
path with zero API keys.

**6 — The human did accounts, keys and the demo.** Every gate that reached me was a browser-only
OAuth grant, an API key paste, or the recording itself. Nothing else.

**7 — Waves against an audit of the running product (2026-09-14 → 16).** Eighty-five commits landed
in these three days — 15 on 09-14, 61 on 09-15, 9 on 09-16, by
`git log --format='%ad' --date=short | sort | uniq -c` — and the unit of work changed. Instead of
phases against a spec, **waves against an audit of the rendered product**, because the thing the
spec could not tell me was that the interface was clunky. A headless browser captured **53 screens**
(every page and state at desktop, laptop and phone widths, with every visible number and every
overflow measured); **seven sessions reviewed the renders** through separate lenses; a skeptic
confirmed each serious finding against its screenshot; the result was **155 verified findings** and a
plan of **15 principles, each with a mechanical detection rule**
(`docs/superpowers/plans/2026-09-14-ux-remediation-plan.md`, screens under
`docs/evidence/ux-audit-2026-09-14/`). Waves W0–W7 implemented it, and after each batch a **fresh
read-only session re-captured every screen and re-scored the plan itself** — four independent
re-audits, each dispatched with the plan, the wave briefs and the owner rulings, the previous
re-audit's report and a fresh capture, and each required to score the 15 principles off the renders
rather than off the implementing session's account of what it had fixed. The first (48 agents)
verified **138 of the 155** findings fixed and failed its own gate; the second (45 agents) reached **150 of
155** and 8 of the 15 principles; the fourth reached **9 of 15**. Every wave and every measure is in
`docs/optimization-log.md` (sections dated 2026-09-14 → 15 and 2026-09-15), with before/after screens
committed under `docs/evidence/ux-w*` and `ux-final` and the audit reports themselves at
`docs/evidence/ux-audit-2026-09-14/` and `docs/evidence/ux-reaudit*.md`.

A screenshot of my own, not one the capture had taken — "Done — your request is with the HR Time Off
team" printed above "Submit the request in MosaicOne" — raised a different question: are the demo paths
*logically* right for the person asking? A second adversarial review, of behaviour rather than
pixels, read **512 captured turns** and drove **16 fresh persona scenarios** one turn at a time
through seven lenses with a refuter per triaged class. It confirmed **22 defect classes, 11 of them
Critical**, and found **11 of the 16 scenarios logically wrong for their persona**
(`docs/evidence/demo-path-review-2026-09-15.md`). The cause was a single one: the deterministic layer
and the model's prose were never reconciled — the rules engine scored a requirement met while the
answer called it unmet, a non-compliant request was filed and then denied, a director was told to get
her director's approval. Waves W8–W10 put verdicts, arithmetic, dates, approvers, ids and the account
of a write behind the deterministic layer and reconciled or replaced the prose against it; re-driving
the same sixteen scenarios went **5 → 8 → 13 of 16** right
(`docs/evidence/scenario-recheck-final-2026-09-16.md`). Over the three days the suite went from
**2,002** collected to **3,040** plus **299** real-browser checks at that window's final build
(`bd4ac93`, 2026-09-16), and the browser test surface from **3 routes to 18**. Both figures are as of
that date and measure the W8–W10 window, not the submitted repository — the collected count at
submission is the one stated in the ownership disclosure below.

**8 — Graded by one workflow, fixed by another (2026-09-21).** Before submission the repository was
put through an independent grading workflow of **82 agents**: assessors over grouped rubric sections,
then one adversarial skeptic per flagged finding whose brief was to *refute* it against the artifact,
then a synthesising grader. It returned a **band-4 verdict and 27 ranked gaps**, each with its
evidence, a proposed fix and an effort estimate; a further set of candidate findings was overturned on
verification and recorded as checked rather than worked on. The fixes then ran in the shape the
phases had used: one Opus implementer per task, an independently dispatched Opus reviewer after it,
and a fix-and-re-review loop until the reviewer had nothing open — the wave's measurement and
documentation tasks follow the same pattern. The plan is committed at
`docs/superpowers/plans/2026-09-21-grade-5.md`, and the grade card and its ranked gap list are
committed verbatim as [`docs/evidence/grade-card-2026-09-21.md`](docs/evidence/grade-card-2026-09-21.md)
and `docs/evidence/grade-card-2026-09-21-gaps.json`, beside the earlier `grade-card-2026-09-11.md`,
so the verdict and every gap behind this wave can be read rather than taken on trust.

**And then graded again, because a fix wave is a change like any other (2026-09-22).** The repaired
repository went back through the same workflow — **78 agents**, the same assessor / skeptic / grader
shape, read-only at `2dee277` — and it came back **band 4 again, with 20 ranked gaps**
([`docs/evidence/grade-card-2026-09-22.md`](docs/evidence/grade-card-2026-09-22.md) and its
`-gaps.json`). That is the most useful thing the second pass produced: the first round had fixed
what the first card named and introduced or left behind a fresh set of one-command-falsifiable
claims — a `git diff` four documents printed as proof of build provenance that no longer came back
empty, a "full-history" secret scan that on a push scanned two commits, a clarification defect
sitting directly under the 1.000 metric the wave had been proud of. Round two (**G5b**) ran in the
same shape as round one — one Opus implementer per task, an independently dispatched Opus reviewer,
fix rounds until the reviewer had nothing open — across code and configuration, the dataset and
corpus, a re-measurement, and the documents. One thing worth recording honestly: the first round-2
drive of the evaluation (`r_1790106448`, build `7ada32e`) was **discarded** rather than published,
because reading its results showed that one dataset item's expected answer demanded a policy
retrieval the task does not need and another turn had no deterministic rule behind the behaviour
gold expected. Those were fixed on the gold and code sides, the build was redeployed, and the
round-2 published run is the drive after that (`r_1790110325_baseline`, build `80a5a71`) — the
discarded drive scored no better, and what would have been dishonest is re-driving until a number
improved and publishing only the last one. Both drives are named, with their figures, in the wave
ledger.

**And a third time, which is where the pattern became the finding (2026-09-22 to 2026-09-23).** The
round-2 tip went through the same read-only workflow at `39dc61c` and came back **band 4 again, with
37 ranked gaps**. What made the third pass worth running is that three of the four claims capping it
were **defects in code or in a committed artifact, not in prose**: the labelling packet printed the
very selection criterion two documents swore it withheld, the `no_structured_tools` ablation arm
called five tools it listed as disabled (8 of 30 items reached one), and the rules engine derived
approvals from requirement rows it had explicitly declined to check. A documentation pass could not
have closed any of them. Round three (**G5c**) therefore ran code first and documents last: the four
application and tooling fixes, then a deploy, then a re-drive of the baseline and both arms on
`34d50fb`, then a re-authored pair of blind label packets, and only then this and the other graded
documents. The ordering is the lesson — the three rounds together read as a repository whose *claims*
were graded harder than its *capability*, and the only durable answer to a falsifiable sentence is a
measurement plus a test that fails when the sentence stops being true.

## What worked well

- **Tests as the contract between subagents.** Each phase's definition of done was a list of
  commands, and a phase was not done until a *different* session ran them. That is what let
  thirteen phases by different agents compose without an integration week at the end. The `P7 →
  P8` hand-off is the clearest case: P7's orchestrator and P8's `/chat` were written by different
  subagents against a two-function interface (`run_turn`, `resume_turn`) named in the spec, and
  they met on the first try.
- **Building the audit trail first.** `core/trace.py` landed at P1, before anything that could
  log, with a grep-based conventions test asserting it is the only writer. Across eleven later
  phases no subagent ever invented a parallel logging path — the single failure mode the project's
  own requirements most feared — because the test would have failed the moment one tried.
- **Grep-based structural tests rather than AST walkers.** Five greps in one file (sole span
  writer, sole fastembed call site, no `parallel=`, `agent/` not importing `mcpserver`, no
  `mcp/__init__.py`) held the architecture for the whole build. The v1 design had AST-based
  sole-writer tests; they needed per-module carve-outs, and each carve-out became a contradiction
  in the next review round.
- **Probing instead of recalling.** Every fact a model would have been happy to invent — the
  `mcp` 2.x API shape, `fastembed`'s footguns, Haiku 4.5's 4,096-token cache floor, Render's
  750-hour and 500-build-minute budgets, Turso's limits, the current Anthropic prices — was read
  live and dated. Two of those probes changed the design; one of them (the cache floor) turned a
  planned feature into a documented non-feature.
- **Recording the model instead of imagining it.** Both demo stub scripts are verbatim recordings
  of real `claude-haiku-4-5` exchanges. That is how we discovered the model reproducibly answers
  demo task 1 with repeated searches rather than a heading fetch — a fact that changed the
  documented expectations rather than being papered over.
- **Refusing to tune the number.** The published evaluation reports 0.900 strict pass against a
  0.85 target — met at the fourth measurement, not the first — with a null ablation beside it and
  each failing item named with its cause, and it reports the 0.692 it started from and the
  intermediate columns, so the optimization work is visible rather than implied. Round two of the
  grade-and-fix wave discarded a drive rather than publishing it, because reading the results showed
  two of its expectations were wrong; the drive that replaced it did not score better. The
  coordinating session's standing ruling was that the only permitted lever was fixing an actual
  defect, and that everything else gets published with its cause.
- **`make` targets as the shared vocabulary.** CI runs the same targets a developer runs, so a
  macOS-only assumption fails immediately rather than at deploy time.
- **Auditing the rendered artifact rather than the code.** The interface and demo-path reviews were
  given screenshots, DOM dumps, overflow measurements and captured turns, told the repository was
  read-only, and required to score the plan's principles off those renders rather than off the
  implementing session's report. That is what produced findings no code review had produced —
  unrounded numbers on human surfaces, span kinds and guardrail names in chat prose, screens that
  scrolled sideways at 390 px, a completed ticket rendered as advice — and it is why each re-audit
  kept catching the previous wave's own regressions rather than confirming them fixed.
- **Refuting a finding before acting on it.** The audit waves and the 2026-09-21 grading pass both put
  each serious finding to a separate session whose job was to overturn it against the artifact.
  Several were overturned — one on arithmetic the flagging session had not done, one on a truncation
  convention the repository deliberately enforces in a test — and no wave spent time on them. Without
  that step an audit's output is a list of things that look wrong in a screenshot.

## What did not work

- **The v1 specification was massively over-engineered, and two full rounds went into deleting
  it.** v1 grew a frozen clock, byte-identical LLM replay in CI, AST sole-writer tests, HMAC
  confirmation tokens with a shared secret, a prose-generating fact ledger, docs generators
  diff-checked in CI, Cohen's κ machinery and a 21-step CI job with per-phase step ownership.
  Every one of those was added to close a review objection, and every one generated new
  contradictions in the following round — the frozen clock in particular had to be un-frozen for
  latency, uptime and cold/warm classification, and each round found another surface where the
  split leaked. **v2 removed 26 mechanisms** (listed one per line in spec §22) and changed the
  architecture not at all. The lesson: an adversarial critic loop with no budget will keep finding
  objections, and answering each one with a mechanism is how a design dies. The loop had to be
  constrained — "propose deletions, not additions" — before it converged.
- **`gitleaks` false positives cost two red CI runs.** The first was synthetic test secrets in
  `tests/fixtures/` and `test_g6_redact.py` — a redaction test necessarily contains key-shaped
  strings. The second was `curl-auth-header` firing on `Makefile` and `ci.yml` lines that send
  `Authorization: Bearer $APP_ACCESS_TOKEN`, where the value is a *variable*. Both were fixed with
  a narrowly scoped `.gitleaks.toml` allowlist and a version pin, but a secret scanner that fires
  on the code proving secrets are handled correctly is a real friction.
- **Provider outages and free-tier quotas cost most of a day.** The Gemini judge project hit its
  free daily cap mid-evaluation; the judge was moved to the second Cloud project's quota, which
  is exactly why two keys exist. Then Google returned `500`/`503 "high demand"` for hours across
  **both** projects, and the P10 evaluation had to be restructured into a **two-pass harness** —
  drive all 30 items now, judge later against the committed run file, gated on eight consecutive
  successful responses — so the run was never lost to a provider's bad afternoon. The design's
  failover path (agent → free Gemini) is the same instinct applied to the product.
- **Two concurrent turns of one agent collided.** I sent a mid-run instruction to a working
  subagent, which resumed it while its previous turn was still executing. Two turns of the same
  agent then wrote into the same working tree, orphaned a `uvicorn` and a runner process, and had
  to be stopped and restarted with a single owner and an explicit sequence. **Lesson recorded in
  the ledger: do not message a working agent mid-run; wait for its report.** A second agent had to
  be stopped for the same reason before the pattern was recognised.
- **A blind labelling round was voided.** The first labelling packet carried 320-character display
  snippets rather than the full chunk text the synthesis prompt actually carried, and the labeller
  returned 5 of 8 `not_grounded` — then said in its notes that the packet looked incomplete.
  Thirteen of fourteen disputed claims were in the full chunk text. The evidence definition was
  widened for the judge and the packet *together, from one function*, the packet was rebuilt, and
  a fresh labeller was dispatched. The voided round is reported in
  `design-and-evaluation.md` rather than quietly discarded.
- **Subagents write more than they are asked to.** Roughly two dozen "minor, deferred" findings
  across the phases are scope creep: a `--json` flag added speculatively, a helper module nobody
  asked for, a changelog entry written by a phase whose scope did not include the changelog. None
  broke anything; all of them are recorded in the ledger rather than absorbed silently. Explicit
  file lists in the brief reduced this but never eliminated it.
- **A commit-trailer instruction was ignored repeatedly.** Several subagent commits carried the
  harness's own attribution line instead of the one the brief specified. It is cosmetic, and it
  was flagged in three separate phase reviews before being accepted as a documented deviation —
  a good illustration that a rule stated once in a long brief is not a rule that survives.
- **One review round produced a genuine cross-phase breaker.** P8's fix rounds changed P7 files —
  the act loop's evidence accounting and its reminders — because both demo tasks refused against
  the live model before those changes. Rather than accept a fix to a previous phase inside the
  current phase's review, a separate **P7-lens review** was dispatched on exactly those commits;
  it found three real issues (a reminder that named tools and therefore biased the tool-selection
  metric, a nudge path that ignored the ablation's disabled-tools flag, and an empty non-final
  assistant turn that provokes a `400` from the Messages API) which were then fixed and
  mutation-verified.
- **Estimates were optimistic.** The plan budgeted ~50 agent-hours across thirteen phases. The
  evaluation phase alone (P10) took four fix rounds, a voided labelling round, a provider outage
  and a two-pass harness rewrite.
- **Every re-audit found residuals in the previous wave's fixes, and the interface gate never
  passed.** Four independent re-audits scored the same 15 principles **6 → 8 → 7 → 9**; the dip at the
  third is real and is printed in `docs/optimization-log.md` rather than smoothed. Worse, **three of
  the four Criticals that failed the first re-audit's gate were regressions the waves had introduced**:
  every dashboard chart collapsed to about a quarter of its panel, a completed HR ticket rendered
  under "What I suggest you do" with the "not company policy" footnote beneath it, and the model's own
  next-steps text painted a deadline computed a month early. Nine of fifteen is where it stopped; the
  gate itself and three of the sixteen persona scenarios are recorded as open follow-ups in the
  optimization log rather than presented as closed. The narrow lesson is not "agents cause
  regressions" — it is that a wave which fixes a screen without adding a guard on the *class* it fixed
  will have the next audit find that class somewhere else, which is why every regression class now has
  a browser test that fails on the build that had it.
- **The recorded demo fixtures kept passing while the live path was broken.** Both stub recordings
  were verbatim 2026-09-10 exchanges, so they could not show what the current prompt does. Only a live
  run on the W6 build showed the flagship question needing nine tool calls against a cap of 8, ending
  the turn partial on top of a complete answer (P28 raised the cap to 12); only a live run showed the
  model writing "HR ticket MOCK-HR-000007 has been created" as a *recommendation*, which the
  one-account guard then kept, so the "Done" lede never appeared and the re-audit's Critical was back
  on the live path; and only a pair of consecutive live runs showed the tenure wording obeying the
  prompt's rule in one and not the other (P29 made both deterministic). The fixtures themselves then
  had to be amended, under a contract test
  that fails on the old text. Recording a real model is better than imagining one, but a recording
  ages against the prompt that produced it.
- **An implementer closing a gap opened a privilege hole (2026-09-21).** One task of the grade-and-fix
  wave made `MCP_TOOLS_DISABLED` actually take effect, and in doing so made the filter statable per
  request: a non-admin caller could send `tools_disabled: []` and switch the operator's default off.
  The implementer's own tests passed. The independent re-reviewer found it, flagged it as outside its
  scope, and it was ruled in and fixed by unioning the process default into the effective filter so no
  caller can state their way past it (`ef917a3`). It is the sharpest argument in the project for the
  reviewer being a different session: the hole was inside the diff that closed the gap.

## AI use and ownership

**Disclosure.** This project was developed with substantial AI assistance, as the course
explicitly permits and encourages. Claude Code (Claude Fable 5.1 as the coordinating session,
Claude Opus 5 as implementer, reviewer and labeller subagents) wrote the great majority of the
code, tests, corpus prose, mock data and documentation in this repository, working from
specifications, briefs, rulings and reviews that I directed. The design decisions recorded in
`design-and-evaluation.md` were adjudicated by me; the mechanical work of implementing and testing
them was delegated. The product itself also uses AI at run time: Anthropic `claude-haiku-4-5` is
the agent, and Google `gemini-3.5-flash-lite` is the evaluation judge and the failover path.

**Ownership and responsibility.** I remain fully responsible for the **correctness**, **security**
and academic **integrity** of everything submitted here. I reviewed the architecture and the
rulings that shaped it, I set the constraints that every phase was held to, and I accept
responsibility for the code as submitted work. Concretely: correctness is defended by the whole
committed suite — 3,469 tests as of 2026-09-22, the count `pytest --collect-only -q` reports and the
count a contract test holds every graded document to — and by a 30-item evaluation whose real
numbers, including the ones below target, are published with their causes — the published run
`r_1790130220_baseline` drives all 30 of them against the deployed build `34d50fb`; security by
secrets that exist only in environment variables, two `gitleaks` scans on every CI run (the
action's own scan of the pushed commits, and a whole-history `gitleaks detect` from the pinned
8.30.1 binary — 280 commits read clean on 2026-09-22, that being the history at `2dee277`, which `git rev-list --count --no-merges 2dee277` counts; later runs scan more), a PII check that fails the build, an entirely synthetic corpus
and dataset, and a write gate enforced at a boundary rather than in a prompt; integrity by this
disclosure, by the fact that no third-party code was represented as my own, and by every vendored
frontend asset carrying its version, upstream URL and full licence text in
`src/hrmosaic/web/static/vendor/LICENSES.md`.

**Third-party content.** All policy documents in `corpus/` and all records in `mock_data/` are
synthetic, written for this project, and describe a fictional company. No proprietary, private or
paid data is included or loaded at run time. Runtime and development dependencies are pinned in
`requirements.txt` and `requirements-dev.txt` and are used under their own licences.

**Where the process is auditable.** The phase-by-phase record is in `CHANGELOG.md` (dated, one
section per phase, including the corrections); the briefs and phase reports themselves are
**committed** under [`docs/process/sdd/`](docs/process/sdd/) — the ledger, every `P<n>-brief.md`
and `P<n>-report.md` with its definition-of-done output pasted verbatim, the binding constraints
and the independent grade card — and the design history is in `docs/superpowers/`. The audit waves of
2026-09-14 → 16 are recorded differently, because they were not phases: their method, measures and
open follow-ups are in `docs/optimization-log.md`, the plan they implemented and the plan for the
2026-09-21 grade-and-fix pass are under `docs/superpowers/plans/`, and the audit and re-audit reports
are committed verbatim under `docs/evidence/` beside the before/after screens they scored. The three
independent grade cards live there too — `grade-card-2026-09-11.md`, `grade-card-2026-09-21.md` with
its ranked gap list `grade-card-2026-09-21-gaps.json`, which is the list round one of this wave
worked through, and `grade-card-2026-09-22.md` with `grade-card-2026-09-22-gaps.json`, which re-graded
the result and is the list round two worked through. The commit history carries one commit per phase with the requirement ids it satisfies in
the trailer.
(They are produced in `.superpowers/`, which is git-ignored; `docs/process/sdd/README.md` says what
was copied, what was not, and how it was scanned for secrets first.)

**One detail a reader of `git log` will notice.** Two `Co-Authored-By` trailers run through the
history, and the split is not random: of the 160 commits through `5b1bd51`, **122 carry
`Claude Opus 5 (1M context)`** — every phase commit from `P0`'s `ad593a3` onward, because an
implementer or reviewer subagent wrote them — **35 carry `Claude Fable 5.1`**, the coordinating
session's own commits (the spec, the roadmap, the optimization log, the merges of adjudicated
rulings), and **3 are branch merges** with no trailer at all. The rule is the same in all three cases,
and it held for every commit through 2026-09-16: **the trailer names the model that actually wrote the
commit.** That census is a **snapshot at `5b1bd51`**, not a running total: the anchor is fixed so the
figures can be recounted rather than trusted. The 85 wave commits of 2026-09-14 → 16 sit after it and
follow the same rule — 56 carry an Opus trailer because an implementer or reviewer subagent wrote them,
29 carry `Claude Fable 5.1` for the coordinating session's own plans, rulings and documents.
`docs/process/sdd/constraints.md` line 14 said it as a fixed string until 2026-09-11 and now says
it as that rule, which is what the history has done since P0. None of those four figures is typed
from memory: `tests/contract/test_docs_completeness.py` recounts them from `git log` at the commit
this paragraph names and fails if they disagree — an earlier hand-typed census had drifted by
fourteen commits before anyone noticed. That recount needs the history, so CI's `test` job checks
out at `fetch-depth: 0` like its `lint` job; the test skips only where the commit genuinely cannot
be present (no `git`, or a shallow clone) and **fails** rather than skipping in a full clone that
does not have it, because a silent skip is how this guard went inert the first time.

**From 2026-09-21 the trailer means something narrower, and a reader should know it.** Every commit of
the grade-and-fix wave — both rounds, `G5(…)` and `G5b(…)` — carries `Claude Fable 5.1`, including the
ones whose diffs an Opus implementer subagent wrote, because that wave's plan fixes the trailer to the coordinating session's model on every
commit (`docs/superpowers/plans/2026-09-21-grade-5.md`, global constraints), following the same
harness-is-authoritative clause of `constraints.md` line 14. So for those commits the trailer names
**the session that coordinated the commit, not the model that wrote it**, and the recount above stops
being a check on authorship. What the history no longer carries, the tracked plan does:
`docs/superpowers/plans/2026-09-21-grade-5.md` states the wave's shape as an Opus implementer per task
with a reviewer per task, and `CLAUDE.md` pins `model: "opus"` on every delegated call. Which session
took which task, and what each reviewer found, is in that wave's ledger and per-task reports, and
those are committed — copied verbatim out of the git-ignored `.superpowers/sdd/` working directory
into [`docs/process/sdd/G5-grade-5/`](docs/process/sdd/G5-grade-5/) the way P0–P27's trail was, with
a `README.md` there naming what was left out of the copy and how every file was scanned for
credentials first. The ledger records the models as well: every implementer, reviewer and re-reviewer
subagent in the wave was dispatched with `model: opus`.
