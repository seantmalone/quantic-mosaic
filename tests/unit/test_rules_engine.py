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
    assert requirement["fact_key"] in FACTS, scenario


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
        as_of=date(2026, 9, 1), employee={}, balance={}, parameters={}, holidays=frozenset(), facts=FACTS
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


async def test_an_absent_subject_is_unmet_but_cannot_prove_non_compliance():
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
    assert vp_limit["reason"].startswith("Not stated:")
    assert "expense.vp_limit" in body["unmet"]
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
    assert body["unmet"] == ["conduct.not_automated"]
    assert body["verdict"] == "conditional"


def test_a_manual_requirement_alone_keeps_a_scenario_off_insufficient_evidence():
    """The isolating case for §8.4's "as an `informational` check is": `manual` on its own.

    No scenario in `corpus/rules.yml` is manual-only, so the rule set is narrowed to the one
    `manual` requirement — `blocking: true` in the data — and run with no parameters at all. If
    `manual` were treated as not evaluable, this would answer `insufficient_evidence`; if the
    `blocking` flag were honoured for it, `non_compliant`.
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
        rule_set=rules.RuleSet(
            rules_version=RULE_SET.rules_version, scenarios={"conduct_escalation": spec}, facts=RULE_SET.facts
        ),
    )
    assert body["unmet"] == ["conduct.not_automated"]
    assert body["verdict"] == "conditional"


async def test_an_unknown_employee_is_a_successful_not_found():
    body = await compliance("pto_request", FIXTURES["pto_request"], employee_id="E1999")
    assert body["code"] == "EMPLOYEE_NOT_FOUND"
