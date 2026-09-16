"""Next-step entailment — a step may not name what the answer does not (spec §7.4; W8, C08).

**Not a guardrail.** No `guardrail` span, no G-number — but it does to `next_steps` what G3 does to
an uncited `policy_fact`, and it records its drops the same way.

`next_steps` is a bare `list[str]` the model writes **in parallel** with the blocks, and until now
no rule read it: G2 resolves citations and G3 separates fact from advice, and both run over blocks
only. So a step routinely named a deadline, an approver or a threshold that the answer's own facts
exclude:

    fact   "Expense reports up to USD 2,500 are approved by the direct manager."
    step   "Submit the expense report to your manager for approval."   ← on a USD 3,000 trip

The rule is entailment, and it is deliberately narrow. A step carrying a **date**, a **duration**,
an **amount** or a **person's name** that appears in no surviving block and in no tool envelope is
dropped. Everything else — a step with no such claim in it — is left exactly as written: this step
exists to remove ungrounded specifics, not to edit advice.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hrmosaic.agent.dates import MONTHS, PARENTHETICAL

#: What the step is called where it is named — reports, the spec paragraph beside §7.4's table.
#: Deliberately not a `G<n>`: the six guardrails are a closed set.
STEP_NAME = "next_step_entailment"

#: A date as prose writes it — `15 September`, `3rd November 2026` — or as a machine does.
DATE = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{'|'.join(MONTHS)})(?:\s+\d{{4}})?\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b",
    re.IGNORECASE,
)

#: A duration with its unit: `3 days`, `5 business days`, `six weeks`, `36 months`.
DURATION = re.compile(
    r"\b\d+(?:\.\d+)?\s+(?:business\s+|working\s+|calendar\s+|consecutive\s+)?(?:day|week|month|year)s?\b",
    re.IGNORECASE,
)

#: An amount of money, in the two shapes the corpus and the answers use.
AMOUNT = re.compile(r"\b(?:USD|EUR|GBP)\s*[\d,]+(?:\.\d+)?\b|[$€£]\s?[\d,]+(?:\.\d+)?\b", re.IGNORECASE)

#: A capitalised word that might be somebody's name. Sentence-initial words are excluded by the
#: caller, and `STOPWORDS` removes the ones this product says all the time.
NAME = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b")

#: Capitalised words that are never a person here: the months and weekdays a date is written in,
#: the product's own nouns, and the teams a policy answer names. Without these the step would drop
#: an honest instruction for naming MosaicOne.
STOPWORDS: frozenset[str] = frozenset(
    {
        *(month.lower() for month in MONTHS),
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "mosaic",
        "mosaicone",
        "mosaicrobotics",
        "robotics",
        "people",
        "operations",
        "employee",
        "relations",
        "finance",
        "procurement",
        "security",
        "legal",
        "benefits",
        "payroll",
        "expenses",
        "policy",
        "holidays",
        "german",
        "germany",
        "boston",
        "austin",
        "berlin",
        "your",
        "you",
        "this",
        "that",
        "these",
        "the",
        "reference",
        "request",
        "ticket",
        "manager",
        "director",
        "review",
        "approval",
        "notice",
        "balance",
        "blackout",
        "tenure",
        "vice",
        "president",
    }
)


@dataclass
class Outcome:
    """The next steps that survived, and the ones that did not."""

    next_steps: list[str] = field(default_factory=list)
    #: `(index into the model's own steps, the step, the claim that was not entailed)`.
    dropped: list[tuple[int, str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.dropped)


def claims(text: str) -> list[str]:
    """Every specific this text commits to: its dates, durations, amounts and names.

    A deadline that **shows its working** — *"by 13 October 2026 (21 days before 3 November)"* — is
    not one of them. `agent/dates.py` has already recomputed that date from its anchor and
    corrected it if it was wrong, so it is derived from a date the turn does carry rather than
    asserted; asking for it verbatim in a block would drop the most useful step a reader gets.
    """
    text = PARENTHETICAL.sub(" ", text)
    found: list[str] = []
    for pattern in (DATE, DURATION, AMOUNT):
        found += [match.group(0) for match in pattern.finditer(text)]
    covered = "".join(found).lower()
    for match in NAME.finditer(text):
        word = match.group(0)
        if word.lower() in STOPWORDS or word.lower() in covered:
            continue
        found.append(word)
    return found


def _normalise(text: str) -> str:
    """Comparable bytes: lower-cased, thousands separators dropped, whitespace flattened."""
    return re.sub(r"\s+", " ", text.replace(",", "")).lower()


def grounds(blocks: Sequence[Mapping[str, Any]], envelopes: Iterable[Any]) -> str:
    """Everything this turn is allowed to have said: the surviving blocks and every tool result."""
    parts = [str(block.get("text") or "") for block in blocks]
    for envelope in envelopes:
        raw = getattr(envelope, "result_json", "") or ""
        parts.append(raw)
        try:
            body = json.loads(raw)
        except (TypeError, ValueError):
            continue
        # The human forms of a machine date live here too, so a step may write `15 September 2026`
        # against an envelope that carries `2026-09-15`.
        parts.append(json.dumps(body, ensure_ascii=False))
    return _normalise(" ".join(parts))


#: A number as a JSON body or a sentence writes one — a whole token, never a run of digits inside
#: a longer one. `"3"` is entailed by `"days": 3` and not by `"13.5"` or `2026-09-03`.
_NUMBER_TOKEN = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")


def entailed(claim: str, ground: str) -> bool:
    """Is this specific one the turn actually established?

    A date or a name has to appear as written. A duration or an amount is entailed when its
    **number** is a whole token of the ground — `USD 2,500` against `2500`, `3 days` against
    `"days": 3` — and not when its digits merely occur inside some longer figure, which is how the
    first version of this let every small duration through (W7-review Minor).
    """
    normalised = _normalise(claim)
    if normalised in ground:
        return True
    number = re.search(r"\d[\d.]*", normalised)
    if number is None:
        return False
    value = number.group(0).rstrip(".")
    tokens = set(_NUMBER_TOKEN.findall(ground))
    return value in tokens or (value.endswith(".0") and value[:-2] in tokens) or f"{value}.0" in tokens


#: The blocks' own sentences, normalised, for the duplicate rule below.
DUPLICATE = "already said in the answer"


def _sentences(text: str) -> list[str]:
    """`text` split at terminal punctuation — enough to compare one instruction with another."""
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def said_in_a_block(step: str, blocks: Sequence[Mapping[str, Any]]) -> bool:
    """Is this step a sentence the answer above it already carries? (W10, ruling 13)

    `render_answer()` prints the blocks and then the next steps, so a step whose normalised text is
    contained in a block is the same instruction printed twice on one screen — which four of the
    sixteen recorded demo paths did (01, 02, 03, 13), once with the two copies differing only in a
    trailing full stop. Containment rather than equality: the model writes *"Submit the request in
    MosaicOne"* as a step under a block sentence that says it and more.
    """
    needle = _normalise(step).rstrip(".")
    if not needle:
        return False
    for block in blocks:
        for sentence in _sentences(str(block.get("text") or "")):
            if needle in _normalise(sentence).rstrip("."):
                return True
    return False


def apply(
    blocks: Sequence[Mapping[str, Any]],
    envelopes: Iterable[Any],
    *,
    next_steps: Sequence[str] = (),
) -> Outcome:
    """The pure rule. Mutates nothing.

    Two reasons a step goes: it names a specific the answer never established (W8, C08), or it
    repeats a sentence the answer already prints (W10, ruling 13).
    """
    ground = grounds(blocks, envelopes)
    kept: list[str] = []
    dropped: list[tuple[int, str, str]] = []
    for index, step in enumerate(next_steps):
        text = str(step)
        if said_in_a_block(text, blocks):
            dropped.append((index, text, DUPLICATE))
            continue
        unentailed = next((claim for claim in claims(text) if not entailed(claim, ground)), None)
        if unentailed is None:
            kept.append(text)
        else:
            dropped.append((index, text, unentailed))
    return Outcome(next_steps=kept, dropped=dropped)


__all__ = [
    "AMOUNT",
    "DUPLICATE",
    "DATE",
    "DURATION",
    "NAME",
    "STEP_NAME",
    "STOPWORDS",
    "Outcome",
    "apply",
    "claims",
    "entailed",
    "grounds",
    "said_in_a_block",
]
