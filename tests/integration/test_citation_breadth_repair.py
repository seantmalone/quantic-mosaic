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

import pytest

from hrmosaic.agent.client import McpClient
from hrmosaic.agent.orchestrator import ChatRequest, Orchestrator
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

    stripped = [
        entry
        for kind, name, payload in spans(response.turn_id)
        if kind == "guardrail" and name.startswith("G2")
        for entry in payload["details"]["stripped"]
    ]
    assert [entry["chunk_id"] for entry in stripped] == ["c_0000000000000000"]
