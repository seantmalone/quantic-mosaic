"""`scripts/measure_cold_start.py` — the four segments, walked in order, against a stub instance.

§14.4 publishes a table of *expectations* and §3.1 lists the real cold start as a fact to be read
on the live instance. The reading itself needs a Render free service that has been idle for sixteen
minutes, which no test can have — so what is pinned here is everything around the stopwatch: that
the probe walks `/health` → `/ready` → `POST /chat` → `POST /chat` in that order, that it polls
`/ready` rather than accepting the first 503, that the gated turns carry the bearer header and the
admin persona, and that `first_request_total_ms` is the sum §14.4's "first request total" row
claims it is.

`idle_s=0` throughout: the idle wait is a `time.sleep` on a wall clock the project deliberately
never abstracts (there is no clock module and no `NOW_OVERRIDE`), so the tests simply do not ask
for one.
"""

from __future__ import annotations

import httpx

from scripts import measure_cold_start

HEALTH = {"status": "ok", "app": {"cold_start": True, "git_sha": "a1b2c3d", "rss_mb": 291.4}}


class StubInstance:
    """Answers the four calls the probe makes; `/ready` is 503 until it has been asked twice."""

    def __init__(self, *, ready_after: int = 2) -> None:
        self.calls: list[tuple[str, str]] = []
        self.headers: list[dict[str, str]] = []
        self._ready_asks = 0
        self._ready_after = ready_after

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.url.path == "/health":
            return httpx.Response(200, json=HEALTH)
        if request.url.path == "/ready":
            self._ready_asks += 1
            if self._ready_asks < self._ready_after:
                return httpx.Response(503, json={"ready": False, "reason": "model not resident"})
            return httpx.Response(200, json={"ready": True})
        if request.url.path == "/chat":
            self.headers.append(dict(request.headers))
            return httpx.Response(200, json={"outcome": "answered", "answer": "…"})
        return httpx.Response(404)


def _measure(instance: StubInstance) -> measure_cold_start.ColdStart:
    with httpx.Client(transport=instance.transport(), base_url="https://x.onrender.com") as client:
        return measure_cold_start.measure(client, "https://x.onrender.com", token="tok", idle_s=0, poll_interval_s=0)


def test_the_probe_walks_the_four_segments_of_14_4_in_order():
    instance = StubInstance(ready_after=1)
    _measure(instance)
    assert instance.calls == [
        ("GET", "/health"),
        ("GET", "/ready"),
        ("POST", "/chat"),
        ("POST", "/chat"),
    ]


def test_ready_is_polled_until_green_not_accepted_at_the_first_503():
    """`/ready` is 503 through the whole ONNX warm-up; that wait *is* the segment (§11.4)."""
    instance = StubInstance(ready_after=3)
    _measure(instance)
    assert [path for _, path in instance.calls].count("/ready") == 3


def test_both_turns_carry_the_bearer_header_and_the_admin_persona():
    instance = StubInstance(ready_after=1)
    _measure(instance)
    assert len(instance.headers) == 2
    for headers in instance.headers:
        assert headers["authorization"] == "Bearer tok"
        assert headers["x-actor"] == "admin"


def test_the_instance_is_asked_whether_it_thought_it_was_cold():
    """A `cold_start: false` on the first `/health` means the idle wait was too short."""
    measurement = _measure(StubInstance(ready_after=1))
    assert measurement.reported_cold is True
    assert measurement.git_sha == "a1b2c3d"


def test_first_request_total_is_the_sum_of_the_three_segments_before_the_warm_turn():
    measurement = measure_cold_start.ColdStart(
        url="https://x.onrender.com",
        measured_at="2026-09-10",
        idle_s=1000,
        health_ms=42_000,
        ready_ms=900,
        first_turn_ms=3_100,
        warm_turn_ms=2_200,
        reported_cold=True,
        git_sha="a1b2c3d",
    )
    assert measurement.first_request_total_ms == 46_000
    rendered = measure_cold_start.markdown(measurement)
    assert "**46.0 s**" in rendered
    assert "**2.2 s**" in rendered
    assert "2026-09-10" in rendered
