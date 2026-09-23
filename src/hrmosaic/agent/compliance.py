"""Compliance restatement — the answer may not contradict the engine (spec §7.4; W8, C03).

**Not a guardrail.** No `guardrail` span, no G-number, no change to the six rules of §7.4. One
deterministic step after synthesis, beside `outcome.py` and `dates.py`, reading nothing but the
turn's own `check_policy_compliance` envelope.

**The failure it exists for**, live on 2026-09-15, demo 2, persona E1042:

    engine   pto.request.notice — met: true — "computed.notice_business_days is 8;
                                              the policy value is 5 (gte)."
    answer   "Your request for 15–17 September does not meet the 5 business day notice
              requirement (only 8 calendar days from today, 15 September)."

The same eight the engine used to *satisfy* the rule, relabelled as calendar days, against an
anchor date the sentence's own words refute, to reach the opposite verdict — and then the reader
was sent to chase a waiver she did not need. The deterministic layer had already decided; nothing
made the written answer agree with it. The replacement is built from the requirement's reader
`label` in `corpus/rules.yml` — *"Your notice before the first day off, in business days, is 8;
the policy asks for at least 5."* — and never from the subject key: the first version of this
step de-underscored `computed.notice_business_days` into prose, and that reached the chat
surface on every finished PTO turn (re-audit #3, JX3-01).

So for every requirement the engine evaluated, any sentence of any block or step that is **about
that requirement's subject** and whose **polarity opposes the row** is replaced by the row's own
result, in the reader's voice. Three rules and nothing else:

* `met` — a sentence that denies it is replaced;
* `unmet` — a sentence that asserts it is replaced;
* `not_stated` — a sentence that concludes **either way** is replaced by "I could not check …",
  because a requirement nobody evaluated has no verdict to state (W8, C05).

**Two sentences are wrong without opposing anything, and each has its own rule.** A threshold the
request has already outgrown — *"expenses up to USD 2,500 are approved by your manager"* on a USD
3,000 claim — is `correct_ceilings` (W8, C07); and a sentence handing the decision to the lower
authority while the engine has that authority's own limit **unmet** is `correct_authority` (G5c, gap
30). Both are replaced by the engine's own routing sentence, which is the reason of the highest
approval tier the request actually reached.

**When it is unsure it leaves the sentence alone and says so.** A sentence carrying both polarities
("meets the notice rule but does not meet the balance rule") is one this step cannot cut safely, so
it is recorded in `unverified` and shipped untouched. A repair that is not certain is worse than
the prose it replaces.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hrmosaic.agent.outcome import about_the_reader, sentences

#: What the step is called where it is named — reports, the spec paragraph beside §7.4's table.
#: Deliberately not a `G<n>`: the six guardrails are a closed set.
STEP_NAME = "compliance_restatement"

#: The tool whose result this step reads, and the only one.
COMPLIANCE_TOOL = "check_policy_compliance"

#: The subjects a requirement can be *about*, matched against its id and its text. A sentence has
#: to name one of them to be a sentence about that requirement — which is what keeps the step off
#: every other sentence in the answer. Ordered, because the first match names the row for a reader.
SUBJECT_WORDS: tuple[str, ...] = (
    "notice",
    "balance",
    "blackout",
    "tenure",
    "destination",
    "duration",
    "device",
    "approval",
    "receipt",
    "deadline",
    "eligibility",
    "waiting period",
    "accrual",
    "country",
    "limit",
    "threshold",
)

#: A sentence denies its subject when it carries one of these and no assertion.
NEGATIVE: tuple[str, ...] = (
    "does not",
    "doesn't",
    "do not",
    "don't",
    "not met",
    "unmet",
    "is not",
    "isn't",
    "are not",
    "aren't",
    "fails",
    "fail to",
    "falls short",
    "short of",
    "insufficient",
    "not sufficient",
    "not enough",
    "cannot",
    "can't",
    "lacks",
    "below the",
    "under the required",
)

#: …and asserts it when it carries one of these and no denial.
POSITIVE: tuple[str, ...] = (
    "meets",
    "is met",
    "are met",
    "satisfies",
    "satisfied",
    "complies",
    "is compliant",
    "sufficient",
    "is covered",
    "covers",
    "exceeds",
    "in line with",
    "clears",
    "qualifies",
)

#: How an operator reads to a person. The engine's `reason` is machine prose — *"the policy value
#: is 5 (gte)"* — and a reader is owed the relation in words.
RELATIONS: dict[str, str] = {
    "gte": "at least",
    "gt": "more than",
    "lte": "no more than",
    "lt": "fewer than",
    "eq": "exactly",
    "in": "one of",
    "date_gte": "on or after",
    "date_lte": "on or before",
}

#: How a boolean value is said to a person. *"is yes"* is not a sentence, so a boolean row takes
#: its own template below.
IN_WORDS: dict[str, str] = {"true": "yes", "false": "no"}

#: A label whose head noun is a count — "days since the transaction", "onsite days each week" — takes
#: a plural verb (W8 minor round, NEW-1): *"Your days since the transaction are 12"*, never *"is"*.
#: The head is the first noun of the label's pre-comma phrase, and in this vocabulary a plural head
#: is always a unit of time in the first two words.
_PLURAL_HEAD = re.compile(r"^(?:\w+\s+)?(?:days|months|weeks|hours)\b", re.IGNORECASE)


def _verb(label: str) -> str:
    head = label.split(",", 1)[0].strip()
    return "are" if _PLURAL_HEAD.match(head) else "is"


#: *"up to USD 2,500"* — a ceiling quoted as though it were the rule that applies (W8, C07). The
#: `expenses-002` answer quoted the manager's limit on a USD 3,000 claim and closed by routing the
#: report to the manager, which is the tier the amount had already left.
CEILING = re.compile(
    r"\bup to\s+(?:USD|EUR|GBP)\s*(?P<value>[\d,]+(?:\.\d+)?)"
    r"|\bup to\s+[$€£]\s?(?P<symbol>[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)

#: The subject whose value is the amount the question asked about.
AMOUNT_SUBJECT = "parameters.amount_usd"

#: *"your manager Dana can approve it"* — the decision handed to the lower authority (G5c, gap 30).
#: Both voices, because both were written: the active one, with up to four words of name or title
#: between the role and its verb, and the passive *"approved by your manager"*. `\bcan\b` does not
#: match inside *"cannot"*, so a sentence that **denies** the authority is left alone.
LOWER_AUTHORITY = re.compile(
    r"\b(?:your|the|a|their)\s+(?:direct\s+|line\s+|reporting\s+)?manager\b"
    r"(?:\s+[\w'’-]+){0,4}?\s+(?:can|may|is able to|has the authority to)\s+"
    r"(?:approve|authorise|authorize|sign)\b"
    r"|\b(?:approved|authorised|authorized|signed\s+off)\s+by\s+(?:your|the|a|their)\s+"
    r"(?:direct\s+|line\s+|reporting\s+)?manager\b",
    re.IGNORECASE,
)

#: A sentence that concludes about **this request** rather than about the rule in general (W8 fix
#: round, W7-review I4). `pto.request.manager_approval` is a `manual` row and therefore
#: `not_stated` on every PTO turn; without this, *"Verbal approval is insufficient."* — a true,
#: cited policy sentence — was replaced by "I could not check the approval requirement."
THIS_REQUEST = re.compile(
    r"\b(?:this|your)\s+(?:request|requirement|claim|trip|application|leave|case)\b", re.IGNORECASE
)

#: The shape `rules.py::_evaluate_requirement` writes a decided reason in.
REASON = re.compile(
    r"^(?P<subject>[\w.]+) is (?P<value>.+?); the (?P<source>policy|request) value is "
    r"(?P<expected>.+?) \((?P<op>\w+)\)\.$"
)

#: A label's unit tail — ", in business days", ", in US dollars" — carried onto the values instead
#: of left dangling as an appositive (UX W9, npo5-02 / CPUX4-03): *"Your PTO balance is 0.25 days;
#: your request is for 3 days."*
_UNIT_TAIL = re.compile(r",\s*in\s+(?P<unit>[^,]+)$")


#: The block type an engine reason is said in (W10, ruling 5). A verdict about the reader's own
#: request is neither company policy nor advice, and `_turn.html` files every `recommendation`
#: under *"What I suggest you do"* with a *"not company policy"* footnote — so scenario 15 shipped
#: the engine's own reason as a suggestion, and scenarios 03, 13 and 16 shipped mandatory steps
#: from `rules.yml` under the same disclaimer. Same value as `agent/outcome.py`'s `RECORD`.
RECORD = "record"

#: The type a sentence sourced from a `rules.yml` requirement or a policy chunk carries.
POLICY_FACT = "policy_fact"

#: How a `not_stated` row is said to the reader — one explicit line per row, never silence
#: (W10, ruling 6). Scenarios 01, 03, 07 and 09 each hid one: the device requirement and the
#: written-approval requirement were simply absent from the answer, so a reader was told their
#: request was in order on rows nobody had checked. **Every** such row gets one, blocking first
#: (settled in the W10 fix round): all four of those scenarios turn on `manual` rows, which are
#: never blocking, so a blocking-only reading would have said nothing on any of them.
NOT_STATED_LINE = "{label}: not verified from your record — confirm before you proceed."

#: What a row with no reader label is called in that line.
UNLABELLED = "This requirement"

#: Words that carry no claim, dropped before an engine `next_step` is matched to the requirement it
#: restates (W10 fix round, Important 1). Deliberately the connectives and the words this product
#: says in every sentence — never a policy noun, because a policy noun is exactly what decides the
#: match.
_STEP_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "any", "are", "as", "at", "be", "before", "by", "can", "do", "each",
        "for", "from", "has", "have", "in", "is", "it", "its", "must", "no", "not", "of", "on",
        "or", "own", "so", "that", "the", "their", "them", "they", "this", "to", "under", "up",
        "was", "were", "when", "which", "while", "will", "with", "you", "your",
    }
)  # fmt: skip

#: How many content words an engine `next_step` and a requirement row have to share before the step
#: is read as a restatement of that row. **Three**, measured against every step `corpus/rules.yml`
#: carries: each step that really does restate a row clears it comfortably — *"Submit the request in
#: MosaicOne so the manager can approve it in writing"* shares `{request, manager, mosaicone}` with
#: `pto.request.manager_approval`, and the Tax & Legal one shares eight with its row — while the
#: steps that restate no single row stop at two: *"Raise the request in MosaicOne under 'Work from
#: another country' …"* shares `{work, country}` with the **tenure** requirement, which is not what
#: it is about. Two admitted that match; three does not. A step that clears nothing stays `record`,
#: which is the half that cannot mislead.
MIN_STEP_OVERLAP = 3


def _content_words(text: str) -> frozenset[str]:
    """The claim-carrying words of a sentence: lower-cased, punctuation split, stopwords dropped.

    Hyphens split — *"company-managed"* is two words — because `rules.yml` and a model's prose
    hyphenate differently and the match is about what is being talked about, not about typography.
    """
    return frozenset(word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in _STEP_STOPWORDS)


@dataclass(frozen=True)
class Row:
    """One evaluated requirement, as this step needs it."""

    id: str
    text: str
    status: str
    reason: str
    #: The requirement's reader label from `corpus/rules.yml` (W8 fix round, JX3-01 = CPUX3-02):
    #: what the measured thing is called in front of a person. The engine's `reason` names the
    #: subject key — `computed.notice_business_days` — and the first version of this step
    #: de-underscored the key into prose ("Your notice business days is 0"), which reached the chat
    #: surface on every finished PTO turn. A key is never turned into English here; the label is.
    label: str = ""
    #: Whether this row can stop the request on its own — the **effective** flag the engine used,
    #: published on the wire by the same wave (W10, ruling 3). Ruling 6's line is for a blocking
    #: row, so the step has to be able to ask.
    blocking: bool = False
    #: The chunk this row's own evidence resolves to. A step this module retypes to `policy_fact`
    #: cites **this** and nothing else (W10 fix round, Important 1): the first version cited the
    #: verdict's first evidence chunk, so a sentence about written manager approval was served
    #: under a citation to the notice requirement — the defect the same wave's citation-carry
    #: ruling calls worse than a missing one, on the surface whose whole promise is "here is the
    #: policy I used".
    chunk_id: str = ""

    @property
    def content(self) -> frozenset[str]:
        """The claim-carrying words of this row's own policy text and reader label."""
        return _content_words(f"{self.text} {self.label}")

    @property
    def subjects(self) -> tuple[str, ...]:
        """The subject words this requirement is about, from its id and its text."""
        haystack = f"{self.id.replace('.', ' ').replace('_', ' ')} {self.text}".lower()
        return tuple(word for word in SUBJECT_WORDS if word in haystack)

    @property
    def topic(self) -> str:
        """What to call this requirement in a sentence addressed to the reader."""
        found = self.subjects
        return found[0] if found else "this requirement"


@dataclass
class Outcome:
    """The blocks and next steps after the step, and what it did to them."""

    blocks: list[dict[str, Any]]
    next_steps: list[str] = field(default_factory=list)
    #: `(index into the blocks, requirement id)` for every sentence rewritten.
    restated: list[tuple[int, str]] = field(default_factory=list)
    #: `(index into the steps, requirement id)` for the same, among the next steps.
    restated_steps: list[tuple[int, str]] = field(default_factory=list)
    #: `(index, requirement id)` for a sentence that opposes a row and could not be cut safely.
    unverified: list[tuple[int, str]] = field(default_factory=list)
    #: How many sentences quoted a threshold the request had already outgrown (W8, C07).
    thresholds: int = 0
    #: How many sentences handed the decision to an authority the amount had outgrown (G5c, gap 30).
    authority: int = 0
    #: `(index into the blocks, the type it was given)` for every block this step retyped
    #: (W10, ruling 5).
    retyped: list[tuple[int, str]] = field(default_factory=list)
    #: The `not_stated` lines this step added, in the engine's own order (W10, ruling 6).
    unchecked: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.restated or self.restated_steps or self.thresholds or self.authority or self.retyped or self.unchecked
        )


def rows(envelopes: Iterable[Any]) -> list[Row]:
    """Every requirement the turn's compliance envelopes evaluated, latest verdict per id.

    A body that will not parse contributes nothing rather than raising: like every step after
    synthesis, this one must never be the reason an answer fails to reach the reader.
    """
    found: dict[str, Row] = {}
    for envelope in envelopes:
        if getattr(envelope, "name", "") != COMPLIANCE_TOOL:
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(body, dict):
            continue
        for requirement in body.get("requirements") or []:
            if not isinstance(requirement, dict) or not requirement.get("id"):
                continue
            status = str(requirement.get("status") or ("met" if requirement.get("met") else "unmet"))
            evidence = requirement.get("evidence")
            found[str(requirement["id"])] = Row(
                id=str(requirement["id"]),
                text=str(requirement.get("text") or ""),
                status=status,
                reason=str(requirement.get("reason") or ""),
                label=str(requirement.get("label") or ""),
                blocking=bool(requirement.get("blocking")),
                chunk_id=str(evidence.get("chunk_id") or "") if isinstance(evidence, dict) else "",
            )
    return list(found.values())


def engine_steps(envelopes: Iterable[Any]) -> list[str]:
    """The engine's own `next_steps`, in order, de-duplicated (W10, ruling 5).

    `rules.yml`'s `next_steps` are *requirements*: "Submit the request in MosaicOne so the manager
    can approve it in writing" is what the policy says happens, not something a model thought of.
    Three scenarios shipped them under *"Recommendation — not company policy"*.
    """
    steps: list[str] = []
    for envelope in envelopes:
        if getattr(envelope, "name", "") != COMPLIANCE_TOOL:
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(body, dict):
            continue
        steps.extend(str(step) for step in (body.get("next_steps") or []) if isinstance(step, str))
    return list(dict.fromkeys(steps))


def supporting_row(step: str, rows_: Sequence[Row]) -> Row | None:
    """The requirement this engine step restates, or `None` (W10 fix round, Important 1).

    A `policy_fact` is a promise that the citation beside it says the sentence. The first version
    of this step cited `citations[0]` — the verdict's **first** evidence chunk, which on every
    `pto_request` turn is the notice requirement — so a sentence about written manager approval was
    served under a citation to a passage about five business days' notice. That is the defect this
    wave's own citation-carry ruling calls worse than a missing citation, on the one surface whose
    promise is *"here is the policy I used"*.

    The match is content overlap against the row's own policy text and reader label: at least
    `MIN_STEP_OVERLAP` claim-carrying words, and a single best row — a tie is not a match, because
    a step this module cannot place is one it has no business citing. Only a row that actually
    resolved evidence can win; a row whose chunk did not resolve cannot support anything.
    """
    words = _content_words(step)
    scored = sorted(
        ((len(words & row.content), row) for row in rows_ if row.chunk_id),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored or scored[0][0] < MIN_STEP_OVERLAP:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]


def not_stated_lines(rows_: Sequence[Row]) -> list[str]:
    """One explicit line per `not_stated` row — **every** one, blocking first (W10, ruling 6).

    **Settled by the coordinator, W10 fix round.** The ruling's sentence says *blocking*; its own
    scenario list — 01, 03, 07, 09 — is entirely `manual` rows, which publish `blocking: false` by
    construction, so the two cannot both be read narrowly. Every `not_stated` row gets its line:
    a requirement nobody could check is a requirement nobody could check, and leaving it out is
    exactly the silence that let scenario 01 read as though the trip were in order on a device
    requirement no one had verified.

    **Blocking first**, then the rest, each group in the engine's own order: a row that can stop
    the request is the one the reader needs first, and the ordering is the only thing the two
    classes are distinguished by on the page.
    """

    def line(row: Row) -> str:
        # `.capitalize()` would lower-case the rest — "Written manager approval in mosaicone" — and
        # the labels carry product names.
        label = (row.label or UNLABELLED).strip()
        return NOT_STATED_LINE.format(label=label[:1].upper() + label[1:])

    unchecked = [row for row in rows_ if row.status == "not_stated"]
    return [line(row) for row in unchecked if row.blocking] + [line(row) for row in unchecked if not row.blocking]


def _normalised(text: str) -> str:
    """Comparable bytes for two statements of the same instruction."""
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def _carries(text: str, phrases: Sequence[str]) -> bool:
    """Whole words only. *"insufficient"* ends in *"sufficient"* and is its opposite."""
    return any(re.search(rf"\b{re.escape(phrase)}", text) for phrase in phrases)


def polarity(text: str) -> str | None:
    """`"asserts"`, `"denies"`, or `None` when the sentence carries both or neither."""
    lowered = text.lower()
    denies = _carries(lowered, NEGATIVE)
    asserts = _carries(lowered, POSITIVE)
    if denies == asserts:
        return None
    return "denies" if denies else "asserts"


def reader_sentence(row: Row) -> str:
    """The row's own result, in the second person, built from its **label** and its values in words.

    `"computed.notice_business_days is 8; the policy value is 5 (gte)."` on the row labelled
    *"notice before the first day off, in business days"* becomes *"Your notice before the first
    day off, in business days, is 8; the policy asks for at least 5."* — the engine's own numbers,
    the engine's own verdict, and nothing the reader has to decode. A boolean row is said as a
    fact, not as "is yes". A row with no label, or a reason in a shape this cannot parse, falls back
    to naming the requirement by its own policy text — and **never** to a key with its underscores
    swapped for spaces, which is the class the re-audit caught on the chat surface (JX3-01).
    """
    if row.status == "not_stated":
        return f"I could not check the {row.topic} requirement."
    match = REASON.match(row.reason)
    verdict = "meets" if row.status == "met" else "does not meet"
    if match is None or not row.label:
        return f"Your request {verdict} this requirement: {row.text.rstrip('.')}."
    value, expected = match["value"], match["expected"]
    if value.lower() in IN_WORDS:
        stated = IN_WORDS[value.lower()]
        wanted = IN_WORDS.get(expected.lower(), expected)
        if row.status == "met":
            return f"Your {row.label}: {stated}, as the policy requires."
        return f"Your {row.label}: {stated}; the policy requires {wanted}."
    # The unit leaves the label and joins the numbers: "Your PTO balance is 0.25 days" rather than
    # "Your PTO balance, in days, is 0.25" (UX W9, npo5-02 / CPUX4-03).
    unit_match = _UNIT_TAIL.search(row.label)
    label = _UNIT_TAIL.sub("", row.label) if unit_match else row.label
    unit = f" {unit_match['unit'].strip()}" if unit_match else ""
    relation = RELATIONS.get(match["op"], "")
    if match["source"] == "request":
        # The comparison value is the reader's own — their request — never "the policy".
        return f"Your {label} {_verb(label)} {value}{unit}; your request is for {expected}{unit}."
    asked = f"{relation} {expected}{unit}".strip()
    return f"Your {label} {_verb(label)} {value}{unit}; the policy asks for {asked}."


def relation(sentence: str, row: Row) -> str | None:
    """How this sentence stands to that requirement: `"opposes"`, `"agrees"`, `"unsure"`, or
    `None` when the sentence is not about the requirement's subject at all."""
    lowered = sentence.lower()
    if not any(word in lowered for word in row.subjects):
        return None
    stated = polarity(sentence)
    if stated is None:
        # It names the subject and states no verdict this step can read — a description, or a
        # sentence carrying both polarities at once. Either way it is not one to cut blind.
        return "unsure"
    if row.status == "met":
        return "opposes" if stated == "denies" else "agrees"
    if row.status == "unmet":
        return "opposes" if stated == "asserts" else "agrees"
    # `not_stated`: a conclusion about **this request** is one the engine did not reach (W8, C05).
    # A sentence about the rule itself — "Verbal approval is insufficient." — states policy, and
    # policy is not a verdict on anybody's request (W8 fix round).
    if about_the_reader(sentence) or THIS_REQUEST.search(sentence):
        return "opposes"
    return "unsure"


def correct(text: str, rows_: Sequence[Row]) -> tuple[str, list[str], list[str]]:
    """`(the repaired text, the requirement ids restated, the ids left unverified)`.

    Unchanged bytes when nothing opposes: the join only happens where a sentence was replaced.
    """
    if not rows_:
        return text, [], []
    restated: list[str] = []
    unverified: list[str] = []
    parts = sentences(text)
    repaired: list[str] = []
    for sentence in parts:
        stood = {row.id: relation(sentence, row) for row in rows_}
        opposed = [row for row in rows_ if stood[row.id] == "opposes"]
        unsure = [row for row in rows_ if stood[row.id] == "unsure"]
        if len(opposed) == 1:
            repaired.append(reader_sentence(opposed[0]))
            restated.append(opposed[0].id)
            continue
        # Nothing certain to say: two rows contradicted by one sentence would lose a verdict if
        # either were cut, and a sentence with no readable polarity is not one to rewrite at all.
        unverified.extend(row.id for row in (opposed or unsure))
        repaired.append(sentence)
    if not restated:
        return text, [], unverified
    return " ".join(part.strip() for part in repaired), restated, unverified


def retype(
    block: Mapping[str, Any],
    restated: Sequence[str],
    mandated: Mapping[str, Row | None],
) -> tuple[str, str] | None:
    """`(the type this block should carry, the chunk it cites)`, or `None` to leave it alone.

    Two moves, and only out of `recommendation` — the one type `_turn.html` disclaims (ruling 5):

    * a block this step rewrote is now carrying the **engine's own reason**, which is a statement
      about the reader's request: `record`, uncited;
    * a block that restates one of the engine's own `next_steps` is `rules.yml` speaking, so it is
      a `policy_fact` — **cited to the requirement row that step restates**, and only when
      `supporting_row` could place it. A step nothing supports stays `record` rather than minting a
      policy citation to a passage about something else (W10 fix round, Important 1).

    Nothing already typed `policy_fact`, `record`, `performed`, `escalation` or `notice` is touched:
    this step only repairs the label the model reaches for when it has nothing better.
    """
    if str(block.get("type") or "") != "recommendation":
        return None
    key = _normalised(str(block.get("text") or ""))
    if key in mandated:
        row = mandated[key]
        return (POLICY_FACT, row.chunk_id) if row is not None else (RECORD, "")
    return (RECORD, "") if restated else None


def stated_amount(rows_: Sequence[Row]) -> float | None:
    """The amount the question asked about, read off the engine's own requirement reasons."""
    for row in rows_:
        match = REASON.match(row.reason)
        if match is not None and match["subject"] == AMOUNT_SUBJECT:
            try:
                return float(match["value"].replace(",", ""))
            except ValueError:
                continue
    return None


def covering_rule(envelopes: Iterable[Any]) -> str | None:
    """The reason of the approval tier the amount actually reaches, or `None` (W8, C07).

    `approvals_required[]` is already filtered by the scenario's own guards, so the **last** entry
    is the highest tier this request triggered: on a USD 3,000 claim that is the director's row,
    whose reason is the rule the answer should have quoted.
    """
    for envelope in envelopes:
        if getattr(envelope, "name", "") != COMPLIANCE_TOOL:
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        approvals = body.get("approvals_required") if isinstance(body, dict) else None
        if isinstance(approvals, list) and len(approvals) > 1:
            reason = approvals[-1].get("reason") if isinstance(approvals[-1], dict) else None
            if isinstance(reason, str) and reason.strip():
                return reason.strip()
    return None


def correct_ceilings(text: str, amount: float | None, covering: str | None) -> tuple[str, int]:
    """`(the text, how many ceiling sentences were replaced or dropped)` (W8, C07).

    A sentence quoting a ceiling **below** the amount the question carries is describing a tier the
    request has left. It is replaced by the tier that actually applies, in the engine's own words,
    or dropped where the engine named no higher tier — a threshold that does not apply is worse
    than no threshold, because the reader acts on it.
    """
    if amount is None:
        return text, 0
    kept: list[str] = []
    changed = 0
    for sentence in sentences(text):
        ceilings = [float((match["value"] or match["symbol"]).replace(",", "")) for match in CEILING.finditer(sentence)]
        if not ceilings or max(ceilings) >= amount:
            kept.append(sentence)
            continue
        changed += 1
        if covering:
            kept.append(covering)
    return (" ".join(part.strip() for part in kept) if changed else text), changed


def correct_authority(text: str, rows_: Sequence[Row], covering: str | None) -> tuple[str, int]:
    """`(the text, how many approval-authority sentences were replaced)` (G5c, gap 30).

    The sibling of `correct_ceilings`, for the other half of the same failure. On the live
    `expenses-002` turn the engine scored `expense.manager_limit` **unmet** — *"parameters.amount_usd
    is 3000; the policy value is 2500"* — and attached the Director approval, and the served answer
    still opened *"Since your USD 3,000 conference trip is below the USD 5,000 director threshold,
    your manager Dana can approve it"*: the right authority for the wrong reason, justified from a
    threshold the failing row is not about. Neither existing repair reaches it. `correct()` reads the
    sentence's polarity as `denies`, which *agrees* with an unmet row, so it leaves it; and
    `correct_ceilings` only matches a *"up to USD X"* ceiling below the amount, while USD 5,000 is
    above USD 3,000 and is quoted as a floor the claim sits under.

    So: while an amount threshold **was checked and failed**, a sentence concluding that the lower
    authority may approve is replaced by the engine's own routing sentence — the reason of the
    highest approval tier the request actually reached, else the failing row's own result. Replaced
    once: a second such sentence is dropped rather than repeating it. Nothing happens on a claim
    whose amount row is `met` (the manager really may approve it) or `not_stated` (nothing was
    checked, and `correct()` already says so).
    """
    failing = [
        row
        for row in rows_
        if row.status == "unmet"
        and (match := REASON.match(row.reason)) is not None
        and match["subject"] == AMOUNT_SUBJECT
    ]
    if not failing:
        return text, 0
    routing = covering or reader_sentence(failing[-1])
    kept: list[str] = []
    changed = 0
    for sentence in sentences(text):
        if not LOWER_AUTHORITY.search(sentence):
            kept.append(sentence)
            continue
        changed += 1
        if changed == 1:
            kept.append(routing)
    return (" ".join(part.strip() for part in kept) if changed else text), changed


def apply(
    blocks: Sequence[Mapping[str, Any]],
    envelopes: Iterable[Any],
    *,
    next_steps: Sequence[str] = (),
) -> Outcome:
    """The pure rule, over everything `render_answer()` puts in front of one reader. Mutates nothing.

    **Typing travels with the sentence** (W10, ruling 5). A sentence this step replaces is now the
    engine's own reason, so its block is the reader's `record` rather than advice; a block that is
    one of the engine's own `next_steps` is `rules.yml` speaking and is a `policy_fact` cited to
    **the requirement row it restates** — never to the verdict's first chunk, and never at all when
    no single row supports it (W10 fix round, Important 1).

    **…and every `not_stated` row is said** (W10, ruling 6): one explicit line each, blocking rows
    first, appended as a `record` block — because a requirement nobody could check is a thing the
    reader has to check, and leaving it out is what let an answer read as though the request were
    in order on a row no one had verified.
    """
    evaluated = rows(envelopes)
    amount, covering = stated_amount(evaluated), covering_rule(envelopes)
    # Each engine step, keyed by its normalised text, paired with the requirement row it restates
    # — the row whose own evidence chunk it will cite. `None` where nothing places it (W10 fix
    # round, Important 1).
    mandated: dict[str, Row | None] = {
        _normalised(step): supporting_row(step, evaluated) for step in engine_steps(envelopes)
    }
    body: list[dict[str, Any]] = []
    restated: list[tuple[int, str]] = []
    unverified: list[tuple[int, str]] = []
    retyped: list[tuple[int, str]] = []
    rewritten = 0
    rerouted = 0
    for index, block in enumerate(blocks):
        item = dict(block)
        text, changed, unsure = correct(str(item.get("text") or ""), evaluated)
        text, ceilings = correct_ceilings(text, amount, covering)
        rewritten += ceilings
        # The engine's own routing sentence, over the blocks only: a `next_step` is `rules.yml`
        # speaking, and this step does not rewrite the engine's own instructions (G5c, gap 30).
        text, routed = correct_authority(text, evaluated, covering)
        rerouted += routed
        if (ceilings or routed) and not text.strip():
            # The block was nothing but a threshold the request had already outgrown.
            continue
        item["text"] = text
        typed = retype(item, changed, mandated)
        if typed is not None:
            kind, chunk_id = typed
            item["type"] = kind
            if kind == POLICY_FACT and chunk_id and not (item.get("citations") or []):
                item["citations"] = [chunk_id]
            retyped.append((index, kind))
        restated.extend((index, requirement_id) for requirement_id in changed)
        unverified.extend((index, requirement_id) for requirement_id in unsure)
        body.append(item)

    steps: list[str] = []
    restated_steps: list[tuple[int, str]] = []
    for index, step in enumerate(next_steps):
        text, changed, unsure = correct(str(step), evaluated)
        text, ceilings = correct_ceilings(text, amount, covering)
        rewritten += ceilings
        if ceilings and not text.strip():
            continue
        steps.append(text)
        restated_steps.extend((index, requirement_id) for requirement_id in changed)
        unverified.extend((index, requirement_id) for requirement_id in unsure)

    unchecked = not_stated_lines(evaluated)
    said = " ".join(str(block.get("text") or "") for block in body)
    stated = [line for line in unchecked if line not in said]
    if stated:
        body.append({"type": RECORD, "text": " ".join(stated), "citations": []})
    return Outcome(
        blocks=body,
        next_steps=steps,
        restated=restated,
        restated_steps=restated_steps,
        unverified=unverified,
        thresholds=rewritten,
        authority=rerouted,
        retyped=retyped,
        unchecked=stated,
    )


__all__ = [
    "COMPLIANCE_TOOL",
    "NOT_STATED_LINE",
    "POLICY_FACT",
    "RECORD",
    "UNLABELLED",
    "NEGATIVE",
    "POSITIVE",
    "REASON",
    "RELATIONS",
    "STEP_NAME",
    "IN_WORDS",
    "AMOUNT_SUBJECT",
    "CEILING",
    "LOWER_AUTHORITY",
    "SUBJECT_WORDS",
    "THIS_REQUEST",
    "Outcome",
    "Row",
    "apply",
    "correct",
    "correct_authority",
    "correct_ceilings",
    "covering_rule",
    "MIN_STEP_OVERLAP",
    "engine_steps",
    "not_stated_lines",
    "supporting_row",
    "polarity",
    "reader_sentence",
    "retype",
    "rows",
    "stated_amount",
]
