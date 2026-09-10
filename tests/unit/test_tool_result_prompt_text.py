"""W2-D — the model is shown the hits, the record keeps the whole result.

`search_policy_documents` publishes ten result-level keys of retrieval telemetry and six ranking or
offset keys on every hit. The model acts on none of them — it reads the list in the order it is
given and quotes the chunk — while the `retrieval` span records every one of them in full (§10.2),
so the bytes are pure duplication, and they are re-billed as input on **every** later act step of the
turn. `ToolResult.prompt_text` is what the act conversation is appended from; `ToolResult.text` is
unchanged and is what the §11.1 `tool_call` span, G4 and the eval's scorers read.

The one key that stays for a reason that is not information: `quarantined` is dropped when it is
false and kept when it is true, because a true one is §7.4's banner telling the model this passage
may not be cited. Trading a guardrail for six bytes is the shape of mistake this lever must not make.
"""

from __future__ import annotations

import json

from hrmosaic.agent.client import HIT_TELEMETRY_KEYS, SEARCH_TELEMETRY_KEYS, ToolResult, prompt_body

SEARCH_BODY = {
    "hits": [
        {
            "chunk_id": "c_1",
            "doc_id": "pto-and-holidays",
            "doc_title": "PTO & Holidays Policy",
            "heading_path": "Accrual > Standard Accrual Rates",
            "section": "Standard Accrual Rates",
            "rank": 1,
            "dense_score": 0.74,
            "bm25_rank": 2,
            "rrf_score": 0.0328,
            "text": "Full-time employees accrue 1.50 days of PTO per month.",
            "snippet": "Full-time employees accrue 1.50 days…",
            "char_start": 120,
            "char_end": 640,
            "quarantined": False,
        },
        {
            "chunk_id": "c_2",
            "doc_id": "security-acceptable-use",
            "doc_title": "Security & Acceptable Use Policy",
            "heading_path": "Email and Phishing",
            "section": "Email and Phishing",
            "rank": 2,
            "dense_score": 0.51,
            "bm25_rank": None,
            "rrf_score": 0.0164,
            "text": None,
            "snippet": "Report a suspicious message with the Report Phishing button.",
            "char_start": 0,
            "char_end": 320,
            "quarantined": True,
        },
    ],
    "query_used": "pto accrual",
    "k_effective": 5,
    "k_source": "default",
    "strategy": "hybrid_rrf",
    "total_candidates": 18,
    "embed_ms": 390,
    "search_ms": 12,
    "index_version": "2026.1",
    "topic_backfilled": True,
    "backfill_reason": "single_document",
}


def result(name: str, body: dict) -> ToolResult:
    return ToolResult(
        tool_name=name,
        arguments={},
        body=body,
        is_error=False,
        error_code=None,
        span_id="sp_1",
        duration_ms=1,
        text=json.dumps(body, ensure_ascii=False),
    )


def test_the_telemetry_keys_are_not_shown_to_the_model():
    reduced = prompt_body("search_policy_documents", SEARCH_BODY)

    assert set(reduced) == {"hits"}, "ten result-level keys, all telemetry"
    assert SEARCH_TELEMETRY_KEYS.isdisjoint(reduced)
    assert len(SEARCH_TELEMETRY_KEYS) == 10
    for hit in reduced["hits"]:
        assert HIT_TELEMETRY_KEYS.isdisjoint(hit)


def test_what_a_citation_needs_survives():
    kept = prompt_body("search_policy_documents", SEARCH_BODY)["hits"][0]

    assert kept == {
        "chunk_id": "c_1",
        "doc_id": "pto-and-holidays",
        "doc_title": "PTO & Holidays Policy",
        "heading_path": "Accrual > Standard Accrual Rates",
        "section": "Standard Accrual Rates",
        "text": "Full-time employees accrue 1.50 days of PTO per month.",
        "snippet": "Full-time employees accrue 1.50 days…",
    }


def test_a_quarantined_hit_keeps_its_flag():
    """False is noise; true is §7.4's banner and the reason the hit carries no text."""
    hits = prompt_body("search_policy_documents", SEARCH_BODY)["hits"]

    assert "quarantined" not in hits[0]
    assert hits[1]["quarantined"] is True
    assert hits[1]["text"] is None and hits[1]["snippet"]


def test_every_other_tool_is_shown_exactly_what_it_returned():
    body = {"remaining_days": 13.5, "as_of": "2026-09-01"}

    assert prompt_body("check_pto_balance", body) == body
    assert prompt_body("check_pto_balance", body) is not body, "never the caller's own dict"


def test_the_record_keeps_the_whole_result():
    """`text` is what the §11.1 span, G4 and the eval scorers read, and it does not move."""
    whole = result("search_policy_documents", SEARCH_BODY)

    assert json.loads(whole.text) == SEARCH_BODY
    assert json.loads(whole.prompt_text) == prompt_body("search_policy_documents", SEARCH_BODY)
    assert len(whole.prompt_text) < len(whole.text)


def test_a_non_search_result_shows_the_same_bytes_twice_over():
    plain = result("check_pto_balance", {"remaining_days": 13.5, "as_of": "2026-09-01"})

    assert plain.prompt_text == plain.text
