# P3 — Synthetic mock data — report

**Branch** `p3` in `/Users/sean/Projects/quantic-mosaic-wt/P3` · **HEAD** `43fb19c165bc133016e83a34f508a549709e4e57`
(branched from `54f514d`) · nothing pushed, `main` untouched, no `.env` read or written.

| Commit | Subject |
|---|---|
| `1eea727` | `P3(mockdata): six synthetic datasets carrying the 2026-09-01 snapshot` |
| `f8a64a8` | `P3(mockdata): record the snapshot facts a later phase must not rediscover` |
| `43fb19c` | `P3(mockdata): fix: drop an unused fixture argument from the id test` |

---

## What I built

**`scripts/gen_mock_data.py`** — the `seed=1729`, byte-idempotent generator, and the Pydantic
models that are the single definition of every dataset's shape. Everything that varies comes
from one `random.Random(1729)` drawn in a fixed order; everything a later phase quotes by hand
is pinned in a hand-authored 24-person roster. Every model sets `extra="forbid"`.

**The six datasets** (`mock_data/*.json`, 84 KB total, budget 300 KB), each carrying the §5.4
banner — `_synthetic` / `_notice` / `_generator` / `as_of: 2026-09-01` — then a `records` array:

| File | Records | Notes |
|---|---|---|
| `employees.json` | 24 | All §5.4 key fields plus `work_phone` (see *Ambiguities*, #3) |
| `pto_balances.json` | 24 | Accrual band, YTD accrual/use, carryover with an expiry, remaining, blackout dates |
| `benefits_elections.json` | 24 | Plan-year elections, dependants, waiting period, open-enrolment window |
| `org_manager_map.json` | 24 | `{employee_id, manager_id, skip_level_id, direct_reports[]}` |
| `offices.json` | 4 | `bos`, `atx`, `ber`, `remote-us` — all four §5.4 ids |
| `holidays_2026.json` | 2 | `us-2026` (11 holidays), `de-2026` (10) |

**The four anchors, exactly as specified.** 24 non-contiguous ids sampled from `E1001`–`E1199`
with `E1002` (Miguel Ferreira, VP Engineering), `E1007` (Dana Whitfield, Director, Engineering),
`E1042` (Priya Raghavan, Senior Robotics Engineer, Boston, hybrid, full-time, hired
**2022-11-13**, **45 months** tenured at the snapshot, manager `E1007`, skip-level `E1002`,
**13.5 days remaining** at 1.50 d/mo from nine 2026 postings) and `E1108` (Marcus Feldman, hired
**2026-08-15**, `waiting_period_ends` **2026-11-13**, `elections: []` — still waiting at the
snapshot). The 20 other ids came out as `E1003 E1014 E1017 E1043 E1047 E1050 E1057 E1077 E1078
E1096 E1110 E1122 E1132 E1133 E1138 E1145 E1162 E1172 E1175 E1192`.

**`scripts/gen_mock_schemas.py`** → `mock_data/schemas/*.schema.json`, one draft-2020-12 schema
per file describing banner *and* records, generated from the models, `additionalProperties:
false` throughout.

**`scripts/pii_check.py`** — two passes over every file in `mock_data/` (data, schemas and the
README): forbidden *field names* (national identifier, date of birth, address, personal contact)
in the JSON **and** in the generated schemas, so "no SSN field in any schema" is a shape
guarantee; and forbidden *text shapes* (SSN pattern, any address outside
`@mosaicrobotics.example`, any number outside `+1-555-01xx`). Exit 1 with one line per hit.
**Added to `ci.yml`'s `test` job** (one line, appended after `pytest -q` — see *Concerns*).

**`mock_data/README.md`** — the SYNTHETIC DATA banner and a full section on the `as_of`
convention: what it means, why every date-bearing tool reports it beside a real `computed_at`,
and why nothing computes against "today" (the clock is real; the *data* is frozen — so the
documented `13.5`, the gold answers and `test_mcp_tool_call.py` never rot). Plus the file table,
the anchor table, the PTO identity, the synthetic conventions and what is absent by design.

**Three test files** — `tests/unit/{test_mock_schemas,test_mock_anchor_ids,test_pto_balance_arithmetic}.py`.

---

## TDD evidence

All three test files were written and run **before** any generator existed:

```
$ .venv/bin/python -m pytest tests/unit/test_mock_schemas.py tests/unit/test_mock_anchor_ids.py \
      tests/unit/test_pto_balance_arithmetic.py -q
...
FAILED tests/unit/test_pto_balance_arithmetic.py::test_e1042_resolves_to_thirteen_point_five
ERROR tests/unit/test_mock_anchor_ids.py::test_e1108_is_still_inside_its_waiting_period_at_the_snapshot
...
28 failed, 1 passed, 1 skipped, 7 errors in 0.57s
```

(The one pass was `test_the_committed_datasets_stay_under_300_kb` over an empty directory; the
one skip was the `corpus/facts.yml` check, correctly skipping.) After the generator:

```
$ .venv/bin/python -m pytest tests/unit/test_mock_schemas.py tests/unit/test_mock_anchor_ids.py \
      tests/unit/test_pto_balance_arithmetic.py -q
....................................s                                    [100%]
36 passed, 1 skipped in 0.09s
```

**`pii_check.py` was proved non-vacuous** by injecting five violations into a copy of
`employees.json` and restoring it:

```
$ .venv/bin/python scripts/pii_check.py
pii_check: 6 problem(s) in mock_data/:
  mock_data/employees.json: forbidden field name 'ssn'
  mock_data/employees.json: forbidden field name 'date_of_birth'
  mock_data/employees.json: forbidden field name 'home_address'
  mock_data/employees.json: SSN-shaped string '123-45-6789'
  mock_data/employees.json: email outside @mosaicrobotics.example: 'someone@gmail.com'
  mock_data/employees.json: phone outside the reserved +1-555-01xx block: '+1-617-555-0199'
exit=1
$ # after restoring
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
restored exit=0
```

**The skipped `facts.yml` check was proved non-vacuous** with a throwaway `corpus/facts.yml`
(written, run, then deleted — it is *not* in the commit; `git status` was clean afterwards):

```
$ # with a stand-in facts.yml carrying the three pto.accrual.* keys
5 passed in 0.02s
$ # after changing pto.accrual.ft_3y_plus to 1.75
E             Expected: 1.5 ± 1.5e-06
FAILED tests/unit/test_pto_balance_arithmetic.py::test_accrual_rate_matches_the_facts_yml_band
1 failed in 0.04s
```

---

## Definition of done — real output

### 1. Byte-idempotent regeneration

```
$ python scripts/gen_mock_data.py && git diff --exit-code mock_data/
mock_data/employees.json  24 records  14124 bytes
mock_data/pto_balances.json  24 records  11748 bytes
mock_data/benefits_elections.json  24 records  44058 bytes
mock_data/org_manager_map.json  24 records  3810 bytes
mock_data/offices.json  4 records  1091 bytes
mock_data/holidays_2026.json  2 records  3118 bytes
git diff --exit-code mock_data/ -> clean (exit 0)
```

### 2. Schemas + PII check

```
$ python scripts/gen_mock_schemas.py && python scripts/pii_check.py
mock_data/schemas/employees.schema.json  4481 bytes
mock_data/schemas/pto_balances.schema.json  3672 bytes
mock_data/schemas/benefits_elections.schema.json  4316 bytes
mock_data/schemas/org_manager_map.schema.json  2248 bytes
mock_data/schemas/offices.schema.json  2136 bytes
mock_data/schemas/holidays_2026.schema.json  2501 bytes
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
exit=0
```

(`gen_mock_schemas.py` is idempotent too — verified by snapshotting `mock_data/`, regenerating
both artifacts and `diff -r`: *no diff*.)

### 3. Schemas valid; anchors present; `E1108` still waiting

```
$ pytest tests/unit/test_mock_schemas.py tests/unit/test_mock_anchor_ids.py -q
................................                                         [100%]
32 passed in 0.06s
```

### 4. The PTO identity at the snapshot

```
$ pytest tests/unit/test_pto_balance_arithmetic.py -q -rs
....s                                                                    [100%]
=========================== short test summary info ============================
SKIPPED [1] tests/unit/test_pto_balance_arithmetic.py:83: corpus/facts.yml not present (P2)
4 passed, 1 skipped in 0.06s
```

The one skip is the sanctioned cross-phase skip named in the dispatch: the reviewer must not
count it as a failure, and **the main session must re-run this file after P2 merges.**

### Whole suite and lint (not in the brief's DoD, run anyway)

```
$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
36 files already formatted

$ make test
.venv/bin/pytest -q
........................................................................ [ 53%]
..........................s...................................           [100%]
133 passed, 1 skipped in 0.91s
```

---

## Files changed

| Path | |
|---|---|
| `scripts/gen_mock_data.py` | new — generator + Pydantic models (651 lines) |
| `scripts/gen_mock_schemas.py` | new — models → `mock_data/schemas/*.schema.json` |
| `scripts/pii_check.py` | new — the CI PII gate |
| `mock_data/{employees,pto_balances,benefits_elections,org_manager_map,offices,holidays_2026}.json` | new — the six datasets |
| `mock_data/schemas/*.schema.json` | new — six draft-2020-12 schemas |
| `mock_data/README.md` | new — SYNTHETIC DATA banner + the `as_of` convention |
| `tests/unit/test_mock_schemas.py` | new |
| `tests/unit/test_mock_anchor_ids.py` | new |
| `tests/unit/test_pto_balance_arithmetic.py` | new |
| `.github/workflows/ci.yml` | **+1 line** — `python scripts/pii_check.py` in job `test` |
| `CHANGELOG.md` | **+22 lines appended** — see below |

21 files, 4739 insertions, 0 deletions. Nothing outside P3's scope was touched;
`tests/architecture/test_conventions.py` was left alone (its five assertions are complete and
P3 adds no new structural invariant — §16.3 and §22 row 29 say there are exactly five).

---

## Ambiguities resolved

1. **`org_manager_map.json` and `holidays_2026.json` are described in §5.4 as maps, but the
   banner example shows `records: [...]`.** I gave every file the same banner + `records` array
   shape: org nodes are `{employee_id, manager_id, skip_level_id, direct_reports[]}` keyed by
   `employee_id`, calendars are `{holiday_calendar_id, country, holidays[]}` keyed by
   `holiday_calendar_id`. The §5.4 lookup semantics are preserved and every dataset loads,
   validates and is schema-checked identically. Documented in `mock_data/README.md`.

2. **`observed` in a holiday record is not typed in §5.4.** I read it as the *observed date*
   (ISO string), not a boolean, because that is what a tool needs: 2026-07-04 is a Saturday, so
   Independence Day is observed on **2026-07-03**. German public holidays are never moved, so
   `observed == date` on `de-2026`. Documented on the field.

3. **Where the accrual-band fact keys come from (the one real cross-phase risk).** §5.2 names
   `pto.accrual.ft_3y_plus` (1.50) and §8.4 tool 6 mentions "the under-3y 1.25" without naming a
   key. I used the minimum set of three: `pto.accrual.ft_3y_plus` = **1.50** (full-time, ≥ 36
   months), `pto.accrual.ft_under_3y` = **1.25** (full-time, < 36 months) and
   `pto.accrual.part_time_prorated` = **0.75** (the three part-time employees). All three are
   recorded in `CHANGELOG.md` with the value and `unit: days_per_month` P2's `facts.yml` must
   carry. See *Concerns* #1.

4. **`work_phone` is not in §5.4's key-field list, but §5.4's conventions require phones in
   `+1-555-01xx` and `pii_check.py` must check them.** Without a phone field the convention and
   half the check would be vacuous, so I added `work_phone` to `employees.json` (schema-pinned
   to `^\+1-555-01[0-9]{2}$`). It is not in `lookup_employee_profile`'s §8.4 output, so no
   user-facing contract changes. Likewise `HolidayCalendar.country`, so a calendar can be
   resolved without going back through `offices.json`.

5. **Employment mix.** The enum keeps all four §5.4 values, but the 24 records are 21
   `full_time` and 3 `part_time`. Adding contractors or interns would have required inventing a
   fourth and fifth `facts.yml` accrual key for classes that do not accrue — extra cross-phase
   risk for no requirement. All four `office_id`s, both `work_country`s and all three
   `work_arrangement`s *are* exercised.

6. **Commit attribution.** The session directive supplied at dispatch (`Co-Authored-By: Claude
   Opus 5 (1M context)`) explicitly replaces earlier attribution guidance, so it is what the
   three commits carry rather than the `Claude Fable 5.1` line in `constraints.md` §14. Flagging
   it in case the main session wants them rewritten before the merge.

---

## Self-review findings (and what I did about them)

- **Fixed: a silently-wrong dependants mapping.** `{"employee_only": 0, ...}.get(tier) or
  rng.randint(1, 3)` returns `0` — falsy — so every `employee_only` record would have got a
  random dependant count. Replaced with explicit branches before the first generation run.
- **Fixed: `pii_check.py` flagged its own schemas.** The first phone regex matched the escaped
  `\+1-555-01` *inside* the schema's `pattern` string. Added a `\\` to the left lookbehind so
  only complete standalone numbers match, and confirmed the check still catches a real
  `+1-617-555-0199` (evidence above).
- **Fixed: two `E501` lines and an unformatted roster.** `ruff format` wanted to explode the
  24-row roster to one field per line; I fenced it (and the PII token set) with `# fmt: off` /
  `# fmt: on` and let the formatter own everything else. Verified the datasets are still
  byte-identical after reformatting.
- **Fixed: an unused `employees` fixture argument** in `test_ids_are_unique_...` (commit
  `43fb19c`).
- **Checked, no change: tests verify behaviour, not the generator.** All three test files read
  the committed JSON off disk and never import `gen_mock_data`, so they would fail if the data
  and the code disagreed. Deliberately *no* "regenerate and compare" test: §21 row 28 makes
  `mock_data/**` an authored-once artifact whose idempotence is gated once here, never in CI.
- **Checked, no change: output is pristine.** No warnings anywhere in the suite; the single skip
  is the sanctioned P2 one.
- **Checked, no change: the identity is exercised in both directions.** Roughly half the
  carryover balances expire `2026-03-31` (lapsed at the snapshot → term contributes 0.0) and
  half `2026-12-31` (unexpired → term contributes), so `carryover_unexpired` is not dead weight.

---

## Concerns

1. **The three `pto.accrual.*` keys are a hard dependency on P2's `corpus/facts.yml`.**
   `pto.accrual.ft_3y_plus` is spec-named and safe; `pto.accrual.ft_under_3y` (1.25) and
   `pto.accrual.part_time_prorated` (0.75) are my names for bands the spec describes but does
   not name. If P2 chose different key names or values, `test_accrual_rate_matches_the_facts_yml_band`
   fails on the first post-merge run. It is a one-line fix on either side, the failure message
   names the missing key, and the required keys/values/units are written into `CHANGELOG.md`.
   **The main session should run `pytest tests/unit/test_pto_balance_arithmetic.py -q` right
   after merging p2 and p3.**
2. **`.github/workflows/ci.yml` is edited by both P2 and P3.** To merge cleanly I appended my
   one line at the very end of job `test` (after `pytest -q`) rather than at the more natural
   spot before it, on the assumption P2 inserts theirs earlier. If both agents appended, expect
   a two-line conflict — resolve by keeping both `run:` steps. Trade-off: a PII hit now fails
   the build after the suite rather than before it, which costs ~1 CI minute and nothing else.
3. **A regeneration reshuffles everything.** Because ids, phones and balances all come from one
   RNG stream, *any* change to the roster or the number of draws changes 20 of the 24 ids. Only
   the four anchors are stable. This is recorded in `CHANGELOG.md` and in `mock_data/README.md`;
   later phases must hard-code anchors only.
4. **`E1108` shows `used_ytd: 0.5` and `pending_days: 0.5`** seventeen days after his hire date.
   Plausible (a half-day taken, a half-day pending) and it usefully exercises the identity on a
   brand-new hire, but a reviewer who wants a pristine new-hire balance would pin it the way
   `E1042` is pinned.
5. **`accrued_ytd` assumes accrual posts on the first of each month** starting the first
   month-start strictly after the hire date, with no waiting period on PTO (the 90-day waiting
   period gates *benefits* only). §5.4's worked example for `E1042` ("nine 2026 postings,
   1 Jan … 1 Sep") is consistent with this and `test_accrued_ytd_is_the_monthly_postings_up_to_the_snapshot`
   asserts it, but if P2's PTO policy prose says accrual begins after a waiting period, the two
   should be reconciled at the merge.
