#!/usr/bin/env bash
# Demo task 2 — a PTO request with a confirmation-gated mock write (spec §18.2).
#
# The safety moment, in two calls: `POST /chat` ends `awaiting_confirmation` with the exact payload
# and **no token**, and only `POST /chat/confirm` mints one and lets the write happen. Plain curl,
# parameterised by BASE_URL. POSIX sh only, because `make demo2` runs it with `sh`.
#
# Every call sends `Authorization: Bearer $APP_ACCESS_TOKEN`; the chat calls stay in the **default
# employee persona** (E1042), and only the `GET /api/traces/turns/{turn_id}` poll of the 202
# fallback additionally sends `X-Actor: admin`. Since UX W1 every `/api/*` read is open to any persona
# holding the token, so this is belt-and-braces, not a requirement.
#
#   BASE_URL=https://mosaic-hr.onrender.com APP_ACCESS_TOKEN=… sh scripts/demo_task_2.sh
#
# The `PROMPT=` line below is the RECORDED wording, with the fixed dates the committed stub scripts
# were recorded against — and it is what `--recorded` sends, not what a run normally sends. The
# rules engine measures notice from the submission date (W8), so a fixed September 2026 date stops
# producing the documented verdict the moment it is in the past: against the deployed service, which
# pins no `MOCK_TODAY` (§12.3), this script used to narrate a rule the request failed.
#
# So before it asks anything it reads the prompt the chat page's own demo button carries
# (`scripts/demo_prompt.py`, `web/api.py::demo_prompts`), which **the server** dates against its own
# clock. `make demo2` pins `MOCK_TODAY=2026-09-01` — the mock data's own snapshot, and the one date
# that gives the recorded 8 business days of notice to 15 September once Boston's Labor Day is
# excluded — so the replay gets the recorded wording back byte for byte; the deployed service gets
# dates that are still in the future. The documented verdicts hold against any instance.
#
# The recorded wording is **opt-in**, `--recorded` (or `DEMO_RECORDED=1`), and a fetch that fails is
# a failed run: a script that quietly fell back would send September dates to the deployed service
# and report the result as a green demo, which is precisely the failure this replaced. The helper
# waits for a cold instance the way `scripts/wait_for_health.py` does, so a spun-down free instance
# is a wait, not a downgrade.
set -eu

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
PYTHON="${PYTHON:-python3}"
PROMPT='Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 — and can you open the request for me?'

# The wording this run actually sends: the instance's own, unless `--recorded` asked for the frozen
# one. `set -e` makes an unreadable page a non-zero exit, and the `if` is only here to say why.
RECORDED="${DEMO_RECORDED:-0}"
if [ "${1:-}" = "--recorded" ]; then
  RECORDED=1
fi
if [ "$RECORDED" = "1" ]; then
  echo "-- --recorded: sending the wording the stub script was recorded against" >&2
elif ! PROMPT="$("$PYTHON" "$(dirname "$0")/demo_prompt.py" --base-url "$BASE_URL" --key demo_2)"; then
  echo "demo task 2 did not run: ${BASE_URL} served no demo prompt (add --recorded to send the" >&2
  echo "recorded wording instead — it only reproduces the documented verdicts against a server" >&2
  echo "pinned to MOCK_TODAY=2026-09-01)" >&2
  exit 1
fi

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
import json, re, sys

turn = json.load(open(sys.argv[1]))
answer = turn.get("answer") or turn.get("final_answer") or ""
blocks = turn.get("answer_blocks") or []
print("-- outcome:", turn.get("outcome"))
print()
print("-- answer")
# The `performed` block is the turn's lede and the only account of the write (P29). It carries no
# label in the joined string — `render_answer` labels a recommendation and an escalation and lets
# a statement of what is so stand bare — so a transcript cannot tell it from a policy fact. This
# names it, the way the page does with a heading above the facts. "Done — " is the statement's own
# opening and is not printed twice.
lede = blocks[0] if blocks and blocks[0].get("type") == "performed" else None
if lede is not None:
    body = answer.split("\n\n", 1)
    print("Done: " + lede["text"].replace("Done — ", "", 1))
    print()
    print(body[1] if len(body) == 2 else "")
else:
    print(answer)
print()

# P22: a confirmed write is reported as done. The id comes from THIS response — the confirmed
# `create_mock_hr_ticket` span's own result — and the answer has to name it. The live failure this
# assertion pins: the ticket was created, the result reached the synthesis prompt verbatim, and
# the answer still ended "I cannot open PTO requests on your behalf" without naming it.
created = [
    match
    for entry in (turn.get("trace") or turn.get("spans") or [])
    if entry.get("kind") == "tool_call" and entry.get("name") == "create_mock_hr_ticket"
    for match in re.findall(r"MOCK-HR-[0-9]+", entry.get("result_preview") or "")
]
if not created:
    print("the confirmed turn carries no created ticket id", file=sys.stderr)
    raise SystemExit(1)
ticket_id = created[-1]
if ticket_id not in answer:
    print(f"the answer never names {ticket_id}, the ticket this turn created", file=sys.stderr)
    raise SystemExit(1)
# …and it is named in the one block that may account for a write (P29). Naming it *somewhere* was
# what this check used to ask, and the live 2026-09-15 turn passed it with the id inside a
# `recommendation` — printed under "What I suggest you do" beneath "Suggestions are guidance, not
# company policy", a created ticket disclaimed as advice. The `performed` block is the lede, so it
# is blocks[0] or the answer does not open with what happened.
if lede is None:
    kinds = [block.get("type") for block in blocks]
    print(f"the answer does not open with a 'performed' block: {kinds}", file=sys.stderr)
    raise SystemExit(1)
if ticket_id not in lede["text"]:
    print(f"the 'performed' block does not name {ticket_id}: {lede['text']!r}", file=sys.stderr)
    raise SystemExit(1)
print(f"-- the confirmed write is reported as done: {ticket_id} in the lede 'performed' block")

# ...and nothing under "Next steps:" sends the reader off to file the request that now exists.
# The same live answer that denied the ticket also ended "Log into MosaicOne and submit your PTO
# request for 15-17 September 2026", one line under the block stating the ticket.
paragraph = next((part for part in answer.split("\n\n") if part.startswith("Next steps:")), "")
steps = [line[2:] for line in paragraph.splitlines() if line.startswith("- ")]
# Mirrors `agent/outcome.py`'s check without importing it: an imperative verb at the head of a
# clause plus the ticket it made in the same clause. "Your manager will open the request" is a
# statement about someone else and is left alone, exactly as the step leaves it alone.
directive = re.compile(
    r"(?:^|[,;:.]\s*|\b(?:and|then|or)\s+)"
    r"(?:please\s+|make sure to\s+|be sure to\s+|you (?:must|should|need to|have to|can)\s+)?"
    r"(?:submit|file|open|raise|create)\b[^.,;:]*\b(?:request|ticket|case)\b",
    re.I,
)
directives = [step for step in steps if directive.search(step)]
if directives:
    print(f"a next step still tells the user to file the request: {directives}", file=sys.stderr)
    raise SystemExit(1)
print(f"-- and no next step asks for it again ({len(steps)} step(s) kept)")
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
