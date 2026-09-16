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

from hrmosaic.agent.outcome import DENIALS, about_the_reader, sentences

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

#: A denial is about **this** assistant only in the first person (W8 fix round, W7-review Minor).
#: "on your behalf" and "for you" are modifiers, not an alternative: *"A manager cannot open a
#: ticket for you without a written request"* is a policy sentence, and it carries both.
FIRST_PERSON = re.compile(r"\b(?:i|we)\b", re.IGNORECASE)

#: Where an attribute word is the name of a **topic**, not a claim about anybody (W8 fix round,
#: Critical 1). All three demo personas are `hybrid`, and demo 1 is about international remote
#: work: without this, every sentence containing the word "remote" — *"Work performed outside your
#: home country under the remote work policy…"* — was dropped from a hybrid employee's answer and a
#: block that was nothing but such a sentence went whole. The phrases are removed before the
#: attribute words are looked for.
TOPIC_PHRASES: tuple[str, ...] = (
    "remote-and-hybrid-work",
    "remote & hybrid work",
    "remote and hybrid work",
    "international remote work",
    "remote work policy",
    "remote-work policy",
    "remote work",
    "remote-work",
    "hybrid work",
    "hybrid-work",
    "onsite work",
    "on-site work",
    "work remotely",
    "working remotely",
)

#: The frames in which an attribute word is a claim about the **reader**, when the sentence does
#: not simply open with "you"/"your": *"as a fully remote employee"*, *"you are a remote worker"*.
READER_FRAME = re.compile(
    r"\b(?:as|for|being)\s+an?\s+(?:\w+\s+)?(?:remote|hybrid|onsite|on-site|in-office)\s+(?:employee|worker|colleague|staff)\b"
    r"|\byou(?:'re| are| work| now work)\s+(?:an?\s+)?(?:\w+\s+)?(?:remote|hybrid|onsite|on-site|in-office)\b",
    re.IGNORECASE,
)


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


def _about_the_readers_arrangement(sentence: str) -> bool:
    """Is this a claim about the reader — not a sentence that happens to name a topic?

    Two shapes count: a sentence whose subject is the reader (*"You are…"*, *"Your…"*), and an
    attribute word inside a reader frame (*"as a fully remote employee"*). A policy sentence in the
    third person is neither, whatever words it uses.
    """
    return about_the_reader(sentence) or bool(READER_FRAME.search(sentence))


def contradicts_the_record(text: str, envelopes: Iterable[Any]) -> bool:
    """Does this sentence state a profile attribute of the **reader** that their envelope contradicts?

    Three gates, in order (W8 fix round, Critical 1): the sentence has to be about the reader; the
    topic phrases are taken out first, so "remote" inside "the remote work policy" names a policy
    and not a person; and only then is what is left compared with the envelope.
    """
    if not _about_the_readers_arrangement(text):
        return False
    lowered = text.lower()
    for phrase in TOPIC_PHRASES:
        lowered = lowered.replace(phrase, " ")
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
        removed: list[str] = []
        for sentence in sentences(text):
            if denies_a_permitted_tool(sentence, permitted) or contradicts_the_record(sentence, envelopes):
                removed.append(sentence)
            else:
                kept.append(sentence)
        dropped.extend((index, sentence) for sentence in removed)
        if removed and not kept:
            emptied.append(index)
            continue
        # Unchanged bytes when nothing came out: the join only happens where a sentence did.
        if removed:
            item["text"] = " ".join(part.strip() for part in kept)
        body.append(item)
    return Outcome(blocks=body, dropped=dropped, emptied=emptied)


__all__ = [
    "FIRST_PERSON",
    "PROFILE_ATTRIBUTES",
    "PROFILE_TOOL",
    "READER_FRAME",
    "STEP_NAME",
    "TOOL_ACTIONS",
    "TOPIC_PHRASES",
    "Outcome",
    "apply",
    "contradicts_the_record",
    "denies_a_permitted_tool",
]
