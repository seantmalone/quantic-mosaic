"""Fixtures shared by the store-backed tests.

Every test gets its own migrated `SqliteStore` in a temporary directory and its own
`TraceWriter`, so nothing touches `data/runtime/traces.sqlite` and no test can see another's
rows. The process-wide store and span-listener registries are reset around each test.
"""

from __future__ import annotations

import pytest

from hrmosaic.core import trace as trace_module
from hrmosaic.core.db import SqliteStore, migrate, set_store


@pytest.fixture
def store(tmp_path):
    store = SqliteStore(tmp_path / "traces.sqlite")
    migrate(store)
    set_store(store)
    yield store
    set_store(None)
    store.close()


@pytest.fixture
def writer(store):
    writer = trace_module.TraceWriter(store)
    trace_module.set_writer(writer)
    yield writer
    trace_module.set_writer(None)
    trace_module.clear_span_listeners()
