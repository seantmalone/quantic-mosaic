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

Exit status is 0 with the prompt on stdout, 1 with a one-line reason on stderr — which the callers
treat as "fall back to the recorded wording", never as a failed demo.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser

#: What `_demo_controls.html` renders, and what `demo_prompts()` keys its pair by.
KEYS = ("demo_1", "demo_2")
TIMEOUT_S = 15.0


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


def fetch(base_url: str, *, token: str | None = None) -> str:
    """`GET /`, with the access token when the gate is on. Raises `OSError` on any failure."""
    request = urllib.request.Request(f"{base_url.rstrip('/')}/")  # noqa: S310 - http(s) URL from the caller
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        if response.status != 200:
            raise OSError(f"GET / answered HTTP {response.status}")
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="base URL of the instance")
    parser.add_argument("--key", default="demo_1", choices=KEYS, help="which demo prompt to print")
    arguments = parser.parse_args(argv)

    try:
        page = fetch(arguments.base_url, token=os.environ.get("APP_ACCESS_TOKEN"))
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"could not read {arguments.base_url}/: {error}", file=sys.stderr)
        return 1
    prompt = prompts_of(page).get(arguments.key, "")
    if not prompt:
        print(f"{arguments.base_url}/ carries no {arguments.key} demo prompt", file=sys.stderr)
        return 1
    print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
