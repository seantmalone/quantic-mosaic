"""`python -m hrmosaic.rag.download_model` — the one network fetch on the push path (spec §15.1).

It runs as its own CI step so that a Hugging Face outage is a named failure in a five-second step
rather than a timeout somewhere inside a 1,800-test suite. Two things about it are load-bearing and
neither is visible from a green run:

* **it retries** — `ATTEMPTS` constructions with `BACKOFF_S` between them, and it returns a non-zero
  exit code only after the last one, so a single flaky fetch cannot block a deploy;
* **`threads=1` on the construction** — constraint 4 and §14.3. Every `TextEmbedding` in this
  project is built with it, this one included, or ONNX sizes a thread pool for a machine the
  container does not have.

The constructor is stubbed here because the point is the retry policy and the arguments, not that
fastembed works: `tests/unit/test_query_embed_is_asymmetric.py` is the test that loads the real
model, and loading a second ONNX session inside the suite would cost §14.3's budget for nothing.
"""

from __future__ import annotations

import pytest

from hrmosaic.rag import download_model
from hrmosaic.settings import settings


@pytest.fixture
def instant_backoff(monkeypatch):
    """Record the sleeps instead of taking them — the policy is asserted, not waited out."""
    slept: list[float] = []
    monkeypatch.setattr(download_model.time, "sleep", slept.append)
    return slept


@pytest.fixture
def cache(tmp_path, monkeypatch):
    directory = tmp_path / "fastembed"
    monkeypatch.setattr(settings, "fastembed_cache_path", directory)
    return directory


def constructions(monkeypatch, failures: int) -> list[dict]:
    """Stand in for `TextEmbedding`, failing the first `failures` constructions."""
    recorded: list[dict] = []

    def build(**kwargs):
        recorded.append(kwargs)
        if len(recorded) <= failures:
            raise RuntimeError("Hugging Face is unreachable")
        return object()

    monkeypatch.setattr(download_model, "TextEmbedding", build)
    return recorded


def test_a_warm_cache_is_one_construction_with_the_single_thread_the_container_has(
    monkeypatch, cache, instant_backoff, capsys
):
    recorded = constructions(monkeypatch, failures=0)

    assert download_model.main() == 0

    assert recorded == [{"model_name": settings.embed_model, "cache_dir": str(cache), "threads": 1}]
    assert cache.is_dir(), "the cache directory is created before the fetch, not by it"
    assert instant_backoff == []
    assert str(cache) in capsys.readouterr().out


def test_a_single_flaky_fetch_is_retried_rather_than_failing_the_push(monkeypatch, cache, instant_backoff, capsys):
    recorded = constructions(monkeypatch, failures=download_model.ATTEMPTS - 1)

    assert download_model.main() == 0

    assert len(recorded) == download_model.ATTEMPTS
    assert instant_backoff == [download_model.BACKOFF_S] * (download_model.ATTEMPTS - 1)
    captured = capsys.readouterr()
    assert captured.err.count("Hugging Face is unreachable") == download_model.ATTEMPTS - 1
    assert f"attempt 1/{download_model.ATTEMPTS} failed" in captured.err


def test_an_upstream_outage_exits_non_zero_after_the_last_attempt_and_never_sleeps_again(
    monkeypatch, cache, instant_backoff, capsys
):
    recorded = constructions(monkeypatch, failures=download_model.ATTEMPTS)

    assert download_model.main() == 1

    assert len(recorded) == download_model.ATTEMPTS
    assert instant_backoff == [download_model.BACKOFF_S] * (download_model.ATTEMPTS - 1)
    assert f"attempt {download_model.ATTEMPTS}/{download_model.ATTEMPTS} failed" in capsys.readouterr().err
