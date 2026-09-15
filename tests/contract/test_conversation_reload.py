"""`GET /?session=<id>` rehydrates the transcript (UX W1, navigation-and-ia-16).

Chat used to lose the whole conversation on any reload, which is what made the dashboard's only
route back dishonest: the `Chat` link landed on an empty composer, and so did the browser's Back
button. Without rehydration the session page could offer nothing better than *"Back to chat (starts
a new conversation)"*.

`/` is **not** admin-gated, so a raw session id in the address bar would otherwise be a way to read
another persona's conversation. The ownership check is the point of half these assertions: own
session or admin replays; anything else renders an empty conversation and one plain sentence, and
never confirms whether the id exists.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio

QUESTION = "How much PTO do full-time employees accrue each month?"
NOTICE = "That conversation could not be opened here, so this is a new one."


async def _turn(client, **headers):
    response = await client.post("/chat", json={"message": QUESTION}, headers=headers or None)
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_reload_replays_the_transcript_for_the_persona_that_owns_it(web):
    async with web("rag_only.json") as client:
        turn = await _turn(client)
        page = await client.get(f"/?session={turn['session_id']}")

    assert page.status_code == 200
    html = page.text
    assert QUESTION in html, "the question is back in the transcript"
    assert f'id="turn-{turn["turn_id"]}"' in html, "rendered through the same partial a live turn uses"
    assert 'class="source-link"' in html, "with its sources"
    # The composer is seeded, so the next question continues the same conversation rather than
    # silently opening a second one.
    assert f'id="session-id" value="{turn["session_id"]}"' in html
    assert NOTICE not in html


async def test_a_foreign_session_renders_an_empty_conversation_and_a_plain_notice(web):
    async with web("rag_only.json") as client:
        turn = await _turn(client, **{"X-Actor": "E1077"})
        page = await client.get(f"/?session={turn['session_id']}", headers={"X-Actor": "E1042"})

    assert page.status_code == 200
    html = page.text
    assert NOTICE in html
    assert QUESTION not in html, "another persona's conversation is never replayed"
    assert 'id="session-id" value=""' in html, "and the next question starts a new session"


async def test_an_unknown_or_malformed_session_id_is_the_same_plain_notice(web):
    async with web("rag_only.json") as client:
        unknown = await client.get("/?session=" + "0" * 32)
        malformed = await client.get("/?session=not-an-id")

    for page in (unknown, malformed):
        assert page.status_code == 200
        assert NOTICE in page.text
        assert page.text.count('class="turn "') == 0


async def test_the_admin_persona_may_replay_any_session(web):
    """The dashboard's "Continue this conversation in chat" has to work from a session record."""
    async with web("rag_only.json") as client:
        turn = await _turn(client)
        page = await client.get(f"/?session={turn['session_id']}", headers={"X-Actor": "admin"})

    assert QUESTION in page.text
    assert NOTICE not in page.text


async def test_a_replayed_turn_never_offers_a_confirmation_it_cannot_honour(web):
    """A confirmation token is minted in exactly one place (§11.2), and never by a replay."""
    demo_2 = (
        "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
        "— and can you open the request for me?"
    )
    async with web("demo_task_2.json") as client:
        parked = await client.post("/chat", json={"message": demo_2})
        assert parked.status_code == 200, parked.text
        assert parked.json()["outcome"] == "awaiting_confirmation"
        page = await client.get(f"/?session={parked.json()['session_id']}")

    assert demo_2 in page.text, "the parked turn still replays as a transcript"
    assert 'class="confirm-card"' not in page.text


async def test_a_plain_reload_with_no_session_parameter_is_unchanged(web):
    async with web() as client:
        page = await client.get("/")

    assert page.status_code == 200
    assert NOTICE not in page.text
    assert 'id="session-id" value=""' in page.text
