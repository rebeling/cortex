from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request

from app.models.project import BootstrapRequest, BootstrapResponse, CreateProjectRequest, ProjectModel, ProjectResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectModel])
async def list_projects(request: Request) -> list[ProjectModel]:
    registry = request.app.state.registry_service
    payload = registry._read()
    return [ProjectModel.model_validate(p) for p in payload["projects"].values()]


@router.post("", response_model=ProjectResponse)
async def create_project(payload: CreateProjectRequest, request: Request) -> ProjectResponse:
    project_id = str(uuid4())
    now = datetime.now(timezone.utc)
    project = ProjectModel(
        id=project_id,
        name=payload.name,
        repo_path="",
        canonical_identity=project_id,
        created_at=now,
        updated_at=now,
        bootstrap_complete=False,
        stored_memory_count=0,
        graph_dirty=False,
        last_graph_sync_at=None,
    )
    request.app.state.registry_service.upsert_project(project)
    return ProjectResponse(
        project=project,
        bootstrap_status={},
        cortex_files={
            ".cortex/project.yaml": False,
            ".cortex/brief.md": False,
            ".cortex/repo_map.json": False,
        }
    )


@router.post("/bootstrap", response_model=BootstrapResponse)
async def bootstrap_project(payload: BootstrapRequest, request: Request) -> BootstrapResponse:
    artifacts = await request.app.state.bootstrap_service.bootstrap(
        payload.repo_path, payload.project_name, max_scan_files=payload.max_scan_files,
    )
    return BootstrapResponse(
        project_id=artifacts.project.id,
        created_files=artifacts.created_files,
        bootstrap_summary=artifacts.bootstrap_summary,
        stored_memory_count=artifacts.stored_memory_count,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, request: Request) -> ProjectResponse:
    project, bootstrap_status, cortex_files = request.app.state.bootstrap_service.get_project(project_id)
    return ProjectResponse(project=project, bootstrap_status=bootstrap_status, cortex_files=cortex_files)
