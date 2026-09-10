"""The dataset and artifact types (spec §13.1, §13.10).

Two families of model live here and nothing else:

* **the dataset** — `EvalItem` and `ExpectedEndState`, loaded from `evaluation/dataset.yaml` in
  **file order**, which *is* the run order (§13.6). `load_dataset()` also returns the file's
  sha256, because `evaluation/ablation.py` refuses to compare two runs whose `dataset_sha` differ;
* **the artifacts** — `ItemResult`, `RunMetrics` and `RunFile`, the exact JSON shape
  `core/archive.py` imports into `eval_runs` / `eval_results` and page 11 renders.

`RunMetrics` field names are §11.6's metric-block names, field for field, so
`web/dashboard.py::EvalMetrics` validates a committed run file without a translation layer. Every
judged aggregate is `float | None`: a judge that failed twice yields a `null` verdict and the item
leaves that metric's denominator, never scoring a silent zero (§13.7).
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from hrmosaic.core.ids import SEED

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "evaluation" / "dataset.yaml"
RESULTS_DIR = REPO_ROOT / "evaluation" / "results"
REFERENCE_LABELS_PATH = REPO_ROOT / "evaluation" / "reference_labels.yaml"
REPORT_PATH = REPO_ROOT / "evaluation" / "REPORT.md"

#: The seven §13.1 labels and the count each must carry.
CATEGORY_COUNTS: dict[str, int] = {
    "simple_policy": 7,
    "multi_doc": 5,
    "tool_task": 6,
    "ambiguous": 3,
    "out_of_scope": 3,
    "unsafe_action": 1,
    "sensitive": 1,
}

#: The five gold behaviour classes. `confirm` is its own class because `awaiting_confirmation` is
#: the correct outcome of the `unsafe_action` item and of demo task 2 (§13.1).
Behavior = Literal["answer", "clarify", "confirm", "refuse", "escalate"]

Category = Literal[
    "simple_policy",
    "multi_doc",
    "tool_task",
    "ambiguous",
    "out_of_scope",
    "unsafe_action",
    "sensitive",
]

#: The three ablation arms of §13.9.
Variant = Literal["baseline", "dense_only_k2", "no_structured_tools"]

#: `local` is development and calibration; `deployed` is the single published run (§13.2).
Target = Literal["local", "deployed"]

#: The three cold probes of §13.5 — re-run after an idle period with `run_phase='cold_probe'`.
COLD_PROBE_IDS: tuple[str, ...] = ("pto-001", "remote-001", "benefits-001")

#: The `options` each variant sends on `POST /chat`. This table **is** §13.9's, and it is the only
#: configuration channel: no process restart and no global `remove_tool` (§13.2).
VARIANT_OPTIONS: dict[str, dict[str, Any]] = {
    "baseline": {"retrieval_strategy": "hybrid_rrf", "k": 5, "tools_disabled": []},
    "dense_only_k2": {"retrieval_strategy": "dense_only", "k": 2, "tools_disabled": []},
    "no_structured_tools": {
        "retrieval_strategy": "hybrid_rrf",
        "k": 5,
        "tools_disabled": [
            "lookup_employee_profile",
            "check_pto_balance",
            "lookup_benefits_status",
            "create_mock_hr_ticket",
            "draft_hr_email",
        ],
    },
}


class ExpectedEndState(BaseModel):
    """An executable predicate over the trace **and** the `mock_writes` table (§13.4).

    `kind` says what closing the turn correctly looks like; `requires_tool_results` names the
    structured-data tools whose results must be in state, which is the clause that makes the
    `no_structured_tools` arm move Workflow completion rather than only ToolSelection (§13.9).
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "answer",
        "answer_with_citations",
        "awaiting_confirmation",
        "ticket_created",
        "clarification",
        "refusal",
        "escalation",
    ]
    min_citations: int = 0
    min_distinct_docs: int = 0
    requires_tool_results: list[str] = Field(default_factory=list)
    #: For `awaiting_confirmation` / `ticket_created`: the write tool the turn must have proposed.
    action: str | None = None
    #: For `ticket_created`: the queue and the `mock_writes` payload fields that must be populated.
    queue: str | None = None
    fields: list[str] = Field(default_factory=list)


class EvalItem(BaseModel):
    """One dataset row (§13.1)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    category: Category
    persona: str
    question: str
    gold_answer_short: str
    #: Set on `remote-004` and `pto-003` only — the two demo-workflow mirrors, which is where
    #: `workflow_completion_by_workflow{}` comes from (§13.4).
    workflow: str | None = None
    #: Bare `corpus/facts.yml` keys — never prefixed, never prose.
    gold_facts: list[str] = Field(default_factory=list)
    expected_docs: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    allowed_extra_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_end_state: ExpectedEndState | None = None
    expected_behavior: Behavior
    requires_confirmation: bool = False
    #: The runner's auto-confirm switch. `false` on the `unsafe_action` item, which is what makes
    #: it assert that nothing is written absent a confirmation (§13.1).
    confirm_on_prompt: bool = False
    #: `ambiguous` only: what the clarifying question must name, for the judged sub-check of §13.4.
    clarification_expects: str | None = None
    #: `inj-001` only: assert the canary chunk is quarantined and absent from `citations[]` (G4).
    asserts_injection_quarantined: bool = False

    @property
    def expects_citations(self) -> bool:
        """§13.3's `CitResolve` denominator rule: does this item expect citations at all?"""
        return bool(self.expected_end_state and self.expected_end_state.min_citations >= 1)


class Dataset(BaseModel):
    """The loaded file: its items in file order, plus the sha256 `ablation.py` compares."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    as_of: str
    items: list[EvalItem]
    sha256: str

    def by_id(self, item_id: str) -> EvalItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def select(self, item_ids: list[str] | None = None, n_items: int | None = None) -> list[EvalItem]:
        """A bounded subset **in file order** — never a sort, never a shuffle (§13.6)."""
        chosen = self.items
        if item_ids:
            wanted = set(item_ids)
            chosen = [item for item in chosen if item.id in wanted]
        if n_items is not None:
            chosen = chosen[:n_items]
        return list(chosen)


#: How many items carry an independent groundedness label (§13.7).
REFERENCE_SUBSET_SIZE = 8


def reference_subset(dataset: Dataset, *, size: int = REFERENCE_SUBSET_SIZE) -> list[str]:
    """The `SEED`-selected item ids that carry a blind reference label (§13.6, §13.7).

    `SEED` is used **only** where sampling exists, and this is the one place. The population is
    sorted by id before sampling and `random.Random(SEED)` is seeded explicitly, so the subset is
    element-for-element identical under any `PYTHONHASHSEED` —
    `tests/unit/test_reference_subset_deterministic.py` builds it twice under different values and
    asserts exactly that.

    Only items whose gold behaviour is `answer` are eligible: a refusal, a clarification and an
    escalation carry no policy claims, so there is no groundedness for a labeller to judge.
    """
    population = sorted(item.id for item in dataset.items if item.expected_behavior == "answer")
    return sorted(random.Random(SEED).sample(population, min(size, len(population))))


def load_dataset(path: Path | str = DATASET_PATH) -> Dataset:
    """Read `dataset.yaml`, preserving file order, and hash the bytes that produced it."""
    source = Path(path)
    raw = source.read_bytes()
    document = yaml.safe_load(raw.decode("utf-8")) or {}
    return Dataset(
        dataset_version=str(document.get("dataset_version") or "unknown"),
        as_of=str(document.get("as_of") or ""),
        items=[EvalItem.model_validate(entry) for entry in document.get("items") or []],
        sha256=hashlib.sha256(raw).hexdigest(),
    )


# --------------------------------------------------------------------------------------
# Artifacts (§13.10)
# --------------------------------------------------------------------------------------


class RunConfig(BaseModel):
    """What the run was configured with — stored as `eval_runs.config_json`."""

    model_config = ConfigDict(extra="forbid")

    retrieval_k: int
    retrieval_strategy: str
    tools_disabled: list[str] = Field(default_factory=list)
    llm_model: str
    judge_model: str
    min_evidence_score: float
    min_support_score: float
    #: The token bucket the run was paced behind (§9.4). Recorded because it is the single biggest
    #: influence on a local run's wall clock, and a reader comparing two runs needs to see it.
    llm_rpm: int
    seed: int


class RunMetrics(BaseModel):
    """§11.6's metric block, name for name — `web/dashboard.py::EvalMetrics` validates this.

    Every judged aggregate is optional: on the two ablation arms judging does not happen at all
    (§13.9) and within `baseline` a twice-failed judge leaves the item out of that denominator
    (§13.7). `n_scored` carries the denominator of every metric that has one.
    """

    model_config = ConfigDict(extra="forbid")

    judged: bool = False
    # the four judged aggregates — `baseline` only
    groundedness_mean: float | None = None
    citation_accuracy_mean: float | None = None
    partial_match_mean: float | None = None
    clarification_accuracy: float | None = None
    # the five deterministic aggregates — non-null on every variant
    cit_resolve_mean: float | None = None
    blocks_dropped_by_g2: int | None = None
    tool_selection_accuracy: float | None = None
    arg_correctness_rate: float | None = None
    strict_pass_rate: float | None = None
    # the rest of the block, in §11.6's order
    escalation_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    escalation_n_excluded: int = 0
    over_refusal_rate: float | None = None
    over_refusal_n: int = 0
    missed_refusal_rate: float | None = None
    missed_refusal_n: int = 0
    action_safety_pass_rate: float | None = None
    workflow_completion_by_workflow: dict[str, float] = Field(default_factory=dict)
    recommendation_labeled_rate: float | None = None
    router_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    catalog_reopened_rate: float | None = None
    n_scored: dict[str, int] = Field(default_factory=dict)
    judge_agreement_rate: float | None = None
    judge_agreement_n: int = 0
    est_cost_usd: float | None = None
    # -- beyond §11.6's list, each earning its place --------------------------------------
    #: The run-level mean of `DocRecall_i` — the number `dense_only_k2` moves most (§13.3).
    doc_recall_mean: float | None = None
    #: `Workflow_i` over the items defining an end state — what `no_structured_tools` moves (§13.9).
    workflow_completion: float | None = None
    #: The P8 carry-forward: the share of scored turns whose `plan` span carries a non-empty
    #: `nudges[]`. A nudged turn is one the harness pushed back into the loop, so §13.4's per-turn
    #: scores are only comparable alongside this figure.
    nudge_rate: float | None = None
    #: R8.3: `tools/list` returned ≥ 5 tools, each with a description and an input schema.
    tool_discovery_ok: bool | None = None
    #: Gated write attempts — `CONFIRMATION_REQUIRED` spans, which are not members of `A` (§13.4).
    gated_attempts: int = 0
    #: The §13.5 assertion that the response cache was off during latency measurement.
    cache_hits: int = 0
    #: The G4 evidence carried by `inj-001` (§13.1).
    injection_quarantined: bool | None = None
    # -- latency (§13.5) -------------------------------------------------------------------
    latency_p50_ms: float | None = None
    latency_p90_ms: float | None = None
    latency_p95_ms: float | None = None
    latency_p99_ms: float | None = None
    n_cold: int = 0
    cold_p50_ms: float | None = None
    latency_by_kind_ms: dict[str, int] = Field(default_factory=dict)


class ItemResult(BaseModel):
    """One `eval_results` row (§10.1)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    item_id: str
    category: str
    session_id: str | None = None
    turn_id: str | None = None
    run_phase: Literal["scored", "cold_probe"] = "scored"
    answer: str | None = None
    latency_ms: int | None = None
    cold: int = 0
    scores: dict[str, Any] = Field(default_factory=dict)
    verdicts: dict[str, Any] | None = None
    passed: int = 0


class RunFile(BaseModel):
    """`evaluation/results/<run_id>.json` — exactly what `core/archive.py` imports (§10.3)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: int
    git_sha: str
    label: str
    variant: str
    target: Target
    target_base_url: str
    dataset_sha: str
    config: RunConfig
    n_items: int
    metrics: RunMetrics
    judge_model: str | None = None
    judge_calls: int = 0
    duration_s: float | None = None
    status: str = "complete"
    notes: str | None = None
    items: list[ItemResult] = Field(default_factory=list)


class ReferenceLabel(BaseModel):
    """One blind groundedness label from `evaluation/reference_labels.yaml` (§13.7)."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    verdict: Literal["grounded", "not_grounded"]
    rationale: str


class ReferenceProtocol(BaseModel):
    """The `protocol` block naming the labeller, the date and the blinding (§13.7)."""

    model_config = ConfigDict(extra="forbid")

    labeller: str
    labelled_on: str
    blinding: str
    selection: str
    seed: int
    method: str


class ReferenceLabels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: ReferenceProtocol
    labels: list[ReferenceLabel]


def load_reference_labels(path: Path | str = REFERENCE_LABELS_PATH) -> ReferenceLabels | None:
    """The blind reference set, or `None` before it is authored."""
    source = Path(path)
    if not source.exists():
        return None
    document = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    return ReferenceLabels.model_validate(document)


__all__ = [
    "CATEGORY_COUNTS",
    "COLD_PROBE_IDS",
    "DATASET_PATH",
    "REFERENCE_LABELS_PATH",
    "REFERENCE_SUBSET_SIZE",
    "REPORT_PATH",
    "RESULTS_DIR",
    "VARIANT_OPTIONS",
    "Behavior",
    "Category",
    "Dataset",
    "EvalItem",
    "ExpectedEndState",
    "ItemResult",
    "ReferenceLabel",
    "ReferenceLabels",
    "ReferenceProtocol",
    "RunConfig",
    "RunFile",
    "RunMetrics",
    "Target",
    "Variant",
    "load_dataset",
    "load_reference_labels",
    "reference_subset",
]
