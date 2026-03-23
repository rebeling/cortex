# Cortex

Cortex is a small FastAPI app that keeps project memory in Cognee for **multi-agent coding teams**.

**What is Cognee?** An open-source AI memory engine that combines vector embeddings and knowledge graphs to help AI systems retrieve more relevant, connected context. Instead of plain vector search, Cognee organizes data into structured memory with relationships.

## What Cortex Does

Cortex provides a **shared memory layer** for coding agents working on the same project:

- **Bootstrap** a repo into a Cortex project (scans docs, extracts structure)
- **Ingest** agent observations and findings incrementally
- **Search** with semantic queries across all agent memories
- **Filter** by agent ID or role (e.g., only backend agent's findings)
- **Build** prompt-ready context blocks for downstream tasks
- **Answer** questions from accumulated memory
- **Track** which agents contributed to which files
- **Expose** everything over REST API and MCP

## Multi-Agent Memory

Cortex is designed for **multiple agents collaborating** on the same codebase:

### Agent Identity & Roles

Each agent can identify itself when pushing memory:

```python
# Agent 1: Backend specialist
cortex_push(
    repo_path="/path/to/project",
    content="Auth middleware validates JWT tokens on every request",
    agent_id="agent-backend-001",
    agent_role="backend"
)

# Agent 2: Frontend specialist
cortex_push(
    repo_path="/path/to/project",
    content="Login form sends credentials to /api/auth/login",
    agent_id="agent-frontend-001",
    agent_role="frontend"
)
```

### Role-Based Filtering

Agents can query memory filtered by role:

```python
# Frontend agent queries only frontend-related memory
cortex_query(
    repo_path="/path/to/project",
    question="How does the login UI work?",
    agent_role="frontend"  # Only returns frontend agent's observations
)

# Backend agent queries only backend-related memory
cortex_query(
    repo_path="/path/to/project",
    question="How is authentication implemented?",
    agent_role="backend"  # Only returns backend agent's observations
)
```

### Agent Contributions

Track which agents worked on the project:

```bash
GET /memory/agents/{project_id}
```

Returns:
```json
{
  "project_id": "abc-123",
  "project_name": "my-app",
  "agents": [
    {
      "agent_id": "agent-backend-001",
      "agent_role": "backend",
      "sessions": [
        {"session_id": "...", "started_at": "2025-03-23T10:00:00Z"}
      ],
      "files_contributed": ["app/auth.py", "app/middleware.py"]
    },
    {
      "agent_id": "agent-frontend-001",
      "agent_role": "frontend",
      "sessions": [
        {"session_id": "...", "started_at": "2025-03-23T11:00:00Z"}
      ],
      "files_contributed": ["src/Login.tsx", "src/api/auth.ts"]
    }
  ]
}
```

## Example: Multi-Agent Team Workflow

### Scenario: Agent Team Working on Authentication

**Agent 1 (Backend)** bootstraps the project and starts exploring:

```python
# Bootstrap project (one-time setup)
cortex_register(repo_path="/workspace/myapp")

# Backend agent discovers auth implementation
cortex_push(
    repo_path="/workspace/myapp",
    content="Uses JWT tokens with 24-hour expiry. Tokens stored in HTTP-only cookies. Refresh endpoint at /api/auth/refresh.",
    file_paths=["app/auth/jwt.py", "app/middleware/auth.py"],
    agent_id="backend-agent-1",
    agent_role="backend"
)
```

**Agent 2 (Frontend)** queries existing memory and adds findings:

```python
# Query what backend agent discovered
context = cortex_query(
    repo_path="/workspace/myapp",
    question="How does authentication work?",
    agent_role="backend"  # Get backend agent's context
)
# Returns: "Uses JWT tokens with 24-hour expiry..."

# Frontend agent adds UI observations
cortex_push(
    repo_path="/workspace/myapp",
    content="Login component at src/Login.tsx sends POST to /api/auth/login with username/password. Sets auth cookie automatically via withCredentials.",
    file_paths=["src/Login.tsx", "src/api/client.ts"],
    agent_id="frontend-agent-1",
    agent_role="frontend"
)
```

**Agent 3 (DevOps)** queries cross-cutting concerns:

```python
# Query ALL agents' memory (no role filter)
context = cortex_query(
    repo_path="/workspace/myapp",
    question="What environment variables are needed for auth?",
    # No agent_role = searches all agents
)
# Returns combined context from backend + frontend findings
```

### New Agent Joining

When a **new agent joins the team**, it can quickly get up to speed:

```python
# New agent: Security auditor
cortex_query(
    repo_path="/workspace/myapp",
    question="Show me all authentication and security findings",
    top_k=10  # Get comprehensive overview
)
# Returns: Combined discoveries from backend + frontend agents
```

## Instructions for New Agents

If you're an **agent new to this project**, here's how to use Cortex:

### 1. Bootstrap the Project (if not already done)

```python
cortex_register(repo_path="/absolute/path/to/project")
```

This scans the repository structure, extracts documentation, and creates foundational memory.

### 2. Identify Yourself

When pushing observations, **always** include your `agent_id` and `agent_role`:

```python
cortex_push(
    repo_path="/absolute/path/to/project",
    content="Your observation or finding here",
    agent_id="your-unique-agent-id",  # e.g., "agent-backend-002"
    agent_role="your-role"  # e.g., "backend", "frontend", "devops", "testing"
)
```

**Role naming conventions:**
- `backend` - Server-side code, APIs, databases
- `frontend` - UI components, client-side logic
- `devops` - Infrastructure, deployment, CI/CD
- `testing` - Test suites, QA findings
- `security` - Security audits, vulnerability findings
- `docs` - Documentation updates and improvements

### 3. Query Existing Memory

**Get general context:**
```python
cortex_query(
    repo_path="/absolute/path/to/project",
    question="What does this project do?",
    top_k=5
)
```

**Get role-specific context:**
```python
cortex_query(
    repo_path="/absolute/path/to/project",
    question="How is the database configured?",
    agent_role="backend"  # Only search backend agent findings
)
```

**Search specific agent's work:**
```python
cortex_query(
    repo_path="/absolute/path/to/project",
    question="What did agent-backend-001 discover about auth?",
    agent_id="agent-backend-001"
)
```

### 4. Accumulate Findings

As you work, **continuously push observations**:

```python
# After exploring a file
cortex_push(
    repo_path="/absolute/path/to/project",
    content="Discovered: Uses Redis for session storage. Connection pooling enabled with max 20 connections.",
    file_paths=["app/cache/redis.py"],
    agent_id="your-agent-id",
    agent_role="backend"
)

# After understanding a pattern
cortex_push(
    repo_path="/absolute/path/to/project",
    content="Pattern: All API routes use @require_auth decorator from app.middleware.auth",
    file_paths=["app/api/routes/users.py", "app/api/routes/posts.py"],
    agent_id="your-agent-id",
    agent_role="backend"
)
```

### 5. Share Findings with Team

Other agents automatically see your observations when they query. No manual coordination needed!

## Quick Start

```bash
uv sync --extra dev
cp .env.example .env
uv run uvicorn app.main:app --reload
```

Set `LLM_API_KEY` in `.env` if you want Cognee-backed features to work. Without it, the app still starts and `GET /health` still works.

## Hints

- Start with `POST /projects/bootstrap` if you want to register a repo over HTTP.
- Use `/memory/ingest`, `/memory/search`, `/memory/context`, and `/memory/chat` for the core memory workflows.
- Use `/mcp` if you want to call Cortex from an MCP client instead of hitting the REST API directly.
- Use `/cognee` for the basic UI.

## Docs

- [Overview](docs/overview.md)
- [Setup](docs/setup.md)
- [API](docs/api.md)
- [MCP](docs/mcp.md)
- [Architecture](docs/architecture.md)
