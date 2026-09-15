"""Outcome consistency — a confirmed write is reported as done (spec §7.4, P22).

**Not a guardrail.** It emits no `guardrail` span, it carries no G-number, and none of the six
rules of §7.4 changed for it. It is one deterministic step that runs after synthesis, on the
blocks G2 and G3 have already repaired, and its whole job is to keep the answer's account of what
happened consistent with what the tools actually did.

**The failure it exists for**, live on 2026-09-11: demo 2's confirmation card was shown with the
exact payload, the user clicked Confirm, the token was consumed, `create_mock_hr_ticket` returned
`{"status": "created", "ticket_id": "MOCK-HR-000002", …}` and the synthesis prompt carried that
result verbatim inside its `<tool_result>` envelope. The answer nevertheless closed with an
escalation — *"I cannot open PTO requests on your behalf. You must submit the request directly in
MosaicOne…"* — and never mentioned the ticket. The write had happened; the answer denied it.

Two moves, both read from the tool result rather than from model output:

1. **The outcome block goes first, in its own type.** A `performed` block (UX W6), because a
   completed irreversible write is neither company policy nor a suggestion: `_turn.html` renders it
   as the turn's lead sentence above the facts, outside the suggestions group and outside its
   *"guidance, not company policy"* footnote, which is where a `recommendation` had been putting it
   (JX-R1 = cpux-re-1). It carries the id verbatim and the queue's human name.
2. **There is exactly one account of the write per turn.** If the model's own answer already names
   the id, this step states nothing and an escalation denying the action becomes the one-line
   `pointer` instead. If it does not, the `performed` block is the account and a denying escalation
   is dropped outright — the `pointer` under a statement that has just said the same thing is the
   answer arguing with itself. Only that kind of escalation is touched: G5's sensitive-topic block
   names a People Operations contact and would be collateral damage, so the check is denial *plus*
   a word for the action the performed tool performs.
3. **A next step that sends the reader off to do it themselves is dropped.** `next_steps` is
   rendered into the same answer as the blocks, so the same contradiction reads the same way: the
   demo-2 answer stated the ticket and then closed with *"Log into MosaicOne and submit your PTO
   request for 15-17 September 2026."* The check is the imperative twin of the escalation one and
   just as narrow — an imperative verb for the performed tool at the head of a clause, *plus* one
   of that tool's own objects in the same clause. "Watch for your manager's approval in MosaicOne"
   and "Dana Whitfield approves request MOCK-HR-000123" are not directives at the reader and
   survive, and so does any step naming the id, which is talking about the thing that exists
   rather than asking for another one.

**A success status is proof of a confirmation.** `mcpserver/confirm.py` mints a token only inside
`POST /chat/confirm`, after a human clicks Confirm, and `mock_writes.confirmation_token` is `NOT
NULL REFERENCES` — so a write tool cannot return `created` / `drafted` without a consumed one
(§8.6). Reading the envelope is therefore the same question as "was this performed after a human
confirmation", asked where the answer is written down.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hrmosaic.core.queues import QUEUE_FALLBACK, queue_label

#: What the step is called where it is named — reports, the spec paragraph beside §7.4's table.
#: Deliberately not a `G<n>`: the six guardrails are a closed set.
STEP_NAME = "outcome_consistency"

#: The block type a *completed* write is reported in — its own, never `recommendation` (UX W6,
#: JX-R1 = cpux-re-1). `_turn.html` groups every `recommendation` under *"What I suggest you do"*
#: and footnotes the group *"Suggestions are guidance, not company policy"*, so an irreversible
#: write that had already happened was filed as non-binding advice and disclaimed. A `performed`
#: block is the turn's lead sentence, above the facts, outside that group and outside its footnote.
#:
#: **Only this module may write one.** A model that emits `performed` is stating that a write it
#: cannot see the result of took place; `apply()` downgrades such a block to `recommendation`
#: before it does anything else, so the claim is only ever made from the tool result.
PERFORMED = "performed"

#: Write tool → the `status` its result carries when the write actually happened (§8.4 tools 8, 9).
#: A `confirmation_required` body — the gated attempt — is not one of these and states nothing.
WRITE_SUCCESS: dict[str, str] = {
    "create_mock_hr_ticket": "created",
    "draft_hr_email": "drafted",
}

#: Phrases that make a sentence a denial. Matched case-insensitively against the block text.
DENIALS = (
    "cannot",
    "can not",
    "can't",
    "unable to",
    "not able to",
    "do not have the ability",
    "am not permitted",
    "did not",
)

#: Denial plus one of these words is a denial *of the action the tool performed*. Without the
#: second half, G5's escalation ("I will not handle a discrimination concern here — contact People
#: Operations") would be replaced by a line about a ticket, which is not what it was there to say.
ACTION_WORDS: dict[str, tuple[str, ...]] = {
    "create_mock_hr_ticket": ("ticket", "request", "open", "file", "submit", "raise", "create"),
    "draft_hr_email": ("email", "draft", "message", "write", "send", "compose"),
}

#: A next step is a directive when a clause *opens* with one of these verbs — the imperative mood,
#: which is the whole difference between "Submit your PTO request in MosaicOne" (an instruction to
#: the reader) and "Your manager will receive the request" (a statement about someone else).
IMPERATIVES: dict[str, tuple[str, ...]] = {
    "create_mock_hr_ticket": ("submit", "file", "open", "raise", "create", "log"),
    "draft_hr_email": ("send", "write", "compose", "draft", "email"),
}

#: ...and the object of that verb, in the same clause, has to be the thing the tool made. Without
#: it, "Open the policy and read section 4" would be read as an instruction to file a request.
#: The subject of the request — "PTO" — is deliberately **not** an object: "Open the PTO &
#: Holidays Policy" names the topic, not the ticket, and dropping that step would lose the reader
#: a real instruction to keep a wording the model is free to vary.
ACTION_OBJECTS: dict[str, tuple[str, ...]] = {
    "create_mock_hr_ticket": ("ticket", "request", "case"),
    "draft_hr_email": ("email", "draft", "message", "note"),
}

#: Clause boundaries. "Log into MosaicOne and submit your PTO request" is two clauses, and only
#: the second one is the directive that contradicts a ticket that already exists.
_CLAUSE = re.compile(r"[,;:.!?]|\band\b|\bthen\b|\bor\b|\bbut\b|\bso\b")

#: Politeness and modality in front of the verb, stripped one layer at a time so that
#: "Please make sure to submit ..." reaches "submit" the way a bare imperative does.
_LEAD_IN = re.compile(
    r"^(?:please|also|first|next|finally|be sure to|make sure to|remember to|go and|go to|"
    r"you must|you should|you need to|you will need to|you have to|you can)\s+"
)


@dataclass(frozen=True)
class PerformedWrite:
    """One write tool result that succeeded, and the two sentences derived from it."""

    tool_name: str
    write_id: str
    body: Mapping[str, Any]

    @property
    def statement(self) -> str:
        """The block that opens the answer: one sentence, what happened, and the reference.

        **Rewritten at UX W2** (chat-production-ux-11, demo-and-grader-controls-15). It used to
        read *"Done: HR ticket MOCK-HR-000002 was opened in queue hr-timeoff (priority normal) —
        this is a mock ticket, nothing was sent outside this app."*: a routing slug, an enum and a
        disclosure about the demo, all inside the one sentence that tells a person their request
        went through. The slug and the priority are still on the `tool_call` span and in
        `mock_writes`, and the *"writes are simulated"* disclosure belongs to the demo panel,
        stated once for the whole session instead of inside every answer.
        """
        if self.tool_name == "draft_hr_email":
            recipient = self.body.get("to_name") or self.body.get("to_role")
            for_whom = f" for {recipient}" if recipient else ""
            return f"Done — the email draft is ready{for_whom}. Reference {self.write_id}."
        # The queue's human name, through the same `queue_label()` the confirmation card is built
        # from (`web/api.py::_confirm_fields`). The card said *"Goes to: HR Time Off team"* and the
        # answer that reported the very same ticket said *"with HR"* (UX W6, cpux-re-2). A named
        # team takes the article; the unnamed fallback is a department and does not.
        label = queue_label(str(self.body.get("queue") or ""))
        team = label if label == QUEUE_FALLBACK else f"the {label}"
        return f"Done — your request is with {team}. Reference {self.write_id}."

    @property
    def pointer(self) -> str:
        """What replaces an escalation that denied this action: one reassuring line, not a rebuttal.

        It used to be a second account of the write — *"The ticket already exists: MOCK-HR-000002
        was opened in queue hr-timeoff on this turn after you confirmed it. There is nothing
        further for you to file."* — printed directly under the `statement` that had just said the
        same thing, so the answer argued with itself over a request that had simply gone through
        (chat-production-ux-11). `statement` reports the write, once, at the top; this says the one
        thing the denial was in the way of.
        """
        if self.tool_name == "draft_hr_email":
            return "That is already taken care of — the draft is ready for you to review."
        return "That is already taken care of — there is nothing further for you to file."


@dataclass
class Outcome:
    """The blocks and next steps after the step, and what it did to them."""

    blocks: list[dict[str, Any]]
    #: The next steps that survived, in order. The same list when nothing contradicted the write.
    next_steps: list[str] = field(default_factory=list)
    #: Whether the outcome block was inserted. False when the model already stated the id.
    stated: bool = False
    #: Indexes **into the model's own block list**, before the outcome block is inserted.
    replaced: list[int] = field(default_factory=list)
    #: Indexes into the model's own `next_steps` of the directives that were dropped.
    dropped: list[int] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.stated or bool(self.replaced) or bool(self.dropped)


def performed_write(envelopes: Iterable[Any]) -> PerformedWrite | None:
    """The last write envelope of the turn that carries a success status, or `None`.

    Envelopes are `_ToolEnvelope(name, result_json)`; a body that will not parse, or that carries
    no id, is not evidence of anything and is ignored rather than raised over — this step must
    never be the reason an answer fails to reach the reader.
    """
    found: PerformedWrite | None = None
    for envelope in envelopes:
        expected = WRITE_SUCCESS.get(getattr(envelope, "name", ""))
        if expected is None:
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(body, dict) or body.get("status") != expected:
            continue
        write_id = body.get("ticket_id") or body.get("draft_id")
        if not write_id:
            continue
        found = PerformedWrite(tool_name=envelope.name, write_id=str(write_id), body=body)
    return found


def denies(text: str, tool_name: str) -> bool:
    """Does this text claim an inability to do the thing `tool_name` just did?"""
    lowered = text.lower()
    if not any(phrase in lowered for phrase in DENIALS):
        return False
    return any(word in lowered for word in ACTION_WORDS.get(tool_name, ()))


def directs(text: str, tool_name: str) -> bool:
    """Does this next step tell the reader to go and do what `tool_name` has already done?

    The imperative twin of `denies`: an imperative verb for the tool at the head of a clause, and
    one of that tool's own objects in the same clause. Both halves are needed — "Your manager will
    receive the request" has the object and no imperative, "Open the policy" has the imperative and
    no object, and neither contradicts a ticket that exists.
    """
    verbs = IMPERATIVES.get(tool_name, ())
    objects = ACTION_OBJECTS.get(tool_name, ())
    if not verbs or not objects:
        return False
    for clause in _CLAUSE.split(text.lower()):
        head = clause.strip()
        while match := _LEAD_IN.match(head):
            head = head[match.end() :]
        words = head.split()
        if words and words[0].strip("\"'()“”‘’") in verbs and any(word in head for word in objects):
            return True
    return False


def apply(
    blocks: Sequence[Mapping[str, Any]],
    envelopes: Iterable[Any],
    *,
    next_steps: Sequence[str] = (),
) -> Outcome:
    """The pure rule: state the write first, and drop what contradicts it. Mutates nothing."""
    write = performed_write(envelopes)
    # Only this step may claim a write happened, and it claims it from the tool result. A model
    # that typed a block `performed` is asserting the outcome of a call whose result it has not
    # been shown, so the claim is demoted to what it actually is — advice (UX W6).
    body = [{**block, "type": "recommendation"} if block.get("type") == PERFORMED else dict(block) for block in blocks]
    steps = [str(step) for step in next_steps]
    if write is None:
        return Outcome(blocks=body, next_steps=steps)

    kept: list[str] = []
    dropped: list[int] = []
    for index, step in enumerate(steps):
        # A step naming the id is talking about the ticket that exists, not asking for another.
        if write.write_id in step or not directs(step, write.tool_name):
            kept.append(step)
        else:
            dropped.append(index)

    # The de-dup guard reads the model's own blocks: **one account of the write per turn** (UX W6).
    # If the answer already names the id, this step adds no statement of its own and the denying
    # escalation below becomes the `pointer` — the single account. If it does not, the `performed`
    # block is the single account and a denying escalation is *removed* rather than rewritten,
    # because the `pointer` says in other words exactly what the statement above it has just said,
    # which is how *"Done — your request is with HR"* and *"That is already taken care of"* came to
    # print two bullets apart (JX-R1 = cpux-re-1).
    already_stated = any(write.write_id in str(block.get("text") or "") for block in body)

    replaced: list[int] = []
    survivors: list[dict[str, Any]] = []
    for index, block in enumerate(body):
        if block.get("type") == "escalation" and denies(str(block.get("text") or ""), write.tool_name):
            replaced.append(index)
            if not already_stated:
                continue
            block = {**block, "type": "recommendation", "text": write.pointer, "citations": []}
        survivors.append(block)

    if already_stated:
        return Outcome(blocks=survivors, next_steps=kept, replaced=replaced, dropped=dropped)
    statement = {"type": PERFORMED, "text": write.statement, "citations": []}
    return Outcome(blocks=[statement, *survivors], next_steps=kept, stated=True, replaced=replaced, dropped=dropped)


__all__ = [
    "ACTION_OBJECTS",
    "ACTION_WORDS",
    "DENIALS",
    "IMPERATIVES",
    "PERFORMED",
    "STEP_NAME",
    "WRITE_SUCCESS",
    "Outcome",
    "PerformedWrite",
    "apply",
    "denies",
    "directs",
    "performed_write",
]
