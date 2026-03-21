# MCP Server for Cortex — Execution Plan

> **Goal**: Add an MCP server to Cortex at `/mcp` exposing 3 tools: `cortex_register`, `cortex_push`, `cortex_query`.
> **Constraint**: Preserve all existing REST functionality. MCP must be a thin adapter over shared services, not a second implementation of memory logic.

---

## Design Correction

The first draft duplicated the memory-ingest flow inside the MCP tool layer. That is the wrong shape for Cortex.

The corrected approach is:

- Extract the current ingest workflow from [app/api/routes/memory.py](/Users/matthias/mr/cortex/app/api/routes/memory.py) into a shared service method.
- Have both the REST route and the MCP tool call that same shared method.
- Keep MCP responses tool-oriented, not HTTP-shaped.
- Add transport-level MCP tests that exercise the mounted `/mcp` server instead of calling Python coroutines directly.

This keeps deduplication, session creation, fingerprinting, Cognee writes, and future fixes in one place.

---

## Step 1: Add `mcp` dependency

**File**: `/Users/matthias/mr/cortex/pyproject.toml`

**Action**: Add `"mcp>=1.20.0,<2.0.0"` to the main dependencies.

Then run:

```bash
cd /Users/matthias/mr/cortex && uv sync --extra dev
```

---

## Step 2: Add a shared memory service

**File**: `/Users/matthias/mr/cortex/app/services/memory_service.py` (NEW)

**Action**: Create a shared service that owns the ingest flow currently embedded in the REST route.

### Responsibilities

- Validate that the project exists
- Create an implicit session when `session_id` is missing
- Resolve `repo_commit`
- Extract memory items
- Deduplicate against stored fingerprints
- Persist new items through `CogneeService`
- Persist new fingerprints only after successful storage

### Suggested interface

```python
async def ingest(
    self,
    *,
    project_id: str,
    source_type: str,
    content: Any,
    file_paths: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_source: str | None = None,
) -> MemoryIngestResult
```

Where `MemoryIngestResult` includes:

- `session_id`
- `stored_items`

Optional helper methods may also be added for:

- `search(project_id, query, top_k, file_paths=None)`
- `context(project_id, query, top_k, file_paths=None)`

Those helpers should delegate to the existing retrieval/context services rather than reimplementing them.

---

## Step 3: Refactor the REST memory routes to use the shared service

**File**: `/Users/matthias/mr/cortex/app/api/routes/memory.py`

**Action**: Replace the inline ingest flow with a call into `MemoryService.ingest(...)`.

### Required behavior

- Keep the existing request/response models unchanged
- Keep existing HTTP behavior unchanged
- Preserve current error mapping:
  - `404` for unknown project
  - `500` for Cognee/config/runtime failures

`/memory/search` and `/memory/context` may also be simplified to call service methods if that reduces duplication cleanly.

---

## Step 4: Add a repo-path lookup method to the registry service

**File**: `/Users/matthias/mr/cortex/app/services/project_registry_service.py`

**Action**: Add a public method such as:

```python
def get_project_by_repo_path(self, repo_path: Path | str) -> ProjectModel | None:
```

### Reason

The MCP layer needs `repo_path -> project_id`, but it should not call `_read()` directly or bypass the registry lock.

---

## Step 5: Create the MCP server module

**File**: `/Users/matthias/mr/cortex/app/mcp_server.py` (NEW)

**Action**: Implement the MCP server as a thin adapter around existing services.

### Server shape

- Use `FastMCP` from the official Python SDK
- Expose the server at `/mcp`
- Mount it into the existing FastAPI app
- Share `app.state` with the MCP adapter via a small setter or context object

### Tool behavior

#### `cortex_register(repo_path)`

- Resolve/validate the repo path
- Call the existing bootstrap service
- Return a tool-friendly success payload such as:

```json
{
  "ok": true,
  "project_id": "...",
  "summary": "...",
  "stored_memory_count": 3
}
```

#### `cortex_push(repo_path, content, file_paths?, source_type?)`

- Resolve the project by repo path
- Auto-bootstrap if missing
- Call `MemoryService.ingest(...)`
- Return a compact tool payload such as:

```json
{
  "ok": true,
  "project_id": "...",
  "session_id": "...",
  "stored_count": 2
}
```

#### `cortex_query(repo_path, question, top_k?)`

- Resolve the project by repo path
- Auto-bootstrap if missing
- Call the shared search/context flow
- Return a compact tool payload such as:

```json
{
  "ok": true,
  "project_id": "...",
  "memory_block": "...",
  "results": [...]
}
```

### Error behavior

MCP tools should not return HTTP status codes. They should return tool-level error payloads, for example:

```json
{
  "ok": false,
  "error": "project not found"
}
```

The underlying behavior must still be equivalent to REST:

- same deduplication
- same auto-bootstrap behavior
- same stored memory items

---

## Step 6: Wire MCP into app startup

**File**: `/Users/matthias/mr/cortex/app/main.py`

**Action**:

- initialize `MemoryService`
- store it on `app.state`
- mount the MCP ASGI app at `/mcp`
- add lifespan management for the MCP session manager if required by the SDK

### Important

Do not replace or break the existing REST app wiring.

---

## Step 7: Add MCP tests

**Files**:

- `/Users/matthias/mr/cortex/tests/test_mcp.py` (NEW)
- `/Users/matthias/mr/cortex/tests/conftest.py` if test fixtures need to expose the mounted app

**Action**: Add transport-level tests against the mounted MCP server.

### Required coverage

1. Register via MCP
   - call the mounted `/mcp` server
   - verify a project is bootstrapped and a `project_id` is returned

2. Push via MCP
   - call the MCP tool
   - verify the shared ingest flow stores memory

3. Query via MCP
   - push content first
   - query via MCP
   - verify the returned `memory_block` and supporting items

4. Auto-bootstrap behavior
   - call `cortex_push` or `cortex_query` on an unregistered repo
   - verify the project becomes registered automatically

### Test rule

Do not satisfy this step by importing tool functions and calling them directly.
The tests must exercise the actual mounted MCP transport or an MCP client against the mounted app.

---

## Step 8: Update README

**File**: `/Users/matthias/mr/cortex/README.md`

**Action**: Add an MCP Integration section that documents:

- Cortex MCP endpoint at `/mcp`
- available tools
- a minimal client configuration example
- optional testing with MCP Inspector

Note that tool responses are compact adapter payloads rather than REST-shaped responses.

---

## Step 9: Verify

Run:

```bash
cd /Users/matthias/mr/cortex && uv sync --extra dev && uv run pytest -v
```

Expected:

- all existing tests still pass
- new MCP tests pass
- REST and MCP paths share the same ingest behavior

---

## Step 10: Manual smoke test

```bash
make start-cortex
```

Then connect an MCP client or MCP Inspector to:

```text
http://localhost:8000/mcp
```

Verify that:

- `cortex_register` works
- `cortex_push` stores memory
- `cortex_query` returns a compact memory block
