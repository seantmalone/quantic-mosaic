"""Approver resolution in the written answer — the backstop for C06 (spec §7.4; W8).

**Not a guardrail.** No `guardrail` span, no G-number. One deterministic step after synthesis.

The chain is resolved at the tool boundary (`mcpserver/approvers.py`), published on the
`check_policy_compliance` and `lookup_employee_profile` envelopes as `approvers[]`, and named by
`synthesize.j2`. This is what runs when the model writes the role anyway, which on 2026-09-15 it
did on every turn that mentioned one:

* *"requires approval from your director"* — served to E1007 Dana Whitfield, **Director,
  Engineering**. The corpus routes that one level higher, to Miguel;
* *"ask your manager to approve it"* — served to a persona whose own profile envelope, in the same
  turn, carried `manager: {preferred_name: "Dana"}`.

Two rewrites, both from the envelope and never from the model:

1. a bare role — *"your manager"*, *"your director"*, *"the skip-level"* — becomes that role with
   its person's name, where the envelope resolved one;
2. a role the reader **holds themselves** becomes the person one level up, with the matrix's reason
   in the same breath, so a director is never sent to herself.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: What the step is called where it is named — reports, the spec paragraph beside §7.4's table.
#: Deliberately not a `G<n>`: the six guardrails are a closed set.
STEP_NAME = "approver_resolution"

#: The envelopes that publish a resolved chain (§8.4 tools 4 and 5).
APPROVER_TOOLS: tuple[str, ...] = ("check_policy_compliance", "lookup_employee_profile")

#: Role word → how an answer writes it. The pattern matches the article an answer actually uses,
#: so *"your manager"*, *"the direct manager"* and *"their manager"* are all the same role.
ROLE_PHRASES: tuple[tuple[str, str], ...] = (
    ("skip-level", r"(?:your|the|their)\s+skip[-\s]level(?:\s+manager)?"),
    ("vice president", r"(?:your|the|their)\s+(?:vice president|VP)"),
    ("director", r"(?:your|the|their)\s+director"),
    ("manager", r"(?:your|the|their)\s+(?:direct\s+|line\s+|reporting\s+)?manager"),
)

#: Said once, in the same breath as the name, when the reader holds the role themselves. The full
#: sentence is `corpus/manager-approval-matrix.md`'s; this is the half that fits inside a clause.
ROUTED_NOTE = "one level up, since nobody approves their own request"

#: The one template that names an approver in front of a reader (W10, ruling 4). Seven of the
#: sixteen recorded demo paths got this wrong in three different ways — a name grafted into a
#: quoted policy sentence, a self-approval routing dropped, a name lost altogether — because the
#: answer's account of who approves was whatever prose the model reached for. It is one `record`
#: line, built from `approvers[]` and from nothing else.
RECORD_TEMPLATE = "Your request goes to {who}."

#: How the record line joins two or more named approvers.
AND = " and "

#: The block type the line is emitted as: the reader's own routing is neither company policy nor
#: advice. Same value as `agent/outcome.py`'s `RECORD`, kept here so this module imports nothing.
RECORD = "record"

#: A block this step may never rewrite: quoted policy text (W10, ruling 4). *"Every PTO request
#: requires written approval from the employee's direct manager Dana in MosaicOne"* is a sentence
#: `corpus/pto-and-holidays.md` does not contain, served under a citation that says it does.
CITED_FACT = "policy_fact"

#: *"approval from Dana"*, *"approved by Dana"*, *"sign-off from Dana"* — where an answer names the
#: person who approves. Used to catch a sentence that names the **reader** in that position.
APPROVED_BY = re.compile(
    r"\b(?:approval|approved|sign-?\s?off|authorisation|authorization)\s+(?:from|by)\s+"
    r"(?P<who>[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)?)"
)


@dataclass(frozen=True)
class Approver:
    """One resolved approval role, as the envelope publishes it."""

    role: str
    name: str
    self_approval_routed: bool = False
    #: `manager-approval-matrix.md`'s own sentence, present only when the routing happened. Printed
    #: verbatim (W10, ruling 4): it is the policy's explanation of a decision about this reader.
    reason: str = ""

    @property
    def phrase(self) -> str:
        """How the name is written where the role was: *"your manager Dana"*, or the routed form."""
        return f"{self.name} ({ROUTED_NOTE})" if self.self_approval_routed else self.name

    @property
    def record_phrase(self) -> str:
        """How the record line names this person: *"Dana Whitfield, your direct manager"*.

        A routed approver is named **without** the role: the person one level up is not the
        reader's director, they are who a director's own request goes to, and the matrix's own
        sentence follows to say so.
        """
        return self.name if self.self_approval_routed else f"{self.name}, your {self.role}"


@dataclass
class Outcome:
    """The blocks and next steps after the step, and what it named."""

    blocks: list[dict[str, Any]]
    next_steps: list[str] = field(default_factory=list)
    #: `(index into the blocks, role)` for every role this step put a name to.
    named: list[tuple[int, str]] = field(default_factory=list)
    #: The same, among the next steps.
    named_steps: list[tuple[int, str]] = field(default_factory=list)
    #: Whether the step added the one `record` line naming who approves (W10, ruling 4).
    stated: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.named or self.named_steps or self.stated)


def approvers(envelopes: Iterable[Any]) -> list[Approver]:
    """Every resolved approver the turn's envelopes carry, first mention per role.

    A body that will not parse contributes nothing rather than raising: like every step after
    synthesis, this one must never be the reason an answer fails to reach the reader.
    """
    found: dict[str, Approver] = {}
    for envelope in envelopes:
        if getattr(envelope, "name", "") not in APPROVER_TOOLS:
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(body, dict):
            continue
        for entry in body.get("approvers") or []:
            if not isinstance(entry, dict) or not entry.get("name") or not entry.get("role"):
                continue
            role = str(entry["role"]).lower()
            found.setdefault(
                role,
                Approver(
                    role=role,
                    name=str(entry["name"]),
                    self_approval_routed=bool(entry.get("self_approval_routed")),
                    reason=str(entry.get("reason") or ""),
                ),
            )
    return list(found.values())


def record_line(resolved: Sequence[Approver]) -> str | None:
    """The one sentence that tells the reader who approves, or `None` (W10, ruling 4).

    Built from `approvers[]` and nothing else. Where the matrix routed a role one level up because
    the reader holds it themselves, the engine's own `reason` — `manager-approval-matrix.md`'s
    sentence — follows the name **verbatim**, so a director is told why her request goes to
    somebody else rather than being quietly handed a different name.
    """
    if not resolved:
        return None
    line = RECORD_TEMPLATE.format(who=AND.join(entry.record_phrase for entry in resolved))
    routed = [entry.reason for entry in resolved if entry.self_approval_routed and entry.reason]
    return " ".join([line, *dict.fromkeys(routed)])


def names_an_approver(text: str, resolved: Sequence[Approver]) -> bool:
    """Does this text already name one of the resolved people?"""
    return any(re.search(rf"(?<!\w){re.escape(entry.name)}(?!\w)", text) for entry in resolved)


def reader_name(envelopes: Iterable[Any]) -> str | None:
    """The reader's own preferred name, from the profile envelope, or `None`."""
    for envelope in envelopes:
        if getattr(envelope, "name", "") != "lookup_employee_profile":
            continue
        try:
            body = json.loads(getattr(envelope, "result_json", "") or "")
        except (TypeError, ValueError):
            continue
        if isinstance(body, dict) and isinstance(body.get("preferred_name"), str):
            return body["preferred_name"]
    return None


def _for_role(resolved: Sequence[Approver], word: str) -> Approver | None:
    """The resolved approver whose role holds `word`, preferring an exact role word."""
    return next((entry for entry in resolved if word in entry.role), None)


def correct(text: str, resolved: Sequence[Approver], *, reader: str | None = None) -> tuple[str, list[str]]:
    """`(the text with the roles named, the roles this named)`. Unchanged bytes when nothing resolves."""
    if not resolved:
        return text, []
    named: list[str] = []

    for word, pattern in ROLE_PHRASES:
        entry = _for_role(resolved, word)
        if entry is None:
            continue

        def substitute(match: re.Match[str], entry: Approver = entry, word: str = word) -> str:
            if entry.name in match.string[match.end() : match.end() + len(entry.name) + 2]:
                return match.group(0)  # already named
            named.append(word)
            return f"{match.group(0)} {entry.phrase}" if not entry.self_approval_routed else entry.phrase

        text = re.sub(pattern, substitute, text, flags=re.IGNORECASE)

    if reader:
        # *"approval from Dana"* addressed **to** Dana. The matrix routes that one level up, and
        # the envelope already says who to.
        higher = next((entry for entry in resolved if entry.self_approval_routed), None) or _for_role(
            resolved, "manager"
        )
        if higher is not None and higher.name != reader:

            def unself(match: re.Match[str]) -> str:
                # The whole name run goes — "Dana Whitfield", not "Dana" with the surname stranded
                # after the replacement (W7-review Minor).
                if match["who"].split()[0] != reader:
                    return match.group(0)
                named.append(higher.role)
                return match.group(0).replace(match["who"], higher.phrase)

            text = APPROVED_BY.sub(unself, text)
    return text, named


def apply(
    blocks: Sequence[Mapping[str, Any]],
    envelopes: Iterable[Any],
    *,
    next_steps: Sequence[str] = (),
) -> Outcome:
    """The pure rule, over everything `render_answer()` puts in front of one reader. Mutates nothing.

    **A cited `policy_fact` is never rewritten** (W10, ruling 4). Quoted policy text is the one
    thing in an answer a reader can check against the document the citation names, and six of the
    sixteen recorded demo paths served *"written approval from the employee's direct manager
    Dana"* under a citation to a sentence that says no such thing.

    **…and where no surviving block names the approver, one is stated** (W10, ruling 4): a single
    `record` line built from `approvers[]`, carrying the matrix's own routing sentence verbatim
    when the reader holds the role themselves. Scenario 03 lost the routing to Miguel entirely;
    scenario 15 lost the name.
    """
    resolved = approvers(envelopes)
    reader = reader_name(envelopes)
    body: list[dict[str, Any]] = []
    named: list[tuple[int, str]] = []
    for index, block in enumerate(blocks):
        item = dict(block)
        if item.get("type") == CITED_FACT and (item.get("citations") or []):
            body.append(item)
            continue
        text, roles = correct(str(item.get("text") or ""), resolved, reader=reader)
        item["text"] = text
        named.extend((index, role) for role in roles)
        body.append(item)

    steps: list[str] = []
    named_steps: list[tuple[int, str]] = []
    for index, step in enumerate(next_steps):
        text, roles = correct(str(step), resolved, reader=reader)
        steps.append(text)
        named_steps.extend((index, role) for role in roles)

    stated = False
    line = record_line(resolved)
    if line is not None and not any(names_an_approver(str(block.get("text") or ""), resolved) for block in body):
        body.append({"type": RECORD, "text": line, "citations": []})
        stated = True
    return Outcome(blocks=body, next_steps=steps, named=named, named_steps=named_steps, stated=stated)


__all__ = [
    "AND",
    "APPROVED_BY",
    "APPROVER_TOOLS",
    "CITED_FACT",
    "RECORD",
    "RECORD_TEMPLATE",
    "ROLE_PHRASES",
    "ROUTED_NOTE",
    "STEP_NAME",
    "Approver",
    "Outcome",
    "apply",
    "approvers",
    "correct",
    "names_an_approver",
    "reader_name",
    "record_line",
]
