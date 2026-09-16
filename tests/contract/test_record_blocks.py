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


# -- W8 fix round, CPUX3-03: a record block holds the reader's data and no company policy ---------

import json as _json  # noqa: E402 - the guard below reads the turn's own envelopes back out of the store
from pathlib import Path as _Path  # noqa: E402

from hrmosaic.agent import compliance as _compliance  # noqa: E402
from hrmosaic.agent import outcome as _outcome  # noqa: E402
from hrmosaic.agent.orchestrator import _ToolEnvelope as _Envelope  # noqa: E402

_RULES = _Path(__file__).resolve().parents[2] / "corpus" / "rules.yml"


def _requirement_texts() -> set[str]:
    import yaml

    rules = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    return {
        " ".join(str(requirement["text"]).lower().split())
        for scenario in rules["scenarios"].values()
        for requirement in scenario["requirements"]
    }


def _envelopes(store, turn_id: str) -> list:
    rows = store.execute(
        "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'tool_call' ORDER BY seq", (turn_id,)
    ).dicts()
    found = []
    for row in rows:
        payload = _json.loads(row["payload_json"])
        if payload.get("structured_content"):
            found.append(
                _Envelope(name=str(payload["tool_name"]), result_json=_json.dumps(payload["structured_content"]))
            )
    return found


@pytest.mark.parametrize("script", ["demo_task_1.json", "demo_task_2.json"])
async def test_every_record_sentence_is_the_readers_data_and_none_is_a_policy_rule(web, store, script):
    """Re-audit #3 found the demo-1 record block carrying *"Stays exceeding 30 consecutive days
    require director approval and a Tax & Legal review…"* — a policy requirement under a heading
    that means "your data", with the one missing citation on the page. Every sentence in a
    `record` block has to state a value from that turn's own data envelopes, and none may be a
    requirement `corpus/rules.yml` states.

    Since W10 (ruling 6) one more shape is the reader's record: the explicit line a `not_stated`
    row renders as — *"<label>: not verified from your record — confirm before you proceed."* It
    states no value because there is none; that **is** the fact, and it is built from the turn's own
    verdict envelope, so it is admitted by construction rather than by wording."""
    question = (
        DEMO_2
        if script == "demo_task_2.json"
        else "I want to work from Berlin from 3 November to 14 December 2026 — can I?"
    )
    async with web(script) as client:
        if script == "demo_task_2.json":
            _card, done = await _confirmed(client)
            turn_id = re.search(r'data-turn-id="([0-9a-f]+)"', done).group(1)
            page = done
        else:
            page = (await client.post("/chat", json={"message": question}, headers=HTMX)).text
            turn_id = re.search(r'data-turn-id="([0-9a-f]+)"', page).group(1)

    blocks = _json.loads(
        store.execute("SELECT answer_blocks_json FROM turns WHERE id = ?", (turn_id,)).scalar() or "[]"
    )
    records = [block for block in blocks if block["type"] == "record"]
    envelopes = _envelopes(store, turn_id)
    numbers, scalars = _outcome.envelope_numbers(envelopes), _outcome.envelope_scalars(envelopes)
    rules = _requirement_texts()
    unchecked = set(_compliance.not_stated_lines(_compliance.rows(envelopes)))
    assert records, "the demo paths both state the reader's record"
    for block in records:
        for sentence in _outcome.sentences(block["text"]):
            normalised = " ".join(sentence.lower().split())
            assert normalised.rstrip(".") not in {rule.rstrip(".") for rule in rules}, sentence
            if sentence in unchecked:
                continue  # W10, ruling 6: the row nobody could check, from this turn's own verdict
            assert _outcome.states_the_record(sentence, numbers, scalars), f"not the reader's data: {sentence}"


async def test_the_demo_paths_say_the_rows_nobody_could_check(web, store):
    """W10, ruling 6, against scenario 01: demo 1's `remote.intl.device` row is `manual`, so it is
    `not_stated` on every run — and the recorded answer simply left it out, so a reader was told
    the trip was in order on a requirement nobody had checked."""
    async with web("demo_task_1.json") as client:
        page = (
            await client.post(
                "/chat",
                json={"message": "I want to work from Berlin from 3 November to 14 December 2026 — can I?"},
                headers=HTMX,
            )
        ).text
    turn_id = re.search(r'data-turn-id="([0-9a-f]+)"', page).group(1)
    blocks = _json.loads(
        store.execute("SELECT answer_blocks_json FROM turns WHERE id = ?", (turn_id,)).scalar() or "[]"
    )
    said = " ".join(block["text"] for block in blocks)
    expected = _compliance.not_stated_lines(_compliance.rows(_envelopes(store, turn_id)))
    assert expected, "the international-remote scenario always carries a `manual` row"
    for line in expected:
        assert line in said, line
