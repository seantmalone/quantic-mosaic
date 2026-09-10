"""The three Jinja prompts and the one deterministic renderer over them (spec §7.2).

Each template carries exactly two blocks and the split *is* the frozen prefix ordering:

| block | contents | changes |
|---|---|---|
| `system` | the standing instructions for that purpose | never — byte-stable, no timestamps |
| `user` | the persona block, the untrusted evidence envelopes, the user's question | every turn |

That ordering — `system` → sorted tool schemas → persona → evidence envelopes → question — is what
makes the Anthropic cache breakpoint pay: the breakpoint sits on the last **system** block, so the
cached prefix is *tools → system*, and a timestamp or a persona id in the system half would move it
every turn (§9.8). The tool schemas themselves are never rendered into a prompt; they travel in the
provider's own `tools` array, sorted by name by `agent/client.py`.

`render(...)` returns the two halves as a `(system, user)` pair, and never a single blob, so a
caller cannot accidentally put per-turn bytes in front of the breakpoint.
`tests/contract/test_prompt_golden.py` snapshots both halves of all three templates, so a shape
change is a deliberate re-review rather than a silent drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from hrmosaic.core import corpusread
from hrmosaic.core.models import UNRENDERED_ENVELOPES

#: The three templates of §7.2, and the only ones. A fourth would be a new prompt surface.
TEMPLATES = ("route.j2", "act.j2", "synthesize.j2")

PROMPT_DIR = Path(__file__).resolve().parent

#: `StrictUndefined` so a renamed context key fails the golden test rather than rendering a hole;
#: `keep_trailing_newline=False` and manual whitespace control keep the bytes stable.
_environment = Environment(
    loader=FileSystemLoader(PROMPT_DIR),
    undefined=StrictUndefined,
    autoescape=False,  # noqa: S701 - these are prompts, not HTML; escaping would corrupt the text
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=False,
)


def corpus_titles() -> tuple[str, ...]:
    """The exact titles of the indexed policy documents, by `doc_id` (§8.4 tool 3's own order).

    `route.j2`'s CORPUS paragraph is rendered from this and never from a hand-typed list: it reads
    the `documents` table `list_policy_documents` returns, which the committed manifest is built
    from, so a corpus edit moves the router prompt with it and the two cannot drift.
    `tests/contract/test_prompt_golden.py` asserts the rendered list equals the manifest's titles.
    """
    return tuple(document.doc_title for document in corpusread.list_documents())


#: A Jinja global rather than a context key: the corpus is a property of the deployment, not of the
#: turn, and `render()`'s callers pass only per-turn values. `system` stays byte-stable across
#: turns because the index behind it does not move while the process runs.
_environment.globals["corpus_titles"] = corpus_titles

#: Which tool envelopes EMPLOYEE CONTEXT leaves out, as a Jinja global for the same reason: it is a
#: property of the tool catalog, not of the turn. It comes from `core/models.py` beside the §13.3
#: evidence map `evaluation/runner.py::_evidence_of` scores, so the set the prompt shows and the set
#: the judge scores are read from one module and cannot drift
#: (`tests/contract/test_envelope_partition.py`).
_environment.globals["unrendered_envelopes"] = UNRENDERED_ENVELOPES


def render(template_name: str, /, **context: Any) -> tuple[str, str]:
    """Render one template's `system` and `user` blocks. Returns `(system, user)`."""
    if template_name not in TEMPLATES:
        raise KeyError(f"{template_name!r} is not one of the three prompts: {TEMPLATES}")
    template = _environment.get_template(template_name)
    rendered = template.new_context(dict(context))
    return (
        "".join(template.blocks["system"](rendered)).strip(),
        "".join(template.blocks["user"](rendered)).strip(),
    )


def persona_block(*, employee_id: str, actor_source: str) -> str:
    """The one persona line every prompt carries, in the frozen position between system and evidence.

    Identity is audit-only (§7.4, §8.7): the block tells the model *who is asking* so the answer is
    addressed to them, and gates nothing. It is deliberately id-only — no name, no office, no
    tenure — because everything else about an employee is a tool result, not a prompt constant.
    """
    return (
        f"ACTING PERSONA: {employee_id} ({actor_source}). "
        "Employee data is a synthetic snapshot; state the as_of date a tool reports whenever you "
        "quote a balance, an accrual or an eligibility date."
    )


__all__ = [
    "PROMPT_DIR",
    "TEMPLATES",
    "UNRENDERED_ENVELOPES",
    "corpus_titles",
    "persona_block",
    "render",
]
