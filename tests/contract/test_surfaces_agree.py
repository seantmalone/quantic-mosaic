"""**P9 — a summary agrees with its detail**, across surfaces (UX W6).

The re-audit's own §4 lists four cross-surface disagreements and every one of them is between two
pages the plan built in the same wave, from the same store, to say the same thing:

* the Overview Traffic tile read **"5 / QUESTIONS ANSWERED"** over a figure that counts *turns* —
  the same 5 the error-rate tile three places right uses as the denominator of "1 of 5 turns" —
  while `/dashboard/turns` listed two of the five as answered (npo2-03 = dr-new-2);
* the designed confirmation pause read *"paused for confirmation"* on `/dashboard/tools` and
  **"create_mock_hr_ticket failed"** in a red chip on the session waterfall, which is the page the
  chat deep link lands on (dr-new-3).

A per-page test cannot see any of this: each page is internally consistent and the defect is the
pair. So this file asks the one store two questions and requires one answer, and it does it through
the rendered HTML rather than the view models, because the label is half of the claim.

`tests/contract/test_demo_controls_are_quarantined.py` owns the third pair (the demo panel's
safety-check count against the six rules, JX-R7), because that sentence is the panel's.
"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.anyio

HTMX = {"HX-Request": "true"}
DEMO_2 = (
    "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
    "— and can you open the request for me?"
)

#: `<span class="kpi-value">5</span> … <span class="kpi-label">Questions asked</span>` — the tile's
#: figure and the name it goes by, read out of the element that carries its `data-kpi` hook.
TILE = re.compile(
    r'data-kpi="(?P<key>[a-z0-9_]+)"[^>]*>\s*<span class="kpi-value">(?P<value>[^<]*)</span>\s*'
    r'<span class="kpi-label">(?P<label>[^<]*)</span>',
    re.DOTALL,
)


def _tiles(html: str) -> dict[str, dict[str, str]]:
    return {
        match.group("key"): {"value": match.group("value").strip(), "label": match.group("label").strip()}
        for match in TILE.finditer(html)
    }


async def test_the_traffic_tile_counts_turns_says_turns_and_agrees_with_the_turns_page(web):
    """npo2-03 = dr-new-2. Three surfaces, one figure: the tile, its own error-rate neighbour, and
    the page that lists the turns the tile is counting."""
    async with web("rag_only.json") as client:
        first = await client.post("/chat", json={"message": "How much PTO do I accrue each month?"})
        assert first.status_code == 200, first.text

        overview = (await client.get("/dashboard")).text
        turns_page = (await client.get("/dashboard/turns")).text
        api = (await client.get("/api/traces/overview")).json()

    tiles = _tiles(overview)
    assert tiles["turns"]["label"] == "Questions asked", "the tile names the thing it counts"
    assert tiles["turns"]["value"] == str(api["kpis"]["turns"])

    # The error-rate tile's denominator is the same figure, said the same way.
    assert f"{api['kpis']['turns']} turn" in " ".join(overview.split())

    # …and the answered sub-line is a *different* figure, stated as a share of that same total.
    squashed = " ".join(overview.split())
    assert f"{api['kpis']['answered_turns']} of {api['kpis']['turns']} turn" in squashed
    assert api["kpis"]["answered_turns"] <= api["kpis"]["turns"]

    # The turns page lists exactly as many rows as the tile counts.
    rows = turns_page.count('<td data-col="turn_id"')
    assert rows == api["kpis"]["turns"], f"the tile says {api['kpis']['turns']} and the page lists {rows}"


async def test_a_write_held_at_the_gate_is_paused_on_both_pages_and_failed_on_neither(web):
    """dr-new-3. `/dashboard/tools` has called this the designed pause since W4; the waterfall —
    the page the chat deep link lands on — called the same span a failure, in red."""
    async with web("demo_task_2.json") as client:
        card = await client.post("/chat", json={"message": DEMO_2}, headers=HTMX)
        assert card.status_code == 200, card.text
        session_id = re.search(r'data-session-id="([0-9a-f]+)"', card.text).group(1)

        tools = (await client.get("/dashboard/tools")).text
        waterfall = (await client.get(f"/dashboard/sessions/{session_id}")).text

    assert "paused for confirmation" in tools, "the Tools page says what the gate did"
    assert "paused for confirmation" in waterfall, "and so does the waterfall"
    rows = re.sub(r"<pre\b.*?</pre>", "", waterfall, flags=re.S)
    assert "failed" not in " ".join(rows.split()).split('<ol class="waterfall">', 1)[1]
    assert 'data-status="paused"' in waterfall, "the row is the designed pause, not an error"


async def test_no_page_prints_a_confirmation_code_where_a_word_belongs(web):
    """The same fact, once, in words: `CONFIRMATION_REQUIRED` under a column headed ERROR CODE on a
    row whose OUTCOME says `paused` is the enum reaching a reader beside its own translation."""
    async with web("demo_task_2.json") as client:
        card = await client.post("/chat", json={"message": DEMO_2}, headers=HTMX)
        assert card.status_code == 200, card.text
        session_id = re.search(r'data-session-id="([0-9a-f]+)"', card.text).group(1)
        waterfall = (await client.get(f"/dashboard/sessions/{session_id}")).text

    # The record keeps it — the span payload is a disclosure on the page and `/api/*` is unchanged
    # (P15) — but the row a reader scans says it in words. The payloads are cut out first: since
    # UX W7 the disclosure is the first thing in a row, so a slice at the summary would read them.
    rows = re.sub(r"<pre\b.*?</pre>", "", waterfall, flags=re.S)
    assert "CONFIRMATION_REQUIRED" not in rows.split('<ol class="waterfall">', 1)[1]


async def test_the_panel_sentence_and_the_session_tile_count_the_same_safety_checks(web):
    """npo3-04 = dgc-r2-2 (UX W7). For one turn the panel said "5 of 5 safety checks passed", the
    session card it links to said "GUARDRAIL CHECKS 7" and the Guardrails page "The six safety
    checks" — three numbers for one idea, one click apart. Both surfaces now say the rules that
    applied out of the six, computed by `api.safety_checks` from the turn's spans, and the tile adds
    the spans that ran as a third, separately named figure."""
    async with web("demo_task_1.json") as client:
        turn = await client.post(
            "/chat",
            json={"message": "I want to work from Berlin from 3 November to 14 December 2026 — can I?"},
            headers=HTMX,
        )
        assert turn.status_code == 200, turn.text
        session_id = re.search(r'data-session-id="([0-9a-f]+)"', turn.text).group(1)
        waterfall = (await client.get(f"/dashboard/sessions/{session_id}")).text
        guardrails = (await client.get("/dashboard/safety")).text

    produced = re.search(r'data-produced="([^"]+)"', turn.text).group(1)
    panel = re.search(
        r"(\d+) of the (\d+) safety checks applied to this answer; (?:all (\d+)|(\d+) of the \d+) passed", produced
    )
    assert panel, produced
    tile = re.search(r"Safety checks</dt><dd>\s*(\d+) of (\d+) applied ·\s*(\d+) checks? run", waterfall)
    assert tile, "the session tile states the same two figures"
    assert (panel.group(1), panel.group(2)) == (tile.group(1), tile.group(2)) == (tile.group(1), "6")
    assert int(tile.group(3)) >= int(tile.group(1)), "spans run are at least the rules that applied"
    assert "The six safety checks" in guardrails, "…and the Guardrails page names the same six"
