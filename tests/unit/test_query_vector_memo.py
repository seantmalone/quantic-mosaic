"""The query-vector memo of the performance plan's W1-B (`rag/embed.py` only).

`search_policy_documents._blocking_search` calls `retrieve()` a **second** time with the identical
query string whenever `backfill_reason_for()` fires, and sums both embeds into one `embed_ms`. 22 of
28 deployed retrievals backfill, and backfilled `embed_ms` p50 is 679 ms against 390 ms for the six
that do not: the second embed is the whole difference and it recomputes a vector the process has
just produced.

So `embed_query` memoises on `(model, convention, dim, text)`. Three properties are what make that
safe rather than merely fast, and each has a test below:

* the key carries **every input the vector depends on** — `model_name()` collapses every fake
  configuration onto `fake-hash-384` while `_fake_embed` reads `settings.embed_dim`, so a dim change
  would otherwise be invisible to the guard the key advertises;
* the caller gets a **copy**, because a list handed out of an LRU is the cache's own object and one
  in-place `sort()` downstream would poison every later hit;
* the cache is **small** (16). The win is intra-call: 22 intra-call hits against 2 cross-call over
  28 spans, and 256 entries would hold 3.16 MB and 256 raw user queries on a 512 MB instance.
"""

from __future__ import annotations

import threading

import pytest

from hrmosaic.rag import embed


@pytest.fixture(autouse=True)
def _counted():
    """Each test starts from an empty cache and its own hit/miss counts."""
    embed.clear_query_cache()


def _hashes(monkeypatch) -> list[str]:
    """Record every text that actually reaches the embedder."""
    seen: list[str] = []
    real = embed._fake_embed

    def counting(text: str) -> list[float]:
        seen.append(text)
        return real(text)

    monkeypatch.setattr(embed, "_fake_embed", counting)
    return seen


def test_the_same_query_embeds_once(fake_embedder, monkeypatch):
    seen = _hashes(monkeypatch)

    first = embed.embed_query("How many days abroad need Tax & Legal review?")
    second = embed.embed_query("How many days abroad need Tax & Legal review?")

    assert first == second
    assert len(seen) == 1, seen


def test_a_different_query_is_a_miss(fake_embedder, monkeypatch):
    seen = _hashes(monkeypatch)

    embed.embed_query("one question")
    embed.embed_query("another question")

    assert len(seen) == 2


def test_the_embedding_dimension_is_part_of_the_key(fake_embedder, monkeypatch):
    """`model_name()` says `fake-hash-384` whatever `EMBED_DIM` is; the vector does not."""
    from hrmosaic.settings import settings

    seen = _hashes(monkeypatch)
    first = embed.embed_query("same text")
    monkeypatch.setattr(settings, "embed_dim", 128)
    second = embed.embed_query("same text")

    assert len(seen) == 2, "a dimension change must not be served from the cache"
    assert len(first) == 384 and len(second) == 128


@pytest.mark.parametrize("member", ["model_name", "QUERY_CONVENTION"])
def test_the_model_and_the_convention_are_part_of_the_key(fake_embedder, monkeypatch, member):
    """A model roll, or a fastembed release that starts prefixing for us, must not be served stale."""
    seen = _hashes(monkeypatch)
    embed.embed_query("same text")
    monkeypatch.setattr(
        embed, member, (lambda: "some/other-model") if member == "model_name" else "fastembed.query_embed"
    )
    embed.embed_query("same text")

    assert len(seen) == 2


def test_the_caller_gets_a_copy_it_may_mutate(fake_embedder):
    first = embed.embed_query("a query")
    first[0] = 99.0

    assert embed.embed_query("a query")[0] != 99.0, "the cached vector was handed out by reference"


def test_the_cache_is_small_enough_for_a_512mb_instance():
    assert embed._embed_query_cached.cache_parameters()["maxsize"] == 16


def test_clearing_the_cache_forgets_everything(fake_embedder, monkeypatch):
    seen = _hashes(monkeypatch)
    embed.embed_query("a query")
    embed.clear_query_cache()
    embed.embed_query("a query")

    assert len(seen) == 2


# --------------------------------------------------------------------------------------
# The measurement hook
# --------------------------------------------------------------------------------------
#
# The lever's own p50 saving is not measurable from a 26-item run p50 — whether the median-rank turn
# happens to carry a backfilled retrieval is luck, and the bootstrap CI runs [0, 480] ms because of
# it. So the invariant is asserted at the span, not at the run: the second `retrieve()` of a
# backfilled search must be served from the memo, and the `retrieval` span says whether it was.


def test_a_retrieval_says_whether_its_query_vector_came_from_the_memo(fake_embedder, mini_index):
    from hrmosaic.rag.retrieve import retrieve

    first = retrieve("annual leave", connection=mini_index)
    second = retrieve("annual leave", connection=mini_index)

    assert first.embed_cache_hit is False, "the first embed of a query is always real work"
    assert second.embed_cache_hit is True, "the backfill's second pass costs no embed"


def test_the_retrieval_payload_carries_the_flag():
    from hrmosaic.core.models import RetrievalPayload

    assert RetrievalPayload(query="q", k=5, k_source="default", strategy="hybrid_rrf").embed_cache_hit is False


# --------------------------------------------------------------------------------------
# The hit flag is decided inside the call (P15 item 0)
# --------------------------------------------------------------------------------------
#
# `retrieve()` runs under `asyncio.to_thread`, so two retrievals are genuinely concurrent threads.
# Deriving `embed_cache_hit` by diffing the process-global LRU hit counter before and after
# `embed_query` therefore stamps another thread's hit onto a span whose embed was real work — the
# flag would say "free" about the 390 ms the span is there to report. `embed_query_with_meta`
# decides inside the same call instead.


def test_the_embed_reports_its_own_hit(fake_embedder):
    vector, cache_hit = embed.embed_query_with_meta("a question")
    again, second_hit = embed.embed_query_with_meta("a question")

    assert (cache_hit, second_hit) == (False, True)
    assert vector == again
    assert embed.embed_query("a question") == vector, "the plain call is the same vector"


def test_two_interleaved_lookups_attribute_their_hits_correctly(fake_embedder, monkeypatch):
    """A hit taken by another thread mid-embed must not be reported as this call's hit."""
    embed.embed_query("already cached")

    inside = threading.Event()
    release = threading.Event()
    real = embed._fake_embed

    def slow(text: str) -> list[float]:
        if text.endswith("fresh question"):
            inside.set()
            assert release.wait(timeout=5), "the main thread never released the embed"
        return real(text)

    monkeypatch.setattr(embed, "_fake_embed", slow)

    seen: dict[str, bool] = {}
    fresh = threading.Thread(target=lambda: seen.__setitem__("fresh", embed.embed_query_with_meta("fresh question")[1]))
    cached = threading.Thread(
        target=lambda: seen.__setitem__("cached", embed.embed_query_with_meta("already cached")[1])
    )

    fresh.start()
    assert inside.wait(timeout=5), "the slow embed never started"
    cached.start()
    cached.join(timeout=0.25)  # the memo lookup is serialised against the embed in flight
    release.set()
    fresh.join(timeout=5)
    cached.join(timeout=5)

    assert seen == {"fresh": False, "cached": True}
