# P11c report — loopback MCP client timeouts, warm-up retry, `/ready` in the deploy smoke

**Status:** DONE
**Branch:** `main` (never pushed) · **Base:** `d0cc8ee` · **HEAD:** `395036d`
**Commit:** `395036d` — `P11c(deploy): loopback MCP client timeouts, warm-up retry, /ready in the smoke`

---

## What was built

### 1. `src/hrmosaic/agent/client.py` — the primary cause

`_http_client` returned `httpx2.AsyncClient(headers=self._headers)` with no `timeout=`, so
httpx2 2.12's default `Timeout(5.0)` applied to connect, **read**, write and pool alike. A
Streamable HTTP `tools/call` holds its response stream open until the result arrives, so the first
`search_policy_documents` on a 0.1-CPU instance — which loads the ONNX session before it embeds
anything — blew straight through the 5 s read timeout and surfaced as
`SSE stream ended without a response`.

New module constant, placed beside `CLOSE_TIMEOUT_S`:

```python
#: The loopback transport's timeouts, mirroring the SDK's own `create_mcp_http_client`: 30 s to
#: connect, write and take a pool slot, and **300 s to read**. httpx2's default is `Timeout(5.0)`
#: on all four phases, which is wrong for a StreamableHTTP `tools/call` (see `_http_client`).
LOOPBACK_TIMEOUT = httpx2.Timeout(30.0, read=300.0)
```

passed as `timeout=LOOPBACK_TIMEOUT`. `mcp.shared._httpx_utils` is **not** imported — the numbers
are restated, not borrowed from a private module. The no-headers branch still returns `None`, and
the SDK then builds its own client with the same numbers. The function-local `import httpx2` was
lifted to the module's third-party import block (the constant needs it at import time; httpx2 is
already imported by `mcp.client.streamable_http`, so nothing new is loaded at boot). The docstring
says why in two sentences, and the return annotation is now `httpx2.AsyncClient | None` instead of
`Any`. `LOOPBACK_TIMEOUT` is exported in `__all__`.

### 2. `src/hrmosaic/web/main.py` — the amplifier

`_warm_up` retried the *handshake* until `settings.ready_warmup_timeout_s` but gave the warm-up
`call_tool` exactly one attempt; a single failure latched `app.state.ready = False` for the life of
the process. The call now shares that one deadline:

- new constant `WARMUP_RETRY_S = 1.0` (named, as the brief asked), documented against the existing
  `WARMUP_POLL_S = 0.2` — the handshake poll paces a socket that is not listening yet, this one
  paces a server that is busy;
- the deadline is checked **between** attempts only, after a failure and before the sleep, so a
  call already on the wire is bounded by the transport's read timeout and is never cancelled;
- a success sets `ready = True` and clears the reason and returns; an `is_error` result and a
  raised exception are both retried, each overwriting `ready_reason`, so exhaustion leaves the
  **last** failure's reason;
- `settings.ready_warmup_timeout_s` default stays 30. No `/ready`-triggered re-warm-up, no
  readiness flip from ordinary turns, no other new mechanism.

§11.4's one-loopback-call contract is intact: the *successful* call is one call, and
`tests/contract/test_lifespan.py::test_the_ready_warm_up_is_one_loopback_tools_call` (which asserts
exactly one `tool_call` span in the maintenance turn) still passes unchanged.

### 3. `scripts/smoke_deployed.py` — the check that was missing

The smoke now answers a fourth question. After the `/health` assertions and before the
opportunistic gate check it polls `GET /ready` until 200:

- `ready_problems(url, *, wait_s, request_timeout_s, poll_s=READY_POLL_S)` — polls, and checks the
  deadline **after** a poll so `wait_s=0` still asks once;
- `READY_TIMEOUT_S = 600.0`, `READY_POLL_S = 5.0`, `READY_TIMEOUT_ENV = "SMOKE_READY_TIMEOUT_S"`;
- `--ready-timeout` on the CLI, defaulting through `ready_timeout_default()`, which reads
  `SMOKE_READY_TIMEOUT_S` and falls back on a malformed value rather than ending the deploy job in
  an argparse traceback;
- a failure reads `/ready never returned 200 within 600s — last answer: HTTP 503: warm-up call
  failed: …`, i.e. it names the endpoint's own `reason` text;
- `main`'s argument parsing was extracted into `parse_arguments()` so the flag is testable without
  running the script;
- a network fault mid-poll is a failed smoke, matching the gate check's existing treatment.

CI's `python scripts/smoke_deployed.py --url "$DEPLOY_URL"` line needs no change — the default is
600 s.

### 4. Spec `docs/superpowers/specs/…-hr-agentic-rag-design.md` §11.4

Two sentences added inside the existing `/ready` paragraph (no new tables, no new subsection): the
30 s / 300 s-read loopback timeouts and why a held-open response stream needs them, and that the
handshake **and** the call both retry inside the single `READY_WARMUP_TIMEOUT_S` deadline, checked
between attempts and never cancelling a call already on the wire.

### 5. `CHANGELOG.md`

One dated P11c entry in the running style of the P11/P12 entries: the defect (`/ready` 503 since
the first deploy while `/health` was `ok` and `/chat` answered), the evidence in one line (the
17:29:05Z boot, the 17:29:06Z warm-up call, `GET stream disconnected` at 17:29:11Z — five seconds,
repeated after the 17:02:45Z boot), and the three-part fix.

---

## TDD evidence

Every test was written first and watched fail for the right reason.

**Round 1 — `tests/unit/test_loopback_client_timeouts.py` (3 tests), red:**

```
E   ImportError: cannot import name 'LOOPBACK_TIMEOUT' from 'hrmosaic.agent.client'
=========================== short test summary info ============================
ERROR tests/unit/test_loopback_client_timeouts.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 1.00s
```

green after the `client.py` change:

```
...                                                                      [100%]
3 passed in 0.86s
```

**Round 2 — `tests/unit/test_warm_up_retry.py` (3 tests), red:**

```
E         At index 0 diff: False != True          # ready stayed False after one failed attempt
...
>       monkeypatch.setattr(web_main, "WARMUP_RETRY_S", 1.0)
E       AttributeError: <module 'hrmosaic.web.main' …> has no attribute 'WARMUP_RETRY_S'
=========================== short test summary info ============================
FAILED tests/unit/test_warm_up_retry.py::test_a_call_that_fails_once_and_then_succeeds_still_goes_green
FAILED tests/unit/test_warm_up_retry.py::test_an_is_error_result_is_retried_like_a_raised_failure
FAILED tests/unit/test_warm_up_retry.py::test_the_retries_stop_at_the_deadline_and_keep_the_last_reason
3 failed in 1.09s
```

green after the `_warm_up` change (with round 1's tests):

```
......                                                                   [100%]
6 passed in 1.12s
```

**Round 3 — five tests appended to `tests/unit/test_deploy_health_scripts.py`, red:**

```
E           AttributeError: module 'scripts.smoke_deployed' has no attribute 'parse_arguments'
=========================== short test summary info ============================
FAILED …::test_a_ready_that_greens_on_the_second_poll_passes_the_smoke
FAILED …::test_a_ready_that_never_greens_fails_the_smoke_and_quotes_its_reason
FAILED …::test_a_ready_that_answers_something_other_than_json_still_fails_by_status
FAILED …::test_the_ready_wait_is_ten_minutes_unless_the_environment_says_otherwise
FAILED …::test_the_cli_carries_a_ready_timeout_flag
5 failed, 31 passed in 0.08s
```

green after the `smoke_deployed.py` change (with the `--help`-under-a-bare-interpreter contract):

```
............................................                             [100%]
44 passed in 0.70s
```

### The 11 tests, and what each pins

| Test | Pins |
|---|---|
| `test_the_gated_loopback_client_reads_for_five_minutes` | `read == 300.0`, `connect == write == pool == 30.0` on the client `_http_client()` actually builds |
| `test_the_ungated_client_is_none_so_the_sdk_builds_its_own` | no headers → `None` |
| `test_the_timeout_is_not_httpx2s_default` | `LOOPBACK_TIMEOUT != httpx2.Timeout(5.0)` and `== httpx2.Timeout(30.0, read=300.0)` — a refactor that drops `timeout=` cannot regress silently on a slow host only |
| `test_a_call_that_fails_once_and_then_succeeds_still_goes_green` | raised failure then success → `ready True`, `ready_reason None`, 2 attempts |
| `test_an_is_error_result_is_retried_like_a_raised_failure` | `result.is_error` then success → same |
| `test_the_retries_stop_at_the_deadline_and_keep_the_last_reason` | every attempt failing → `ready False`, reason is the **last** failure, and the loop stops at the deadline (4 attempts, virtual clock at exactly 3.0 s of a 3 s budget) |
| `test_a_ready_that_greens_on_the_second_poll_passes_the_smoke` | a cold instance answering 503 first is not a failure |
| `test_a_ready_that_never_greens_fails_the_smoke_and_quotes_its_reason` | the failure message carries the `reason` text |
| `test_a_ready_that_answers_something_other_than_json_still_fails_by_status` | a non-JSON body degrades to `HTTP 502`, never a traceback |
| `test_the_ready_wait_is_ten_minutes_unless_the_environment_says_otherwise` | 600 s default, `SMOKE_READY_TIMEOUT_S` honoured, a malformed value falls back |
| `test_the_cli_carries_a_ready_timeout_flag` | `--ready-timeout` overrides the env default |

No test spends a real second: the warm-up tests run on a virtual clock (a loop stand-in whose
`time()` only moves when the patched `asyncio.sleep` says so — `_warm_up` reads the clock through
`asyncio.get_running_loop()`), and the smoke tests pass `poll_s=0.0`.

---

## Definition of done — real output

`ruff check .`

```
All checks passed!
```

`.venv/bin/pytest -q` (whole suite, `LLM_PROVIDER=stub` via `tests/conftest.py`)

```
........................................................................ [ 98%]
..........................                                               [100%]
1682 passed in 142.41s (0:02:22)
```

1,682 = the 1,671 the base commit `d0cc8ee` reported in its own gate line, plus the 11 added here.
(The brief's "1,652 at `17bb389`" predates two P11/P12 commits that added tests; the collected
count at `d0cc8ee` is 1,671.) No warnings, no skips, no xfails — output pristine.

`.venv/bin/python scripts/check_facts.py`

```
  travel-policy                      md     12 sections
  workplace-conduct                  pdf    13 sections

14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
--- exit 0 ---
```

`.venv/bin/python scripts/pii_check.py`

```
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
--- exit 0 ---
```

Nothing was run against the live URL; `.env` was never read, printed or committed.

---

## Files changed

```
 CHANGELOG.md                                            |  +1 entry
 docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md | §11.4, two sentences
 scripts/smoke_deployed.py                               |  +/ready poll, --ready-timeout
 src/hrmosaic/agent/client.py                            |  +LOOPBACK_TIMEOUT
 src/hrmosaic/web/main.py                                |  +WARMUP_RETRY_S, retried call
 tests/unit/test_deploy_health_scripts.py                |  +5 tests
 tests/unit/test_loopback_client_timeouts.py             |  new, 3 tests
 tests/unit/test_warm_up_retry.py                        |  new, 3 tests
 8 files changed, 379 insertions(+), 20 deletions(-)
```

Staged by explicit path; `git status` clean afterwards; nothing else touched.

---

## Self-review findings (and what I did about them)

1. **The module docstring of `smoke_deployed.py` still said "three questions".** Fixed to "four"
   in the same pass — a numbered list that does not match its own count is exactly the kind of
   staleness this file's docstring exists to prevent.
2. **The `/ready` console line was ambiguous.** My first version printed
   `503 within the wait` on any failure, including a network fault, which would have been a lie
   about what the instance answered. It now prints `  /ready: 200` or
   `  /ready: never green — see below`, with the detail in the FAIL list.
3. **`except Exception` in the retry loop does not swallow shutdown.** `asyncio.CancelledError` is
   a `BaseException` in 3.12, so a lifespan teardown cancelling the warm-up task still unwinds
   through the `finally:` that closes the maintenance turn. Verified by the existing lifespan
   contract tests, which start and stop a real uvicorn.
4. **Retries recover a dropped session, not just a slow one.** `McpClient.call_tool` re-discovers
   when `self._connection.session` is gone, so a retry after a transport failure re-handshakes
   rather than calling into a dead session. No extra code needed; worth stating.
5. **A failed attempt that returns `is_error` writes a `tool_call` span, a raised one does not.**
   That asymmetry is pre-existing (`call_tool` raises `McpUnavailable` before the span is added)
   and the §11.4 contract test still sees exactly one span on the happy path, so I left it alone
   rather than inventing a span-suppression rule the spec does not have.
6. **YAGNI check.** No `/ready`-triggered re-warm-up, no health-driven readiness flip, no retry on
   the *smoke*'s `/health` read, no new settings field, no `.env.example` entry
   (`SMOKE_READY_TIMEOUT_S` is a script knob, not a `Settings` field, and the `.env.example` ↔
   `Settings` bijection test would have failed if I had added one).
7. **Stray worktree.** While measuring the baseline test count I created a `git worktree` that
   landed at `<repo>/baseline`; removed with `git worktree remove --force` before staging, and
   `git worktree list` shows only the main checkout. Nothing of it reached the commit.

---

## Ambiguities resolved

- **"a short sleep (1 s is fine; name it)"** → `WARMUP_RETRY_S = 1.0`, a module constant beside
  `WARMUP_POLL_S`, documented as distinct from it.
- **Where in the smoke the `/ready` poll goes.** The brief says "after the `/health` assertions".
  I put it immediately after `health_problems(payload)` and *before* the opportunistic gate check,
  so a deployment that never warms up is reported even when `APP_ACCESS_TOKEN` is absent (the CI
  case). Its problems join the same `found` list, so the exit status and the FAIL block are
  unchanged in shape.
- **Deadline placement.** "Checked between attempts only" is implemented as *poll → judge → check
  deadline → sleep*, which means the first attempt always happens even with a spent budget, and a
  call in flight is never cancelled. Same shape in the smoke's `ready_problems`, so `wait_s=0`
  still asks once.
- **`SMOKE_READY_TIMEOUT_S` with a non-numeric value.** The brief does not say. It falls back to
  600 s rather than raising, on the reading that the wait is a convenience knob and an argparse
  traceback in the deploy job would be a worse failure than a longer wait.
- **Where `httpx2` is imported.** A module constant needs a module-level import, so the
  function-local `import httpx2` moved up. The SDK's `streamable_http` already imports httpx2 at
  our own import time, so this costs no boot latency.

---

## Concerns / carry-forward

1. **The fix is unverified against the live instance by design.** Everything here is proven
   locally; the actual proof is the next deploy's `/ready` going 200 and the re-measured cold
   start. That is the main session's step, not mine.
2. **The smoke can now take up to 10 extra minutes in CI on a broken deploy.** Bounded, and it is
   the number the brief specified, but a genuinely dead instance will hold the `deploy` job for
   600 s before failing. `SMOKE_READY_TIMEOUT_S` is the knob if that turns out to be too patient.
3. **The 300 s read timeout also applies to the persistent `GET` stream** of the Streamable HTTP
   session, not only to `tools/call` — an idle stream will now sit for up to 300 s instead of
   reconnecting every 5 s. That is the SDK's own default behaviour and it is what removes the
   `GET stream disconnected, reconnecting in 1000ms...` churn from the logs, but it is a behaviour
   change worth knowing about when reading a future log.
4. **`ready_warmup_timeout_s` is still 30 s** (unchanged, as instructed). With a 1 s gap that is
   roughly 30 attempts, but if the very first call genuinely takes longer than the whole 30 s
   budget on a cold 0.1-CPU worker, the warm-up will still exhaust — the call is not cancelled, so
   a late success is simply not waited for. If the re-measurement shows `/ready` still slow to
   green, raising `READY_WARMUP_TIMEOUT_S` (an env var, no code change) is the lever.
