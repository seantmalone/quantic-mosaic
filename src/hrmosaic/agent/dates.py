"""Date consistency — an answer that shows its arithmetic has its arithmetic redone (UX W6, npo2-02).

**Not a guardrail.** Like `agent/outcome.py` and `agent/breadth.py` it emits no `guardrail` span and
carries no G-number: it is one deterministic step that runs after synthesis, on the blocks G2 and G3
have already repaired, and its whole job is to keep a computed deadline consistent with the
computation the answer prints beside it.

**The failure it exists for**, in the re-audit's own `chat-answer` capture: *"File the
work-from-another-country request in MosaicOne by 13 September 2026 (21 days before 3 November)"*.
3 November 2026 minus 21 days is 13 **October**. The same answer computed *"27 October 2026 (5
business days before departure)"* correctly, so it contradicted itself, and a reader acting on it
would have filed a month early. A wrong date in an HR answer is worse than no date.

The step is deliberately narrow, and the narrowness is the point:

1. **It only checks what the answer offers to have checked.** A deadline in bare prose — *"file it
   three weeks before you go"* — is model output nothing deterministic can verify. A parenthetical
   of the form *"(N days before <date>)"* is an arithmetic claim with both operands in it, and that
   is the only shape this step reads.
2. **It corrects rather than deletes** wherever there is a stated date to correct: the deadline is
   the useful half and the parenthetical is the working.
3. **It removes the claim only when there is nothing to correct** — a parenthetical beside no
   stated date at all asserts a relation the reader cannot check and this step cannot fix.
4. **It changes nothing it cannot resolve.** An anchor that is not a date (*"before departure"*), or
   a pair of dates with no year between them, leaves the sentence exactly as the model wrote it.

Real wall clock everywhere (constraint 6): no clock is read here at all. Both operands come out of
the sentence, so the step's answer does not depend on when it runs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

#: What the step is called where it is named — reports, the spec paragraph beside §7.4's table.
#: Deliberately not a `G<n>`: the six guardrails are a closed set.
STEP_NAME = "date_consistency"

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_MONTH_NUMBER = {name.lower(): number for number, name in enumerate(MONTHS, start=1)}

#: `13 September 2026`, `3 November`, `1st January 2027` — the vocabulary `web/api.py::human_date()`
#: writes and the one the models in this app have been observed to write back.
_DATE = r"\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+(?:\s+\d{4})?"

#: A stated deadline immediately followed by the working behind it. `\s*` and not a wider gap on
#: purpose: the two have to be adjacent for the parenthetical to be *about* that date.
PARENTHETICAL = re.compile(
    rf"(?:(?P<stated>{_DATE})\s*)?"
    r"\(\s*(?P<n>\d+)\s+(?:(?:business|working|calendar)\s+)?days?"
    r"\s+before\s+(?P<anchor>[^)]+?)\s*\)",
    re.IGNORECASE,
)

#: `(21 business days before …)` — the `business`/`working` qualifier can sit either side of the
#: count's noun depending on how the sentence was written, so both positions are read.
_BUSINESS = re.compile(r"\b(?:business|working)\b", re.IGNORECASE)


def human_date(value: date) -> str:
    """`date(2026, 10, 13)` → `13 October 2026` — the one date vocabulary the chat surface reads."""
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def parse_date(text: str, *, default_year: int | None = None) -> date | None:
    """`3 November` with a year to fall back on → `date(2026, 11, 3)`, or `None` for anything else."""
    match = re.fullmatch(r"\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)(?:\s+(\d{4}))?\s*", text)
    if match is None:
        return None
    month = _MONTH_NUMBER.get(match.group(2).lower())
    year = int(match.group(3)) if match.group(3) else default_year
    if month is None or year is None:
        return None
    try:
        return date(year, month, int(match.group(1)))
    except ValueError:
        return None


def minus_days(anchor: date, count: int, *, business: bool) -> date:
    """`count` days before `anchor` — calendar days, or working days skipping Saturday and Sunday."""
    if not business:
        return anchor - timedelta(days=count)
    moment, remaining = anchor, count
    while remaining > 0:
        moment -= timedelta(days=1)
        if moment.weekday() < 5:
            remaining -= 1
    return moment


def _repair(match: re.Match[str]) -> str | None:
    """What one parenthetical should become: `None` to leave the model's words exactly as they are,
    `""` to drop the claim, or the corrected deadline plus its working."""
    stated_text = match.group("stated")
    anchor_text = match.group("anchor")
    count = int(match.group("n"))
    business = bool(_BUSINESS.search(match.group(0)[: match.start("anchor") - match.start()]))

    stated = parse_date(stated_text) if stated_text else None
    anchor = parse_date(anchor_text, default_year=stated.year if stated else None)
    if anchor is None:
        # The anchor is not a date at all ("before departure"), or neither side carries a year:
        # there is no arithmetic to redo, so the model's sentence stands.
        return None
    if stated_text and stated is None:
        # "by 1 January (21 days before 3 November 2026)" — the year the deadline left out is
        # the one the anchor carries, which is the only year in the sentence.
        stated = parse_date(stated_text, default_year=anchor.year)
        if stated is None:
            return None

    if stated_text is None:
        # A parenthetical with no deadline in front of it states a relation the reader cannot
        # check and this step cannot correct. The claim goes; the sentence stays.
        return ""

    expected = minus_days(anchor, count, business=business)
    if stated == expected:
        return None
    working = match.group(0)[match.start("stated") - match.start() + len(stated_text) :]
    return f"{human_date(expected)}{working}"


def correct(text: str) -> str:
    r"""One passage with its arithmetic redone. Returns it unchanged when there is nothing to check.

    **Only the span a parenthetical occupies is rewritten.** The step used to finish by running
    `\s{2,}` → `" "` and `" ."` → `"."` over the *whole* string whenever anything in it changed —
    and `\s` matches a newline, so one corrected deadline in a multi-paragraph block flattened the
    block: paragraph breaks became spaces and every unrelated `" ."` in it was rewritten. That text
    is what is stored in `turns.final_answer` and `answer_blocks_json` and what `/chat` returns, so
    the record was rewritten too (UX W6, the fix round of the re-audit). Everything outside the
    spans below — line breaks included — now comes back byte for byte.
    """
    pieces: list[str] = []
    cursor = 0
    for match in PARENTHETICAL.finditer(text):
        replacement = _repair(match)
        if replacement is None:
            continue
        prefix = text[cursor : match.start()]
        if replacement == "":
            # Dropping the claim drops the space that introduced it — spaces and tabs only, because
            # a newline is structure this step has no business touching. A space is put back when
            # the removal would otherwise weld two words together.
            trimmed = prefix.rstrip(" \t")
            if trimmed != prefix and text[match.end() : match.end() + 1].isalnum():
                trimmed += " "
            pieces.append(trimmed)
        else:
            pieces.append(prefix)
            pieces.append(replacement)
        cursor = match.end()

    if not pieces:
        return text
    pieces.append(text[cursor:])
    return "".join(pieces)


@dataclass
class Outcome:
    """The blocks and next steps after the step, and how many sentences it rewrote."""

    blocks: list[dict[str, Any]]
    next_steps: list[str] = field(default_factory=list)
    #: How many strings the step changed, across the blocks and the steps together.
    corrected: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.corrected)


def apply(blocks: Sequence[Mapping[str, Any]], *, next_steps: Sequence[str] = ()) -> Outcome:
    """The pure rule, over everything `render_answer()` puts in front of one reader. Mutates nothing."""
    corrected = 0
    body: list[dict[str, Any]] = []
    for block in blocks:
        item = dict(block)
        before = str(item.get("text") or "")
        after = correct(before)
        if after != before:
            item["text"] = after
            corrected += 1
        body.append(item)

    steps: list[str] = []
    for step in next_steps:
        before = str(step)
        after = correct(before)
        corrected += after != before
        steps.append(after)
    return Outcome(blocks=body, next_steps=steps, corrected=corrected)


__all__ = [
    "MONTHS",
    "PARENTHETICAL",
    "STEP_NAME",
    "Outcome",
    "apply",
    "correct",
    "human_date",
    "minus_days",
    "parse_date",
]
