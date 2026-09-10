"""The three deploy-time health assertions, tested on payloads instead of on a live instance.

`assert_health.py`, `wait_for_deploy.py` and `smoke_deployed.py` each run exactly once per deploy,
in CI, against a URL that does not exist on a developer's machine — so the part worth testing is
the part that decides pass or fail, which is a pure function over a parsed `/health` body in all
three. The HTTP shells around them are three lines each and are exercised for real by the `docker`
job and by the P11 acceptance gates.

What each check exists to catch (spec §15.1, §14.5, §12.3):

* `assert_health` — the image booted but the MCP handshake, the tool catalogue or the baked index
  is wrong. A container that answers `/health` at all is not evidence of any of those.
* `wait_for_deploy` — the deploy hook returned 202 and the **old** instance is still answering.
  Matching `app.git_sha` is the only thing that distinguishes the new release from the old one.
* `smoke_deployed` — the live service is running a `dev` build, lost its MCP server, or was
  deployed with `APP_ENV=render` and no `APP_ACCESS_TOKEN`, which 403s every gated route.
"""

from __future__ import annotations

import copy
import json
from unittest import mock

import pytest

from scripts import assert_health, smoke_deployed, wait_for_deploy

HEALTHY: dict = {
    "status": "ok",
    "app": {"version": "2026.1", "git_sha": "a1b2c3d", "rss_mb": 291.4, "deploy_mode": "render"},
    "mcp": {"connected": True, "tool_count": 9, "tool_names": ["search_policy_documents"], "last_error": None},
    "index": {"loaded": True, "doc_count": 14, "chunk_count": 281, "embed_model": "BAAI/bge-small-en-v1.5"},
    "degradations": [],
}


def _broken() -> dict:
    return _without(mcp__connected=False)


class _FakeResponse:
    """The two attributes `urllib.request.urlopen`'s context manager exposes to this script."""

    status = 200

    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload if payload is not None else HEALTHY

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _without(**overrides) -> dict:
    payload = copy.deepcopy(HEALTHY)
    for dotted, value in overrides.items():
        block, _, field = dotted.partition("__")
        payload[block][field] = value
    return payload


# --- assert_health ------------------------------------------------------------------------


def test_assert_health_accepts_a_fully_booted_image():
    assert assert_health.problems(HEALTHY) == []


def test_assert_health_rejects_a_disconnected_mcp_server():
    reported = assert_health.problems(_without(mcp__connected=False))
    assert len(reported) == 1
    assert "mcp.connected" in reported[0]


def test_assert_health_rejects_a_short_tool_catalogue():
    reported = assert_health.problems(_without(mcp__tool_count=8))
    assert reported == [f"mcp.tool_count is 8, expected {assert_health.EXPECTED_TOOL_COUNT}"]


def test_assert_health_rejects_an_index_that_did_not_load():
    reported = assert_health.problems(_without(index__loaded=False))
    assert len(reported) == 1
    assert "index.loaded" in reported[0]


def test_assert_health_rejects_a_partial_corpus():
    reported = assert_health.problems(_without(index__doc_count=13))
    assert reported == [f"index.doc_count is 13, expected {assert_health.EXPECTED_DOC_COUNT}"]


def test_assert_health_ignores_rss_until_a_ceiling_is_asked_for():
    """CI's `docker` job has no cgroup limit; only `make docker-run-512` sets a budget (§14.3)."""
    assert assert_health.problems(_without(app__rss_mb=999.0)) == []


def test_the_memory_gate_fails_above_the_512mb_budget_ceiling():
    """§14.3's gate: 345 MB budgeted, 420 MB asserted, 512 MB the hard cgroup limit."""
    reported = assert_health.problems(_without(app__rss_mb=421.0), max_rss_mb=420.0)
    assert reported == ["app.rss_mb is 421.0, expected < 420.0"]


def test_the_memory_gate_passes_at_the_measured_figure():
    assert assert_health.problems(_without(app__rss_mb=291.4), max_rss_mb=420.0) == []


def test_assert_health_reports_every_problem_at_once():
    """One CI log line per fault, so a broken image is diagnosed from the first run, not the third."""
    broken = _without(mcp__connected=False, index__loaded=False)
    assert len(assert_health.problems(broken)) == 2


# --- wait_for_deploy ----------------------------------------------------------------------


def test_wait_for_deploy_waits_while_the_previous_release_answers():
    """The hook is async: the old instance keeps serving for a minute or more after it returns."""
    assert wait_for_deploy.is_live(HEALTHY, expected_sha="f00ba12") is False


def test_wait_for_deploy_accepts_the_expected_sha():
    assert wait_for_deploy.is_live(HEALTHY, expected_sha="a1b2c3d") is True


def test_wait_for_deploy_accepts_a_short_sha_prefix_of_the_expected_commit():
    """`RENDER_GIT_COMMIT` is a full sha; `GITHUB_SHA` is too, but a build may stamp an abbreviation."""
    full = _without(app__git_sha="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678")
    assert wait_for_deploy.is_live(full, expected_sha="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678") is True
    assert wait_for_deploy.is_live(full, expected_sha="a1b2c3d") is True


def test_wait_for_deploy_without_an_expected_sha_only_rejects_dev():
    assert wait_for_deploy.is_live(HEALTHY, expected_sha=None) is True
    assert wait_for_deploy.is_live(_without(app__git_sha="dev"), expected_sha=None) is False


# --- smoke_deployed -----------------------------------------------------------------------


def test_smoke_deployed_accepts_a_healthy_live_instance():
    assert smoke_deployed.health_problems(HEALTHY) == []


def test_smoke_deployed_rejects_a_dev_build_stamp():
    """§12.3: `GIT_SHA` resolves to `dev` only when neither it nor `RENDER_GIT_COMMIT` was set."""
    reported = smoke_deployed.health_problems(_without(app__git_sha="dev"))
    assert len(reported) == 1
    assert "git_sha" in reported[0]


def test_smoke_deployed_rejects_a_deployment_with_no_access_token():
    """`access_token_missing` means every gated route 403s — the deployment is unusable (§11.4)."""
    degraded = copy.deepcopy(HEALTHY)
    degraded["status"] = "degraded"
    degraded["degradations"] = ["access_token_missing"]
    reported = smoke_deployed.health_problems(degraded)
    assert reported == ["/health lists access_token_missing: every gated route on this deployment 403s"]


def test_smoke_deployed_tolerates_other_degradations():
    """A missing judge key or an unreachable store must not fail the deploy smoke (§11.4)."""
    degraded = copy.deepcopy(HEALTHY)
    degraded["status"] = "degraded"
    degraded["degradations"] = ["llm_api_key_missing", "trace_store_unreachable"]
    assert smoke_deployed.health_problems(degraded) == []


def test_smoke_deployed_rejects_a_disconnected_mcp_server():
    reported = smoke_deployed.health_problems(_without(mcp__connected=False))
    assert len(reported) == 1
    assert "mcp.connected" in reported[0]


# --- assert_health's boot window ----------------------------------------------------------


def test_assert_health_retries_until_the_container_is_listening(monkeypatch):
    """`docker run -d … && assert_health.py` must not race the boot; the wait is bounded."""
    monkeypatch.setattr(assert_health, "RETRY_INTERVAL_S", 0.0)
    attempts: list[int] = []

    def flaky(url: str, timeout: float):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionRefusedError(61, "Connection refused")
        return _FakeResponse()

    with mock.patch.object(assert_health.urllib.request, "urlopen", flaky):
        assert assert_health.fetch_health("http://127.0.0.1:10000", 5.0) == HEALTHY
    assert len(attempts) == 3


def test_assert_health_gives_up_when_nothing_ever_answers():
    def refused(url: str, timeout: float):
        raise ConnectionRefusedError(61, "Connection refused")

    with mock.patch.object(assert_health.urllib.request, "urlopen", refused):
        with pytest.raises(RuntimeError) as raised:
            assert_health.fetch_health("http://127.0.0.1:10000", 0.0)
    assert "did not answer" in str(raised.value)


def test_a_wrong_payload_is_judged_at_once_and_never_retried_into_a_timeout():
    """The retry is for a socket that is not open yet, never for an image that is wrong."""
    calls: list[int] = []

    def answering(url: str, timeout: float):
        calls.append(1)
        return _FakeResponse(_broken())

    with mock.patch.object(assert_health.urllib.request, "urlopen", answering):
        payload = assert_health.fetch_health("http://127.0.0.1:10000", 30.0)
    assert len(calls) == 1
    assert assert_health.problems(payload)


# --- smoke_deployed's opportunistic gate check --------------------------------------------


def _gate(answers: dict[str | None, int]) -> list[str]:
    def fake_get(url: str, token: str | None, timeout_s: float) -> tuple[int, bytes]:
        return answers[token], b""

    with mock.patch.object(smoke_deployed, "_get", fake_get):
        return smoke_deployed.gate_problems("https://x.onrender.com", "tok", 5.0)


def test_the_gate_check_wants_a_401_anonymously_and_a_200_with_the_bearer():
    """The access gate answers its key page with 401; `ADMIN_REQUIRED`'s 403 is a different check."""
    assert _gate({None: 401, "tok": 200}) == []


def test_an_open_deployment_is_reported_even_though_it_serves_pages():
    reported = _gate({None: 200, "tok": 200})
    assert len(reported) == 1
    assert "the access gate is not on" in reported[0]


def test_a_token_the_deployment_does_not_recognise_is_reported():
    reported = _gate({None: 401, "tok": 401})
    assert len(reported) == 1
    assert "expected 200" in reported[0]


def _health_then(fault):
    """`/health` succeeds, then every subsequent call raises — the mid-smoke disconnection."""

    def dispatch(url: str, token: str | None, timeout_s: float) -> tuple[int, bytes]:
        if url.endswith("/health"):
            return 200, json.dumps(HEALTHY).encode("utf-8")
        return fault(url, token, timeout_s)

    return dispatch


def test_a_network_fault_during_the_gate_check_is_a_failed_smoke_not_a_traceback():
    """`/health` answered a moment ago; the instance dropping now is the thing this script catches."""

    def drop(url: str, token: str | None, timeout_s: float) -> tuple[int, bytes]:
        raise ConnectionResetError(54, "Connection reset by peer")

    with mock.patch.object(smoke_deployed, "_get", drop):
        with pytest.raises(ConnectionResetError):
            smoke_deployed.gate_problems("https://x.onrender.com", "tok", 5.0)

    with mock.patch.dict(smoke_deployed.os.environ, {"APP_ACCESS_TOKEN": "tok"}):
        with mock.patch.object(smoke_deployed, "_get", _health_then(drop)):
            assert smoke_deployed.main(["--url", "https://x.onrender.com"]) == 1


# --- an unset DEPLOY_URL secret -------------------------------------------------------------
#
# In the `deploy` job an unset `DEPLOY_URL` repository secret expands to the empty string, so both
# scripts are invoked as `--url ""`. `urllib.request.urlopen("/health")` then raises
# `ValueError: unknown url type: '/health'`, which neither script's except tuple catches — so the
# job explicitly designed so that "a job that skipped quietly would look identical to a green one"
# would end in an unexplained stack trace. Both now reject it up front, by name.


@pytest.mark.parametrize("script", [wait_for_deploy, smoke_deployed], ids=["wait_for_deploy", "smoke_deployed"])
def test_an_empty_url_is_refused_by_name_and_names_the_secret(script, capsys):
    exit_code = script.main(["--url", ""])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "DEPLOY_URL" in captured.err
    assert "NEEDS-FROM-USER.md" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("script", [wait_for_deploy, smoke_deployed], ids=["wait_for_deploy", "smoke_deployed"])
def test_a_schemeless_url_is_refused_rather_than_probed(script, capsys):
    exit_code = script.main(["--url", "mosaic-hr-copilot.onrender.com"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "scheme" in captured.err


@pytest.mark.parametrize("script", [wait_for_deploy, smoke_deployed], ids=["wait_for_deploy", "smoke_deployed"])
def test_a_real_url_survives_the_check_with_its_trailing_slash_trimmed(script):
    assert (
        script.require_base_url("https://mosaic-hr-copilot.onrender.com/") == "https://mosaic-hr-copilot.onrender.com"
    )
