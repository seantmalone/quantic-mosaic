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
    assert "I can help with things like" in html_module.unescape(fragment.text)
    assert "See the full policy library" in fragment.text, "the rest of the library is a link now"


async def test_the_snapshot_date_is_stated_once_in_one_format(web):
    """`numbers-precision-overflow-12`: three date conventions on one screen, two of them ISO."""
    script, question, _ = CASES[0]
    async with web(script) as client:
        fragment = (await client.post("/chat", json={"message": question}, headers=HTMX)).text

    text = _visible_text(fragment)
    assert text.count("Based on employee data from 1 September 2026") == 1


#: The quoted corpus passage under each citation. The policy library says what it says — *"at least
#: 12 months of continuous service"* is the rule's own wording — and this guard judges what the app
#: writes, not what it quotes. Same exclusion, same reason, as `DEMO_PANEL` in the jargon file.
SOURCES = re.compile(r'<section class="sources">.*?</section>', re.S)

#: The snapshot date, in every form the surface could state it in. The footer states it once, in
#: the second form; a second occurrence — in any form — is the same fact twice on one screen.
SNAPSHOT_FORMS = (
    re.compile(r"\b2026-09-01\b"),
    re.compile(r"\b1 September 2026\b"),
    re.compile(r"\b1 Sept?\.? 2026\b"),
)
#: A tenure the reader has to divide to use: *"45 months of continuous service"*. The profile tool
#: returns `tenure` in words — *"3 years 9 months"* — for exactly this reason.
TENURE_IN_MONTHS = re.compile(r"\b\d{2,3} months\b")

#: The two scripts that carry an employee-data snapshot into an answered turn. `demo_task_2`'s
#: synthesis is on the far side of the confirmation gate, so its surface takes two requests.
SNAPSHOT_SCRIPTS = (
    ("demo_task_1.json", CASES[0][1], False),
    ("demo_task_2.json", CASES[1][1], True),
)


async def _answered_surface(web, script: str, question: str, *, through_confirmation: bool) -> str:
    """The rendered turn a reader ends up looking at, confirmation gate walked if there is one."""
    async with web(script) as client:
        fragment = await client.post("/chat", json={"message": question}, headers=HTMX)
        if not through_confirmation:
            return fragment.text
        ids = re.search(r'data-session-id="([0-9a-f]+)" *\n? *data-turn-id="([0-9a-f]+)"', fragment.text)
        assert ids, fragment.text[:400]
        done = await client.post(
            "/chat/confirm",
            json={"session_id": ids.group(1), "turn_id": ids.group(2), "decision": "confirmed"},
            headers=HTMX,
        )
    assert done.status_code == 200, done.text
    return done.text


@pytest.mark.parametrize(
    "script,question,through_confirmation", SNAPSHOT_SCRIPTS, ids=[s for s, _, _ in SNAPSHOT_SCRIPTS]
)
async def test_the_answer_states_no_iso_date_no_second_snapshot_and_no_tenure_in_months(
    web, script, question, through_confirmation
):
    """UX W6b — `npo2-08` / `npo2-13`, on the surface rather than in the prompt.

    W6 forbade all three at source (`synthesize.j2` rules 6 and 6b), and the sibling above was the
    guard that should have caught them reaching the page anyway. It could not: it counted the
    **footer's** sentence, asserted it appeared exactly once, and said nothing at all about what the
    answer above it said — so *"45 months of continuous service as of 2026-09-01"* sat six lines
    over *"Based on employee data from 1 September 2026"* and the suite stayed green. It also ran
    over one script, and `demo_task_2` carries the same defect past the confirmation gate.

    This one judges the whole rendered turn minus the quoted sources, over both demo scripts:

    a. no ISO date — chat speaks in `human_date()`'s words (`numbers-precision-overflow-12`);
    b. the snapshot date exactly once, in any format, and that once is the footer;
    c. no tenure in months — `lookup_employee_profile.tenure` is *"3 years 9 months"* for a reason.
    """
    page = SOURCES.sub("", await _answered_surface(web, script, question, through_confirmation=through_confirmation))
    text = _visible_text(page)

    assert not ISO_DATE.findall(text), f"{script}: the answer carries an ISO date — {ISO_DATE.findall(text)[:3]}"
    stated = [found for form in SNAPSHOT_FORMS for found in form.findall(text)]
    assert len(stated) == 1, f"{script}: the snapshot date is stated {len(stated)} times — {stated[:4]}"
    assert text.count("Based on employee data from 1 September 2026") == 1, f"{script}: the footer is where"
    months = TENURE_IN_MONTHS.findall(text)
    assert not months, f"{script}: a duration the reader has to divide — {months[:3]}"
