# MCP

Cortex exposes an MCP server at `/mcp`.

The MCP server is implemented in [`app/mcp_server.py`](/Users/matthias/mr/cortex/app/mcp_server.py) and is mounted into the FastAPI app in [`app/main.py`](/Users/matthias/mr/cortex/app/main.py).

## Available Tools

### `cortex_register(repo_path)`

Bootstraps a repository and returns a compact registration payload.

Example shape:

```json
{
  "ok": true,
  "project_id": "...",
  "summary": "...",
  "stored_memory_count": 3
}
```

### `cortex_push(repo_path, content, file_paths?, source_type?)`

Stores memory for a repository. If the repo is not yet registered, Cortex bootstraps it first.

Example shape:

```json
{
  "ok": true,
  "project_id": "...",
  "session_id": "...",
  "stored_count": 2
}
```

### `cortex_query(repo_path, question, top_k?)`

Retrieves a prompt-ready memory block for a repository question. If the repo is not yet registered, Cortex bootstraps it first.

Example shape:

```json
{
  "ok": true,
  "project_id": "...",
  "memory_block": "...",
  "results": []
}
```

## Error Responses

MCP tools return tool-level payloads instead of HTTP status codes.

Example:

```json
{
  "ok": false,
  "error": "project not found"
}
```

## Client Configuration

```json
{
  "cortex": {
    "url": "http://localhost:8000/mcp"
  }
}
```

## MCP Inspector

```bash
make start-cortex
npx -y @modelcontextprotocol/inspector
```

Connect the inspector to `http://localhost:8000/mcp`.
