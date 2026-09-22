"""The privileged-`options` matrix (spec §11.1), naming the code per row.

Every field of `options` except `k` is accepted only when `client_label == "eval"` **and** the
caller is in the admin persona. The refusal **splits by cause**, and both codes are
contract-visible — never a silent ignore, so a misconfigured eval run fails loudly instead of
quietly measuring the baseline three times.

| Row | Persona | `client_label` | Gate | Expected |
|---|---|---|---|---|
| 1 | admin | `eval` | off | **200**, and the options reach the retriever |
| 2 | employee | `eval` | off | **403** `ADMIN_REQUIRED` |
| 3 | admin | `web` | off | **403** `PRIVILEGED_OPTION_REFUSED` naming the field |
| 4 | — | — | on, no token | **401** at the gate |

The matrix is about what a **request** states. `options.tools_disabled` also has a process default
(`MCP_TOOLS_DISABLED`, §12.3), and the last test below is why that distinction is load-bearing: a
resolved value read as a stated one would turn the tool-filter knob into a 403 on every ordinary
turn.
"""

from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.anyio

QUESTION = "How much PTO do full-time employees accrue each month?"
ADMIN = {"X-Actor": "admin"}
PRIVILEGED = {"retrieval_strategy": "dense_only", "eval_run_id": "r_9f2c1b7e", "variant": "dense_only_k2", "k": 2}


async def test_row_1_admin_plus_client_label_eval_is_accepted(web, store):
    async with web("rag_only.json") as client:
        response = await client.post(
            "/chat",
            json={"message": QUESTION, "client_label": "eval", "options": PRIVILEGED},
            headers=ADMIN,
        )

    assert response.status_code == 200, response.text
    assert (
        store.execute("SELECT eval_run_id FROM sessions WHERE id = ?", (response.json()["session_id"],)).scalar()
        == "r_9f2c1b7e"
    )


async def test_row_2_the_employee_persona_is_403_admin_required(web):
    async with web() as client:
        response = await client.post("/chat", json={"message": QUESTION, "client_label": "eval", "options": PRIVILEGED})

    assert response.status_code == 403
    assert response.json() == {"code": "ADMIN_REQUIRED"}


async def test_row_3_an_admin_with_the_wrong_label_is_403_privileged_option_refused(web):
    async with web() as client:
        response = await client.post(
            "/chat",
            json={"message": QUESTION, "client_label": "web", "options": {"variant": "baseline"}},
            headers=ADMIN,
        )

    assert response.status_code == 403
    assert response.json() == {"code": "PRIVILEGED_OPTION_REFUSED", "field": "variant"}


async def test_row_4_the_gate_refuses_before_the_persona_is_consulted(web):
    async with web(app_access_token=SecretStr("s3cret")) as client:
        response = await client.post(
            "/chat",
            json={"message": QUESTION, "client_label": "eval", "options": PRIVILEGED},
            headers=ADMIN,
        )

    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_REQUIRED"


async def test_k_alone_is_unprivileged_and_needs_no_persona(web):
    """`k` is the one unprivileged option; everything else is refused (§11.1)."""
    async with web("rag_only.json") as client:
        response = await client.post("/chat", json={"message": QUESTION, "options": {"k": 3}})

    assert response.status_code == 200, response.text


async def test_retrieval_options_reach_the_tool(web, store):
    """The only path from `POST /chat`'s options to the retriever is `_meta.mosaic/retrieval` (§8.7).

    Retrieval lives inside the MCP server and `agent/**` may not import it, so an option that is
    accepted but never travels would be a silent no-op — exactly the failure the split refusal
    above exists to prevent, one layer down.
    """
    async with web("rag_only.json") as client:
        response = await client.post(
            "/chat",
            json={
                "message": QUESTION,
                "client_label": "eval",
                "options": {"k": 2, "retrieval_strategy": "dense_only"},
            },
            headers=ADMIN,
        )
    assert response.status_code == 200, response.text

    rows = store.execute(
        "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'retrieval' ORDER BY seq",
        (response.json()["turn_id"],),
    ).dicts()
    payloads = [json.loads(row["payload_json"]) for row in rows]

    assert payloads, "the turn did retrieve"
    for payload in payloads:
        assert payload["strategy"] == "dense_only"
        assert payload["k"] == 2
        assert payload["k_source"] == "override"


async def test_a_stated_tools_disabled_is_privileged_in_the_employee_persona(web):
    """The negative half of the row below (fix round 1, Important 2). `privileged_options_used` was
    narrowed to what the request *states*, so the thing that must still be refused is a request that
    states it: an employee persona asking for the tool filter is `403 ADMIN_REQUIRED`, whatever the
    process default happens to be — the ablation is admin-plus-`eval` and nothing else (§11.1)."""
    async with web() as client:
        refused = await client.post(
            "/chat",
            json={"message": QUESTION, "client_label": "eval", "options": {"tools_disabled": ["draft_hr_email"]}},
        )
        as_admin_on_the_wrong_label = await client.post(
            "/chat",
            json={"message": QUESTION, "client_label": "web", "options": {"tools_disabled": ["draft_hr_email"]}},
            headers=ADMIN,
        )

    assert refused.status_code == 403
    assert refused.json() == {"code": "ADMIN_REQUIRED"}
    assert as_admin_on_the_wrong_label.status_code == 403
    assert as_admin_on_the_wrong_label.json() == {"code": "PRIVILEGED_OPTION_REFUSED", "field": "tools_disabled"}


async def test_the_process_wide_tool_filter_is_not_read_as_a_privileged_request(web, store):
    """`MCP_TOOLS_DISABLED` is the process default for `options.tools_disabled` (gap 20), and a
    default is not something the caller asked for: an employee-persona `web` turn on a process that
    sets it is answered, with the tool genuinely withheld — not refused `ADMIN_REQUIRED`."""
    async with web("rag_only.json", mcp_tools_disabled="get_policy_section") as client:
        response = await client.post("/chat", json={"message": QUESTION})

    assert response.status_code == 200, response.text
    offered = [
        json.loads(row["payload_json"]).get("tools_offered") or []
        for row in store.execute(
            "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'llm_call' ORDER BY seq",
            (response.json()["turn_id"],),
        ).dicts()
    ]
    assert any(offered), "the turn called the model with a catalogue"
    assert all("get_policy_section" not in names for names in offered), "the filter withheld the tool"
    assert any("search_policy_documents" in names for names in offered), "and withheld nothing else"
