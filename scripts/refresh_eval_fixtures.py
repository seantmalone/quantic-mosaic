"""Rebuild `tests/fixtures/eval_runs/` from the three committed P10 runs (§13.10).

The dashboard's contract tests do not fabricate an eval run: they import one, through the same
`core/archive.py` path a real run takes, and then assert what page 11 renders. This script is what
makes those fixtures *derived* artifacts rather than hand-written ones, and committing it is what
makes them reproducible — `python scripts/refresh_eval_fixtures.py` regenerates them byte for byte
from the run files in `evaluation/results/`.

Three properties are deliberate:

* **The run ids stay `r_p9fixture_<variant>`.** `tests/contract/test_dashboard_pages.py` and
  `tests/contract/test_dashboard_viewmodels.py` address them by name, and the committed real runs
  are imported at every boot (§10.3), so a fixture that kept its real `<run_id>::<item_id>` primary
  key would collide with the row the real run already put in `eval_results`.
* **The item rows are verbatim.** Six items with a full behaviour spread — including one that flips
  on both ablation arms — are copied out of the run file unmodified. Nothing is re-scored.
* **The run-level metrics are re-derived over exactly those six by `Runner.assemble()`**, so each
  fixture is the shipped aggregation of its own rows rather than a second description of it. A
  fixture cannot drift from the aggregator without the aggregator itself changing.

The only synthetic content is the three trailing `cold_probe` rows, and each fixture's `_note` says
so: a local process never spins down, so a real §13.5 cold probe on this host can only ever record
`cold = 0`, and page 11's cold/warm split needs rows to render.

    python scripts/refresh_eval_fixtures.py
    python scripts/refresh_eval_fixtures.py <baseline_run_id> <arm_run_id> <arm_run_id>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # `python scripts/<name>.py` puts this file's own directory on sys.path, not the repository
    # root, so the `evaluation` package (which is not installed) would not import.
    sys.path.insert(0, str(REPO_ROOT))

from evaluation import deterministic as det  # noqa: E402
from evaluation.runner import Runner, RunOptions, ScoredItem  # noqa: E402
from evaluation.schema import RESULTS_DIR, Dataset, ItemResult, RunFile, load_dataset  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "eval_runs"

#: The three variants, in §13.9's order. The positional arguments are the run ids, in this order.
VARIANTS: tuple[str, str, str] = ("baseline", "dense_only_k2", "no_structured_tools")

#: The three committed P10 runs the fixtures currently ship from — the defaults, so that the
#: regeneration command in the docstring reproduces the committed files with no arguments.
DEFAULT_RUN_IDS: tuple[str, str, str] = (
    "r_1789032950_baseline",
    "r_1789033498_dense_only_k2",
    "r_1789034108_no_structured_tools",
)

#: Six items with a full behaviour spread — an answer, a multi-doc answer, a tool workflow that
#: flips on both arms, a clarification, a refusal and the escalation — so the fixture exercises
#: every row page 11 can render.
KEEP: tuple[str, ...] = ("pto-001", "onboarding-001", "remote-004", "amb-001", "oos-001", "sens-001")

#: The three §13.5 cold probes, and the latency each synthetic probe row is given.
COLD: dict[str, int] = {"pto-001": 42_180, "remote-001": 39_640, "benefits-001": 44_910}

NOTE = (
    "Refreshed at P10 from the real local run `{run_id}` (§13.10): six item rows taken verbatim "
    "from that run, and the run-level metrics re-derived over exactly those six by "
    "`evaluation.runner.Runner.assemble()` — the shipped aggregation, not a second description of "
    "it. The three trailing `cold_probe` rows are the file's only synthetic content: a local "
    "process never spins down, so a real §13.5 cold probe on this host can only ever record "
    "`cold = 0`, and page 11's cold/warm split needs rows to render. The run id is held at "
    "`r_p9fixture_{variant}` because the dashboard tests address it by name. Regenerate with "
    "`python scripts/refresh_eval_fixtures.py`."
)


def scored_from(result: ItemResult, dataset: Dataset) -> ScoredItem:
    """Re-wrap a stored row as the `ScoredItem` the aggregator consumes.

    The per-item numbers are read straight back off the row — nothing is re-scored here, because a
    fixture that re-derived its own item scores would stop being the run it claims to be.
    """
    item = dataset.by_id(result.item_id)
    usage = det.ToolUsage(called=list(result.scores.get("tools_called") or []), gated=[], failed=[], ok_spans=[])
    return ScoredItem(
        result=result,
        item=item,
        turn=None,
        gold_behavior=item.expected_behavior,
        predicted_behavior=det.behaviour_class(result.scores.get("outcome") or "error"),
        tool=det.tool_scores(item, usage),
        doc_recall=result.scores.get("doc_recall"),
        workflow=result.scores.get("workflow"),
        groundedness=result.scores.get("groundedness"),
        citation_accuracy=result.scores.get("citation_accuracy"),
        partial_match=result.scores.get("partial_match"),
        clarification=result.scores.get("clarification"),
        cost_usd=0.0,
    )


def build_fixture(variant: str, run_id: str, *, dataset: Dataset, results_dir: Path) -> RunFile:
    """One fixture: the six kept rows plus three cold probes, aggregated by the real aggregator."""
    source = RunFile.model_validate(json.loads((results_dir / f"{run_id}.json").read_text(encoding="utf-8")))
    fixture_id = f"r_p9fixture_{variant}"
    rows = [row for row in source.items if row.item_id in KEEP and row.run_phase == "scored"]
    if len(rows) != len(KEEP):
        raise SystemExit(f"{variant}: expected {list(KEEP)}, got {[row.item_id for row in rows]}")

    scored = [scored_from(row, dataset) for row in rows]
    for probe_id, latency in COLD.items():
        base = next(row for row in source.items if row.item_id == probe_id)
        probe = base.model_copy(
            update={
                "id": f"{fixture_id}::{probe_id}::cold",
                "run_phase": "cold_probe",
                "cold": 1,
                "latency_ms": latency,
            }
        )
        scored.append(scored_from(probe, dataset))

    runner = Runner(
        RunOptions(variant=variant, base_url="http://127.0.0.1:8000", judge=False, write_report=False),
        dataset=dataset,
        judge=None,
    )
    runner.run_id = fixture_id
    # `assemble()` reads this to decide whether the judged aggregates belong in the file at all;
    # §13.9 judges `baseline` only, and the two arms must render "not judged", not a zero.
    runner._judge_enabled = variant == "baseline"
    run = runner.assemble(scored, duration_s=source.duration_s or 0.0)

    # Provenance is the source run's, not this process's.
    run.created_at = source.created_at
    run.git_sha = source.git_sha
    run.target_git_sha = source.target_git_sha
    run.label = f"P10 fixture — {variant}"
    run.dataset_sha = source.dataset_sha
    run.judge_model = source.judge_model
    run.judge_calls = source.judge_calls
    run.judge_status = source.judge_status
    run.config = source.config
    run.metrics.est_cost_usd = source.metrics.est_cost_usd
    run.metrics.judge_agreement_rate = source.metrics.judge_agreement_rate
    run.metrics.judge_agreement_n = source.metrics.judge_agreement_n
    run.metrics.judge_agreement_subset = source.metrics.judge_agreement_subset
    run.metrics.judge_agreement_rate_hard = source.metrics.judge_agreement_rate_hard
    run.metrics.judge_agreement_n_hard = source.metrics.judge_agreement_n_hard
    run.metrics.judge_agreement_subset_hard = source.metrics.judge_agreement_subset_hard
    run.notes = NOTE.format(run_id=run_id, variant=variant)
    for row in run.items:
        row.id = f"{fixture_id}::{row.item_id}" + ("::cold" if row.run_phase == "cold_probe" else "")
    return run


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "run_ids",
        nargs="*",
        default=list(DEFAULT_RUN_IDS),
        metavar="RUN_ID",
        help=f"the three run ids, in the order {', '.join(VARIANTS)} (default: the committed P10 runs)",
    )
    parser.add_argument("--results-dir", default=str(RESULTS_DIR))
    parser.add_argument("--out-dir", default=str(FIXTURE_DIR))
    args = parser.parse_args(argv)

    run_ids = list(args.run_ids) or list(DEFAULT_RUN_IDS)
    if len(run_ids) != len(VARIANTS):
        parser.error(f"expected {len(VARIANTS)} run ids ({', '.join(VARIANTS)}), got {len(run_ids)}")

    dataset = load_dataset()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for variant, run_id in zip(VARIANTS, run_ids, strict=True):
        run = build_fixture(variant, run_id, dataset=dataset, results_dir=Path(args.results_dir))
        body = json.dumps(run.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n"
        (out_dir / f"{run.run_id}.json").write_text(body, encoding="utf-8")
        print(  # noqa: T201 — this is a CLI
            f"{run.run_id}  from {run_id}  items={len(run.items)}  judged={run.metrics.judged}  "
            f"judge_status={run.judge_status}  strict_pass_rate={run.metrics.strict_pass_rate}  "
            f"n_cold={run.metrics.n_cold}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
