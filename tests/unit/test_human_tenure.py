"""`lookup_employee_profile`'s human tenure phrasing (UX W5, owner decision).

The dataset carries `tenure_months_at_as_of`, an integer computed against the `as_of: 2026-09-01`
snapshot. The tool now carries the same fact in the words a person uses, beside it and never
instead of it, so the synthesis prompt's EMPLOYEE CONTEXT hands the model *"3 years 9 months"*
rather than `45` and an invitation to do arithmetic in prose.

What the phrasing owes a reader: the right singular, no unit that is zero, and no `0 months` for
somebody who started last week.
"""

from __future__ import annotations

import pytest

from hrmosaic.mcpserver.tools.lookup_employee_profile import human_tenure


@pytest.mark.parametrize(
    "months,expected",
    [
        (45, "3 years 9 months"),  # E1042, the demo persona
        (24, "2 years"),  # a whole number of years names no months
        (12, "1 year"),
        (13, "1 year 1 month"),
        (11, "11 months"),
        (1, "1 month"),
        (0, "less than a month"),
    ],
)
def test_the_months_are_said_the_way_a_person_says_them(months, expected):
    assert human_tenure(months) == expected


def test_a_missing_tenure_stays_missing():
    """`exclude_none=True` on the model dump: a record with no tenure carries no `tenure` key, and
    the string "None" must never reach the prompt."""
    assert human_tenure(None) is None


def test_a_negative_tenure_is_not_printed_as_a_negative_duration():
    """The generator cannot produce one, but an employee hired after the snapshot would — and
    "-2 years -1 months" is worse than saying nothing useful."""
    assert human_tenure(-3) == "less than a month"
