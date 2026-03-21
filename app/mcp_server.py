"""MCP adapter for Cortex."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.services.cognee_service import CogneeStorageError, CogneeUnavailableError
from app.services.memory_service import ProjectNotFoundError

logger = logging.getLogger(__name__)


def create_mcp_server(app_state: Any) -> FastMCP:
    mcp = FastMCP(
        "Cortex",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "testserver"],
            allowed_origins=["http://localhost", "http://localhost:*", "http://127.0.0.1", "http://127.0.0.1:*"],
        ),
    )

    def error_payload(message: str) -> dict[str, Any]:
        return {"ok": False, "error": message}

    async def resolve_or_bootstrap_project(repo_path: str) -> str:
        project = app_state.registry_service.get_project_by_repo_path(Path(repo_path))
        if project:
            return project.id
        artifacts = await app_state.bootstrap_service.bootstrap(repo_path)
        return artifacts.project.id

    @mcp.tool()
    async def cortex_register(repo_path: str) -> dict[str, Any]:
        try:
            artifacts = await app_state.bootstrap_service.bootstrap(repo_path)
        except Exception as exc:
            logger.exception("mcp cortex_register failed", extra={"repo_path": repo_path})
            return error_payload(str(exc))
        return {
            "ok": True,
            "project_id": artifacts.project.id,
            "summary": artifacts.bootstrap_summary,
            "stored_memory_count": artifacts.stored_memory_count,
        }

    @mcp.tool()
    async def cortex_push(
        repo_path: str,
        content: str,
        file_paths: list[str] | None = None,
        source_type: str = "agent_summary",
    ) -> dict[str, Any]:
        try:
            project_id = await resolve_or_bootstrap_project(repo_path)
            result = await app_state.memory_service.ingest(
                project_id=project_id,
                source_type=source_type,
                content=content,
                file_paths=file_paths or [],
                metadata={"source": "mcp"},
                session_source="mcp",
            )
        except (ProjectNotFoundError, CogneeUnavailableError, CogneeStorageError, RuntimeError, ValueError) as exc:
            logger.exception("mcp cortex_push failed", extra={"repo_path": repo_path})
            return error_payload(str(exc))
        return {
            "ok": True,
            "project_id": project_id,
            "session_id": result.session_id,
            "stored_count": len(result.stored_items),
        }

    @mcp.tool()
    async def cortex_query(repo_path: str, question: str, top_k: int = 5) -> dict[str, Any]:
        try:
            project_id = await resolve_or_bootstrap_project(repo_path)
            result = await app_state.memory_service.context(
                project_id=project_id,
                query=question,
                top_k=top_k,
            )
        except (ProjectNotFoundError, CogneeUnavailableError, CogneeStorageError, RuntimeError, ValueError) as exc:
            logger.exception("mcp cortex_query failed", extra={"repo_path": repo_path})
            return error_payload(str(exc))
        return {
            "ok": True,
            "project_id": project_id,
            "memory_block": result.memory_block,
            "results": [
                {
                    "content": item.item.content,
                    "title": item.item.title,
                    "type": item.item.type,
                    "score": item.score,
                    "file_paths": item.item.file_paths,
                }
                for item in result.supporting_items
            ],
        }

    return mcp
