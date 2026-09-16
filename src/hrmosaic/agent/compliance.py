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
from collections.abc import Collection, Iterable, Mapping, Sequence
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
#: request was in order on rows nobody had checked.
NOT_STATED_LINE = "{label}: not verified from your record — confirm before you proceed."

#: What a row with no reader label is called in that line.
UNLABELLED = "This requirement"


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
    #: `(index into the blocks, the type it was given)` for every block this step retyped
    #: (W10, ruling 5).
    retyped: list[tuple[int, str]] = field(default_factory=list)
    #: The `not_stated` lines this step added, in the engine's own order (W10, ruling 6).
    unchecked: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.restated or self.restated_steps or self.thresholds or self.retyped or self.unchecked)


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


def engine_steps(envelopes: Iterable[Any]) -> tuple[list[str], list[dict[str, str]]]:
    """`(the engine's own next_steps, the citations its verdict resolved)` (W10, ruling 5).

    `rules.yml`'s `next_steps` are *requirements*: "Submit the request in MosaicOne so the manager
    can approve it in writing" is what the policy says happens, not something a model thought of.
    Three scenarios shipped them under *"Recommendation — not company policy"*.
    """
    steps: list[str] = []
    citations: list[dict[str, str]] = []
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
        # The per-requirement evidence first: those are the ids `_engine_evidence` absorbs into the
        # turn, so a citation taken from here resolves for G2 and reaches the top-level array
        # (W10, ruling 10). The verdict's own `citations[]` follow as the fallback.
        for source in (body.get("requirements") or [], body.get("citations") or []):
            for entry in source:
                if not isinstance(entry, dict):
                    continue
                citation = entry.get("evidence") if "evidence" in entry else entry
                if isinstance(citation, dict) and citation.get("chunk_id"):
                    citations.append({str(key): str(value) for key, value in citation.items() if key != "snippet"})
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for citation in citations:
        if citation["chunk_id"] in seen:
            continue
        seen.add(citation["chunk_id"])
        unique.append(citation)
    return list(dict.fromkeys(steps)), unique


def not_stated_lines(rows_: Sequence[Row]) -> list[str]:
    """One explicit line per `not_stated` row, in the engine's own order (W10, ruling 6)."""
    # `.capitalize()` would lower-case the rest — "Written manager approval in mosaicone" — and the
    # labels carry product names.
    return [
        NOT_STATED_LINE.format(label=(label := (row.label or UNLABELLED).strip())[:1].upper() + label[1:])
        for row in rows_
        if row.status == "not_stated"
    ]


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
    mandated: Collection[str],
    citations: Sequence[Mapping[str, str]],
) -> str | None:
    """The type this block should carry, or `None` to leave it alone (W10, ruling 5).

    Two moves, and only out of `recommendation` — the one type `_turn.html` disclaims:

    * a block this step rewrote is now carrying the **engine's own reason**, which is a statement
      about the reader's request: `record`;
    * a block that restates one of the engine's own `next_steps` is `rules.yml` speaking, so it is
      a `policy_fact` — provided the verdict resolved a citation for it to carry, because an
      uncited policy claim is worse than an undisclaimed one.

    Nothing already typed `policy_fact`, `record`, `performed`, `escalation` or `notice` is touched:
    this step only repairs the label the model reaches for when it has nothing better.
    """
    if str(block.get("type") or "") != "recommendation":
        return None
    if _normalised(str(block.get("text") or "")) in mandated:
        return POLICY_FACT if citations else RECORD
    return RECORD if restated else None


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
    """The pure rule, over everything `render_answer()` puts in front of one reader. Mutates nothing.

    **Typing travels with the sentence** (W10, ruling 5). A sentence this step replaces is now the
    engine's own reason, so its block is the reader's `record` rather than advice; a block that is
    one of the engine's own `next_steps` is `rules.yml` speaking and is a cited `policy_fact`.

    **…and every `not_stated` row is said** (W10, ruling 6): one explicit line each, appended as a
    `record` block, because a requirement nobody checked is a thing the reader has to check.
    """
    evaluated = rows(envelopes)
    amount, covering = stated_amount(evaluated), covering_rule(envelopes)
    engine_next_steps, engine_citations = engine_steps(envelopes)
    mandated = {_normalised(step) for step in engine_next_steps}
    body: list[dict[str, Any]] = []
    restated: list[tuple[int, str]] = []
    unverified: list[tuple[int, str]] = []
    retyped: list[tuple[int, str]] = []
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
        kind = retype(item, changed, mandated, engine_citations)
        if kind is not None:
            item["type"] = kind
            if kind == POLICY_FACT and not (item.get("citations") or []):
                item["citations"] = [engine_citations[0]["chunk_id"]]
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
    "SUBJECT_WORDS",
    "THIS_REQUEST",
    "Outcome",
    "Row",
    "apply",
    "correct",
    "correct_ceilings",
    "covering_rule",
    "engine_steps",
    "not_stated_lines",
    "polarity",
    "reader_sentence",
    "retype",
    "rows",
    "stated_amount",
]
