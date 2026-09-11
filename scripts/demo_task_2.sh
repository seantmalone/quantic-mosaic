#!/usr/bin/env bash
# Demo task 2 — a PTO request with a confirmation-gated mock write (spec §18.2).
#
# The safety moment, in two calls: `POST /chat` ends `awaiting_confirmation` with the exact payload
# and **no token**, and only `POST /chat/confirm` mints one and lets the write happen. Plain curl,
# parameterised by BASE_URL. POSIX sh only, because `make demo2` runs it with `sh`.
#
# Every call sends `Authorization: Bearer $APP_ACCESS_TOKEN`; the chat calls stay in the **default
# employee persona** (E1042), and only the `GET /api/traces/turns/{turn_id}` poll of the 202
# fallback — the one admin-only route this script touches — additionally sends `X-Actor: admin`.
#
#   BASE_URL=https://mosaic-hr.onrender.com APP_ACCESS_TOKEN=… sh scripts/demo_task_2.sh
set -eu

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
PYTHON="${PYTHON:-python3}"
PROMPT='Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 — and can you open the request for me?'

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

echo "== Demo task 2 — PTO request with a confirmation-gated mock write"
echo "   ${BASE_URL}"
echo "   \"${PROMPT}\""
echo

"$PYTHON" - "$PROMPT" > "$WORK/request.json" <<'PY'
import json, sys
print(json.dumps({"message": sys.argv[1], "client_label": "demo"}))
PY

STATUS="$(curl -sS -o "$WORK/gated.json" -w '%{http_code}' \
  -X POST "${BASE_URL}/chat" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${APP_ACCESS_TOKEN:-}" \
  --data-binary "@$WORK/request.json")"

# §9.4's documented fallback, exactly as in demo_task_1.sh.
if [ "$STATUS" = "202" ]; then
  TURN_ID="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["turn_id"])' "$WORK/gated.json")"
  echo "-- /chat returned 202; polling GET /api/traces/turns/${TURN_ID} as X-Actor: admin"
  ATTEMPT=0
  while [ "$ATTEMPT" -lt 120 ]; do
    curl -sS -o "$WORK/gated.json" \
      -H "Authorization: Bearer ${APP_ACCESS_TOKEN:-}" \
      -H 'X-Actor: admin' \
      "${BASE_URL}/api/traces/turns/${TURN_ID}"
    if "$PYTHON" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("outcome") else 1)' \
        "$WORK/gated.json"; then
      break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    sleep 1
  done
  # Falling out of the loop is a turn that never closed. Without this the script carried on and
  # exited 0 on a half-finished turn, which is worse than a red `make demo1`.
  if ! "$PYTHON" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("outcome") else 1)' \
      "$WORK/gated.json"; then
    echo "the turn never closed after ${ATTEMPT} polls of GET /api/traces/turns/${TURN_ID}" >&2
    exit 1
  fi
elif [ "$STATUS" != "200" ]; then
  echo "POST /chat returned HTTP ${STATUS}" >&2
  cat "$WORK/gated.json" >&2
  exit 1
fi

echo "-- the confirmation card (nothing has been created yet, and there is no token in this body)"
"$PYTHON" - "$WORK/gated.json" > "$WORK/confirm.json" <<'PY'
import json, sys

turn = json.load(open(sys.argv[1]))
card = turn.get("confirmation")
if turn.get("outcome") != "awaiting_confirmation" or card is None:
    print(f"expected awaiting_confirmation, got {turn.get('outcome')!r}", file=sys.stderr)
    raise SystemExit(1)
if "confirmation_token" in json.dumps(turn):
    print("a confirmation token leaked into the /chat response", file=sys.stderr)
    raise SystemExit(1)

print(f"   action:  {card['action']}", file=sys.stderr)
print(f"   summary: {card['human_summary']}", file=sys.stderr)
for key, value in sorted(card["arguments_preview"].items()):
    print(f"   {key}: {value}", file=sys.stderr)
print(json.dumps({"session_id": turn["session_id"], "turn_id": turn["turn_id"], "decision": "confirmed"}))
PY

echo
echo "-- Confirm: POST /chat/confirm mints the one-time token and the write happens"
curl -sS -o "$WORK/turn.json" -w '' \
  -X POST "${BASE_URL}/chat/confirm" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${APP_ACCESS_TOKEN:-}" \
  --data-binary "@$WORK/confirm.json"
echo

"$PYTHON" - "$WORK/turn.json" <<'PY'
import json, sys

turn = json.load(open(sys.argv[1]))
print("-- outcome:", turn.get("outcome"))
print()
print("-- answer")
print(turn.get("answer") or turn.get("final_answer") or "")
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
PY
