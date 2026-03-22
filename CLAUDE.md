# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cortex is a FastAPI application that provides a project-memory layer for agentic coding. It scans repositories, extracts structured memory, stores it in Cognee, and exposes retrieval, chat, graph, and MCP workflows.

## Essential Commands

### Development Setup

```bash
uv sync --extra dev
cp .env.example .env
# Edit .env and set LLM_API_KEY for Cognee-backed features
```

### Running the Application

```bash
# Start server with auto-reload
uv run uvicorn app.main:app --reload

# Or use Makefile
make start-cortex
```

### Testing

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_bootstrap.py

# Run single test
uv run pytest tests/test_bootstrap.py::test_bootstrap_success -v
```

## Architecture

### Service Layer Pattern

The application uses a shared service layer accessed by three interfaces: REST API, UI (Jinja templates), and MCP. All interfaces reuse the same services—never duplicate logic across interfaces.

Services are instantiated in `app/main.py:create_app()` and attached to `app.state`. Routes and MCP tools access services via `request.app.state` or `app_state` parameter.

### Dependency Flow

```
Bootstrap Service → extraction_service, cognee_service, registry_service
Memory Service → registry_service, bootstrap_service, extraction_service, cognee_service, retrieval_service, context_service, chat_service
```

Memory Service is the main orchestrator. It coordinates ingest, search, context, and chat workflows by delegating to specialized services.

### State Management

Project and session metadata is stored locally via `ProjectRegistryService` in the `CORTEX_SERVICE_DATA_DIR` (default: `.cortex-service/`).

Memory content is stored in Cognee using the vector database (LanceDB) and graph database (Kuzu) configured via environment variables.

Graph state is tracked per-project. The graph is marked dirty after ingest and automatically synced before search/context/chat operations if needed.

## Core Workflows

### Bootstrap Flow

1. Validate absolute repository path (optionally check against `CORTEX_ALLOWED_ROOTS`)
2. Scan files respecting `CORTEX_MAX_SCAN_FILES`, `CORTEX_MAX_FILE_SIZE_BYTES`, and `excluded_dirs`
3. Detect languages, frameworks, entrypoints, important directories
4. Write `.cortex/` metadata files to repository
5. Extract foundational memory items via `ExtractionService`
6. Store in Cognee via `CogneeService`
7. Update `ProjectRegistryService` state

Bootstrap is idempotent—re-bootstrapping an already-registered repo updates existing project records.

### Ingest Flow

1. Resolve project (auto-bootstrap if needed)
2. Extract memory items from request payload via `ExtractionService`
3. Deduplicate using fingerprints stored in `ProjectRegistryService`
4. Store new items in Cognee
5. Mark graph dirty
6. Increment stored memory count

### Search / Context / Chat Flow

1. Resolve project
2. Sync graph if dirty (ensures graph is current before retrieval)
3. Search Cognee memory
4. Rank and normalize results via `RetrievalService`
5. Return results directly (search), build prompt-ready memory block (context), or generate grounded answer (chat)

### MCP Integration

MCP tools in `app/mcp_server.py` are thin wrappers over the same services:
- `cortex_register` → `BootstrapService.bootstrap`
- `cortex_push` → `MemoryService.ingest`
- `cortex_query` → `MemoryService.context`

MCP tools auto-bootstrap projects if not registered. They return structured JSON payloads with `{"ok": true/false}` instead of HTTP status codes.

## Configuration

### Environment Variables

Required for Cognee features:
- `LLM_API_KEY`: API key for LLM provider
- `LLM_PROVIDER`: openai (default), anthropic, etc.
- `LLM_MODEL`: gpt-4o-mini (default)

Storage paths (must be absolute if set):
- `DATA_ROOT_DIRECTORY`: Cognee data storage (default: `.cognee/data`)
- `SYSTEM_ROOT_DIRECTORY`: Cognee system files (default: `.cognee/system`)
- `CACHE_ROOT_DIRECTORY`: Cognee cache (default: `.cognee/cache`)

Service configuration:
- `CORTEX_SERVICE_DATA_DIR`: Local registry storage (default: `.cortex-service`)
- `CORTEX_ALLOWED_ROOTS`: Comma-separated allowed repo paths (optional security restriction)
- `CORTEX_MAX_SCAN_FILES`: Max files to scan during bootstrap (default: 500)
- `CORTEX_MAX_FILE_SIZE_BYTES`: Max individual file size (default: 262144 / 256KB)
- `CORTEX_LOG_LEVEL`: INFO (default), DEBUG, WARNING, ERROR

Database providers (set via Cognee):
- `VECTOR_DB_PROVIDER`: lancedb (default)
- `GRAPH_DATABASE_PROVIDER`: kuzu (default)

### Scan Behavior

Bootstrap excludes these directories (hardcoded in `app/core/config.py:excluded_dirs`):
`.git`, `.hg`, `.svn`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `dist`, `build`, `target`, `.next`, `.turbo`, `.idea`, `.vscode`, `coverage`, `.cache`, `test`, `tests`

Priority is given to root-level files matching `root_priority_patterns`:
`README*`, `pyproject.toml`, `package.json`, `requirements*.txt`, `Dockerfile*`, `docker-compose*`, `compose.yaml`, `.env.example`, `Makefile`

Important directories scanned for structure detection:
`app`, `src`, `docs`, `scripts`, `config`, `configs`, `migrations`

## Testing Patterns

Tests use `FakeCogneeService` from `tests/conftest.py` to avoid external Cognee dependencies. The fake service implements in-memory storage and search with simple token-based ranking.

Common fixtures:
- `repo_dir`: Creates temporary sample repository
- `app`: FastAPI app instance with test settings and fake Cognee
- `client`: TestClient for HTTP requests
- `project_id`: Bootstrapped project ID for tests requiring existing project

Tests follow arrange-act-assert pattern. Use `tmp_path` fixture for file system tests to ensure isolation.

## Error Handling

Services raise specific exceptions:
- `ProjectNotFoundError`: Project ID not in registry
- `CogneeUnavailableError`: Cognee backend unreachable
- `CogneeStorageError`: Cognee storage operation failed

REST routes catch these and return appropriate HTTP status codes. MCP tools catch these and return `{"ok": false, "error": "message"}` payloads.

Validation errors from Pydantic models are automatically handled by FastAPI and return 422 responses.

## UI Pages

The application serves three UI pages via Jinja templates:
- `/` and `/cognee`: Project memory interface
- `/chat`: Chat interface for querying memory
- `/graph`: Knowledge graph visualization

Templates are in `app/templates/`, static assets in `app/static/`. Templates use a base layout in `base.html` with active page tracking.

## Key Files

- `app/main.py`: Application factory, service wiring, route mounting
- `app/core/config.py`: Settings dataclass with environment variable loading
- `app/services/memory_service.py`: Main orchestrator for memory workflows
- `app/services/bootstrap_service.py`: Repository scanning and initialization
- `app/services/extraction_service.py`: Memory extraction from content
- `app/services/cognee_service.py`: Cognee storage/search/graph wrapper
- `app/mcp_server.py`: MCP tool definitions
- `tests/conftest.py`: Test fixtures and fake Cognee implementation
