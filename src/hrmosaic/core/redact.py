"""G6 — redaction of every trace payload before persistence (spec §7.4 G6, §10.4).

Three mechanisms, in order:

1. **key-name denylist** — a key matching `(?i)(api[_-]?key|token|secret|password|authorization|
   cookie|bearer)` has its whole value replaced with `"[REDACTED]"`;
2. **value regexes** — provider key shapes (`sk-ant-…`, `sk-…`, `AIza…`), JWTs and long base64 runs;
3. **an exact-match environment sweep** — every `os.environ` value whose key ends `_KEY`, `_TOKEN`
   or `_SECRET` is searched for as a literal substring and replaced.

**Preserved:** the integer token-count fields of an `llm_call` payload, which the denylist's
`token` pattern would otherwise eat — `prompt_tokens`, `completion_tokens` and `total_tokens`
(the three §10.4 names) plus the two cache counters of the same class, so the dashboard's token
and cost columns stay honest.
"""

from __future__ import annotations

import os
import re
from typing import Any

REDACTED = "[REDACTED]"

#: A value shorter than this is never swept: a two-character secret would turn every payload
#: into confetti, and no real credential is that short.
MIN_SWEEPABLE_LENGTH = 8

KEY_DENYLIST = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|cookie|bearer)")

#: Integer token counts on `llm_call` payloads. Exempt from the denylist by name (§10.4).
PRESERVED_KEYS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    }
)

CREDENTIAL_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET")

VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{12,}"),  # Anthropic
    re.compile(r"sk-[A-Za-z0-9\-_]{16,}"),  # OpenAI-shaped
    re.compile(r"AIza[A-Za-z0-9\-_]{16,}"),  # Google
    re.compile(r"eyJ[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}"),  # JWT
    re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{64,}={0,2}(?![A-Za-z0-9+/=])"),  # long base64 run
)


def _environment_secrets() -> list[str]:
    """The literal credential values currently in the process environment, longest first."""
    values = {
        value
        for name, value in os.environ.items()
        if name.upper().endswith(CREDENTIAL_SUFFIXES) and len(value) >= MIN_SWEEPABLE_LENGTH
    }
    return sorted(values, key=len, reverse=True)


def redact_text(text: str) -> str:
    """Scrub one string: value regexes, then the exact-match environment sweep."""
    for pattern in VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    for secret in _environment_secrets():
        if secret in text:
            text = text.replace(secret, REDACTED)
    return text


def _is_denied(key: str) -> bool:
    return key.lower() not in PRESERVED_KEYS and bool(KEY_DENYLIST.search(key))


def _walk(value: Any, key: str | None) -> Any:
    if key is not None and _is_denied(key):
        return REDACTED
    if isinstance(value, dict):
        return {name: _walk(item, str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_walk(item, key) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact(payload: Any) -> Any:
    """Redact a payload — a dict, a list, a string or a scalar — returning a new object."""
    return _walk(payload, None)
