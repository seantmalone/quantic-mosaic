"""G5 `sensitive_escalation` — never answer a matter that belongs to a person (spec §7.4).

Harassment, discrimination, a legal threat, a medical condition and a compensation dispute are
**detected by the router** (`RouteDecision.sensitive`) and never answered directly. The turn ends
`escalated` after naming the route and the contact, having burned **no tools** — which is also what
the dataset's one `sensitive` item asserts (§13.1).

`corpus/hr-escalation-and-case-handling.md` is the authority for both halves. Its *What Must Be
Escalated* section is cited so the answer is grounded rather than asserted, and its *Contacts*
section is where the four addresses below come from — `tests/unit/test_g5_sensitive.py` asserts each
one still appears verbatim in that document, so a corpus edit cannot silently leave the assistant
routing people to an address that no longer exists.

The ticket offer is an **offer**: §8.6 gates every write behind a human confirmation, and this path
makes no `tools/call` at all, so the answer says what it could open rather than proposing it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hrmosaic.agent.guardrails import emit
from hrmosaic.core import corpusread
from hrmosaic.core.models import AnswerBlock, AnswerSchema

if TYPE_CHECKING:
    from hrmosaic.core.trace import TurnBuffer

#: The policy that owns both the escalation list and the contacts.
ESCALATION_DOC_ID = "hr-escalation-and-case-handling"
ESCALATION_HEADING = "What Must Be Escalated"

#: From that document's *Contacts* section, verbatim. Pinned by a test in both directions.
PEOPLE_OPS = "people-ops@mosaicrobotics.example"
EMPLOYEE_RELATIONS = "employee-relations@mosaicrobotics.example"
LEAVE = "leave@mosaicrobotics.example"
IT_SECURITY = "it-security@mosaicrobotics.example"

#: The five categories §7.4 names, each routed to the address its own policy names. The patterns
#: pick a **contact**, never the escalation decision itself — that is the router's (§7.4 G5).
CATEGORIES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "harassment_or_discrimination",
        EMPLOYEE_RELATIONS,
        re.compile(
            r"(?i)\b(harass\w*|bull(y|ied|ying)|discriminat\w*|retaliat\w*|racist|sexist|"
            r"sexual misconduct|hostile work environment)\b"
        ),
    ),
    (
        "medical_condition",
        LEAVE,
        re.compile(
            r"(?i)\b(medical condition|disabilit\w*|pregnan\w*|mental health|accommodation|"
            r"fitness to work|sick leave)\b"
        ),
    ),
    (
        "legal_threat",
        PEOPLE_OPS,
        re.compile(r"(?i)\b(sue|suing|lawsuit|legal action|my lawyer|attorney|tribunal|regulator\w*)\b"),
    ),
    (
        "compensation_dispute",
        PEOPLE_OPS,
        re.compile(r"(?i)\b(underpaid|pay is unfair|unfair (pay|rating|bonus)|discriminatory pay|pay dispute)\b"),
    ),
    (
        "security_incident",
        IT_SECURITY,
        re.compile(r"(?i)\b(data breach|security incident|credentials? (were |was )?stolen|phish\w* attack)\b"),
    ),
)

DEFAULT_CATEGORY = "people_operations_case"


@dataclass(frozen=True)
class Verdict:
    """The pure decision: whether to escalate, and to whom."""

    escalate: bool
    category: str
    contact: str


def classify(message: str) -> tuple[str, str]:
    """`(category, contact)` for one message. Pure, and it only chooses **where** to route."""
    for category, contact, pattern in CATEGORIES:
        if pattern.search(message):
            return category, contact
    return DEFAULT_CATEGORY, PEOPLE_OPS


def evaluate(*, sensitive: bool, message: str) -> Verdict:
    """The pure rule. `sensitive` is the router's decision; the message picks the contact."""
    category, contact = classify(message)
    return Verdict(escalate=bool(sensitive), category=category, contact=contact)


def evidence_chunk_id() -> str | None:
    """The *What Must Be Escalated* chunk id, resolved from the real index — never hard-coded.

    Chunk ids are content hashes, so a corpus edit moves them; resolving by `(doc_id, heading_path)`
    is how `mcpserver/rules.py` does it too, and it keeps the citation resolvable through G2.
    """
    try:
        chunks = corpusread.list_chunks(ESCALATION_DOC_ID)
    except Exception:  # no built index (a bare unit test): an uncited escalation block is still valid
        return None
    for chunk in chunks:
        if chunk.heading_path == ESCALATION_HEADING:
            return chunk.chunk_id
    return None


def escalation(verdict: Verdict) -> AnswerSchema:
    """The escalation answer: the route, the contact, the process — and never a direct answer."""
    chunk_id = evidence_chunk_id()
    citations = [chunk_id] if chunk_id else []
    return AnswerSchema(
        blocks=[
            AnswerBlock(
                type="escalation",
                text=(
                    "This is a matter for a person, not for an automated assistant. Mosaic Robotics "
                    "policy routes harassment, discrimination, retaliation, legal threats, medical "
                    "matters and pay disputes to a named People Operations partner, so I will not "
                    f"answer it here. Contact {verdict.contact}, or raise a case in MosaicOne under "
                    '"Raise an HR case". You may also use the third-party ethics line anonymously.'
                ),
                citations=citations,
            )
        ],
        next_steps=[
            f"Email {verdict.contact} — a case needs only your name and a description of the matter.",
            'Or raise it yourself in MosaicOne under "Raise an HR case"; you will get a case reference.',
            "If you would like me to open an HR case for you, say so and I will show you the exact "
            "summary for your confirmation before anything is created.",
        ],
        rationale_summary=f"Escalated to {verdict.category}: never answered directly."[:200],
    )


def check(*, sensitive: bool, message: str, turn: TurnBuffer | None = None) -> Verdict:
    """Evaluate and emit the one `guardrail` span."""
    verdict = evaluate(sensitive=sensitive, message=message)
    emit(
        turn,
        "G5",
        verdict="escalate" if verdict.escalate else "allow",
        reason=(
            f"routed to {verdict.contact} as {verdict.category}"
            if verdict.escalate
            else "the router did not flag this turn as sensitive"
        ),
        details={"category": verdict.category, "contact": verdict.contact, "doc_id": ESCALATION_DOC_ID},
    )
    return verdict


__all__ = [
    "CATEGORIES",
    "DEFAULT_CATEGORY",
    "EMPLOYEE_RELATIONS",
    "ESCALATION_DOC_ID",
    "ESCALATION_HEADING",
    "IT_SECURITY",
    "LEAVE",
    "PEOPLE_OPS",
    "Verdict",
    "check",
    "classify",
    "escalation",
    "evaluate",
    "evidence_chunk_id",
]
