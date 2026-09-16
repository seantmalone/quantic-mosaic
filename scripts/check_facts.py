"""Corpus loader plus the one corpus consistency check (spec §5.2, §6.2).

Run it from the repository root:

    python scripts/check_facts.py

It asserts three things and prints one line per document:

1. every `corpus/facts.yml` `quote` appears **verbatim**, after whitespace normalisation, in the
   rendered text of its `doc_id`;
2. every `facts.yml` `section` — and every `corpus/rules.yml` requirement `heading_path` — is a real
   `" > "`-joined heading path in the document it names;
3. every `rules.yml` requirement `fact_key` resolves to an entry in `facts.yml`, and every requirement
   carries exactly the keys of `REQUIREMENT_KEYS` and no others.

Together those make the corpus, the rules engine and the evaluation gold answers agree: all three cite
fact ids rather than prose, so a corpus edit that moves a number fails here before it can contradict a
gold answer.

**Heading path convention.** A document's title is *not* part of a heading path: it travels separately
as `doc_title` in every citation. So the path of an `##`/`###` pair in Markdown is
`"Accrual > Standard Accrual Rates"`, two components, not three. Per format:

| Format | Title | Path level 1 | Path level 2 |
|---|---|---|---|
| `.md`  | `#`            | `##`              | `###`                 |
| `.html`| `<h1>`         | `<h2>`            | `<h3>`                |
| `.txt` | `===` underline| `---` underline   | an ALL-CAPS line      |
| `.pdf` | from `.src.md` | from `.src.md`    | from `.src.md`        |

The PDF is generated from `workplace-conduct.src.md` by `scripts/build_pdf.py`, so its heading set is
the source's by construction (spec §6.2); its *text*, however, is extracted from the committed PDF with
`pypdf`, so a quote that did not survive rendering fails this check.

This module is also the corpus reader for `scripts/corpus_stats.py` and for the `tests/unit/test_corpus_*`
and `test_facts_quotes` tests. It is deliberately not `core/corpusread.py`, which is P4's index-backed
reader over the chunked corpus.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml
from bs4 import BeautifulSoup
from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "corpus"
FACTS_PATH = CORPUS_DIR / "facts.yml"
RULES_PATH = CORPUS_DIR / "rules.yml"
MOCK_DATA = REPO_ROOT / "mock_data"

#: Files under `corpus/` that are index or documentation rather than policy documents.
NON_DOCUMENT_STEMS = {"facts", "rules", "README"}

HEADING_SEPARATOR = " > "

#: The only keys a `rules.yml` requirement may carry. Spec §8.4 fixes the tool's output schema and says
#: each requirement names a `fact_key`, a `doc_id` and a `heading_path`; it does not say how a
#: requirement is *evaluated*. P5 owns that and adopted P2's proposed grammar, so `check`, `applies_when`
#: and `blocking` joined the set here in the same commit as `mcpserver/rules.py` — the deliberate,
#: reviewed act the header of `corpus/rules.yml` asks for. The grammar's own closed vocabulary is
#: enforced by the engine and by `tests/unit/test_rules_engine.py`, not here.
REQUIREMENT_KEYS = frozenset({"id", "text", "label", "fact_key", "doc_id", "heading_path"})
#: Keys a requirement may carry but need not: a requirement with no `check` is not evaluable.
OPTIONAL_REQUIREMENT_KEYS = frozenset({"check", "applies_when", "blocking"})

#: A `fact_key` prefix that names a field of the employee's own balance row rather than a fact
#: (W8, C29). `mcpserver/rules.py::Context.resolve_fact_key` reads it; this file checks that every
#: value the committed data puts there is a real fact.
BALANCE_FACT_KEY_PREFIX = "pto_balance."

#: `mock_data/pto_balances.json` fields this file cross-checks against the corpus (W8, C29). The
#: data layer had been encoding two rules the corpus does not publish: the accrual band quoted on
#: the decisive PTO requirement was `pto.accrual.ft_3y_plus` for everybody, and the December
#: blackout was on all twenty-four employees although `pto-and-holidays.md` scopes it to three
#: organisations and exempts the rest by name.
BLACKOUT_FACT_KEYS = ("pto.blackout.year_end_2026",)
BLACKOUT_ORGANISATIONS = ("Manufacturing", "Field Service", "Customer Support")
ACCRUAL_BAND_FACT_KEYS = ("pto.accrual.ft_3y_plus", "pto.accrual.ft_under_3y")

#: The running footer `scripts/build_pdf.py` stamps on every PDF page. Dropping it is the
#: "drop the boilerplate footer" half of the uniform cleaning in spec §6.2.
PDF_FOOTER = re.compile(r"^Mosaic Robotics, Inc\. · [a-z0-9-]+ · Page \d+$", re.MULTILINE)

_ATX = re.compile(r"^(#{1,3})\s+(.*?)\s*#*$")
_FENCE = re.compile(r"^\s*(?:```|~~~)")
_TXT_TITLE_RULE = re.compile(r"^=+$")
_TXT_SECTION_RULE = re.compile(r"^-{3,}$")
_TXT_SUBSECTION = re.compile(r"^[A-Z][A-Z0-9 ,'&()./-]*[A-Z0-9)]$")
_TOPICS_LINE = re.compile(r"^\s*Topics:\s*(.+?)\s*$", re.MULTILINE)


def normalise(text: str) -> str:
    """Collapse every run of whitespace to a single space — the comparison form for quotes."""
    return " ".join(text.split())


@dataclass(frozen=True)
class Section:
    """One leaf of a document: its `" > "`-joined heading path and its own body text."""

    heading_path: str
    text: str


@dataclass(frozen=True)
class Document:
    """One policy document, as rendered text plus its heading structure."""

    doc_id: str
    path: Path
    source_format: str
    title: str
    topics: tuple[str, ...]
    text: str
    sections: tuple[Section, ...]

    @property
    def heading_paths(self) -> tuple[str, ...]:
        return tuple(section.heading_path for section in self.sections if section.heading_path)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def section_text(self, heading_path: str) -> str:
        for section in self.sections:
            if section.heading_path == heading_path:
                return section.text
        raise KeyError(f"{self.doc_id}: no section {heading_path!r}")


def _assemble(levels: list[tuple[int, str]], body: list[str]) -> Section:
    path = HEADING_SEPARATOR.join(name for _, name in levels)
    return Section(heading_path=path, text="\n".join(body).strip())


def _sections_from_headings(lines: list[tuple[int | None, str]]) -> tuple[str, tuple[Section, ...]]:
    """Fold `(level, line)` pairs into a title and an ordered list of sections.

    `level` is 0 for the document title, 1 or 2 for a heading, and `None` for body text.
    """
    title = ""
    open_levels: list[tuple[int, str]] = []
    body: list[str] = []
    sections: list[Section] = []
    for level, line in lines:
        if level is None:
            body.append(line)
            continue
        sections.append(_assemble(open_levels, body))
        body = []
        if level == 0:
            title = line
            open_levels = []
        else:
            open_levels = [entry for entry in open_levels if entry[0] < level]
            open_levels.append((level, line))
    sections.append(_assemble(open_levels, body))
    return title, tuple(sections)


def _markdown_lines(text: str) -> list[tuple[int | None, str]]:
    lines: list[tuple[int | None, str]] = []
    in_fence = False
    for raw in text.splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
            lines.append((None, raw))
            continue
        match = None if in_fence else _ATX.match(raw)
        if match:
            lines.append((len(match.group(1)) - 1, match.group(2)))
        else:
            lines.append((None, raw))
    return lines


def _text_lines(text: str) -> list[tuple[int | None, str]]:
    raw_lines = text.splitlines()
    lines: list[tuple[int | None, str]] = []
    skip_next = False
    for index, raw in enumerate(raw_lines):
        if skip_next:
            skip_next = False
            continue
        stripped = raw.strip()
        following = raw_lines[index + 1].strip() if index + 1 < len(raw_lines) else ""
        if stripped and _TXT_TITLE_RULE.fullmatch(following):
            lines.append((0, stripped))
            skip_next = True
        elif stripped and _TXT_SECTION_RULE.fullmatch(following):
            lines.append((1, stripped))
            skip_next = True
        elif raw == stripped and _TXT_SUBSECTION.fullmatch(stripped):
            lines.append((2, stripped))
        else:
            lines.append((None, raw))
    return lines


def _html_lines(html: str) -> list[tuple[int | None, str]]:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup
    lines: list[tuple[int | None, str]] = []
    for element in body.find_all(["h1", "h2", "h3", "p", "li", "td", "th"]):
        content = normalise(element.get_text(" "))
        if not content:
            continue
        if element.name in ("h1", "h2", "h3"):
            lines.append((int(element.name[1]) - 1, content))
        else:
            lines.append((None, content))
    return lines


def _pdf_text(path: Path) -> str:
    pages = [page.extract_text() or "" for page in PdfReader(str(path)).pages]
    return PDF_FOOTER.sub("", "\n".join(pages))


def _topics(text: str) -> tuple[str, ...]:
    match = _TOPICS_LINE.search(text)
    if not match:
        return ()
    return tuple(topic.strip() for topic in match.group(1).split(",") if topic.strip())


def _load_one(path: Path) -> Document:
    suffix = path.suffix.lstrip(".")
    if suffix == "md":
        text = path.read_text(encoding="utf-8")
        title, sections = _sections_from_headings(_markdown_lines(text))
    elif suffix == "html":
        raw = path.read_text(encoding="utf-8")
        lines = _html_lines(raw)
        title, sections = _sections_from_headings(lines)
        text = "\n".join(line for _, line in lines)
    elif suffix == "txt":
        text = path.read_text(encoding="utf-8")
        title, sections = _sections_from_headings(_text_lines(text))
    elif suffix == "pdf":
        source = path.with_suffix(".src.md")
        title, sections = _sections_from_headings(_markdown_lines(source.read_text(encoding="utf-8")))
        text = _pdf_text(path)
    else:  # pragma: no cover - guarded by the caller's glob
        raise ValueError(f"unsupported corpus format: {path}")
    return Document(
        doc_id=path.stem,
        path=path,
        source_format=suffix,
        title=title,
        topics=_topics(text),
        text=text,
        sections=sections,
    )


def load_documents(corpus_dir: Path = CORPUS_DIR) -> dict[str, Document]:
    """Load every policy document under `corpus_dir`, keyed by `doc_id`.

    `<stem>.src.md` files are the PDF's source and are not documents in their own right, and
    `facts.yml`, `rules.yml` and `README.md` are index rather than policy.
    """
    documents: dict[str, Document] = {}
    for path in sorted(corpus_dir.iterdir()):
        if path.suffix not in (".md", ".html", ".txt", ".pdf"):
            continue
        if path.stem in NON_DOCUMENT_STEMS or path.name.endswith(".src.md"):
            continue
        documents[path.stem] = _load_one(path)
    return documents


def load_facts(path: Path = FACTS_PATH) -> dict[str, dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["facts"]


def load_rules(path: Path = RULES_PATH) -> dict[str, dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["scenarios"]


def load_mock(name: str) -> list[dict]:
    """One committed mock-data file's records, or `[]` when it is not there (nothing to check)."""
    path = MOCK_DATA / f"{name}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["records"]


def _published_blackout_dates(facts: dict[str, dict]) -> set[str]:
    """Every date the corpus publishes as a blackout, expanded from its `start..end` ranges."""
    published: set[str] = set()
    for key in BLACKOUT_FACT_KEYS:
        value = str(facts.get(key, {}).get("value") or "")
        start_text, _, end_text = value.partition("..")
        try:
            start = date.fromisoformat(start_text)
            end = date.fromisoformat(end_text or start_text)
        except ValueError:
            continue
        cursor = start
        while cursor <= end:
            published.add(cursor.isoformat())
            cursor += timedelta(days=1)
    return published


def check_mock_data(facts: dict[str, dict]) -> list[str]:
    """The data layer against the corpus: every blackout date scoped, every accrual band real.

    Two rules, both from `corpus/pto-and-holidays.md` (W8, C29):

    * a blackout date on an employee's row must be one the corpus publishes, **and** that employee
      must be in one of the organisations the corpus says it applies to;
    * `accrual_fact_key` must name a real accrual band and `accrual_rate_days_per_month` must equal
      that band's published rate times the employee's FTE — the rate and the quote a requirement
      shows the reader cannot be allowed to describe different bands.
    """
    problems: list[str] = []
    employees = {row["employee_id"]: row for row in load_mock("employees")}
    published = _published_blackout_dates(facts)
    for row in load_mock("pto_balances"):
        employee = employees.get(row["employee_id"], {})
        where = f"pto_balances.json: {row['employee_id']}"
        for day in row.get("blackout_dates") or []:
            if day not in published:
                problems.append(f"{where}: blackout date {day} is published in no facts.yml blackout range")
            elif employee.get("department") not in BLACKOUT_ORGANISATIONS:
                problems.append(
                    f"{where}: blackout date {day} is scoped to {', '.join(BLACKOUT_ORGANISATIONS)} "
                    f"and this employee is in {employee.get('department')!r}"
                )
        key = row.get("accrual_fact_key")
        if key not in ACCRUAL_BAND_FACT_KEYS:
            problems.append(f"{where}: accrual_fact_key {key!r} is not one of {ACCRUAL_BAND_FACT_KEYS}")
            continue
        expected = round(float(facts[key]["value"]) * float(employee.get("fte") or 1.0), 2)
        if round(float(row["accrual_rate_days_per_month"]), 2) != expected:
            problems.append(
                f"{where}: accrual_rate_days_per_month {row['accrual_rate_days_per_month']} disagrees with "
                f"{key} ({facts[key]['value']} × FTE {employee.get('fte')} = {expected})"
            )
    return problems


def check_corpus() -> list[str]:
    """Return a list of human-readable problems; an empty list means the corpus is consistent."""
    documents = load_documents()
    facts = load_facts()
    problems: list[str] = []

    for key, fact in sorted(facts.items()):
        document = documents.get(fact["doc_id"])
        if document is None:
            problems.append(f"facts.yml: {key}: unknown doc_id {fact['doc_id']!r}")
            continue
        if normalise(fact["quote"]) not in normalise(document.text):
            problems.append(f"facts.yml: {key}: quote is not verbatim in {document.path.name}")
        if fact["section"] not in document.heading_paths:
            problems.append(
                f"facts.yml: {key}: section {fact['section']!r} is not a heading path in {document.path.name}"
            )

    for scenario, spec in sorted(load_rules().items()):
        for requirement in spec["requirements"]:
            rid = f"rules.yml: {scenario}.{requirement['id']}"
            extra = sorted(set(requirement) - REQUIREMENT_KEYS - OPTIONAL_REQUIREMENT_KEYS)
            if extra:
                problems.append(
                    f"{rid}: unexpected requirement key(s) {extra} — the requirement grammar is a closed "
                    f"vocabulary (see the header of rules.yml); add the key to REQUIREMENT_KEYS or "
                    f"OPTIONAL_REQUIREMENT_KEYS in scripts/check_facts.py in the same commit if that is a "
                    f"deliberate decision"
                )
            missing = sorted(REQUIREMENT_KEYS - set(requirement))
            if missing:
                problems.append(f"{rid}: missing requirement key(s) {missing}")
            # The reader label is what the chat surface calls the measured thing (W8 fix round,
            # JX3-01): a requirement without one would fall back to its policy text, never to a
            # key, but the build fails here so the fallback is never the shipped state.
            label = str(requirement.get("label") or "").strip()
            if not label or "_" in label:
                problems.append(f"{rid}: `label` must be a non-empty reader phrase with no underscores")
            fact_key = str(requirement["fact_key"])
            if fact_key.startswith(BALANCE_FACT_KEY_PREFIX):
                # An indirect key: the employee's own balance row holds the real one (W8, C29).
                field = fact_key[len(BALANCE_FACT_KEY_PREFIX) :]
                for row in load_mock("pto_balances"):
                    resolved = row.get(field)
                    if resolved not in facts:
                        problems.append(
                            f"{rid}: fact_key {fact_key!r} resolves to {resolved!r} for "
                            f"{row['employee_id']}, which is not in facts.yml"
                        )
            elif fact_key not in facts:
                problems.append(f"{rid}: fact_key {fact_key!r} is not in facts.yml")
            document = documents.get(requirement["doc_id"])
            if document is None:
                problems.append(f"{rid}: unknown doc_id {requirement['doc_id']!r}")
            elif requirement["heading_path"] not in document.heading_paths:
                problems.append(
                    f"{rid}: heading_path {requirement['heading_path']!r} is not a heading path in {document.path.name}"
                )

    return problems + check_mock_data(facts)


def main() -> int:
    documents = load_documents()
    facts = load_facts()
    rules = load_rules()
    for doc_id, document in documents.items():
        print(f"  {doc_id:<34} {document.source_format:<5} {len(document.heading_paths):>3} sections")
    print(
        f"\n{len(documents)} documents · {len(facts)} facts · {len(rules)} rule scenarios · "
        f"{sum(len(spec['requirements']) for spec in rules.values())} requirements"
    )

    problems = check_corpus()
    if problems:
        print(f"\nFAIL — {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("OK — every quote is verbatim, every heading path is real, every fact_key resolves,")
    print("     every blackout date is published and scoped, every accrual rate matches its band.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
