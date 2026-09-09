"""The whole confirmation gate, in three tests (spec §8.6, §17 *Irreversible actions*, R4.5).

* **missing** — a write tool called with **no** token returns `CONFIRMATION_REQUIRED` and inserts no
  `mock_writes` row;
* **mismatched** — a valid token replayed against **different** arguments returns
  `CONFIRMATION_REQUIRED`, leaves `used_at` null and writes nothing;
* **reused** — a token that already has `used_at` returns `CONFIRMATION_REQUIRED` and writes nothing.

Plus the positive control — a valid token *does* write exactly one row — because three rejections
that always reject would pass on a tool that can never write at all.

Every call goes over a real MCP session rather than through `server.call_tool(...)`, because the gate
compares the **raw wire arguments**: the tool body sees schema defaults already applied, and
comparing those would let a caller who omitted `priority` mismatch a token minted from the arguments
the client actually sent.

Tokens are minted here directly through `confirm.mint()`. In the running system only `web/` mints
them, at P8, after a human clicks Confirm.
"""

from __future__ import annotations

import json

import pytest
from mcp import Client

from hrmosaic.mcpserver import confirm
from hrmosaic.mcpserver.server import build_hr_server

pytestmark = pytest.mark.anyio

TICKET_ARGUMENTS = {
    "employee_id": "E1042",
    "queue": "hr-timeoff",
    "summary": "PTO request 15-17 Sep 2026 (3 days)",
    "details": "Three consecutive days of PTO, already agreed verbally with the manager.",
    "priority": "normal",
}


@pytest.fixture
def seeded(store):
    """A session and turn row for the `confirmations` foreign keys, and nothing else."""
    store.execute(
        "INSERT INTO sessions (id, created_at, last_activity_at, employee_id, auth_mode, actor_role, "
        "client_label, app_version, deploy_mode, mcp_transport) "
        "VALUES ('s-gate', 1, 1, 'E1042', 'open', 'employee', 'web', 'dev', 'local', 'http')"
    )
    store.execute(
        "INSERT INTO turns (id, session_id, seq, started_at, user_message, process_uptime_ms) "
        "VALUES ('t-gate', 's-gate', 1, 1, 'book three days off', 1)"
    )
    return store


def mint(store, arguments=TICKET_ARGUMENTS, **overrides):
    return confirm.mint(
        store,
        session_id="s-gate",
        turn_id="t-gate",
        span_id="ab" * 8,
        tool_name=overrides.pop("tool_name", "create_mock_hr_ticket"),
        arguments=arguments,
        human_summary="Open an HR ticket in hr-timeoff for E1042.",
        **overrides,
    )


async def call(arguments: dict) -> dict:
    async with Client(build_hr_server()) as client:
        result = await client.call_tool("create_mock_hr_ticket", arguments)
    body = json.loads(result.content[0].text)
    assert result.structured_content == body
    return body


def rejected(body: dict) -> None:
    """The five keys of §8.4 tool 8 — and no token of any kind, anywhere in the payload."""
    assert body["status"] == "confirmation_required"
    assert body["code"] == "CONFIRMATION_REQUIRED"
    assert body["action"] == "create_mock_hr_ticket"
    assert body["human_summary"]
    assert set(body["arguments_preview"]) == {"employee_id", "queue", "summary", "priority"}
    serialised = json.dumps(body)
    assert "token" not in serialised.lower()


def writes(store) -> int:
    return int(store.execute("SELECT COUNT(*) FROM mock_writes").scalar())


async def test_missing_token_is_rejected_and_writes_nothing(seeded):
    body = await call(TICKET_ARGUMENTS)
    rejected(body)
    assert writes(seeded) == 0


async def test_a_token_replayed_against_different_arguments_is_rejected(seeded):
    token = mint(seeded)
    body = await call({**TICKET_ARGUMENTS, "queue": "hr-benefits", "confirmation_token": token})
    rejected(body)
    assert writes(seeded) == 0
    assert seeded.execute("SELECT used_at FROM confirmations WHERE token = ?", (token,)).scalar() is None


async def test_a_used_token_is_rejected_and_writes_nothing(seeded):
    token = mint(seeded)
    first = await call({**TICKET_ARGUMENTS, "confirmation_token": token})
    assert first["status"] == "created"
    assert writes(seeded) == 1

    second = await call({**TICKET_ARGUMENTS, "confirmation_token": token})
    rejected(second)
    assert writes(seeded) == 1, "the second use must not append a second row"


async def test_a_valid_token_writes_exactly_one_mock_row(seeded):
    token = mint(seeded)
    body = await call({**TICKET_ARGUMENTS, "confirmation_token": token})
    assert body["status"] == "created"
    assert body["mock"] is True
    assert body["ticket_id"].startswith("MOCK-HR-")
    assert body["url"] == f"/dashboard/safety#{body['ticket_id']}"

    row = seeded.execute("SELECT * FROM mock_writes").one()
    assert row["id"] == body["ticket_id"]
    assert row["kind"] == "hr_ticket"
    assert row["confirmation_token"] == token
    assert row["employee_id"] == "E1042"
    assert json.loads(row["payload_json"])["queue"] == "hr-timeoff"
    assert seeded.execute("SELECT used_at FROM confirmations WHERE token = ?", (token,)).scalar() is not None


async def test_a_declined_token_never_opens_the_gate(seeded):
    token = mint(seeded, user_response="declined")
    rejected(await call({**TICKET_ARGUMENTS, "confirmation_token": token}))
    assert writes(seeded) == 0


async def test_an_expired_token_never_opens_the_gate(seeded):
    token = mint(seeded, ttl_s=0)
    rejected(await call({**TICKET_ARGUMENTS, "confirmation_token": token}))
    assert writes(seeded) == 0


async def test_a_token_minted_for_another_tool_never_opens_the_gate(seeded):
    token = mint(seeded, tool_name="draft_hr_email")
    rejected(await call({**TICKET_ARGUMENTS, "confirmation_token": token}))
    assert writes(seeded) == 0


async def test_the_canonical_form_ignores_the_token_and_key_order():
    reordered = dict(reversed(list(TICKET_ARGUMENTS.items())))
    assert confirm.canonical_arguments(TICKET_ARGUMENTS) == confirm.canonical_arguments(reordered)
    assert confirm.canonical_arguments({**TICKET_ARGUMENTS, "confirmation_token": "x"}) == (
        confirm.canonical_arguments(TICKET_ARGUMENTS)
    )
    assert "confirmation_token" not in confirm.canonical_arguments({**TICKET_ARGUMENTS, "confirmation_token": "x"})
