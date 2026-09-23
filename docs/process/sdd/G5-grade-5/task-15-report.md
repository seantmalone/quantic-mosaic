# Task 15 — the labelling packet never names its own selection criterion (round 3, part 1)

**Status:** complete. One commit on `main`. Three files touched: `scripts/gen_label_packet.py`,
`tests/unit/test_gen_label_packet_store.py`, `tests/contract/test_docs_completeness.py`. **No
committed packet was regenerated or edited** (`git diff docs/evidence/` is empty) — the run is about
to be re-driven, and the two packets are the files the labelling sessions actually read.

## 1. The builder

`docs/evidence/label-packet-hard-2026-09-22.md:3` printed ``subset `judge_lowest` `` because `HEADER`
interpolated the `--subset` CLI value. Five lines below it the same packet promised the labeller that
the criterion is *"deliberately withheld from this packet"*. Three changes:

* **`SUBSET_TOKEN = {"seed": "A", "judge_lowest": "B"}`.** The header renders ``subset `A` `` /
  ``subset `B` ``; the mapping stays in the repository with the rest of the disclosure. The run id
  and the item count are unchanged, so a packet is still attributable to exactly one run
  (`Run `r_…` · dataset sha `…` · subset `B` · 8 items.`). `--subset` is untouched as a CLI flag.
* **`CRITERION_WORDS = ("judge", "lowest", "hardest", "worst")` and a build-time guard.** The new
  `header_for()` formats the header and raises `SystemExit` rather than writing a packet whose own
  instructions carry any of those words. Two existing strings tripped it and were reworded:
  `SELECTION_NOTE["seed"]`'s *"before the run was judged"* → *"before the run was scored"* (same
  claim: the seed sample was drawn before any verdict existed), and the instruction line *"Judge
  against this set alone"* → *"Decide against this set alone"*. Everything else the labeller is told
  is unchanged, including the `judge_lowest` note's "a criterion … deliberately withheld" wording and
  "They are listed in item-id order".
* The module docstring now states the token rule and names the pre-fix packet as the artifact that
  predates it.

Unchanged and re-asserted: `select()` sorts both subsets into item-id order, and the builder still
reads neither `scores` nor `verdicts`, so no score, verdict or rationale can reach a packet.

## 2. The tests

Both are **extensions of existing test functions**. The collected suite size is a published figure in
`README.md`, `ai-tooling.md`, `design-and-evaluation.md` and `docs/requirements-traceability.md`, held
to a real `pytest --collect-only` by this very contract file, and another agent owns those figures
this round — so no new test was collected anywhere (unit file still 3 tests, contract file still 49).

* `tests/unit/test_gen_label_packet_store.py::test_auto_resolves_through_get_store` — for both
  subsets: `criterion_words_in(header_for(...)) == []`, the token is present, `judge_lowest` is absent
  verbatim, the run id and `8 items` survive. Then the guard itself (a `SUBSET_TOKEN` patched to leak
  raises `SystemExit`), and `select("judge_lowest", …)` sorting an unsorted worst-first
  `judge_lowest_subset()` into item-id order. (`seed` is deliberately *not* asserted absent: that
  subset's selection is blind and the note discloses it — "a fixed seed" contains the word.)
* `tests/contract/test_docs_completeness.py::test_judge_methodology_names_the_labeller_and_the_blinding`
  — over every committed `docs/evidence/label-packet-*.md`: no line carries a `CRITERION_WORDS` entry
  (the tuple is read from the builder, not restated), and no line matches
  `groundedness\D{0,32}\d` (a leaked score; the word alone is in every packet's title).

  **The one allowance, and why it is not a hole.** The two 2026-09-22 packets predate the fix and
  cannot be rewritten — their labels are published. So `RUN_BEFORE_THE_NEUTRAL_HEADER =
  "r_1790110325_baseline"` plus a frozen `PACKET_CRITERION_BASELINE` of exactly four `<file>:<line>`
  positions (hard:3, hard:18, seed:5, seed:18) is tolerated **only** for a packet whose own header
  names that run. Verified by mutation: appending `the judge scored this lowest` to the hard packet
  fails (a fifth position); appending `groundedness 0.55` fails; and changing only the run id in the
  header makes the expectation `[]` and fails. Regenerating either packet — even under the same name,
  on the same day — retires the allowance, because the new run id will not match.

`make lint` clean (`ruff check` + `ruff format --check`, 321 files). `pytest tests/unit/test_gen_label_packet_store.py -q` →
**3 passed**; `pytest tests/contract/test_docs_completeness.py -q` → **49 passed** (run one at a time).

## 3. What must be reworded for the CURRENT run

The current labels were authored from a packet that named the subset in its header. The honest
statement is that **the criterion's name was visible in the header, while the rows were still
rendered in item-id order and carried no score, verdict or rationale** — so the ordering claim stands
and the criterion claim does not. Four places (none of them mine; all owned elsewhere):

1. **`evaluation/reference_labels_hard.yaml:40–42`, `protocol.blinding`** — the source of
   `evaluation/REPORT.md:146`, which renders it verbatim (and is held to it by
   `test_the_reports_protocol_paragraphs_are_the_label_files_own_words`, so the yaml is edited and
   the report regenerated with `python -m evaluation.runner --report r_1790110325_baseline`; editing
   REPORT.md alone fails the suite). Reword:

   > It also disclosed neither the selection criterion nor the score ordering: the items are rendered
   > in item-id order, so the labeller could not tell a low-scoring item from a high-scoring one.

   to something that keeps the ordering claim and retracts the criterion claim, e.g. *"Its header
   named the subset — `subset judge_lowest` — so the selection criterion was legible to this
   labeller; the score ordering was not disclosed, because the items are rendered in item-id order
   and no item carries a score, a verdict or a rationale. The packet builder no longer prints a
   subset name; this packet predates that fix."*

2. **`design-and-evaluation.md:1494–1497`**:

   > Neither packet carried judge output regardless of when it was built, because its builder never
   > reads `scores` or `verdicts`; the hard packet additionally withholds both the selection
   > criterion and the score ordering, rendering the items in item-id order, so the labeller could
   > not tell a low-scoring item from a high-scoring one.

   The clause from *"the hard packet additionally withholds both the selection criterion and"*
   onwards is the false half: it withheld the **ordering**, not the criterion.

3. **`design-and-evaluation.md:1508–1509`**, inside *"both packets are committed, so the blinding is
   inspectable rather than asserted"* (1501 — that sentence itself is true and is now the mechanism
   that caught this):

   > There is no verdict, no per-claim verdict, no rationale and no groundedness score anywhere in
   > either file; the hard packet's header says a criterion chose its eight items and withholds it,
   > and renders them in item-id order rather than score order.

   The first clause holds and is now machine-checked. *"and withholds it"* must go — the header
   prints `judge_lowest`.

4. **`docs/evidence/README.md:63`** (the hard packet's table row): *"Its header says a criterion chose
   the items and **withholds it**, and the items are rendered in item-id order rather than score
   order, so nothing in the packet separates a low-scoring item from a high-scoring one"* — same
   correction; the item-id-order half stands. And **`docs/evidence/README.md:73`**, which lists what
   the packets evidence as withheld: *"no verdict, no per-claim verdict, no rationale, no
   groundedness score, **no selection criterion in the hard packet**, and no ordering hint"* — the
   bolded clause must come out.

`evaluation/reference_labels.yaml`'s seed `protocol.blinding` needs nothing: it claims no criterion
withholding, and `subset seed` is not a criterion.

After the re-drive, the controller regenerates both packets with the fixed builder, re-labels, and
then all four passages can state the blinding without an exception — at which point
`PACKET_CRITERION_BASELINE` and `RUN_BEFORE_THE_NEUTRAL_HEADER` should be deleted.
