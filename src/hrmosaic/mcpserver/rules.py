"""The deterministic rule engine behind `check_policy_compliance` (spec §8.4 tool 4).

Zero LLM calls, one pure function, the most heavily unit-testable component in the build. Its whole
knowledge is `corpus/rules.yml` (the seven scenarios) and `corpus/facts.yml` (the numbers), and its
whole vocabulary is the closed grammar documented in the header of `rules.yml`: `check.subject`,
`check.operator`, `check.compare_to`, `applies_when`, `blocking`. Anything outside that vocabulary
raises here rather than degrading quietly — a rule the engine silently ignored would be worse than a
build that stops.

**How a rule's `(doc_id, heading_path)` becomes a real `chunk_id`.** `rules.yml` cannot contain a
chunk id: ids are content hashes computed at ingest. So the pair is resolved at call time through
`core.corpusread.list_chunks(doc_id)`, filtered on the exact `" > "`-joined heading path, taking the
lowest `char_start` when a leaf was windowed. A stale id would be stripped silently by guardrail G2,
which is why `tests/unit/test_rules_engine.py` asserts every emitted `evidence.chunk_id` resolves in
the committed index.

**Notice is anchored on the submission date; balances and tenure keep the snapshot** (W8, C04).
Notice is *how much warning a request gives*, which is measured from the day it is submitted —
`submitted_on`, the turn's own date (`Settings.today()`, pinned by `MOCK_TODAY` for the recorded
stubs). It was measured from the mock data's frozen `as_of: 2026-09-01`, so every same-day PTO
request in the demo was scored as giving eight business days of notice it had not given. Balances,
tenure and the claim age are properties of the record and still read `as_of`; a caller-supplied
notice value is still ignored, exactly as §8.4 requires, so a verdict cannot swing on a model's
guess.

**Every requirement carries a `status`** (W8, C05): `met`, `unmet` or `not_stated`. `met: false`
had been doing two jobs — "the engine checked this and it fails" and "the caller never supplied the
parameter, so nothing was checked" — and the answer could not tell them apart, so a requirement
nobody had evaluated was narrated as a settled failure. `met` stays for every existing consumer and
means exactly `status == "met"`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from hrmosaic.core import corpusread

#: The seven scenarios of the §8.4 tool-4 input enum.
SCENARIOS = (
    "international_remote",
    "domestic_remote",
    "pto_request",
    "expense_claim",
    "equipment_request",
    "benefits_change",
    "conduct_escalation",
)

#: The four verdicts of the §8.4 tool-4 output.
VERDICTS = ("compliant", "conditional", "non_compliant", "insufficient_evidence")

#: `check.subject` — the closed vocabulary. `computed.*` means the engine derives it and never takes
#: it from the caller.
SUBJECT_PREFIXES = ("parameters.", "employee.")
COMPUTED_SUBJECTS = (
    "computed.tenure_days",
    "computed.notice_business_days",
    "computed.notice_calendar_days",
    "computed.overlaps_blackout",
    "computed.claim_age_days",
    "computed.days_since_eligibility",
)
#: `remaining_days` is an output of `check_pto_balance`, not a field of the employee profile: the two
#: would drift if the profile grew a copy (P2 report §9.2).
BALANCE_SUBJECTS = ("pto_balance.remaining_days",)

#: A `fact_key` may be **indirect**: `pto_balance.accrual_fact_key` names the field of the
#: employee's own balance row that holds the real key (W8, C29). `rules.yml` hard-coded
#: `pto.accrual.ft_3y_plus` on the PTO balance requirement, so nine of the twenty-four mock
#: employees were quoted the accrual band of a tenure they do not have on the one requirement that
#: decides their request.
FACT_KEY_INDIRECTION = ("pto_balance.",)

#: The three values `status` takes (W8, C05). `not_stated` is the one `met: false` used to hide:
#: nothing was supplied, so nothing was checked.
STATUSES = ("met", "unmet", "not_stated")

#: The subjects that read the frozen record rather than the request: they are evaluated against
#: `as_of` and are not verifiable when the request was submitted **before** the snapshot they would
#: be read from (W8, C04).
SNAPSHOT_SUBJECTS = (
    "employee.tenure_months_at_as_of",
    "computed.tenure_days",
    *BALANCE_SUBJECTS,
)

#: `check.operator` — the closed vocabulary.
COMPARISON_OPERATORS = ("lte", "lt", "gte", "gt", "eq", "in", "date_lte", "date_gte")
UNVERIFIABLE_OPERATORS = ("manual", "informational")
OPERATORS = COMPARISON_OPERATORS + UNVERIFIABLE_OPERATORS

#: `applies_when` — the closed vocabulary.
GUARD_PREFIXES = ("unmet:", "met:", "parameter_eq:", "parameter_gte:", "employee_eq:")

_SNIPPET_CHARS = 300


class RuleError(ValueError):
    """A `rules.yml` construct outside the closed vocabulary. A build-stopping bug, not a verdict."""


@dataclass(frozen=True)
class RuleSet:
    """`corpus/rules.yml` plus `corpus/facts.yml`, parsed once."""

    rules_version: str
    scenarios: dict[str, Any]
    facts: dict[str, Any]


_cache: dict[tuple[str, str], RuleSet] = {}


def load_rules(rules_path: Path, facts_path: Path) -> RuleSet:
    """Parse both YAML files, cached per path pair — they are committed and read-only at run time."""
    key = (str(rules_path), str(facts_path))
    if key not in _cache:
        rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        facts = yaml.safe_load(facts_path.read_text(encoding="utf-8"))["facts"]
        _cache[key] = RuleSet(rules_version=str(rules["rules_version"]), scenarios=rules["scenarios"], facts=facts)
    return _cache[key]


# --------------------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------------------


def resolve_evidence(
    doc_id: str, heading_path: str, connection: sqlite3.Connection | None = None
) -> dict[str, Any] | None:
    """`(doc_id, heading_path)` → the real chunk that carries it, or `None` when nothing matches.

    The lowest `char_start` wins when the chunker windowed a long leaf, so a requirement always
    cites the head of its section rather than an arbitrary continuation.
    """
    matches = [chunk for chunk in corpusread.list_chunks(doc_id, connection) if chunk.heading_path == heading_path]
    if not matches:
        return None
    chunk = min(matches, key=lambda row: row.char_start)
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "heading_path": chunk.heading_path,
        "snippet": chunk.text[:_SNIPPET_CHARS].strip(),
    }


# --------------------------------------------------------------------------------------
# Date arithmetic, all against the snapshot
# --------------------------------------------------------------------------------------


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def business_days_between(start: date, end: date, holidays: frozenset[date]) -> int:
    """Business days strictly after `start` and strictly before `end` — the notice a request gives.

    Weekends and the employee's own observed company holidays are excluded, so "5 business days"
    means five days somebody could act on. Zero when `end` is not after `start`: the engine reports
    a shortfall, never negative notice.
    """
    if end <= start:
        return 0
    count = 0
    cursor = start + timedelta(days=1)
    while cursor < end:
        if cursor.weekday() < 5 and cursor not in holidays:
            count += 1
        cursor += timedelta(days=1)
    return count


# --------------------------------------------------------------------------------------
# The evaluation context
# --------------------------------------------------------------------------------------


@dataclass
class Context:
    """Everything one `check_policy_compliance` call may read. Assembled once, then read-only."""

    as_of: date
    #: The day the request is submitted — the turn's own date (W8, C04). Notice is measured from
    #: here; everything the record knows is still measured from `as_of`.
    submitted_on: date
    employee: dict[str, Any]
    balance: dict[str, Any]
    parameters: dict[str, Any]
    holidays: frozenset[date]
    facts: dict[str, Any]
    connection: sqlite3.Connection | None = None

    # -- computed subjects -------------------------------------------------------------
    def tenure_days(self) -> int | None:
        hire = _parse_date(self.employee.get("hire_date"))
        return None if hire is None else (self.as_of - hire).days

    def notice_calendar_days(self) -> int | None:
        start = _parse_date(self.parameters.get("start_date"))
        return None if start is None else max(0, (start - self.submitted_on).days)

    def notice_business_days(self) -> int | None:
        start = _parse_date(self.parameters.get("start_date"))
        return None if start is None else business_days_between(self.submitted_on, start, self.holidays)

    def claim_age_days(self) -> int | None:
        transaction = _parse_date(self.parameters.get("transaction_date"))
        return None if transaction is None else max(0, (self.submitted_on - transaction).days)

    def days_since_eligibility(self) -> int | None:
        """Days since this employee's benefits waiting period ended — negative before it ends.

        The new-hire election window runs from the END of the waiting period, not from the hire
        date (W8, C30): a new hire told the open-enrollment window was their deadline lost three
        weeks of it.
        """
        hire = _parse_date(self.employee.get("hire_date"))
        waiting = _numeric(self.facts.get("benefits.eligibility.waiting_period_days", {}).get("value"))
        if hire is None or waiting is None:
            return None
        return (self.submitted_on - (hire + timedelta(days=int(waiting)))).days

    def eligibility_date(self) -> date | None:
        """The day this employee's benefits waiting period ends."""
        hire = _parse_date(self.employee.get("hire_date"))
        waiting = _numeric(self.facts.get("benefits.eligibility.waiting_period_days", {}).get("value"))
        return None if hire is None or waiting is None else hire + timedelta(days=int(waiting))

    def span_end(self) -> date | None:
        """The last day the request covers: `end_date`, or `days` business days from the start.

        The `days` fallback used to add calendar days, so a three-business-day request starting on
        a Friday was walked to Sunday and a blackout on the Monday it actually covered was missed
        (W8, C04). The walk is the same calendar `business_days_between` uses — weekends and the
        employee's own observed holidays.
        """
        start = _parse_date(self.parameters.get("start_date"))
        if start is None:
            return None
        end = _parse_date(self.parameters.get("end_date"))
        if end is not None:
            return end
        days = self.parameters.get("days")
        span = int(days) if isinstance(days, int | float) and not isinstance(days, bool) else 1
        cursor, remaining = start, max(span, 1)
        while True:
            if cursor.weekday() < 5 and cursor not in self.holidays:
                remaining -= 1
            if remaining <= 0:
                return cursor
            cursor += timedelta(days=1)

    def duration_days(self) -> int | None:
        """Consecutive calendar days the request covers, derived from the two dates (W8, C05)."""
        start = _parse_date(self.parameters.get("start_date"))
        end = _parse_date(self.parameters.get("end_date"))
        return None if start is None or end is None else (end - start).days + 1

    def overlaps_blackout(self) -> bool | None:
        """True when the requested span touches a blackout date on the employee's balance record."""
        start = _parse_date(self.parameters.get("start_date"))
        end = self.span_end()
        if start is None or end is None:
            return None
        blackout = {parsed for parsed in (_parse_date(day) for day in self.balance.get("blackout_dates", [])) if parsed}
        return any(start <= day <= end for day in blackout)

    def subject(self, name: str) -> Any:
        if name.startswith("parameters."):
            return self.parameters.get(name.removeprefix("parameters."))
        if name.startswith("employee."):
            return self.employee.get(name.removeprefix("employee."))
        if name in BALANCE_SUBJECTS:
            return self.balance.get(name.removeprefix("pto_balance."))
        if name == "computed.tenure_days":
            return self.tenure_days()
        if name == "computed.notice_calendar_days":
            return self.notice_calendar_days()
        if name == "computed.notice_business_days":
            return self.notice_business_days()
        if name == "computed.claim_age_days":
            return self.claim_age_days()
        if name == "computed.days_since_eligibility":
            return self.days_since_eligibility()
        if name == "computed.overlaps_blackout":
            return self.overlaps_blackout()
        raise RuleError(f"unknown check.subject {name!r}")

    def resolve_fact_key(self, fact_key: str) -> str:
        """A literal key, or the one the employee's own balance row names (W8, C29)."""
        if not fact_key.startswith(FACT_KEY_INDIRECTION):
            return fact_key
        field = fact_key.split(".", 1)[1]
        resolved = self.balance.get(field)
        if not isinstance(resolved, str) or resolved not in self.facts:
            raise RuleError(f"fact_key {fact_key!r} resolves to {resolved!r}, which is not a fact")
        return resolved

    def computed(self) -> dict[str, Any]:
        """Every value the engine derived, for the answer to read instead of recomputing it.

        The reader's tenure in months is in here for the same reason (W8, C22): a turn that
        established tenure through the engine rather than through the profile tool had no envelope
        carrying it, and handed the reader "45 months of continuous service".
        """
        eligibility = self.eligibility_date()
        window = _numeric(self.facts.get("benefits.new_hire.election_window_days", {}).get("value"))
        values: dict[str, Any] = {
            "as_of": self.as_of.isoformat(),
            "submitted_on": self.submitted_on.isoformat(),
            # The two dates the request itself carries, echoed so an answer — and the orchestrator's
            # own deterministic confirmation card (W8, C09) — can name the span the verdict scored
            # without parsing it back out of a reason string.
            "start_date": start.isoformat() if (start := _parse_date(self.parameters.get("start_date"))) else None,
            "end_date": end.isoformat() if (end := _parse_date(self.parameters.get("end_date"))) else None,
            "tenure_days": self.tenure_days(),
            "tenure_months_at_as_of": self.employee.get("tenure_months_at_as_of"),
            "notice_business_days": self.notice_business_days(),
            "notice_calendar_days": self.notice_calendar_days(),
            "duration_days": self.duration_days(),
            "claim_age_days": self.claim_age_days(),
            "overlaps_blackout": self.overlaps_blackout(),
            "span_end": end.isoformat() if (end := self.span_end()) else None,
            "benefits_eligibility_date": eligibility.isoformat() if eligibility else None,
            "benefits_election_deadline": (
                (eligibility + timedelta(days=int(window))).isoformat() if eligibility and window else None
            ),
        }
        return {key: value for key, value in values.items() if value is not None}

    def fact(self, key: str) -> Any:
        if key not in self.facts:
            raise RuleError(f"unknown fact_key {key!r}")
        return self.facts[key]["value"]


# --------------------------------------------------------------------------------------
# Operators and guards
# --------------------------------------------------------------------------------------


def _literal(text: str) -> Any:
    lowered = text.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _compare_value(check: Mapping[str, Any], fact_key: str, context: Context) -> Any:
    compare_to = str(check.get("compare_to", "fact"))
    if compare_to == "fact":
        return context.fact(fact_key)
    if compare_to.startswith("parameters."):
        return context.parameters.get(compare_to.removeprefix("parameters."))
    if compare_to.startswith("literal:"):
        return _literal(compare_to.removeprefix("literal:"))
    raise RuleError(f"unknown check.compare_to {compare_to!r}")


def _render(value: Any) -> str:
    """A value as it should read in a `reason` string.

    The tool's `parameters` are typed `string | number | boolean` (§8.4), so an integer arrives as a
    float: "42 days" must not be narrated as "42.0 days".
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return None


def _apply(operator: str, subject: Any, expected: Any) -> bool:
    if operator == "in":
        members = [item.strip() for item in str(expected).split(",")]
        return str(subject) in members
    if operator in ("date_lte", "date_gte"):
        left, right = _parse_date(subject), _parse_date(expected)
        if left is None or right is None:
            raise RuleError(f"{operator} needs two ISO-8601 dates, got {subject!r} and {expected!r}")
        return left <= right if operator == "date_lte" else left >= right
    if operator == "eq":
        return subject == expected
    left_number, right_number = _numeric(subject), _numeric(expected)
    if left_number is None or right_number is None:
        raise RuleError(f"{operator} needs two numbers, got {subject!r} and {expected!r}")
    return {
        "lte": left_number <= right_number,
        "lt": left_number < right_number,
        "gte": left_number >= right_number,
        "gt": left_number > right_number,
    }[operator]


def guard_holds(guard: Any, context: Context, decided: Mapping[str, bool], known: frozenset[str]) -> bool:
    """`applies_when` — the closed vocabulary of the `rules.yml` header.

    `unmet:`/`met:` read requirements already decided in file order, which is why the file lists a
    dependent requirement after the one it depends on. A requirement that *did not apply* is neither
    met nor unmet, so both forms are false for it — the Tax & Legal approval does not attach itself
    to a request whose duration was never in question. A guard naming an id the scenario does not
    contain at all is a typo, and raises.
    """
    if guard is None or guard == "always":
        return True
    if not isinstance(guard, str) or not guard.startswith(GUARD_PREFIXES):
        raise RuleError(f"unknown applies_when {guard!r}")
    kind, _, rest = guard.partition(":")
    if kind in ("unmet", "met"):
        if rest not in known:
            raise RuleError(f"applies_when {guard!r} names a requirement this scenario does not carry")
        if rest not in decided:
            return False
        return decided[rest] if kind == "met" else not decided[rest]
    if kind == "employee_eq":
        field, _, expected = rest.partition(":")
        return str(context.employee.get(field)) == expected
    name, _, expected = rest.partition(":")
    value = context.parameters.get(name)
    if kind == "parameter_eq":
        return str(value) == expected
    threshold = _numeric(context.fact(expected))
    number = _numeric(value)
    return number is not None and threshold is not None and number >= threshold


# --------------------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """One evaluated requirement, in the §8.4 output shape plus the three fields the verdict needs."""

    entry: dict[str, Any]
    met: bool
    evaluable: bool
    blocking: bool
    #: Whether the requirement was decided by comparing real data (W8, C05). A `manual` row is
    #: not, and a scenario made only of `manual` rows has evaluated nothing.
    data_backed: bool = True

    @property
    def status(self) -> str:
        return str(self.entry["status"])


def _entry(requirement: Mapping[str, Any], fact_key: str, evidence: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "id": str(requirement["id"]),
        "text": str(requirement["text"]),
        # The reader label (W8 fix round): what the measured thing is called in front of a person.
        # `agent/compliance.py` builds its restatement from this and never from the subject key.
        "label": str(requirement.get("label") or ""),
        "met": False,
        "status": "not_stated",
        "reason": "",
        "fact_key": fact_key,
        "evidence": evidence,
    }


def _settle(entry: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    """One place writes the pair, so `met` can never disagree with `status` (W8, C05)."""
    entry["status"] = status
    entry["met"] = status == "met"
    entry["reason"] = reason
    return entry


def _evaluate_requirement(requirement: Mapping[str, Any], context: Context) -> Decision:
    check = requirement.get("check")
    fact_key = context.resolve_fact_key(str(requirement["fact_key"]))
    blocking = bool(requirement.get("blocking", False))
    evidence = resolve_evidence(str(requirement["doc_id"]), str(requirement["heading_path"]), context.connection)
    entry = _entry(requirement, fact_key, evidence)
    if check is None:
        raise RuleError(f"requirement {requirement['id']!r} carries no check")
    operator = str(check.get("operator"))
    if operator not in OPERATORS:
        raise RuleError(f"unknown check.operator {operator!r}")
    subject_name = str(check.get("subject"))
    if not (subject_name.startswith(SUBJECT_PREFIXES) or subject_name in COMPUTED_SUBJECTS + BALANCE_SUBJECTS):
        raise RuleError(f"unknown check.subject {subject_name!r}")

    if operator == "informational":
        reason = f"Standing rule; {context.fact(fact_key)!r} applies whatever the request says."
        return Decision(entry=_settle(entry, "met", reason), met=True, evaluable=True, blocking=blocking)
    if operator == "manual":
        reason = "Not verifiable from the synthetic record; confirm before proceeding."
        return Decision(
            entry=_settle(entry, "not_stated", reason),
            met=False,
            evaluable=True,
            blocking=False,
            data_backed=False,
        )

    if subject_name in SNAPSHOT_SUBJECTS and context.submitted_on < context.as_of:
        # The record is dated later than the request that would be judged against it, so this row
        # is not a verdict anybody can stand behind (W8, C04).
        reason = (
            f"Not verifiable: the record snapshot is {context.as_of.isoformat()} and the request "
            f"was submitted {context.submitted_on.isoformat()}."
        )
        return Decision(entry=_settle(entry, "not_stated", reason), met=False, evaluable=False, blocking=blocking)

    subject = context.subject(subject_name)
    if subject is None:
        reason = f"Not stated: {subject_name} was not supplied."
        return Decision(entry=_settle(entry, "not_stated", reason), met=False, evaluable=False, blocking=blocking)
    expected = _compare_value(check, fact_key, context)
    if expected is None:
        reason = f"Not stated: {check.get('compare_to')} was not supplied."
        return Decision(entry=_settle(entry, "not_stated", reason), met=False, evaluable=False, blocking=blocking)
    met = _apply(operator, subject, expected)
    # Whose number the comparison value is (UX W9, npo5-02): a `compare_to: parameters.<name>` is
    # the READER'S request, and the answer may not attribute it to the policy — "the policy asks
    # for at least 3" was said of a figure the reader chose.
    source = "request" if str(check.get("compare_to") or "fact").startswith("parameters.") else "policy"
    reason = f"{subject_name} is {_render(subject)}; the {source} value is {_render(expected)} ({operator})."
    return Decision(entry=_settle(entry, "met" if met else "unmet", reason), met=met, evaluable=True, blocking=blocking)


def _settle_manual(decisions: Sequence[Decision]) -> list[Decision]:
    """A `manual` row is evaluable only beside a data-backed one (W8, C05).

    Without this, a call that supplied no parameter at all still evaluated *something* — the
    "confirm before proceeding" row — so `insufficient_evidence` was unreachable and a turn that
    had checked nothing came back `conditional`.
    """
    grounded = any(decision.data_backed and decision.evaluable for decision in decisions)
    return [
        decision if decision.data_backed or grounded else replace(decision, evaluable=False) for decision in decisions
    ]


def _verdict(decisions: Sequence[Decision]) -> str:
    if not decisions or not any(decision.evaluable for decision in decisions):
        return "insufficient_evidence"
    if any(decision.blocking and decision.evaluable and not decision.met for decision in decisions):
        return "non_compliant"
    if any(not decision.met for decision in decisions):
        return "conditional"
    return "compliant"


def derive_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """The caller's parameters plus what the two dates imply (W8, C05).

    `duration_days` is derived from `start_date` and `end_date` rather than taken on trust, because
    a model that supplied neither got a requirement reported as "Not stated" and an answer that
    asserted a duration anyway. An `end_date` before its `start_date` is an **argument error**: it
    is not a request the engine can score, and the live Berlin turn that sent one was answered with
    a confident conclusion built on rows that had evaluated nothing.
    """
    derived = dict(parameters)
    start, end = _parse_date(derived.get("start_date")), _parse_date(derived.get("end_date"))
    if start is not None and end is not None:
        if end < start:
            raise RuleError(
                f"end_date {end.isoformat()} is before start_date {start.isoformat()}; send the dates in order"
            )
        derived.setdefault("duration_days", (end - start).days + 1)
    return derived


def evaluate(
    scenario: str,
    *,
    employee: Mapping[str, Any],
    balance: Mapping[str, Any],
    parameters: Mapping[str, Any],
    holidays: Sequence[str],
    as_of: str,
    submitted_on: str,
    rule_set: RuleSet,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Run one scenario and return the §8.4 tool-4 output body. A pure function of its arguments."""
    if scenario not in rule_set.scenarios:
        raise RuleError(f"unknown scenario {scenario!r}")
    spec = rule_set.scenarios[scenario]
    snapshot = _parse_date(as_of)
    if snapshot is None:
        raise RuleError(f"unparseable as_of {as_of!r}")
    submitted = _parse_date(submitted_on)
    if submitted is None:
        raise RuleError(f"unparseable submitted_on {submitted_on!r}")
    context = Context(
        as_of=snapshot,
        submitted_on=submitted,
        employee=dict(employee),
        balance=dict(balance),
        parameters=derive_parameters(parameters),
        holidays=frozenset(parsed for parsed in (_parse_date(day) for day in holidays) if parsed),
        facts=rule_set.facts,
        connection=connection,
    )

    known = frozenset(str(requirement["id"]) for requirement in spec["requirements"])
    decided: dict[str, bool] = {}
    decisions: list[Decision] = []
    for requirement in spec["requirements"]:
        if not guard_holds(requirement.get("applies_when"), context, decided, known):
            continue
        decision = _evaluate_requirement(requirement, context)
        decided[decision.entry["id"]] = decision.met
        decisions.append(decision)
    decisions = _settle_manual(decisions)

    approvals = [
        {key: value for key, value in approval.items() if key != "applies_when"}
        for approval in spec["approvals_required"]
        if guard_holds(approval.get("applies_when"), context, decided, known)
    ]
    next_steps = [
        str(step["text"])
        for step in spec["next_steps"]
        if guard_holds(step.get("applies_when"), context, decided, known)
    ]

    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for decision in decisions:
        evidence = decision.entry["evidence"]
        if evidence and evidence["chunk_id"] not in seen:
            seen.add(evidence["chunk_id"])
            citations.append({key: evidence[key] for key in ("chunk_id", "doc_id", "heading_path")})
    for approval in approvals:
        evidence = resolve_evidence(str(approval["doc_id"]), str(approval["heading_path"]), connection)
        if evidence and evidence["chunk_id"] not in seen:
            seen.add(evidence["chunk_id"])
            citations.append({key: evidence[key] for key in ("chunk_id", "doc_id", "heading_path")})

    return {
        "scenario": scenario,
        "verdict": _verdict(decisions),
        "as_of": as_of,
        "submitted_on": submitted.isoformat(),
        "computed": context.computed(),
        "requirements": [decision.entry for decision in decisions],
        # The rows that were checked and failed — never a `not_stated` one, which is the exact
        # conflation `status` exists to end (W8, C05; the list itself caught up in the fix round).
        "unmet": [decision.entry["id"] for decision in decisions if decision.entry.get("status") == "unmet"],
        "approvals_required": approvals,
        "next_steps": next_steps,
        "escalate_to": str(spec["escalate_to"]),
        "citations": citations,
        "rules_version": rule_set.rules_version,
    }
