PYTHON ?= 3.12
UV_CACHE_DIR ?= .uv-cache
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: start-cortex

start-cortex:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run --python $(PYTHON) uvicorn app.main:app --host $(HOST) --port $(PORT) --reload
