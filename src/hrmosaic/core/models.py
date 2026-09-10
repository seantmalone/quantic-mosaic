"""The span-payload union, the answer view-models, `strict_json_schema()` and `MODEL_PRICES`.

`payload_json` is **one Pydantic discriminated union on `kind`** (spec §10.2) — the single most
important type in the project. Every span written by `core/trace.py` carries one of these nine
payloads, and every reader (the `/chat` `trace[]`, the SSE rail, the dashboard, the eval scorers)
parses the same union, so there is exactly one description of what a record contains.

The answer models of §7.3 live here too, because `strict_json_schema()` — which inlines `$defs`
and asserts the strict-mode invariants (`required == list(properties)`, `additionalProperties is
False` at every level) — is the function that makes them usable as a constrained-JSON schema.
"""

from __future__ import annotations

import copy
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------------------
# Vocabularies (§10.1, §10.2)
# --------------------------------------------------------------------------------------

SpanKind = Literal[
    "mcp_discovery",
    "plan",
    "llm_call",
    "retrieval",
    "tool_call",
    "guardrail",
    "confirmation",
    "judge",
    "error",
]

SpanStatus = Literal["ok", "error"]

TurnOutcome = Literal[
    "answered",
    "clarify",
    "refused",
    "escalated",
    "awaiting_confirmation",
    "partial",
    "error",
    "configuration_required",
    "maintenance",
]

AuthMode = Literal["cookie", "bearer", "open"]
ActorRole = Literal["employee", "admin"]
ClientLabel = Literal["web", "api", "eval", "demo", "eval_judge", "maintenance"]
LlmPurpose = Literal["route", "act", "synthesize", "repair", "judge", "decompose"]
RetrievalStrategy = Literal["hybrid_rrf", "dense_only"]
GuardrailVerdict = Literal["allow", "refuse", "redirect", "warn", "repair", "strip", "escalate"]
ConfirmationResponse = Literal["pending", "confirmed", "declined", "expired"]


class _Payload(BaseModel):
    """Shared configuration: unknown fields are a bug, not a silent extra column."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------
# Payload members
# --------------------------------------------------------------------------------------


class ServerInfo(_Payload):
    name: str
    version: str


class DiscoveredTool(_Payload):
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None


class McpDiscoveryPayload(_Payload):
    kind: Literal["mcp_discovery"] = "mcp_discovery"
    server: str
    transport: str
    url: str | None = None
    protocol_version: str | None = None
    server_info: ServerInfo | None = None
    tools: list[DiscoveredTool] = Field(default_factory=list)
    tool_count: int = 0
    catalog_sha: str | None = None
    mcp_session_id: str | None = None
    cached: bool = False
    handshake_ms: int | None = None
    discovered_at: int | None = None


class PlanPayload(_Payload):
    """Operational only — never raw chain-of-thought (§9.7)."""

    kind: Literal["plan"] = "plan"
    intent: str
    workflow: str | None = None
    step_summaries: list[str] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)
    rationale_summary: str = ""
    step_index: int = 0
    catalog_reopened: bool = False
    #: Which of the act loop's deterministic reminders fired on this turn (§9.1 step 2) —
    #: `workflow_incomplete`, `action_outstanding`. A nudged turn is one the harness pushed back
    #: into the loop, so §13.4's per-turn scores are only comparable alongside a `nudge_rate`;
    #: recording the names here is what lets P10 report one. **Defaulted on purpose**: rows written
    #: before the field existed still parse as `PlanPayload` (§10.2).
    nudges: list[str] = Field(default_factory=list)


class MessagesRef(_Payload):
    """Points at the `llm_messages` rows holding the exact prompt bytes (§10.1)."""

    span_id: str
    n_messages: int
    total_chars: int


class ProposedToolCall(_Payload):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class LlmCallPayload(_Payload):
    kind: Literal["llm_call"] = "llm_call"
    provider: str
    model: str
    purpose: LlmPurpose
    messages_ref: MessagesRef | None = None
    tools_offered: list[str] = Field(default_factory=list)
    response_text: str | None = None
    tool_calls: list[ProposedToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd_estimate: float = 0.0
    temperature: float = 0.0
    retry_count: int = 0
    cache_hit: bool = False
    limiter_wait_ms: int = 0
    provider_failover: bool = False
    structured_output_mode: str | None = None
    ttfb_ms: int | None = None


class RetrievedChunk(_Payload):
    chunk_id: str
    doc_id: str
    doc_title: str
    heading_path: str
    section: str
    rank: int
    dense_score: float
    bm25_rank: int | None = None
    rrf_score: float | None = None
    snippet: str
    quarantined: bool = False


class RetrievalPayload(_Payload):
    kind: Literal["retrieval"] = "retrieval"
    query: str
    k: int
    k_source: Literal["model", "override", "default"]
    filters: dict[str, Any] = Field(default_factory=dict)
    strategy: RetrievalStrategy
    min_dense_score: float | None = None
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    max_dense_score: float | None = None
    embed_ms: int | None = None
    search_ms: int | None = None
    index_version: str | None = None
    #: `topic` is a soft filter (§8.4): when it alone yields fewer than `k` hits or a single
    #: document, the rest is backfilled from an unfiltered search of the same query. They move
    #: together — `backfill_reason` is set only when the widening actually added a hit, so
    #: `topic_backfilled: false` always carries `backfill_reason: null`. Both fields are defaulted
    #: so `retrieval` rows written before the P10 fix round still parse — they predate the widening
    #: and read back as the plain topic search they were.
    topic_backfilled: bool = False
    backfill_reason: Literal["fewer_than_k", "single_document"] | None = None


class ToolCallPayload(_Payload):
    kind: Literal["tool_call"] = "tool_call"
    server: str
    transport: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_json: str | None = None
    structured_content: dict[str, Any] | None = None
    is_error: bool = False
    error_code: str | None = None
    duration_ms: int | None = None
    server_timing_ms: int | None = None
    discovery_source: Literal["tools/list"] = "tools/list"
    actor_employee_id: str | None = None
    actor_source: Literal["explicit", "default"] = "default"


class GuardrailPayload(_Payload):
    kind: Literal["guardrail"] = "guardrail"
    rule_id: Literal["G1", "G2", "G3", "G4", "G5", "G6"]
    rule_name: str
    verdict: GuardrailVerdict
    reason: str = ""
    evidence_span_ids: list[str] = Field(default_factory=list)
    matched_pattern: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ConfirmationPayload(_Payload):
    """Never the token, and `arguments_preview` is a display subset (§10.2)."""

    kind: Literal["confirmation"] = "confirmation"
    action: str
    arguments_preview: dict[str, Any] = Field(default_factory=dict)
    human_summary: str
    prompt_shown: str
    expires_at: int
    user_response: ConfirmationResponse = "pending"
    resolved_at: int | None = None


class JudgePayload(_Payload):
    """Written by `evaluation/runner.py` into its own `client_label='eval_judge'` session."""

    kind: Literal["judge"] = "judge"
    metric: str
    judge_provider: str
    judge_model: str
    prompt: str
    raw: str
    parsed: dict[str, Any] = Field(default_factory=dict)
    repair_attempts: int = 0
    item_id: str
    run_id: str
    scored_turn_id: str


class ErrorPayload(_Payload):
    kind: Literal["error"] = "error"
    error_kind: str
    message: str
    retryable: bool = False
    component: str | None = None
    upstream_status: int | None = None


SpanPayload = Annotated[
    McpDiscoveryPayload
    | PlanPayload
    | LlmCallPayload
    | RetrievalPayload
    | ToolCallPayload
    | GuardrailPayload
    | ConfirmationPayload
    | JudgePayload
    | ErrorPayload,
    Field(discriminator="kind"),
]


class SpanPayloadEnvelope(BaseModel):
    """Parsing seam for the union — `SpanPayloadEnvelope(payload=…).payload`."""

    model_config = ConfigDict(extra="forbid")
    payload: SpanPayload


def parse_payload(payload: dict[str, Any]) -> Any:
    """Parse a stored `payload_json` dict into its typed member of the §10.2 union."""
    return SpanPayloadEnvelope(payload=payload).payload


PAYLOAD_MODELS: dict[str, type[_Payload]] = {
    "mcp_discovery": McpDiscoveryPayload,
    "plan": PlanPayload,
    "llm_call": LlmCallPayload,
    "retrieval": RetrievalPayload,
    "tool_call": ToolCallPayload,
    "guardrail": GuardrailPayload,
    "confirmation": ConfirmationPayload,
    "judge": JudgePayload,
    "error": ErrorPayload,
}


# --------------------------------------------------------------------------------------
# Answer view-models (§7.3) — no defaults anywhere: strict mode rejects them
# --------------------------------------------------------------------------------------


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    doc_id: str
    doc_title: str
    heading_path: str
    section: str
    snippet: str
    score: float
    quarantined: bool
    source_url: str


class AnswerBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["policy_fact", "recommendation", "escalation"]
    text: str
    citations: list[str]

    @field_validator("citations")
    @classmethod
    def _policy_facts_are_cited(cls, value: list[str], info) -> list[str]:
        if info.data.get("type") == "policy_fact" and not value:
            raise ValueError("a policy_fact block must carry at least one citation")
        return value


class AnswerSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocks: list[AnswerBlock]
    next_steps: list[str]
    rationale_summary: str


class TraceEntry(BaseModel):
    """One line of the `/chat` `trace[]` projection (§11.1)."""

    model_config = ConfigDict(extra="forbid")
    seq: int
    kind: SpanKind
    name: str
    duration_ms: int | None = None
    status: SpanStatus = "ok"
    summary: str = ""
    args_preview: str | None = None
    result_preview: str | None = None
    detail_url: str | None = None


# --------------------------------------------------------------------------------------
# Strict JSON schema (§7.3)
# --------------------------------------------------------------------------------------


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            resolved = copy.deepcopy(defs[ref.split("/")[-1]])
            resolved.update({key: value for key, value in node.items() if key != "$ref"})
            return _inline_refs(resolved, defs)
        return {key: _inline_refs(value, defs) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def _assert_strict(node: Any, path: str = "$") -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            properties = list(node["properties"])
            required = node.get("required", [])
            if required != properties:
                raise ValueError(f"{path}: required {required} != properties {properties}")
            if node.get("additionalProperties") is not False:
                raise ValueError(f"{path}: additionalProperties must be false")
        for key, value in node.items():
            _assert_strict(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _assert_strict(item, f"{path}[{index}]")


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The JSON schema of `model` with `$defs` inlined, asserted strict-mode compatible.

    Raises `ValueError` when any object level would be rejected by
    `response_format: {"type": "json_schema", "strict": true}` — a field carrying a default, or a
    model without `extra="forbid"`.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})
    inlined = _inline_refs(schema, defs)
    _assert_strict(inlined)
    return inlined


# --------------------------------------------------------------------------------------
# Cost accounting (§9.8)
# --------------------------------------------------------------------------------------

#: USD per million tokens. Re-verified against the live pricing page at P10 step 0 (§3.1).
MODEL_PRICES: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
    "gemini-3.5-flash-lite": {"input": 0.0, "output": 0.0, "cache_write": 0.0, "cache_read": 0.0},
}

_PER_MTOK = 1_000_000.0


def estimate_cost_usd(
    model: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    """`llm_call.cost_usd_estimate`. An unpriced model estimates 0.0 — always an estimate (§9.8)."""
    prices = MODEL_PRICES.get(model)
    if not prices:
        return 0.0
    total = (
        prompt_tokens * prices["input"]
        + completion_tokens * prices["output"]
        + cache_creation_input_tokens * prices["cache_write"]
        + cache_read_input_tokens * prices["cache_read"]
    )
    return total / _PER_MTOK
