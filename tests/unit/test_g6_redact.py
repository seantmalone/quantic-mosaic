"""G6 — `redact()` over every payload before persistence (spec §7.4 G6, §10.4).

Both directions are asserted, as §10.4 requires: leaked values are scrubbed **and** the
integer token counts on an `llm_call` payload — which the denylist's `token` pattern would
otherwise eat — survive intact.
"""

from __future__ import annotations

import json

from hrmosaic.core.models import AnswerBlock
from hrmosaic.core.redact import REDACTED, redact, redact_text
from hrmosaic.core.trace import SessionSpec

# Synthetic, invalid-by-construction credentials. Nothing here is a real key.
FAKE_ANTHROPIC = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8" * 2
FAKE_OPENAI = "sk-" + "Zz9Yy8Xx7Ww6Vv5U" * 2
FAKE_GOOGLE = "AIza" + "SyD1e2F3g4H5i6J7k8L9m0N1o2P3q4R5s"
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJFMTA0MiIsIm5hbWUiOiJ0ZXN0In0.QK7t9r0Zx3aVb2Nc4Md6Pe8Qf1Rg3Sh5Ti7Uj9Vk"
FAKE_BASE64 = "TW9zYWljSFJDb3B5cmlnaHRTeW50aGV0aWNQYXlsb2FkQmxvYlZhbHVl" * 3


def test_key_name_denylist_scrubs_every_shape():
    payload = {
        "api_key": "whatever-was-here",
        "API-KEY": "whatever-was-here",
        "authorization": "Bearer abc.def",
        "Cookie": "mosaic_access=abc",
        "password": "hunter2",
        "client_secret": "shhh",
        "access_token": "abc123",
        "bearer": "abc123",
    }
    scrubbed = redact(payload)
    assert set(scrubbed) == set(payload)
    assert all(value == REDACTED for value in scrubbed.values()), scrubbed


def test_value_regexes_scrub_keys_embedded_in_free_text():
    text = (
        f"traceback: header was {FAKE_ANTHROPIC} and fallback {FAKE_OPENAI}; "
        f"gemini {FAKE_GOOGLE}; jwt {FAKE_JWT}; blob {FAKE_BASE64}"
    )
    scrubbed = redact_text(text)
    for leaked in (FAKE_ANTHROPIC, FAKE_OPENAI, FAKE_GOOGLE, FAKE_JWT, FAKE_BASE64):
        assert leaked not in scrubbed
    assert "sk-ant-" not in scrubbed and "AIza" not in scrubbed
    assert scrubbed.startswith("traceback: header was ")
    assert REDACTED in scrubbed


def test_environment_sweep_replaces_exact_values(monkeypatch):
    """Every `os.environ` value whose key ends `_KEY`/`_TOKEN`/`_SECRET`, as a literal substring."""
    monkeypatch.setenv("MOSAIC_TEST_API_KEY", "kangaroo-lantern-42")
    monkeypatch.setenv("MOSAIC_TEST_AUTH_TOKEN", "pelican-marmalade-77")
    monkeypatch.setenv("MOSAIC_TEST_SIGNING_SECRET", "walrus-trombone-91")
    monkeypatch.setenv("MOSAIC_TEST_PUBLIC_URL", "https://example.invalid")

    payload = {
        "message": "connect failed for kangaroo-lantern-42 using pelican-marmalade-77",
        "detail": ["signed with walrus-trombone-91", "posted to https://example.invalid"],
    }
    scrubbed = redact(payload)
    assert "kangaroo-lantern-42" not in scrubbed["message"]
    assert "pelican-marmalade-77" not in scrubbed["message"]
    assert "walrus-trombone-91" not in scrubbed["detail"][0]
    # a non-credential variable is not swept, so ordinary values are not mangled
    assert scrubbed["detail"][1] == "posted to https://example.invalid"


def test_short_environment_values_are_not_swept(monkeypatch):
    """A two-character value would otherwise turn every payload into confetti."""
    monkeypatch.setenv("MOSAIC_TEST_TINY_TOKEN", "ok")
    assert redact({"message": "the tool call is ok"}) == {"message": "the tool call is ok"}


def test_token_counts_survive_on_an_llm_call_payload():
    payload = {
        "kind": "llm_call",
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "purpose": "synthesize",
        "prompt_tokens": 7412,
        "completion_tokens": 883,
        "total_tokens": 8295,
        "cache_creation_input_tokens": 4096,
        "cache_read_input_tokens": 0,
        "api_key": "leaked-somehow",
        "response_text": f"the operator pasted {FAKE_ANTHROPIC} into chat",
    }
    scrubbed = redact(payload)
    assert scrubbed["prompt_tokens"] == 7412
    assert scrubbed["completion_tokens"] == 883
    assert scrubbed["total_tokens"] == 8295
    assert scrubbed["cache_creation_input_tokens"] == 4096
    assert scrubbed["cache_read_input_tokens"] == 0
    assert scrubbed["api_key"] == REDACTED
    assert FAKE_ANTHROPIC not in scrubbed["response_text"]


def test_nested_structures_and_non_strings_are_handled():
    payload = {
        "tool_calls": [{"name": "create_hr_case", "args": {"authorization": "Bearer x", "priority": 3}}],
        "cache_hit": False,
        "cost_usd_estimate": 0.0012,
        "chunks": [{"chunk_id": "c_1b7e", "quarantined": False, "score": 0.74}],
        "resolved_at": None,
    }
    scrubbed = redact(payload)
    assert scrubbed["tool_calls"][0]["args"]["authorization"] == REDACTED
    assert scrubbed["tool_calls"][0]["args"]["priority"] == 3
    assert scrubbed["cache_hit"] is False
    assert scrubbed["cost_usd_estimate"] == 0.0012
    assert scrubbed["chunks"][0] == {"chunk_id": "c_1b7e", "quarantined": False, "score": 0.74}
    assert scrubbed["resolved_at"] is None


def test_redaction_is_idempotent_and_does_not_mutate_its_input():
    payload = {"api_key": "abc", "note": f"key {FAKE_GOOGLE}"}
    once = redact(payload)
    assert payload == {"api_key": "abc", "note": f"key {FAKE_GOOGLE}"}
    assert redact(once) == once


def test_ordinary_policy_prose_is_left_alone():
    prose = (
        "Employees requesting international remote work must obtain written approval from "
        "People Operations at mobility@mosaicrobotics.example at least 21 days before departure."
    )
    assert redact_text(prose) == prose


def test_every_answer_column_of_the_closing_update_is_scrubbed(writer, store):
    """`answer_blocks_json` and `citations_json` hold the same model prose as `final_answer`.

    §7.3 makes `blocks[].text` the text the UI renders, so a credential that leaks into an answer
    must not survive in the column the dashboard reads back (§10.4, §17 Secrets).
    """
    turn = writer.start_turn(SessionSpec(employee_id="E1042"), user_message="what is the api key?")
    turn.close(
        outcome="answered",
        stop_reason="complete",
        final_answer=f"The configured key is {FAKE_ANTHROPIC}.",
        answer_blocks=[
            AnswerBlock(
                type="policy_fact",
                text=f"The configured key is {FAKE_ANTHROPIC}.",
                citations=["c_1b7e"],
            )
        ],
        citations=[{"chunk_id": "c_1b7e", "snippet": f"secret: {FAKE_GOOGLE}", "authorization": "Bearer abc"}],
    )

    row = store.execute(
        "SELECT final_answer, answer_blocks_json, citations_json FROM turns WHERE id = ?", (turn.turn_id,)
    ).one()
    assert FAKE_ANTHROPIC not in row["final_answer"]
    assert FAKE_ANTHROPIC not in row["answer_blocks_json"]
    assert FAKE_GOOGLE not in row["citations_json"]

    blocks = json.loads(row["answer_blocks_json"])
    assert blocks[0]["text"] == "The configured key is [REDACTED]."
    assert blocks[0]["citations"] == ["c_1b7e"], "the citation ids must survive the scrub"
    assert json.loads(row["citations_json"])[0]["authorization"] == REDACTED
