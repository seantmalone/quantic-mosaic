"""An empty `EVAL_TARGET_BASE_URL` is a named failure, never a traceback and never a `deployed` run.

`EVAL_TARGET_BASE_URL="$DEPLOY_URL" make eval` is four lines of the P11 definition of done, and
with `DEPLOY_URL` unset — which is exactly the state before user gates 2 and 4 land — the shell
expands it to the empty string. Before this guard that produced
`httpx.UnsupportedProtocol: Request URL is missing an 'http://' or 'https://' protocol`, a raw
traceback out of `make`, and `resolve_target("")` had *already* labelled the run `deployed`,
because an empty URL has no loopback host. A run that never reached a server could therefore have
been filed under the one target §13.10 publishes from.

The guard is the same one `scripts/wait_for_deploy.py` and `scripts/smoke_deployed.py` grew in the
first P11 fix round, applied at the harness's own door.
"""

from __future__ import annotations

import pytest

import evaluation.runner as runner
from evaluation.runner import BadTargetUrl, RunOptions


@pytest.fixture
def no_target(monkeypatch):
    """The post-gate command with `DEPLOY_URL` unset: `EVAL_TARGET_BASE_URL=""`."""
    monkeypatch.setattr(runner.default_settings, "eval_target_base_url", "")
    return ""


def test_an_empty_target_names_the_secret_and_the_gate():
    with pytest.raises(BadTargetUrl) as caught:
        runner.require_base_url("")
    message = str(caught.value)
    assert "EVAL_TARGET_BASE_URL is empty" in message
    assert "DEPLOY_URL" in message
    assert "NEEDS-FROM-USER.md" in message
    assert "provision_render.py" in message


def test_a_schemeless_target_is_refused_by_name():
    with pytest.raises(BadTargetUrl) as caught:
        runner.require_base_url("mosaic-hr-copilot.onrender.com")
    assert "has no http:// or https:// scheme" in str(caught.value)


def test_a_real_base_url_passes_through_stripped():
    assert runner.require_base_url("  https://mosaic-hr-copilot.onrender.com  ") == (
        "https://mosaic-hr-copilot.onrender.com"
    )
    assert runner.require_base_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"


def test_an_empty_target_can_no_longer_be_resolved_to_deployed(no_target):
    """The trap this closes: `resolve_target("")` still says `deployed`, so the guard must run first."""
    assert runner.resolve_target("") == "deployed"
    with pytest.raises(BadTargetUrl):
        runner.Runner(RunOptions(variant="baseline", base_url=""))


def test_the_cli_prints_a_named_fail_and_exits_one(no_target, capsys):
    assert runner.main(["--variant", "baseline"]) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("FAIL — ")
    assert "EVAL_TARGET_BASE_URL is empty" in captured.err
    assert captured.out == ""


@pytest.mark.anyio
async def test_the_smoke_stream_ends_with_a_named_frame_not_a_five_hundred(no_target):
    """§8.6: a misconfigured target must not break a `text/event-stream` halfway through."""
    frames = [frame async for frame in runner.smoke_run(variant="baseline", n_items=1)]
    assert len(frames) == 1
    assert frames[0].startswith("event: run_error\n")
    assert "BAD_TARGET_URL" in frames[0]
    assert "run_started" not in "".join(frames)
