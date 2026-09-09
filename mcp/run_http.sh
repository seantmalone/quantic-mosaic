#!/bin/sh
# Serve the nine HR tools over Streamable HTTP on http://127.0.0.1:${PORT}/mcp-server/mcp (spec §8.1).
# This is the standalone form, for pointing MCP Inspector at a server with no web app in front of
# it. The deployed topology mounts the same factory inside the FastAPI process instead.
set -eu
cd "$(dirname "$0")/.."
exec "${PYTHON:-.venv/bin/python}" mcp/server_entrypoint.py --http --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
