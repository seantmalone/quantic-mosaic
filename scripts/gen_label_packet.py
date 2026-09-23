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
to detect. So the packet states that a selection criterion exists and is withheld, refers to its
subset by an opaque token rather than by name (the *names* are the criterion: `judge_lowest` tells a
reader exactly what chose these eight items), and renders the items **in item-id order**, never in
score order, so the ranking cannot leak through the sequence either. The header is checked against
`CRITERION_WORDS` before the file is written; `docs/evidence/label-packet-hard-2026-09-22.md` is the
packet that predates all three of those measures, and it printed ``subset `judge_lowest` `` on line 3.

The `traces` argument is the literal `auto` when the run was driven against the **deployed**
service: its turns are then in the service's own store (Turso), not in a local sqlite file, and
`auto` resolves through `hrmosaic.core.db.get_store()`, which builds whichever store the
environment configures. Any other value is a path and stays a local `SqliteStore`, unchanged.

    python scripts/gen_label_packet.py <run.json> <traces.sqlite> <out.md>
    python scripts/gen_label_packet.py <run.json> <traces.sqlite> <out.md> --subset judge_lowest --n 8
    python -m scripts.gen_label_packet <run.json> auto <out.md>   # deployed run: the service's store
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
from hrmosaic.core.db import SqliteStore, Store, get_store  # noqa: E402

SUBSETS = ("seed", "judge_lowest")

#: The `traces` value that means "whichever store this environment configures" — see the docstring.
AUTO_STORE = "auto"

#: How the packet refers to its own subset. The subset *names* are the criterion — `judge_lowest`
#: says "the eight the judge liked least" to anyone who reads it — so the packet prints an opaque
#: token instead and the mapping stays here, in the repository, with the rest of the disclosure.
#: This is the leak that made the guard below necessary: the header used to interpolate the `--subset`
#: CLI value, so the one packet whose criterion had to be withheld announced it on line 3.
SUBSET_TOKEN: dict[str, str] = {"seed": "A", "judge_lowest": "B"}

#: Words that would tell the labeller *why* these eight items are in front of them. `judge` and
#: `lowest` name the hard subset's selector; `hardest` and `worst` are the same hint in prose. The
#: packet's own instructions are checked against this tuple before the file is written.
CRITERION_WORDS = ("judge", "lowest", "hardest", "worst")

#: What the packet tells the labeller about how its items were chosen. Neither line contains a
#: score, a verdict, an ordering or a `CRITERION_WORDS` entry — see the module docstring.
SELECTION_NOTE: dict[str, str] = {
    "seed": (
        "These items were sampled with a fixed seed from the questions whose correct behaviour is "
        "to answer, before the run was scored. Nothing about any answer influenced which items are "
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

Run `{run_id}` · dataset sha `{dataset_sha}…` · subset `{subset_token}` · {count} items.

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
record is grounded, not invented. Decide against this set alone — outside knowledge and plausibility
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


def criterion_words_in(text: str) -> list[str]:
    """Which `CRITERION_WORDS` `text` carries. Empty is the only acceptable answer for a packet's
    instructions; an item's own question, answer or evidence is not checked, because a policy
    passage is allowed to contain an English word."""
    lowered = text.lower()
    return [word for word in CRITERION_WORDS if word in lowered]


def header_for(run: RunFile, subset: str, count: int) -> str:
    """The packet's instructions, with the subset named by token only — see `SUBSET_TOKEN`.

    Refuses rather than writes a packet whose own instructions carry a criterion-bearing word: the
    labeller's blindness is a published claim about this file, so the failure mode worth having is a
    build that stops, not a packet that quietly names the criterion it says it withholds.
    """
    header = HEADER.format(
        run_id=run.run_id,
        dataset_sha=run.dataset_sha[:16],
        subset_token=SUBSET_TOKEN[subset],
        count=count,
        selection_note=SELECTION_NOTE[subset],
    )
    leaked = criterion_words_in(header)
    if leaked:
        raise SystemExit(f"refusing to write a packet whose header names its selection criterion: {leaked}")
    return header


def select(subset: str, run: RunFile, dataset: Dataset, size: int) -> list[str]:
    """The item ids this packet covers, **in item-id order** whichever subset was asked for."""
    if subset == "seed":
        return sorted(reference_subset(dataset, size=size))
    if subset == "judge_lowest":
        return sorted(judge_lowest_subset(run, size=size, dataset=dataset))
    raise SystemExit(f"unknown subset {subset!r}; expected one of {', '.join(SUBSETS)}")


def open_store(traces: str) -> Store:
    """The trace store the run wrote: `auto` is the configured store, anything else is a path."""
    if traces == AUTO_STORE:
        return get_store()
    return SqliteStore(Path(traces))


def render(run: RunFile, dataset: Dataset, store: Store, item_ids: Sequence[str], subset: str) -> str:
    """The packet. Reads the served answers and the evidence; reads no score and no verdict."""
    by_id = {row.item_id: row for row in run.items if row.run_phase == "scored"}
    questions = {item.id: item.question for item in dataset.items}
    lines = [header_for(run, subset, len(item_ids)), ""]
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
    parser.add_argument(
        "traces",
        help=(
            "path to the trace store the run wrote (data/runtime/traces.sqlite), or the literal "
            f"{AUTO_STORE!r} to use the store this environment configures (a deployed run's turns "
            "are in the service's store, not in a local file)"
        ),
    )
    parser.add_argument("out", help="path to write the packet to")
    parser.add_argument("--subset", default="seed", choices=SUBSETS, help="which §13.7 subset (default: seed)")
    parser.add_argument("--n", type=int, default=REFERENCE_SUBSET_SIZE, help="how many items (default: 8)")
    args = parser.parse_args(argv)

    run = RunFile.model_validate(json.loads(Path(args.run).read_text(encoding="utf-8")))
    dataset = load_dataset()
    store = open_store(args.traces)
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
