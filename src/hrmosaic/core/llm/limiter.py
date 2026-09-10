"""The token-bucket limiter and the daily spend guard (spec §9.4, §9.8).

**Why a bucket and not strict pacing.** A typical turn makes five or six provider calls. At
`LLM_RPM = 10`, strict pacing would sleep ~30 s before any provider latency and an ordinary turn
would exceed `AGENT_WALL_CLOCK_S`. So the limiter is a token bucket of capacity `LLM_BURST`
(default = `LLM_RPM`) refilling continuously at `LLM_RPM / 60` tokens per second: a full bucket
admits a whole interactive turn with **zero** delay, while sustained eval throughput stays bounded
at `LLM_RPM` per minute. Every `llm_call` span records `limiter_wait_ms`, so a paced turn is
visible on the dashboard rather than looking like provider latency.

**The spend guard is orthogonal to the limiter.** `LLM_DAILY_CALL_CAP` (default 1500 Anthropic
calls per UTC day) is counted from the `llm_call` spans already in the store — there is no second
counter to drift — and raises `DailyCapExceeded`, which `POST /chat` renders as HTTP 200 with
`outcome: "error"` and an `error` span whose `error_kind` is `daily_cap_reached`.

The clock and the sleep are injectable so `tests/unit/test_limiter_burst.py` can watch the pacing
of the 7th–11th call without spending thirty seconds of wall clock on it.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from hrmosaic.core.db import Store

#: `spans` is the only counter: one `llm_call` row per logical call, written by `core/trace.py`.
CALLS_TODAY_SQL = """
SELECT COUNT(*) AS n FROM spans
WHERE kind = 'llm_call'
  AND started_at >= ?
  AND json_extract(payload_json, '$.provider') = ?
"""


class DailyCapExceeded(RuntimeError):
    """`LLM_DAILY_CALL_CAP` reached for the UTC day — the turn ends `error`/`daily_cap_reached`."""

    error_kind = "daily_cap_reached"

    def __init__(self, *, provider: str, calls_today: int, cap: int) -> None:
        super().__init__(
            f"the daily model budget is exhausted: {calls_today} {provider} calls today, cap {cap} (LLM_DAILY_CALL_CAP)"
        )
        self.provider = provider
        self.calls_today = calls_today
        self.cap = cap


def utc_day_start_micros(now: datetime | None = None) -> int:
    """Epoch micros at 00:00 UTC of the current day — the window the cap is counted over."""
    moment = now or datetime.now(UTC)
    midnight = moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * 1_000_000)


def count_calls_today(store: Store, provider: str) -> int:
    """`llm_call` spans for `provider` since 00:00 UTC — `/health.llm.agent.calls_today` (§11.4)."""
    return int(store.execute(CALLS_TODAY_SQL, (utc_day_start_micros(), provider)).scalar() or 0)


#: How many calls a seed is trusted for before the authoritative count runs again. The counter sees
#: only this process's own calls, so on a multi-worker deployment it under-counts; re-seeding bounds
#: how far the cap can be overshot by that blind spot, at one indexed query per hundred calls.
RESEED_EVERY = 100


class DailyCallCounter:
    """A per-process, per-provider count of the `llm_call` spans this process has written today.

    **It is a fast negative, and it is nothing else.** `count_calls_today` is an indexed query
    (`ix_spans_kind`), so ~1.8 ms of round trip rather than a scan — but it was running before
    *every* logical call, five or six times a turn, on the request path of a 0.1-CPU instance. This
    counter answers only one question, "is this process demonstrably nowhere near the cap?", and
    answers `False` whenever it cannot be sure: the provider has not been seeded this UTC day, the
    seed is `RESEED_EVERY` calls old, or its own count has reached the cap. Every `False` sends the
    caller to `count_calls_today`, and **every refusal is raised from that number**.

    So §9.8's "counted from the `llm_call` spans, so there is no second counter to drift" stays
    literally true. Nothing user-visible is computed here: not a refusal, not
    `/health.llm.agent.calls_today`, not `est_cost_usd`. A drifted counter can only cost an extra
    SQL round trip or, on a second worker, let the cap be overshot by less than `RESEED_EVERY`
    before the re-seed catches it — never refuse a call the store says is under the cap.
    """

    def __init__(self, *, reseed_every: int = RESEED_EVERY) -> None:
        self._reseed_every = reseed_every
        self._lock = threading.Lock()
        self._day: int | None = None
        self._counts: dict[str, int] = {}
        self._since_seed: dict[str, int] = {}

    def below(self, provider: str, cap: int, *, now: datetime | None = None) -> bool:
        """`True` only when this process can prove, from its own calls, that it is under `cap`."""
        with self._lock:
            self._roll(now)
            seen = self._since_seed.get(provider)
            if seen is None or seen >= self._reseed_every:
                return False
            return self._counts.get(provider, 0) < cap

    def seed(self, provider: str, used: int, *, now: datetime | None = None) -> None:
        """Adopt the authoritative count and start a fresh window of trust."""
        with self._lock:
            self._roll(now)
            self._counts[provider] = used
            self._since_seed[provider] = 0

    def record(self, provider: str, *, now: datetime | None = None) -> None:
        """One `llm_call` span was written for `provider`. Called from `record_llm_call` only.

        A provider nobody has seeded stays **unseeded**: `record_llm_call` also writes spans for
        adapters that carry no cap at all (the judge), and letting those calls open a window of
        trust would mean the first capped call skipped the authoritative count it exists to take.
        """
        with self._lock:
            self._roll(now)
            self._counts[provider] = self._counts.get(provider, 0) + 1
            if provider in self._since_seed:
                self._since_seed[provider] += 1

    def count(self, provider: str, *, now: datetime | None = None) -> int:
        """Diagnostics and tests. Never an input to a refusal — see the class docstring."""
        with self._lock:
            self._roll(now)
            return self._counts.get(provider, 0)

    def reset(self) -> None:
        """Forget everything, as a fresh process would. The seam the tests use."""
        with self._lock:
            self._day = None
            self._counts.clear()
            self._since_seed.clear()

    def _roll(self, now: datetime | None) -> None:
        """A new UTC day is *unseeded*, not zero: the cap's window moved, so go and count it."""
        day = utc_day_start_micros(now)
        if self._day != day:
            self._day = day
            self._counts.clear()
            self._since_seed.clear()


_daily_calls = DailyCallCounter()


def daily_calls() -> DailyCallCounter:
    """The process-wide counter. One per process, exactly as the token bucket is."""
    return _daily_calls


class TokenBucket:
    """Capacity `LLM_BURST`, refilling at `LLM_RPM / 60` tokens per second."""

    def __init__(
        self,
        *,
        capacity: int,
        refill_per_second: float,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if capacity < 1:
            raise ValueError("a token bucket needs a capacity of at least one call")
        if refill_per_second <= 0:
            raise ValueError("a token bucket needs a positive refill rate")
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._monotonic = monotonic
        self._sleep = sleep
        self._tokens = float(capacity)
        self._updated = monotonic()
        self._lock = asyncio.Lock()

    @property
    def tokens(self) -> float:
        """Tokens available at the last refill — diagnostics only, never a decision input."""
        return self._tokens

    async def acquire(self) -> int:
        """Take one token, sleeping until one exists. Returns the milliseconds waited."""
        async with self._lock:
            start = self._monotonic()
            while True:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return max(0, round((self._monotonic() - start) * 1000))
                await self._sleep((1.0 - self._tokens) / self.refill_per_second)

    def _refill(self) -> None:
        now = self._monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.refill_per_second)
        self._updated = now
