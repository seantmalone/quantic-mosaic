#!/usr/bin/env python3
"""Re-capture the UX audit's screens against the working tree (`make ux-capture`).

The audit that produced `docs/superpowers/plans/2026-09-14-ux-remediation-plan.md` is evidence, and
evidence has to be reproducible: this is the harness that reproduces it, so a wave can be checked
against the same 53 screen ids at the same three viewports rather than eyeballed.

**How it runs, and it is exactly how the audit ran.** Four stub servers, each with its own
`LLM_STUB_SCRIPT`, all sharing **one** `TRACE_DB_PATH` — so the dashboard screens show all four
conversations:

| script | what it is for |
|---|---|
| `demo_task_1` | key page, the gate's 401s, chat at rest, the cited multi-document answer |
| `demo_task_2` | the confirmation card and the confirmed resume |
| `out_of_corpus_tuition` | the refusal (G1's evidence gate) |
| `fault_ambiguous` | the clarification, the error turn, and every dashboard route |

`LLM_PROVIDER=stub` throughout: **no live model call is ever made**, and nothing here touches the
deployed URL. Output goes to a git-ignored directory (`.ux-capture/` by default), one
`.full.png` / `.fold.png` / `.txt` / `.numbers.json` / `.overflow.json` per screen and viewport,
plus an `index.json` with the same shape the audit's carries.

**Both colour schemes, since UX W5.** `brand.css` ships a whole dark palette behind
`prefers-color-scheme` and no screen of the audit had ever been taken in it. After the light pass a
second context runs with `color_scheme="dark"` over the key page, chat at rest, the demo panel, the
answered conversation and every dashboard route, under ids suffixed `-dark`. It asks **no new
question**: the four servers share one trace store, so `/?session=<id>` rehydrates the conversation
the light pass produced and the dashboard renders the same records.

    make ux-capture                 # into .ux-capture/
    make ux-capture UX_OUT=/tmp/w1  # somewhere else

Exit status is non-zero if any screen failed to capture, so a broken page cannot pass as a picture.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "tests" / "fixtures" / "llm_scripts"

#: The three viewports the audit measured, in the order its `index.json` lists them.
VIEWPORTS = (("1440x900", 1440, 900), ("1280x800", 1280, 800), ("390x844", 390, 844))

#: The audit's own token. It opens one loopback server for the length of one capture run and is
#: destroyed with it; nothing it opens leaves this machine.
ACCESS_TOKEN = "uxaudit"

#: The four stub scripts, and what each one's server is used for.
SERVERS = {
    "demo_1": ("demo_task_1.json", "key page, the gate's 401s, chat at rest, the cited answer"),
    "demo_2": ("demo_task_2.json", "the confirmation card and the confirmed resume"),
    "refusal": ("out_of_corpus_tuition.json", "the refusal (G1's evidence gate)"),
    "dash": ("fault_ambiguous.json", "clarification, the error turn, and every dashboard route"),
}

PROMPTS = {
    "demo_1": "I want to work from Berlin from 3 November to 14 December 2026 — can I?",
    "demo_2": (
        "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
        "— and can you open the request for me?"
    ),
    "refusal": (
        "What is Mosaic's tuition reimbursement cap for a part-time master's degree, and how many "
        "years of service do I need to qualify?"
    ),
    "dash": "Can I take some time off soon?",
}

#: Every rendered number token with 40 characters of context, every element that overflows or
#: clips, and the document's own horizontal-scroll flag. Lifted from the audit's `cap.py` so the
#: before/after `.numbers.json` and `.overflow.json` files compare directly.
PROBE_JS = r"""
() => {
  const text = document.body ? document.body.innerText : "";
  const numbers = [];
  const re = /\d[\d.,:% ]*/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    numbers.push({
      token: m[0],
      index: m.index,
      context: text.slice(Math.max(0, m.index - 40), m.index + m[0].length + 40).replace(/\n/g, " ⏎ "),
    });
    if (numbers.length > 4000) break;
  }
  const pathOf = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 8) {
      let seg = node.tagName.toLowerCase();
      if (node.id) { seg += "#" + node.id; parts.unshift(seg); break; }
      if (node.classList && node.classList.length) seg += "." + Array.from(node.classList).join(".");
      parts.unshift(seg);
      node = node.parentElement;
    }
    return parts.join(" > ");
  };
  const overflow = [];
  for (const el of document.querySelectorAll("*")) {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") continue;
    const sw = el.scrollWidth, cw = el.clientWidth, sh = el.scrollHeight, ch = el.clientHeight;
    const wide = cw > 0 && sw > cw + 1;
    const ellipsis = cs.textOverflow === "ellipsis" && sw > cw + 1;
    const tallerThanItsBox = ch > 0 && sh > ch + 1;
    const clippedY = tallerThanItsBox && cs.overflowY === "hidden";
    // A box that scrolls *vertically* inside itself was invisible here until UX W3's review: only
    // `overflow-y: hidden` was recorded, so the demo panel could cap itself at 45vh, hide its own
    // last rows behind an overlay scrollbar nobody sees until they scroll, and pass the harness.
    // P7 permits a scroll container — "with a visible affordance" — so this is reported, not failed:
    // the transcript and the wide-table wrappers are legitimately in this list on most screens.
    const scrollsY = tallerThanItsBox && (cs.overflowY === "auto" || cs.overflowY === "scroll");
    if (wide || ellipsis || clippedY || scrollsY) {
      overflow.push({
        path: pathOf(el), tag: el.tagName.toLowerCase(),
        scrollWidth: sw, clientWidth: cw, scrollHeight: sh, clientHeight: ch,
        overflowX: cs.overflowX, overflowY: cs.overflowY, textOverflow: cs.textOverflow,
        horizontal_overflow: wide, ellipsis_clipped: ellipsis, vertical_clipped: clippedY,
        vertical_scrollable: scrollsY,
        text: (el.innerText || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 180),
      });
    }
    if (overflow.length > 600) break;
  }
  const de = document.documentElement;
  return {
    text, numbers, overflow,
    page: {
      title: document.title, url: location.href,
      scrollWidth: de.scrollWidth, clientWidth: de.clientWidth,
      scrollHeight: de.scrollHeight, clientHeight: de.clientHeight,
      body_horizontal_scroll: de.scrollWidth > de.clientWidth + 1,
    },
  };
}
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for_health(base_url: str, *, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=5) as response:  # noqa: S310
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.3)
    raise SystemExit(f"{base_url} never became healthy")


@contextmanager
def stub_servers(trace_db: Path) -> Iterator[dict[str, str]]:
    """The four servers of the audit, sharing one trace store, torn down on the way out."""
    processes: list[subprocess.Popen[bytes]] = []
    urls: dict[str, str] = {}
    logs = trace_db.parent / "servers"
    logs.mkdir(parents=True, exist_ok=True)
    try:
        for name, (script, _) in SERVERS.items():
            port = free_port()
            env = {
                **os.environ,
                "LLM_PROVIDER": "stub",
                "LLM_STUB_SCRIPT": str(SCRIPTS / script),
                "APP_ACCESS_TOKEN": ACCESS_TOKEN,
                "APP_ENV": "local",
                "PERSIST_BACKEND": "sqlite",
                "TRACE_DB_PATH": str(trace_db),
                "EMBED_WARMUP": "0",
                "PORT": str(port),
            }
            handle = (logs / f"{name}.log").open("wb")
            processes.append(
                subprocess.Popen(  # noqa: S603
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "hrmosaic.web.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--log-level",
                        "warning",
                    ],
                    cwd=REPO_ROOT,
                    env=env,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
            )
            urls[name] = f"http://127.0.0.1:{port}"
            # Sequentially, and this matters: all four share one SQLite file, and four processes
            # racing to set `PRAGMA journal_mode=WAL` on it at boot is a reliable
            # `database is locked`. The first server through creates the WAL; the rest join it.
            wait_for_health(urls[name])
        yield urls
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()


class Capture:
    """One output directory, and the `index.json` entries accumulated into it."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.shots = out / "shots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.entries: list[dict[str, Any]] = []
        self.failures: list[str] = []

    def screen(
        self,
        page: Any,
        screen_id: str,
        *,
        route: str,
        state: str,
        notes: str,
        selector: str | None = None,
        before: Callable[[Any], None] | None = None,
    ) -> None:
        for label, width, height in VIEWPORTS:
            try:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(300)
                # A resize preserves the scroll offset in pixels, not the thing that was on
                # screen — so a fragment-addressed page (a citation's landing) has to be
                # re-landed at each viewport, or the shot photographs the wrong section.
                page.evaluate(
                    "() => { const t = location.hash && document.getElementById(location.hash.slice(1));"
                    " if (t) { t.scrollIntoView({block: 'start'}); } }"
                )
                page.wait_for_timeout(150)
                if before is not None:
                    before(page)
                self._one(page, screen_id, label, route=route, state=state, notes=notes, selector=selector)
            except Exception as exc:  # a broken page must not pass as a picture
                self.failures.append(f"{screen_id}@{label}: {exc}")
                print(f"  ! {screen_id}@{label}: {exc}", file=sys.stderr)

    def _one(
        self, page: Any, screen_id: str, label: str, *, route: str, state: str, notes: str, selector: str | None
    ) -> None:
        base = f"{screen_id}__{label}"
        data = page.evaluate(PROBE_JS)
        text = self.shots / f"{base}.txt"
        text.write_text(data["text"], encoding="utf-8")
        numbers = self.shots / f"{base}.numbers.json"
        numbers.write_text(
            json.dumps(
                {
                    "screen": screen_id,
                    "viewport": label,
                    "route": route,
                    "state": state,
                    "count": len(data["numbers"]),
                    "numbers": data["numbers"],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        overflow = self.shots / f"{base}.overflow.json"
        overflow.write_text(
            json.dumps(
                {
                    "screen": screen_id,
                    "viewport": label,
                    "route": route,
                    "state": state,
                    "page": data["page"],
                    "count": len(data["overflow"]),
                    "elements": data["overflow"],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        common = {
            "route": route,
            "state": state,
            "viewport": label,
            "notes": notes,
            "text": str(text),
            "numbers_json": str(numbers),
            "overflow_json": str(overflow),
            "body_horizontal_scroll": data["page"]["body_horizontal_scroll"],
        }
        if selector is not None:
            element = page.query_selector(selector)
            if element is None:
                raise RuntimeError(f"selector {selector!r} matched nothing")
            zoom = self.shots / f"{base}.zoom.png"
            element.screenshot(path=str(zoom))
            self.entries.append({"id": f"{screen_id}@{label}", "capture": "element", "png": str(zoom), **common})
            return
        fold = self.shots / f"{base}.fold.png"
        full = self.shots / f"{base}.full.png"
        page.screenshot(path=str(fold), full_page=False)
        page.screenshot(path=str(full), full_page=True)
        self.entries.append({"id": f"{screen_id}@{label}", "capture": "fold", "png": str(fold), **common})
        self.entries.append({"id": f"{screen_id}@{label}#full", "capture": "full_page", "png": str(full), **common})

    def write_index(self, facts: dict[str, Any]) -> None:
        ids = sorted({entry["id"].split("@")[0] for entry in self.entries})
        (self.out / "index.json").write_text(
            json.dumps(
                {
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "app": {
                        "repo": str(REPO_ROOT),
                        "mode": "LOCAL, LLM_PROVIDER=stub (no live LLM call was made)",
                        "servers": {name: script for name, (script, _) in SERVERS.items()},
                        "note": "All four servers shared one TRACE_DB_PATH.",
                    },
                    "viewports": [label for label, _, _ in VIEWPORTS],
                    "screen_ids": ids,
                    "screen_count": len(self.entries),
                    "facts": facts,
                    "screens": self.entries,
                },
                indent=1,
            ),
            encoding="utf-8",
        )


#: The three ids a finished turn carries on its own article element.
TURN_FACTS_JS = "e => ({session: e.dataset.sessionId, turn: e.dataset.turnId, outcome: e.dataset.outcome})"


def expand_all(page: Any) -> None:
    """Every disclosure on the page, open.

    The demo panel used to be a `<details>` this had to leave alone, so that a chat screen was not
    photographed with chrome it does not ship (UX W3 review, finding 1). Since UX W7 (Addendum 2)
    the panel is always expanded and holds no disclosure of its own, so there is nothing to except.
    """
    page.eval_on_selector_all("details", "els => els.forEach(d => { d.open = true; })")
    page.wait_for_timeout(200)


def sign_in(context: Any, base_url: str, actor: str) -> Any:
    """The key exchange and the persona, exactly as a grader does it."""
    page = context.new_page()
    page.goto(f"{base_url}/?access={ACCESS_TOKEN}", wait_until="networkidle")
    context.add_cookies([{"name": "mosaic_actor", "value": actor, "url": base_url}])
    page.goto(f"{base_url}/", wait_until="networkidle")
    return page


#: The `POST /chat` requests `ask(..., hold=True)` has parked. They are resumed by `release()`.
_HELD: list[Any] = []

#: Proof that the screen about to be taken really is the in-flight one: Stop has replaced Send.
IN_FLIGHT_JS = "() => { const b = document.getElementById('stop-button'); return b && !b.hidden; }"


def ask(page: Any, base_url: str, prompt: str, *, hold: bool = False) -> None:
    """Ask one question and wait for the turn to land in `#messages`.

    `hold=True` **parks** the `POST /chat` request instead of answering it, and returns as soon as
    the page is provably in flight. `release()` lets it through.

    It used to sleep inside the route handler — `lambda route: (time.sleep(6), route.continue_())`
    — and a sync Playwright route handler runs on the dispatcher thread, so the sleep blocked the
    very loop that would have delivered the response. Both "in-flight" screens came out
    byte-identical to the finished turn beside them, at all three viewports, and §3.2 therefore had
    no screen evidence and no regression guard at all (UX W6, cpux-re-10). Parking the route holds
    the server's answer without blocking anything, and the wait below is an assertion: a
    mis-capture now fails the run instead of producing a duplicate.
    """
    before = page.eval_on_selector_all("#messages .turn", "els => els.length")
    if hold:
        _HELD.clear()

        # A plain `def`, not `_HELD.append`: Playwright stamps an attribute onto the handler it is
        # given, and a builtin method object cannot carry one.
        def park(route: Any) -> None:
            _HELD.append(route)

        page.route("**/chat", park)
    page.fill("#message", prompt)
    page.click("#send-button")
    if hold:
        page.wait_for_function(IN_FLIGHT_JS, timeout=30_000)
        page.wait_for_timeout(400)
        return
    page.wait_for_function("n => document.querySelectorAll('#messages .turn').length > n", arg=before, timeout=180_000)
    page.wait_for_timeout(1200)


def release(page: Any) -> None:
    """Let the parked `POST /chat` through, so the turn it was carrying finishes."""
    for route in _HELD:
        route.continue_()
    _HELD.clear()
    page.unroute("**/chat")


def capture(out: Path, urls: dict[str, str]) -> Capture:
    from playwright.sync_api import sync_playwright

    shot = Capture(out)
    facts: dict[str, Any] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        # -- the pre-auth surfaces, and the gate's own refusals ---------------------------
        anonymous = browser.new_context(viewport={"width": 1440, "height": 900})
        page = anonymous.new_page()
        page.goto(f"{urls['demo_1']}/access", wait_until="networkidle")
        shot.screen(
            page,
            "access-key-page",
            route="/access",
            state="no cookie, blank form",
            notes="The key page as a first-time visitor sees it.",
        )
        page.fill("#access", "not-the-key")
        page.click(".access-form button")
        page.wait_for_load_state("networkidle")
        shot.screen(
            page,
            "access-key-wrong",
            route="/access",
            state="rejected key",
            notes="What a wrong key says, and what it offers next.",
        )
        page.goto(f"{urls['demo_1']}/", wait_until="networkidle")
        shot.screen(page, "gate-401-root", route="/", state="no credential", notes="The gate's 401 on the chat route.")
        page.goto(f"{urls['demo_1']}/api/traces/overview", wait_until="networkidle")
        shot.screen(
            page,
            "gate-401-api",
            route="/api/traces/overview",
            state="no credential",
            notes="The gate's 401 on an API route, followed by a browser.",
        )
        anonymous.close()

        # -- server 1: chat at rest, and the cited multi-document answer ------------------
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = sign_in(context, urls["demo_1"], "E1042")
        shot.screen(
            page, "chat-rest", route="/", state="persona E1042, no turns", notes="Chat at rest for the default persona."
        )
        shot.screen(
            page,
            "zoom-header-rest",
            route="/",
            state="persona E1042",
            notes="The shared masthead.",
            selector="header.masthead",
        )
        shot.screen(
            page,
            "zoom-composer-rest",
            route="/",
            state="persona E1042",
            notes="The composer at rest — sticky, one row, Enter to send.",
            selector="#chat-form",
        )
        shot.screen(
            page,
            "zoom-empty-state",
            route="/",
            state="persona E1042, no turns",
            notes="NEW at W2: the greeting and the four starter questions.",
            selector="#empty-state",
        )
        shot.screen(
            page,
            "demo-panel",
            route="/",
            state="persona E1042, panel always expanded",
            notes="NEW at W1, rebuilt at W3: every demo affordance, in one labelled panel. Always "
            "expanded since W7 (Addendum 2): no disclosure to open.",
            selector="section.demo-panel",
        )

        ask(page, urls["demo_1"], PROMPTS["demo_1"], hold=True)
        shot.screen(
            page,
            "chat-inflight",
            route="/",
            state="turn in flight (POST parked, Stop on screen)",
            notes="What a question looks like while it is being answered.",
        )
        release(page)
        page.wait_for_selector("#messages .turn", timeout=180_000)
        page.wait_for_timeout(1500)
        facts["demo_1"] = page.eval_on_selector("#messages .turn", TURN_FACTS_JS)
        shot.screen(
            page, "chat-answer", route="/", state="cited multi-document answer", notes="The answer a grader is shown."
        )
        shot.screen(
            page,
            "zoom-turn-answer",
            route="/",
            state="cited answer",
            notes="One finished turn.",
            selector="#messages .turn",
        )
        shot.screen(
            page,
            "demo-panel-after-answer",
            route="/",
            state="one answered turn, panel always expanded",
            notes="NEW at W3: the grader's summary of the last turn, the session id and the deep "
            "link into its record, all written by the page after the turn landed.",
            selector="section.demo-panel",
        )
        shot.screen(
            page,
            "chat-answer-expanded",
            route="/",
            state="answer, expanders open",
            notes="Every disclosure on the answered turn, open.",
            before=expand_all,
        )
        shot.screen(
            page,
            "zoom-sources",
            route="/",
            state="sources expanded",
            notes="NEW at W2: the always-visible sources strip, each reference opened.",
            selector=".sources",
            before=expand_all,
        )

        # the citation's destination, and the conversation opened again from its id
        expand_all(page)
        chip = page.eval_on_selector(".source-link", "e => e.getAttribute('href')")
        facts["citation_href"] = chip
        page.goto(urls["demo_1"] + chip, wait_until="networkidle")
        shot.screen(
            page,
            "policy-reader",
            route=chip,
            state="followed a citation",
            notes="NEW at W1: where a citation goes — the reader, not the chunk inspector.",
        )
        session = facts["demo_1"]["session"]
        page.goto(f"{urls['demo_1']}/?session={session}", wait_until="networkidle")
        shot.screen(
            page,
            "chat-reloaded",
            route=f"/?session={session}",
            state="transcript rehydrated",
            notes="NEW at W1: the conversation survives a reload.",
        )
        context.close()

        # -- server 2: the confirmation card, and the confirmed resume --------------------
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = sign_in(context, urls["demo_2"], "E1042")
        ask(page, urls["demo_2"], PROMPTS["demo_2"], hold=True)
        shot.screen(
            page,
            "chat-confirm-inflight",
            route="/",
            state="gated turn in flight (POST parked, Stop on screen)",
            notes="The turn that is about to ask for a confirmation.",
        )
        release(page)
        page.wait_for_selector(".confirm-card", timeout=180_000)
        page.wait_for_timeout(1000)
        facts["demo_2"] = page.eval_on_selector("#messages .turn", TURN_FACTS_JS)
        shot.screen(
            page, "chat-confirm-card", route="/", state="awaiting_confirmation", notes="Nothing has been written yet."
        )
        shot.screen(
            page,
            "zoom-confirm-card",
            route="/",
            state="awaiting_confirmation",
            notes="The card itself.",
            selector=".confirm-card",
        )
        shot.screen(
            page,
            "chat-confirm-card-expanded",
            route="/",
            state="awaiting_confirmation, expanders open",
            notes="The gated turn with every disclosure open.",
            before=expand_all,
        )
        page.set_viewport_size({"width": 1440, "height": 900})
        page.click(".button-confirm")
        page.wait_for_selector(".confirm-card", state="detached", timeout=180_000)
        page.wait_for_timeout(1500)
        shot.screen(
            page,
            "chat-after-confirm",
            route="/",
            state="confirmed, write performed",
            notes="What the user is told after approving a write.",
        )
        shot.screen(
            page,
            "zoom-turn-after-confirm",
            route="/",
            state="confirmed",
            notes="The resolved turn.",
            selector="#messages .turn",
        )
        shot.screen(
            page,
            "chat-after-confirm-expanded",
            route="/",
            state="confirmed, expanders open",
            notes="The resumed turn with every disclosure open.",
            before=expand_all,
        )
        context.close()

        # -- server 3: the refusal --------------------------------------------------------
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = sign_in(context, urls["refusal"], "E1042")
        ask(page, urls["refusal"], PROMPTS["refusal"])
        shot.screen(
            page,
            "chat-refusal",
            route="/",
            state="refused (G1 evidence gate)",
            notes="An out-of-corpus question, refused.",
        )
        shot.screen(
            page,
            "chat-refusal-expanded",
            route="/",
            state="refused, expanders open",
            notes="The refusal with every disclosure open.",
            before=expand_all,
        )
        context.close()

        # -- server 4: clarification, the error turn, and every dashboard route -----------
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = sign_in(context, urls["dash"], "E1042")
        ask(page, urls["dash"], PROMPTS["dash"])
        facts["clarify"] = page.eval_on_selector("#messages .turn", TURN_FACTS_JS)
        shot.screen(
            page, "chat-clarify", route="/", state="clarify", notes="An ambiguous question, answered with a question."
        )
        shot.screen(
            page,
            "chat-clarify-expanded",
            route="/",
            state="clarify, expanders open",
            notes="The clarification with every disclosure open.",
            before=expand_all,
        )

        # a second question exhausts the one-entry stub script: the graceful error turn
        page.set_viewport_size({"width": 1440, "height": 900})
        page.fill("#message", "And what about carrying unused days into next year?")
        page.click("#send-button")
        page.wait_for_timeout(9000)
        shot.screen(
            page,
            "chat-error-degraded",
            route="/",
            state="server-side failure mid-turn",
            notes="What a human sees when the turn fails.",
        )

        # the dashboard, as the employee persona — the whole point of W1
        session = facts["demo_1"]["session"]
        routes = [
            ("dashboard-403-employee", "/dashboard", "persona E1042 (was a 403; W1 opened it)"),
            ("deeplink-403-employee", f"/dashboard/sessions/{session}", "persona E1042, followed from chat"),
            ("dashboard-overview", "/dashboard", "the overview"),
            ("dashboard-sessions", "/dashboard/sessions", "the sessions list"),
            ("dashboard-session-demo1", f"/dashboard/sessions/{session}", "the demo-1 session"),
            ("dashboard-session-demo2", f"/dashboard/sessions/{facts['demo_2']['session']}", "the demo-2 session"),
            ("dashboard-turns", "/dashboard/turns", "the turns list"),
            ("dashboard-llm", "/dashboard/llm", "model calls"),
            ("dashboard-retrieval", "/dashboard/retrieval", "retrieval"),
            ("dashboard-tools", "/dashboard/tools", "tool calls"),
            ("dashboard-safety", "/dashboard/safety", "guardrails and confirmations"),
            ("dashboard-mcp", "/dashboard/mcp", "the tool server"),
            ("dashboard-corpus", "/dashboard/corpus", "the policy library"),
            ("dashboard-corpus-doc", "/dashboard/corpus/remote-and-hybrid-work", "one document"),
            ("dashboard-evals", "/dashboard/evals", "the eval runs"),
        ]
        for screen_id, route, state in routes:
            response = page.goto(urls["dash"] + route, wait_until="networkidle", timeout=90_000)
            facts[f"{screen_id}_status"] = response.status if response else None
            page.wait_for_timeout(400)
            shot.screen(
                page,
                screen_id,
                route=route,
                state=state,
                notes=f"Dashboard route {route} as the DEFAULT persona. HTTP {facts[f'{screen_id}_status']}.",
            )

        run_id = (
            page.eval_on_selector("#eval-runs-table a[href^='/dashboard/evals/']", "e => e.getAttribute('href')")
            if page.query_selector("#eval-runs-table a[href^='/dashboard/evals/']")
            else None
        )
        if run_id:
            page.goto(urls["dash"] + run_id, wait_until="networkidle")
            shot.screen(
                page, "dashboard-eval-run", route=run_id, state="one run", notes="One committed evaluation run."
            )

        page.goto(f"{urls['dash']}/dashboard", wait_until="networkidle")
        shot.screen(
            page,
            "zoom-dash-masthead",
            route="/dashboard",
            state="persona E1042",
            notes="The dashboard masthead — the same partial chat renders.",
            selector="header.masthead",
        )
        shot.screen(
            page,
            "zoom-dash-nav",
            route="/dashboard",
            state="persona E1042",
            notes="The grouped page nav. Since W7 (Addendum 2) the group labels are muted eyebrows "
            "and the page links are pills, so the two no longer read alike.",
            selector="#dash-nav",
        )
        page.goto(f"{urls['dash']}/dashboard/sessions/{session}#turn-1", wait_until="networkidle")
        shot.screen(
            page,
            "deeplink-session-turn1",
            route=f"/dashboard/sessions/{session}#turn-1",
            state="persona E1042, followed a deep link",
            notes="Where a chat turn's own deep link lands.",
        )

        # the themed refusal: a write control reached without the admin persona
        page.goto(f"{urls['dash']}/dashboard/nope", wait_until="networkidle")
        shot.screen(
            page,
            "refused-page",
            route="/dashboard/nope",
            state="404 as a page",
            notes="NEW at W1: an HTML refusal is a page with the masthead and a route back.",
        )

        # -- the second colour scheme (UX W5) ---------------------------------------------
        #
        # `brand.css` ships a whole dark palette behind `prefers-color-scheme`, and until now not
        # one screen of the audit had ever been taken in it: every before/after pair in
        # `docs/evidence/` is the light theme, so a dark-only regression — a hard-coded rgba, an
        # ink on the wrong ground — could land green.
        #
        # The dark pass deliberately asks no new question. `StubAdapter` spends its script once per
        # process, and all four servers share one `TRACE_DB_PATH`, so `/?session=<id>` rehydrates
        # demo 1's answered conversation and every dashboard route renders the same records the
        # light pass photographed. Same states, same data, one emulated preference apart.
        context.close()
        context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        page = context.new_page()
        page.goto(f"{urls['dash']}/access", wait_until="networkidle")
        shot.screen(
            page,
            "access-key-page-dark",
            route="/access",
            state="no cookie, prefers-color-scheme: dark",
            notes="NEW at W5: the key page in the dark palette.",
        )
        page = sign_in(context, urls["dash"], "E1042")
        shot.screen(
            page,
            "chat-rest-dark",
            route="/",
            state="persona E1042, no turns, prefers-color-scheme: dark",
            notes="NEW at W5: chat at rest in the dark palette.",
        )
        shot.screen(
            page,
            "demo-panel-dark",
            route="/",
            state="persona E1042, panel always expanded, prefers-color-scheme: dark",
            notes="NEW at W5: the demo panel's dashed border and its own ground in dark (W7: "
            "`--demo-ground` lifts rather than sinks there).",
            selector="section.demo-panel",
        )
        page.goto(f"{urls['dash']}/?session={session}", wait_until="networkidle")
        shot.screen(
            page,
            "chat-answer-dark",
            route=f"/?session={session}",
            state="cited answer, rehydrated, prefers-color-scheme: dark",
            notes="NEW at W5: the answered conversation in dark — rehydrated, so no second model "
            "call was made to photograph it.",
        )
        for screen_id, route, state in routes:
            # The two `*-403-employee` ids are the *same page* as the two below them, captured
            # under the name of the 403 W1 removed; one dark photograph of each page is enough.
            if not route.startswith("/dashboard") or screen_id.endswith("-403-employee"):
                continue
            page.goto(urls["dash"] + route, wait_until="networkidle", timeout=90_000)
            page.wait_for_timeout(400)
            shot.screen(
                page,
                f"{screen_id}-dark",
                route=route,
                state=f"{state}, prefers-color-scheme: dark",
                notes=f"NEW at W5: dashboard route {route} in the dark palette.",
            )
        if run_id:
            page.goto(urls["dash"] + run_id, wait_until="networkidle")
            shot.screen(
                page,
                "dashboard-eval-run-dark",
                route=run_id,
                state="one run, prefers-color-scheme: dark",
                notes="NEW at W5: the run a grader reads first, in the dark palette.",
            )

        # chat in the admin persona — identical chrome, which is the W1 claim
        context.close()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = sign_in(context, urls["dash"], "admin")
        shot.screen(
            page,
            "chat-rest-admin",
            route="/",
            state="persona admin, no turns",
            notes="The same chat page in the admin persona.",
        )
        shot.screen(
            page,
            "zoom-header-admin",
            route="/",
            state="persona admin",
            notes="The masthead in the admin persona.",
            selector="header.masthead",
        )
        context.close()
        browser.close()

    shot.write_index(facts)
    return shot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO_ROOT / ".ux-capture"), help="output directory (git-ignored)")
    parser.add_argument("--keep", action="store_true", help="add to an existing directory instead of clearing it")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    if out.exists() and not args.keep:
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    trace_db = out / "traces.sqlite"
    print(f"capturing into {out}")
    with stub_servers(trace_db) as urls:
        for name, url in urls.items():
            print(f"  {name:8s} {url}  ({SERVERS[name][0]})")
        shot = capture(out, urls)

    ids = sorted({entry["id"].split("@")[0] for entry in shot.entries})
    print(f"\n{len(ids)} screen ids, {len(shot.entries)} captures → {out / 'index.json'}")
    sideways = sorted({entry["id"] for entry in shot.entries if entry["body_horizontal_scroll"]})
    print(f"screens whose document scrolls sideways: {len(sideways)}")
    for entry in sideways:
        print(f"  ! {entry}")
    if shot.failures:
        print(f"\n{len(shot.failures)} screens failed to capture:", file=sys.stderr)
        for failure in shot.failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
