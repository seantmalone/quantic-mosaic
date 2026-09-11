"""The §7.4 injection-pattern table and the pure scan over it — the half both sides need.

`agent/guardrails/g4.py` is still the **only public name** for the injection shield: it re-exports
`PATTERNS` and `scan` and owns everything with a policy in it (the `guardrail` span, the quarantine
decisions, the tool-result shield). What lives here is the part with no policy at all — a regex
table and a first-match-wins search — because two packages on opposite sides of §4.2's dependency
arrow have to agree on it byte for byte.

**Why it moved.** W2-C makes a `search_policy_documents` hit carry the whole stored chunk. The
BLOCKING requirement of that lever is that a quarantined chunk's full text is never put on the wire,
and `mcp/server_entrypoint.py --http` is deliberately publicly reachable (§15, R-12) so a grader can
attach MCP Inspector — so "the wire" is not only the loopback hop to our own client. The decision
therefore has to be taken in `mcpserver/tools/search_policy_documents.py`, which may import `core/`
and may **not** import `hrmosaic.agent` (§4.2: `mcpserver/ → rag/ → core/`; measured, that import
pulls ~2,800 modules and ~0.9 s of `anthropic`/`openai`/`uvicorn` into the stdio server process —
`import hrmosaic.agent.guardrails.g4` = 2,823 modules / 0.85 s against
`import hrmosaic.core.injection` = 12 / 0.003 s).

The agent still runs its own scan on the way in (`g4.quarantine_tool_result`). That is not
redundancy for its own sake: a client that trusts a server to police its own output has no shield at
all against any other MCP server it is pointed at, and the agent reaches its tools over a wire.
"""

from __future__ import annotations

import re

#: The §7.4 table, verbatim in shape. Each entry is `(name, pattern)`; the name is what the
#: `guardrail` span records as `matched_pattern`, so the dashboard names the rule that fired
#: rather than echoing a regex.
#:
#: A quarantined chunk is shown with a warning banner and **cannot be cited**: G2 strips the
#: citation, the block is dropped, and G1 may then refuse — on camera. So a false positive here is
#: as dangerous as a false negative, and the patterns are scoped to **imperative-to-assistant**
#: forms rather than to the bare verbs. Our own corpus legitimately says *"send your case details to
#: people-ops@mosaicrobotics.example"*, and demo task 1 has to cite the People Ops mobility contact.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_previous_instructions",
        re.compile(
            r"(?i)\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all)\b"
            r"[^.\n]{0,40}\b(instruction|prompt|rule|direction)s?\b"
        ),
    ),
    ("role_header", re.compile(r"(?im)^\s*(system|assistant)\s*:")),
    ("persona_override", re.compile(r"(?i)\byou are now\b")),
    ("act_as_assistant", re.compile(r"(?i)\bact as (an?|the)\b[^.\n]{0,30}\b(assistant|ai|model)\b")),
    (
        "exfiltration",
        re.compile(r"(?i)\b(exfiltrat|leak)\w*\b[^.\n]{0,40}\b(roster|database|credential|secret|key)s?\b"),
    ),
    (
        "bulk_data_imperative",
        re.compile(
            r"(?i)\b(email|send|forward|post)\b[^.\n]{0,30}\b(the )?"
            r"(roster|employee list|database|all (records|employees))\b"
        ),
    ),
    ("tool_call_frame", re.compile(r"(?i)<tool_call")),
    ("chat_template_frame", re.compile(r"<\|im_start\|>")),
    ("long_base64_run", re.compile(r"[A-Za-z0-9+/]{201,}={0,2}")),
)


def scan(text: str) -> tuple[str, str] | None:
    """The pure rule: `(pattern_name, excerpt)` for the first pattern that matches, else `None`.

    First match wins and the scan stops: the verdict is binary — the chunk is quarantined or it is
    not — and naming one pattern keeps the span readable. The excerpt is capped so a span payload
    never carries a document.
    """
    for name, pattern in PATTERNS:
        found = pattern.search(text)
        if found is not None:
            return name, found.group(0)[:200]
    return None


__all__ = ["PATTERNS", "scan"]
