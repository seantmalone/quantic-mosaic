"""Report the month's Render free-tier consumption — and only ever **warn** (spec §14.1, §3.1).

    RENDER_API_KEY=… python scripts/check_render_hours.py

Two free-tier budgets bind this project: **750 instance-hours** per workspace per calendar month
and **500 build-pipeline minutes**. Both were re-read live at P11 step 0 and dated in
`deployed.md`; this script is what keeps them honest afterwards, and its output goes into
`deployed.md`'s `## Cost` so the remaining headroom is arithmetic rather than a guess.

**Render publishes no usage or billing endpoint**, so both figures are *derived* from endpoints
that do exist, and the derivation is stated rather than hidden:

* **instance-hours** — `GET /v1/resources/metrics/instance-count` sampled hourly over the month to
  date, integrated as `Σ value_i × (t_{i+1} − t_i)`. On the free tier the count is 1 while the
  service is awake and 0 for the 15-minute-idle spin-downs, which is precisely why §14.4 refuses a
  keep-alive cron: pinging round the clock would consume ~744 of the 750 hours.
* **build-minutes** — the wall-clock of every deploy created this month, from
  `GET /v1/services/{id}/deploys`. It is an upper bound on pipeline minutes (a deploy's clock
  includes the post-build rollout), which is the right direction for a budget warning to err in.

Both are approximations of the dashboard's own numbers and say so on every line. **The exit status
is always 0.** §14.1 says warn, never fail: a budget check that could break a build would be
deleted rather than heeded.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # `python scripts/<name>.py` puts this file's own directory on sys.path, not the repository
    # root, so the sibling `scripts.provision_render` import below would not resolve.
    sys.path.insert(0, str(REPO_ROOT))

from scripts.provision_render import RenderApiError, RenderClient, load_blueprint  # noqa: E402

#: The free-tier budgets of §14.1, and the thresholds at which this script speaks up.
INSTANCE_HOURS_BUDGET = 750
INSTANCE_HOURS_WARN = 600
BUILD_MINUTES_BUDGET = 500
BUILD_MINUTES_WARN = 400

#: Hourly samples: fine enough to see a spin-down, coarse enough for one request per month.
RESOLUTION_SECONDS = 3600


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def month_start(now: datetime | None = None) -> str:
    """The first instant of the current calendar month, which is what Render bills against."""
    moment = now or datetime.now(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def instance_hours(series: list[dict[str, Any]]) -> float:
    """Integrate every resource's instance-count series: `Σ value_i × (t_{i+1} − t_i)` in hours."""
    total = 0.0
    for resource in series:
        samples = resource.get("values") or []
        for current, following in zip(samples, samples[1:], strict=False):
            span_s = (_parse(following["timestamp"]) - _parse(current["timestamp"])).total_seconds()
            total += float(current["value"]) * span_s / 3600.0
    return total


def build_minutes(deploys: list[dict[str, Any]], *, since: str) -> float:
    """Sum the wall-clock of every deploy created on or after `since`; unfinished ones count 0."""
    floor = _parse(since)
    total = 0.0
    for row in deploys:
        deploy = row.get("deploy") or row
        created, finished = deploy.get("createdAt"), deploy.get("finishedAt")
        if not created or not finished:
            continue
        if _parse(created) < floor:
            continue
        total += (_parse(finished) - _parse(created)).total_seconds() / 60.0
    return total


def warnings_for(*, instance_hours: float, build_minutes: float) -> list[str]:
    """One line per budget in the danger zone. Empty means there is nothing to say."""
    found: list[str] = []
    if instance_hours > INSTANCE_HOURS_WARN:
        found.append(
            f"instance hours this month are ~{instance_hours:.0f} of {INSTANCE_HOURS_BUDGET} "
            f"(warning above {INSTANCE_HOURS_WARN}): the service will stop serving when the budget runs out"
        )
    if build_minutes > BUILD_MINUTES_WARN:
        found.append(
            f"build minutes this month are ~{build_minutes:.0f} of {BUILD_MINUTES_BUDGET} "
            f"(warning above {BUILD_MINUTES_WARN}): with no payment method Render disables new builds "
            "for the rest of the month"
        )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--service-id", default=os.environ.get("RENDER_SERVICE_ID"), help="srv-… (default: by name)")
    arguments = parser.parse_args(argv)

    api_key = os.environ.get("RENDER_API_KEY")
    if not api_key:
        # Warn, never fail (§14.1) — including about our own missing input.
        print("RENDER_API_KEY is unset; skipping the free-tier budget check (user gate 4).", file=sys.stderr)
        return 0

    since = month_start()
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    client = RenderClient(api_key)
    try:
        service_id = arguments.service_id
        if not service_id:
            service = client.find_service(load_blueprint().name)
            if service is None:
                print("no Render service found for the committed render.yaml; nothing to measure.", file=sys.stderr)
                return 0
            service_id = str(service["id"])

        series = client.get_json(
            "/v1/resources/metrics/instance-count",
            {"resource": service_id, "startTime": since, "endTime": now, "resolutionSeconds": RESOLUTION_SECONDS},
        )
        deploys = client.get_json(f"/v1/services/{service_id}/deploys", {"limit": 100})
    except (RenderApiError, httpx.HTTPError) as exc:
        print(f"could not read Render usage ({exc}); skipping the budget check.", file=sys.stderr)
        return 0
    finally:
        client.close()

    hours = instance_hours(series)
    minutes = build_minutes(deploys, since=since)
    print(
        f"  since {since}\n"
        f"  instance hours ~{hours:.1f} of {INSTANCE_HOURS_BUDGET} "
        f"({INSTANCE_HOURS_BUDGET - hours:.1f} left) — derived from the instance-count metric\n"
        f"  build minutes  ~{minutes:.1f} of {BUILD_MINUTES_BUDGET} "
        f"({BUILD_MINUTES_BUDGET - minutes:.1f} left) — derived from deploy wall-clock, an upper bound"
    )
    for warning in warnings_for(instance_hours=hours, build_minutes=minutes):
        print(f"  WARNING — {warning}")
    print("\nBoth figures are approximations of the dashboard's own; the dashboard is authoritative.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
