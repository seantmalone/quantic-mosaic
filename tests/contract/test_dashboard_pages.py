"""The eleven dashboard pages render, and only in the admin persona (spec §11.6, §11.7, §11.8).

Nothing here is seeded by hand. The fixture drives a **real** tool-using turn through the shipped
app with the stub model, confirms the proposed write, and imports the three committed per-variant
run fixtures of `tests/fixtures/eval_runs/` — so every page is asserted against the same rows
`core/trace.py` and `core/archive.py` actually wrote, which is the USER.4 invariant the whole
dashboard exists to demonstrate.

What this file pins down:

* every page answers **200** with its key selectors in the admin persona;
* every page **and** every `/api/*` read answers **403** `{"code": "ADMIN_REQUIRED"}` without it;
* pages 1 and 2 show and filter on `auth_mode` and `actor_role`;
* the three write controls of §11.6 are present and wired, never rendered dead;
* the bounded smoke-eval endpoint refuses an over-large request and reports the missing P10 runner
  rather than raising;
* the eval-row → trace deep link resolves.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytestmark = pytest.mark.anyio

ADMIN = {"X-Actor": "admin"}
EVAL_RUNS = Path(__file__).resolve().parents[1] / "fixtures" / "eval_runs"

DEMO_2 = (
    "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
    "— and can you open the request for me?"
)

#: The eleven pages of §11.6. Page 3 and page 10's detail take an id, filled in by the fixture.
PAGE_TEMPLATES = (
    (1, "/dashboard"),
    (2, "/dashboard/sessions"),
    (3, "/dashboard/sessions/{session_id}"),
    (4, "/dashboard/turns"),
    (5, "/dashboard/llm"),
    (6, "/dashboard/retrieval"),
    (7, "/dashboard/tools"),
    (8, "/dashboard/safety"),
    (9, "/dashboard/mcp"),
    (10, "/dashboard/corpus"),
    (10, "/dashboard/corpus/{doc_id}"),
    (11, "/dashboard/evals"),
    (11, "/dashboard/evals/{run_id}"),
)

#: Every `/api/*` read of §11.8.
API_TEMPLATES = (
    "/api/traces/overview",
    "/api/traces/sessions",
    "/api/traces/sessions/{session_id}",
    "/api/traces/turns",
    "/api/traces/turns/{turn_id}",
    "/api/traces/llm",
    "/api/traces/retrieval",
    "/api/traces/tools",
    "/api/traces/safety",
    "/api/mcp/discovery",
    "/api/corpus/documents",
    "/api/corpus/documents/{doc_id}",
    "/api/corpus/chunks/{chunk_id}",
    "/api/eval/runs",
    "/api/eval/runs/{run_id}",
    "/api/eval/compare",
)


class Seeded:
    """The live client plus the ids every page template needs."""

    def __init__(self, client, ids: dict[str, str]) -> None:
        self.client = client
        self.ids = ids

    def pages(self) -> list[tuple[int, str]]:
        return [(number, template.format(**self.ids)) for number, template in PAGE_TEMPLATES]

    def apis(self) -> list[str]:
        return [template.format(**self.ids) for template in API_TEMPLATES]


@pytest.fixture
async def seeded(web, store):
    """One real confirmed-write turn, plus the three committed per-variant eval runs."""
    from hrmosaic.core import archive

    async with web("demo_task_2.json") as client:
        proposed = await client.post("/chat", json={"message": DEMO_2, "client_label": "demo"})
        assert proposed.status_code == 200, proposed.text
        turn = proposed.json()
        resumed = await client.post(
            "/chat/confirm",
            json={"session_id": turn["session_id"], "turn_id": turn["turn_id"], "decision": "confirmed"},
        )
        assert resumed.status_code == 200, resumed.text

        report = archive.import_results(store=store, results_dir=EVAL_RUNS)
        assert "r_p9fixture_baseline.json" in report.imported, report

        chunk_id = store.execute(
            "SELECT json_extract(payload_json, '$.chunks[0].chunk_id') AS chunk_id FROM spans "
            "WHERE kind = 'retrieval' ORDER BY seq LIMIT 1"
        ).scalar()
        yield Seeded(
            client,
            {
                "session_id": turn["session_id"],
                "turn_id": turn["turn_id"],
                "doc_id": "pto-and-holidays",
                "run_id": "r_p9fixture_baseline",
                "chunk_id": chunk_id or "c_missing",
            },
        )


# --------------------------------------------------------------------------------------
# Access — the whole dashboard, reads included, is admin-only (§11.6 *Access*)
# --------------------------------------------------------------------------------------


async def test_every_page_and_every_api_read_is_403_admin_required_without_the_admin_persona(seeded):
    refusals = {}
    for _, url in seeded.pages():
        refusals[url] = await seeded.client.get(url)
    for url in seeded.apis():
        refusals[url] = await seeded.client.get(url)

    for url, response in refusals.items():
        assert response.status_code == 403, f"{url} answered {response.status_code}"
        assert response.json() == {"code": "ADMIN_REQUIRED"}, url


async def test_the_three_write_controls_are_403_without_the_admin_persona(seeded):
    for url in ("/api/dev/reset-sandbox", "/api/mcp/rediscover", "/api/eval/runs"):
        response = await seeded.client.post(url, json={})
        assert response.status_code == 403, url
        assert response.json() == {"code": "ADMIN_REQUIRED"}, url


# --------------------------------------------------------------------------------------
# The eleven pages
# --------------------------------------------------------------------------------------


async def test_every_page_renders_200_with_its_chrome_in_the_admin_persona(seeded):
    for number, url in seeded.pages():
        response = await seeded.client.get(url, headers=ADMIN)
        assert response.status_code == 200, f"{url}: {response.text[:300]}"
        body = response.text
        assert f'data-page="{number}"' in body, url
        assert 'id="export-json"' in body, url
        assert 'id="dash-nav"' in body, url
        # Every wide table lives inside its own scroll container, never the page (§11.6).
        if "<table" in body:
            assert "table-scroll" in body, url


async def test_page_one_shows_the_kpi_strip_the_sparkline_and_the_cost_estimates(seeded):
    response = await seeded.client.get("/dashboard", headers=ADMIN)
    body = response.text
    for kpi in (
        "sessions_24h",
        "turns",
        "tool_calls",
        "guardrail_blocks",
        "escalations",
        "pending_confirmations",
        "error_rate",
        "p50_ms",
        "p95_ms",
        "est_cost_usd",
        "spend_today_usd",
        "spend_7d_usd",
        "llm_calls_today",
        "llm_daily_call_cap",
    ):
        assert f'data-kpi="{kpi}"' in body, kpi
    assert 'id="chart-turns-per-hour"' in body
    assert "/static/vendor/chart.umd.js" in body
    assert "estimate" in body


async def test_pages_one_and_two_show_and_filter_on_auth_mode_and_actor_role(seeded):
    overview = await seeded.client.get("/dashboard", headers=ADMIN)
    sessions = await seeded.client.get("/dashboard/sessions", headers=ADMIN)
    matched = await seeded.client.get("/dashboard/sessions?actor_role=employee", headers=ADMIN)
    unmatched = await seeded.client.get("/dashboard/sessions?actor_role=admin", headers=ADMIN)

    for response in (overview, sessions):
        assert 'data-col="auth_mode"' in response.text
        assert 'data-col="actor_role"' in response.text
    assert 'id="filter-bar"' in sessions.text
    assert seeded.ids["session_id"] in matched.text
    assert seeded.ids["session_id"] not in unmatched.text


async def test_the_pager_keeps_the_filters_and_never_repeats_the_page_parameter(seeded):
    """A pager link that carried two `page=` values would silently ignore the second one."""
    page_two = await seeded.client.get("/dashboard/sessions?client_label=demo&page=2", headers=ADMIN)
    assert page_two.status_code == 200
    links = re.findall(r'<a class="button" href="(\?[^"]+)"', page_two.text)
    assert links, "page 2 must offer at least a Previous link"
    for link in links:
        assert link.count("page=") == 1, link
        assert "client_label=demo" in link, link


async def test_a_free_text_filter_survives_the_pager_and_the_export_link_intact(seeded):
    """§11.6: "Export JSON" can never answer a different row set than the page displays.

    `q` is free text. Concatenated into the query string raw, a `&` truncates every link that
    carries it and a `#` sends the rest to the fragment — so the pager would drop the filter and
    the export would silently widen the result set, with nothing on screen to say so.
    """
    q = "PTO & holidays #2026 = 50%"
    page_two = await seeded.client.get("/dashboard/turns", params={"q": q, "page": 2}, headers=ADMIN)
    assert page_two.status_code == 200, page_two.text[:300]

    export = html.unescape(re.search(r'id="export-json"[^>]*href="([^"]+)"', page_two.text).group(1))
    assert urlparse(export).fragment == "", export
    assert parse_qs(urlparse(export).query)["q"] == [q], export

    pager_links = [html.unescape(link) for link in re.findall(r'<a class="button" href="(\?[^"]+)"', page_two.text)]
    assert pager_links, "page 2 must offer at least a Previous link"
    for link in pager_links:
        assert parse_qs(urlparse(link).query)["q"] == [q], link

    # Following the export link gives back exactly the page's own filtered result set.
    exported = await seeded.client.get(export, headers=ADMIN)
    direct = await seeded.client.get("/api/traces/turns", params={"q": q, "page": 2}, headers=ADMIN)
    assert exported.status_code == 200, exported.text[:300]
    assert exported.json() == direct.json()


async def test_page_three_renders_every_span_of_the_turn_in_a_waterfall(seeded, store, spans):
    response = await seeded.client.get(f"/dashboard/sessions/{seeded.ids['session_id']}", headers=ADMIN)
    body = response.text
    assert 'id="span-waterfall"' in body
    assert 'id="kind-toggles"' in body

    recorded = spans(seeded.ids["turn_id"])
    assert recorded, "the fixture turn recorded no spans"
    rendered = len(re.findall(r'class="span-row"', body))
    assert rendered >= len(recorded)
    for kind, _, _ in recorded:
        assert f'data-kind="{kind}"' in body, kind
    # the proportional CSS duration bars of §11.6
    assert "span-bar" in body


async def test_page_eight_shows_the_guardrails_the_confirmation_and_the_mock_write(seeded):
    response = await seeded.client.get("/dashboard/safety", headers=ADMIN)
    body = response.text
    for selector in (
        'id="chart-verdicts"',
        'id="by-rule-table"',
        'id="injection-hits"',
        'id="confirmations-table"',
        'id="mock-writes-table"',
    ):
        assert selector in body, selector
    assert "confirmed" in body
    assert "MOCK-HR-" in body, "the confirmed write should be listed in the sandbox"


async def test_page_nine_lists_the_live_catalog_and_page_ten_the_corpus(seeded):
    mcp = await seeded.client.get("/dashboard/mcp", headers=ADMIN)
    corpus = await seeded.client.get("/dashboard/corpus", headers=ADMIN)
    document = await seeded.client.get(f"/dashboard/corpus/{seeded.ids['doc_id']}", headers=ADMIN)

    assert 'id="mcp-tools"' in mcp.text
    assert "search_policy_documents" in mcp.text
    assert 'id="handshake-history"' in mcp.text
    assert 'id="corpus-documents"' in corpus.text
    assert seeded.ids["doc_id"] in corpus.text
    assert 'id="corpus-chunks"' in document.text
    assert 'id="corpus-full-text"' in document.text


async def test_page_eleven_renders_not_judged_rather_than_a_zero_on_an_ablation_arm(seeded):
    listing = await seeded.client.get("/dashboard/evals", headers=ADMIN)
    baseline = await seeded.client.get("/dashboard/evals/r_p9fixture_baseline", headers=ADMIN)
    arm = await seeded.client.get("/dashboard/evals/r_p9fixture_dense_only_k2", headers=ADMIN)

    assert 'id="eval-runs-table"' in listing.text
    assert 'id="chart-ablation"' in listing.text
    assert 'id="chunk-size-table"' in listing.text

    assert 'data-metric="groundedness_mean"' in baseline.text
    assert "not judged on this variant" not in _metric_cell(baseline.text, "groundedness_mean")
    assert "not judged on this variant" in _metric_cell(arm.text, "groundedness_mean")
    # the deterministic aggregates are shown on both, and never as "not judged"
    for metric in ("cit_resolve_mean", "tool_selection_accuracy", "strict_pass_rate"):
        assert "not judged on this variant" not in _metric_cell(arm.text, metric), metric

    for selector in ('id="chart-latency"', 'id="chart-cold-warm"', 'id="chart-rss"', 'id="escalation-matrix"'):
        assert selector in baseline.text, selector


def _metric_cell(body: str, metric: str) -> str:
    match = re.search(rf'<div class="metric" data-metric="{metric}">(.*?)</div>\s*<div', body, re.S)
    assert match, f"{metric} is not on the page"
    return match.group(1)


async def test_the_eval_row_deep_link_resolves_to_the_session_page(seeded, store):
    """★ one click from any eval row to its full audit trace (§10.1)."""
    from hrmosaic.core.db import Statement

    session_id, turn_id = seeded.ids["session_id"], seeded.ids["turn_id"]
    store.batch(
        [
            Statement(
                "UPDATE eval_results SET session_id = ?, turn_id = ? "
                "WHERE run_id = 'r_p9fixture_baseline' AND item_id = 'pto-003'",
                (session_id, turn_id),
            )
        ]
    )
    page = await seeded.client.get("/dashboard/evals/r_p9fixture_baseline", headers=ADMIN)
    link = f"/dashboard/sessions/{session_id}#turn-{turn_id}"
    assert link in page.text

    followed = await seeded.client.get(f"/dashboard/sessions/{session_id}", headers=ADMIN)
    assert followed.status_code == 200
    assert f'id="turn-{turn_id}"' in followed.text


# --------------------------------------------------------------------------------------
# The three write controls (§11.6) — never dead, because the page proves the persona
# --------------------------------------------------------------------------------------


async def test_reset_sandbox_is_on_page_eight_and_clears_the_mock_writes(seeded, store):
    page = await seeded.client.get("/dashboard/safety", headers=ADMIN)
    assert 'id="reset-sandbox"' in page.text
    assert 'hx-post="/api/dev/reset-sandbox"' in page.text
    assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 1

    response = await seeded.client.post("/api/dev/reset-sandbox", headers=ADMIN)
    assert response.status_code == 200
    assert response.json() == {"cleared": 1}
    assert store.execute("SELECT COUNT(*) AS n FROM mock_writes").scalar() == 0


async def test_rediscover_is_on_page_nine_and_opens_a_synthetic_maintenance_turn(seeded, store):
    page = await seeded.client.get("/dashboard/mcp", headers=ADMIN)
    assert 'id="rediscover"' in page.text
    assert 'hx-post="/api/mcp/rediscover"' in page.text

    response = await seeded.client.post("/api/mcp/rediscover", headers=ADMIN)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rediscovered"] is True
    assert body["tool_count"] >= 5

    session = store.execute("SELECT client_label FROM sessions WHERE id = ?", (body["session_id"],)).one()
    turn = store.execute("SELECT outcome FROM turns WHERE id = ?", (body["turn_id"],)).one()
    span = store.execute(
        "SELECT kind FROM spans WHERE turn_id = ? AND kind = 'mcp_discovery'", (body["turn_id"],)
    ).one()
    assert session == {"client_label": "maintenance"}
    assert turn == {"outcome": "maintenance"}
    assert span == {"kind": "mcp_discovery"}


async def test_run_smoke_eval_is_on_page_eleven_bounded_and_lazily_imports_the_runner(seeded):
    """§11.7: at most `EVAL_SMOKE_MAX_ITEMS` items, one variant, `evaluation.runner` imported late."""
    page = await seeded.client.get("/dashboard/evals", headers=ADMIN)
    assert 'id="run-smoke-eval"' in page.text
    assert 'hx-post="/api/eval/runs"' in page.text

    too_many = await seeded.client.post("/api/eval/runs", json={"variant": "baseline", "n_items": 99}, headers=ADMIN)
    assert too_many.status_code == 400
    assert too_many.json()["code"] == "SMOKE_BOUNDS_EXCEEDED"
    assert too_many.json()["max_items"] == 6

    two_variants = await seeded.client.post(
        "/api/eval/runs", json={"variant": ["baseline", "dense_only_k2"]}, headers=ADMIN
    )
    assert two_variants.status_code == 422

    # `evaluation/runner.py` is P10's; until it lands the bounded request answers a clear 501
    # rather than raising, and P10's own test replaces this assertion with a real one-item run.
    bounded = await seeded.client.post("/api/eval/runs", json={"variant": "baseline", "n_items": 2}, headers=ADMIN)
    try:
        import evaluation.runner  # noqa: F401
    except ImportError:
        assert bounded.status_code == 501, bounded.text
        assert bounded.json()["code"] == "EVAL_RUNNER_UNAVAILABLE"
    else:  # pragma: no cover — true only once P10 has landed
        assert bounded.status_code == 200
