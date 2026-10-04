# Evidence — what is here, when it was taken, and on which build

Every artifact in this directory is a capture of something that actually ran: a live transcript, a
screen set, a probe or a labelling packet. Each was taken on the build named in its row, and its
header is left as written on that date. The build the **published evaluation run measures is
`34d50fb`**: run `r_1790130220_baseline`, driven 2026-09-23 over the 30-item dataset, the run
`evaluation/results/latest.json` points at and the one `evaluation/REPORT.md`,
`design-and-evaluation.md`, `README.md` and `deployed.md` publish. Artifacts captured on earlier
builds are kept as dated records. A header that calls its build "the final build" means the latest
build on the date it was written.

`git log --diff-filter=A -1 -- docs/evidence/<name>` gives the commit any artifact was added in.
That is how the *Build* column is filled for the screen sets, which record a harness and a date
rather than a service sha.

## Index

| Artifact | Date | Build | What it shows |
|---|---|---|---|
| [`mcp-discovery-4-tools.json`](mcp-discovery-4-tools.json) | 2026-09-09 | added at `15bdfe2` | `tools/list` from the ablation arm's separate stdio server: 4 tools, with the five structured-data and write tools absent from discovery itself. |
| [`mcp-discovery-4-tools.png`](mcp-discovery-4-tools.png) | 2026-09-10 | added at `73eb047` | The same 4-tool discovery on screen, beside the five removed tool names. |
| [`mcp-discovery-page.png`](mcp-discovery-page.png) | 2026-09-10 | added at `70faf71` | `/dashboard/mcp` rendering live discovery: the connected server, its 9 tools and every tool's input and output schema. |
| [`ci-deploy-skipped.png`](ci-deploy-skipped.png) | 2026-09-10 | added at `5419ec5` | A recorded red CI run (run `34485304411`) in which `test` fails and `deploy` is skipped with *"dependent job failed"*. |
| [`cold-start-probes.json`](cold-start-probes.json) | 2026-09-10 → 11 | probe 1 on `bf85ffd`, probes 2–3 on `da0dca2` | The three live cold-start probes behind `deployed.md`'s `## Cold start`: per-segment seconds, their medians and their `n`. |
| [`demo-task-1-live-2026-09-11.txt`](demo-task-1-live-2026-09-11.txt) | 2026-09-11 | `e13a772` (deployed `/health`) | Demo task 1, international remote-work eligibility, driven live against the deployed service. |
| [`demo-task-2-live-2026-09-11.txt`](demo-task-2-live-2026-09-11.txt) | 2026-09-11 | `e13a772` (deployed `/health`) | Demo task 2, a PTO request through the confirmation gate to a mock write, with a citation-breadth caveat in its header. |
| [`demo-task-2-live-2026-09-12.txt`](demo-task-2-live-2026-09-12.txt) | 2026-09-12 | `f5e86c3` | Demo task 2 re-run after a citation-breadth fix: the confirmation card, nothing written, then the confirmed write (ticket `MOCK-HR-000006`). |
| [`mcp-external-session-2026-09-12.txt`](mcp-external-session-2026-09-12.txt) | 2026-09-12 | `f5e86c3` | The deployed MCP mount reached from outside by plain `curl`: `initialize`, `tools/list` returning all nine tools, and a real `search_policy_documents` call. |
| [`brand-preview.html`](brand-preview.html) | 2026-09-14 | added at `7792090` | The visual identity in one self-contained page: the mark, the type pairing and the colour tokens, light and dark side by side. |
| [`ux-final/`](ux-final/) | 2026-09-15 | added at `3c94353` | 39 screens of every surface at 1440 px, at phone width and in dark mode, captured by `make ux-capture` against stub servers; see its README. |
| [`final-2026-09-16/`](final-2026-09-16/) | 2026-09-16 | `bd4ac93` | Six Playwright screens and `answer.txt` taken against the deployed service with one real model turn; see its README. |
| [`demo-task-1-live-2026-09-22.txt`](demo-task-1-live-2026-09-22.txt) | 2026-09-22 | `8782177`, a docs-only commit over app build `8a89310` | Demo task 1 as the first turn of a cold instance: 38.2 s of turn time over 39 spans, 8 passages across four documents. |
| [`demo-task-2-live-2026-09-22.txt`](demo-task-2-live-2026-09-22.txt) | 2026-09-22 | `8782177`, a docs-only commit over app build `8a89310` | Demo task 2 on a warm instance: the confirmation card, nothing written, then the confirmed write, with the two `mcp_discovery` spans a resumed turn carries. |
| [`draft-hr-email-live-2026-09-22.txt`](draft-hr-email-live-2026-09-22.txt) | 2026-09-22 | `8782177`, a docs-only commit over app build `8a89310` | `draft_hr_email` live with both endings, the same request confirmed once and cancelled once. |
| [`label-packet-seed-2026-09-23.md`](label-packet-seed-2026-09-23.md) | 2026-09-23 | `34d50fb` (published build) | The exact packet the blind labeller read for the 8 `seed_1729_8` items; its labels are `evaluation/reference_labels.yaml` (`judge_agreement_rate` **0.875, n = 8**). |
| [`label-packet-hard-2026-09-23.md`](label-packet-hard-2026-09-23.md) | 2026-09-23 | `34d50fb` (published build) | The same for the `judge_lowest_8` subset, with the selection criterion hidden and items in id order; its labels are `evaluation/reference_labels_hard.yaml` (`judge_agreement_rate_hard` **0.750, n = 8**). |

**Why the label packets are here.** A reader cannot check from the label files alone that the
labeller was blind, because a packet that had leaked a judge score would produce labels of the same
shape. So the inputs are published. Each packet holds the question, the answer the deployed service
served in `r_1790130220_baseline` and the evidence envelopes the synthesis prompt carried. It holds
no judge verdict, rationale or groundedness score, and the hard packet carries a neutral subset name
and no score ordering. `scripts/gen_label_packet.py` never reads scores or verdicts. The packets are
copies of the files the labelling sessions were given and have not been edited since.
`design-and-evaluation.md`'s *Judge methodology* section points at them.

## What is not here

Full screen captures run to hundreds of megabytes, so they are not committed. The full set is
**72** screen ids × 3 viewports (390 captures), with `.txt` DOM dumps and `.numbers.json` and
`.overflow.json` sidecars. `make ux-capture` regenerates it into the git-ignored `.ux-capture/` and
prints the count at the end of its run. No capture in this directory made a live model call except
the ones whose header says so, and none of them read `.env`.
