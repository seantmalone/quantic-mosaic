"""The two demo prompts are dated against the day they are read (W8, C04).

They were two frozen strings, which was right while the rules engine measured notice from the mock
data's own `as_of: 2026-09-01`. It does not any more: notice is measured from the **submission
date**, so §18.2's "three days of PTO from Tuesday 15 September" is a request with zero business
days' notice on any run after that week — the engine scores its own demo `unmet` on the notice
requirement, and the headline path demonstrates a policy failure instead of the confirmation gate.

The dates move on the page. The shell scripts keep the recorded wording as the fallback they send
when the instance cannot be read, and `make demo1` / `make demo2` run against `MOCK_TODAY=2026-09-01`,
so the two have to agree byte for byte — the test below parses the scripts, because the first version
of it compared `DEMO_PROMPTS` with its own definition and `make demo2` shipped two business days of
notice past it (W8 fix round, Critical 2).

What a run normally sends is the **served** prompt: the scripts ask the page for it, so the dates are
the server's own (gap 7). `tests/contract/test_demo_scripts_send_the_served_prompt.py` owns that half
against a running instance; the two tests at the bottom own the scripts' side of it as text.

The questions, the personas and the two capabilities they show do not move.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from hrmosaic.agent.dates import MONTHS
from hrmosaic.mcpserver.rules import business_days_between
from hrmosaic.web import api
from scripts import demo_prompt

#: Every starting day over four months, so no run of the demo is on a day the prompt is wrong
#: for — including the two holiday-dense weeks the second-week formula alone gets wrong.
DAYS = [date(2026, 9, 1) + timedelta(days=offset) for offset in range(0, 130)]

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

#: `PROMPT='…'` as the two POSIX scripts write it: single-quoted, one line, no escapes.
PROMPT_LINE = re.compile(r"^PROMPT='(.+)'$", re.MULTILINE)

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
    """Counted the way the engine counts it — in the demo persona's own holiday calendar. The
    second-week formula alone gives four business days on six days around Thanksgiving and
    Christmas (W7-review Minor), and the prompt rolls a week on exactly those."""
    start, end = _dates(api.demo_prompts(today)["demo_2"])

    assert business_days_between(today, start, api._demo_holidays()) >= STANDARD_NOTICE
    assert business_days_between(today, start, frozenset()) >= STANDARD_NOTICE
    assert (end - start).days == 2, "three days, Tuesday to Thursday"
    assert start.weekday() == 1 and end.weekday() == 3


def test_the_holiday_calendar_is_the_demo_personas_own():
    assert date(2026, 9, 7) in api._demo_holidays(), "Labor Day, observed in Boston"
    assert date(2026, 11, 26) in api._demo_holidays()


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


def _script_prompt(name: str) -> str:
    match = PROMPT_LINE.search((SCRIPTS / name).read_text(encoding="utf-8"))
    assert match, f"{name} no longer carries a one-line PROMPT='…'"
    return match.group(1)


def test_the_recorded_pair_is_byte_for_byte_what_the_shell_scripts_send():
    """`make demo1` / `make demo2` send the scripts' own wording against `MOCK_TODAY=2026-09-01`,
    and `DEMO_PROMPTS` claims to be that pair. Parsed out of the scripts, not out of its own
    definition — the tautological version of this test let `make demo2` ship a request with two
    business days of notice (W8 fix round, Critical 2)."""
    assert api.DEMO_PROMPTS["demo_1"] == _script_prompt("demo_task_1.sh")
    assert api.DEMO_PROMPTS["demo_2"] == _script_prompt("demo_task_2.sh")
    assert set(api.DEMO_PROMPTS) == set(api.DEMO_PROMPT_LABELS)


def test_the_recorded_date_gives_the_recorded_notice():
    """Eight business days from `RECORDED_TODAY` to the scripts' 15 September, holidays excluded —
    the figure the recorded demo-2 synthesis and `docs/demo-script.md` both state."""
    start, _end = _dates(api.DEMO_PROMPTS["demo_2"])
    assert start == date(2026, 9, 15)
    assert business_days_between(api.RECORDED_TODAY, start, api._demo_holidays()) == 8


#: `scripts/demo_prompt.py --base-url … --key demo_N`, as the two POSIX scripts invoke it.
HELPER_CALL = 'demo_prompt.py" --base-url "$BASE_URL" --key demo_'


@pytest.mark.parametrize("index", (1, 2))
def test_each_script_asks_the_server_for_its_own_prompt(index: int):
    """The fix for gap 7, as the script reads: the served prompt is what gets sent, the key is this
    script's own — demo_task_2.sh asking for `demo_1` would run the PTO demo on the Berlin question
    and fail nowhere near the cause — and a page it cannot read ends the run."""
    script = (SCRIPTS / f"demo_task_{index}.sh").read_text(encoding="utf-8")

    assert f'elif ! PROMPT="$("$PYTHON" "$(dirname "$0")/{HELPER_CALL}{index})"; then' in script
    assert script.index("PROMPT='") < script.index(HELPER_CALL), "the recorded line is only the opt-in"
    assert "exit 1" in script.split(HELPER_CALL, 1)[1], "an unreadable page is a failed run"


@pytest.mark.parametrize("index", (1, 2))
def test_the_recorded_wording_is_opt_in_and_never_a_silent_downgrade(index: int):
    """Fix round 1, Important 1. A script that fell back on its own sent September dates to the
    deployed service and reported a green demo — which is what the frozen prompt cost in the first
    place. So the frozen wording needs `--recorded` (or `DEMO_RECORDED=1`) and says so when used."""
    script = (SCRIPTS / f"demo_task_{index}.sh").read_text(encoding="utf-8")

    assert 'RECORDED="${DEMO_RECORDED:-0}"' in script
    assert '[ "${1:-}" = "--recorded" ]' in script
    assert "--recorded: sending the wording the stub script was recorded against" in script
    assert "|| true" not in script.split("set -eu", 1)[1], "no command in this script may swallow a failure"


def test_an_unreachable_instance_is_a_loud_failure(capsys):
    """`demo_prompt.py` exits 1 with a reason on stderr and nothing on stdout, which is what makes
    the caller's `set -e` end the run instead of sending the recorded dates."""
    status = demo_prompt.main(["--base-url", "http://127.0.0.1:1", "--key", "demo_1", "--timeout", "0"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == "", "nothing on stdout is what the scripts read"
    assert "could not read demo_1 from http://127.0.0.1:1/" in captured.err


def test_a_base_url_with_no_scheme_is_reported_at_once(capsys):
    """Fix round 2. `urlopen` reports a missing `http://` as `URLError("unknown url type")`, which
    the retry loop would have sat on for its whole 120 s budget before blaming the network for a
    typo. The default timeout is deliberately left in place here: the guard is what makes it fast."""
    status = demo_prompt.main(["--base-url", "127.0.0.1:8000", "--key", "demo_1"])

    assert status == 1
    assert "is not an http(s) URL" in capsys.readouterr().err


def test_the_key_is_required(capsys):
    """Fix round 1, Minor 4: it defaulted to `demo_1`, so a forgotten flag ran the wrong demo."""
    with pytest.raises(SystemExit) as refused:
        demo_prompt.main(["--base-url", "http://127.0.0.1:1"])

    assert refused.value.code == 2
    assert "--key" in capsys.readouterr().err
