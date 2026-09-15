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


#: Every dashboard page §11.6 defines, plus the two detail routes that are only reachable with data
#: behind them. `/dashboard/evals/{run}` is the one that mattered: the crawl visited five routes and
#: never an eval-run detail, which is how 52 dead links per run page shipped green (UX W6,
#: nav-reaudit-3 / **P5**).
DASHBOARD_PAGES = (
    "/dashboard",
    "/dashboard/sessions",
    "/dashboard/turns",
    "/dashboard/llm",
    "/dashboard/retrieval",
    "/dashboard/tools",
    "/dashboard/safety",
    "/dashboard/mcp",
    "/dashboard/corpus",
    "/dashboard/evals",
)


async def test_every_href_the_dashboard_offers_resolves_for_the_default_persona(web, store):
    """Every `/dashboard/*` page, the session detail, **and an eval-run detail**.

    Including `Export JSON` and the `Continue this conversation in chat` action. The eval-run page
    is the reason this list is a list: its runs are imported from committed fixtures whose turns
    were never written into this store, so every `Trace` chip and every session pill it offered was
    a 404 — 52 of them on one page — and the crawl that was supposed to catch exactly this class of
    defect had never visited the route.
    """
    from pathlib import Path

    from hrmosaic.core import archive

    eval_runs = Path(__file__).resolve().parents[1] / "fixtures" / "eval_runs"
    async with web("rag_only.json") as client:
        turn = await client.post("/chat", json={"message": "How much PTO do I accrue each month?"})
        assert turn.status_code == 200, turn.text
        archive.import_results(store=store, results_dir=eval_runs)
        session_id = turn.json()["session_id"]

        runs = _links((await client.get("/dashboard/evals")).text)
        run_pages = [href for href in runs if href.startswith("/dashboard/evals/")]
        assert run_pages, "the imported runs give the crawl an eval-run detail to visit"

        pages = (*DASHBOARD_PAGES, f"/dashboard/sessions/{session_id}", run_pages[0])
        results: dict[str, int] = {}
        for url in pages:
            body = (await client.get(url)).text
            for href in _links(body):
                results[href] = (await client.get(href)).status_code

    assert f"/?session={session_id}" in results, "the session page offers the way back to chat"
    assert all(200 <= status < 300 for status in results.values()), {
        href: status for href, status in results.items() if not 200 <= status < 300
    }


async def test_following_a_citation_and_coming_back_keeps_the_conversation(web):
    """**P5 / nav-reaudit-1**, the round trip the re-audit called the most-travelled path there is.

    Six citations per answer, each one an ordinary `href`. Chat now writes `?session=<id>` into its
    own URL after the first turn, the reader offers an explicit way back to that URL, and the URL
    replays the transcript — so Back, reload and the reader's own link all land on the conversation
    rather than on an empty composer.
    """
    async with web("demo_task_1.json") as client:
        turn = await client.post("/chat", json={"message": TOOL_USING_QUESTION}, headers=HTMX)
        assert turn.status_code == 200, turn.text
        session_id = re.search(r'data-session-id="([0-9a-f]+)"', turn.text).group(1)

        citation = next(href for href in _links(turn.text) if href.startswith("/policy/"))
        reader = await client.get(citation.partition("#")[0])
        assert reader.status_code == 200

        back = re.search(r'class="back-to-chat" href="([^"]+)"', reader.text)
        assert back, "the reader offers an explicit way back to the conversation"
        assert back.group(1) == f"/?session={session_id}", back.group(1)

        conversation = await client.get(back.group(1))

    assert conversation.status_code == 200
    assert f'data-session-id="{session_id}"' in conversation.text, "the transcript is still rendered"
    assert conversation.text.count('class="turn"') == 1, "one turn, replayed once"


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
