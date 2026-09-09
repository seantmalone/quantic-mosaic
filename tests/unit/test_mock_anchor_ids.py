"""The four anchor records the rest of the build is written against (spec §5.4).

`E1042` is the demo persona of §18, `E1007` her manager and `E1002` her skip-level; `E1108`
is the benefits fixture whose 90-day waiting period is still open **at the 2026-09-01
snapshot** — not "today", which is the whole point of the snapshot convention. Later phases
hard-code these ids (`test_mcp_tool_call.py` calls `check_pto_balance("E1042")`), so they are
asserted here, in the phase that mints them.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_DATA = REPO_ROOT / "mock_data"

AS_OF = date(2026, 9, 1)
EMPLOYEE_ID = re.compile(r"^E1[0-9]{3}$")
ANCHORS = ("E1002", "E1007", "E1042", "E1108")


def _records(name: str) -> list[dict]:
    return json.loads((MOCK_DATA / f"{name}.json").read_text(encoding="utf-8"))["records"]


@pytest.fixture(scope="module")
def employees() -> dict[str, dict]:
    return {record["employee_id"]: record for record in _records("employees")}


def test_ids_are_unique_well_formed_and_non_contiguous():
    ids = [record["employee_id"] for record in _records("employees")]
    assert len(ids) == 24
    assert len(set(ids)) == 24
    assert all(EMPLOYEE_ID.match(employee_id) for employee_id in ids)

    numbers = sorted(int(employee_id[1:]) for employee_id in ids)
    assert numbers[0] >= 1001 and numbers[-1] <= 1199
    # "non-contiguous": the 24 ids are not a solid block, so nothing can iterate a range
    # and assume every id in it exists.
    assert numbers != list(range(numbers[0], numbers[0] + 24))


def test_the_four_anchors_are_present(employees):
    assert set(ANCHORS) <= set(employees)


def test_e1042_is_the_demo_persona(employees):
    priya = employees["E1042"]
    assert priya["preferred_name"] == "Priya"
    assert priya["legal_name"] == "Priya Raghavan"
    assert priya["title"] == "Senior Robotics Engineer"
    assert priya["department"] == "Engineering"
    assert priya["employment_type"] == "full_time"
    assert priya["fte"] == 1.0
    assert priya["level"] == "L5"
    assert priya["hire_date"] == "2022-11-13"
    assert priya["tenure_months_at_as_of"] == 45
    assert priya["work_arrangement"] == "hybrid"
    assert priya["work_country"] == "US"
    assert priya["office_id"] == "bos"
    assert priya["manager_id"] == "E1007"


def test_e1042_manager_and_skip_level_resolve(employees):
    org = {record["employee_id"]: record for record in _records("org_manager_map")}
    assert org["E1042"]["manager_id"] == "E1007"
    assert org["E1042"]["skip_level_id"] == "E1002"
    assert "E1042" in org["E1007"]["direct_reports"]
    assert org["E1007"]["manager_id"] == "E1002"
    assert employees["E1007"]["legal_name"] == "Dana Whitfield"
    assert employees["E1007"]["title"] == "Director, Engineering"
    assert employees["E1002"]["preferred_name"] == "Miguel"
    assert employees["E1002"]["title"] == "VP Engineering"


def test_e1108_is_still_inside_its_waiting_period_at_the_snapshot(employees):
    assert employees["E1108"]["hire_date"] == "2026-08-15"
    benefits = {record["employee_id"]: record for record in _records("benefits_elections")}["E1108"]
    assert benefits["waiting_period_ends"] == "2026-11-13"
    assert date.fromisoformat(benefits["waiting_period_ends"]) > AS_OF
    assert benefits["eligibility_reason"] == "90-day waiting period ends 2026-11-13"
    assert benefits["elections"] == []


def test_every_person_dataset_covers_the_same_24_employees(employees):
    for name in ("pto_balances", "benefits_elections", "org_manager_map"):
        assert {record["employee_id"] for record in _records(name)} == set(employees)


def test_manager_and_office_references_resolve(employees):
    office_ids = {record["office_id"] for record in _records("offices")}
    roots = 0
    for record in employees.values():
        assert record["office_id"] in office_ids
        if record["manager_id"] is None:
            roots += 1
        else:
            assert record["manager_id"] in employees
    assert roots == 1
