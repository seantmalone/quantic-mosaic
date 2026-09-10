"""`POST /api/eval/runs` — §11.7's bounded smoke run, end to end.

The success path P9 could not test, because `evaluation/runner.py` is P10's: a **one-item bounded
run as admin**, driven over the same `POST /chat` path `make eval` drives, against the very app
under test. `EVAL_TARGET_BASE_URL` is pointed at the running server, so what the dashboard
demonstrates is what the offline harness runs — the whole point of §11.7 — and no request escapes
to whatever else happens to be listening on port 8000.

Also here, because both belong to the same endpoint:

* **403 `ADMIN_REQUIRED`** in the employee persona — the privileged `options` the runner sends fail
  closed outside the admin persona (§11.1), and so does the launcher itself;
* the hard refusal of anything outside the smoke bounds — never a silent trim.

The app runs on the stub adapter, so the run makes no provider call and needs no key.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import free_port

pytestmark = pytest.mark.anyio

ADMIN = {"X-Actor": "admin"}
EMPLOYEE = {"X-Actor": "E1042"}


def _frames(body: str) -> list[tuple[str, dict]]:
    """Parse the SSE stream into `(event, data)` pairs."""
    frames = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines and "data" in lines:
            frames.append((lines["event"], json.loads(lines["data"])))
    return frames


@pytest.fixture
async def app(web):
    """The app on a known port, with `EVAL_TARGET_BASE_URL` pointed back at itself."""
    port = free_port()
    async with web(
        "demo_task_1.json",
        port=port,
        mcp_server_url=f"http://127.0.0.1:{port}/mcp-server/mcp",
        eval_target_base_url=f"http://127.0.0.1:{port}",
    ) as client:
        yield client


async def test_the_employee_persona_is_refused_with_admin_required(app):
    response = await app.post("/api/eval/runs", json={"variant": "baseline", "n_items": 1}, headers=EMPLOYEE)
    assert response.status_code == 403
    assert response.json() == {"code": "ADMIN_REQUIRED"}


async def test_a_request_outside_the_smoke_bounds_is_refused_not_trimmed(app):
    response = await app.post("/api/eval/runs", json={"variant": "baseline", "n_items": 99}, headers=ADMIN)
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "SMOKE_BOUNDS_EXCEEDED"
    assert body["max_items"] == 6
    assert body["requested"] == 99


async def test_a_one_item_bounded_run_as_admin_streams_and_records_the_run(app, store):
    response = await app.post(
        "/api/eval/runs",
        json={"variant": "baseline", "item_ids": ["pto-001"], "judge": False, "label": "smoke test"},
        headers=ADMIN,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = _frames(response.text)
    events = [event for event, _ in frames]
    assert events[0] == "run_started"
    assert "run_completed" in events, frames

    started = dict(frames)["run_started"]
    assert started["variant"] == "baseline"
    assert started["target"] == "local"

    item = next(data for event, data in frames if event == "item")
    assert item["item_id"] == "pto-001"
    assert item["of"] == 1
    assert item["trace_url"].startswith("/dashboard/sessions/")

    completed = dict(frames)["run_completed"]
    assert completed["n_items"] == 1
    assert completed["detail_url"] == f"/dashboard/evals/{completed['run_id']}"

    # §13.2: the item produced a real session and turn, `sessions.eval_run_id` is populated, and the
    # `eval_results` row links straight back to the audit trace — one click, in both modes.
    row = store.execute(
        "SELECT run_id, item_id, session_id, turn_id, run_phase FROM eval_results WHERE run_id = ?",
        (completed["run_id"],),
    ).one()
    assert row is not None, "the run was not imported into eval_results"
    assert row["item_id"] == "pto-001"
    assert row["run_phase"] == "scored"
    session = store.execute("SELECT eval_run_id, client_label FROM sessions WHERE id = ?", (row["session_id"],)).one()
    assert session == {"eval_run_id": completed["run_id"], "client_label": "eval"}


async def test_the_smoke_run_is_visible_on_page_eleven_afterwards(app):
    launched = await app.post(
        "/api/eval/runs", json={"variant": "baseline", "item_ids": ["remote-001"], "judge": False}, headers=ADMIN
    )
    assert launched.status_code == 200, launched.text
    run_id = dict(_frames(launched.text))["run_completed"]["run_id"]

    detail = await app.get(f"/api/eval/runs/{run_id}", headers=ADMIN)
    assert detail.status_code == 200, detail.text
    view = detail.json()
    assert view["run"]["variant"] == "baseline"
    assert view["run"]["target"] == "local"
    assert [row["item_id"] for row in view["items"]] == ["remote-001"]
    # The dataset supplies the question and gold columns page 11 renders (§11.6).
    assert view["items"][0]["question"]
    assert view["items"][0]["gold"]
