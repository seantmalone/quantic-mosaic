# Mosaic HR Copilot — the one image (spec §14.2).
#
# Two things happen at BUILD time that must never happen at boot on a 0.1-CPU free instance:
# the fastembed ONNX model is baked into the image (~64 MB, otherwise a 16–63 s download on the
# first query) and the sqlite-vec + FTS5 index is built from the committed corpus and verified
# against the committed chunk manifest. A cold start therefore only has to mmap and open files.
#
# The build also *proves* two `.dockerignore` negations against Docker's own matcher: the
# `COPY tests/fixtures/llm_scripts/` and `COPY data/index/chunks.manifest.jsonl` lines below fail
# the build outright if `!tests/fixtures/llm_scripts/` or `!data/index/chunks.manifest.jsonl` ever
# stops re-including its path, and the `RUN test -f` after them fails if the paths arrive empty.
FROM python:3.12-slim
ARG GIT_SHA=dev
WORKDIR /app

# OMP_NUM_THREADS is honoured by ONNX Runtime's OpenMP layer and stays. ORT_INTRA/INTER_OP_NUM_THREADS
# are deliberately absent: ORT does not read them; pools are sized via TextEmbedding(threads=1).
# PYTHON is read by `mcp/run_stdio.sh` and `mcp/run_http.sh`, whose default is the developer's
# `.venv/bin/python` — a path that does not exist in this image (spec §8.1, P5 carry-forward).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 \
    FASTEMBED_CACHE_PATH=/app/models \
    PYTHONPATH=/app/src:/app \
    PYTHON=python \
    GIT_SHA=$GIT_SHA

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the ONNX model into the image (~64 MB): a cold start must never download it.
RUN python -c "from fastembed import TextEmbedding; \
    TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/app/models')"

# `src/` carries the Jinja templates and the vendored static assets as well as the Python
# packages; nothing here is a wheel install, so `PYTHONPATH=/app/src` is what makes
# `hrmosaic.web.templates` and `hrmosaic.web.static` resolve inside the container (P9
# carry-forward — `pyproject.toml` declares both as package data for the non-editable case).
COPY src/ src/
COPY mcp/ mcp/
COPY corpus/ corpus/
COPY mock_data/ mock_data/
COPY evaluation/ evaluation/
COPY tests/fixtures/llm_scripts/ tests/fixtures/llm_scripts/
COPY data/index/chunks.manifest.jsonl data/index/
RUN test -f tests/fixtures/llm_scripts/demo_task_1.json \
    && test -f data/index/chunks.manifest.jsonl \
    && test -f src/hrmosaic/web/templates/chat.html \
    && test -f src/hrmosaic/web/static/app.css \
    && test -f src/hrmosaic/agent/prompts/act.j2

# Build the index at BUILD time on the 2-CPU builder, never at boot, verifying the chunking.
RUN python -m hrmosaic.rag.ingest --verify-manifest && python -m hrmosaic.rag.index --selftest

EXPOSE 8000
# sh -c so ${PORT} is expanded by the shell at run time — Render injects it.
CMD ["sh", "-c", "uvicorn hrmosaic.web.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
