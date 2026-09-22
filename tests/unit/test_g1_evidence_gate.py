"""G1 `evidence_gate` (spec §7.4 row G1, §9.2).

Three things are asserted here, and the third is the one that costs a rubric point:

1. the rule itself — both triggers, and the fact that it is **total** because §7.1's fill step
   gives every fused candidate a dense score, including one that entered from the BM25 arm only;
2. the refusal — it names what the corpus *does* cover, read from `core.corpusread.list_documents()`
   rather than from a hard-coded list, and it never states a policy;
3. **an out-of-scope turn produces no `tool_call` span** (§9.2). §13.4 scores `ToolPrecision = 1.0`
   when both the called and the expected tool sets are empty, so a refusal that issued a
   `list_policy_documents` call to find out what the corpus covers would score 0.0 for exemplary
   behaviour. That one runs the whole loop against the real MCP server, so "zero tool calls" is a
   fact about a real session rather than about a stand-in that could not have called anything.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from hrmosaic.agent.guardrails import g1
from hrmosaic.agent.orchestrator import ChatRequest
from hrmosaic.core import corpusread

pytestmark = pytest.mark.anyio


@dataclass(frozen=True)
class Candidate:
    """A fused candidate, carrying the one score of §7.1 and the fusion weight that is not it."""

    dense_score: float
    rrf_score: float = 0.03
    bm25_rank: int | None = None


def test_a_strong_candidate_set_passes():
    verdict = g1.evaluate([Candidate(0.71), Candidate(0.64), Candidate(0.48)])
    assert verdict.passed
    assert verdict.max_dense_score == 0.71
    assert verdict.supporting == 3


def test_everything_below_the_evidence_threshold_refuses():
    # The out-of-scope band this corpus actually produces: P10's calibration measured every
    # out-of-corpus probe at `max_dense_score` ≤ 0.584 against an in-scope floor of 0.622.
    verdict = g1.evaluate([Candidate(0.58), Candidate(0.57), Candidate(0.54)])
    assert not verdict.passed
    # Two decimal places since UX W4: the span's arithmetic at the precision the 0-1 scale carries.
    assert "evidence-gate score 0.58 < 0.60" in verdict.reason


def test_one_strong_chunk_alone_is_not_enough_support():
    verdict = g1.evaluate([Candidate(0.71), Candidate(0.11)])
    assert not verdict.passed
    assert "1 passage at or above 0.45" in verdict.reason, "the noun agrees with the count (P9)"


def test_an_empty_candidate_set_refuses():
    verdict = g1.evaluate([])
    assert not verdict.passed
    assert verdict.reason == g1.NO_EVIDENCE
    assert verdict.max_dense_score == 0.0


def test_a_performed_write_grounds_a_turn_the_evidence_clauses_would_refuse():
    """G5, gap 21: the exemption passes the verdict and keeps the measurement in the reason.

    `MOCK-EMAIL-000018` existed and its turn was refused here at `candidates: 0`, because "draft me
    an email to my manager" searches nothing.
    """
    verdict = g1.evaluate([], grounded_by_write=True)

    assert verdict.passed
    assert verdict.reason == f"{g1.PERFORMED_WRITE}: {g1.NO_EVIDENCE}"
    assert (verdict.max_dense_score, verdict.supporting, verdict.candidates) == (0.0, 0, 0)
    # The weak-evidence clause keeps its arithmetic behind the exemption too.
    weak = g1.evaluate([Candidate(0.58), Candidate(0.57)], grounded_by_write=True)
    assert weak.passed
    assert weak.reason.startswith(g1.PERFORMED_WRITE)
    assert "evidence-gate score 0.58 < 0.60" in weak.reason


def test_the_exemption_changes_nothing_when_it_is_not_set():
    """The flag defaults off, and a passing set is not relabelled by it."""
    assert g1.evaluate([]) == g1.evaluate([], grounded_by_write=False)
    assert not g1.evaluate([], grounded_by_write=False).passed

    strong = [Candidate(0.71), Candidate(0.64)]
    assert g1.evaluate(strong) == g1.evaluate(strong, grounded_by_write=True), "no clause failed to exempt"


def test_a_bm25_only_candidate_is_judged_on_its_dense_score_not_its_rrf_score():
    """§7.1's fill step scores BM25-only arrivals, so the rule is total (§7.4 row G1).

    `rrf_score`'s theoretical maximum for two arms is ~0.033, so a gate that read it would refuse
    every query at the project's own defaults. Both candidates below carry that maximum; only the
    dense score separates them.
    """
    retained = g1.evaluate([Candidate(0.71, rrf_score=0.03, bm25_rank=1), Candidate(0.64, bm25_rank=2)])
    dropped = g1.evaluate([Candidate(0.10, rrf_score=0.03, bm25_rank=1), Candidate(0.09, bm25_rank=2)])
    assert retained.passed
    assert not dropped.passed


def test_the_thresholds_are_configurable_so_the_ablation_can_move_them():
    candidates = [Candidate(0.31), Candidate(0.30)]
    assert not g1.evaluate(candidates).passed
    assert g1.evaluate(candidates, min_evidence_score=0.20, min_support_score=0.10).passed


def test_the_span_records_the_observed_scores(writer, spans):
    turn = writer.start_turn(writer_session(), user_message="pto accrual")
    g1.check([Candidate(0.11), Candidate(0.09)], turn=turn, evidence_span_ids=["a" * 16])
    turn.close(outcome="refused", stop_reason="refused")

    guardrails = [payload for kind, _, payload in spans(turn.turn_id) if kind == "guardrail"]
    assert len(guardrails) == 1
    payload = guardrails[0]
    assert (payload["rule_id"], payload["rule_name"], payload["verdict"]) == ("G1", "evidence_gate", "refuse")
    assert payload["details"]["max_dense_score"] == 0.11
    assert payload["details"]["supporting_chunks"] == 0
    assert payload["evidence_span_ids"] == ["a" * 16]


def test_the_refusal_names_what_the_corpus_covers_in_plain_topics():
    answer = g1.refusal(g1.OUT_OF_SCOPE)
    titles = [document.doc_title for document in corpusread.list_documents()]

    # The product's own voice, not advice (W8, C17): rendered bare, with no heading over it and no
    # "Suggestions are guidance, not company policy" under it.
    assert [block.type for block in answer.blocks] == ["notice"], "a refusal cites nothing"
    assert answer.blocks[0].citations == []
    covered = " ".join(answer.next_steps)
    # Five topics, not five titles, and not all fourteen. The title slice this replaced came off a
    # query ordered `BY doc_id`, so it was alphabetical and structurally excluded PTO, remote work,
    # travel and tax — every topic the product is demonstrated on (UX W6, cpux-re-8 = JX-R8). The
    # inventory moved to `/policy`, which the turn links to (UX W3, jargon-and-exposure-3).
    assert [topic for topic in g1.EXAMPLE_TOPICS if topic in covered] == list(g1.EXAMPLE_TOPICS)
    assert not [title for title in titles if title in covered], "topics a person would say, not filenames"
    assert len(titles) > g1.EXAMPLE_TOPIC_COUNT, "the library is bigger than the sample it is introduced by"
    # The reader is told the boundary; the clause that measured it stays on the span (UX W2,
    # numbers-precision-overflow-3, jargon-and-exposure-3).
    # …and the copy matches the reason (W8, C19): an out-of-scope turn searched nothing, so it
    # makes no claim to have searched. `test_refusal_copy_states_the_reason_it_had` pins the pair.
    assert answer.blocks[0].text == g1.OUT_OF_SCOPE_REFUSAL
    assert g1.OUT_OF_SCOPE not in answer.blocks[0].text
    assert g1.OUT_OF_SCOPE in answer.rationale_summary
    assert "tools" not in answer.blocks[0].text, "a reader counting the assistant's tools is a grader"


async def test_an_out_of_scope_turn_makes_no_tool_call(run_agent, spans):
    """§9.2: the redirect must issue **zero** `tools/call`, or ToolPrecision scores 0.0."""
    response = await run_agent(
        "out_of_scope.json",
        ChatRequest(message="Who won the 1998 World Cup final?", employee_id="E1042"),
    )

    assert response.outcome == "refused"
    kinds = [kind for kind, _, _ in spans(response.turn_id)]
    assert "tool_call" not in kinds, "a refusal that calls a tool scores ToolPrecision 0.0 (§13.4)"
    assert "retrieval" not in kinds
    assert kinds.count("mcp_discovery") == 1, "discovery still happens: it is a per-turn record (§8.2)"
    assert response.usage.tool_calls == 0


async def test_the_zero_llm_pre_check_refuses_before_the_router_runs(run_agent, spans):
    """§9.1 step 0: an obviously non-HR question never reaches the model at all."""
    response = await run_agent(
        "out_of_scope.json",
        ChatRequest(message="What is the weather in Berlin tomorrow?", employee_id="E1042"),
    )

    assert response.outcome == "refused"
    assert response.usage.llm_calls == 0, "the pre-check exists to save the free-tier quota"
    assert [kind for kind, _, _ in spans(response.turn_id)].count("tool_call") == 0


def writer_session():
    from hrmosaic.core.trace import SessionSpec

    return SessionSpec(client_label="api")


def test_refusal_copy_states_the_reason_it_had():
    """W8, C19: `fresh:f2250fa0…:1` recorded `{"tool_calls": 0, "retrievals": 0}` and no G1 span,
    and told the reader a search of the policy library had come back empty. It had not searched."""
    searched = g1.refusal(g1.NO_EVIDENCE).blocks[0].text
    weak = g1.refusal(f"{g1.WEAK_EVIDENCE}: evidence-gate score 0.42 < 0.60").blocks[0].text
    out_of_scope = g1.refusal(g1.OUT_OF_SCOPE).blocks[0].text

    assert "policy library" in searched and "policy library" in weak
    assert "policy library" not in out_of_scope
    assert "could not find" not in out_of_scope, "a turn that searched nothing claims no search"
    assert out_of_scope == g1.OUT_OF_SCOPE_REFUSAL
    # The diagnostic never reaches the reader, whichever branch was taken.
    assert "0.42" not in weak and "0.60" not in weak
