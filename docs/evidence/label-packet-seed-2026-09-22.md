# Blind groundedness labelling packet

Run `r_1790110325_baseline` · dataset sha `2c8973147744a351…` · subset `seed` · 8 items.

These items were sampled with a fixed seed from the questions whose correct behaviour is to answer, before the run was judged. Nothing about any answer influenced which items are here.

You are the reference labeller for spec §13.7. For each item below decide **one binary verdict**
about the ANSWER, using ONLY the EVIDENCE shown with it:

* `grounded` — every statement of company policy in the answer is supported by the passages shown;
* `not_grounded` — at least one is not.

The evidence comes in four classes, and they all count. `kind="retrieval"` is a policy passage the
assistant searched up; `kind="section"` is one it fetched in full; `kind="compliance"` is the
deterministic rule engine's own requirement evidence; and `kind="structured_data"` is a record it
read about this employee — a PTO balance, a benefits eligibility date, a profile. **A claim is
supported if ANY item of ANY class supports it**: a correct fact taken from the employee's own
record is grounded, not invented. Judge against this set alone — outside knowledge and plausibility
are irrelevant, and a claim that no item supports is `not_grounded` however true it sounds.

Return YAML in exactly this shape, one entry per item, in this order:

```yaml
labels:
  - item_id: <id>
    verdict: grounded | not_grounded
    rationale: >-
      One or two sentences naming the specific claim that decided it.
```

---


## benefits-001

**QUESTION**  How long is the new-hire waiting period before benefits coverage begins?

**ANSWER**

```
New hires become eligible for medical, dental and vision coverage 90 days after their hire date. Coverage begins on the day the waiting period ends, not on the first of the following month.

The 401(k) retirement plan has no waiting period; you may begin contributing from your first payroll run.

Basic life insurance and accidental death and dismemberment cover begin when the medical waiting period ends.

Next steps:
- Enroll in benefits during week one of onboarding
- Check MosaicOne Benefits for your digital cards when coverage begins
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_7566e6e377678fcd" kind="retrieval">
New hires become eligible for medical, dental and vision coverage 90 days after their hire date. Coverage begins on the day the waiting period
ends, not on the first of the following month, so an employee whose waiting period ends on 13 November is covered from 13 November.

An employee has 30 days from the end of the waiting period to make elections in MosaicOne Benefits. An employee who makes no election within that
window is enrolled in employee-only coverage on the standard medical plan by default, and may not change it until the next open enrollment or a
qualifying life event.

Retirement plan eligibility is different and shorter: an employee may begin contributing to the 401(k) plan from their first payroll run, with no
waiting period at all.

The waiting period is not restarted by an internal transfer, a promotion, or a change from part-time to full-time status. It is restarted by a
break in service of more than 26 weeks.

Employees scheduled at 0.5 FTE or more are eligible for the full benefit programme. Employees below 0.5 FTE, contractors and interns are not
eligible for company medical, dental, vision or life cover, and are eligible for the 401(k) plan only where the plan document requires it.
</evidence>

<evidence id="c_88f9cf68022eeaea" kind="retrieval">
Mosaic Robotics provides basic life insurance and accidental death and dismemberment cover at two times base salary, up to a maximum of USD 500,000,
at no cost to the employee. Cover begins when the medical waiting period ends.

Employees may buy supplemental life cover for themselves up to a further five times base salary, and spouse and child cover at fixed amounts.
Supplemental cover elected within 30 days of first eligibility is issued without medical underwriting; elected later, it requires evidence of
insurability.

Short-term disability pays 70% of base salary for up to 13 weeks after a 7-day elimination period, at no cost to the employee. Long-term disability
pays 60% of base salary after 13 weeks, to a monthly maximum of USD 12,000, also at no cost.

Disability cover interacts with the Leave of Absence Policy. An employee on a medical leave receives disability benefit rather than salary, and
People Operations coordinates the two so there is no gap in pay.
</evidence>

<evidence id="c_76cc7adc6c535185" kind="retrieval">
Three practical notes that answer most of the questions People Operations receives.

**Find your card.** Digital medical, dental and vision cards are in MosaicOne Benefits from
the day coverage begins. Physical cards arrive within fifteen days. A provider who cannot find you is
usually looking on the day before coverage started.

**Check the network first.** Every plan pays substantially more in network than out of it,
and the carrier's directory is the authority, not the provider's own website. A five-minute check before an
appointment is the single most effective thing an employee can do to control their own cost.

**Appeal a denied claim.** Carriers deny claims for administrative reasons more often than
for clinical ones, and a first-level appeal succeeds surprisingly often. People Operations will help draft
one, and will escalate on the employee's behalf where the carrier's own appeal has failed.

Employees leaving Mosaic Robotics keep medical, dental and vision cover to the end of the month in which
they leave, and are sent continuation-coverage information within fourteen days of their final day.
</evidence>

<evidence id="c_5892cd18e5f9cae8" kind="retrieval">
By the end of week one the new hire has met their immediate team, their onboarding buddy, and at least two people outside their function whose work
touches theirs. Those cross-functional introductions are booked by the manager, not left to chance.

Benefits enrolment opens in week one even though coverage does not begin until the 90-day waiting period ends. Enrolling early means the elections are
in place when eligibility arrives, and People Operations runs a benefits question session every second Tuesday for anyone who wants one.

Payroll setup, tax withholding elections and 401(k) enrolment are completed in week one. The 401(k) has no waiting period, so a new hire may begin
contributing from their first payroll run.

Engineering hires clone the relevant repositories, build the codebase or bring up a bench, and land a first small change by the end of the week. The
first change is deliberately trivial; its purpose is to prove that access, tooling and review all work.

The manager holds a short check-in at the end of week one, asking two questions: what has been confusing, and what is missing. Both answers usually
point at something the company should fix for the next hire.
</evidence>

<evidence id="c_daacc61b42bf9eff" kind="retrieval">
fore the anniversary and at the higher rate from the first posting date
on or after it; there is no retroactive true-up for the months already posted.

New hires begin accruing on the first posting date on or after their start date. An employee who starts on 20 March therefore receives their first
posting on 1 April. There is no waiting period for *using* accrued PTO — an employee may request time off against a positive balance from day one — but
Mosaic Robotics does not permit a negative PTO balance, so a new hire cannot borrow against future accrual.
</evidence>

<evidence id="c_aa88b3304b4feeee" kind="retrieval">
nominates an onboarding buddy, books the first-week meetings, and sends a short introduction to the team explaining what the new
person will work on. New hires consistently report that the introduction matters more than anyone expects.

People Operations sends the new hire a welcome pack five business days before the start date: the first-day logistics, the office address and access
arrangements, what to bring, and a plain-language summary of the benefits enrolment they will complete in their first week.
</evidence>

<evidence id="c_5cd8e7321e674970" kind="retrieval">
By day 30 the new hire should understand what their team does, how it fits into the company, who the customers are, and where to find things. Depth
comes later; orientation comes first.

Required training is complete by day 30 in every case, and security training considerably sooner — see *Required Training* below.

The new hire attends the monthly all-hands and the quarterly product review in their first 30 days wherever the calendar allows, and their manager
makes sure they are invited to both.

The manager holds weekly one-to-ones through the first 30 days without exception. After that the cadence is agreed between the two of them, but it never
drops below fortnightly in the first year.

People Operations sends a 30-day survey directly to the new hire. It is confidential, it is short, and the aggregate results are reviewed with
department heads quarterly. Individual answers are never shared with the manager.
</evidence>

<evidence id="c_492c8f3d3327af90" kind="retrieval">
Dependent children may remain on a Mosaic Robotics medical plan until the end of the month in which they turn 26. Dental and vision plans follow the
same rule.

Eligible dependents are a legal spouse, a registered domestic partner, a biological or adopted child, a stepchild, and a child for whom the employee
has legal guardianship. Documentation is required within 60 days of adding a dependent; a dependent whose documentation is not supplied is removed from
coverage retroactively to the date they were added.

A child of any age who is incapable of self-support because of a disability that began before age 26 may remain covered indefinitely, subject to the
carrier's certification.
</evidence>

<evidence id="c_16d5fa1a07ca573f" kind="retrieval">
The dental plan covers preventive care at 100% with no deductible, basic restorative care at 80% and major restorative care at 50%, with an annual
maximum benefit of USD 2,000 per covered person. Orthodontia carries a separate lifetime maximum of USD 2,500 and is available to covered dependents
under 19.

The vision plan covers one eye examination per plan year at a USD 10 copay, and provides an allowance of USD 200 per plan year toward frames or
contact lenses. Employees whose role requires safety eyewear receive prescription safety glasses through Facilities rather than through the vision
plan, at no cost and outside the allowance.

Dental and vision elections are independent of the medical election. An employee may decline medical cover and still elect dental and vision, or the
reverse.
</evidence>

<evidence id="c_4ba83fb1511ae9aa" kind="retrieval">
Mosaic Robotics provides 16 weeks of fully paid parental leave to every eligible new parent. The 16 weeks are the same whether the employee gave birth,
did not give birth, adopted, or became a parent through surrogacy or foster placement leading to adoption.

Parental leave eligibility begins after 6 months of continuous service. An employee who becomes a parent before reaching six months receives the
statutory entitlement their jurisdiction provides, and the company benefit begins the day the service requirement is met.

Leave must begin within 12 months of the birth or placement. It may be taken as one continuous block, or as up to three blocks of at least two weeks
each, agreed with the manager and People Operations before the first block begins. Splitting the leave does not extend the total.

An employee who gives birth also receives any period of medical disability leave certified by their clinician, before the parental leave begins. The
disability period is paid through short-term disability rather than as parental leave, and it does not reduce the 16 weeks.

Parental leave for both parents where both work at Mosaic Robotics is 16 weeks each. The company does not pool or reduce the entitlement.
</evidence>

<evidence id="c_749c3f5abec91fe8" kind="retrieval">
Continuous medical leave is available for up to 26 weeks in a rolling 12-month period. The leave covers the employee's own serious health condition,
including physical illness, surgery, recovery and mental health treatment.

The first 13 weeks are paid at 70% of base salary through short-term disability after a 7-day elimination period covered by the employee's sick balance
or PTO. Weeks 14 to 26 are paid at 60% of base salary through long-term disability. Mosaic Robotics tops the first two weeks up to 100% of base salary
so that a short recovery is not a financial event.

Intermittent medical leave — a course of treatment requiring a day a week, a reduced schedule during recovery — is available on the same 26-week
budget, counted in hours rather than weeks. The schedule is agreed with People Operations and the manager is told only the schedule.

A clinician's certification is required for any medical leave longer than five consecutive working days, and a recertification is required every eight
weeks for a continuing leave. Certifications go to People Operations and are stored in a restricted-access record separate from the employee file.
</evidence>

---

## benefits-002

**QUESTION**  When does my benefits waiting period end, and how long is that waiting period under the policy?

**ANSWER**

```
Your benefits waiting period ends on 13 November 2026.

New hires become eligible for medical, dental and vision coverage 90 days after their hire date. Coverage begins on the day the waiting period ends, not on the first of the following month.

Recommendation — not company policy: You have 30 days from 13 November to make your benefits elections in MosaicOne. If you make no election within that window, you will be enrolled in employee-only coverage on the standard medical plan by default and may not change it until the next open enrollment or a qualifying life event.

Retirement plan eligibility is different: you may begin contributing to the 401(k) plan from your first payroll run, with no waiting period at all.

Next steps:
- Review plan options before 13 November
- Submit elections in MosaicOne by 13 December
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_7566e6e377678fcd" kind="retrieval">
New hires become eligible for medical, dental and vision coverage 90 days after their hire date. Coverage begins on the day the waiting period
ends, not on the first of the following month, so an employee whose waiting period ends on 13 November is covered from 13 November.

An employee has 30 days from the end of the waiting period to make elections in MosaicOne Benefits. An employee who makes no election within that
window is enrolled in employee-only coverage on the standard medical plan by default, and may not change it until the next open enrollment or a
qualifying life event.

Retirement plan eligibility is different and shorter: an employee may begin contributing to the 401(k) plan from their first payroll run, with no
waiting period at all.

The waiting period is not restarted by an internal transfer, a promotion, or a change from part-time to full-time status. It is restarted by a
break in service of more than 26 weeks.

Employees scheduled at 0.5 FTE or more are eligible for the full benefit programme. Employees below 0.5 FTE, contractors and interns are not
eligible for company medical, dental, vision or life cover, and are eligible for the 401(k) plan only where the plan document requires it.
</evidence>

<evidence id="c_0df5d11cd585014f" kind="retrieval">
Benefits questions go to People Operations at benefits@mosaicrobotics.example. Eligibility and waiting-period questions, and anything involving a
dependent's documentation, go to the same address. Claims disputes with a carrier are escalated by People Operations on the employee's behalf where the
carrier's own appeal has failed. Payroll deduction questions go to payroll@mosaicrobotics.example.
</evidence>

<evidence id="c_88f9cf68022eeaea" kind="retrieval">
Mosaic Robotics provides basic life insurance and accidental death and dismemberment cover at two times base salary, up to a maximum of USD 500,000,
at no cost to the employee. Cover begins when the medical waiting period ends.

Employees may buy supplemental life cover for themselves up to a further five times base salary, and spouse and child cover at fixed amounts.
Supplemental cover elected within 30 days of first eligibility is issued without medical underwriting; elected later, it requires evidence of
insurability.

Short-term disability pays 70% of base salary for up to 13 weeks after a 7-day elimination period, at no cost to the employee. Long-term disability
pays 60% of base salary after 13 weeks, to a monthly maximum of USD 12,000, also at no cost.

Disability cover interacts with the Leave of Absence Policy. An employee on a medical leave receives disability benefit rather than salary, and
People Operations coordinates the two so there is no gap in pay.
</evidence>

<evidence id="c_5892cd18e5f9cae8" kind="retrieval">
By the end of week one the new hire has met their immediate team, their onboarding buddy, and at least two people outside their function whose work
touches theirs. Those cross-functional introductions are booked by the manager, not left to chance.

Benefits enrolment opens in week one even though coverage does not begin until the 90-day waiting period ends. Enrolling early means the elections are
in place when eligibility arrives, and People Operations runs a benefits question session every second Tuesday for anyone who wants one.

Payroll setup, tax withholding elections and 401(k) enrolment are completed in week one. The 401(k) has no waiting period, so a new hire may begin
contributing from their first payroll run.

Engineering hires clone the relevant repositories, build the codebase or bring up a bench, and land a first small change by the end of the week. The
first change is deliberately trivial; its purpose is to prove that access, tooling and review all work.

The manager holds a short check-in at the end of week one, asking two questions: what has been confusing, and what is missing. Both answers usually
point at something the company should fix for the next hire.
</evidence>

<evidence id="c_4ba83fb1511ae9aa" kind="retrieval">
Mosaic Robotics provides 16 weeks of fully paid parental leave to every eligible new parent. The 16 weeks are the same whether the employee gave birth,
did not give birth, adopted, or became a parent through surrogacy or foster placement leading to adoption.

Parental leave eligibility begins after 6 months of continuous service. An employee who becomes a parent before reaching six months receives the
statutory entitlement their jurisdiction provides, and the company benefit begins the day the service requirement is met.

Leave must begin within 12 months of the birth or placement. It may be taken as one continuous block, or as up to three blocks of at least two weeks
each, agreed with the manager and People Operations before the first block begins. Splitting the leave does not extend the total.

An employee who gives birth also receives any period of medical disability leave certified by their clinician, before the parental leave begins. The
disability period is paid through short-term disability rather than as parental leave, and it does not reduce the 16 weeks.

Parental leave for both parents where both work at Mosaic Robotics is 16 weeks each. The company does not pool or reduce the entitlement.
</evidence>

<evidence id="c_d2a55afc5567ce2a" kind="retrieval">
gh the carrier.

A wellbeing allowance of USD 40 per month may be claimed for exercise, sports club membership,
mindfulness applications or equipment. It is claimed in MosaicOne Expenses like any other allowance and is
taxable where the entity's rules require it.

Backup care provides ten days per plan year of subsidised childcare or eldercare for the days when the
usual arrangement falls through. The employee pays a fixed contribution per day and the company pays the
rest.

None of these programmes reports individual usage to a manager, and none is visible on an employee's
record beyond the payroll deduction where one applies.
</evidence>

<evidence id="c_864fb910f46475a7" kind="retrieval">
No employee may work outside their home country for more than 90 days in a rolling 12-month period. The 90-day figure is a company limit and is
independent of any shorter limit imposed by the destination country's immigration rules, which always take precedence.

Days are counted as calendar days of presence, including weekends and company holidays that fall inside the trip. A trip that begins on 3 November and
ends on 14 December counts as 42 days.

Separate trips inside the rolling window are added together. An employee who spent 55 days abroad in March and April may take no more than 35 further
days before the March allocation begins to roll off.
</evidence>

<evidence id="c_0d2c84e4df38b6a0" kind="retrieval">
International remote work of more than 30 days requires approval from the employee's director and from Tax & Legal. Shorter stays are a direct-manager
decision, and every stay of any length must satisfy the device and connectivity requirements in the Security & Acceptable Use Policy.

| Request | First approver | Second approver | Notice |
|---|---|---|---|
| Work abroad, up to 30 consecutive days, approved country | Direct manager | - | 21 calendar days |
| Work abroad, more than 30 consecutive days | Director | Tax & Legal | 21 calendar days |
| Work abroad, destination not on the approved list | Director | Tax & Legal | 30 calendar days |
| Extension of an approved stay | Director | Tax & Legal | Before the approved end date |
| Permanent relocation to another country | VP People Operations | Tax & Legal | 60 calendar days |
| International business travel (Travel Policy) | Direct manager | - | 14 calendar days |

The Tax & Location Addendum sets the thresholds behind this table and explains why the 30-day line sits where it does. The addendum, not this matrix, is
the authority on whether a particular destination and duration are workable.
</evidence>

<evidence id="c_26d73a3bc194792c" kind="retrieval">
Employees of Mosaic Robotics GmbH participate in the German statutory health, pension, unemployment and long-term care systems, with contributions
split between employer and employee as the statute requires. The plans described above do not apply.

The company supplements the statutory position with a private supplementary health plan, an occupational pension contribution of 5% of gross salary
into a company-supported scheme, and a monthly public transport allowance. There is no waiting period for the supplementary plans; they begin on the
first day of employment.

German employees do not participate in open enrollment. Their supplementary elections are made at hire and may be changed at any time with one
month's notice.
</evidence>

<evidence id="c_16186f87d12c1302" kind="retrieval">
PTO requests must be submitted at least 5 business days in advance. A request of six or more consecutive business days requires 15 business days of
advance notice. Notice is counted in business days between the day the request is submitted in MosaicOne and the first day of the requested absence,
excluding both the submission day and any company holiday on the employee's office calendar.

The notice requirement exists so that a manager can rebalance work, not to create a barrier. A manager may waive the notice requirement for a request
that falls inside the window; the waiver is recorded in MosaicOne with a short reason, and People Operations reviews waivers quarterly to make sure the
exception has not become the rule.

Unforeseeable absences — a sudden illness, a family emergency, a transport failure that makes work impossible — are never held to the notice
requirement. The employee notifies their manager as early as they reasonably can, and the absence is entered in MosaicOne retroactively, against sick
time where the reason was illness and against PTO otherwise.
</evidence>

<evidence id="lookup_benefits_status#1" kind="structured_data">
{"employee_id": "E1108", "plan_year": 2026, "as_of": "2026-09-01", "eligible": false, "eligibility_reason": "90-day waiting period ends 2026-11-13", "waiting_period_ends": "2026-11-13", "elections": [], "dependents": 0, "open_enrollment_window": {"open": "2026-11-01", "close": "2026-11-21"}, "qualifying_life_event_window_open": false, "policy_doc_id": "benefits-and-open-enrollment"}
</evidence>

---

## conduct-001

**QUESTION**  What are the published timelines for a workplace conduct case: acknowledgement, investigation, and the response target for a severity-1 case?

**ANSWER**

```
People Operations acknowledges every reported concern within 2 business days.

Investigations are targeted for completion within 30 calendar days of the report.

Severity 1 cases receive a response within 4 business hours.

Target resolution times for Severity 1 cases are as fast as the facts allow.

Next steps:
- Contact Employee Relations if you have a conduct concern
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_8befbf9c1eefd50e" kind="retrieval">
Every case is assigned a severity on creation by the People Operations partner who receives it. Severity drives response time, not outcome, and it can
be raised at any point as more is learned.

**Severity 1** covers immediate risk to a person: violence or a threat of it, a safety incident with injury, a credible risk of self-harm, sexual
misconduct involving physical contact, and any matter where someone must be separated from a situation today. Severity 1 cases receive a response within
4 business hours.

**Severity 2** covers serious matters without immediate physical risk: harassment, discrimination, retaliation, suspected fraud, a regulatory inquiry, a
legal threat. Severity 2 cases receive a first response within 1 business day and a written plan within 3 business days.

**Severity 3** covers everything else that requires a person: accommodation requests, compensation disputes, undisclosed conflicts of interest, and
matters an employee has asked to be handled formally. Severity 3 cases receive a response within 3 business days.
</evidence>

<evidence id="c_8e5b6fa6417ebbd2" kind="retrieval">
disclosed conflicts of interest, and
matters an employee has asked to be handled formally. Severity 3 cases receive a response within 3 business days.

Response means a named human being contacting the person who raised the case, acknowledging what was raised, naming who owns it and describing what
happens next. It does not mean an outcome, and People Operations is careful not to imply otherwise.

Target resolution times are 10 business days for Severity 3, 30 calendar days for Severity 2 and as fast as the facts allow for Severity 1. Where a case
will run past its target, the person who raised it is told in writing why and when to expect the next update. Updates continue at least every 10
business days until the case closes.
</evidence>

<evidence id="c_faa7e3e074e0f281" kind="retrieval">
People Operations acknowledges every reported concern within 2 business days. The
acknowledgement names the person who will handle the case, explains
the process, and sets out what the reporter can expect to be told and when.
Not every concern becomes a formal investigation. Some are resolved by a conversation, some by
a change of arrangement, some by coaching. The reporter
is told which route is proposed and why, and may ask for a formal investigation instead.
Where a formal investigation is opened, an investigator is appointed who has no reporting
relationship to anyone involved. The investigator interviews
the reporter, the person the concern is about, and any witnesses, and reviews any relevant records.
The person the concern is about is told the
substance of the allegation and given a fair opportunity to respond.
Investigations are targeted for completion within 30 calendar days of the report. Where an
investigation will take longer, the reporter and the
respondent are both told, in writing, why and when to expect the outcome.
</evidence>

<evidence id="c_b1b9f056ae7f2f27" kind="retrieval">
General conduct questions and reports go to People Operations at
people-ops@mosaicrobotics.example. Harassment, discrimination and retaliation reports
go to Employee Relations at employee-relations@mosaicrobotics.example. Anonymous reports go
to the third-party ethics line published in MosaicOne.
Reports concerning the executive team go to the chair of the audit committee, reachable through
the ethics line. The escalation routes, severity levels
and response times that apply to every case are set out in the HR Escalation and Case Handling
Policy.
</evidence>

<evidence id="c_44c603b1a3b6b75b" kind="retrieval">
People Operations reports four numbers to the executive team and the board each quarter: case volume by
category, median time to first response against the severity target, median time to closure, and the share
of cases reopened within 90 days.

No individual is identifiable in the reporting. Categories with fewer than five cases in a quarter are
aggregated so that a small team's single case cannot be inferred from the numbers.

Reporters and witnesses are surveyed after closure on whether they were treated fairly and whether they
would raise a concern again. The second question is the one the company watches most closely, because a
process that resolves cases while teaching people not to report has failed.

Trends are acted on rather than filed. Three cases from the same team in a quarter, a category rising
without an obvious cause, or a persistent gap between severity targets and actual response times each
trigger a review with the department head involved.

The escalation list itself is reviewed annually against the cases that arrived, and categories are added
when the year's experience shows a gap. It has grown twice since 2024 and has never shrunk.
</evidence>

<evidence id="c_f7ec2fe078c43c2d" kind="retrieval">
of the report. Where an
investigation will take longer, the reporter and the
respondent are both told, in writing, why and when to expect the outcome. Complexity is a reason
for delay; inattention is not.
At the conclusion the investigator makes a finding on the balance of probabilities and recommends
an outcome. The reporter is told whether the concern
was upheld and, in general terms, what action follows. The respondent is told the finding in full.
Interim measures are available while an investigation runs: a change of reporting line, a change of
shift, a temporary reassignment, or paid suspension
of the respondent where the allegation is serious. Interim measures are never applied to the
reporter as a way of separating the parties unless the
reporter asks for them.
Either party may ask for a review of the outcome within 10 business days, on the grounds that the
process was unfair, that a material fact was
overlooked, or that the outcome was disproportionate. The review is conducted by a person who
was not involved in the original investigation.
</evidence>

---

## expenses-001

**QUESTION**  What is the annual home-office reimbursement cap?

**ANSWER**

```
Each employee may claim up to USD 750 per plan year for home office furniture and accessories, including items such as a desk, chair, lamp, footrest, adjustable monitor arm, acoustic treatment, and small filing cabinet.

The allowance resets on 1 January and does not carry over.

Laptops, monitors, docks, keyboards, mice, headsets and webcams are not claimed against this allowance; they are issued as company assets under the Equipment & Asset Policy.

Next steps:
- Review eligible items in MosaicOne Expenses
- Submit claims by 20th of month for same-month reimbursement
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_9ce35f1b68d5c0f8" kind="retrieval">
This policy describes what Mosaic Robotics pays for, how an employee claims it back, and who approves it. It covers business expenses incurred by
employees of Mosaic Robotics, Inc. and Mosaic Robotics GmbH in the ordinary course of their work, together with the standing allowances the company
offers for home offices, connectivity and professional development.

Travel expenses — flights, hotels, ground transport, per diem — are set out in the Travel Policy, which sits alongside this one and shares its
submission mechanics, deadlines and approval thresholds. Where the Travel Policy sets a cap, that cap governs; where it is silent, this policy governs.

All expenses are submitted in MosaicOne Expenses. Reimbursement is paid with the next payroll run after approval, which means an expense approved by
the 20th of a month is reimbursed in that month's payroll and an expense approved after it lands in the following month.

Amounts in this policy are stated in United States dollars. Employees of the German entity claim in euros; MosaicOne converts the cap at the European
Central Bank reference rate on the transaction date, and the converted figure — not a re-negotiated one — is the cap that applies.
</evidence>

<evidence id="c_c0b4b1d7c6436137" kind="retrieval">
Each employee may claim up to USD 750 per plan year for home office furniture and accessories. The allowance is intended for the things that make a
home workspace work: a desk, a chair, a lamp, a footrest, an adjustable monitor arm, acoustic treatment, a small filing cabinet.

The allowance resets on 1 January and does not carry over. It is available to hybrid and fully remote employees; onsite employees may claim against it
only where their manager has agreed a regular remote pattern in MosaicOne.

Laptops, monitors, docks, keyboards, mice, headsets and webcams are **not** claimed against this allowance. They are issued as company assets under the
Equipment & Asset Policy, remain company property and are tracked in the asset register. An employee who buys a monitor with the home office allowance
has bought a monitor for themselves, which is rarely what they intended.

Items purchased under the allowance belong to the employee and are not returned at separation. Because of that, the allowance is taxable in some
jurisdictions; MosaicOne applies the correct treatment automatically for each entity.

A new hire may claim the full allowance from their start date. An employee who joins after 1 October may claim the following year's allowance
immediately as well, so that a December start is not penalised.
</evidence>

<evidence id="c_ea06a3ed336f31b5" kind="retrieval">
The daily meal cap for domestic travel is USD 75 per traveller. The cap covers all meals in a 24-hour period including tips and non-alcoholic drinks,
and it applies per person rather than per receipt, so a shared dinner for three colleagues is measured against USD 225.

Alcohol is reimbursable only as part of a hosted meal with customers, partners or candidates, and only in moderation. Alcohol claimed on a solo travel
day is refused.

Team meals — a lunch for a team that has just shipped, a dinner during an offsite — are reimbursable with manager approval. The claim names every
attendee. A team meal of more than USD 100 per head requires director approval.

Meals with candidates are reimbursable by the hiring manager under the same caps. Meals with a supplier, or any hospitality offered by a supplier to a
Mosaic Robotics employee, must also be checked against the conflict-of-interest rules in the Workplace Conduct Policy.
</evidence>

<evidence id="c_9f6ea967a241b29d" kind="retrieval">
Fully remote employees receive a monthly connectivity stipend of USD 60. The stipend is paid automatically through payroll, requires no claim and no
receipt, and is intended to cover the incremental cost of home internet and mobile data used for work.

Hybrid and onsite employees do not receive the connectivity stipend, because the company provides connectivity at the office. A hybrid employee whose
role requires reliable home connectivity for on-call duty may request the stipend through their manager, and it is granted for the duration of the
on-call assignment.

The stipend is not paid for months in which the employee is on unpaid leave. It continues during paid leave, PTO and approved work abroad.
</evidence>

<evidence id="c_33b92d987d9bf8c6" kind="retrieval">
The standard lodging cap is USD 250 per night before taxes and fees. The cap covers the room rate only; local occupancy taxes, resort fees and
mandatory service charges are reimbursable above it.

The cap rises to USD 350 per night in Boston, New York, San Francisco, London, Zurich and Tokyo, and for any city during a period when a conference the
company is attending has inflated local rates. MosaicOne Travel applies the higher cap automatically for those markets.

Where the cap cannot be met — a remote field site with one hotel, a sold-out market — the traveller books the most reasonable available option and
notes the reason. No pre-approval is needed; the note is enough.

In-room charges are reimbursable only for internet access and for meals claimed within the meal cap. Minibar, laundry on trips under five nights, pay
television and spa charges are not.

Employees on trips of more than 14 nights should ask MosaicOne Travel for an extended-stay or serviced-apartment rate, which is usually cheaper than a
hotel and always more comfortable.

Sharing a room is never required and is never a condition of approval.
</evidence>

<evidence id="c_8a91f1b8287b0b1b" kind="retrieval">
A corporate card is issued on request to any employee whose role involves regular business spending:
travel, customer hospitality, field service purchases, recruiting. The request is made in MosaicOne with
manager approval and the card arrives within ten business days.

The card is issued in the employee's name and is the company's liability, not the employee's. It carries a
default monthly limit of USD 5,000, raised on request with director approval for roles that need it. A
card is never shared, never lent to a colleague, and never used by anyone but the person named on it.

Every card transaction appears in MosaicOne Expenses within two business days and must be reconciled to a
claim line with a business purpose. A transaction left unreconciled for 45 calendar days triggers a
reminder to the employee and their manager; at 60 days the card is suspended until the backlog clears.

Personal use of a corporate card is a mistake rather than a crime the first time it happens. The employee
marks the line personal in MosaicOne and repays it within 30 calendar days.
</evidence>

<evidence id="c_e0d1b52d3efced01" kind="retrieval">
A remote workspace must have a wired or wireless connection of at least 50 Mbps download. Employees who cannot meet the threshold at home should speak
to their manager about a coworking allowance rather than working from a connection that makes them inaudible in every meeting.

The workspace must be a place where the employee can hold a confidential conversation, lock their screen when they step away, and keep company hardware
out of reach of other people. Working from a shared coworking space is fine; working from a café for a full day, with Confidential material on screen,
is not.

Home office equipment and furniture are covered by the Expenses & Reimbursement Policy's annual home office allowance, and the standard laptop, monitor
and dock are issued under the Equipment & Asset Policy. Mosaic Robotics does not reimburse home internet service for hybrid employees; fully remote
employees receive the monthly connectivity stipend described in the Expenses & Reimbursement Policy.

Employees are responsible for the safety of their own workspace. People Operations publishes an ergonomic self-assessment in MosaicOne and will fund a
professional assessment where a health need is documented.
</evidence>

<evidence id="c_8bd05205ab4632d6" kind="retrieval">
ay request a second set for home; the request is approved routinely for employees whose
recorded arrangement includes at least two remote days a week.

Mobile phones are issued only to employees in Field Service, Customer Support, Security and the executive team, and to anyone in a documented on-call
rotation. Everyone else uses their own phone and, where the role requires it, receives the connectivity stipend described in the Expenses &
Reimbursement Policy.

Manufacturing and laboratory roles are issued the personal protective equipment required for their area — safety glasses, hearing protection, ESD
footwear, cut-resistant gloves. PPE is replaced on demand and is never charged to the employee.
</evidence>

<evidence id="c_48a9f45a84eef721" kind="retrieval">
Keyboards, mice, headsets, webcams, cables, adapters and laptop stands are consumables from the company's point of view. They are issued on request
without approval, replaced on failure, and not tracked individually in the asset register below a USD 150 unit value.

Employees may choose from the catalogue's alternatives — a mechanical keyboard, a trackball, a different headset — where the alternative is within USD
75 of the standard item. Beyond that the difference needs manager approval.

External storage devices are issued only where a documented business need exists, must be hardware-encrypted, and are tracked in the asset register
regardless of value. The Security & Acceptable Use Policy's rules on removable media apply in full.

Printers are not issued for home use. Employees who need something printed use an office printer or the company's print-and-post service, because a
home printer holding company documents is a data-protection problem the company cannot see.
</evidence>

<evidence id="c_31cd6d43c0aabf49" kind="retrieval">
This policy covers the company-owned equipment Mosaic Robotics issues to employees: laptops, monitors, docks, peripherals, mobile devices, test
instruments and the safety equipment used on the manufacturing floor. It sets what is issued as standard, how additional equipment is requested, how
assets are tracked, and what happens when something is damaged, lost or no longer needed.

Every item in this policy remains the property of Mosaic Robotics for as long as it is in service, whatever its value and wherever it sits. Items an
employee buys for themselves with the annual home office allowance described in the Expenses & Reimbursement Policy are the employee's property and are
not covered here.

All issued assets are recorded in the MosaicOne asset register against the holding employee. The register is the authoritative record of who holds
what: an item that is not in the register is not tracked, is not insured and cannot be replaced under this policy.

Equipment decisions are made by IT for computing and mobile devices, by Facilities for furniture and site equipment, and by Engineering Operations for
test instruments. People Operations owns this policy but does not own the equipment.
</evidence>

---

## pto-001

**QUESTION**  How many PTO days does a full-time employee with three or more years of service accrue each month?

**ANSWER**

```
Full-time employees with three or more years of service accrue 1.50 days of PTO per month.
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_e178629918c7cd96" kind="retrieval">
PTO accrues monthly and is posted to the employee's MosaicOne balance on the first calendar day of each month. Accrual is not pro-rated within a month:
an employee who is active on the posting date receives the full monthly posting for that month.

Full-time employees with fewer than three years of service accrue 1.25 days of PTO per month. Full-time employees with three or more years of service
accrue 1.50 days of PTO per month. The service band is evaluated on the posting date using the employee's most recent hire date as recorded in
MosaicOne; a promotion, transfer or change of manager does not reset it, and neither does an internal move between the United States and Germany
entities.

At 1.25 days per month an employee earns 15.0 days across a full plan year. At 1.50 days per month the annual figure is 18.0 days. An employee who
crosses the three-year mark mid-year accrues at the lower rate for the months before the anniversary and at the higher rate from the first posting date
on or after it; there is no retroactive true-up for the months already posted.
</evidence>

<evidence id="c_be7309499c15c7e1" kind="retrieval">
Part-time employees scheduled at 0.5 FTE or more accrue PTO in proportion to their FTE. A 0.6 FTE employee in the under-three-year band accrues 0.75
days per month, and the same employee in the three-year-plus band accrues 0.90 days per month. Proration is calculated to two decimal places and the
posted value is rounded to the nearest 0.05 days.

Employees scheduled below 0.5 FTE do not accrue PTO. They are instead paid for hours worked and may take unpaid time off with their manager's
agreement, recorded in MosaicOne as an unpaid absence so that payroll and headcount reporting stay accurate.

A change of FTE takes effect for accrual purposes on the first posting date on or after the effective date of the change. Balances already accrued at a
higher FTE are never clawed back.
</evidence>

<evidence id="c_daacc61b42bf9eff" kind="retrieval">
fore the anniversary and at the higher rate from the first posting date
on or after it; there is no retroactive true-up for the months already posted.

New hires begin accruing on the first posting date on or after their start date. An employee who starts on 20 March therefore receives their first
posting on 1 April. There is no waiting period for *using* accrued PTO — an employee may request time off against a positive balance from day one — but
Mosaic Robotics does not permit a negative PTO balance, so a new hire cannot borrow against future accrual.
</evidence>

<evidence id="c_ede7ba673fc4e14a" kind="retrieval">
Medical, dental, vision, life and disability cover continue unchanged during every paid leave in this policy, with the employee's share of the premium
deducted from any pay they receive and invoiced where pay is insufficient.

During unpaid leave the employee remains enrolled and pays their ordinary share by direct payment to payroll. Missing three consecutive payments ends
cover, and People Operations gives 30 days of written warning before that happens.

PTO accrues normally during paid leave. It does not accrue during unpaid leave, and it does not accrue during any period in which the employee is
receiving long-term disability benefit.

401(k) contributions continue from any pay the employee receives, and the company match continues on the same terms. Contributions stop during unpaid
periods and resume automatically on return, at the same rate.

Service for the purpose of tenure, PTO accrual bands and vesting continues to accumulate during every protected leave, paid or unpaid.
</evidence>

<evidence id="c_bac3a6e294c7f82b" kind="retrieval">
s stay active
only so that nothing breaks on their return. Colleagues are asked not to contact them about work, and
managers are accountable for that.

Benefits, PTO accrual, service accumulation and 401(k) contributions all continue unchanged during a
sabbatical, which is paid at 100% of base salary.

An employee may combine a sabbatical with PTO to make a longer break, subject to the ordinary notice
rules for the PTO portion. An employee may not combine a sabbatical with a leave of absence; where the
two would overlap, the leave takes precedence and the sabbatical is rescheduled.
</evidence>

---

## remote-001

**QUESTION**  How many days per week must a hybrid employee work from their assigned office?

**ANSWER**

```
Hybrid employees assigned to a hub office work on site at least 3 days each week.
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_cf43ea100f30ec65" kind="retrieval">
Hybrid employees assigned to a hub office work on site at least 3 days each week. The specific days are set by the team, not by the individual, so that
a team's onsite days overlap and the office time is actually collaborative; most teams anchor on Tuesday, Wednesday and Thursday.

A week containing a company holiday, approved PTO or approved travel reduces the requirement proportionally: an employee who works three days in a
holiday-shortened week is expected on site for two of them. The requirement is measured as a rolling four-week average in MosaicOne rather than week by
week, so a single unusual week is never a compliance problem.

Managers are responsible for the requirement within their team. Persistent, unexplained non-attendance is a performance conversation, not a
disciplinary one, and People Operations expects the manager to ask what is getting in the way before escalating anything.
</evidence>

<evidence id="c_599a663c3479402f" kind="retrieval">
A fully remote arrangement means the employee has no assigned office and works from a home workspace in the United States. The fully-remote cohort is
capped at 25% of United States headcount so that the hub offices stay viable as collaboration spaces, and roles are designated remote-eligible by the
department head with People Operations' agreement.

Fully remote employees are assigned to the `remote-us` office record for calendar and payroll purposes and follow the United States holiday calendar.
They are expected on site at a hub office for at least four working days per quarter — typically a team offsite, a planning week or a hardware
milestone — and the company pays travel and lodging for those visits under the Travel Policy.

There is no fully-remote cohort on the German entity. German employees are assigned to the Berlin office and work hybrid or onsite.
</evidence>

<evidence id="c_3cddc16e5ca0b138" kind="retrieval">
A hybrid arrangement means the employee is assigned to a hub office and splits their working week between that office and a home workspace. Hybrid is
the default arrangement for Engineering, Product, Design, Marketing, Finance and People Operations roles at all three hubs.

A hybrid employee has a permanent desk or a bookable seat in their assigned office, is included in the office's holiday calendar, and is expected to be
reachable during core collaboration hours in that office's time zone regardless of where they are working on a given day.
</evidence>

<evidence id="c_9f6ea967a241b29d" kind="retrieval">
Fully remote employees receive a monthly connectivity stipend of USD 60. The stipend is paid automatically through payroll, requires no claim and no
receipt, and is intended to cover the incremental cost of home internet and mobile data used for work.

Hybrid and onsite employees do not receive the connectivity stipend, because the company provides connectivity at the office. A hybrid employee whose
role requires reliable home connectivity for on-call duty may request the stipend through their manager, and it is granted for the duration of the
on-call assignment.

The stipend is not paid for months in which the employee is on unpaid leave. It continues during paid leave, PTO and approved work abroad.
</evidence>

<evidence id="c_89d50903128314a9" kind="retrieval">
Every employee is issued a standard laptop configured for their role, a power adapter, a headset and a laptop bag. The standard configurations for 2026
are a 14-inch developer laptop with 32 GB of memory for engineering roles, and a 13-inch laptop with 16 GB of memory for all other roles.

Employees whose work requires more — hardware-in-the-loop simulation, large CAD assemblies, video production — are issued a high-specification laptop
or a fixed workstation on their manager's request, with no separate spending approval needed because the machines are on the standard catalogue.

Hybrid and onsite employees receive a monitor, keyboard, mouse and dock at their office desk. Fully remote employees receive the same set for their home
workspace, shipped before their start date. Hybrid employees may request a second set for home; the request is approved routinely for employees whose
recorded arrangement includes at least two remote days a week.
</evidence>

<evidence id="c_1ab470129a180cfa" kind="retrieval">
Mosaic Robotics builds industrial robots. Some of the work — assembly, calibration, field validation, safety certification — can only happen where the
hardware is, and some of it can happen anywhere there is a laptop and a reliable connection. This policy sets out how the company reconciles those two
facts: which work arrangements exist, what each one commits the employee and the company to, and how an arrangement is changed.

It applies to every employee of Mosaic Robotics, Inc. and Mosaic Robotics GmbH. Where an employee wants to work from outside the country their
employment contract is registered in, this policy sets the *people* requirements and the Tax & Location Addendum sets the *tax, payroll and legal*
requirements; both must be satisfied and neither can waive the other.

Mosaic Robotics is hybrid by default. An employee assigned to one of the three hub offices — Austin, Boston and Berlin — is expected on site for part of
each week. A defined fully-remote cohort exists in the United States for roles where physical presence adds nothing. Neither arrangement is a reward or
a sanction: the arrangement follows the role, and it is recorded on the employee record in MosaicOne as `work_arrangement`.
</evidence>

<evidence id="c_3bd7eff626822bf3" kind="retrieval">
This addendum sits underneath the Remote & Hybrid Work Policy and governs the consequences of *where* work is physically performed. The Remote & Hybrid
Work Policy answers whether an arrangement suits the role and the team. This addendum answers whether the company and the employee can lawfully and
affordably carry it.

It applies to every employee of Mosaic Robotics, Inc. and Mosaic Robotics GmbH who intends to perform work from a country other than the one their
employment contract is registered in, and to every permanent relocation across a national border. It also applies to Mosaic Robotics itself: the
thresholds below are the company's obligations as much as the employee's.

Nothing in this addendum is personal tax advice. Mosaic Robotics can describe its own obligations and can tell an employee what the company will and
will not do. It cannot tell an employee what their personal tax return should say, and it does not reimburse personal tax preparation except where the
*Payroll and Withholding* section says so explicitly.

Where this addendum and the Remote & Hybrid Work Policy both set a requirement, both apply. Where they appear to conflict, the stricter requirement
governs and People Operations resolves the conflict in writing.
</evidence>

<evidence id="c_763b799ee8de38d2" kind="retrieval">
**"I am visiting family in Germany for three weeks and would like to work rather than take PTO."** That is
a stay of 21 consecutive days in an approved country. Manager approval under the Remote & Hybrid Work
Policy is enough, requested at least 21 calendar days ahead, and no Tax & Legal review is required. The
device requirements apply in full and the days count against the rolling 90-day annual limit.

**"The same trip, but six weeks."** That is 42 days, over the 30-day threshold, so it needs director
approval and a Tax & Legal review filed at least 21 calendar days before departure. The review will
usually approve it with conditions: a hard end date and a prohibition on customer-facing activity.

**"I want to move to Portugal permanently."** Mosaic Robotics has no Portuguese entity, so a permanent
relocation there is not available. The alternative is a stay inside the 90-day annual limit, or a
conversation about whether the role could be based in Berlin.
</evidence>

<evidence id="c_d4ca7d1a45f75cdd" kind="retrieval">
An onsite arrangement means the employee's regular place of work is a Mosaic Robotics office or facility, and they are expected there on every
scheduled working day. Onsite is the default for Manufacturing, Test & Calibration, Field Service and Facilities roles, and for any role that handles
prototype hardware under export-control or customer-confidentiality obligations.

Onsite employees may work from home occasionally with their manager's agreement — a delivery, a repair visit, a day of focused writing — recorded in
MosaicOne as an ad-hoc remote day. There is no fixed allowance, and no approval is needed for a single day; a pattern of more than four ad-hoc remote
days in a calendar month is a signal that the arrangement itself should be revisited rather than stretched.
</evidence>

<evidence id="c_4142a3cd62ef49dd" kind="retrieval">
A stay of 30 consecutive days or fewer in an approved country requires manager approval under the Remote & Hybrid Work Policy and nothing further from
Tax & Legal. The employee remains on their home payroll, no shadow withholding is set up, and no corporate-tax filing is triggered.

The employee must still hold the right to work in the destination country, must still meet the device and connectivity requirements, and must still
stay inside the company's rolling 90-day annual limit. A short stay is administratively simple; it is not unregulated.

Consecutive days are counted from the first calendar day of presence to the last, inclusive of weekends and holidays. Two trips separated by fewer than
14 days are treated as one continuous stay for the purposes of this threshold, so an employee cannot reset the count with a weekend flight home.
</evidence>

<evidence id="c_598a56bc1ec155da" kind="retrieval">
n there is not available. The alternative is a stay inside the 90-day annual limit, or a
conversation about whether the role could be based in Berlin.

**"I am attending a conference in Japan for four days."** That is business travel under the Travel Policy,
not work from another country. No tenure requirement, no Tax & Legal review, and the days do not count
against the 90-day limit. The device and network requirements still apply.

**"My partner has a two-year posting in Ireland and I want to go with them."** That is a relocation
question rather than a travel question, and Ireland has no Mosaic Robotics entity. People Operations will
look at whether an employer-of-record arrangement is affordable for the role; the honest answer in most
cases is that it is not, and the company says so early rather than late.

**"I did not ask and I have been working from Spain for two months."** Tell mobility@mosaicrobotics.example
today. Unwinding an exposure that is disclosed is administrative; discovering one in an audit two years
later is expensive, and the difference in how the company responds is entirely about the disclosure.
</evidence>

<evidence id="c_9b86a15196bc9c32" kind="retrieval">
This policy covers business travel by employees of Mosaic Robotics, Inc. and Mosaic Robotics GmbH: customer visits, field service calls, supplier
audits, conferences, inter-office visits and team offsites. It sets what may be booked, through which channel, at what cost, and with whose approval.

Business travel is travel undertaken at the company's request or with the company's approval to perform work at a location other than the employee's
normal place of work. It is not the same thing as working from another country, which is governed by the Remote & Hybrid Work Policy and the Tax &
Location Addendum; a trip that begins as travel and turns into a period of remote work needs approvals under both documents.

Submission mechanics, receipt rules and approval thresholds are shared with the Expenses & Reimbursement Policy. This document sets only the additional
caps and rules that travel needs.

Mosaic Robotics ships heavy, calibrated hardware and sends engineers to install it. Field travel is therefore a core operating cost rather than an
occasional perk, and this policy is written to keep it predictable rather than to discourage it.
</evidence>

<evidence id="c_fd324297edd149c0" kind="retrieval">
Domestic arrangements are governed by the Remote & Hybrid Work Policy. Notification and approval are different things, and the table distinguishes them.

| Request | First approver | Second approver | Notice |
|---|---|---|---|
| Ad-hoc remote day (onsite employee) | Direct manager | - | - |
| Work from another US state, up to 10 business days | None (notification only) | - | - |
| Work from another US state, over 10 business days | Direct manager | People Operations | 10 business days |
| Work from another US state, over 30 consecutive days | Direct manager | People Operations | 30 calendar days |
| Change of work arrangement (onsite, hybrid, remote) | Direct manager | Department head | 30 calendar days |
| Work from Alaska, Hawaii or Wyoming | Director | VP People Operations | 30 calendar days |
</evidence>

---

## remote-002

**QUESTION**  What must be in place before an employee works from an approved country for more than 30 consecutive days?

**ANSWER**

```
A stay of more than 30 consecutive days requires three separate approvals before travel begins: manager approval under the Remote & Hybrid Work Policy, director approval (not manager approval), and a Tax & Legal review.

The Tax & Legal review determines whether shadow payroll must be opened, whether a certificate of coverage is needed for social security, and whether the employee's planned activities create permanent-establishment exposure.

Tax & Legal review requests must be filed at least 21 calendar days before departure and must name the destination, exact dates, workspace address and a short description of the work to be performed.

The review has three possible outcomes: Approved (trip proceeds as requested), Approved with conditions (most often a prohibition on customer-facing activity and a hard end date), or Not approved (employee is offered an alternative destination or shorter stay).

The employee must hold the right to work in the destination country for the whole of the requested period. Mosaic Robotics will not sponsor a visa for temporary work abroad.

Work must use a company-managed, full-disk-encrypted laptop with always-on VPN. IT Security must be notified of the destination country at least 5 business days before departure so that conditional-access rules and travel-risk monitoring can be adjusted.

The employee must have completed at least 12 months of continuous service, be in good standing with no active performance improvement plan or open conduct case, and not hold a role with export-control obligations, Restricted data access, or physical prototype access.

Company data may only be processed on company-managed systems and on cloud services IT has approved. Copying company data into personal accounts, personal cloud drives, or third-party services not approved by IT is a policy breach.

Next steps:
- File Tax & Legal review request 21 days ahead
- Obtain director approval before departure
- Notify IT Security 5 business days prior
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_4142a3cd62ef49dd" kind="retrieval">
A stay of 30 consecutive days or fewer in an approved country requires manager approval under the Remote & Hybrid Work Policy and nothing further from
Tax & Legal. The employee remains on their home payroll, no shadow withholding is set up, and no corporate-tax filing is triggered.

The employee must still hold the right to work in the destination country, must still meet the device and connectivity requirements, and must still
stay inside the company's rolling 90-day annual limit. A short stay is administratively simple; it is not unregulated.

Consecutive days are counted from the first calendar day of presence to the last, inclusive of weekends and holidays. Two trips separated by fewer than
14 days are treated as one continuous stay for the purposes of this threshold, so an employee cannot reset the count with a weekend flight home.
</evidence>

<evidence id="c_763b799ee8de38d2" kind="retrieval">
**"I am visiting family in Germany for three weeks and would like to work rather than take PTO."** That is
a stay of 21 consecutive days in an approved country. Manager approval under the Remote & Hybrid Work
Policy is enough, requested at least 21 calendar days ahead, and no Tax & Legal review is required. The
device requirements apply in full and the days count against the rolling 90-day annual limit.

**"The same trip, but six weeks."** That is 42 days, over the 30-day threshold, so it needs director
approval and a Tax & Legal review filed at least 21 calendar days before departure. The review will
usually approve it with conditions: a hard end date and a prohibition on customer-facing activity.

**"I want to move to Portugal permanently."** Mosaic Robotics has no Portuguese entity, so a permanent
relocation there is not available. The alternative is a stay inside the 90-day annual limit, or a
conversation about whether the role could be based in Berlin.
</evidence>

<evidence id="c_b189d36f26fb7c60" kind="retrieval">
Germany, Ireland, the Netherlands, Portugal, Spain, Canada and Mexico are approved destinations for temporary work abroad. The list is maintained by
Tax & Legal and reviewed twice a year; it reflects where the company has an entity, a treaty position it understands, or a low enough exposure to
accept.

A destination not on the list is not automatically refused, but it requires a Tax & Legal assessment that typically takes 30 calendar days rather than
21, and it is more often refused than approved. Employees planning an unlisted destination should raise it early rather than after booking travel.

Work from a country subject to United States or European Union sanctions, or from a country on the company's elevated-risk list maintained by IT
Security, is prohibited outright and no exception process exists.

Approval of a country is not approval of a trip. Every trip needs its own manager approval, and every trip over 30 consecutive days needs its own Tax &
Legal review, regardless of how many colleagues have worked from the same country before.
</evidence>

<evidence id="c_c502ccd2ba5028f5" kind="retrieval">
A stay of more than 30 consecutive days in another country requires a Tax & Legal review before travel begins. The review determines whether shadow
payroll must be opened, whether a certificate of coverage is needed for social security, and whether the employee's planned activities create
permanent-establishment exposure.

Tax & Legal review requests must be filed at least 21 calendar days before departure. The request is raised in MosaicOne alongside the manager approval
and names the destination, the exact dates, the workspace address and a short description of the work the employee will perform while abroad.

A review has one of three outcomes. **Approved** — the trip proceeds as requested. **Approved with conditions** — the trip proceeds with named
restrictions, most often a prohibition on customer-facing activity and a hard end date. **Not approved** — the exposure cannot be managed at a
reasonable cost, and the employee is offered an alternative destination or a shorter stay.

A trip that exceeds 30 consecutive days also requires director approval rather than direct-manager approval, as set out in the Manager Approval Matrix.
Manager approval, director approval and Tax & Legal approval are three separate records and all three must be present before departure.
</evidence>

<evidence id="c_6577bf6f392890bf" kind="retrieval">
Employees must have completed at least 12 months of continuous service to work outside their home country. The requirement applies to temporary work
abroad, not to business travel: attending a customer site or a trade show on company business is governed by the Travel Policy and carries no tenure
requirement.

An employee must be in good standing — no active performance improvement plan and no open conduct case — and must hold the right to work in the
destination country for the period requested. Mosaic Robotics does not sponsor visas for temporary work abroad and does not act as the employer of
record in a country where it has no entity.

Roles with export-control obligations, roles that handle Restricted data as defined in the Security & Acceptable Use Policy, and roles that require
access to physical prototypes are not eligible regardless of tenure.
</evidence>

<evidence id="c_57b2015388bbf7d4" kind="retrieval">
Work performed outside the home country must use a company-managed, full-disk-encrypted laptop with always-on VPN. Personal devices may not be used for
any Mosaic Robotics work outside the home country, including reading email on a phone that is not enrolled in mobile device management.

IT Security must be notified of the destination country at least 5 business days before departure so that conditional-access rules and travel-risk
monitoring can be adjusted. A sign-in from an unexpected country will otherwise be blocked, which is exactly what the control is for.

Employees travelling to a country on the company's elevated-risk list are issued a loaner laptop with a clean profile and are asked to leave their
regular device at home. The elevated-risk list is maintained by IT Security and published in the Security & Acceptable Use Policy's companion pages.

Public and hotel networks are treated as hostile. The Security & Acceptable Use Policy's rules on always-on VPN, screen locks and physical device
custody apply in full and are not relaxed because the employee is on approved travel.
</evidence>

<evidence id="c_e0d1b52d3efced01" kind="retrieval">
A remote workspace must have a wired or wireless connection of at least 50 Mbps download. Employees who cannot meet the threshold at home should speak
to their manager about a coworking allowance rather than working from a connection that makes them inaudible in every meeting.

The workspace must be a place where the employee can hold a confidential conversation, lock their screen when they step away, and keep company hardware
out of reach of other people. Working from a shared coworking space is fine; working from a café for a full day, with Confidential material on screen,
is not.

Home office equipment and furniture are covered by the Expenses & Reimbursement Policy's annual home office allowance, and the standard laptop, monitor
and dock are issued under the Equipment & Asset Policy. Mosaic Robotics does not reimburse home internet service for hybrid employees; fully remote
employees receive the monthly connectivity stipend described in the Expenses & Reimbursement Policy.

Employees are responsible for the safety of their own workspace. People Operations publishes an ergonomic self-assessment in MosaicOne and will fund a
professional assessment where a health need is documented.
</evidence>

<evidence id="c_1ab470129a180cfa" kind="retrieval">
Mosaic Robotics builds industrial robots. Some of the work — assembly, calibration, field validation, safety certification — can only happen where the
hardware is, and some of it can happen anywhere there is a laptop and a reliable connection. This policy sets out how the company reconciles those two
facts: which work arrangements exist, what each one commits the employee and the company to, and how an arrangement is changed.

It applies to every employee of Mosaic Robotics, Inc. and Mosaic Robotics GmbH. Where an employee wants to work from outside the country their
employment contract is registered in, this policy sets the *people* requirements and the Tax & Location Addendum sets the *tax, payroll and legal*
requirements; both must be satisfied and neither can waive the other.

Mosaic Robotics is hybrid by default. An employee assigned to one of the three hub offices — Austin, Boston and Berlin — is expected on site for part of
each week. A defined fully-remote cohort exists in the United States for roles where physical presence adds nothing. Neither arrangement is a reward or
a sanction: the arrangement follows the role, and it is recorded on the employee record in MosaicOne as `work_arrangement`.
</evidence>

<evidence id="c_176702a8d5fb03cf" kind="retrieval">
General questions about work arrangements go to People Operations at people-ops@mosaicrobotics.example. Questions about a specific destination country,
its duration limits or its tax consequences go to mobility@mosaicrobotics.example and to the Tax & Location Addendum. Device and network questions go to
IT Security at it-security@mosaicrobotics.example.
</evidence>

<evidence id="c_0ed1a256c9148ee2" kind="retrieval">
Restricted information is the small set of material where disclosure would cause severe harm: safety
certification evidence for shipped robots, firmware signing keys, credentials, the source data behind an
investigation, and export-controlled technical data. Access is granted individually, is logged, and is
reviewed quarterly. Restricted material never leaves company-managed systems and never travels on a device
taken outside the employee's home country.

Labelling is the author's responsibility. Where a document is unlabelled, treat it as Confidential until its
owner says otherwise.
</evidence>

<evidence id="c_f6640704084ced7f" kind="retrieval">
ering where the data will sit, who can reach it, how it is encrypted, how it is deleted and what
the supplier's own breach notification commitment is. Confidential and Restricted data may only be
processed by suppliers who have passed that review and signed the company's data processing agreement.

Customer data that reaches Mosaic Robotics as part of a field service or integration engagement is treated
as Confidential at minimum, is held only for as long as the engagement needs it, and is returned or
destroyed at its end with a written confirmation to the customer.

Suppliers do not connect their own devices to Mosaic Robotics production networks. A guest network is
provided for visitors, and any device that must reach a production system is provided and managed by IT.
</evidence>

<evidence id="c_fda4f4779ad55565" kind="retrieval">
Company systems are provided for company work. Reasonable personal use is permitted and expected: reading the
news at lunch, booking a dentist appointment, messaging a family member. The test is whether the use is
occasional, lawful, and does not interfere with work or with anyone else's.

The following are never acceptable on a company system or network: accessing or storing unlawful material;
harassing, threatening or defaming anyone; infringing copyright, including downloading pirated software or
media; running a private business; mining cryptocurrency; attempting to bypass a security control; scanning or
probing a network the company does not own; and installing software that has not been approved by IT.

Company data may only be processed on company-managed systems and on the cloud services IT has approved.
Copying company data into a personal account, a personal cloud drive, a personal note-taking application or a
third-party artificial-intelligence service that IT has not approved is a policy breach, whatever the
intention behind it.
</evidence>

<evidence id="c_fae6eb1a11ba443a" kind="retrieval">
Tax and legal questions about working abroad go to tax-legal@mosaicrobotics.example. Mobility logistics, approvals and destination questions go to
mobility@mosaicrobotics.example. Device, network and travel-risk questions go to it-security@mosaicrobotics.example. General questions about work
arrangements go to people-ops@mosaicrobotics.example.
</evidence>

<evidence id="c_cceb27b487508cbd" kind="retrieval">
The employee is responsible for holding the right to be present and to work in the destination country for the whole of the requested period. Mosaic
Robotics will confirm employment, provide a letter of assignment and pay for the assignment letter's notarisation where required, and will not sponsor
a visa for temporary work abroad.

An employee who is refused entry, whose permission expires mid-trip, or who is told by an immigration officer that their activity is not permitted must
stop working immediately and contact mobility@mosaicrobotics.example. Continuing to work in that situation puts both the employee and the company at
risk and is treated as a serious matter.

Non-citizens working in the United States on a company-sponsored visa should assume that any period abroad has immigration consequences at home, and
must speak to People Operations before requesting a trip of any length. The rules governing re-entry are stricter than the rules governing departure.
</evidence>

<evidence id="c_f2519389927a580b" kind="retrieval">
Three separate legal systems attach to the physical location of work, and they do not share a single threshold.

**Immigration** asks whether the person has the right to be present and to work. It is binary and it is the destination country's decision. A tourist
entry that permits remote work for a foreign employer in one country is a criminal matter in another, and neither Mosaic Robotics nor the employee can
negotiate it.

**Payroll and personal tax** ask which authority is owed withholding on the employee's earnings, and from which day. Some countries begin at the first
day of presence, most apply a treaty-based day count, and a few look at where the economic employer sits rather than where the person is.

**Corporate tax** asks whether the employee's activity creates a taxable presence — a *permanent establishment* — for Mosaic Robotics in the destination
country. This is the risk with the largest financial consequence and the one an employee is least likely to have considered, because it depends on what
the employee *does* rather than on how long they stay.

The thresholds in this addendum are set conservatively against all three, which is why they are shorter than the day counts an employee may find in a
tax treaty.
</evidence>

---

## remote-003

**QUESTION**  I am thinking about working from Ireland from 1 October to 20 October 2026. Does that need Tax & Legal review?

**ANSWER**

```
A stay of 30 consecutive days or fewer in an approved country requires manager approval under the Remote & Hybrid Work Policy and nothing further from Tax & Legal.

Your trip is 20 consecutive days, which is under the 30-day threshold.

Ireland is an approved destination for temporary work abroad.

Work abroad of up to 30 consecutive days in an approved country requires written manager approval at least 21 calendar days before departure, with the direct manager as the approver.

Recommendation — not company policy: Raise the request in MosaicOne under 'Work from another country', naming the destination, exact dates, and workspace address.

You must use a company-managed, full-disk-encrypted laptop with always-on VPN, and IT Security must be notified of Ireland at least 5 business days before departure.

Recommendation — not company policy: Confirm with IT Security that your travel laptop meets the encryption and VPN requirements before you depart.

Company-managed laptop with full-disk encryption and always-on VPN: not verified from your record — confirm before you proceed.

Your request goes to Dana, your direct manager.

Next steps:
- Request manager approval in MosaicOne by 10 September.
- Notify IT Security of your Ireland destination by 24 September.
- Verify your laptop has full-disk encryption and always-on VPN enabled.
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_4142a3cd62ef49dd" kind="retrieval">
A stay of 30 consecutive days or fewer in an approved country requires manager approval under the Remote & Hybrid Work Policy and nothing further from
Tax & Legal. The employee remains on their home payroll, no shadow withholding is set up, and no corporate-tax filing is triggered.

The employee must still hold the right to work in the destination country, must still meet the device and connectivity requirements, and must still
stay inside the company's rolling 90-day annual limit. A short stay is administratively simple; it is not unregulated.

Consecutive days are counted from the first calendar day of presence to the last, inclusive of weekends and holidays. Two trips separated by fewer than
14 days are treated as one continuous stay for the purposes of this threshold, so an employee cannot reset the count with a weekend flight home.
</evidence>

<evidence id="c_c502ccd2ba5028f5" kind="retrieval">
A stay of more than 30 consecutive days in another country requires a Tax & Legal review before travel begins. The review determines whether shadow
payroll must be opened, whether a certificate of coverage is needed for social security, and whether the employee's planned activities create
permanent-establishment exposure.

Tax & Legal review requests must be filed at least 21 calendar days before departure. The request is raised in MosaicOne alongside the manager approval
and names the destination, the exact dates, the workspace address and a short description of the work the employee will perform while abroad.

A review has one of three outcomes. **Approved** — the trip proceeds as requested. **Approved with conditions** — the trip proceeds with named
restrictions, most often a prohibition on customer-facing activity and a hard end date. **Not approved** — the exposure cannot be managed at a
reasonable cost, and the employee is offered an alternative destination or a shorter stay.

A trip that exceeds 30 consecutive days also requires director approval rather than direct-manager approval, as set out in the Manager Approval Matrix.
Manager approval, director approval and Tax & Legal approval are three separate records and all three must be present before departure.
</evidence>

<evidence id="c_7bd4fd63c0658168" kind="retrieval">
An employee working abroad remains on their home payroll unless Tax & Legal open a shadow payroll. Shadow payroll reports the same earnings to a second
authority so that withholding can be remitted where it is owed; it does not change the employee's net pay, though it usually changes the timing of
their personal filings.

Presence of more than 183 days in a calendar year in a single foreign country generally creates personal tax residency there. The 183-day figure is a
common treaty threshold and not a promise: several countries apply shorter tests, and the company's own 90-day limit is set well below it precisely so
that no employee stumbles across the line by accident.

Where a company-directed assignment causes an employee to owe tax in two countries on the same earnings, Mosaic Robotics funds tax-equalisation support
through its external provider. Where an employee-requested trip does the same, the employee is responsible for their own filings and the company will
supply the payroll records needed to complete them.

Social security is handled separately from income tax. For stays in countries with a totalisation agreement, Tax & Legal obtain a certificate of
coverage so that contributions continue in the home system; without one, the employee and the company may both owe contributions twice.
</evidence>

<evidence id="c_0d2c84e4df38b6a0" kind="retrieval">
International remote work of more than 30 days requires approval from the employee's director and from Tax & Legal. Shorter stays are a direct-manager
decision, and every stay of any length must satisfy the device and connectivity requirements in the Security & Acceptable Use Policy.

| Request | First approver | Second approver | Notice |
|---|---|---|---|
| Work abroad, up to 30 consecutive days, approved country | Direct manager | - | 21 calendar days |
| Work abroad, more than 30 consecutive days | Director | Tax & Legal | 21 calendar days |
| Work abroad, destination not on the approved list | Director | Tax & Legal | 30 calendar days |
| Extension of an approved stay | Director | Tax & Legal | Before the approved end date |
| Permanent relocation to another country | VP People Operations | Tax & Legal | 60 calendar days |
| International business travel (Travel Policy) | Direct manager | - | 14 calendar days |

The Tax & Location Addendum sets the thresholds behind this table and explains why the 30-day line sits where it does. The addendum, not this matrix, is
the authority on whether a particular destination and duration are workable.
</evidence>

<evidence id="c_64fbd63786de81d4" kind="retrieval">
Written manager approval must be obtained at least 21 calendar days before departure. The request is raised in MosaicOne under *Work from another
country*, names the destination, the exact start and end dates, and the address of the workspace the employee will use.

Approval is a two-step gate. The direct manager approves the working arrangement — coverage, meeting overlap, on-call implications. Where the stay
exceeds the threshold set in the Tax & Location Addendum, Tax & Legal must also review and approve before travel begins, and the Manager Approval
Matrix routes the request to a director rather than the direct manager.

Approval is granted for a specific destination and a specific date range. Extending the stay requires a new approval, requested before the approved end
date; returning early requires nothing beyond updating the record so the rolling 90-day count stays accurate.

International mobility questions go to People Operations at mobility@mosaicrobotics.example. The mobility team, not the manager, is the owner of any
question about whether a particular destination or duration is workable.
</evidence>

<evidence id="c_b189d36f26fb7c60" kind="retrieval">
Germany, Ireland, the Netherlands, Portugal, Spain, Canada and Mexico are approved destinations for temporary work abroad. The list is maintained by
Tax & Legal and reviewed twice a year; it reflects where the company has an entity, a treaty position it understands, or a low enough exposure to
accept.

A destination not on the list is not automatically refused, but it requires a Tax & Legal assessment that typically takes 30 calendar days rather than
21, and it is more often refused than approved. Employees planning an unlisted destination should raise it early rather than after booking travel.

Work from a country subject to United States or European Union sanctions, or from a country on the company's elevated-risk list maintained by IT
Security, is prohibited outright and no exception process exists.

Approval of a country is not approval of a trip. Every trip needs its own manager approval, and every trip over 30 consecutive days needs its own Tax &
Legal review, regardless of how many colleagues have worked from the same country before.
</evidence>

<evidence id="c_598a56bc1ec155da" kind="retrieval">
n there is not available. The alternative is a stay inside the 90-day annual limit, or a
conversation about whether the role could be based in Berlin.

**"I am attending a conference in Japan for four days."** That is business travel under the Travel Policy,
not work from another country. No tenure requirement, no Tax & Legal review, and the days do not count
against the 90-day limit. The device and network requirements still apply.

**"My partner has a two-year posting in Ireland and I want to go with them."** That is a relocation
question rather than a travel question, and Ireland has no Mosaic Robotics entity. People Operations will
look at whether an employer-of-record arrangement is affordable for the role; the honest answer in most
cases is that it is not, and the company says so early rather than late.

**"I did not ask and I have been working from Spain for two months."** Tell mobility@mosaicrobotics.example
today. Unwinding an exposure that is disclosed is administrative; discovering one in an audit two years
later is expensive, and the difference in how the company responds is entirely about the disclosure.
</evidence>

<evidence id="c_57b2015388bbf7d4" kind="retrieval">
Work performed outside the home country must use a company-managed, full-disk-encrypted laptop with always-on VPN. Personal devices may not be used for
any Mosaic Robotics work outside the home country, including reading email on a phone that is not enrolled in mobile device management.

IT Security must be notified of the destination country at least 5 business days before departure so that conditional-access rules and travel-risk
monitoring can be adjusted. A sign-in from an unexpected country will otherwise be blocked, which is exactly what the control is for.

Employees travelling to a country on the company's elevated-risk list are issued a loaner laptop with a clean profile and are asked to leave their
regular device at home. The elevated-risk list is maintained by IT Security and published in the Security & Acceptable Use Policy's companion pages.

Public and hotel networks are treated as hostile. The Security & Acceptable Use Policy's rules on always-on VPN, screen locks and physical device
custody apply in full and are not relaxed because the employee is on approved travel.
</evidence>

<evidence id="c_763b799ee8de38d2" kind="retrieval">
**"I am visiting family in Germany for three weeks and would like to work rather than take PTO."** That is
a stay of 21 consecutive days in an approved country. Manager approval under the Remote & Hybrid Work
Policy is enough, requested at least 21 calendar days ahead, and no Tax & Legal review is required. The
device requirements apply in full and the days count against the rolling 90-day annual limit.

**"The same trip, but six weeks."** That is 42 days, over the 30-day threshold, so it needs director
approval and a Tax & Legal review filed at least 21 calendar days before departure. The review will
usually approve it with conditions: a hard end date and a prohibition on customer-facing activity.

**"I want to move to Portugal permanently."** Mosaic Robotics has no Portuguese entity, so a permanent
relocation there is not available. The alternative is a stay inside the 90-day annual limit, or a
conversation about whether the role could be based in Berlin.
</evidence>

<evidence id="c_864fb910f46475a7" kind="retrieval">
No employee may work outside their home country for more than 90 days in a rolling 12-month period. The 90-day figure is a company limit and is
independent of any shorter limit imposed by the destination country's immigration rules, which always take precedence.

Days are counted as calendar days of presence, including weekends and company holidays that fall inside the trip. A trip that begins on 3 November and
ends on 14 December counts as 42 days.

Separate trips inside the rolling window are added together. An employee who spent 55 days abroad in March and April may take no more than 35 further
days before the March allocation begins to roll off.
</evidence>

<evidence id="c_6577bf6f392890bf" kind="retrieval">
Employees must have completed at least 12 months of continuous service to work outside their home country. The requirement applies to temporary work
abroad, not to business travel: attending a customer site or a trade show on company business is governed by the Travel Policy and carries no tenure
requirement.

An employee must be in good standing — no active performance improvement plan and no open conduct case — and must hold the right to work in the
destination country for the period requested. Mosaic Robotics does not sponsor visas for temporary work abroad and does not act as the employer of
record in a country where it has no entity.

Roles with export-control obligations, roles that handle Restricted data as defined in the Security & Acceptable Use Policy, and roles that require
access to physical prototypes are not eligible regardless of tenure.
</evidence>

<evidence id="c_946583143faa41f3" kind="retrieval">
A change of work arrangement must be requested at least 30 calendar days before the intended effective date. The request is made in MosaicOne, states
the requested arrangement and the reason, and is routed to the direct manager and then to the department head.

The company evaluates a change request against three questions: whether the role can be performed under the requested arrangement, whether the team's
collaboration pattern survives it, and whether the change creates a payroll, tax or immigration obligation the company is not already carrying. The
third question is answered by People Operations against the Tax & Location Addendum, not by the manager.

A refused request is answered in writing with the reason and, where the obstacle is fixable, what would need to change. An employee may re-request after
90 days, or sooner if the circumstances that caused the refusal have changed.

A change of arrangement that also changes the employee's work location across a state or national border is treated as a relocation and follows the Tax
& Location Addendum's notice periods, which are longer than the 30 calendar days above.
</evidence>

<evidence id="c_bed326a7d15c0d80" kind="retrieval">
Every company laptop must have full-disk encryption enabled and a screen lock of 10 minutes or less. Both
settings are enforced by the device management platform and cannot be turned off locally; a device that
reports them as disabled loses network access until IT restores them.

Devices must run a supported operating system version and must apply security updates within 14 calendar days
of release. Critical updates flagged by IT Security are applied within 72 hours, and a device that has not
applied one is disconnected from company services until it has.

The endpoint protection agent, the device management agent and the company certificate must all be present and
healthy. Removing or disabling any of them is treated as a deliberate breach rather than a technical fault.

Company devices are for the use of the person they are issued to. Family members, housemates and colleagues do
not use them, and no company device is left unlocked and unattended in a place the employee does not control.

Personal devices may access company email and chat only when enrolled in mobile device management with a
device passcode, encryption and remote wipe enabled. No other company system may be reached from a personal
device, and no company file may be stored on one.
</evidence>

<evidence id="c_21fb57a686af7f30" kind="retrieval">
Always-on VPN is required whenever a company device connects to a network that Mosaic Robotics does not
control. That includes home networks, hotel and airport networks, customer guest networks, mobile hotspots and
coworking spaces.

Screens showing Confidential or Restricted material are not visible to other people. Privacy filters are
issued on request and are expected on any device used regularly in transit. Confidential conversations do not
happen on a train, in an open café or in a shared lounge.

Devices are never left unattended in a public place, never checked into hold luggage, and never left visible
in a parked vehicle. A hotel room safe is acceptable for short periods; a hotel room desk is not.

Employees travelling to a country on the elevated-risk list maintained by IT Security are issued a loaner
laptop with a clean profile and no cached credentials, and leave their regular device at home. The list is
published in MosaicOne and is reviewed quarterly.

The device and connectivity requirements for working outside the home country in the Remote & Hybrid Work
Policy sit on top of this section and are not relaxed by approval to travel.
</evidence>

<evidence id="c_d528eb9e64c1eaf4" kind="retrieval">
USB storage devices are blocked by default on company laptops. Where a role genuinely needs one - transferring
a firmware image to an isolated test cell, recovering data from a customer machine - IT issues a
hardware-encrypted device, records it in the asset register, and enables it for that laptop only.

Company data is stored in the approved cloud platforms and nowhere else. Approved platforms are listed in
MosaicOne and are the only ones covered by the company's backup, retention and legal-hold arrangements. A file
that exists only on a laptop is not backed up and is one hardware failure away from gone.

Sharing links from approved platforms default to named recipients inside the company. Creating a
publicly-accessible link to Confidential or Restricted material requires the data owner's approval, an expiry
date and a documented reason.

Personal cloud accounts, personal email, personal messaging applications and unapproved artificial-intelligence
services are not places company data may go. This is the single most common accidental breach at companies of
this size, and it is almost always well-intentioned.
</evidence>

<evidence id="c_3c0eba56eda3852a" kind="retrieval">
International business travel requires manager approval before booking and, for destinations outside the approved-country list in the Tax & Location
Addendum, a note to mobility@mosaicrobotics.example so that the trip is visible to the mobility team.

A business trip of 30 consecutive days or fewer does not trigger the Tax & Legal review that the Tax & Location Addendum requires for *working* from
another country, provided the traveller's activity is genuinely travel — meetings, installation, training, a conference — and not the ordinary conduct
of their role from a foreign desk. Where a trip's character is unclear, the mobility team decides, not the traveller.

The device and network requirements in the Security & Acceptable Use Policy apply in full to international travel. IT Security must be notified of the
destination country at least 5 business days before departure, and travellers to countries on the elevated-risk list are issued a loaner laptop.
</evidence>

<evidence id="check_policy_compliance#1" kind="compliance">
{"scenario": "international_remote", "verdict": "conditional", "as_of": "2026-09-01", "submitted_on": "2026-09-22", "computed": {"as_of": "2026-09-01", "submitted_on": "2026-09-22", "start_date": "2026-10-01", "end_date": "2026-10-20", "tenure_days": 1388, "tenure_months_at_as_of": 45, "notice_business_days": 6, "notice_calendar_days": 9, "notice_span": "Tuesday 22 September to Thursday 1 October: 6 business days' notice", "business_days": 14, "business_day_span": "Thursday 1 October to Tuesday 20 October: 14 business days", "duration_days": 20, "overlaps_blackout": false, "span_end": "2026-10-20", "benefits_eligibility_date": "2023-02-11", "benefits_election_deadline": "2023-03-13"}, "requirements": [{"id": "remote.intl.tenure", "text": "Employees need at least 12 months of continuous service to work outside their home country.", "met": true, "status": "met", "blocking": true, "reason": "employee.tenure_months_at_as_of is 45; the policy value is 12 (gte).", "label": "continuous service, in months", "fact_key": "remote.international.eligibility_tenure_months", "evidence": {"chunk_id": "c_6577bf6f392890bf", "doc_id": "remote-and-hybrid-work", "heading_path": "Working Outside Your Home Country > Eligibility", "snippet": "Employees must have completed at least 12 months of continuous service to work outside their home country. The requirement applies to temporary work\nabroad, not to business travel: attending a customer site or a trade show on company business is governed by the Travel Policy and carries no tenure\nre"}}, {"id": "remote.intl.duration", "text": "Stays over 30 consecutive days require Tax & Legal review.", "met": true, "status": "met", "blocking": false, "reason": "parameters.duration_days is 20; the policy value is 30 (lte).", "label": "stay abroad, in consecutive days", "fact_key": "remote.international.threshold_days", "evidence": {"chunk_id": "c_c502ccd2ba5028f5", "doc_id": "tax-and-location-addendum", "heading_path": "Duration Thresholds > Stays Exceeding 30 Days", "snippet": "A stay of more than 30 consecutive days in another country requires a Tax & Legal review before travel begins. The review determines whether shadow\npayroll must be opened, whether a certificate of coverage is needed for social security, and whether the employee's planned activities create\npermanent-"}}, {"id": "remote.intl.annual_limit", "text": "No more than 90 days outside the home country in a rolling 12-month period.", "met": true, "status": "met", "blocking": true, "reason": "parameters.duration_days is 20; the policy value is 90 (lte).", "label": "days outside the home country in the rolling year", "fact_key": "remote.international.max_days_per_year", "evidence": {"chunk_id": "c_864fb910f46475a7", "doc_id": "remote-and-hybrid-work", "heading_path": "Working Outside Your Home Country > Duration Limits", "snippet": "No employee may work outside their home country for more than 90 days in a rolling 12-month period. The 90-day figure is a company limit and is\nindependent of any shorter limit imposed by the destination country's immigration rules, which always take precedence.\n\nDays are counted as calendar days of"}}, {"id": "remote.intl.destination", "text": "The destination must be on the approved-country list.", "met": true, "status": "met", "blocking": false, "reason": "parameters.destination_country is IE; the policy value is DE,IE,NL,PT,ES,CA,MX (in).", "label": "destination country", "fact_key": "tax.approved_countries", "evidence": {"chunk_id": "c_b189d36f26fb7c60", "doc_id": "tax-and-location-addendum", "heading_path": "Approved Countries", "snippet": "Germany, Ireland, the Netherlands, Portugal, Spain, Canada and Mexico are approved destinations for temporary work abroad. The list is maintained by\nTax & Legal and reviewed twice a year; it reflects where the company has an entity, a treaty position it understands, or a low enough exposure to\naccep"}}, {"id": "remote.intl.manager_notice", "text": "Written manager approval at least 21 calendar days before departure.", "met": false, "status": "unmet", "blocking": false, "reason": "computed.notice_calendar_days is 9; the policy value is 21 (gte).", "label": "notice to your manager before departure, in calendar days", "fact_key": "remote.international.manager_notice_days", "evidence": {"chunk_id": "c_64fbd63786de81d4", "doc_id": "remote-and-hybrid-work", "heading_path": "Working Outside Your Home Country > Approval", "snippet": "Written manager approval must be obtained at least 21 calendar days before departure. The request is raised in MosaicOne under *Work from another\ncountry*, names the destination, the exact start and end dates, and the address of the workspace the employee will use.\n\nApproval is a two-step gate. The"}}, {"id": "remote.intl.device", "text": "A company-managed, full-disk-encrypted laptop with always-on VPN is mandatory.", "met": false, "status": "not_stated", "blocking": false, "reason": "Not verifiable from the synthetic record; confirm before proceeding.", "label": "company-managed laptop with full-disk encryption and always-on VPN", "fact_key": "remote.international.device_requirement", "evidence": {"chunk_id": "c_57b2015388bbf7d4", "doc_id": "remote-and-hybrid-work", "heading_path": "Working Outside Your Home Country > Device and Connectivity Requirements", "snippet": "Work performed outside the home country must use a company-managed, full-disk-encrypted laptop with always-on VPN. Personal devices may not be used for\nany Mosaic Robotics work outside the home country, including reading email on a phone that is not enrolled in mobile device management.\n\nIT Security"}}, {"id": "remote.intl.no_contract_signing", "text": "No contracts may be signed or customer agreements negotiated while abroad.", "met": true, "status": "met", "blocking": false, "reason": "Standing rule; False applies whatever the request says.", "label": "customer-facing activity while abroad", "fact_key": "tax.pe_risk.no_contract_signing", "evidence": {"chunk_id": "c_b2664838607c21cd", "doc_id": "tax-and-location-addendum", "heading_path": "Permanent Establishment Risk", "snippet": "A permanent establishment is a taxable presence that a company creates in a country by having a fixed place of business there, or by having a person\nthere who habitually concludes contracts on its behalf. Creating one exposes Mosaic Robotics to corporate tax, filing obligations and penalties in that"}}], "unmet": ["remote.intl.manager_notice"], "approvals_required": [{"role": "Direct manager", "reason": "Every stay abroad needs written manager approval.", "doc_id": "manager-approval-matrix", "heading_path": "Remote Work > International"}], "approvers": [{"role": "Direct manager", "employee_id": "E1007", "name": "Dana", "title": "Director, Engineering", "self_approval_routed": false}], "next_steps": ["Raise the request in MosaicOne under 'Work from another country' with the exact dates and workspace address.", "Obtain written manager approval at least 21 calendar days before departure.", "Confirm with IT Security that the travel laptop is company-managed, encrypted and on always-on VPN."], "escalate_to": "People Operations — mobility@mosaicrobotics.example", "citations": [{"chunk_id": "c_6577bf6f392890bf", "doc_id": "remote-and-hybrid-work", "heading_path": "Working Outside Your Home Country > Eligibility"}, {"chunk_id": "c_c502ccd2ba5028f5", "doc_id": "tax-and-location-addendum", "heading_path": "Duration Thresholds > Stays Exceeding 30 Days"}, {"chunk_id": "c_864fb910f46475a7", "doc_id": "remote-and-hybrid-work", "heading_path": "Working Outside Your Home Country > Duration Limits"}, {"chunk_id": "c_b189d36f26fb7c60", "doc_id": "tax-and-location-addendum", "heading_path": "Approved Countries"}, {"chunk_id": "c_64fbd63786de81d4", "doc_id": "remote-and-hybrid-work", "heading_path": "Working Outside Your Home Country > Approval"}, {"chunk_id": "c_57b2015388bbf7d4", "doc_id": "remote-and-hybrid-work", "heading_path": "Working Outside Your Home Country > Device and Connectivity Requirements"}, {"chunk_id": "c_b2664838607c21cd", "doc_id": "tax-and-location-addendum", "heading_path": "Permanent Establishment Risk"}, {"chunk_id": "c_0d2c84e4df38b6a0", "doc_id": "manager-approval-matrix", "heading_path": "Remote Work > International"}], "rules_version": "2026.1"}
</evidence>

<evidence id="lookup_employee_profile#1" kind="structured_data">
{"employee_id": "E1042", "as_of": "2026-09-01", "preferred_name": "Priya", "legal_name": "Priya Raghavan", "title": "Senior Robotics Engineer", "department": "Engineering", "employment_type": "full_time", "fte": 1.0, "level": "L5", "hire_date": "2022-11-13", "tenure_months_at_as_of": 45, "tenure": "3 years 9 months", "work_arrangement": "hybrid", "work_country": "US", "office": {"office_id": "bos", "city": "Boston", "country": "US", "timezone": "America/New_York", "entity": "Mosaic Robotics, Inc."}, "manager": {"employee_id": "E1007", "preferred_name": "Dana", "title": "Director, Engineering"}, "skip_level": {"employee_id": "E1002", "preferred_name": "Miguel", "title": "VP Engineering"}, "approvers": [{"role": "Direct manager", "employee_id": "E1007", "name": "Dana", "title": "Director, Engineering", "self_approval_routed": false}]}
</evidence>

---
