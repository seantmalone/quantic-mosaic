# Task 13 — G5b final fix wave (round 2)

**Status:** complete. One commit on `main`. Nothing under `src/`, `mcp/`, `corpus/`, `data/`,
`Dockerfile`, `render.yaml` or `requirements*.txt` was touched — the provenance claim's pathspec is
still empty at HEAD, and the new contract test is what proves it.

## 1. The provenance pathspec is now executed, not asserted

**One deviation from the brief, and it is load-bearing.** The pathspec as specified —
`… mcp/run_http.sh corpus data/index/chunks.manifest.jsonl …` — is **not** empty at HEAD:

```
$ git diff --stat 80a5a71..HEAD -- src mcp/tools mcp/server_entrypoint.py mcp/run_stdio.sh \
    mcp/run_http.sh corpus data/index/chunks.manifest.jsonl Dockerfile render.yaml requirements.txt
 corpus/README.md | 20 ++++++++++++++------
 1 file changed, 14 insertions(+), 6 deletions(-)
```

`corpus/README.md` moved at `e9ee3b3` (this wave's own README pass: the fact count 58 → 60, the
`corpus_stats` line, the refresh-versus-request paragraph). Publishing a command that prints a path is
the exact self-falsifying shape the whole fix exists to end — and it is the *same* shape that
`mcp/README.md` caused in round 1. So the README is excluded by name, on the same ground: it is the
directory's map, not one of the fourteen documents the index is built from
(`NON_DOCUMENT_STEMS` in `src/hrmosaic/rag/parse/__init__.py:187` skips it by stem). The published
command is now:

```bash
git diff --stat 80a5a71..HEAD -- src mcp/tools mcp/server_entrypoint.py \
  mcp/run_stdio.sh mcp/run_http.sh corpus ':!corpus/README.md' \
  data/index/chunks.manifest.jsonl Dockerfile render.yaml requirements.txt
```

**Result at HEAD: empty, exit 0.** Verified before the commit at `97177e5` and again after it.

Widened in all five documents that print it: `README.md`, `deployed.md`,
`docs/pre-submission-checklist.md`, `docs/requirements-traceability.md`, `CHANGELOG.md`. Each now
also says **why `corpus` and the chunk manifest are in it**: `Dockerfile` line 41 copies the corpus
in, line 45 copies the committed manifest, line 53 builds the sqlite-vec + FTS5 index from that corpus
at *build* time behind `ingest --verify-manifest`. They are compiled into the artifact, so a policy
edit or a re-chunk changes the answers the deployed service gives exactly as a code change does —
round 2's own equipment repair moved the live index 204 → 205 chunks, which the old pathspec would
have called no change at all.

**The contract test** is one function in `tests/contract/test_published_run_commands.py`:
`test_the_application_tree_has_not_moved_since_the_measured_build`. It reads `run_id` from
`evaluation/results/latest.json`, opens that run file, takes its own `target_git_sha` (`80a5a71` —
never a sha typed into a document), and runs `git diff --quiet <sha> HEAD -- <APPLICATION_PATHSPEC>`,
failing with the changed paths named. The pathspec is a module constant, and the same test asserts all
five documents print the line derived from it — so the command a reader copies cannot drift from the
command the suite runs.

**No `ci.yml` depth change was needed.** The `test` job already checks out at `fetch-depth: 0` (added
so the `ai-tooling.md` commit-census guard could not skip itself green), as does `lint`. The skip is
still implemented and still *earned*: a checkout that cannot resolve the base sha must prove it could
not hold it (no git, or `--is-shallow-repository` true) or the test fails rather than skips.

## 2. stdio "Where used" cell

`design-and-evaluation.md`'s transport table no longer claims the demo video as the stdio
demonstration. It now matches `mcp/README.md:33`: local dev (`make run-stdio`, MCP Inspector) and the
fast CI discovery test — a visibly separate OS process, demonstrated by `make run-stdio`, with the
recording driven entirely against the deployed URL and therefore carrying no stdio beat.

## 3. Two disclosures, written twice each (in section and in Known limitations)

**(a) `unmet:` guards cannot tell "checked and failed" from "could not check"** — under *The nine
tools*, and Known limitations item 13. Verified by running the engine, not by reading it:
`check_policy_compliance(scenario="equipment_request", parameters={"request_type": "refresh"})` with no
`device_age_months` returns `verdict: insufficient_evidence` and `unmet: []` (both right) and still
attaches the **early**-refresh direct-manager approval and its next step. Mechanism:
`decided[id] = decision.met` (`rules.py:783`), a `not_stated` row is `met: False` (`rules.py:636`),
`unmet:<id>` is `not decided[id]` (`rules.py:533`); the published `unmet[]` is careful and the guard
vocabulary is not (`rules.py:832`). The tool's `parameters` description
(`mcp/tools/check_policy_compliance.schema.json:50`) names `request_type` and its three values and
never names `device_age_months`. The class pre-exists on `equipment.director_threshold`: verified
`request_type: "new"` with no `amount_usd` attaches Director + the off-catalogue next step the same
way (`corpus/rules.yml:438`, `:443`). Bounded and deferred: verdict correct, blocking `not_stated`
still refuses a write, `agent/compliance.py` says the row was unchecked in its own line, and no item
of the published run reaches it (`equipment-001` has `check_policy_compliance` as an allowed *extra*
and its served answer names no approval). The fix touches `corpus/rules.yml`, `src/` and a published
schema — all inside the frozen pathspec.

**(b) the bare-balance rule keys on twelve words** — under *Clarification*, and Known limitations item
14. The docstring's *"a question that names its balance … is never forced to clarify"*
(`orchestrator.py:453–454`) overstates a substring test against `NAMED_BALANCE_WORDS`
(`orchestrator.py:418–434`). Verified live: `is_bare_balance_ask` returns **True** for *"How many days
off do I have left?"*, *"what's my holidays balance?"* and *"how much is left in my flexible spending
account?"* (the last being the account `fsa` was added for, spelled out), and **False** for *"What is
my PTO balance?"* and *"how much is left in my FSA?"*. Cost: one extra turn. No tool call, no write
reachable, no dataset item affected, `clarification_accuracy` still 1.000 (n = 3).

## 4. "280 commits"

Attributed to the history it belongs to in all four places — `README.md`, `ai-tooling.md`,
`.github/workflows/ci.yml` (the comment) and `docs/demo-script.md` (not in the brief, same claim).
`git rev-list --count --no-merges 2dee277` = **280**; at HEAD it is 293, so each place now names
`2dee277` and says the number on a later run will be larger.

## 5. Checklist warm-up line

`docs/pre-submission-checklist.md` gains a box: read `/health.llm.agent.calls_today` against
`llm.agent.daily_call_cap` (1,500 shipped) before the take. Counted from `llm_call` spans since 00:00
UTC and resets there; the five modelled `degradations[]` (`api.py:2079–2099`) have no value for an
exhausted cap, so `/health` reads `status: ok` with an empty `degradations[]` while the next turn ends
`error` / `daily_cap_reached`.

## 6. Label packets promoted to evidence

`docs/evidence/label-packet-seed-2026-09-22.md` and `label-packet-hard-2026-09-22.md`, copied
unedited from `.superpowers/sdd/2026-09-21-grade-5/packet-{seed,hard}-g5b.md`. Secret-scanned clean:
zero hits for the README `?access=` token value, `?access=`, `sk-ant`, `sk-proj`, `AIza`, `eyJ…`,
`ghp_`, `xox*`. (A loose `sk-` grep hits only *"full-di**sk-**encrypted"*.) Both indexed in
`docs/evidence/README.md` with a *Why the packets are here* note — they are evidence of **what was
withheld**, which is the one §13.7 claim the outputs cannot show — and the design document's blinding
paragraph now links both.

## 7. G1 row, minor 2

The G1 guardrail row now says that at the shipped defaults both clauses see a set already floored at
`MIN_SUPPORT_SCORE`: `search_policy_documents` applies it itself when `min_dense_score` is omitted
(`search_policy_documents.py:205`) and the agent always omits it, so clause 2 reduces to *fewer than
two candidates at all* — a second line of defence, not an independent threshold. It becomes one only
if a call supplies a lower `min_dense_score`, which is a published parameter.

## Suite figure

`pytest --collect-only -q -m ""` reports **3,439** (was 3,438 — the one new contract test); `-m ux` is
**299**, so `make test` collects **3,140**. Bumped in `README.md`, `ai-tooling.md`,
`design-and-evaluation.md`, `docs/requirements-traceability.md` and `docs/demo-script.md`'s pair, plus
the `CHANGELOG.md` entry this wave is still writing. `docs/optimization-log.md` keeps 3,139 — it is a
dated record and is excluded from the guard's `NUMBER_DOCS` for that reason.

## Verification

* `.venv/bin/python scripts/paste_eval_numbers.py --check` → `OK — the results table matches evaluation/results/latest.json`
* `make lint` → ruff check clean, 321 files already formatted
* `.venv/bin/pytest -q -p no:cacheprovider tests/contract` → **559 passed in 151.78s**, one process
* the new pathspec at HEAD → empty, exit 0
