"""Assert that a running Mosaic HR Copilot image is not merely up but complete (spec §15.1).

    python scripts/assert_health.py --url http://127.0.0.1:8000

`wait_for_health.py` proves the process answers. This proves the *image* is the one we meant to
ship, and it is the last gate of CI's `docker` job and of `make docker-run-512`:

* **`mcp.connected`** — the in-process MCP server mounted and the loopback Streamable HTTP
  handshake completed. A container whose `${PORT}` was not expanded by the shell dials a closed
  port here and fails, which is exactly how the `-e PORT=10000` run proves the `sh -c` form of the
  Dockerfile's `CMD` (§14.2).
* **`mcp.tool_count == 9`** — all nine tools of §8.4 registered.
* **`index.loaded`** and **`index.doc_count == 14`** — the sqlite-vec + FTS5 index really was built
  at *build* time from all 14 documents (§5.3), so a cold start opens a file instead of embedding a
  corpus on 0.1 CPU.

* **`app.rss_mb`**, but only when `--max-rss-mb` arms it — the §14.3 memory gate. CI's `docker`
  job runs the image with no cgroup limit and asserts nothing about memory; `make docker-run-512`
  runs it under `-m 512m` and passes `--max-rss-mb 420`.

Nothing here is gated: `/health` is an open route and is always 200 while the process is up, so
this script needs no credential and makes no gated call (§15.2). Exit status is 0 when the payload
is complete and 1 otherwise, with one line per problem so a broken image is diagnosed in one run.

`--timeout` is the window in which `/health` must start answering **at all**, so
`docker run -d … && python scripts/assert_health.py` does not race the container's boot. It never
softens the assertions themselves: the moment a payload arrives it is judged once, and a wrong
answer fails immediately rather than being retried into a timeout.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

#: The nine tools of §8.4. A tenth tool, or a missing one, is a contract change, not a warning.
EXPECTED_TOOL_COUNT = 9

#: The 14 policy documents of §5.3, counted from `index_meta` — i.e. from what ingestion actually
#: indexed inside the image, not from what happens to be on the build host.
EXPECTED_DOC_COUNT = 14


def problems(payload: dict, *, max_rss_mb: float | None = None) -> list[str]:
    """Return one human-readable line per fault; an empty list means the image is complete.

    `max_rss_mb` arms the §14.3 memory gate. It is off by default because CI's `docker` job runs
    the image with no cgroup limit and only `make docker-run-512` — `docker run -m 512m` — has a
    budget to assert against.
    """
    found: list[str] = []
    mcp = payload.get("mcp") or {}
    index = payload.get("index") or {}
    application = payload.get("app") or {}

    if not mcp.get("connected"):
        found.append(f"mcp.connected is false (last_error: {mcp.get('last_error')!r})")
    elif mcp.get("tool_count") != EXPECTED_TOOL_COUNT:
        found.append(f"mcp.tool_count is {mcp.get('tool_count')}, expected {EXPECTED_TOOL_COUNT}")

    if not index.get("loaded"):
        found.append(f"index.loaded is false ({index.get('error')!r})")
    elif index.get("doc_count") != EXPECTED_DOC_COUNT:
        found.append(f"index.doc_count is {index.get('doc_count')}, expected {EXPECTED_DOC_COUNT}")

    if max_rss_mb is not None:
        rss = application.get("rss_mb")
        if rss is None or float(rss) >= max_rss_mb:
            found.append(f"app.rss_mb is {rss}, expected < {max_rss_mb}")

    return found


#: Per-request timeout, and the pause between attempts while the container is still booting.
REQUEST_TIMEOUT_S = 10.0
RETRY_INTERVAL_S = 0.5


def fetch_health(url: str, timeout_s: float) -> dict:
    """`GET /health`, retried until it answers or `timeout_s` runs out. Raises on failure."""
    deadline = time.monotonic() + timeout_s
    last: Exception = RuntimeError("no attempt was made")
    while True:
        try:
            with urllib.request.urlopen(  # noqa: S310
                f"{url.rstrip('/')}/health", timeout=REQUEST_TIMEOUT_S
            ) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"/health answered HTTP {response.status}; it is always 200 while the process is up"
                    )
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last = exc
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{url}/health did not answer within {timeout_s:.0f}s ({last})") from last
        time.sleep(RETRY_INTERVAL_S)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of the instance")
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for /health to answer at all")
    parser.add_argument(
        "--max-rss-mb",
        type=float,
        default=None,
        help="arm the §14.3 memory gate: fail unless app.rss_mb is below this",
    )
    arguments = parser.parse_args(argv)

    try:
        payload = fetch_health(arguments.url, arguments.timeout)
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"FAIL — could not read {arguments.url}/health: {exc}", file=sys.stderr)
        return 1

    application = payload.get("app") or {}
    mcp = payload.get("mcp") or {}
    index = payload.get("index") or {}
    print(
        f"  status={payload.get('status')}  git_sha={application.get('git_sha')}  "
        f"rss_mb={application.get('rss_mb')}  deploy_mode={application.get('deploy_mode')}\n"
        f"  mcp.connected={mcp.get('connected')}  tool_count={mcp.get('tool_count')}  "
        f"transport={mcp.get('transport')}  url={mcp.get('url')}\n"
        f"  index.loaded={index.get('loaded')}  doc_count={index.get('doc_count')}  "
        f"chunk_count={index.get('chunk_count')}  embed_model={index.get('embed_model')}\n"
        f"  degradations={payload.get('degradations')}"
    )

    found = problems(payload, max_rss_mb=arguments.max_rss_mb)
    if found:
        print(f"\nFAIL — {len(found)} problem(s):", file=sys.stderr)
        for problem in found:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    ceiling = f" · rss_mb {application.get('rss_mb')} < {arguments.max_rss_mb}" if arguments.max_rss_mb else ""
    print(f"\nOK — MCP connected with 9 tools and the baked index carries all 14 documents{ceiling}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
