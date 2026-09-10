"""The evaluation harness (spec §13).

Five modules, and the dependency order between them is strictly one way:

```
schema.py         the dataset and artifact types — no I/O beyond reading dataset.yaml
deterministic.py  every scorer that needs no model: citations, docs, tools, workflow, safety
judges.py         the four judge prompts of §13.7 on gemini-3.5-flash-lite
runner.py         the harness: POST /chat per item, score, judge, write results + REPORT.md
ablation.py       compares runs that already exist under evaluation/results/ — it runs nothing
```

`evaluation/ → core/` and the HTTP API, never the other way round (§4.2): the harness drives the
application through `POST {EVAL_TARGET_BASE_URL}/chat` exactly as any client would, and reads what
happened from the trace store through `core/db.py`. It imports no `hrmosaic.agent`,
`hrmosaic.mcpserver` or `hrmosaic.web` module, so nothing it measures can be measured by reaching
inside the thing under test — `tests/architecture/test_conventions.py` greps for all three. The one
piece of application logic the harness genuinely has to share, the canonical argument serialisation
clause 2 of §13.4 compares, lives in `core/canonical.py` for exactly that reason.
"""

from __future__ import annotations

__all__ = ["ablation", "deterministic", "judges", "runner", "schema"]
