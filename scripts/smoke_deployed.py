"""Smoke the **live** deployment right after a deploy hook fires (spec §14.5, §15.2).

    python scripts/smoke_deployed.py --url "$DEPLOY_URL"

The last step of CI's `deploy` job, and an acceptance gate of P11. It answers three questions that
`assert_health.py` cannot ask of a local container:

1. **Is this a real build?** `/health.app.git_sha` must not be `"dev"`. §12.3 resolves
   `GIT_SHA -> RENDER_GIT_COMMIT -> "dev"`, so `"dev"` on the live URL means the instance was
   started outside Render's build pipeline and nothing about it is traceable to a commit.
2. **Did the MCP server come up in the deployed process?** `mcp.connected`.
3. **Is the deployment usable at all?** `access_token_missing` in `degradations[]` means
   `APP_ENV=render` with no `APP_ACCESS_TOKEN`, which 403s every gated route — the service would be
   live and useless (§11.4). Every *other* degradation is tolerated: a missing judge key or an
   unreachable trace store degrades a feature, not the deployment.

**The bearer check is opportunistic by design.** `APP_ACCESS_TOKEN` is deliberately *not* a CI
secret (§15.2), so in the `deploy` job this script makes no gated call and says so. Run locally
with `APP_ACCESS_TOKEN` exported — as P11's acceptance gate does — it additionally proves the gate
is on and that the token opens it: `GET /` must be **401** without the header (the access gate
answers the key page, not `ADMIN_REQUIRED`) and 200 with it.

Exit status is 0 when every check passes, 1 otherwise. The token is read from the environment,
sent only to `--url`, and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

#: The one degradation that makes a deployment unusable rather than merely reduced (§11.4).
FATAL_DEGRADATION = "access_token_missing"

#: What a gated route answers with no credential: the access-key page, HTTP 401 (§11). It is not
#: the 403 `ADMIN_REQUIRED` of the persona check — that one is about *which* actor you are, this
#: one about whether you got past the door at all.
UNAUTHENTICATED_STATUS = 401


def health_problems(payload: dict) -> list[str]:
    """Return one line per fault in a live `/health` body; empty means the deployment is sound."""
    found: list[str] = []
    application = payload.get("app") or {}
    mcp = payload.get("mcp") or {}

    if (application.get("git_sha") or "dev") == "dev":
        found.append('app.git_sha is "dev": this instance was not built from a commit')
    if not mcp.get("connected"):
        found.append(f"mcp.connected is false (last_error: {mcp.get('last_error')!r})")
    if FATAL_DEGRADATION in (payload.get("degradations") or []):
        found.append(f"/health lists {FATAL_DEGRADATION}: every gated route on this deployment 403s")
    return found


def _get(url: str, token: str | None, timeout_s: float) -> tuple[int, bytes]:
    """One GET. Returns `(status, body)`, mapping an HTTP error response to its own status."""
    request = urllib.request.Request(url)  # noqa: S310
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def gate_problems(url: str, token: str, timeout_s: float) -> list[str]:
    """Prove the access gate is on and that this token opens it (§11, §14.1)."""
    found: list[str] = []
    root = f"{url.rstrip('/')}/"
    anonymous, _ = _get(root, None, timeout_s)
    if anonymous != UNAUTHENTICATED_STATUS:
        found.append(
            f"GET / without a token answered HTTP {anonymous}, expected "
            f"{UNAUTHENTICATED_STATUS} — the access gate is not on"
        )
    authorised, _ = _get(root, token, timeout_s)
    if authorised != 200:
        found.append(f"GET / with Authorization: Bearer answered HTTP {authorised}, expected 200")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="base URL of the deployed instance")
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds to allow each request")
    arguments = parser.parse_args(argv)
    base = arguments.url.rstrip("/")

    try:
        status, body = _get(f"{base}/health", None, arguments.timeout)
        if status != 200:
            raise RuntimeError(f"/health answered HTTP {status}; it is always 200 while the process is up")
        payload = json.loads(body.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"FAIL — could not read {base}/health: {exc}", file=sys.stderr)
        return 1

    application = payload.get("app") or {}
    mcp = payload.get("mcp") or {}
    print(
        f"  status={payload.get('status')}  git_sha={application.get('git_sha')}  "
        f"deploy_mode={application.get('deploy_mode')}  uptime_ms={application.get('uptime_ms')}\n"
        f"  mcp.connected={mcp.get('connected')}  tool_count={mcp.get('tool_count')}\n"
        f"  degradations={payload.get('degradations')}"
    )

    found = health_problems(payload)

    token = os.environ.get("APP_ACCESS_TOKEN")
    if token:
        try:
            found += gate_problems(base, token, arguments.timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # A network fault mid-check is a failed smoke, not a traceback: `/health` answered a
            # moment ago, so the instance dropping now is exactly what this script exists to catch.
            found.append(f"the access-gate check could not complete: {exc}")
        print("  access gate: checked with APP_ACCESS_TOKEN from the environment")
    else:
        # §15.2: the access token is deliberately not a CI secret, so the deploy job cannot make a
        # gated call. Saying so is the honest alternative to skipping silently.
        print("  access gate: NOT checked — APP_ACCESS_TOKEN is unset (expected in CI, §15.2)")

    if found:
        print(f"\nFAIL — {len(found)} problem(s):", file=sys.stderr)
        for problem in found:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"\nOK — {base} is serving a real build with its MCP server connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
