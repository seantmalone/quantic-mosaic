"""The token bucket lets a whole turn through, then paces (spec §9.4).

A typical turn makes five or six provider calls. Under strict pacing at `LLM_RPM = 10` that is
~30 s of sleep before any provider latency, and an ordinary turn blows `AGENT_WALL_CLOCK_S`. So a
full bucket must admit the whole turn at once — asserted here against the **real** clock, since a
fake one could hide a bug that only wall-clock time reveals — while the calls after it pace at
`60 / LLM_RPM` seconds each, asserted against an injected clock so the test does not spend thirty
seconds proving it.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from hrmosaic.core.llm.limiter import TokenBucket

RPM = 10
BURST = 6
SECONDS_PER_TOKEN = 60.0 / RPM


class FakeClock:
    """A monotonic clock that only ever advances because someone slept."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_a_full_bucket_admits_a_whole_turn_with_no_delay():
    bucket = TokenBucket(capacity=BURST, refill_per_second=RPM / 60.0)

    async def drain() -> list[int]:
        return [await bucket.acquire() for _ in range(BURST)]

    started = time.monotonic()
    waits = asyncio.run(drain())
    elapsed_ms = (time.monotonic() - started) * 1000

    assert waits == [0] * BURST
    assert elapsed_ms < 50, f"six back-to-back calls slept {elapsed_ms:.1f} ms"


def test_the_calls_after_the_burst_pace():
    clock = FakeClock()
    bucket = TokenBucket(
        capacity=BURST,
        refill_per_second=RPM / 60.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    async def drain() -> list[int]:
        return [await bucket.acquire() for _ in range(11)]

    waits = asyncio.run(drain())

    assert waits[:BURST] == [0] * BURST, "the burst must stay free"
    paced = waits[BURST:]
    assert len(paced) == 5
    for wait_ms in paced:
        assert wait_ms == pytest.approx(SECONDS_PER_TOKEN * 1000, rel=0.02)
    # Eleven calls at LLM_RPM = 10 cost the five tokens the bucket did not hold, and no more.
    assert clock.now == pytest.approx(5 * SECONDS_PER_TOKEN, rel=1e-6)


def test_the_bucket_refills_over_time_and_never_overflows():
    clock = FakeClock()
    bucket = TokenBucket(
        capacity=BURST,
        refill_per_second=RPM / 60.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    async def drain_then_idle() -> list[int]:
        waits = [await bucket.acquire() for _ in range(BURST)]
        clock.now += 3600  # an hour of silence
        return waits + [await bucket.acquire() for _ in range(BURST)]

    waits = asyncio.run(drain_then_idle())

    assert waits == [0] * (2 * BURST)
    assert bucket.tokens == pytest.approx(0.0, abs=1e-9)


def test_a_bucket_needs_a_capacity_and_a_refill_rate():
    with pytest.raises(ValueError, match="capacity"):
        TokenBucket(capacity=0, refill_per_second=1.0)
    with pytest.raises(ValueError, match="refill"):
        TokenBucket(capacity=1, refill_per_second=0.0)
