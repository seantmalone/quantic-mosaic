# Evidence — what is here, when it was taken, and on which build

Every artifact in this directory is a capture of something that actually ran: a live transcript, a
screen set, a probe, an independent report. Several of the older headers call the build they ran on
**"the final build"** — `f5e86c3` on 2026-09-12, `bd4ac93` on 2026-09-16, `da0dca2` for the Waves 1–2
cold-start probes. Each of those was true when it was written and none of them is now: read *"the
final build"* in any header below as **final as of that date**. The build the **published evaluation
run measures is `80a5a71`** — run `r_1790110325_baseline`, driven 2026-09-22 at 20:52Z over the
30-item dataset, the run `evaluation/results/latest.json` points at and the one
`evaluation/REPORT.md`, `design-and-evaluation.md`, `README.md` and `deployed.md` publish. `8a89310`
held that place for ten hours the same day, which is why three transcripts below name it.
Transcripts and headers are never edited to keep up; this index is where the dates are reconciled
instead.

A `git log --diff-filter=A -1 -- docs/evidence/<name>` gives the commit any artifact landed in, which
is how the *Build* column is filled for the screen sets, whose own captures record a harness and a
date rather than a service sha.

## Index

| Artifact | Date | Build | What it shows |
|---|---|---|---|
| [`mcp-discovery-4-tools.json`](mcp-discovery-4-tools.json) | 2026-09-09 | added at `15bdfe2` | `tools/list` from the **separate stdio server** of the ablation arm: 4 tools, with the five structured-data and write tools genuinely absent from discovery rather than filtered downstream |
| [`mcp-discovery-4-tools.png`](mcp-discovery-4-tools.png) | 2026-09-10 | added at `73eb047` | the same 4-tool discovery on screen, beside the five removed names |
| [`mcp-discovery-page.png`](mcp-discovery-page.png) | 2026-09-10 | added at `70faf71` | `/dashboard/mcp` rendering live discovery: the server card (`connected yes`, protocol `2025-11-25`, 32 ms handshake, 9 tools), every tool's `input_schema` / `output_schema` / `annotations`, and the handshake-history row |
| [`ci-deploy-skipped.png`](ci-deploy-skipped.png) | 2026-09-10 | added at `5419ec5` | the job graph of a recorded **red** CI run — `test` fails, `deploy` is skipped with the reason *"dependent job failed"* (run `34485304411`) |
| [`cold-start-probes.json`](cold-start-probes.json) | 2026-09-10 → 11 | probe 1 on `bf85ffd`, probes 2–3 on `da0dca2` | the three live cold-start probes behind `deployed.md`'s `## Cold start`: per-segment seconds, their medians and their `n`, transcribed from each run's ledger entry. Its probe-2/3 `build` field is the *"final build (Waves 1-2)"* — final as of 2026-09-11 |
| [`demo-task-1-live-2026-09-11.txt`](demo-task-1-live-2026-09-11.txt) | 2026-09-11 | `e13a772` (deployed `/health`) | demo task 1 — international remote-work eligibility — driven live against the deployed service, the first pinned transcript |
| [`demo-task-2-live-2026-09-11.txt`](demo-task-2-live-2026-09-11.txt) | 2026-09-11 | `e13a772` (deployed `/health`) | demo task 2 — a PTO request through the confirmation gate to a mock write, with the citation-breadth caveat in its own header |
| [`grade-card-2026-09-11.md`](grade-card-2026-09-11.md) | 2026-09-11 | graded at `e13a772` | the **first** independent grade card, read-only against `docs/project-requirements.md`; its findings are the P23 fixes |
| [`demo-task-2-live-2026-09-12.txt`](demo-task-2-live-2026-09-12.txt) | 2026-09-12 | `f5e86c3` — its header's *"the final build"* | demo task 2 re-run after the P24 breadth repair: the card first, nothing written, then the confirmed write, ticket `MOCK-HR-000006` |
| [`mcp-external-session-2026-09-12.txt`](mcp-external-session-2026-09-12.txt) | 2026-09-12 | `f5e86c3` — its header's *"the final build"* | the MCP mount reached from **outside** the service by plain `curl` over HTTP/2: `initialize` with a session id, `notifications/initialized`, `tools/list` returning all nine tools, and a real `search_policy_documents` call with its server-side retrieval span |
| [`ux-audit-2026-09-14/`](ux-audit-2026-09-14/) | 2026-09-14 | captured 23:55Z, added at `af31e7c` | the **original** UX audit's own capture set — 36 of the 53 screens it took, plus the `index.json` that records the harness (LOCAL, `LLM_PROVIDER=stub`, no live model call, every visible number and every overflow measured). The 155 findings it produced are the remediation plan's inventory |
| [`brand-preview.html`](brand-preview.html) | 2026-09-14 | added at `7792090` | the W0 identity in one self-contained page: the mark, the type pairing and the whole token block, light **and** dark side by side |
| [`ux-w1/`](ux-w1/) | 2026-09-14 | after-shots at `81f2d3e` | W1 before/after — one masthead on every page in every persona, one gate (roles gate only the three writes), the themed error page, the policy reader route, a conversation that survives a reload |
| [`ux-w2/`](ux-w2/) | 2026-09-14 | after-shots at `ff9a9a3` | W2 before/after — the chat redesign: one conversation column, plain language, sources as friendly references, the confirmation card, a refusal, the phone. This is the wave that deleted the 22 rem span rail and the per-turn trace panel |
| [`ux-w3/`](ux-w3/) | 2026-09-15 | after-shots at `42ca1fe` | W3 before/after — the quarantined *Demo & grader* panel, the outcome-aware live region, and refusals that name five example policies and link the library |
| [`ux-w4/`](ux-w4/) | 2026-09-15 | `before-` at `42ca1fe`, `after-` at `efbbde0` | W4 before/after over **every dashboard route** at 1440×900 (plus `-full` for the two pages whose change is below the fold, and `-390` for the phone): one formatter path per number, ledes and breadcrumbs, tables that scan, KPI tiles that agree with their detail |
| [`ux-final/`](ux-final/) | 2026-09-15 | added at `3c94353` | **the screen set at the end of the five-wave remediation** (W0–W5), 39 screens and a README: every surface at 1440, the phone, and `prefers-color-scheme: dark`, captured by `make ux-capture` against four stub servers on loopback. Later waves (W6–W9) have their own before/after directories below — this is the W5-era set the report and the README cite, not the last screens taken |
| [`ux-reaudit-2026-09-15.md`](ux-reaudit-2026-09-15.md) | 2026-09-15 | working tree, added at `63e4754` | the **first** independent re-audit (48 agents) of W0–W5: 138 of 155 inventory findings verified fixed, 6 of 15 principles passing, and a gate failed on four Criticals — three of them regressions the waves introduced |
| [`ux-w6/`](ux-w6/) | 2026-09-15 | `before-` = the re-audit's own captures, `after-` at `d6d2e64` | W6 before/after, one pair per Critical — the sized chart container, the `performed` block, `next_steps` rendered only where nothing is grouped, date-consistency, and the chat URL that carries its session |
| [`demo-task-1-live-2026-09-15-cap8-partial.txt`](demo-task-1-live-2026-09-15-cap8-partial.txt) | 2026-09-15 | `4058404` (after UX W6) | the live run that found the tool-call cap: nine calls wanted, eight allowed, so a complete nine-block answer shipped labelled `partial` with the limit preface. The reason `AGENT_MAX_TOOL_CALLS` is 12 (P28) |
| [`demo-task-1-live-2026-09-15.txt`](demo-task-1-live-2026-09-15.txt) · [`demo-task-2-live-2026-09-15.txt`](demo-task-2-live-2026-09-15.txt) | 2026-09-15 | `ebd665a` (UX W6 + P28) | both demo tasks re-driven on the raised cap: demo 1 answered over four documents, demo 2 through the gate to the write — and the two defects only a real model produced (a write narrated as a *recommendation*, a tenure restated in months with the snapshot date) |
| [`demo-task-1-live-2026-09-15-session.json`](demo-task-1-live-2026-09-15-session.json) · [`demo-task-2-live-2026-09-15-session.json`](demo-task-2-live-2026-09-15-session.json) | 2026-09-15 | `ebd665a` (`app_version` in the file) | the **store's own rows** for those two turns — session, turns and every span with its payload — so the transcripts can be checked against the audit trail rather than against each other |
| [`ux-reaudit-2-2026-09-15.md`](ux-reaudit-2-2026-09-15.md) | 2026-09-15 | captured on `7655321`; `48c1c8d` and `d8a2ca3` landed while it ran, as its own caveat records | re-audit #2 (45 agents): 150 of 155 verified fixed, 8 of 15 principles passing, one Critical — a phone that never scrolled to the newest answer — and 36 confirmed findings |
| [`demo-task-1-live-2026-09-15-p29.txt`](demo-task-1-live-2026-09-15-p29.txt) · [`demo-task-2-live-2026-09-15-p29.txt`](demo-task-2-live-2026-09-15-p29.txt) | 2026-09-15 | `d8a2ca3` (UX W6 + P28 + P29) | the same two tasks after P29 made both defects deterministic: tenure in the tool's own words with no restated snapshot date, and demo 2 leading with *"Done: … Reference MOCK-HR-000008."* Demo 1 here is the run the demo script's timings and citation breadth are read from (46.8 s over 35 spans, 10 passages across four documents) |
| [`demo-path-review-2026-09-15.md`](demo-path-review-2026-09-15.md) | 2026-09-15 | the deployed build of that day, added at `c051bd4` | the adversarial logic review: 512 captured turns plus 16 fresh persona scenarios through seven lenses with a refuter per class — 22 defect classes (11 Critical) and **11 of 16 scenarios logically wrong for their persona**. The brief for the W8 logic wave |
| [`ux-w7/`](ux-w7/) | 2026-09-15 | `before-` on `d8a2ca3`, `after-` at `e7f1b60` | W7 before/after, eight pairs — the phone scroller picked at runtime, the reader's own record as a `record` block, the always-expanded demo panel, the eyebrow-and-pill dashboard menu, real eval tabs, and a fresh load per viewport |
| [`ux-w8/`](ux-w8/) | 2026-09-15 | `before-` on `16217b7`, `after-` at `133e853` | the W8 fix round, four pairs — one per Critical of re-audit #3, including the refusal branch of a blocked write photographed on purpose |
| [`ux-w9/`](ux-w9/) | 2026-09-15 | `before-` on `133e853`, `after-` at `6f11bcd` | W9 before/after for re-audit #4's two Criticals: the conversation owning the first viewport at 1440 and 1280, and the waterfall's payload disclosures |
| [`ux-reaudit-3-2026-09-16.md`](ux-reaudit-3-2026-09-16.md) | 2026-09-16 | captured on `16217b7`, added at `98c893f` | re-audit #3 over W7 and W8 — 71 screen ids × 3 viewports, 26 confirmed findings, four Criticals (the four `ux-w8/` closes) |
| [`ux-reaudit-4-2026-09-16.md`](ux-reaudit-4-2026-09-16.md) | 2026-09-16 | the tree at `133e853`, added at `98c893f` | re-audit #4, scoring the redesign against the plan's 15 principles and the owner's three goals: 9 of 15 principles passing, two Criticals (the two `ux-w9/` closes) |
| [`scenario-recheck-final-2026-09-16.md`](scenario-recheck-final-2026-09-16.md) | 2026-09-16 | the live build of that day, added at `98c893f` | the same 16 persona scenarios re-driven one turn at a time after W8: **13 of 16 logically right, was 5 of 16** — and no scenario shipping a contradicted write, a non-compliant filing or an unrefused unsafe request |
| [`final-2026-09-16/`](final-2026-09-16/) | 2026-09-16 | `bd4ac93` — its README's *"the final build"* | six live Playwright screens plus `answer.txt`, against the deployed service with the grader key and one real model turn. `bd4ac93` was the build the **then**-published run `r_1789555212_baseline` measured; the run published now is `r_1790110325_baseline` on `80a5a71` |
| [`grade-card-2026-09-21.md`](grade-card-2026-09-21.md) | 2026-09-21 | graded at `98c893f` | the **second** independent grade card — an 82-agent read-only grading workflow (assessors, one adversarial skeptic per finding, one synthesising grader): **band 4**, with 27 ranked gaps. Its own header records what the wave then did about them |
| [`grade-card-2026-09-21-gaps.json`](grade-card-2026-09-21-gaps.json) | 2026-09-21 | graded at `98c893f` | the machine twin of that card's ranked gap list — per gap: severity, section, why it costs marks, the evidence, a proposed fix and an effort estimate. The list the grade-and-fix wave worked through |
| [`demo-task-1-live-2026-09-22.txt`](demo-task-1-live-2026-09-22.txt) | 2026-09-22 | `8782177` — a docs-only commit over the app build `8a89310`, which round 2 superseded that evening with `80a5a71` | demo task 1 on the **published** build, and the first turn of a cold instance's life (`cold_start: true` before, `false` after): 38.2 s of turn time, verbatim stdout and stderr |
| [`demo-task-2-live-2026-09-22.txt`](demo-task-2-live-2026-09-22.txt) | 2026-09-22 | `8782177` — a docs-only commit over the app build `8a89310`, which round 2 superseded that evening with `80a5a71` | demo task 2 on the published build, warm: the confirmation card, nothing written, then the confirmed write and its `performed` lede, with the served block text quoted from the store |
| [`draft-hr-email-live-2026-09-22.txt`](draft-hr-email-live-2026-09-22.txt) | 2026-09-22 | `8782177` — a docs-only commit over the app build `8a89310`, which round 2 superseded that evening with `80a5a71` | the first live capture of `draft_hr_email`'s **two endings** — the same ask confirmed once and cancelled once — on the build carrying task 1c's fixes, so a cancelled write is answered by its receipt rather than by an evidence refusal |
| [`grade-card-2026-09-22.md`](grade-card-2026-09-22.md) | 2026-09-22 | graded at `2dee277` | the **third** independent grade card — a 78-agent read-only grading workflow of the same shape as the second, run against the repository the first round of the grade-and-fix wave left: **band 4**, with 20 ranked gaps, led by a provenance command four documents printed that no longer held at HEAD. Its own header records what round two did about them |
| [`grade-card-2026-09-22-gaps.json`](grade-card-2026-09-22-gaps.json) | 2026-09-22 | graded at `2dee277` | the machine twin of that card's ranked list — per gap: severity, section, why it costs marks, the evidence, a proposed fix and an effort estimate. The list round two worked through |

The three 2026-09-22 transcripts are the live re-capture the grade-and-fix wave's first round added;
the two rows below them are its second round's grade card. Everything above predates the wave.

**No `ux-w5/`.** The five-wave remediation's W5 was the accessibility pass (skip link, focus
management, 44 px targets, token and painted contrast, dark-theme captures), and its evidence is the
contract and browser tests it added plus the `-dark-1440.png` set inside `ux-final/` — not a
before/after directory of its own. The numbering below it is unchanged so that every wave report's
own references keep resolving.

## What is not here

Screen captures run to hundreds of megabytes, so each wave directory keeps the pairs that show a
finding rather than the whole run: the full sets — 69 to 71 screen ids × 3 viewports, with their
`.txt` DOM dumps, `.numbers.json` and `.overflow.json` sidecars — are one `make ux-capture` away in
the git-ignored `.ux-capture/`, and each wave README names the harness, the stub scripts and the
commit it was captured on. No capture in this directory made a live model call except the ones whose
header says it did, and `.env` was never read by any of them.
