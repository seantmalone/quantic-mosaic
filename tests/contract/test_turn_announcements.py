"""The one live region announces what actually happened (UX W3, P12, plan §1 P12).

`#turn-status` is the chat page's only `role="status"` (W2 removed the rail that was 46 additions a
turn). It announced *"Answer ready."* on every `turn_completed` frame — including a refusal, a
clarifying question, a confirmation card waiting on the reader and a crash. Three outcomes out of
five were announced as the opposite of what had happened, which is worse for a screen-reader user
than silence.

The sentences live in `web/api.TURN_ANNOUNCEMENTS` and reach the page as JSON, so there is one copy.
The browser half — the region really saying this sentence after a real turn of each kind — is
`tests/ux/test_principles.py::test_p12_the_live_region_announces_the_outcome`.
"""

from __future__ import annotations

import json
import re

import pytest

from hrmosaic.core.models import TurnOutcome
from hrmosaic.web import api

pytestmark = pytest.mark.anyio


def test_every_outcome_the_contract_allows_has_a_sentence():
    """`TurnOutcome` is the closed set (§10.1); nothing in it may fall through to silence."""
    outcomes = set(TurnOutcome.__args__)
    assert set(api.TURN_ANNOUNCEMENTS) <= outcomes, "an announcement for an outcome that cannot happen"
    for outcome in outcomes:
        sentence = api.TURN_ANNOUNCEMENTS.get(outcome, api.TURN_ANNOUNCEMENT_FALLBACK)
        assert sentence and sentence[-1] in ".?", f"{outcome} announces {sentence!r}"


def test_only_an_answered_turn_is_announced_as_an_answer_being_ready():
    assert api.TURN_ANNOUNCEMENTS["answered"] == "Answer ready."
    assert api.TURN_ANNOUNCEMENTS["awaiting_confirmation"] == "Waiting for your confirmation."
    assert api.TURN_ANNOUNCEMENTS["refused"] == "I can't answer that one — see below."
    assert api.TURN_ANNOUNCEMENTS["clarify"] == "Could you clarify?"
    assert api.TURN_ANNOUNCEMENTS["error"] == "Something went wrong — you can retry."
    ready = [outcome for outcome, text in api.TURN_ANNOUNCEMENTS.items() if text == "Answer ready."]
    assert ready == ["answered"], f"these outcomes also claim an answer is ready: {ready}"


async def test_the_page_reads_the_sentences_from_the_server_rather_than_keeping_a_second_copy(web):
    async with web() as client:
        html = (await client.get("/")).text

    embedded = re.search(r'<script id="turn-announcements" type="application/json">(.*?)</script>', html, re.S)
    assert embedded, "the mapping is handed to the page"
    assert json.loads(embedded.group(1)) == api.TURN_ANNOUNCEMENTS

    # The frame carries the outcome (§11.3) and the handler looks the sentence up by it — no
    # constant, and no branch that hard-codes "Answer ready." for everything.
    assert "paintStatus(announcementFor(JSON.parse(event.data).outcome));" in html
    assert "return ANNOUNCEMENTS[outcome] || ANNOUNCEMENT_FALLBACK;" in html
    assert 'var ANSWER_READY = "Answer ready.";' not in html, "the one-sentence-for-every-outcome constant is gone"

    # And the swapped-in turn announces itself too: a short turn can finish before the page's
    # `EventSource` has connected, and the region then said nothing at all.
    assert "paintStatus(announcementFor(lastTurn.dataset.outcome));" in html


def test_the_completed_frame_carries_the_outcome_the_announcement_is_chosen_by(monkeypatch):
    """A guard on the one wire the page's choice depends on: `turn_completed` states the outcome."""
    from hrmosaic.agent.orchestrator import ChatResponse

    published: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        api.broker, "publish", lambda turn_id, event, data: published.append((event, data)), raising=True
    )
    api._publish_turn_completed(
        ChatResponse(
            session_id="s" * 32,
            turn_id="t" * 32,
            trace_id="s" * 32,
            outcome="refused",
            answer="",
            answer_blocks=[],
            citations=[],
            trace=[],
        )
    )

    assert published == [("turn_completed", {"outcome": "refused", "duration_ms": 0, "dashboard_url": ""})]
