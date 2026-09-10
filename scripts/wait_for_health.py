"""Block until a Mosaic HR Copilot instance answers `GET /health`, or give up (spec §11.4).

`make demo1`, `make demo2` and `make docker-run-512` all start a server and then immediately drive
it; without this they race the boot. `/health` is the right thing to wait on precisely because it is
**never gated and always 200 while the process is up** — a readiness probe would report 503 through
the whole ONNX warm-up, and a gated route would need the access token this script deliberately does
not want.

    python scripts/wait_for_health.py --url http://127.0.0.1:8000 --timeout 120
    python scripts/wait_for_health.py --url http://127.0.0.1:8000 --timeout 180 --ready

`--ready` keeps waiting after that first 200, until `GET /ready` is 200 too — the ONNX model
resident and the index open (§11.4). That is what the §14.3 memory gate needs before it can serve
a turn and read a meaningful `rss_mb`: a process that has not loaded the model yet is not the
process the 512 MB budget is about. `/ready` is open and 503 until warm, so polling it needs no
credential either.

Exit status is 0 once the requested endpoint answers 200, 1 on timeout. Nothing here reads a
credential.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

POLL_INTERVAL_S = 0.5


def probe(url: str, path: str = "/health") -> dict | None:
    """One GET. Returns the parsed body, or `None` while the endpoint is not answering 200 yet."""
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}{path}", timeout=5) as response:  # noqa: S310
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, OSError):
        return None


def wait(url: str, timeout_s: float, *, until_ready: bool = False) -> int:
    started = time.monotonic()
    deadline = started + timeout_s
    seen_health = False
    while time.monotonic() < deadline:
        if not seen_health:
            body = probe(url)
            if body is not None:
                seen_health = True
                degradations = body.get("degradations") or []
                suffix = f" (degraded: {', '.join(degradations)})" if degradations else ""
                print(f"{url} is up after {time.monotonic() - started:.1f}s{suffix}")
                if not until_ready:
                    return 0
                continue
        elif probe(url, "/ready") is not None:
            print(f"{url}/ready is green after {time.monotonic() - started:.1f}s")
            return 0
        time.sleep(POLL_INTERVAL_S)
    endpoint = "/ready" if seen_health else "/health"
    print(f"{url}{endpoint} did not answer within {timeout_s:.0f}s", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of the instance")
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds to wait before giving up")
    parser.add_argument("--ready", action="store_true", help="keep waiting until GET /ready is 200 too")
    arguments = parser.parse_args(argv)
    return wait(arguments.url, arguments.timeout, until_ready=arguments.ready)


if __name__ == "__main__":
    raise SystemExit(main())
