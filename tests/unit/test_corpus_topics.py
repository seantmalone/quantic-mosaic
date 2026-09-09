"""Every PD.2 topic is covered by at least one document (spec §5.3).

The `Topics:` line in each document header is the single source of truth for a document's topics — the
parsers read it into `documents.topics` and `chunks.topics`, and `corpus/README.md`'s topic map is a
human-readable restatement of those lines, never a second source of truth (spec §5.1). This test
therefore asserts against the header lines, and asks of the README only that it mentions every document
so the map cannot silently go stale.

Header topics are additionally constrained to `search_policy_documents`'s `topic` enum (spec §8.4 tool 1),
because a topic outside it would be unreachable through the tool.
"""

from __future__ import annotations

import pytest

from scripts.check_facts import CORPUS_DIR, load_documents

DOCUMENTS = load_documents()

#: The ten topics requirement PD.2 asks the corpus to cover (spec §5.3).
PD2_TOPICS = (
    "pto",
    "holidays",
    "remote_work",
    "expenses",
    "data_security",
    "benefits",
    "onboarding",
    "equipment",
    "leave",
    "conduct",
)

#: `search_policy_documents.topic` — the enum a caller may filter on (spec §8.4 tool 1).
TOOL_TOPIC_ENUM = frozenset(
    {
        "pto",
        "holidays",
        "remote_work",
        "tax_location",
        "expenses",
        "travel",
        "data_security",
        "benefits",
        "onboarding",
        "equipment",
        "leave",
        "conduct",
        "performance",
        "compensation",
        "approvals",
        "escalation",
    }
)


def _documents_for(topic: str) -> list[str]:
    return sorted(doc_id for doc_id, document in DOCUMENTS.items() if topic in document.topics)


@pytest.mark.parametrize("topic", PD2_TOPICS)
def test_every_pd2_topic_maps_to_a_document(topic):
    assert _documents_for(topic), f"no document declares Topics: {topic}"


@pytest.mark.parametrize("doc_id", sorted(DOCUMENTS))
def test_header_topics_are_inside_the_tool_enum(doc_id):
    document = DOCUMENTS[doc_id]
    assert set(document.topics) <= TOOL_TOPIC_ENUM


def test_no_topic_in_the_enum_is_orphaned():
    # Every value the tool advertises must return something, or a caller filtering on it gets an
    # empty result from a perfectly valid request.
    orphans = sorted(topic for topic in TOOL_TOPIC_ENUM if not _documents_for(topic))
    assert orphans == []


def test_readme_topic_map_mentions_every_document():
    readme = (CORPUS_DIR / "README.md").read_text(encoding="utf-8")
    missing = sorted(doc_id for doc_id in DOCUMENTS if doc_id not in readme)
    assert missing == []
