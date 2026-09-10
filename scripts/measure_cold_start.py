"""Measure the real cold start and warm turn on the live instance (spec §14.4, §3.1).

    APP_ACCESS_TOKEN=… python scripts/measure_cold_start.py --url "$DEPLOY_URL"

§14.4 publishes a *table of expectations* — ~30–60 s of Render spin-up, 1–3 s to the first
`/health`, a warm turn of ~1.5–5 s — and §3.1 lists "measured cold start and warm turn latency on
the live instance" as a fact to be **read, not assumed**. This script is the reading, and its
output is pasted into `deployed.md`'s `## Cold start` with the date.

How it gets a genuinely cold instance: Render spins a free service down after **15 minutes**
without inbound traffic, so the script idles for `--idle` seconds first (default `EVAL_COLD_IDLE_S`
= 1000 s ≈ 16.7 min, the same constant the cold probes of §13.5 use) and touches nothing while it
waits. Then, in order:

1. `GET /health` — the spin-up plus the container start. `/health` answers before the ONNX model
   is resident, so this is the "container start → 200" segment, not the model load.
2. `GET /ready` polled to 200 — the model mmap from the baked cache and the index open, i.e. the
   segment the Dockerfile's build-time bake exists to keep under a second.
3. `POST /chat` — the first real turn, including the first LLM round trip.
4. `POST /chat` again — the **warm** turn, which is what §13.5's warm p50 is comparable to.

`app.cold_start` from the first `/health` is recorded alongside, because it is the instance's own
answer to "was I cold?" and a mismatch means the idle wait was too short.

The turn is gated, so `APP_ACCESS_TOKEN` is required and sent as `Authorization: Bearer`; it is
never printed. Two turns of a paid Haiku model, once, is the whole cost of this measurement.

**Every segment must succeed or nothing is published.** `httpx` does not raise on 4xx/5xx, so each
call's status is asserted explicitly: a `/chat` that 403s on a wrong token or a non-admin persona,
a `/health` that is not 200, or a `/ready` that never greens inside `ready_timeout_s` all end the
run with a named `MeasurementFailed` naming the status and quoting the first 200 characters of the
body — rather than being timed and pasted into `deployed.md` as a real latency.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

#: The idle wait of §13.5's cold probes: comfortably past Render's 15-minute spin-down.
DEFAULT_IDLE_S = float(os.environ.get("EVAL_COLD_IDLE_S", "1000"))

#: A question that goes through retrieval but needs no structured tool, so the number is the
#: system's own latency and not a mock-data lookup's.
DEFAULT_QUESTION = "How many days of paid time off do I accrue each year?"

READY_POLL_INTERVAL_S = 1.0

#: How much of a failing body is quoted back. Enough to read a `{"code": "ADMIN_REQUIRED"}`, short
#: enough that a stack trace or an HTML error page cannot flood the console.
BODY_EXCERPT_CHARS = 200


class MeasurementFailed(RuntimeError):
    """A segment did not complete successfully, so there is no latency worth publishing."""


def _excerpt(response: httpx.Response) -> str:
    """The first line of the body, truncated. The request's bearer is never echoed in a response."""
    body = " ".join(response.text.split())
    return body[:BODY_EXCERPT_CHARS] + ("…" if len(body) > BODY_EXCERPT_CHARS else "")


def _require_200(response: httpx.Response, what: str) -> httpx.Response:
    """A measurement that cannot fail is not a measurement (§14.4).

    `httpx` does not raise on 4xx/5xx, so without this a `POST /chat` that 403s — a wrong or
    expired `APP_ACCESS_TOKEN`, or a non-admin persona — would be *timed* and its latency published
    in `deployed.md` as the project's "first turn" figure.
    """
    if response.status_code != 200:
        raise MeasurementFailed(f"{what} answered HTTP {response.status_code}: {_excerpt(response)}")
    return response


@dataclass(frozen=True)
class ColdStart:
    url: str
    measured_at: str
    idle_s: float
    health_ms: float
    ready_ms: float
    first_turn_ms: float
    warm_turn_ms: float
    reported_cold: bool | None
    git_sha: str | None

    @property
    def first_request_total_ms(self) -> float:
        """§14.4's "first request total" row: everything a visitor waits through, once."""
        return self.health_ms + self.ready_ms + self.first_turn_ms


def markdown(measurement: ColdStart) -> str:
    """The block that goes into `deployed.md`'s `## Cold start`, numbers and date included."""
    return "\n".join(
        [
            f"| Segment | Measured on {measurement.measured_at} |",
            "|---|---|",
            f"| Spin-up + container start → `/health` 200 | {measurement.health_ms / 1000:.1f} s |",
            f"| `/health` 200 → `/ready` 200 (model mmap + index open) | {measurement.ready_ms / 1000:.1f} s |",
            f"| First `POST /chat` (includes the first LLM round trip) | {measurement.first_turn_ms / 1000:.1f} s |",
            f"| **First request total** | **{measurement.first_request_total_ms / 1000:.1f} s** |",
            f"| **Warm turn** | **{measurement.warm_turn_ms / 1000:.1f} s** |",
            "",
            f"Idle before the cold probe: {measurement.idle_s:.0f} s. "
            f"The instance reported `app.cold_start = {measurement.reported_cold}` on the first "
            f"`/health`; build `{measurement.git_sha}`.",
        ]
    )


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000.0


def measure(
    client: httpx.Client,
    url: str,
    *,
    token: str,
    idle_s: float,
    question: str = DEFAULT_QUESTION,
    ready_timeout_s: float = 180.0,
    poll_interval_s: float = READY_POLL_INTERVAL_S,
) -> ColdStart:
    """Idle, then walk the four segments of §14.4 in order against a genuinely cold instance."""
    base = url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "X-Actor": "admin"}

    if idle_s > 0:
        print(f"  idling {idle_s:.0f}s so Render spins the instance down (§14.4)…", flush=True)
        time.sleep(idle_s)

    started = time.monotonic()
    health = _require_200(client.get(f"{base}/health", timeout=180.0), "GET /health")
    health_ms = _elapsed_ms(started)
    payload = health.json()

    started = time.monotonic()
    became_ready = False
    while _elapsed_ms(started) < ready_timeout_s * 1000:
        if client.get(f"{base}/ready", timeout=60.0).status_code == 200:
            became_ready = True
            break
        time.sleep(poll_interval_s)
    ready_ms = _elapsed_ms(started)
    if not became_ready:
        # Falling out of the loop used to *record* the timeout as the model-load segment, so a
        # never-green instance published `ready_timeout_s` as a measurement (§11.4: /ready is 503
        # until the model and the index are resident — if it never greens, nothing is measurable).
        raise MeasurementFailed(
            f"GET /ready never answered 200 within {ready_timeout_s:.0f}s: the model or the index "
            "never became resident, so there is no cold-start figure to publish"
        )

    started = time.monotonic()
    _require_200(
        client.post(f"{base}/chat", json={"message": question}, headers=headers, timeout=180.0),
        "the first POST /chat",
    )
    first_turn_ms = _elapsed_ms(started)

    started = time.monotonic()
    _require_200(
        client.post(f"{base}/chat", json={"message": question}, headers=headers, timeout=180.0),
        "the warm POST /chat",
    )
    warm_turn_ms = _elapsed_ms(started)

    application = payload.get("app") or {}
    return ColdStart(
        url=base,
        measured_at=datetime.now(UTC).strftime("%Y-%m-%d"),
        idle_s=idle_s,
        health_ms=health_ms,
        ready_ms=ready_ms,
        first_turn_ms=first_turn_ms,
        warm_turn_ms=warm_turn_ms,
        reported_cold=application.get("cold_start"),
        git_sha=application.get("git_sha"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("DEPLOY_URL"), help="base URL of the live instance")
    parser.add_argument("--idle", type=float, default=DEFAULT_IDLE_S, help="seconds to idle before the cold probe")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="the question both turns ask")
    arguments = parser.parse_args(argv)

    if not arguments.url:
        print("no --url and no DEPLOY_URL: there is no live instance to measure yet.", file=sys.stderr)
        return 1
    token = os.environ.get("APP_ACCESS_TOKEN")
    if not token:
        print("APP_ACCESS_TOKEN is unset; POST /chat is gated and would 403.", file=sys.stderr)
        return 1

    with httpx.Client(follow_redirects=True) as client:
        try:
            measurement = measure(
                client, arguments.url, token=token, idle_s=arguments.idle, question=arguments.question
            )
        except (httpx.HTTPError, MeasurementFailed) as exc:
            print(f"FAIL — {arguments.url} could not be measured: {exc}", file=sys.stderr)
            return 1

    print()
    print(markdown(measurement))
    print("\nPaste the table above into deployed.md's `## Cold start`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
