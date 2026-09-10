"""`scripts/check_render_hours.py` — the free-tier budget warning that must never fail (spec §14.1).

Two free-tier budgets bind this project: **750 instance-hours** per workspace per month and **500
build-pipeline minutes**. Render's REST API publishes no billing or usage endpoint, so the script
derives both from what the API *does* expose — the `instance-count` metric time series, integrated
over the month to date, and the wall-clock of each deploy in the same window. The arithmetic is
what these tests pin, because the numbers land in `deployed.md` and a wrong one would either hide
an overrun or invent a scare.

The other half of the contract is the exit status. §14.1: the script **warns, never fails**. A
budget check that could break a build would eventually be deleted rather than heeded, so
`warnings_for()` returns strings and `main()` returns 0 whatever it found.
"""

from __future__ import annotations

from scripts import check_render_hours as usage

HOUR = 3600


def _series(values: list[tuple[str, float]]) -> list[dict]:
    return [
        {
            "labels": [{"field": "resource", "value": "srv-1"}],
            "values": [{"timestamp": timestamp, "value": value} for timestamp, value in values],
            "unit": "count",
        }
    ]


# --- instance hours -----------------------------------------------------------------------


def test_one_instance_running_for_three_hours_is_three_instance_hours():
    hours = usage.instance_hours(
        _series(
            [
                ("2026-09-01T00:00:00Z", 1),
                ("2026-09-01T01:00:00Z", 1),
                ("2026-09-01T02:00:00Z", 1),
                ("2026-09-01T03:00:00Z", 1),
            ]
        )
    )
    assert hours == 3.0


def test_the_idle_hours_of_a_spun_down_instance_cost_nothing():
    """The whole free-tier argument of §14.4: no keep-alive cron, so idle time is free.

    Awake for the first hour, spun down for the next two, awake again at the last sample — which
    is the *left* endpoint of an interval that has not closed yet, so it contributes nothing to a
    month-to-date figure and the answer is one hour, not three.
    """
    hours = usage.instance_hours(
        _series(
            [
                ("2026-09-01T00:00:00Z", 1),
                ("2026-09-01T01:00:00Z", 0),
                ("2026-09-01T02:00:00Z", 0),
                ("2026-09-01T03:00:00Z", 1),
            ]
        )
    )
    assert hours == 1.0


def test_an_empty_or_single_sample_series_is_zero_not_a_crash():
    assert usage.instance_hours([]) == 0.0
    assert usage.instance_hours(_series([("2026-09-01T00:00:00Z", 1)])) == 0.0


def test_every_resource_in_the_response_is_counted():
    """A workspace's 750 hours are shared across services, so the budget sums them."""
    two = _series([("2026-09-01T00:00:00Z", 1), ("2026-09-01T01:00:00Z", 1)])
    two.append(dict(two[0]))
    assert usage.instance_hours(two) == 2.0


# --- build minutes ------------------------------------------------------------------------


def _deploy(created: str, finished: str | None) -> dict:
    return {"deploy": {"id": "dep-1", "createdAt": created, "finishedAt": finished, "status": "live"}}


def test_build_minutes_sum_the_wall_clock_of_each_deploy_this_month():
    minutes = usage.build_minutes(
        [
            _deploy("2026-09-02T10:00:00Z", "2026-09-02T10:04:30Z"),
            _deploy("2026-09-03T10:00:00Z", "2026-09-03T10:05:30Z"),
        ],
        since="2026-09-01T00:00:00Z",
    )
    assert minutes == 10.0


def test_deploys_from_last_month_do_not_count_against_this_month():
    minutes = usage.build_minutes(
        [
            _deploy("2026-08-31T23:00:00Z", "2026-08-31T23:10:00Z"),
            _deploy("2026-09-02T10:00:00Z", "2026-09-02T10:04:00Z"),
        ],
        since="2026-09-01T00:00:00Z",
    )
    assert minutes == 4.0


def test_a_deploy_still_running_contributes_nothing_yet():
    assert usage.build_minutes([_deploy("2026-09-02T10:00:00Z", None)], since="2026-09-01T00:00:00Z") == 0.0


# --- the warnings -------------------------------------------------------------------------


def test_a_quiet_month_produces_no_warning():
    assert usage.warnings_for(instance_hours=120.0, build_minutes=60.0) == []


def test_instance_hours_above_the_threshold_warn():
    reported = usage.warnings_for(instance_hours=601.0, build_minutes=0.0)
    assert len(reported) == 1
    assert "601" in reported[0]
    assert str(usage.INSTANCE_HOURS_BUDGET) in reported[0]


def test_build_minutes_above_the_threshold_warn():
    reported = usage.warnings_for(instance_hours=0.0, build_minutes=401.0)
    assert len(reported) == 1
    assert str(usage.BUILD_MINUTES_BUDGET) in reported[0]


def test_the_thresholds_are_the_documented_ones():
    assert (usage.INSTANCE_HOURS_WARN, usage.INSTANCE_HOURS_BUDGET) == (600, 750)
    assert (usage.BUILD_MINUTES_WARN, usage.BUILD_MINUTES_BUDGET) == (400, 500)
    assert usage.warnings_for(instance_hours=600.0, build_minutes=400.0) == []


def test_both_budgets_can_warn_at_once():
    assert len(usage.warnings_for(instance_hours=700.0, build_minutes=450.0)) == 2


# --- what the first live run corrected ------------------------------------------------------


def test_the_instance_count_metric_path_has_no_resources_segment():
    """`/v1/resources/metrics/instance-count` answered `404 page not found` on 2026-09-10.

    The script's own warn-never-fail path swallowed that into "skipping the budget check", which is
    the correct behaviour for an outage and the wrong behaviour for a wrong URL — so the path is
    pinned here rather than left to the next live run to rediscover.
    """
    assert usage.INSTANCE_COUNT_METRIC == "/v1/metrics/instance-count"


def test_an_empty_metric_series_is_reported_as_unavailable_not_as_zero_hours():
    """Render answers 200 with `[]` for a free instance type; `~0.0 of 750` would be a lie."""
    assert usage.has_samples([]) is False
    assert usage.has_samples([{"values": []}]) is False
    assert usage.has_samples([{"values": [{"timestamp": "2026-09-01T00:00:00Z", "value": 1}]}]) is True
