"""**P3 — one global nav on every page.** Identical markup, identical position (UX W1).

Before W1 there were three mastheads and two product names: chat carried an "Act as" `<select>`
plus a `Dashboard` link that existed only for the `admin` persona, the dashboard carried a `Chat`
link plus a static `HR ADMIN` chip and no way to sign out, and the key page carried neither. The
switch between the two surfaces therefore changed shape with the page *and* with the persona.

`templates/_masthead.html` is now the one partial both surfaces include, and this file is its
contract: the rendered `<header class="masthead">…</header>` block is **byte-identical** on `/` and
on all 13 `/dashboard/*` routes once `aria-current="page"` — the single marker of which half of the
switch is current — is removed.
"""

from __future__ import annotations

import re

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.anyio

TOKEN = "nav-parity-token"

MASTHEAD = re.compile(r'<header class="masthead">.*?</header>', re.S)
ARIA_CURRENT = re.compile(r'\s*aria-current="page"')

#: The 13 `/dashboard/*` routes of §11.6. The two id-taking ones are filled in by the fixture.
DASHBOARD_ROUTES = (
    "/dashboard",
    "/dashboard/sessions",
    "/dashboard/sessions/{session_id}",
    "/dashboard/turns",
    "/dashboard/llm",
    "/dashboard/retrieval",
    "/dashboard/tools",
    "/dashboard/safety",
    "/dashboard/mcp",
    "/dashboard/corpus",
    "/dashboard/corpus/{doc_id}",
    "/dashboard/evals",
    "/dashboard/evals/{run_id}",
)


def _masthead(html: str) -> str:
    match = MASTHEAD.search(html)
    assert match, 'no `<header class="masthead">` on this page'
    return match.group(0)


def _shape(html: str) -> str:
    """The masthead with its one permitted difference removed."""
    return ARIA_CURRENT.sub("", _masthead(html))


@pytest.fixture
async def seeded(web, store):
    """One real turn plus the committed eval runs, so every id-taking route has an id."""
    from pathlib import Path

    from hrmosaic.core import archive

    eval_runs = Path(__file__).resolve().parents[1] / "fixtures" / "eval_runs"
    async with web("rag_only.json") as client:
        turn = await client.post("/chat", json={"message": "How much PTO do I accrue each month?"})
        assert turn.status_code == 200, turn.text
        archive.import_results(store=store, results_dir=eval_runs)
        yield (
            client,
            {
                "session_id": turn.json()["session_id"],
                "doc_id": "pto-and-holidays",
                "run_id": "r_p9fixture_baseline",
            },
        )


async def test_the_masthead_is_byte_identical_on_chat_and_on_all_thirteen_dashboard_routes(seeded):
    client, ids = seeded
    chat = _shape((await client.get("/")).text)

    for template in DASHBOARD_ROUTES:
        url = template.format(**ids)
        response = await client.get(url)
        assert response.status_code == 200, f"{url} answered {response.status_code}"
        assert _shape(response.text) == chat, f"the masthead on {url} differs from the one on /"


async def test_the_switch_marks_the_current_surface_and_only_that(seeded):
    client, ids = seeded
    chat = _masthead((await client.get("/")).text)
    dashboard = _masthead((await client.get("/dashboard")).text)

    assert chat.count('aria-current="page"') == 1
    assert dashboard.count('aria-current="page"') == 1
    assert re.search(r'id="chat-link"[^>]*aria-current="page"', chat)
    assert re.search(r'id="dashboard-link"[^>]*aria-current="page"', dashboard)


async def test_the_dashboard_link_is_rendered_for_the_default_persona(web):
    """navigation-and-ia-1: 24 of 25 personas used to have no route to the dashboard at all."""
    async with web() as client:
        employee = await client.get("/")
        admin = await client.get("/", headers={"X-Actor": "admin"})

    assert 'id="dashboard-link" href="/dashboard"' in employee.text
    assert 'id="dashboard-link" href="/dashboard"' in admin.text


async def test_sign_out_is_on_both_surfaces_when_the_gate_is_on_and_on_neither_when_it_is_off(web):
    """navigation-and-ia-6: Sign out existed on chat and on none of the 13 dashboard routes."""
    async with web(app_access_token=SecretStr(TOKEN)) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        gated = [(await client.get(url, headers=headers)).text for url in ("/", "/dashboard")]
    async with web() as client:
        open_app = [(await client.get(url)).text for url in ("/", "/dashboard")]

    for html in gated:
        assert 'action="/access/logout"' in html
    for html in open_app:
        assert 'action="/access/logout"' not in html, "nothing to sign out of when the gate is off"


async def test_the_masthead_carries_a_read_only_identity_chip_and_no_persona_control(web):
    """jargon-and-exposure-10 / navigation-and-ia-20: the select and the `HR ADMIN` pill are gone."""
    async with web() as client:
        chat = await client.get("/")
        dashboard = await client.get("/dashboard")

    for response in (chat, dashboard):
        masthead = _masthead(response.text)
        assert "Priya Raghavan" in masthead, "the acting persona, by name"
        assert "<select" not in masthead, "the act-as selector moved to the demo panel"
        assert "persona-chip" not in masthead, "the static HR ADMIN pill is gone"
        assert "audit trail" not in masthead and "observability" not in masthead


async def test_the_dashboard_nav_is_grouped_and_carries_no_ordinals_or_inert_entry(web):
    """navigation-and-ia-8 / accessibility-and-responsive-7: no `1.`–`11.`, no greyed pseudo-entry."""
    async with web() as client:
        html = (await client.get("/dashboard")).text

    nav = re.search(r'<nav id="dash-nav".*?</nav>', html, re.S)
    assert nav, "the dashboard page nav"
    body = nav.group(0)
    assert not re.search(r">\s*\d+\.\s", body), "nav labels carry no spec-section ordinals"
    assert "is-detail" not in body, "the inert `3. Session detail` entry is gone"
    assert 'data-nav="4"' in body, "`data-nav` survives — the contract tests key on it"
    for group in ("Activity", "Under the hood", "Quality", "Reference"):
        assert group in body, f"the nav group {group!r}"


async def test_the_nav_group_labels_are_eyebrows_and_only_the_page_links_are_targets(web):
    """UX W7, Addendum 2 — the owner's decision. ACTIVITY / UNDER THE HOOD / QUALITY / REFERENCE
    sat in the same row and weight as the page links and read as targets. Each is now a
    non-interactive eyebrow: not an `<a>`, not a `<button>`, no `href`, not focusable, hidden from
    assistive tech — which hears the group's name from the `aria-label` on its `<ul>` instead."""
    async with web() as client:
        html = (await client.get("/dashboard/tools")).text

    nav = re.search(r'<nav id="dash-nav".*?</nav>', html, re.S)
    assert nav, "the dashboard page nav"
    body = nav.group(0)
    groups = re.findall(r'<ul class="dash-nav-group" aria-label="([^"]+)">', body)
    assert groups == ["Activity", "Under the hood", "Quality", "Reference"], groups
    eyebrows = re.findall(r'<li class="dash-nav-eyebrow"([^>]*)>([^<]+)</li>', body)
    assert [text for _attrs, text in eyebrows] == groups, "one eyebrow per group, in the group's own words"
    for attrs, text in eyebrows:
        assert 'aria-hidden="true"' in attrs, f"{text!r} is announced twice"
        assert "href" not in attrs and "tabindex" not in attrs and "role" not in attrs, f"{text!r} is a target: {attrs}"
    for group in groups:
        assert not re.search(rf"<(a|button)\b[^>]*>\s*{re.escape(group)}\s*</(a|button)>", body), (
            f"the group label {group!r} is rendered as a control"
        )
    links = re.findall(r'<a class="dash-nav-link"[^>]*>', body)
    assert len(links) == 10 and all("href=" in link for link in links), links
    assert "Corpus &amp; chunks" in body and "Policy library" not in body, (
        "the inspector is named for what it is; the reader keeps the library's name (nav-r2-5)"
    )


async def test_session_detail_highlights_its_real_parent_in_the_nav(seeded):
    """…as the section it is *in*, not as the page the reader is on (UX W4, navigation-and-ia-10).

    W1 lit the parent with `aria-current="page"`, which tells a screen-reader user that the Sessions
    link is the current page when it is not: following it goes somewhere else. A detail page is
    `aria-current="true"` — within this section — and carries a breadcrumb to the parent instead.
    """
    client, ids = seeded
    detail = (await client.get(f"/dashboard/sessions/{ids['session_id']}")).text
    listing = (await client.get("/dashboard/sessions")).text

    assert re.search(r'data-nav="2"[^>]*aria-current="true"|aria-current="true"[^>]*data-nav="2"', detail), (
        "session detail highlights Sessions, the section it is opened from"
    )
    page_nav = re.search(r'<nav id="dash-nav".*?</nav>', detail, re.S)
    assert page_nav and 'aria-current="page"' not in page_nav.group(0), (
        "no page-nav link on a detail page claims to be the page the reader is on"
    )
    assert re.search(r'data-nav="2"[^>]*aria-current="page"|aria-current="page"[^>]*data-nav="2"', listing), (
        "the listing itself is the current page"
    )
    assert re.search(r'<nav class="crumbs".*?href="/dashboard/sessions"', detail, re.S), (
        "and the way back to the parent is a breadcrumb"
    )
