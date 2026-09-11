# P17 brief — GitHub Actions keep-alive for the Render free instance (approved by Sean 2026-09-10)

## Where this fits
Runs LAST, after the two remaining cold-start probes have been measured on the idle instance (the
measured cold start stays in `deployed.md` as the documented no-ping behaviour; RUBRIC5.6 wants
cold-start behaviour documented). Sean's instruction: "implement the GitHub actions keepalive to
remove the cold-start lag." Free-tier facts (performance plan §4 W3-B): Render spins a free
instance down after 15 idle minutes; the workspace has 750 free instance-hours per month and one
always-on instance uses ≈ 744 in a 31-day month; running out suspends free services until the month
resets — it never bills. The repo is public, so Actions minutes are free.

## Required
1. `.github/workflows/keepalive.yml`: `schedule: cron: "*/10 * * * *"` plus `workflow_dispatch`;
   one job, `ubuntu-latest`, ≤ 1 minute, `permissions: {}`; `curl` `GET $DEPLOY_URL/health` (the URL
   from a repository variable `DEPLOY_URL`, falling back to the committed live URL) with `--retry 3`
   and a 60 s max time; print `status`, `app.cold_start`, `app.uptime_ms` from the JSON; the job
   NEVER fails the repo's status on a transient error (exit 0 with a warning) but sets a job summary
   line so a suspended instance is visible in the Actions tab. No secrets; `/health` is ungated.
2. Document: `deployed.md` gains a "Keep-alive" subsection (what it does, the 750-hour arithmetic,
   what happens if hours run out, how to turn it off — disable the workflow), placed right after the
   measured cold-start table, which stays labelled "measured without keep-alive". `README.md` one
   line. `docs/superpowers/specs/…design.md` §14.x: replace the "No keep-alive cron" sentence with the
   decision and its date/reason. `scripts/check_render_hours.py`: keep its 600/750 warn line; add a
   note in its docstring that the keep-alive makes reaching ~744 expected.
3. Tests: a contract test that the workflow file exists, is valid YAML, pings the documented URL's
   `/health`, runs on a schedule of ≤ 10 minutes, and grants no permissions.

## Definition of done
`ruff check .` clean; `pytest -q` green; `check_facts.py`, `pii_check.py` unchanged. Commit
`P17(deploy): …` on `main`; never push (the main session pushes after the final review). Never read
or print `.env`. No subagents. Report to `.superpowers/sdd/2026-09-08-implementation-roadmap/P17-report.md`.

## Also in this wave: the cold-start table becomes n=3
`deployed.md`'s cold-start section currently states one probe. Replace it with the three measured
probes (all after ≥ 1000 s idle, without keep-alive; probe 1 on commit bf85ffd, probes 2–3 on da0dca2):

| Segment | Probe 1 (2026-09-10) | Probe 2 (2026-09-11) | Probe 3 (2026-09-11) | Median |
|---|---|---|---|---|
| Spin-up + container start → `/health` 200 | 44.8 s | 43.5 s | 52.4 s | 44.8 s |
| `/health` 200 → `/ready` 200 | 2.8 s | 0.1 s | 0.1 s | 0.1 s |
| First `POST /chat` | 23.3 s | 23.9 s | 25.2 s | 23.9 s |
| First request total | 71.0 s | 67.5 s | 77.6 s | 71.0 s |
| Warm turn | 22.5 s | 22.5 s | 23.9 s | 22.5 s |

Label it "measured without keep-alive" and keep it directly above the new Keep-alive subsection, so a
reader sees both the documented cold-start behaviour and the mitigation. If `docs/optimization-log.md`
is the only other place quoting n=1, leave it (main-session owned) — the ledger has the figures.

## Also in this wave: three deploy-scoped carry-forwards from the publish step
4. **gitleaks and the grader link.** `README.md`'s `Deployed:` line carries the tokenized grader link
   (`?access=<43-char token>`) by design (spec §11: the token is a speed bump against scanners, public
   to the grader, rotated after grading). CI's lint job runs gitleaks 8.30.1 over the full history.
   Download that exact gitleaks release binary into the scratchpad (GitHub releases, darwin/arm64) and
   run `gitleaks detect --source . --config .gitleaks.toml --redact` (history) and `--no-git` (tree).
   If the README line is flagged, add the NARROWEST allowlist to `.gitleaks.toml`: `[[allowlists]]`
   with `targetRules = ["generic-api-key"]`, `paths = ['^README\.md$']` and a regex anchored on
   `access=`, with a comment stating why this string is intentionally public and where it is rotated.
   Never widen an existing allowlist. Paste gitleaks' output (redacted) in the report. If nothing is
   flagged, say so and change nothing.
5. **`render.yaml` header comment** still says the deploy hook is "the ONLY path from a commit to the
   running service"; CI now POSTs `/v1/services/{id}/deploys`. Fix the comment only; the contract
   tests over render.yaml must stay green unchanged.
6. **`docs/architecture.html`**: the figure-6 SVG node and edge payloads still say "Render deploy hook";
   rename the text to "Render deploy (API)" / matching wording — text only, no restyling, no layout
   change; keep the file's existing tests green.
