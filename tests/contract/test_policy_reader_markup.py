"""The policy reader prints prose, never markup, and lists exactly the sections it renders (UX W7).

* **JX2-04**: the corpus is hard-wrapped at ~150 characters and its emphasis spans straddle the
  wraps. W6 marked each source line up on its own, so a span across a wrap matched nothing and
  printed its literal asterisks to employees. The paragraph's lines are now joined *before* the
  inline pass — and this test reads every one of the fourteen documents, not the one the capture
  happens to photograph.
* **nav-r2-6 = a11y-re2-8**: one `<section>` per heading, every passage anchored inside it, so the
  contents list and the body agree one to one and no section opens mid-word.
"""

from __future__ import annotations

import html as html_module
import re

import pytest

from hrmosaic.core import corpusread

pytestmark = pytest.mark.anyio

#: Literal markdown a reader must never see: bold/emphasis asterisks, and `_word_` emphasis.
LITERAL_MARKUP = re.compile(r"\*\*|(?<![\w/])_[A-Za-z][^_\n]{0,60}[A-Za-z]_(?![\w/])")


def _reader_text(page: str) -> str:
    article = re.search(r'<article class="reader-doc">.*?</article>', page, re.S)
    assert article, "the reader renders one article"
    return html_module.unescape(re.sub(r"<[^>]+>", " ", article.group(0)))


async def test_no_document_in_the_library_shows_a_reader_its_markup(web):
    documents = [document.doc_id for document in corpusread.list_documents()]
    assert documents, "the library is loaded"
    async with web() as client:
        offenders = {}
        for doc_id in documents:
            page = (await client.get(f"/policy/{doc_id}")).text
            found = LITERAL_MARKUP.findall(_reader_text(page))
            if found:
                offenders[doc_id] = found[:3]
    assert not offenders, f"literal markup reached the reader: {offenders}"


async def test_the_contents_list_and_the_sections_agree_one_to_one_and_every_passage_is_anchored(web):
    async with web() as client:
        rows = {document.doc_id: corpusread.list_chunks(document.doc_id) for document in corpusread.list_documents()}
        for doc_id, chunks in rows.items():
            page = (await client.get(f"/policy/{doc_id}")).text
            listed = re.findall(r'<nav class="reader-contents".*?</nav>', page, re.S)[0].count("<li>")
            sections = page.count('<section class="reader-section"')
            assert listed == sections, f"{doc_id}: {listed} contents entries for {sections} sections"
            headings = len({chunk.heading_path for chunk in chunks})
            assert sections == headings, f"{doc_id}: {sections} sections for {headings} distinct headings"
            for chunk in chunks:
                assert f'id="{chunk.chunk_id}"' in page, f"{doc_id}: passage {chunk.chunk_id} has no anchor"
