#!/usr/bin/env python3
"""Generate the six committed mock datasets of spec §5.4.

    python scripts/gen_mock_data.py

The output is an **authored-once generator artifact** (§21 row 28): the JSON is committed,
reviewed like source, and re-running this script must reproduce it byte for byte —
`python scripts/gen_mock_data.py && git diff --exit-code mock_data/` is P3's gate. Everything
that varies is drawn from a single `random.Random(SEED)` with `SEED = 1729`; everything a
later phase names by hand (the four anchor records, Priya's 13.5 days) is pinned in the roster
below, never sampled.

**The `as_of` snapshot.** Balances, tenure and waiting periods are stated as of `2026-09-01`,
exactly as an HRIS export would be. Nothing here — and nothing that reads this data — computes
against "today": the system runs on the real wall clock, but date-bearing *answers* are
snapshot-relative, so the documented `13.5` is right on any day a grader runs it. See
`mock_data/README.md`.

**Synthetic conventions.** `@mosaicrobotics.example` addresses (RFC 2606), phones in the
reserved `+1-555-01xx` block, no SSN field in any schema, no dates of birth, no street
addresses. `scripts/pii_check.py` fails the build on any hit.

The Pydantic models in this module are the single definition of every dataset's shape;
`scripts/gen_mock_schemas.py` imports them and writes `mock_data/schemas/*.schema.json`.
"""

from __future__ import annotations

import datetime
import json
import random
import unicodedata
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SEED = 1729
AS_OF = datetime.date(2026, 9, 1)
PLAN_YEAR = 2026
GENERATOR = "scripts/gen_mock_data.py seed=1729"
NOTICE = (
    "SYNTHETIC DATA — fictional persons, generated for the Quantic AI Engineering project. "
    "No real employee information."
)
EMAIL_DOMAIN = "mosaicrobotics.example"
WAITING_PERIOD_DAYS = 90

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_DATA = REPO_ROOT / "mock_data"

EmployeeId = Annotated[str, StringConstraints(pattern=r"^E1[0-9]{3}$")]
Email = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z.\-]*@mosaicrobotics\.example$")]
Phone = Annotated[str, StringConstraints(pattern=r"^\+1-555-01[0-9]{2}$")]
CostCenter = Annotated[str, StringConstraints(pattern=r"^CC-[0-9]{4}$")]

OfficeId = Literal["bos", "atx", "ber", "remote-us"]
Country = Literal["US", "DE"]
EmploymentType = Literal["full_time", "part_time", "contractor", "intern"]
WorkArrangement = Literal["onsite", "hybrid", "remote"]
PlanType = Literal["medical", "dental", "vision", "retirement_401k", "hsa", "fsa", "life"]
Tier = Literal["employee_only", "employee_spouse", "employee_children", "family"]


# --------------------------------------------------------------------------------------
# models — the single definition of every dataset's shape
# --------------------------------------------------------------------------------------


class MockDataFile(BaseModel):
    """The banner every mock dataset carries, so no reader can mistake it for real data."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    synthetic: Literal[True] = Field(alias="_synthetic", description="Always true; this file is fabricated.")
    notice: str = Field(alias="_notice", description="Human-readable synthetic-data notice.")
    generator: str = Field(alias="_generator", description="The command that produced this file.")
    as_of: datetime.date = Field(description="The snapshot date every date-bearing value is stated against.")


class Employee(BaseModel):
    """One synthetic employee. No SSN, no date of birth, no home address — by design."""

    model_config = ConfigDict(extra="forbid")

    employee_id: EmployeeId
    preferred_name: str
    legal_name: str
    email: Email
    work_phone: Phone = Field(description="Reserved fictional block (+1-555-01xx); never a real number.")
    title: str
    department: str
    employment_type: EmploymentType
    fte: float = Field(ge=0.1, le=1.0)
    hire_date: datetime.date
    tenure_months_at_as_of: int = Field(ge=0, description="Whole months of service completed at as_of.")
    level: str
    office_id: OfficeId
    work_country: Country
    work_arrangement: WorkArrangement
    manager_id: EmployeeId | None = Field(description="null for the one org root.")
    cost_center: CostCenter


class EmployeesFile(MockDataFile):
    records: list[Employee]


class PtoBalance(BaseModel):
    """A PTO balance stated at the snapshot.

    `remaining_days == accrued_ytd - used_ytd - pending_days + carryover_unexpired`, where
    `carryover_unexpired` is 0.0 once `carryover_expires_on` has passed at `as_of`.
    """

    model_config = ConfigDict(extra="forbid")

    employee_id: EmployeeId
    as_of: datetime.date
    accrual_rate_days_per_month: float = Field(ge=0)
    accrual_fact_key: str = Field(description="The corpus/facts.yml entry this rate comes from.")
    accrued_ytd: float = Field(ge=0)
    used_ytd: float = Field(ge=0)
    pending_days: float = Field(ge=0)
    carryover_from_prior_year: float = Field(ge=0)
    carryover_expires_on: datetime.date | None
    remaining_days: float = Field(ge=0)
    blackout_dates: list[datetime.date]
    next_accrual_date: datetime.date


class PtoBalancesFile(MockDataFile):
    records: list[PtoBalance]


class Election(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_type: PlanType
    plan_id: str
    plan_name: str
    tier: Tier
    effective_date: datetime.date
    employee_cost_monthly: float = Field(ge=0)


class EnrollmentWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: datetime.date
    close: datetime.date


class BenefitsElections(BaseModel):
    """Benefits as of the snapshot. Eligibility is *derived* from `waiting_period_ends`."""

    model_config = ConfigDict(extra="forbid")

    employee_id: EmployeeId
    plan_year: int
    as_of: datetime.date
    waiting_period_ends: datetime.date
    eligibility_reason: str
    elections: list[Election]
    dependents: int = Field(ge=0)
    open_enrollment_window: EnrollmentWindow


class BenefitsElectionsFile(MockDataFile):
    records: list[BenefitsElections]


class OrgNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: EmployeeId
    manager_id: EmployeeId | None
    skip_level_id: EmployeeId | None
    direct_reports: list[EmployeeId]


class OrgManagerMapFile(MockDataFile):
    records: list[OrgNode]


class Office(BaseModel):
    model_config = ConfigDict(extra="forbid")

    office_id: OfficeId
    city: str
    country: Country
    timezone: str
    entity: str
    holiday_calendar_id: str


class OfficesFile(MockDataFile):
    records: list[Office]


class Holiday(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: datetime.date = Field(description="The calendar date of the holiday itself.")
    name: str
    observed: datetime.date = Field(description="The date the company observes it; US weekend dates shift.")


class HolidayCalendar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holiday_calendar_id: str
    country: Country
    holidays: list[Holiday]


class Holidays2026File(MockDataFile):
    records: list[HolidayCalendar]


# --------------------------------------------------------------------------------------
# the roster — hand-authored people, seeded ids
# --------------------------------------------------------------------------------------

# key, preferred, legal, title, department, level, employment_type, fte, hire_date,
# office_id, work_arrangement, manager key, cost_center
# One person per two lines reads as a roster; one field per line does not.
# fmt: off
ROSTER: tuple[tuple[str, str, str, str, str, str, str, float, str, str, str, str | None, str], ...] = (
    ("ceo", "Nadine", "Nadine Alarcon", "Chief Executive Officer", "Executive",
     "L10", "full_time", 1.0, "2018-03-05", "atx", "hybrid", None, "CC-1000"),
    ("vp_eng", "Miguel", "Miguel Ferreira", "VP Engineering", "Engineering",
     "L9", "full_time", 1.0, "2019-06-17", "atx", "hybrid", "ceo", "CC-1200"),
    ("vp_people", "Adaeze", "Adaeze Okonkwo", "VP People Operations", "People Operations",
     "L9", "full_time", 1.0, "2019-09-02", "atx", "hybrid", "ceo", "CC-1600"),
    ("dir_eng", "Dana", "Dana Whitfield", "Director, Engineering", "Engineering",
     "L8", "full_time", 1.0, "2020-02-24", "bos", "hybrid", "vp_eng", "CC-1210"),
    ("dir_mfg", "Tomasz", "Tomasz Wierzbicki", "Director, Manufacturing", "Manufacturing",
     "L8", "full_time", 1.0, "2020-07-13", "atx", "onsite", "ceo", "CC-1400"),
    ("dir_sales", "Renata", "Renata Villalobos", "Director, Sales", "Sales",
     "L8", "full_time", 1.0, "2021-01-11", "remote-us", "remote", "ceo", "CC-1500"),
    ("dir_de", "Katrin", "Katrin Hoffmann", "Site Director, Berlin", "Operations",
     "L8", "full_time", 1.0, "2021-04-06", "ber", "onsite", "ceo", "CC-1900"),
    ("eng_priya", "Priya", "Priya Raghavan", "Senior Robotics Engineer", "Engineering",
     "L5", "full_time", 1.0, "2022-11-13", "bos", "hybrid", "dir_eng", "CC-1210"),
    ("eng_wes", "Wes", "Weston Ackroyd", "Staff Software Engineer", "Engineering",
     "L6", "full_time", 1.0, "2021-08-30", "bos", "hybrid", "dir_eng", "CC-1210"),
    ("eng_yuki", "Yuki", "Yuki Tanabe", "Robotics Engineer II", "Engineering",
     "L4", "full_time", 1.0, "2024-03-04", "remote-us", "remote", "dir_eng", "CC-1210"),
    ("eng_ola", "Ola", "Olamide Adeyemi", "Firmware Engineer", "Engineering",
     "L4", "full_time", 1.0, "2023-05-22", "atx", "hybrid", "dir_eng", "CC-1220"),
    ("eng_ines", "Ines", "Ines Duarte", "Controls Engineer", "Engineering",
     "L5", "full_time", 1.0, "2022-02-07", "ber", "hybrid", "dir_de", "CC-1910"),
    ("eng_marcus", "Marcus", "Marcus Feldman", "Robotics Engineer I", "Engineering",
     "L3", "full_time", 1.0, "2026-08-15", "bos", "hybrid", "dir_eng", "CC-1210"),
    ("qa_bea", "Bea", "Beatriz Mendes", "QA Automation Engineer", "Engineering",
     "L4", "part_time", 0.6, "2023-10-02", "remote-us", "remote", "dir_eng", "CC-1230"),
    ("mfg_hector", "Hector", "Hector Salgado", "Manufacturing Technician", "Manufacturing",
     "L3", "full_time", 1.0, "2021-11-08", "atx", "onsite", "dir_mfg", "CC-1400"),
    ("mfg_junie", "Junie", "Junie Baptiste", "Production Planner", "Manufacturing",
     "L4", "full_time", 1.0, "2024-09-16", "atx", "onsite", "dir_mfg", "CC-1400"),
    ("mfg_sigrid", "Sigrid", "Sigrid Moller", "Quality Inspector", "Manufacturing",
     "L3", "part_time", 0.8, "2022-06-13", "atx", "onsite", "dir_mfg", "CC-1410"),
    ("sales_cam", "Cam", "Camille Boudreaux", "Enterprise Account Executive", "Sales",
     "L5", "full_time", 1.0, "2023-01-09", "remote-us", "remote", "dir_sales", "CC-1500"),
    ("sales_ravi", "Ravi", "Ravinder Chadha", "Solutions Engineer", "Sales",
     "L5", "full_time", 1.0, "2025-02-17", "remote-us", "remote", "dir_sales", "CC-1500"),
    ("cs_noor", "Noor", "Noor Haddad", "Customer Success Manager", "Customer Success",
     "L4", "full_time", 1.0, "2024-06-10", "bos", "hybrid", "dir_sales", "CC-1520"),
    ("people_gwen", "Gwen", "Gwendolyn Astley", "Senior People Partner", "People Operations",
     "L5", "full_time", 1.0, "2022-08-15", "atx", "hybrid", "vp_people", "CC-1600"),
    ("people_tobi", "Tobi", "Tobias Lindqvist", "HR Operations Specialist", "People Operations",
     "L3", "full_time", 1.0, "2025-06-02", "atx", "hybrid", "vp_people", "CC-1600"),
    ("fin_marta", "Marta", "Marta Kowalczyk", "Financial Analyst", "Finance",
     "L4", "part_time", 0.8, "2023-03-13", "atx", "hybrid", "ceo", "CC-1700"),
    ("sec_devon", "Devon", "Devon Achebe", "Information Security Engineer", "IT & Security",
     "L5", "full_time", 1.0, "2021-09-27", "remote-us", "remote", "vp_eng", "CC-1800"),
)
# fmt: on

# The anchors of §5.4: the ids later phases hard-code. Everything else is sampled from
# E1001–E1199, so the set is deliberately non-contiguous.
ANCHOR_IDS = {"vp_eng": "E1002", "dir_eng": "E1007", "eng_priya": "E1042", "eng_marcus": "E1108"}
ID_RANGE = range(1001, 1200)

OFFICES = (
    ("bos", "Boston", "US", "America/New_York", "Mosaic Robotics, Inc.", "us-2026"),
    ("atx", "Austin", "US", "America/Chicago", "Mosaic Robotics, Inc.", "us-2026"),
    ("ber", "Berlin", "DE", "Europe/Berlin", "Mosaic Robotics GmbH", "de-2026"),
    ("remote-us", "Remote — United States", "US", "America/Chicago", "Mosaic Robotics, Inc.", "us-2026"),
)

# 2026 company holidays. US weekend dates are observed on the nearest weekday; German public
# holidays are not moved, so `observed` equals `date` on the de-2026 calendar.
US_HOLIDAYS = (
    ("2026-01-01", "New Year's Day", "2026-01-01"),
    ("2026-01-19", "Martin Luther King Jr. Day", "2026-01-19"),
    ("2026-02-16", "Presidents' Day", "2026-02-16"),
    ("2026-05-25", "Memorial Day", "2026-05-25"),
    ("2026-06-19", "Juneteenth", "2026-06-19"),
    ("2026-07-04", "Independence Day", "2026-07-03"),
    ("2026-09-07", "Labor Day", "2026-09-07"),
    ("2026-11-26", "Thanksgiving Day", "2026-11-26"),
    ("2026-11-27", "Day after Thanksgiving", "2026-11-27"),
    ("2026-12-24", "Christmas Eve", "2026-12-24"),
    ("2026-12-25", "Christmas Day", "2026-12-25"),
)
DE_HOLIDAYS = (
    ("2026-01-01", "Neujahrstag", "2026-01-01"),
    ("2026-03-08", "Internationaler Frauentag", "2026-03-08"),
    ("2026-04-03", "Karfreitag", "2026-04-03"),
    ("2026-04-06", "Ostermontag", "2026-04-06"),
    ("2026-05-01", "Tag der Arbeit", "2026-05-01"),
    ("2026-05-14", "Christi Himmelfahrt", "2026-05-14"),
    ("2026-05-25", "Pfingstmontag", "2026-05-25"),
    ("2026-10-03", "Tag der Deutschen Einheit", "2026-10-03"),
    ("2026-12-25", "Erster Weihnachtsfeiertag", "2026-12-25"),
    ("2026-12-26", "Zweiter Weihnachtsfeiertag", "2026-12-26"),
)

COMPANY_BLACKOUT = ("2026-12-22", "2026-12-23")
MANUFACTURING_BLACKOUT = ("2026-06-29", "2026-06-30")

# Accrual bands. Each key must exist in corpus/facts.yml (P2) with unit `days_per_month`;
# tests/unit/test_pto_balance_arithmetic.py asserts the two agree.
ACCRUAL_BANDS = {
    "pto.accrual.ft_3y_plus": 1.50,
    "pto.accrual.ft_under_3y": 1.25,
    "pto.accrual.part_time_prorated": 0.75,
}

PLANS = {
    "medical_ppo": ("MED-PPO-1500", "MosaicCare PPO 1500", (142.00, 286.00, 262.00, 398.00)),
    "medical_hdhp": ("MED-HDHP-3000", "MosaicCare HDHP 3000", (78.00, 158.00, 144.00, 224.00)),
    "medical_de": ("MED-DE-SUPP", "MosaicCare Berlin Supplement", (22.00, 44.00, 40.00, 62.00)),
    "dental": ("DEN-STD", "MosaicSmile Standard Dental", (14.00, 26.00, 24.00, 38.00)),
    "vision": ("VIS-STD", "MosaicView Standard Vision", (6.00, 11.00, 10.00, 16.00)),
    "life": ("LIFE-BASIC", "Basic Life & AD&D (company paid)", (0.00, 0.00, 0.00, 0.00)),
    "retirement": ("RET-401K", "MosaicOne 401(k)", (0.00, 0.00, 0.00, 0.00)),
    "hsa": ("HSA-STD", "MosaicSave Health Savings Account", (0.00, 0.00, 0.00, 0.00)),
    "fsa": ("FSA-HC", "MosaicSave Health Care FSA", (0.00, 0.00, 0.00, 0.00)),
}
TIERS: tuple[Tier, ...] = ("employee_only", "employee_spouse", "employee_children", "family")


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

_FOLD = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "œ": "oe", "ß": "ss", "ł": "l", "Ł": "L", "đ": "d"})


def ascii_slug(name: str) -> str:
    """Fold a legal name to the lowercase ASCII local part of a `.example` address."""
    folded = unicodedata.normalize("NFKD", name.translate(_FOLD))
    stripped = "".join(character for character in folded if not unicodedata.combining(character))
    parts = [part for part in stripped.lower().replace("'", "").replace("-", "").split() if part]
    return ".".join(parts)


def whole_months_between(start: datetime.date, end: datetime.date) -> int:
    """Whole months of service completed between `start` and `end`."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def accrual_postings_ytd(hire_date: datetime.date) -> int:
    """Monthly accrual postings in `AS_OF`'s year, on the first, up to and including `AS_OF`."""
    return sum(1 for month in range(1, AS_OF.month + 1) if datetime.date(AS_OF.year, month, 1) > hire_date)


def accrual_band(employment_type: str, tenure_months: int) -> str:
    if employment_type == "part_time":
        return "pto.accrual.part_time_prorated"
    return "pto.accrual.ft_3y_plus" if tenure_months >= 36 else "pto.accrual.ft_under_3y"


def first_of_next_month(day: datetime.date) -> datetime.date:
    return datetime.date(day.year + day.month // 12, day.month % 12 + 1, 1)


def assign_employee_ids(rng: random.Random) -> dict[str, str]:
    """Pin the four anchors, then sample the remaining 20 ids from E1001–E1199."""
    pool = sorted(set(ID_RANGE) - {int(anchor[1:]) for anchor in ANCHOR_IDS.values()})
    sampled = sorted(rng.sample(pool, len(ROSTER) - len(ANCHOR_IDS)))
    remaining = iter(f"E{number}" for number in sampled)
    return {row[0]: ANCHOR_IDS.get(row[0]) or next(remaining) for row in ROSTER}


# --------------------------------------------------------------------------------------
# dataset builders
# --------------------------------------------------------------------------------------


def build_employees(rng: random.Random, ids: dict[str, str]) -> list[Employee]:
    office_country = {row[0]: row[2] for row in OFFICES}
    phones = sorted(rng.sample(range(100), len(ROSTER)))
    employees = []
    for row, phone in zip(ROSTER, phones, strict=True):
        (
            key,
            preferred,
            legal,
            title,
            department,
            level,
            employment_type,
            fte,
            hire_date,
            office_id,
            arrangement,
            manager_key,
            cost_center,
        ) = row
        hired = datetime.date.fromisoformat(hire_date)
        employees.append(
            Employee(
                employee_id=ids[key],
                preferred_name=preferred,
                legal_name=legal,
                email=f"{ascii_slug(legal)}@{EMAIL_DOMAIN}",
                work_phone=f"+1-555-01{phone:02d}",
                title=title,
                department=department,
                employment_type=employment_type,
                fte=fte,
                hire_date=hired,
                tenure_months_at_as_of=whole_months_between(hired, AS_OF),
                level=level,
                office_id=office_id,
                work_country=office_country[office_id],
                work_arrangement=arrangement,
                manager_id=ids[manager_key] if manager_key else None,
                cost_center=cost_center,
            )
        )
    return sorted(employees, key=lambda employee: employee.employee_id)


def build_pto_balances(rng: random.Random, employees: list[Employee]) -> list[PtoBalance]:
    by_id = {employee.employee_id: employee for employee in employees}
    balances = []
    for employee_id in sorted(by_id):
        employee = by_id[employee_id]
        fact_key = accrual_band(employee.employment_type, employee.tenure_months_at_as_of)
        rate = ACCRUAL_BANDS[fact_key]
        accrued = round(rate * accrual_postings_ytd(employee.hire_date), 2)

        carryover, expires_on = 0.0, None
        if employee.hire_date.year < AS_OF.year and rng.random() < 0.5:
            carryover = rng.choice((1.0, 1.5, 2.0, 2.5, 3.0))
            # Half the carryover balances have already lapsed at the snapshot — the case the
            # `carryover_unexpired` term in tool 6 exists for.
            expires_on = datetime.date(2026, 3, 31) if rng.random() < 0.5 else datetime.date(2026, 12, 31)
        unexpired = carryover if expires_on is not None and expires_on >= AS_OF else 0.0

        available = accrued + unexpired
        used = 0.5 * rng.randint(0, int(available * 2 * 0.6))
        pending = 0.5 * rng.randint(0, min(6, int((available - used) * 2)))
        if employee.employee_id == "E1042":
            # The demo persona is pinned: nine 2026 postings at 1.50 and nothing taken, so the
            # documented answer is exactly 13.5 days remaining at the snapshot.
            carryover, expires_on, unexpired, used, pending = 0.0, None, 0.0, 0.0, 0.0

        blackout = list(COMPANY_BLACKOUT)
        if employee.department == "Manufacturing":
            blackout += list(MANUFACTURING_BLACKOUT)

        balances.append(
            PtoBalance(
                employee_id=employee.employee_id,
                as_of=AS_OF,
                accrual_rate_days_per_month=rate,
                accrual_fact_key=fact_key,
                accrued_ytd=accrued,
                used_ytd=used,
                pending_days=pending,
                carryover_from_prior_year=carryover,
                carryover_expires_on=expires_on,
                remaining_days=round(accrued - used - pending + unexpired, 2),
                blackout_dates=sorted(datetime.date.fromisoformat(day) for day in blackout),
                next_accrual_date=first_of_next_month(AS_OF),
            )
        )
    return balances


def _elections(rng: random.Random, employee: Employee, tier: Tier, effective: datetime.date) -> list[Election]:
    tier_index = TIERS.index(tier)
    if employee.work_country == "DE":
        chosen = ["medical_de", "dental", "vision", "life"]
    else:
        medical = "medical_hdhp" if rng.random() < 0.4 else "medical_ppo"
        savings = "hsa" if medical == "medical_hdhp" else "fsa"
        chosen = [medical, "dental", "vision", "life", "retirement", savings]
    plan_types: dict[str, PlanType] = {
        "medical_ppo": "medical",
        "medical_hdhp": "medical",
        "medical_de": "medical",
        "dental": "dental",
        "vision": "vision",
        "life": "life",
        "retirement": "retirement_401k",
        "hsa": "hsa",
        "fsa": "fsa",
    }
    elections = []
    for plan_key in chosen:
        plan_id, plan_name, costs = PLANS[plan_key]
        elections.append(
            Election(
                plan_type=plan_types[plan_key],
                plan_id=plan_id,
                plan_name=plan_name,
                tier=tier if plan_types[plan_key] in ("medical", "dental", "vision") else "employee_only",
                effective_date=effective,
                employee_cost_monthly=costs[tier_index],
            )
        )
    return elections


def build_benefits(rng: random.Random, employees: list[Employee]) -> list[BenefitsElections]:
    window = EnrollmentWindow(open=datetime.date(2026, 11, 1), close=datetime.date(2026, 11, 21))
    by_id = {employee.employee_id: employee for employee in employees}
    records = []
    for employee_id in sorted(by_id):
        employee = by_id[employee_id]
        waiting_ends = employee.hire_date + datetime.timedelta(days=WAITING_PERIOD_DAYS)
        still_waiting = waiting_ends > AS_OF

        tier: Tier = rng.choice(TIERS[:1] * 2 + TIERS[1:])
        if tier == "employee_only":
            dependents = 0
        elif tier == "employee_spouse":
            dependents = 1
        else:
            dependents = rng.randint(1, 3)
        effective = max(datetime.date(PLAN_YEAR, 1, 1), first_of_next_month(waiting_ends))

        if still_waiting:
            reason = f"{WAITING_PERIOD_DAYS}-day waiting period ends {waiting_ends.isoformat()}"
            elections: list[Election] = []
            dependents = 0
        else:
            reason = (
                f"Eligible since {waiting_ends.isoformat()} "
                f"({WAITING_PERIOD_DAYS}-day new-hire waiting period complete)"
            )
            elections = _elections(rng, employee, tier, effective)

        records.append(
            BenefitsElections(
                employee_id=employee.employee_id,
                plan_year=PLAN_YEAR,
                as_of=AS_OF,
                waiting_period_ends=waiting_ends,
                eligibility_reason=reason,
                elections=elections,
                dependents=dependents,
                open_enrollment_window=window,
            )
        )
    return records


def build_org_map(employees: list[Employee]) -> list[OrgNode]:
    managers = {employee.employee_id: employee.manager_id for employee in employees}
    reports: dict[str, list[str]] = {employee.employee_id: [] for employee in employees}
    for employee in employees:
        if employee.manager_id:
            reports[employee.manager_id].append(employee.employee_id)
    return [
        OrgNode(
            employee_id=employee_id,
            manager_id=managers[employee_id],
            skip_level_id=managers.get(managers[employee_id]) if managers[employee_id] else None,
            direct_reports=sorted(reports[employee_id]),
        )
        for employee_id in sorted(managers)
    ]


def build_offices() -> list[Office]:
    return [
        Office(
            office_id=office_id,
            city=city,
            country=country,
            timezone=timezone,
            entity=entity,
            holiday_calendar_id=calendar,
        )
        for office_id, city, country, timezone, entity, calendar in OFFICES
    ]


def build_holidays() -> list[HolidayCalendar]:
    def calendar(calendar_id: str, country: Country, rows) -> HolidayCalendar:
        return HolidayCalendar(
            holiday_calendar_id=calendar_id,
            country=country,
            holidays=[
                Holiday(
                    date=datetime.date.fromisoformat(day), name=name, observed=datetime.date.fromisoformat(observed)
                )
                for day, name, observed in rows
            ],
        )

    return [calendar("us-2026", "US", US_HOLIDAYS), calendar("de-2026", "DE", DE_HOLIDAYS)]


# --------------------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------------------


def build_all() -> dict[str, MockDataFile]:
    """Build every dataset from one seeded RNG, in a fixed order, so the bytes are stable."""
    rng = random.Random(SEED)
    banner = {"synthetic": True, "notice": NOTICE, "generator": GENERATOR, "as_of": AS_OF}

    ids = assign_employee_ids(rng)
    employees = build_employees(rng, ids)
    return {
        "employees": EmployeesFile(**banner, records=employees),
        "pto_balances": PtoBalancesFile(**banner, records=build_pto_balances(rng, employees)),
        "benefits_elections": BenefitsElectionsFile(**banner, records=build_benefits(rng, employees)),
        "org_manager_map": OrgManagerMapFile(**banner, records=build_org_map(employees)),
        "offices": OfficesFile(**banner, records=build_offices()),
        "holidays_2026": Holidays2026File(**banner, records=build_holidays()),
    }


def render(payload: MockDataFile) -> str:
    return json.dumps(payload.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    MOCK_DATA.mkdir(parents=True, exist_ok=True)
    for name, payload in build_all().items():
        path = MOCK_DATA / f"{name}.json"
        path.write_text(render(payload), encoding="utf-8")
        print(f"{path.relative_to(REPO_ROOT)}  {len(payload.records)} records  {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
