# P25 brief — publish pass after the model-behaviour wave

## Where this fits
P24 changed prompts, a guardrail and the dataset (28 items); the main session re-drove the deployed
sweep (three arms), judged the baseline, re-authored the blind labels and recomputed agreement. This
pass writes the resulting numbers and the two verified live facts into the graded documents. Values
come only from files; never invent a number; the live URL may be read with GET /health only.

## Sources
- `evaluation/results/latest.json`, `comparison.json`, the newest `r_*_baseline.json` (FINAL run —
  its id is in the ledger's "final sweep 2" entry), and the earlier columns r_1789055103_baseline
  (before), r_1789069158_baseline (after P13), r_1789086979_baseline (after Waves 1–2).
- `.superpowers/sdd/2026-09-08-implementation-roadmap/progress.md` (rulings; the verification that the
  public MCP endpoint answered an external `initialize` with HTTP 200 on 2026-09-11 20:32Z).
- `docs/optimization-log.md` is main-session owned: read it, do not edit it.

## Required edits
1. `python scripts/paste_eval_numbers.py` (and `--check`) so README's results block shows the FINAL
   run with the before column; refresh every hand-written metric in `design-and-evaluation.md`
   (results table, strict-pass cause table, ablation table, agreement figures, dataset count 28,
   known limitations), `docs/requirements-traceability.md` (rows that cite figures), `deployed.md`
   (the eval sha rows: target sha and harness sha now recorded by the runner), `ai-tooling.md` if it
   quotes counts, `docs/demo-script.md`'s evaluation beat.
2. MCP endpoint wording: every place P23 changed to say the endpoint answers 421 (mcp/README.md,
   design-and-evaluation.md, deployed.md, docs/architecture.html, NEEDS-FROM-USER.md gate 2b) now says
   the public mount accepts external clients (verified 2026-09-11 20:32Z with an `initialize` over the
   public hostname; `MCP_ALLOWED_HOSTS` set on the service and in render.yaml) and remove gate 2b as
   discharged. Keep the sentence that says `/dashboard/mcp` and `mcp/run_stdio.sh` are the other two
   ways to see the tools.
3. `CHANGELOG.md`: entries for P23, P24 and this pass, in the file's voice, one line each with the
   measured effect where known.
4. `docs/pre-submission-checklist.md`: tick what is now done; leave the demo video and the dashboard
   submission open. `NEEDS-FROM-USER.md`: same.
5. `docs/demo-script.md`: keep the cautions honest to what the FINAL run shows for demo-1/demo-2
   citation breadth (read the final run's items for those prompts, or the committed live transcripts).

## Definition of done
`ruff check .` clean; `pytest -q` pristine (the docs-completeness tests must pass with your values);
`scripts/check_facts.py`, `scripts/pii_check.py` clean; `python scripts/paste_eval_numbers.py --check`
OK. Commit `P25(docs): …` on `main`; never push; never read or print `.env`. No subagents. Report to
`.superpowers/sdd/2026-09-08-implementation-roadmap/P25-report.md` with every value and its source.
