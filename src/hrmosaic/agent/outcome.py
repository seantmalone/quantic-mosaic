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
from datetime import date
from typing import Any

from hrmosaic.agent import dates as date_consistency
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

#: The same verbs with the prefix English puts in front of *doing it again* (W8, C01). "Resubmit
#: the request in MosaicOne once Dana agrees" walked straight past a list of bare stems.
RE_PREFIXES = ("re", "re-")

#: The modal frames that make a statement an instruction without the imperative mood (W8, C01).
#: *"You must still submit the formal PTO request in MosaicOne"* is a directive; the sentence never
#: opens with a verb, so every clause-head test in the world misses it.
DIRECTIVE_MODALS = (
    "must",
    "need to",
    "needs to",
    "should",
    "have to",
    "has to",
    "are required to",
    "will need to",
    "are expected to",
    "ought to",
)

#: Objects that stand in for the thing the tool made, when the sentence does not name it again.
#: *"Submit it in MosaicOne for your manager written approval."* is the same instruction as
#: *"Submit the request …"*, and it was surviving (W8, C01).
PRONOUN_OBJECTS: frozenset[str] = frozenset({"it", "this", "that", "these", "those", "them", "one"})

#: A preposition where the object should be means the object was elided — "Submit in MosaicOne so
#: your manager can approve it" — which is still an instruction to go and file it.
PREPOSITIONS: frozenset[str] = frozenset(
    {"in", "into", "to", "on", "at", "for", "via", "through", "with", "from", "under", "by", "onto"}
)

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

#: A sentence whose subject is the reader (W8, C15). *"Your manager is Dana."* is a statement of
#: the reader's own record however few numbers it contains, and it had been shipping under
#: *"Recommendation — not company policy"*.
_ABOUT_THE_READER = re.compile(r"^\W*(?:you|your|you're|yours|you've|you'll)\b", re.IGNORECASE)

#: The predicates that turn a sentence naming the write's id into the model's own claim that the
#: write happened (W8, C01, and P29 before it). The `performed` statement is the turn's one
#: account of the write; this is what a second account looks like.
_CLAIMS_THE_WRITE = re.compile(
    r"\b(?:has been|have been|had been|was|were|is|are|i(?:'ve| have)?)\s+(?:successfully\s+)?"
    r"(?:created|opened|open|filed|raised|submitted|logged|entered|drafted|sent|generated)\b"
    r"|^\W*done\b",
    re.IGNORECASE,
)

#: Envelope fields whose value is prose rather than a record value (W8, C15). A requirement's
#: `text` is a sentence of company policy; counting it as one of the reader's own scalars would
#: retype every faithful `policy_fact` as the reader's data.
PROSE_FIELDS: frozenset[str] = frozenset(
    {"text", "reason", "quote", "snippet", "hint", "note", "summary", "details", "human_summary", "prompt_shown"}
)

#: How long a scalar may be and still be a value rather than a sentence (W8, C15).
MAX_SCALAR_CHARS = 48

#: …and how short it may be and still be a value rather than a word that happens to be in a
#: sentence (W8 fix round). `status: "met"` matched "met", "meter" and "metric" as a substring.
MIN_SCALAR_CHARS = 4

#: The envelope keys whose string value is the reader's own record (W8 fix round, W7-review I3).
#: Admitting every short string admitted `verdict: "conditional"`, `role: "Director"` and
#: `department: "Engineering"`, so advice naming a director was retyped as the reader's data and a
#: cited policy sentence lost its citation. Names, the office, the work arrangement, ids — and an
#: ISO date under any key, because that is how a date reaches an envelope.
SCALAR_KEYS: frozenset[str] = frozenset(
    {
        "preferred_name",
        "legal_name",
        "first_name",
        "last_name",
        "name",
        "to_name",
        "city",
        "office_name",
        "work_arrangement",
        "ticket_id",
        "draft_id",
    }
)

#: The key a block carries while it is a policy claim G3 demoted from an uncited `policy_fact`
#: (W8 fix round, W7-review I1). Positional indexes into the block list drifted as soon as the
#: merge and restatement steps removed a block ahead of one, so the exemption from the record
#: backstop protected the wrong block; the marker travels with the block through every step's
#: `dict(block)` copy and is stripped before the answer is validated.
POLICY_CLAIM = "_policy_claim"

#: An ISO date, so the human form of the same day joins the scalar set.
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

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


def filing_verbs(tool_name: str) -> tuple[str, ...]:
    """The tool's own imperative verbs, and the same verbs meaning *do it again* (W8, C01)."""
    verbs = IMPERATIVES.get(tool_name, ())
    return (*verbs, *(f"{prefix}{verb}" for verb in verbs for prefix in RE_PREFIXES))


def _acts_on_the_write(clause: str, objects: Sequence[str]) -> bool:
    """Does this clause's opening verb act on the thing the tool made?

    Three shapes count. The tool's own noun anywhere in the clause, however modified — *"submit the
    formal PTO request"*; a pronoun standing in for it — *"submit it"*; and an object elided
    straight into a preposition — *"submit in MosaicOne"*, *"log into MosaicOne"*. A clause that
    opens with the verb and acts on something else — *"open the policy"*, *"create a calendar
    hold"* — is not about the write and survives.
    """
    words = [word.strip(_QUOTES + ",.;:") for word in clause.split()[1:]]
    if not words:
        return False
    # A pronoun or a preposition counts only in the object's own position, right after the verb:
    # "submit it", "log into MosaicOne". Further along, "for those dates" is not an object at all.
    if words[0] in PREPOSITIONS or words[0] in PRONOUN_OBJECTS:
        return True
    return any(word in objects for word in words)


def _imperative(text: str, tool_name: str) -> bool:
    """A clause in the imperative mood whose object is the thing the tool made.

    Three objects count, and the second and third are what UX W7's lexical list missed: the tool's
    own nouns ("submit the request"), a pronoun standing in for them ("submit it"), and an elided
    object in front of a preposition ("submit in MosaicOne"). *"Open the policy and read section 4"*
    has an imperative and an object that is neither, so it survives — it names the topic, not the
    ticket.
    """
    verbs = filing_verbs(tool_name)
    objects = ACTION_OBJECTS.get(tool_name, ())
    if not verbs or not objects:
        return False
    return any(first in verbs and _acts_on_the_write(head, objects) for head, first in _clause_heads(text))


def directs(text: str, tool_name: str) -> bool:
    """Does this text tell the reader to go and do what `tool_name` has already done?

    **Grammatical, not lexical** (W8, C01). UX W7 shipped an imperative-verb list crossed with an
    object list, and the model's own recorded output already walked past it four ways: a pronoun
    object, a modal frame, a `re-` prefix and an infinitival. The review executed HEAD's own
    `directs()` against those wordings and got `False` for all four. So the question is asked about
    the *shape* of the sentence instead, in four ways, any one of which is a directive:

    1. the imperative mood, with the tool's object, a pronoun for it, or no object at all;
    2. a directive modal aimed at the reader — "you must / need to / should / have to … submit";
    3. `still` beside a filing verb — the hedge that concedes the write and directs anyway;
    4. an infinitival addressed back to the reader — "To submit the request … yourself".

    "Your manager will receive the request" and "Watch for your manager's approval in MosaicOne"
    are none of these and survive, which is the whole point: an answer after a performed write
    should still be able to say what happens next.
    """
    verbs = filing_verbs(tool_name)
    if not verbs or not ACTION_OBJECTS.get(tool_name):
        return False
    lowered = text.lower()
    named = any(re.search(rf"\b{verb}\b", lowered) for verb in verbs)
    if named:
        # `still` beside a filing verb is the hedge that concedes the write and directs anyway —
        # when it is aimed at the reader. *"The ticket is still open"* is a statement (W7-review
        # Minor), so the clause has to be second-person as well.
        if "still" in lowered and re.search(r"\byou\b", lowered):
            return True
        if re.search(rf"\byou\b[^.!?]*?\b(?:{'|'.join(DIRECTIVE_MODALS)})\b", lowered):
            return True
        if re.search(rf"\bto\s+(?:{'|'.join(verbs)})\b[^.!?]*\byourself\b", lowered):
            return True
    return _imperative(text, tool_name)


def opens_with_a_directive(text: str) -> bool:
    """Does any clause of `text` open with a directive verb — is this advice, or a statement?"""
    return any(first in DIRECTIVE_VERBS for _head, first in _clause_heads(text))


def sentences(text: str) -> list[str]:
    """`text` as the sentences a reader hears it in."""
    return [part for part in _SENTENCE.split(text) if part.strip()]


def claims_the_write(text: str, write: PerformedWrite) -> bool:
    """Is this sentence the **model's** account of the write, rather than a use of its id?

    The precedence the two rules need, decided here (W8, Addendum 4). Before this, `apply()`
    removed any block whose text named the write id, so `trim()`'s "a sentence naming the id is
    kept" branch could never run — the block was already gone — and the stand-in test asserted the
    opposite of what shipped. Removal is sentence-level now, and the id alone is no longer the
    test:

    * *"HR ticket MOCK-HR-000007 has been created."* is the model asserting the outcome of a call
      it was never shown the result of, printed under *"Suggestions are guidance, not company
      policy"*. There is exactly one account of a write per turn and it is the `performed`
      statement (P29), so this goes.
    * *"Dana Whitfield approves request MOCK-HR-000123."* names the same id to say what happens
      next. It survives, and so does a directive that names it — that one is talking about the
      request that exists rather than asking for another.
    """
    return write.write_id in text and bool(_CLAIMS_THE_WRITE.search(text))


def trim(text: str, write: PerformedWrite) -> tuple[str, list[str]]:
    """`text` without the sentences a performed write contradicts — and those sentences.

    Two kinds come out: the model's own account of the write (`claims_the_write`), and a sentence
    that tells the reader to go and do what the write did (`directs`). A sentence naming the id
    that does neither is kept. Unchanged bytes when nothing comes out: the join only happens where
    a sentence was removed.
    """
    kept: list[str] = []
    removed: list[str] = []
    for sentence in sentences(text):
        if claims_the_write(sentence, write):
            removed.append(sentence)
        elif write.write_id in sentence or not directs(sentence, write.tool_name):
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


def envelope_scalars(envelopes: Iterable[Any]) -> set[str]:
    """Every short scalar value a *data* tool result carried, lower-cased (W8, C15).

    The UX W7 backstop asked for a number, so *"Your manager is Dana."* and *"Your office is
    Boston."* could never qualify and `record` was emitted zero times in 512 turns. A name, a city,
    a work arrangement and an ISO date are the reader's own record just as a balance is — but a
    requirement's `text` is a sentence of company policy, so `PROSE_FIELDS` and a length cap keep
    prose out of the set. ISO dates contribute the human form as well, because that is how an
    answer writes them.
    """
    found: set[str] = set()

    def walk(node: Any, key: str = "") -> None:
        if isinstance(node, str):
            value = node.strip()
            if key in PROSE_FIELDS or not value or len(value) > MAX_SCALAR_CHARS:
                return
            if _ISO_DATE.fullmatch(value):
                found.add(value.casefold())
                found.add(date_consistency.human_date(date.fromisoformat(value)).casefold())
            elif key in SCALAR_KEYS and len(value) >= MIN_SCALAR_CHARS:
                found.add(value.casefold())
        elif isinstance(node, dict):
            for name, value in node.items():
                walk(value, str(name))
        elif isinstance(node, list):
            for value in node:
                walk(value, key)

    for envelope in envelopes:
        if getattr(envelope, "name", "") in UNRENDERED_ENVELOPES:
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        walk(body)
    return found


def about_the_reader(text: str) -> bool:
    """Is this sentence about the person reading it? *"Your manager is Dana."* is (W8, C15)."""
    return bool(_ABOUT_THE_READER.match(text))


def states_the_record(
    text: str, numbers: set[float], scalars: Iterable[str] = (), *, scalars_only: bool = False
) -> bool:
    """The backstop's rule (UX W7, JX2-05; widened W8, C15): no clause opens with a directive verb,
    and the text states a value a data tool on this turn returned — a balance, a tenure, a notice
    figure, a manager's name, an office, a date.

    `scalars_only` drops the numeric half. It is what a **cited** block is judged by: *"You accrue
    1.50 days of PTO per month"* states a number the envelope also carries and is still company
    policy, written in the second person; *"Your manager is Dana"* names a person only the
    reader's own record knows.
    """
    if opens_with_a_directive(text):
        return False
    if not scalars_only and numbers and numbers_in(text) & numbers:
        return True
    lowered = text.casefold()
    # Whole words: "Dana" is not in "Danaher", and the four-character floor above keeps "hybrid"
    # while dropping the "met" that matched "metric".
    return any(re.search(rf"(?<!\w){re.escape(scalar)}(?!\w)", lowered) for scalar in scalars)


def _record_split(
    block: Mapping[str, Any],
    is_policy_claim: bool,
    *,
    numbers: set[float],
    scalars: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    """`(what is left of the block, the `record` block split out of it, whether anything moved)`.

    The reader's own record is neither policy nor advice, and it had been shipping as both. Two
    shapes are handled (W8, C15):

    * a `recommendation` that is nothing but the reader's record is retyped where it stands — the
      UX W7 backstop, now reading strings and dates as well as numbers;
    * a block that **mixes** them gives up only the sentences that are the record. A `policy_fact`
      does so only for a sentence whose subject is the reader — *"Your manager is Dana"* under a
      citation to the approval matrix is the reader's record wearing a policy's authority, and the
      citation leaves with it — because a policy sentence that merely quotes a threshold the
      envelope also carries is still policy.

    A block G3 demoted from an uncited `policy_fact` is exempt throughout: that one is a policy
    claim wearing the wrong label, not a record.
    """
    kind = str(block.get("type") or "")
    text = str(block.get("text") or "")
    if is_policy_claim or block.get(POLICY_CLAIM) or kind not in ("recommendation", "policy_fact") or not text:
        return dict(block), None, False

    def is_record(sentence: str) -> bool:
        # A **cited** block gives up only a sentence about the reader that names a value only the
        # reader's record knows and carries **no number at all**. A policy sentence written in the
        # second person — *"You accrue 1.50 days of PTO per month"* — is still policy, and so is
        # *"You have completed 3 years 9 months of service, exceeding the 12-month minimum"*: the
        # number in it is the policy's, and retyping the sentence would strip the citation that is
        # the reader's only way to check it (W8 fix round, W7-review I3).
        if kind == "policy_fact":
            return (
                about_the_reader(sentence)
                and not numbers_in(sentence)
                and states_the_record(sentence, numbers, scalars, scalars_only=True)
            )
        return states_the_record(sentence, numbers, scalars)

    parts = sentences(text)
    directives = [sentence for sentence in parts if opens_with_a_directive(sentence)]
    records = [sentence for sentence in parts if sentence not in directives and is_record(sentence)]
    if directives and records:
        # A **mixed** block gives up only its record half; the advice keeps its own type and its
        # place. Splitting a block that is all record would fragment one statement into two.
        rest = [sentence for sentence in parts if sentence not in records]
        kept = {**block, "text": " ".join(part.strip() for part in rest)}
        return kept, {"type": RECORD, "text": " ".join(part.strip() for part in records), "citations": []}, True
    if not directives and is_record(text):
        return {**block, "type": RECORD, "citations": []}, None, True
    return dict(block), None, False


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
    # been shown, so the claim is demoted to what it actually is — advice (UX W6). On a turn that
    # DID perform a write the block goes entirely: the statement below is re-emitted from the tool
    # result, and re-reading a previous run's own statement as model prose is what made this step
    # non-idempotent (W8).
    typed_performed = [index for index, block in enumerate(blocks) if block.get("type") == PERFORMED]
    body = [{**block, "type": "recommendation"} if block.get("type") == PERFORMED else dict(block) for block in blocks]
    steps = [str(step) for step in next_steps]
    claims = set(policy_claims)
    numbers = envelope_numbers(envelopes)
    scalars = envelope_scalars(envelopes)

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
            if claims_the_write(step, write):
                dropped.append(index)
            elif write.write_id in step or not directs(step, write.tool_name):
                kept_steps.append(step)
            else:
                dropped.append(index)
    else:
        kept_steps = steps

    for index, block in enumerate(body):
        text = str(block.get("text") or "")
        if write is not None:
            # An escalation denying the very action the result shows was performed is answered by
            # the statement below, and goes whole: it is one claim, not a paragraph (P22). So does
            # a block the model typed `performed`, and so does this step's own statement from a
            # previous pass.
            if index in typed_performed or (block.get("type") == "escalation" and denies(text, write.tool_name)):
                replaced.append(index)
                continue
            # **One account of the write per turn, and no sentence sends the reader to repeat it**
            # (P29; UX W7 Addendum 3; W8 C01). Sentence-level, so a sentence that uses the id to
            # say what happens next survives while the model's own claim that the write happened
            # does not — see `claims_the_write` for the precedence.
            text, removed = trim(text, write)
            if removed:
                # Two removals, two records. A sentence that was the model's own account of the
                # write is `replaced` — the statement below takes its place; a sentence that
                # directed the reader to go and file it is `trimmed`.
                claimed = [sentence for sentence in removed if claims_the_write(sentence, write)]
                trimmed.extend((index, sentence) for sentence in removed if sentence not in claimed)
                if claimed:
                    replaced.append(index)
                if not text:
                    if not claimed:
                        emptied.append(index)
                    continue
                block = {**block, "text": text}
                # What is left of a block that mixed a directive about the write with statements
                # is the reader's record, unless it is a policy claim or still advice.
                if block.get("type") == "recommendation" and index not in claims and not opens_with_a_directive(text):
                    block["type"] = RECORD
                    retyped.append(index)
        # **The reader's own data is not advice** (UX W7, JX2-05 = cpux2-4; widened W8, C15): a
        # block that states a value a data tool on this turn returned, split at sentence
        # boundaries so a mixed block gives up only the half that is the reader's record.
        block, record, split = _record_split(block, index in claims, numbers=numbers, scalars=scalars)
        if split:
            retyped.append(index)
        if block is not None:
            survivors.append((index, block))
        if record is not None:
            survivors.append((index, record))

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
    "DIRECTIVE_MODALS",
    "DIRECTIVE_VERBS",
    "IMPERATIVES",
    "MAX_SCALAR_CHARS",
    "MIN_SCALAR_CHARS",
    "POLICY_CLAIM",
    "NEXT_EVENT",
    "PERFORMED",
    "PREPOSITIONS",
    "PRONOUN_OBJECTS",
    "PROSE_FIELDS",
    "RECORD",
    "RE_PREFIXES",
    "SCALAR_KEYS",
    "STEP_NAME",
    "WRITE_SUCCESS",
    "Outcome",
    "PerformedWrite",
    "about_the_reader",
    "apply",
    "claims_the_write",
    "denies",
    "directs",
    "envelope_numbers",
    "envelope_scalars",
    "filing_verbs",
    "numbers_in",
    "opens_with_a_directive",
    "performed_write",
    "sentences",
    "states_the_record",
    "trim",
]
