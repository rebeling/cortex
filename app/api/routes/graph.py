from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.services.cognee_service import CogneeStorageError, CogneeUnavailableError

router = APIRouter(prefix="/graph", tags=["graph"])


def _graph_artifact_path(request: Request, project) -> Path:
    if project.repo_path:
        return Path(project.repo_path) / ".cortex" / "artifacts" / "graph_visualization.html"
    return request.app.state.settings.service_data_dir / "graph_artifacts" / project.id / "graph_visualization.html"


def _visualization_is_stale(path: Path, last_graph_sync_at: datetime | None) -> bool:
    if not path.exists():
        return True
    if last_graph_sync_at is None:
        return False
    artifact_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return artifact_mtime < last_graph_sync_at


@router.post("/{project_id}/sync")
async def sync_graph(project_id: str, request: Request) -> dict:
    project = request.app.state.registry_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    try:
        await request.app.state.cognee_service.sync_graph(project_id)
    except (CogneeUnavailableError, CogneeStorageError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    synced_at = datetime.now(timezone.utc)
    updated_project = request.app.state.bootstrap_service.mark_graph_synced(project, synced_at=synced_at)
    return {
        "ok": True,
        "project_id": project_id,
        "graph_dirty": updated_project.graph_dirty,
        "last_graph_sync_at": synced_at.isoformat(),
    }


@router.get("/{project_id}/visualization")
async def get_graph_visualization(project_id: str, request: Request) -> FileResponse:
    project = request.app.state.registry_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    try:
        artifact_path = _graph_artifact_path(request, project)
        needs_sync = project.graph_dirty or _visualization_is_stale(artifact_path, project.last_graph_sync_at)
        if needs_sync:
            synced_at = datetime.now(timezone.utc)
            await request.app.state.cognee_service.sync_graph(project_id)
            project = request.app.state.bootstrap_service.mark_graph_synced(project, synced_at=synced_at)

        if not artifact_path.exists() or _visualization_is_stale(artifact_path, project.last_graph_sync_at):
            await request.app.state.cognee_service.generate_graph_visualization(project_id, artifact_path)
    except (CogneeUnavailableError, CogneeStorageError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    if not artifact_path.exists():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="graph visualization file was not created")

    return FileResponse(artifact_path, media_type="text/html")


@router.get("/{project_id}")
async def get_graph(project_id: str, request: Request) -> dict:
    project = request.app.state.registry_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    try:
        triples = await request.app.state.cognee_service.get_graph(project_id)
    except (CogneeUnavailableError, CogneeStorageError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    node_set: set[str] = set()
    nodes: list[dict] = []
    edges: list[dict] = []
    for triple in triples:
        for label in (triple["source"], triple["target"]):
            if label not in node_set:
                node_set.add(label)
                nodes.append({"id": label, "label": label})
        edges.append({"from": triple["source"], "to": triple["target"], "label": triple["relation"]})
    return {"nodes": nodes, "edges": edges}
