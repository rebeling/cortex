from __future__ import annotations

from fastapi import APIRouter, Request

from app.models.project import BootstrapRequest, BootstrapResponse, ProjectModel, ProjectResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectModel])
async def list_projects(request: Request) -> list[ProjectModel]:
    registry = request.app.state.registry_service
    payload = registry._read()
    return [ProjectModel.model_validate(p) for p in payload["projects"].values()]


@router.post("/bootstrap", response_model=BootstrapResponse)
async def bootstrap_project(payload: BootstrapRequest, request: Request) -> BootstrapResponse:
    artifacts = await request.app.state.bootstrap_service.bootstrap(payload.repo_path, payload.project_name)
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
