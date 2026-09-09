#!/usr/bin/env python3
"""Generate `mock_data/schemas/*.schema.json` from the Pydantic models of `gen_mock_data.py`.

    python scripts/gen_mock_schemas.py

One JSON Schema (draft 2020-12) per dataset, describing the whole file — banner and records —
so `tests/unit/test_mock_schemas.py` can validate the committed JSON against it. The models are
the single source of truth: every model sets `extra="forbid"`, so each schema closes
`additionalProperties` and an accidental new field fails validation rather than travelling
silently into a later phase's tool output.

Like the datasets themselves these are authored-once generator outputs (spec §21 row 28):
committed, reviewed like source, and regenerated only when the models change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.gen_mock_data import MOCK_DATA, MockDataFile, build_all  # noqa: E402

SCHEMAS = MOCK_DATA / "schemas"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def schema_for(name: str, payload: MockDataFile) -> dict:
    """The model's JSON Schema, with the dialect and a stable `$id` in front of it."""
    body = type(payload).model_json_schema()
    return {
        "$schema": DIALECT,
        "$id": f"https://mosaicrobotics.example/schemas/mock_data/{name}.schema.json",
        **body,
    }


def main() -> None:
    SCHEMAS.mkdir(parents=True, exist_ok=True)
    for name, payload in build_all().items():
        path = SCHEMAS / f"{name}.schema.json"
        path.write_text(json.dumps(schema_for(name, payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{path.relative_to(REPO_ROOT)}  {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
