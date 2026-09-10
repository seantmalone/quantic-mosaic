"""Both demo agentic tasks, end to end through `POST /chat` (spec §18, R10.3).

`DEMO_EXPECTATIONS` is **two records, not one shared predicate**, because task 1 performs no write
and no confirmation and task 2 does. Each record is checked against the turn's own spans, so the
documented sequences of §18.1 and §18.2 cannot silently rot: change a tool name, drop a retrieval,
or let the write escape its confirmation, and this file fails.

* **`required_tools`** — every name must appear in the turn's `tool_call` spans with `status ==
  "ok"`. A set check, so repeats and extra permitted tools are fine.
* **`precedence_edges`** — for each `(a, b)`, the first `ok` span named `a` has a lower `seq` than
  the first named `b` (you cannot check a balance before you know who the employee is), without
  being brittle about interleaving.
* **`forbidden_tools`** — a hard fail on any occurrence.

Both prompts use **explicit dates**. There is no frozen clock, so "next Tuesday" would resolve
differently on every run and the documented arguments would rot within a week.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

pytestmark = pytest.mark.anyio


@dataclass(frozen=True)
class DemoExpectation:
    """What one demo task must do, as §18 documents it."""

    id: str
    min_tool_calls: int
    min_retrievals: int
    min_structured_data_tools: int
    requires_write: bool
    requires_confirmation: bool
    min_distinct_docs_cited: int
    forbidden_tools: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    precedence_edges: list[tuple[str, str]] = field(default_factory=list)


DEMO_EXPECTATIONS = [
    DemoExpectation(
        id="demo-1",
        min_tool_calls=4,
        min_retrievals=1,
        min_structured_data_tools=1,
        requires_write=False,
        requires_confirmation=False,
        min_distinct_docs_cited=3,
        forbidden_tools=["create_mock_hr_ticket", "draft_hr_email"],
        required_tools=[
            "lookup_employee_profile",
            "search_policy_documents",
            "get_policy_section",
            "check_policy_compliance",
        ],
        precedence_edges=[
            ("lookup_employee_profile", "search_policy_documents"),
            ("search_policy_documents", "get_policy_section"),
            ("get_policy_section", "check_policy_compliance"),
        ],
    ),
    DemoExpectation(
        id="demo-2",
        min_tool_calls=4,
        min_retrievals=1,
        min_structured_data_tools=1,
        requires_write=True,
        requires_confirmation=True,
        min_distinct_docs_cited=2,
        forbidden_tools=[],
        required_tools=[
            "lookup_employee_profile",
            "check_pto_balance",
            "search_policy_documents",
            "check_policy_compliance",
            "create_mock_hr_ticket",
        ],
        precedence_edges=[
            ("lookup_employee_profile", "check_pto_balance"),
            ("check_pto_balance", "search_policy_documents"),
            ("search_policy_documents", "check_policy_compliance"),
            ("check_policy_compliance", "create_mock_hr_ticket"),
        ],
    ),
]

BY_ID = {expectation.id: expectation for expectation in DEMO_EXPECTATIONS}

#: The people-data tools of §8.4 — "structured data", as distinct from the four RAG tools.
STRUCTURED_DATA_TOOLS = frozenset({"lookup_employee_profile", "check_pto_balance", "lookup_benefits_status"})

DEMO_1_PROMPT = "I want to work from Berlin from 3 November to 14 December 2026 — can I?"
DEMO_2_PROMPT = (
    "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
    "— and can you open the request for me?"
)


def _spans(store, turn_id: str) -> list[dict]:
    rows = store.execute(
        "SELECT seq, kind, name, status, payload_json FROM spans WHERE turn_id = ? ORDER BY seq", (turn_id,)
    ).dicts()
    for row in rows:
        row["payload"] = json.loads(row.pop("payload_json"))
    return rows


def check(expectation: DemoExpectation, response: dict, spans: list[dict], store) -> None:
    """The whole record, applied to one finished turn. Raises on the first breach."""
    ok_calls = [span for span in spans if span["kind"] == "tool_call" and span["status"] == "ok"]
    successful = [span for span in ok_calls if not span["payload"].get("is_error")]
    names = [span["name"] for span in successful]

    assert len(successful) >= expectation.min_tool_calls, f"{expectation.id}: only {len(successful)} tool calls"
    assert len([span for span in spans if span["kind"] == "retrieval"]) >= expectation.min_retrievals, (
        f"{expectation.id}: too few retrievals"
    )
    assert len(STRUCTURED_DATA_TOOLS & set(names)) >= expectation.min_structured_data_tools, (
        f"{expectation.id}: no structured-data tool was used"
    )

    assert set(expectation.required_tools) <= set(names), (
        f"{expectation.id}: missing {sorted(set(expectation.required_tools) - set(names))}"
    )
    assert not (set(expectation.forbidden_tools) & {span["name"] for span in spans if span["kind"] == "tool_call"}), (
        f"{expectation.id}: a forbidden tool was called"
    )

    first: dict[str, int] = {}
    for span in successful:
        first.setdefault(span["name"], span["seq"])
    for before, after in expectation.precedence_edges:
        assert first[before] < first[after], f"{expectation.id}: {before} must precede {after}"

    documents = {citation["doc_id"] for citation in response["citations"]}
    assert len(documents) >= expectation.min_distinct_docs_cited, (
        f"{expectation.id}: cited {sorted(documents)}, wanted {expectation.min_distinct_docs_cited} documents"
    )

    confirmations = [span for span in spans if span["kind"] == "confirmation"]
    writes = store.execute(
        "SELECT id, kind, confirmation_token FROM mock_writes WHERE turn_id = ?", (response["turn_id"],)
    ).dicts()
    if expectation.requires_confirmation:
        assert any(span["payload"]["user_response"] == "confirmed" for span in confirmations)
    else:
        assert confirmations == [], f"{expectation.id}: nothing should have needed confirming"
    if expectation.requires_write:
        assert len(writes) == 1, f"{expectation.id}: expected exactly one mock write"
        assert writes[0]["confirmation_token"], "a mock write cannot exist without a confirmation"
    else:
        assert writes == [], f"{expectation.id}: this task performs no write"


def test_there_are_exactly_two_expectation_records():
    """§18: two records, not one shared predicate — task 1 writes nothing and task 2 does."""
    assert [expectation.id for expectation in DEMO_EXPECTATIONS] == ["demo-1", "demo-2"]
    assert BY_ID["demo-1"].requires_write is False
    assert BY_ID["demo-2"].requires_write is True


async def test_demo_task_1_international_remote_work(web, store):
    """§18.1 — multi-document, no write. Five tool calls and a conditional, cited verdict."""
    expectation = BY_ID["demo-1"]
    async with web("demo_task_1.json") as client:
        response = await client.post("/chat", json={"message": DEMO_1_PROMPT, "client_label": "demo"})
        assert response.status_code == 200, response.text
        body = response.json()

    assert body["outcome"] == "answered"
    check(expectation, body, _spans(store, body["turn_id"]), store)

    assert {block["type"] for block in body["answer_blocks"]} >= {"policy_fact", "recommendation", "escalation"}
    assert body["dashboard_url"].startswith("/dashboard/sessions/")


async def test_demo_task_1_reaches_the_documented_verdict_with_its_arguments(web, store):
    """The `check_policy_compliance` call carries §18.1's arguments and comes back `conditional`."""
    async with web("demo_task_1.json") as client:
        body = (await client.post("/chat", json={"message": DEMO_1_PROMPT, "client_label": "demo"})).json()

    compliance = next(span for span in _spans(store, body["turn_id"]) if span["name"] == "check_policy_compliance")
    arguments = compliance["payload"]["arguments"]
    assert arguments["scenario"] == "international_remote"
    assert arguments["parameters"]["duration_days"] == 42
    assert arguments["parameters"]["destination_country"] == "DE"
    assert json.loads(compliance["payload"]["result_json"])["verdict"] == "conditional"


async def test_demo_task_2_pto_request_through_confirm_to_write(web, store):
    """§18.2 — the safety moment: the ticket does not exist until a human clicks Confirm."""
    expectation = BY_ID["demo-2"]
    async with web("demo_task_2.json") as client:
        gated = await client.post("/chat", json={"message": DEMO_2_PROMPT, "client_label": "demo"})
        assert gated.status_code == 200, gated.text
        proposal = gated.json()

        assert proposal["outcome"] == "awaiting_confirmation"
        assert proposal["confirmation"]["action"] == "create_mock_hr_ticket"
        assert "confirmation_token" not in gated.text
        assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 0

        confirmed = await client.post(
            "/chat/confirm",
            json={
                "session_id": proposal["session_id"],
                "turn_id": proposal["turn_id"],
                "decision": "confirmed",
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        body = confirmed.json()

    assert body["outcome"] == "answered"
    assert body["turn_id"] == proposal["turn_id"], "the same turn, reopened"
    check(expectation, body, _spans(store, body["turn_id"]), store)

    write = store.execute("SELECT id, kind, employee_id, payload_json FROM mock_writes").dicts()[0]
    assert write["id"].startswith("MOCK-HR-")
    assert write["kind"] == "hr_ticket"
    assert write["employee_id"] == "E1042"
    assert json.loads(write["payload_json"])["queue"] == "hr-timeoff"


async def test_demo_task_2_cites_the_snapshot_and_the_balance(web, store):
    """The answer is balance-aware and states the date its employee data came from (§5.4)."""
    async with web("demo_task_2.json") as client:
        proposal = (await client.post("/chat", json={"message": DEMO_2_PROMPT, "client_label": "demo"})).json()
        body = (
            await client.post(
                "/chat/confirm",
                json={
                    "session_id": proposal["session_id"],
                    "turn_id": proposal["turn_id"],
                    "decision": "confirmed",
                },
            )
        ).json()

    balance = next(span for span in _spans(store, body["turn_id"]) if span["name"] == "check_pto_balance")
    result = json.loads(balance["payload"]["result_json"])
    assert result["remaining_days"] == 13.5
    assert result["as_of"] == "2026-09-01"
    assert "13.5" in body["answer"]
