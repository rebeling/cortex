from __future__ import annotations

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
