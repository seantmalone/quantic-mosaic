# Task 9 — the eval runs table fits its box at 1280px again

**CI:** run 35733477527, job `ux`, tip `de13ac4` — 1 failed, 298 passed.
`tests/ux/test_dashboard_principles.py::test_no_table_overflows_without_the_affordance_and_no_narrow_column_holds_prose[1280x800]`,
`{'/dashboard/evals': {'overWide': [{'table': 'eval-runs-table', 'over': 1, 'box': 1199}]}}` — and
the same one table on both `?tab=` panels, which are the same page.

## Root cause

Not the build column and not the runs' `notes`. `eval-runs-table` renders neither `notes` nor the
file's `label` (the RUN cell is the view-model's `variant · target`), and the six run files this
wave committed print nothing longer than the runs before them — the longest string in every one of
the nine columns is identical before and after (measured by dumping each cell's `innerText` with the
new files in place and with them moved aside).

What changed is **how wide the same-length string paints**. `CREATED` is `.cell-time`, which is
`white-space: nowrap` and is *not* in the `font-variant-numeric: tabular-nums` group, so the column
is as wide as its own digits. Measured min-content of the table at 1280 (box 1,199px):

| data | CREATED | table min-content |
|---|---|---|
| through `82994ce` (16 runs) | 185.45px | **1,195.81px** |
| with `r_17900676…`/`r_17900749…` and their arms (22 runs) | 189.13px | **1,199.48px** |

The other eight columns did not move. So the table had been fitting its 1,199px container by 0.52px
— on CI's font stack that half-pixel is spent and `scrollWidth - clientWidth` is 1. The runs table
has no slack at 1280 at all: every column sits at min-content and the nine of them sum to the box.

## Fix

Two lines, no information removed, no threshold touched.

* `src/hrmosaic/web/static/app.css` — a new opt-in override beside the nowrap block:
  `.data-table td.cell-time.cell-time-stacked { white-space: normal; }`, with the reasoning above in
  the comment. A timestamp is a date *and* a clock, not one token; `nowrap` over both is what made
  the column's width a function of the data's digits.
* `src/hrmosaic/web/templates/dashboard/evals.html` — the runs table's Created column takes
  `'cls': 'cell-time-stacked'` (the `_table.html` macro's own documented per-column option, used
  here for the first time). Only this table opts in: every other timestamp column, the headline
  table's included, keeps its one-line instant.

Result at 1280: table min-content 1,199.48 → **1,089.38px**, i.e. 110px of slack that no future run
can spend, against the 3.68px of drift that caused this. Nothing is abbreviated — the cell still
paints `2026-09-21 21:30:12 UTC`, over two lines where the table is tight. At 1440 the column has
room and still takes one line; at 390 the card layout is unchanged. The page grows 3,081 → 3,375px
at 1280, because the rows whose JUDGE cell was a single em dash now match the ones that already
stood two lines tall.

Considered and rejected: `tabular-nums` on `.cell-time` (makes the column *wider* — 189 → 206px, 18px
over); a `max-width` + ellipsis on the id chips (the ruling at `dashboard.py:520` keeps the **tail**
of a structured id, which is exactly what an ellipsis eats); adding the table to
`WIDTH_EXEMPT_TABLES` (that is editing the test).

## Tests

No test added, so no suite figure moves (still 3,415).

```
MOCK_TODAY=2026-09-01 .venv/bin/pytest -q -p no:cacheprovider -m ux \
  "tests/ux/test_dashboard_principles.py::test_no_table_overflows_without_the_affordance_and_no_narrow_column_holds_prose"
                                                    2 passed in 101.02s   (1440x900, 1280x800)
MOCK_TODAY=2026-09-01 .venv/bin/pytest -q -p no:cacheprovider -m ux tests/ux/test_dashboard_principles.py
                                                   43 passed in 216.89s
make lint                                          ruff check: all checks passed; 321 files already formatted
.venv/bin/pytest -q -p no:cacheprovider tests/contract/test_dashboard_pages.py \
  tests/contract/test_dashboard_viewmodels.py tests/contract/test_css_has_no_orphan_classes.py
                                                   58 passed in 50.95s
```

Note for a later wave, not fixed here: `eval-headline-table` renders the same timestamps with the
same nowrap and sits at 1,174px inside the same 1,199px box — 25px of slack, seven times the drift
seen here, but it is the next table to run out.
