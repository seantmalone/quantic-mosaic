"""The demo-2 stub, replayed the way `make demo2` replays it, never narrates a filed ticket beside
a rule it breaks (W8 fix round, JX3-02 = dgc-r3-6).

Re-audit #3 photographed a confirmed PTO ticket next to "PTO requests must be submitted at least 5
business days in advance" and a notice of 0 — because the capture's servers had no `MOCK_TODAY`
and the engine anchored the recorded 15 September request on the wall clock. With the stubs'
submission date pinned (`tests/conftest.py`, `tests/ux/conftest.py`, `scripts/ux_capture.py`, the
Makefile, CI), every data-backed row of the demo's own verdict is met, the notice is the recorded
eight business days, and the answer carries no unmet-notice sentence. C02's other branch — a
`non_compliant` verdict proposes no card — is pinned by `test_write_is_coupled_to_the_verdict.py`.
"""

from __future__ import annotations

import json
import re

import pytest

pytestmark = pytest.mark.anyio

HTMX = {"HX-Request": "true"}

DEMO_2 = (
    "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
    "— and can you open the request for me?"
)

#: What an unmet-notice sentence looks like on the chat surface, in the two shapes the steps write.
UNMET_NOTICE = re.compile(r"does not meet the [^.]*notice|could not check the notice|notice[^.]*is 0\b", re.IGNORECASE)


async def _confirmed_turn(client) -> dict:
    proposal = (await client.post("/chat", json={"message": DEMO_2})).json()
    assert proposal["outcome"] == "awaiting_confirmation", proposal["outcome"]
    return (
        await client.post(
            "/chat/confirm",
            json={"session_id": proposal["session_id"], "turn_id": proposal["turn_id"], "decision": "confirmed"},
        )
    ).json()


def _verdict(store, turn_id: str) -> dict:
    rows = store.execute(
        "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'tool_call' ORDER BY seq", (turn_id,)
    ).dicts()
    bodies = [
        json.loads(row["payload_json"]).get("structured_content") or {}
        for row in rows
        if json.loads(row["payload_json"]).get("tool_name") == "check_policy_compliance"
    ]
    assert bodies, "the demo scores its request"
    return bodies[-1]


async def test_the_recorded_demo_meets_every_data_backed_requirement(web, store):
    async with web("demo_task_2.json") as client:
        body = await _confirmed_turn(client)
    verdict = _verdict(store, body["turn_id"])

    assert verdict["submitted_on"] == "2026-09-01", "the stubs' pinned submission date"
    assert verdict["verdict"] != "non_compliant"
    notice = next(row for row in verdict["requirements"] if row["id"] == "pto.request.notice")
    assert notice["status"] == "met"
    assert verdict["computed"]["notice_business_days"] == 8, "the recorded figure, Labor Day excluded"
    assert all(row["status"] == "met" for row in verdict["requirements"] if row["status"] != "not_stated")


async def test_a_performed_write_never_stands_beside_an_unmet_notice(web, store):
    async with web("demo_task_2.json") as client:
        body = await _confirmed_turn(client)

    types = [block["type"] for block in body["answer_blocks"]]
    assert types[0] == "performed"
    assert not UNMET_NOTICE.search(body["answer"]), body["answer"]
    for block in body["answer_blocks"]:
        assert "notice_business_days" not in block["text"] and "notice business days" not in block["text"]


async def test_no_turn_carries_a_performed_write_and_an_unmet_blocking_row(web, store):
    """The general rule C02 guarantees, stated over the served turn rather than over the stub."""
    async with web("demo_task_2.json") as client:
        body = await _confirmed_turn(client)
    verdict = _verdict(store, body["turn_id"])

    performed = any(block["type"] == "performed" for block in body["answer_blocks"])
    assert not (performed and verdict["verdict"] == "non_compliant")
