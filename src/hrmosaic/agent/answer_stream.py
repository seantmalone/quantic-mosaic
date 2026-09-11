"""Turning the synthesis call's token stream into `answer_delta` frames (performance plan §3 W2-E).

The synthesis call answers with one constrained-JSON body (`AnswerSchema`). Three rules decide what
of it may be shown before the turn is over, and all three are safety rules rather than taste:

1. **Complete blocks only.** `orchestrator.render_answer()` labels a `recommendation` with
   `"Recommendation — not company policy: "` and an `escalation` with `"Escalation: "`. A block
   rendered as it is typed would read as company policy until its prefix arrived, which is exactly
   what §7.3's typed blocks exist to prevent. The measured cost of the rule is that the head start
   falls from 6,624 ms to 5,352 ms at p50 — 19.2 % of the synthesis output goes into closing the
   first block — and 81 % of it is kept.
2. **`blocks[].text` and `blocks[].citations`, nothing else.** `rationale_summary` is §9.7's hidden
   reasoning, clamped to 200 characters only *after* the fact; `next_steps` is joined by
   `render_answer` from the final answer. Neither is streamed. The scanner below reads the `blocks`
   array and never looks at another key.
3. **Redacted before it leaves the process (§7.4 G6, §17).** Every block's `text` goes through
   `redact_text()` in `_drain`. A delta is neither a persisted span payload (`core/trace.py`'s
   `prepare_payload`) nor the finished answer (`g6.check` over `render_answer`'s output), so
   without this the one model-written thing on this path would be the one thing G6 never saw.
   `redact()` is idempotent, so the finished answer and the persisted spans are unaffected.

**Coalescing.** The buffer is only re-scanned once ~40 characters or ~100 ms have accumulated. A
2,000-delta synthesis therefore costs ~50 scans rather than 2,000, and — because a frame is emitted
per completed *block* rather than per delta — a whole turn puts a handful of frames into
`web/sse.py`'s bounded queue. That matters: `_offer` drops a frame silently when the queue is full,
and uncoalesced token frames were measured overrunning `QUEUE_MAX = 512` (2,000 offered, 512
delivered, 1,488 dropped).

The scan itself is incremental and resumable: `_BlockScanner` keeps its cursor, its brace depth and
its in-string state across calls, so feeding n characters costs O(n) in total however they arrive.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from hrmosaic.core.redact import redact_text

#: The two coalescing thresholds. Whichever trips first ends the batch.
COALESCE_CHARS = 40
COALESCE_S = 0.1

#: The key whose array carries the answer. The first occurrence is the right one: `AnswerSchema`
#: declares `blocks` first and the constrained-JSON encoder emits the schema's order.
BLOCKS_KEY = '"blocks"'


@dataclass(frozen=True)
class StreamedBlock:
    """One finished answer block, in the only three fields that may leave the process.

    `text` is already redacted (§7.4 G6): the block is constructed that way in `_drain`, so no
    consumer of a `StreamedBlock` can publish an unscrubbed secret.
    """

    index: int
    type: str
    text: str
    citations: list[str] = field(default_factory=list)


class _BlockScanner:
    """A resumable scan of a partial JSON body for the completed objects of its `blocks` array."""

    def __init__(self) -> None:
        self.blocks: list[dict] = []
        self.done = False
        self._buffer = ""
        self._cursor = 0
        self._in_array = False
        self._depth = 0
        self._start = -1
        self._in_string = False
        self._escaped = False

    def push(self, text: str) -> None:
        self._buffer += text

    def advance(self) -> None:
        """Consume whatever has arrived since the last call, appending any newly complete block."""
        if self.done:
            return
        if not self._in_array and not self._open_array():
            return
        buffer = self._buffer
        index = self._cursor
        length = len(buffer)
        while index < length:
            char = buffer[index]
            if self._in_string:
                if self._escaped:
                    self._escaped = False
                elif char == "\\":
                    self._escaped = True
                elif char == '"':
                    self._in_string = False
            elif char == '"':
                self._in_string = True
            elif char == "{":
                if self._depth == 0:
                    self._start = index
                self._depth += 1
            elif char == "}":
                self._depth -= 1
                if self._depth == 0:
                    if not self._take(buffer[self._start : index + 1]):
                        self._cursor = index + 1
                        return
            elif char == "]" and self._depth == 0:
                # The array closed: everything after it is `next_steps` and `rationale_summary`,
                # neither of which is streamed.
                self.done = True
                self._cursor = index + 1
                return
            index += 1
        self._cursor = index

    def _open_array(self) -> bool:
        head = self._buffer.find(BLOCKS_KEY, self._cursor)
        if head < 0:
            return False
        bracket = self._buffer.find("[", head + len(BLOCKS_KEY))
        if bracket < 0:
            return False
        self._in_array = True
        self._cursor = bracket + 1
        return True

    def _take(self, raw: str) -> bool:
        """Decode one balanced object. A body that will not parse stops the scan, quietly."""
        try:
            block = json.loads(raw)
        except json.JSONDecodeError:
            # The provisional render is an enhancement: `turn_completed` carries the real answer a
            # moment later, so a malformed stream costs a preview and nothing else.
            self.done = True
            return False
        if isinstance(block, dict):
            self.blocks.append(block)
        return True


class AnswerAssembler:
    """Feed it the synthesis call's text deltas; it hands back complete blocks, coalesced."""

    def __init__(
        self,
        *,
        coalesce_chars: int = COALESCE_CHARS,
        coalesce_s: float = COALESCE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._scanner = _BlockScanner()
        self._coalesce_chars = coalesce_chars
        self._coalesce_s = coalesce_s
        self._clock = clock
        self._pending = 0
        self._last_scan = clock()
        self._emitted = 0
        #: How many times the buffer has actually been scanned — what coalescing bounds, and what
        #: `test_sse_delta_coalescing_under_queue_max` reads to prove it is doing something.
        self.scans = 0

    def feed(self, text: str) -> list[StreamedBlock]:
        """Absorb one delta. Returns the blocks it completed, which is usually none."""
        self._scanner.push(text)
        self._pending += len(text)
        now = self._clock()
        if self._pending < self._coalesce_chars and (now - self._last_scan) < self._coalesce_s:
            return []
        self._pending = 0
        self._last_scan = now
        return self._drain()

    def flush(self) -> list[StreamedBlock]:
        """Scan whatever the last batch left, once the call is over. Never coalesced away."""
        return self._drain()

    def _drain(self) -> list[StreamedBlock]:
        self.scans += 1
        self._scanner.advance()
        fresh = self._scanner.blocks[self._emitted :]
        first = self._emitted
        self._emitted = len(self._scanner.blocks)
        return [
            StreamedBlock(
                index=first + offset,
                type=str(block.get("type") or "policy_fact"),
                # G6 (§7.4, §17) applies here too, and only here: a delta is neither a persisted
                # span payload (`trace.prepare_payload`) nor the finished answer (`g6.check`), so
                # this is the one place on the streaming path where the model's own prose is
                # scrubbed before it leaves the process. A secret can reach the model through a
                # corpus chunk or a tool result and be echoed into a synthesis block; without this
                # the block would be rendered verbatim in `#provisional-blocks` and stay on screen
                # for the rest of the turn while G6's span still recorded `verdict=allow`, because
                # the string it scrubbed — the final rendered answer — is a different object.
                # `redact()` is idempotent, so the finished answer and the spans are unchanged.
                text=redact_text(str(block.get("text") or "")),
                citations=[str(citation) for citation in (block.get("citations") or [])],
            )
            for offset, block in enumerate(fresh)
        ]


__all__ = ["COALESCE_CHARS", "COALESCE_S", "AnswerAssembler", "StreamedBlock"]
