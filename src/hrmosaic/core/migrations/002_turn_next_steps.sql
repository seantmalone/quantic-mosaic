-- Migration 002 — `turns.next_steps_json` (UX W3).
--
-- `turns` stored the answer blocks and the citations but not the *steps* beside them, so a
-- conversation replayed by `GET /?session=<id>` had to reconstruct them by parsing the joined
-- `final_answer` back apart. That works only while the join format holds and only while the
-- stored string is the one `render_answer()` produced — and a refusal's redirect, which is the
-- most useful half of a refusal, was what depended on it.
--
-- Forward-only: rows written before this migration keep `next_steps_json = NULL`, and the replay
-- falls back to parsing `final_answer` for exactly those.

ALTER TABLE turns ADD COLUMN next_steps_json TEXT;  -- ["Reply with…"], beside answer_blocks_json
