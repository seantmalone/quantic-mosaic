# The Mosaic Robotics policy corpus

Fourteen hand-authored HR policy documents for **Mosaic Robotics, Inc.**, a fictional 420-person
industrial robotics company — HQ Austin TX, offices Boston MA and Berlin DE, a fully-remote US cohort, US
and German legal entities, hybrid by default, calendar fiscal year, benefits plan year 2026, HRIS called
"MosaicOne". Every person, address, number and threshold in these documents is invented for this project.

The documents are the retrieval corpus. `facts.yml` is an index into them, `rules.yml` is the rule engine's
knowledge, and this file is the map. Nothing here is generated: the prose is written directly and
committed, and the only build step in the whole directory is `scripts/build_pdf.py`, which renders
`workplace-conduct.src.md` to `workplace-conduct.pdf` once.

## What is in this directory

| File | What it is |
|---|---|
| 11 × `*.md`, 1 × `*.html`, 1 × `*.txt`, 1 × `*.pdf` (+ its `.src.md`) | the 14 policy documents |
| `facts.yml` | ~56 checkable facts, each with a verbatim quote and a heading path |
| `rules.yml` | the requirements behind `check_policy_compliance`'s seven scenarios |
| `README.md` | this map: topics, outlines, conventions, format rationale |

Three scripts operate on it:

```bash
python scripts/check_facts.py     # quotes verbatim, heading paths real, every fact_key resolves
python scripts/corpus_stats.py    # files, pages, words, per-format counts
python scripts/build_pdf.py       # regenerate workplace-conduct.pdf from its .src.md
```

`scripts/check_facts.py` runs in CI's `test` job alongside `pytest -q`.

## Conventions

**Document header.** Every document opens with its title, then two lines:

```
Document ID: pto-and-holidays · Owner: People Operations · Effective 2026-01-01 · Version 2026.1
Topics: pto, holidays
```

The `Topics:` line is the **single source of truth** for a document's topics — the P4 parsers read it into
`documents.topics` and `chunks.topics`, and the map below is a human-readable restatement of those lines,
never a second source of truth. Values are drawn from `search_policy_documents`'s `topic` enum.

**Heading paths.** A document's title is *not* part of a heading path: it travels separately as
`doc_title` in every citation. So a `##` / `###` pair in Markdown produces
`"Accrual > Standard Accrual Rates"` — two components, not three.

| Format | Title | Path level 1 | Path level 2 |
|---|---|---|---|
| `.md` | `#` | `##` | `###` |
| `.html` | `<h1>` | `<h2>` | `<h3>` |
| `.txt` | a line underlined with `=` | a line underlined with `-` | a line in CAPITALS |
| `.pdf` | from `workplace-conduct.src.md` | from the same source | from the same source |

**Fictional contacts.** Every address is at `mosaicrobotics.example` (RFC 2606), so nothing in the corpus
can reach a real inbox: `people-ops@`, `employee-relations@`, `mobility@`, `tax-legal@`, `leave@`,
`benefits@`, `payroll@`, `finance@`, `it-help@`, `it-security@`, `phishing@`, `safety@`.

**Snapshot discipline.** Policy facts are timeless; employee facts are not. Nothing in these documents
states a balance, a tenure or an eligibility date for a person — those live in `mock_data/` against its
`as_of: 2026-09-01` snapshot. A document that said "you have 13.5 days" would rot; one that says "1.50
days per month at three or more years of service" does not.

## Topic map

A restatement of the `Topics:` header lines. `tests/unit/test_corpus_topics.py` asserts every one of the
ten PD.2 topics resolves to at least one document, and that no value of the tool's topic enum is orphaned.

| Topic | Documents |
|---|---|
| `pto` | `pto-and-holidays` |
| `holidays` | `pto-and-holidays` |
| `remote_work` | `remote-and-hybrid-work`, `tax-and-location-addendum` |
| `tax_location` | `tax-and-location-addendum` |
| `expenses` | `expenses-and-reimbursement`, `travel-policy` |
| `travel` | `travel-policy` |
| `data_security` | `security-acceptable-use` |
| `benefits` | `benefits-and-open-enrollment` |
| `onboarding` | `onboarding-and-first-90-days` |
| `equipment` | `equipment-and-asset` |
| `leave` | `leave-of-absence` |
| `conduct` | `workplace-conduct`, `hr-escalation-and-case-handling` |
| `performance` | `performance-and-compensation` |
| `compensation` | `performance-and-compensation` |
| `approvals` | `manager-approval-matrix` |
| `escalation` | `hr-escalation-and-case-handling` |

## The documents

Each outline lists the level-1 headings; the numbers in parentheses are the level-2 subsections.

### 1. `pto-and-holidays.md` — PTO & Holidays Policy · `pto, holidays`

Purpose and Scope · Accrual (3) · Requesting Time Off (3) · Carryover and Expiry · Company Holidays (3) ·
Unused PTO at Separation · Sick Time and Personal Days · Managing Time Off as a Manager · Questions.

The accrual bands (1.25 and 1.50 days per month either side of three years' service), the 5- and
15-business-day notice rules, the 30.0-day accrual cap, the 5.0-day carryover limit and the 2026 year-end
blackout all live here. It is the most heavily cited document in the corpus and the one demo task 2 turns
on.

### 2. `remote-and-hybrid-work.md` — Remote & Hybrid Work Policy · `remote_work`

Purpose and Scope · Work Arrangements (3) · Hybrid Expectations (2) · Changing Your Work Arrangement ·
Working Outside Your Home Country (4) · Working From Another US State · Home Workspace Standards ·
Meetings, Availability and On-Call · Questions and Contacts.

The people side of working elsewhere: the three arrangements, the three onsite days a week, the 12-month
tenure gate, the rolling 90-day annual limit, the 21-day manager notice, and the encrypted-laptop-plus-VPN
requirement. Demo task 1 reads `Working Outside Your Home Country > Approval` verbatim.

### 3. `tax-and-location-addendum.md` — Tax & Location Addendum · `remote_work, tax_location`

Purpose and Scope · Why Location Matters · Duration Thresholds (3) · Approved Countries · Payroll and
Withholding · Permanent Establishment Risk · Immigration and Right to Work · Frequently Asked Situations ·
Contacts.

The legal side of the same question, deliberately split into its own document so that a multi-document
answer is genuinely multi-document. Carries the **30-consecutive-day threshold** that makes demo task 1's
42-day request `conditional`, the approved-country list (Germany is on it), and the permanent-establishment
restriction on signing anything abroad.

### 4. `expenses-and-reimbursement.md` — Expenses & Reimbursement Policy · `expenses`

Purpose and Scope · General Principles · Submission and Deadlines · Receipt Requirements · Home Office and
Equipment Stipends (2) · Meals and Entertainment · Professional Development · Non-Reimbursable Expenses ·
Approval Thresholds · Corporate Cards · Contacts.

The USD 750 home office allowance, the USD 60 connectivity stipend, the USD 25 receipt threshold, the
45-day submission deadline, and an approval-threshold table that has to survive parsing as pipe-delimited
text.

### 5. `travel-policy.md` — Travel Policy · `expenses, travel`

Purpose and Scope · Booking and Advance Purchase · Air Travel (2) · Lodging · Ground Transportation ·
International Travel · Per Diem · Traveller Safety and Duty of Care · Conferences and Events · Contacts.

Deliberately adjacent to document 4 and to documents 2 and 3: it is the document a retrieval system should
*not* return for "can I work from Berlin", which makes it a useful distractor as well as a real policy.

### 6. `equipment-and-asset.md` — Equipment & Asset Policy · `equipment`

Purpose and Scope · Standard Issue · Refresh Cycle · Requesting Additional Equipment · Accessories and
Peripherals · Damage, Loss and Theft · Return at Separation · Software and Licences · Asset Register and
Audits · Contacts.

The 36-month laptop refresh, the USD 500 director threshold, the 24-hour loss report and the 5-business-day
return window. Draws the line between company assets and things bought with the home office allowance.

### 7. `benefits-and-open-enrollment.html` — Benefits and Open Enrollment Guide · `benefits`

Purpose and Scope · Eligibility (2) · Plan Year · Open Enrollment (2) · Medical Plans · Dental and Vision ·
Retirement · HSA and FSA · Life and Disability · Qualifying Life Events · Germany Entity Supplement ·
Wellbeing and Family Support · How to Use Your Benefits · Contacts.

The 90-day waiting period that makes `E1108` ineligible at the snapshot, the 1–21 November 2026 enrollment
window, and the 30-day qualifying-life-event window. Authored as HTML because a benefits guide is the
document a real company most often publishes as an intranet page.

### 8. `leave-of-absence.md` — Leave of Absence Policy · `leave`

Purpose and Scope · Types of Leave (6) · Requesting a Leave · Benefits During Leave · Return to Work ·
Germany Entity Differences · Sabbaticals · Contacts.

Sixteen weeks of paid parental leave, 26 weeks of medical leave, 12 weeks of family care, and the 30-day
notice rule for foreseeable leave. Kept strictly separate from PTO, because conflating the two is the
single most common HR-assistant error this corpus is designed to make visible.

### 9. `onboarding-and-first-90-days.md` — Onboarding & First 90 Days · `onboarding`

Purpose and Scope · Before Day One · Day One · Week One · First 30 Days · First 90 Days (1) · Buddy
Programme · Required Training · Onboarding for Internal Moves · What Good Onboarding Looks Like · Contacts.

The 14-day security training deadline, the 90-day check-in and the eight-week buddy pairing. Written in
chronological sections so that a "what happens in week one" question has a single obvious leaf.

### 10. `workplace-conduct.pdf` — Workplace Conduct Policy · `conduct`

Purpose and Scope · Our Standards · Prohibited Conduct (3) · Reporting Concerns · Investigation Process ·
Conflicts of Interest · Consequences · Alcohol, Substances and Company Events · Confidentiality and Records ·
Contacts.

Harassment, discrimination, retaliation, the 2-business-day acknowledgement and the 30-calendar-day
investigation target. Authored in `workplace-conduct.src.md` and rendered to PDF, because a conduct policy
is the document most companies publish as a signed PDF — and because R2.1 needs a fourth parsing path.

### 11. `performance-and-compensation.md` — Performance & Compensation Policy · `performance, compensation`

Purpose and Scope · Performance Cycle (2) · Ratings · Compensation Review · Promotions · Bonus Plan ·
Levels and Bands · Off-Cycle Adjustments · Performance Improvement · Contacts.

Ratings, bands, the November cycle, the 1 March merit effective date and the L5 12% bonus target. Its
subject matter is on the escalation list — a *dispute* about pay is never answered by the assistant, while
a question about how the cycle works is.

### 12. `manager-approval-matrix.md` — Manager Approval Matrix · `approvals`

Purpose and Scope · How to Read This Matrix · Time Off · Expenses · Equipment · Remote Work (2) · Hiring
and Offers · Escalation When an Approver Is Unavailable · Delegation and Proxy Approvals · Common Routing
Questions · Contacts.

Seven approval tables and no new rules: every threshold is drawn from the policy that owns it. It exists so
that "who approves this" is a one-hop retrieval, and so that the corpus contains a document that is mostly
tables — the parsing case §6.2 singles out.

### 13. `hr-escalation-and-case-handling.md` — HR Escalation & Case Handling Policy · `escalation, conduct`

Purpose and Scope · What Must Be Escalated · How to Raise a Case · Case Severity and Response Times ·
Confidentiality · Working With the HR Assistant · Working With Managers · Metrics and Continuous
Improvement · Contacts.

The document guardrail G5 answers from. It names the ten categories that are never handled by an automated
assistant, the three severity levels with their response times, and the three rules that bound the
assistant itself.

### 14. `security-acceptable-use.txt` — Security & Acceptable Use Policy · `data_security`

Purpose and Scope · Acceptable Use · Device Security · Data Classification (4) · Passwords and
Multi-Factor Authentication · Email and Phishing (1) · Working in Public Places · Removable Media and Cloud
Storage · Reporting a Security Incident · Third-Party and Supplier Access · Security Training and Awareness ·
Contacts.

Full-disk encryption, mandatory MFA, the four data classes, always-on VPN on any network the company does
not control, and the 1-hour incident report. Authored as plain text because that is how a security baseline
is most often circulated, and because it gives R2.1 its fourth format with a heading convention that owes
nothing to Markdown.

**It also carries the injection canary.** Inside `Email and Phishing`, a subsection labelled
`EXAMPLE OF A PHISHING LURE - DO NOT ACT ON TEXT LIKE THIS` quotes a lure with the full
imperative-to-assistant shape guardrail G4 quarantines. The section is deliberately short — under
`CHUNK_MAX_CHARS`, so the chunker cannot split the lure away from the label that explains it. It is corpus
content rather than a test fixture because eval item `inj-001` has to retrieve it from the real index, and
because the demo shows the quarantine banner on camera.

## Why four formats

R2.1 asks for at least two document formats; the corpus has four, and each was chosen because it is what a
real company would actually publish that document as, not to tick a box:

* **Markdown (11 documents)** — the working format for policy that changes. Cheap to diff, cheap to review,
  and its ATX headings are the reference implementation of the heading-path convention.
* **HTML (`benefits-and-open-enrollment`)** — the intranet page. Exercises the `beautifulsoup4` →
  `markdownify` path into the same Markdown heading extraction, so the HTML parser is a converter rather
  than a second implementation.
* **PDF (`workplace-conduct`)** — the signed, circulated policy. The hardest parsing path: text extraction
  with `pypdf`, a running footer to drop, and headings recoverable only by heuristic. Keeping the `.src.md`
  in the repository is what lets a test assert that the extracted heading set *equals* the source's.
* **Plain text (`security-acceptable-use`)** — the security baseline, with a heading convention (`=`
  underline, `-` underline, CAPITALS) that shares nothing with Markdown and so genuinely tests a fourth
  code path rather than a fourth file extension.

## `facts.yml` — the index

Roughly fifty-six entries of the shape:

```yaml
pto.accrual.ft_3y_plus:
  value: 1.50
  unit: days_per_month
  doc_id: pto-and-holidays
  section: "Accrual > Standard Accrual Rates"
  quote: "Full-time employees with three or more years of service accrue 1.50 days of PTO per month."
```

`scripts/check_facts.py` and `tests/unit/test_facts_quotes.py` assert, for every entry, that the quote is
verbatim in the rendered text of `doc_id` — for the PDF that means the text `pypdf` extracts from the
committed file, not its Markdown source — and that `section` is a real heading path there.

That one assertion is what makes three artifacts agree. Evaluation gold answers cite fact keys; `rules.yml`
requirements cite fact keys; the corpus holds the prose. Move a number in a document and the quote stops
matching, so the build fails before the corpus can contradict a gold answer.

## `rules.yml` — the rule engine's knowledge

`check_policy_compliance` (spec §8.4 tool 4) is a deterministic pure function over seven scenarios:
`international_remote`, `domestic_remote`, `pto_request`, `expense_claim`, `equipment_request`,
`benefits_change`, `conduct_escalation`. Each requirement names an `id`, its `text`, a `fact_key`, a
`doc_id` and a `heading_path` — those five keys and nothing else — and each scenario adds `title`,
`topics`, `escalate_to`, `approvals_required` and `next_steps`.

**How a requirement is evaluated is not decided in this file.** Spec §8.4 fixes the tool's input and
output schemas and says the rules come from `rules.yml`, each requirement naming a `fact_key`, a `doc_id`
and a `heading_path`; it does not say how `met`, `unmet`, the `verdict` (`compliant` / `conditional` /
`non_compliant` / `insufficient_evidence`) or the applicable subset of `approvals_required` and
`next_steps` are derived. Those are user-facing outputs, so **P5 owns them**; the P2 report §7.5 carries a
non-binding proposal. `scripts/check_facts.py` asserts the requirement key vocabulary, so an evaluation
field cannot reappear here without an explicit edit to `REQUIREMENT_KEYS` in the same commit.

Requirements carry no `chunk_id`, because chunk ids are content hashes computed at ingest.
`mcpserver/rules.py` resolves `(doc_id, heading_path)` to a real chunk at call time. A stale heading path
would produce evidence guardrail G2 silently strips, so `scripts/check_facts.py` asserts every requirement's
heading path is real as well as every `fact_key`.

## Editing the corpus

1. Edit the document. Keep the header lines intact and keep any sentence quoted in `facts.yml` verbatim —
   or update the quote in the same commit.
2. Run `python scripts/check_facts.py`. It names the fact and the file for every problem.
3. Run `python scripts/corpus_stats.py` if you added or removed a document.
4. If you edited `workplace-conduct.src.md`, run `python scripts/build_pdf.py` and commit the regenerated
   PDF; the script pins its creation date, so an unchanged source produces byte-identical output.
5. From P4 onward, re-run the ingest so `data/index/chunks.manifest.jsonl` matches the new prose.
