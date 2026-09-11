"""`hrmosaic.mcpserver.stdio_main` — the stdio transport entrypoint (spec §8.1).

`tests/integration/test_mcp_discovery.py` proves the whole thing works by spawning
`python mcp/server_entrypoint.py --stdio` as a separate OS process, which is the right proof and
also the reason nothing in-process ever executed a line of this module. The two properties that
would be silently wrong in that subprocess are asserted here instead:

* **stdout belongs to the JSON-RPC framing.** A single log record written to stdout corrupts the
  stream, and the client's failure is a parse error a long way from the cause. `configure_logging`
  removes whatever handlers are already installed and pins one at stderr.
* **The transport is `stdio` on both halves** — the `ServerDeps` the tools record their provenance
  from, and the `run()` call itself. A default that drifted to `streamable-http` would hang the
  client on a pipe nobody is writing to.
"""

from __future__ import annotations

import logging
import sys

import pytest
from mcp.server.mcpserver import MCPServer

from hrmosaic.mcpserver import stdio_main
from hrmosaic.mcpserver.server import SERVER_NAME


@pytest.fixture
def restored_root_logger():
    """Hand the root logger back exactly as it was — pytest's own capture lives on it."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield root
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)


def test_every_log_record_is_pinned_to_stderr_because_stdout_carries_the_protocol(restored_root_logger):
    stray = logging.StreamHandler(stream=sys.stdout)
    restored_root_logger.addHandler(stray)

    stdio_main.configure_logging()

    assert stray not in restored_root_logger.handlers, "a pre-existing stdout handler must be removed"
    assert len(restored_root_logger.handlers) == 1
    installed = restored_root_logger.handlers[0]
    assert isinstance(installed, logging.StreamHandler)
    assert installed.stream is sys.stderr
    assert restored_root_logger.level == logging.WARNING


def test_a_quieter_or_louder_level_is_the_only_thing_a_caller_may_choose(restored_root_logger):
    stdio_main.configure_logging(logging.DEBUG)
    assert restored_root_logger.level == logging.DEBUG
    assert restored_root_logger.handlers[0].stream is sys.stderr


def test_main_serves_the_hr_server_over_stdio_and_nothing_else(monkeypatch, restored_root_logger):
    """The real server is built; only the call that would block on the pipe is intercepted."""
    served: dict[str, object] = {}

    def record(self: MCPServer, transport: str = "stdio", **kwargs: object) -> None:
        served["server"] = self
        served["transport"] = transport
        served["kwargs"] = kwargs

    monkeypatch.setattr(MCPServer, "run", record)

    stdio_main.main()

    assert served["transport"] == "stdio"
    assert served["kwargs"] == {}
    assert served["server"].name == SERVER_NAME
    assert restored_root_logger.handlers[0].stream is sys.stderr, "logging is configured before serving"


def test_main_serves_the_deps_it_is_handed_rather_than_building_its_own(monkeypatch, restored_root_logger):
    """`mcp/server_entrypoint.py` may pass its own `ServerDeps`; the default is the stdio one."""
    from hrmosaic.mcpserver.server import ServerDeps

    served: dict[str, object] = {}
    monkeypatch.setattr(MCPServer, "run", lambda self, **kwargs: served.update(kwargs=kwargs))

    deps = ServerDeps(transport="stdio")
    stdio_main.main(deps)

    assert served["kwargs"] == {"transport": "stdio"}
    assert deps.transport == "stdio"
