"""Both demo agentic tasks, end to end through `POST /chat` (spec §18, R10.3).

`DEMO_EXPECTATIONS` is **two records, not one shared predicate**, because task 1 performs no write
and no confirmation and task 2 does. Each record is checked against the turn's own spans, so the
documented sequences of §18.1 and §18.2 cannot silently rot: change a tool name, drop a retrieval,
or let the write escape its confirmation, and this file fails.

* **`required_tools`** — every name must appear in the turn's `tool_call` spans with `status ==
  "ok"`. A set check, so repeats and extra permitted tools are fine. It lists what the workflow
  genuinely needs, never every tool §18's table happens to illustrate: `get_policy_section` is a
  way of reading a passage in full, not a step demo task 1 depends on, so it is not required.
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

from hrmosaic.mcpserver.tools.check_policy_compliance import normalise_country

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
    #: A write the user confirmed is reported **as done, with its id**, in the answer text (P22).
    #: The measured failure it pins: the ticket was created, the result reached the synthesis
    #: prompt verbatim, and the answer said "I cannot open PTO requests on your behalf" — and,
    #: under `next_steps`, "Log into MosaicOne and submit your PTO request".
    answer_states_the_write_id: bool = False
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
        # `get_policy_section` is **optional**, and deliberately so (P10 fix round, §18.1). Live
        # recordings of this task show `claude-haiku-4-5` reproducibly answering it with repeated
        # `search_policy_documents` calls instead of fetching a heading in full — which grounds the
        # answer just as well, because a search hit carries the whole chunk, not a snippet. §18.1's
        # table still shows the fetch as the illustrative sequence; what this record fixes is the
        # *outcome* — the profile, the corpus, the deterministic verdict and ≥ 3 cited documents —
        # not the one path a model may take to it. Requiring the fetch would have made the demo
        # assert a preference rather than a capability.
        required_tools=[
            "lookup_employee_profile",
            "search_policy_documents",
            "check_policy_compliance",
        ],
        precedence_edges=[
            ("lookup_employee_profile", "search_policy_documents"),
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
        answer_states_the_write_id=True,
        forbidden_tools=[],
        # `lookup_employee_profile` is **optional** here for the same reason (P10 fix round,
        # §18.2): the persona already carries the employee id, `check_pto_balance` answers the
        # question that was asked, and live recordings show `claude-haiku-4-5` reproducibly going
        # straight to it. The precedence edges kept are the ones this demo is actually *about* —
        # the write comes last, after the balance is known and after the deterministic verdict.
        # `search_policy_documents` before `check_policy_compliance` is not one of them: the
        # engine returns its own citations, and grounding the prose afterwards is a legitimate
        # order that the recordings take.
        required_tools=[
            "check_pto_balance",
            "search_policy_documents",
            "check_policy_compliance",
            "create_mock_hr_ticket",
        ],
        precedence_edges=[
            ("check_pto_balance", "create_mock_hr_ticket"),
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


def _rendered_next_steps(answer: str) -> list[str]:
    """The `- ` lines of `render_answer`'s "Next steps:" paragraph, as the reader sees them."""
    paragraph = next((part for part in answer.split("\n\n") if part.startswith("Next steps:")), "")
    return [line[2:] for line in paragraph.splitlines() if line.startswith("- ")]


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
        if expectation.answer_states_the_write_id:
            assert writes[0]["id"] in response["answer"], (
                f"{expectation.id}: the answer never names {writes[0]['id']}, the write it performed"
            )
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

    # `policy_fact` and `recommendation` are what the recorded exchange produces, every time. The
    # `escalation` block §18.1's outcome paragraph also imagined is a *labelling* choice the model
    # does not make here — it states the director approval and the Tax & Legal review as cited
    # policy facts instead, which is the substance the block was there to carry. So the substance
    # is asserted directly, and the block-type set asserts only what the workflow genuinely emits.
    # The capability itself is not left unasserted: demo 2's recording does emit an `escalation`
    # block, and `test_demo_task_2_pto_request_through_confirm_to_write` asserts it there.
    assert {block["type"] for block in body["answer_blocks"]} >= {"policy_fact", "recommendation"}
    assert "Tax & Legal" in body["answer"], "the human review the conditional verdict requires"
    assert body["dashboard_url"].startswith("/dashboard/sessions/")


async def test_demo_task_1_reaches_the_documented_verdict_with_its_arguments(web, store):
    """The `check_policy_compliance` call carries §18.1's arguments and comes back `conditional`."""
    async with web("demo_task_1.json") as client:
        body = (await client.post("/chat", json={"message": DEMO_1_PROMPT, "client_label": "demo"})).json()

    compliance = next(span for span in _spans(store, body["turn_id"]) if span["name"] == "check_policy_compliance")
    arguments = compliance["payload"]["arguments"]
    assert arguments["scenario"] == "international_remote"
    assert arguments["parameters"]["duration_days"] == 42
    # §18.1 documents `"DE"`; the recorded model sends `"Germany"`. The span keeps the caller's own
    # bytes — that is what an audit trail is for — and the tool normalises the name to its ISO code
    # at the wire boundary, so the engine compares codes with codes either way. The assertion is
    # therefore on the *destination the engine used*, not on the spelling that reached it.
    assert normalise_country(arguments["parameters"]["destination_country"]) == "DE"
    result = json.loads(compliance["payload"]["result_json"])
    assert result["verdict"] == "conditional"
    destination = next(item for item in result["requirements"] if item["id"] == "remote.intl.destination")
    assert destination["met"] is True and "DE" in destination["reason"]


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

    # Outcome consistency (P22). The recorded synthesis for this turn ends with an `escalation`
    # block — "I cannot open PTO requests in MosaicOne on your behalf" — written while the ticket
    # it denies was already in `mock_writes`. The deterministic step states the outcome first and
    # replaces that denial with a line pointing at the ticket, so neither survives into the answer.
    blocks = body["answer_blocks"]
    assert blocks[0]["type"] == "recommendation" and blocks[0]["text"].startswith("Done: HR ticket ")
    assert "escalation" not in {block["type"] for block in blocks}
    assert "cannot open PTO requests" not in body["answer"]

    # The same contradiction one line further down the same answer: the recorded synthesis also
    # ends `next_steps` with "Log into MosaicOne and submit your PTO request for 15–17 September
    # 2026", which `render_answer` prints under the blocks. A reader told the ticket exists must
    # not then be told to go and file it, so the directive is dropped and the rest is kept.
    steps = _rendered_next_steps(body["answer"])
    assert steps, "the answer still ends with the advice that does not contradict the ticket"
    assert not any("submit your PTO request" in step for step in steps), (
        f"a next step still tells the user to file the request that exists: {steps}"
    )
    assert "Log into MosaicOne" not in body["answer"]
    assert any("manager" in step for step in steps), "what happens next to the ticket is still said"

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
