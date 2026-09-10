"""No credential, no crash — on all three surfaces (spec §12.3, §11.4, §9.5).

Structural configuration is validated at import and fails fast, because those are programmer
errors. **Credentials are validated lazily, at the point of use, so boot always succeeds.** The
three surfaces a missing `ANTHROPIC_API_KEY` reaches, and what each does about it:

1. **boot** — the process comes up and `GET /` serves the chat page;
2. **`GET /health`** — 200, `status: degraded`, `llm_api_key_missing` in `degradations[]`;
3. **`POST /chat`** — 200, `outcome: "configuration_required"`, and an answer that names the
   variable to set rather than an error the grader has to decode.

A restart loop on a stale image is worse than a degraded instance; that is the whole rule.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.anyio

QUESTION = "How much PTO do full-time employees accrue each month?"

#: A real provider with no key — the state a fresh clone with an untouched `.env` is in.
KEYLESS = {"llm_provider": "anthropic", "anthropic_api_key": None}


async def test_surface_1_the_app_still_boots_and_serves_the_chat_page(web):
    async with web(**KEYLESS) as client:
        response = await client.get("/")
    assert response.status_code == 200


async def test_surface_2_health_is_200_degraded_and_names_the_missing_key(web):
    async with web(**KEYLESS) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert "llm_api_key_missing" in body["degradations"]
    assert body["llm"]["agent"]["configured"] is False
    assert body["llm"]["agent"]["provider"] == "anthropic"


async def test_surface_3_chat_answers_200_configuration_required_and_names_the_variable(web, store):
    async with web(**KEYLESS) as client:
        response = await client.post("/chat", json={"message": QUESTION})

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "configuration_required"
    assert "ANTHROPIC_API_KEY" in body["answer"]
    assert body["answer_blocks"], "a configuration message is still a typed answer block"

    row = store.execute("SELECT outcome, error_kind FROM turns WHERE id = ?", (body["turn_id"],)).one()
    assert (row["outcome"], row["error_kind"]) == ("configuration_required", "configuration_required")
    errors = store.execute(
        "SELECT payload_json FROM spans WHERE turn_id = ? AND kind = 'error'", (body["turn_id"],)
    ).dicts()
    kinds = [json.loads(error["payload_json"])["error_kind"] for error in errors]
    assert kinds == ["configuration_required"]


async def test_the_stub_provider_is_configured_by_construction(web):
    """`LLM_PROVIDER=stub` needs no credential — that is what makes the key-free push path (§16.2)."""
    async with web() as client:
        response = await client.get("/health")

    body = response.json()
    assert body["llm"]["agent"]["configured"] is True
    assert "llm_api_key_missing" not in body["degradations"]
