"""Snapshot consistency — the data snapshot is stated once, by the page, and never by the answer.

**Not a guardrail.** Like `agent/outcome.py`, `agent/dates.py` and `agent/breadth.py` it emits no
`guardrail` span and carries no G-number: it is one deterministic step that runs after synthesis,
on the blocks G2, G3 and the two steps before it have already repaired, and its whole job is to
stop the answer restating two facts the surface already states better than it can.

**The failures it exists for**, both on the live path on 2026-09-15 and both npo2-08 / npo2-13, the
numbers-precision lens:

1. *"Your PTO balance as of 1 September 2026 is 13.5 days remaining…"* (demo 2) and *"You have
   completed 45 months of continuous service as of 1 September 2026, which exceeds…"* (demo 1),
   printed above the chat surface's own footer, *"Based on employee data from 1 September 2026"*.
   One screen, one fact, two statements of it — and in demo 1's earlier capture the answer said it
   in ISO. The footer is the right place: it is stated once, for the whole answer, in the one date
   vocabulary chat speaks (`web/api.py::human_date()`).
2. *"45 months of continuous service"*. `lookup_employee_profile` returns `tenure_months_at_as_of`
   for arithmetic and `tenure` — *"3 years 9 months"* — for people, and a reader who has to divide
   by twelve to know whether they qualify has been handed the machine's copy.

`synthesize.j2` rules 6 and 6b already tell the model both things, and the model obeys them most of
the time: the 17:54 run of demo 1 wrote *"3 years 9 months"* with no date at all. **Most of the
time is what a prompt buys**, which is why the two live turns of 18:34 said it the other way and
why this step exists — the prompt asks, the step makes it true.

Four clauses bound it, and the narrowness is the point:

1. **It only deletes a date the tools themselves put in the envelope.** Every `as_of` on this
   turn's tool results is collected first; a date that is not one of them is somebody else's fact —
   a deadline (*"by 13 October 2026"*), a start date, a blackout — and is never touched.
2. **It deletes the restatement, not the sentence.** The `as of <date>` phrase goes with the
   parentheses or the comma that introduced it and the seam is closed, so the sentence reads as if
   it had never carried the date: *"…service as of 1 September 2026, which exceeds"* → *"…service,
   which exceeds"*.
3. **A tenure in months becomes the profile's own words, and only where it is that employee's
   tenure.** `N months` is rewritten only for an `N` a profile envelope actually reported, only
   from 13 months up — under a year *"9 months"* is already how a person says it — and never where
   the text is quoting a policy threshold (*"at least 12 months"*, *"requires 45 months"*), which
   is the rule's own wording and not this employee's record.
4. **It runs on the blocks and the next steps, and on nothing else.** `rationale_summary` is §9.7's
   hidden reasoning and never reaches a reader; the `llm_call` span keeps what the model actually
   emitted, verbatim, because the record of a model's output is not something a later step may
   edit (the same rule that stopped `dates.correct` rewriting whole strings).

Real wall clock nowhere (constraint 6): every date this step acts on comes out of a tool envelope,
so what it does depends on the turn and never on when the turn ran.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hrmosaic.core.tenure import human_tenure

#: What the step is called where it is named — reports, the spec paragraph beside §7.4's table.
#: Deliberately not a `G<n>`: the six guardrails are a closed set.
STEP_NAME = "snapshot_consistency"

#: The tool whose result carries an employee's tenure in both forms (§8.4 tool 2). Kept as the name
#: of the canonical source; since W8 (C22) the pair is read from **any** envelope that reports it.
PROFILE_TOOL = "lookup_employee_profile"

#: The field that carries a tenure in months, wherever an envelope puts it — top level on the
#: profile result, inside `computed` on a compliance verdict.
TENURE_MONTHS_FIELD = "tenure_months_at_as_of"

#: Below this, months *are* the human unit: *"9 months of continuous service"* needs no translation
#: and `tenure` would say the same thing back. At and above it the reader is doing division.
TENURE_FLOOR = 13

#: `N months` right after one of these is the **rule's** threshold, not the **employee's** service:
#: "at least 12 months", "requires 45 months of continuous service". Rewriting those would change
#: what the policy says, which is the one thing no post-synthesis step may do.
THRESHOLD_WORDS = ("at least", "minimum", "required", "requires", "need", "needs")

#: How far back a threshold word counts. Long enough for "requires a minimum of 45 months", short
#: enough that an unrelated "required" earlier in the sentence is not read as governing this match.
THRESHOLD_WINDOW = 20

_MONTHS = (
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

#: An ISO snapshot date, which is the only shape an `as_of` field takes (§8.4's output schemas).
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: A comma this step's cut has orphaned at the head of a clause.
_ORPHAN_COMMA = re.compile(r"^,[ \t]*")
#: The `(` … `)` a restatement may be parenthesised in, read against the text either side of it.
_OPEN = re.compile(r"[ \t]*[(\[][ \t]*$")
_CLOSE = re.compile(r"^[ \t]*[)\]]")
#: The comma that introduced it, and the one that closed it.
_LEAD_COMMA = re.compile(r"[ \t]*,[ \t]*$")
_FOLLOW_COMMA = re.compile(r"^[ \t]*,[ \t]*")
#: …and the words that make the second comma the sentence's rather than the phrase's. *"13.5 days
#: remaining, as of 1 September 2026, which covers"* needs that comma; *"your balance, as of
#: 1 September 2026, is 13.5"* does not, and would be left reading *"your balance, is 13.5"*.
_OPENS_A_CLAUSE = re.compile(r"(?:which|who|whom|that|and|but|so|or|while|although|though|because)\b", re.IGNORECASE)


def variants(as_of: str) -> tuple[str, ...]:
    """Every way the one snapshot date has been observed written, ISO first.

    `2026-09-01` → the ISO string itself, `1 September 2026`, `September 1, 2026`,
    `September 1 2026`, `1 Sept 2026`, `1 Sep 2026`, `Sept 1, 2026`, `Sep 1, 2026` (each
    abbreviation with an optional full stop) and `01 September 2026`. The surface writes exactly
    one of them (`human_date()`); the model has been recorded writing the ISO one and the
    American ones, and the step reads them all because the sentence it is repairing is the
    model's, not the surface's. `_phrase()` orders them for the alternation.
    """
    year, month, day = (int(part) for part in as_of.split("-"))
    name = _MONTHS[month - 1]
    # `Sept` is September's own four-letter abbreviation; every other month stops at three.
    abbreviations = ("Sept", "Sep") if month == 9 else (name[:3],)
    forms = [as_of, f"{day} {name} {year}", f"{name} {day}, {year}", f"{name} {day} {year}"]
    for abbreviation in abbreviations:
        forms += [
            f"{day} {abbreviation} {year}",
            f"{abbreviation} {day}, {year}",
            f"{day} {abbreviation}. {year}",
            f"{abbreviation}. {day}, {year}",
        ]
    forms.append(f"{day:02d} {name} {year}")
    return tuple(dict.fromkeys(forms))


def _phrase(dates: Sequence[str]) -> re.Pattern[str] | None:
    """`as of <any variant of any snapshot date>`, or `None` when the turn carried no `as_of`."""
    forms = [form for date in dates for form in variants(date)]
    if not forms:
        return None
    alternatives = "|".join(re.escape(form).replace(r"\ ", r"\s+") for form in sorted(forms, key=len, reverse=True))
    return re.compile(rf"\bas\s+(?:of|at)\s+(?:{alternatives})", re.IGNORECASE)


def snapshot_dates(envelopes: Iterable[Any]) -> list[str]:
    """Every ISO `as_of` this turn's tool results carried, in order, without repeats.

    A body that will not parse, or that carries no `as_of`, contributes nothing rather than
    raising: like every step after synthesis, this one must never be the reason an answer fails to
    reach the reader.
    """
    found: list[str] = []
    for body in _bodies(envelopes):
        as_of = body.get("as_of")
        if isinstance(as_of, str) and ISO.match(as_of) and as_of not in found:
            found.append(as_of)
    return found


def _months_reported(node: Any) -> Iterator[int]:
    """Every `tenure_months_at_as_of` an envelope body carries, however deeply nested (W8, C22)."""
    if isinstance(node, dict):
        value = node.get(TENURE_MONTHS_FIELD)
        # `bool` is an `int` in Python and `True` is not a tenure.
        if isinstance(value, int) and not isinstance(value, bool):
            yield value
        for child in node.values():
            yield from _months_reported(child)
    elif isinstance(node, list):
        for child in node:
            yield from _months_reported(child)


def tenures(envelopes: Iterable[Any]) -> list[tuple[int, str]]:
    """`(45, "3 years 9 months")` for every envelope that reported a tenure, without repeats.

    **Any envelope, not only the profile tool's** (W8, C22). Whether the reader's tenure arrived as
    words or as a raw month count depended only on whether the model happened to call
    `lookup_employee_profile`: a turn that established tenure through the compliance engine had no
    profile envelope, so nothing rewrote *"45 months of continuous service"* — the same persona, on
    the same build, got *"3 years 9 months"* on the turn that did call it. The engine now reports
    `computed.tenure_months_at_as_of`, and where an envelope carries the count without the words
    the words are computed from it by the one implementation both layers share.
    """
    found: list[tuple[int, str]] = []
    for body in _bodies(envelopes):
        stated = body.get("tenure")
        for months in _months_reported(body):
            words = stated.strip() if isinstance(stated, str) and stated.strip() else human_tenure(months)
            if not words:
                continue
            pair = (months, words)
            if pair not in found:
                found.append(pair)
    return found


def _bodies(envelopes: Iterable[Any], *, tool: str | None = None) -> list[dict[str, Any]]:
    """The decoded result of every envelope (optionally of one tool) that decodes to an object."""
    bodies: list[dict[str, Any]] = []
    for envelope in envelopes:
        if tool is not None and getattr(envelope, "name", "") != tool:
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        if isinstance(body, dict):
            bodies.append(body)
    return bodies


def _seam(left: str, right: str) -> str:
    """Close the gap a removed phrase left: one space, none before punctuation, no orphan comma.

    Spaces and tabs only. A newline is structure — `dates.correct` once ran `\\s{2,}` over whole
    blocks and flattened every paragraph in them (UX W6), and that text is what `turns.final_answer`
    stores and `/chat` returns.
    """
    trimmed = left.rstrip(" \t")
    if right.startswith(("\n", "\r")):
        return trimmed + right
    head = right.lstrip(" \t")
    if not head:
        return trimmed
    sentence_start = not trimmed or trimmed.endswith(("\n", "\r")) or trimmed[-1] in ".!?"
    if sentence_start or trimmed[-1] in ":;":
        # The phrase opened the clause — *"As of 1 September 2026, your balance is 13.5 days"* —
        # so the comma that followed it now has nothing to separate.
        head = _ORPHAN_COMMA.sub("", head)
        if sentence_start:
            head = head[:1].upper() + head[1:]
        return f"{trimmed} {head}" if trimmed else head
    if head[0] in ",.;:!?)]":
        return trimmed + head
    return f"{trimmed} {head}"


def _cuts(text: str, phrase: re.Pattern[str]) -> list[tuple[int, int]]:
    """Each restatement's span, widened to whatever punctuation was only there to introduce it."""
    spans: list[tuple[int, int]] = []
    for match in phrase.finditer(text):
        start, end = match.start(), match.end()
        if spans and start < spans[-1][1]:
            continue
        before, after = text[: match.start()], text[match.end() :]
        opened, closed = _OPEN.search(before), _CLOSE.match(after)
        if opened and closed:
            # "(as of 2026-09-01)" — the brackets came with the phrase and leave with it.
            spans.append((opened.start(), end + closed.end()))
            continue
        lead, follow = _LEAD_COMMA.search(before), _FOLLOW_COMMA.match(after)
        if lead:
            start = lead.start()
            if follow and not _OPENS_A_CLAUSE.match(after[follow.end() :]):
                end += follow.end()
        spans.append((start, end))
    return spans


def undate(text: str, dates: Sequence[str]) -> str:
    """One passage with the snapshot date's restatements removed. Unchanged when it carries none."""
    phrase = _phrase(dates)
    if phrase is None:
        return text
    spans = _cuts(text, phrase)
    if not spans:
        return text
    out = text[: spans[0][0]]
    for index, (_, end) in enumerate(spans):
        following = text[end : spans[index + 1][0]] if index + 1 < len(spans) else text[end:]
        out = _seam(out, following)
    return out


def restate_tenure(text: str, pairs: Sequence[tuple[int, str]]) -> str:
    """`45 months` → `3 years 9 months`, where 45 is this employee's own reported tenure."""
    for months, words in pairs:
        if months < TENURE_FLOOR:
            continue
        pattern = re.compile(rf"\b{months}\s+months\b")

        def swap(match: re.Match[str], *, words: str = words, source: str = text) -> str:
            window = source[max(0, match.start() - THRESHOLD_WINDOW) : match.start()].lower()
            if any(word in window for word in THRESHOLD_WORDS):
                return match.group(0)
            return words

        text = pattern.sub(swap, text)
    return text


def correct(text: str, *, dates: Sequence[str] = (), pairs: Sequence[tuple[int, str]] = ()) -> str:
    """Both rules over one passage, in the order a sentence reads them. Idempotent by construction:
    the date is gone after the first pass, and a tenure in words carries no `N months` to match."""
    return restate_tenure(undate(text, dates), pairs)


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
    dates = snapshot_dates(envelopes)
    pairs = tenures(envelopes)
    if not dates and not pairs:
        return Outcome(blocks=[dict(block) for block in blocks], next_steps=[str(step) for step in next_steps])

    corrected = 0
    body: list[dict[str, Any]] = []
    for block in blocks:
        item = dict(block)
        before = str(item.get("text") or "")
        after = correct(before, dates=dates, pairs=pairs)
        if after != before:
            item["text"] = after
            corrected += 1
        body.append(item)

    steps: list[str] = []
    for step in next_steps:
        before = str(step)
        after = correct(before, dates=dates, pairs=pairs)
        corrected += after != before
        steps.append(after)
    return Outcome(blocks=body, next_steps=steps, corrected=corrected)


__all__ = [
    "ISO",
    "PROFILE_TOOL",
    "TENURE_MONTHS_FIELD",
    "STEP_NAME",
    "TENURE_FLOOR",
    "THRESHOLD_WINDOW",
    "THRESHOLD_WORDS",
    "Outcome",
    "apply",
    "correct",
    "restate_tenure",
    "snapshot_dates",
    "tenures",
    "undate",
    "variants",
]
