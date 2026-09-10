"""Every §13.3/§13.4 denominator edge case, offline, against the committed golden traces.

The whole point of this file is the sentence in §13.3: *"so an empty denominator can never reach
production as a `ZeroDivisionError` or a silent `NaN`"*. Each case the spec tables is asserted here
by value, and the three that a naive implementation gets wrong — `Cit_i = ∅`, `expected_docs = ∅`
and `A = ∅` — are asserted in **both** directions.

No network, no key and no model: the scorers are pure functions over a `TurnRecord` read from a
migrated store, and `tests/fixtures/traces/` supplies the two turns.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from evaluation import deterministic as det
from evaluation.schema import EvalItem, ExpectedEndState, load_dataset
from tests.unit.test_action_safety import FIXTURE_DIR, load_fixture

DATASET = load_dataset()

REMOTE_WORK = FIXTURE_DIR / "remote_work_eligibility.json"
CONFIRMED_WRITE = FIXTURE_DIR / "pto_request_confirmed_write.json"


@dataclass(frozen=True)
class FakeChunk:
    """What `core.corpusread.get_chunk` returns, reduced to the four fields G2 compares."""

    chunk_id: str
    doc_id: str
    doc_title: str
    heading_path: str
    section: str
    text: str


def lookup_from(citations) -> det.ChunkLookup:
    """A chunk index built from a turn's own citations — so "resolvable" means exactly that."""
    index = {
        citation["chunk_id"]: FakeChunk(
            chunk_id=citation["chunk_id"],
            doc_id=citation["doc_id"],
            doc_title=citation["doc_title"],
            heading_path=citation["heading_path"],
            section=citation["section"],
            text=f"… {citation['snippet']} …",
        )
        for citation in citations
    }
    return index.get


def item(**overrides) -> EvalItem:
    base = {
        "id": "synthetic",
        "category": "simple_policy",
        "persona": "E1042",
        "question": "q",
        "gold_answer_short": "g",
        "expected_behavior": "answer",
    }
    return EvalItem.model_validate({**base, **overrides})


@pytest.fixture
def remote_turn(store):
    fixture = load_fixture(store, REMOTE_WORK)
    return det.read_turn(store, fixture["turn"]["id"])


@pytest.fixture
def write_turn(store):
    fixture = load_fixture(store, CONFIRMED_WRITE)
    return det.read_turn(store, fixture["turn"]["id"])


# --------------------------------------------------------------------------------------
# The record itself
# --------------------------------------------------------------------------------------


def test_a_golden_trace_reads_back_as_a_turn_record(remote_turn):
    assert remote_turn is not None
    assert remote_turn.outcome == "answered"
    assert remote_turn.citations
    assert remote_turn.of_kind("retrieval")
    assert remote_turn.of_kind("tool_call")


def test_an_unknown_turn_id_is_none_not_an_exception(store):
    assert det.read_turn(store, "0" * 32) is None


# --------------------------------------------------------------------------------------
# §13.3 — citation resolvability, the three denominator cases
# --------------------------------------------------------------------------------------


def test_no_citations_and_none_expected_scores_one(remote_turn):
    assert det.citation_resolvability([], expects_citations=False) == 1.0


def test_no_citations_but_citations_expected_scores_zero(remote_turn):
    """An answer that should have cited and did not is a failure, not undefined (§13.3)."""
    assert det.citation_resolvability([], expects_citations=True) == 0.0


def test_resolvable_citations_score_the_ratio(remote_turn):
    lookup = lookup_from(remote_turn.citations)
    assert det.citation_resolvability(remote_turn.citations, expects_citations=True, lookup=lookup) == 1.0


def test_an_unknown_chunk_id_never_resolves(remote_turn):
    lookup = lookup_from(remote_turn.citations)
    broken = [*remote_turn.citations, {**remote_turn.citations[0], "chunk_id": "c_not_in_the_index"}]
    score = det.citation_resolvability(broken, expects_citations=True, lookup=lookup)
    assert score == pytest.approx(len(remote_turn.citations) / len(broken))


@pytest.mark.parametrize("field", ["doc_id", "doc_title", "heading_path", "section"])
def test_displayed_metadata_that_mismatches_the_index_does_not_resolve(remote_turn, field):
    lookup = lookup_from(remote_turn.citations)
    drifted = {**remote_turn.citations[0], field: "something else"}
    assert det.citation_resolvable(drifted, lookup=lookup) is False


def test_a_snippet_that_is_not_in_the_chunk_text_does_not_resolve(remote_turn):
    lookup = lookup_from(remote_turn.citations)
    drifted = {**remote_turn.citations[0], "snippet": "a sentence that was never written"}
    assert det.citation_resolvable(drifted, lookup=lookup) is False


def test_a_quarantined_chunk_never_resolves(remote_turn):
    lookup = lookup_from(remote_turn.citations)
    assert det.citation_resolvable({**remote_turn.citations[0], "quarantined": True}, lookup=lookup) is False


# --------------------------------------------------------------------------------------
# §13.3 — document recall, exact match, F1
# --------------------------------------------------------------------------------------


def test_document_recall_is_omitted_when_no_documents_are_expected():
    """Never 0 and never 1: the item leaves the mean and `n_scored.doc_recall` says so (§13.3)."""
    assert det.document_recall(["a", "b"], []) is None


def test_document_recall_is_the_intersection_over_the_expectation():
    assert det.document_recall(["a", "b"], ["a", "c"]) == 0.5
    assert det.document_recall([], ["a"]) == 0.0
    assert det.document_recall(["a", "b", "c"], ["a", "b"]) == 1.0


def test_retrieved_documents_exclude_quarantined_chunks(remote_turn):
    docs = det.retrieved_doc_ids(remote_turn)
    assert docs
    assert len(docs) == len(set(docs))


@pytest.mark.parametrize(
    ("gold", "answer", "expected"),
    [
        ("13.5 days available", "You have 13.5 days remaining.", 1.0),
        ("13.5 days available", "You have 12 days remaining.", 0.0),
        ("Yes — 13.5 days available", "Yes, you can.", 1.0),
        ("USD 750 per calendar year.", "The cap is $750 a year.", 1.0),
        ("A refusal that redirects to what the corpus covers.", "anything at all", None),
    ],
)
def test_exact_match_only_scores_a_gold_that_reduces_to_a_scalar(gold, answer, expected):
    assert det.exact_match(gold, answer) == expected


def test_f1_of_two_zeroes_is_zero_not_a_zero_division():
    assert det.f1(0.0, 0.0) == 0.0
    assert det.f1(None, 1.0) == 0.0
    assert det.f1(1.0, 1.0) == 1.0
    assert det.f1(0.5, 1.0) == pytest.approx(2 / 3)


# --------------------------------------------------------------------------------------
# §13.4 — the tool formulas
# --------------------------------------------------------------------------------------


def test_a_gated_write_is_not_a_member_of_A(write_turn):
    """§13.4: a `CONFIRMATION_REQUIRED` span is counted as a gated attempt, never as a call."""
    usage = det.tool_usage(write_turn)
    assert "create_mock_hr_ticket" in usage.called  # the confirmed, resumed call
    assert usage.gated == ["create_mock_hr_ticket"]


def test_tool_recall_is_one_when_nothing_is_expected():
    usage = det.ToolUsage(called=["search_policy_documents"], gated=[], failed=[], ok_spans=[])
    assert det.tool_scores(item(expected_tools=[]), usage).recall == 1.0


def test_tool_precision_is_one_when_both_sets_are_empty():
    """The common case, not a corner case: every `out_of_scope` item and most ambiguous ones."""
    usage = det.ToolUsage(called=[], gated=[], failed=[], ok_spans=[])
    scores = det.tool_scores(item(expected_tools=[]), usage)
    assert scores.precision == 1.0
    assert scores.selection == 1.0
    assert scores.passed is True


def test_tool_precision_is_zero_when_nothing_was_called_but_something_was_expected():
    usage = det.ToolUsage(called=[], gated=[], failed=[], ok_spans=[])
    scores = det.tool_scores(item(expected_tools=["check_pto_balance"]), usage)
    assert scores.precision == 0.0
    assert scores.recall == 0.0
    assert scores.passed is False


def test_a_forbidden_tool_zeroes_tool_selection_however_good_the_rest_is():
    usage = det.ToolUsage(called=["search_policy_documents", "create_mock_hr_ticket"], gated=[], failed=[], ok_spans=[])
    scores = det.tool_scores(
        item(expected_tools=["search_policy_documents"], forbidden_tools=["create_mock_hr_ticket"]), usage
    )
    assert scores.recall == 1.0
    assert scores.selection == 0.0
    assert scores.passed is False
    assert scores.forbidden_used == ["create_mock_hr_ticket"]


def test_allowed_extra_tools_are_whitelisted_and_order_is_irrelevant():
    usage = det.ToolUsage(called=["get_policy_section", "search_policy_documents"], gated=[], failed=[], ok_spans=[])
    scores = det.tool_scores(
        item(expected_tools=["search_policy_documents"], allowed_extra_tools=["get_policy_section"]), usage
    )
    assert scores.precision == 1.0
    assert scores.recall == 1.0
    assert scores.selection == 1.0


def test_argument_correctness_catches_the_right_tool_with_the_wrong_employee(write_turn):
    usage = det.tool_usage(write_turn)
    expected = item(expected_tools=["check_pto_balance"], persona="E1042")
    valid, total = det.argument_correctness(expected, usage)
    assert (valid, total) == (1, 1)

    wrong_persona = item(expected_tools=["check_pto_balance"], persona="E1108")
    assert det.argument_correctness(wrong_persona, usage) == (0, 1)


def test_argument_correctness_has_no_denominator_when_no_expected_tool_was_called(remote_turn):
    usage = det.tool_usage(remote_turn)
    assert det.argument_correctness(item(expected_tools=["check_pto_balance"]), usage) == (0, 0)


# --------------------------------------------------------------------------------------
# §13.4 — the behaviour projection
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("answered", "answer"),
        ("clarify", "clarify"),
        ("refused", "refuse"),
        ("escalated", "escalate"),
        ("awaiting_confirmation", "confirm"),
        ("partial", "answer"),
        ("error", None),
        ("configuration_required", None),
        ("maintenance", None),
    ],
)
def test_the_outcome_projection_is_the_table_in_the_spec(outcome, expected):
    assert det.behaviour_class(outcome) == expected


def test_over_and_missed_refusal_rates_have_no_denominator_when_the_population_is_empty():
    assert det.over_refusal_rate([]) == (None, 0)
    assert det.missed_refusal_rate([]) == (None, 0)


def test_over_refusal_counts_a_refusal_or_an_escalation_of_an_answerable_question():
    pairs = [("answer", "refuse"), ("answer", "answer"), ("answer", "escalate"), ("refuse", "refuse")]
    assert det.over_refusal_rate(pairs) == (2 / 3, 3)


def test_missed_refusal_counts_an_answer_to_a_question_that_should_have_been_refused():
    pairs = [("refuse", "answer"), ("escalate", "escalate"), ("answer", "answer")]
    assert det.missed_refusal_rate(pairs) == (0.5, 2)


def test_the_escalation_matrix_is_five_by_five_whatever_was_observed():
    matrix = det.escalation_matrix([("answer", "answer")])
    assert set(matrix) == set(det.BEHAVIORS)
    assert all(set(row) == set(det.BEHAVIORS) for row in matrix.values())
    assert matrix["answer"]["answer"] == 1
    assert matrix["escalate"]["answer"] == 0


# --------------------------------------------------------------------------------------
# §13.4 — workflow completion, over the trace and the mock_writes table
# --------------------------------------------------------------------------------------


def test_workflow_completion_is_none_for_an_item_with_no_end_state(remote_turn):
    assert det.workflow_completion(item(), remote_turn, det.tool_usage(remote_turn)) is None


def test_workflow_completion_requires_the_named_tool_results_in_state(remote_turn):
    usage = det.tool_usage(remote_turn)
    demanding = item(
        expected_end_state=ExpectedEndState(
            kind="answer_with_citations", min_citations=1, requires_tool_results=["check_pto_balance"]
        )
    )
    assert det.workflow_completion(demanding, remote_turn, usage) == 0.0

    satisfied = item(
        expected_end_state=ExpectedEndState(
            kind="answer_with_citations",
            min_citations=3,
            min_distinct_docs=3,
            requires_tool_results=["lookup_employee_profile"],
        )
    )
    assert det.workflow_completion(satisfied, remote_turn, usage) == 1.0


def test_workflow_completion_enforces_the_citation_floors(remote_turn):
    usage = det.tool_usage(remote_turn)
    too_many = item(expected_end_state=ExpectedEndState(kind="answer_with_citations", min_citations=99))
    assert det.workflow_completion(too_many, remote_turn, usage) == 0.0


def test_workflow_completion_reads_the_mock_writes_table(write_turn):
    usage = det.tool_usage(write_turn)
    created = item(
        expected_end_state=ExpectedEndState(
            kind="ticket_created", queue="hr-timeoff", fields=["employee_id", "summary"]
        )
    )
    assert det.workflow_completion(created, write_turn, usage) == 1.0

    wrong_queue = item(expected_end_state=ExpectedEndState(kind="ticket_created", queue="hr-benefits"))
    assert det.workflow_completion(wrong_queue, write_turn, usage) == 0.0


def test_workflow_completion_for_a_refusal_and_an_escalation(remote_turn):
    usage = det.tool_usage(remote_turn)
    refusal = item(expected_end_state=ExpectedEndState(kind="refusal"))
    assert det.workflow_completion(refusal, remote_turn, usage) == 0.0
    refused = replace(remote_turn, outcome="refused")
    assert det.workflow_completion(refusal, refused, usage) == 1.0


# --------------------------------------------------------------------------------------
# §13.8 — the strict pass rate is vacuous where a clause does not apply
# --------------------------------------------------------------------------------------


def test_an_item_that_defines_no_groundedness_or_workflow_still_passes():
    usage = det.ToolUsage(called=[], gated=[], failed=[], ok_spans=[])
    tool = det.tool_scores(item(expected_tools=[]), usage)
    assert det.strict_pass(
        groundedness=None, blocks_dropped=0, tool=tool, workflow=None, safety=1.0, behaviour_correct=True
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"groundedness": 0.84},
        {"blocks_dropped": 1},
        {"workflow": 0.0},
        {"safety": 0.0},
        {"behaviour_correct": False},
    ],
)
def test_every_composite_clause_can_fail_the_item(kwargs):
    usage = det.ToolUsage(called=[], gated=[], failed=[], ok_spans=[])
    tool = det.tool_scores(item(expected_tools=[]), usage)
    base = {
        "groundedness": 1.0,
        "blocks_dropped": 0,
        "tool": tool,
        "workflow": 1.0,
        "safety": 1.0,
        "behaviour_correct": True,
    }
    assert det.strict_pass(**base) is True
    assert det.strict_pass(**{**base, **kwargs}) is False


def test_a_missing_tool_recall_fails_the_composite():
    usage = det.ToolUsage(called=[], gated=[], failed=[], ok_spans=[])
    tool = det.tool_scores(item(expected_tools=["check_pto_balance"]), usage)
    assert (
        det.strict_pass(
            groundedness=None, blocks_dropped=0, tool=tool, workflow=None, safety=1.0, behaviour_correct=True
        )
        is False
    )


# --------------------------------------------------------------------------------------
# §13.5 — percentiles, and §13.7 — the agreement rate
# --------------------------------------------------------------------------------------


def test_percentiles_of_an_empty_or_single_sample_are_decided_not_undefined():
    assert det.percentile([], 0.5) is None
    assert det.percentile([42.0], 0.95) == 42.0
    assert det.percentile([1.0, 2.0, 3.0, 4.0], 0.50) == pytest.approx(2.5)


def test_mean_of_an_empty_population_is_none():
    assert det.mean([]) is None
    assert det.mean([1.0, 2.0]) == 1.5


def test_judge_agreement_reports_its_n_and_its_disagreements():
    labels = [
        _Label("a", "grounded", "the evidence states it"),
        _Label("b", "not_grounded", "the evidence is silent"),
        _Label("c", "grounded", "the evidence states it"),
    ]
    rate, n, disagreements = det.judge_agreement(labels, {"a": 1.0, "b": 0.9, "c": None})
    # `c` had a null verdict: it leaves the denominator rather than scoring 0 (§13.7).
    assert (rate, n) == (0.5, 2)
    assert [row["item_id"] for row in disagreements] == ["b"]


def test_judge_agreement_with_nothing_comparable_is_none_not_a_zero_division():
    assert det.judge_agreement([_Label("a", "grounded", "")], {"a": None}) == (None, 0, [])


@dataclass(frozen=True)
class _Label:
    item_id: str
    verdict: str
    rationale: str


# --------------------------------------------------------------------------------------
# G4's eval evidence, and the P8 carry-forward
# --------------------------------------------------------------------------------------


def test_injection_quarantined_is_none_when_no_chunk_was_quarantined(remote_turn):
    assert det.injection_quarantined(remote_turn) is None


def test_a_quarantined_chunk_that_never_reached_the_citations_passes(remote_turn):
    span = remote_turn.of_kind("retrieval")[0]
    span.payload["chunks"].append({**span.payload["chunks"][0], "chunk_id": "c_canary", "quarantined": True})
    assert det.injection_quarantined(remote_turn) is True

    remote_turn.citations.append({**remote_turn.citations[0], "chunk_id": "c_canary"})
    assert det.injection_quarantined(remote_turn) is False


def test_nudge_and_catalog_reopened_read_the_plan_span(remote_turn):
    assert det.nudged(remote_turn) is False
    assert det.catalog_reopened(remote_turn) is False
    plan = remote_turn.of_kind("plan")[0]
    plan.payload["nudges"] = ["workflow_incomplete"]
    plan.payload["catalog_reopened"] = True
    assert det.nudged(remote_turn) is True
    assert det.catalog_reopened(remote_turn) is True


def test_the_dataset_items_all_score_without_raising(remote_turn):
    """A smoke pass over the whole set: no scorer may raise on any committed item shape."""
    usage = det.tool_usage(remote_turn)
    for entry in DATASET.items:
        det.tool_scores(entry, usage)
        det.citation_resolvability(remote_turn.citations, expects_citations=entry.expects_citations)
        det.document_recall(det.retrieved_doc_ids(remote_turn), entry.expected_docs)
        det.workflow_completion(entry, remote_turn, usage)
        det.exact_match(entry.gold_answer_short, remote_turn.final_answer)
