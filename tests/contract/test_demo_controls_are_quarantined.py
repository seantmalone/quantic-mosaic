"""**P8 — demo controls are quarantined and labelled** (UX W3, plan §1 P8 / §2B / §3.7).

> *Persona switch, demo prompts and grader deep links live in one visually distinct section with a
> heading that says so.*

The detection rule, run over the rendered chat page: no `#actor-select`, no `.demo-button` and no
`/dashboard/…#turn-` link exists outside `section.demo-panel`, and the panel says what it is. The
plan writes the last clause as `section.demo-panel > h2`; the heading is one level deeper here
because the panel is a `<details>` whose `<summary>` is that heading — the phone layout W2's review
asked for — so this file asserts the heading is inside the panel and inside no other section.

Why it is worth a permanent test rather than a screenshot: every one of these controls was in
production chrome before W3 and each arrived there innocently. The `<select>` was in the masthead
because that is where a persona belongs in a real product; the demo buttons were beside Send because
that is where an action belongs. Only the rule keeps them out.
"""

from __future__ import annotations

import re
from html import escape

import pytest

pytestmark = pytest.mark.anyio

HTMX = {"HX-Request": "true"}
BERLIN = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"

PANEL = re.compile(r'<section class="demo-panel">.*?</section>', re.S)
#: A deep link into the technical record. Anywhere but the panel it is a grader affordance sitting
#: in a reader's conversation (navigation-and-ia-5, demo-and-grader-controls-4).
DEEP_LINK = re.compile(r'href="/dashboard/[^"]*#turn-')

QUARANTINED = ('id="actor-select"', 'class="button demo-button"')

#: The panel's sign-out row exists only when there is a key to clear, exactly as the masthead's
#: does — `tests/contract/test_nav_parity.py` owns the other half of that rule.
TOKEN = "demo-panel-token"


def _panel(html: str) -> str:
    found = PANEL.search(html)
    assert found, "the chat page renders one `section.demo-panel`"
    return found.group(0)


def _outside_the_panel(html: str) -> str:
    return PANEL.sub("", html)


async def test_every_demo_control_is_inside_the_panel_and_nowhere_else(web):
    async with web() as client:
        html = (await client.get("/")).text

    assert html.count('<section class="demo-panel">') == 1, "one panel, not several"
    panel, rest = _panel(html), _outside_the_panel(html)
    for marker in QUARANTINED:
        assert marker in panel, f"{marker!r} belongs in the demo panel"
        assert marker not in rest, f"{marker!r} is loose in production chrome"


async def test_the_panel_offers_a_way_out_of_the_demo_when_there_is_a_key_to_clear(web):
    """demo-and-grader-controls-11: signing out clears the shared key, and nothing said so."""
    from pydantic import SecretStr

    async with web(app_access_token=SecretStr(TOKEN)) as client:
        gated = (await client.get("/", headers={"Authorization": f"Bearer {TOKEN}"})).text
    async with web() as client:
        open_app = (await client.get("/")).text

    panel = _panel(gated)
    assert "Sign out of the demo" in panel
    assert "This clears the shared access key for the whole browser." in panel
    assert "Sign out of the demo" not in _outside_the_panel(gated), "the masthead's own control is not this one"
    assert "Sign out of the demo" not in open_app, "nothing to sign out of when the gate is off"


async def test_the_panel_says_what_it_is(web):
    async with web() as client:
        panel = _panel((await client.get("/")).text)

    assert re.search(r"<h2>Demo &amp; grader controls</h2>", panel), "a heading that names the section"
    # Both inside the `<summary>`, so the collapsed panel carries the whole disclosure: the name of
    # the section and the sentence saying who it is not for (UX W3 review).
    summary = re.search(r"<summary class=\"demo-summary\">.*?</summary>", panel, re.S)
    assert summary, "the collapsed panel is the summary"
    assert "Demo &amp; grader controls" in summary.group(0)
    assert "For evaluation only — a real user never sees this panel." in summary.group(0)


async def test_no_demo_control_is_in_the_masthead_or_in_the_composer(web):
    """The two places they were: the shared shell, and the composer's action row."""
    async with web() as client:
        html = (await client.get("/")).text

    masthead = re.search(r'<header class="masthead">.*?</header>', html, re.S)
    composer = re.search(r'<form id="chat-form".*?</form>', html, re.S)
    assert masthead and composer
    for region, where in ((masthead.group(0), "the masthead"), (composer.group(0), "the composer")):
        assert "actor-select" not in region, f"the persona picker is back in {where}"
        assert "demo-button" not in region, f"a demo prompt is back in {where}"
        assert not DEEP_LINK.search(region), f"a dashboard deep link is in {where}"


async def test_the_deep_link_appears_once_a_turn_exists_and_only_in_the_panel(web):
    """Plan §3.7 item 3: enabled once there is a conversation to open, and pointing at that turn."""
    async with web("demo_task_1.json") as client:
        at_rest = (await client.get("/")).text
        turn = await client.post("/chat", json={"message": BERLIN}, headers=HTMX)
        assert turn.status_code == 200, turn.text
        session_id = re.search(r'data-session-id="([0-9a-f]+)"', turn.text).group(1)
        reloaded = (await client.get(f"/?session={session_id}")).text

    assert 'id="demo-dashboard-link"' in _panel(at_rest), "the control exists at rest"
    assert not DEEP_LINK.search(at_rest), "…but there is nothing to open yet, so it is not a link"

    panel = _panel(reloaded)
    assert f'href="/dashboard/sessions/{session_id}#turn-1"' in panel
    assert not DEEP_LINK.search(_outside_the_panel(reloaded)), "and it is offered nowhere else"


async def test_a_demo_prompt_is_the_question_it_asks_and_only_fills_the_box(web):
    """navigation-and-ia-19 / jargon-and-exposure-11: `Demo 1 — …`, and a click that submitted it."""
    from hrmosaic.web import api

    async with web() as client:
        html = (await client.get("/")).text

    panel = _panel(html)
    labels = [label.strip() for label in re.findall(r'class="button demo-button"[^>]*>(.*?)</button>', panel, re.S)]
    assert labels == [escape(prompt) for prompt in api.DEMO_PROMPTS.values()], (
        "each button is labelled with the question it asks, in §18's own words"
    )
    for prompt in api.DEMO_PROMPTS.values():
        assert f'data-prompt="{escape(prompt)}"' in panel
    assert "Demo 1" not in panel and "Demo 2" not in panel, "the button is the question, not its ordinal"
    # One delegated handler fills the composer for starters, quick replies and demo prompts alike;
    # none of them submits.
    handler = html.split('event.target.closest(".starter, .quick-reply, .demo-button")')[1].split("document.body")[0]
    assert "prefill(prompt.dataset.prompt" in handler
    assert "requestSubmit" not in handler


async def test_the_panel_states_the_demo_environment_once(web):
    """Plan §3.7 item 5: the provider, the snapshot date and the simulated-writes note, here only."""
    from hrmosaic.web import api

    async with web() as client:
        html = (await client.get("/")).text

    panel, rest = _panel(html), _outside_the_panel(html)
    assert api.RECORDED_PROVIDER in panel, "the stub is a recorded script, said in words"
    assert "1 September 2026" in panel, "the snapshot date, in the one date convention chat speaks"
    assert api.SIMULATED_WRITES in panel
    assert api.SIMULATED_WRITES not in rest, "stated once, in the panel — not inside the answers"


async def test_the_environment_block_says_so_when_a_live_model_is_answering(web):
    """The stub is the demo's normal state; the deployed app is not, and the line has to differ."""
    from hrmosaic.web import api

    async with web(llm_provider="anthropic") as client:
        panel = _panel((await client.get("/")).text)

    assert api.LIVE_PROVIDER in panel
    assert api.RECORDED_PROVIDER not in panel


async def test_the_panel_summarises_how_the_last_turn_was_produced(web):
    """Plan §3.7 item 4: three counts, in plain language, with no identifier in them."""
    async with web("demo_task_1.json") as client:
        turn = await client.post("/chat", json={"message": BERLIN}, headers=HTMX)
        session_id = re.search(r'data-session-id="([0-9a-f]+)"', turn.text).group(1)
        reloaded = (await client.get(f"/?session={session_id}")).text

    produced = re.search(r'data-produced="([^"]+)"', turn.text)
    assert produced, "the rendered turn carries the summary the panel shows"
    summary = produced.group(1)
    expected = r"How this answer was produced: \d+ tools? used, \d+ policy sections? read, \d+ safety checks? passed\."
    assert re.fullmatch(expected, summary), summary
    assert "(s)" not in summary, "the plural follows the count (P9)"
    assert summary in _panel(reloaded), "and a replayed conversation shows the same sentence"
