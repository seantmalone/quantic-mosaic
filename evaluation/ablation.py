"""The three-variant comparison (spec §13.9). `make ablation` is `python -m evaluation.ablation`.

**This module only compares runs that already exist** under `evaluation/results/`. It never
executes a variant — which is why each phase runs the two non-baseline arms itself — and it
asserts that every run it compares shares the same `target` **and** the same `dataset_sha`, so
`comparison.json` can never mix a deployed run with two local ones.

**A null result is surfaced, never misreported.** The interpretive claim behind the
`no_structured_tools` arm is that the agentic layer does real work rather than decorating a RAG
bot, and the test of that claim is

```
workflow_completion(no_structured_tools) < workflow_completion(baseline) − 0.25
```

If it does not hold, `evaluation/REPORT.md` carries an explicit *not supported by this run* banner
in place of the standard narrative and this script **exits non-zero**, so the main session sees it.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evaluation import runner as runner_module
from evaluation.schema import RESULTS_DIR, RunFile

logger = logging.getLogger(__name__)

#: §13.9's threshold for "the agentic layer does real work".
WORKFLOW_DELTA_THRESHOLD = 0.25

#: The order the comparison publishes, `baseline` first.
VARIANT_ORDER: tuple[str, ...] = ("baseline", "dense_only_k2", "no_structured_tools")

#: The metrics the compare tab plots. Each is judge-free except the first two, which are `baseline`
#: only — page 11 footnotes which metric was judged on which variant (§13.9).
COMPARED_METRICS: tuple[str, ...] = (
    "groundedness_mean",
    "citation_accuracy_mean",
    "cit_resolve_mean",
    "doc_recall_mean",
    "tool_selection_accuracy",
    "arg_correctness_rate",
    "workflow_completion",
    "over_refusal_rate",
    "strict_pass_rate",
)

NOT_SUPPORTED_BANNER = """\
> ⚠ **The `no_structured_tools` variant did not move Workflow completion; the interpretive claim
> below is NOT supported by this run.** §13.9 predicts
> `workflow_completion(no_structured_tools) < workflow_completion(baseline) − {threshold}`; the
> observed values are baseline **{baseline}** and no_structured_tools **{variant}**
> (delta **{delta}**). Read the table as a measurement, not as evidence that the agentic layer
> does the work."""

SUPPORTED_NARRATIVE = """\
Withdrawing the five structured-data tools moved Workflow completion from **{baseline}** to
**{variant}** (delta **{delta}**, past §13.9's {threshold} threshold) while Groundedness stayed
broadly flat — which is the signal the arm exists to produce: the agentic layer does real work
rather than decorating a RAG bot. `check_policy_compliance` is deliberately left available, so this
is not "an agent with no tools"; the movement comes from §9.3's completion predicates, which
require a `lookup_employee_profile` result and a `check_pto_balance` result **in state**."""


class AblationError(RuntimeError):
    """The compared runs are not comparable — a mixed target or a moved dataset."""


def load_runs(results_dir: Path = RESULTS_DIR) -> dict[str, RunFile]:
    """The newest run of each variant under `results_dir`, keyed by variant."""
    newest: dict[str, RunFile] = {}
    for path in sorted(Path(results_dir).glob("*.json")):
        if path.name in ("latest.json", "comparison.json", "chunk_size_comparison.json"):
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("could not read %s; skipping it", path)
            continue
        if not (isinstance(document, dict) and "run_id" in document and "metrics" in document):
            continue
        run = RunFile.model_validate(document)
        current = newest.get(run.variant)
        if current is None or run.created_at > current.created_at:
            newest[run.variant] = run
    return newest


def assert_comparable(runs: Sequence[RunFile]) -> None:
    """Same `target`, same `dataset_sha` — the two ways a comparison silently becomes a lie."""
    targets = {run.target for run in runs}
    if len(targets) > 1:
        raise AblationError(
            "the runs do not share a target: " + ", ".join(f"{run.variant}={run.target}" for run in runs)
        )
    shas = {run.dataset_sha for run in runs}
    if len(shas) > 1:
        raise AblationError(
            "the runs do not share a dataset_sha: " + ", ".join(f"{run.variant}={run.dataset_sha[:12]}" for run in runs)
        )


def _delta(baseline: float | None, variant: float | None) -> float | None:
    if baseline is None or variant is None:
        return None
    return round(variant - baseline, 4)


def build_comparison(runs: dict[str, RunFile]) -> dict[str, Any]:
    """`comparison.json`: the metric vector per variant, plus the workflow-completion check."""
    ordered = [runs[name] for name in VARIANT_ORDER if name in runs]
    assert_comparable(ordered)
    baseline = runs.get("baseline")

    variants = []
    for run in ordered:
        metrics = run.metrics.model_dump(mode="json")
        variants.append(
            {
                "variant": run.variant,
                "run_id": run.run_id,
                "judged": run.metrics.judged,
                "judge_status": run.judge_status,
                "metrics": {name: metrics.get(name) for name in COMPARED_METRICS},
                "deltas": {
                    name: _delta(
                        None if baseline is None else baseline.metrics.model_dump(mode="json").get(name),
                        metrics.get(name),
                    )
                    for name in COMPARED_METRICS
                }
                if baseline is not None and run.variant != "baseline"
                else {},
            }
        )

    check = workflow_check(runs)
    return {
        "generated_at": None,
        "target": ordered[0].target if ordered else None,
        "dataset_sha": ordered[0].dataset_sha if ordered else None,
        "variants": variants,
        "workflow_completion_check": check,
        "flips": _flips(runs),
        "note": (
            "Judged metrics are computed on `baseline` only (§13.9); a `null` on an ablation arm "
            "means not judged, never zero."
        ),
    }


def workflow_check(runs: dict[str, RunFile]) -> dict[str, Any]:
    """§13.9's explicit check, with every input recorded so the banner can quote them."""
    baseline = runs.get("baseline")
    variant = runs.get("no_structured_tools")
    base_value = baseline.metrics.workflow_completion if baseline else None
    arm_value = variant.metrics.workflow_completion if variant else None
    if base_value is None or arm_value is None:
        return {
            "supported": False,
            "reason": "both baseline and no_structured_tools runs are needed",
            "baseline": base_value,
            "no_structured_tools": arm_value,
            "delta": None,
            "threshold": WORKFLOW_DELTA_THRESHOLD,
        }
    delta = arm_value - base_value
    return {
        "supported": arm_value < base_value - WORKFLOW_DELTA_THRESHOLD,
        "reason": None,
        "baseline": round(base_value, 4),
        "no_structured_tools": round(arm_value, 4),
        "delta": round(delta, 4),
        "threshold": WORKFLOW_DELTA_THRESHOLD,
    }


def _flips(runs: dict[str, RunFile]) -> list[dict[str, Any]] | None:
    """Every scored item whose pass flips against `baseline` — what the compare tab lists.

    `None`, not `[]`, while the baseline is `judge_status: pending`. A pending item's `passed` is
    the same vacuous `strict_pass` §13.8 withholds the composite over — every clause that needs a
    judge is trivially true on it — so the flips computed against it are an artefact of what was
    never scored, not a measurement. `render_section` prints "not computable — judge pending"
    instead of a list that would read as one.
    """
    baseline = runs.get("baseline")
    if baseline is None:
        return []
    if baseline.judge_status == "pending":
        return None
    before = {item.item_id: bool(item.passed) for item in baseline.items if item.run_phase == "scored"}
    flips: list[dict[str, Any]] = []
    for name in VARIANT_ORDER:
        if name == "baseline" or name not in runs:
            continue
        for item in runs[name].items:
            if item.run_phase != "scored" or item.item_id not in before:
                continue
            if before[item.item_id] != bool(item.passed):
                flips.append(
                    {
                        "item_id": item.item_id,
                        "variant": name,
                        "baseline_passed": before[item.item_id],
                        "variant_passed": bool(item.passed),
                    }
                )
    return flips


def render_section(comparison: dict[str, Any]) -> str:
    """The `## Ablation` body: the table, then the banner or the narrative."""
    variants = comparison["variants"]
    if not variants:
        return runner_module.ABLATION_PLACEHOLDER
    header = "| Metric | " + " | ".join(entry["variant"] for entry in variants) + " |"
    divider = "|---" * (len(variants) + 1) + "|"
    rows = []
    for name in COMPARED_METRICS:
        cells = []
        for entry in variants:
            value = entry["metrics"].get(name)
            if value is not None or entry["judged"]:
                cells.append(runner_module.fmt(value))
            else:
                # "not judged" and "judge pending" are different facts about an absent cell: §13.9
                # judges `baseline` only, so an arm's blank is by design, while a baseline's blank
                # means the judged half has not been computed **yet** (§13.2's two-pass shape).
                cells.append("judge pending" if entry.get("judge_status") == "pending" else "not judged")
        rows.append(f"| `{name}` | " + " | ".join(cells) + " |")
    table = "\n".join([header, divider, *rows])

    check = comparison["workflow_completion_check"]
    body = (SUPPORTED_NARRATIVE if check["supported"] else NOT_SUPPORTED_BANNER).format(
        baseline=runner_module.fmt(check["baseline"]),
        variant=runner_module.fmt(check["no_structured_tools"]),
        delta=runner_module.fmt(check["delta"]),
        threshold=check["threshold"],
    )
    flips = comparison["flips"]
    if flips is None:
        flip_lines = (
            "\n\nItems whose strict pass flips against `baseline`: **not computable — judge "
            "pending.** Every clause of `strict_pass` that needs a judge is vacuously true on an "
            "unjudged item, so the baseline's per-item `passed` cannot be compared against yet "
            "(§13.8). Run `python -m evaluation.runner --judge <baseline run_id>`, then "
            "`make ablation` again."
        )
    elif flips:
        flip_lines = "\n\nItems whose strict pass flips against `baseline`: " + ", ".join(
            f"`{flip['item_id']}` ({flip['variant']})" for flip in flips
        )
    else:
        flip_lines = "\n\nNo item's strict pass flipped against `baseline`."
    footnote = (
        "\n\nAll three runs share `target: "
        f"{comparison['target']}` and `dataset_sha: {str(comparison['dataset_sha'])[:16]}…`, which "
        "`evaluation/ablation.py` asserts before it writes anything. " + comparison["note"]
    )
    return f"{table}\n\n{body}{flip_lines}{footnote}"


def update_report(comparison: dict[str, Any]) -> None:
    """Replace the `## Ablation` body between the two markers, and nothing else."""
    path = runner_module.REPORT_PATH
    if not path.exists():
        logger.warning("no %s to update; run the harness first", path)
        return
    text = path.read_text(encoding="utf-8")
    begin, end = runner_module.ABLATION_BEGIN, runner_module.ABLATION_END
    if begin not in text or end not in text:
        logger.warning("%s carries no ablation markers; leaving it alone", path)
        return
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    path.write_text(f"{head}{begin}\n{render_section(comparison)}\n{end}{tail}", encoding="utf-8")
    logger.info("updated %s", path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare the three ablation variants (§13.9).")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    directory = Path(args.results_dir)
    runs = load_runs(directory)
    missing = [name for name in VARIANT_ORDER if name not in runs]
    if missing:
        print(f"missing run(s) for: {', '.join(missing)}", file=sys.stderr)  # noqa: T201 — CLI
        return 2
    try:
        comparison = build_comparison(runs)
    except AblationError as exc:
        print(f"runs are not comparable: {exc}", file=sys.stderr)  # noqa: T201 — CLI
        return 2

    from hrmosaic.core.db import now_micros

    comparison["generated_at"] = now_micros()
    path = directory / "comparison.json"
    path.write_text(json.dumps(comparison, indent=1) + "\n", encoding="utf-8")
    logger.info("wrote %s", path)
    update_report(comparison)

    check = comparison["workflow_completion_check"]
    print(json.dumps(check, indent=1))  # noqa: T201 — CLI
    if not check["supported"]:
        print(  # noqa: T201 — CLI
            "the no_structured_tools variant did not move workflow completion past the "
            f"{WORKFLOW_DELTA_THRESHOLD} threshold; REPORT.md carries the not-supported banner",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "COMPARED_METRICS",
    "NOT_SUPPORTED_BANNER",
    "SUPPORTED_NARRATIVE",
    "VARIANT_ORDER",
    "WORKFLOW_DELTA_THRESHOLD",
    "AblationError",
    "assert_comparable",
    "build_comparison",
    "load_runs",
    "main",
    "render_section",
    "update_report",
    "workflow_check",
]
