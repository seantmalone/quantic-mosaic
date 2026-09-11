# P20 report — coverage gate in CI, tests for the least-covered modules, proxy headers behind Render's edge

**Branch:** `main` · **base** `d455646` · **head** `6e2e1ff` · three commits, never pushed.
**Result:** overall coverage 92% → **94%** (1,844 → **1,901** tests, all green, output pristine).
Every module the brief named, and every other module the report listed under 85%, is now at or
above 92%.

---

## 1. What was built

### Item 1 — tooling (`53ff770`)

* `coverage==7.10.7` added to `pyproject.toml`'s `[dependency-groups] dev`, beside `pytest`,
  `ruff` and `fpdf2`, and compiled into `requirements-dev.txt` with the file's own recorded
  command, `uv pip compile --group pyproject.toml:dev -o requirements-dev.txt`. That is how the
  repo pins test tools; the Docker image installs `requirements.txt` alone, so
  `test_requirements_dev_never_enters_the_image` stays true and coverage never enters the
  container.
* `make coverage` (and `COVERAGE_MIN ?= 90`, so the floor is one place):

  ```make
  coverage:
  	$(BIN)/coverage run --branch --source=src/hrmosaic -m pytest -q
  	$(BIN)/coverage xml
  	$(BIN)/coverage report --fail-under=$(COVERAGE_MIN)
  ```

* `.gitignore` gains `.coverage` and `coverage.xml` (verified with `git check-ignore -v`).

### Item 2 — CI (`53ff770`)

`.github/workflows/ci.yml`'s `test` job runs those same three lines in place of the bare
`pytest -q`, keeping `LLM_PROVIDER: stub` and every existing step (`check_facts.py`,
`ingest --verify-manifest`, `pii_check.py`) exactly where it was:

```yaml
      - run: coverage run --branch --source=src/hrmosaic -m pytest -q
      - run: coverage xml
      - name: The coverage table, then the gate    # `coverage report` prints the per-module table
        run: coverage report --fail-under=90
      - run: python scripts/pii_check.py
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: coverage-xml, path: coverage.xml }
```

No third-party coverage service, no badge, no new secret — §15.2's claim that nothing CI holds is
a credential is unchanged, and `test_no_model_key_and_no_access_token_is_a_ci_secret` still passes.

### Item 3 — tests for the least-covered modules (`6e2e1ff`)

| module | before | after | what had no test |
|---|---|---|---|
| `rag/index.py` | 76% | **100%** | the whole `--selftest` (a `Dockerfile` RUN line), `main()`, `cosine`'s zero-norm guard |
| `mcpserver/rules.py` | 89% | **100%** | every refusal in the closed grammar, and the two "Not stated" paths |
| `web/sse.py` | 86% | **100%** | queue-full drop, heartbeat, shutdown, unbound/closed/dying loop, deadline |
| `core/llm/stub.py` | 83% | **100%** | every `load_script` validation message, and `reset()` |
| `core/procstat.py` | 80% | **100%** | the RSS reader for whichever platform you are not running on |
| `mcpserver/stdio_main.py` | 0% | **100%** | never imported in-process; only ever run as a subprocess |
| `rag/download_model.py` | 0% | **92%** | the retry policy and `threads=1` on the construction |

New files: `tests/unit/test_index_selftest.py` (8 tests), `tests/unit/test_stub_script_validation.py`
(11), `tests/unit/test_procstat_readings.py` (5), `tests/unit/test_stdio_entrypoint.py` (4),
`tests/unit/test_download_model.py` (3). Extended: `tests/unit/test_rules_engine.py`
(+21, a "closed vocabulary, at the edges" section), `tests/integration/test_sse.py` (+9, a
"broker's own promises" section), `tests/contract/test_deploy_manifests.py` (+1, item 6).

None of them exists to touch a line. Each drives a path the shipped code takes only when something
has gone wrong — which is precisely the half a green suite cannot reach by running normally:

* the self-test's three red paths (wrong top-1 document, an index that built empty, a
  `chunk_count` that has drifted from the committed manifest) beside its green path against the
  real committed index;
* the rule engine's refusals, driven through a one-requirement scenario built by the test, because
  `corpus/rules.yml` is well-formed and nothing in it can reach a `RuleError`;
* the SSE broker's three promises to the *turn* — never block, never raise, always let go;
* every `StubScriptError` message, because a malformed script is a red suite or a dead demo on
  camera, not a fixture problem;
* both `procstat` unit conversions, since `ru_maxrss` is kilobytes on Linux and **bytes** on macOS
  and neither machine ever executes the other's branch;
* stdio logging pinned to stderr (stdout is the JSON-RPC framing) and the transport `main()` serves;
* `download_model`'s retry policy and its `threads=1`.

### Item 4 — documentation (`6e2e1ff`)

* `README.md` — `make coverage` in the `## Local Run` block, plus a **Tests and coverage**
  paragraph with the measured figure (95% of statements / 87% of branches over 7,110 statements,
  94% combined), the gate, and how to run it. The CI/CD paragraph now names the 90% gate.
* `design-and-evaluation.md` — the `test` row of the CI/CD table describes the coverage run and the
  gate; one added paragraph ("The coverage gate is the same command locally and in CI") carries
  the figure and the no-third-party-service point.
* `docs/requirements-traceability.md` — R8.2's evidence cell (the testing row) cites the gate, the
  measured figures, the artifact, and that no coverage service is in the path.
* `ai-tooling.md` and `design-and-evaluation.md` — the published test count moves 1,844 → **1,901**
  (P19's last commit existed to keep that number true; it would otherwise be wrong again).

### Item 5 — concurrency note (time-boxed, ~20 min)

**No shared mutable path was found; nothing was changed.** What was checked:

* **`data/runtime/…`** — `tests/conftest.py` gives every store-backed test its own migrated
  `SqliteStore` under `tmp_path`. Verified empirically rather than by reading: the mtime of
  `data/runtime/traces.sqlite` is **unchanged** after separate `pytest -q tests/unit`,
  `tests/contract`, `tests/integration` and `tests/e2e` runs. Nothing in the suite falls through
  to `settings.trace_db_path`.
* **fixed temp files** — every `write_text` / `mkdir` in `tests/` is under `tmp_path` or
  `tmp_path_factory`; `git status` is clean of new artifacts after a full run.
* **fixed ports** — every server takes `tests/conftest.py::free_port()`. The `127.0.0.1:8000`
  literals in the unit suite are `RunOptions` strings that no test connects to.
* What two concurrent runs in one checkout genuinely share is the **OS port space**: `free_port()`
  closes its probe socket before uvicorn binds it, so two runs can pick the same port inside that
  window. Closing it means handing the socket to `uvicorn.Config(fd=…)` in every server fixture —
  not worth it for a suite that is not meant to run twice at once, and the observed failures are
  equally consistent with the real-clock margins P19 widened tripping on a doubly loaded machine.
  The other shared file, `data/index/hr_index.sqlite`, is read-only to the suite and rewritten in
  place by `ingest --verify-manifest`; that is the documented sequencing constraint, not a
  per-test fix.

### Item 6 — proxy headers behind Render's edge (`64efbbd`)

`Dockerfile` CMD now ends `--workers 1 --proxy-headers --forwarded-allow-ips='*'`, with a comment
beside it naming the two headers and why `'*'` is the only usable value (Render does not publish
its edge addresses and they change). `ACCESS_RATE_LIMIT_PER_MIN` untouched.

P19's cookie-`Secure` fix does **not** regress and is **not** made redundant: `request_is_https()`
still reads `X-Forwarded-Proto` itself, because `make run`, `make demo1` and every test server pass
no proxy flags at all. With the middleware on, the two agree — it rewrites the scope and strips no
header. Its docstring said the edge "is not" a trusted peer, which stops being true inside the
image, so it now says which run modes carry the flags and which do not.

`deployed.md`'s rate-limit sentence goes back to per-client keying. `design-and-evaluation.md`
(line 635) and `docs/architecture.html` already said "per IP" and carried no shared-bucket wording,
so neither needed an edit — confirmed by grep.

---

## 2. Definition-of-done commands, with real output

### `ruff check .` and `ruff format --check .`

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
242 files already formatted
```

### `make coverage` — the gate, and the table

```
$ LLM_PROVIDER=stub make coverage
.venv/bin/coverage run --branch --source=src/hrmosaic -m pytest -q
[...]
1901 passed in 190.43s (0:03:10)
.venv/bin/coverage xml
Wrote XML report to coverage.xml
.venv/bin/coverage report --fail-under=90
```
Name                                                      Stmts   Miss Branch BrPart  Cover
-------------------------------------------------------------------------------------------
src/hrmosaic/__init__.py                                      1      0      0      0   100%
src/hrmosaic/agent/__init__.py                                3      0      0      0   100%
src/hrmosaic/agent/answer_stream.py                         111      0     36      3    98%
src/hrmosaic/agent/client.py                                241     11     44      5    94%
src/hrmosaic/agent/guardrails/__init__.py                    12      0      2      0   100%
src/hrmosaic/agent/guardrails/g1.py                          49      0      6      0   100%
src/hrmosaic/agent/guardrails/g2.py                          89      0     34      3    98%
src/hrmosaic/agent/guardrails/g3.py                          27      0      4      0   100%
src/hrmosaic/agent/guardrails/g4.py                          46      1     18      1    97%
src/hrmosaic/agent/guardrails/g5.py                          46      3      8      1    93%
src/hrmosaic/agent/guardrails/g6.py                          13      0      0      0   100%
src/hrmosaic/agent/orchestrator.py                          686     50    190     26    91%
src/hrmosaic/agent/prompts/__init__.py                       22      0      2      0   100%
src/hrmosaic/agent/router.py                                 48      1      2      0    98%
src/hrmosaic/agent/workflows/__init__.py                     60      3      8      0    96%
src/hrmosaic/agent/workflows/pto_request.py                  13      0      0      0   100%
src/hrmosaic/agent/workflows/remote_work.py                  13      0      0      0   100%
src/hrmosaic/core/__init__.py                                 0      0      0      0   100%
src/hrmosaic/core/archive.py                                 76      4     10      0    95%
src/hrmosaic/core/canonical.py                                8      0      0      0   100%
src/hrmosaic/core/corpusread.py                              92      4      6      1    93%
src/hrmosaic/core/db.py                                     196     12     54     10    91%
src/hrmosaic/core/ids.py                                     14      1      2      1    88%
src/hrmosaic/core/injection.py                               10      0      4      0   100%
src/hrmosaic/core/llm/__init__.py                            42      4     14      4    86%
src/hrmosaic/core/llm/anthropic.py                          121     10     46      2    90%
src/hrmosaic/core/llm/base.py                               220      7     34      4    96%
src/hrmosaic/core/llm/cache.py                               40      0      4      0   100%
src/hrmosaic/core/llm/limiter.py                             94      0     12      0   100%
src/hrmosaic/core/llm/openai_compat.py                      103      6     24      5    91%
src/hrmosaic/core/llm/stub.py                                58      0     20      0   100%
src/hrmosaic/core/models.py                                 246      0     24      0   100%
src/hrmosaic/core/procstat.py                                36      0      4      0   100%
src/hrmosaic/core/redact.py                                  34      0     14      0   100%
src/hrmosaic/core/retention.py                               26      0      2      0   100%
src/hrmosaic/core/trace.py                                  424     21     86     14    93%
src/hrmosaic/mcpserver/__init__.py                            2      0      0      0   100%
src/hrmosaic/mcpserver/asgi.py                               24      0      0      0   100%
src/hrmosaic/mcpserver/confirm.py                            63      2     16      2    95%
src/hrmosaic/mcpserver/rules.py                             261      0    112      0   100%
src/hrmosaic/mcpserver/server.py                            105      6      8      0    93%
src/hrmosaic/mcpserver/stdio_main.py                         16      0      2      0   100%
src/hrmosaic/mcpserver/tools/__init__.py                      4      0      0      0   100%
src/hrmosaic/mcpserver/tools/check_policy_compliance.py      86      0      6      0   100%
src/hrmosaic/mcpserver/tools/check_pto_balance.py            58      1      4      1    97%
src/hrmosaic/mcpserver/tools/create_mock_hr_ticket.py        50      0      0      0   100%
src/hrmosaic/mcpserver/tools/draft_hr_email.py               68      1      2      1    97%
src/hrmosaic/mcpserver/tools/get_policy_section.py           78      1     16      1    98%
src/hrmosaic/mcpserver/tools/list_policy_documents.py        43      0      0      0   100%
src/hrmosaic/mcpserver/tools/lookup_benefits_status.py       56      1      2      1    97%
src/hrmosaic/mcpserver/tools/lookup_employee_profile.py      63      1      4      1    97%
src/hrmosaic/mcpserver/tools/search_policy_documents.py     119      1     20      1    99%
src/hrmosaic/rag/__init__.py                                  0      0      0      0   100%
src/hrmosaic/rag/chunk.py                                    91      0     24      2    98%
src/hrmosaic/rag/download_model.py                           21      1      4      1    92%
src/hrmosaic/rag/embed.py                                    52      0     10      0   100%
src/hrmosaic/rag/index.py                                   161      0     46      0   100%
src/hrmosaic/rag/ingest.py                                   80      2     18      4    94%
src/hrmosaic/rag/parse/__init__.py                          108      1     28      3    97%
src/hrmosaic/rag/parse/html.py                               12      0      0      0   100%
src/hrmosaic/rag/parse/md.py                                 21      0      6      0   100%
src/hrmosaic/rag/parse/pdf.py                                39      0     12      0   100%
src/hrmosaic/rag/parse/txt.py                                29      0     10      0   100%
src/hrmosaic/rag/retrieve.py                                 86      2     10      2    96%
src/hrmosaic/settings.py                                    105      4     16      5    93%
src/hrmosaic/web/__init__.py                                  0      0      0      0   100%
src/hrmosaic/web/api.py                                     506     32    128     13    93%
src/hrmosaic/web/dashboard.py                              1076    109    156     47    87%
src/hrmosaic/web/main.py                                    155     12     12      1    92%
src/hrmosaic/web/narration.py                                35      2     14      0    96%
src/hrmosaic/web/sse.py                                     117      0     28      0   100%
-------------------------------------------------------------------------------------------
TOTAL                                                      7110    317   1428    166    94%
```

`coverage json` on the same data: `covered_lines 6793 / num_statements 7110` (**95.5% lines**),
`covered_branches 1246 / num_branches 1428` (**87.3% branches**), `percent_covered 94.16`.
Exit status 0 — the gate passed.

### `pytest -q` — pristine

```
$ LLM_PROVIDER=stub ./.venv/bin/pytest -q
[...]
1901 passed in 162.58s (0:02:42)
```

No warnings, no skips, no xfails; `filterwarnings = ["error"]` and
`addopts = "--strict-markers --strict-config"` are untouched.

### `check_facts.py`, `pii_check.py`, `--verify-manifest` — unchanged

```
$ ./.venv/bin/python scripts/check_facts.py
  tax-and-location-addendum          md     12 sections
  travel-policy                      md     12 sections
  workplace-conduct                  pdf    13 sections

14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ ./.venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers

$ ./.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  md          11     153    23276
  html         1      17     2515
  pdf          1      15     2425
  txt          1      19     2624
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
```

### The CI YAML validates, and the workflow contract tests pass

```
$ ./.venv/bin/python -c "import yaml;yaml.safe_load(open('.github/workflows/ci.yml'))"
ci.yml parses

$ ./.venv/bin/pytest -q tests/contract/test_deploy_manifests.py
...............................                                          [100%]
31 passed in 0.60s
```

Jobs read back from the parsed YAML: `['lint', 'test', 'docker', 'deploy']`; the `test` job's
steps: checkout → setup-python → `pip install -r requirements.txt -r requirements-dev.txt` →
`pip install -e .` → cache → `download_model` → `check_facts.py` → `ingest --verify-manifest` →
`coverage run …` → `coverage xml` → `coverage report --fail-under=90` → `pii_check.py` →
`upload-artifact`.

### `git check-ignore`

```
$ git check-ignore -v coverage.xml .coverage
.gitignore:35:coverage.xml	coverage.xml
.gitignore:34:.coverage	.coverage
```

---

## 3. TDD evidence

Item 6 is the one place in this wave where a test could fail before the change, and it did. The
test was written, the `Dockerfile` at `d455646` was restored under it, and the failure was
observed:

```
$ git show HEAD:Dockerfile > Dockerfile
$ ./.venv/bin/pytest -q tests/contract/test_deploy_manifests.py -k forwarded
        command = next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD "))
>       assert "--proxy-headers" in command
E       assert '--proxy-headers' in 'CMD ["sh", "-c", "uvicorn hrmosaic.web.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]'

tests/contract/test_deploy_manifests.py:87: AssertionError
FAILED tests/contract/test_deploy_manifests.py::test_the_command_trusts_the_edge_s_forwarded_headers
1 failed, 30 deselected in 0.66s

$ # Dockerfile restored with the two flags
$ ./.venv/bin/pytest -q tests/contract/test_deploy_manifests.py -k forwarded
1 passed, 30 deselected in 0.53s
```

Items 1–5 add tests for behaviour that already exists and is already correct, so there is no
failing state to observe; the honest analogue is the **measured gap before and after**, taken from
`coverage report -m` on the same command the gate runs. Before (at `d455646`):

```
src/hrmosaic/core/llm/stub.py         58   9    20   4   83%   67, 120-123, 126, 129, 132, 135
src/hrmosaic/core/procstat.py         38   5     6   2   80%   46, 52-53, 88, 92
src/hrmosaic/mcpserver/rules.py      261  26   112  16   89%   116, 133, 138-139, 198, 228, 241-248,
                                                              259, 277, 290, 296, 321, 366, 369,
                                                              372, 388-389, 419, 423
src/hrmosaic/mcpserver/stdio_main.py  16  16     2   0    0%   12-35
src/hrmosaic/rag/download_model.py    23  23     6   0    0%   8-41
src/hrmosaic/rag/index.py            163  36    48   2   76%   101, 321-353, 357-363, 367
src/hrmosaic/web/sse.py              117  12    28   8   86%   143, 156, 157->159, 159->exit, 199,
                                                              203, 206-207, 219-220, 232, 236-237, 239
```

After: `stub.py` 100%, `procstat.py` 100%, `rules.py` 100%, `stdio_main.py` 100%,
`download_model.py` 92%, `index.py` 100%, `sse.py` 100%. Each of those missing line numbers was
read, understood and turned into a named behaviour test before any of them was re-measured; the
per-module runs are in the transcript.

---

## 4. Files changed

**Tooling / CI** — `pyproject.toml`, `requirements-dev.txt`, `Makefile`, `.gitignore`,
`.github/workflows/ci.yml`.

**Deploy (item 6)** — `Dockerfile`, `src/hrmosaic/web/api.py` (one docstring),
`tests/contract/test_deploy_manifests.py` (+1 test), `deployed.md`.

**Tests** — new: `tests/unit/test_index_selftest.py`, `tests/unit/test_stub_script_validation.py`,
`tests/unit/test_procstat_readings.py`, `tests/unit/test_stdio_entrypoint.py`,
`tests/unit/test_download_model.py`. Extended: `tests/unit/test_rules_engine.py`,
`tests/integration/test_sse.py`.

**Shipping code** — `src/hrmosaic/rag/index.py`, `src/hrmosaic/rag/download_model.py`,
`src/hrmosaic/core/procstat.py`: **one comment each**, a `# pragma: no cover` with a reason on the
`if __name__ == "__main__":` guard. No executable line of shipping code changed anywhere in this
wave.

**Docs** — `README.md`, `design-and-evaluation.md`, `docs/requirements-traceability.md`,
`ai-tooling.md`, `deployed.md`. `docs/optimization-log.md` untouched, as instructed.

---

## 5. Self-review of the diff

Read back against the brief, line by line. What it turned up and what was done:

1. **The `request_is_https()` docstring became false.** It said uvicorn's middleware trusts only
   `127.0.0.1` "which the edge is not" — true at `d455646`, false in the image the same commit
   ships once the flags are added. Rewritten to say which run modes carry the flags, and why the
   header is still read directly (every non-container run mode passes none).
2. **The first draft of the `Dockerfile` comment overclaimed.** It said the flags are safe because
   "a local `docker run` binds it to 127.0.0.1" — `make docker-run-512` and the CI `docker` job
   both publish with `-p 8000:8000`, which binds `0.0.0.0`. And the first `deployed.md` draft said
   an edge "overwrites the header on every request", which I cannot verify without calling the live
   URL. Both were rewritten against something I *could* verify: uvicorn 0.52.4's
   `_TrustedHosts.get_trusted_client_address` takes `x_forwarded_for_hosts[0]` when
   `always_trust` — see the concern below.
3. **`_collect` collided with an existing helper** of the same name in `test_sse.py`, which broke
   two confirmation tests. Renamed `_read_stream`; both green.
4. **`ruff format` reflowed three of the new files** (two signatures, one docstring that opened with
   a quoted phrase). Reformatted, and the docstring reworded so the format is stable rather than
   merely appeased.
5. **The published test count would have gone stale again.** P19's final commit existed to fix
   exactly that; adding 57 tests without touching `design-and-evaluation.md:724` and
   `ai-tooling.md:174` would have reintroduced it. Both moved to 1,901, re-read off
   `pytest --collect-only -q`.
6. **YAGNI check.** `core/llm/__init__.py` (86%) and `core/ids.py` (88%) were left alone: the brief
   says "any other module under 85%", and neither is. Nothing was added beyond the six brief items.
7. **Do the tests verify behaviour?** Two use a stand-in: `test_a_loop_that_shuts_down_mid_publish…`
   (a loop that reports itself open then raises what asyncio raises — the race cannot be provoked
   with a real loop, and the assertion is that `publish` does not raise) and `test_download_model.py`
   (the constructor, so the suite does not open a second ONNX session). Both assert on observable
   outcomes — the return code, the frames, the sleeps, the kwargs — not on "was this mock called".
   `stdio_main.main()` builds the **real** server and intercepts only the blocking `run()`.
8. **Pristine output.** No new warnings; `filterwarnings = ["error"]` is untouched and would have
   caught any.

---

## 6. Ambiguities, and how they were resolved

1. **"Enforce `--fail-under=90` on line coverage"** (item 2) vs. **"`coverage report --fail-under=90`"**
   (item 1). With `--branch` in the data file, `coverage report`'s total is the *combined*
   line+branch figure (94%), not line-only (95.5%), and `--fail-under` reads that. Taking the
   simplest reading, item 1's literal command is used in both the Makefile and CI, so the two are
   the same command. The gate is therefore very slightly stricter than a line-only 90 would be.
   Both figures are published in the README so nobody has to guess which one a number is.
2. **"Print the per-package table"** (item 2). `coverage report` has no per-package grouping; its
   table is per module. That table is what the job log prints.
3. **`coverage xml` before or after the gate.** The brief lists the report first. It is written
   first here, so the artifact exists on the run that *fails* the gate — the run whose numbers
   someone actually needs. The upload step carries `if: always()` for the same reason.
4. **Three `__main__` guards got `# pragma: no cover`.** `index.py`, `download_model.py` and
   `procstat.py` each ship a `python -m` entrypoint whose last line cannot execute in-process,
   while their `main()` functions are now fully tested. `stdio_main.py` already carried exactly
   this pragma with exactly this reason, so the three follow an established convention rather than
   inventing one; each names where the line really runs. This is the one place the *measurement*
   was adjusted rather than the tests, and it is flagged here for that reason. Without it the
   figures would be `index.py` 99%, `procstat.py` 97%, `download_model.py` 91% — all still over the
   floor, so nothing depended on it; consistency did.
5. **`selftest`'s "wrong top-1" case needs a retrieval floor drop.** The hash embedder's query and
   passage vectors are near-orthogonal by construction, so at the shipped `MIN_SUPPORT_SCORE` the
   mini index returns nothing and the failure observed is "no hits" rather than "wrong document".
   The test drops the floor for its own duration and says so in its docstring; "no hits" is
   covered separately by an index that genuinely built empty.
6. **Date.** Documents are dated **2026-09-11**, matching the brief's own measurement date and
   P19's most recent entries.

---

## 7. Concerns

1. **`--forwarded-allow-ips='*'` makes the rate-limit key client-settable, not just correct.**
   This is the one thing in the wave a reviewer should look at. In uvicorn 0.52.4,
   `_TrustedHosts.get_trusted_client_address` returns `x_forwarded_for_hosts[0]` — the **first**
   entry — when `always_trust` is set (it scans in reverse for the first untrusted host only when
   a concrete trust list is configured). Render's edge appends to or sets that header; if it
   *appends*, the first entry is whatever the caller sent. So for ordinary traffic the fix is real
   — a browser sends no such header, the edge supplies the visitor's address, and the limiter keys
   per client exactly as the brief intends — while a caller who deliberately forges
   `X-Forwarded-For` can rotate buckets at will. That is a milder failure than the single shared
   bucket it replaces, nothing authorises on the value (the gate is `secrets.compare_digest`, the
   write path is the confirmation gate, every record is synthetic), and I could not verify Render's
   exact header behaviour without calling the live URL, which is forbidden here. Implemented as the
   brief specifies; the caveat is written into the `Dockerfile` comment and `deployed.md` rather
   than papered over. If the reviewer wants it airtight, the shape is
   `--forwarded-allow-ips=<Render's edge CIDR>`, which needs a value only Render can confirm.
2. **The flags are not proven end to end here.** `test_the_command_trusts_the_edge_s_forwarded_headers`
   asserts the CMD text, which is all a pytest process can reach — the same limitation every other
   assertion in `test_deploy_manifests.py` has. The CI `docker` job boots the image, so the flags
   are at least proven not to break the container's boot; nothing in this repository can prove the
   keying behaviour without a live edge.
3. **`web/dashboard.py` is the largest remaining gap** — 1,076 statements at 87%, 109 lines
   missing, which is a third of everything the project still has uncovered. It is not under 85% and
   the brief does not ask for it, so it was left alone; it is the obvious next target if anyone
   wants the overall figure past 95%.
4. **`rag/download_model.py:37` is unreachable.** `return 1` after the `for` loop can never
   execute — every path inside the loop returns. It was left in place (a type checker reading the
   function would want it) and is the module's one missing line. Removing it would be a shipping-code
   change for a coverage point, which is not what this wave is for.
5. **The gate's floor is 90 against a measured 94.** Deliberate: a floor that tracks the current
   number turns every unrelated commit into a coverage negotiation. 90 is a regression guard, and
   the README says so in as many words.
6. **The concurrency artefact is recorded, not fixed** (item 5 above). If it recurs, the first
   thing to instrument is the `free_port()` → `uvicorn` bind window, and the second is the
   real-clock margins in `test_limiter_burst` and `test_llm_span_emission`.

---

# P20 fix round 1 — the limiter key is the last forwarded hop, not the first

**Finding addressed:** *[Important] `Dockerfile:74` — `--forwarded-allow-ips='*'` sets uvicorn's
`always_trust`, so `request.client.host` is the **first** `X-Forwarded-For` entry, i.e. whatever the
caller sent. That made the `ACCESS_RATE_LIMIT_PER_MIN` bucket key client-settable — a regression on
the pre-P20 state, where a hostile caller was capped at 30/min along with everyone else.*

**Resolution:** the reviewer's second option — the one that needs no external fact. `'*'` is kept
(the scheme rewrite is what it is there for, and P19's cookie-`Secure` claim rests on it being
right), and the limiter stops taking its key from `request.client.host`. It now derives the key from
the **last** `X-Forwarded-For` entry: each proxy *appends* the address it received the request from,
so the final entry is the edge's own observation of the caller and no forged prefix can displace it.
Spec §14's per-IP denial-of-service control is therefore genuinely per-caller again, and strictly
better than the pre-P20 shared bucket rather than worse.

## 1. What changed

### `src/hrmosaic/web/api.py` — a new `rate_limit_key()`, and the gate uses it

```python
def rate_limit_key(request: Request) -> str:
    """The bucket §17's `ACCESS_RATE_LIMIT_PER_MIN` counts against — the **last** forwarded hop.
    ...
    """
    hops = [
        hop.strip() for value in request.headers.getlist("x-forwarded-for") for hop in value.split(",") if hop.strip()
    ]
    if hops:
        return hops[-1]
    return request.client.host if request.client else "unknown"
```

`AccessGateMiddleware._rate_limited` now opens `client = rate_limit_key(request)` where it opened
`client = request.client.host if request.client else "unknown"`. Nothing else in the gate moved.

Three properties worth stating, because each is a decision:

* **Local behaviour is bit-for-bit unchanged.** `make run`, `make demo1`, a bare `uvicorn` and every
  test server pass no proxy flags and receive no `X-Forwarded-For`, so `hops` is empty and the key is
  exactly `request.client.host`, as before.
* **The loopback exemption got *stricter*, not looser.** `is_own_loopback_client(request, client)` is
  now handed the same last-hop key. The app's own in-process MCP client sends no forwarded header, so
  it still keys on `127.0.0.1` and is still exempt. But an outside caller who sends
  `X-Forwarded-For: 127.0.0.1` used to be able to make `request.client.host` read `127.0.0.1` inside
  the image (uvicorn's first-entry rule); now the edge's appended entry is the last one and the
  `is_loopback()` half of the exemption fails. The nonce was always the real secret; this removes a
  way of defeating the belt while the braces held.
* **A header present but empty (`X-Forwarded-For: " , "`) falls back to the peer**, rather than
  keying every such request onto one shared `""` bucket — which would have been a second, quieter
  form of the same denial-of-service hole.

### `Dockerfile` — the comment now says why the flag is not load-bearing for the limit

The "what it buys, stated precisely" paragraph became "what `'*'` does **not** do, and why the
limiter does not rely on it": it still records uvicorn 0.52.4's first-entry rule and that
`request.client.host` is caller-settable in the container, and then says the bucket selector is never
taken from that value. The flags themselves and the CMD are unchanged, so the brief's item 6 mandate
and its contract test still hold verbatim.

### `deployed.md` — the published claim matches the code

The rate-limit bullet no longer says a forger "can still rotate buckets". It says the limit does not
rely on the flag to decide whose bucket it is, names `rate_limit_key()` and the last-entry rule, and
keeps the `Secure`/`X-Forwarded-Proto` half unchanged. `design-and-evaluation.md` and
`docs/architecture.html` say "per IP", which is now true without a caveat, so neither needed an edit.

### Published counts re-measured

`README.md`, `ai-tooling.md`, `design-and-evaluation.md` and `docs/requirements-traceability.md`:
1,901 → **1,911** tests, 7,110 → **7,115** statements. The percentages (95% of statements, 87% of
branches, 94% combined) are unchanged at the published precision — re-read off `coverage json`, not
assumed.

## 2. The covering tests

**`tests/unit/test_rate_limit_key.py` (new, 8 tests)** — the function itself, over bare ASGI scopes:
the no-header fallback to the transport peer; last-hop-not-first; two different forged prefixes
collapsing to one key; two genuine visitors keeping two keys; a chain split across repeated header
lines; whitespace and empty entries; an all-empty header falling back to the peer; and a scope with
no `client` at all.

**`tests/contract/test_access_gate.py` (+2 tests)** — the live app, behind a uvicorn configured
exactly as the image configures it. This is the part that needed care: the `web` fixture's uvicorn
uses the *default* trust list, under which `_TrustedHosts.get_trusted_client_address` scans the chain
in **reverse** and lands on the last untrusted hop by itself — so a test on the default configuration
passes no matter what the limiter keys on. The tests therefore set `FORWARDED_ALLOW_IPS=*`, which is
what `uvicorn.Config` reads when no `forwarded_allow_ips=` is passed (`config.py:356`), reproducing
`always_trust` and the first-entry rule.

* `test_a_forged_forwarded_for_prefix_cannot_rotate_the_rate_limit_bucket` — limit 1, two `POST
  /chat`s with `1.1.1.1, 198.51.100.4` then `2.2.2.2, 198.51.100.4`; the second must be 429.
* `test_two_visitors_behind_the_edge_still_get_their_own_budgets` — the other half of the pair, so
  that over-correcting back to one shared bucket cannot pass: `198.51.100.4`, `198.51.100.5`,
  `198.51.100.4` → 200, 200, 429.

### Red before green

The first of those two was written against the shipped key and observed failing:

```
$ sed -i '' 's|client = rate_limit_key(request)|client = request.client.host if request.client else "unknown"|' \
      src/hrmosaic/web/api.py
$ LLM_PROVIDER=stub ./.venv/bin/pytest -q tests/contract/test_access_gate.py -k "forged_forwarded_for or two_visitors"
        first = await client.post("/chat", json=question, headers={"X-Forwarded-For": "1.1.1.1, 198.51.100.4"})
        second = await client.post("/chat", json=question, headers={"X-Forwarded-For": "2.2.2.2, 198.51.100.4"})

        assert first.status_code == 200
>       assert second.status_code == 429, "a rotated prefix is not a new client"
E       AssertionError: a rotated prefix is not a new client
E       assert 200 == 429
E        +  where 200 = <Response [200 OK]>.status_code

tests/contract/test_access_gate.py:228: AssertionError
FAILED tests/contract/test_access_gate.py::test_a_forged_forwarded_for_prefix_cannot_rotate_the_rate_limit_bucket
1 failed, 1 passed, 23 deselected in 2.42s
```

That is the finding, reproduced: under `always_trust`, rotating the prefix bought a second budget.
`test_two_visitors_…` passes in both states by design — it is the guard against the over-correction,
not the proof of the fix. With `rate_limit_key()` restored:

```
$ LLM_PROVIDER=stub ./.venv/bin/pytest -q tests/contract/test_access_gate.py -k "forged_forwarded_for or two_visitors"
2 passed, 23 deselected in 2.42s
```

An earlier draft of these two tests did **not** set `FORWARDED_ALLOW_IPS` and passed against the
*unfixed* code. That was caught by running the red state rather than assuming it, and is the reason
the env var is in the test with a comment explaining what it buys.

## 3. Definition-of-done commands, with real output

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
243 files already formatted
$ ./.venv/bin/python -c "import yaml;yaml.safe_load(open('.github/workflows/ci.yml'));print('ci.yml parses')"
ci.yml parses
```

### `make coverage` — the gate

```
$ LLM_PROVIDER=stub make coverage
.venv/bin/coverage run --branch --source=src/hrmosaic -m pytest -q
1911 passed in 191.37s (0:03:11)
.venv/bin/coverage xml
Wrote XML report to coverage.xml
.venv/bin/coverage report --fail-under=90
Name                                                      Stmts   Miss Branch BrPart  Cover
-------------------------------------------------------------------------------------------
...
src/hrmosaic/core/llm/stub.py                                58      0     20      0   100%
src/hrmosaic/mcpserver/rules.py                             261      0    112      0   100%
src/hrmosaic/mcpserver/stdio_main.py                         16      0      2      0   100%
src/hrmosaic/rag/download_model.py                           21      1      4      1    92%
src/hrmosaic/rag/index.py                                   161      0     46      0   100%
src/hrmosaic/web/api.py                                     511     32    130     13    93%
src/hrmosaic/web/dashboard.py                              1076    109    156     47    87%
src/hrmosaic/web/sse.py                                     117      0     28      0   100%
-------------------------------------------------------------------------------------------
TOTAL                                                      7115    317   1430    166    94%
```

Exit status 0. `web/api.py` went 506 → 511 statements and its miss count stayed at **32**, so all
five new statements are covered; `coverage json` confirms no line of `rate_limit_key()` is in
`missing_lines`. Totals: `covered_lines 6798 / num_statements 7115` (**95.54% lines**),
`covered_branches 1248 / num_branches 1430` (**87.27% branches**), `percent_covered 94.16` — the
overall figure did not drop.

### `pytest -q` — pristine

```
$ LLM_PROVIDER=stub ./.venv/bin/pytest -q
1911 passed in 163.91s (0:02:43)
```

No warnings, no skips, no xfails.

### The tests covering the amended code

```
$ LLM_PROVIDER=stub ./.venv/bin/pytest -q tests/contract/test_deploy_manifests.py \
      tests/contract/test_access_gate.py tests/unit/test_rate_limit_key.py \
      tests/unit/test_rate_limiter_eviction.py
69 passed in 11.30s
```

### `check_facts.py`, `pii_check.py`, `--verify-manifest` — unchanged

```
$ ./.venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.

$ ./.venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers

$ ./.venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
```

## 4. Considered and deliberately not changed

1. **`request_is_https()` still reads the *first* `X-Forwarded-Proto` entry.** The same forgery is
   available there, and its whole consequence is that the forger's own `mosaic_access` cookie ships
   without `Secure`. It is self-inflicted, it grants nothing, and P19's behaviour and its contract
   test are documented around the first entry — so it was left alone rather than swept into a fix
   about a denial-of-service control. Recorded here so the asymmetry is a decision and not an
   oversight.
2. **`--forwarded-allow-ips=<Render edge CIDR>`** remains the airtight shape and still needs a value
   only Render publishes. The fix above makes the limiter correct *without* that value, so obtaining
   it would now be a hardening step rather than a correction.
3. **`ACCESS_RATE_LIMIT_PER_MIN` is untouched** (brief item 6, explicit).
4. **The CMD line is untouched**, so the brief's mandated flags and
   `test_the_command_trusts_the_edge_s_forwarded_headers` stand exactly as written.

## 5. Remaining concerns

1. **Still not proven end to end against a live edge.** The contract tests reproduce uvicorn's
   `always_trust` configuration faithfully, which is the half this repository can reach; what Render's
   edge actually writes into `X-Forwarded-For` (append vs. overwrite) is unverifiable here without a
   live call. The fix is correct under **both** behaviours — if the edge overwrites, the chain is one
   entry and first and last coincide — which is why it needed no external fact.
2. **A deployment with no proxy in front of it gains nothing from this.** If the container port were
   ever reachable directly, a caller could forge the whole chain and the last entry would be theirs
   too. That is the same exposure the flags already assume away (`nothing but the edge can route to
   this port`), and it is stated in the Dockerfile comment.
3. `web/dashboard.py` at 87% remains the largest uncovered surface, as in the original report.
