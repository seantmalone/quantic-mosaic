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

1. **The outcome block goes first.** A `recommendation`, because it is tool data and not a
   statement of company policy (§7.3), carrying the id verbatim. It is skipped when the model's
   own answer already states that id — the point is that the reader is told once, not twice.
2. **An escalation that denies the performed action is replaced** by a line pointing at what was
   created. Only that kind of escalation: G5's sensitive-topic block names a People Operations
   contact and would be collateral damage, so the check is denial *plus* a word for the action the
   performed tool performs, and nothing else is touched.

**A success status is proof of a confirmation.** `mcpserver/confirm.py` mints a token only inside
`POST /chat/confirm`, after a human clicks Confirm, and `mock_writes.confirmation_token` is `NOT
NULL REFERENCES` — so a write tool cannot return `created` / `drafted` without a consumed one
(§8.6). Reading the envelope is therefore the same question as "was this performed after a human
confirmation", asked where the answer is written down.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: What the step is called where it is named — reports, the spec paragraph beside §7.4's table.
#: Deliberately not a `G<n>`: the six guardrails are a closed set.
STEP_NAME = "outcome_consistency"

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


@dataclass(frozen=True)
class PerformedWrite:
    """One write tool result that succeeded, and the two sentences derived from it."""

    tool_name: str
    write_id: str
    body: Mapping[str, Any]

    @property
    def statement(self) -> str:
        """The block that opens the answer: what happened, with the id, and that it is a mock."""
        if self.tool_name == "draft_hr_email":
            recipient = self.body.get("to_name") or self.body.get("to_role")
            for_whom = f" for {recipient}" if recipient else ""
            return (
                f"Done: HR email draft {self.write_id} was prepared{for_whom} — this is a mock "
                "draft, nothing was sent outside this app."
            )
        queue = self.body.get("queue")
        priority = self.body.get("priority")
        where = f" in queue {queue}" if queue else ""
        how = f" (priority {priority})" if priority else ""
        return (
            f"Done: HR ticket {self.write_id} was opened{where}{how} — this is a mock ticket, "
            "nothing was sent outside this app."
        )

    @property
    def pointer(self) -> str:
        """What replaces an escalation that denied this action: where the thing already is."""
        if self.tool_name == "draft_hr_email":
            return (
                f"The draft already exists: {self.write_id}, prepared on this turn after you "
                "confirmed it. Review it before anything is sent for real."
            )
        queue = self.body.get("queue")
        where = f" in queue {queue}" if queue else ""
        return (
            f"The ticket already exists: {self.write_id} was opened{where} on this turn after you "
            "confirmed it. There is nothing further for you to file."
        )


@dataclass
class Outcome:
    """The blocks after the step, and what it did to them."""

    blocks: list[dict[str, Any]]
    #: Whether the outcome block was inserted. False when the model already stated the id.
    stated: bool = False
    #: Indexes **into the model's own block list**, before the outcome block is inserted.
    replaced: list[int] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.stated or bool(self.replaced)


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


def apply(blocks: Sequence[Mapping[str, Any]], envelopes: Iterable[Any]) -> Outcome:
    """The pure rule: state the write first, and replace an escalation that denies it. Mutates nothing."""
    write = performed_write(envelopes)
    body = [dict(block) for block in blocks]
    if write is None:
        return Outcome(blocks=body)

    replaced: list[int] = []
    for index, block in enumerate(body):
        if block.get("type") == "escalation" and denies(str(block.get("text") or ""), write.tool_name):
            block["type"] = "recommendation"
            block["text"] = write.pointer
            block["citations"] = []
            replaced.append(index)

    if any(write.write_id in str(block.get("text") or "") for block in blocks):
        return Outcome(blocks=body, replaced=replaced)
    statement = {"type": "recommendation", "text": write.statement, "citations": []}
    return Outcome(blocks=[statement, *body], stated=True, replaced=replaced)


__all__ = [
    "ACTION_WORDS",
    "DENIALS",
    "STEP_NAME",
    "WRITE_SUCCESS",
    "Outcome",
    "PerformedWrite",
    "apply",
    "denies",
    "performed_write",
]
