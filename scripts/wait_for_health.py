"""Block until a Mosaic HR Copilot instance answers `GET /health`, or give up (spec §11.4).

`make demo1`, `make demo2` and `make docker-run-512` all start a server and then immediately drive
it; without this they race the boot. `/health` is the right thing to wait on precisely because it is
**never gated and always 200 while the process is up** — a readiness probe would report 503 through
the whole ONNX warm-up, and a gated route would need the access token this script deliberately does
not want.

    python scripts/wait_for_health.py --url http://127.0.0.1:8000 --timeout 120

Exit status is 0 once `/health` answers 200, 1 on timeout. Nothing here reads a credential.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

POLL_INTERVAL_S = 0.5


def probe(url: str) -> dict | None:
    """One `GET /health`. Returns the parsed body, or `None` while the server is not up yet."""
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=5) as response:  # noqa: S310
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, OSError):
        return None


def wait(url: str, timeout_s: float) -> int:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = probe(url)
        if body is not None:
            degradations = body.get("degradations") or []
            suffix = f" (degraded: {', '.join(degradations)})" if degradations else ""
            print(f"{url} is up after {timeout_s - (deadline - time.monotonic()):.1f}s{suffix}")
            return 0
        time.sleep(POLL_INTERVAL_S)
    print(f"{url}/health did not answer within {timeout_s:.0f}s", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of the instance")
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds to wait before giving up")
    arguments = parser.parse_args(argv)
    return wait(arguments.url, arguments.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
