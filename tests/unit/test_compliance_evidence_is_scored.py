"""G1 counts the compliance engine's evidence — scored, never admitted on trust (P13 R7, §7.4).

`check_policy_compliance` is deterministic: every requirement it evaluates carries an `evidence`
block naming a **committed** chunk of the corpus, resolved by `mcpserver/rules.py` from a
`(doc_id, heading_path)` pair in `corpus/rules.yml`. Those chunk ids were invisible to the evidence
gate, because G1 scores retrieved candidates and nothing had ever scored these. A turn could
therefore reach a correct, cited verdict and be refused for want of evidence — `remote-003`.

**The widening is of the candidate set, never of the rule.** Each id is resolved against the
committed index, scored against the turn's own query on the same dense path §7.1's fill step uses,
run through G4, and only then handed to `LoopState.note_evidence` and the turn's citable set — the
same treatment a retrieved chunk gets. G1's rule and both thresholds are untouched: a resolved
chunk below the bar still refuses, and no chunk is ever admitted unscored.

The engine's top-level `citations[]` is deliberately **not** admitted. It is the union of the
requirement evidence and the approval evidence, and `tests/unit/test_agent_nudge.py` pins what it
has meant since P8: a merely cited id is not evidence.
"""

from __future__ import annotations

import asyncio
import threading
from unittest import mock

import pytest

from hrmosaic.agent.guardrails import g1, g4
from hrmosaic.core import corpusread
from hrmosaic.rag import retrieve
from tests.unit.test_agent_nudge import a_turn, orchestrator, result

#: A remote-work question, so the engine's own evidence is genuinely about what was asked.
QUESTION = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"


def chunk_ids(doc_id: str, *, quarantined: bool = False) -> list[str]:
    """Committed chunk ids of one document, split by what G4 makes of their text."""
    return [row.chunk_id for row in corpusread.list_chunks(doc_id) if (g4.scan(row.text) is not None) is quarantined]


def compliance(*ids: str, verdict: str = "conditional") -> dict:
    """A `check_policy_compliance` body in the shape §8.4 publishes: evidence per requirement."""
    return {
        "scenario": "international_remote",
        "verdict": verdict,
        "as_of": "2026-09-01",
        "requirements": [
            {
                "id": f"remote.intl.req{position}",
                "text": "a requirement of the scenario",
                "met": True,
                "reason": "the record satisfies it",
                "fact_key": "remote.intl",
                "evidence": {
                    "chunk_id": chunk_id,
                    "doc_id": (row.doc_id if (row := corpusread.get_chunk(chunk_id)) else "unknown"),
                    "heading_path": (row.heading_path if row else ""),
                    "snippet": (row.snippet if row else ""),
                },
            }
            for position, chunk_id in enumerate(ids, start=1)
        ],
    }


def a_turn_asking(question: str = QUESTION):
    """A turn that has retrieved nothing at all — the whole point of the tests below."""
    turn = a_turn(intent="workflow", workflow=None, searches=0)
    turn.request = turn.request.model_copy(update={"message": question})
    return turn


def absorb(turn, body: dict) -> None:
    orchestrator()._absorb(turn, result("check_policy_compliance", body))


def test_a_compliance_chunk_above_the_threshold_grounds_a_turn_that_never_retrieved():
    """`remote-003`'s shape: a correct verdict, cited from the corpus, and nothing retrieved."""
    turn = a_turn_asking()
    ids = chunk_ids("remote-and-hybrid-work")[:2] + chunk_ids("tax-and-location-addendum")[:2]
    absorb(turn, compliance(*ids))

    citable = turn.citable()
    assert [chunk.chunk_id for chunk in citable] == ids, "each resolved id entered the citable set"
    assert all(chunk.dense_score > 0.0 for chunk in citable), "and each was scored, not admitted on trust"
    assert turn.state.evidence_chunk_ids == ids
    assert set(turn.state.evidence_doc_ids) == {"remote-and-hybrid-work", "tax-and-location-addendum"}

    top = max(chunk.dense_score for chunk in citable)
    support = sorted((chunk.dense_score for chunk in citable), reverse=True)[1]
    verdict = g1.evaluate(citable, min_evidence_score=top - 0.01, min_support_score=support - 0.01)
    assert verdict.passed and verdict.candidates == len(ids)


def test_a_compliance_chunk_below_the_threshold_still_refuses():
    """The rule did not move: engine evidence is candidates, not a licence."""
    turn = a_turn_asking()
    ids = chunk_ids("remote-and-hybrid-work")[:2]
    absorb(turn, compliance(*ids))

    top = max(chunk.dense_score for chunk in turn.citable())
    verdict = g1.evaluate(turn.citable(), min_evidence_score=top + 0.01)
    assert not verdict.passed
    assert "below the evidence threshold" in verdict.reason


def test_a_quarantined_compliance_chunk_is_never_admitted():
    """G4 runs over the resolved TEXT, so the canary cannot enter by the engine's door either."""
    turn = a_turn_asking()
    lure = chunk_ids("security-acceptable-use", quarantined=True)
    assert lure, "the corpus canary must be reachable"
    absorb(turn, compliance(lure[0]))

    assert turn.evidence[lure[0]].quarantined is True, "it is shown, flagged, exactly as a retrieved hit is"
    assert turn.citable() == []
    assert turn.state.evidence_chunk_ids == [] and turn.state.evidence_doc_ids == []
    assert g1.evaluate(turn.citable()).passed is False


def test_an_unknown_compliance_chunk_id_is_ignored_rather_than_raised():
    turn = a_turn_asking()
    real = chunk_ids("remote-and-hybrid-work")[0]
    absorb(turn, compliance("c_notarealchunkid", real))

    assert list(turn.evidence) == [real]
    assert turn.state.evidence_chunk_ids == [real]


def test_the_score_is_the_one_retrieval_would_have_given_the_same_chunk():
    """ "The SAME dense path": `1 − cosine_distance` against the turn's own query vector.

    A second, kinder definition of the score would have made the gate mean two different things
    depending on which door the chunk came in through.

    The tolerance is the one §7.1's own fill step lives with: `vec0` computes the KNN distance in
    float32 inside sqlite-vec, while a score recomputed from the same stored vector is Python
    doubles, so the two agree to about 1e-6 and not to the bit.
    """
    from hrmosaic.rag.retrieve import retrieve

    turn = a_turn_asking()
    hits = retrieve(QUESTION, k=10, min_dense_score=0.0).hits[:3]
    absorb(turn, compliance(*[hit.chunk_id for hit in hits]))

    scored = {chunk.chunk_id: chunk.dense_score for chunk in turn.citable()}
    for hit in hits:
        if hit.chunk_id in scored:
            assert scored[hit.chunk_id] == pytest.approx(hit.dense_score, abs=1e-5)
    assert scored, "the fixture must actually resolve something"


def test_the_engines_own_citation_list_is_still_not_evidence():
    """The P8 narrowing stands: only the per-requirement evidence blocks are scored and admitted."""
    turn = a_turn_asking()
    real = chunk_ids("remote-and-hybrid-work")[0]
    absorb(
        turn,
        {
            "verdict": "compliant",
            "citations": [{"chunk_id": real, "doc_id": "remote-and-hybrid-work", "heading_path": "x"}],
        },
    )

    assert turn.evidence == {}
    assert turn.state.evidence_chunk_ids == []


# --------------------------------------------------------------------------------------
# …and it does not block the event loop (P13 carry-forward p2)
# --------------------------------------------------------------------------------------
#
# `score_chunk_ids` embeds the turn's question. On the 0.1-CPU instance that is ≈ 0.6 s of CPU, and
# it was being spent inside a synchronous `_absorb` called straight from the act loop — so for that
# 0.6 s the process served nothing: not the SSE rail, not `/health`, not another turn. Every other
# embed in the request path already runs under `asyncio.to_thread` (§2.1); this one did not.
#
# The unit call sites stay synchronous on purpose: `_absorb` is also called from the *rehydrate*
# path, which has no loop to block. The async boundary does the scoring in a thread and hands the
# result down, so there is still exactly one place that decides what engine evidence is worth.


def test_the_compliance_embed_does_not_run_on_the_event_loop():
    turn = a_turn_asking()
    ids = chunk_ids("remote-and-hybrid-work")[:2]
    scored_on: list[int] = []
    real = retrieve.score_chunk_ids

    def recording(chunk_ids_, *, query):
        scored_on.append(threading.get_ident())
        return real(chunk_ids_, query=query)

    async def drive():
        with mock.patch.object(retrieve, "score_chunk_ids", recording):
            await orchestrator()._absorb_async(turn, result("check_policy_compliance", compliance(*ids)))
        return threading.get_ident()

    loop_thread = asyncio.run(drive())

    citable = turn.citable()
    assert [chunk.chunk_id for chunk in citable] == ids, "the same evidence the synchronous path admits"
    assert all(chunk.dense_score > 0.0 for chunk in citable)
    assert scored_on, "the embed must still happen"
    assert all(thread != loop_thread for thread in scored_on), "and never on the thread running the loop"


def test_a_tool_that_is_not_the_compliance_engine_costs_the_async_path_no_embed():
    """`_absorb_async` is on every tool result; only a compliance body may reach the embedder."""
    calls: list[object] = []

    async def drive():
        with mock.patch.object(retrieve, "score_chunk_ids", lambda *a, **k: calls.append(a) or {}):
            await orchestrator()._absorb_async(a_turn_asking(), result("check_pto_balance", {"balance_days": 12}))

    asyncio.run(drive())
    assert calls == []
