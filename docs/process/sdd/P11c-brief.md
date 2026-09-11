# P11c brief — loopback MCP client timeouts, warm-up retry, `/ready` in the smoke

## Where this fits
P11 deployed the service to Render's free tier and P11b ran the post-gate steps. Measuring cold
start (spec §14.4) exposed a deployment defect that has been present since the first deploy:
`/ready` is permanently 503 on the live instance while `/chat` works. This wave fixes it. The fix
is redeployed by the normal CI path, then the cold start is re-measured (not your job).

## The defect — evidence
- Render logs, boot at 17:29:05Z (2026-09-10): "Started server process", the MCP handshake over
  the loopback StreamableHTTP mount succeeds, the warm-up `tools/call` POST is issued at 17:29:06Z,
  and at 17:29:11Z — five seconds later — the client logs `GET stream disconnected, reconnecting in
  1000ms...`. The identical five-second pattern follows the 17:02:45Z boot.
- Live `GET /ready` fifteen minutes later:
  `{"ready": false, "reason": "warm-up call failed: search_policy_documents could not be called: SSE stream ended without a response"}`
  while `GET /health` is `status: ok`, `degradations: []`, index loaded (14 docs, 204 chunks),
  rss 300 MB, and a `POST /chat` answers 200 with `search_policy_documents` ok in 26.3 s.
- Primary cause — `src/hrmosaic/agent/client.py::_http_client` returns
  `httpx2.AsyncClient(headers=self._headers)`; httpx2 2.12's default is `Timeout(5.0)` for connect,
  read, write and pool. The SDK's own factory (`mcp.shared._httpx_utils.create_mcp_http_client`)
  uses 30 s connect/write/pool and a **300 s read** timeout precisely because a StreamableHTTP
  response stream is held open until the result arrives. On the 0.1-CPU free instance the first
  embed (ONNX session load) takes longer than 5 s, the POST response stream read-times-out, and the
  SDK surfaces "SSE stream ended without a response". Locally the model loads in 2.6 s, so no local
  gate saw it. Any loopback tool call that goes 5 s without a byte has the same failure.
- Amplifier — `src/hrmosaic/web/main.py::_warm_up` retries the handshake until
  `settings.ready_warmup_timeout_s` but gives the warm-up `call_tool` exactly one attempt; a
  failure latches `app.state.ready = False` for the life of the process.
- Nothing in the deploy path checks `/ready`: `scripts/wait_for_deploy.py` reads
  `/health.app.git_sha`, `scripts/smoke_deployed.py` reads `/health` fields only.

## Required changes (exactly these files; nothing else)
1. `src/hrmosaic/agent/client.py` — `_http_client` builds the client with explicit timeouts that
   mirror the SDK's factory: a module constant `LOOPBACK_TIMEOUT = httpx2.Timeout(30.0, read=300.0)`
   (30 s connect/write/pool, 300 s read), passed as `timeout=`. Do not import the SDK's private
   `_httpx_utils` module. The no-headers branch keeps returning `None` (the SDK then builds its
   own client with the same numbers). Docstring says why in two sentences (the 0.1-CPU first embed;
   a stream that is silent between bytes is not a dead stream).
2. `src/hrmosaic/web/main.py` — `_warm_up` gives `call_tool` the same bounded retry the handshake
   already has, inside the existing `settings.ready_warmup_timeout_s` deadline: the deadline is
   checked **between** attempts only (an in-flight call is bounded by the transport's read timeout
   and is never cancelled), attempts are separated by a short sleep (1 s is fine; name it), a
   success sets `ready = True` and clears the reason, exhaustion keeps the last reason. Keep the
   one-loopback-call contract of §11.4 (the *successful* call is one call; retries are of a failed
   one). No new mechanisms: no `/ready`-triggered re-warm-up, no readiness flip from ordinary turns.
   Default `ready_warmup_timeout_s` stays 30.
3. `scripts/smoke_deployed.py` — after the `/health` assertions, poll `GET /ready` until 200 within
   a bounded wait (default 600 s, `--ready-timeout` on the CLI, `SMOKE_READY_TIMEOUT_S` env), and
   FAIL the smoke naming the `reason` text if it never greens. The smoke must catch this defect
   next time.
4. Spec `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md` §11.4 — add two sentences:
   the loopback client's 30 s / 300 s-read timeouts (why), and the bounded warm-up retry inside
   `READY_WARMUP_TIMEOUT_S`. Keep the section's length discipline; no new tables.
5. `CHANGELOG.md` — one entry (P11c) stating the defect, the evidence in one line, and the fix.

## Tests (add; all existing tests stay green)
- Unit: `_http_client()` with headers set returns a client whose `timeout.read == 300.0` and
  `connect == write == pool == 30.0`; with no headers returns `None`. Also assert the constant is
  not httpx2's default (`!= httpx2.Timeout(5.0)`), so a refactor cannot silently regress it.
- Unit: `_warm_up` with a fake client whose `call_tool` fails once (an exception, and separately a
  `result.is_error`) then succeeds → `ready True`, `ready_reason None`; all attempts failing until
  the deadline → `ready False`, reason = last failure; the loop stops at the deadline (use a small
  `ready_warmup_timeout_s` and a patched sleep, not real seconds).
- Unit for `smoke_deployed.py`'s `/ready` wait: greens on the second poll → pass; never greens →
  the failure message carries the `reason` text.

## Definition of done
- `ruff check .` clean; `pytest -q` green (baseline 1,652 tests at 17bb389 plus yours);
  `python scripts/check_facts.py` and `python scripts/pii_check.py` unchanged.
- Commit(s) on `main` prefixed `P11c(deploy): …`. Never push. Never read or print `.env`; run
  nothing against the live URL (the cold-start re-measurement is a later step).
- No subagents. Report to `.superpowers/sdd/2026-09-08-implementation-roadmap/P11c-report.md`;
  return status, commit sha(s), one-line test summary, concerns.
