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


async def test_the_helper_answers_the_gate_with_the_access_token(web, monkeypatch):
    """The deployed service is gated, and the scripts already carry `APP_ACCESS_TOKEN` for `/chat`.
    Reading `GET /` is no different: without the header the page is the key page, not the prompts."""
    from pydantic import SecretStr

    token = "a-throwaway-demo-token"
    async with web(app_access_token=SecretStr(token)) as client:
        base_url = str(client.base_url)
        monkeypatch.delenv("APP_ACCESS_TOKEN", raising=False)
        refused = await asyncio.to_thread(demo_prompt.main, ["--base-url", base_url])
        monkeypatch.setenv("APP_ACCESS_TOKEN", token)
        allowed = await asyncio.to_thread(demo_prompt.main, ["--base-url", base_url])

    assert refused == 1, "an ungated read of a gated page carries no prompt"
    assert allowed == 0
