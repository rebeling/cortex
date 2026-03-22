# Setup

## Requirements

- Python 3.12
- `cognee==0.5.5`

This project is pinned to Python 3.12.

Cognee is the AI memory engine that powers Cortex's storage and retrieval capabilities. It manages vector embeddings, the knowledge graph, and hybrid search. See [Overview](overview.md) for more details on how Cortex uses Cognee.

## Local Setup

```bash
uv sync --extra dev
cp .env.example .env
uv run uvicorn app.main:app --reload
```

## Environment Variables

These settings are loaded from `.env` by [`app/core/config.py`](/Users/matthias/mr/cortex/app/core/config.py).

- `LLM_API_KEY`: required for Cognee-backed operations.
- `LLM_PROVIDER`: defaults to `openai`.
- `LLM_MODEL`: defaults to `gpt-4o-mini`.
- `VECTOR_DB_PROVIDER`: defaults to `lancedb`.
- `GRAPH_DATABASE_PROVIDER`: defaults to `kuzu`.
- `DATA_ROOT_DIRECTORY`: optional absolute override for Cognee data storage.
- `SYSTEM_ROOT_DIRECTORY`: optional absolute override for Cognee system storage.
- `CACHE_ROOT_DIRECTORY`: optional absolute override for Cognee cache storage.
- `CORTEX_ALLOWED_ROOTS`: optional comma-separated allowlist for bootstrap paths.
- `CORTEX_SERVICE_DATA_DIR`: local registry path for project/session metadata.
- `CORTEX_MAX_SCAN_FILES`: repository scan limit, default `500`.
- `CORTEX_MAX_FILE_SIZE_BYTES`: per-file read limit, default `262144`.
- `CORTEX_LOG_LEVEL`: logging level, default `INFO`.

## Running Cortex

Start the app directly:

```bash
uv run uvicorn app.main:app --reload
```

Or use:

```bash
make start-cortex
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

If `LLM_API_KEY` is missing, the service still starts and `/health` stays available, but Cognee-backed endpoints return configuration errors until `.env` is populated.
