"""W2-D — one definition of which tool envelope is evidence, read by the prompt and by the judge.

§13.3 says `evaluation/runner.py::_evidence_of` is *the* definition of what the model was shown, and
`scripts/gen_label_packet.py` builds the §13.7 blind-labelling packet from the same function so the
packet and the judge cannot drift. The synthesis prompt now decides what to render from a set
declared in the same module as that map (`core/models.py`), which makes a second copy of the
membership a correctness bug rather than a duplication: if the render and the scorer disagreed,
`groundedness` would stop describing what the model saw, and it would do so silently.

The envelopes the render drops are `search_policy_documents` and `list_policy_documents`, and
**only** those two. Two mistakes are guarded here, both of them near misses:

* the proposal's own filter ("employee-data and write tools only") would have deleted the
  `check_policy_compliance` envelope, whose `verdict`, `requirements[].met`, `unmet`,
  `approvals_required`, `escalate_to`, `as_of` and `rules_version` exist nowhere else in the prompt
  — `_absorb` populates `turn.evidence` only from `result.retrievals`, and only
  `search_policy_documents` returns a `RetrievalPayload` — and the `get_policy_section` envelopes
  whose chunk ids were absent from EVIDENCE on 3 of 14 deployed calls;
* rendering *only* what `ENVELOPE_KINDS` scores would have deleted the two **write** tools, which
  are correctly outside the evidence map — a proposal asserts no fact — but whose result on the
  resumed half of a confirmed write is where the answer gets the ticket id it reports.
"""

from __future__ import annotations

import re

from evaluation.runner import ENVELOPE_KINDS as scored
from hrmosaic.agent import prompts
from hrmosaic.agent.orchestrator import WRITE_TOOLS, _ToolEnvelope
from hrmosaic.core.models import ENVELOPE_KINDS as shared
from hrmosaic.core.models import UNRENDERED_ENVELOPES
from hrmosaic.mcpserver.tools import TOOL_NAMES

RENDERED = re.compile(r'<tool_result tool="([^"]+)"')


def rendered_envelopes(names) -> set[str]:
    """The tool names the synthesis prompt actually renders, given an envelope for each of `names`."""
    _, user = prompts.render(
        "synthesize.j2",
        persona=prompts.persona_block(employee_id="E1042", actor_source="explicit"),
        question="Can I work from Berlin for six weeks?",
        chunks=[],
        tool_results=[_ToolEnvelope(name=name, result_json="{}") for name in names],
    )
    return set(RENDERED.findall(user))


def test_envelope_partition_is_one_definition():
    """The set rendered into EMPLOYEE CONTEXT and the set the judge scores come from one module."""
    assert scored is shared, "the judge's map and the prompt's map must be the same object"
    rendered = rendered_envelopes(TOOL_NAMES)

    assert set(shared) <= rendered, "every envelope scored as evidence is an envelope the model saw"
    assert rendered - set(shared) == set(WRITE_TOOLS), (
        "the only rendered envelope that is not evidence is a confirmed write's own result"
    )
    assert set(TOOL_NAMES) - rendered == set(UNRENDERED_ENVELOPES)


def test_the_render_drops_exactly_the_two_tools_that_ground_nothing():
    """`search_policy_documents` and `list_policy_documents`, and nothing else — not by inference."""
    assert set(UNRENDERED_ENVELOPES) == {"search_policy_documents", "list_policy_documents"}
    assert set(shared).isdisjoint(UNRENDERED_ENVELOPES)
    assert {"get_policy_section", "check_policy_compliance"} <= set(shared), (
        "these two carry facts that exist nowhere else in the prompt"
    )
    assert set(WRITE_TOOLS).isdisjoint(UNRENDERED_ENVELOPES), (
        "a confirmed write asserts no fact, but its result is where the answer gets the ticket id"
    )


def test_an_unknown_tool_is_still_rendered_but_is_not_evidence():
    """The render is a denylist and the evidence map is an allowlist; they answer different questions."""
    assert rendered_envelopes(["some_future_tool", "check_pto_balance"]) == {
        "some_future_tool",
        "check_pto_balance",
    }
    assert "some_future_tool" not in shared
