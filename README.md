# Cortex

Cortex is a small FastAPI app that keeps project memory in Cognee.

**What is Cognee?** An open-source AI memory engine that combines vector embeddings and knowledge graphs to help AI systems retrieve more relevant, connected context. Instead of plain vector search, Cognee organizes data into structured memory with relationships.

Right now it can:

- bootstrap a repo into a Cortex project
- ingest and search project memory
- build prompt-ready context blocks
- answer questions from stored memory
- expose the same workflows over MCP
- serve basic UI pages at `/cognee`, `/chat`, and `/graph`

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
