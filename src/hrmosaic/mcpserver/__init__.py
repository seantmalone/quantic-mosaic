"""The MCP server: nine tools, three transports, one factory (spec §8).

Import boundary (§4.2): `mcpserver/` depends on `rag/` and `core/` and on nothing above it.
`agent/**` never imports this package — it reaches the server over the MCP wire, which is what
`tests/architecture/test_conventions.py` greps for — so the same code serves the in-process mount,
the stdio subprocess and a remote deployment with no branch anywhere.
"""

from hrmosaic.mcpserver.server import ServerDeps, build_hr_server

__all__ = ["ServerDeps", "build_hr_server"]
