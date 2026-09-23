"""The deterministic rule engine (spec §8.4 tool 4, R5.2).

Three assertions carry the weight, and the spec names all three:

* **every emitted `evidence.chunk_id` resolves in the committed index** — a stale id would be
  stripped silently by guardrail G2, leaving a requirement that looks cited and is not;
* **every `fact_key` exists in `corpus/facts.yml`** — the rules, the corpus and the evaluation gold
  answers all cite fact ids rather than prose, so a moved number fails here rather than contradicting
  a gold answer;
* **each of the seven scenarios has a fixture input producing a non-`insufficient_evidence` verdict**
  — otherwise five advertised scenarios could ship unbacked.

Everything else here pins the closed vocabulary of `corpus/rules.yml`'s header, which is the engine's
whole grammar: a construct outside it raises rather than degrading into a silently ignored rule.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
import yaml
from mcp import Client

from hrmosaic.core import corpusread
from hrmosaic.mcpserver import rules
from hrmosaic.mcpserver.server import DEFAULT_ACTOR, ServerDeps, build_hr_server

pytestmark = pytest.mark.anyio

DEPS = ServerDeps()
RULE_SET = rules.load_rules(DEPS.rules_path, DEPS.facts_path)
FACTS = yaml.safe_load(DEPS.facts_path.read_text(encoding="utf-8"))["facts"]

REQUIREMENTS = [
    (scenario, requirement)
    for scenario, spec in sorted(RULE_SET.scenarios.items())
    for requirement in spec["requirements"]
]
REQUIREMENT_IDS = [f"{scenario}.{requirement['id']}" for scenario, requirement in REQUIREMENTS]

#: One input per scenario that reaches a real verdict. Deliberately hand-written rather than
#: generated: the point is that a human can state a plausible request for each of the seven.
FIXTURES: dict[str, dict[str, object]] = {
    "international_remote": {
        "destination_country": "DE",
        "duration_days": 42,
        "start_date": "2026-10-05",
        "device_is_company_managed": True,
        "activity_is_customer_facing": False,
    },
    "domestic_remote": {
        "duration_days": 6,
        "onsite_days_per_week": 3,
        "network_is_company_controlled": True,
    },
    "pto_request": {
        "start_date": "2026-09-15",
        "end_date": "2026-09-17",
        "days": 3,
        "manager_approval_recorded": True,
    },
    "expense_claim": {
        "amount_usd": 1200,
        "category": "travel",
        "transaction_date": "2026-08-20",
        "has_itemised_receipt": True,
    },
    "equipment_request": {"amount_usd": 320, "request_type": "new"},
    "benefits_change": {"reason": "open_enrollment", "effective_date": "2026-11-10"},
    "conduct_escalation": {"reported": True, "severity": "1", "handled_by_named_partner": True},
}


async def compliance(scenario: str, parameters: dict, employee_id: str = DEFAULT_ACTOR) -> dict:
    async with Client(build_hr_server()) as client:
        result = await client.call_tool(
            "check_policy_compliance",
            {"scenario": scenario, "employee_id": employee_id, "parameters": parameters},
        )
    body = json.loads(result.content[0].text)
    assert result.structured_content == body
    return body


# -- the three named assertions --------------------------------------------------------


@pytest.mark.parametrize(("scenario", "requirement"), REQUIREMENTS, ids=REQUIREMENT_IDS)
def test_every_fact_key_exists(scenario, requirement):
    """A literal key resolves in `facts.yml`; an indirect one resolves through every balance row.

    `pto_balance.accrual_fact_key` names the field of the employee's own row that holds the real
    key, so the accrual band the decisive PTO requirement quotes is the reader's own (W8, C29).
    """
    fact_key = requirement["fact_key"]
    if fact_key.startswith("pto_balance."):
        field = fact_key.removeprefix("pto_balance.")
        resolved = {row[field] for row in DEPS.records("pto_balances")}
        assert resolved, f"{scenario}: no balance row carries {field!r}"
        assert resolved <= set(FACTS), f"{scenario}: {sorted(resolved - set(FACTS))} are not facts"
        return
    assert fact_key in FACTS, scenario


@pytest.mark.parametrize("row", DEPS.records("pto_balances"), ids=lambda row: row["employee_id"])
def test_the_balance_requirement_quotes_each_employees_own_accrual_band(row):
    """W8, C29: the band on `pto.request.balance` is the one that employee actually accrues at."""
    requirement = next(
        item for item in RULE_SET.scenarios["pto_request"]["requirements"] if item["id"] == "pto.request.balance"
    )
    context = rules.Context(
        as_of=date(2026, 9, 1),
        submitted_on=date(2026, 9, 1),
        employee={},
        balance=dict(row),
        parameters={},
        holidays=frozenset(),
        facts=FACTS,
    )
    assert context.resolve_fact_key(requirement["fact_key"]) == row["accrual_fact_key"]


@pytest.mark.parametrize(("scenario", "requirement"), REQUIREMENTS, ids=REQUIREMENT_IDS)
def test_every_requirement_anchor_resolves_to_a_real_chunk(scenario, requirement):
    evidence = rules.resolve_evidence(requirement["doc_id"], requirement["heading_path"])
    assert evidence is not None, f"{scenario}: {requirement['doc_id']} has no {requirement['heading_path']!r}"
    assert corpusread.get_chunk(evidence["chunk_id"]) is not None
    assert evidence["snippet"].strip()


@pytest.mark.parametrize("scenario", sorted(FIXTURES), ids=sorted(FIXTURES))
async def test_every_scenario_reaches_a_real_verdict(scenario):
    body = await compliance(scenario, FIXTURES[scenario])
    assert body["verdict"] in rules.VERDICTS
    assert body["verdict"] != "insufficient_evidence", scenario
    assert body["requirements"], scenario
    assert body["rules_version"] == RULE_SET.rules_version
    assert body["as_of"] == DEPS.as_of()
    assert body["escalate_to"]
    for requirement in body["requirements"]:
        assert corpusread.get_chunk(requirement["evidence"]["chunk_id"]) is not None, requirement["id"]
    for citation in body["citations"]:
        assert corpusread.get_chunk(citation["chunk_id"]) is not None


# -- the closed vocabulary -------------------------------------------------------------


@pytest.mark.parametrize(("scenario", "requirement"), REQUIREMENTS, ids=REQUIREMENT_IDS)
def test_every_requirement_stays_inside_the_closed_grammar(scenario, requirement):
    check = requirement["check"]
    assert set(check) <= {"subject", "operator", "compare_to"}, scenario
    assert check["operator"] in rules.OPERATORS, scenario
    subject = check["subject"]
    known = subject.startswith(rules.SUBJECT_PREFIXES) or subject in (rules.COMPUTED_SUBJECTS + rules.BALANCE_SUBJECTS)
    assert known, f"{scenario}: unknown subject {subject!r}"
    compare_to = check.get("compare_to", "fact")
    assert compare_to == "fact" or compare_to.startswith(("parameters.", "literal:")), scenario
    guard = requirement.get("applies_when", "always")
    assert guard == "always" or guard.startswith(rules.GUARD_PREFIXES), scenario


def test_an_unknown_operator_stops_the_build_rather_than_being_ignored():
    context = rules.Context(
        as_of=date(2026, 9, 1),
        submitted_on=date(2026, 9, 1),
        employee={},
        balance={},
        parameters={},
        holidays=frozenset(),
        facts=FACTS,
    )
    with pytest.raises(rules.RuleError):
        rules.guard_holds("whenever:something", context, {}, frozenset())
    with pytest.raises(rules.RuleError):
        context.subject("nonsense.field")


# -- the verdict rules -----------------------------------------------------------------


async def test_the_worked_example_of_the_spec():
    """42 days in Berlin: over the 30-day threshold, so Tax & Legal is pulled in (§8.4)."""
    body = await compliance("international_remote", FIXTURES["international_remote"])
    assert body["verdict"] == "conditional"
    assert "remote.intl.duration" in body["unmet"]
    assert "Tax & Legal" in {approval["role"] for approval in body["approvals_required"]}
    duration = next(item for item in body["requirements"] if item["id"] == "remote.intl.duration")
    assert duration["met"] is False
    assert "42" in duration["reason"], "the reason narrates the request, not a float"


async def test_a_short_stay_does_not_pull_in_tax_and_legal():
    """The selection logic is the point: a 12-day stay must not summon the 30-day approvals."""
    body = await compliance(
        "international_remote",
        {**FIXTURES["international_remote"], "duration_days": 12, "start_date": "2026-11-02"},
    )
    assert "remote.intl.duration" not in body["unmet"]
    assert "Tax & Legal" not in {approval["role"] for approval in body["approvals_required"]}
    assert not any(item["id"] == "remote.intl.tax_review_lead" for item in body["requirements"])


async def test_an_unapproved_destination_is_reported_against_the_facts_list():
    body = await compliance("international_remote", {**FIXTURES["international_remote"], "destination_country": "JP"})
    destination = next(item for item in body["requirements"] if item["id"] == "remote.intl.destination")
    assert destination["met"] is False
    assert FACTS["tax.approved_countries"]["value"] in destination["reason"]


async def test_a_blocking_requirement_makes_the_verdict_non_compliant():
    body = await compliance("pto_request", {**FIXTURES["pto_request"], "days": 40})
    assert "pto.request.balance" in body["unmet"]
    assert body["verdict"] == "non_compliant"


async def test_a_fully_satisfied_scenario_is_compliant():
    """The bottom rung of the ladder, which nothing else asserted.

    `domestic_remote` is the one scenario with no `manual` requirement, so it is the only one that
    can reach `compliant` at all; every other scenario carries something a synthetic record cannot
    verify. With all three subjects supplied and met the verdict is `compliant`, `unmet[]` is empty,
    and the `applies_when` guards leave only the `always` approval and the `always` next step.
    """
    body = await compliance("domestic_remote", FIXTURES["domestic_remote"])
    assert body["verdict"] == "compliant"
    assert body["unmet"] == []
    assert all(item["met"] for item in body["requirements"])
    assert [approval["role"] for approval in body["approvals_required"]] == ["Direct manager"]
    assert len(body["next_steps"]) == 1, "an unmet-guarded next step must not ride along on a clean verdict"


async def test_an_absent_subject_is_not_stated_and_cannot_prove_non_compliance():
    """The one adopted verdict rule nothing else in the suite pinned.

    `corpus/rules.yml`'s header states it: a requirement whose subject is **absent** is `met: false`
    with a `"Not stated: …"` reason and lands in `unmet[]`, but is *not evaluable*, so it cannot
    make the verdict `non_compliant`. `test_no_parameters_at_all_is_insufficient_evidence` does not
    reach it — with nothing evaluable the first rung of the ladder answers first. This is the mixed
    case, the only one that separates the two: one requirement evaluable and met, and a `blocking`
    requirement whose subject was never supplied.

    Without the `evaluable` guard in `rules._verdict`'s `non_compliant` clause, a caller who simply
    omits `amount_usd` would be told the claim violates the VP approval limit.
    """
    body = await compliance("expense_claim", {"transaction_date": "2026-08-20"})
    vp_limit = next(item for item in body["requirements"] if item["id"] == "expense.vp_limit")
    assert next(r for r in RULE_SET.scenarios["expense_claim"]["requirements"] if r["id"] == "expense.vp_limit")[
        "blocking"
    ], "the fixture only bites while expense.vp_limit is blocking"
    assert vp_limit["met"] is False
    assert vp_limit["status"] == "not_stated"
    assert vp_limit["reason"].startswith("Not stated:")
    # Not in `unmet[]` either: that list is the rows that were checked and failed (W8 fix round).
    assert "expense.vp_limit" not in body["unmet"]
    window = next(item for item in body["requirements"] if item["id"] == "expense.submission_window")
    assert window["met"] is True, "something must be evaluable, or the verdict is insufficient_evidence"
    assert body["verdict"] == "conditional", "an absent subject cannot prove a violation"


async def test_notice_days_are_computed_and_a_supplied_value_is_ignored():
    """§8.4: the engine computes notice itself, so a verdict cannot swing on a model's guess."""
    honest = await compliance("pto_request", {**FIXTURES["pto_request"], "start_date": "2026-09-02"})
    lying = await compliance(
        "pto_request",
        {**FIXTURES["pto_request"], "start_date": "2026-09-02", "notice_business_days": 99},
    )
    notice = next(item for item in honest["requirements"] if item["id"] == "pto.request.notice")
    assert notice["met"] is False, "one day is not five business days of notice"
    assert honest["requirements"] == lying["requirements"]


async def test_business_days_skip_weekends_and_company_holidays():
    # 2026-09-07 is Labor Day on the us-2026 calendar, so the week to 2026-09-15 holds seven
    # business days, not eight.
    holidays = frozenset({date(2026, 9, 7)})
    assert rules.business_days_between(date(2026, 9, 1), date(2026, 9, 15), holidays) == 8
    assert rules.business_days_between(date(2026, 9, 1), date(2026, 9, 15), frozenset()) == 9
    assert rules.business_days_between(date(2026, 9, 15), date(2026, 9, 1), frozenset()) == 0


async def test_a_manual_requirement_is_unmet_but_never_blocking():
    body = await compliance("conduct_escalation", FIXTURES["conduct_escalation"])
    manual = next(item for item in body["requirements"] if item["id"] == "conduct.not_automated")
    assert manual["met"] is False
    assert "confirm" in manual["reason"].lower()
    assert body["verdict"] == "conditional", "an unverifiable requirement cannot prove non-compliance"


async def test_an_informational_requirement_is_met_and_cited():
    body = await compliance("conduct_escalation", FIXTURES["conduct_escalation"])
    standing = next(item for item in body["requirements"] if item["id"] == "conduct.retaliation_protection")
    assert standing["met"] is True
    assert standing["id"] not in body["unmet"]
    assert standing["evidence"]["chunk_id"]


async def test_no_parameters_at_all_is_insufficient_evidence():
    body = await compliance("expense_claim", {})
    assert body["verdict"] == "insufficient_evidence"


async def test_manual_and_informational_need_no_parameter_to_be_evaluable():
    """§8.4: neither needs a supplied subject to keep a scenario off `insufficient_evidence`.

    The same empty `parameters` that leaves `expense_claim` with nothing evaluable (the test above)
    still produces a real verdict for `conduct_escalation`, whose four requirements are one `manual`
    and three `informational`. That is the whole difference between "unmet" and "not evaluable", and
    it is the rung `conduct.not_automated` — `blocking: true` in the data — would otherwise reach.
    """
    body = await compliance("conduct_escalation", {})
    assert [item["id"] for item in body["requirements"]] == [
        "conduct.not_automated",
        "conduct.acknowledgement",
        "conduct.severity_response",
        "conduct.retaliation_protection",
    ]
    # A `manual` row is `not_stated`, and `unmet[]` lists only rows that were checked and failed.
    assert body["unmet"] == []
    assert body["verdict"] == "conditional"


def test_a_manual_requirement_alone_is_insufficient_evidence_not_a_verdict():
    """W8, C05: "confirm this yourself" is not something the engine evaluated.

    No scenario in `corpus/rules.yml` is manual-only, so the rule set is narrowed to the one
    `manual` requirement — `blocking: true` in the data — and run with no parameters at all. It
    used to come back `conditional`, which reads as a decision: the engine had checked the request
    and found one open item. Nothing had been checked. `manual` is evaluable only beside a
    data-backed row; alone it is `insufficient_evidence`, and the `blocking` flag is still never
    honoured for it.
    """
    spec = dict(RULE_SET.scenarios["conduct_escalation"])
    spec["requirements"] = [item for item in spec["requirements"] if item["id"] == "conduct.not_automated"]
    assert spec["requirements"][0]["blocking"] is True
    assert spec["requirements"][0]["check"]["operator"] == "manual"

    body = rules.evaluate(
        "conduct_escalation",
        employee={},
        balance={},
        parameters={},
        holidays=(),
        as_of="2026-09-01",
        submitted_on="2026-09-01",
        rule_set=rules.RuleSet(
            rules_version=RULE_SET.rules_version, scenarios={"conduct_escalation": spec}, facts=RULE_SET.facts
        ),
    )
    # A `manual` row is `not_stated`, and `unmet[]` lists only rows that were checked and failed.
    assert body["unmet"] == []
    assert body["requirements"][0]["status"] == "not_stated"
    assert body["verdict"] == "insufficient_evidence"


async def test_an_unknown_employee_is_a_successful_not_found():
    body = await compliance("pto_request", FIXTURES["pto_request"], employee_id="E1999")
    assert body["code"] == "EMPLOYEE_NOT_FOUND"


# -- the closed vocabulary, at the edges -----------------------------------------------
#
# Everything above drives the seven shipped scenarios. The block below drives the engine's
# *refusals* and its "not stated" paths, which `corpus/rules.yml` deliberately never exercises: the
# committed rule set is well-formed, so the only way to assert that a malformed construct stops the
# build — rather than degrading into a silently ignored rule, or worse a falsely `compliant`
# verdict — is to hand the engine a one-requirement scenario of the test's own making (P20).

#: A real `(doc_id, heading_path)` pair, so a synthesised requirement still resolves real evidence
#: and these tests exercise the same `resolve_evidence` path the shipped rules take.
ANCHOR = {"doc_id": "tax-and-location-addendum", "heading_path": "Approved Countries"}


def one_requirement(check: object | None, **overrides) -> rules.RuleSet:
    """A rule set carrying exactly one requirement — the isolating harness for the block below."""
    requirement = {"id": "probe", "text": "A probe requirement.", "fact_key": "tax.approved_countries"}
    requirement.update(ANCHOR)
    if check is not None:
        requirement["check"] = check
    requirement.update(overrides)
    return rules.RuleSet(
        rules_version=RULE_SET.rules_version,
        scenarios={
            "probe_scenario": {
                "requirements": [requirement],
                "approvals_required": [],
                "next_steps": [],
                "escalate_to": "People Operations — probe@mosaicrobotics.example",
            }
        },
        facts=RULE_SET.facts,
    )


def run_probe(rule_set: rules.RuleSet, parameters: dict | None = None, **overrides) -> dict:
    arguments = {
        "employee": {},
        "balance": {},
        "parameters": parameters or {},
        "holidays": (),
        "as_of": "2026-09-01",
        "submitted_on": "2026-09-01",
        "rule_set": rule_set,
    }
    arguments.update(overrides)
    return rules.evaluate("probe_scenario", **arguments)


def test_an_anchor_that_names_no_real_section_resolves_to_no_evidence():
    """A `heading_path` no chunk carries yields `evidence: null`, not a fabricated chunk id.

    G2 would strip a stale id silently, so the engine has to be able to say "nothing backs this".
    """
    assert rules.resolve_evidence("tax-and-location-addendum", "A Heading That Does Not Exist") is None


def test_a_date_yaml_already_parsed_is_used_as_it_stands():
    """`corpus/rules.yml` and a caller may both hand over a real `date`, not only an ISO string."""
    context = rules.Context(
        as_of=date(2026, 9, 1),
        submitted_on=date(2026, 9, 1),
        employee={"hire_date": date(2020, 9, 1)},
        balance={},
        parameters={},
        holidays=frozenset(),
        facts=FACTS,
    )
    assert context.tenure_days() == (date(2026, 9, 1) - date(2020, 9, 1)).days


def test_an_unparseable_date_is_not_stated_rather_than_a_crash_or_a_zero():
    """A date like `next tuesday` must not silently become "0 days of notice", and a verdict."""
    context = rules.Context(
        as_of=date(2026, 9, 1),
        submitted_on=date(2026, 9, 1),
        employee={"hire_date": "next tuesday"},
        balance={},
        parameters={"start_date": 20261005},
        holidays=frozenset(),
        facts=FACTS,
    )
    assert context.tenure_days() is None
    assert context.notice_calendar_days() is None
    assert context.notice_business_days() is None
    assert context.claim_age_days() is None


def test_a_request_with_no_dates_has_no_blackout_answer_at_all():
    """Absent `start_date`, "does this overlap a blackout" is unanswerable — not `False`."""
    context = rules.Context(
        as_of=date(2026, 9, 1),
        submitted_on=date(2026, 9, 1),
        employee={},
        balance={"blackout_dates": ["2026-09-02"]},
        parameters={},
        holidays=frozenset(),
        facts=FACTS,
    )
    assert context.overlaps_blackout() is None


def test_a_fact_key_that_does_not_resolve_stops_the_build():
    rule_set = one_requirement({"subject": "parameters.amount", "operator": "lte"}, fact_key="no.such.fact")
    with pytest.raises(rules.RuleError, match="unknown fact_key"):
        run_probe(rule_set, {"amount": 10})


def test_a_literal_compare_to_keeps_the_type_it_is_written_as():
    """`literal:30` compares as a number and `literal:DE` as a string — "30" > 9 is not a verdict."""
    numeric = one_requirement({"subject": "parameters.days", "operator": "lte", "compare_to": "literal:30"})
    assert run_probe(numeric, {"days": 42})["verdict"] == "conditional"
    assert run_probe(numeric, {"days": 9})["verdict"] == "compliant"

    fractional = one_requirement({"subject": "parameters.rate", "operator": "lte", "compare_to": "literal:1.5"})
    assert run_probe(fractional, {"rate": 1.4})["verdict"] == "compliant"
    assert run_probe(fractional, {"rate": 1.6})["verdict"] == "conditional"

    textual = one_requirement({"subject": "parameters.country", "operator": "eq", "compare_to": "literal:DE"})
    assert run_probe(textual, {"country": "DE"})["verdict"] == "compliant"
    assert run_probe(textual, {"country": "FR"})["verdict"] == "conditional"


def test_a_compare_to_outside_the_vocabulary_stops_the_build():
    rule_set = one_requirement({"subject": "parameters.days", "operator": "lte", "compare_to": "employee.level"})
    with pytest.raises(rules.RuleError, match="unknown check.compare_to"):
        run_probe(rule_set, {"days": 1})


def test_a_boolean_parameter_compares_as_a_number():
    """§8.4 types `parameters` as `string | number | boolean`, so `true` has to reach a comparison."""
    rule_set = one_requirement({"subject": "parameters.approved", "operator": "gte", "compare_to": "literal:1"})
    assert run_probe(rule_set, {"approved": True})["verdict"] == "compliant"
    assert run_probe(rule_set, {"approved": False})["verdict"] == "conditional"


def test_a_date_operator_against_something_that_is_not_a_date_stops_the_build():
    rule_set = one_requirement(
        {"subject": "parameters.effective_date", "operator": "date_lte", "compare_to": "literal:soon"}
    )
    with pytest.raises(rules.RuleError, match="needs two ISO-8601 dates"):
        run_probe(rule_set, {"effective_date": "2026-10-05"})


def test_a_numeric_operator_against_something_that_is_not_a_number_stops_the_build():
    rule_set = one_requirement({"subject": "parameters.days", "operator": "lte", "compare_to": "literal:thirty"})
    with pytest.raises(rules.RuleError, match="needs two numbers"):
        run_probe(rule_set, {"days": 42})


def test_a_guard_naming_a_requirement_the_scenario_does_not_carry_is_a_typo_not_a_pass():
    """`unmet:remote.intl.duraton` must fail loudly; silently false would drop a Tax & Legal step."""
    rule_set = one_requirement(
        {"subject": "parameters.days", "operator": "lte", "compare_to": "literal:30"},
        applies_when="unmet:probe.typo",
    )
    with pytest.raises(rules.RuleError, match="does not carry"):
        run_probe(rule_set, {"days": 42})


def test_a_requirement_with_no_check_stops_the_build():
    with pytest.raises(rules.RuleError, match="carries no check"):
        run_probe(one_requirement(None))


def test_a_requirement_operator_outside_the_vocabulary_stops_the_build():
    rule_set = one_requirement({"subject": "parameters.days", "operator": "approximately"})
    with pytest.raises(rules.RuleError, match="unknown check.operator"):
        run_probe(rule_set, {"days": 1})


def test_a_requirement_subject_outside_the_vocabulary_stops_the_build():
    rule_set = one_requirement({"subject": "computed.phase_of_the_moon", "operator": "lte"})
    with pytest.raises(rules.RuleError, match="unknown check.subject"):
        run_probe(rule_set, {"days": 1})


def test_a_compare_to_parameter_nobody_supplied_is_not_stated_rather_than_unmet():
    """Comparing against an absent parameter cannot prove non-compliance, even when blocking."""
    rule_set = one_requirement(
        {"subject": "parameters.days", "operator": "lte", "compare_to": "parameters.cap"},
        blocking=True,
    )
    body = run_probe(rule_set, {"days": 42})
    assert body["requirements"][0]["reason"].startswith("Not stated:")
    assert body["requirements"][0]["met"] is False
    assert body["verdict"] == "insufficient_evidence"


def test_an_unknown_scenario_is_refused():
    with pytest.raises(rules.RuleError, match="unknown scenario"):
        rules.evaluate(
            "teleportation_request",
            employee={},
            balance={},
            parameters={},
            holidays=(),
            as_of="2026-09-01",
            submitted_on="2026-09-01",
            rule_set=RULE_SET,
        )


def test_an_unparseable_as_of_is_refused_rather_than_defaulted_to_today():
    """Constraint 6: verdicts are computed against the snapshot, so a bad snapshot is fatal."""
    rule_set = one_requirement({"subject": "parameters.days", "operator": "lte", "compare_to": "literal:30"})
    with pytest.raises(rules.RuleError, match="unparseable as_of"):
        run_probe(rule_set, {"days": 1}, as_of="the first of September")


# -- W8: the submission date, the three statuses, the approval chain -------------------
#
# The four defects these pin were all live on 2026-09-15 (`demo-path-review-2026-09-15.md`):
# notice measured from a frozen snapshot, a requirement nobody evaluated narrated as a settled
# failure, a director told to get her own approval, and a new hire given the annual open-enrolment
# window as their election deadline.


def _pto(parameters: dict, *, submitted_on: str, employee_id: str = DEFAULT_ACTOR) -> dict:
    """One `pto_request` evaluation straight through the engine, at a stated submission date."""
    from hrmosaic.mcpserver.tools.check_pto_balance import balance_row

    employee = DEPS.employee(employee_id)
    assert employee is not None
    return rules.evaluate(
        "pto_request",
        employee=employee,
        balance=balance_row(DEPS, employee_id) or {},
        parameters=parameters,
        holidays=(),
        as_of=DEPS.as_of(),
        submitted_on=submitted_on,
        rule_set=RULE_SET,
        connection=DEPS.index(),
    )


def _row(body: dict, requirement_id: str) -> dict:
    return next(item for item in body["requirements"] if item["id"] == requirement_id)


def test_notice_is_measured_from_the_submission_date_not_the_snapshot():
    """C04. Every same-day PTO request in the demo scored eight business days of notice it had
    not given, because the engine measured from `as_of: 2026-09-01` rather than from the day the
    request was made."""
    same_day = _pto({"start_date": "2026-09-15", "days": 3}, submitted_on="2026-09-15")
    assert same_day["computed"]["notice_business_days"] == 0
    assert _row(same_day, "pto.request.notice")["status"] == "unmet"

    ahead = _pto({"start_date": "2026-09-15", "days": 3}, submitted_on="2026-09-01")
    assert ahead["computed"]["notice_business_days"] == 9
    assert _row(ahead, "pto.request.notice")["status"] == "met"


def test_the_blackout_span_is_walked_in_business_days():
    """C04. `days` counts business days, so three days from a Friday reaches the Tuesday — the
    calendar walk stopped on the Sunday and missed a blackout the request actually covers."""
    body = _pto({"start_date": "2026-12-18", "days": 3}, submitted_on="2026-11-01", employee_id="E1017")
    assert body["computed"]["span_end"] == "2026-12-22"
    assert body["computed"]["overlaps_blackout"] is True


def test_a_requirement_nobody_supplied_a_parameter_for_says_so():
    """C05. `met: false` meant both "checked and failed" and "never checked"; `status` separates
    them, so an answer can no longer narrate an unevaluated row as a settled failure."""
    body = _pto({"days": 3}, submitted_on="2026-09-10")
    notice = _row(body, "pto.request.notice")
    assert notice["status"] == "not_stated"
    assert notice["met"] is False
    assert "Not stated" in notice["reason"]
    assert {item["status"] for item in body["requirements"]} <= set(rules.STATUSES)


def test_duration_is_derived_from_the_two_dates():
    """C05. The Berlin turn asserted "27 consecutive calendar days" the engine never computed."""
    derived = rules.derive_parameters({"start_date": "2026-11-03", "end_date": "2026-12-14"})
    assert derived["duration_days"] == 42


def test_an_end_date_before_its_start_date_is_an_argument_error():
    """C05. The live year-end turn sent 15 December → 10 January and was answered anyway."""
    with pytest.raises(rules.RuleError, match="before start_date"):
        rules.derive_parameters({"start_date": "2026-12-15", "end_date": "2026-01-10"})


async def test_a_director_is_never_sent_to_her_own_director():
    """C06. E1007 Dana *is* the Director of Engineering; the matrix routes one level higher."""
    body = await compliance("international_remote", FIXTURES["international_remote"], employee_id="E1007")
    roles = {entry["role"]: entry for entry in body["approvers"]}
    assert [approval["role"] for approval in body["approvals_required"]] == [
        "Direct manager",
        "Director",
        "Tax & Legal",
    ]
    assert roles["Direct manager"]["name"] == "Miguel"
    director = roles["Director"]
    assert director["self_approval_routed"] is True
    assert director["name"] == "Miguel"
    assert "one level higher" in director["reason"]
    # A role that is a team and not a person stays a team rather than being guessed at.
    assert roles["Tax & Legal"].get("name") is None


async def test_an_engineer_is_given_her_managers_name():
    """C06. "your manager" on a turn whose own envelope already carried the name."""
    body = await compliance("pto_request", FIXTURES["pto_request"], employee_id="E1042")
    assert [entry["name"] for entry in body["approvers"] if entry["role"] == "Direct manager"] == ["Dana"]


async def test_a_new_hires_election_deadline_is_the_end_of_their_own_window():
    """C30. E1108 was given the annual open-enrollment window — three weeks early."""
    body = await compliance("benefits_change", {"reason": "new_hire"}, employee_id="E1108")
    assert body["computed"]["benefits_eligibility_date"] == "2026-11-13"
    assert body["computed"]["benefits_election_deadline"] == "2026-12-13"
    assert _row(body, "benefits.new_hire_window")["status"] == "met"


def test_the_unmet_list_never_carries_a_not_stated_row():
    """W7-review Minor: `unmet[]` listed every row with `met: false`, which is the exact conflation
    `status` exists to end — and it is published on the wire and rendered into EMPLOYEE CONTEXT."""
    body = _pto({"days": 3}, submitted_on="2026-09-10")

    not_stated = {row["id"] for row in body["requirements"] if row["status"] == "not_stated"}
    assert not_stated, "the fixture has rows nobody supplied a parameter for"
    assert not set(body["unmet"]) & not_stated
    assert set(body["unmet"]) == {row["id"] for row in body["requirements"] if row["status"] == "unmet"}


@pytest.mark.parametrize(("scenario", "requirement"), REQUIREMENTS, ids=REQUIREMENT_IDS)
def test_every_requirement_carries_a_reader_label(scenario, requirement):
    """W8 fix round, JX3-01: the chat surface's restatement is built from this and never from the
    subject key, so every one of the 34 rows has one, and none is a key in disguise."""
    label = requirement["label"]
    assert label.strip() and "_" not in label, scenario


def test_the_label_rides_on_the_wire_row():
    body = _pto({"start_date": "2026-09-15", "days": 3}, submitted_on="2026-09-01")
    notice = _row(body, "pto.request.notice")
    assert notice["label"] == "notice before the first day off, in business days"


# -- G5c, gaps 4 and 29: `unmet:` means checked-and-failed, never "could not check" ----
#
# `guard_holds` read `decided[id]` as a `met` boolean, so `unmet:<id>` meant `not met` — and a
# `not_stated` row carries `met: false` by construction. Every one of `corpus/rules.yml`'s 18
# `unmet:`-guarded approvals and next steps therefore fired on a requirement the engine had
# explicitly not been able to check. Two instances were reproduced in process on 2026-09-22: an
# `equipment_request` refresh with no `device_age_months` came back `insufficient_evidence` with an
# early-refresh manager approval and its next step attached, and an `international_remote` carrying
# only a destination reached **`conditional`** with Director and Tax & Legal attached and `unmet: []`
# — byte-identical to the 42-day run, and self-contradicting, because the published `unmet[]` list
# has been filtered on `status == "unmet"` since W8's fix round.
#
# `decided` now holds each row's **status**, and both guard forms are false for a `not_stated` row.
# The five cases below are the whole ladder of the one scenario where both forms appear.

EARLY_REFRESH_APPROVAL = "An early laptop refresh, before the 36-month anniversary, is a direct-manager decision."
EARLY_REFRESH_STEP = "Ask your direct manager to approve an early refresh"
DUE_REFRESH_STEP = "A refresh that falls due on the 36-month cycle needs no spending approval"


def _equipment(parameters: dict) -> dict:
    """One `equipment_request` evaluation straight through the engine, at the pinned snapshot."""
    employee = DEPS.employee(DEFAULT_ACTOR)
    assert employee is not None
    return rules.evaluate(
        "equipment_request",
        employee=employee,
        balance={},
        parameters=parameters,
        holidays=(),
        as_of=DEPS.as_of(),
        submitted_on=DEPS.as_of(),
        rule_set=RULE_SET,
        connection=DEPS.index(),
    )


def _roles(body: dict) -> list[str]:
    return [approval["role"] for approval in body["approvals_required"]]


def test_a_refresh_with_no_device_age_attaches_nothing_from_the_early_refresh_rows():
    """The reproduction from the 2026-09-21 grade card, rank 4: a verdict of `insufficient_evidence`
    that still told the reader to get a manager's approval for an early refresh, on a request whose
    device age nobody had supplied."""
    body = _equipment({"request_type": "refresh"})

    eligibility = _row(body, "equipment.refresh_eligibility")
    assert eligibility["status"] == "not_stated"
    assert body["verdict"] == "insufficient_evidence", "nothing was evaluable"
    assert body["unmet"] == []
    assert _roles(body) == [], "an approval cannot be derived from a row nobody could check"
    assert body["next_steps"] == []


def test_an_early_refresh_is_conditional_and_needs_the_direct_manager():
    """The `unmet:` branch itself, which the fix must leave working: 24 months is short of the
    36-month cycle, so the row was checked and failed and the approval is real."""
    body = _equipment({"request_type": "refresh", "device_age_months": 24})

    assert _row(body, "equipment.refresh_eligibility")["status"] == "unmet"
    assert body["verdict"] == "conditional"
    assert body["unmet"] == ["equipment.refresh_eligibility"]
    assert _roles(body) == ["Direct manager"]
    assert [approval["reason"] for approval in body["approvals_required"]] == [EARLY_REFRESH_APPROVAL]
    assert any(step.startswith(EARLY_REFRESH_STEP) for step in body["next_steps"]), body["next_steps"]


def test_a_refresh_that_falls_due_is_compliant_and_is_an_it_ticket_at_any_price():
    """The `met:` branch, and the corpus rule G5b's equipment fix wrote down: a scheduled refresh
    needs no spending approval whatever the replacement costs."""
    body = _equipment({"request_type": "refresh", "device_age_months": 36})

    assert _row(body, "equipment.refresh_eligibility")["status"] == "met"
    assert body["verdict"] == "compliant"
    assert _roles(body) == [], "no approver on a refresh that is simply due"
    assert [step.startswith(DUE_REFRESH_STEP) for step in body["next_steps"]] == [True]


def test_a_new_request_with_no_amount_does_not_summon_the_director():
    """The same class on the other guarded branch. `equipment.director_threshold` applies to
    `request_type: "new"`, and with no `amount_usd` it is `not_stated` — so the USD 500 director
    approval, and the off-catalogue next step that rides with it, must not attach."""
    body = _equipment({"request_type": "new"})

    assert _row(body, "equipment.director_threshold")["status"] == "not_stated"
    assert body["verdict"] == "insufficient_evidence"
    assert _roles(body) == ["Direct manager"], "the always-guarded approval stands; the unmet one does not"
    assert not any("15 business days" in step for step in body["next_steps"]), body["next_steps"]


def test_a_new_request_above_the_threshold_still_summons_the_director():
    """The other direction: USD 1,200 is above the USD 500 catalogue threshold, the row was checked
    and failed, and both tiers are attached."""
    body = _equipment({"request_type": "new", "amount_usd": 1200})

    assert _row(body, "equipment.director_threshold")["status"] == "unmet"
    assert body["verdict"] == "conditional"
    assert _roles(body) == ["Direct manager", "Director"]
    assert any("15 business days" in step for step in body["next_steps"]), body["next_steps"]


def test_an_international_stay_with_only_a_destination_attaches_no_tax_review():
    """Rank 29's half of the same defect, on the flagship demo scenario. With the duration never
    supplied, the 30-day branch is unreachable: no Director, no Tax & Legal, and no 21-day filing
    step — the answer the engine used to produce was byte-identical to the 42-day one."""
    body = rules.evaluate(
        "international_remote",
        employee=DEPS.employee(DEFAULT_ACTOR) or {},
        balance={},
        parameters={"destination_country": "PT"},
        holidays=(),
        as_of=DEPS.as_of(),
        submitted_on=DEPS.as_of(),
        rule_set=RULE_SET,
        connection=DEPS.index(),
    )

    assert _row(body, "remote.intl.duration")["status"] == "not_stated"
    assert body["unmet"] == []
    assert _roles(body) == ["Direct manager"]
    assert not any("Tax & Legal" in step for step in body["next_steps"]), body["next_steps"]
    assert not any(item["id"] == "remote.intl.tax_review_lead" for item in body["requirements"])


def test_the_guard_reads_a_status_and_a_not_stated_row_satisfies_neither_form():
    """The unit of the fix, at the function. Nothing else in the suite pinned `guard_holds` beyond
    its unknown-prefix refusal, which is what left this class unfrozen (rank 29)."""
    context = rules.Context(
        as_of=date(2026, 9, 1),
        submitted_on=date(2026, 9, 1),
        employee={},
        balance={},
        parameters={},
        holidays=frozenset(),
        facts=FACTS,
    )
    known = frozenset({"probe"})

    assert rules.guard_holds("unmet:probe", context, {"probe": "unmet"}, known) is True
    assert rules.guard_holds("met:probe", context, {"probe": "met"}, known) is True
    assert rules.guard_holds("unmet:probe", context, {"probe": "not_stated"}, known) is False
    assert rules.guard_holds("met:probe", context, {"probe": "not_stated"}, known) is False
    # A requirement that did not apply at all is decided by nothing, and both forms stay false.
    assert rules.guard_holds("unmet:probe", context, {}, known) is False
    assert rules.guard_holds("met:probe", context, {}, known) is False
