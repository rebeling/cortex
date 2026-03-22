# Cortex Overview

Cortex adds a transparent project-memory layer for coding agents. It scans a repository, extracts structured memory, stores that memory in Cognee, and exposes retrieval, chat, graph, and MCP workflows over the resulting project data.

## What is Cognee?

Cognee is an open-source AI memory engine for agents and LAG/RAG-style systems. It ingests data from many formats, turns that data into structured "memory" using embeddings plus a knowledge graph, and then helps AI systems retrieve more relevant, connected context over time instead of relying only on plain vector search. Its docs describe it as organizing your data into AI memory, with configurable LLMs, embedding models, vector stores, and graph databases.

Cortex uses Cognee as its storage and retrieval backend, leveraging:
- **Vector embeddings** for semantic search across project documentation and memory
- **Knowledge graph** to maintain relationships between code concepts, files, and dependencies
- **Hybrid retrieval** combining vector similarity with graph traversal for better context

This means Cortex can answer questions like "how does authentication work?" by finding not just relevant documentation, but also understanding how different parts of the system connect.

## Core Concepts

### Projects

A project represents a registered repository or an empty placeholder created through the API. Project records track:

- repository identity and path
- detected languages and frameworks
- bootstrap status
- stored memory count
- graph sync state

### Bootstrap

Bootstrap scans a repository, detects important files and folders, extracts foundational project memory, and writes Cortex metadata files under `.cortex/`.

Bootstrap is implemented through [`app/services/bootstrap_service.py`](/Users/matthias/mr/cortex/app/services/bootstrap_service.py) and exposed through [`app/api/routes/projects.py`](/Users/matthias/mr/cortex/app/api/routes/projects.py).

### Memory

Memory items are structured records extracted from repository scans or user-provided content. Cortex deduplicates them before storage and keeps a lightweight project/session registry in the local service data directory.

The main memory workflow lives in [`app/services/memory_service.py`](/Users/matthias/mr/cortex/app/services/memory_service.py).

### Retrieval and Context

Search returns ranked memory results. Context turns those results into a prompt-ready memory block for downstream agent use.

This is handled by:

- [`app/services/retrieval_service.py`](/Users/matthias/mr/cortex/app/services/retrieval_service.py)
- [`app/services/context_service.py`](/Users/matthias/mr/cortex/app/services/context_service.py)

### Chat

Chat uses retrieved memory to answer questions about a project. If OpenAI is configured, Cortex can ask the model for a grounded answer. If not, it falls back to a deterministic answer built from stored memory.

Chat behavior is implemented in [`app/services/chat_service.py`](/Users/matthias/mr/cortex/app/services/chat_service.py).

### Graph

Cortex tracks whether the knowledge graph is dirty after ingest. Search and graph workflows can trigger graph synchronization before retrieval or visualization.

Graph endpoints live in [`app/api/routes/graph.py`](/Users/matthias/mr/cortex/app/api/routes/graph.py).

### MCP

Cortex exposes an MCP server at `/mcp`. The MCP tools are thin adapters over the same shared services used by the REST API.

The MCP adapter lives in [`app/mcp_server.py`](/Users/matthias/mr/cortex/app/mcp_server.py).
