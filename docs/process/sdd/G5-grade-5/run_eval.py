"""Run one evaluation-harness command against the deployed service with the same trace store the
service writes to. Loads `data/runtime/provision_turso.json` into the environment in-process (nothing
is printed), sets EVAL_TARGET_BASE_URL and APP_ACCESS_TOKEN (from README's Deployed: line), and then
runs `python -m <module> <args…>` so `.env` is read by pydantic-settings as usual.

    .venv/bin/python .superpowers/sdd/2026-09-21-grade-5/run_eval.py evaluation.runner --variant baseline
    .venv/bin/python .superpowers/sdd/2026-09-21-grade-5/run_eval.py evaluation.ablation
"""

from __future__ import annotations

import json
import os
import re
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HANDOFF = ROOT / "data" / "runtime" / "provision_turso.json"
DEPLOY_URL = "https://mosaic-hr-copilot.onrender.com"


def main() -> None:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    handoff = json.loads(HANDOFF.read_text())
    for key in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
        os.environ[key] = str(handoff[key])
    readme = (ROOT / "README.md").read_text()
    match = re.search(r"\?access=([A-Za-z0-9_-]+)", readme)
    if not match:
        raise SystemExit("no ?access= token on README's Deployed: line")
    os.environ.setdefault("APP_ACCESS_TOKEN", match.group(1))
    os.environ.setdefault("EVAL_TARGET_BASE_URL", DEPLOY_URL)
    if len(sys.argv) < 2:
        raise SystemExit("usage: run_eval.py <module> [args…]")
    module = sys.argv[1]
    sys.argv = [module, *sys.argv[2:]]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
