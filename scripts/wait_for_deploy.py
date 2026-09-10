"""Block until the **new** release is the one answering `$DEPLOY_URL` (spec §14.5).

    python scripts/wait_for_deploy.py --url "$DEPLOY_URL" --timeout 900

The deploy hook is asynchronous: `curl -fsS -X POST "$RENDER_DEPLOY_HOOK_URL"` returns as soon as
Render has queued a build, while the *previous* instance keeps serving for the several minutes the
Docker build takes. Polling `/health` for a 200 would therefore go green instantly against the old
release and the smoke test that follows would certify the wrong build.

So the wait is on **identity, not liveness**: `/health.app.git_sha` must become the commit being
deployed. Render sets `RENDER_GIT_COMMIT` on the instance and `settings.py` resolves
`GIT_SHA -> RENDER_GIT_COMMIT -> "dev"` (§12.3), so the expected value in CI is simply
`GITHUB_SHA`, read from the environment when `--sha` is not given. With no expected sha available
at all the script degrades to the weakest useful check — a build stamp that is not `"dev"` — and
says so, rather than silently reverting to a liveness poll.

Exit status is 0 once the expected build answers, and 1 on timeout or on an unusable `--url`
(empty or schemeless — what an unset `DEPLOY_URL` secret expands to). `/health` is open, so
nothing here reads a credential.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

POLL_INTERVAL_S = 5.0

#: A short sha is a prefix of the full one; anything shorter than this is too weak to match on.
MIN_SHA_PREFIX = 7

#: `--url ""` is what an unset `DEPLOY_URL` secret expands to in CI, and it is not a rare case: it
#: is the second-most-likely state of the `deploy` job before the Render account exists.
URL_SCHEMES = ("http://", "https://")


class BadUrl(ValueError):
    """`--url` was empty or had no scheme; nothing was probed."""


def require_base_url(url: str | None) -> str:
    """Reject an unusable `--url` by name, before urllib turns it into a raw `ValueError`.

    `urllib.request.urlopen("/health")` raises `ValueError: unknown url type: '/health'`, which
    `probe`'s except tuple deliberately does not catch — a malformed URL is a configuration fault
    to report, not a transient network fault to retry. Saying so here means the operator reads
    "DEPLOY_URL is empty" instead of a stack trace.
    """
    candidate = (url or "").strip()
    if not candidate:
        raise BadUrl(
            "--url is empty. In CI that means the DEPLOY_URL repository secret is unset — see "
            "NEEDS-FROM-USER.md (gates 2 and 4), then run scripts/provision_render.py."
        )
    if not candidate.lower().startswith(URL_SCHEMES):
        raise BadUrl(f"--url {candidate!r} has no http:// or https:// scheme; it is not a base URL.")
    return candidate.rstrip("/")


def is_live(payload: dict, expected_sha: str | None) -> bool:
    """True when this `/health` body is the expected build (§12.3's `GIT_SHA` resolution)."""
    observed = ((payload.get("app") or {}).get("git_sha") or "").strip()
    if not observed or observed == "dev":
        return False
    if expected_sha is None:
        return True
    expected = expected_sha.strip()
    if len(expected) < MIN_SHA_PREFIX or len(observed) < MIN_SHA_PREFIX:
        return False
    return observed.startswith(expected) or expected.startswith(observed)


def probe(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=15) as response:  # noqa: S310
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, OSError):
        return None


def wait(url: str, expected_sha: str | None, timeout_s: float) -> int:
    if expected_sha is None:
        print("no expected sha (neither --sha nor GITHUB_SHA): waiting only for a build stamp that is not 'dev'")
    else:
        print(f"waiting for {url} to report git_sha {expected_sha}")
    started = time.monotonic()
    deadline = started + timeout_s
    last_seen = "(no answer yet)"
    while time.monotonic() < deadline:
        payload = probe(url)
        if payload is not None:
            last_seen = ((payload.get("app") or {}).get("git_sha")) or "(absent)"
            if is_live(payload, expected_sha):
                print(f"{url} is serving git_sha {last_seen} after {time.monotonic() - started:.0f}s")
                return 0
        time.sleep(POLL_INTERVAL_S)
    print(
        f"{url} did not report the expected build within {timeout_s:.0f}s (last seen: {last_seen})",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="base URL of the deployed instance")
    parser.add_argument("--timeout", type=float, default=900.0, help="seconds to wait before giving up")
    parser.add_argument("--sha", default=None, help="expected commit (default: $GITHUB_SHA)")
    arguments = parser.parse_args(argv)
    try:
        base = require_base_url(arguments.url)
    except BadUrl as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        return 1
    expected = arguments.sha or os.environ.get("GITHUB_SHA") or None
    return wait(base, expected, arguments.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
