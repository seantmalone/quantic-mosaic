"""`evaluation/dataset.yaml` against every clause of spec §13.1.

The list is the spec's, in the spec's order:

* `n == 26`, inside the 20–30 band;
* all seven labels with their exact counts;
* all five `expected_behavior` classes carry ≥ 1 item;
* **no relative date expression** in any question — the property that makes the dataset durable
  without a frozen clock (§13.6, §22);
* `inj-001` exists as `simple_policy` with `security-acceptable-use` in `expected_docs`;
* every item has a non-empty gold;
* every `gold_facts` entry resolves to a key in `corpus/facts.yml`;
* every `tool_task` item's `expected_end_state` carries a non-empty `requires_tool_results`;
* ≥ 3 `multi_doc` items carry ≥ 3 distinct `expected_docs` (the R3.5 floor);
* every `out_of_scope` item has `expected_tools: []`;
* `pto-001`, `remote-001` and `benefits-001` exist as `simple_policy` — the §13.5 cold probes.

Plus the two named items of §13.1: the `sensitive` item routes `escalate` and burns no tools, and
the two demo-workflow mirrors `remote-004` and `pto-003` carry a `workflow`.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from evaluation.schema import CATEGORY_COUNTS, COLD_PROBE_IDS, DATASET_PATH, load_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = REPO_ROOT / "corpus" / "facts.yml"

DATASET = load_dataset()
FACT_KEYS = set((yaml.safe_load(FACTS_PATH.read_text(encoding="utf-8")) or {}).get("facts") or {})

#: §13.1's own regular expression, verbatim in intent: a question may not depend on the day it runs.
RELATIVE_DATE = re.compile(
    r"\b(next|last|this)\s+(week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\btoday\b|\btomorrow\b|\byesterday\b",
    re.IGNORECASE,
)

#: The nine published tool names — nothing else may appear in an expectation list.
TOOL_NAMES = {path.name.removesuffix(".schema.json") for path in (REPO_ROOT / "mcp" / "tools").glob("*.schema.json")}


def test_the_set_holds_twenty_six_items_inside_the_band():
    assert len(DATASET.items) == 26
    assert 20 <= len(DATASET.items) <= 30


def test_every_category_carries_its_count():
    assert Counter(item.category for item in DATASET.items) == Counter(CATEGORY_COUNTS)


def test_all_five_expected_behavior_classes_are_represented():
    seen = Counter(item.expected_behavior for item in DATASET.items)
    for behaviour in ("answer", "clarify", "confirm", "refuse", "escalate"):
        assert seen[behaviour] >= 1, f"no item carries expected_behavior={behaviour}"


def test_item_ids_are_unique():
    ids = [item.id for item in DATASET.items]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("item", DATASET.items, ids=lambda item: item.id)
def test_no_question_uses_a_relative_date(item):
    assert RELATIVE_DATE.search(item.question) is None


@pytest.mark.parametrize("item", DATASET.items, ids=lambda item: item.id)
def test_every_item_has_a_non_empty_gold(item):
    assert item.gold_answer_short.strip()


@pytest.mark.parametrize("item", DATASET.items, ids=lambda item: item.id)
def test_every_gold_fact_resolves_to_a_facts_yml_key(item):
    unknown = [key for key in item.gold_facts if key not in FACT_KEYS]
    assert unknown == [], f"{item.id} cites unknown fact key(s) {unknown}"


@pytest.mark.parametrize("item", DATASET.items, ids=lambda item: item.id)
def test_every_named_tool_is_a_published_tool(item):
    named = set(item.expected_tools) | set(item.allowed_extra_tools) | set(item.forbidden_tools)
    assert named <= TOOL_NAMES, f"{item.id} names tool(s) that do not exist: {sorted(named - TOOL_NAMES)}"


def test_inj_001_is_a_simple_policy_item_over_the_security_document():
    item = DATASET.by_id("inj-001")
    assert item is not None
    # §13.1: placed in `simple_policy`, not `out_of_scope`, because the out-of-scope route ends at
    # G1's refusal *before* the act loop and retrieves nothing, so a probe there asserts nothing.
    assert item.category == "simple_policy"
    assert "security-acceptable-use" in item.expected_docs
    assert item.asserts_injection_quarantined is True


def test_every_tool_task_requires_a_structured_tool_result():
    for item in DATASET.items:
        if item.category != "tool_task":
            continue
        assert item.expected_end_state is not None, item.id
        assert item.expected_end_state.requires_tool_results, item.id


def test_at_least_three_multi_doc_items_span_three_documents():
    spanning = [item for item in DATASET.items if item.category == "multi_doc" and len(set(item.expected_docs)) >= 3]
    assert len(spanning) >= 3


def test_every_out_of_scope_item_expects_no_tools():
    for item in DATASET.items:
        if item.category == "out_of_scope":
            assert item.expected_tools == [], item.id
            assert item.expected_docs == [], item.id
            assert item.expected_behavior == "refuse", item.id


def test_the_three_cold_probes_exist_as_simple_policy():
    for item_id in COLD_PROBE_IDS:
        item = DATASET.by_id(item_id)
        assert item is not None, item_id
        assert item.category == "simple_policy", item_id


def test_the_sensitive_item_escalates_and_burns_no_tools():
    item = next(item for item in DATASET.items if item.category == "sensitive")
    assert item.expected_behavior == "escalate"
    assert item.expected_tools == []
    assert item.expected_docs == []


def test_the_unsafe_action_item_asserts_nothing_is_written_without_a_confirmation():
    item = next(item for item in DATASET.items if item.category == "unsafe_action")
    assert item.expected_behavior == "confirm"
    assert item.requires_confirmation is True
    # The runner must NOT auto-confirm it: that is what makes the item assert the absence of a write.
    assert item.confirm_on_prompt is False
    # `A` holds only `ok` tool_call spans, so a *successful* write here is a hard fail while the
    # gated attempt is counted separately as `gated_attempts` (§13.4).
    assert "create_mock_hr_ticket" in item.forbidden_tools


def test_both_demo_workflows_are_mirrored_in_the_dataset():
    """§13.1: `workflow_completion_by_workflow` has real items and R4.2 has a named artifact."""
    by_workflow = {item.workflow: item.id for item in DATASET.items if item.workflow}
    assert by_workflow == {"remote_work_eligibility": "remote-004", "pto_request": "pto-003"}


def test_the_file_order_is_the_run_order():
    """§13.6: the runner iterates the file — no sort, no shuffle. The loader must preserve it."""
    raw = yaml.safe_load(DATASET_PATH.read_text(encoding="utf-8"))
    assert [entry["id"] for entry in raw["items"]] == [item.id for item in DATASET.items]


def test_every_answering_item_names_the_documents_it_expects():
    """An `answer` item with no `expected_docs` would silently leave the DocRecall denominator."""
    for item in DATASET.items:
        if item.expected_behavior == "answer":
            assert item.expected_docs, item.id
