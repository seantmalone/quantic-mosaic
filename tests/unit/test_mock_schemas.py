"""Every committed dataset validates against its committed schema (spec §5.4, PD.3).

The schemas in `mock_data/schemas/` are generated from the Pydantic models in
`scripts/gen_mock_data.py` by `scripts/gen_mock_schemas.py`; they are authored-once generator
outputs (§21 row 28), reviewed like source and byte-idempotence-checked in P3's gate rather
than in CI. What CI carries is this test: the data still matches the shape every later phase
reads, banner and all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_DATA = REPO_ROOT / "mock_data"
SCHEMAS = MOCK_DATA / "schemas"

NOTICE = (
    "SYNTHETIC DATA — fictional persons, generated for the Quantic AI Engineering project. "
    "No real employee information."
)
GENERATOR = "scripts/gen_mock_data.py seed=1729"

# dataset name -> the number of records it must carry
DATASETS = {
    "employees": 24,
    "pto_balances": 24,
    "benefits_elections": 24,
    "org_manager_map": 24,
    "offices": 4,
    "holidays_2026": 2,
}


def _payload(name: str) -> dict:
    return json.loads((MOCK_DATA / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_dataset_validates_against_its_committed_schema(name):
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(_payload(name)), key=lambda error: list(error.absolute_path))
    assert errors == [], "\n".join(f"{list(error.absolute_path)}: {error.message}" for error in errors)


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_every_dataset_carries_the_synthetic_banner_and_the_snapshot(name):
    payload = _payload(name)
    assert payload["_synthetic"] is True
    assert payload["_notice"] == NOTICE
    assert payload["_generator"] == GENERATOR
    assert payload["as_of"] == "2026-09-01"


@pytest.mark.parametrize(("name", "count"), sorted(DATASETS.items()))
def test_record_counts(name, count):
    assert len(_payload(name)["records"]) == count


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_schema_is_closed(name):
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    # `extra="forbid"` on every model, so an accidental new field fails validation instead of
    # being silently carried into a later phase's tool output.
    assert schema["additionalProperties"] is False
    for definition in schema.get("$defs", {}).values():
        assert definition.get("additionalProperties") is False, definition.get("title")


def test_the_committed_datasets_stay_under_300_kb():
    total = sum(path.stat().st_size for path in MOCK_DATA.glob("*.json"))
    assert total < 300 * 1024, total
