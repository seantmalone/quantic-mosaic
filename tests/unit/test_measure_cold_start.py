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

import inspect

import httpx
import pytest

from scripts import measure_cold_start

HEALTH = {"status": "ok", "app": {"cold_start": True, "git_sha": "a1b2c3d", "rss_mb": 291.4}}


class StubInstance:
    """Answers the four calls the probe makes; `/ready` is 503 until it has been asked twice.

    `ready_after=None` means it never greens, `health_status` and `chat_status` make a segment
    answer something other than 200 — the three ways a live measurement fails on a real instance.
    """

    def __init__(
        self,
        *,
        ready_after: int | None = 2,
        health_status: int = 200,
        chat_status: int = 200,
        chat_body: dict | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.headers: list[dict[str, str]] = []
        self._ready_asks = 0
        self._ready_after = ready_after
        self._health_status = health_status
        self._chat_status = chat_status
        self._chat_body = chat_body or {"outcome": "answered", "answer": "…"}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.url.path == "/health":
            return httpx.Response(self._health_status, json=HEALTH)
        if request.url.path == "/ready":
            self._ready_asks += 1
            if self._ready_after is None or self._ready_asks < self._ready_after:
                return httpx.Response(503, json={"ready": False, "reason": "model not resident"})
            return httpx.Response(200, json={"ready": True})
        if request.url.path == "/chat":
            self.headers.append(dict(request.headers))
            return httpx.Response(self._chat_status, json=self._chat_body)
        return httpx.Response(404)


def _measure(instance: StubInstance, *, ready_timeout_s: float = 180.0) -> measure_cold_start.ColdStart:
    with httpx.Client(transport=instance.transport(), base_url="https://x.onrender.com") as client:
        return measure_cold_start.measure(
            client,
            "https://x.onrender.com",
            token="tok",
            idle_s=0,
            poll_interval_s=0,
            ready_timeout_s=ready_timeout_s,
        )


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


# --- a measurement that cannot fail is not a measurement --------------------------------------


def test_a_chat_that_403s_is_a_failed_measurement_not_a_first_turn_latency():
    """`httpx` does not raise on 4xx, so without an explicit check a 403 was *timed* and published.

    A wrong or expired `APP_ACCESS_TOKEN`, or a persona that is not `admin`, answers 403 in
    milliseconds — which would have gone into `deployed.md`'s `## Cold start` as this project's
    published "first turn" figure.
    """
    instance = StubInstance(ready_after=1, chat_status=403, chat_body={"code": "ADMIN_REQUIRED"})
    with pytest.raises(measure_cold_start.MeasurementFailed) as raised:
        _measure(instance)
    assert "403" in str(raised.value)
    assert "ADMIN_REQUIRED" in str(raised.value)
    assert "first POST /chat" in str(raised.value)


def test_a_ready_that_never_greens_fails_instead_of_recording_the_timeout():
    """Falling out of the poll used to record `ready_timeout_s` as the model-load segment."""
    instance = StubInstance(ready_after=None)
    with pytest.raises(measure_cold_start.MeasurementFailed) as raised:
        _measure(instance, ready_timeout_s=0.05)
    assert "/ready never answered 200" in str(raised.value)
    assert ("POST", "/chat") not in instance.calls


def test_a_health_that_is_not_200_is_a_failed_measurement():
    """`/health` is always 200 while the process is up (§11.4); anything else is not measurable."""
    instance = StubInstance(ready_after=1, health_status=502)
    with pytest.raises(measure_cold_start.MeasurementFailed) as raised:
        _measure(instance)
    assert "502" in str(raised.value)
    assert ("GET", "/ready") not in instance.calls


def test_a_failed_segment_exits_non_zero_rather_than_printing_a_table(monkeypatch, capsys):
    """`main` must not paste a table built from a 403 into the operator's console."""
    instance = StubInstance(ready_after=1, chat_status=403, chat_body={"code": "ADMIN_REQUIRED"})
    real_client = httpx.Client
    monkeypatch.setenv("APP_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(
        measure_cold_start.httpx,
        "Client",
        lambda **kwargs: real_client(transport=instance.transport(), **kwargs),
    )
    exit_code = measure_cold_start.main(["--url", "https://x.onrender.com", "--idle", "0"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "FAIL" in captured.err
    assert "First request total" not in captured.out


# --- the ready timeout the first live probe blew through -------------------------------------


def test_the_ready_timeout_is_generous_enough_for_a_free_instance():
    """180 s was measured against the local image, where `/ready` greens in 2.6 s.

    Render's free plan gives 0.1 of a CPU and `/health` — its health-check path — answers 200 while
    the ONNX model is still loading, so the first live cold probe on 2026-09-10 timed out at 180 s
    without producing a figure. A ceiling that stops the measurement before the thing being measured
    has finished is a missing number, not a safeguard.
    """
    assert measure_cold_start.DEFAULT_READY_TIMEOUT_S >= 600


def test_the_ready_timeout_is_settable_from_the_command_line():
    parser_default = measure_cold_start.main.__globals__["DEFAULT_READY_TIMEOUT_S"]
    assert parser_default == measure_cold_start.DEFAULT_READY_TIMEOUT_S
    signature = inspect.signature(measure_cold_start.measure)
    assert signature.parameters["ready_timeout_s"].default == measure_cold_start.DEFAULT_READY_TIMEOUT_S
