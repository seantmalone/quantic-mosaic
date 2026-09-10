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
    verdict = g1.evaluate([Candidate(0.71), Candidate(0.44), Candidate(0.28)])
    assert verdict.passed
    assert verdict.max_dense_score == 0.71
    assert verdict.supporting == 3


def test_everything_below_the_evidence_threshold_refuses():
    verdict = g1.evaluate([Candidate(0.31), Candidate(0.30), Candidate(0.29)])
    assert not verdict.passed
    assert "0.310" in verdict.reason and "0.32" in verdict.reason


def test_one_strong_chunk_alone_is_not_enough_support():
    verdict = g1.evaluate([Candidate(0.71), Candidate(0.11)])
    assert not verdict.passed
    assert "1 chunk(s) at or above 0.26" in verdict.reason


def test_an_empty_candidate_set_refuses():
    verdict = g1.evaluate([])
    assert not verdict.passed
    assert verdict.reason == g1.NO_EVIDENCE
    assert verdict.max_dense_score == 0.0


def test_a_bm25_only_candidate_is_judged_on_its_dense_score_not_its_rrf_score():
    """§7.1's fill step scores BM25-only arrivals, so the rule is total (§7.4 row G1).

    `rrf_score`'s theoretical maximum for two arms is ~0.033, so a gate that read it would refuse
    every query at the project's own defaults. Both candidates below carry that maximum; only the
    dense score separates them.
    """
    retained = g1.evaluate([Candidate(0.71, rrf_score=0.03, bm25_rank=1), Candidate(0.44, bm25_rank=2)])
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


def test_the_refusal_names_what_the_corpus_covers_from_the_real_index():
    answer = g1.refusal(g1.OUT_OF_SCOPE, tool_names=("search_policy_documents",))
    titles = [document.doc_title for document in corpusread.list_documents()]

    assert [block.type for block in answer.blocks] == ["recommendation"], "a refusal cites nothing"
    assert answer.blocks[0].citations == []
    covered = " ".join(answer.next_steps)
    assert titles and all(title in covered for title in titles)


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
