"""The `SEED`-selected reference subset is stable under `PYTHONHASHSEED` (spec §13.6, §13.7).

> Eval sampling | `SEED = 1729` in `core/ids.py`, used **only** where sampling exists: selecting the
> 8 reference-labelled items. `test_reference_subset_deterministic` builds the subset twice under
> different `PYTHONHASHSEED` values and asserts element-for-element identity.

The two builds happen in **separate interpreter processes** with different `PYTHONHASHSEED` values,
because that is the only way to observe the failure this guards against: a subset drawn from a set
(or from any hash-ordered collection) is stable inside one process and moves between them, and a
reference label file that silently pointed at different items after a restart would make
`judge_agreement_rate` meaningless.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.schema import (
    REFERENCE_SUBSET_SIZE,
    load_dataset,
    load_reference_labels,
    reference_subset,
)
from hrmosaic.core.ids import SEED

REPO_ROOT = Path(__file__).resolve().parents[2]

PROGRAM = (
    "import json;"
    "from evaluation.schema import load_dataset, reference_subset;"
    "print(json.dumps(reference_subset(load_dataset())))"
)


def _subset_in_a_fresh_interpreter(hash_seed: str) -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-c", PROGRAM],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": hash_seed, "PYTHONPATH": f"{REPO_ROOT}/src:{REPO_ROOT}"},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_the_seed_is_the_one_the_spec_names():
    assert SEED == 1729


def test_the_subset_holds_eight_items():
    assert len(reference_subset(load_dataset())) == REFERENCE_SUBSET_SIZE


def test_the_subset_is_element_for_element_identical_under_two_hash_seeds():
    first = _subset_in_a_fresh_interpreter("0")
    second = _subset_in_a_fresh_interpreter("12345")
    assert first == second
    assert first == reference_subset(load_dataset())


def test_only_answering_items_are_eligible():
    """A refusal, a clarification and an escalation carry no policy claims to ground."""
    dataset = load_dataset()
    behaviours = {item.id: item.expected_behavior for item in dataset.items}
    assert all(behaviours[item_id] == "answer" for item_id in reference_subset(dataset))


@pytest.mark.skipif(load_reference_labels() is None, reason="reference_labels.yaml is authored at P10")
def test_the_committed_labels_cover_exactly_the_selected_subset():
    labels = load_reference_labels()
    assert labels is not None
    assert sorted(label.item_id for label in labels.labels) == reference_subset(load_dataset())


@pytest.mark.skipif(load_reference_labels() is None, reason="reference_labels.yaml is authored at P10")
def test_the_protocol_block_names_the_labeller_the_date_and_the_blinding():
    """§13.7: the methodology is named accurately — never "human-vs-judge"."""
    labels = load_reference_labels()
    assert labels is not None
    protocol = labels.protocol
    assert protocol.labeller.strip()
    assert protocol.labelled_on.strip()
    assert protocol.blinding.strip()
    assert protocol.seed == SEED
    assert "human" not in protocol.labeller.lower()
