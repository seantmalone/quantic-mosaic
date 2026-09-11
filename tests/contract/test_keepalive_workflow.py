"""The keep-alive workflow, asserted as a contract (spec §14.4).

`.github/workflows/keepalive.yml` is the mitigation for the cold start `deployed.md` measures and
publishes: a scheduled `GET /health` often enough that Render's 15-minute idle spin-down never
fires. Like the deployment manifests next door, GitHub Actions runs it and pytest cannot, so the
properties that carry the argument are pinned here rather than left to a reviewer's eye.

The load-bearing ones, and what each would cost if it drifted:

* **The schedule is at most ten minutes.** Render spins a free instance down after 15 idle
  minutes, so a longer interval stops being a keep-alive; ten leaves headroom for GitHub's own
  scheduler lag.
* **It pings the URL the repository documents.** The fallback literal is the live origin on
  `README.md`'s `Deployed:` line, so the workflow cannot quietly keep some other service warm if
  the repository variable is unset.
* **It grants no permissions and reads no secret.** `/health` is an open route (§11.5), so this
  job needs neither a token nor write access to anything; `permissions: {}` says so in the file.
* **It can never fail the repository's status.** A suspended instance, a Render outage or a
  GitHub network blip must not paint `main` red — the ping reports and exits 0, and writes the
  outcome to the job summary so a suspended service is still visible in the Actions tab.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_TEXT = (ROOT / ".github/workflows/keepalive.yml").read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)
README_TEXT = (ROOT / "README.md").read_text(encoding="utf-8")


def _triggers() -> dict:
    """The `on:` block.

    PyYAML reads YAML 1.1, where the bare key `on` is the boolean `True` — so the block has to be
    fetched under both spellings for the assertion to be about the workflow rather than about the
    parser.
    """
    return WORKFLOW.get("on", WORKFLOW.get(True))


def _job() -> dict:
    (only,) = WORKFLOW["jobs"].values()
    return only


def _run_lines() -> str:
    return "\n".join(str(step.get("run", "")) for step in _job()["steps"])


def _documented_origin() -> str:
    """The scheme and host of `README.md`'s `Deployed:` link, without its `?access=` token."""
    line = next(line for line in README_TEXT.splitlines() if line.startswith("Deployed:"))
    url = urlsplit(line.split(":", 1)[1].strip())
    return f"{url.scheme}://{url.netloc}"


def test_the_workflow_is_valid_yaml_with_exactly_one_ubuntu_job():
    assert isinstance(WORKFLOW, dict)
    assert len(WORKFLOW["jobs"]) == 1
    assert _job()["runs-on"] == "ubuntu-latest"


def test_the_schedule_pings_at_least_as_often_as_every_ten_minutes():
    """Render spins a free instance down after 15 idle minutes (§14.4)."""
    crons = [entry["cron"] for entry in _triggers()["schedule"]]
    assert crons, "the workflow carries no `schedule:`"
    for cron in crons:
        minute = cron.split()[0]
        match = re.fullmatch(r"\*/(\d+)", minute)
        assert match, f"{cron!r} is not a fixed every-N-minutes schedule"
        assert int(match.group(1)) <= 10, f"{cron!r} pings less often than every ten minutes"


def test_it_can_also_be_triggered_by_hand():
    """A grader's tab is warmed on demand, and the ping is testable without waiting ten minutes."""
    assert "workflow_dispatch" in _triggers()


def test_the_job_grants_no_permissions():
    """`/health` is open (§11.5): this job needs no `GITHUB_TOKEN` scope at all."""
    assert _job()["permissions"] == {}


def test_the_job_is_bounded_in_time():
    """One ping, one curl budget: a hung job must not sit on a runner for six hours."""
    assert 0 < _job()["timeout-minutes"] <= 2


def test_it_pings_the_health_endpoint_of_the_url_the_repository_documents():
    """The repository variable wins; the committed live origin is the fallback."""
    url = str(_job()["env"]["DEPLOY_URL"])
    assert "vars.DEPLOY_URL" in url
    assert _documented_origin() in url
    assert "/health" in _run_lines()


def test_the_curl_retries_and_is_bounded_at_sixty_seconds():
    """A cold instance answers `/health` in ~45 s; a dead one must not hold the job open."""
    runs = _run_lines()
    assert "--retry 3" in runs
    assert "--max-time 60" in runs


def test_it_reports_the_three_health_fields_that_say_whether_the_ping_worked():
    """`status`, `app.cold_start` and `app.uptime_ms` are the payload of `/health` (§11.5)."""
    runs = _run_lines()
    for field in (".status", ".app.cold_start", ".app.uptime_ms"):
        assert field in runs, f"the ping never reads {field} out of the payload"


def test_a_transient_failure_warns_and_still_exits_zero():
    """R-10: an exhausted free tier suspends the service — that is news, not a broken build."""
    runs = _run_lines()
    assert "exit 1" not in runs, "the keep-alive must never fail the repository's status"
    assert "exit 0" in runs
    assert "::warning::" in runs


def test_the_outcome_reaches_the_job_summary():
    """So a suspended instance is visible in the Actions tab without opening the log."""
    assert "GITHUB_STEP_SUMMARY" in _run_lines()


def test_the_keep_alive_needs_no_secret():
    """§15.2's invariant, extended: nothing here holds a credential the application answers with."""
    assert "secrets." not in WORKFLOW_TEXT
