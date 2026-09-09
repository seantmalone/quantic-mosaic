"""The asymmetry check is a test, not an assumption (spec §6.4).

bge-small is asymmetric: a query carries an instruction prefix, a passage does not. Some fastembed
releases implement that in `query_embed`; **0.8.0 delegates `query_embed` to `embed`**, so the two
return identical vectors and the prefix has to be applied by `embed_query` itself.

This test asserts the contract that must hold either way — `embed_query` and `embed_passages` differ
for the same string — and pins `QUERY_CONVENTION` to whichever branch the installed library actually
takes. If a future release starts prefixing on our behalf, this fails, the convention string changes
and the index is rebuilt: `open_index()`'s guard compares `index_meta.query_convention` with the
running one, so a silent switch cannot serve a query embedded one way against passages embedded the
other.

The branch taken and the measured fastembed version are recorded in `CHANGELOG.md`.

This is the one unit test that loads the real ONNX model. CI runs
`python -m hrmosaic.rag.download_model` before `pytest`, so the cache is warm.
"""

from __future__ import annotations

from importlib.metadata import version

from hrmosaic.rag import embed

SAMPLE = "How many consecutive days abroad require Tax & Legal review?"

#: The pin of `constraints.md`. A bump has to re-measure the branch below, so it is asserted here
#: rather than left as a comment.
FASTEMBED_VERSION = "0.8.0"


def test_fastembed_is_the_pinned_version():
    assert version("fastembed") == FASTEMBED_VERSION


def test_a_query_and_a_passage_embedding_of_one_string_differ():
    passage = embed.embed_passages([SAMPLE])[0]
    query = embed.embed_query(SAMPLE)
    assert len(passage) == len(query) == 384
    assert query != passage


def test_the_recorded_query_convention_is_the_branch_the_library_forces():
    model = embed._get_model()
    delegates = (
        list(model.query_embed([SAMPLE], batch_size=embed.EMBED_BATCH_SIZE))[0].tolist()
        == list(model.embed([SAMPLE], batch_size=embed.EMBED_BATCH_SIZE))[0].tolist()
    )
    if delegates:
        assert embed.QUERY_CONVENTION == f"prefix:{embed.QUERY_PREFIX}"
        assert embed.embed_query(SAMPLE) == embed.embed_passages([embed.QUERY_PREFIX + SAMPLE])[0]
    else:  # pragma: no cover - reached only when a future release prefixes on our behalf
        assert embed.QUERY_CONVENTION == "fastembed.query_embed"


def test_a_passage_vector_is_unit_norm():
    vector = embed.embed_passages([SAMPLE])[0]
    assert abs(sum(value * value for value in vector) ** 0.5 - 1.0) < 1e-5
