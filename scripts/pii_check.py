#!/usr/bin/env python3
"""Fail the build if anything under `mock_data/` looks like real personal data (spec §5.4).

    python scripts/pii_check.py        # exit 0 = clean, exit 1 = one line per hit

Two passes over every committed file in `mock_data/` — the datasets, the generated schemas and
the README:

1. **Field names.** No key (and, in a schema, no declared property) may name a national
   identifier, a date of birth or a street address. "No SSN field in any schema" is a shape
   guarantee, not a data guarantee: the field cannot exist, so it cannot be populated later.
2. **Text shapes.** No US SSN pattern anywhere; every email address at `@mosaicrobotics.example`
   (RFC 2606 reserves `.example`); every phone number inside the reserved fictional
   `+1-555-01xx` block.

This runs in CI's `test` job (P3's one-line addition, spec §22 row 14) and is cheap enough to
run by hand before any commit that touches the datasets.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_DATA = REPO_ROOT / "mock_data"

EMAIL_DOMAIN = "mosaicrobotics.example"

# Tokens that must never appear in a snake_case field name. Matched per underscore-separated
# token, so `postal_code` is caught while `cost_center` is not.
# fmt: off
FORBIDDEN_NAME_TOKENS = frozenset(
    {
        "ssn", "sin", "nino", "nin",
        "socialsecurity", "nationalid", "taxid", "passport", "driverslicense", "license",
        "dob", "birthdate", "birthday", "birth",
        "address", "street", "postal", "postcode", "zip", "zipcode",
        "homephone", "personalemail", "mobile", "cell",
    }
)
# fmt: on
FORBIDDEN_NAME_PHRASES = ("social_security", "date_of_birth", "national_id", "tax_id", "street_address")

SSN_SHAPE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A full E.164-ish token: bounded on both sides so documentation placeholders such as
# `+1-555-01xx` and the schemas' own escaped regex `\+1-555-01[0-9]{2}` are not read as
# numbers — only a complete, standalone number is.
PHONE = re.compile(r"(?<![\w\-\\])\+\d[\d\-]{6,}(?![\w\-])")
ALLOWED_PHONE = re.compile(r"^\+1-555-01\d{2}$")


def _files() -> list[Path]:
    return sorted(path for path in MOCK_DATA.rglob("*") if path.is_file())


def _walk_names(node: object) -> list[str]:
    names: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            names.append(key)
            names.extend(_walk_names(value))
    elif isinstance(node, list):
        for item in node:
            names.extend(_walk_names(item))
    return names


def _bad_name(name: str) -> bool:
    lowered = name.lower().lstrip("_")
    if any(phrase in lowered for phrase in FORBIDDEN_NAME_PHRASES):
        return True
    return any(token in FORBIDDEN_NAME_TOKENS for token in lowered.split("_"))


def check_field_names(path: Path) -> list[str]:
    if path.suffix != ".json":
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    where = path.relative_to(REPO_ROOT)
    return [f"{where}: forbidden field name {name!r}" for name in _walk_names(payload) if _bad_name(name)]


def check_text_shapes(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    hits = [f"{path.relative_to(REPO_ROOT)}: SSN-shaped string {match.group()!r}" for match in SSN_SHAPE.finditer(text)]
    hits += [
        f"{path.relative_to(REPO_ROOT)}: email outside @{EMAIL_DOMAIN}: {match.group()!r}"
        for match in EMAIL.finditer(text)
        if not match.group().endswith(f"@{EMAIL_DOMAIN}")
    ]
    hits += [
        f"{path.relative_to(REPO_ROOT)}: phone outside the reserved +1-555-01xx block: {match.group()!r}"
        for match in PHONE.finditer(text)
        if not ALLOWED_PHONE.match(match.group())
    ]
    return hits


def main() -> int:
    files = _files()
    if not files:
        print(f"pii_check: no files under {MOCK_DATA.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1

    hits: list[str] = []
    for path in files:
        hits.extend(check_field_names(path))
        hits.extend(check_text_shapes(path))

    if hits:
        print(f"pii_check: {len(hits)} problem(s) in mock_data/:", file=sys.stderr)
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        return 1

    print(f"pii_check: clean — {len(files)} files, no SSN shapes, no non-.example addresses, no non-555 numbers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
