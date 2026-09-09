# What Mosaic HR Copilot needs from Sean

Nothing here blocks P0–P9: every phase up to the dashboard builds, tests and passes CI with
`LLM_PROVIDER=stub` and no credentials at all. These two items are requested now only so that
they are never on the critical path when P11 needs them.

- [ ] **2 — Render account + install the Render GitHub App on `seantmalone/quantic-mosaic`.**
      A browser-only OAuth grant; no API can install a GitHub App. Without it Render cannot read
      the repo and no deploy is possible.
      Do it at: https://github.com/apps/render/installations/new → grant access to the repo.
      Needed by: **P11**. Requested: 2026-09-09.
      If it never arrives: no deployment, so RUBRIC5.6 and much of 5.9 fail. The documented
      fallback is Google Cloud Run (same image, but it needs a card), and `make docker-run-512`
      proves the exact image locally regardless.

- [ ] **3 — Turso account + platform token → `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`.**
      Render's free tier has no persistent disk and wipes the filesystem on every 15-minute
      spin-down, so without Turso any chat session the grader creates is lost. Free, no card,
      provisioned unattended by `scripts/provision_turso.py` from one pasted platform token.
      Do it at: https://turso.tech → GitHub SSO → create a Platform API token → paste it in.
      Needed by: any time after **P1**; a pure environment change with no code change.
      Requested: 2026-09-09.
      If it never arrives: `SqliteStore` remains the coded fallback and committed eval results
      still populate the evaluation pages, but every session created after the last deploy —
      including every session the grader starts — is lost at the next spin-down, and
      `deployed.md` says so plainly.

Items 1 (model API keys) and 4–7 (the recording and submission steps) are tracked in the design
spec §19; the keys were supplied on 2026-09-09 and live only in the git-ignored `.env`.
