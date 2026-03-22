# API

## Health

`GET /health`

Returns a simple status payload:

```json
{"status":"ok"}
```

## Projects

### List Projects

`GET /projects`

Returns the registered projects known to Cortex.

### Create Project

`POST /projects`

Creates an empty project record without bootstrapping a repository.

Example:

```bash
curl -X POST http://127.0.0.1:8000/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-project"
  }'
```

### Bootstrap a Repository

`POST /projects/bootstrap`

Bootstraps a repository, scans it, creates `.cortex` metadata, and stores foundational memory.

Example:

```bash
curl -X POST http://127.0.0.1:8000/projects/bootstrap \
  -H "Content-Type: application/json" \
  -d '{
    "repo_path": "/absolute/path/to/repo"
  }'
```

### Get Project Details

`GET /projects/{project_id}`

Returns the project record, current bootstrap status payload, and which `.cortex` files exist.

## Memory

### Ingest Memory

`POST /memory/ingest`

Adds structured memory for a project.

Example:

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

### Search Memory

`POST /memory/search`

Returns ranked retrieval results for a project query.

Example:

```bash
curl -X POST http://127.0.0.1:8000/memory/search \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "your-project-id",
    "query": "How is memory stored?",
    "top_k": 5
  }'
```

### Compose Context

`POST /memory/context`

Builds a prompt-ready memory block from retrieval results.

Example:

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

### Chat

`POST /memory/chat`

Answers a question using retrieved memory. When OpenAI is configured, Cortex can ask the model for a grounded answer. Otherwise it falls back to a deterministic memory-based answer.

Example:

```bash
curl -X POST http://127.0.0.1:8000/memory/chat \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "your-project-id",
    "query": "How does authentication work?",
    "top_k": 6
  }'
```

## Graph

### Get Graph Data

`GET /graph/{project_id}`

Returns graph nodes and edges for visualization clients.

### Sync Graph

`POST /graph/{project_id}/sync`

Forces a graph sync and clears the project's dirty-graph flag.

### Get Graph Visualization

`GET /graph/{project_id}/visualization`

Returns an HTML visualization artifact. If the graph is dirty or the artifact is stale, Cortex syncs and regenerates it first.

## Error Behavior

Common error patterns:

- `404` when a project does not exist
- `422` when a bootstrap repo path is invalid
- `500` for Cognee/config/runtime failures
