"""Ask a running instance for one of its two demo prompts, the way the chat page's buttons carry it.

    python scripts/demo_prompt.py --base-url http://127.0.0.1:8000 --key demo_1

`scripts/demo_task_1.sh` and `scripts/demo_task_2.sh` used to carry two frozen prompts with fixed
September 2026 dates. The rules engine measures notice from the **submission date** (W8), so those
dates only produce the documented verdicts against a server pinned to `MOCK_TODAY=2026-09-01`:
against the deployed service — which pins nothing, exactly as §12.3 requires — demo task 2 asked
for PTO in the past, which the notice requirement scores at zero business days, and the scripts
narrated a filed ticket beside a rule the request failed.

The chat page never had that problem, because `web/api.py::demo_prompts()` dates both prompts
against the day they are read. This is how a shell script gets the same wording: the dates are
computed by **the server's own clock**, never by `sh`, so a server pinned to `MOCK_TODAY=2026-09-01`
hands back byte-for-byte the recorded pair the stub replays of `make demo1` / `make demo2` expect,
and a server on the real wall clock hands back today's.

`GET /` is the only endpoint that serves the pair (§11.8's route list is exact, and a JSON route
for two strings is not worth an endpoint), so the prompt is read off the demo buttons' own
`data-prompt` attribute, keyed by `data-demo`. Standard library only: the two demo scripts run
under whatever `python3` is on the PATH, not necessarily the project's venv.

Exit status is 0 with the prompt on stdout, 1 with a one-line reason on stderr. A failure is a
**failure**: the callers stop on it rather than quietly sending the recorded wording, because a
quiet downgrade is the very thing this exists to remove — it looked like a green demo and asked for
PTO in the past. The recorded wording is opt-in, `sh scripts/demo_task_2.sh --recorded`.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

#: What `_demo_controls.html` renders, and what `demo_prompts()` keys its pair by.
KEYS = ("demo_1", "demo_2")

#: One request's own timeout, and how long the whole attempt may take. The free Render instance
#: spins down, and the project's measured cold start is 43–52 s to the first `/health` 200 — so a
#: single 15 s request against the deployed service is a fetch that fails on exactly the instance
#: the demo is most often run against. `--timeout` is the total, and it is the same 120 s
#: `make demo1` gives `scripts/wait_for_health.py`.
REQUEST_TIMEOUT_S = 15.0
DEFAULT_TIMEOUT_S = 120.0

#: The retry: half a second, doubling, never waiting more than five seconds between attempts.
FIRST_INTERVAL_S = 0.5
MAX_INTERVAL_S = 5.0

#: A waking instance answers through its proxy before it answers for itself. These are worth
#: another attempt; every other HTTP status is the instance saying something definite (401 is a
#: token that is wrong, 404 is a URL that is wrong) and is reported immediately.
RETRYABLE_STATUS = frozenset({408, 429, 502, 503, 504})


class _DemoButtons(HTMLParser):
    """Collect `data-demo` → `data-prompt` off the chat page's two demo buttons.

    An HTML parser rather than a regular expression because the value is an *attribute*: the
    prompts carry an em dash and could carry an apostrophe, and `HTMLParser` unescapes the entity
    forms Jinja writes for them. Attribute order in the template is then not part of the contract.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.prompts: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "button":
            return
        found = dict(attrs)
        key, prompt = found.get("data-demo"), found.get("data-prompt")
        if key and prompt:
            self.prompts[key] = prompt


def prompts_of(page: str) -> dict[str, str]:
    """The keyed demo prompts carried by a rendered chat page."""
    parser = _DemoButtons()
    parser.feed(page)
    return parser.prompts


class Refused(Exception):  # noqa: N818 - it is the instance's answer, not this script's failure mode
    """The instance answered something definite that is not the page: no retry will change it."""


def fetch(base_url: str, *, token: str | None = None) -> str:
    """One `GET /`, with the access token when the gate is on.

    Raises `Refused` on an HTTP status the instance means (401 with a wrong token, 404 with a wrong
    URL) and `OSError` on the ones a waking instance produces — which the caller retries.
    """
    request = urllib.request.Request(f"{base_url.rstrip('/')}/")  # noqa: S310 - http(s) URL from the caller
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:  # noqa: S310
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as error:
        if error.code in RETRYABLE_STATUS:
            raise OSError(f"HTTP {error.code}") from error
        raise Refused(f"HTTP {error.code}") from error


def read_prompt(base_url: str, key: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """The instance's own `key` prompt, waiting for it the way `scripts/wait_for_health.py` waits.

    A free instance spins down, and the first request to a cold one is answered somewhere between
    43 and 52 seconds later (§14.4's measurement). Without this the fetch timed out against exactly
    the deployment the demo scripts are advertised for.
    """
    deadline = time.monotonic() + timeout_s
    interval, last = FIRST_INTERVAL_S, "no attempt was made"
    while True:
        try:
            page = fetch(base_url, token=os.environ.get("APP_ACCESS_TOKEN"))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = str(error) or error.__class__.__name__
        else:
            prompt = prompts_of(page).get(key, "")
            if prompt:
                return prompt
            # A page without the pair is a page that is not the chat page — a status screen, a
            # redirect target, a template that dropped `data-demo`. None of that improves by waiting.
            raise Refused(f"the page carries no {key} demo prompt")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{base_url}/ did not answer within {timeout_s:.0f}s ({last})")
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
        interval = min(interval * 2, MAX_INTERVAL_S)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="base URL of the instance")
    # Required: the default was `demo_1`, so a caller that forgot the flag — or misspelt it — ran
    # the PTO demo on the Berlin question and failed a long way from the cause.
    parser.add_argument("--key", required=True, choices=KEYS, help="which demo prompt to print")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="seconds to keep trying while the instance wakes",
    )
    arguments = parser.parse_args(argv)

    try:
        print(read_prompt(arguments.base_url, arguments.key, timeout_s=arguments.timeout))
    except (Refused, TimeoutError) as error:
        print(f"could not read {arguments.key} from {arguments.base_url}/: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
