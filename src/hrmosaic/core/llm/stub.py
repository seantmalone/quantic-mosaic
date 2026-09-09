"""`StubAdapter` — the keystone of the key-free push path (spec §16.2).

It replays a scripted list of completions from `tests/fixtures/llm_scripts/*.json`, one file per
scenario, **selected by the test** (or by `LLM_STUB_SCRIPT`, which `make run` / `make demo1` /
`make demo2` / `make docker-run-512` export) and **never by prompt matching** — so a prompt-wording
change can never break a stub. Entries are consumed in order and each declares the `purpose` it
answers; a script that has drifted out of step with the loop fails loudly rather than silently
replaying the wrong completion.

Because it subclasses `RecordingAdapter`, a stubbed turn writes exactly the same `llm_call` span
and `llm_messages` rows a live turn writes. That is what lets `test_audit_completeness`, the
`/chat` contract tests, the dashboard render tests and both demo scripts run in CI with zero
secrets while still exercising the real record.

At P10 one **real** exchange per demo task is recorded and committed here, so the shipped scripts
are recordings rather than inventions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hrmosaic.core.llm.base import Completion, CompletionRequest, Deadline, RecordingAdapter, ToolCall

#: Keys an entry may carry. `prompt_tokens` / `completion_tokens` are optional and default to 0:
#: a stub must never invent token counts that a cost estimate would then treat as real.
ENTRY_KEYS = frozenset(
    {"purpose", "response_text", "tool_calls", "finish_reason", "prompt_tokens", "completion_tokens"}
)


class StubScriptError(RuntimeError):
    """The script is exhausted, malformed, or out of step with the purposes the loop asked for."""


class StubAdapter(RecordingAdapter):
    """Replays `tests/fixtures/llm_scripts/<scenario>.json`, one entry per call, in order."""

    provider = "stub"

    def __init__(self, *, script_path: Path | str, model: str = "stub") -> None:
        super().__init__(model=model)
        self.script_path = Path(script_path)
        self._entries = load_script(self.script_path)
        self._cursor = 0

    @property
    def configured(self) -> bool:
        """A stub needs no credential — that is the whole point (§16.2)."""
        return True

    @property
    def remaining(self) -> int:
        """Entries not yet replayed — a test asserting a script was fully consumed reads this."""
        return len(self._entries) - self._cursor

    def reset(self) -> None:
        """Rewind to the first entry, so one adapter can drive two turns of the same scenario."""
        self._cursor = 0

    async def invoke(self, request: CompletionRequest, deadline: Deadline | None = None) -> Completion:
        # `deadline` is accepted and ignored: a replay makes no round trip, so it can neither
        # outlive the logical call's budget nor be cut short by it.
        if self._cursor >= len(self._entries):
            raise StubScriptError(
                f"{self.script_path} has {len(self._entries)} entries and the loop asked for "
                f"{self._cursor + 1} (purpose {request.purpose!r})"
            )
        entry = self._entries[self._cursor]
        self._cursor += 1
        expected = entry.get("purpose")
        if expected is not None and expected != request.purpose:
            raise StubScriptError(
                f"{self.script_path} entry {self._cursor} scripts purpose {expected!r} but the loop "
                f"asked for {request.purpose!r}"
            )
        return Completion(
            text=entry.get("response_text") or "",
            tool_calls=[
                ToolCall(
                    id=call.get("id", f"stub_{self._cursor}_{index}"),
                    name=call["name"],
                    args=call.get("args", {}),
                )
                for index, call in enumerate(entry.get("tool_calls") or [])
            ],
            finish_reason=entry.get("finish_reason"),
            provider=self.provider,
            model=self.model,
            prompt_tokens=int(entry.get("prompt_tokens") or 0),
            completion_tokens=int(entry.get("completion_tokens") or 0),
            structured_output_mode="stub" if request.response_schema is not None else None,
        )


def load_script(path: Path) -> list[dict[str, Any]]:
    """Read and structurally validate a script — a typo in a fixture must fail at load, not mid-turn."""
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StubScriptError(f"no stub script at {path} (LLM_STUB_SCRIPT)") from exc
    except json.JSONDecodeError as exc:
        raise StubScriptError(f"{path} is not valid JSON: {exc}") from exc
    entries = body.get("completions") if isinstance(body, dict) else body
    if not isinstance(entries, list) or not entries:
        raise StubScriptError(f"{path} must hold a non-empty list of completions")
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise StubScriptError(f"{path} entry {index} is not an object")
        unknown = set(entry) - ENTRY_KEYS
        if unknown:
            raise StubScriptError(f"{path} entry {index} carries unknown keys {sorted(unknown)}")
        for call in entry.get("tool_calls") or []:
            if not isinstance(call, dict) or "name" not in call:
                raise StubScriptError(f"{path} entry {index} has a tool call with no name")
    return entries
