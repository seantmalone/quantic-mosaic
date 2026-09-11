# The process trail — briefs, reports and the ledger

This directory is the **committed audit trail** behind `ai-tooling.md`'s AI-use disclosure. It is a
verbatim copy of the working directory the build ran out of
(`.superpowers/sdd/2026-09-08-implementation-roadmap/`, which is git-ignored), so a reader can check
the disclosure against the artifacts rather than take it on trust.

## What is here

| File | What it is |
|---|---|
| `progress.md` | The ledger: one row per phase, its status, and the commit range each review covered |
| `P<n>-brief.md` | The requirements handed to the implementing session for that phase — written before any code |
| `P<n>-report.md` | What that session built, the definition-of-done command output pasted verbatim, its self-review, and the ambiguities it resolved |
| `final-review-brief.md` | The brief for the end-to-end review pass |
| `grade-card-2026-09-11.md` | An independent, read-only grading pass against `docs/project-requirements.md` — the source of the P23 fixes |
| `constraints.md` | The global constraints every phase was held to, copied from the design spec |

## What is deliberately not here

* **The review diffs** (`review-<a>..<b>.diff`). They are byte-for-byte reproducible from the
  repository — `git diff <a>..<b>` — and together they run to tens of megabytes.
* **The controller's handoff JSON.** It is scheduling state for the orchestration, not a record of
  a decision, and it carries no argument a reader would want.
* **`.env` and every credential.** Nothing here was ever allowed to read it. The files were scanned
  for `sk-ant-…`, `sk-…`, `AIza…`, JWT and GitHub-token shapes and for the live access token before
  being copied; the only matches are the deliberately synthetic placeholders quoted inside test
  output (`sk-ant-api03-AAAA…`, `ci-access-token`), and `gitleaks` 8.30.1 reads the tree clean.

## How to read it

`CHANGELOG.md` is the narrative, one dated section per phase. This directory is the evidence under
it: for any claim in the changelog, the brief says what was asked and the report says what was
delivered and shows the commands that proved it. The design history — specs, plans and the
brainstorm that preceded them — is in `docs/superpowers/`.

These are working documents, reproduced unedited. They record wrong turns, corrections and
disagreements, which is the point of an audit trail.
