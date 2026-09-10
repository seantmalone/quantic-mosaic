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


__all__ = ["PROMPT_DIR", "TEMPLATES", "persona_block", "render"]
