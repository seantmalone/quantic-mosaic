"""Every deploy-time script runs as `python scripts/<name>.py`, from the repository root (§14.6).

These eight scripts are invoked from a shell — by CI's `docker` and `deploy` jobs, by
`make docker-run-512`, and by the operator following `NEEDS-FROM-USER.md` — and never by pytest.
That is exactly how `provision_render.py` and `check_render_hours.py` shipped broken for a few
minutes during P11: `python scripts/<name>.py` puts *the script's own directory* on `sys.path`,
not the repository root, so their sibling `from scripts.… import …` lines raised
`ModuleNotFoundError` while the test suite — which sets `pythonpath = ["src", "."]` — stayed green.

So this test does the one thing importing the module cannot: it starts a real interpreter, exactly
as the shell does, and asks each script for its `--help`. That reaches every import and every
module-level statement. `--help` exits 0 before any network call, any credential read and any
write, so nothing here provisions anything or touches an account.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

DEPLOY_SCRIPTS = [
    "assert_health.py",
    "check_render_hours.py",
    "measure_cold_start.py",
    "provision_render.py",
    "provision_turso.py",
    "smoke_deployed.py",
    "wait_for_deploy.py",
    "wait_for_health.py",
]


@pytest.mark.parametrize("script", DEPLOY_SCRIPTS)
def test_the_script_starts_under_a_bare_interpreter(script: str):
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, f"scripts/{script}", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout
