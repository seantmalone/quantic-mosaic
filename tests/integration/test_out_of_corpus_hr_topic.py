"""An HR question this corpus does not answer is refused, not improvised (spec §7.4 G1, P24).

The 2026-09-11 grade card's R3.4 finding: all three `out_of_scope` items were non-HR trivia — a
capital city, a linked list, a weather forecast — each refused by the router before a single chunk
was read. The case that actually matters was never probed: a question whose **topic** is HR, that
an employee would plausibly ask, and that the corpus does not carry, which is exactly where a
model's parametric idea of "what companies usually offer" leaks into an answer. `oos-004` (tuition
reimbursement) and `oos-005` (employee referral bonus) are that probe in `dataset.yaml`; this is the
same shape end to end, against the real MCP server and the real index.

Nothing is faked below the model: the search really runs, and the chunks it returns are the ones the
committed index holds for tuition — Expenses' professional-development budget, the non-reimbursable
list — none of which reaches `MIN_EVIDENCE_SCORE`. The refusal is therefore G1's, on real scores.
"""

from __future__ import annotations

import pytest

from hrmosaic.agent.client import McpClient
from hrmosaic.agent.orchestrator import ChatRequest, Orchestrator
from hrmosaic.core.llm.stub import StubAdapter
from tests.conftest import LLM_SCRIPTS

pytestmark = pytest.mark.anyio

QUESTION = (
    "What is Mosaic's tuition reimbursement cap for a part-time master's degree, "
    "and how many years of service do I need to qualify?"
)


@pytest.fixture
async def refused(writer):
    orchestrator = Orchestrator(
        client=McpClient(transport="stdio"),
        model=StubAdapter(script_path=LLM_SCRIPTS / "out_of_corpus_tuition.json"),
    )
    try:
        yield await orchestrator.run_turn(ChatRequest(message=QUESTION, employee_id="E1042"))
    finally:
        await orchestrator.aclose()


async def test_the_turn_refuses_rather_than_answering_from_parametric_knowledge(refused):
    assert refused.outcome == "refused"
    assert refused.citations == [], "a refusal cites nothing"
    assert "USD" not in refused.answer and "tuition" not in refused.answer.lower(), "no cap is invented"


async def test_the_refusal_redirects_to_what_the_corpus_does_cover(refused):
    """§7.4 G1: refuse **and** redirect, naming the library rather than leaving the reader nowhere."""
    assert "The corpus covers:" in refused.answer
    assert "Expenses & Reimbursement Policy" in refused.answer, "the library is named, read from the index"
    assert "people-ops@mosaicrobotics.example" in refused.answer, "and a human to ask instead"


async def test_the_search_really_ran_and_really_returned_weakly_related_chunks(refused, spans):
    records = spans(refused.turn_id)
    retrievals = [payload for kind, _, payload in records if kind == "retrieval"]
    assert retrievals, "the turn searched the corpus for real"
    scores = [payload["max_dense_score"] for payload in retrievals if payload["max_dense_score"] is not None]
    assert scores and max(scores) < 0.60, f"the fixture needs weak evidence; got {max(scores):.3f}"

    gate = [payload for kind, name, payload in records if kind == "guardrail" and name.startswith("G1")]
    assert gate and gate[-1]["verdict"] == "refuse"
