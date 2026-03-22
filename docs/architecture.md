# Architecture

## High-Level Shape

Cortex is a FastAPI application with a shared service layer. REST routes, the UI, and MCP all reuse the same underlying services instead of duplicating memory logic.

Key wiring lives in [`app/main.py`](/Users/matthias/mr/cortex/app/main.py).

## Main Components

### FastAPI Layer

Routes are split by concern:

- [`app/api/routes/projects.py`](/Users/matthias/mr/cortex/app/api/routes/projects.py)
- [`app/api/routes/memory.py`](/Users/matthias/mr/cortex/app/api/routes/memory.py)
- [`app/api/routes/graph.py`](/Users/matthias/mr/cortex/app/api/routes/graph.py)

### Service Layer

- [`app/services/bootstrap_service.py`](/Users/matthias/mr/cortex/app/services/bootstrap_service.py)
  Handles repo validation, scanning, bootstrap files, and project bootstrap lifecycle.
- [`app/services/memory_service.py`](/Users/matthias/mr/cortex/app/services/memory_service.py)
  Owns ingest, search, context, and chat orchestration.
- [`app/services/extraction_service.py`](/Users/matthias/mr/cortex/app/services/extraction_service.py)
  Extracts structured memory items from repository scans and user-provided content.
- [`app/services/retrieval_service.py`](/Users/matthias/mr/cortex/app/services/retrieval_service.py)
  Normalizes and ranks Cognee retrieval results.
- [`app/services/context_service.py`](/Users/matthias/mr/cortex/app/services/context_service.py)
  Builds prompt-ready context blocks from retrieval results.
- [`app/services/chat_service.py`](/Users/matthias/mr/cortex/app/services/chat_service.py)
  Produces grounded answers from retrieved memory.
- [`app/services/cognee_service.py`](/Users/matthias/mr/cortex/app/services/cognee_service.py)
  Wraps Cognee storage, search, graph sync, and visualization behavior.
- [`app/services/project_registry_service.py`](/Users/matthias/mr/cortex/app/services/project_registry_service.py)
  Stores local project/session/fingerprint metadata.

### UI Layer

The app serves:

- a static asset bundle from [`app/static`](/Users/matthias/mr/cortex/app/static)
- Jinja templates from [`app/templates`](/Users/matthias/mr/cortex/app/templates)

### MCP Layer

[`app/mcp_server.py`](/Users/matthias/mr/cortex/app/mcp_server.py) exposes MCP tools as thin adapters over the same bootstrap and memory services used by REST.

## Data Flow

### Bootstrap Flow

1. Validate an absolute repository path.
2. Scan candidate files while respecting size and directory exclusions.
3. Detect languages, frameworks, entrypoints, and important folders.
4. Write `.cortex` metadata files.
5. Extract and store foundational memory in Cognee.
6. Update project registry state.

### Ingest Flow

1. Resolve project and session.
2. Extract memory items from the request payload.
3. Deduplicate using stored fingerprints.
4. Store new memory in Cognee.
5. Mark the graph dirty and increment stored memory count.

### Search / Context / Chat Flow

1. Resolve project.
2. Sync the graph first if it is marked dirty.
3. Search Cognee-backed memory.
4. Rank and normalize results.
5. Return results directly, build a memory block, or generate a chat answer.

### Graph Flow

1. Read graph state from the project record.
2. Sync if the graph is dirty.
3. Generate or return the visualization artifact.
4. Return either graph edges/nodes or an HTML visualization.
