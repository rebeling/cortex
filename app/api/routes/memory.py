from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.models.memory import (
    ChatRequest,
    ChatResponse,
    ContextRequest,
    ContextResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
)
from app.services.cognee_service import CogneeStorageError, CogneeUnavailableError
from app.services.memory_service import ProjectNotFoundError

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_memory(payload: IngestRequest, request: Request) -> IngestResponse:
    try:
        result = await request.app.state.memory_service.ingest(
            project_id=payload.project_id,
            session_id=payload.session_id,
            source_type=payload.source_type,
            content=payload.content,
            file_paths=payload.file_paths,
            metadata=payload.metadata,
            agent_id=payload.agent_id,
            agent_role=payload.agent_role,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CogneeUnavailableError, CogneeStorageError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return IngestResponse(session_id=result.session_id, stored_items=result.stored_items)


@router.post("/search", response_model=SearchResponse)
async def search_memory(payload: SearchRequest, request: Request) -> SearchResponse:
    try:
        results = await request.app.state.memory_service.search(
            project_id=payload.project_id,
            query=payload.query,
            top_k=payload.top_k,
            agent_id=payload.agent_id,
            agent_role=payload.agent_role,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CogneeUnavailableError, CogneeStorageError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return SearchResponse(results=results)


@router.post("/context", response_model=ContextResponse)
async def compose_context(payload: ContextRequest, request: Request) -> ContextResponse:
    try:
        result = await request.app.state.memory_service.context(
            project_id=payload.project_id,
            query=payload.query,
            top_k=payload.top_k,
            file_paths=payload.file_paths,
            agent_id=payload.agent_id,
            agent_role=payload.agent_role,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CogneeUnavailableError, CogneeStorageError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return ContextResponse(memory_block=result.memory_block, supporting_items=result.supporting_items)


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    try:
        result = await request.app.state.memory_service.chat(
            project_id=payload.project_id,
            query=payload.query,
            top_k=payload.top_k,
            file_paths=payload.file_paths,
            agent_id=payload.agent_id,
            agent_role=payload.agent_role,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CogneeUnavailableError, CogneeStorageError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return ChatResponse(
        answer=result.answer,
        answer_mode=result.answer_mode,
        supporting_items=result.supporting_items,
    )


@router.get("/agents/{project_id}")
async def get_agent_contributions(project_id: str, request: Request) -> dict[str, Any]:
    """Get agent contributions for a project, showing which agents worked on which files."""
    try:
        registry_service = request.app.state.registry_service
        project = registry_service.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        # Get all sessions for this project
        sessions = registry_service.list_sessions(project_id)

        # Build agent contribution map
        agents: dict[str, dict[str, Any]] = {}
        file_memory_index = registry_service.get_file_memory_index(project_id)

        for session in sessions:
            if not session.agent_id:
                continue

            if session.agent_id not in agents:
                agents[session.agent_id] = {
                    "agent_id": session.agent_id,
                    "agent_role": session.agent_role,
                    "sessions": [],
                    "files_contributed": set(),
                }

            agents[session.agent_id]["sessions"].append({
                "session_id": session.id,
                "started_at": session.started_at.isoformat(),
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "source": session.source,
            })

        # Convert sets to lists for JSON serialization
        for agent_data in agents.values():
            agent_data["files_contributed"] = sorted(list(agent_data["files_contributed"]))

        return {
            "project_id": project_id,
            "project_name": project.name,
            "total_files": len(file_memory_index),
            "agents": list(agents.values()),
        }

    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
