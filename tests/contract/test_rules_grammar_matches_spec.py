"""Spec §8.4 and `mcpserver/rules.py` state one requirement grammar, and it is checked both ways.

The grammar (`check{subject, operator, compare_to}`, `applies_when`, `blocking`) and the verdict
ladder were adopted at P5 from the candidate P2 authored and set aside. They are a user-facing MCP
contract — P7's guardrails and P10's gold answers are written against them — so they live in the
spec, not only in `corpus/rules.yml`'s header. This test is what stops the two drifting: every token
the engine accepts must be published in §8.4, and §8.4 must not advertise a `computed.*` subject or a
verdict the engine does not know.
"""

import re
from pathlib import Path

from hrmosaic.mcpserver.rules import (
    BALANCE_SUBJECTS,
    COMPUTED_SUBJECTS,
    GUARD_PREFIXES,
    OPERATORS,
    SUBJECT_PREFIXES,
    VERDICTS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-09-08-hr-agentic-rag-design.md"

#: The verdict ladder, highest-precedence rung first.
LADDER = ("insufficient_evidence", "non_compliant", "conditional", "compliant")


def _section() -> str:
    """§8.4 tool 4's prose, from the grammar paragraph to the start of tool 5."""
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("**How a requirement is evaluated.**")
    end = text.index("**5. `lookup_employee_profile`**", start)
    return text[start:end]


def _words(section: str) -> set[str]:
    return set(re.findall(r"[a-z_]+", section))


def test_the_spec_publishes_every_subject_the_engine_accepts() -> None:
    section = _section()
    for prefix in SUBJECT_PREFIXES:
        assert f"`{prefix}<" in section, f"§8.4 does not publish the subject prefix {prefix!r}"
    for subject in COMPUTED_SUBJECTS + BALANCE_SUBJECTS:
        assert f"`{subject}`" in section, f"§8.4 does not publish the subject {subject!r}"


def test_the_spec_advertises_no_computed_subject_the_engine_would_reject() -> None:
    published = set(re.findall(r"computed\.[a-z_]+", _section()))
    assert published == set(COMPUTED_SUBJECTS)


def test_the_spec_publishes_every_operator_and_guard_the_engine_accepts() -> None:
    words = _words(_section())
    assert set(OPERATORS) <= words, f"§8.4 omits operators {sorted(set(OPERATORS) - words)}"
    guards = {prefix.rstrip(":") for prefix in GUARD_PREFIXES} | {"always"}
    assert guards <= words, f"§8.4 omits guards {sorted(guards - words)}"


def test_the_spec_states_the_verdict_ladder_in_precedence_order() -> None:
    assert set(LADDER) == set(VERDICTS)
    tail = _section().split("first rung that holds:")[1]
    positions = [tail.index(f"`{verdict}`") for verdict in LADDER]
    assert positions == sorted(positions), "§8.4's ladder is not in the engine's precedence order"


def test_the_spec_states_the_two_rules_that_stop_an_unmet_requirement_proving_a_violation() -> None:
    section = _section()
    assert "**never** blocking" in section, "§8.4 does not state that `manual` is never blocking"
    assert "**not** evaluable" in section, "§8.4 does not state that an absent subject is not evaluable"
    assert '"Not stated: …"' in section, "§8.4 does not state the absent-subject reason prefix"
