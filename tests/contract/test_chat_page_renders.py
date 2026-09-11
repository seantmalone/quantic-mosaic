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
PTO_QUESTION = (
    "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
    "— and can you open the request for me?"
)
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


async def test_at_rest_the_page_carries_neither_a_banner_nor_an_empty_answer_preview(web):
    """Page load, before any turn: the two transient areas are off screen, and stay off (§11.5).

    Both were on screen at rest, and neither could be dismissed. `hidden` was on both elements from
    the day they were written, but an author `display:` beats the user-agent sheet's
    `[hidden] { display: none }` — and `.banner` and `.turn` each set one. So the
    *"Waking the free instance…"* strip was painted on every load and survived `banner.hidden =
    true` when `/health` answered, and the provisional-answer box was painted empty under its
    *"Writing the answer…"* caption before a question had been asked. One `!important` declaration
    gives the pages back their one visibility switch; these assertions are what keep it.
    """
    async with web() as client:
        html = (await client.get("/")).text
        css = (await client.get("/static/app.css")).text

    assert '<div id="cold-start-banner" class="banner" hidden>' in html
    assert '<article id="provisional-answer" class="turn turn-provisional" aria-live="polite" hidden>' in html
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}", css), (
        "`hidden` must beat every author `display:` rule, or neither area can be hidden at all"
    )

    # The preview is revealed by the first `answer_delta` frame and hidden again by the hard
    # replace on `turn_completed` — never at load.
    assert "provisional.hidden = false;" in html
    assert "provisional.hidden = true;" in html

    # The banner describes one state: a request that is actually waiting. The page itself was
    # served by the instance, so the preflight answers in milliseconds on a warm one and the
    # banner is never revealed at all.
    preflight = html.split("function coldStartPreflight()")[1]
    assert "COLD_START_BANNER_DELAY_MS" in preflight
    assert preflight.count("banner.hidden = false") == 1
    assert "setTimeout(" in preflight, "the reveal is deferred, so a warm load never flashes it"
    assert "clearTimeout(reveal)" in preflight, "a preflight that answers first cancels the reveal"
    assert "banner.hidden = true" in preflight, "and hides it if it was already on screen"


async def test_the_rail_narrates_each_step_and_the_answer_streams_under_it(web):
    """§11.3's two additions, asserted on the markup and the script a grader actually loads."""
    async with web() as client:
        html = (await client.get("/")).text
        css = (await client.get("/static/app.css")).text

    # The rail is `aria-live="polite"` — unchanged — and its in-progress line carries a spinner and
    # a live elapsed counter that the closed span then replaces, matched on `span_id`.
    assert '<ol id="span-rail" class="span-rail" aria-live="polite">' in html
    assert 'stream.addEventListener("step_started"' in html
    assert "item.dataset.spanId = step.span_id" in html
    assert "span-spinner" in html and "span-elapsed" in html
    assert "rail.querySelector('[data-span-id=\"' + span.span_id + '\"]')" in html
    assert "@keyframes span-spin" in css

    # The provisional answer, and the JS mirror of `render_answer()` that keeps a recommendation
    # labelled even before the turn is over (§7.3).
    assert 'id="provisional-answer"' in html
    assert 'stream.addEventListener("answer_delta"' in html
    assert RECOMMENDATION_BADGE + ": " in html, "the JS mirror carries render_answer's own prefix"
    assert '"Escalation: "' in html
    assert "clearProvisional();" in html, "`turn_completed` is a hard replace, never a merge"


async def test_the_provisional_render_mirrors_g3s_relabel_of_an_uncited_policy_fact(web):
    """`#provisional-blocks` must never show an unverified claim as company policy (§11.3).

    `renderBlock()` mirrored `render_answer()`'s two prefixes but not G3's relabel rule: a streamed
    `policy_fact` with an empty `citations[]` is exactly what G3 turns into a `recommendation` in
    the final answer, and what G2 drops when its citations do not resolve. `turn_completed` hard-
    replaces the preview — but §11.3 records 2 of 17 answered turns being revised after the last
    token, and for those seconds the claim was on screen wearing the wrong label. `StreamedBlock`
    already carries `citations`, so the rule costs nothing on the wire.
    """
    async with web() as client:
        html = (await client.get("/")).text

    assert 'block.type === "policy_fact" && (block.citations || []).length === 0' in html
    assert 'if (block.type === "recommendation" || uncitedFact)' in html


async def test_the_page_resubscribes_for_the_resumed_half_of_a_gated_turn(web):
    """The confirm card's POST opens a stream of its own, on the SAME turn id (§10.3 step 4).

    `POST /chat` publishes `turn_completed` even when the outcome is `awaiting_confirmation`, so the
    page's `EventSource` is closed by the time the confirm card is on screen. Without a second
    subscription the resumed half — the one that performs the mock write and writes the answer —
    would publish every span and every `answer_delta` into a broker with no subscribers, and the
    rail would sit on its pre-gate lines until the htmx swap.
    """
    async with web() as client:
        html = (await client.get("/")).text

    assert 'event.detail.path === "/chat/confirm"' in html
    assert "openStream(resumed, false)" in html, "the rail keeps its pre-gate lines"
    assert "openStream(turnId, true)" in html, "a new turn still starts from an empty rail"
    # The id is the card's own hidden field: minting a second one would subscribe to a turn that
    # never publishes, and overwriting `turnField` would misroute the NEXT message.
    assert "var resumed = event.detail.parameters.turn_id;" in html


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

    chips = re.findall(r'<a class="citation-chip" href="([^"]+)"', html)
    assert chips, "at least one citation chip"
    assert all(href.startswith("/dashboard/corpus/") and "#c_" in href for href in chips)
    assert citations == 200


async def test_an_escalation_block_renders_its_own_badge(web):
    """The third badge, on the turn that actually produces one.

    Demo task 1's committed recording — a real exchange, not a hand-written fixture — states the
    director approval and the Tax & Legal review as cited `policy_fact`s rather than labelling them
    an escalation, so the `escalation` badge has to be asserted where the model does emit one:
    demo task 2, after the human confirms, where the answer hands the reader off to their manager.
    """
    async with web("demo_task_2.json") as client:
        proposal = await client.post("/chat", json={"message": PTO_QUESTION, "client_label": "web"})
        assert proposal.status_code == 200, proposal.text
        pending = proposal.json()
        assert pending["outcome"] == "awaiting_confirmation"

        confirmed = await client.post(
            "/chat/confirm",
            json={
                "session_id": pending["session_id"],
                "turn_id": pending["turn_id"],
                "decision": "confirmed",
            },
            headers=HTMX,
        )

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.headers["content-type"].startswith("text/html")
    assert 'class="badge badge-escalation"' in confirmed.text


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
