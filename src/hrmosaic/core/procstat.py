"""Live process statistics: resident memory and uptime, with no third-party dependency.

`/health` reports `rss_mb` / `rss_peak_mb` (§11.4), `turns.rss_mb_at_end` is sampled in the
closing UPDATE (§10.3) and plotted by dashboard page 11, and `turns.process_uptime_ms` under
60 s classifies a turn as COLD for the latency statistics (§10.1).

Two sources, and the reading always names the one it used:

* **Linux** — `/proc/self/status` `VmRSS`, the *current* resident set. This is the number the
  §14.3 memory gate asserts inside the container.
* **Everywhere else** (macOS development) — `resource.getrusage`, which reports the *peak*
  resident set, so `rss_mb` is a high-water mark rather than a live reading off Linux.

Run it directly for a one-shot reading: `python -m hrmosaic.core.procstat`.
"""

from __future__ import annotations

import json
import os
import resource
import sys
import time
from pathlib import Path
from typing import Any

_PROCESS_START = time.monotonic()

_STATUS_PATH = Path("/proc/self/status")
_LINUX_SOURCE = "/proc/self/status"
_RUSAGE_SOURCE = "resource.getrusage"

_BYTES_PER_MB = 1024.0 * 1024.0


def uptime_ms() -> int:
    """Milliseconds since this module was first imported — the process's own age (§10.1)."""
    return int((time.monotonic() - _PROCESS_START) * 1000)


def _maxrss_mb() -> float:
    """`ru_maxrss` is kilobytes on Linux and **bytes** on macOS."""
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return maxrss / _BYTES_PER_MB
    return maxrss / 1024.0


def _vmrss_mb() -> float | None:
    try:
        for line in _STATUS_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    except OSError:  # pragma: no cover - only on a Linux kernel without /proc
        return None
    return None  # pragma: no cover


def source() -> str:
    """Which reader `rss_mb()` will use on this platform."""
    return _LINUX_SOURCE if _vmrss_mb() is not None else _RUSAGE_SOURCE


def rss_mb() -> float:
    """Resident set size in MB — current on Linux, peak elsewhere (see the module docstring)."""
    current = _vmrss_mb()
    return round(current if current is not None else _maxrss_mb(), 1)


def rss_peak_mb() -> float:
    """Peak resident set size in MB."""
    return round(_maxrss_mb(), 1)


def snapshot() -> dict[str, Any]:
    """Everything `/health` and the closing UPDATE need, in one reading."""
    return {
        "rss_mb": rss_mb(),
        "rss_peak_mb": rss_peak_mb(),
        "source": source(),
        "platform": sys.platform,
        "uptime_ms": uptime_ms(),
        "pid": os.getpid(),
    }


def main() -> None:
    print(json.dumps(snapshot(), indent=2))


if __name__ == "__main__":
    main()
