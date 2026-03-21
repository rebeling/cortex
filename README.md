# Cortex

Cortex is a small FastAPI service that bootstraps a repository, extracts structured project memory, and stores that memory in Cognee for later semantic retrieval.

## Requirements

- Python 3.10, 3.11, or 3.12
- `cognee==0.5.5`
- An LLM API key supported by Cognee

## Local setup

```bash
uv sync --extra dev
cp .env.example .env
uv run uvicorn app.main:app --reload
```

Set `LLM_API_KEY` in `.env` before using bootstrap, ingest, search, or context endpoints. Cortex now loads `.env` explicitly at startup and passes the configured values through to Cognee.

The local shell in this repo currently defaults to Python 3.14, but the project is pinned to Python 3.10-3.12 because that is the safe overlap for Cognee 0.5.5.

## Environment variables

- `LLM_API_KEY`: required by Cognee.
- `LLM_PROVIDER`: defaults to `openai`.
- `LLM_MODEL`: defaults to `gpt-4o-mini`.
- `VECTOR_DB_PROVIDER`: defaults to `lancedb`.
- `GRAPH_DATABASE_PROVIDER`: defaults to `kuzu`.
- `DATA_ROOT_DIRECTORY`, `SYSTEM_ROOT_DIRECTORY`, `CACHE_ROOT_DIRECTORY`: optional overrides. Omit them unless you need custom locations. If you set them in `.env`, use absolute paths only because Cognee rejects relative values.
- `CORTEX_ALLOWED_ROOTS`: optional comma-separated allowlist for bootstrap paths.
- `CORTEX_SERVICE_DATA_DIR`: local metadata registry for project and session metadata.

## Run the API

```bash
uv run uvicorn app.main:app --reload
```

Or use:

```bash
make start-cortex
```

If `LLM_API_KEY` is missing, the service will still start and `/health` will stay available, but Cognee-backed endpoints will return a configuration error until `.env` is populated.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Example API calls

Bootstrap a repo:

```bash
curl -X POST http://127.0.0.1:8000/projects/bootstrap \
  -H "Content-Type: application/json" \
  -d '{
    "repo_path": "/absolute/path/to/repo"
  }'
```

Ingest memory:

```bash
curl -X POST http://127.0.0.1:8000/memory/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "your-project-id",
    "source_type": "agent_summary",
    "content": "The API layer uses FastAPI and stores memory in Cognee.",
    "file_paths": ["app/main.py"],
    "metadata": {"source": "codex"}
  }'
```

Search memory:

```bash
curl -X POST http://127.0.0.1:8000/memory/search \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "your-project-id",
    "query": "How is memory stored?",
    "top_k": 5
  }'
```

Compose prompt context:

```bash
curl -X POST http://127.0.0.1:8000/memory/context \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "your-project-id",
    "query": "Summarize how Cortex stores project memory",
    "file_paths": ["app/services/cognee_service.py"],
    "top_k": 4
  }'
```

## Bootstrap behavior

First bootstrap creates:

- `.cortex/project.yaml`
- `.cortex/brief.md`
- `.cortex/repo_map.json`
- `.cortex/bootstrap_status.json`

Bootstrap is idempotent. If `.cortex/project.yaml` already exists, Cortex updates derived files as needed and avoids re-storing bootstrap memories.

## Tests

```bash
uv run pytest
```

The test suite uses a fake Cognee service so endpoint behavior can be validated without a live Cognee installation.

## MCP Integration

Cortex exposes an MCP server at `/mcp`. MCP tools are thin adapters over the same shared services used by the REST API.

### Available tools

- `cortex_register(repo_path)`: bootstrap a repo and return a compact summary
- `cortex_push(repo_path, content, file_paths?, source_type?)`: store memory for a repo, auto-bootstrapping if needed
- `cortex_query(repo_path, question, top_k?)`: retrieve a compact prompt-ready memory block

### Example client configuration

```json
{
  "cortex": {
    "url": "http://localhost:8000/mcp"
  }
}
```

### MCP Inspector

```bash
make start-cortex
npx -y @modelcontextprotocol/inspector
```

Connect the inspector to `http://localhost:8000/mcp`.
