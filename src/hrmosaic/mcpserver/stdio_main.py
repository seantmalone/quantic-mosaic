"""The stdio transport entrypoint (spec §8.1).

`MCP_TRANSPORT=stdio` runs the same nine tools as a **visibly separate OS process**: local dev, the
demo video, and CI's fast discovery test, which needs no uvicorn and no port. `mcp/server_entrypoint.py`
is the thin repo-root script `python mcp/server_entrypoint.py --stdio` invokes; the logic lives here so
that `mcp/` can stay `__init__.py`-free and un-importable (§4.1).

**stdout belongs to the protocol.** Anything printed on it corrupts the JSON-RPC framing, so logging
is pinned to stderr before the server starts.
"""

from __future__ import annotations

import logging
import sys

from hrmosaic.mcpserver.server import ServerDeps, build_hr_server


def configure_logging(level: int = logging.WARNING) -> None:
    """Send every log record to stderr — stdout carries the JSON-RPC stream and nothing else."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)


def main(deps: ServerDeps | None = None) -> None:
    """Serve the nine tools over stdio until the client closes the pipe."""
    configure_logging()
    server = build_hr_server(deps if deps is not None else ServerDeps(transport="stdio"))
    server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess by the discovery test
    main()
