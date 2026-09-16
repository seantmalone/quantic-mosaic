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

#: A sentence that concludes about **this request** rather than about the rule in general (W8 fix
#: round, W7-review I4). `pto.request.manager_approval` is a `manual` row and therefore
#: `not_stated` on every PTO turn; without this, *"Verbal approval is insufficient."* — a true,
#: cited policy sentence — was replaced by "I could not check the approval requirement."
THIS_REQUEST = re.compile(
    r"\b(?:this|your)\s+(?:request|requirement|claim|trip|application|leave|case)\b", re.IGNORECASE
)

#: The shape `rules.py::_evaluate_requirement` writes a decided reason in.
REASON = re.compile(r"^(?P<subject>[\w.]+) is (?P<value>.+?); the policy value is (?P<expected>.+?) \((?P<op>\w+)\)\.$")


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

    @property
    def changed(self) -> bool:
        return bool(self.restated or self.restated_steps or self.thresholds)


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
            found[str(requirement["id"])] = Row(
                id=str(requirement["id"]),
                text=str(requirement.get("text") or ""),
                status=status,
                reason=str(requirement.get("reason") or ""),
                label=str(requirement.get("label") or ""),
            )
    return list(found.values())


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
    relation = RELATIONS.get(match["op"], "")
    asked = f"{relation} {expected}".strip()
    # A label that ends in an appositive — "…, in business days" — closes it with a comma before
    # the verb; a plain label takes none (NEW-1: "Your destination country, is DE" was a comma too
    # many, and "Your days since the transaction is 12" a verb too few).
    joiner = ", " if "," in row.label else " "
    return f"Your {row.label}{joiner}{_verb(row.label)} {value}; the policy asks for {asked}."


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


def apply(
    blocks: Sequence[Mapping[str, Any]],
    envelopes: Iterable[Any],
    *,
    next_steps: Sequence[str] = (),
) -> Outcome:
    """The pure rule, over everything `render_answer()` puts in front of one reader. Mutates nothing."""
    evaluated = rows(envelopes)
    amount, covering = stated_amount(evaluated), covering_rule(envelopes)
    body: list[dict[str, Any]] = []
    restated: list[tuple[int, str]] = []
    unverified: list[tuple[int, str]] = []
    rewritten = 0
    for index, block in enumerate(blocks):
        item = dict(block)
        text, changed, unsure = correct(str(item.get("text") or ""), evaluated)
        text, ceilings = correct_ceilings(text, amount, covering)
        rewritten += ceilings
        if ceilings and not text.strip():
            # The block was nothing but a threshold the request had already outgrown.
            continue
        item["text"] = text
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
    return Outcome(
        blocks=body,
        next_steps=steps,
        restated=restated,
        restated_steps=restated_steps,
        unverified=unverified,
        thresholds=rewritten,
    )


__all__ = [
    "COMPLIANCE_TOOL",
    "NEGATIVE",
    "POSITIVE",
    "REASON",
    "RELATIONS",
    "STEP_NAME",
    "IN_WORDS",
    "AMOUNT_SUBJECT",
    "CEILING",
    "SUBJECT_WORDS",
    "THIS_REQUEST",
    "Outcome",
    "Row",
    "apply",
    "correct",
    "correct_ceilings",
    "covering_rule",
    "polarity",
    "reader_sentence",
    "rows",
    "stated_amount",
]
