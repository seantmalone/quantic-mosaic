"""**P5 — no link is offered to a persona that cannot follow it** (UX W1).

The audit's worst single number: an answered turn rendered 7–9 hrefs that all 403'd for the default
persona, and the most inviting of them were the citation chips. Every one pointed at
`/dashboard/corpus/{doc}#{chunk}` behind a gate 24 of the 25 personas could not pass.

The rule is mechanical and permanent: crawl every `href` the page renders **as the default actor**
and require each to resolve 2xx as that same actor. It is the regression guard for the whole class,
not for the one link that started it.
"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.anyio

HTMX = {"HX-Request": "true"}
TOOL_USING_QUESTION = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"

HREF = re.compile(r'href="([^"]+)"')

#: `/static/*` is served by `StaticFiles`, not a route, and `/health` is a JSON probe; both are
#: crawled all the same — the point is that nothing the page offers is a dead end.
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "javascript:", "#")


def _links(html: str) -> list[str]:
    seen: list[str] = []
    for href in HREF.findall(html):
        if href.startswith(SKIP_SCHEMES) or href in seen:
            continue
        seen.append(href)
    return seen


async def test_every_href_on_the_chat_page_resolves_for_the_default_persona(web):
    async with web() as client:
        page = await client.get("/")
        results = {href: (await client.get(href)).status_code for href in _links(page.text)}

    assert results, "the chat page renders at least one link"
    assert all(200 <= status < 300 for status in results.values()), results


async def test_every_href_on_an_answered_turn_resolves_for_the_default_persona(web):
    """The citation chips, followed as the persona that was shown them."""
    async with web("demo_task_1.json") as client:
        turn = await client.post("/chat", json={"message": TOOL_USING_QUESTION}, headers=HTMX)
        assert turn.status_code == 200, turn.text
        links = _links(turn.text)
        results = {href: (await client.get(href)).status_code for href in links}

    assert any(href.startswith("/policy/") for href in links), "an answered turn cites something"
    assert all(200 <= status < 300 for status in results.values()), results


async def test_every_href_the_dashboard_offers_resolves_for_the_default_persona(web, store):
    """Including `Export JSON` and the `Continue this conversation in chat` action."""
    from pathlib import Path

    from hrmosaic.core import archive

    eval_runs = Path(__file__).resolve().parents[1] / "fixtures" / "eval_runs"
    async with web("rag_only.json") as client:
        turn = await client.post("/chat", json={"message": "How much PTO do I accrue each month?"})
        assert turn.status_code == 200, turn.text
        archive.import_results(store=store, results_dir=eval_runs)
        session_id = turn.json()["session_id"]

        pages = ("/dashboard", "/dashboard/sessions", f"/dashboard/sessions/{session_id}")
        results: dict[str, int] = {}
        for url in pages:
            body = (await client.get(url)).text
            for href in _links(body):
                results[href] = (await client.get(href)).status_code

    assert f"/?session={session_id}" in results, "the session page offers the way back to chat"
    assert all(200 <= status < 300 for status in results.values()), results


async def test_the_policy_reader_anchors_every_chunk_a_citation_can_name(web):
    """navigation-and-ia-11: the chip's fragment has to exist on the page it lands on."""
    async with web("demo_task_1.json") as client:
        turn = await client.post("/chat", json={"message": TOOL_USING_QUESTION}, headers=HTMX)
        chips = [href for href in _links(turn.text) if href.startswith("/policy/")]
        assert chips, "an answered turn cites something"
        path, _, fragment = chips[0].partition("#")
        page = await client.get(path)

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert f'id="{fragment}"' in page.text, "the chunk the citation names is an anchor on the page"
    assert 'class="masthead"' in page.text, "the reader is inside the shell, so there is a way back"
