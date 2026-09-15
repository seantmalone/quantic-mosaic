"""The refusal's redirect, and the page it links to (UX W3, jargon-and-exposure-3).

Before this wave a refusal ended with all fourteen document titles joined by semicolons — the
longest single string on the chat surface, printed at the moment a reader is least inclined to read
a list. It now names five example titles and links `/policy`, a reader-facing index of the whole
library: the inventory still exists, on a page whose job it is.

Both halves are asserted here because they are one promise. A link with no page is a dead end (P5,
P6) and a shortened sentence with no link would be the technical record destroyed rather than
relocated (P15).
"""

from __future__ import annotations

import html as html_module
import re

import pytest

from hrmosaic.agent.guardrails import g1
from hrmosaic.core import corpusread

pytestmark = pytest.mark.anyio

HTMX = {"HX-Request": "true"}
TUITION = (
    "What is Mosaic's tuition reimbursement cap for a part-time master's degree, and how many "
    "years of service do I need to qualify?"
)


def test_the_redirect_names_five_example_titles_from_the_real_index():
    steps = g1.refusal(g1.OUT_OF_SCOPE).next_steps
    covered = g1.coverage()
    assert len(covered) > g1.EXAMPLE_TOPIC_COUNT, "the library is bigger than the sample, or this rule is moot"

    named = [title for title in covered if title in steps[0]]
    assert len(named) == g1.EXAMPLE_TOPIC_COUNT, f"five examples, not {len(named)}: {steps[0]!r}"
    assert named == g1.example_topics(), "and they are the index's own, never a hard-coded list"
    assert ";" not in steps[0], "a sentence, not a semicolon-separated dump"
    assert steps[0].endswith("."), steps[0]


def test_the_english_list_reads_as_a_sentence():
    assert g1._sentence(["A", "B", "C"]) == "A, B and C"
    assert g1._sentence(["A", "B"]) == "A and B"
    assert g1._sentence(["A"]) == "A"
    assert g1._sentence([]) == ""


async def test_a_refused_turn_offers_the_library_instead_of_listing_it(web):
    async with web("out_of_corpus_tuition.json") as client:
        refused = await client.post("/chat", json={"message": TUITION}, headers=HTMX)

    assert refused.status_code == 200, refused.text
    assert 'data-outcome="refused"' in refused.text
    assert '<p class="policy-library"><a href="/policy">See the full policy library</a></p>' in refused.text
    titles = [title for title in g1.coverage() if html_module.escape(title) in refused.text]
    assert len(titles) == g1.EXAMPLE_TOPIC_COUNT, f"the turn names {len(titles)} documents"


async def test_a_declined_confirmation_is_refused_but_is_not_a_coverage_question(web):
    """`_record_decline()` closes the turn as `refused` with no steps; it gets no library link."""
    demo_2 = (
        "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
        "— and can you open the request for me?"
    )
    async with web("demo_task_2.json") as client:
        card = await client.post("/chat", json={"message": demo_2}, headers=HTMX)
        ids = re.search(r'data-session-id="([0-9a-f]+)" *\n? *data-turn-id="([0-9a-f]+)"', card.text)
        assert ids, card.text[:400]
        declined = await client.post(
            "/chat/confirm",
            json={"session_id": ids.group(1), "turn_id": ids.group(2), "decision": "declined"},
            headers=HTMX,
        )

    assert declined.status_code == 200, declined.text
    assert 'data-outcome="refused"' in declined.text
    assert "policy-library" not in declined.text


async def test_the_library_page_lists_every_document_and_links_the_reader_route(web):
    async with web() as client:
        page = await client.get("/policy")
        first = await client.get(f"/policy/{corpusread.list_documents()[0].doc_id}")

    assert page.status_code == 200 and first.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    linked = re.findall(r'<a href="/policy/([a-z0-9-]+)">', page.text)
    assert linked == [document.doc_id for document in corpusread.list_documents()]
    assert '<header class="masthead">' in page.text, "the library wears the one shell (P3)"
