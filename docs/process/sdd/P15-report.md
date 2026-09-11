# P15 report — performance Wave 2 (item 0, W2-A … W2-D)

Base `4a3677604233fe579245d0f5cdbaa89ba148e2dd` on `main`. Six commits, nothing pushed.
Final HEAD `2195f5ea252cb61fab659fbcfc97072e94051ed3`. Working tree clean.

| commit | subject |
|---|---|
| `c16ba27` | `P15(rag): the query memo reports its own hit, inside the call that took it` |
| `3321d23` | `P15(agent): W2-A — the act loop's closing step is one sentence, not a discarded answer` |
| `8efeea6` | `P15(agent): W2-B — synthesize output diet, the two de-risked clauses only` |
| `8835f43` | `P15(mcp): W2-C — a search hit carries the whole chunk, never a quarantined one's text` |
| `b2b895b` | `P15(agent): W2-D — input diet on the model-facing tool envelopes, one evidence definition` |
| `2195f5e` | `fix: P15(agent): drop the unused ENVELOPE_KINDS re-export from agent/prompts` (self-review) |

Every lever is its own commit, in the order the brief fixes, and the whole suite was run green at
each one: 1748 → 1752 → 1753 → 1758 → 1767 → 1767 passing (baseline on the working tree at
`4a36776` was **1746**; the brief's 1745 is the count at `20dbb79`).

---

## Item 0 — the query memo reports its own hit (`c16ba27`)

`retrieve()` derived `embed_cache_hit` by diffing `functools.lru_cache`'s **process-global** hit
counter around `embed_query`. `retrieve()` runs under `asyncio.to_thread`, so two retrievals are
genuinely concurrent threads and that diff attributes another thread's hit to this one — the flag
that is W1-B's only measurement hook would say "free" about 390 ms of real ONNX work.

- `embed.embed_query_with_meta(text) -> tuple[list[float], bool]` decides inside one lookup, under a
  module lock held across the embed itself. Holding it across the embed is deliberate twice over: it
  makes the (`hits` before, `hits` after) pair belong to this call, and two threads asking for the
  same vector then cost one ONNX run rather than two, which is what a 512 MB / 0.1 CPU box wants.
- `embed_query` is now a one-line wrapper; `query_cache_hits()` is deleted (its only caller was the
  diff, and its docstring described exactly the behaviour being removed).
- Two existing tests monkey-patched `embed.embed_query` as `retrieve()`'s seam
  (`test_min_dense_score_is_not_rrf`, `test_retrieval_filters`); both now patch the new seam. Every
  other memo test is untouched.

**TDD.** `test_the_embed_reports_its_own_hit` and
`test_two_interleaved_lookups_attribute_their_hits_correctly` were written first and failed with
`AttributeError: module 'hrmosaic.rag.embed' has no attribute 'embed_query_with_meta'`. After the
implementation I *re-introduced* the counter-diff (no lock) to prove the second test catches the
race it is named for:

```
E       AssertionError: assert {'cached': Tr...'fresh': True} == {'fresh': Fal...cached': True}
E         Differing items:
E         {'fresh': True} != {'fresh': False}
tests/unit/test_query_vector_memo.py:190: AssertionError
FAILED tests/unit/test_query_vector_memo.py::test_two_interleaved_lookups_attribute_their_hits_correctly
```

The lock restored, it passes. The test forces the interleave with an embedder that blocks inside the
slow call and a second thread taking a hit on an already-cached query while it is in flight.

---

## W2-A — the act loop's closing step (`3321d23`)

`act.j2` rule 7 only. No code.

```
-7. Stop calling tools as soon as you have what the turn needs, and say so in one line.
+7. Stop calling tools as soon as you have what the turn needs, and say so in one line: ONE
+   sentence of at most 30 words naming what you gathered — which documents, which values.
```
(one line in the file; wrapped here)

Every "Required changes applied" bullet is honoured, and the golden test asserts each of them:

- `"Stop calling tools as soon as you have what the turn needs"` is byte-for-byte unchanged, and
  what follows is **only** a format constraint.
- Nothing says a separate later step composes the answer. `test_the_closing_act_step_is_capped_to_one_short_sentence`
  asserts `"later step" not in system and "separate step" not in system`.
- No blanket "must not restate policy" — asserted as `"restate" not in system`. The sentence still
  has to name *what was gathered* ("which documents, which values"), so `_nudge`'s `continue`, the
  G1 recovery reopen and `_rehydrate_messages` still read something that says what ground is covered.
- The budget is **40** tokens, not 15 (`CLOSING_TOKEN_BUDGET`), and 30 words is what produces it.

**`test_act_closing_step_is_short`** (`tests/contract/test_act_closing_step_is_short.py`) reads every
committed stub script, classifies each zero-tool-call act entry as *terminal* (nothing follows it, or
a non-`act` purpose does) or *consumed* (another act step follows, which is exactly the shape a §9.1
reminder produces), and asserts the **terminal** median ≤ 40. A second test asserts the split is not
cosmetic — `max(consumed) > 40` — because pooling would let the budget be met by shortening messages
the loop still reads. A third drives a real turn and asserts the recorded count is the count on the
`llm_call` span, so the script and the record cannot drift.

Today: terminal = `[8, 18, 18, 18, 18, 18, 18, 19]`, median **18**; consumed carries the two P10
recordings at 372 and 284 output tokens — precisely the population the plan says not to pool with.

*TDD note.* The prompt assertion was written first and went red on the old rule 7 (output below in
"TDD evidence"). The token-budget test is a **guard** rather than a failing-first test: the recorded
fixtures already satisfy it, and no prompt edit can move a recorded token count. I proved it bites by
temporarily raising the four `four_turns` terminal entries to the deployed median of 224:

```
E       assert 121.5 <= 40
E        +  where 121.5 = <function median ...>([224, 224, 224, 224, 18, 8, ...])
FAILED tests/contract/test_act_closing_step_is_short.py::test_act_closing_step_is_short
```

**Golden.** `act.system.txt` 1,027 → 1,118 bytes, rule 7 only. The system half remains byte-stable
*across turns and employees* (`test_the_system_half_is_byte_stable_across_turns`), so the Anthropic
breakpoint still sits where it did; what moved is the cached prefix's **content**, once, deliberately
— the next deployed sweep pays one cache write for it.

**Spec.** §7.2 gains a "Two output-diet rules were added at P15" paragraph recording the rule and the
two things it must not say, with the measurements behind both.

---

## W2-B — synthesize output diet (`8efeea6`)

`synthesize.j2` rule 7 only.

```
-7. `rationale_summary` is ONE operational line of at most 200 characters. Never reasoning.
+7. `rationale_summary` is ONE operational line of at most 120 characters. Never reasoning.
+   `next_steps` is at most 3 items, each of at most 20 words.
```

- 3 items of **≤ 20 words** (not 12) and **≤ 120 chars** (not 80) — the de-risked numbers.
- Citation ordinals: **not implemented**, and `test_the_synthesis_output_is_capped_where_capping_costs_nothing`
  asserts `"ordinal" not in system.lower()` so a later round cannot add them quietly.
- `max_tokens['synthesize'] → 900`: **not implemented**; `settings` untouched.
- Rule 8 and the CITATION COVERAGE index are untouched; the test asserts both are still there.
- The 120 is a **prompt** cap. §9.7's `MAX_RATIONALE_CHARS` clamp stays 200 and the test asserts it,
  because lowering the clamp would truncate a summary the model was asked for rather than shorten it.

**TDD.** Written first, red on the old rule:

```
E       AssertionError: assert '`rationale_summary` is ONE operational line of at most 120 characters' in
        '7. `rationale_summary` is ONE operational line of at most 200 characters. Never reasoning.\n'
FAILED tests/contract/test_prompt_golden.py::test_the_synthesis_output_is_capped_where_capping_costs_nothing
```

**Golden.** `synthesize.system.txt` 1,597 → 1,659 bytes, rule 7 only. **Spec** §7.2 records both caps
and both rejections, and that the clamp did not move.

---

## W2-C — full chunk text in search results (`8835f43`)

**Server.** `SearchHit.text: str | None`, taken from the `Hit` the same `retrieve()` call already
produced (zero extra work), clamped by the new `CHUNK_MAX_CHARS = 1500`. The wire description now
states the full text, the null-on-quarantine rule, and the retargeted neighbour use of
`get_policy_section`; the committed schema was regenerated with `scripts/gen_tool_schemas.py`.

**The BLOCKING gate.** The corpus's one quarantinable chunk is 630 characters and its imperative
begins at character 355 — past `SNIPPET_CHARS`, so the old `g4.scan(snippet)` never saw it. The
§7.4 shield now runs over a search result's hits **before the `tool_call` span is written and long
before the message is appended**: `g4.quarantine_search_hits`, called from `client.call_tool` right
after `_trace` is popped. A quarantined hit is handed on as its snippet alone with
`quarantined: true`, on the copy the model reads and on the copy the record keeps.

> **Deviation from the plan's stated locus, and the one architectural judgement call in this phase.**
> The plan puts this in `_search` (`mcpserver/tools/search_policy_documents.py`). I did not, because
> spec §4.2 — authoritative, and the constraints file repeats it — says the six packages' dependencies
> run **strictly downward**, `mcpserver/ → rag/ → core/`. G4 lives in `agent/guardrails/`, so scanning
> inside `_search` means `mcpserver` importing `hrmosaic.agent`; measured, that import pulls the whole
> agent stack into the stdio server process (2,867 modules, ~1.0 s, `anthropic`, `openai`, `uvicorn`
> and the MCP *client* among them) on a 512 MB / 0.1 CPU box. The alternatives were a new `core/`
> module (the constraints forbid inventing components) or folding an injection-pattern table into
> `core/redact.py`, which is G6.
> What the agent-side placement delivers is the guarantee the plan's bullet is actually about — the
> imperative never reaches the act conversation, the `tool_call` span, the synthesis prompt or the
> dashboard — plus a shield that holds against **any** MCP server the client is pointed at, rather
> than one that trusts a server to police its own output. What it does not deliver is the literal
> "never on the wire": the loopback/stdio hop between our own client and our own server carries the
> chunk text. If the reviewer wants the literal reading, the change is ~5 lines in `_search` plus a
> §4.2 amendment, and `g4.quarantine_search_hits` is already the pure function to call.

**Rule 6 retargeted, not removed:**

```
-6. … call `search_policy_documents` (and `get_policy_section` for exact wording) before you conclude. …
+6. … call `search_policy_documents` before you conclude. Each hit already carries the chunk's full
+   text, so never call `get_policy_section` for a chunk you have — use it only for the sections
+   AROUND a hit (`include_neighbors`) or for a section no search returned. …
```

- **Do not render the full text twice** — `_envelope_text` stripped `text` out of the search envelope
  before the synthesis prompt rendered it. (W2-D then drops that envelope entirely and the helper is
  deleted; each commit is independently correct, which is what the one-commit-per-lever rule asks for.)
- **Cap the injected text** — `CHUNK_MAX_CHARS = 1500`, chosen just above the longest committed chunk
  (1,384) so it truncates **nothing** today and is a bound on a future corpus rather than a live edit
  to policy text; at the schema's `k = 10` ceiling it caps one search at 15,000 characters. The test
  asserts both halves: every emitted `text` is within the clamp, and the clamp is above the corpus
  maximum. I took the `CHUNK_MAX_CHARS` option rather than top-N because truncating hits 4–5 to
  snippet-only would spend the document breadth the plan protects elsewhere.
- **The `remote-004` dataset edit** — not done; `evaluation/dataset.yaml` untouched.
- **Contracts declared** — spec §13.3 and the `ENVELOPE_KINDS` docstring both restate why the search
  envelope stays out of `_evidence_of` now that "display snippets of chunks already present in full"
  is false; the committed schema and the tool description changed.

**Tests** (`tests/integration/test_search_returns_full_chunk_text.py`, five):
`test_search_hit_omits_text_for_quarantined_chunk` (the wave's highest-severity gate),
`test_no_act_message_contains_unbannered_g4_pattern` (over `llm_messages`; "unbannered" is made
concrete — no act message trips `g4.scan` at all, while the synthesis prompt's copy must appear
inside a `quarantined="true"` `<document>`), plus the clean-hit shape, the clamp, and the single-copy
invariant. All five drive the real loop against the real MCP server over stdio.

**TDD.** Written first; collection failed on `ImportError: cannot import name 'CHUNK_MAX_CHARS'`. With
the server change in and the shield stubbed to a no-op, the gate fails with exactly its own message:

```
E   AssertionError: tool message trips ignore_previous_instructions: {"hits": [{"chunk_id":
    "c_a00f876a1342b84f", "doc_id": "security-acceptable-use", … 
E   assert ('ignore_previous_instructions', 'IGNORE ALL PREVIOUS INSTRUCTIONS') is None
FAILED …::test_no_act_message_contains_unbannered_g4_pattern
```

**Golden.** `act.system.txt` 1,118 → 1,280 bytes, rule 6 only.

---

## W2-D — input diet on the model-facing envelopes (`b2b895b`, `2195f5e`)

**(1) `ToolResult.prompt_text` alongside `text`.** A property over `prompt_body(tool_name, body)`,
so no constructor changed and no existing construction site broke. For `search_policy_documents` it
drops the ten result-level telemetry keys (`query_used`, `k_effective`, `k_source`, `strategy`,
`total_candidates`, `embed_ms`, `search_ms`, `index_version`, `topic_backfilled`, `backfill_reason`)
and six ranking/offset keys per hit (`rank`, `dense_score`, `bm25_rank`, `rrf_score`, `char_start`,
`char_end`). For every other tool `prompt_text == text`. The act conversation and the one repair
round trip are appended from `prompt_text`; `text` is untouched, so the §11.1 span, G4 and the eval
scorers still read the whole body.

**(2) EMPLOYEE CONTEXT filter.** `ENVELOPE_KINDS` moved to `src/hrmosaic/core/models.py` and
`evaluation/runner.py` re-exports it (`ENVELOPE_KINDS = _ENVELOPE_KINDS`), so §13.3's definition is
one object with two readers. `test_envelope_partition_is_one_definition` asserts `scored is shared`
and that the set the prompt renders agrees.

**(3)** The act-history digest stays dropped. Nothing in the diff touches act history.

**Golden fixture** extended with a `get_policy_section` and a `check_policy_compliance` envelope, for
the reason the plan gives: `check_pto_balance` alone survives every filter ever proposed, so a suite
pinning it alone would have stayed green while the other two vanished.
`synthesize.user.txt` 2,991 → 3,793 bytes, the two added envelopes only.

**Spec** §7.2 records `prompt_text`, the key lists, the `quarantined` exception and the render filter;
§13.3 and the `ENVELOPE_KINDS` docstring are restated again now that the envelope is not rendered.

---

## Ambiguities resolved (and how)

1. **Where the quarantine gate lives.** See the boxed note under W2-C: agent-side, because
   `mcpserver → agent` inverts §4.2's strictly-downward dependencies. Flagged as the reviewer's call.
2. **"the 7 per-hit score/offset keys."** `SearchHit` has exactly seven non-identity keys — `rank`,
   `dense_score`, `bm25_rank`, `rrf_score`, `char_start`, `char_end` and `quarantined` — which is
   where the plan's "7" comes from (it was counted when `quarantined` was always `false` on the wire).
   W2-C makes `quarantined` load-bearing, so `prompt_body` drops six unconditionally and drops
   `quarantined` **only when false**; a `true` one is §7.4's banner telling the model the passage may
   not be cited, and trading a guardrail for six bytes is the mistake this lever must not make. A
   normal hit therefore loses seven keys, exactly as the plan says.
3. **"filter by the complement of `ENVELOPE_KINDS` — drop only search and list."** Those two clauses
   contradict each other: the complement of `ENVELOPE_KINDS` over the catalog is **four** tools, and
   the other two are `create_mock_hr_ticket` / `draft_hr_email`, whose envelope on the resumed half of
   a confirmed write is where the answer gets the ticket id it reports. The emphasised clause wins.
   The render therefore filters on `core/models.py::UNRENDERED_ENVELOPES` — a denylist of exactly the
   two named tools, declared beside `ENVELOPE_KINDS` in the same module so both readers still come
   from one place — and the contract test pins all three sets apart, including that the only rendered
   envelope the judge does not score is a write result.
4. **`topic_backfilled` is one of the ten dropped keys**, and `TOPIC_DESCRIPTION` told the model to
   "see topic_backfilled". A description naming a field the model cannot see is a lie on the wire, so
   that parenthetical is gone and the schema was regenerated. The widening is still on the `retrieval`
   span, where an audit reads it.
5. **`CHUNK_MAX_CHARS = 1500`** — the plan gives a choice ("top-N hits, or a `CHUNK_MAX_CHARS` clamp")
   and no number. Reasoning under W2-C.
6. **`test_act_closing_step_is_short` measured over recorded stub scripts**, not over a live sweep:
   the brief says "use recorded fixtures / stub scripts", `StubAdapter` replays `completion_tokens`
   verbatim onto the span, and the third test in that file ties the two together on a real turn.

## Self-review findings (fixed)

- **YAGNI** — `agent/prompts/__init__.py` imported `ENVELOPE_KINDS` only to re-export it, and nothing
  read it there. Removed in `2195f5e`.
- **Wrong assertion** — the first draft of `test_the_partition_drops_exactly_the_two_tools…` asserted
  `set(TOOL_NAMES) - set(ENVELOPE_KINDS) == {search, list}`. It went red, which is what surfaced
  ambiguity 3 above and the write-tool regression that the naive complement filter would have shipped.
- **Fragile source** — the W2-C tests first read the hits out of the span's `result_json`. §10.5 caps
  every payload **string** at 8 KB and a k=5 search carrying whole chunks serialises to ~8.3 KB, so
  that string is stored truncated and `json.loads` on it raised. Switched to `structured_content`,
  which holds the same body with each individual string well under the cap. See the concerns below.
- **Line length / format** — two `ruff` findings (E501 in the closing-step test, a blank-line change
  after deleting `_envelope_text`), both fixed before the commit that carried them.
- **Test-output hygiene** — the interleaving test raised `PytestUnhandledThreadExceptionWarning` while
  red; green, it raises nothing. The final `pytest -q` output is pristine.

---

## Definition of done — real output

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
229 files already formatted

$ .venv/bin/pytest -q
........................................................................ [ 93%]
........................................................................ [ 97%]
.......................................                                  [100%]
1767 passed in 157.78s (0:02:37)

$ .venv/bin/python scripts/check_facts.py
  benefits-and-open-enrollment       html   18 sections
  equipment-and-asset                md     10 sections
  expenses-and-reimbursement         md     13 sections
  hr-escalation-and-case-handling    md      9 sections
  leave-of-absence                   md     14 sections
  manager-approval-matrix            md     13 sections
  onboarding-and-first-90-days       md     12 sections
  performance-and-compensation       md     12 sections
  pto-and-holidays                   md     18 sections
  remote-and-hybrid-work             md     18 sections
  security-acceptable-use            txt    17 sections
  tax-and-location-addendum          md     12 sections
  travel-policy                      md     12 sections
  workplace-conduct                  pdf    13 sections

14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
exit=0

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
exit=0

$ .venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  format    docs  chunks    words
  md          11     153    23276
  html         1      17     2515
  pdf          1      15     2425
  txt          1      19     2624
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)
exit=0

$ .venv/bin/python scripts/gen_tool_schemas.py && git diff --exit-code mcp/tools/
  wrote mcp/tools/check_policy_compliance.schema.json
  … (9 files)
9 tool schemas generated from a live tools/list.
SCHEMA CLEAN

$ .venv/bin/pytest -q tests/contract/test_tool_schemas_committed.py
....                                                                     [100%]
4 passed in 0.92s
```

Not run, and assigned to the main session: the deployed 26-item sweep, the judge pass, both §13.9
ablation arms, `evaluation.runner`, `evaluation.ablation`, `make eval`, `make ablation`. Nothing
under `evaluation/results/**`, `evaluation/REPORT.md` or `docs/optimization-log.md` was read for
writing, staged or committed. `.env` was never read, printed or committed.

---

## The six goldens, each diffed and explained

| file | before | after | what changed |
|---|---|---|---|
| `route.system.txt` | 2,544 | 2,544 | **nothing.** Regenerated and byte-identical; no lever touches `route.j2`. |
| `route.user.txt` | 257 | 257 | **nothing.** |
| `act.system.txt` | 1,027 | 1,280 | rule 7 (W2-A, +91) and rule 6 (W2-C, +162). Rules 1–5 byte-identical. |
| `act.user.txt` | 257 | 257 | **nothing** — persona and question only. |
| `synthesize.system.txt` | 1,597 | 1,659 | rule 7 only (W2-B, +62): 200 → 120 chars, plus the `next_steps` line. Rules 1–6b and 8–9 byte-identical. |
| `synthesize.user.txt` | 2,991 | 3,793 | two added `<tool_result>` envelopes in the fixture (W2-D, +802). The EVIDENCE block, CITATION COVERAGE and the question are byte-identical — the filter changed which envelopes render, and the three in the fixture are all on the render side of it. |

(Byte counts are the rendered halves; `wc -c` reads one more for the user files, which end in a
newline the committed system files do not.)

The regeneration was a deliberate re-review: every golden was rewritten from the live templates by a
script that preserves each file's existing trailing-newline convention, so an unchanged half shows as
*unchanged* rather than as a whitespace diff — which is what makes the three real diffs readable.

---

## Concerns for the reviewer

1. **The quarantine gate is agent-side, not in `_search`.** The boxed note under W2-C is the whole
   argument. This is the one place I chose the spec over the plan's literal wording, and it is cheap
   to reverse if the reviewer disagrees.
2. **§10.5 truncates the search `tool_call` span's `result_json`.** At the default `k = 5` a hit list
   carrying whole chunks serialises to ~8.3 KB against `MAX_STRING_BYTES = 8 KB`, so that string is
   stored with `…[truncated]` and `truncated = 1`. Nothing functional depends on it: the same body is
   on the span intact as `structured_content` (its individual strings are ~1 KB), `llm_messages` holds
   the verbatim prompt bytes and is exempt from the cap, and `_evidence_of` does not read the search
   envelope. But the plan's phrase "`text` stays whole for the §11.1 span" is now only true of
   `structured_content`, and the dashboard's tool-result drill-down will badge search results as
   truncated. At `k = 10` (~17.6 KB, reachable only through the model's own `k` or the `_meta`
   override) the 32 KB payload cap would shed the `hits` list altogether. Raising `MAX_STRING_BYTES`
   is a §10.5 change and outside this brief; flagging it rather than doing it.
3. **A search hit now ships `text` and `snippet`, and the snippet is a prefix of the text.** The plan
   says "alongside", and `snippet` is the wire contract a citation displays, so I kept both — but it
   is ~320 duplicated characters per hit, re-billed on every later act step, which is larger than
   W2-D's entire credited saving. Worth re-deriving with W2-C's cost line, which the plan already
   credits 0 pending re-derivation.
4. **`test_act_closing_step_is_short` is a guard, not a live measurement.** The recorded fixtures
   already sit at a median of 18 terminal output tokens; the deployed median of 224 can only be moved
   by the sweep. The real proof of W2-A is the next deployed run's act-output distribution, and the
   test exists to stop a future recording regressing the fixture side.
5. **Re-labelling.** `ENVELOPE_KINDS` **membership did not change** — the same five tools, moved to a
   different module — so the plan's trigger for re-authoring `evaluation/reference_labels.yaml`
   ("if `ENVELOPE_KINDS` membership changes") has not fired. What *did* change is the bytes inside a
   `retrieval` item's neighbourhood (W2-C) and the prompt (W2-A/B), so the fresh blind labels the
   brief schedules are still required; I am flagging only that the stated trigger is not the reason.
6. **The prompt caps are instructions, not enforcement.** Nothing rejects a fourth `next_step` or a
   130-character `rationale_summary`; §9.7's clamp still truncates at 200. That is deliberate (a hard
   bound is what W2-B's dropped `max_tokens` clause would have been), but the acceptance gate
   "`turns.total_tokens_out` per answered turn does not rise" is the only thing that will catch a
   model that ignores them.

---

# Fix round 1/3 — the review's three Important findings

Three commits on `main`, nothing pushed. Base `2195f5e`.

| commit | subject | finding |
|---|---|---|
| `0d69f47` | `fix: P15(mcp): W2-C's blocking gate is taken in the tool, so the wire never carries it` | 1 |
| `fc2e73f` | `fix: P15(agent): the injection shield is per message, not per search result` | 2 |
| `b7d7a91` | `fix: P15(agent): prompt_body never invents a hits key the tool did not return` | 3 |
| `699f631` | `fix: P15(mcp): §4.2's import-cost figure is the reproducible command's` | docs only |

Each is independently green; the whole suite ran at each one: 1769 → 1771 → 1773 → 1773 (from 1767
at `2195f5e`). Final HEAD `699f631`; working tree clean. `.superpowers/` is gitignored, so this
report is written but not staged, as in every earlier phase. `.env` was never read, printed or committed; nothing under `evaluation/results/**`,
`evaluation/REPORT.md` or `docs/optimization-log.md` was staged; every `git add` named files
explicitly.

---

## Finding 1 — the blocking gate now sits in `_search` (`0d69f47`)

Option (a) of the review, taken in full. Sean was not available to ratify the agent-side locus, and
(a) is the option that needs no ratification: it satisfies the plan bullet literally *and* keeps the
§4.2 argument the review found sound.

**What moved, and only what moved.** `src/hrmosaic/core/injection.py` is new and holds two things:
the §7.4 `PATTERNS` table and the pure `scan()`. Nothing with a *policy* in it went with them —
`agent/guardrails/g4.py` re-exports both names, stays the only public name for the shield, and keeps
the `guardrail` span, the quarantine decisions, `Match`, `scan_all` and `check`. The one importer of
`core.injection` outside g4 is `mcpserver/tools/search_policy_documents.py`.

The §4.2 argument the review checked and upheld is why it is `core/` rather than an
`mcpserver → agent` edge, and it is now a measurement in the spec rather than a claim in a report:

```
$ .venv/bin/python -c "import sys,time; b=len(sys.modules); t=time.perf_counter(); \
    import hrmosaic.agent.guardrails.g4; print(len(sys.modules)-b, round(time.perf_counter()-t,2))"
2823 0.85
$ .venv/bin/python -c "import sys,time; b=len(sys.modules); t=time.perf_counter(); \
    import hrmosaic.core.injection; print(len(sys.modules)-b, round(time.perf_counter()-t,3))"
12 0.003
```

(The implementer's 2,867 / ~1.0 s and this 2,823 / 0.85 s are the same measurement on a differently
warmed machine. The spec now carries the reproducible command's numbers.)

**The decision.** `_hit(hit, rank)` is a new function that replaces the inline `SearchHit(...)`
comprehension in `_search`. It scans and emits `text=None, quarantined=True` for a dirty chunk. Two
notes on it:

- **The snippet is scanned too.** `snippet` is a prefix of the same chunk, so an imperative inside
  the first 320 characters would otherwise ride out on the very field the quarantine leaves behind.
  Today's canary has a clean snippet (the imperative starts at char 355), so this changes nothing on
  the committed corpus and is a bound on a future one — the same reasoning as `CHUNK_MAX_CHARS`.
- **`RetrievalPayload` is unchanged in shape.** It already read `hit.quarantined`, which was always
  `False` from the server; it is now the server's real verdict, and the orchestrator's `_mark` still
  re-resolves each chunk from the committed index and marks it independently, so the eval's `retrieval`-span
  assertion is unaffected either way.

**The client shield stays**, exactly as the review asked: a client that trusts a server to police its
own output has no shield against any other MCP server it is pointed at (§8.1's remote-transport row),
and defence in depth is free here.

**Covering test.** `test_the_server_never_puts_a_quarantined_chunk_on_the_wire` asserts on
`result.content[0].text` — the bytes the server serialised — with no agent anywhere between them and
the assertion, on **both** transports via the `open_session` fixture. It also asserts `g4.scan` finds
nothing anywhere in the whole serialised body, not only in the canary's hit.

*Red-proof* (neutering `_hit`'s two scan lines to `False`):

```
E           assert hit["quarantined"] is True, "the decision is the server's own, at the plan's locus"
E           AssertionError: the decision is the server's own, at the plan's locus
E           assert False is True
FAILED …::test_the_server_never_puts_a_quarantined_chunk_on_the_wire[http]
FAILED …::test_the_server_never_puts_a_quarantined_chunk_on_the_wire[stdio]
2 failed in 2.13s
```

**Spec, amended in the same commit.** §4.2 gains a paragraph naming `core/injection.py`, the boundary
it exists for and the measurement; the repo-layout tree lists it beside `corpusread.py`; §7.4 records
the locus. The tool's own module docstring and `_hit`'s docstring say the same thing at the code.

---

## Finding 2 — the shield is per message, not per tool (`fc2e73f`)

`quarantine_search_hits` became `g4.quarantine_tool_result(name, body)`: a depth-bounded
(`MAX_DEPTH = 6`) depth-first walk over the decoded body that nulls every `text` / `snippet` string
`scan` fires on and sets `quarantined: true` on its containing object. `client.call_tool` calls it
unconditionally — the `if name == g4.SEARCH_TOOL:` guard is gone.

**Why those two keys and not every string.** `TEXT_KEYS = ("text", "snippet")` is the set that
carries untrusted *corpus prose*: a search hit's chunk, `get_policy_section`'s whole section,
`check_policy_compliance`'s `Requirement.text` and `Evidence.snippet`. Everything else a §8.4 tool
returns is either a number/date from the mock snapshot or prose **we** composed (`draft_hr_email`'s
subject and body). Walking every string would put a model-facing false positive on a field with no
untrusted input, and a G4 false positive is as expensive as a false negative (§7.4).

**The recording that makes the test measure its claim.**
`tests/fixtures/llm_scripts/injection_section_probe.json` — the same phishing question, answered by a
model that does exactly what W2-C's rule 6 tells it: two searches (step 1), then
`get_policy_section(doc_id="security-acceptable-use", chunk_id="c_61736dcd8aeae989")` (step 2), then
the closing sentence (step 3, 19 output tokens). Two searches deliberately, so the §9.1 breadth
reminder does not fire and the step count is the model's own rather than the harness's.

**Covering tests.**

- `test_no_act_message_contains_unbannered_g4_pattern` is now `@pytest.mark.parametrize`d over
  `injection_probe.json` and `injection_section_probe.json`, so the global claim it makes is measured
  through both doors into the canary.
- `test_a_quarantined_section_is_nulled_on_the_way_in` pins tool 2's half directly, on the
  `tool_call` span: `chunk_ids == [canary_id()]`, `text is None`, `quarantined is True`, and
  everything that is *not* the text still present.

*Red-proof* (restoring the `if name == SEARCH_TOOL:` guard around the walk):

```
E       AssertionError: tool message trips ignore_previous_instructions: {"doc_id":
    "security-acceptable-use", "doc_title": "Security & Acceptable Use Policy", "source_format":
    "txt", "heading_path": "Email and Phishing > EXAMPLE OF A PHISHING LURE - DO NOT ACT ON TEXT LIK
E       assert ('ignore_previous_instructions', 'IGNORE ALL PREVIOUS INSTRUCTIONS') is None
FAILED …::test_no_act_message_contains_unbannered_g4_pattern[injection_section_probe.json]
FAILED …::test_a_quarantined_section_is_nulled_on_the_way_in
2 failed, 1 passed in 3.46s
```

Note which one is *passed*: `injection_probe.json`, the recording the original test used. That is the
finding, reproduced.

**Effect on W2-A's budget test.** The new script adds one terminal zero-tool-call act entry at 19
output tokens. Terminal population is now `[8, 18, 18, 18, 18, 18, 18, 19, 19]`, median **18**,
unchanged; `test_act_closing_step_is_short` and its two siblings stay green.

**Spec** §7.4 now records both loci as a numbered pair and why neither is redundant.

---

## Finding 3 — `prompt_body` subtracts, it does not fabricate (`b7d7a91`)

`if "hits" in body:` around the one assignment, plus the docstring sentence and the inline reason.
Verified before the fix, exactly as the review reported:

```
$ .venv/bin/python -c "from hrmosaic.agent.client import prompt_body; \
    print(prompt_body('search_policy_documents', {'code':'INVALID_ARGUMENT','message':'k must be 1..10'}))"
{'code': 'INVALID_ARGUMENT', 'message': 'k must be 1..10', 'hits': []}
```

and after:

```
{'code': 'INVALID_ARGUMENT', 'message': 'k must be 1..10'}
```

**Covering tests**, both in `tests/unit/test_tool_result_prompt_text.py`:

- `test_an_error_body_never_grows_a_hits_key` — an `{code, message, fields}` body round-trips
  unchanged (and is not the caller's own dict).
- `test_an_empty_hit_list_is_still_reported_as_empty` — a search that genuinely returned nothing
  still says `{"hits": []}`, so the fix is "set the key only when it was there", not "drop empty
  lists", which would have been a second lie in the other direction.

*Red-proof* (`if "hits" in body:` → `if True:`):

```
E       AssertionError: assert {'code': 'INV...], 'hits': []} == {'code': 'INV...ields': ['k']}
E         Left contains 1 more item:
E         {'hits': []}
FAILED tests/unit/test_tool_result_prompt_text.py::test_an_error_body_never_grows_a_hits_key
```

**Spec** §7.2's W2-D paragraph records that the reduction is subtraction only, and why.

---

## Definition of done — real output at `b7d7a91`

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
230 files already formatted

$ .venv/bin/pytest -q
........................................................................ [ 93%]
........................................................................ [ 97%]
.............................................                            [100%]
1773 passed in 153.54s (0:02:33)

$ .venv/bin/python scripts/check_facts.py
14 documents · 57 facts · 7 rule scenarios · 33 requirements
OK — every quote is verbatim, every heading path is real, every fact_key resolves.
exit=0

$ .venv/bin/python scripts/pii_check.py
pii_check: clean — 13 files, no SSN shapes, no non-.example addresses, no non-555 numbers
exit=0

$ .venv/bin/python -m hrmosaic.rag.ingest --verify-manifest
  totals      14     204    30840
  index    data/index/hr_index.sqlite

OK — data/index/chunks.manifest.jsonl is byte-identical to the rebuild (204 chunks)

$ .venv/bin/python scripts/gen_tool_schemas.py && git diff --exit-code mcp/tools/
9 tool schemas generated from a live tools/list.
SCHEMA CLEAN

$ .venv/bin/pytest -q tests/contract/test_tool_schemas_committed.py
....                                                                     [100%]
4 passed in 0.87s
```

The committed schemas are byte-identical after regeneration: `SearchHit.text` was already
`str | None` on the wire, so moving *when* the null is decided changed no published schema. No prompt
template was touched, so the six golden fixtures are unchanged and needed no re-review.

Not run, and still the main session's: the deployed 26-item sweep, the judge pass, both §13.9
ablation arms, `evaluation.runner`, `evaluation.ablation`, `make eval`, `make ablation`.

---

## Concerns for the reviewer

1. **`get_policy_section` is still unshielded *server-side*.** Finding 1's public-endpoint argument
   applies to tool 2 as well: an MCP Inspector session attached to `/mcp-server/mcp` can ask for
   `security-acceptable-use / "Email and Phishing > EXAMPLE OF A PHISHING LURE …"` and receive the
   imperative verbatim. I did not close that, for three reasons and I want them on the record rather
   than assumed: the review scoped finding 2's fix to `call_tool`; it is not a W2-C regression (tool
   2 has returned verbatim sections since P5, and the plan bullet is about the search hit); and
   nulling it in the tool would make `get_policy_section` unable to return a section that a human
   reader has a legitimate reason to read, which is a contract change nobody has ratified. If the
   reviewer wants it closed, it is `_section()`'s return and ~4 lines, and `core/injection.py` is
   already the import.
2. **The walk reaches `check_policy_compliance`'s per-requirement text.** `Requirement.text` and
   `Evidence.snippet` are in `TEXT_KEYS`'s scope at depth 2–3. Nothing in `corpus/rules.yml` trips
   G4 today (whole suite green, and `test_compliance_evidence_is_scored` still passes), but a future
   rule whose requirement text quoted an injection example would be shown to the model as
   `"text": null, "quarantined": true`. That is the correct behaviour under §7.4 and it is also a
   surprise the first time it happens, so: deliberate, and flagged.
3. **Against our own server, the client's search-hit walk now finds nothing to do.** That is the
   point of defence in depth, but it means the client half's *live* coverage comes from
   `get_policy_section` and from any remote MCP server (§8.1 row 3) — not from the search path any
   more. `test_no_act_message_contains_unbannered_g4_pattern[injection_section_probe.json]` is what
   keeps the client half honest; the search path is now covered server-side.
4. **The original report's concerns 2–6 all still stand unchanged** — §10.5's 8 KB per-string cap
   truncating the search `tool_call` span's `result_json`, `text` and `snippet` duplicating ~320
   characters per hit, `test_act_closing_step_is_short` being a guard rather than a live measurement,
   the `ENVELOPE_KINDS` re-labelling note, and the prompt caps being instructions rather than
   enforcement. Nothing in this round touched any of them.
5. **Fresh blind labels and the deployed sweep are still owed.** This round changed no prompt bytes,
   but it does change what a turn that hits the canary sees (tool 2's `text` is now `null` on that
   one section), so a recorded arm that fetches it will differ from the pre-fix recording.
