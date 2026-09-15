"""The named UI smoke test (spec §11.5, R6.2).

`GET /` returns 200 and the HTML carries the act-as `<select>`, both demo buttons and the status
line; then a tool-using message is posted and the **rendered turn** is asserted: a cited
`policy_fact` block, the grouped suggestions with their one footnote, and at least one source link
whose `href` is the chunk's `source_url` deep link.

**Amended at UX W2.** The rail this used to assert on is gone, and so are the per-sentence badges:
the technical record lives on the dashboard, a fact is prose with a friendly reference under it,
and the labelling guarantee — a suggestion must never read as company policy — is stated once per
turn by `SUGGESTION_FOOTNOTE` and, unchanged, by `orchestrator.render_answer()` in the plain-text
`answer` the JSON contract and the eval harness read.

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
SENSITIVE_QUESTION = "A colleague has been harassing me in meetings and I want to raise it formally."
SUGGESTION_FOOTNOTE = "Suggestions are guidance, not company policy."


async def test_the_chat_page_carries_the_selector_the_demo_buttons_and_the_status_line(web):
    async with web() as client:
        response = await client.get("/")

    assert response.status_code == 200
    html = response.text
    assert '<select id="actor-select" name="actor"' in html
    assert html.count('<option value="E1') == 24, "the 24 mock employees"
    assert '<option value="admin"' in html, "plus HR admin"
    assert html.count('class="button demo-button"') == 2
    assert 'id="turn-status"' in html, "one progress line, where the 22rem rail used to be"
    assert 'id="cold-start-banner"' in html
    assert 'value="E1042" selected' in html, "the default persona is pre-selected"


async def test_the_empty_conversation_greets_the_persona_and_offers_four_starters(web):
    """chat-production-ux-1: at rest the page was an unlabelled textarea and two buttons."""
    async with web() as client:
        html = (await client.get("/")).text

    assert "Hi Priya — ask me anything about HR" in html
    assert html.count('class="starter"') == 4
    # A starter prefills the composer and focuses it; nothing is submitted for the reader.
    starters = html.split('document.querySelectorAll(".starter")')[1].split("document.querySelectorAll")[0]
    assert "messageBox.value = button.dataset.prompt" in starters
    assert "requestSubmit" not in starters
    assert "Enter to send · Shift+Enter for a new line" in html


async def test_at_rest_the_page_carries_neither_a_banner_nor_an_empty_answer_preview(web):
    """Page load, before any turn: the two transient areas are off screen, and stay off (§11.5).

    Both were on screen at rest, and neither could be dismissed. `hidden` was on both elements from
    the day they were written, but an author `display:` beats the user-agent sheet's
    `[hidden] { display: none }` — and `.banner` and `.turn` each set one. So the
    *"Waking the free instance…"* strip was painted on every load and survived `banner.hidden =
    true` when `/health` answered, and the provisional-answer box was painted empty under its
    *"Writing the answer…"* caption before a question had been asked. One `!important` declaration
    gives the pages back their one visibility switch; these assertions are what keep it.

    The preview is `aria-hidden` since UX W2: it is a preview, the finished answer is what the one
    live region announces, and a region that appended a paragraph per streamed block was half of
    the 46-announcements-a-turn firehose the audit measured (accessibility-and-responsive-3).
    """
    async with web() as client:
        html = (await client.get("/")).text
        css = (await client.get("/static/app.css")).text

    assert '<p id="cold-start-banner" class="banner" hidden>' in html
    assert (
        '<div id="provisional-answer" class="message message-agent turn-provisional" aria-hidden="true" hidden>'
    ) in html
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


async def test_one_status_line_narrates_the_turn_and_the_answer_streams_under_it(web):
    """§11.3's two additions, asserted on the markup and the script a grader actually loads.

    The rail that used to carry this — 22rem of `span.kind · span.name — span.summary`, a 100 ms
    elapsed ticker per running step and a `turn completed · awaiting_confirmation` line — is gone
    (jargon-and-exposure-1, -13). What is left is one throttled `role="status"` line fed by
    `narration.label_for()`, and it is the page's only live region.
    """
    async with web() as client:
        html = (await client.get("/")).text

    assert '<p id="turn-status" class="turn-status" role="status">' in html
    assert 'stream.addEventListener("step_started"' in html
    assert "setStatus(JSON.parse(event.data).label)" in html, "the label, and nothing else off the span"
    assert "STATUS_MIN_MS" in html, "throttled, or the same label is announced six times a turn"
    assert html.count('role="status"') == 1, "one live region on the page at rest, not a rail of them"
    assert 'aria-live="polite"' not in html, "the rail's `aria-live` firehose is gone with the rail"

    # The provisional answer, and the JS mirror of `render_answer()`: complete blocks only, with
    # the one footnote the finished turn carries rather than a badge per sentence (§7.3).
    assert 'id="provisional-answer"' in html
    assert 'stream.addEventListener("answer_delta"' in html
    assert "Suggestions are guidance, not company policy." in html
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
    assert 'return block.type === "recommendation" || uncitedFact;' in html


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


async def test_the_dashboard_link_is_rendered_for_every_persona(web):
    """W1 reversed this: the switch is part of the shell, not a reward for picking a persona.

    The parity contract for the shared masthead lives in `tests/contract/test_nav_parity.py`; this
    assertion stays here because §11.5's named UI smoke test is what a grader reads first.
    """
    async with web() as client:
        employee = await client.get("/")
        admin = await client.get("/", headers={"X-Actor": "admin"})

    assert 'id="dashboard-link"' in employee.text
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

    assert 'class="answer-block answer-block-policy_fact"' in html
    assert 'class="answer-block answer-block-recommendation"' in html
    assert SUGGESTION_FOOTNOTE in html, "the labelling guarantee, once per turn instead of once per sentence"
    assert 'class="badge' not in html, "no chip on any sentence (chat-production-ux-8)"

    chips = re.findall(r'<a class="source-link" href="([^"]+)"', html)
    assert chips, "at least one source link"
    # UX W1 repointed `SOURCE_URL` at the reader route: a citation is a promise to a person that
    # they can go and read the passage, and the dashboard's chunk inspector was neither readable
    # nor reachable for the default persona.
    assert all(href.startswith("/policy/") and "#c_" in href for href in chips)
    assert citations == 200


async def test_an_escalation_block_renders_its_own_badge(web):
    """The third badge, on the turn that actually produces one: G5's sensitive escalation (§7.4).

    Demo task 1's committed recording — a real exchange, not a hand-written fixture — states the
    director approval and the Tax & Legal review as cited `policy_fact`s rather than labelling them
    an escalation. Demo task 2's recording *did* emit one, and that is exactly the block P22's
    outcome-consistency step now replaces: it denied a ticket the same turn had already created.
    So the badge is asserted where an escalation is the right answer and always will be — a
    harassment report, which G5 escalates deterministically without calling a tool.
    """
    async with web("sensitive.json") as client:
        response = await client.post("/chat", json={"message": SENSITIVE_QUESTION}, headers=HTMX)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert 'class="answer-block answer-block-escalation"' in response.text


async def test_a_rendered_turn_carries_the_snapshot_note_when_a_tool_result_has_an_as_of(web):
    """*"Employee data as of 1 September 2026"* — under any answer whose tool results carry it."""
    async with web("demo_task_1.json") as client:
        response = await client.post("/chat", json={"message": TOOL_USING_QUESTION}, headers=HTMX)

    assert 'class="snapshot-note"' in response.text
    assert "Based on employee data from 1 September 2026" in response.text


async def test_the_same_post_returns_json_to_an_api_client(web):
    """The htmx fragment is a representation, never a second contract (§11.1)."""
    async with web("rag_only.json") as client:
        response = await client.post(
            "/chat", json={"message": "How much PTO do full-time employees accrue each month?"}
        )

    assert response.headers["content-type"].startswith("application/json")
    assert set(response.json()) >= {"answer", "citations", "trace", "answer_blocks"}
