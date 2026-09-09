"""The one arithmetic identity the PTO answer rests on (spec §5.4, §8.4 tool 6).

`remaining_days == accrued_ytd - used_ytd - pending_days + carryover_unexpired`, stated at the
**2026-09-01 snapshot** for every one of the 24 employees, with `carryover_unexpired` zero when
`carryover_expires_on` is absent or already past at the snapshot. `E1042` resolves to `13.5`,
the number quoted in the demo narration, the eval gold answer and `test_mcp_tool_call.py`.

The accrual-rate check reads `corpus/facts.yml`, which P2 produces; it skips while that file is
absent so this phase's gate stays green in isolation, and the main session runs it after the
merge.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_DATA = REPO_ROOT / "mock_data"
FACTS_YML = REPO_ROOT / "corpus" / "facts.yml"

AS_OF = date(2026, 9, 1)


def _balances() -> list[dict]:
    return json.loads((MOCK_DATA / "pto_balances.json").read_text(encoding="utf-8"))["records"]


def _carryover_unexpired(record: dict) -> float:
    expires_on = record["carryover_expires_on"]
    if expires_on is None or date.fromisoformat(expires_on) < AS_OF:
        return 0.0
    return record["carryover_from_prior_year"]


def test_identity_holds_for_every_employee_at_the_snapshot():
    records = _balances()
    assert len(records) == 24
    for record in records:
        expected = record["accrued_ytd"] - record["used_ytd"] - record["pending_days"] + _carryover_unexpired(record)
        assert record["remaining_days"] == pytest.approx(expected), record["employee_id"]
        assert record["remaining_days"] >= 0.0, record["employee_id"]


def test_every_balance_is_stated_against_the_snapshot():
    for record in _balances():
        assert record["as_of"] == "2026-09-01"
        # 2026-09-01 is itself an accrual posting date, so the next one is the first of October.
        assert record["next_accrual_date"] == "2026-10-01"


def test_accrued_ytd_is_the_monthly_postings_up_to_the_snapshot():
    hire_dates = {
        record["employee_id"]: date.fromisoformat(record["hire_date"])
        for record in json.loads((MOCK_DATA / "employees.json").read_text(encoding="utf-8"))["records"]
    }
    for record in _balances():
        hired = hire_dates[record["employee_id"]]
        postings = sum(1 for month in range(1, AS_OF.month + 1) if date(2026, month, 1) > hired)
        expected = round(record["accrual_rate_days_per_month"] * postings, 2)
        assert record["accrued_ytd"] == pytest.approx(expected), record["employee_id"]


def test_e1042_resolves_to_thirteen_point_five():
    priya = next(record for record in _balances() if record["employee_id"] == "E1042")
    assert priya["accrual_rate_days_per_month"] == 1.50
    assert priya["accrual_fact_key"] == "pto.accrual.ft_3y_plus"
    # nine 2026 postings, 1 January through 1 September, at 1.50 days a month
    assert priya["accrued_ytd"] == pytest.approx(13.50)
    assert priya["used_ytd"] == 0.0
    assert priya["pending_days"] == 0.0
    assert priya["carryover_from_prior_year"] == 0.0
    assert priya["carryover_expires_on"] is None
    assert priya["remaining_days"] == pytest.approx(13.5)


def test_accrual_rate_matches_the_facts_yml_band():
    if not FACTS_YML.exists():
        pytest.skip("corpus/facts.yml not present (P2)")
    facts = yaml.safe_load(FACTS_YML.read_text(encoding="utf-8"))["facts"]
    for record in _balances():
        key = record["accrual_fact_key"]
        assert key in facts, f"{record['employee_id']}: {key} is missing from corpus/facts.yml"
        entry = facts[key]
        assert entry["unit"] == "days_per_month", key
        assert float(entry["value"]) == pytest.approx(record["accrual_rate_days_per_month"]), key
