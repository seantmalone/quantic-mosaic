"""`check_policy_compliance` accepts a country *name* where the rules compare ISO codes (§8.4).

`corpus/rules.yml`'s `remote.intl.destination` compares `parameters.destination_country` with the
`in` operator against `corpus/facts.yml`'s `tax.approved_countries`, which is the code list
`DE,IE,NL,PT,ES,CA,MX`. Live recordings of demo task 1 showed `claude-haiku-4-5` reproducibly
sending `destination_country: "Germany"`, and a string comparison against a code list then reported
Berlin as **not** an approved destination — a wrong verdict produced by a spelling.

The normalisation is deliberately one-directional and small:

* the seven approved destinations are recognised by name, in the spellings the corpus itself uses;
* a bare two-letter code is upper-cased, so `"de"` is `"DE"`;
* **anything else passes through untouched** — an unrecognised name is not on the approved list
  under any spelling, so it must keep failing the check rather than being guessed at.

The last test pins the alias table to the corpus: add a country to `tax.approved_countries` without
teaching this table its name, and it fails here rather than silently in a verdict.
"""

from __future__ import annotations

import pytest

from hrmosaic.mcpserver import rules
from hrmosaic.mcpserver.server import ServerDeps
from hrmosaic.mcpserver.tools.check_policy_compliance import (
    APPROVED_COUNTRIES_FACT,
    COUNTRY_ALIASES,
    _compliance,
    normalise_country,
    normalise_parameters,
)

DEPS = ServerDeps()


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("Germany", "DE"),
        ("germany", "DE"),
        ("  Germany  ", "DE"),
        ("the Netherlands", "NL"),
        ("Netherlands", "NL"),
        ("de", "DE"),
        ("DE", "DE"),
        ("Mexico", "MX"),
    ],
)
def test_a_country_name_normalises_to_its_iso_code(supplied, expected):
    assert normalise_country(supplied) == expected


@pytest.mark.parametrize("supplied", ["France", "Ruritania", "Federal Republic of Germany", ""])
def test_an_unrecognised_country_passes_through_untouched(supplied):
    """Not on the approved list under any spelling — it must keep failing, not be guessed at."""
    assert normalise_country(supplied) == supplied


@pytest.mark.parametrize("supplied", [42, 3.5, True, None])
def test_a_non_string_is_left_alone(supplied):
    """`parameters` is `dict[str, str | float | bool]`; only the string half can carry a name."""
    assert normalise_country(supplied) is supplied


def test_only_the_country_parameter_is_touched():
    parameters = {
        "destination_country": "Germany",
        "start_date": "2026-11-03",
        "duration_days": 42,
        "category": "Germany",
    }
    assert normalise_parameters(parameters) == {
        "destination_country": "DE",
        "start_date": "2026-11-03",
        "duration_days": 42,
        "category": "Germany",
    }


def test_normalise_parameters_returns_a_new_mapping():
    parameters = {"destination_country": "Germany"}
    assert normalise_parameters(parameters) is not parameters
    assert parameters == {"destination_country": "Germany"}, "the caller's dict is not mutated"


def test_every_approved_country_code_has_a_name_the_table_recognises():
    """The alias table is pinned to `corpus/facts.yml` — a new approved country fails here first."""
    rule_set = rules.load_rules(DEPS.rules_path, DEPS.facts_path)
    approved = {code.strip() for code in str(rule_set.facts[APPROVED_COUNTRIES_FACT]["value"]).split(",")}
    assert approved, "the fact must still be a comma-separated code list"
    assert approved <= set(COUNTRY_ALIASES.values()), (
        f"no country name maps to {sorted(approved - set(COUNTRY_ALIASES.values()))}"
    )


#: §18.1's own call, in the two spellings — the documented one and the one the model actually sent.
DEMO_1_PARAMETERS = {"duration_days": 42, "start_date": "2026-11-03"}


@pytest.mark.parametrize("spelling", ["DE", "Germany"])
def test_the_engine_reaches_the_same_verdict_whichever_spelling_arrives(spelling):
    """The behavioural claim: Berlin is an approved destination however the caller writes it."""
    body = _compliance(
        DEPS,
        scenario="international_remote",
        employee_id="E1042",
        parameters={**DEMO_1_PARAMETERS, "destination_country": spelling},
    )
    destination = next(item for item in body["requirements"] if item["id"] == "remote.intl.destination")
    assert destination["met"] is True, destination["reason"]
    assert "DE" in destination["reason"], "the reason quotes the normalised code, not the raw name"
    assert body["verdict"] == "conditional", "42 days still exceeds the 30-day tax threshold (§18.1)"
