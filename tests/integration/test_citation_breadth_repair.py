"""The citation-breadth repair, end to end over a real MCP server (spec §7.4, P24).

`expenses-002` in the published run `r_1789086979_baseline` cited two of the five documents its own
evidence spanned and lost the approval rule the question asked for. The step here is what closes
that gap: on a multi-document turn whose answer is narrower than its citable evidence, ONE more
synthesis call names the uncited documents, and the second answer replaces the first only if it is
strictly broader and G2/G3 cost it nothing.

Nothing is mocked below the model: the two searches run against the shipped MCP server and the real
index, so the documents the step names are the ones retrieval actually returned, and the citations
the repair adds resolve — or fail to — against the committed chunks.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent import orchestrator as agent_orchestrator
from hrmosaic.agent.client import McpClient
from hrmosaic.agent.orchestrator import BUDGET_NOTE, ChatRequest, Orchestrator
from hrmosaic.core.llm.stub import load_script
from hrmosaic.settings import settings
from tests.conftest import LLM_SCRIPTS
from tests.integration.test_act_loop_wire_shape import _Recorder

pytestmark = pytest.mark.anyio

QUESTION = "For a USD 3,000 conference trip, how far ahead must travel be booked, and who approves the spend?"

#: `tests/fixtures/llm_scripts/rag_only.json`'s question — one document answers it, and its router
#: decision carries `multi_doc: false` with no workflow.
SINGLE_DOC_QUESTION = "How much PTO do I accrue each month?"


async def drive(script: str, message: str = QUESTION):
    recorder = _Recorder(LLM_SCRIPTS / script)
    orchestrator = Orchestrator(client=McpClient(transport="stdio"), model=recorder)
    try:
        response = await orchestrator.run_turn(ChatRequest(message=message, employee_id="E1042"))
    finally:
        await orchestrator.aclose()
    return response, recorder


async def test_a_narrow_answer_on_a_multi_document_turn_is_broadened(writer):
    response, recorder = await drive("citation_breadth_repair.json")

    assert response.outcome == "answered"
    assert [purpose for purpose, _ in recorder.calls].count("repair") == 1, "one extra call, never two"
    documents = {citation.doc_id for citation in response.citations}
    assert documents == {"travel-policy", "expenses-and-reimbursement", "manager-approval-matrix"}
    assert "USD 2,500" in response.answer, "the block the repair added reaches the reader"


async def test_the_repair_call_is_told_which_documents_are_uncited(writer):
    _, recorder = await drive("citation_breadth_repair.json")

    ask = next(messages for purpose, messages in recorder.calls if purpose == "repair")
    assert [message.role for message in ask] == ["system", "user", "assistant", "user"], "it continues the synthesis"
    instruction = ask[-1].content
    assert "BREADTH CHECK" in instruction
    assert "manager-approval-matrix" in instruction and "expenses-and-reimbursement" in instruction
    assert "travel-policy" not in instruction, "the document the answer already cites is not re-litigated"


async def test_a_single_document_turn_never_pays_for_the_second_call(writer):
    """The gate: `multi_doc` false and no workflow, so the step is not reached at all."""
    response, recorder = await drive("rag_only.json", SINGLE_DOC_QUESTION)

    assert response.outcome == "answered"
    assert [purpose for purpose, _ in recorder.calls].count("repair") == 0


async def test_a_repair_that_fails_g2_keeps_the_first_answer(writer, spans):
    """The broader answer cites an id the index does not hold: G2 drops the block, so it is refused."""
    response, recorder = await drive("citation_breadth_unresolvable.json")

    assert [purpose for purpose, _ in recorder.calls].count("repair") == 1, "the call was still made"
    assert {citation.doc_id for citation in response.citations} == {"travel-policy"}
    assert "USD 2,500" not in response.answer, "the block G2 dropped never reached the reader"
    assert response.outcome == "answered"

    # A rejected repair is a draft nobody was shown, so no `guardrail` span carries a verdict on
    # it: §13.3's `blocks_dropped_by_g2` sums every G2 span of the turn, and a draft's drop would
    # otherwise be published as a grounded fact the reader lost.
    g2_spans = [
        payload for kind, name, payload in spans(response.turn_id) if kind == "guardrail" and name.startswith("G2")
    ]
    assert len(g2_spans) == 1, "only the served answer's verification is recorded"
    assert g2_spans[0]["details"]["blocks_dropped"] == 0
    assert "c_0000000000000000" not in json.dumps(g2_spans)


def clock_that_jumps_after(monkeypatch, *, steps: int) -> None:
    """Make the turn's wall clock read past `AGENT_WALL_CLOCK_S` once `steps` act steps are done.

    `tests/unit/test_agent_budgets.py` leaves the third budget unexercised because a test that
    burned 90 s of real clock would be the slowest thing in the suite by two orders of magnitude.
    Moving the clock instead of the limit keeps the assertion on the shipped `AGENT_WALL_CLOCK_S`
    and drives the real `turn.elapsed_s >= settings.agent_wall_clock_s` check in `_act`.
    """
    past = settings.agent_wall_clock_s + 1.0
    monkeypatch.setattr(
        agent_orchestrator._Turn,
        "elapsed_s",
        property(lambda turn: 0.0 if turn.steps_taken < steps else past),
    )


async def test_a_timed_out_multi_document_turn_never_buys_the_repair_call(writer, spans, monkeypatch):
    """§9.4's budget stop bounds the turn, so step 5b does not spend one more call widening it.

    The clock runs out inside the act loop of a multi-document turn whose first answer is narrow —
    exactly the shape the breadth step exists for — and the answer the reader gets is the graceful
    partial. Widening it would cost a second synthesis-sized round trip (~15 s at the deployed p50)
    and one more call against `LLM_DAILY_CALL_CAP` on the one turn the budget was there to bound.
    """
    clock_that_jumps_after(monkeypatch, steps=1)

    response, recorder = await drive("citation_breadth_timeout.json")

    assert [purpose for purpose, _ in recorder.calls].count("repair") == 0, "the budget stop skips the step"
    assert load_script(LLM_SCRIPTS / "citation_breadth_timeout.json")[-1]["purpose"] == "repair", (
        "the script must still hold the repair the gate refused, or the absence above proves nothing"
    )

    assert response.outcome == "partial"
    errors = [payload for kind, _, payload in spans(response.turn_id) if kind == "error"]
    assert [payload["error_kind"] for payload in errors] == ["timeout"]
    assert response.answer_blocks[0].text == BUDGET_NOTE["timeout"]
    assert {citation.doc_id for citation in response.citations} == {"travel-policy"}, "the narrow answer stands"


async def test_a_turn_whose_clock_ran_out_during_synthesis_also_skips_the_step(writer, spans, monkeypatch):
    """The other half of the gate: the loop finished inside 90 s and synthesis carried it past.

    `stop_reason` is `answered` here — no budget stop was ever recorded — so the clock has to be
    re-read at step 5b rather than inferred from the stop reason alone.
    """
    clock_that_jumps_after(monkeypatch, steps=2)

    response, recorder = await drive("citation_breadth_repair.json")

    assert [purpose for purpose, _ in recorder.calls].count("repair") == 0
    assert response.outcome == "answered"
    assert [kind for kind, _, _ in spans(response.turn_id) if kind == "error"] == []
    assert {citation.doc_id for citation in response.citations} == {"travel-policy"}
