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

import html as html_module
import json
import re

import pytest

from hrmosaic.web import api

pytestmark = pytest.mark.anyio

HTMX = {"HX-Request": "true"}
QUESTION = "How much PTO do full-time employees accrue each month?"
BERLIN = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"
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


async def test_a_replayed_turn_renders_exactly_what_the_live_one_did(web):
    """The parity the two render paths owe each other (UX W2 review, fix round 1).

    `_rehydrate()` and `_render_turn()` build the same context through `_turn_context()`, but the
    page has to *bind* it: `{% include %}` sees only what the surrounding `{% with %}` names, so a
    key the partial reads and the loop forgets is `Undefined` — falsy, and silent. `labelled` was
    that key. It is `turn.outcome in LABELLED_OUTCOMES`, it gates the *"What I suggest you do"*
    heading and the *"Suggestions are guidance, not company policy."* footnote, and because the page
    never bound it an answered turn came back from a reload as bare paragraphs: the labelling
    guarantee §11.5 states was absent on every reloaded transcript, and `api.py`'s own computation
    of it was dead code.
    """
    async with web("demo_task_1.json") as client:
        live = await client.post("/chat", json={"message": BERLIN}, headers=HTMX)
        assert live.status_code == 200, live.text
        assert 'data-outcome="answered"' in live.text
        reloaded = await client.get(f"/?session={_session_of(live.text)}")

    assert reloaded.status_code == 200
    for promise in (api.BLOCK_HEADINGS["recommendation"], api.SUGGESTION_FOOTNOTE):
        assert promise in live.text, f"the live turn carries {promise!r}"
        assert promise in reloaded.text, f"and so does the same turn replayed — {promise!r}"

    # Not just the two strings: the whole agent message is the same markup, modulo the turn's own
    # clock time, which is the only thing in it that depends on when it is rendered.
    assert _agent_message(live.text) == _agent_message(reloaded.text)


async def test_a_replayed_refusal_still_carries_its_redirect(web, store):
    """The redirect survives a reload because the turn **stores** it (UX W3).

    A refusal's `next_steps` are the half of it worth reading: what the library does cover, and who
    to ask when it does not. `turns` held the blocks and the citations but not the steps, so the
    replay had to take the joined `final_answer` back apart to find them — a redirect that existed
    only as long as one string format held. `next_steps_json` is the column beside
    `answer_blocks_json`; rewriting `final_answer` out from under the row proves the replay no
    longer depends on it.
    """
    question = (
        "What is Mosaic's tuition reimbursement cap for a part-time master's degree, and how many "
        "years of service do I need to qualify?"
    )
    async with web("out_of_corpus_tuition.json") as client:
        refused = await client.post("/chat", json={"message": question})
        assert refused.status_code == 200, refused.text
        body = refused.json()
        assert body["outcome"] == "refused"
        assert body["next_steps"], "a refusal redirects"

        stored = store.execute("SELECT next_steps_json FROM turns WHERE id = ?", (body["turn_id"],)).scalar()
        assert json.loads(stored) == body["next_steps"], "the steps are a column, not a parse"

        # Nothing else in the row can stand in for them now.
        store.execute("UPDATE turns SET final_answer = ? WHERE id = ?", ("(the answer)", body["turn_id"]))
        page = await client.get(f"/?session={body['session_id']}")

    assert page.status_code == 200
    for step in body["next_steps"]:
        assert html_module.escape(step) in page.text, f"the replayed refusal lost {step!r}"


async def test_a_turn_written_before_the_column_existed_still_replays_its_steps(web, store):
    """Forward-only migration: an older row has `next_steps_json = NULL` and falls back to the join."""
    question = (
        "What is Mosaic's tuition reimbursement cap for a part-time master's degree, and how many "
        "years of service do I need to qualify?"
    )
    async with web("out_of_corpus_tuition.json") as client:
        refused = await client.post("/chat", json={"message": question})
        body = refused.json()
        store.execute("UPDATE turns SET next_steps_json = NULL WHERE id = ?", (body["turn_id"],))
        page = await client.get(f"/?session={body['session_id']}")

    for step in body["next_steps"]:
        assert html_module.escape(step) in page.text, f"the pre-migration row lost {step!r}"


def _session_of(fragment: str) -> str:
    found = re.search(r'data-session-id="([0-9a-f]+)"', fragment)
    assert found, fragment[:400]
    return found.group(1)


def _agent_message(markup: str) -> str:
    """The agent half of the first turn, whitespace-normalised."""
    found = re.search(r'<div class="message message-agent">(.*?)\n  </div>', markup, re.S)
    assert found, markup[:400]
    return re.sub(r"\s+", " ", found.group(1)).strip()


def test_the_page_binds_every_name_the_turn_partial_reads():
    """The structural guard, so the next key added to the context cannot be half-wired.

    `TURN_CONTEXT_KEYS` is what `_turn_context()` produces and what `_turn.html` reads. The live
    path passes the dict straight to the template; the replay path goes through the page's
    `{% with %}`, which is the only place a name can be dropped. So the list is asserted against
    the tuple rather than against a screenshot of the defect.
    """
    chat = (api.PACKAGE_DIR / "templates" / "chat.html").read_text(encoding="utf-8")
    block = re.search(r"\{% with turn = item\.turn,(.*?)%\}", chat, re.S)
    assert block, "the replay loop still binds its context with a `{% with %}`"
    bound = set(re.findall(r"(\w+) = item\.", "turn = item." + block.group(1)))
    assert set(api.TURN_CONTEXT_KEYS) == bound, (
        "every key `_turn_context()` builds must be bound for the replayed turn too; "
        f"missing {sorted(set(api.TURN_CONTEXT_KEYS) - bound)}, extra {sorted(bound - set(api.TURN_CONTEXT_KEYS))}"
    )
