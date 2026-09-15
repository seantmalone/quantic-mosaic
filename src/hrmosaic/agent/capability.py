"""The answer may not deny what the turn could do, or invent what it could have read.

**Not a guardrail.** No `guardrail` span, no G-number. One deterministic step after synthesis,
reading the turn's permitted-tool list and its own envelopes (spec §7.4; W8, C09 and C10).

Two failures, both measured, both the same shape — the written answer disagreeing with what the
deterministic layer knows:

* **C09.** *"I cannot submit PTO requests in MosaicOne on your behalf"* — on a turn where
  `create_mock_hr_ticket` was offered, gated and one confirmation away from doing exactly that.
  Nine of twelve recorded runs of `unsafe-001` produced it. The product's headline capability,
  denied by the product.
* **C10.** *"for a fully remote employee"* — written for E1042, whose own profile envelope says
  `work_arrangement: "hybrid"`, on a turn that had read it.

So: a block that asserts an inability to do what a **permitted** tool does is dropped, and a
sentence that states a profile attribute the turn's own envelope contradicts is dropped with it. A
block left with nothing goes whole. Nothing is rewritten — an answer that got the reader's own
record wrong has nothing this step can put in its place, and the other steps repair what they can.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hrmosaic.agent.outcome import DENIALS, sentences

#: What the step is called where it is named — reports, the spec paragraph beside §7.4's table.
#: Deliberately not a `G<n>`: the six guardrails are a closed set.
STEP_NAME = "capability_check"

#: Tool → the words a denial of **that** tool's action uses. Same shape as `outcome.ACTION_WORDS`
#: and the same reason for the second half: without it, G5's sensitive-topic escalation ("I will
#: not handle a discrimination concern here") reads as a capability denial and is destroyed.
TOOL_ACTIONS: dict[str, tuple[str, ...]] = {
    "create_mock_hr_ticket": ("ticket", "request", "open", "file", "submit", "raise", "create"),
    "draft_hr_email": ("email", "draft", "message", "compose"),
    "lookup_employee_profile": ("profile", "record", "office", "manager", "arrangement", "tenure"),
    "check_pto_balance": ("balance", "accrual", "days remaining"),
    "lookup_benefits_status": ("benefit", "election", "enrollment", "enrolment"),
}

#: Profile attributes an answer may state, and the envelope field each is read from. A closed set:
#: these are the ones an answer has been observed inventing, and the ones a reader acts on.
PROFILE_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "work_arrangement": ("remote", "hybrid", "onsite", "on-site", "in-office"),
}

#: The profile envelope, and the only one this step reads attributes from.
PROFILE_TOOL = "lookup_employee_profile"

#: *"on your behalf"*, *"for you"* — the phrase that makes a denial one about **this** assistant
#: rather than about a policy. Without it, "a manager cannot approve their own request" reads as a
#: capability denial.
FIRST_PERSON = re.compile(r"\b(?:i|we)\b|\bon your behalf\b|\bfor you\b", re.IGNORECASE)


@dataclass
class Outcome:
    """The blocks after the step, and what it took out."""

    blocks: list[dict[str, Any]]
    #: `(index into the model's own blocks, the sentence)` for every sentence removed.
    dropped: list[tuple[int, str]] = field(default_factory=list)
    #: Indexes of the blocks that were nothing but such sentences.
    emptied: list[int] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.dropped)


def _bodies(envelopes: Iterable[Any], *, tool: str) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []
    for envelope in envelopes:
        if getattr(envelope, "name", "") != tool:
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        if isinstance(body, dict):
            bodies.append(body)
    return bodies


def denies_a_permitted_tool(text: str, permitted: Sequence[str]) -> bool:
    """Does this sentence claim the assistant cannot do what one of `permitted` does?

    Three halves, all required: a denial, in the first person, about the action a permitted tool
    performs. *"Nobody approves their own request"* has the first two missing, *"I cannot give
    legal advice"* the third.
    """
    lowered = text.lower()
    if not any(phrase in lowered for phrase in DENIALS) or not FIRST_PERSON.search(lowered):
        return False
    return any(word in lowered for name in permitted for word in TOOL_ACTIONS.get(name, ()))


def contradicts_the_record(text: str, envelopes: Iterable[Any]) -> bool:
    """Does this sentence state a profile attribute the reader's own envelope contradicts?"""
    lowered = text.lower()
    for body in _bodies(envelopes, tool=PROFILE_TOOL):
        for field_name, vocabulary in PROFILE_ATTRIBUTES.items():
            actual = str(body.get(field_name) or "").lower()
            if not actual:
                continue
            stated = [word for word in vocabulary if re.search(rf"\b{re.escape(word)}\b", lowered)]
            if stated and not any(word in actual or actual in word for word in stated):
                return True
    return False


def apply(
    blocks: Sequence[Mapping[str, Any]],
    envelopes: Iterable[Any],
    *,
    permitted: Sequence[str] = (),
) -> Outcome:
    """The pure rule, sentence by sentence. Mutates nothing."""
    body: list[dict[str, Any]] = []
    dropped: list[tuple[int, str]] = []
    emptied: list[int] = []
    for index, block in enumerate(blocks):
        item = dict(block)
        text = str(item.get("text") or "")
        kept: list[str] = []
        for sentence in sentences(text):
            if denies_a_permitted_tool(sentence, permitted) or contradicts_the_record(sentence, envelopes):
                dropped.append((index, sentence))
            else:
                kept.append(sentence)
        if not kept and text:
            emptied.append(index)
            continue
        item["text"] = " ".join(part.strip() for part in kept) if len(kept) != len(sentences(text)) else text
        body.append(item)
    return Outcome(blocks=body, dropped=dropped, emptied=emptied)


__all__ = [
    "FIRST_PERSON",
    "PROFILE_ATTRIBUTES",
    "PROFILE_TOOL",
    "STEP_NAME",
    "TOOL_ACTIONS",
    "Outcome",
    "apply",
    "contradicts_the_record",
    "denies_a_permitted_tool",
]
