"""G5 `sensitive_escalation` (spec §7.4 row G5, §13.1's one `sensitive` item).

Harassment, discrimination, a legal threat, a medical condition and a compensation dispute are never
answered by an automated assistant. The router detects them; G5 names the route, the contact and the
process from `corpus/hr-escalation-and-case-handling.md`, and the turn ends `escalated` having
burned **no tools**.

The contacts are pinned against the corpus in both directions: a corpus edit that renames an inbox
must fail here rather than leave the assistant routing people to an address that no longer exists.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent.guardrails import g2, g5
from hrmosaic.agent.orchestrator import ChatRequest
from hrmosaic.core import corpusread
from hrmosaic.core.trace import SessionSpec

pytestmark = pytest.mark.anyio

ESCALATION_DOC = corpusread.get_document(g5.ESCALATION_DOC_ID)

CASES = [
    ("A colleague has been harassing me for weeks.", "harassment_or_discrimination", g5.EMPLOYEE_RELATIONS),
    (
        "I think I was passed over because of my age — this is discrimination.",
        "harassment_or_discrimination",
        g5.EMPLOYEE_RELATIONS,
    ),
    ("I need an accommodation for a medical condition.", "medical_condition", g5.LEAVE),
    ("My lawyer says I should take legal action against the company.", "legal_threat", g5.PEOPLE_OPS),
    ("I am underpaid compared with my peers and it is not right.", "compensation_dispute", g5.PEOPLE_OPS),
    ("We had a data breach on my laptop last night.", "security_incident", g5.IT_SECURITY),
    ("How many PTO days do I get?", g5.DEFAULT_CATEGORY, g5.PEOPLE_OPS),
]


@pytest.mark.parametrize(("message", "category", "contact"), CASES, ids=[case[1] for case in CASES])
def test_each_category_routes_to_the_contact_its_own_policy_names(message, category, contact):
    assert g5.classify(message) == (category, contact)


@pytest.mark.parametrize("contact", [g5.PEOPLE_OPS, g5.EMPLOYEE_RELATIONS, g5.LEAVE, g5.IT_SECURITY])
def test_every_contact_appears_verbatim_in_the_escalation_policy(contact):
    assert ESCALATION_DOC is not None
    assert contact in ESCALATION_DOC.full_text


def test_the_escalation_decision_is_the_routers_not_the_patterns():
    """§7.4: the category picks the inbox; only the router decides that a turn is sensitive."""
    assert g5.evaluate(sensitive=False, message="A colleague has been harassing me.").escalate is False
    assert g5.evaluate(sensitive=True, message="How many PTO days do I get?").escalate is True


def test_the_escalation_answer_names_the_route_the_contact_and_the_process():
    verdict = g5.evaluate(sensitive=True, message="A colleague has been harassing me for weeks.")
    answer = g5.escalation(verdict)

    assert [block.type for block in answer.blocks] == ["escalation"]
    text = answer.blocks[0].text
    assert g5.EMPLOYEE_RELATIONS in text
    assert "Raise an HR case" in text, "the process, from the policy's own 'How to Raise a Case'"
    assert any("confirmation" in step or "confirm" in step for step in answer.next_steps), (
        "the mock HR case ticket is offered behind a confirmation, never opened (§8.6)"
    )


def test_the_escalation_citation_resolves_through_g2():
    verdict = g5.evaluate(sensitive=True, message="I was harassed.")
    answer = g5.escalation(verdict)
    outcome = g2.apply([block.model_dump() for block in answer.blocks])

    assert answer.blocks[0].citations, "the escalation is grounded in the policy, not asserted"
    assert not outcome.stripped
    assert outcome.citations[0].doc_id == g5.ESCALATION_DOC_ID
    assert outcome.citations[0].heading_path == g5.ESCALATION_HEADING


def test_the_span_records_the_route(writer, spans):
    turn = writer.start_turn(SessionSpec(client_label="api"), user_message="I was harassed at work.")
    g5.check(sensitive=True, message="I was harassed at work.", turn=turn)
    turn.close(outcome="escalated", stop_reason="escalated")

    payload = next(payload for kind, _, payload in spans(turn.turn_id) if kind == "guardrail")
    assert (payload["rule_id"], payload["rule_name"], payload["verdict"]) == (
        "G5",
        "sensitive_escalation",
        "escalate",
    )
    assert payload["details"]["contact"] == g5.EMPLOYEE_RELATIONS


async def test_a_sensitive_turn_escalates_and_burns_no_tools(run_agent, spans):
    response = await run_agent(
        "sensitive.json",
        ChatRequest(message="A colleague has been harassing me and I want it to stop.", employee_id="E1042"),
    )

    assert response.outcome == "escalated"
    kinds = [kind for kind, _, _ in spans(response.turn_id)]
    assert "tool_call" not in kinds, "the sensitive route burns no tools (§13.1)"
    assert response.usage.llm_calls == 1, "one route call, and no synthesis of an answer we must not give"
    assert [block.type for block in response.answer_blocks] == ["escalation"]
    assert g5.EMPLOYEE_RELATIONS in response.answer
