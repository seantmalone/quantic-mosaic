"""`web/api.py`'s `RateLimiter` does not grow without bound (spec §14.3, §17).

The limit is a sliding 60-second window per client address, held in memory for the life of the
process. A Render instance that stays up for days and never drops a key accumulates one `deque`
per distinct address it has **ever** seen inside the 512 MB budget §14.3 sets — a drive-by scanner
is enough. So the eviction is not a tidy-up, it is what keeps the table bounded by "clients seen in
the last minute" rather than "clients seen since boot".

These assert on `len(limiter._hits)` directly, because the table is the leak: under a `defaultdict`
a `pop` is silently undone by the very next subscript, and every behavioural assertion about the
limit still passes while the table grows for ever.
"""

from __future__ import annotations

from hrmosaic.web.api import RateLimiter


def test_a_key_is_dropped_once_its_window_has_expired():
    limiter = RateLimiter(per_minute=5)

    assert limiter.allow("10.0.0.1", now=100.0) is True
    assert len(limiter._hits) == 1

    assert limiter.allow("10.0.0.2", now=200.0) is True

    assert len(limiter._hits) == 1, "the expired key was dropped, not merely emptied"
    assert set(limiter._hits) == {"10.0.0.2"}


def test_a_thousand_one_shot_visitors_are_swept_and_do_not_accumulate():
    limiter = RateLimiter(per_minute=5)
    for index in range(1000):
        assert limiter.allow(f"10.1.{index // 256}.{index % 256}", now=100.0) is True
    assert len(limiter._hits) == 1000

    # One request a full window later. Nobody came back, so nothing in the table is live any more.
    assert limiter.allow("10.9.9.9", now=200.0) is True

    assert len(limiter._hits) == 1, "the sweep dropped every window that had expired"
    assert set(limiter._hits) == {"10.9.9.9"}


def test_the_sweep_keeps_a_client_that_is_still_inside_its_window():
    limiter = RateLimiter(per_minute=5)
    assert limiter.allow("10.0.0.1", now=100.0) is True
    assert limiter.allow("10.0.0.1", now=190.0) is True  # sweeps, then re-hits the same key

    assert limiter.allow("10.0.0.2", now=200.0) is True
    assert set(limiter._hits) == {"10.0.0.1", "10.0.0.2"}, "a live window survives the sweep"


def test_the_window_still_refuses_a_burst_inside_one_minute():
    limiter = RateLimiter(per_minute=3)
    assert [limiter.allow("10.0.0.9", now=100.0 + step) for step in range(5)] == [
        True,
        True,
        True,
        False,
        False,
    ]
    # And lets the same client back in once the oldest hit has aged out.
    assert limiter.allow("10.0.0.9", now=161.0) is True


def test_a_limit_of_zero_refuses_everyone_without_recording_a_key():
    limiter = RateLimiter(per_minute=0)
    assert limiter.allow("10.0.0.1", now=100.0) is False
    assert limiter._hits == {}
