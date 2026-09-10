"""W2-A — the act loop's closing step is one short sentence, not an answer nobody reads.

21 of 53 deployed act calls closed the loop with zero tool calls and a median 224 output tokens of
prose — 48 % of all act output tokens — that no answer path consumes: `_synthesize` re-renders from
`turn.chunks()` / `turn.envelopes`, `_clarification_text` uses the router's rationale, `_park` uses
the proposal and `_degraded` a constant. Act output costs ~10.2 ms/token, so that prose is the
single largest avoidable block of latency in the median turn.

**The measurement is split by terminality, and that split is the whole test.** Only some zero-tool-
call act calls are terminal. The rest are *consumed*: a §9.1 reminder fires, the loop `continue`s,
and the closing text becomes the assistant turn that reminder answers — the G1 recovery path
appends `G1_RECOVERY` to the same conversation, and `_rehydrate_messages` replays it on resume.
Measuring the pooled median would report success by shortening messages the loop still reads, which
is why `CLOSING_TOKEN_BUDGET` is asserted against the terminal set alone and the consumed set is
asserted to be genuinely different.

The source is the committed recordings under `tests/fixtures/llm_scripts/` — `StubAdapter` replays
`completion_tokens` verbatim onto the `llm_call` span, so a scripted entry *is* the span the budget
is measured on, and the last test drives a real turn to hold those two together.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest

from hrmosaic.agent.orchestrator import ChatRequest
from hrmosaic.core.llm.stub import load_script

pytestmark = pytest.mark.anyio

SCRIPTS = Path(__file__).resolve().parents[1] / "fixtures" / "llm_scripts"

#: The plan's budget for the closing step. **40, not 15**: 15 is below what "one short sentence
#: naming what was gathered" produces, and a budget the rule cannot meet is a budget that gets
#: met by deleting the naming clause the nudged step depends on.
CLOSING_TOKEN_BUDGET = 40

QUESTION = "How much PTO do full-time employees accrue each month?"


def closing_steps() -> tuple[list[int], list[int]]:
    """`(terminal, consumed)` completion-token counts over every recorded zero-tool-call act step.

    A zero-tool-call act entry is **consumed** when the loop takes another act step after it — that
    is exactly the shape a reminder produces — and **terminal** otherwise.
    """
    terminal: list[int] = []
    consumed: list[int] = []
    for path in sorted(SCRIPTS.glob("*.json")):
        entries = load_script(path)
        for index, entry in enumerate(entries):
            if entry.get("purpose") != "act" or entry.get("tool_calls"):
                continue
            following = entries[index + 1].get("purpose") if index + 1 < len(entries) else None
            bucket = consumed if following == "act" else terminal
            bucket.append(int(entry.get("completion_tokens") or 0))
    return terminal, consumed


def test_act_closing_step_is_short():
    """The lever's gate: the median terminal closing step fits in one sentence's worth of tokens."""
    terminal, _ = closing_steps()

    assert terminal, "no recorded act step closes the loop — the fixtures cannot measure this"
    assert statistics.median(terminal) <= CLOSING_TOKEN_BUDGET, terminal


def test_the_consumed_closing_steps_are_measured_separately():
    """The split is load-bearing: pooled, the budget would be met by shortening read messages."""
    terminal, consumed = closing_steps()

    assert consumed, "the fixtures must carry a nudged turn, or the split proves nothing"
    assert max(consumed) > CLOSING_TOKEN_BUDGET, (
        "every recorded consumed step is already inside the budget, so this test no longer "
        "distinguishes the two populations"
    )
    assert max(consumed) > max(terminal)


async def test_the_recorded_count_is_the_count_on_the_span(run_agent, spans):
    """`StubAdapter` replays the recording onto a real `llm_call` span, so the two cannot drift."""
    answered = await run_agent("rag_only.json", ChatRequest(message=QUESTION, employee_id="E1042"))

    records = spans(answered.turn_id)
    acts = [payload for kind, _, payload in records if kind == "llm_call" and payload["purpose"] == "act"]
    assert acts, "the act loop ran"
    closing = acts[-1]

    assert not closing["tool_calls"], "the last act step closed the loop"
    assert closing["completion_tokens"] <= CLOSING_TOKEN_BUDGET
