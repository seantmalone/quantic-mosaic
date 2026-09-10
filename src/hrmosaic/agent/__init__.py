"""The agent package (spec §9): the MCP client, the router, the loop, the guardrails, the workflows.

Import boundary (§4.2): `web/ → agent/ → core/`, and `agent/ →` (the MCP **wire** only) `→
mcpserver/`. Nothing under `agent/**` imports `hrmosaic.mcpserver` — the tools are reached over a
real MCP session on whichever of the three transports is configured, which is what makes the
topology a real client talking to a real server rather than a function call wearing a costume.
`tests/architecture/test_conventions.py` greps for the import.

The one exemption is `hrmosaic.core.corpusread`, the read-only index reader: G1's refusal names what
the corpus covers and G2 resolves a cited `chunk_id` against the real index, and neither may go
through a `tools/call` — G1 because a refusal must make **zero** tool calls (§9.2), G2 because
resolving against the retrieved set would let a plausible id from a prior turn resolve (§7.4).

`web/api.py` (P8) needs exactly four names from here.
"""

from __future__ import annotations

from hrmosaic.agent.orchestrator import (
    ChatOptions,
    ChatRequest,
    ChatResponse,
    ConfirmationCard,
    Orchestrator,
    get_orchestrator,
    resume_turn,
    run_turn,
    set_orchestrator,
)

__all__ = [
    "ChatOptions",
    "ChatRequest",
    "ChatResponse",
    "ConfirmationCard",
    "Orchestrator",
    "get_orchestrator",
    "resume_turn",
    "run_turn",
    "set_orchestrator",
]
