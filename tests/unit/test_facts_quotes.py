"""`corpus/facts.yml` is an index into the corpus, and this is the test that keeps it honest (spec §5.2).

For every entry it asserts that `quote` appears **verbatim** — after whitespace normalisation — inside
the rendered text of `doc_id`, and that `section` matches a real `" > "`-joined heading path there. That
single pair of assertions is what makes the corpus, `corpus/rules.yml` and the evaluation gold answers
agree: all three cite fact ids rather than prose, so a corpus edit that moves a number fails here before
it can contradict a gold answer.

The quote is checked against the **rendered** text of each format, which for `workplace-conduct` means
the text `pypdf` extracts from the committed PDF, not its Markdown source — a sentence that did not
survive rendering fails.
"""

from __future__ import annotations

import pytest

from scripts.check_facts import check_corpus, load_documents, load_facts, load_rules, normalise

DOCUMENTS = load_documents()
FACTS = load_facts()
RULES = load_rules()

REQUIREMENTS = [
    (scenario, requirement) for scenario, spec in sorted(RULES.items()) for requirement in spec["requirements"]
]
REQUIREMENT_IDS = [f"{scenario}.{requirement['id']}" for scenario, requirement in REQUIREMENTS]


def test_facts_index_is_populated():
    assert len(FACTS) >= 40
    assert {fact["doc_id"] for fact in FACTS.values()} <= set(DOCUMENTS)


@pytest.mark.parametrize("key", sorted(FACTS))
def test_quote_is_verbatim(key):
    fact = FACTS[key]
    document = DOCUMENTS[fact["doc_id"]]
    assert normalise(fact["quote"]) in normalise(document.text)


@pytest.mark.parametrize("key", sorted(FACTS))
def test_section_is_a_real_heading_path(key):
    fact = FACTS[key]
    document = DOCUMENTS[fact["doc_id"]]
    assert fact["section"] in document.heading_paths


@pytest.mark.parametrize("key", sorted(FACTS))
def test_every_fact_carries_a_value_and_a_unit(key):
    fact = FACTS[key]
    assert fact["value"] is not None
    assert isinstance(fact["unit"], str) and fact["unit"]


def test_the_quote_check_is_not_vacuous():
    # A number that is deliberately not in the corpus must not match, or the assertion above proves
    # nothing about the corpus at all.
    document = DOCUMENTS["pto-and-holidays"]
    assert normalise("Full-time employees accrue 9.99 days of PTO per month.") not in normalise(document.text)


@pytest.mark.parametrize(("scenario", "requirement"), REQUIREMENTS, ids=REQUIREMENT_IDS)
def test_every_rule_requirement_resolves(scenario, requirement):
    assert requirement["fact_key"] in FACTS, scenario
    document = DOCUMENTS[requirement["doc_id"]]
    assert requirement["heading_path"] in document.heading_paths


def test_check_facts_script_is_green():
    assert check_corpus() == []
