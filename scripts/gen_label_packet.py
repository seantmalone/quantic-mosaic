"""Build a blind groundedness-labelling packet for one of §13.7's two reference subsets.

Deliberately judge-free. It reads three things and nothing else:

* `evaluation/dataset.yaml` — for the question text, and to run the subset selector;
* the run file — for `item_id` → `turn_id` and the **served answer**;
* the trace store the run wrote — for the spans the synthesis prompt was built from.

`scores` and `verdicts` are the judge's output and are **never** read into the packet, so a labeller
working from it cannot see a groundedness score, a per-claim verdict or a rationale. Neither is
REPORT.md, the run's notes or any phase report.

The evidence is `evaluation.runner._evidence_of` — called, never re-derived. There is exactly one
definition of "the evidence the judge scores against" in this project, and the packet and the judge
render the same items with the same labels, so they cannot disagree by construction. (This builder
got it wrong twice in two different ways before that rule existed: first it showed the
320-character display snippet of each chunk instead of its stored text, then it showed only the
`retrieval` class, so a correct fact the agent had read out of the employee's own benefits record
looked unsupported.)

Two subsets, `--subset`:

* `seed` (default) — the 8 items of `evaluation.schema.reference_subset()`, sampled with
  `SEED = 1729` over the gold-`answer` population **before any judge verdict existed**. Blind in
  selection as well as in labelling. This is the original §13.7 protocol and its default `--n` is
  unchanged.
* `judge_lowest` — the 8 gold-`answer` items with the lowest judge groundedness in the run, ties
  broken by item id (`evaluation.schema.judge_lowest_subset()`). It exists because the seed subset
  came back 8/8 `grounded` on both sides: its agreement matrix has no discriminating cell, so the
  rate over it cannot separate a good judge from one that answers `grounded` to everything.

**The selection criterion is disclosed in the artifacts, not in the packet.** `judge_lowest` picks
items using the judge's own scores, and `evaluation/reference_labels_hard.yaml` records that as
`selection_disclosed: true` — the report says so too, and never merges the two figures. What must
not happen is the *labeller* learning it: told "these are the eight the judge liked least", a
labeller drifts toward `not_grounded` and manufactures the very disagreement the subset was built
to detect. So the packet states that a selection criterion exists and is withheld, and renders the
items **in item-id order**, never in score order, so the ranking cannot leak through the sequence.

    python scripts/gen_label_packet.py <run.json> <traces.sqlite> <out.md>
    python scripts/gen_label_packet.py <run.json> <traces.sqlite> <out.md> --subset judge_lowest --n 8
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

from evaluation.deterministic import read_turn  # noqa: E402
from evaluation.runner import _evidence_of  # noqa: E402
from evaluation.schema import (  # noqa: E402
    REFERENCE_SUBSET_SIZE,
    Dataset,
    RunFile,
    judge_lowest_subset,
    load_dataset,
    reference_subset,
)
from hrmosaic.core.db import SqliteStore  # noqa: E402

SUBSETS = ("seed", "judge_lowest")

#: What the packet tells the labeller about how its items were chosen. Neither line contains a
#: score, a verdict or an ordering — see the module docstring.
SELECTION_NOTE: dict[str, str] = {
    "seed": (
        "These items were sampled with a fixed seed from the questions whose correct behaviour is "
        "to answer, before the run was judged. Nothing about any answer influenced which items are "
        "here."
    ),
    "judge_lowest": (
        "These items were selected from a finished run by a criterion that is recorded in the "
        "project's artifacts and **deliberately withheld from this packet**. It tells you nothing "
        "about which verdict is correct for any item, and it is not a hint: treat every item below "
        "as an independent decision on its own evidence, exactly as you would in a random sample. "
        "They are listed in item-id order."
    ),
}

HEADER = """# Blind groundedness labelling packet

Run `{run_id}` · dataset sha `{dataset_sha}…` · subset `{subset}` · {count} items.

{selection_note}

You are the reference labeller for spec §13.7. For each item below decide **one binary verdict**
about the ANSWER, using ONLY the EVIDENCE shown with it:

* `grounded` — every statement of company policy in the answer is supported by the passages shown;
* `not_grounded` — at least one is not.

The evidence comes in four classes, and they all count. `kind="retrieval"` is a policy passage the
assistant searched up; `kind="section"` is one it fetched in full; `kind="compliance"` is the
deterministic rule engine's own requirement evidence; and `kind="structured_data"` is a record it
read about this employee — a PTO balance, a benefits eligibility date, a profile. **A claim is
supported if ANY item of ANY class supports it**: a correct fact taken from the employee's own
record is grounded, not invented. Judge against this set alone — outside knowledge and plausibility
are irrelevant, and a claim that no item supports is `not_grounded` however true it sounds.

Return YAML in exactly this shape, one entry per item, in this order:

```yaml
labels:
  - item_id: <id>
    verdict: grounded | not_grounded
    rationale: >-
      One or two sentences naming the specific claim that decided it.
```

---
"""


def select(subset: str, run: RunFile, dataset: Dataset, size: int) -> list[str]:
    """The item ids this packet covers, **in item-id order** whichever subset was asked for."""
    if subset == "seed":
        return sorted(reference_subset(dataset, size=size))
    if subset == "judge_lowest":
        return sorted(judge_lowest_subset(run, size=size, dataset=dataset))
    raise SystemExit(f"unknown subset {subset!r}; expected one of {', '.join(SUBSETS)}")


def render(run: RunFile, dataset: Dataset, store: SqliteStore, item_ids: Sequence[str], subset: str) -> str:
    """The packet. Reads the served answers and the evidence; reads no score and no verdict."""
    by_id = {row.item_id: row for row in run.items if row.run_phase == "scored"}
    questions = {item.id: item.question for item in dataset.items}
    lines = [
        HEADER.format(
            run_id=run.run_id,
            dataset_sha=run.dataset_sha[:16],
            subset=subset,
            count=len(item_ids),
            selection_note=SELECTION_NOTE[subset],
        ),
        "",
    ]
    for item_id in item_ids:
        entry = by_id.get(item_id)
        if entry is None:
            lines += [f"## {item_id}", "", "_not present in this run_", "", "---", ""]
            continue
        lines += [
            f"## {item_id}",
            "",
            f"**QUESTION**  {questions.get(item_id, '')}",
            "",
            "**ANSWER**",
            "",
            "```",
            (entry.answer or "").strip() or "(no answer was produced)",
            "```",
            "",
            "**EVIDENCE — everything the assistant was shown, verbatim**",
            "",
        ]
        turn = read_turn(store, entry.turn_id) if entry.turn_id else None
        chunks = _evidence_of(turn) if turn is not None else []
        if not chunks:
            lines += ["_no policy evidence reached the synthesis prompt for this turn_", ""]
        for item in chunks:
            lines += [f'<evidence id="{item.id}" kind="{item.kind}">', item.text.strip(), "</evidence>", ""]
        lines += ["---", ""]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", help="path to evaluation/results/<run_id>.json")
    parser.add_argument("traces", help="path to the trace store the run wrote (data/runtime/traces.sqlite)")
    parser.add_argument("out", help="path to write the packet to")
    parser.add_argument("--subset", default="seed", choices=SUBSETS, help="which §13.7 subset (default: seed)")
    parser.add_argument("--n", type=int, default=REFERENCE_SUBSET_SIZE, help="how many items (default: 8)")
    args = parser.parse_args(argv)

    run = RunFile.model_validate(json.loads(Path(args.run).read_text(encoding="utf-8")))
    dataset = load_dataset()
    store = SqliteStore(Path(args.traces))
    item_ids = select(args.subset, run, dataset, args.n)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(run, dataset, store, item_ids, args.subset), encoding="utf-8")
    print(  # noqa: T201 — this is a CLI
        f"wrote {out} — subset {args.subset}, {len(item_ids)} items: {', '.join(item_ids)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
