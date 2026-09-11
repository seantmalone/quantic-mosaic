"""`load_script` — a typo in a fixture fails at load, not three turns into a demo (spec §16.2).

`StubAdapter` is the keystone of the key-free push path: every contract, integration and e2e test in
this repository, both `make demo` targets and the `docker` job's container all replay a committed
JSON script through it. So a malformed script is not a test-fixture problem — it is a red suite, a
dead demo or a 500 on camera, and the message has to name the file and the entry. That validation is
what this file drives; `test_llm_span_emission.py` owns the *replay* half (out of step, exhausted).

`reset()` is here too: it is what lets one adapter drive a confirmation-gated turn and its resumed
second half from a single script.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from hrmosaic.core.llm.base import Message
from hrmosaic.core.llm.stub import StubAdapter, StubScriptError, load_script

MESSAGES = [Message(role="user", content="hello")]


def write_script(tmp_path, body) -> object:
    path = tmp_path / "script.json"
    path.write_text(json.dumps(body) if not isinstance(body, str) else body, encoding="utf-8")
    return path


def test_a_script_path_that_does_not_exist_names_the_setting_that_points_at_it(tmp_path):
    with pytest.raises(StubScriptError, match="LLM_STUB_SCRIPT"):
        load_script(tmp_path / "absent.json")


def test_a_script_that_is_not_valid_json_says_so_rather_than_raising_a_decode_error(tmp_path):
    path = write_script(tmp_path, "{not json at all")
    with pytest.raises(StubScriptError, match="not valid JSON"):
        load_script(path)


@pytest.mark.parametrize("body", [[], {"completions": []}, {"completions": "route"}, {}], ids=str)
def test_a_script_with_no_completions_is_refused(tmp_path, body):
    """Both shapes are accepted — a bare list and `{"completions": [...]}` — but never an empty one."""
    path = write_script(tmp_path, body)
    with pytest.raises(StubScriptError, match="non-empty list of completions"):
        load_script(path)


def test_an_entry_that_is_not_an_object_is_refused_by_its_position(tmp_path):
    path = write_script(tmp_path, [{"purpose": "route", "response_text": "ok"}, "act"])
    with pytest.raises(StubScriptError, match="entry 2 is not an object"):
        load_script(path)


def test_an_entry_key_outside_the_vocabulary_is_refused_and_listed(tmp_path):
    """`respones_text` would otherwise replay as an empty answer and blame the agent."""
    path = write_script(tmp_path, [{"purpose": "route", "respones_text": "ok"}])
    with pytest.raises(StubScriptError, match=r"unknown keys \['respones_text'\]"):
        load_script(path)


def test_a_scripted_tool_call_with_no_name_is_refused(tmp_path):
    """A nameless call reaches `tools/call` as `KeyError: 'name'` mid-turn instead."""
    path = write_script(tmp_path, [{"purpose": "act", "tool_calls": [{"args": {"employee_id": "E1042"}}]}])
    with pytest.raises(StubScriptError, match="tool call with no name"):
        load_script(path)


def test_a_well_formed_script_survives_both_accepted_shapes(tmp_path):
    entries = [{"purpose": "route", "response_text": "policy_qa"}]
    assert load_script(write_script(tmp_path, entries)) == entries
    assert load_script(write_script(tmp_path, {"completions": entries})) == entries


def test_reset_rewinds_one_adapter_so_it_can_drive_a_second_turn(tmp_path):
    """A confirmation-gated turn resumes as a *second* turn against the same committed script."""
    path = write_script(tmp_path, [{"purpose": "route", "response_text": "policy_qa"}])
    adapter = StubAdapter(script_path=path)

    first = asyncio.run(adapter.complete(MESSAGES, purpose="route"))
    assert first.text == "policy_qa"
    assert adapter.remaining == 0

    adapter.reset()
    assert adapter.remaining == 1
    assert asyncio.run(adapter.complete(MESSAGES, purpose="route")).text == "policy_qa"
