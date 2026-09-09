"""`EMBED_PROVIDER=fake` — the deterministic hash embedder (spec §6.4).

384 dimensions, unit norm, and **identical across two interpreter runs**: it hashes bytes rather than
consulting `hash()`, which is salted per process, so a fake index built in one process is readable in
another and a unit test never loads ONNX.
"""

from __future__ import annotations

import json
import subprocess
import sys

from hrmosaic.rag.embed import FAKE_MODEL_NAME, QUERY_PREFIX, embed_passages, embed_query, model_name

SAMPLE = "How many consecutive days abroad require Tax & Legal review?"

_CHILD = (
    "import json;"
    "from hrmosaic.settings import settings;"
    "settings.embed_provider = 'fake';"
    "from hrmosaic.rag.embed import embed_passages;"
    f"print(json.dumps(embed_passages([{SAMPLE!r}])[0]))"
)


def test_the_fake_vector_is_384_dimensional_and_unit_norm(fake_embedder):
    vector = embed_passages([SAMPLE])[0]
    assert len(vector) == 384
    assert abs(sum(value * value for value in vector) ** 0.5 - 1.0) < 1e-9


def test_the_fake_embedder_is_identical_across_two_interpreter_runs(fake_embedder):
    first = embed_passages([SAMPLE])[0]
    completed = subprocess.run([sys.executable, "-c", _CHILD], capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout) == first


def test_batching_does_not_change_a_vector(fake_embedder):
    texts = [f"{SAMPLE} {index}" for index in range(20)]
    assert embed_passages(texts) == [embed_passages([text])[0] for text in texts]
    assert embed_passages([]) == []


def test_the_fake_embedder_is_asymmetric_like_the_real_one(fake_embedder):
    assert embed_query(SAMPLE) != embed_passages([SAMPLE])[0]
    assert embed_query(SAMPLE) == embed_passages([QUERY_PREFIX + SAMPLE])[0]


def test_a_fake_index_is_stamped_so_the_guard_can_reject_it(fake_embedder):
    assert model_name() == FAKE_MODEL_NAME == "fake-hash-384"
