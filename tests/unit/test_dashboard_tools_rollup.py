"""Page 7's `by_tool` rollup is a SQL aggregate, and only `recent` is materialised (spec §11.6).

`build_tools` used to `SELECT` every `tool_call` span in the store with no `LIMIT` and `json.loads`
each payload — up to 32 KB apiece (§10.5) — purely to count the calls, while `ROW_LIMIT` bounded
only the rows it kept. On the 0.1-CPU / 512 MB instance §14 targets, one admin refreshing page 7
against a full retention window would have walked the lot into memory. Every sibling builder
(`build_llm`, `build_retrieval`, `build_safety`) bounds its `SELECT`; this pins that page 7 does too,
*and* that bounding the row list did not cost the rollup its completeness — the counts still cover
every call, not just the newest `ROW_LIMIT`.
"""

from __future__ import annotations

from types import SimpleNamespace

from hrmosaic.core.models import ToolCallPayload
from hrmosaic.core.trace import SessionSpec
from hrmosaic.web import dashboard as dash

#: More `tool_call` spans than the page lists, so a rollup computed from the row list would be short.
CALLS = dash.ROW_LIMIT + 25


def _request():
    """The two attributes `build_tools` reads: `get_store(None)` returns the fixture store."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=None)))


class RecordingStore:
    """The fixture store, remembering every statement and how many rows it handed back."""

    def __init__(self, store) -> None:
        self._store = store
        self.calls: list[tuple[str, int]] = []

    def execute(self, sql, params=()):
        rows = self._store.execute(sql, params)
        self.calls.append((" ".join(sql.split()), len(rows.dicts())))
        return rows

    def batch(self, stmts):
        return self._store.batch(stmts)

    def payload_rows(self) -> list[tuple[str, int]]:
        """The statements that pull `payload_json` — the ones whose row count costs memory."""
        return [(sql, count) for sql, count in self.calls if "payload_json FROM spans" in sql]


def _tool_calls(writer, *, name: str, count: int, errors: int = 0) -> None:
    """`count` real `tool_call` spans through `core/trace.py` — never a hand-written INSERT."""
    session = SessionSpec(employee_id="E1042", client_label="web")
    turn = writer.start_turn(session, user_message="How much PTO do I have?")
    for index in range(count):
        turn.add_span(
            "tool_call",
            name,
            ToolCallPayload(
                server="hr-mosaic",
                transport="streamable_http",
                tool_name=name,
                arguments={"employee_id": "E1042"},
                # A payload of the size §10.5 actually allows, so a scan of all of them is felt.
                result_json="x" * 4_000,
                is_error=index < errors,
                error_code="TOOL_ERROR" if index < errors else None,
                duration_ms=index + 1,
            ),
            started_at=1_000_000 + index,
            ended_at=1_000_000 + index + (index + 1) * 1_000,
        )
    turn.close(outcome="answered")


def test_the_tool_rollup_counts_every_call_while_the_row_list_stays_bounded(writer, store, monkeypatch):
    _tool_calls(writer, name="check_pto_balance", count=CALLS, errors=7)
    _tool_calls(writer, name="create_hr_case", count=3)
    recorder = RecordingStore(store)
    monkeypatch.setattr(dash, "get_store", lambda settings=None: recorder)

    view = dash.build_tools(_request(), dash.Filters())

    # The memory bound, stated where it bites: no statement reads more payloads than the page lists.
    payload_reads = recorder.payload_rows()
    assert payload_reads, "page 7 still has to read some payloads"
    for sql, count in payload_reads:
        assert "LIMIT" in sql, sql
        assert count <= dash.ROW_LIMIT, f"{count} payloads materialised by: {sql}"

    assert len(view.recent) == dash.ROW_LIMIT, "page 7 must list at most ROW_LIMIT rows"
    rollup = {row.tool_name: row for row in view.by_tool}
    assert set(rollup) == {"check_pto_balance", "create_hr_case"}
    assert rollup["check_pto_balance"].calls == CALLS, "the rollup counts calls the page does not list"
    assert rollup["create_hr_case"].calls == 3
    assert rollup["check_pto_balance"].error_rate == round(7 / CALLS, 4)
    assert rollup["create_hr_case"].error_rate == 0.0
    assert rollup["check_pto_balance"].p50_ms is not None
    assert rollup["check_pto_balance"].p95_ms >= rollup["check_pto_balance"].p50_ms
    assert rollup["check_pto_balance"].last_called_at is not None


def test_the_tool_filters_narrow_both_the_rollup_and_the_rows(writer):
    _tool_calls(writer, name="check_pto_balance", count=5, errors=2)
    _tool_calls(writer, name="create_hr_case", count=4)

    by_name = dash.build_tools(_request(), dash.Filters(tool="create_hr_case"))
    assert [row.tool_name for row in by_name.by_tool] == ["create_hr_case"]
    assert {row.tool_name for row in by_name.recent} == {"create_hr_case"}

    failing = dash.build_tools(_request(), dash.Filters(errors_only=True))
    assert [(row.tool_name, row.calls) for row in failing.by_tool] == [("check_pto_balance", 2)]
    assert all(row.is_error for row in failing.recent)
