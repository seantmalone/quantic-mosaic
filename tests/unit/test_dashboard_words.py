"""The dashboard's words for three things the re-audit #4 found spelled as code (UX W9).

- **DR4-07 / DR4-08**: a compliance verdict and a tool's stop reason are words, and one fact has
  one spelling in adjacent cells.
- **DR4-09**: PERSONA is the person's name; the id stays in the record.
- **DR4-14 = npo5-08**: the handshake history is in DISCOVERED order.
"""

from __future__ import annotations

from hrmosaic.web import dashboard


def test_a_verdict_and_a_stop_reason_are_words_not_de_underscored_tokens():
    assert dashboard._f_enum_label("non_compliant") == "non-compliant"
    assert dashboard._f_enum_label("insufficient_evidence") == "insufficient evidence"
    assert dashboard._f_enum_label("CONFIRMATION_REQUIRED") == "paused for confirmation"
    assert dashboard._f_enum_label("VERDICT_NON_COMPLIANT") == "refused: verdict non-compliant"


def test_the_persona_is_named_from_the_roster_and_an_unknown_id_stays_an_id():
    names = dashboard._persona_names()
    assert names, "the roster the tools read is the roster the dashboard names from"
    employee_id, name = next(iter(names.items()))
    assert dashboard._f_persona_name(employee_id) == name != employee_id
    assert dashboard._f_persona_name("E9999999") == "E9999999"
    assert dashboard._f_persona_name(None) == ""


def test_the_handshake_history_is_in_discovered_order_newest_first():
    spans = [
        {"id": "a", "started_at": 300, "payload": {"discovered_at": 100}},
        {"id": "b", "started_at": 200, "payload": {"discovered_at": 250}},
        {"id": "c", "started_at": 100, "payload": {}},
    ]
    assert [span["id"] for span in dashboard._by_discovery(spans)] == ["b", "a", "c"]
