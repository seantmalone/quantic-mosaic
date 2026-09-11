"""Citation breadth — the post-synthesis coverage check of §7.4 (P24), as a pure rule.

The measured failure is `r_1789086979_baseline`: `expenses-002` cited `travel-policy` and
`expenses-and-reimbursement` while its evidence spanned five documents, so the answer lost the
`manager-approval-matrix` rule the question asked for and failed `min_distinct_docs: 3`;
`onboarding-001` cited two of the four documents its gold answer names. The evidence set was
broader than the answer in both, so this is a synthesis defect and the fix is a second look.

This file is the arithmetic: which documents a set of blocks covers, which citable ones it does
not, what the repair call is told, and when the repaired answer is allowed to replace the first.
The wiring — one bounded LLM call, on multi-document turns only — is asserted end to end in
`tests/integration/test_citation_breadth_repair.py`.
"""

from __future__ import annotations

from hrmosaic.agent import breadth
from hrmosaic.agent.orchestrator import EvidenceChunk
from hrmosaic.agent.router import RouteDecision


def chunk(chunk_id: str, doc_id: str, *, quarantined: bool = False) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        doc_title=doc_id.replace("-", " ").title(),
        heading_path="Section",
        section="Section",
        snippet="…",
        dense_score=0.7,
        quarantined=quarantined,
    )


EVIDENCE = [
    chunk("c_1", "travel-policy"),
    chunk("c_2", "travel-policy"),
    chunk("c_3", "expenses-and-reimbursement"),
    chunk("c_4", "manager-approval-matrix"),
]


def fact(*citations: str) -> dict:
    return {"type": "policy_fact", "text": "A rule.", "citations": list(citations)}


def route(*, multi_doc: bool = True, workflow: str | None = None) -> RouteDecision:
    return RouteDecision(
        intent="policy_qa",
        workflow=workflow,
        multi_doc=multi_doc,
        needs_employee_data=False,
        needs_clarification=False,
        out_of_scope=False,
        sensitive=False,
        target_employee_id=None,
        selected_tools=["search_policy_documents"],
        rationale_summary="fixture",
    )


# --- when the check runs at all ---------------------------------------------------------


def test_a_multi_document_turn_is_in_scope():
    assert breadth.applies(route(multi_doc=True))


def test_a_workflow_turn_is_in_scope_even_when_the_router_called_it_single_document():
    assert breadth.applies(route(multi_doc=False, workflow="remote_work_eligibility"))


def test_a_single_document_turn_is_not():
    """The whole point of the gate: a second synthesis call is not spent on a one-document turn."""
    assert not breadth.applies(route(multi_doc=False))


# --- the arithmetic ---------------------------------------------------------------------


def test_uncited_documents_are_the_citable_ones_no_block_cites():
    missing = breadth.uncited_documents([fact("c_1"), fact("c_3")], EVIDENCE)
    assert missing == ["manager-approval-matrix"]


def test_a_document_cited_through_any_of_its_passages_is_covered():
    assert breadth.uncited_documents([fact("c_2"), fact("c_3"), fact("c_4")], EVIDENCE) == []


def test_a_quarantined_chunk_is_not_a_coverage_target():
    """G2 strips every citation to one (§7.4 trigger 4), so it can never be the gap to close."""
    evidence = [*EVIDENCE, chunk("c_5", "security-acceptable-use", quarantined=True)]
    assert breadth.uncited_documents([fact("c_1"), fact("c_3"), fact("c_4")], evidence) == []


def test_a_citation_to_a_chunk_outside_the_evidence_covers_nothing():
    assert breadth.uncited_documents([fact("c_9")], EVIDENCE) == [
        "travel-policy",
        "expenses-and-reimbursement",
        "manager-approval-matrix",
    ]


# --- what the repair call is told --------------------------------------------------------


def test_the_instruction_names_every_uncited_document_and_its_passages():
    text = breadth.instruction(["manager-approval-matrix"], EVIDENCE)
    assert "manager-approval-matrix" in text
    assert "c_4" in text
    assert "not used:" in text, "the alternative to citing it is naming it in rationale_summary"
    for cited in ("c_1", "c_2", "c_3"):
        assert cited not in text, "a covered document is not re-litigated"


# --- when the repaired answer replaces the first ------------------------------------------


def test_a_broader_answer_that_costs_nothing_replaces_the_first():
    assert breadth.accepted(
        [fact("c_1")],
        [fact("c_1"), fact("c_4")],
        EVIDENCE,
        dropped_blocks=0,
        refused=False,
    )


def test_an_answer_that_did_not_get_broader_is_kept_out():
    assert not breadth.accepted([fact("c_1")], [fact("c_2")], EVIDENCE, dropped_blocks=0, refused=False)


def test_an_answer_g2_had_to_drop_a_block_from_is_kept_out():
    assert not breadth.accepted(
        [fact("c_1")],
        [fact("c_1"), fact("c_4")],
        EVIDENCE,
        dropped_blocks=1,
        refused=False,
    )


def test_an_answer_g2_refused_is_kept_out():
    assert not breadth.accepted([fact("c_1")], [], EVIDENCE, dropped_blocks=0, refused=True)


def test_an_answer_that_bought_breadth_by_dropping_content_is_kept_out():
    """Broader is not better if a block the reader already had went missing to get there."""
    assert not breadth.accepted(
        [fact("c_1"), fact("c_3")],
        [fact("c_1", "c_3", "c_4")],
        EVIDENCE,
        dropped_blocks=0,
        refused=False,
    )
