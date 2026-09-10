"""A real uvicorn serving `hrmosaic.web.main:app`, with one turn deliberately left open (§10.3).

Run as `python tests/integration/uvicorn_with_open_turn.py <port>` by the subprocess form of
`tests/integration/test_process_exit_mid_turn.py`. Not a test module — pytest collects `test_*.py`
only — and never imported by `src/`.

**Why a helper rather than an endpoint.** The subprocess tests need a process whose in-memory
`TraceWriter` is holding an unfinished turn at the moment it is killed. Reaching that state through
an HTTP request means either racing a signal against a request (a timing assumption) or relying on
a request that *fails*, which the app no longer lets happen: `web/api.py`'s
`UnhandledErrorMiddleware` closes the turn and answers 200, precisely so nothing is left open. So
the turn is opened here, directly on the process-wide writer the lifespan installed — the same
writer a request would have used, through `core/trace.py`, which is still the only span writer.
That is exactly the state a crash mid-turn leaves behind, with no timing assumption at all.
"""

from __future__ import annotations

import asyncio
import sys

import uvicorn

from hrmosaic.core import trace as trace_module
from hrmosaic.core.models import PlanPayload
from hrmosaic.core.trace import SessionSpec

QUESTION = "How much PTO do full-time employees accrue each month?"


async def main(port: int) -> None:
    from hrmosaic.web.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)

    # The lifespan has installed the process-wide writer (and the shutdown handlers, on the main
    # thread). One turn, one closed span, and then nothing: the buffer stays open for as long as
    # the process lives.
    buffer = trace_module.start_turn(SessionSpec(client_label="api"), user_message=QUESTION)
    with buffer.span("plan", "router") as span:
        span.set_payload(PlanPayload(intent="policy_qa", workflow=None))

    await serving


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1])))
