# AI tooling — how Mosaic HR Copilot was actually built

**Project:** `quantic-mosaic` · **Author:** Sean Malone · **Period:** 2026-09-08 → 2026-09-11

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

**4 — Blind labelling by separate sessions (2026-09-10).** The judge-agreement figures in
`design-and-evaluation.md` come from a fresh Opus session — a third model family, independent of
both the Anthropic agent and the Gemini judge — that read *only* a labelling packet containing the
question, the served answer and the verbatim evidence, with no judge output anywhere upstream of
it. It read no run file, no report, no changelog.

**5 — CI on every phase.** Every phase ended with a pushed commit and a watched GitHub Actions
run. The suite grew from 72 tests at P1 to **1,590** at P11, and the whole suite runs on the push
path with zero API keys.

**6 — The human did accounts, keys and the demo.** Every gate that reached me was a browser-only
OAuth grant, an API key paste, or the recording itself. Nothing else.

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
- **Refusing to tune the number.** The published evaluation reports 0.808 strict pass against a
  0.85 target and a null ablation, each failing item with its cause — and it reports the 0.692 it
  started from beside it, so the optimization work is visible rather than implied. The
  coordinating session's standing ruling was that the only permitted lever was fixing an actual
  defect, and that everything else gets published with its cause.
- **`make` targets as the shared vocabulary.** CI runs the same targets a developer runs, so a
  macOS-only assumption fails immediately rather than at deploy time.

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
  drive all 26 items now, judge later against the committed run file, gated on eight consecutive
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
committed suite — 1,962 tests as of 2026-09-11, the count `pytest --collect-only -q` reports and the
count a contract test holds every graded document to — and by a 26-item evaluation whose real
numbers, including the ones below target, are published with their causes; security by secrets that exist only in environment variables, a
`gitleaks` scan over full history, a PII check that fails the build, an entirely synthetic corpus
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
and the independent grade card — and the design history is in `docs/superpowers/`. The commit
history carries one commit per phase with the requirement ids it satisfies in the trailer.
(They are produced in `.superpowers/`, which is git-ignored; `docs/process/sdd/README.md` says what
was copied, what was not, and how it was scanned for secrets first.)
