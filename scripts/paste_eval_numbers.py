"""Fill `design-and-evaluation.md`'s results table from a committed evaluation run.

This is the **only** thing any script writes into a documentation file in this repository, and it
writes between two markers and nowhere else:

    <!-- EVAL-NUMBERS:BEGIN -->  …the table…  <!-- EVAL-NUMBERS:END -->

Everything outside those markers is hand-authored. There is no docs generator, and **no CI
diff-check of documentation** (spec §21 row 28, §22 row 13): an earlier design regenerated blocks
in CI and deadlocked — a docs commit triggering a regenerate that triggered a docs commit — and
failed builds on wording edits.

**Source.** `evaluation/results/latest.json`, which the runner writes only for a `deployed`
`baseline` run. That run is BLOCKED-BY-GATE until the Render account exists (gates 2 and 4 of
`NEEDS-FROM-USER.md`), so until then this script falls back to the newest committed `baseline`
run file, marks the table's provenance line accordingly, and prints which source it used. It
never invents a figure, and it never presents a `local` run as if it were the published one.
"Newest" is read from **inside** the file — the run's `created_at`, or the epoch in its
`r_<seconds>_<variant>` id — never from `st_mtime`, which git does not preserve and a fresh clone
therefore assigns arbitrarily (see `run_sort_key`).

Usage:

    python scripts/paste_eval_numbers.py            # rewrite the block in place
    python scripts/paste_eval_numbers.py --check    # exit 1 if the block is stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "evaluation" / "results"
LATEST = RESULTS_DIR / "latest.json"
DESIGN_DOC = REPO_ROOT / "design-and-evaluation.md"

BEGIN = "<!-- EVAL-NUMBERS:BEGIN -->"
END = "<!-- EVAL-NUMBERS:END -->"

#: (label, metrics key, n key in `n_scored`, the design target where one exists)
ROWS: list[tuple[str, str, str | None, str]] = [
    ("Groundedness (mean, claim-level)", "groundedness_mean", "groundedness", "≥ 0.90"),
    ("Citation accuracy (CitResolve × F1)", "citation_accuracy_mean", "citation_accuracy", "–"),
    ("Citation resolvability (served answer)", "cit_resolve_mean", "cit_resolve", "≥ 0.95"),
    ("Document recall", "doc_recall_mean", "doc_recall", "–"),
    ("Partial match (gold facts entailed)", "partial_match_mean", "partial_match", "–"),
    ("Tool selection (F1, order-insensitive)", "tool_selection_accuracy", "tool_selection", "–"),
    ("Argument correctness", "arg_correctness_rate", "arg_correctness", "–"),
    ("Workflow completion", "workflow_completion", "workflow", "–"),
    ("Action safety pass rate", "action_safety_pass_rate", "safety", "1.00"),
    ("Clarification accuracy", "clarification_accuracy", "clarification", "–"),
    ("Over-refusal rate", "over_refusal_rate", None, "lower is better"),
    ("Missed-refusal rate", "missed_refusal_rate", None, "lower is better"),
    ("Strict pass rate (composite)", "strict_pass_rate", "items", "≥ 0.85"),
]


def _fmt(value: Any) -> str:
    if value is None:
        return "not judged"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _ms(value: Any) -> str:
    """Milliseconds read as whole numbers; a percentile of 17670.0 ms is not a 3-decimal quantity."""
    return "–" if value is None else f"{round(float(value)):,}"


#: `r_<epoch seconds>_<variant>` — the run id the runner mints, and the fallback ordering key for
#: a run file written before `created_at` existed.
RUN_ID_EPOCH = re.compile(r"^r_(\d+)_")


def _epoch_seconds(value: Any) -> float | None:
    """A run timestamp normalised to seconds, whatever unit it was written in.

    The runner writes `created_at` in **microseconds**; the run id embeds **seconds**. Comparing
    the two raw would order every microsecond stamp above every second stamp, so both are scaled
    into the same unit here. Anything beyond ~year 5138 in seconds is a finer unit.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    seconds = float(value)
    while seconds > 1e11:
        seconds /= 1000.0
    return seconds


def run_sort_key(path: Path) -> tuple[float, str]:
    """Order committed runs by the timestamp **inside** the file, never by the filesystem's.

    `st_mtime` was the original key and it is not a property of the run: git records no mtime, so
    every file in a fresh clone carries its checkout time, in whatever order the checkout happened
    to write them. A CI job and a developer's laptop could therefore paste different figures from
    the same commit. `created_at` — and, for a file that predates it, the epoch in the run id — is
    written by the run itself and survives a clone.
    """
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (-1.0, path.name)
    if not isinstance(run, dict):
        return (-1.0, path.name)
    stamp = _epoch_seconds(run.get("created_at"))
    if stamp is None:
        match = RUN_ID_EPOCH.match(str(run.get("run_id") or path.stem))
        stamp = _epoch_seconds(int(match.group(1))) if match else None
    # `path.name` breaks ties deterministically rather than leaving glob order to decide.
    return (stamp if stamp is not None else -1.0, path.name)


def _load_run() -> tuple[dict, str]:
    """The published run if it exists, else the newest committed `baseline` run."""
    if LATEST.exists():
        pointer = json.loads(LATEST.read_text(encoding="utf-8"))
        run_id = pointer.get("run_id") if isinstance(pointer, dict) else None
        # `latest.json` may be the pointer or the run itself; accept both.
        if run_id and "metrics" not in pointer:
            run_path = RESULTS_DIR / f"{run_id}.json"
            return json.loads(run_path.read_text(encoding="utf-8")), str(LATEST.relative_to(REPO_ROOT))
        return pointer, str(LATEST.relative_to(REPO_ROOT))

    candidates = sorted(RESULTS_DIR.glob("*_baseline.json"), key=run_sort_key)
    if not candidates:
        raise SystemExit(
            "no evaluation run to read: evaluation/results/latest.json is absent (gates 2 and 4) "
            "and no *_baseline.json is committed"
        )
    newest = candidates[-1]
    return json.loads(newest.read_text(encoding="utf-8")), str(newest.relative_to(REPO_ROOT))


def render(run: dict, source: str) -> str:
    metrics = run["metrics"]
    counts = metrics.get("n_scored", {})
    target = run.get("target", "unknown")

    lines: list[str] = []
    if target == "deployed":
        lines.append(
            f"**The published run.** `{run['run_id']}` · variant `{run['variant']}` · "
            f"target **`deployed`** · {run['n_items']} items · agent "
            f"`{run.get('config', {}).get('llm_model', 'claude-haiku-4-5')}` · judge "
            f"`{run.get('judge_model')}` · dataset sha `{run['dataset_sha'][:16]}…`."
        )
    else:
        lines.append(
            f"> ⚠ **`BLOCKED-BY-GATE` — these are the `target: {target}` proving-run figures, not "
            "the published ones.** `evaluation/results/latest.json` can only ever name a "
            "`target: deployed`, `variant: baseline` run, and that run needs the live service "
            "(gates 2 and 4 of `NEEDS-FROM-USER.md`). The exact commands that produce it, and "
            "then re-run this script, are in `NEEDS-FROM-USER.md` §3."
        )
        lines.append("")
        lines.append(
            f"**The run below.** `{run['run_id']}` · variant `{run['variant']}` · target "
            f"`{target}` · {run['n_items']} items · agent "
            f"`{run.get('config', {}).get('llm_model', 'claude-haiku-4-5')}` · judge "
            f"`{run.get('judge_model')}` · dataset sha `{run['dataset_sha'][:16]}…` · "
            f"estimated spend ${metrics.get('est_cost_usd', 0):.4f}."
        )

    lines.append("")
    lines.append("| Metric | Value | n | Target |")
    lines.append("|---|---|---|---|")
    for label, key, count_key, goal in ROWS:
        if key not in metrics:
            continue
        count = counts.get(count_key) if count_key else metrics.get(f"{key.removesuffix('_rate')}_n")
        lines.append(f"| {label} | {_fmt(metrics[key])} | {count if count is not None else '–'} | {goal} |")

    lines.append(
        f"| Latency p50 / p95 (ms) | {_ms(metrics.get('latency_p50_ms'))} / "
        f"{_ms(metrics.get('latency_p95_ms'))} | "
        f"{counts.get('items', run['n_items'])} | – |"
    )
    lines.append(f"| Cold turns in the distribution | n_cold = {metrics.get('n_cold', 0)} | – | reported separately |")
    lines.append("")
    lines.append(
        "**Behaviour, from the same run.** Escalation matrix over five gold classes with "
        f"`escalation_n_excluded` = {metrics.get('escalation_n_excluded', 0)}; "
        f"`nudge_rate` = {_fmt(metrics.get('nudge_rate'))}; "
        f"`catalog_reopened_rate` = {_fmt(metrics.get('catalog_reopened_rate'))}; "
        f"`gated_attempts` = {metrics.get('gated_attempts')} (write calls the confirmation gate "
        "refused — deliberately *not* members of the action-safety population); "
        f"`injection_quarantined` = {str(metrics.get('injection_quarantined')).lower()}; "
        f"`blocks_dropped_by_g2` = {metrics.get('blocks_dropped_by_g2')}; "
        "`workflow_completion_by_workflow` = "
        f"{json.dumps(metrics.get('workflow_completion_by_workflow', {}))}."
    )
    lines.append("")
    if target != "deployed":
        lines.append(
            "⚠ **Latency here is not representative.** It was measured against a developer "
            "laptop, not the 0.1-CPU deployed instance; the dashboard renders these greyed out "
            "and labelled."
        )
        lines.append("")
    lines.append(f"*Figures written by `scripts/paste_eval_numbers.py` from `{source}`. Do not hand-edit.*")
    return "\n".join(lines)


def splice(text: str, block: str) -> str:
    start = text.index(BEGIN) + len(BEGIN)
    stop = text.index(END)
    return text[:start] + "\n" + block + "\n" + text[stop:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the block is stale, write nothing")
    args = parser.parse_args()

    run, source = _load_run()
    text = DESIGN_DOC.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        raise SystemExit(f"{DESIGN_DOC.name} carries no {BEGIN} / {END} markers")

    updated = splice(text, render(run, source))
    if args.check:
        if updated != text:
            print(f"STALE — design-and-evaluation.md's results table does not match {source}", file=sys.stderr)
            return 1
        print(f"OK — the results table matches {source}")
        return 0

    if updated == text:
        print(f"unchanged — the results table already matches {source}")
        return 0
    DESIGN_DOC.write_text(updated, encoding="utf-8")
    print(f"wrote design-and-evaluation.md's results table from {source} (target: {run.get('target')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
