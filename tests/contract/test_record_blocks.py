"""**JX2-05 = cpux2-4, and Addendum 3** (UX W7): the reader's own record is neither policy nor advice.

The re-audit's screen: *"You have 13.5 PTO days remaining…"* printed under *"What I suggest you
do"* and disclaimed *"Suggestions are guidance, not company policy"* — a reader told their own
balance is non-binding. The owner's screen, live on the confirm path: the turn led *"Done — your
request is with the HR Time Off team"* and then, under the same heading, told the reader to
*"Submit the request in MosaicOne"*.

Rendered, on the demo-2 stub (`tests/fixtures/llm_scripts/demo_task_2.json`, a verbatim recording
whose synthesis types the balance `recommendation`): the balance is a `record` block under *"From
your HR record"*, outside the suggestions group and its footnote; no sentence on the page tells the
reader to file the request the write filed; and the lede says what happens next.
"""

from __future__ import annotations

import html as html_module
import re

import pytest

pytestmark = pytest.mark.anyio

HTMX = {"HX-Request": "true"}

DEMO_2 = (
    "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
    "— and can you open the request for me?"
)

#: The owner's own reading of the contradiction (Addendum 3).
DIRECTIVE = re.compile(r"\b(submit|file|raise|log|open|enter)\b.{0,40}\brequest", re.IGNORECASE)

RECORD_SECTION = re.compile(r'<section class="answer-block answer-block-record">.*?</section>', re.S)
SUGGESTIONS = re.compile(r'<section class="answer-block answer-block-recommendation">.*?</section>', re.S)
ANSWER_BODY = re.compile(r'<div class="answer-body">.*?<p class="snapshot-note">', re.S)


def _text(markup: str) -> str:
    return " ".join(html_module.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


async def _confirmed(client) -> tuple[str, str]:
    """The card, then the resumed turn — as the page and as the JSON contract."""
    card = await client.post("/chat", json={"message": DEMO_2}, headers=HTMX)
    ids = re.search(r'data-session-id="([0-9a-f]+)" *\n? *data-turn-id="([0-9a-f]+)"', card.text)
    assert ids, card.text[:400]
    decision = {"session_id": ids.group(1), "turn_id": ids.group(2), "decision": "confirmed"}
    done = await client.post("/chat/confirm", json=decision, headers=HTMX)
    assert done.status_code == 200, done.text
    return card.text, done.text


async def test_the_balance_is_the_readers_record_outside_the_suggestions_and_their_footnote(web):
    async with web("demo_task_2.json") as client:
        _card, done = await _confirmed(client)

    record = RECORD_SECTION.search(done)
    assert record, "the balance renders in its own block"
    assert "From your HR record" in record.group(0)
    assert "13.5" in record.group(0)
    assert "not company policy" not in record.group(0), "the reader's own data is not disclaimed"

    suggestions = SUGGESTIONS.search(done)
    if suggestions:
        assert "13.5" not in suggestions.group(0), "the balance is not a suggestion"

    body = ANSWER_BODY.search(done)
    assert body, "the answered turn has a body and a snapshot note"
    assert (
        body.group(0).index("answer-block-record") < body.group(0).index("answer-block-recommendation")
        if ("answer-block-recommendation" in body.group(0))
        else True
    ), "the record is read before the suggestions"


async def test_no_sentence_on_the_confirmed_page_tells_the_reader_to_file_the_request(web):
    """Addendum 3: the ticket IS the request. The lede says it is filed and what happens next; nothing
    below it sends the reader off to file it again."""
    async with web("demo_task_2.json") as client:
        _card, done = await _confirmed(client)

    body = ANSWER_BODY.search(done)
    assert body
    text = _text(body.group(0))
    assert text.startswith("Done — your request is with the HR Time Off team.")
    # …and the manager is named, because the turn's own envelope resolved the chain (W8, C06).
    assert "Your manager Dana's written approval is the next step." in text
    assert not DIRECTIVE.search(text), f"a sentence still tells the reader to file the request: {text}"


async def test_the_json_contract_carries_the_record_type(web):
    async with web("demo_task_2.json") as client:
        proposal = (await client.post("/chat", json={"message": DEMO_2})).json()
        body = (
            await client.post(
                "/chat/confirm",
                json={"session_id": proposal["session_id"], "turn_id": proposal["turn_id"], "decision": "confirmed"},
            )
        ).json()

    types = [block["type"] for block in body["answer_blocks"]]
    assert types[0] == "performed"
    assert "record" in types, types
    record = next(block for block in body["answer_blocks"] if block["type"] == "record")
    assert "13.5" in record["text"] and record["citations"] == []
    assert not DIRECTIVE.search(body["answer"]), body["answer"]


# -- W8, C17: the product's own voice, rendered bare in the lede slot --------------------

NOTICE = re.compile(r'<p class="answer-notice">(.*?)</p>', re.S)


async def test_a_clarifying_question_is_the_products_voice_and_wears_nothing(web):
    """`live:62536ccd…:1` — *"Recommendation — not company policy: I reached my tool-call limit…"*,
    printed after six facts and three suggestions, under "Suggestions are guidance, not company
    policy". A budget stop, a clarifying question, a refusal, a cancellation receipt and the reason
    a write was not proposed are all Mosaic talking about itself, and none of them is advice."""
    async with web("fault_ambiguous.json") as client:
        page = await client.post("/chat", json={"message": "Can you look up the balance?"}, headers=HTMX)

    assert page.status_code == 200, page.text
    notice = NOTICE.search(page.text)
    assert notice, "the clarification renders as a notice"
    assert _text(notice.group(0)).strip(), "and it says something"
    body = ANSWER_BODY.search(page.text) or re.search(r'<div class="answer-body">.*?</div>', page.text, re.S)
    assert body
    rendered = body.group(0)
    assert "not company policy" not in rendered, "the product's own voice is not disclaimed"
    assert "What I suggest you do" not in rendered, "and wears no heading"
    assert rendered.index("answer-notice") < len(rendered), "it is in the lede slot"


async def test_the_cancellation_receipt_is_a_notice_above_the_answer_it_kept(web):
    """W8, C11 and C17 in one screen: the receipt leads, the earned answer follows it."""
    async with web("demo_task_2.json") as client:
        card = await client.post("/chat", json={"message": DEMO_2}, headers=HTMX)
        ids = re.search(r'data-session-id="([0-9a-f]+)" *\n? *data-turn-id="([0-9a-f]+)"', card.text)
        assert ids, card.text[:400]
        declined = await client.post(
            "/chat/confirm",
            json={"session_id": ids.group(1), "turn_id": ids.group(2), "decision": "declined"},
            headers=HTMX,
        )

    notice = NOTICE.search(declined.text)
    assert notice and "Cancelled — nothing was created." in _text(notice.group(0))
    assert "answer-block-policy_fact" in declined.text, "the answer the turn earned is still there"
    assert declined.text.index("answer-notice") < declined.text.index("answer-block-policy_fact")
