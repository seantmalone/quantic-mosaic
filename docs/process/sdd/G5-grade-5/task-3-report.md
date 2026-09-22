# Task 3 — configuration and scripts: the dead knob, self-dating demo scripts

Commit: **7678e0c** `G5(config-scripts): MCP_TOOLS_DISABLED is read, and the demo scripts send the
prompt the server dates` (on `main`, parent `e4007f1`, no `Claude-Session` trailer).

## Gap 20 — `MCP_TOOLS_DISABLED` is now read

The cheapest fix the gap offers, plus one consequence it did not mention.

* `src/hrmosaic/settings.py` — the field keeps its name and its `.env.example` line; it gains a
  doc-comment saying what it is, and a `mcp_tools_disabled_list` property that parses it exactly the
  way the neighbouring `mcp_allowed_hosts_list` parses its sibling (split on `,`, strip, drop
  blanks, so an untouched `MCP_TOOLS_DISABLED=` is `[]`).
* `src/hrmosaic/agent/orchestrator.py` — `ChatOptions.tools_disabled` is now
  `Field(default_factory=lambda: list(default_settings.mcp_tools_disabled_list))`. A request that
  states the field wins, **including when it states the empty list**, which is what the eval's
  `no_structured_tools` / baseline arms need (`evaluation/runner.py` always states it).
* `src/hrmosaic/web/api.py` — **required by the above, and the one thing worth reviewing.**
  `privileged_options_used()` compared the resolved *value* against `(None, [], "")`, so a process
  with `MCP_TOOLS_DISABLED` set would have read every ordinary web turn as a request that asked for
  the ablation and answered `403 ADMIN_REQUIRED`: the knob would have broken the chat surface rather
  than filtering the catalogue. It now also requires `name in options.model_fields_set`, which is
  what the function's own docstring already claimed ("which privileged fields this request actually
  set"). No wire behaviour changes for any other field: an absent field used to resolve to
  `None`/`[]`/`""` and was not counted, and still is not.
* `.env.example:67` — the comment now reads `comma-separated tool names; the process default for
  options.tools_disabled` (it said "process default only", which was true of nothing).
* `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md:2271` — the gap's "also fix the spec
  line's location claim": the table said the filter "is applied in the MCP client's schema
  conversion". It is applied in the agent router (`allowed_tools`). One row rewritten. No other
  document owns this variable, and no other task in the plan owns this file.

## Gap 7 — the demo scripts send the prompt the server dates

Implemented as the gap's "better" option, which the dispatch also preferred: ask the server for its
prompt instead of computing dates in `sh`. No `--recorded` flag was needed — a server pinned to
`MOCK_TODAY=2026-09-01` *serves* the recorded wording, so the stub replays get it for free.

* `scripts/demo_prompt.py` (new, stdlib only, ~100 lines incl. docstring) — `GET /` on the instance,
  parse the two demo buttons' `data-prompt` keyed by `data-demo` with `html.parser`, print one.
  Sends `Authorization: Bearer $APP_ACCESS_TOKEN` when the environment carries it, so it works
  against the gated deployment. Exit 1 with a one-line reason on stderr, which the callers read as
  "send the recorded wording".
* `src/hrmosaic/web/templates/_demo_controls.html` — the two buttons gain `data-demo="demo_1|2"`, so
  the helper keys on the prompt it wants rather than on position or attribute order. `class="button
  demo-button"` is untouched (the P8 quarantine test and the prefill handler both key on it).
* `scripts/demo_task_1.sh`, `scripts/demo_task_2.sh` — before anything else, `SERVED="$(... 
  demo_prompt.py --base-url "$BASE_URL" --key demo_N || true)"`; `PROMPT="$SERVED"` when non-empty,
  otherwise the recorded `PROMPT='…'` line stands and the script says so on stderr. Header comments
  rewritten: the recorded line is now documented as the fallback, not as the thing that needs a
  pinned server. Nothing else in either script changed. **No `Makefile` change was needed.**
* **Why no new endpoint.** `tests/contract/test_app_starts.py` pins the route table to §11.8's exact
  endpoint list, so a JSON route for two strings would have meant editing that test, the spec's
  endpoint table and `docs/architecture.html`. Reading `GET /` was strictly cheaper and is what the
  gap proposed first.

Verified by hand against an *unpinned* stub server (today 2026-09-21): `demo_1` →
"3 November to 14 December 2026" (the spec dates, still 21+ days out), `demo_2` → "Tuesday 6 October
to Thursday 8 October 2026" (12 business days' notice). Against the pinned `make demo*` server both
come back as the recorded pair.

## Tests added (13, suite 3,370 → 3,383)

* `tests/unit/test_mcp_tools_disabled_default.py` (5) — the list parsing; an unstated request takes
  the process default (`ChatOptions()` and `ChatRequest`); an empty variable is `[]`; a stated field
  wins including `[]`; and the default reaches `router.allowed_tools`, which is what withholds the
  tool.
* `tests/contract/test_demo_scripts_send_the_served_prompt.py` (4) — the rendered page carries both
  prompts keyed, equal to `demo_prompts()`; `demo_prompt.main` reads one off a live instance over
  HTTP (in `asyncio.to_thread`, since the server under test shares the test's loop); a server pinned
  to `RECORDED_TODAY` serves `DEMO_PROMPTS` exactly (the property that keeps the replays green); the
  helper needs the access token on a gated instance.
* `tests/contract/test_chat_privileged_options.py` (+1) — a process default is not a privileged
  request: an employee-persona `web` turn on a process with `MCP_TOOLS_DISABLED=get_policy_section`
  is **200** and the tool is genuinely absent from every `tools_offered` while
  `search_policy_documents` is present. Confirmed non-vacuous: it fails with the orchestrator change
  stashed (checked), and the withheld tool is one this turn really is offered otherwise (checked by
  printing `tools_offered` — `draft_hr_email`, my first choice, is never offered on a rag-only turn
  and would have been a vacuous assertion).
* `tests/unit/test_demo_prompts_are_dated.py` (+3) — each script invokes the helper with its own key,
  assigns `PROMPT="$SERVED"`, and keeps `PROMPT='…'` above it as the fallback (parametrized over both
  scripts); an unreachable instance exits 1 with a reason and prints nothing on stdout.

The four documents that state the suite size (`README.md:50`, `ai-tooling.md:179`,
`design-and-evaluation.md:801`, `docs/requirements-traceability.md:146`) were bumped to **3,383** in
the same commit; `tests/contract/test_docs_completeness.py` recounts it from a real collection.

## Commands run

| Command | Result |
|---|---|
| `make lint` | `All checks passed!` / `318 files already formatted` |
| `.venv/bin/python -m pytest --collect-only -q -m ""` | `3383 tests collected in 2.63s` |
| `make test` | `3084 passed, 299 deselected in 334.97s (0:05:34)`, exit 0 |
| `make demo1` | exit 0, `-- outcome: answered`, recorded Berlin wording sent |
| `make demo2` | exit 0, `-- outcome: answered`, `MOCK-HR-000079` in the lede `performed` block, `-- and no next step asks for it again` |
| focused | `tests/unit/test_mcp_tools_disabled_default.py`, `tests/contract/test_demo_scripts_send_the_served_prompt.py`, `tests/contract/test_chat_privileged_options.py`, `tests/unit/test_demo_prompts_are_dated.py`, `tests/e2e/test_demo_tasks.py`, `tests/contract/test_docs_completeness.py`, `tests/contract/test_app_starts.py`, `tests/contract/test_env_example_covers_settings.py`, `tests/contract/test_demo_controls_are_quarantined.py`, `tests/contract/test_chat_page_renders.py`, `tests/contract/test_deploy_scripts_are_runnable.py`, `tests/contract/test_demo_two_verdict_is_consistent.py` — all green |

`make test` and both demos were re-run after the `web/api.py` change, not only before it.

## Assumptions

1. **The spec line was in scope.** Gap 20's fix says "Also fix the spec line's location claim"; the
   brief only mentions `.env.example`. No task in the plan owns
   `docs/superpowers/specs/2026-09-08-hr-agentic-rag-design.md`, so I corrected the one row rather
   than leave a documented falsehood.
2. **`data-demo` is cheaper than positional parsing.** One attribute on two buttons, versus a helper
   that depends on the demo buttons being the first two `data-prompt` carriers on a page that also
   renders four starters and any number of quick replies.
3. **The recorded `PROMPT='…'` line stays** in both scripts, as the fallback — required anyway by
   `test_the_recorded_pair_is_byte_for_byte_what_the_shell_scripts_send`, which parses it.
4. `scripts/demo_prompt.py` was not added to `tests/contract/test_deploy_scripts_are_runnable.py`'s
   list: it is not a deploy-time script, and it is covered for real by the contract test that runs
   `main()` against a live instance.

## For Task 6a — README's demo-script paragraph (lines ~72-74)

The `# or against any running instance, including the deployed one:` comment in the fenced block is
now literally true and needs no caveat. Replace the paragraph after the block with:

> `make demo1` / `make demo2` each start their own server with their own recorded stub script, so
> they need no key. The scripts are plain `curl`, parameterised by `BASE_URL`, and print the answer,
> the citations, the full span trace and the `dashboard_url` for the turn. Every call sends
> `Authorization: Bearer $APP_ACCESS_TOKEN`. Each one asks the instance for its own demo prompt
> before it starts, the same self-dated question the chat page's Demo 1 / Demo 2 buttons carry, so
> the dates are always far enough ahead for the notice rules to pass and the verdicts hold against
> the deployed service as well as against the pinned replays.

(Do not add a "only against `MOCK_TODAY=2026-09-01`" caveat — that was gap 7's cheap option and this
task took the real fix instead.)

---

# Fix round 1

Commit: **e923bc3** `G5(config-scripts): fix round 1 — a cold instance is waited for, the recorded
wording is opt-in, and a stated tools_disabled is provably refused` (on `main`, parent `7678e0c`).

## Important 1 — no silent degradation on a cold instance

`scripts/demo_prompt.py`:

* `read_prompt(base_url, key, timeout_s=120.0)` is the new entry point: it retries on connection
  failures, timeouts and the statuses a waking instance produces (`RETRYABLE_STATUS = {408, 429,
  502, 503, 504}`), interval 0.5 s doubling to a 5 s cap, until a total `--timeout` that defaults to
  the same 120 s `make demo1` gives `scripts/wait_for_health.py`. Per-request timeout is still 15 s
  (`REQUEST_TIMEOUT_S`).
* A new `Refused` exception is raised — **not** retried — for a status the instance means (401 with a
  wrong token, 404 with a wrong URL) and for a 200 whose page carries no `data-demo` pair. Spending
  120 s waiting for a wrong token to become a right one would only delay the message that names it.
* `--key` is `required=True` (Minor 4). `--timeout` is new.
* Module docstring rewritten: a failure is a failure, and the recorded wording is opt-in.

`scripts/demo_task_1.sh` / `scripts/demo_task_2.sh`:

* `RECORDED="${DEMO_RECORDED:-0}"`, plus `if [ "${1:-}" = "--recorded" ]` (an `if`, not a `&&` list —
  under `set -e` a failing `[ … ] && X=1` as the final pipeline would exit the script).
* `--recorded` prints `-- --recorded: sending the wording the stub script was recorded against` and
  keeps the frozen `PROMPT='…'`; otherwise
  `elif ! PROMPT="$("$PYTHON" "$(dirname "$0")/demo_prompt.py" … --key demo_N)"; then` → three lines
  of stderr naming the instance, naming `--recorded` and saying what `--recorded` is only good for,
  then `exit 1`. There is no `|| true` anywhere after `set -eu` in either script (asserted by a test).
* Headers updated: the recorded line is described as what `--recorded` sends, not as a fallback.

**The Makefile was deliberately left unchanged** (the dispatch left this to me): the `demo` recipe
already runs `wait_for_health.py --timeout 120` before the script, so the fetch succeeds and
`make demo1` / `make demo2` exercise the real served-prompt path rather than the escape hatch. Both
still send the recorded pair, because the server they talk to is pinned to `MOCK_TODAY=2026-09-01`.

Manual verification (not just tests):

| Invocation | Result |
|---|---|
| `sh scripts/demo_task_1.sh` with no server | exit **1** after the 120 s budget: `could not read demo_1 from http://127.0.0.1:8000/: … did not answer within 120s (<urlopen error [Errno 61] Connection refused>)` then `demo task 1 did not run: … (add --recorded …)` |
| `sh scripts/demo_task_2.sh --recorded` with no server | the `-- --recorded:` line immediately, the frozen prompt echoed, then curl's own failure — i.e. no fetch, no wait |
| `make demo1` / `make demo2` | exit 0, `-- outcome: answered`, `MOCK-HR-000081` in the lede `performed` block |

## Important 2 — the negative privileged-options test

`tests/contract/test_chat_privileged_options.py::test_a_stated_tools_disabled_is_privileged_in_the_employee_persona`:
employee persona + `client_label: "eval"` + `options={"tools_disabled": ["draft_hr_email"]}` → **403**
`{"code": "ADMIN_REQUIRED"}`; admin + `client_label: "web"` + the same options → **403**
`{"code": "PRIVILEGED_OPTION_REFUSED", "field": "tools_disabled"}`. I added a dedicated test rather
than putting `tools_disabled` into the shared `PRIVILEGED` dict, because in that dict the refusal
could be caused by any of the four fields and the field name in row 3's assertion would still be
`variant` — the point is that `tools_disabled` *by itself* is refused.

## Minor 5 — the gate's answer is named

`test_the_helper_answers_the_gate_with_the_access_token` now asserts `GET /` without a token is
**401**, that `prompts_of()` of that key page is `{}`, that the helper's stderr carries `HTTP 401`
(so it is the fast `Refused` path, not a retry loop), and that the same call with the token is 0.

## Tests added (6; suite 3,383 → 3,389)

* `tests/contract/test_demo_scripts_send_the_served_prompt.py` (+2) —
  `test_a_cold_instance_is_waited_for_rather_than_downgraded` (a stubbed `fetch` raises `HTTP 502`
  twice, the third attempt returns the real page; asserts 3 attempts and the served prompt) and
  `test_a_page_that_is_not_the_chat_page_is_reported_at_once` (one attempt, `Refused`).
* `tests/contract/test_chat_privileged_options.py` (+1) — Important 2 above.
* `tests/unit/test_demo_prompts_are_dated.py` (+3) —
  `test_the_recorded_wording_is_opt_in_and_never_a_silent_downgrade` parametrized over both scripts,
  and `test_the_key_is_required` (argparse exits 2).
* Rewritten, not added: `test_each_script_asks_the_server_for_its_own_prompt` now pins the
  `elif ! PROMPT="$(…)"` form and an `exit 1` after it, and
  `test_an_unreachable_instance_falls_back_instead_of_failing_the_demo` became
  `test_an_unreachable_instance_is_a_loud_failure` (runs with `--timeout 0`, so it costs nothing).

The four documents that state the suite size were bumped to **3,389**.

## Commands run

| Command | Result |
|---|---|
| `make lint` | `All checks passed!` / `318 files already formatted` |
| `.venv/bin/pytest -q tests/contract` | `553 passed in 177.56s (0:02:57)` |
| `.venv/bin/pytest -q tests/unit/test_demo_prompts_are_dated.py tests/unit/test_mcp_tools_disabled_default.py tests/e2e/test_demo_tasks.py` | `411 passed in 5.73s` |
| `.venv/bin/pytest -q tests/contract/test_chat_privileged_options.py` | `8 passed` |
| `.venv/bin/pytest -q tests/contract/test_demo_scripts_send_the_served_prompt.py` | `6 passed` |
| `.venv/bin/python -m pytest --collect-only -q -m ""` | `3389 tests collected` |
| `make demo1` / `make demo2` | exit 0 / exit 0, both `-- outcome: answered` |

The full `make test` was not re-run in this round (the previous round's run was
`3084 passed, 299 deselected`); `tests/contract` in full plus every touched unit and e2e file were,
and nothing in `src/` changed in this round — the diff is two shell scripts, one helper script, three
test files and the four suite-size figures.

---

# Fix round 2

Commit: **ef917a3** `G5(config-scripts): fix round 2 — the operator's tool filter is additive, so no
caller can state their way past it` (on `main`, parent `e923bc3`).

## The hole, stated plainly

`privileged_options_used` skips `(None, [], "")`, and it is right to: an empty
`options.tools_disabled` asks for nothing. But while `MCP_TOOLS_DISABLED` was the **default** for
that field, "asks for nothing" was worth something — a caller in any persona could send
`"tools_disabled": []`, override the operator's default, and be offered the tool the process was
configured to withhold. Before this wave the variable did nothing at all, so the hole arrived with my
change. A knob that the people it is pointed at can switch off is worse than a knob that does nothing.

## The fix — additive, in the one place the effective set is computed

`src/hrmosaic/agent/router.py::allowed_tools` now does
`blocked = set(disabled) | set(settings.mcp_tools_disabled_list)`. That function is the single
chokepoint: `offered()` (which builds the tool array for every model call, orchestrator:1583) and
`_permitted()` (which `_nudge` consults, orchestrator:2120) both go through it, so there is one union
and no second place to keep in step. A request can withhold **more** tools and never fewer.

§13.9's ablation arms only ever add (`no_structured_tools` names five tools; `baseline` and
`dense_only_k2` name none), so their behaviour is unchanged — on eval runs `MCP_TOOLS_DISABLED` is
empty and the union is the request's own list exactly.

**Two round-1 changes are reverted**, because their justification was the default and the default is
gone:

* `ChatOptions.tools_disabled` is `Field(default_factory=list)` again — the request's own list, and
  nothing else.
* `privileged_options_used` tests the value again (no `model_fields_set`). No field carries a
  non-empty default now, so an absent field and an unstated one are the same thing. Round 1's
  negative test (`test_a_stated_tools_disabled_is_privileged_in_the_employee_persona`) is untouched
  and still passes: a stated non-empty list is privileged under either form of the check.

I chose to revert rather than keep the narrowing as a latent improvement: leaving it would have left
a docstring explaining a default that no longer exists.

## Wording

* `.env.example:67` — `comma-separated tool names withheld on every turn; a request may add, never remove`.
* `src/hrmosaic/settings.py` — the field comment says the same, and says why it is not a default.
* The §12.3 table row in the design spec — "Tool names this process withholds on every turn … **Unioned**
  with the per-request `options.tools_disabled` … an empty `options.tools_disabled` is unprivileged,
  so a default a request could state its way past would be a hole rather than a knob".

## The `demo_prompt.py` minor, and one thing it turned up

The coordinator asked for `ValueError` back in `main`'s except tuple; it is back. But the case it was
about was worse than a traceback in the version I shipped: `urlopen` reports a scheme-less URL as
`URLError("unknown url type")`, which is not a `ValueError` at all and which my retry loop therefore
sat on for the **whole 120 s budget** before printing a message that read like an instance that would
not answer. Measured: `python3 scripts/demo_prompt.py --base-url "127.0.0.1:8000" --key demo_1` took
120 s. So `read_prompt` checks the scheme once, up front, and raises `Refused` for anything that is
not `http`/`https`. Re-measured: **0.08 s**, exit 1, `'127.0.0.1:8000' is not an http(s) URL`.

## Tests added (3; suite 3,389 → 3,392)

* `tests/unit/test_mcp_tools_disabled_default.py` — rewritten for the union (6 tests, was 5): the
  filter applies to a request that asks for nothing; **a stated `[]` cannot switch it off** (the test
  the coordinator asked for); a request adds to it; an unset variable withholds nothing of its own;
  the request field carries no default; and the parsing test is unchanged.
* `tests/contract/test_chat_privileged_options.py` — `test_no_caller_can_switch_the_process_wide_tool_filter_off`:
  employee persona, `options={"tools_disabled": []}` → **200** (it is unprivileged, as it should be)
  and `get_policy_section` is still absent from every `tools_offered`. The existing process-filter
  test was renamed to `test_the_process_wide_tool_filter_applies_to_an_ordinary_turn` and both now
  share a `_tools_offered()` helper.
* `tests/unit/test_demo_prompts_are_dated.py` — `test_a_base_url_with_no_scheme_is_reported_at_once`
  (runs on the default 120 s timeout deliberately: the guard is what makes it fast).

Non-vacuous check: with `src/hrmosaic/agent/router.py` stashed, the three union tests and the new
contract test fail (`4 failed, 3 passed`).

## Commands run

| Command | Result |
|---|---|
| `make lint` | `All checks passed!` / `318 files already formatted` |
| `.venv/bin/pytest -q tests/contract tests/unit/test_mcp_tools_disabled_default.py` | `560 passed in 177.22s (0:02:57)` |
| touched files (`test_demo_prompts_are_dated`, `test_mcp_tools_disabled_default`, `test_demo_scripts_send_the_served_prompt`, `test_chat_privileged_options`) | `423 passed in 7.60s` |
| `make test` | `3093 passed, 299 deselected in 336.25s (0:05:36)`, exit 0 |
| `.venv/bin/python -m pytest --collect-only -q -m ""` | `3392 tests collected` |
| `make demo1` / `make demo2` | exit 0 / exit 0, both `-- outcome: answered`, `MOCK-HR-000082` in the lede |
| `python3 scripts/demo_prompt.py --base-url "127.0.0.1:8000" --key demo_1` | exit 1 in 0.08 s with the reason |

The full `make test` was run this round (not only `tests/contract`), because `router.py` is on every
turn's path and the ablation arms read it.
