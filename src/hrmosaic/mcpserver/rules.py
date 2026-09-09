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

**Dates come from the snapshot, never the wall clock.** Notice days are computed by the engine from
`parameters.start_date` against the mock-data `as_of` snapshot and a caller-supplied
`notice_business_days` is ignored, exactly as §8.4 requires, so a verdict cannot swing on a model's
guess.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
)
#: `remaining_days` is an output of `check_pto_balance`, not a field of the employee profile: the two
#: would drift if the profile grew a copy (P2 report §9.2).
BALANCE_SUBJECTS = ("pto_balance.remaining_days",)

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
        return None if start is None else max(0, (start - self.as_of).days)

    def notice_business_days(self) -> int | None:
        start = _parse_date(self.parameters.get("start_date"))
        return None if start is None else business_days_between(self.as_of, start, self.holidays)

    def claim_age_days(self) -> int | None:
        transaction = _parse_date(self.parameters.get("transaction_date"))
        return None if transaction is None else max(0, (self.as_of - transaction).days)

    def overlaps_blackout(self) -> bool | None:
        """True when the requested span touches a blackout date on the employee's balance record."""
        start = _parse_date(self.parameters.get("start_date"))
        if start is None:
            return None
        end = _parse_date(self.parameters.get("end_date"))
        if end is None:
            days = self.parameters.get("days")
            span = int(days) if isinstance(days, int | float) else 1
            end = start + timedelta(days=max(span, 1) - 1)
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
        if name == "computed.overlaps_blackout":
            return self.overlaps_blackout()
        raise RuleError(f"unknown check.subject {name!r}")

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
    """One evaluated requirement, in the §8.4 output shape plus the two fields the verdict needs."""

    entry: dict[str, Any]
    met: bool
    evaluable: bool
    blocking: bool


def _evaluate_requirement(requirement: Mapping[str, Any], context: Context) -> Decision:
    check = requirement.get("check")
    fact_key = str(requirement["fact_key"])
    blocking = bool(requirement.get("blocking", False))
    evidence = resolve_evidence(str(requirement["doc_id"]), str(requirement["heading_path"]), context.connection)
    entry: dict[str, Any] = {
        "id": str(requirement["id"]),
        "text": str(requirement["text"]),
        "met": False,
        "reason": "",
        "fact_key": fact_key,
        "evidence": evidence,
    }
    if check is None:
        raise RuleError(f"requirement {requirement['id']!r} carries no check")
    operator = str(check.get("operator"))
    if operator not in OPERATORS:
        raise RuleError(f"unknown check.operator {operator!r}")
    subject_name = str(check.get("subject"))
    if not (subject_name.startswith(SUBJECT_PREFIXES) or subject_name in COMPUTED_SUBJECTS + BALANCE_SUBJECTS):
        raise RuleError(f"unknown check.subject {subject_name!r}")

    if operator == "informational":
        entry["met"] = True
        entry["reason"] = f"Standing rule; {context.fact(fact_key)!r} applies whatever the request says."
        return Decision(entry=entry, met=True, evaluable=True, blocking=blocking)
    if operator == "manual":
        entry["reason"] = "Not verifiable from the synthetic record; confirm before proceeding."
        return Decision(entry=entry, met=False, evaluable=True, blocking=False)

    subject = context.subject(subject_name)
    if subject is None:
        entry["reason"] = f"Not stated: {subject_name} was not supplied."
        return Decision(entry=entry, met=False, evaluable=False, blocking=blocking)
    expected = _compare_value(check, fact_key, context)
    if expected is None:
        entry["reason"] = f"Not stated: {check.get('compare_to')} was not supplied."
        return Decision(entry=entry, met=False, evaluable=False, blocking=blocking)
    met = _apply(operator, subject, expected)
    entry["met"] = met
    entry["reason"] = f"{subject_name} is {_render(subject)}; the policy value is {_render(expected)} ({operator})."
    return Decision(entry=entry, met=met, evaluable=True, blocking=blocking)


def _verdict(decisions: Sequence[Decision]) -> str:
    if not decisions or not any(decision.evaluable for decision in decisions):
        return "insufficient_evidence"
    if any(decision.blocking and decision.evaluable and not decision.met for decision in decisions):
        return "non_compliant"
    if any(not decision.met for decision in decisions):
        return "conditional"
    return "compliant"


def evaluate(
    scenario: str,
    *,
    employee: Mapping[str, Any],
    balance: Mapping[str, Any],
    parameters: Mapping[str, Any],
    holidays: Sequence[str],
    as_of: str,
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
    context = Context(
        as_of=snapshot,
        employee=dict(employee),
        balance=dict(balance),
        parameters=dict(parameters),
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
        "requirements": [decision.entry for decision in decisions],
        "unmet": [decision.entry["id"] for decision in decisions if not decision.met],
        "approvals_required": approvals,
        "next_steps": next_steps,
        "escalate_to": str(spec["escalate_to"]),
        "citations": citations,
        "rules_version": rule_set.rules_version,
    }
