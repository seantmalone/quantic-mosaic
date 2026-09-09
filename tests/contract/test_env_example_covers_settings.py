"""`.env.example` and `Settings` must agree in both directions (spec §12.3)."""

import re
from pathlib import Path

from hrmosaic.settings import DERIVED_FIELDS, Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# A key line is `NAME=...` at line start, or the commented `# NAME=` form reserved for
# fields whose default is computed (§12.3).
KEY_LINE = re.compile(r"^(?P<commented>#\s*)?(?P<key>[A-Z][A-Z0-9_]*)=(?P<rest>.*)$")
MARKER = re.compile(r"\bREQUIRED\b|\bOPTIONAL\b")


def _key_lines() -> dict[str, str]:
    keys: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = KEY_LINE.match(line)
        if match:
            keys[match.group("key")] = line
    return keys


def test_every_settings_field_is_documented_with_a_marker():
    keys = _key_lines()
    missing = []
    unmarked = []
    for name in Settings.model_fields:
        if name in DERIVED_FIELDS:
            continue
        key = name.upper()
        if key not in keys:
            missing.append(key)
        elif not MARKER.search(keys[key]):
            unmarked.append(key)
    assert missing == [], f".env.example is missing: {missing}"
    assert unmarked == [], f".env.example entries without a REQUIRED/OPTIONAL marker: {unmarked}"


def test_every_env_example_key_is_a_real_settings_field():
    fields = {name.upper() for name in Settings.model_fields}
    stale = sorted(key for key in _key_lines() if key not in fields)
    assert stale == [], f".env.example carries keys that are not Settings fields: {stale}"


def test_env_example_declares_no_removed_variables():
    """§12.3: there is deliberately no SEED, no NOW_OVERRIDE and no OTEL variable."""
    keys = _key_lines()
    forbidden = [key for key in keys if key in {"SEED", "NOW_OVERRIDE", "EVAL_FIXED_NOW"} or key.startswith("OTEL_")]
    assert forbidden == [], f".env.example declares variables the spec forbids: {forbidden}"
