"""§10.5 size control — the caps are enforced, and `truncated` is recorded honestly.

The table is 8 KB per string, 32 KB per span payload and 128 KB for an `llm_call`; a truncated
payload sets `truncated = 1` while `payload_bytes` keeps the **pre-truncation** size, "so the
dashboard badges it honestly". §17 lists the same caps as a denial-of-service control, which is
why the shed loop must terminate *against the cap* rather than break out from under it — a payload
whose bulk sits in a nested list or in many small sibling strings is exactly the shape that used
to escape.

Prose, not filler: `redact()` runs first, and a long run of `[A-Za-z0-9+/]` is a base64 credential
shape it replaces wholesale, so `"x" * 60_000` would arrive at the size control as `[REDACTED]`.
"""

from __future__ import annotations

import json

from hrmosaic.core.trace import (
    MAX_LLM_PAYLOAD_BYTES,
    MAX_PAYLOAD_BYTES,
    MAX_STRING_BYTES,
    TRUNCATION_MARKER,
    SessionSpec,
    prepare_payload,
)

SENTENCE = "Employees accrue paid time off monthly, and unused days roll over once. "


def prose(byte_length: int) -> str:
    """A string of roughly `byte_length` bytes that no redaction pattern matches."""
    return (SENTENCE * (byte_length // len(SENTENCE) + 2))[:byte_length]


def stored_span(store, turn_id: str) -> dict:
    return store.execute(
        "SELECT kind, payload_json, payload_bytes, truncated FROM spans WHERE turn_id = ?", (turn_id,)
    ).one()


# --- the 8 KB per-string cap ------------------------------------------------------------


def test_a_single_string_field_is_capped_at_8_kb():
    payload = {"query": prose(40_000), "k": 5, "k_source": "default", "strategy": "hybrid_rrf"}
    serialised, payload_bytes, truncated = prepare_payload("retrieval", payload)

    capped = json.loads(serialised)["query"]
    assert capped.endswith(TRUNCATION_MARKER)
    assert capped.count(TRUNCATION_MARKER) == 1
    body = capped[: -len(TRUNCATION_MARKER)]
    assert len(body.encode("utf-8")) <= MAX_STRING_BYTES
    assert truncated is True
    assert payload_bytes > 40_000


def test_a_string_under_the_cap_is_untouched_and_not_flagged():
    payload = {"query": prose(1_000), "k": 5, "k_source": "default", "strategy": "hybrid_rrf"}
    serialised, payload_bytes, truncated = prepare_payload("retrieval", payload)

    assert truncated is False
    assert TRUNCATION_MARKER not in serialised
    assert payload_bytes == len(serialised.encode("utf-8"))


# --- the 32 KB payload cap --------------------------------------------------------------


def test_a_nested_list_payload_is_shed_down_to_the_32_kb_cap():
    """The escape: the bulk lives in `structured_content.items`, not in a top-level list."""
    payload = {
        "server": "hrmosaic",
        "transport": "http",
        "tool_name": "list_tickets",
        "structured_content": {"items": [{"id": index, "note": prose(60)} for index in range(900)]},
    }
    serialised, payload_bytes, truncated = prepare_payload("tool_call", payload)

    assert payload_bytes > MAX_PAYLOAD_BYTES
    assert len(serialised.encode("utf-8")) <= MAX_PAYLOAD_BYTES
    assert truncated is True
    assert json.loads(serialised)["structured_content"]["items"], "shedding must not empty the list"


def test_a_payload_of_many_small_sibling_strings_is_capped_and_flagged():
    """The other escape: no list at all, and every string already under the 8 KB cap."""
    payload = {
        "server": "hrmosaic",
        "transport": "http",
        "tool_name": "get_handbook",
        "arguments": {f"section_{index}": prose(1_000) for index in range(60)},
    }
    serialised, payload_bytes, truncated = prepare_payload("tool_call", payload)

    assert payload_bytes > MAX_PAYLOAD_BYTES
    assert len(serialised.encode("utf-8")) <= MAX_PAYLOAD_BYTES
    assert truncated is True


def test_a_payload_that_cannot_fit_becomes_the_oversize_stub():
    payload = {"server": "hrmosaic", "transport": "http", "tool_name": "dump"}
    payload.update({f"field_{index}": prose(120) for index in range(2_000)})
    serialised, payload_bytes, truncated = prepare_payload("tool_call", payload)

    assert json.loads(serialised) == {
        "kind": "tool_call",
        "error_kind": "payload_oversize",
        "payload_bytes": payload_bytes,
    }
    assert len(serialised.encode("utf-8")) <= MAX_PAYLOAD_BYTES
    assert truncated is True


# --- the 128 KB `llm_call` cap ----------------------------------------------------------


def test_an_llm_call_keeps_what_a_default_payload_would_shed():
    payload = {
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "purpose": "synthesize",
        "tool_calls": [{"name": "search_policies", "args": {"note": prose(60)}} for _ in range(900)],
    }
    default_json, _, _ = prepare_payload("tool_call", dict(payload))
    llm_json, payload_bytes, truncated = prepare_payload("llm_call", dict(payload))

    assert MAX_PAYLOAD_BYTES < payload_bytes < MAX_LLM_PAYLOAD_BYTES
    assert len(llm_json.encode("utf-8")) == payload_bytes
    assert truncated is False
    assert len(default_json.encode("utf-8")) <= MAX_PAYLOAD_BYTES


def test_an_llm_call_over_128_kb_is_shed_to_its_own_cap():
    payload = {
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "purpose": "synthesize",
        "tool_calls": [{"name": "search_policies", "args": {"note": prose(60)}} for _ in range(4_000)],
    }
    serialised, payload_bytes, truncated = prepare_payload("llm_call", payload)

    assert payload_bytes > MAX_LLM_PAYLOAD_BYTES
    assert len(serialised.encode("utf-8")) <= MAX_LLM_PAYLOAD_BYTES
    assert truncated is True


# --- what actually reaches the `spans` row ----------------------------------------------


def test_the_stored_row_is_under_the_cap_and_badged_truncated(writer, store):
    turn = writer.start_turn(SessionSpec(employee_id="E1042"), user_message="list every open ticket")
    with turn.span("tool_call", "list_tickets") as span:
        span.set_payload(
            {
                "kind": "tool_call",
                "server": "hrmosaic",
                "transport": "http",
                "tool_name": "list_tickets",
                "structured_content": {"items": [{"id": index, "note": prose(60)} for index in range(900)]},
            }
        )
    turn.close(outcome="answered", stop_reason="complete", final_answer="Here they are.")

    row = stored_span(store, turn.turn_id)
    assert len(row["payload_json"].encode("utf-8")) <= MAX_PAYLOAD_BYTES
    assert row["truncated"] == 1
    assert row["payload_bytes"] > MAX_PAYLOAD_BYTES
    assert row["payload_bytes"] > len(row["payload_json"].encode("utf-8"))


def test_a_small_payload_is_stored_whole_and_not_badged(writer, store):
    turn = writer.start_turn(SessionSpec(employee_id="E1042"), user_message="how much PTO?")
    with turn.span("tool_call", "get_pto_balance") as span:
        span.set_payload(
            {
                "kind": "tool_call",
                "server": "hrmosaic",
                "transport": "http",
                "tool_name": "get_pto_balance",
                "structured_content": {"days": 13.5},
            }
        )
    turn.close(outcome="answered", stop_reason="complete", final_answer="13.5 days.")

    row = stored_span(store, turn.turn_id)
    assert row["truncated"] == 0
    assert row["payload_bytes"] == len(row["payload_json"].encode("utf-8"))
