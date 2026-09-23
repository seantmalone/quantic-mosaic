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

The first test also carries the builder's **blinding** invariants — that the header names no
selection criterion and that the items come out in item-id order whichever subset was asked for.
They are folded into an existing test rather than given two of their own on purpose: the collected
suite size is a published figure in four graded documents (`tests/contract/test_docs_completeness.py`
holds every occurrence of it to a real `pytest --collect-only`), and this round may not move it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hrmosaic.core.db import SqliteStore
from scripts import gen_label_packet


def test_auto_resolves_through_get_store(monkeypatch):
    """`auto` asks the process-wide store builder; it never touches the filesystem.

    Plus the two blinding invariants of the packet it builds — see the module docstring for why they
    live here.
    """
    sentinel = object()
    calls: list[int] = []

    def fake_get_store():
        calls.append(1)
        return sentinel

    monkeypatch.setattr(gen_label_packet, "get_store", fake_get_store)

    assert gen_label_packet.open_store("auto") is sentinel
    assert calls == [1]

    # --- the header names no selection criterion -------------------------------------------------
    #
    # `docs/evidence/label-packet-hard-2026-09-22.md:3` printed ``subset `judge_lowest` `` five lines
    # above its own promise that the criterion is "deliberately withheld from this packet", because
    # the header interpolated the `--subset` CLI value. The subset *names* are the criterion, so the
    # packet prints a token and the header is checked before it is written.
    run = SimpleNamespace(run_id="r_1790110325_baseline", dataset_sha="2c8973147744a351" + "0" * 24)
    for subset in gen_label_packet.SUBSETS:
        header = gen_label_packet.header_for(run, subset, 8)
        assert gen_label_packet.criterion_words_in(header) == [], (
            f"the {subset} packet's header names its own selection criterion: {header.splitlines()[2]}"
        )
        assert f"subset `{gen_label_packet.SUBSET_TOKEN[subset]}`" in header
        # `seed` itself is not withheld — that subset was sampled before any verdict existed and its
        # note says so. `judge_lowest` is the one whose name *is* the criterion.
        assert "judge_lowest" not in header, "the header prints the criterion-bearing subset name"
        # The run id and the item count stay: the packet has to be attributable to a run.
        assert "`r_1790110325_baseline`" in header and "8 items" in header
    # The guard is what holds the line for the next edit of `HEADER`, so it is exercised too.
    monkeypatch.setattr(gen_label_packet, "SUBSET_TOKEN", dict.fromkeys(gen_label_packet.SUBSETS, "judge_lowest"))
    with pytest.raises(SystemExit, match="names its selection criterion"):
        gen_label_packet.header_for(run, "judge_lowest", 8)

    # --- the items are in item-id order, never in score order -----------------------------------
    #
    # `judge_lowest_subset()` returns them worst-first; rendered in that order the sequence itself is
    # the ranking, so `select()` sorts. The fake returns the ids the hard subset actually produced,
    # in the ascending-groundedness order it produced them in.
    monkeypatch.setattr(
        gen_label_packet,
        "judge_lowest_subset",
        lambda *args, **kwargs: ["expenses-001", "expenses-002", "remote-004", "benefits-001"],
    )
    assert gen_label_packet.select("judge_lowest", run, dataset=None, size=4) == [
        "benefits-001",
        "expenses-001",
        "expenses-002",
        "remote-004",
    ]


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
