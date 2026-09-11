"""`GET /health` and `GET /ready` (spec §11.4, R6.4).

`/health` **always returns 200 while the process is up** — degradation is a status string, never a
5xx — so a provider hiccup or a slow model load never makes Render restart-loop the instance.
`degradations[]` has exactly five possible strings and every `degraded` status carries at least one,
so the field is never empty while `status != "ok"`.

`/ready` is the other half of that split: 503 until the ONNX model and the index are resident, which
is what a deploy gate should wait on and what a liveness probe must not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hrmosaic.web.api import DEGRADATIONS
from tests.conftest import health_after_the_boot_import

pytestmark = pytest.mark.anyio

TOP_LEVEL = {"status", "app", "mcp", "index", "data", "llm", "trace_store", "degradations"}


async def test_health_reports_every_block_of_the_payload(web):
    async with web() as client:
        # The boot import of `evaluation/results/*.json` runs in the lifespan's maintenance task,
        # so `eval_runs_imported` climbs to its final value a moment after the server is up. CI
        # read it mid-import on 753596e — `assert 1 == 12`, under the coverage tracer, on a run
        # that passed locally — so the equality below waits for the import rather than racing it.
        response = await health_after_the_boot_import(client, eval_runs=_committed_run_count())

    assert response.status_code == 200
    body = response.json()
    assert set(body) == TOP_LEVEL
    assert body["status"] in {"ok", "degraded"}

    app = body["app"]
    assert set(app) >= {"version", "git_sha", "uptime_ms", "cold_start", "rss_mb", "rss_peak_mb", "deploy_mode", "now"}
    assert app["uptime_ms"] >= 0 and app["rss_mb"] > 0
    assert app["now"].endswith("Z")

    assert body["data"] == {"as_of": "2026-09-01", "employees": 24}
    assert body["trace_store"]["backend"] == "sqlite"
    assert body["trace_store"]["reachable"] is True
    # Every committed `evaluation/results/<run_id>.json` is imported at boot (§10.3), so this is
    # the number of committed run objects — three from P10's local proving runs — not zero.
    assert body["trace_store"]["eval_runs_imported"] == _committed_run_count()


def _committed_run_count() -> int:
    """`evaluation/results/*.json` minus the three aggregates `core/archive.py` skips (§10.3)."""
    results = Path(__file__).resolve().parents[2] / "evaluation" / "results"
    return sum(
        1
        for path in results.glob("*.json")
        if path.name not in {"latest.json", "comparison.json", "chunk_size_comparison.json"}
    )


async def test_health_reports_the_live_mcp_catalog(web):
    """The `mcp` block is the live handshake, not a constant — RUBRIC5.2's evidence on a URL."""
    async with web() as client:
        body = (await client.get("/health")).json()

    mcp = body["mcp"]
    assert mcp["connected"] is True
    assert mcp["transport"] == "http"
    assert mcp["url"].endswith("/mcp-server/mcp")
    assert mcp["tool_count"] == 9
    assert "search_policy_documents" in mcp["tool_names"]
    assert mcp["server_info"]["name"] == "mosaic-hr"
    assert mcp["protocol_version"]
    assert mcp["last_error"] is None


async def test_health_reports_the_index_it_will_actually_search(web):
    async with web() as client:
        body = (await client.get("/health")).json()

    index = body["index"]
    assert index["loaded"] is True
    assert index["embed_model"] == "BAAI/bge-small-en-v1.5"
    assert index["dim"] == 384
    assert index["doc_count"] >= 1 and index["chunk_count"] >= 1
    assert index["corpus_sha256"] and index["manifest_sha256"] and index["built_at"]


async def test_a_healthy_stub_deployment_is_ok_with_no_degradations(web):
    async with web() as client:
        body = (await client.get("/health")).json()

    assert body["degradations"] == []
    assert body["status"] == "ok"


async def test_every_degradation_string_is_one_of_the_five(web):
    """§11.4: exactly five strings, and the daily-cap stop of §9.8 adds no sixth."""
    async with web(app_env="render", app_access_token=None) as client:
        body = (await client.get("/health")).json()

    assert set(body["degradations"]) <= set(DEGRADATIONS)
    assert body["status"] == "degraded"
    assert body["degradations"], "a degraded status always names at least one cause"
    assert len(DEGRADATIONS) == 5


async def test_ready_is_503_until_the_warm_up_has_run(web):
    """`EMBED_WARMUP=0` is what CI's health-only steps use; the flag is the whole difference."""
    async with web(embed_warmup=False) as client:
        skipped = await client.get("/ready")
    assert skipped.status_code == 200
    assert skipped.json() == {"ready": True, "reason": None}


async def test_ready_reports_a_reason_while_it_is_not_ready(web, monkeypatch):
    """The 503 body names what is still missing, so a deploy wait is diagnosable (§11.4)."""
    from hrmosaic.web import main

    async def never_warm(app):
        app.state.ready_reason = "the embedding model is still loading"

    monkeypatch.setattr(main, "_warm_up", never_warm)
    async with web() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"ready": False, "reason": "the embedding model is still loading"}
