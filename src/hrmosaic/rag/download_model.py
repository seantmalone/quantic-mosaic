"""Populate the fastembed model cache before anything needs it (spec §15.1).

The first CI run is always a cache miss, so this runs as its own step ahead of the suite:
`actions/cache` restores `.cache/fastembed`, and on a miss this is the one network fetch on
the push path. Hugging Face is retried twice before the step is allowed to fail.
"""

from __future__ import annotations

import sys
import time

from fastembed import TextEmbedding

from hrmosaic.settings import settings

ATTEMPTS = 3
BACKOFF_S = 5


def main() -> int:
    cache = settings.fastembed_cache_path
    cache.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, ATTEMPTS + 1):
        try:
            # `threads=1` on every construction, as `rag/embed.py` does: the single-core
            # container of §14.3 must not have ONNX spawn a thread pool behind its back.
            TextEmbedding(model_name=settings.embed_model, cache_dir=str(cache), threads=1)
        except Exception as error:  # any transport or filesystem failure here is retryable
            print(f"attempt {attempt}/{ATTEMPTS} failed: {error}", file=sys.stderr)
            if attempt == ATTEMPTS:
                return 1
            time.sleep(BACKOFF_S)
        else:
            print(f"fastembed model {settings.embed_model} is cached in {cache}")
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
