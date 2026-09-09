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
