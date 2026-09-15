"""The two demo prompts are dated against the day they are read (W8, C04).

They were two frozen strings, which was right while the rules engine measured notice from the mock
data's own `as_of: 2026-09-01`. It does not any more: notice is measured from the **submission
date**, so §18.2's "three days of PTO from Tuesday 15 September" is a request with zero business
days' notice on any run after that week — the engine scores its own demo `unmet` on the notice
requirement, and the headline path demonstrates a policy failure instead of the confirmation gate.

The dates move. The questions, the personas and the two capabilities they show do not.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from hrmosaic.agent.dates import MONTHS
from hrmosaic.mcpserver.rules import business_days_between
from hrmosaic.web import api

#: Every Monday-to-Sunday starting day, over three months, so no run of the demo is on a day the
#: prompt is wrong for.
DAYS = [date(2026, 9, 1) + timedelta(days=offset) for offset in range(0, 120, 3)]

#: `pto.notice.standard_days` — what §18.2's request has to give.
STANDARD_NOTICE = 5

#: `remote.international.manager_notice_days` — what §18.1's trip has to give.
INTERNATIONAL_NOTICE = 21

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _dates(text: str) -> list[date]:
    """Every `3 November 2026` / `3 November` in a prompt, as dates.

    A span writes its year once, at the end — *"from 30 November to 10 January 2027"* — so the
    year is read right to left, and a date that would land **after** the one following it belongs
    to the year before. Without that, a trip over the new year parses as a trip backwards in time.
    """
    found: list[tuple[str, str, str]] = re.findall(rf"(\d{{1,2}}) ({'|'.join(MONTHS)})( \d{{4}})?", text)
    parsed: list[date] = []
    for day, month, stated in reversed(found):
        year = int(stated) if stated.strip() else (parsed[0].year if parsed else 2026)
        moment = date(year, MONTHS.index(month) + 1, int(day))
        if parsed and moment > parsed[0]:
            moment = moment.replace(year=year - 1)
        parsed.insert(0, moment)
    return parsed


@pytest.mark.parametrize("today", DAYS, ids=lambda value: value.isoformat())
def test_the_pto_prompt_always_gives_the_notice_the_policy_asks_for(today):
    start, end = _dates(api.demo_prompts(today)["demo_2"])

    assert business_days_between(today, start, frozenset()) >= STANDARD_NOTICE
    assert (end - start).days == 2, "three days, Tuesday to Thursday"
    assert start.weekday() == 1 and end.weekday() == 3


@pytest.mark.parametrize("today", DAYS, ids=lambda value: value.isoformat())
def test_the_pto_prompt_names_the_weekday_the_date_actually_is(today):
    text = api.demo_prompts(today)["demo_2"]
    start, end = _dates(text)

    assert f"{WEEKDAYS[start.weekday()]} {start.day} {MONTHS[start.month - 1]}" in text
    assert f"{WEEKDAYS[end.weekday()]} {end.day} {MONTHS[end.month - 1]}" in text


@pytest.mark.parametrize("today", DAYS, ids=lambda value: value.isoformat())
def test_the_berlin_prompt_always_gives_twenty_one_days_notice(today):
    start, end = _dates(api.demo_prompts(today)["demo_1"])

    assert (start - today).days >= INTERNATIONAL_NOTICE
    assert (end - start).days > 30, "the trip is still long enough to need Tax & Legal review"


def test_the_berlin_prompt_keeps_the_spec_dates_while_they_still_work():
    """§18.1 names 3 November – 14 December 2026, and nothing moves while that is far enough off."""
    assert api.demo_prompts(date(2026, 9, 10))["demo_1"] == (
        "I want to work from Berlin from 3 November to 14 December 2026 — can I?"
    )
    assert api.demo_prompts(date(2026, 10, 13))["demo_1"] == (
        "I want to work from Berlin from 3 November to 14 December 2026 — can I?"
    )


def test_the_berlin_prompt_rolls_to_a_monday_once_the_spec_dates_are_too_close():
    rolled = api.demo_prompts(date(2026, 10, 20))["demo_1"]
    start, _end = _dates(rolled)

    assert start.weekday() == 0, "a trip starts on a Monday"
    assert "3 November" not in rolled


def test_the_recorded_pair_is_what_the_shell_scripts_send():
    """`scripts/demo_task_*.sh` carry their own fixed wording, and the stubs were recorded against
    it with `MOCK_TODAY=2026-09-10`. `DEMO_PROMPTS` is that pair, and stays reachable."""
    assert api.DEMO_PROMPTS == api.demo_prompts(api.RECORDED_TODAY)
    assert set(api.DEMO_PROMPTS) == set(api.DEMO_PROMPT_LABELS)
