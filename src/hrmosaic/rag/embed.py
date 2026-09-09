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

import hashlib
import math

from hrmosaic.settings import settings

EMBED_BATCH_SIZE = 8

#: bge-small's published query instruction.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

#: What `index_meta.query_convention` records — `fastembed.query_embed` if the library prefixes for
#: us, `prefix:<literal>` if we do. See the module docstring for the measurement behind this value.
QUERY_CONVENTION = f"prefix:{QUERY_PREFIX}"

#: `index_meta.embed_model` for an index built with `EMBED_PROVIDER=fake`.
FAKE_MODEL_NAME = "fake-hash-384"

_model = None


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


def embed_query(text: str) -> list[float]:
    """Embed one question. The asymmetric half: the prefix of `QUERY_CONVENTION` is applied here."""
    if settings.embed_provider == "fake":
        return _fake_embed(QUERY_PREFIX + text)
    return [vector.tolist() for vector in _get_model().embed([QUERY_PREFIX + text], batch_size=EMBED_BATCH_SIZE)][0]
