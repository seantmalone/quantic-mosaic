"""Smoke the **live** deployment right after a deploy hook fires (spec §14.5, §15.2).

    python scripts/smoke_deployed.py --url "$DEPLOY_URL"

The last step of CI's `deploy` job, and an acceptance gate of P11. It answers four questions that
`assert_health.py` cannot ask of a local container:

1. **Is this a real build?** `/health.app.git_sha` must not be `"dev"`. §12.3 resolves
   `GIT_SHA -> RENDER_GIT_COMMIT -> "dev"`, so `"dev"` on the live URL means the instance was
   started outside Render's build pipeline and nothing about it is traceable to a commit.
2. **Did the MCP server come up in the deployed process?** `mcp.connected`.
3. **Is the deployment usable at all?** `access_token_missing` in `degradations[]` means
   `APP_ENV=render` with no `APP_ACCESS_TOKEN`, which 403s every gated route — the service would be
   live and useless (§11.4). Every *other* degradation is tolerated: a missing judge key or an
   unreachable trace store degrades a feature, not the deployment.
4. **Did the warm-up finish?** `GET /ready` must reach 200 within `--ready-timeout` (default 600 s,
   `SMOKE_READY_TIMEOUT_S`). Nothing in the deploy path used to ask: `/ready` was 503 on the live
   instance for every deploy up to P11c — the warm-up `tools/call` read-timed-out after five
   seconds on a 0.1-CPU worker and was never retried — while `/health` said `ok` and `POST /chat`
   answered, so the smoke was green the whole time. A failure here quotes the `reason` field.

**The bearer check is opportunistic by design.** `APP_ACCESS_TOKEN` is deliberately *not* a CI
secret (§15.2), so in the `deploy` job this script makes no gated call and says so. Run locally
with `APP_ACCESS_TOKEN` exported — as P11's acceptance gate does — it additionally proves the gate
is on and that the token opens it: `GET /` must be **401** without the header (the access gate
answers the key page, not `ADMIN_REQUIRED`) and 200 with it.

Exit status is 0 when every check passes, 1 otherwise — including when `--url` is empty or
schemeless, which is what an unset `DEPLOY_URL` secret expands to. The token is read from the
environment, sent only to `--url`, and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

#: The one degradation that makes a deployment unusable rather than merely reduced (§11.4).
FATAL_DEGRADATION = "access_token_missing"

#: What a gated route answers with no credential: the access-key page, HTTP 401 (§11). It is not
#: the 403 `ADMIN_REQUIRED` of the persona check — that one is about *which* actor you are, this
#: one about whether you got past the door at all.
UNAUTHENTICATED_STATUS = 401

#: `--url ""` is what an unset `DEPLOY_URL` secret expands to in CI.
URL_SCHEMES = ("http://", "https://")

#: How long `/ready` has to green. A cold free-tier instance spends its first minutes loading the
#: ONNX model on a 0.1 CPU, and the warm-up itself retries inside `READY_WARMUP_TIMEOUT_S`, so this
#: is generous on purpose: the check exists to catch a readiness that never arrives, not a slow one.
READY_TIMEOUT_S = 600.0

#: The environment override, for a caller who wants a shorter wait than the deploy job's.
READY_TIMEOUT_ENV = "SMOKE_READY_TIMEOUT_S"

#: How long between polls. `/ready` is an open route and answers from process state, so this is
#: paced for politeness rather than for cost.
READY_POLL_S = 5.0


class BadUrl(ValueError):
    """`--url` was empty or had no scheme; nothing was smoked."""


def require_base_url(url: str | None) -> str:
    """Reject an unusable `--url` by name, before urllib turns it into a raw `ValueError`.

    `urllib.request.urlopen("/health")` raises `ValueError: unknown url type: '/health'`, which is
    not in `main`'s except tuple — so an unset `DEPLOY_URL` would end this script in a stack trace
    rather than a sentence naming the secret. Same check, same wording, as `wait_for_deploy.py`;
    the two are deliberately standalone scripts with no shared import.
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


def ready_timeout_default() -> float:
    """`SMOKE_READY_TIMEOUT_S` when it parses as a number, else `READY_TIMEOUT_S`.

    A malformed value falls back rather than ending the deploy job in an argparse traceback: the
    wait is a convenience knob, and no deployment fact depends on which number it took. It does say
    so on stderr, though — a caller who exported `SMOKE_READY_TIMEOUT_S=30s` asked for thirty
    seconds and would otherwise wait ten minutes with nothing in the log to explain it. An **unset**
    variable is the ordinary case and warns about nothing.
    """
    raw = os.environ.get(READY_TIMEOUT_ENV)
    if raw is None:
        return READY_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        print(
            f"WARN — {READY_TIMEOUT_ENV}={raw!r} is not a number; waiting {READY_TIMEOUT_S:g}s for /ready instead",
            file=sys.stderr,
        )
        return READY_TIMEOUT_S


def _ready_reason(status: int, body: bytes) -> str:
    """`/ready`'s own `reason`, or the bare status when the body is not the documented JSON."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return f"HTTP {status}"
    reason = payload.get("reason") if isinstance(payload, dict) else None
    return f"HTTP {status}: {reason}" if reason else f"HTTP {status}"


def ready_problems(url: str, *, wait_s: float, request_timeout_s: float, poll_s: float = READY_POLL_S) -> list[str]:
    """Poll `GET /ready` until it answers 200, or report the last `reason` it gave (§11.4).

    The deadline is checked after a poll, so `wait_s=0` still asks once — a bounded wait, never a
    single-shot check that would fail every genuinely cold instance.
    """
    deadline = time.monotonic() + wait_s
    while True:
        status, body = _get(f"{url.rstrip('/')}/ready", None, request_timeout_s)
        if status == 200:
            return []
        reason = _ready_reason(status, body)
        if time.monotonic() >= deadline:
            return [f"/ready never returned 200 within {wait_s:g}s — last answer: {reason}"]
        time.sleep(poll_s)


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="base URL of the deployed instance")
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds to allow each request")
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=ready_timeout_default(),
        help=f"seconds to wait for /ready to answer 200 (default {READY_TIMEOUT_S:g}, {READY_TIMEOUT_ENV})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    try:
        base = require_base_url(arguments.url)
    except BadUrl as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        return 1

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

    try:
        ready = ready_problems(base, wait_s=arguments.ready_timeout, request_timeout_s=arguments.timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # `/health` answered a moment ago, so an instance that drops now is a failed smoke.
        ready = [f"the /ready check could not complete: {exc}"]
    found += ready
    print("  /ready: never green — see below" if ready else "  /ready: 200")

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
    print(f"\nOK — {base} is serving a real build with its MCP server connected, and /ready is green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
