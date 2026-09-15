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
2. **There is exactly one account of the write per turn, and it is the `performed` statement.**
   The first version of this guard was right about *one account* and wrong about which one: it read
   any model block naming the id as that account, stated nothing itself, and left the sentence
   where the model had filed it. So on 2026-09-15, live, the answer reported `MOCK-HR-000007` in a
   `recommendation` — printed under *"What I suggest you do"* beneath *"Suggestions are guidance,
   not company policy"* (JX-R1 = cpux-re-1, back on the live path), a created ticket disclaimed as
   advice. A model block of **any** type whose text names `write.write_id` is therefore the model's
   account of a write only the tool result can attest, and it is **removed**; the `performed`
   statement is prepended in its place. An escalation that denies the action goes the same way and
   for the same reason — the statement above it has already said what the denial was in the way of.
   Only that kind of escalation is touched: G5's sensitive-topic block names a People Operations
   contact and would be collateral damage, so the check is denial *plus* a word for the action the
   performed tool performs.
3. **A next step that sends the reader off to do it themselves is dropped.** `next_steps` is
   rendered into the same answer as the blocks, so the same contradiction reads the same way: the
   demo-2 answer stated the ticket and then closed with *"Log into MosaicOne and submit your PTO
   request for 15-17 September 2026."* The check is the imperative twin of the escalation one and
   just as narrow — an imperative verb for the performed tool at the head of a clause, *plus* one
   of that tool's own objects in the same clause. "Watch for your manager's approval in MosaicOne"
   and "Dana Whitfield approves request MOCK-HR-000123" are not directives at the reader and
   survive, and so does any step naming the id, which is talking about the thing that exists
   rather than asking for another one.

4. **No sentence of any block tells the reader to go and do it either** (UX W7, Addendum 3). The
   owner saw, live, *"Done — your request is with the HR Time Off team. Reference MOCK-HR-000009."*
   followed under *"What I suggest you do"* by *"… Submit the request in MosaicOne so your manager
   can approve it in writing."* Rule 3 looked at the steps and never inside a block. After a
   performed write every block of every type is split into sentences, each sentence is put to the
   same `directs` test, the ones that direct are removed, a block left with nothing is dropped, and
   the edits are recorded beside `dropped` and `replaced`. A sentence naming the id is kept, as a
   step naming it is: it talks about the request that exists.
5. **What is left of such a block is the reader's record, not advice.** *"You have 13.5 days
   remaining. Your three-day request is covered by your balance."* is a statement of the reader's
   own data, and it was sitting under *"Suggestions are guidance, not company policy"*. It becomes
   a `record` block (UX W7, JX2-05 = cpux2-4) — and so, on any turn, does a `recommendation` that
   opens no clause with a directive verb and states a number a data tool on this turn returned (a
   balance, a tenure in months, notice days). A block G3 demoted from an uncited `policy_fact` is
   exempt: that one is a policy claim wearing the wrong label, not a record.
6. **The statement says what happens next when the write is a PTO ticket.** *"Your manager's
   written approval is the next step."* — only for the `hr-timeoff` queue, whose design (§18.2)
   is that the ticket *is* the request, routed to the team and then to the manager.

**A success status is proof of a confirmation.** `mcpserver/confirm.py` mints a token only inside
`POST /chat/confirm`, after a human clicks Confirm, and `mock_writes.confirmation_token` is `NOT
NULL REFERENCES` — so a write tool cannot return `created` / `drafted` without a consumed one
(§8.6). Reading the envelope is therefore the same question as "was this performed after a human
confirmation", asked where the answer is written down.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hrmosaic.core.models import UNRENDERED_ENVELOPES
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

#: The block type a statement of the reader's own HR record is reported in (UX W7, JX2-05 =
#: cpux2-4, Addendum 3): a balance, a tenure, notice arithmetic, a compliance verdict. Neither
#: company policy nor advice, so `_turn.html` renders it under *"From your HR record"* and outside
#: the suggestions group and its *"guidance, not company policy"* footnote. The model may type a
#: block `record` itself (`synthesize.j2` rule 6b); `apply()` is the deterministic backstop for the
#: one it types `recommendation` instead.
RECORD = "record"

#: What happens next once a write of this queue has been performed — said in the `performed`
#: statement, because the ticket *is* the request and the reader must not be sent to file another
#: (UX W7, Addendum 3). Only the queue whose design says so; every other statement is unchanged.
NEXT_EVENT: dict[str, str] = {
    "hr-timeoff": "Your manager's written approval is the next step.",
}

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
    "create_mock_hr_ticket": ("submit", "file", "open", "raise", "create", "log", "enter"),
    "draft_hr_email": ("send", "write", "compose", "draft", "email"),
}

#: The verbs that open a directive clause, for the `record` backstop's "no imperative" half: every
#: write tool's own IMPERATIVES, plus the verbs an HR answer uses when it tells the reader to do
#: something. *"note"* and *"see"* are deliberately absent — *"Note that you have 13.5 days left"*
#: is a framing verb in front of a statement of record, not an instruction.
DIRECTIVE_VERBS: frozenset[str] = frozenset(
    {
        *(verb for verbs in IMPERATIVES.values() for verb in verbs),
        "add",
        "aim",
        "allow",
        "apply",
        "arrange",
        "ask",
        "attach",
        "avoid",
        "begin",
        "book",
        "bring",
        "budget",
        "call",
        "check",
        "choose",
        "complete",
        "confirm",
        "consider",
        "contact",
        "coordinate",
        "decide",
        "discuss",
        "double-check",
        "ensure",
        "escalate",
        "expect",
        "factor",
        "fill",
        "finish",
        "follow",
        "get",
        "give",
        "go",
        "hold",
        "include",
        "inform",
        "keep",
        "let",
        "look",
        "make",
        "monitor",
        "notify",
        "obtain",
        "pick",
        "plan",
        "prepare",
        "print",
        "provide",
        "quote",
        "reach",
        "read",
        "reconfirm",
        "record",
        "remember",
        "reply",
        "report",
        "request",
        "respond",
        "return",
        "review",
        "save",
        "schedule",
        "secure",
        "seek",
        "select",
        "set",
        "sign",
        "speak",
        "start",
        "stop",
        "take",
        "talk",
        "tell",
        "track",
        "try",
        "update",
        "upload",
        "use",
        "verify",
        "visit",
        "wait",
        "watch",
    }
)

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
    r"you must|you should|you need to|you will need to|you have to|you can|you could|you may|"
    r"you might|you will want to|you'll want to|you would|you'd|it is best to|it's best to|"
    r"it would be wise to|we recommend that you|we recommend|i recommend that you|i recommend|"
    r"i suggest that you|i suggest|i'd suggest|i'd recommend)\s+"
)

#: A sentence boundary: terminal punctuation, then whitespace, then something that begins a
#: sentence. *"13.5 days"* and *"e.g. this"* do not split; *"MosaicOne. Your"* does.
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[\"'“‘(\[A-Z0-9])")

#: A number as prose writes it: `13.5`, `45`, the `3` of `3-day`, never the `2` of `v2.1`.
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?!\w|\.\d)")

#: The quote marks a clause may open with, stripped before its first word is read.
_QUOTES = "\"'()“”‘’"


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
        queue = str(self.body.get("queue") or "")
        label = queue_label(queue)
        team = label if label == QUEUE_FALLBACK else f"the {label}"
        statement = f"Done — your request is with {team}. Reference {self.write_id}."
        # …and, for a PTO ticket, the honest next event (UX W7, Addendum 3): the ticket is the
        # request, and what the reader is waiting on now is their manager, not a form.
        follow = NEXT_EVENT.get(queue)
        return f"{statement} {follow}" if follow else statement


@dataclass
class Outcome:
    """The blocks and next steps after the step, and what it did to them."""

    blocks: list[dict[str, Any]]
    #: The next steps that survived, in order. The same list when nothing contradicted the write.
    next_steps: list[str] = field(default_factory=list)
    #: Whether the outcome block was inserted — true on every turn that performed a write, since
    #: the `performed` statement is now the turn's one account of it whatever the model wrote.
    stated: bool = False
    #: Indexes **into the model's own block list**, before the outcome block is inserted, of the
    #: blocks this step took out: the model's own account of the write (any block naming the id)
    #: and any escalation denying it. Both are replaced by the one statement at the top.
    replaced: list[int] = field(default_factory=list)
    #: Indexes into the model's own `next_steps` of the directives that were dropped.
    dropped: list[int] = field(default_factory=list)
    #: `(index into the model's own block list, sentence)` for every sentence removed from a block
    #: because it directed the reader to do what the write did (UX W7, Addendum 3).
    trimmed: list[tuple[int, str]] = field(default_factory=list)
    #: Indexes of the blocks that were nothing but such sentences, and so were dropped whole.
    emptied: list[int] = field(default_factory=list)
    #: Indexes of the blocks retyped `record` — the reader's own data, out from under the
    #: *"not company policy"* footnote (UX W7, JX2-05).
    retyped: list[int] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return (
            self.stated
            or bool(self.replaced)
            or bool(self.dropped)
            or bool(self.trimmed)
            or bool(self.emptied)
            or bool(self.retyped)
        )


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


def _clause_heads(text: str) -> Iterator[tuple[str, str]]:
    """Each clause of `text`, lower-cased with its lead-in stripped, and the word it opens with."""
    for clause in _CLAUSE.split(text.lower()):
        head = clause.strip()
        while match := _LEAD_IN.match(head):
            head = head[match.end() :]
        words = head.split()
        yield head, (words[0].strip(_QUOTES) if words else "")


def directs(text: str, tool_name: str) -> bool:
    """Does this text tell the reader to go and do what `tool_name` has already done?

    The imperative twin of `denies`: an imperative verb for the tool at the head of a clause, and
    one of that tool's own objects in the same clause. Both halves are needed — "Your manager will
    receive the request" has the object and no imperative, "Open the policy" has the imperative and
    no object, and neither contradicts a ticket that exists. Since UX W7 (Addendum 3) it is put to
    every sentence of every block as well as to every next step.
    """
    verbs = IMPERATIVES.get(tool_name, ())
    objects = ACTION_OBJECTS.get(tool_name, ())
    if not verbs or not objects:
        return False
    return any(first in verbs and any(word in head for word in objects) for head, first in _clause_heads(text))


def opens_with_a_directive(text: str) -> bool:
    """Does any clause of `text` open with a directive verb — is this advice, or a statement?"""
    return any(first in DIRECTIVE_VERBS for _head, first in _clause_heads(text))


def sentences(text: str) -> list[str]:
    """`text` as the sentences a reader hears it in."""
    return [part for part in _SENTENCE.split(text) if part.strip()]


def trim(text: str, write: PerformedWrite) -> tuple[str, list[str]]:
    """`text` without the sentences that direct the reader to do what `write` did — and those sentences.

    Unchanged bytes when nothing directs: the join only happens where a sentence came out.
    """
    kept: list[str] = []
    removed: list[str] = []
    for sentence in sentences(text):
        # A sentence naming the id is talking about the request that exists, not asking for another.
        if write.write_id in sentence or not directs(sentence, write.tool_name):
            kept.append(sentence)
        else:
            removed.append(sentence)
    if not removed:
        return text, []
    return " ".join(part.strip() for part in kept), removed


def numbers_in(text: str) -> set[float]:
    """Every number `text` states, as a value: `13.5`, the `3` of `3-day`, the `8` of `8 business days`."""
    return {float(token) for token in _NUMBER.findall(text)}


def envelope_numbers(envelopes: Iterable[Any]) -> set[float]:
    """Every numeric field of every *data* tool result on the turn, however deeply nested.

    A search envelope is not the reader's record — its hits carry ranks and scores that would match
    a *"1"* in any sentence — so `UNRENDERED_ENVELOPES` (the tools whose results the prompt does not
    show as employee context either) are skipped. Booleans are not numbers.
    """
    found: set[float] = set()

    def walk(node: Any) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, int | float):
            found.add(float(node))
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for envelope in envelopes:
        if getattr(envelope, "name", "") in UNRENDERED_ENVELOPES:
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        walk(body)
    return found


def states_the_record(text: str, numbers: set[float]) -> bool:
    """The backstop's rule (UX W7, JX2-05): no clause opens with a directive verb, and the text states
    a number a data tool on this turn returned — a balance, a tenure in months, notice days."""
    return bool(numbers) and not opens_with_a_directive(text) and bool(numbers_in(text) & numbers)


def apply(
    blocks: Sequence[Mapping[str, Any]],
    envelopes: Iterable[Any],
    *,
    next_steps: Sequence[str] = (),
    policy_claims: Sequence[int] = (),
) -> Outcome:
    """The pure rule: state the write first, drop what contradicts it, and type the reader's own
    record as such. Mutates nothing.

    `policy_claims` are the indexes (into `blocks`) G3 relabelled from an uncited `policy_fact`:
    policy claims wearing the wrong label, which the `record` backstop must leave alone.
    """
    write = performed_write(envelopes)
    # Only this step may claim a write happened, and it claims it from the tool result. A model
    # that typed a block `performed` is asserting the outcome of a call whose result it has not
    # been shown, so the claim is demoted to what it actually is — advice (UX W6).
    body = [{**block, "type": "recommendation"} if block.get("type") == PERFORMED else dict(block) for block in blocks]
    steps = [str(step) for step in next_steps]
    claims = set(policy_claims)
    numbers = envelope_numbers(envelopes)

    kept_steps: list[str] = []
    dropped: list[int] = []
    replaced: list[int] = []
    trimmed: list[tuple[int, str]] = []
    emptied: list[int] = []
    retyped: list[int] = []
    survivors: list[tuple[int, dict[str, Any]]] = []

    if write is not None:
        for index, step in enumerate(steps):
            # A step naming the id is talking about the ticket that exists, not asking for another.
            if write.write_id in step or not directs(step, write.tool_name):
                kept_steps.append(step)
            else:
                dropped.append(index)
    else:
        kept_steps = steps

    for index, block in enumerate(body):
        text = str(block.get("text") or "")
        if write is not None:
            # **One account of the write per turn, and it is the statement below** (P29). A model
            # block that names the id is the model's account of a write it cannot see the result
            # of — it was left in place while this step stayed silent, and the live 2026-09-15 turn
            # reported `MOCK-HR-000007` in a `recommendation`, under *"What I suggest you do"* and
            # its *"guidance, not company policy"* footnote (JX-R1 = cpux-re-1). It is removed here
            # whatever its type, and so is an escalation denying the action, which the statement
            # has already answered.
            if write.write_id in text or (block.get("type") == "escalation" and denies(text, write.tool_name)):
                replaced.append(index)
                continue
            # **No sentence tells the reader to go and do it either** (UX W7, Addendum 3).
            text, removed = trim(text, write)
            if removed:
                trimmed.extend((index, sentence) for sentence in removed)
                if not text:
                    emptied.append(index)
                    continue
                block = {**block, "text": text}
                # What is left of a block that mixed a directive about the write with statements
                # is the reader's record, unless it is a policy claim or still advice.
                if block.get("type") == "recommendation" and index not in claims and not opens_with_a_directive(text):
                    block["type"] = RECORD
                    retyped.append(index)
        # **The reader's own data is not advice** (UX W7, JX2-05 = cpux2-4): a `recommendation`
        # with no directive in it that states a number a data tool on this turn returned.
        if block.get("type") == "recommendation" and index not in claims and states_the_record(text, numbers):
            block = {**block, "type": RECORD}
            retyped.append(index)
        survivors.append((index, block))

    result = [block for _index, block in survivors]
    if write is None:
        return Outcome(blocks=result, next_steps=kept_steps, retyped=retyped)
    statement = {"type": PERFORMED, "text": write.statement, "citations": []}
    return Outcome(
        blocks=[statement, *result],
        next_steps=kept_steps,
        stated=True,
        replaced=replaced,
        dropped=dropped,
        trimmed=trimmed,
        emptied=emptied,
        retyped=retyped,
    )


__all__ = [
    "ACTION_OBJECTS",
    "ACTION_WORDS",
    "DENIALS",
    "DIRECTIVE_VERBS",
    "IMPERATIVES",
    "NEXT_EVENT",
    "PERFORMED",
    "RECORD",
    "STEP_NAME",
    "WRITE_SUCCESS",
    "Outcome",
    "PerformedWrite",
    "apply",
    "denies",
    "directs",
    "envelope_numbers",
    "numbers_in",
    "opens_with_a_directive",
    "performed_write",
    "sentences",
    "states_the_record",
    "trim",
]
