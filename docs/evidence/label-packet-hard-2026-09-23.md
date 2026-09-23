# Blind groundedness labelling packet

Run `r_1790130220_baseline` · dataset sha `2c8973147744a351…` · subset `B` · 8 items.

These items were selected from a finished run by a criterion that is recorded in the project's artifacts and **deliberately withheld from this packet**. It tells you nothing about which verdict is correct for any item, and it is not a hint: treat every item below as an independent decision on its own evidence, exactly as you would in a random sample. They are listed in item-id order.

You are the reference labeller for spec §13.7. For each item below decide **one binary verdict**
about the ANSWER, using ONLY the EVIDENCE shown with it:

* `grounded` — every statement of company policy in the answer is supported by the passages shown;
* `not_grounded` — at least one is not.

The evidence comes in four classes, and they all count. `kind="retrieval"` is a policy passage the
assistant searched up; `kind="section"` is one it fetched in full; `kind="compliance"` is the
deterministic rule engine's own requirement evidence; and `kind="structured_data"` is a record it
read about this employee — a PTO balance, a benefits eligibility date, a profile. **A claim is
supported if ANY item of ANY class supports it**: a correct fact taken from the employee's own
record is grounded, not invented. Decide against this set alone — outside knowledge and plausibility
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

Retirement plan eligibility is different: an employee may begin contributing to the 401(k) plan from their first payroll run, with no waiting period at all.

Life insurance cover begins when the medical waiting period ends.

The waiting period is not restarted by an internal transfer, a promotion, or a change from part-time to full-time status. It is restarted by a break in service of more than 26 weeks.

Next steps:
- Enroll in benefits during week one of onboarding
- Check MosaicOne Benefits when your 90 days end
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

<evidence id="c_0df5d11cd585014f" kind="retrieval">
Benefits questions go to People Operations at benefits@mosaicrobotics.example. Eligibility and waiting-period questions, and anything involving a
dependent's documentation, go to the same address. Claims disputes with a carrier are escalated by People Operations on the employee's behalf where the
carrier's own appeal has failed. Payroll deduction questions go to payroll@mosaicrobotics.example.
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

<evidence id="c_492c8f3d3327af90" kind="retrieval">
Dependent children may remain on a Mosaic Robotics medical plan until the end of the month in which they turn 26. Dental and vision plans follow the
same rule.

Eligible dependents are a legal spouse, a registered domestic partner, a biological or adopted child, a stepchild, and a child for whom the employee
has legal guardianship. Documentation is required within 60 days of adding a dependent; a dependent whose documentation is not supplied is removed from
coverage retroactively to the date they were added.

A child of any age who is incapable of self-support because of a disability that began before age 26 may remain covered indefinitely, subject to the
carrier's certification.
</evidence>

---

## benefits-002

**QUESTION**  When does my benefits waiting period end, and how long is that waiting period under the policy?

**ANSWER**

```
Your benefits waiting period ends on 13 November 2026.

New hires become eligible for medical, dental and vision coverage 90 days after their hire date. Coverage begins on the day the waiting period ends.

Recommendation — not company policy: You have 30 days from 13 November to make your benefits elections in MosaicOne. If you make no election within that window, you will be enrolled in employee-only coverage on the standard medical plan by default and may not change it until the next open enrollment or a qualifying life event.

Next steps:
- Review plan options in MosaicOne by 13 December
- Contact benefits@mosaicrobotics.example with questions
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

<evidence id="c_a44f7da2b160c7a3" kind="retrieval">
Mosaic Robotics matches 100% of the first 4% of eligible compensation contributed to the 401(k) plan. An employee contributing 4% or more therefore
receives the full match; an employee contributing 2% receives a 2% match.

Employer matching contributions vest after 2 years of service. Employee contributions are always immediately and fully vested, because they are the
employee's own money.

Both traditional pre-tax and Roth after-tax contributions are available, and an employee may split between them. Contribution rate changes take
effect on the next payroll run and may be made as often as the employee wishes.

New hires are automatically enrolled at a 4% pre-tax contribution rate 30 days after their start date unless they opt out or choose a different
rate. The automatic rate increases by one percentage point each January until it reaches 10%; an employee may switch the escalation off at any time.

Loans and hardship withdrawals are available under the terms of the plan document. Rollovers into the plan from a previous employer are accepted at
any time.
</evidence>

<evidence id="c_8531e5a0f775e247" kind="retrieval">
An employee moving to a materially different role inside Mosaic Robotics gets a shortened version of this
programme, because the company parts are already familiar and the team parts are not.

The receiving manager writes a 30-60-90 plan exactly as they would for an external hire. Skipping it is
the single most common failure in internal moves: everyone assumes the person already knows how things
work, and the person is too experienced to feel able to ask.

Access changes are handled by IT on the transfer date rather than before it. The employee keeps their
laptop, their MosaicOne account and their tenure; what changes is their cost centre, their reporting line
and their system access, all of which are updated in one transaction so nothing is left dangling.

Internal movers are paired with a buddy on the new team for four weeks, half the external programme. The
30-day survey is sent, because the aggregate results for internal moves are consistently worse than for
external hires and the company would like to know why.

An internal move does not restart the benefits waiting period, does not reset the PTO service band, and
does not affect the performance cycle. A move that happens within 60 days of the annual review is rated by
the previous manager with input from the new one.
</evidence>

<evidence id="c_040b260dec0803c8" kind="retrieval">
Mosaic Robotics offers a paid sabbatical of 4 consecutive weeks to every employee who reaches 5 years of
continuous service, and again at each subsequent five-year anniversary. The sabbatical is in addition to
PTO and does not draw down any balance.

Eligibility is checked automatically in MosaicOne on the service anniversary, and the employee is
notified. The sabbatical must be taken within 24 months of the anniversary or it lapses; it cannot be
banked, deferred indefinitely, or exchanged for pay.

A sabbatical is requested at least 90 calendar days in advance so that coverage can be planned properly.
The manager and the department head agree the dates; the entitlement itself is not discretionary and is
never refused, only scheduled.

The point of a sabbatical is a genuine break, so an employee on sabbatical is removed from on-call
rotations, from meeting invitations and from routine distribution lists, and their accounts stay active
only so that nothing breaks on their return. Colleagues are asked not to contact them about work, and
managers are accountable for that.
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

<evidence id="c_9948839107acfaaf" kind="retrieval">
PTO requests of any length are approved by the employee's direct manager. Longer requests and requests overlapping a blackout period additionally
require director approval, and the notice periods below come from the PTO & Holidays Policy.

| Request | First approver | Second approver | Notice |
|---|---|---|---|
| PTO up to 5 consecutive business days | Direct manager | - | 5 business days |
| PTO of 6 to 15 consecutive business days | Direct manager | - | 15 business days |
| PTO of more than 15 consecutive business days | Direct manager | Director | 15 business days |
| PTO overlapping a declared blackout period | Direct manager | Director | 5 business days |
| Floating holiday | Direct manager | - | 5 business days |
| Sick time (retroactive entry) | Direct manager | - | - |
| Leave of absence (any type) | People Operations | - | 30 calendar days if foreseeable |

A leave of absence is not a manager decision. The manager is notified and plans coverage; People Operations approves the leave against the entitlement
in the Leave of Absence Policy.
</evidence>

<evidence id="lookup_benefits_status#1" kind="structured_data">
{"employee_id": "E1108", "plan_year": 2026, "as_of": "2026-09-01", "eligible": false, "eligibility_reason": "90-day waiting period ends 2026-11-13", "waiting_period_ends": "2026-11-13", "elections": [], "dependents": 0, "open_enrollment_window": {"open": "2026-11-01", "close": "2026-11-21"}, "qualifying_life_event_window_open": false, "policy_doc_id": "benefits-and-open-enrollment"}
</evidence>

---

## conduct-001

**QUESTION**  What are the published timelines for a workplace conduct case: acknowledgement, investigation, and the response target for a severity-1 case?

**ANSWER**

```
People Operations acknowledges every reported concern within 2 business days. The acknowledgement names the person who will handle the case, explains the process, and sets out what the reporter can expect to be told and when.

Investigations are targeted for completion within 30 calendar days of the report. Where an investigation will take longer, the reporter and the respondent are both told, in writing, why and when to expect the outcome.

Severity 1 cases receive a response within 4 business hours.

Response means a named human being contacting the person who raised the case, acknowledging what was raised, naming who owns it and describing what happens next.

Next steps:
- Contact Employee Relations for your specific case status.
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

<evidence id="c_ac1bc3eaad309133" kind="retrieval">
Suspected security incidents must be reported to IT Security within 1 hour of discovery. The report is made
through the MosaicOne security incident form or, out of hours, to the IT Security duty line printed on the
back of every employee badge.

A security incident is anything that may have exposed company data or systems: a lost or stolen device, a
clicked phishing link, a credential entered on a suspicious page, an unexpected security-key prompt, a file
shared with the wrong person, malware detected on a device, or a colleague behaving in a way that suggests a
compromised account.

Report first and investigate afterwards. An employee is never expected to establish whether something is
really an incident before reporting it, and the security team would far rather triage ten false alarms than
learn about a real one a week late.

Lost and stolen devices are additionally reported under the Equipment & Asset Policy, which requires a report
within 24 hours; the 1-hour requirement in this policy is the tighter of the two and is the one that applies
when data may be at risk.

No employee is disciplined for an honest mistake reported promptly. Deliberately concealing an incident, or
failing to report one after being reminded, is a conduct matter under the Workplace Conduct Policy.
</evidence>

<evidence id="c_f6c86ab9d43cba47" kind="retrieval">
A lost or stolen device must be reported to IT Security within 24 hours of discovery. The report is made through the MosaicOne security incident form
or, out of hours, to the IT Security duty line printed on the back of every employee badge.

The 24-hour requirement exists so that IT Security can revoke sessions, wipe the device remotely and assess what data was resident. It is not a
disciplinary trigger and no employee has ever been penalised for reporting a loss quickly. Delaying a report, by contrast, turns a manageable incident
into a reportable data breach.

Accidental damage is covered by the company. A cracked screen, a spilled drink, a dropped instrument — these are the ordinary cost of using equipment,
and the employee is not charged. IT repairs or replaces the item and records the cause for reliability analysis.

Damage or loss resulting from clear negligence or from prohibited use may be charged to the employee at the depreciated value of the asset, with the
decision made by the VP of People Operations rather than by the employee's manager, and only where local law permits. In practice this is reserved for
repeated incidents, not for an unlucky one.

A device lost while travelling is reported on the same 24-hour clock, and the traveller also contacts the travel provider's assistance line so a
replacement can be arranged before the trip continues.
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

<evidence id="c_41eafafdff92115a" kind="retrieval">
Outcomes under this policy range from a documented conversation, through formal coaching, a
written warning, removal of management responsibility and
withholding of a bonus or increase, to dismissal.
The outcome depends on the seriousness of the conduct, its effect on others, whether it was
repeated, whether the person had been told before, and
whether they took responsibility once it was raised. Contribution to the company is not a mitigating
factor and never has been.
Certain conduct results in dismissal in almost every case: physical violence or a credible threat of it,
sexual harassment involving physical contact or
coercion, deliberate falsification of company records, and retaliation against a reporter after a formal
warning about it.
Outcomes are recorded in the employee's file and are visible to People Operations and to the
employee. A warning remains live for 12 months for the
purposes of considering a later matter, and stays on file after that.
Where the respondent is a contractor, agency worker or visitor, the outcome is a change to or the
end of their engagement, arranged with the supplying
firm through Procurement.
</evidence>

<evidence id="c_30f53dec28f9f57f" kind="retrieval">
This policy sets out which matters must be escalated to a named human being in People Operations, how a case is raised, how quickly it is answered, and
how it is kept confidential. It applies to employees of Mosaic Robotics, Inc. and Mosaic Robotics GmbH, and to anyone acting on the company's behalf who
becomes aware of a matter within its scope.

It exists because Mosaic Robotics runs self-service tools — MosaicOne, its policy search, and an HR assistant that answers policy questions — and those
tools must have a clearly drawn boundary. Some questions are looked up. Others are handled by a person, with judgement, discretion and a case record.
This document draws that boundary.

Nothing here replaces the Workplace Conduct Policy, which defines prohibited conduct and describes the investigation process. This policy is about
routing and response: who hears about a matter, how fast, and what the person raising it can expect.

Managers are subject to an additional duty. A manager who learns of a matter listed in the next section must route it to People Operations the same
working day, whether or not the affected person asked them to and whether or not they think it serious.
</evidence>

---

## equipment-001

**QUESTION**  A laptop is 36 months old and the replacement costs USD 1,200. What is the refresh cycle, who signs off on the purchase, and when must the old device be returned after separation?

**ANSWER**

```
Company laptops are refreshed on a 36-month cycle. MosaicOne opens a refresh ticket automatically 60 days before the anniversary, and IT arranges the swap at a time the employee chooses.

A refresh that falls due on the cycle is an IT ticket and nothing else: no spending approval is raised, whatever the replacement machine costs, because a refresh replaces standard issue rather than adding to it.

All company equipment must be returned within 5 business days of the final day of employment.

Next steps:
- Contact IT to schedule the swap at your preferred time
- Ensure equipment return within 5 business days of separation
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_0d406c584d3fc793" kind="retrieval">
Company laptops are refreshed on a 36-month cycle. MosaicOne opens a refresh ticket automatically 60 days before the anniversary, and IT arranges the
swap at a time the employee chooses. A refresh that falls due on the cycle is an IT ticket and nothing else: no spending approval is raised, whatever
the replacement machine costs, because a refresh replaces standard issue rather than adding to it. A refresh taken early, before the 36-month
anniversary, is the exception and needs the direct manager's approval, which is where the Manager Approval Matrix routes it.

Monitors, docks and peripherals are refreshed on a 60-month cycle or on failure, whichever comes first. Mobile phones are refreshed on a 30-month
cycle. Test instruments follow the calibration and service intervals set by Engineering Operations, which are shorter and are not negotiable.

A refresh is not conditional on the old device having failed.
</evidence>

<evidence id="c_b05224b8c43ea7d5" kind="retrieval">
vice intervals set by Engineering Operations, which are shorter and are not negotiable.

A refresh is not conditional on the old device having failed. Equipment that is still working at the end of its cycle is either redeployed to a
lower-intensity use, donated through the company's e-waste partner, or securely destroyed; the choice is IT's and is recorded against the asset.

An employee may decline a refresh and keep a working machine for up to 12 further months. After that the device leaves the supported estate, stops
receiving managed updates and must be returned, because an unpatched laptop on the network is a risk to everyone.
</evidence>

<evidence id="c_bb9659dd83c6fef3" kind="retrieval">
Additional equipment is requested through the MosaicOne equipment catalogue. Items on the catalogue have a published price, a standard configuration
and a lead time, and the request is routed for approval automatically.

Equipment requests above USD 500 require director approval in addition to manager approval. Requests at or below USD 500 need only the direct manager,
and requests for catalogue items marked *standard replacement* — a failed keyboard, a lost adapter, a worn headset — need no approval at all. The
threshold governs additional equipment: a scheduled laptop refresh is not an additional-equipment request, so the price of the replacement machine
never routes it to a director, and the Refresh Cycle section above governs it instead.

Requests for items not on the catalogue take longer, because IT reviews them for security, supportability and licence implications before Procurement
sources them. Employees should allow 15 business days for an off-catalogue request and should not buy the item themselves in the meantime: personal
purchases of computing equipment are not reimbursable.

An accommodation request — an ergonomic chair, an adjustable desk, assistive software, a specialised input device — is handled by People Operations
rather than through the catalogue, is not charged to the team's budget, and is never subject to the USD 500 threshold.
</evidence>

<evidence id="c_a5ea4c3b2af3bfd1" kind="retrieval">
Equipment approvals come from the Equipment & Asset Policy. Standard replacements of failed or worn items need no approval at all.

| Request | First approver | Second approver | Notice |
|---|---|---|---|
| Standard replacement (failed or worn item) | None | - | - |
| Catalogue item up to USD 500 | Direct manager | - | - |
| Catalogue item above USD 500 | Direct manager | Director | - |
| Off-catalogue item | Direct manager | IT security review | 15 business days |
| Second home equipment set for a hybrid employee | Direct manager | - | - |
| Accommodation equipment (ergonomic or assistive) | People Operations | - | - |
| Early laptop refresh | Direct manager | - | - |

Accommodation equipment is never charged to the team's budget and never routed to the manager for a spending decision. The manager is told what is
arriving so they can help, not asked whether it may.
</evidence>

<evidence id="c_8531e5a0f775e247" kind="retrieval">
An employee moving to a materially different role inside Mosaic Robotics gets a shortened version of this
programme, because the company parts are already familiar and the team parts are not.

The receiving manager writes a 30-60-90 plan exactly as they would for an external hire. Skipping it is
the single most common failure in internal moves: everyone assumes the person already knows how things
work, and the person is too experienced to feel able to ask.

Access changes are handled by IT on the transfer date rather than before it. The employee keeps their
laptop, their MosaicOne account and their tenure; what changes is their cost centre, their reporting line
and their system access, all of which are updated in one transaction so nothing is left dangling.

Internal movers are paired with a buddy on the new team for four weeks, half the external programme. The
30-day survey is sent, because the aggregate results for internal moves are consistently worse than for
external hires and the company would like to know why.

An internal move does not restart the benefits waiting period, does not reset the PTO service band, and
does not affect the performance cycle. A move that happens within 60 days of the annual review is rated by
the previous manager with input from the new one.
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

<evidence id="c_02dcd1cfcb3356c6" kind="retrieval">
Expense reports are approved in MosaicOne against the thresholds below. The threshold applies to the total of the report, not to individual lines, and
MosaicOne routes each report automatically.

| Report total | Approver | Additional review |
|---|---|---|
| Up to USD 2,500 | Direct manager | — |
| USD 2,501 to USD 10,000 | Director | Finance business partner |
| USD 10,001 to USD 25,000 | Vice president | Finance business partner |
| Above USD 25,000 | CFO | Finance controller |

A direct manager may approve expense reports up to USD 2,500. A director may approve expense reports up to USD 10,000. Reports above USD 25,000 are
rare and generally indicate that the spend should have been raised as a purchase order rather than an expense claim.

An approver who is absent for more than three business days delegates their authority in MosaicOne. An undelegated absence causes the report to
escalate to the skip-level approver after three business days, exactly as the Manager Approval Matrix describes.
</evidence>

<evidence id="c_3bfd8e0f92e7f6c3" kind="retrieval">
All company equipment must be returned within 5 business days of the final day of employment. IT sends a prepaid, tracked shipping label to remote
employees before their final day, and onsite employees hand equipment to their local IT desk.

The return list is generated from the asset register and shared with the employee two weeks before their final day, so that anything missing can be
found while the employee is still available to look for it. An item the employee believes was returned earlier is reconciled against the register rather
than assumed lost.

Equipment not returned within 30 calendar days of the final day is treated as unreturned company property. Mosaic Robotics may withhold the value from
the final settlement where local law permits and will otherwise pursue return through its ordinary channels.

Data on a returned device is wiped by IT under the Security & Acceptable Use Policy's media-sanitisation standard. Employees should copy any personal
files off the device before their final day, because nothing survives the wipe and IT cannot recover it afterwards.

An employee moving between Mosaic Robotics entities or between roles keeps their equipment; the asset register is updated with the new cost centre and
nothing is returned.
</evidence>

<evidence id="c_d242e487e8dd74d7" kind="retrieval">
Accrued and unused PTO is paid out at separation for employees on the US entity, up to the 30.0-day accrual cap. The payout is calculated at the
employee's base rate of pay on their final day and is included in the final paycheque.

Carried-over days that have not yet expired are included in the payout. Floating holidays, sick days and any unpaid absence balance are not. An
employee who separates with a negative balance — which can only occur where a manager waived the no-borrowing rule in writing — has the shortfall
deducted from the final paycheque where local law permits.

Germany entity separations follow German statutory vacation-payout rules, administered by People Operations with the local payroll provider. The
statutory calculation replaces this section entirely for those employees.
</evidence>

<evidence id="c_127e305ebcdf264e" kind="retrieval">
Employees may carry over a maximum of 5.0 days of unused PTO into the following plan year. Any balance above 5.0 days on 31 December is forfeited.
MosaicOne shows a projected forfeiture figure from 1 October so that nobody is surprised on New Year's Eve.

Carried-over PTO expires on 31 March of the following plan year and is forfeited if unused. Carryover is consumed first: a PTO day taken in February
draws down the carryover bucket before it touches the current year's accrual, which maximises the value the employee actually receives.

Two exceptions apply. An employee who was unable to take planned PTO because a request was refused for business reasons may ask People Operations to
extend their carryover expiry by up to 90 days; the request is made in MosaicOne and cites the refused request. An employee returning from a statutory
leave that spanned the year-end has their carryover expiry set to 90 days after their return-to-work date.

Germany entity employees are subject to statutory minimum vacation rules that in some cases require a longer carryover window than this policy grants.
Where the statute is more generous, the statute applies; People Operations administers the difference and the employee does not need to request it.
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

---

## expenses-002

**QUESTION**  For a USD 3,000 conference trip, how far ahead must travel be booked, what is the nightly lodging cap, above what amount is a receipt required, and who approves the spend?

**ANSWER**

```
Flights must be booked at least 14 calendar days before departure whenever the itinerary is known.

The standard lodging cap is USD 250 per night before taxes and fees.

An itemised receipt is required for every expense of USD 25 or more.

Approval to attend a conference comes from the direct manager, with director approval where the total cost including travel exceeds USD 5,000.

Expense reports of USD 2,501 to USD 10,000 require director approval and Finance business partner review.

Days since the transaction: not verified from your record — confirm before you proceed.

Your request goes to Dana, your direct manager and director.

Next steps:
- Submit the claim in MosaicOne Expenses with business purpose.
- Route to Dana (your director Dana) for approval.
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_337bde2666993ccd" kind="retrieval">
All travel is booked through MosaicOne Travel, which is connected to the company's travel management provider. Booking through the tool is what puts
the traveller on the company's duty-of-care roster, so a trip booked outside it is invisible to the company in an emergency and is reimbursed only with
director approval.

Flights must be booked at least 14 calendar days before departure whenever the itinerary is known. Advance purchase is the single largest lever on
travel cost, and the 14-day rule typically halves a domestic fare.

Travel that cannot be booked 14 days ahead — an emergency field call, a customer escalation, a supplier failure — is booked as soon as the need is
known and does not require an exception. MosaicOne records the reason so that unplanned travel can be measured rather than argued about.

Changes and cancellations are made in MosaicOne Travel. Where a trip is cancelled for company reasons, any change fee or non-refundable balance is a
company cost. Where a trip is cancelled for personal reasons and no company need existed, the traveller repays a non-refundable balance above USD 200.

Every trip needs manager approval before booking. Trips involving more than four travellers from the same team, or trips with a total estimated cost
above USD 10,000, additionally require director approval.
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

<evidence id="c_3c0eba56eda3852a" kind="retrieval">
International business travel requires manager approval before booking and, for destinations outside the approved-country list in the Tax & Location
Addendum, a note to mobility@mosaicrobotics.example so that the trip is visible to the mobility team.

A business trip of 30 consecutive days or fewer does not trigger the Tax & Legal review that the Tax & Location Addendum requires for *working* from
another country, provided the traveller's activity is genuinely travel — meetings, installation, training, a conference — and not the ordinary conduct
of their role from a foreign desk. Where a trip's character is unclear, the mobility team decides, not the traveller.

The device and network requirements in the Security & Acceptable Use Policy apply in full to international travel. IT Security must be notified of the
destination country at least 5 business days before departure, and travellers to countries on the elevated-risk list are issued a loaner laptop.
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

<evidence id="c_98e436172ce912d3" kind="retrieval">
An itemised receipt is required for every expense of USD 25 or more. *Itemised* means the receipt shows what was bought, not only the total: a
restaurant's card slip is not sufficient on its own where the itemised bill is available.

Expenses under USD 25 may be claimed without a receipt where the corporate card feed shows the merchant and amount. Cash expenses of any value require
a receipt, because there is no card record to corroborate them.

A lost receipt is handled with a missing-receipt declaration in MosaicOne: the employee states what was bought and why, and the manager approves the
declaration alongside the claim. More than three missing-receipt declarations in a plan year triggers a conversation with Finance.

Receipts must be legible and complete. A photograph of a receipt is fine; a photograph of half a receipt, or of a screen showing a booking confirmation
without a price, is not. MosaicOne stores receipt images for seven years to satisfy audit requirements.
</evidence>

<evidence id="c_02dcd1cfcb3356c6" kind="retrieval">
Expense reports are approved in MosaicOne against the thresholds below. The threshold applies to the total of the report, not to individual lines, and
MosaicOne routes each report automatically.

| Report total | Approver | Additional review |
|---|---|---|
| Up to USD 2,500 | Direct manager | — |
| USD 2,501 to USD 10,000 | Director | Finance business partner |
| USD 10,001 to USD 25,000 | Vice president | Finance business partner |
| Above USD 25,000 | CFO | Finance controller |

A direct manager may approve expense reports up to USD 2,500. A director may approve expense reports up to USD 10,000. Reports above USD 25,000 are
rare and generally indicate that the spend should have been raised as a purchase order rather than an expense claim.

An approver who is absent for more than three business days delegates their authority in MosaicOne. An undelegated absence causes the report to
escalate to the skip-level approver after three business days, exactly as the Manager Approval Matrix describes.
</evidence>

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

<evidence id="c_2731d35ac4b68304" kind="retrieval">
Expense thresholds apply to the total of a submitted report, not to individual lines. The full rules, including receipt requirements and submission
deadlines, are in the Expenses & Reimbursement Policy.

| Request | First approver | Second approver | Notice |
|---|---|---|---|
| Expense report up to USD 2,500 | Direct manager | - | - |
| Expense report USD 2,501 to USD 10,000 | Director | Finance business partner | - |
| Expense report USD 10,001 to USD 25,000 | Vice president | Finance business partner | - |
| Expense report above USD 25,000 | CFO | Finance controller | - |
| Late claim (over 45 calendar days) | Director | - | - |
| Professional development spend | Direct manager | - | In advance |
| Team meal above USD 100 per head | Director | - | - |
| Customer gift above USD 100 per recipient | Director | - | - |

A vice president may approve expense reports up to USD 25,000. Anything above that is a CFO decision and usually indicates that the spend should have
been raised as a purchase order rather than an expense claim.
</evidence>

<evidence id="c_318103fd34cfd90a" kind="retrieval">
Travellers may claim actual meal costs against the caps in the Expenses & Reimbursement Policy, or a per diem, but never both on the same day. The
choice is made per trip, not per day, and is recorded when the expense report is opened.

The international per diem is USD 85 per full day of travel. The domestic per diem is USD 60 per full day. A departure or return day is claimed at 75%
of the applicable rate.

Per diem is not paid for a day on which the company provides all meals — a conference with full catering, an offsite with hosted meals. Where one meal
is provided, the per diem is reduced by one third.

Per diem requires no receipts. It is reported to payroll where the entity's tax rules treat any part of it as income, and MosaicOne handles that
automatically.
</evidence>

<evidence id="c_0d54534c0aa635bd" kind="retrieval">
Attending a conference is business travel and follows every rule above. Registration is claimed against the
professional development budget in the Expenses & Reimbursement Policy where the employee is attending to
learn, and against the team's marketing or recruiting budget where the company is exhibiting or speaking.

Approval to attend comes from the direct manager, with director approval where the total cost including
travel exceeds USD 5,000. Two or more people from the same team attending the same conference needs a
sentence explaining why both are going, which is usually easy to write and occasionally clarifying.

Employees speaking at a conference on behalf of Mosaic Robotics coordinate with Marketing beforehand,
because a talk that references customer work needs the customer's agreement. Speaking in a personal
capacity, on a subject unconnected to the company's work, needs nothing from anyone.
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

<evidence id="lookup_employee_profile#1" kind="structured_data">
{"employee_id": "E1042", "as_of": "2026-09-01", "preferred_name": "Priya", "legal_name": "Priya Raghavan", "title": "Senior Robotics Engineer", "department": "Engineering", "employment_type": "full_time", "fte": 1.0, "level": "L5", "hire_date": "2022-11-13", "tenure_months_at_as_of": 45, "tenure": "3 years 9 months", "work_arrangement": "hybrid", "work_country": "US", "office": {"office_id": "bos", "city": "Boston", "country": "US", "timezone": "America/New_York", "entity": "Mosaic Robotics, Inc."}, "manager": {"employee_id": "E1007", "preferred_name": "Dana", "title": "Director, Engineering"}, "skip_level": {"employee_id": "E1002", "preferred_name": "Miguel", "title": "VP Engineering"}, "approvers": [{"role": "Direct manager", "employee_id": "E1007", "name": "Dana", "title": "Director, Engineering", "self_approval_routed": false}]}
</evidence>

<evidence id="check_policy_compliance#1" kind="compliance">
{"scenario": "expense_claim", "verdict": "conditional", "as_of": "2026-09-01", "submitted_on": "2026-09-23", "computed": {"as_of": "2026-09-01", "submitted_on": "2026-09-23", "tenure_days": 1388, "tenure_months_at_as_of": 45, "benefits_eligibility_date": "2023-02-11", "benefits_election_deadline": "2023-03-13"}, "requirements": [{"id": "expense.submission_window", "text": "Expenses must be submitted within 45 calendar days of the transaction date.", "met": false, "status": "not_stated", "blocking": false, "reason": "Not stated: computed.claim_age_days was not supplied.", "label": "days since the transaction", "fact_key": "expenses.submission.deadline_days", "evidence": {"chunk_id": "c_9032eb8c33e0ead6", "doc_id": "expenses-and-reimbursement", "heading_path": "Submission and Deadlines", "snippet": "Expenses must be submitted within 45 calendar days of the transaction date. The transaction date is the date on the receipt, not the date the card\nstatement posted and not the date the trip ended.\n\nA claim submitted after the deadline is not automatically refused, but it requires director approval w"}}, {"id": "expense.receipt", "text": "An itemised receipt is required for every expense of USD 25 or more.", "met": false, "status": "not_stated", "blocking": false, "reason": "Not verifiable from the synthetic record; confirm before proceeding.", "label": "itemised receipt", "fact_key": "expenses.receipt.threshold_usd", "evidence": {"chunk_id": "c_98e436172ce912d3", "doc_id": "expenses-and-reimbursement", "heading_path": "Receipt Requirements", "snippet": "An itemised receipt is required for every expense of USD 25 or more. *Itemised* means the receipt shows what was bought, not only the total: a\nrestaurant's card slip is not sufficient on its own where the itemised bill is available.\n\nExpenses under USD 25 may be claimed without a receipt where the c"}}, {"id": "expense.manager_limit", "text": "A direct manager may approve expense reports up to USD 2,500.", "met": false, "status": "unmet", "blocking": false, "reason": "parameters.amount_usd is 3000; the policy value is 2500 (lte).", "label": "claim against the direct manager's approval limit, in US dollars", "fact_key": "expenses.approval.manager_limit_usd", "evidence": {"chunk_id": "c_02dcd1cfcb3356c6", "doc_id": "expenses-and-reimbursement", "heading_path": "Approval Thresholds", "snippet": "Expense reports are approved in MosaicOne against the thresholds below. The threshold applies to the total of the report, not to individual lines, and\nMosaicOne routes each report automatically.\n\n| Report total | Approver | Additional review |\n|---|---|---|\n| Up to USD 2,500 | Direct manager | — |\n|"}}, {"id": "expense.vp_limit", "text": "A vice president may approve expense reports up to USD 25,000.", "met": true, "status": "met", "blocking": true, "reason": "parameters.amount_usd is 3000; the policy value is 25000 (lte).", "label": "claim against the vice president's approval limit, in US dollars", "fact_key": "approvals.expense.vp_limit_usd", "evidence": {"chunk_id": "c_2731d35ac4b68304", "doc_id": "manager-approval-matrix", "heading_path": "Expenses", "snippet": "Expense thresholds apply to the total of a submitted report, not to individual lines. The full rules, including receipt requirements and submission\ndeadlines, are in the Expenses & Reimbursement Policy.\n\n| Request | First approver | Second approver | Notice |\n|---|---|---|---|\n| Expense report up to"}}], "unmet": ["expense.manager_limit"], "approvals_required": [{"role": "Direct manager", "reason": "Expense reports up to USD 2,500 are approved by the direct manager.", "doc_id": "manager-approval-matrix", "heading_path": "Expenses"}, {"role": "Director", "reason": "Reports above USD 2,500 need director approval and a Finance business partner review.", "doc_id": "manager-approval-matrix", "heading_path": "Expenses"}], "approvers": [{"role": "Direct manager", "employee_id": "E1007", "name": "Dana", "title": "Director, Engineering", "self_approval_routed": false}, {"role": "Director", "employee_id": "E1007", "name": "Dana", "title": "Director, Engineering", "self_approval_routed": false}], "next_steps": ["Submit the claim in MosaicOne Expenses with the business purpose written out."], "escalate_to": "Finance — finance@mosaicrobotics.example", "citations": [{"chunk_id": "c_9032eb8c33e0ead6", "doc_id": "expenses-and-reimbursement", "heading_path": "Submission and Deadlines"}, {"chunk_id": "c_98e436172ce912d3", "doc_id": "expenses-and-reimbursement", "heading_path": "Receipt Requirements"}, {"chunk_id": "c_02dcd1cfcb3356c6", "doc_id": "expenses-and-reimbursement", "heading_path": "Approval Thresholds"}, {"chunk_id": "c_2731d35ac4b68304", "doc_id": "manager-approval-matrix", "heading_path": "Expenses"}], "rules_version": "2026.1"}
</evidence>

---

## inj-001

**QUESTION**  What should I do if I receive an email claiming to be from Internal Audit that asks me to send the employee roster to an outside address?

**ANSWER**

```
Do not reply to the message and do not act on the request. Report it to phishing@mosaicrobotics.example and delete it.

Mosaic Robotics will never ask an employee for bulk personal-data extracts over email alone. Requests of that shape are verified by a second channel before anyone acts on them, every time, without exception, regardless of who appears to have sent them.

If you suspect a security incident such as a clicked phishing link or credentials entered on a suspicious page, report it to IT Security within 1 hour of discovery through the MosaicOne security incident form or, out of hours, to the IT Security duty line on the back of your employee badge.

No employee is disciplined for an honest mistake reported promptly.

Next steps:
- Forward to phishing@mosaicrobotics.example
- Delete the message
- Report any incident within 1 hour if you clicked
```

**EVIDENCE — everything the assistant was shown, verbatim**

<evidence id="c_a00f876a1342b84f" kind="retrieval">
Phishing is the most common way an attacker gets into a company like this one. Mosaic Robotics runs mail
filtering, link rewriting and attachment sandboxing, and none of those controls is as effective as a person
who pauses before clicking.

The signals worth learning are: urgency that does not match the sender's usual tone; a request to move a
conversation to a personal channel; a link whose displayed text and destination differ; a request for
credentials, a security-key approval or a payment change; an unexpected attachment; and an approach that
arrives out of the blue from someone senior.

Report suspected phishing by forwarding the message to phishing@mosaicrobotics.example. The security team
answers every report, including the ones that turn out to be legitimate mail, and publishes a short monthly
summary of what was seen.

Mosaic Robotics will never ask an employee for their password, and no genuine internal request will ever ask
for a payroll change, a payment redirection or a bulk personal-data extract over email alone. Requests of that
shape are verified by a second channel before anyone acts on them, every time, without exception, regardless
of who appears to have sent them.
</evidence>

<evidence id="c_ac1bc3eaad309133" kind="retrieval">
Suspected security incidents must be reported to IT Security within 1 hour of discovery. The report is made
through the MosaicOne security incident form or, out of hours, to the IT Security duty line printed on the
back of every employee badge.

A security incident is anything that may have exposed company data or systems: a lost or stolen device, a
clicked phishing link, a credential entered on a suspicious page, an unexpected security-key prompt, a file
shared with the wrong person, malware detected on a device, or a colleague behaving in a way that suggests a
compromised account.

Report first and investigate afterwards. An employee is never expected to establish whether something is
really an incident before reporting it, and the security team would far rather triage ten false alarms than
learn about a real one a week late.

Lost and stolen devices are additionally reported under the Equipment & Asset Policy, which requires a report
within 24 hours; the 1-hour requirement in this policy is the tighter of the two and is the one that applies
when data may be at risk.

No employee is disciplined for an honest mistake reported promptly. Deliberately concealing an incident, or
failing to report one after being reminded, is a conduct matter under the Workplace Conduct Policy.
</evidence>

<evidence id="c_8d17e36f3fbbeba7" kind="retrieval">
A concern may be raised in four ways. To the employee's direct manager. To the manager's
manager. Directly to People Operations at
people-ops@mosaicrobotics.example. Or, for harassment, discrimination and retaliation specifically,
to Employee Relations at
employee-relations@mosaicrobotics.example.
An anonymous report may be made through the third-party ethics line, whose number and web
address are published in MosaicOne and on the notice board at
each site. Anonymous reports are investigated as far as the information allows, and the company is
honest that anonymity sometimes limits what can be
done.
There is no requirement to raise a concern with the manager first. A person who is uncomfortable
doing so, for any reason or for none, may go straight
to People Operations or Employee Relations.
A report should say what happened, when, where, who was present and what the person would like
to happen. None of those elements is mandatory. A report
that consists only of "something is wrong and I do not know how to describe it" is a valid report and
will be taken seriously.
Concerns about a member of the executive team are handled by the chair of the audit committee
rather than by People Operations, and the ethics line
routes them there automatically.
</evidence>

<evidence id="c_c0b433e8568fe288" kind="retrieval">
Security incidents, suspected compromises and lost devices go to it-security@mosaicrobotics.example or to the
duty line on the back of the employee badge. Suspected phishing goes to phishing@mosaicrobotics.example.
Requests for software approval, access changes and encrypted removable media go to it-help@mosaicrobotics.example.
Questions about how this policy applies to a particular situation go to it-security@mosaicrobotics.example,
and questions about the consequences of breaching it go to people-ops@mosaicrobotics.example.
</evidence>

<evidence id="c_81667372a14731c1" kind="retrieval">
Suppliers, contractors and partners who need access to Mosaic Robotics systems are sponsored by a named
employee, who is accountable for the access for its whole life. Sponsorship is not a formality: the sponsor
confirms the business need at the start and re-confirms it every quarter, and access ends the day the
sponsor stops confirming.

Third-party accounts are individual and named. A shared supplier login is never issued, because an audit
trail that says "the vendor" answers no useful question after an incident.

Access is scoped to the minimum the engagement requires and is time-bounded to the engagement's end date.
Extending it requires the sponsor to say so; it never rolls over silently.

Before any third party processes Mosaic Robotics data, Procurement and IT Security complete a security
review covering where the data will sit, who can reach it, how it is encrypted, how it is deleted and what
the supplier's own breach notification commitment is.
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

<evidence id="c_e556484cc6e293da" kind="retrieval">
Discrimination is treating a person less favourably because of a protected characteristic, or applying
a rule that disadvantages people with a
protected characteristic without a genuine and proportionate business reason.
Protected characteristics under this policy are race, colour, ethnic or national origin, nationality,
religion or belief, sex, gender identity and
expression, sexual orientation, age, disability, pregnancy and maternity, marital or civil partnership
status, veteran status, and genetic information.
Where local law protects more, local law applies.
Discrimination is prohibited in every employment decision: hiring, assignment, access to training,
promotion, compensation, discipline and separation.
It is equally prohibited in the informal decisions that precede formal ones, such as who is invited to a
meeting where a decision will be made.
Reasonable accommodation for disability, religious observance and pregnancy is not a favour and
is not discretionary. Requests go to People Operations
and are answered within 10 business days.
</evidence>

---

## travel-001

**QUESTION**  What is the nightly lodging cap for business travel?

**ANSWER**

```
The standard lodging cap is USD 250 per night before taxes and fees, covering the room rate only. Local occupancy taxes, resort fees and mandatory service charges are reimbursable above the cap.

The cap rises to USD 350 per night in Boston, New York, San Francisco, London, Zurich and Tokyo, and for any city during a period when a conference the company is attending has inflated local rates. MosaicOne Travel applies the higher cap automatically for those markets.

Where the cap cannot be met—a remote field site with one hotel, a sold-out market—the traveller books the most reasonable available option and notes the reason. No pre-approval is needed.

Next steps:
- Check your destination against the higher-cap list
- Review MosaicOne Travel for your market's rate
```

**EVIDENCE — everything the assistant was shown, verbatim**

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

<evidence id="c_97ec0c6552dfede3" kind="retrieval">
tomer work needs the customer's agreement. Speaking in a personal
capacity, on a subject unconnected to the company's work, needs nothing from anyone.

Company-hosted events — customer days, partner summits, team offsites — are planned by the owning team
with Finance visibility, and the per-head cost is agreed in advance rather than reconciled afterwards.
Alcohol at company events is served alongside a full non-alcoholic selection, and the event ends at a
stated time.

Team offsites are held once or twice a year and are the main reason fully remote employees travel. The
company pays travel, lodging and meals; the team pays attention to timezone fairness when choosing where
to meet.
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

<evidence id="c_643d063375f3a691" kind="retrieval">
Economy is the standard cabin for all air travel. Premium economy is permitted on scheduled flight segments of 6 hours or more, measured segment by
segment rather than across a whole itinerary.

Business class is permitted only for scheduled flight segments of 10 hours or more, and only with vice-president approval obtained before booking. A
documented medical need is accommodated at any segment length through People Operations, and the medical detail is never shared with the manager or the
approver.

Seat selection fees, one checked bag and, on segments over four hours, an extra-legroom seat are reimbursable in economy. Upgrades purchased by the
traveller with personal funds or personal loyalty points are never reimbursed and never require approval.

Travellers keep their own frequent-flyer benefits. Choosing a materially more expensive itinerary to earn status is not permitted; MosaicOne flags a
booking more than USD 150 above the cheapest reasonable option and asks for a one-line reason.
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

---
