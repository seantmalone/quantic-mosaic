"""The §13.7 packet builder can read the turns of a run driven against the **deployed** service.

`scripts/gen_label_packet.py` used to construct `SqliteStore(Path(args.traces))` unconditionally,
which silently assumes the run's turns are in a local file. They are not when the run was driven
with `EVAL_TARGET_BASE_URL` pointing at the deployed service: the service writes to its own store
(Turso in production), so the builder opened an empty sqlite file and every item rendered as
"_no policy evidence reached the synthesis prompt for this turn_" — a packet that looks like
evidence of an ungrounded agent when it is really evidence of the wrong database.

`traces` now accepts the literal `auto`, which resolves through `hrmosaic.core.db.get_store()` so
the environment decides the backend, exactly as the service and the evaluation harness do. A path
still means a local sqlite file, which is what every earlier (locally driven) packet used.
"""

from __future__ import annotations

from pathlib import Path

from hrmosaic.core.db import SqliteStore
from scripts import gen_label_packet


def test_auto_resolves_through_get_store(monkeypatch):
    """`auto` asks the process-wide store builder; it never touches the filesystem."""
    sentinel = object()
    calls: list[int] = []

    def fake_get_store():
        calls.append(1)
        return sentinel

    monkeypatch.setattr(gen_label_packet, "get_store", fake_get_store)

    assert gen_label_packet.open_store("auto") is sentinel
    assert calls == [1]


def test_a_path_is_still_a_local_sqlite_store(tmp_path):
    """The original behaviour is unchanged: anything that is not `auto` is a sqlite path."""
    traces = tmp_path / "nested" / "traces.sqlite"

    store = gen_label_packet.open_store(str(traces))

    assert isinstance(store, SqliteStore)
    assert Path(store.path) == traces
    store.close()


def test_a_path_does_not_consult_get_store(tmp_path, monkeypatch):
    """A local packet build must not need Turso credentials in the environment."""

    def explode():  # pragma: no cover — the assertion is that this is never called
        raise AssertionError("open_store consulted get_store for a filesystem path")

    monkeypatch.setattr(gen_label_packet, "get_store", explode)

    store = gen_label_packet.open_store(str(tmp_path / "traces.sqlite"))
    store.close()
