"""The demo scripts send the prompt the **server** dates, not two dates frozen in September 2026.

`README.md` invites a grader to run `scripts/demo_task_1.sh` / `scripts/demo_task_2.sh` against any
running instance, including the deployed one. Both carried fixed dates, and the rules engine
measures notice from the submission date (W8): on the deployed service — which pins no `MOCK_TODAY`,
exactly as §12.3 requires — demo task 2 asked for PTO in the past, the notice requirement measured
zero business days, and the script narrated a filed ticket beside a rule the request failed (gap 7).

The chat page never had that problem: `demo_prompts()` dates both prompts against the day they are
read. So the scripts now ask the page for its prompt through `scripts/demo_prompt.py` instead of
computing dates in `sh`, and these tests pin the three properties that makes correct:

1. the rendered page carries both prompts, keyed by `data-demo`, exactly as `demo_prompts()` says;
2. the helper reads them off a real instance over HTTP;
3. a server pinned to `MOCK_TODAY=2026-09-01` serves **the recorded pair byte for byte**, which is
   what keeps the stub replays of `make demo1` / `make demo2` (and `tests/e2e/test_demo_tasks.py`)
   driving the recorded script with the wording it was recorded against.
"""

from __future__ import annotations

import asyncio

import pytest

from hrmosaic.web.api import DEMO_PROMPTS, RECORDED_TODAY, demo_prompts
from scripts import demo_prompt

pytestmark = pytest.mark.anyio


async def test_the_page_carries_both_prompts_keyed_for_the_scripts(web):
    async with web() as client:
        html = (await client.get("/")).text

    served = demo_prompt.prompts_of(html)

    assert set(served) == set(demo_prompt.KEYS)
    assert served == demo_prompts()


async def test_the_helper_reads_the_prompt_off_a_running_instance(web, capsys):
    async with web() as client:
        base_url = str(client.base_url)
        # In a worker thread: the helper is a blocking `urlopen`, and the server under test is
        # serving on this test's own event loop.
        status = await asyncio.to_thread(demo_prompt.main, ["--base-url", base_url, "--key", "demo_2"])

    assert status == 0
    assert capsys.readouterr().out.strip() == demo_prompts()["demo_2"]


async def test_a_server_pinned_to_the_recorded_date_serves_the_recorded_pair(web):
    """The stub replays' side of it: `make demo1` / `make demo2` pin `MOCK_TODAY=2026-09-01`, so the
    wording the scripts send there is the wording the recorded LLM script expects."""
    async with web(mock_today=RECORDED_TODAY.isoformat()) as client:
        html = (await client.get("/")).text

    assert demo_prompt.prompts_of(html) == dict(DEMO_PROMPTS)


async def test_the_helper_answers_the_gate_with_the_access_token(web, monkeypatch, capsys):
    """The deployed service is gated, and the scripts already carry `APP_ACCESS_TOKEN` for `/chat`.
    Reading `GET /` is no different — and the refusal is named rather than counted (fix round 1,
    Minor 5): the gate answers `401` with the key page, so the helper reports `HTTP 401` at once
    instead of spending its retry budget waiting for a wrong token to become a right one."""
    from pydantic import SecretStr

    token = "a-throwaway-demo-token"
    async with web(app_access_token=SecretStr(token)) as client:
        base_url = str(client.base_url)
        ungated = await client.get("/")
        monkeypatch.delenv("APP_ACCESS_TOKEN", raising=False)
        refused = await asyncio.to_thread(demo_prompt.main, ["--base-url", base_url, "--key", "demo_1"])
        stderr = capsys.readouterr().err
        monkeypatch.setenv("APP_ACCESS_TOKEN", token)
        allowed = await asyncio.to_thread(demo_prompt.main, ["--base-url", base_url, "--key", "demo_1"])

    assert ungated.status_code == 401, "the gate answers the read itself, not a 200 without prompts"
    assert demo_prompt.prompts_of(ungated.text) == {}, "and the key page carries no demo prompt"
    assert refused == 1
    assert "HTTP 401" in stderr
    assert allowed == 0


async def test_a_cold_instance_is_waited_for_rather_than_downgraded(web, monkeypatch):
    """Fix round 1, Important 1. The measured cold start is 43–52 s to the first `/health` 200 and a
    single 15 s request used to fail on it — silently, because the caller then sent the recorded
    September dates. The fetch now retries until its own deadline, so the first few refusals of a
    waking instance cost a wait rather than the wrong prompt."""
    attempts: list[float] = []
    real_fetch = demo_prompt.fetch

    def waking(base_url: str, *, token: str | None = None) -> str:
        attempts.append(0.0)
        if len(attempts) < 3:
            raise OSError("HTTP 502")
        return real_fetch(base_url, token=token)

    async with web() as client:
        monkeypatch.setattr(demo_prompt, "fetch", waking)
        monkeypatch.setattr(demo_prompt, "FIRST_INTERVAL_S", 0.01)
        prompt = await asyncio.to_thread(demo_prompt.read_prompt, str(client.base_url), "demo_1")

    assert len(attempts) == 3, "the two refusals were retried, not reported"
    assert prompt == demo_prompts()["demo_1"]


def test_a_page_that_is_not_the_chat_page_is_reported_at_once(monkeypatch):
    """The other half of that: a 200 without the pair never improves by waiting, so it is reported on
    the first attempt — a deadline spent on a template that dropped `data-demo` is a timeout that
    blames the network for a markup change."""
    attempts: list[str] = []

    def not_the_chat_page(base_url: str, *, token: str | None = None) -> str:
        attempts.append(base_url)
        return "<html><body><button class='starter' data-prompt='something else'>x</button></body></html>"

    monkeypatch.setattr(demo_prompt, "fetch", not_the_chat_page)

    with pytest.raises(demo_prompt.Refused, match="no demo_1 demo prompt"):
        demo_prompt.read_prompt("http://127.0.0.1:8000", "demo_1", timeout_s=30.0)

    assert attempts == ["http://127.0.0.1:8000"], "one attempt, not a retry loop"
