"""The only module in the project that touches fastembed (spec §6.4, §4.2).

Three footguns are closed here and nowhere else, all measured in the P0 probe:

* `batch_size=EMBED_BATCH_SIZE` (8) on **every** call — the default peaked at 1,477 MB RSS against
  334 MB at 8, and the deployed instance has 512 MB;
* `threads=1` on construction — ONNX Runtime sizes its pools from it, and 0.1 CPU cannot use more;
* the `parallel` keyword **never** — passing it hung indefinitely in two separate 600 s runs.

`tests/architecture/test_conventions.py` greps for the call site and for that keyword, so a later phase
cannot reintroduce any of the three quietly.

**The query convention is a measurement, not an assumption.** bge-small is asymmetric: a query carries
an instruction prefix, a passage does not. Measured on 2026-09-09 with fastembed 0.8.0, `query_embed`
returns a vector *identical* to `embed` for `BAAI/bge-small-en-v1.5` — it delegates — so `embed_query`
applies the literal prefix itself and `index_meta.query_convention` records `prefix:<literal>`.
`tests/unit/test_query_embed_is_asymmetric.py` is what holds that branch honest: it fails if a future
release starts prefixing on our behalf, at which point the convention string changes and the index is
rebuilt (the `open_index()` mismatch guard refuses to serve the old one against the new convention).

`EMBED_PROVIDER=fake` selects `_fake_embed()`, a deterministic hash embedder, for unit tests and the
offline ingest smoke only. It stamps `index_meta.embed_model = fake-hash-384`, which the mismatch guard
rejects at runtime, so a fake index can never answer a real question.
"""

from __future__ import annotations

import functools
import hashlib
import math
import threading

from hrmosaic.settings import settings

EMBED_BATCH_SIZE = 8

#: How many distinct query vectors the memo below keeps. Sixteen, not 256: the win it exists for is
#: **intra-call** — `search_policy_documents._blocking_search` calls `retrieve()` a second time with
#: the identical query string whenever the backfill fires, and 22 of 28 deployed retrievals
#: backfilled against 2 cross-call repeats and 0 within-turn query repeats. A 256-entry cache would
#: hold 3.16 MB of float lists on a 512 MB instance and keep 256 raw user queries alive for the
#: process lifetime, for two more hits.
QUERY_CACHE_SIZE = 16

#: bge-small's published query instruction.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

#: What `index_meta.query_convention` records — `fastembed.query_embed` if the library prefixes for
#: us, `prefix:<literal>` if we do. See the module docstring for the measurement behind this value.
QUERY_CONVENTION = f"prefix:{QUERY_PREFIX}"

#: `index_meta.embed_model` for an index built with `EMBED_PROVIDER=fake`.
FAKE_MODEL_NAME = "fake-hash-384"

_model = None

#: Guards the memo lookup so `embed_query_with_meta` can attribute a hit to the call that took it.
_query_lock = threading.Lock()


def model_name() -> str:
    """The value this configuration writes into `index_meta.embed_model`."""
    return FAKE_MODEL_NAME if settings.embed_provider == "fake" else settings.embed_model


def _get_model():
    """The process-wide `TextEmbedding`, constructed on first use so boot never loads ONNX."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(
            model_name=settings.embed_model,
            cache_dir=str(settings.fastembed_cache_path),
            threads=1,
        )
    return _model


def _fake_embed(text: str) -> list[float]:
    """A deterministic 384-dimension hash embedder: sha256 blocks, L2-normalised.

    Deterministic across interpreter runs and machines — it hashes bytes rather than reading
    `hash()`, which is salted per process.
    """
    dim = settings.embed_dim
    raw = bytearray()
    counter = 0
    while len(raw) < dim * 2:
        raw += hashlib.sha256(f"{counter}|{text}".encode()).digest()
        counter += 1
    values = [int.from_bytes(raw[index * 2 : index * 2 + 2], "big") / 32768.0 - 1.0 for index in range(dim)]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Embed chunk text for storage. Passages carry no instruction prefix."""
    if not texts:
        return []
    if settings.embed_provider == "fake":
        return [_fake_embed(text) for text in texts]
    return [vector.tolist() for vector in _get_model().embed(texts, batch_size=EMBED_BATCH_SIZE)]


@functools.lru_cache(maxsize=QUERY_CACHE_SIZE)
def _embed_query_cached(model: str, convention: str, embed_dim: int, text: str) -> list[float]:
    """The memoised half of `embed_query`. **Never call this directly** — it hands out its own list.

    Every input the vector depends on is in the key, including `embed_dim`, which is not decoration:
    `model_name()` collapses every fake-provider configuration onto `fake-hash-384` while
    `_fake_embed` reads `settings.embed_dim`, so a dimension change would otherwise be invisible to
    the very key that is advertised as the staleness guard. `convention` is in the key for the same
    reason — a fastembed release that starts applying the query prefix for us changes the vector
    without changing the model id (see the module docstring).
    """
    if settings.embed_provider == "fake":
        return _fake_embed(QUERY_PREFIX + text)
    return [vector.tolist() for vector in _get_model().embed([QUERY_PREFIX + text], batch_size=EMBED_BATCH_SIZE)][0]


def clear_query_cache() -> None:
    """Forget every memoised query vector. The seam an autouse test fixture uses (`tests/conftest.py`).

    A process-wide LRU makes an embed count order-dependent across a whole test session, and a test
    that asserts "this embedded once" would pass vacuously against a cache some earlier test filled.
    """
    with _query_lock:
        _embed_query_cached.cache_clear()


def embed_query_with_meta(text: str) -> tuple[list[float], bool]:
    """The vector **and** whether the memo served it, decided inside this one call.

    `RetrievalResult.embed_cache_hit` used to be derived by `retrieve()` diffing the LRU's
    process-global hit counter around `embed_query`. `retrieve()` runs under `asyncio.to_thread`,
    so two retrievals are genuinely concurrent threads and that diff attributes **another**
    thread's hit to this one: a span whose embed was 390 ms of real ONNX work reports the work as
    free, and the one number W1-B is measured by stops describing the call it sits on.

    The lock is held across the embed itself, not only across the counter reads. That is the point
    of it twice over: it makes the pair (`hits` before, `hits` after) belong to this call, and two
    threads asking for the same vector then cost one ONNX run rather than two — which is what a
    512 MB / 0.1 CPU instance wants regardless.

    The caller gets a **copy**: the list inside an LRU entry is the cache's own object, and one
    `sort()` or in-place scale downstream would poison every later hit for the lifetime of the
    process.
    """
    with _query_lock:
        before = _embed_query_cached.cache_info().hits
        vector = _embed_query_cached(model_name(), QUERY_CONVENTION, settings.embed_dim, text)
        cache_hit = _embed_query_cached.cache_info().hits > before
    return list(vector), cache_hit


def embed_query(text: str) -> list[float]:
    """Embed one question. The asymmetric half: the prefix of `QUERY_CONVENTION` is applied here."""
    return embed_query_with_meta(text)[0]
