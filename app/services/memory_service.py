from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.memory import MemoryItem, RetrievalResult
from app.models.project import SessionModel
from app.services.bootstrap_service import BootstrapService
from app.services.cognee_service import CogneeService
from app.services.context_service import ContextService
from app.services.extraction_service import ExtractionService
from app.services.project_registry_service import ProjectRegistryService
from app.services.retrieval_service import RetrievalService


class ProjectNotFoundError(RuntimeError):
    """Raised when a project cannot be found for a memory operation."""


@dataclass(slots=True)
class MemoryIngestResult:
    session_id: str
    stored_items: list[MemoryItem]


@dataclass(slots=True)
class MemoryContextResult:
    memory_block: str
    supporting_items: list[RetrievalResult]


class MemoryService:
    def __init__(
        self,
        registry_service: ProjectRegistryService,
        bootstrap_service: BootstrapService,
        extraction_service: ExtractionService,
        cognee_service: CogneeService,
        retrieval_service: RetrievalService,
        context_service: ContextService,
    ) -> None:
        self._registry_service = registry_service
        self._bootstrap_service = bootstrap_service
        self._extraction_service = extraction_service
        self._cognee_service = cognee_service
        self._retrieval_service = retrieval_service
        self._context_service = context_service

    def _require_project(self, project_id: str):
        project = self._registry_service.get_project(project_id)
        if project is None:
            raise ProjectNotFoundError("project not found")
        return project

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
    ) -> MemoryIngestResult:
        project = self._require_project(project_id)
        metadata = metadata or {}
        file_paths = file_paths or []
        actual_session_id = session_id or str(uuid.uuid4())
        session = self._registry_service.get_session(actual_session_id)
        if session is None:
            session = SessionModel(
                id=actual_session_id,
                project_id=project_id,
                started_at=datetime.now(timezone.utc),
                source=session_source or metadata.get("source", "implicit_ingest"),
            )
            self._registry_service.upsert_session(session)

        run_id = str(uuid.uuid4())
        repo_commit = self._bootstrap_service.repo_commit_for_path(Path(project.repo_path))
        items = self._extraction_service.extract_ingest_items(
            project_id=project_id,
            session_id=actual_session_id,
            source_type=source_type,
            content=content,
            file_paths=file_paths,
            metadata=metadata,
            repo_commit=repo_commit,
            run_id=run_id,
        )

        deduped_items: list[MemoryItem] = []
        deduped_fingerprints: list[str] = []
        for item in items:
            fingerprint = self._extraction_service.fingerprint(item)
            if self._registry_service.has_fingerprint(project_id, fingerprint):
                continue
            deduped_items.append(item)
            deduped_fingerprints.append(fingerprint)

        await self._cognee_service.store_memory_items(project_id, deduped_items)
        for fingerprint in deduped_fingerprints:
            self._registry_service.remember_fingerprint(project_id, fingerprint)

        return MemoryIngestResult(session_id=actual_session_id, stored_items=deduped_items)

    async def search(
        self,
        *,
        project_id: str,
        query: str,
        top_k: int,
        file_paths: list[str] | None = None,
    ) -> list[RetrievalResult]:
        self._require_project(project_id)
        return await self._retrieval_service.search(
            project_id=project_id,
            query=query,
            top_k=top_k,
            file_paths=file_paths,
        )

    async def context(
        self,
        *,
        project_id: str,
        query: str,
        top_k: int,
        file_paths: list[str] | None = None,
    ) -> MemoryContextResult:
        results = await self.search(project_id=project_id, query=query, top_k=top_k, file_paths=file_paths)
        memory_block = self._context_service.compose(results)
        return MemoryContextResult(memory_block=memory_block, supporting_items=results)
