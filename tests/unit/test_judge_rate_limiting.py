"""The judge's pacing and its 429 handling (spec §13.7).

Written after the first deployed judge pass aborted at item **2 of 26**. Nothing was wrong with the
answers or the prompts: Google meters `gemini-3.5-flash-lite`'s free tier **per minute** as well as
per day, the pass fired its calls back to back, and a sequential 10-call burst on either of the two
Google projects answered 4 × 200 and 6 × 429 that afternoon. `_ask` treated the 429 as a malformed
reply, spent its one repair retry re-sending the prompt with a parse-error note appended — which a
rate limiter does not care about — and then counted a lost verdict. Four lost verdicts against a
budget of three ended the pass.

So two things are asserted here, and they are different things:

* a **rate-limit** refusal is not a bad answer: the identical prompt is re-sent after a wait, the
  repair attempt is left intact for a genuinely malformed reply, and `failures` does not move;
* calls are **paced**, with a floor on the gap between them rather than a token bucket — a bucket
  would let a pass spend a whole minute's allowance in two seconds and then be refused for the
  remaining fifty-eight, which is exactly the shape that failed.
"""

from __future__ import annotations

import pytest

from evaluation import judges
from hrmosaic.core.llm import ProviderError

# --- is_rate_limited ------------------------------------------------------------------------


def test_a_429_is_recognised_from_the_status():
    assert judges.is_rate_limited(ProviderError("nope", status=429)) is True


def test_a_429_is_recognised_when_the_adapter_only_put_it_in_the_message():
    """`OpenAICompatAdapter` wraps a transport failure without a status; the text still says it."""
    for message in (
        "gemini-3.5-flash-lite transport failure: 429 Too Many Requests",
        "RESOURCE_EXHAUSTED",
        "You exceeded your current quota, please check your plan and billing details.",
    ):
        assert judges.is_rate_limited(ProviderError(message)) is True


def test_an_ordinary_failure_is_not_mistaken_for_a_rate_limit():
    assert judges.is_rate_limited(ProviderError("bad gateway", status=502)) is False
    assert judges.is_rate_limited(ProviderError("invalid schema")) is False


# --- the pacer ------------------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.mark.anyio
async def test_the_pacer_puts_a_floor_under_the_gap_between_calls():
    clock = FakeClock()
    pacer = judges.Pacer(10, clock=clock, sleep=clock.sleep)

    await pacer.wait()  # the first call goes immediately
    assert clock.slept == []
    await pacer.wait()
    await pacer.wait()

    assert clock.slept == [6.0, 6.0], "10 rpm is one call every six seconds"


@pytest.mark.anyio
async def test_the_pacer_does_not_sleep_when_the_caller_was_already_slow():
    clock = FakeClock()
    pacer = judges.Pacer(10, clock=clock, sleep=clock.sleep)

    await pacer.wait()
    clock.now += 30.0  # a long provider round trip already covered the interval
    await pacer.wait()

    assert clock.slept == []


@pytest.mark.anyio
async def test_a_zero_rpm_pacer_never_waits():
    """`JUDGE_RPM=0` is the escape hatch for a paid key; it must not divide by zero."""
    clock = FakeClock()
    pacer = judges.Pacer(0, clock=clock, sleep=clock.sleep)
    await pacer.wait()
    await pacer.wait()
    assert clock.slept == []


# --- the 429 retry --------------------------------------------------------------------------


class Completion:
    def __init__(self, payload: dict) -> None:
        self.text = "{}"
        self._payload = payload

    def parsed_json(self) -> dict:
        return self._payload


class ScriptedModel:
    """Raises the queued exceptions in order, then answers."""

    model = "gemini-3.5-flash-lite"
    provider = "openai_compat"

    def __init__(self, failures: list[Exception], payload: dict) -> None:
        self._failures = list(failures)
        self._payload = payload
        self.attempts = 0
        self.prompts: list[int] = []

    async def complete(self, messages, **_kwargs):
        self.attempts += 1
        self.prompts.append(len(messages))
        if self._failures:
            raise self._failures.pop(0)
        return Completion(self._payload)


class FakeTurn:
    """Just enough `TurnBuffer` for `Judge._record`: somewhere to put the judge span."""

    def __init__(self) -> None:
        self.spans: list = []

    def add_span(self, *args, **kwargs) -> None:
        self.spans.append((args, kwargs))


def _judge(model: ScriptedModel) -> judges.Judge:
    """A judge whose pacer never sleeps, so only the 429 backoff shows up in the sleep log."""
    clock = FakeClock()
    return judges.Judge(run_id="r_test", model=model, pacer=judges.Pacer(0, clock=clock, sleep=clock.sleep))


@pytest.mark.anyio
async def test_a_rate_limited_call_is_re_sent_unchanged_and_costs_no_repair(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(judges.asyncio, "sleep", fake_sleep)
    model = ScriptedModel([ProviderError("429 RESOURCE_EXHAUSTED", status=429)], {"entailed": True, "rationale": "r"})
    judge = _judge(model)

    result = await judge._ask(
        metric="gold_fact_entailment",
        system="s",
        user="u",
        schema=judges.EntailmentVerdict,
        item_id="pto-001",
        scored_turn_id="t1",
        turn=FakeTurn(),
    )

    assert result == {"entailed": True, "rationale": "r"}
    assert judge.failures == 0, "a 429 is not a lost verdict"
    assert judge.rate_limited == 1
    assert model.attempts == 2
    assert model.prompts == [2, 2], "the identical prompt is re-sent; no repair note is appended"
    assert slept, "the retry waited"


@pytest.mark.anyio
async def test_the_providers_own_retry_after_is_honoured(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(judges.asyncio, "sleep", fake_sleep)
    model = ScriptedModel(
        [ProviderError("429", status=429, retryable=True, retry_after=27.0)],
        {"entailed": True, "rationale": "r"},
    )
    judge = _judge(model)

    await judge._ask(
        metric="gold_fact_entailment",
        system="s",
        user="u",
        schema=judges.EntailmentVerdict,
        item_id="pto-001",
        scored_turn_id="t1",
        turn=FakeTurn(),
    )
    assert slept == [27.0]


@pytest.mark.anyio
async def test_a_backoff_is_capped_so_a_pass_cannot_stall_for_minutes(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(judges.asyncio, "sleep", fake_sleep)
    model = ScriptedModel(
        [ProviderError("429", status=429, retry_after=6000.0)],
        {"entailed": True, "rationale": "r"},
    )
    judge = _judge(model)
    await judge._ask(
        metric="gold_fact_entailment",
        system="s",
        user="u",
        schema=judges.EntailmentVerdict,
        item_id="pto-001",
        scored_turn_id="t1",
        turn=FakeTurn(),
    )
    assert slept == [judges.JUDGE_RATE_LIMIT_MAX_BACKOFF_S]


@pytest.mark.anyio
async def test_a_provider_that_only_ever_429s_still_gives_up_and_records_a_null_verdict(monkeypatch):
    """The pass must not retry forever; §13.7's `None` verdict is still the floor."""

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(judges.asyncio, "sleep", fake_sleep)
    failures = [ProviderError("429", status=429) for _ in range(judges.JUDGE_RATE_LIMIT_ATTEMPTS * 4)]
    model = ScriptedModel(failures, {"entailed": True, "rationale": "r"})
    judge = _judge(model)

    result = await judge._ask(
        metric="gold_fact_entailment",
        system="s",
        user="u",
        schema=judges.EntailmentVerdict,
        item_id="pto-001",
        scored_turn_id="t1",
        turn=FakeTurn(),
    )

    assert result is None
    assert judge.failures == 1
    # Two `_ask` attempts (the original and the repair), each spending its full rate-limit budget.
    assert model.attempts == 2 * judges.JUDGE_RATE_LIMIT_ATTEMPTS


@pytest.mark.anyio
async def test_a_non_rate_limit_failure_still_buys_exactly_one_repair(monkeypatch):
    """The behaviour §13.7 already specified must be untouched by the 429 path."""

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(judges.asyncio, "sleep", fake_sleep)
    model = ScriptedModel([ProviderError("malformed", status=400)], {"entailed": False, "rationale": "r"})
    judge = _judge(model)

    result = await judge._ask(
        metric="gold_fact_entailment",
        system="s",
        user="u",
        schema=judges.EntailmentVerdict,
        item_id="pto-001",
        scored_turn_id="t1",
        turn=FakeTurn(),
    )

    assert result == {"entailed": False, "rationale": "r"}
    assert judge.rate_limited == 0
    assert model.attempts == 2
    assert model.prompts == [2, 3], "the repair appends the parse error to the conversation"
