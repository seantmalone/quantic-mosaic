# POSIX sh + `python -m` only, so CI runs the same targets a developer runs and any
# macOS-ism fails immediately. Every target assumes the venv of `make setup`.
SHELL := /bin/sh
PYTHON ?= python3.12
VENV ?= .venv
BIN := $(VENV)/bin
PORT ?= 8000
HOST ?= 127.0.0.1
GIT_SHA ?= $(shell git rev-parse HEAD 2>/dev/null || echo dev)
IMAGE ?= mosaic-hr
BASE_URL ?= http://$(HOST):$(PORT)

.PHONY: setup run run-stdio lint test ingest eval ablation demo1 demo2 docker docker-run-512

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt -r requirements-dev.txt
	$(BIN)/pip install -e .

run:
	$(BIN)/uvicorn hrmosaic.web.main:app --host $(HOST) --port $(PORT) --workers 1

run-stdio:
	$(BIN)/python mcp/server_entrypoint.py --stdio

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

test:
	$(BIN)/pytest -q

ingest:
	$(BIN)/python -m hrmosaic.rag.ingest

eval:
	$(BIN)/python -m evaluation.runner --variant baseline

ablation:
	$(BIN)/python -m evaluation.ablation

# Each demo target starts its own server with its own stub script, waits for /health,
# runs the curl script and always stops the server again.
define demo
	set -e; \
	LLM_PROVIDER=stub LLM_STUB_SCRIPT=tests/fixtures/llm_scripts/$(1).json \
	  $(BIN)/uvicorn hrmosaic.web.main:app --host $(HOST) --port $(PORT) --workers 1 & \
	server=$$!; \
	trap 'kill $$server 2>/dev/null || true' EXIT INT TERM; \
	$(BIN)/python scripts/wait_for_health.py --url $(BASE_URL) --timeout 120; \
	BASE_URL=$(BASE_URL) sh scripts/$(1).sh
endef

demo1:
	@$(call demo,demo_task_1)

demo2:
	@$(call demo,demo_task_2)

docker:
	docker build -t $(IMAGE) --build-arg GIT_SHA=$(GIT_SHA) .

# The memory gate (§14.3): APP_ENV stays local, so the access gate is on only because
# APP_ACCESS_TOKEN is set — exactly as in the CI docker job. `--memory-swap` equal to `-m` means
# the container cannot buy headroom back as swap, so 512 MB is a hard ceiling and not a hint.
#
# Poll /ready (not just /health) so the ONNX session is resident before anything is measured,
# serve one stubbed turn over `Authorization: Bearer`, and only then read `/health.app.rss_mb`.
# The trap is what stops a failed assertion from leaving a container holding the port.
MEMORY_CEILING_MB ?= 420
docker-run-512:
	@set -e; \
	docker run --rm -d --name $(IMAGE)-512 -m 512m --memory-swap 512m \
	  -e LLM_PROVIDER=stub -e PORT=$(PORT) -e APP_ACCESS_TOKEN=local-memory-gate \
	  -p $(PORT):$(PORT) $(IMAGE); \
	trap 'docker rm -f $(IMAGE)-512 >/dev/null 2>&1 || true' EXIT INT TERM; \
	$(BIN)/python scripts/wait_for_health.py --url $(BASE_URL) --timeout 300 --ready; \
	curl -fsS -o /dev/null -X POST $(BASE_URL)/chat \
	  -H 'Authorization: Bearer local-memory-gate' -H 'Content-Type: application/json' \
	  -d '{"message":"How many days of paid time off do I accrue each year?"}'; \
	$(BIN)/python scripts/assert_health.py --url $(BASE_URL) --max-rss-mb $(MEMORY_CEILING_MB)
