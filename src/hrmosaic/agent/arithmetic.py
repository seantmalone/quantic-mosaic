"""Arithmetic consistency — the numeric twin of `agent/dates.py` (spec §7.4; W8, C13).

**Not a guardrail.** No `guardrail` span, no G-number, no change to the six rules of §7.4. One
deterministic step after synthesis, reading the turn's `check_pto_balance` envelope and nothing
else.

**The failure it exists for**, live on 2026-09-15, persona E1007:

    engine   remaining_days 8.0  (13.5 accrued − 4.0 used − 1.5 pending + 0.0 carryover;
                                  the carryover expired on 31 March 2026)
    answer   "8.0 days … (13.5 accrued minus 4.0 used, plus 2.5 carryover)"

The total is the tool's and is right. The working beside it comes to **12.0**: it adds a carryover
the same sentence calls expired and silently drops the 1.5 pending days that actually produce the
figure. A reader who checks the arithmetic — which is exactly what showing the working invites —
finds the product contradicting itself.

`dates.py` already redoes a *date* the answer shows its working for. This does the same for a
number: where a sentence states a total and a parenthetical decomposition of it, the decomposition
is evaluated, and on a mismatch it is replaced by the envelope's own — `accrued − used − pending`,
with carryover only where there is unexpired carryover to add — or removed. **The total is never
touched**: it came from the tool and it is right.

One more rule, from the same exhibit: **an addend whose envelope counterpart is zero is
forbidden**, whether or not the sum happens to work out. `carryover_unexpired == 0.0` means there
is no carryover to add, and a decomposition that names one is describing somebody else's balance.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: What the step is called where it is named — reports, the spec paragraph beside §7.4's table.
#: Deliberately not a `G<n>`: the six guardrails are a closed set.
STEP_NAME = "arithmetic_consistency"

#: The tool whose result carries the decomposition's terms (§8.4 tool 6).
BALANCE_TOOL = "check_pto_balance"

#: How close two floats have to be to be the same number after a `0.5`-grained sum.
TOLERANCE = 0.001

#: The envelope field behind each word a decomposition uses for its terms. `carryover` resolves to
#: the **unexpired** carryover, because that is the only carryover the balance actually contains.
TERM_FIELDS: dict[str, str] = {
    "accrued": "accrued_ytd",
    "accrual": "accrued_ytd",
    "used": "used_ytd",
    "taken": "used_ytd",
    "pending": "pending_days",
    "carryover": "carryover_unexpired",
    "carried over": "carryover_unexpired",
    "carry-over": "carryover_unexpired",
    "rollover": "carryover_unexpired",
}

#: The order the envelope's own decomposition is written in, and the word each term is called by.
DECOMPOSITION_TERMS: tuple[tuple[str, str, str], ...] = (
    ("accrued_ytd", "accrued", "plus"),
    ("used_ytd", "used", "minus"),
    ("pending_days", "pending", "minus"),
    ("carryover_unexpired", "carried over", "plus"),
)

#: A stated total with a parenthetical decomposition of it directly after — *"8.0 days remaining
#: (13.5 accrued minus 4.0 used, plus 2.5 carryover)"*. The parenthetical must carry at least one
#: `plus`/`minus` between two numbers, or it is not a decomposition at all.
DECOMPOSITION = re.compile(
    r"(?P<total>\d+(?:\.\d+)?)(?P<between>[^.()]{0,60}?)"
    r"(?P<paren>\()\s*(?P<body>[^)]*?\d[^)]*?\b(?:plus|minus)\b[^)]*?\d[^)]*?)\s*\)",
    re.IGNORECASE,
)

#: One signed term of a decomposition: the operator that introduced it, the number, and the words
#: that name it up to the next operator.
_TERM = re.compile(
    r"(?P<sign>plus|minus|and)?\s*(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<label>(?:(?!\b(?:plus|minus|and)\b)[^,;])*)",
    re.IGNORECASE,
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _render(value: float) -> str:
    """`13.5` → `"13.5"`, `4.0` → `"4.0"` — the grain the balance tool publishes."""
    return f"{value:.1f}"


def balance(envelopes: Iterable[Any]) -> dict[str, Any] | None:
    """The turn's latest `check_pto_balance` body, or `None`.

    A body that will not parse contributes nothing rather than raising: like every step after
    synthesis, this one must never be the reason an answer fails to reach the reader.
    """
    found: dict[str, Any] | None = None
    for envelope in envelopes:
        if getattr(envelope, "name", "") != BALANCE_TOOL:
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        if isinstance(body, dict):
            found = body
    return found


def terms(body: str) -> list[tuple[float, str]]:
    """`"13.5 accrued minus 4.0 used, plus 2.5 carryover"` → `[(13.5, "accrued"), (-4.0, "used"), …]`.

    The first term is positive unless it was introduced by `minus`; `and` is a separator, not an
    operator, so *"13.5 accrued and 2.5 carryover"* adds.
    """
    found: list[tuple[float, str]] = []
    for match in _TERM.finditer(body):
        value = float(match["value"])
        sign = (match["sign"] or "").lower()
        found.append((-value if sign == "minus" else value, match["label"].strip().lower()))
    return found


def field_of(label: str) -> str | None:
    """Which envelope field a decomposition's term names, if any."""
    return next((field for word, field in TERM_FIELDS.items() if word in label), None)


def decomposition(body: Mapping[str, Any]) -> str | None:
    """The envelope's own working, or `None` when it does not reproduce the envelope's own total.

    `accrued − used − pending`, and carryover only where there is unexpired carryover to add. A
    zero term is left out rather than written as `minus 0.0`, which is arithmetic nobody says out
    loud.
    """
    total = _number(body.get("remaining_days"))
    if total is None:
        return None
    running = 0.0
    parts: list[str] = []
    for field_name, word, operator in DECOMPOSITION_TERMS:
        value = _number(body.get(field_name))
        if value is None or value == 0.0:
            continue
        running += value if operator == "plus" else -value
        if parts:
            parts.append(f"{operator} {_render(value)} {word}")
        else:
            parts.append(f"{_render(value)} {word}")
    if not parts or abs(running - total) > TOLERANCE:
        return None
    return " ".join(parts)


def _sound(stated_total: float, body: str, envelope: Mapping[str, Any]) -> bool:
    """Does this decomposition add up **and** name only terms the envelope actually carries?"""
    parsed = terms(body)
    if not parsed:
        return False
    if abs(sum(value for value, _label in parsed) - stated_total) > TOLERANCE:
        return False
    for value, label in parsed:
        field_name = field_of(label)
        if field_name is None:
            continue
        counterpart = _number(envelope.get(field_name))
        # An addend the envelope scores at zero is somebody else's balance (W8, C13).
        if counterpart == 0.0 and value != 0.0:
            return False
    return True


def correct(text: str, envelope: Mapping[str, Any] | None) -> str:
    """One passage with its arithmetic checked. Returns it unchanged when there is nothing to check.

    Only the span a parenthetical occupies is rewritten — the rule `dates.correct` learned the hard
    way at UX W6, when a whole-string clean-up flattened every paragraph of a repaired block.
    """
    if envelope is None:
        return text
    replacement = decomposition(envelope)
    pieces: list[str] = []
    cursor = 0
    for match in DECOMPOSITION.finditer(text):
        if _sound(float(match["total"]), match["body"], envelope):
            continue
        # Up to the parenthesis itself, wherever the body starts after it: "( 13.5 accrued …"
        # used to keep its "(" and gain a second one (W7-review Minor).
        pieces.append(text[cursor : match.start("paren")])
        if replacement is not None:
            pieces.append(f"({replacement})")
            cursor = match.end()
            continue
        # Nothing trustworthy to put in its place: the claim goes and the total stays. The space
        # that introduced the parenthetical goes with it — spaces and tabs only, never a newline.
        pieces[-1] = pieces[-1].rstrip(" \t")
        cursor = match.end()
    if not pieces:
        return text
    pieces.append(text[cursor:])
    return "".join(pieces)


@dataclass
class Outcome:
    """The blocks and next steps after the step, and how many strings it rewrote."""

    blocks: list[dict[str, Any]]
    next_steps: list[str] = field(default_factory=list)
    #: How many strings the step changed, across the blocks and the steps together — the same
    #: count `dates.Outcome` keeps, for the same reason: it is what a report of this step says.
    corrected: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.corrected)


def apply(
    blocks: Sequence[Mapping[str, Any]],
    envelopes: Iterable[Any],
    *,
    next_steps: Sequence[str] = (),
) -> Outcome:
    """The pure rule, over everything `render_answer()` puts in front of one reader. Mutates nothing."""
    envelope = balance(envelopes)
    corrected = 0
    body: list[dict[str, Any]] = []
    for block in blocks:
        item = dict(block)
        before = str(item.get("text") or "")
        after = correct(before, envelope)
        if after != before:
            item["text"] = after
            corrected += 1
        body.append(item)

    steps: list[str] = []
    for step in next_steps:
        before = str(step)
        after = correct(before, envelope)
        corrected += after != before
        steps.append(after)
    return Outcome(blocks=body, next_steps=steps, corrected=corrected)


__all__ = [
    "BALANCE_TOOL",
    "DECOMPOSITION",
    "DECOMPOSITION_TERMS",
    "STEP_NAME",
    "TERM_FIELDS",
    "TOLERANCE",
    "Outcome",
    "apply",
    "balance",
    "correct",
    "decomposition",
    "field_of",
    "terms",
]
