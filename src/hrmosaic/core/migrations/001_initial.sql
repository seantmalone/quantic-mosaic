-- Migration 001 — the complete trace / audit schema of spec §10.1, verbatim.
--
-- `schema_migrations` itself is created by the migration runner (core/db.py::migrate)
-- before any migration file is applied, so it is not repeated here.
--
-- SQLite dialect throughout (SQLite ⊃ libSQL): the identical statements run against
-- `SqliteStore` locally and against `TursoHTTPStore` in production.

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,                 -- 32-hex; doubles as the root trace_id
  created_at INTEGER NOT NULL,         -- epoch micros
  last_activity_at INTEGER NOT NULL,
  employee_id TEXT,                    -- the acting persona chosen in the UI
  auth_mode TEXT NOT NULL CHECK (auth_mode IN ('cookie','bearer','open')),   -- how the access gate was satisfied (§11)
  actor_role TEXT NOT NULL CHECK (actor_role IN ('employee','admin')),       -- the persona's privilege level (§11)
  client_label TEXT NOT NULL,          -- web|api|eval|demo (client-suppliable);
                                       -- eval_judge|maintenance (server-only)
  eval_run_id TEXT,                    -- non-null iff produced by an eval run
  user_agent_hash TEXT,                -- sha256[:16]; raw UA and IP are NEVER stored
  app_version TEXT NOT NULL,           -- git sha
  deploy_mode TEXT NOT NULL,           -- local | docker | render
  mcp_transport TEXT NOT NULL,         -- http | stdio | remote
  cold_start INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ix_sessions_created ON sessions(created_at DESC);

CREATE TABLE turns (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  seq INTEGER NOT NULL,                -- 1-based within the session
  started_at INTEGER NOT NULL, ended_at INTEGER, duration_ms INTEGER,
  user_message TEXT NOT NULL, final_answer TEXT,
  answer_blocks_json TEXT,             -- [{type, text, citations[]}]
  citations_json TEXT,                 -- the §7.3 Citation model, all nine fields
  outcome TEXT,                        -- answered|clarify|refused|escalated|awaiting_confirmation
                                       -- |partial|error|configuration_required|maintenance
  stop_reason TEXT, intent TEXT, workflow TEXT, error_kind TEXT,
  total_tokens_in INTEGER, total_tokens_out INTEGER,
  llm_calls INTEGER, tool_calls INTEGER, retrievals INTEGER, guardrail_hits INTEGER,
  llm_ms INTEGER, retrieval_ms INTEGER, tool_ms INTEGER, store_ms INTEGER,
  provider TEXT, model TEXT, provider_failover INTEGER NOT NULL DEFAULT 0,
  process_uptime_ms INTEGER NOT NULL,  -- < 60000 ⇒ classified COLD for latency stats
  rss_mb_at_end REAL,                  -- sampled by trace.py in the closing UPDATE; the series page 11 plots
  resumed_count INTEGER NOT NULL DEFAULT 0,  -- incremented when /chat/confirm reopens the turn
  awaiting_ms INTEGER NOT NULL DEFAULT 0,    -- time parked awaiting a human; excluded from every latency stat
  UNIQUE(session_id, seq));
CREATE INDEX ix_turns_session ON turns(session_id, seq);
CREATE INDEX ix_turns_started ON turns(started_at DESC);

CREATE TABLE spans (
  id TEXT PRIMARY KEY,                 -- 16-hex, OTel-shaped span_id
  turn_id TEXT NOT NULL REFERENCES turns(id),
  session_id TEXT NOT NULL,            -- denormalised: avoids a join on the busiest query
  parent_span_id TEXT, seq INTEGER NOT NULL,
  kind TEXT NOT NULL,                  -- mcp_discovery|plan|llm_call|retrieval|tool_call
                                       -- |guardrail|confirmation|judge|error
  name TEXT NOT NULL,                  -- 'anthropic:claude-haiku-4-5' | 'check_pto_balance'
  started_at INTEGER NOT NULL, ended_at INTEGER, duration_ms INTEGER,
  status TEXT NOT NULL,                -- ok | error
  error_message TEXT,
  payload_json TEXT NOT NULL,          -- the discriminated union of §10.2
  payload_bytes INTEGER NOT NULL,      -- PRE-truncation size
  truncated INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ix_spans_turn ON spans(turn_id, seq);
CREATE INDEX ix_spans_kind ON spans(kind, started_at DESC);
CREATE INDEX ix_spans_name ON spans(name, started_at DESC);

-- The exact prompt bytes USER.2 requires, held OUTSIDE payload_json so the 32 KB cap can never truncate them
-- (§7.2, §10.5). Written in the same end-of-turn batch as its span; pruned with its parent session.
CREATE TABLE llm_messages (
  span_id TEXT NOT NULL REFERENCES spans(id),
  seq INTEGER NOT NULL,                -- position in the messages array
  role TEXT NOT NULL,                  -- system | user | assistant | tool
  content TEXT NOT NULL,               -- verbatim, redacted, NOT truncated
  PRIMARY KEY (span_id, seq));

CREATE TABLE confirmations (           -- the confirmation gate (§8.6)
  token TEXT PRIMARY KEY,              -- secrets.token_urlsafe(32), minted only in web/
  session_id TEXT NOT NULL, turn_id TEXT NOT NULL, span_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  arguments_json TEXT NOT NULL,        -- the EXACT proposed arguments, canonically serialised
  human_summary TEXT NOT NULL,
  created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
  used_at INTEGER,                     -- non-null once consumed; a second use is rejected
  user_response TEXT NOT NULL);        -- confirmed | declined
CREATE INDEX ix_confirmations_turn ON confirmations(turn_id);

CREATE TABLE mock_writes (             -- the mock-action sandbox (written only by mcpserver/**)
  id TEXT PRIMARY KEY,                 -- 'MOCK-HR-000123' | 'MOCK-EMAIL-000045'
  kind TEXT NOT NULL,                  -- hr_ticket | hr_email
  created_at INTEGER NOT NULL,
  session_id TEXT, turn_id TEXT, span_id TEXT,
  employee_id TEXT NOT NULL, payload_json TEXT NOT NULL,
  confirmation_token TEXT NOT NULL REFERENCES confirmations(token));
                                       -- NOT NULL: no mock write without a confirmation

CREATE TABLE llm_cache (               -- optional; demo warm-up and cheap eval re-runs only
  key TEXT PRIMARY KEY,                -- sha256(provider|model|temperature|messages|tools)
  created_at INTEGER NOT NULL, provider TEXT, model TEXT,
  response_json TEXT NOT NULL, prompt_tokens INTEGER, completion_tokens INTEGER);

CREATE TABLE eval_runs (
  id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, git_sha TEXT NOT NULL, label TEXT NOT NULL,
  variant TEXT NOT NULL,               -- baseline | dense_only_k2 | no_structured_tools
  target TEXT NOT NULL,                -- local | deployed
  target_base_url TEXT NOT NULL, dataset_sha TEXT NOT NULL, config_json TEXT NOT NULL,
  n_items INTEGER NOT NULL, metrics_json TEXT NOT NULL,
  judge_model TEXT, judge_calls INTEGER, duration_s REAL, status TEXT NOT NULL, notes TEXT);

CREATE TABLE eval_results (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES eval_runs(id),
  item_id TEXT NOT NULL, category TEXT NOT NULL,
  session_id TEXT, turn_id TEXT,       -- ★ ONE CLICK from any eval row to its full audit trace
  run_phase TEXT NOT NULL DEFAULT 'scored',   -- 'scored' | 'cold_probe' (§13.5)
  answer TEXT, latency_ms INTEGER, cold INTEGER NOT NULL DEFAULT 0,
  scores_json TEXT NOT NULL,           -- {groundedness, cit_resolve, cit_f1, doc_recall, partial_match,
                                       --  clarification, tool_selection, arg_correctness, workflow, behavior, safety}
  verdicts_json TEXT,                  -- per-metric {score, pass, rationale, judge_model}
  passed INTEGER NOT NULL);
CREATE INDEX ix_eval_results_run ON eval_results(run_id, category);

CREATE TABLE import_state (            -- makes the boot import of eval results idempotent (§10.3)
  path TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
  imported_at INTEGER NOT NULL, n_records INTEGER NOT NULL);
