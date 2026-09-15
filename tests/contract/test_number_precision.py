"""**P1**: no number on the chat surface carries more digits than its purpose supports.

`docs/superpowers/plans/2026-09-14-ux-remediation-plan.md` §1 P1, and the three findings behind it
(`numbers-precision-overflow-3`, `-12`, `-22`): a cosine threshold inside a refusal sentence
(*"max dense score 0.583 < 0.60"*), `0.7612` beside `0.774` in a trace panel, `1176→121 tok`, and
`0 ms` on 16 of 28 rows — all on the page a person reads, none of it rounded, none of it useful
there.

The rule is mechanical and deliberately narrow: **four or more decimal places is never a human
number**, and money never carries more than two. The dashboard half of this principle turns on at
W4, where the shared formatters are fixed; this file is the chat half, and it also holds the one
date convention chat is allowed to speak in (`numbers-precision-overflow-12`: three formats on one
screen, two of them ISO).

Every precise value still exists on the dashboard and in `/api/*` — P15 is the principle that the
technical record is relocated, never destroyed, and `test_dashboard_viewmodels.py` is where it is
asserted.
"""

from __future__ import annotations

import html as html_module
import re

import pytest

from tests.contract.test_chat_has_no_jargon import CASES, _visible_text

pytestmark = pytest.mark.anyio

HTMX = {"HX-Request": "true"}

#: Four decimal places or more — a stored score, never a sentence.
MACHINE_PRECISION = re.compile(r"\d+\.\d{4,}")
#: Money with more than two decimal places.
MACHINE_MONEY = re.compile(r"\$\d+\.\d{3,}")
#: `2026-09-01`. Chat says *1 September 2026*, once, through `api.human_date()`.
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _numbers_are_human(page: str, *, where: str) -> None:
    text = _visible_text(page)
    assert not MACHINE_PRECISION.findall(text), f"{where}: {MACHINE_PRECISION.findall(text)[:3]}"
    assert not MACHINE_MONEY.findall(text), f"{where}: {MACHINE_MONEY.findall(text)[:3]}"


async def test_the_chat_page_at_rest_shows_no_machine_precision(web):
    async with web() as client:
        page = (await client.get("/")).text

    _numbers_are_human(page, where="GET / at rest")
    assert not ISO_DATE.findall(_visible_text(page)), "the snapshot date left with the rail's footer"


@pytest.mark.parametrize("script,question,state", CASES, ids=[state for _, _, state in CASES])
async def test_no_turn_state_prints_a_stored_score_or_a_fractional_cent(web, script, question, state):
    async with web(script) as client:
        fragment = (await client.post("/chat", json={"message": question}, headers=HTMX)).text

    _numbers_are_human(fragment, where=f"a {state} turn from {script}")


async def test_the_refusal_states_the_boundary_and_not_the_threshold_that_measured_it(web):
    """`numbers-precision-overflow-3`: `0.583 < 0.60` used to be inside the refusal sentence."""
    script, question, _ = CASES[2]
    # Two servers, because the stub script holds exactly the calls one turn makes.
    async with web(script) as client:
        fragment = await client.post("/chat", json={"message": question}, headers=HTMX)
    async with web(script) as client:
        payload = (await client.post("/chat", json={"message": question})).json()

    text = _visible_text(fragment.text)
    assert "I could not find anything in Mosaic's policy library" in text
    assert "dense" not in text.lower() and "threshold" not in text.lower()
    assert not re.findall(r"\b0\.\d+\b", text), "no bare probability in a sentence"

    # …and the redirect it builds is now rendered rather than silently dropped
    # (jargon-and-exposure-3). The scores themselves are on the G1 span, which is the record.
    assert payload["next_steps"], "a refusal carries its redirect"
    assert "I can help with:" in html_module.unescape(fragment.text)


async def test_the_snapshot_date_is_stated_once_in_one_format(web):
    """`numbers-precision-overflow-12`: three date conventions on one screen, two of them ISO."""
    script, question, _ = CASES[0]
    async with web(script) as client:
        fragment = (await client.post("/chat", json={"message": question}, headers=HTMX)).text

    text = _visible_text(fragment)
    assert text.count("Based on employee data from 1 September 2026") == 1
