#!/usr/bin/env python3
"""Run the Mosaic HR MCP server standalone (spec §8.1, §4.1).

    python mcp/server_entrypoint.py --stdio
    python mcp/server_entrypoint.py --http --port 8000     # serves http://127.0.0.1:8000/mcp-server/mcp

DOCS.8 asks for a top-level `mcp/` directory, which risks shadowing the installed `mcp` 2.2.0
package. The resolution is that **this directory contains no `__init__.py`**, so it is never an
importable package — `tests/architecture/test_conventions.py` asserts the file's absence and
`tests/contract/test_mcp_api_shape.py` importing `mcp.server.mcpserver` from the repository root is
the live proof that the real SDK still wins. Everything real lives in `src/hrmosaic/mcpserver/`; this
file is the argument parser and nothing else.
"""

from __future__ import annotations

import argparse

from hrmosaic.mcpserver.server import ServerDeps
from hrmosaic.mcpserver.stdio_main import main as stdio_main
from hrmosaic.settings import settings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mosaic HR Copilot MCP server")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--stdio", action="store_true", help="serve over stdio (default)")
    transport.add_argument("--http", action="store_true", help="serve Streamable HTTP with uvicorn")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=settings.port)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.http:
        import uvicorn

        from hrmosaic.mcpserver.asgi import build_mounted_app

        uvicorn.run(build_mounted_app(ServerDeps(transport="http")), host=args.host, port=args.port, workers=1)
        return 0
    stdio_main(ServerDeps(transport="stdio"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
