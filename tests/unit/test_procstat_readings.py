"""`core/procstat.py` — the two resident-memory readers, and which one a platform gets (§11.4).

The number this module returns is the §14.3 memory gate (`make docker-run-512` asserts
`/health.app.rss_mb` under 420 MB), the `turns.rss_mb_at_end` series dashboard page 11 plots, and
the COLD/WARM split of §10.1. Two unit conversions stand between a kernel reading and that number,
and each is wrong on the *other* platform: `ru_maxrss` is kilobytes on Linux and **bytes** on macOS,
and `/proc/self/status` reports `VmRSS` in kilobytes. A developer on macOS never executes the Linux
branch and a CI runner never executes the macOS one, so both are driven here explicitly rather than
left to whichever machine happens to run the suite (P20).
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.core import procstat

#: One `/proc/self/status` excerpt, in the shape the Linux kernel writes it.
PROC_STATUS = """Name:\tpython3.12
State:\tR (running)
VmPeak:\t  512000 kB
VmRSS:\t  307200 kB
Threads:\t3
"""


def test_the_linux_reader_converts_kilobytes_of_vmrss_to_megabytes(tmp_path, monkeypatch):
    """300 MB written as `307200 kB` must read back as 300.0, not 307200 and not 0.3."""
    status = tmp_path / "status"
    status.write_text(PROC_STATUS, encoding="utf-8")
    monkeypatch.setattr(procstat, "_STATUS_PATH", status)

    assert procstat._vmrss_mb() == pytest.approx(300.0)
    assert procstat.source() == procstat._LINUX_SOURCE
    assert procstat.rss_mb() == pytest.approx(300.0)


def test_a_status_file_without_a_vmrss_line_falls_back_to_rusage(tmp_path, monkeypatch):
    status = tmp_path / "status"
    status.write_text("Name:\tpython3.12\nState:\tR (running)\n", encoding="utf-8")
    monkeypatch.setattr(procstat, "_STATUS_PATH", status)

    assert procstat._vmrss_mb() is None
    assert procstat.source() == procstat._RUSAGE_SOURCE


def test_ru_maxrss_is_read_as_bytes_on_macos_and_as_kilobytes_everywhere_else(monkeypatch):
    """The one conversion that is silently 1024× wrong if the platform test is ever dropped."""

    class Usage:
        ru_maxrss = 1024 * 1024 * 300  # 300 MB as macOS reports it; 300 GB if read as kilobytes

    monkeypatch.setattr(procstat.resource, "getrusage", lambda who: Usage())

    monkeypatch.setattr(procstat.sys, "platform", "darwin")
    assert procstat._maxrss_mb() == pytest.approx(300.0)

    monkeypatch.setattr(procstat.sys, "platform", "linux")
    assert procstat._maxrss_mb() == pytest.approx(300.0 * 1024)


def test_the_reading_always_names_the_source_it_came_from(tmp_path, monkeypatch):
    """`/health` publishes `source`, so a 293 MB figure can be read as current or as peak."""
    snapshot = procstat.snapshot()
    assert snapshot["source"] in (procstat._LINUX_SOURCE, procstat._RUSAGE_SOURCE)
    assert snapshot["platform"] == procstat.sys.platform
    assert snapshot["rss_mb"] > 0 and snapshot["rss_peak_mb"] > 0
    assert snapshot["uptime_ms"] >= 0
    assert snapshot["pid"] == procstat.os.getpid()


def test_the_module_prints_one_reading_as_json_when_run_directly(capsys):
    """`python -m hrmosaic.core.procstat` is the documented one-shot reading."""
    procstat.main()
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {"rss_mb", "rss_peak_mb", "source", "platform", "uptime_ms", "pid"}
