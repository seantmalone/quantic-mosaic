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


def test_the_redirect_names_five_plain_topics_and_not_an_alphabetical_slice():
    """UX W6, cpux-re-8 = JX-R8. The five titles this replaced came off a `BY doc_id` ordering, so
    a reader who had just been refused was redirected to equipment and expenses — and never to PTO,
    remote work, travel or tax, the four topics §3.5 names and the product is demonstrated on."""
    steps = g1.refusal(g1.OUT_OF_SCOPE).next_steps
    titles = [document.doc_title for document in corpusread.list_documents()]
    assert len(titles) > g1.EXAMPLE_TOPIC_COUNT, "the library is bigger than the sample, or this rule is moot"

    named = [topic for topic in g1.example_topics() if topic in steps[0]]
    assert len(named) == g1.EXAMPLE_TOPIC_COUNT, f"five examples, not {len(named)}: {steps[0]!r}"
    assert not [title for title in titles if title in steps[0]], "topics, never document titles"
    for topic in ("PTO", "remote", "travel", "benefits"):
        assert topic in steps[0], f"the redirect never mentions {topic}: {steps[0]!r}"
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
    named = [topic for topic in g1.example_topics() if html_module.escape(topic) in refused.text]
    assert len(named) == g1.EXAMPLE_TOPIC_COUNT, f"the turn names {len(named)} topics"


async def test_a_declined_confirmation_is_not_a_coverage_question(web):
    """A decline answers the question it was asked and gets no library link (W8, C11).

    The link belongs to a **refusal for want of coverage** — "I could not find anything in Mosaic's
    policy library" — where naming a few of the things the library does cover is the useful half of
    the answer. A reader who cancelled a confirmation card has not been refused anything; since W8
    they keep the cited answer the turn already earned, and a library link under it would be an
    invitation to go and look for what they were just told.
    """
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
    assert 'data-outcome="answered"' in declined.text
    assert "Cancelled — nothing was created." in declined.text
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


#: One sentence of `corpus/remote-and-hybrid-work.md` that the source file wraps across two lines
#: (lines 97–98). Nothing about it is special except that it is hard-wrapped, which every paragraph
#: in this corpus is: the documents are stored at ~150 characters a line.
SPLIT_SENTENCE = "The requirement applies to temporary work abroad, not to business travel"


def test_a_hard_wrapped_paragraph_is_one_paragraph_and_not_a_column_of_ragged_lines():
    """UX W6 fix round. `policy_markup()` joined a paragraph's source lines with `<br>`, so every
    accident of the corpus's 150-character wrap became a forced break in the reader — mid-sentence,
    at every viewport. Markdown's own rule is the one the reader follows now: a soft wrap is a
    space, and only a line the author ended in two spaces is a break they asked for."""
    from hrmosaic.web import api

    wrapped = "At least 12 months of continuous service is required\nto work outside\nyour home country."
    assert api.policy_markup(wrapped) == (
        "<p>At least 12 months of continuous service is required to work outside your home country.</p>"
    )

    # The one break markdown keeps: a line ended with two spaces, which is an instruction.
    assert api.policy_markup("Ends in two spaces  \nso this is a new line.") == (
        "<p>Ends in two spaces<br>so this is a new line.</p>"
    )
    # A blank line is still a paragraph boundary.
    assert api.policy_markup("One.\n\nTwo.") == "<p>One.</p><p>Two.</p>"


async def test_the_reader_prints_a_corpus_paragraph_without_a_forced_line_break(web):
    """The same rule where a reader meets it: the rendered page, over the real corpus."""
    async with web() as client:
        page = await client.get("/policy/remote-and-hybrid-work")

    assert page.status_code == 200, page.text
    passages = re.findall(r'<div class="reader-passage">(.*?)</div>', page.text, re.S)
    assert passages, "the reader renders the document's passages"
    assert not [passage for passage in passages if "<br>" in passage], (
        "a hard-wrapped source line is a soft wrap, not a forced break"
    )

    holding = [paragraph for passage in passages for paragraph in re.findall(r"<p>(.*?)</p>", passage, re.S)]
    carrying = [paragraph for paragraph in holding if SPLIT_SENTENCE in paragraph]
    assert len(carrying) == 1, f"the wrapped sentence is one paragraph, not {len(carrying)}"


def test_dropping_an_employee_id_rewrites_that_span_and_nothing_else():
    """The other half of the same defect (UX W6 fix round). `without_employee_ids()` is the filter
    every chat string is printed through, and it finished with the same whole-string
    `re.sub(r"\\s{2,}", " ", …).replace(" .", ".")` — so one id in a multi-paragraph block collapsed
    the paragraph breaks of a block that merely happened to contain one."""
    from hrmosaic.web import api

    assert api.without_employee_ids("your director (Dana, E1007) approved it") == "your director (Dana) approved it"
    assert api.without_employee_ids("your director (E1007).") == "your director."
    assert api.without_employee_ids("Ask Dana E1007 today.") == "Ask Dana today."

    block = "Dana (E1007) approves it.\n\nThe approval is recorded . Keep the confirmation."
    assert api.without_employee_ids(block) == "Dana approves it.\n\nThe approval is recorded . Keep the confirmation."
