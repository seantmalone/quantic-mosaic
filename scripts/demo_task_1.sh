#!/usr/bin/env bash
# Demo task 1 — international remote-work eligibility (spec §18.1).
#
# Plain curl, parameterised by BASE_URL, pretty-printing the answer, the citations, the concise
# trace and the dashboard_url. POSIX sh only, because `make demo1` runs it with `sh`.
#
# Every call sends `Authorization: Bearer $APP_ACCESS_TOKEN`; the chat call stays in the **default
# employee persona** (E1042), and only the `GET /api/traces/turns/{turn_id}` poll of the 202
# fallback — the one admin-only route this script touches — additionally sends `X-Actor: admin`.
#
#   BASE_URL=https://mosaic-hr.onrender.com APP_ACCESS_TOKEN=… sh scripts/demo_task_1.sh
set -eu

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
PYTHON="${PYTHON:-python3}"
PROMPT='I want to work from Berlin from 3 November to 14 December 2026 — can I?'

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

echo "== Demo task 1 — international remote-work eligibility"
echo "   ${BASE_URL}"
echo "   \"${PROMPT}\""
echo

"$PYTHON" - "$PROMPT" > "$WORK/request.json" <<'PY'
import json, sys
print(json.dumps({"message": sys.argv[1], "client_label": "demo"}))
PY

STATUS="$(curl -sS -o "$WORK/turn.json" -w '%{http_code}' \
  -X POST "${BASE_URL}/chat" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${APP_ACCESS_TOKEN:-}" \
  --data-binary "@$WORK/request.json")"

# §9.4's documented fallback: if the platform's request timeout is under AGENT_WALL_CLOCK_S, /chat
# answers 202 with {session_id, turn_id, stream_url} and the client follows the turn instead.
if [ "$STATUS" = "202" ]; then
  TURN_ID="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["turn_id"])' "$WORK/turn.json")"
  echo "-- /chat returned 202; polling GET /api/traces/turns/${TURN_ID} as X-Actor: admin"
  ATTEMPT=0
  while [ "$ATTEMPT" -lt 120 ]; do
    curl -sS -o "$WORK/turn.json" \
      -H "Authorization: Bearer ${APP_ACCESS_TOKEN:-}" \
      -H 'X-Actor: admin' \
      "${BASE_URL}/api/traces/turns/${TURN_ID}"
    if "$PYTHON" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("outcome") else 1)' \
        "$WORK/turn.json"; then
      break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    sleep 1
  done
  # Falling out of the loop is a turn that never closed. Without this the script carried on and
  # exited 0 on a half-finished turn, which is worse than a red `make demo1`.
  if ! "$PYTHON" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("outcome") else 1)' \
      "$WORK/turn.json"; then
    echo "the turn never closed after ${ATTEMPT} polls of GET /api/traces/turns/${TURN_ID}" >&2
    exit 1
  fi
elif [ "$STATUS" != "200" ]; then
  echo "POST /chat returned HTTP ${STATUS}" >&2
  cat "$WORK/turn.json" >&2
  exit 1
fi

"$PYTHON" - "$WORK/turn.json" <<'PY'
import json, sys

turn = json.load(open(sys.argv[1]))
answer = turn.get("answer") or turn.get("final_answer") or ""
print("-- outcome:", turn.get("outcome"))
print()
print("-- answer")
print(answer)
print()

citations = turn.get("citations") or []
print(f"-- citations ({len(citations)} from {len({c['doc_id'] for c in citations})} document(s))")
for citation in citations:
    print(f"  [{citation['doc_id']}] {citation['heading_path']}")
    print(f"      {citation['snippet'][:140]}")
    print(f"      {citation['source_url']}")
print()

trace = turn.get("trace") or turn.get("spans") or []
print(f"-- trace ({len(trace)} spans)")
for entry in trace:
    line = f"  {entry['seq']:>3}  {entry['kind']:<14} {entry['name']:<28} {entry.get('duration_ms') or 0:>6} ms"
    summary = entry.get("summary") or ""
    print(line + (f"  {summary}" if summary else ""))
    if entry.get("args_preview"):
        print(f"        args   {entry['args_preview']}")
    if entry.get("result_preview"):
        print(f"        result {entry['result_preview']}")
print()

usage, timings = turn.get("usage") or {}, turn.get("timings") or {}
if usage:
    print(
        f"-- usage: {usage.get('llm_calls', 0)} model call(s), {usage.get('tool_calls', 0)} tool call(s), "
        f"{usage.get('retrievals', 0)} retrieval(s), {usage.get('prompt_tokens', 0)}→"
        f"{usage.get('completion_tokens', 0)} tokens in {timings.get('total_ms', 0)} ms"
    )
print("-- dashboard:", turn.get("dashboard_url"))

# `make demo1` is a definition-of-done command, so it has to fail on a turn that did not work.
# Without this the script exited 0 on an empty answer, zero citations or `outcome: null`.
# Citations are asserted as non-empty rather than at the three distinct documents
# `tests/e2e/test_demo_tasks.py` requires under the stub: this script is also run against the live
# URL, where document breadth varies run to run (see `docs/demo-script.md`, task 1 element ④).
problems = []
if turn.get("outcome") != "answered":
    problems.append(f"outcome is {turn.get('outcome')!r}, not 'answered'")
if not answer.strip():
    problems.append("the answer is empty")
if not citations:
    problems.append("the answer carries no citations")
if problems:
    print("demo task 1 did not complete: " + "; ".join(problems), file=sys.stderr)
    raise SystemExit(1)
PY
