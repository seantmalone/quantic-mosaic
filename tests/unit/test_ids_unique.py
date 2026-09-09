"""Ids are minted from `secrets` and collide neither within nor across interpreter runs (§10.1)."""

from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
import textwrap

from hrmosaic.core import ids

N = 10_000

HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX16 = re.compile(r"^[0-9a-f]{16}$")

CHILD = textwrap.dedent(
    """
    import json
    from hrmosaic.core import ids
    print(json.dumps([ids.new_session_id() for _ in range(%d)]))
    """
)


def test_session_ids_are_32_hex_and_unique():
    minted = [ids.new_session_id() for _ in range(N)]
    assert len(set(minted)) == N
    assert all(HEX32.match(value) for value in minted)


def test_turn_ids_are_32_hex_and_span_ids_are_16_hex():
    assert HEX32.match(ids.new_turn_id())
    assert HEX16.match(ids.new_span_id())
    assert len({ids.new_span_id() for _ in range(N)}) == N


def test_ids_from_two_interpreter_runs_are_disjoint():
    """A restarted process must never re-mint an id already in the store."""
    mine = {ids.new_session_id() for _ in range(N)}
    completed = subprocess.run(
        [sys.executable, "-c", CHILD % N],
        capture_output=True,
        text=True,
        check=True,
    )
    theirs = set(json.loads(completed.stdout))
    assert len(theirs) == N
    assert mine.isdisjoint(theirs)
    assert completed.stderr == ""


def test_seed_is_a_module_constant_with_no_environment_variable():
    """§12.3: there is deliberately no `SEED` variable — it is a constant read by `evaluation/**`."""
    assert ids.SEED == 1729
    source = inspect.getsource(ids)
    assert "os.environ" not in source
    assert "getenv" not in source
