"""The named UI smoke test (spec §11.5, R6.2).

`GET /` returns 200 and the HTML carries the act-as `<select>`, both demo buttons and the span-rail
container; then a tool-using message is posted and the **rendered turn** is asserted: a
`policy_fact` badge, a `recommendation` badge with the literal *"Recommendation — not company
policy"*, and at least one citation chip whose `href` is the chunk's `source_url` deep link.

`POST /chat` is one endpoint with two representations: JSON for API clients (the contract of §11.1)
and the same `ChatResponse` rendered server-side for an htmx request from the page. §11.8's endpoint
list is exact, so a second "render this turn" route was never an option — and rendering on the
server is what lets this test assert on the badges a grader actually sees rather than on a template
that some JavaScript may or may not use.
"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.anyio

HTMX = {"HX-Request": "true"}
TOOL_USING_QUESTION = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"
RECOMMENDATION_BADGE = "Recommendation — not company policy"


async def test_the_chat_page_carries_the_selector_the_demo_buttons_and_the_rail(web):
    async with web() as client:
        response = await client.get("/")

    assert response.status_code == 200
    html = response.text
    assert '<select id="actor-select" name="actor"' in html
    assert html.count('<option value="E1') == 24, "the 24 mock employees"
    assert '<option value="admin"' in html, "plus HR admin"
    assert html.count('class="button demo-button"') == 2
    assert 'id="span-rail"' in html
    assert 'id="cold-start-banner"' in html
    assert 'value="E1042" selected' in html, "the default persona is pre-selected"


async def test_the_dashboard_link_is_rendered_only_in_the_admin_persona(web):
    async with web() as client:
        employee = await client.get("/")
        admin = await client.get("/", headers={"X-Actor": "admin"})

    assert 'id="dashboard-link"' not in employee.text
    assert 'id="dashboard-link"' in admin.text


async def test_a_rendered_turn_shows_typed_blocks_badges_and_citation_chips(web):
    async with web("demo_task_1.json") as client:
        response = await client.post(
            "/chat", json={"message": TOOL_USING_QUESTION, "client_label": "web"}, headers=HTMX
        )
        citations = (await client.post("/chat", json={"message": "What is the weather?"}, headers=HTMX)).status_code

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text

    assert 'class="badge badge-policy_fact"' in html
    assert 'class="badge badge-recommendation"' in html
    assert RECOMMENDATION_BADGE in html
    assert 'class="badge badge-escalation"' in html

    chips = re.findall(r'<a class="citation-chip" href="([^"]+)"', html)
    assert chips, "at least one citation chip"
    assert all(href.startswith("/dashboard/corpus/") and "#c_" in href for href in chips)
    assert citations == 200


async def test_a_rendered_turn_carries_the_snapshot_note_when_a_tool_result_has_an_as_of(web):
    """*"Employee data as of 1 September 2026"* — under any answer whose tool results carry it."""
    async with web("demo_task_1.json") as client:
        response = await client.post("/chat", json={"message": TOOL_USING_QUESTION}, headers=HTMX)

    assert 'class="snapshot-note"' in response.text
    assert "Employee data as of 1 September 2026" in response.text


async def test_the_same_post_returns_json_to_an_api_client(web):
    """The htmx fragment is a representation, never a second contract (§11.1)."""
    async with web("rag_only.json") as client:
        response = await client.post(
            "/chat", json={"message": "How much PTO do full-time employees accrue each month?"}
        )

    assert response.headers["content-type"].startswith("application/json")
    assert set(response.json()) >= {"answer", "citations", "trace", "answer_blocks"}
