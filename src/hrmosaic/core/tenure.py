"""How long somebody has worked here, in the words a person uses (spec §8.4 tool 5).

`45` → `"3 years 9 months"`. The months are the record; this is how a reader hears it.

It lives in `core/` because two layers need the same arithmetic and neither may import the other:
`mcpserver/tools/lookup_employee_profile.py` publishes it on the profile envelope, and
`agent/snapshot.py` uses it to repair an answer that reached the reader's tenure through the
compliance engine instead — where there is a month count and no `tenure` string to quote
(W8, C22). Two copies of this would have drifted the moment one of them was corrected.
"""

from __future__ import annotations


def human_tenure(months: int | None) -> str | None:
    """`45` → `"3 years 9 months"`. `None` in, `None` out.

    Singular where the count is one, and the smaller unit dropped when it is zero — "3 years",
    never "3 years 0 months". Below a month there is no unit left to name, so it says so in words
    rather than printing a zero.
    """
    if months is None:
        return None
    if months <= 0:
        return "less than a month"
    years, remainder = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if remainder:
        parts.append(f"{remainder} month{'s' if remainder != 1 else ''}")
    return " ".join(parts)


__all__ = ["human_tenure"]
