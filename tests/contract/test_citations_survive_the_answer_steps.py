"""The served answer cites at least what the breadth repair produced (W9 addendum, ruling 2).

`remote-002` — multi-document, `answer_with_citations` with three distinct documents required —
reached the breadth repair citing three documents and was served citing two. Two things are
pinned here, through the whole orchestrator on demo task 1's recorded exchange: the repair still
runs after W8's reordering of the answer steps (inside the budget), and no step between it and the
served answer drops a document it produced.
"""

from __future__ import annotations

import json

import pytest

from hrmosaic.agent import breadth
from hrmosaic.agent.orchestrator import BUDGET_STOPS, ChatRequest

pytestmark = pytest.mark.anyio

DEMO_1 = (
    "I'd like to work from Berlin, Germany for six weeks starting 3 November 2026. "
    "Am I eligible, and what approvals do I need?"
)


async def test_the_repair_runs_and_the_served_answer_cites_every_document_it_produced(
    run_agent, mounted_mcp_url, store, monkeypatch
):
    produced: list[set[str]] = []
    merge = breadth.merge

    def capturing_merge(blocks):
        merged, away = merge(blocks)
        produced.append({citation for block in merged for citation in block.get("citations") or []})
        return merged, away

    monkeypatch.setattr(breadth, "merge", capturing_merge)
    response = await run_agent(
        "demo_task_1.json", ChatRequest(message=DEMO_1, employee_id="E1042"), url=mounted_mcp_url
    )
    spans = store.execute(
        "SELECT kind, name, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (response.turn_id,)
    ).dicts()
    payloads = [(row["kind"], json.loads(row["payload_json"])) for row in spans]

    # The breadth repair ran: a second synthesis-purpose call, and no budget stop cut it off.
    purposes = [payload.get("purpose") for kind, payload in payloads if kind == "llm_call"]
    assert purposes.count("synthesize") + purposes.count("repair") >= 2, purposes
    turn = store.execute("SELECT stop_reason, outcome FROM turns WHERE id = ?", (response.turn_id,)).one()
    assert turn["stop_reason"] not in BUDGET_STOPS and turn["outcome"] == "answered", dict(turn)

    # …and every chunk the repair produced is still cited by a served block, so every document is.
    assert produced, "the merge step ran on the post-repair blocks"
    served = {citation for block in response.answer_blocks for citation in block.citations}
    assert served >= produced[0], f"lost: {produced[0] - served}"
    doc_of = {citation.chunk_id: citation.doc_id for citation in response.citations}
    served_docs = {doc_of[chunk] for chunk in served if chunk in doc_of}
    produced_docs = {doc_of[chunk] for chunk in produced[0] if chunk in doc_of}
    assert served_docs >= produced_docs and len(served_docs) >= 3, (served_docs, produced_docs)
