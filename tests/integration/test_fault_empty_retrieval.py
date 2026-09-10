"""§9.5 row 3 — retrieval too weak to ground an answer, at **HTTP 200** with a refuse-and-redirect.

G1 fires when the fused candidate set is below the evidence bar, and the refusal is built
**deterministically**: no model call, and — crucially — **no `tools/call`**. §13.4 scores tool
precision 1.0 when both the called and the expected tool sets are empty, so a refusal that issued a
`list_policy_documents` call to find out what the corpus covers would score 0.0 for exemplary
behaviour. The redirect names what the corpus *does* cover, read from the same index the tool would
have read.

The fault is injected by raising `MIN_EVIDENCE_SCORE` — G1's own bar, and the only threshold the
retriever does not also apply — rather than by inventing a nonsense question: this embedding model's
cosine floor over this corpus is around 0.52, so no phrasing produces a genuinely empty hit list,
and a test that pretended otherwise would be testing the fixture rather than the rule. Raising G1's
bar reproduces exactly the case §9.5 names — evidence retrieved, none of it good enough — and leaves
the **observed** scores on the guardrail span, which is what the row asks for.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.anyio

QUESTION = "Does Mosaic offer a sabbatical after seven years, and how long is it?"

#: Above every dense score this corpus produces, so no candidate clears the evidence bar.
IMPOSSIBLE_EVIDENCE = 0.95


@pytest.fixture
async def refused(web):
    async with web("fault_empty_retrieval.json", min_evidence_score=IMPOSSIBLE_EVIDENCE) as client:
        response = await client.post("/chat", json={"message": QUESTION})
        assert response.status_code == 200, response.text
        yield response.json()


async def test_the_turn_refuses_and_redirects_at_http_200(refused):
    assert refused["outcome"] == "refused"
    assert refused["citations"] == [], "a refusal cites nothing, because nothing grounded it"
    assert refused["answer"].strip()


async def test_the_redirect_names_what_the_corpus_does_cover(refused):
    from hrmosaic.agent.guardrails import g1

    covered = g1.coverage()
    assert covered
    assert any(title in refused["answer"] for title in covered)


async def test_the_guardrail_span_carries_the_observed_scores(refused, store):
    rows = store.execute(
        "SELECT name, payload_json FROM spans WHERE turn_id = ? AND kind = 'guardrail' ORDER BY seq",
        (refused["turn_id"],),
    ).dicts()
    g1_spans = [json.loads(row["payload_json"]) for row in rows if row["name"].startswith("G1")]

    assert g1_spans, "G1 fired"
    final = g1_spans[-1]
    assert final["verdict"] == "refuse"
    assert final["details"]["candidates"] > 0, "evidence was retrieved — it was simply too weak"
    assert 0.0 < final["details"]["max_dense_score"] < IMPOSSIBLE_EVIDENCE
    assert final["details"]["min_evidence_score"] == IMPOSSIBLE_EVIDENCE
    assert "below the evidence threshold" in final["reason"]


async def test_the_refusal_makes_no_extra_tool_call_of_its_own(refused, store):
    """The redirect reads the index directly; a `list_policy_documents` call would score 0.0."""
    called = [
        row["name"]
        for row in store.execute(
            "SELECT name FROM spans WHERE turn_id = ? AND kind = 'tool_call' ORDER BY seq", (refused["turn_id"],)
        ).dicts()
    ]
    assert called == ["search_policy_documents", "search_policy_documents"]
    assert "list_policy_documents" not in called


async def test_no_synthesis_call_was_made_over_evidence_that_did_not_qualify(refused, store):
    purposes = [
        json.loads(row["payload_json"])["purpose"]
        for row in store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'llm_call' ORDER BY seq",
            (refused["turn_id"],),
        ).dicts()
    ]
    assert "synthesize" not in purposes
    assert purposes[0] == "route"


async def test_the_turn_row_records_the_refusal(refused, store):
    row = store.execute("SELECT outcome, stop_reason FROM turns WHERE id = ?", (refused["turn_id"],)).one()
    assert (row["outcome"], row["stop_reason"]) == ("refused", "refused")
