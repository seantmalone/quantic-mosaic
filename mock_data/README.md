# SYNTHETIC DATA — NOT REAL EMPLOYEE INFORMATION

> Every file in this directory is **fabricated**. The people, offices, balances and elections
> below describe **Mosaic Robotics, Inc.**, a fictional 420-person industrial robotics company
> invented for a Quantic AI Engineering course project. Nothing here was derived from, sampled
> from, or anonymised out of any real HR system. No real person is described.

Every dataset carries the same banner, so a reader who opens one file in isolation still knows
what it is:

```json
{ "_synthetic": true,
  "_notice": "SYNTHETIC DATA — fictional persons, generated for the Quantic AI Engineering project. No real employee information.",
  "_generator": "scripts/gen_mock_data.py seed=1729",
  "as_of": "2026-09-01",
  "records": [ ... ] }
```

---

## The `as_of` snapshot convention

**Every date-bearing value in this directory is stated as of `2026-09-01`** — balances, tenure,
eligibility, waiting periods — exactly as an HRIS export would be. `2026-09-01` is the
*snapshot date*, and it is the single most important data decision in the project.

### What it means

`pto_balances.json` does not say "Priya has 13.5 days". It says "Priya had 13.5 days **on
1 September 2026**". Nine monthly accrual postings had landed by then (1 January through
1 September) at 1.50 days a month, and she had taken none. That statement is true forever,
because it is anchored to a date rather than to the moment you read it.

### Why every date-bearing tool reports it

`check_pto_balance` and `lookup_benefits_status` return the `as_of` they computed against,
next to a `computed_at` carrying the **real** wall-clock time of the call:

```jsonc
{"employee_id":"E1042","as_of":"2026-09-01","computed_at":"2026-11-02T14:08:31Z",
 "remaining_days":13.5,"note":"Balances are a synthetic snapshot as of 2026-09-01."}
```

Ask for a balance "as of 2026-09-15" and the tool echoes your `requested_as_of`, answers from
the snapshot, and says so. It never extrapolates. The chat UI renders *"Balances as of
1 September 2026 (synthetic snapshot)"* under any tool result carrying an `as_of`, so a grader
is never misled about freshness. The audit trail therefore records both facts: which snapshot
the answer came from, and when the answer was produced.

### Why nothing computes against "today"

The system runs on the **real wall clock** everywhere. There is no `core/clock.py`, no
`NOW_OVERRIDE`, no `EVAL_FIXED_NOW` — latency, uptime, span durations and `computed_at` are all
genuinely now. What is frozen is not the clock but the **data**.

That split is what makes the project durable:

- **The documented answer stays correct.** `E1042 → 13.5 days` is quoted in the design
  document, the demo narration, the evaluation gold answers and
  `tests/integration/test_mcp_tool_call.py`. Computed against "today" it would drift by 1.50
  days every month and every one of those artifacts would rot.
- **The evaluation never rots.** Every question in `evaluation/dataset.yaml` uses absolute
  dates and every gold answer is snapshot-relative, so a run in March scores the same as a run
  in September without freezing anything.
- **Nothing about the running system is faked.** A frozen clock would have made every latency
  measurement, retention sweep and span duration a lie. Freezing the data instead costs
  nothing and buys the same determinism.

`2026-09-01` is a Tuesday and the first of a month, so it is itself an accrual posting date:
`next_accrual_date` is `2026-10-01` for everyone.

---

## The files

The company the corpus describes has **420 people**; these datasets hold **24 employee records** —
a slice of it, enough to answer every demo and evaluation question about a named person without
generating four hundred rows nobody reads.

| File | Records | What it holds |
|---|---|---|
| `employees.json` | 24 | Identity, role, office, arrangement, manager, tenure at the snapshot |
| `pto_balances.json` | 24 | Accrual band, YTD accrual and use, carryover, remaining days, blackout dates |
| `benefits_elections.json` | 24 | Plan-year elections, dependants, waiting period, open-enrolment window |
| `org_manager_map.json` | 24 | `employee_id → {manager_id, skip_level_id, direct_reports[]}` |
| `offices.json` | 4 | `bos`, `atx`, `ber`, `remote-us` — city, country, timezone, legal entity, holiday calendar |
| `holidays_2026.json` | 2 | The `us-2026` and `de-2026` calendars |
| `schemas/*.schema.json` | 6 | JSON Schema (draft 2020-12) for each file, generated from the Pydantic models |

Each file is one JSON object: the four banner keys, then a `records` array. The two files that
§5.4 describes as maps — `org_manager_map.json` and `holidays_2026.json` — use the same
`records` array shape, keyed by `employee_id` and `holiday_calendar_id` respectively, so every
dataset loads, validates and is schema-checked identically.

### Anchor records

Four ids are fixed, because later phases name them by hand:

| Id | Who | Why it is pinned |
|---|---|---|
| `E1002` | Miguel Ferreira, VP Engineering | `E1042`'s skip-level |
| `E1007` | Dana Whitfield, Director, Engineering | `E1042`'s manager; the recipient in `draft_hr_email` |
| `E1042` | Priya Raghavan, Senior Robotics Engineer, Boston | The demo persona: hired 2022-11-13, **45 months** tenured at the snapshot, **13.5 days** remaining at 1.50 d/mo |
| `E1108` | Marcus Feldman, Robotics Engineer I | Hired 2026-08-15, so his 90-day waiting period ends **2026-11-13** — still open at the snapshot, which is how `lookup_benefits_status` gets a genuine `eligible: false` |

The other 20 ids are sampled from `E1001`–`E1199`, so the set is deliberately **non-contiguous**:
nothing may iterate a range and assume every id in it exists.

### The PTO identity

For every employee, at the snapshot:

```
remaining_days == accrued_ytd - used_ytd - pending_days + carryover_unexpired
```

`carryover_unexpired` is `carryover_from_prior_year` when `carryover_expires_on` is on or after
the snapshot, and `0.0` when that date is absent or already past. Roughly half the carryover
balances here have lapsed, so the term is exercised in both directions.
`tests/unit/test_pto_balance_arithmetic.py` asserts the identity for all 24 records, checks
`accrued_ytd` against the monthly postings, and checks each
`accrual_rate_days_per_month` against the `corpus/facts.yml` entry its `accrual_fact_key` names —
so a policy edit that moves a number cannot silently contradict the data.

### The accrual rate, and how part-time proration is modelled

`accrual_rate_days_per_month` is always **`fte` x the tenure band's full-time rate, rounded to two
decimal places**, and `accrual_fact_key` always names the **band**:

| `accrual_fact_key` | Full-time rate | Applies to |
|---|---|---|
| `pto.accrual.ft_under_3y` | 1.25 d/mo | fewer than 36 months of service at the snapshot |
| `pto.accrual.ft_3y_plus` | 1.50 d/mo | 36 months or more |

`corpus/pto-and-holidays.md` ("Accrual > Part-Time and Prorated Accrual") makes proration a
*multiplier* on the band, not a band of its own: *"Part-time employees scheduled at 0.5 FTE or
more accrue PTO in proportion to their FTE."* So the three part-time records here read:

| Id | FTE | Tenure | Band | Rate |
|---|---|---|---|---|
| `E1096` | 0.6 | 34 mo | `pto.accrual.ft_under_3y` | 0.6 x 1.25 = **0.75** |
| `E1132` | 0.8 | 50 mo | `pto.accrual.ft_3y_plus` | 0.8 x 1.50 = **1.20** |
| `E1175` | 0.8 | 41 mo | `pto.accrual.ft_3y_plus` | 0.8 x 1.50 = **1.20** |

Full-time is the same rule at `fte` 1.0, so one assertion covers all 24 people. The **band** is
what a tool may quote — it is the fact that carries a document, a section and a verbatim sentence
in `corpus/facts.yml` — while the FTE factor is arithmetic over a field that already exists in
`employees.json`. That is why `fte` is **not** copied onto the balance record: one copy of a number
is the only copy that can never disagree with itself. `pto.accrual.part_time_prorated` (0.75) stays
in `facts.yml` as the document's own worked example for a 0.6 FTE employee; no balance record
names it.

---

## Synthetic conventions, and what is deliberately absent

| Convention | Detail |
|---|---|
| Email | `first.last@mosaicrobotics.example` — `.example` is reserved by RFC 2606 and can never be delivered |
| Phone | `+1-555-01xx` — the fictional-number block reserved for exactly this use |
| Employee ids | `^E1[0-9]{3}$`, 24 non-contiguous values in `E1001`–`E1199` |
| Names | Invented; any resemblance to a real person is coincidental |

**Absent by design — the field does not exist, so it cannot be populated later:**

- no national-identifier field of any kind (no US Social Security number),
- no date of birth,
- no home or street address, postcode or personal contact detail.

`python scripts/pii_check.py` enforces all of that and **fails the build** on any hit. It runs
in CI's `test` job and checks both the field names (in the data *and* in the generated schemas)
and the text shapes: national-identifier patterns, any address outside
`@mosaicrobotics.example`, any number outside the `+1-555-01xx` block.

---

## Regenerating

These files are **committed artifacts**, reviewed like source. They are produced once and are
byte-idempotent — running the generator on an unchanged tree must leave the working tree clean:

```bash
python scripts/gen_mock_data.py && git diff --exit-code mock_data/
python scripts/gen_mock_schemas.py
python scripts/pii_check.py
```

Everything that varies comes from a single `random.Random(1729)`; everything a later phase
quotes by hand is pinned in the roster in `scripts/gen_mock_data.py`. The Pydantic models in
that same file are the single definition of every dataset's shape, and
`scripts/gen_mock_schemas.py` writes `schemas/*.schema.json` from them.

## Read-only, by construction

Nothing in this directory is ever written at run time. The two mock write tools
(`create_mock_hr_ticket`, `draft_hr_email`) append a row to the `mock_writes` table in the
durable trace store — never back to this JSON and never to the ephemeral container filesystem —
so a ticket created live on camera is still visible to a grader days later.
