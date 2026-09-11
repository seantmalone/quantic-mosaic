# P21 brief — a keep-alive that actually keeps the instance alive, and two resting-state UI fixes

## Finding
The GitHub Actions keep-alive (`.github/workflows/keepalive.yml`, cron `*/10`) ran only twice in the
nine hours after it was pushed (09:48Z and 13:53Z on 2026-09-11; both successes) — GitHub's scheduler
is best-effort and skips or delays low-traffic repos' cron runs. The live instance was found asleep at
14:25Z. So the workflow does not remove the cold-start lag Sean asked to remove.

## Required
1. **Self keep-alive inside the app.** A startup background task in `src/hrmosaic/web/main.py` (same
   lifespan pattern as `_warm_up` / maintenance): when the new setting `keep_alive_url`
   (`KEEP_ALIVE_URL`, default unset → task not started) is set, every `KEEP_ALIVE_INTERVAL_S`
   (default 600) it GETs `{keep_alive_url}/health` through the public hostname with a 30 s timeout,
   logs at DEBUG, never raises, and stops cleanly on shutdown. Rationale (in the docstring): Render
   counts inbound traffic at its edge, and a request to the service's own public URL is inbound; the
   loop runs whenever the instance is up, which is exactly when a ping is needed, and it needs no
   scheduler. Add the two settings to `settings.py`, `.env.example` and the spec's env table (§21 /
   §11) with one sentence each; keep the `.env.example` bijection test green. Tests: task not created
   when unset; created when set; the loop calls the client on its schedule with a patched sleep and
   survives a client exception; shutdown cancels it.
2. **Keep the GitHub workflow** as the second layer; amend `deployed.md`'s Keep-alive subsection to
   state the measured scheduler behaviour (two runs in nine hours), that the in-process self-ping is
   the primary mechanism, and that the 744-of-750-hour arithmetic is unchanged. One sentence in
   README's deployment section. Update `.github/workflows/keepalive.yml`'s header comment.
3. **Resting-state UI (chat.html).** At page load, before any turn: (a) the provisional-answer area
   and its caption "Writing the answer… this preview is replaced by the checked answer when the turn
   finishes." are visible with an empty box — hide them until the first `answer_delta` frame arrives
   and hide them again on `turn_completed` once the final answer has replaced the preview; (b) the
   "Waking the free instance…" banner with its elapsed counter stays on screen after the app has
   answered — hide it as soon as the first `/health` (or the page's own load) succeeds, and only show
   it while a request is actually waiting. Keep the served-HTML contract tests honest (update the
   assertions to the new resting-state markup; never weaken them).

## Definition of done
`ruff check .` / `ruff format --check` clean; `pytest -q` pristine (baseline 1,901 at 753596e);
`make coverage` still ≥ 90%; `check_facts.py`, `pii_check.py`, `--verify-manifest` unchanged;
`make demo1` then `make demo2` (separately) green. Commits `P21(web): …` / `P21(deploy): …` on `main`;
never push; never read or print `.env`; never call a live LLM; the live URL may be read with GET
/health only. No subagents. Report to `.superpowers/sdd/2026-09-08-implementation-roadmap/P21-report.md`.
