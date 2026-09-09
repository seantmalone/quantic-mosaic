#!/bin/sh
# Serve the nine HR tools over stdio, as a visibly separate OS process (spec §8.1).
# Used by local dev, by the demo video and by `make run-stdio`; CI's discovery test spawns the
# entrypoint directly. Run from the repository root: the corpus, the index and the mock data are
# all read from working-directory-relative paths.
set -eu
cd "$(dirname "$0")/.."
exec "${PYTHON:-.venv/bin/python}" mcp/server_entrypoint.py --stdio
