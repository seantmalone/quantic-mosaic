"""The synthesis stream's two safety rules and its one performance rule (W2-E).

* **Complete blocks only.** A block reaches the page when its closing brace does, never before —
  `render_answer()` labels a recommendation, so a partly written one would read as company policy
  until its prefix arrived.
* **`text` and `citations` only.** `rationale_summary` is §9.7's hidden reasoning and `next_steps`
  is joined from the finished answer; the scanner reads the `blocks` array and stops at its `]`.
* **Coalescing.** `web/sse.py` drops a frame *silently* when a subscriber's queue is full
  (`QUEUE_MAX = 512`), and an uncoalesced token stream was measured overrunning it 2,000 → 512.
  A batch of ~40 characters or ~100 ms is what keeps the scan count — and the frame count — small.
"""

from __future__ import annotations

import json

from hrmosaic.agent.answer_stream import COALESCE_CHARS, AnswerAssembler
from hrmosaic.web.sse import QUEUE_MAX

BODY = {
    "blocks": [
        {
            "type": "policy_fact",
            "text": "Full-time employees accrue PTO monthly on a service-based scale.",
            "citations": ["c_e178629918c7cd96"],
        },
        {
            "type": "recommendation",
            "text": "With 13.5 days left you can cover a three-day request.",
            "citations": [],
        },
        {
            "type": "escalation",
            "text": "I cannot open the request in MosaicOne for you.",
            "citations": [],
        },
    ],
    "next_steps": ["Submit the request in MosaicOne."],
    "rationale_summary": "The accrual table and the balance tool agree; nothing else was needed.",
}
RAW = json.dumps(BODY, ensure_ascii=False)


class _Clock:
    """A monotonic clock the test moves by hand, so coalescing is deterministic."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _feed(assembler: AnswerAssembler, raw: str, *, chunk: int) -> list:
    delivered = []
    for offset in range(0, len(raw), chunk):
        delivered.extend(assembler.feed(raw[offset : offset + chunk]))
    delivered.extend(assembler.flush())
    return delivered


def test_a_block_is_delivered_only_once_it_is_complete():
    clock = _Clock()
    assembler = AnswerAssembler(clock=clock)
    head = RAW.index('"citations"')

    # Everything up to (but not including) the first block's closing brace.
    assert assembler.feed(RAW[:head]) == []
    assert assembler.feed(RAW[head : RAW.index("}", head)]) == []

    rest = assembler.feed(RAW[RAW.index("}", head) :])
    assert [block.type for block in rest] == ["policy_fact", "recommendation", "escalation"]


def test_every_block_arrives_with_only_its_three_streamable_fields():
    delivered = _feed(AnswerAssembler(clock=_Clock()), RAW, chunk=7)

    assert [block.index for block in delivered] == [0, 1, 2]
    assert [block.type for block in delivered] == ["policy_fact", "recommendation", "escalation"]
    assert delivered[0].text == BODY["blocks"][0]["text"]
    assert delivered[0].citations == ["c_e178629918c7cd96"]
    assert set(vars(delivered[0])) == {"index", "type", "text", "citations"}


def test_the_rationale_summary_and_next_steps_never_leave_the_process():
    """§9.7: the model's reasoning is clamped post hoc and is not something to stream."""
    delivered = _feed(AnswerAssembler(clock=_Clock()), RAW, chunk=3)

    streamed = " ".join(block.text for block in delivered)
    assert BODY["rationale_summary"] not in streamed
    assert BODY["next_steps"][0] not in streamed


def test_a_brace_inside_a_block_string_does_not_close_it():
    raw = json.dumps(
        {"blocks": [{"type": "policy_fact", "text": 'Use the {"form": 1} template.', "citations": ["c_1"]}]}
    )
    delivered = _feed(AnswerAssembler(clock=_Clock()), raw, chunk=5)

    assert [block.text for block in delivered] == ['Use the {"form": 1} template.']


def test_sse_delta_coalescing_under_queue_max():
    """A 2,000-delta synthesis delivers every block, and offers far fewer frames than the queue holds."""
    clock = _Clock()
    assembler = AnswerAssembler(clock=clock)
    body = json.dumps(
        {
            "blocks": [
                {"type": "policy_fact", "text": f"Sentence number {index} of the answer.", "citations": ["c_1"]}
                for index in range(40)
            ],
            "next_steps": [],
            "rationale_summary": "x",
        },
        ensure_ascii=False,
    )
    # 2,000 deltas, exactly as the plan measured, with the clock frozen so only the character
    # threshold can trip: the coalescing under test is the one that survives a fast provider.
    chunk = max(1, len(body) // 2_000 + 1)
    deltas = [body[offset : offset + chunk] for offset in range(0, len(body), chunk)]
    assert len(deltas) >= 1_000, "the fixture has to be a real token stream, not four big pieces"

    delivered = []
    for delta in deltas:
        delivered.extend(assembler.feed(delta))
    delivered.extend(assembler.flush())

    assert [block.index for block in delivered] == list(range(40)), "every block, none dropped"
    # One frame per block, so the whole synthesis costs 40 of the 512 slots — where an uncoalesced
    # token stream offered 2,000 and `_offer` discarded 1,488 of them without a word.
    assert len(delivered) < QUEUE_MAX
    # And the buffer was scanned once per batch rather than once per delta.
    assert assembler.scans <= len(body) // COALESCE_CHARS + 2 < len(deltas)


def test_the_time_threshold_flushes_a_trickle():
    """A slow provider that sends three characters a second still shows its blocks."""
    clock = _Clock()
    assembler = AnswerAssembler(clock=clock)
    head, tail = RAW[: RAW.index("}") + 1], RAW[RAW.index("}") + 1 :]

    delivered = []
    for character in head:
        # Past the 100 ms window on every character and never near the 40-character one: what a
        # provider trickling a token at a time looks like.
        clock.now += 0.15
        delivered.extend(assembler.feed(character))
    assert [block.index for block in delivered] == [0], "the first block arrived on the clock alone"

    delivered.extend(assembler.feed(tail))
    delivered.extend(assembler.flush())
    assert [block.index for block in delivered] == [0, 1, 2]


def test_a_malformed_stream_costs_a_preview_and_nothing_else():
    """`turn_completed` carries the real answer a moment later, so the scan just stops."""
    delivered = _feed(AnswerAssembler(clock=_Clock()), '{"blocks": [{"type": "policy_fact", ,,, }]}', chunk=9)

    assert delivered == []
